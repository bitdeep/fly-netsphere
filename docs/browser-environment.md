# Browser environment

The browser shows one physical flybody animal in the NETSPHERE. It supports
contact feeding, finite food/water portions and survival reserves. **It does not
yet seek nearby food, walk or fly.** The [delivery plan](embodied-roadmap.md)
defines that unfinished integration and its acceptance tests.

## Use the observatory

Start with **Objects → Apple → Offer at mouth**. After the body settles, contact
can trigger a neural response, mouth movement and intake. Try water next.
Both reserves start at 70%; either reaching zero ends the simulated life.
See [feeding and survival](habitat.md) for resource rules and measured results.

| Control | What it does today |
|---|---|
| Objects → Offer at mouth | Places a finite portion at the measured mouth; never moves the fly |
| Objects → Place in world | Click a surface within 3 cm; a source outside mouth contact causes no response |
| React to objects / × | Enable or disable world taste input / remove a source |
| Feed / Water / Bitter | Direct taste experiments; these buttons do not replenish reserves |
| Antenna | Separate neural-only assay, with no body actuation |
| Baseline / Block link or Block sensory | Compare the selected experiment with its causal control |
| Pause / Stop | Freeze simulation time / cancel the current trial; stopping a world trial also disables reactive senses |
| New life | Available after death; restores reserves while preserving pose, objects and Pause |
| Wings / Walk | Not connected |
| Neural activity | Inspect measured signals; commands stay available with the panel closed |

Taste experiments drive only the rostrum through the
[MN9 adapter](motor-link.md). The [antennal assay](neural-reference.md) has its
own clock and no motor authority. Touching an antenna, moving the mouse or
changing the camera does not stimulate it.

Select **Fly 001**, its card or marker to follow the measured thorax; drag to
orbit and scroll to zoom. **Focus** frames the head. In city views, drag to look,
use **W A S D** to move, **Q / E** vertically and **Shift** for speed; the wheel
moves forward/backward. Touch screens have movement buttons. These controls
move the observer, never the animal.

Hover, focus or tap inspector values for explanations. Point along a trace for
its nearest measured 5 ms sample; Escape dismisses hints. Results remain visible
in the action bar. The amber sphere is a separate gravity experiment, and the
[flight recordings](stabilized-pov.md) are an offline pipeline.

## Start

Use the provisioned, Socket-protected Docker package launcher:

```bash
pnpm-docker install --frozen-lockfile
scripts/fetch_flybody.sh  # pinned anatomical source; policies are unnecessary here
docker compose --profile dev build environment-dev
mkdir -p out/browser-fly
docker compose --profile dev run --rm --no-deps --user "$(id -u):$(id -g)" \
  -v "$PWD/out/browser-fly:/cache" environment-dev \
  python scripts/prepare_browser_fly.py --output /cache
docker compose --profile dev up -d --no-build environment-dev
```

Open **http://localhost:8089** on the same machine. This is the only development
stack. The service binds to loopback; it is not a public deployment.
An SSH tunnel can forward port 8089 for remote use.
After installing dependencies, the page loads all scripts and textures locally.
No CDN, analytics, external fonts or browser extensions are required. Preparation
is done once; rebuild the cache after changing the source anatomy or generator.
Startup verifies the source XML, generator, physics and visual packet hashes.
The manifest also records source mesh hashes for provenance.

Next, [prepare and validate the neural cache](neural-reference.md#resources-and-preparation)
to enable the taste and antennal experiments. The body setup alone does not
enable them; missing or stale neural validation disables their controls.

```bash
docker compose logs --tail 30 environment-dev
docker compose stop environment-dev
```

Stopping the service ends the current session. There is no restart policy or
persistent recording in this first environment version.

## Interactive development

The detached `environment-dev` container uses a read-only bind mount of this
checkout. `scripts/dev_environment.py` checks backend source timestamps once per
second and restarts its child server after a Python edit. Syntax errors postpone
reload, leaving the previous process running and a diagnostic in container logs.
The injected `web/dev-reload.js` checks asset versions every 1.5 seconds while
visible, then reloads the page when frontend files or the backend instance change.
This is page live-reload and process restart, not module HMR.

A backend restart starts a new development body simulation and ends any current
trial. A frontend reload preserves backend state. Neural preparation and Brian2
validation are explicit one-shot tools; the watcher never reruns them on an edit.
After regenerating the neural cache, restart `environment-dev` to load it.
Docker configuration or watcher changes also require restarting/recreating that
one service. Reuse port 8089; do not launch a second viewer stack.
The GPU recording service belongs to the separate `recording` profile, so
activating the `dev` profile cannot start a flight recording in the background.

## Simulation and rendering

- `scripts/serve_environment.py` instantiates `City` from `city_world.py` and
  attaches the cached fly anatomy and compiles its MJCF with MuJoCo 3.13.0.
  The exported 383 world geoms retain their
  primitive dimensions and compiled world transforms. Geometry is not rebuilt
  procedurally in JavaScript. Positions and dimensions use centimetres.
- MuJoCo runs on the CPU at a 0.1 ms step, with gravity −981 cm/s², matching the
  anatomical model's default passive/walking step. This is **not the 50 µs flight
  physics timestep** and does not measure controlled flight or neural performance.
- Preparation processes one source geom at a time. Mass, centre of mass and
  inertia are computed from the full-resolution source before visual reduction;
  explicit principal inertias preserve even tiny foot tensors. Recompilation
  checks mass and inertia to relative tolerance 1e-10. Collision primitives,
  joints, passive parameters, tendons and sensor definitions remain intact.
- Only noncolliding visual surfaces are simplified. The current cache contains
  103,807 triangles (source: 272,550), with maximum original-vertex displacement
  15.2 µm, and a 2.56 MiB binary packet before HTTP compression.
  The 67 physical segments have a total mass of approximately 0.985 mg.
- Native MuJoCo sleep is allowed between motor trials, at the default
  0.001 cm/s tolerance. The attachment frame's rotational sleep length is corrected
  from its distance to the world origin to a conservative anatomical collision
  radius (0.286 cm). This changes sleep eligibility, not forces or integration.
  Settling is integrated normally; no pose is frozen or reset to fake a rest state.
  Sleep remains an approximation: the measured difference from awake dynamics
  over 200 ms is about 10 µm, below the measured visual reduction displacement.
  Stricter tolerances kept micro-adjustments active beyond 15 simulated seconds.
  This accuracy/idle-cost tradeoff is specific to the passive viewer, not a
  connectome or controlled-locomotion validation.
  See [MuJoCo sleeping semantics](https://mujoco.readthedocs.io/en/stable/programming/simulation.html#sleeping-islands).
  The motor bridge uses MuJoCo's documented negative-zero applied-force wake
  signal, adding no nonzero force. The fly tree cannot sleep while driven;
  completing or stopping the trial restores passive sleep eligibility.
- One backend simulation thread advances independently of browser tabs. Server
  events target changed body poses at up to 30 Hz and idle status at 1 Hz.
  Unchanged poses and trails are omitted per viewer; reconnect starts with a full
  state. Native stepping runs in bounded blocks with no catch-up backlog.
  A thread-CPU duty budget of 0.9 core leaves headroom for HTTP inside the
  container ceiling. Integration releases the shared state lock after roughly
  6 ms of thread CPU, checked between native stepping blocks, so costly body
  settling cannot hold up every state read for a full 250-step batch.
  Only executed steps are subtracted from the bounded accumulator.
  A coupled motor trial advances one neural and one physical step together,
  inside that same physics-thread budget. It adds no second simulation worker.
  While settling, physical time may advance slower than wall
  time; the footer reports the measured ratio. Resting bodies resume near 1×.
  Pause and 0.25× speed affect the
  shared simulation; the observer camera remains usable while paused.
- Three.js 0.180.0 uses WebGL 2 for the viewer. Static solids are batched by
  material; the fly uses seven rigidly skinned material batches sharing one
  skeleton. Its geometry is loaded once, and only segment transforms change.
  Anatomy smaller than eight rendered pixels is culled; a selectable marker
  identifies its position when unobstructed. Surface images come from the compiled model; lighting, fog, UV tiling
  and perspective are observer presentation and do not simulate compound eyes.
- Rendering is on demand, without a perpetual animation callback: a stationary
  camera and settled bodies produce no new
  scene frames. Movement targets 30 FPS, paced on browser vsync without an extra
  full-frame timer. The pixel ceiling is 1.5 million (360,000 for detected
  software renderers, which also target 30 FPS). Hidden tabs stop drawing.
  WebGL requests the browser's high-performance GPU. The footer identifies GPU,
  software or undisclosed WebGL rendering. It reports `FPS` while moving the
  camera, `UPDATES/S` for changed scene frames while stationary and `VIEW IDLE`
  when nothing redraws. A low stationary update count does not measure the
  renderer's maximum frame rate.
  A GPU preference is a request, not a guarantee that hardware acceleration is
  available in that browser. Container GPU access would not accelerate this
  client-side WebGL renderer.
  World shadow maps are 1024² and only recomputed when the probe moves.
  The tiny fly receives direct scene lighting without a separate shadow pass.
  Its close-up camera uses a smaller near plane and orbit controls.
- The camera is an observer with swept point-ray clearance against source solids.
  It is not an embodied collision controller. View presets may move the observer
  directly and never move a physical animal.
- “Test gravity” releases a 9 mm sphere with steel density (7.85 g/cm³) above `bridge_0`, preserving the
  global simulation clock and the fly's position and velocity. The displayed trail
  consists of measured positions in a fixed-size GPU buffer.
  Releasing it again explicitly initializes a new test. The sphere has ordinary
  contact/friction and finite solver penetration.

The server only serves an allowlist of frontend assets and read endpoints:
`/api/world`, `/api/state`, `/api/events`, `/health`, plus `/api/dev-version` in
development mode. `POST /api/command` accepts bounded drop, pause, speed,
`neural_trial`, `neural_stop`, `motor_trial`, `motor_stop`, `object_place`,
`object_remove`, `reactive_senses` and `life_restart` commands with same-origin JSON.
`life_restart` accepts no parameters and is rejected while the animal is alive.
Trial mode must be `stimulus`, `baseline` or `blocked`; only one neural or motor
trial runs at a time. `motor_trial` optionally accepts `stimulus`: exactly
`sugar`, `water` or `bitter`, defaulting to `sugar` for older clients.
Motor commands cannot select arbitrary neurons, actuator
names, gains, torques or durations. It cannot read
arbitrary project files or edit anatomical/world geometry. Object commands expose
only four named taste presets, four slots and finite positions within 3 cm of
the fly; they do not accept arbitrary neural or motor parameters.
At most eight event streams are open
at once. The container has a read-only filesystem and limits of 2 CPUs, 1 GiB
RAM and 64 PIDs. These limits cover the backend; the browser is a separate process.
The separate antennal worker has a duty budget of 0.15 core, runs only on request
and publishes changes at up to 10 Hz. It adds no continuous scene render loop.
This local server is not intended to be exposed directly to the internet.

`web/actions.js` owns trial commands. `web/neural.js` and `web/motor.js` only
inspect state; they draw changed data while their tab is visible.
`web/inspect.js` manages one shared, event-driven tooltip, including the bounded
sample lookup. Neither the inspector nor the action bar adds an idle animation
loop, and unchanged control state causes no repeated DOM writes.
`web/habitat.js` shares one small sphere geometry across four preallocated
meshes, with no shadow pass or animation loop. Object lists are sent by revision,
and the scene redraws only when their visible geometry changes. Contact sensing
runs on physical time in the same worker. Used nonfood controls stop sensing;
remaining apple/water portions can retry under the documented rest/cooldown
gates. Death stops sensing. `web/survival.js` updates DOM meters on changed state
without requesting 3D redraws; its small revisioned packet contains no anatomy.

The renderer already supports richer textures: Three.js
[MeshStandardMaterial](https://threejs.org/docs/pages/MeshStandardMaterial.html)
provides color, normal, roughness, metalness and environment maps. After the
seeking loop passes, visual work can improve authored materials, UVs and lighting
within the existing frame/memory budget. The official
[KTX2Loader](https://threejs.org/docs/pages/KTX2Loader.html) supports compressed
GPU textures; it is a candidate for larger assets, not yet enabled here. Changing
the renderer is not required for that material workflow. No external assets or
new runtime dependencies were introduced for reserves.

## Validation

```bash
pnpm-docker run check
docker compose --profile dev exec environment-dev python scripts/test_environment.py
docker compose --profile dev exec environment-dev python -c \
  "import pathlib; [compile(p.read_bytes(), str(p), 'exec') for p in pathlib.Path('scripts').glob('*.py')]"
```

The physics checks isolate gravity in zero air for an analytic trajectory in centimetres,
check contact and the final height on the existing bridge, preserve the global
clock and animal state across probe resets, and reject unsupported commands.
They check the unchanged anatomical contracts, disabled actuation, fly contact,
native sleep and force-triggered wake, and compare sleep with 200 ms of awake
dynamics (segment drift must remain below the measured visual reduction
displacement, currently 15.2 µm). Delta telemetry is also checked.
The [motor validation](motor-link.md#validation) separately tests the full graph
against no-input and blocked-link controls, exact clock alignment, sleeping-body
wake, the actuator allowlist, cancellation and failure handling.
Browser checks cover visible rendering, view changes, mouse/keyboard motion,
pause/resume, slow motion, the gravity experiment, reconnect and mobile layout.
The measured passive-viewer sample below predates the neural panel. The later
publication check repeated all seven physical checks and checked the JavaScript,
Python, shell and dependency locks. A short browser session exercised stimulus,
baseline and blocked sensory output, verified their displayed counts, and
inspected the panel on desktop and at 390×844 with no horizontal overflow.
There were no JavaScript exceptions or failed requests; a software graphics
context reset during viewport resizing recovered. The session was then closed.
The subsequent action-bar round exercised all four stimuli, blocked water input's
motor link with the inspector closed, and stopped/restarted an antennal trial.
Desktop and mobile tooltips worked with pointer, click and keyboard focus.
The mobile panel and action bar remained separate with no horizontal overflow.
Detailed counts and causal comparisons are in the [motor guide](motor-link.md#validation).
An additional control audit found that a comparison tooltip could cover the Water
button and intercept the next click. After correcting placement and pointer
handling, all 12 preset/mode combinations were exercised through the browser with
the inspector closed, checking both telemetry and the visible result. Focus changed
only the camera; the inspector toggle opened/closed; Stop cancelled both a driven
motor trial while paused and an antennal trial. Disabled Wings/Walk captions and
their explanations were inspected; those behaviors remain unimplemented.
The 390×844 layout had no horizontal overflow or panel/bar overlap, and the
comparison-to-preset transition worked with its tooltip visible. No JavaScript
exceptions or non-200 requests were observed in that audit; the software graphics
context recovered after resizing. The test browser was closed.
Page/process live-reload and 30 FPS on the user's hardware remain separate from
those checks.
The subsequent [gallery checks](habitat.md#resource-bounds-and-verification)
exercised object placement/contact/removal, all manual comparisons, both Stop
paths and mobile panel behavior, and measured resting resource usage.

Resource efficiency is an acceptance requirement. Keep the one-animal default
and existing container ceilings; measure CPU, RAM and browser rendering before
increasing population. Multiple animals would need independent dynamic state and
shared immutable surfaces/connectivity. No multi-animal runtime is enabled yet.
Neural activity, sensory channels and motor control must be validated separately
before describing this as connectome-controlled behavior.

### Measured passive-viewer sample

Earlier validation on 2026-09-12, one animal and one isolated browser, before the
resource increase (0.5 CPU / 512 MiB container, 0.25-core physics budget):

| Workload | Observed |
|---|---:|
| Anatomy preparation peak RSS | 231.6 MiB |
| Server while settling, 24-second sample | 25–26% of one CPU core; about 131 MiB |
| Server at rest, 3-second sample | 8.34% of one CPU core; 137.5 MiB |
| Isolated Chrome at rest, 3-second sample | 0.33% of one CPU core; 495.3 MiB summed PSS |
| New scene frames during a stationary 2.2-second observation | 0 |
| Simulated clock advance during that observation | 2.001 seconds |
| Native settling time | 4.8 simulated seconds |
| Maximum segment drift in the 200 ms awake comparison | 10.062 µm |
| Triangles in the distant gallery after animal culling | 16,802 |

Browser measurements include Chrome and its software renderer, with a 360,000-pixel
budget and 12 FPS ceiling. They are short samples, not guarantees for other tabs,
hardware or neural workloads. The backend allocates no GPU. The startup settling
phase runs slower than wall time under its CPU budget; idle physics subsequently
runs near 1×. Seven physics/transport checks passed. Browser checks also confirmed
orbit/zoom, selection and return, mobile framing, pause/resume, probe contact without
moving the animal, unchanged geometry counts at rest, and no console or request
errors. The isolated test browser was closed afterwards.

The subsequent performance round increased the dev ceiling to 2 CPUs / 1 GiB
and the physics budget to 0.9 core, shortened lock-held batches, raised pose
delivery toward 30 Hz and requested high-performance browser graphics. Container
diagnostics are distinct from user-side FPS: the 30 FPS target still requires
measurement while moving the camera in the user's browser.
