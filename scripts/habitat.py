"""Bounded world taste cues sampled against the fly's anatomical mouth geometry.

Objects are permeable, stationary taste volumes, not rigid food or odor fields.
Finite portions transfer simplified reserves only during measured motor contact.
"""
import math

import mujoco
import numpy as np

from passive_fly import FLY_ID
from survival import PORTION

CAPACITY = 4
RADIUS = .025  # cm: a 0.5 mm diameter taste volume.
SENSE_INTERVAL = .005  # 200 Hz, on physical time.
RETRY_INTERVAL = 2.  # At most one rest-start response per source per two seconds.
KINDS = {
    "fruit": {"label": "Apple bite", "stimulus": "sugar", "color": "#dc775e"},
    "water": {"label": "Water drop", "stimulus": "water", "color": "#80c7df"},
    "bitter": {"label": "Bitter drop", "stimulus": "bitter", "color": "#b094ce"},
    "neutral": {"label": "Neutral bead", "stimulus": None, "color": "#adb9b2"},
}
RESOURCES = {"fruit": "energy", "water": "water"}


def attach_objects(root):
    for slot in range(CAPACITY):
        body = root.worldbody.add("body", name=f"habitat_{slot}", mocap=True,
                                 pos=[0, 0, -200])
        body.add("geom", name=f"habitat_{slot}_volume", type="sphere", size=[RADIUS],
                 contype=0, conaffinity=0, rgba=[1, 1, 1, 0])


class Habitat:
    def __init__(self, model, data):
        self.model, self.data = model, data
        self.geoms = [model.geom(f"habitat_{i}_volume").id for i in range(CAPACITY)]
        self.mocaps = [int(model.body_mocapid[model.body(f"habitat_{i}").id])
                       for i in range(CAPACITY)]
        # The published GRNs used by the current assay are from the right labellum.
        # flybody calls its corresponding mouthpart "labrum_right".
        self.mouth = model.geom(f"{FLY_ID}/labrum_right_lower_collision").id
        self.thorax = model.body(f"{FLY_ID}/thorax").id
        self.objects = []
        self.serial = self.revision = 0
        self.enabled = True
        self.next_sample = 0.
        self.status = "Place an object, or offer one at the mouth."
        self.descriptor = {
            "capacity": CAPACITY, "radius_cm": RADIUS,
            "portion_capacity": PORTION,
            "sample_ms": SENSE_INTERVAL*1000,
            "kinds": [{"id": key, **value} for key, value in KINDS.items()],
            "retry_seconds": RETRY_INTERVAL,
            "boundary": "Finite taste portions and simplified reserves; no odor or autonomous locomotion.",
        }

    def _change(self, text):
        if self.status != text:
            self.status = text
            self.revision += 1

    def place(self, kind, position=None):
        if not isinstance(kind, str) or kind not in KINDS:
            raise ValueError("Unknown habitat object")
        if len(self.objects) == CAPACITY:
            raise ValueError("The gallery is full. Remove an object before adding another.")
        if position is None:
            # Offering places only a taste volume at the current measured mouth.
            # It neither resets the animal nor moves its mouth to a target.
            point = self.data.geom_xpos[self.mouth].copy()
        else:
            if (not isinstance(position, list) or len(position) != 3
                    or any(type(x) not in (int, float) or not math.isfinite(x) for x in position)):
                raise ValueError("Object position must contain three finite numbers")
            point = np.asarray(position, dtype=float)
            if np.linalg.norm(point-self.data.xpos[self.thorax]) > 3:
                raise ValueError("Place objects within 3 cm of the fly")
        occupied = {item["slot"] for item in self.objects}
        slot = next(i for i in range(CAPACITY) if i not in occupied)
        self.serial += 1
        item = {"id": self.serial, "slot": slot, "kind": kind,
                "position": point.tolist(), "used": False, "contact": False,
                "remaining": PORTION if kind in RESOURCES else None,
                "retry_at": 0.}
        self.objects.append(item)
        self.data.mocap_pos[self.mocaps[slot]] = point
        mujoco.mj_kinematics(self.model, self.data)
        self.next_sample = 0.
        self.revision += 1
        self._change(f"{KINDS[kind]['label']} placed · waiting for mouth contact.")

    def remove(self, object_id):
        if type(object_id) is not int:
            raise ValueError("Invalid object ID")
        item = next((item for item in self.objects if item["id"] == object_id), None)
        if item is None:
            raise ValueError("Object is no longer present")
        self.objects.remove(item)
        self.data.mocap_pos[self.mocaps[item["slot"]]] = [0, 0, -200]
        mujoco.mj_kinematics(self.model, self.data)
        self.revision += 1
        self._change("Object removed · existing neural activity can decay.")

    def touching(self, object_id):
        item = next((x for x in self.objects if x["id"] == object_id), None)
        if item is None or not self.enabled:
            return False
        distance = mujoco.mj_geomDistance(self.model, self.data, self.mouth,
                                         self.geoms[item["slot"]], .001, None)
        return distance <= 0

    def set_enabled(self, value):
        if type(value) is not bool:
            raise ValueError("Reactive senses must be boolean")
        self.enabled = value
        self.next_sample = 0.
        self.revision += 1
        self._change("Reactive senses on." if value else "Reactive senses off.")

    def consume(self, motor, survival, seconds):
        """Measured force, displacement and native contact gate each transfer.

        This resource accounting is an engineered approximation of intake, not
        simulated swallowing. It has no authority over body state or neurons.
        """
        if (not survival.alive or not self.enabled or not motor or not motor.active
                or motor.mode != "stimulus" or not motor.motor_total
                or not motor.state.get("source")
                or abs(self.data.actuator_force[motor.actuator]) <= 1e-12
                or abs(self.data.qpos[motor.qpos]-motor.initial_angle) < math.radians(1)):
            return
        object_id = motor.state["source"]["object_id"]
        item = next((x for x in self.objects if x["id"] == object_id), None)
        if item is None or item["kind"] not in RESOURCES or not self.touching(object_id):
            return
        amount = survival.receive(RESOURCES[item["kind"]], item["remaining"], seconds)
        if amount <= 0:
            return
        item["remaining"] = max(0., item["remaining"]-amount)
        self.revision += 1
        label = KINDS[item["kind"]]["label"]
        if item["remaining"] <= 1e-12:
            self.remove(object_id)
            self.next_sample = 0.
            self._change(f"{label} consumed · portion empty.")
        else:
            self._change(f"{label} · consuming during mouth contact.")

    def sample(self, motor, neural_running, sleeping, survival=None):
        if (not self.enabled or not self.objects or self.data.time < self.next_sample
                or survival is not None and not survival.alive):
            return
        self.next_sample = self.data.time+SENSE_INTERVAL
        for item in self.objects:
            if item["used"]:
                resource = RESOURCES.get(item["kind"])
                if (survival is None or resource is None or motor and motor.active
                        or self.data.time < item["retry_at"]):
                    continue
                # Reserve feedback schedules another bounded contact reflex.
                # It is not an ongoing neural hunger signal.
                if getattr(survival, resource) >= .95:
                    continue
            resource = RESOURCES.get(item["kind"])
            if survival is not None and resource and getattr(survival, resource) >= .95:
                continue
            contact = self.touching(item["id"])
            if contact != item["contact"]:
                item["contact"] = contact
                self.revision += 1
            if not contact:
                continue
            label = KINDS[item["kind"]]["label"]
            stimulus = KINDS[item["kind"]]["stimulus"]
            if stimulus is None:
                item["used"] = True
                item["retry_at"] = float(self.data.time)+RETRY_INTERVAL
                self.revision += 1
                self._change(f"{label} · mouth contact · no taste input.")
            elif not motor or not motor.descriptor["available"]:
                self._change("Mouth contact · neural link unavailable.")
            elif motor.active or neural_running or not sleeping:
                self._change(f"{label} · mouth contact · waiting for the fly to rest.")
            else:
                object_id = item["id"]
                motor.start("stimulus", stimulus,
                            sensory_gate=lambda: self.touching(object_id),
                            source={"object_id": object_id, "label": label})
                item["used"] = True
                item["retry_at"] = float(self.data.time)+RETRY_INTERVAL
                self.revision += 1
                self._change(f"{label} · world contact triggered a neural response.")
                break
        if all(item["used"] and (survival is None or item["kind"] not in RESOURCES)
               for item in self.objects):
            self.next_sample = math.inf

    def snapshot(self):
        return {"revision": self.revision, "enabled": self.enabled,
                "status": self.status, "objects": [
                    {**item, "remaining": (round(item["remaining"], 4)
                                          if item["remaining"] is not None else None)}
                    for item in self.objects]}
