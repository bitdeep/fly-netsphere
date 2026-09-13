"""Local City observatory with one physical fly and a bounded neural motor assay."""
import argparse
import base64
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import mujoco
import numpy as np
from PIL import Image

from city_world import City
from passive_fly import FLY_ID, attach_fly, describe_fly, initialize_fly
from prepare_browser_fly import CACHE
from habitat import Habitat, attach_objects
from survival import Survival, DESCRIPTOR as SURVIVAL_DESCRIPTOR


ROOT = Path(__file__).resolve().parents[1]
PROBE_START = [-44.0, -26.0, 16.0]
PROBE_RADIUS = .45
DEV_MODE = os.environ.get("FLY_DEV") == "1"
DEV_INSTANCE = str(time.time_ns())
# One physics thread, with headroom for HTTP and the independent neural assay.
PHYSICS_CPU_BUDGET = .9
PHYSICS_SLICE_CPU_SECONDS = .006
POSE_INTERVAL = 1/30


class Environment:
    """One authoritative physical clock, independent of viewers and rendering."""

    def __init__(self):
        self.city = City()
        fly_manifest, self.fly_joint_name = attach_fly(self.city)
        root = self.city.mjcf_model
        # City/flybody use centimetres; Earth's acceleration is 981 cm/s².
        root.option.set_attributes(timestep=.0001, gravity=[0, 0, -981],
                                   integrator="implicitfast", noslip_iterations=0,
                                   sleep_tolerance=.001)
        body = root.worldbody.add("body", name="gravity_probe", pos=PROBE_START)
        body.add("freejoint", name="probe_free")
        body.add("geom", name="probe_sphere", type="sphere", size=[PROBE_RADIUS],
                 density=7.85, rgba=[1, .57, .19, 1], friction=[.8, .005, .0001],
                 solref=[.002, 1], priority=1, contype=1, conaffinity=1)
        attach_objects(root)
        xml = root.to_xml_string()
        self.model = mujoco.MjModel.from_xml_string(xml, root.get_assets())
        # Start passive. A motor trial may enable only its allowlisted actuator.
        self.model.opt.enableflags |= int(mujoco.mjtEnableBit.mjENBL_SLEEP)
        self.model.opt.disableflags |= int(mujoco.mjtDisableBit.mjDSBL_ACTUATION)
        self.model.tree_sleep_policy[:] = mujoco.mjtSleepPolicy.mjSLEEP_ALLOWED
        self.data = mujoco.MjData(self.model)
        initialize_fly(self.model, self.data)
        self.habitat = Habitat(self.model, self.data)
        self.survival = Survival()
        self.fly_description, self.fly_body_ids = describe_fly(self.model, fly_manifest)
        self.fly_body_mask = np.zeros(self.model.nbody, dtype=bool)
        self.fly_body_mask[self.fly_body_ids] = True
        self.fly_root_id = self.model.body(f"{FLY_ID}/thorax").id
        self.fly_tree = int(self.model.body_treeid[self.fly_root_id])
        self.fly_contacts_seen = False
        self.fly_contact_count = 0
        self.fly_pose_revision = 0
        self.fly_pose_array = None
        self.fly_pose_bytes = ""
        self.next_pose_time = 0.
        self.fly_surfaces = (CACHE/"surfaces.bin").read_bytes()
        self.fly_surfaces_gzip = gzip.compress(self.fly_surfaces, compresslevel=6, mtime=0)
        self.probe_id = self.model.body("gravity_probe").id
        self.probe_geom = self.model.geom("probe_sphere").id
        self.probe_joint = self.model.joint("probe_free").id
        self.probe_qpos = int(self.model.jnt_qposadr[self.probe_joint])
        self.probe_dof = int(self.model.jnt_dofadr[self.probe_joint])
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.neural = None
        self.motor = None
        if os.environ.get("FLY_NEURAL") == "1":
            from neural_lab import NeuralLab
            from motor_bridge import MotorBridge
            self.neural = NeuralLab(self.stop)
            self.motor = MotorBridge(self.neural.graph, self.model, self.data, self.fly_tree)
            if self.motor.descriptor["available"]:
                self.fly_description["neural_controller"] = "experimental MN9-to-rostrum link"
                self.fly_description["actuator_drive"] = "rostrum only during motor trials"
        self.paused = False
        self.speed = 1.0
        self.probe_active = False
        self.probe_generation = 0
        self.probe_trail = []
        self.contact_seen = False
        self.sequence = 0
        self.ratio = 0.
        self.error = None
        mujoco.mj_forward(self.model, self.data)
        # The empty MJCF attachment frame gives rotational DOFs a world-offset
        # length (~46 cm here). Sleep needs an animal-sized length, independent
        # of where it lives. Use a conservative radius of its physical geoms.
        fly_geoms = self.fly_body_mask[self.model.geom_bodyid]
        radius = np.max(np.linalg.norm(
            self.data.geom_xpos[fly_geoms]-self.data.xpos[self.fly_root_id], axis=1)
            + self.model.geom_rbound[fly_geoms])
        fly_dof = int(self.model.joint(self.fly_joint_name).dofadr[0])
        self.model.dof_length[fly_dof+3:fly_dof+6] = radius
        self.fly_sleep_radius = float(radius)
        self._cache_fly_pose()
        self.textures = {}
        self.world = self._export(xml)
        self.world_bytes = json.dumps(self.world, separators=(",", ":")).encode()
        self.thread = threading.Thread(target=self._run, name="environment", daemon=True)
        # The cache contains no source OBJ files; anatomy is not rebuilt at runtime.

    def _export(self, xml):
        """Read compiled geometry transforms, not a second procedural world."""
        model, data = self.model, self.data
        for i in range(model.ntex):
            if int(model.tex_type[i]) == int(mujoco.mjtTexture.mjTEXTURE_SKYBOX):
                continue
            width, height = int(model.tex_width[i]), int(model.tex_height[i])
            channels, address = int(model.tex_nchannel[i]), int(model.tex_adr[i])
            pixels = model.tex_data[address:address+width*height*channels].reshape(
                height, width, channels)
            # Cube textures contain six repeated faces. The viewer tiles one face.
            if int(model.tex_type[i]) == int(mujoco.mjtTexture.mjTEXTURE_CUBE):
                pixels = pixels[:width]
            stream = io.BytesIO()
            Image.fromarray(pixels.squeeze()).save(stream, format="PNG")
            self.textures[i] = stream.getvalue()
        materials = []
        for i in range(model.nmat):
            texture = int(model.mat_texid[i, int(mujoco.mjtTextureRole.mjTEXROLE_RGB)])
            materials.append({
                "name": model.material(i).name, "rgba": model.mat_rgba[i].tolist(),
                "emission": float(model.mat_emission[i]),
                "texture": f"/textures/{texture}.png" if texture in self.textures else None,
            })
        types = {int(getattr(mujoco.mjtGeom, f"mjGEOM_{name.upper()}")): name
                 for name in ("plane", "sphere", "capsule", "cylinder", "box")}
        geoms = []
        for i in range(model.ngeom):
            if (i == self.probe_geom or model.geom(i).name.startswith(FLY_ID+"/")
                    or i in self.habitat.geoms):
                continue
            kind = types.get(int(model.geom_type[i]))
            if kind is None:
                raise ValueError(f"Unsupported world geometry: {model.geom(i).name}")
            geoms.append({
                "id": i, "name": model.geom(i).name, "type": kind,
                "position": data.geom_xpos[i].tolist(),
                "rotation": data.geom_xmat[i].reshape(3, 3).tolist(),
                "size": model.geom_size[i].tolist(),
                "material": int(model.geom_matid[i]),
                "collision": bool(model.geom_contype[i] or model.geom_conaffinity[i]),
            })
        return {
            "schema": 2, "name": "NETSPHERE", "units": "cm",
            "source": "scripts/city_world.py", "model_sha256": hashlib.sha256(xml.encode()).hexdigest(),
            "engine": f"MuJoCo {mujoco.__version__}", "timestep": float(model.opt.timestep),
            "gravity": model.opt.gravity.tolist(), "geoms": geoms, "materials": materials,
            "neural_controller": ("experimental MN9-to-rostrum link"
                                  if self.motor and self.motor.descriptor["available"] else None),
            "fly_body": self.fly_description,
            "neural": self.neural.descriptor if self.neural else None,
            "motor": self.motor.descriptor if self.motor else None,
            "habitat": self.habitat.descriptor,
            "survival": SURVIVAL_DESCRIPTOR,
            "probe": {"radius": PROBE_RADIUS, "start": PROBE_START},
            "views": [
                {"id": "gallery", "title": "South gallery", "position": [-50, -35, 16],
                 "target": [-8, -22, 24], "caption": "Walkways, pillars and suspended cables."},
                {"id": "shaft", "title": "Central shaft", "position": [-45, -30, 108],
                 "target": [16, -24, 42], "caption": "A city stacked above the void."},
                {"id": "lower", "title": "Lower walkway", "position": [-55, -37, 22],
                 "target": [-44, -26, 4], "caption": "Observe gravity and contact with the walkway."},
            ],
        }

    def start(self):
        self.thread.start()

    def command(self, command):
        if not isinstance(command, dict):
            raise ValueError("Expected a command object")
        action = command.get("action")
        with self.lock:
            if self.stop.is_set():
                raise ValueError("The environment is stopping")
            if (action in ("neural_trial", "motor_trial")
                    and (set(command) == {"action", "mode"}
                         or action == "motor_trial" and set(command) == {"action", "mode", "stimulus"})):
                if self.neural is None:
                    raise ValueError("The neural lab is not enabled in this environment")
                if not self.survival.alive:
                    raise ValueError("The fly has died. Start a new life before running a trial.")
                if self.motor.active or self.neural.snapshot()["status"] == "running":
                    raise ValueError("A neural trial is already running")
                if action == "motor_trial":
                    if self.paused or self.error:
                        raise ValueError("Resume the physical simulation before starting a motor trial")
                    if self.data.tree_asleep[self.fly_tree] < 0:
                        raise ValueError("Let the fly settle before starting a motor trial")
                    self.motor.start(command["mode"], command.get("stimulus", "sugar"))
                    self.next_pose_time = 0.
                else:
                    self.neural.start(command["mode"])
            elif action == "motor_stop" and set(command) == {"action"}:
                if self.motor:
                    if self.motor.active and self.motor.state.get("source"):
                        self.habitat.set_enabled(False)
                    self.motor.finish()
            elif action == "neural_stop" and set(command) == {"action"}:
                if self.neural:
                    self.neural.cancel_trial()
            elif action == "object_place" and set(command) in (
                    {"action", "kind"}, {"action", "kind", "position"}):
                self.habitat.place(command["kind"], command.get("position"))
            elif action == "object_remove" and set(command) == {"action", "id"}:
                self.habitat.remove(command["id"])
            elif action == "reactive_senses" and set(command) == {"action", "enabled"}:
                self.habitat.set_enabled(command["enabled"])
            elif action == "life_restart" and set(command) == {"action"}:
                if self.survival.alive:
                    raise ValueError("A new life can start only after death")
                self.survival.restart()
                self.habitat.next_sample = 0.
            elif action == "pause" and set(command) == {"action", "paused"}:
                if not isinstance(command["paused"], bool):
                    raise ValueError("paused must be boolean")
                self.paused = command["paused"]
                if self.motor:
                    self.motor.set_paused(self.paused)
            elif action == "speed" and set(command) == {"action", "value"}:
                if type(command["value"]) not in (int, float) or command["value"] not in (.25, 1):
                    raise ValueError("speed must be 0.25 or 1")
                self.speed = float(command["value"])
            elif action == "drop" and set(command) == {"action"}:
                # Initialize only the test particle. Never reset or move the fly.
                q, v = self.probe_qpos, self.probe_dof
                self.data.qpos[q:q+7] = self.model.qpos0[q:q+7]
                self.data.qvel[v:v+6] = 0
                self.data.qacc_warmstart[v:v+6] = 0
                mujoco.mj_forward(self.model, self.data)
                self.probe_active = True
                self.contact_seen = False
                self.probe_generation += 1
                self.probe_trail = [PROBE_START.copy()]
                self.paused = False
                if self.motor:
                    self.motor.set_paused(False)
            else:
                raise ValueError("Unknown command")

    def _cache_fly_pose(self):
        """A shared float32 pose packet; never rebuild surfaces during simulation."""
        pose = np.column_stack((self.data.xpos[self.fly_body_ids],
                                self.data.xquat[self.fly_body_ids])).astype("<f4")
        if self.fly_pose_array is None or not np.array_equal(pose, self.fly_pose_array):
            self.fly_pose_array = pose
            self.fly_pose_bytes = base64.b64encode(pose.tobytes()).decode("ascii")
            self.fly_pose_revision += 1

    def _sample_contacts(self):
        if not self.data.ncon:
            return
        geoms = self.data.contact.geom[:self.data.ncon]
        self.contact_seen |= bool(self.probe_active and np.any(geoms == self.probe_geom))
        bodies = self.model.geom_bodyid[geoms]
        fly = self.fly_body_mask[bodies]
        world = bodies == 0
        count = int(np.count_nonzero((fly[:, 0] & world[:, 1]) | (fly[:, 1] & world[:, 0])))
        if count:
            self.fly_contacts_seen = True
            self.fly_contact_count = count

    def snapshot(self, pose_revision=None, trail_version=None, neural_revision=None,
                 motor_revision=None, habitat_revision=None, survival_revision=None):
        with self.lock:
            state = {
                "sequence": self.sequence, "time": float(self.data.time),
                "paused": self.paused, "speed": self.speed,
                "realtime_ratio": self.ratio, "error": self.error,
                "fly": {
                    "id": FLY_ID, "pose_revision": self.fly_pose_revision,
                    "sleeping": bool(self.data.tree_asleep[self.fly_tree] >= 0),
                    "contact_seen": self.fly_contacts_seen,
                    "last_contact_count": self.fly_contact_count,
                },
                "probe": {
                    "active": self.probe_active, "generation": self.probe_generation,
                    "position": self.data.xpos[self.probe_id].tolist(),
                    "contact_seen": self.contact_seen,
                },
            }
            if pose_revision != self.fly_pose_revision:
                state["fly"]["poses_b64"] = self.fly_pose_bytes
            if trail_version != (self.probe_generation, len(self.probe_trail)):
                state["probe"]["trail"] = list(self.probe_trail)
            state["probe"]["trail_count"] = len(self.probe_trail)
            if self.neural:
                neural = self.neural.snapshot()
                state["neural_revision"] = neural["revision"]
                state["neural_running"] = neural["status"] == "running"
                if neural_revision != neural["revision"]:
                    state["neural"] = neural
            if self.motor:
                motor = self.motor.state
                state["motor_revision"] = motor["revision"]
                state["motor_running"] = self.motor.active
                if motor_revision != motor["revision"]:
                    state["motor"] = motor
            state["habitat_revision"] = self.habitat.revision
            if habitat_revision != self.habitat.revision:
                state["habitat"] = self.habitat.snapshot()
            survival = self.survival.snapshot()
            state["survival_revision"] = survival["revision"]
            if survival_revision != survival["revision"]:
                state["survival"] = survival
            return state

    def _advance_survival(self, seconds):
        """Runs on executed physics blocks only, under the existing state lock."""
        if self.survival.advance(seconds):
            if self.motor:
                self.motor.finish()
            if self.neural:
                self.neural.cancel_trial()
        self.habitat.consume(self.motor, self.survival, seconds)

    def _run(self):
        previous = time.monotonic()
        measured_wall, measured_sim = previous, self.data.time
        accumulator = 0.
        wait = .01
        try:
            while not self.stop.wait(wait):
                now = time.monotonic()
                cpu_started = time.thread_time()
                elapsed, previous = now-previous, now
                with self.lock:
                    if self.paused:
                        accumulator = 0.
                    else:
                        # Never skip physical time or accumulate an unbounded catch-up queue.
                        accumulator = min(accumulator+elapsed*self.speed, .025)
                        steps = min(int(accumulator/self.model.opt.timestep), 250)
                        remaining = steps
                        while remaining:
                            if self.motor and self.motor.active:
                                block = 1
                                self.motor.step()
                            else:
                                block = min(10, remaining) if self.data.ntree_awake else remaining
                                mujoco.mj_step(self.model, self.data, nstep=block)
                            remaining -= block
                            self._advance_survival(block*self.model.opt.timestep)
                            self._sample_contacts()
                            if (self.habitat.enabled and self.habitat.objects
                                    and self.survival.alive
                                    and self.data.time >= self.habitat.next_sample):
                                was_running = bool(self.motor and self.motor.active)
                                self.habitat.sample(
                                    self.motor,
                                    bool(self.neural and self.neural.snapshot()["status"] == "running"),
                                    bool(self.data.tree_asleep[self.fly_tree] >= 0),
                                    self.survival)
                                if not was_running and self.motor and self.motor.active:
                                    self.next_pose_time = 0.
                            if self.probe_active and len(self.probe_trail) < 500:
                                p = self.data.xpos[self.probe_id]
                                if np.linalg.norm(p-self.probe_trail[-1]) > .15:
                                    self.probe_trail.append(p.tolist())
                            # Release the lock frequently enough to serve poses
                            # and commands while a costly articulated body settles.
                            if time.thread_time()-cpu_started >= PHYSICS_SLICE_CPU_SECONDS:
                                break
                        accumulator -= (steps-remaining)*self.model.opt.timestep
                        if not np.isfinite(self.data.qpos).all():
                            raise RuntimeError("Non-finite physical state")
                        if self.data.warning.number.any():
                            raise RuntimeError("Physics warning; simulation stopped")
                    if now >= self.next_pose_time:
                        mujoco.mj_kinematics(self.model, self.data)
                        self._cache_fly_pose()
                        active = self.data.ntree_awake or (self.motor and self.motor.active)
                        self.next_pose_time = now + (POSE_INTERVAL if active else 1)
                    self.sequence += 1
                    if now-measured_wall >= 1:
                        self.ratio = (self.data.time-measured_sim)/(now-measured_wall)
                        measured_wall, measured_sim = now, self.data.time
                    awake = (bool(self.data.ntree_awake) or bool(self.motor and self.motor.active)) and not self.paused
                # Enforce the worker's duty budget even if host quota accounting
                # is delayed. Slow physical time rather than growing a backlog.
                cpu_used = time.thread_time()-cpu_started
                wait = max(.001 if awake else .01,
                           cpu_used/PHYSICS_CPU_BUDGET-(time.monotonic()-now))
        except Exception as exc:
            with self.lock:
                if self.motor:
                    self.motor.finish("error", str(exc))
                self.error = str(exc)
                self.paused = True
        finally:
            with self.lock:
                if self.motor:
                    self.motor.finish()


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, port, environment):
        self.environment = environment
        self.stream_slots = threading.BoundedSemaphore(8)
        self.allowed_hosts = {f"localhost:{port}", f"127.0.0.1:{port}"}
        super().__init__(("0.0.0.0", port), Handler)


class Handler(BaseHTTPRequestHandler):
    """Allowlisted local assets and narrow simulation commands; no file browser."""

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def valid_host(self):
        if self.headers.get("Host") not in self.server.allowed_hosts:
            self.send_error(403)
            return False
        return True

    def respond(self, payload, content_type="application/json", status=200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        try:
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        if not self.valid_host():
            return
        path = urlsplit(self.path).path
        env = self.server.environment
        if path == "/api/dev-version" and DEV_MODE:
            files = sorted((ROOT/"web").glob("*"))
            revision = hashlib.sha256("".join(
                f"{p.name}:{p.stat().st_mtime_ns}:{p.stat().st_size}"
                for p in files if p.is_file()).encode()).hexdigest()
            return self.respond(json.dumps({"instance": DEV_INSTANCE, "assets": revision}).encode())
        if path == "/api/world":
            return self.respond(env.world_bytes)
        if path in ("/api/state", "/health"):
            state = env.snapshot()
            return self.respond(json.dumps(state).encode(), status=503 if state["error"] else 200)
        if path == "/api/events":
            if not self.server.stream_slots.acquire(blocking=False):
                return self.send_error(503, "Viewer limit reached")
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                pose_revision = trail_version = neural_revision = motor_revision = habitat_revision = None
                survival_revision = None
                while not env.stop.is_set():
                    state = env.snapshot(pose_revision, trail_version, neural_revision,
                                         motor_revision, habitat_revision, survival_revision)
                    payload = json.dumps(state, separators=(",", ":"))
                    self.wfile.write(f"data: {payload}\n\n".encode())
                    self.wfile.flush()
                    pose_revision = state["fly"]["pose_revision"]
                    trail_version = (state["probe"]["generation"], state["probe"]["trail_count"])
                    neural_revision = state.get("neural_revision")
                    motor_revision = state.get("motor_revision")
                    habitat_revision = state["habitat_revision"]
                    survival_revision = state["survival_revision"]
                    active = not state["fly"]["sleeping"] or (state["probe"]["active"] and not state["probe"]["contact_seen"])
                    interval = POSE_INTERVAL if active and not state["paused"] else 1
                    running = state.get("neural_running") or (state.get("motor_running") and not state["paused"])
                    env.stop.wait(min(interval, .1) if running else interval)
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                pass
            finally:
                self.server.stream_slots.release()
            return
        if path == "/assets/fly-surfaces.bin":
            compressed = "gzip" in self.headers.get("Accept-Encoding", "")
            payload = env.fly_surfaces_gzip if compressed else env.fly_surfaces
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Vary", "Accept-Encoding")
            self.send_header("Cache-Control", "no-store")
            if compressed:
                self.send_header("Content-Encoding", "gzip")
            self.end_headers()
            try:
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        textures = {f"/textures/{i}.png": data for i, data in env.textures.items()}
        if path in textures:
            return self.respond(textures[path], "image/png")
        assets = {
            "/": ("web/index.html", "text/html; charset=utf-8"),
            "/environment.js": ("web/environment.js", "text/javascript; charset=utf-8"),
            "/fly.js": ("web/fly.js", "text/javascript; charset=utf-8"),
            "/neural.js": ("web/neural.js", "text/javascript; charset=utf-8"),
            "/motor.js": ("web/motor.js", "text/javascript; charset=utf-8"),
            "/actions.js": ("web/actions.js", "text/javascript; charset=utf-8"),
            "/inspect.js": ("web/inspect.js", "text/javascript; charset=utf-8"),
            "/habitat.js": ("web/habitat.js", "text/javascript; charset=utf-8"),
            "/habitat.css": ("web/habitat.css", "text/css; charset=utf-8"),
            "/survival.js": ("web/survival.js", "text/javascript; charset=utf-8"),
            "/survival.css": ("web/survival.css", "text/css; charset=utf-8"),
            "/actions.css": ("web/actions.css", "text/css; charset=utf-8"),
            "/neural.css": ("web/neural.css", "text/css; charset=utf-8"),
            "/dev-reload.js": ("web/dev-reload.js", "text/javascript; charset=utf-8"),
            "/style.css": ("web/style.css", "text/css; charset=utf-8"),
            "/favicon.svg": ("web/favicon.svg", "image/svg+xml"),
            "/vendor/three.module.js": ("node_modules/three/build/three.module.js", "text/javascript"),
            "/vendor/three.core.js": ("node_modules/three/build/three.core.js", "text/javascript"),
            "/vendor/LICENSE": ("node_modules/three/LICENSE", "text/plain"),
        }
        if path not in assets:
            return self.send_error(404)
        filename, content_type = assets[path]
        try:
            payload = (ROOT/filename).read_bytes()
            if path == "/" and DEV_MODE:
                payload = payload.replace(b"</head>", b'<script type="module" src="/dev-reload.js"></script></head>')
            self.respond(payload, content_type)
        except FileNotFoundError:
            self.send_error(503, "Browser assets unavailable; install locked dependencies first")

    def do_POST(self):
        if not self.valid_host():
            return
        host = self.headers.get("Host")
        if (self.headers.get("Origin") != f"http://{host}"
                or self.headers.get("Content-Type") != "application/json"):
            return self.send_error(403)
        if self.path != "/api/command":
            return self.send_error(404)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 1024:
                raise ValueError("Invalid request length")
            command = json.loads(self.rfile.read(length))
            self.server.environment.command(command)
        except (ValueError, UnicodeDecodeError) as exc:
            return self.respond(json.dumps({"error": str(exc)}).encode(), status=400)
        self.respond(json.dumps(self.server.environment.snapshot()).encode())

    def log_message(self, fmt, *args):
        # No per-frame logs; requests remain visible in browser network tooling.
        if args and str(args[1]) not in ("200", "304"):
            super().log_message(fmt, *args)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8089)
    args = parser.parse_args()
    if not (ROOT/"node_modules/three/build/three.module.js").is_file():
        raise SystemExit("Missing browser dependencies. Run the guarded pnpm install first.")
    environment = Environment()
    server = Server(args.port, environment)
    environment.start()
    print(f"NETSPHERE ready on port {args.port}: "
          f"{len(environment.world['geoms'])} world geoms; one physical fly.", flush=True)
    if environment.neural:
        print(f"Neural reference lab: {environment.neural.snapshot()['status']}; "
              f"MN9 motor link: {environment.motor.state['status']}.", flush=True)
    try:
        server.serve_forever()
    finally:
        environment.stop.set()
        server.server_close()


if __name__ == "__main__":
    main()
