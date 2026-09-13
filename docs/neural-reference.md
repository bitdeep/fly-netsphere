# Neural reference lab

The development observatory at **http://localhost:8089** runs a bounded antennal
stimulus-response assay using the published **FlyWire 630** graph: **127,400
neurons and 14,687,178 stored directed connections**, with their signed synapse
counts preserved. It uses the data and model parameters from
[Shiu and Spiller's reference repository at commit 91bdd1e](https://github.com/philshiu/Drosophila_brain_model/tree/91bdd1e7dcf193f3e7ca5a8933497fcef63b7960).
This is not the newer MaleCNS dataset. Specimens and releases remain distinct.

The antennal assay described here has its own clock, starts from neural rest
and does not drive the body. A separate [taste-response motor experiment](motor-link.md)
now couples the same full graph's MN9 neurons to the flybody rostrum through an
explicit engineered adapter, with a shared neural/physical clock.
The [object gallery](habitat.md) now supplies geometric mouth-contact input to
that taste experiment. Broader sensory/muscle control, walking and flight remain
future work; this is not a continuously embodied animal.

This guide is the numerical reference for those bounded experiments. The
[delivery plan](embodied-roadmap.md) requires sustained sensory, directional
readout and resource checks before using the model for seeking. Agreement on
short trials does not establish stable continuous activity or useful locomotor
commands. A future solver port must pass comparisons with this reference.

## Protocol and visible signals

Choose **Antenna** in the action bar. Open **Neural activity → Antenna** to
inspect the result; the action bar works with the inspector closed.
Each antennal trial lasts 150 ms of neural
time: 100 ms of input followed by 50 ms of recovery. The 146 published JON
antennal neurons come from the CE, F and D groups in the reference notebook.
Input is delivered directly to those neurons, not through simulated antenna
mechanics. A fixed seed (`20260912`) makes comparisons repeatable.

| Control | Input | Intervention |
|---|---|---|
| Antenna | 150 Hz per input neuron | Normal published connections |
| Baseline | No external input | Normal published connections |
| Block sensory | Same input events as stimulus | Zero outgoing weights from input neurons |

Silencing follows the reference code's outgoing-weight intervention. It does not
delete neurons. The JON neurons still spike in the blocked trial. **Stop** cancels
the current trial at the next bounded block; another trial starts fresh.

The transparent panel shows accumulated trial spikes, membrane voltages, a 5 ms binned
timeline and published aBN1, aDN1 and aDN2 readouts. The last two are descending
neurons; aBN1 is an interneuron. The schematic displays 21 selected actual neurons
and their connections, using no invented anatomical coordinates. The selection
does not prune the simulated graph. Node sizes/colors encode measured accumulated
spikes and remain visible after completion; no decorative animation runs at rest.
Excitatory/inhibitory edges show signed structural weights, not measured current
on each connection.
Hover, focus or tap the components and values for their interpretation, IDs and
measured voltages. Point along the timeline to inspect a sample.

The neural panel updates from the existing event stream without invalidating the
3D scene. It redraws its diagram/timeline only after a changed sample, while open
and visible. Muscle disconnection stays explicit in the antennal workflow;
the taste motor link has its own tab, labeled workflow and measured body trace.

## Model and numerical comparison

`scripts/neural_reference.py` integrates the reference leaky integrate-and-fire
equations analytically in float64, using a 0.1 ms clock:

```text
dv/dt = (-52 mV - v + g) / 20 ms
dg/dt = -g / 5 ms
spike when v > -45 mV; reset v = -52 mV and g = 0
refractory period = 2.2 ms (0 for externally driven input neurons)
synaptic delay = 1.8 ms; signed synapse count × 0.275 mV
external input event = 250 × 0.275 mV added to v
```

The update order is groups → threshold detection → delayed synapses → external
input → resets. Refractory variables reject input and remain frozen, matching
Brian2. The clock resumes at `tick - last_spike >= refractory_ticks`; this
boundary was checked against Brian2's generated state updater. N=1 Poisson input
uses an independent Bernoulli draw per input neuron per step.

The comparator is **Brian2 2.8.0.4** with NumPy code generation, installed only in
the disposable tooling container. The original repository specified Brian2
2.5.1; this is not a claim to reproduce its exact historical software environment.
Its reset string also includes `w=0`, although no neuronal `w` variable is
declared in the supplied equations. The comparator retains the defined `v` and
`g` resets and omits that undeclared assignment. The downloaded reference Python
is retained as text and never imported or executed.

`scripts/validate_neural_reference.py` compares membrane and synaptic states to
absolute tolerance 1e-8 mV, with **exact spike indices and ticks**, on excitation,
inhibition, recurrent and disconnected fixtures and an induced graph of the real
selected neurons. It also compares chunked versus continuous execution and
equilibrium skipping versus dense arithmetic. Deterministic input events are
identical in both implementations, avoiding unrelated RNG differences.

The full graph then runs the three interventions. This is a numerical and causal
check of the implementation, **not biological validation**, a reproduction of
all paper figures, or a whole-graph Brian2 comparison.

Measured on 2026-09-12:

| Trial | Input spikes | Downstream spikes | aBN1 / aDN1 / aDN2 |
|---|---:|---:|---|
| Baseline | 0 | 0 | 0 / 0 / 0 |
| Antennal stimulus | 2,200 | 706 | 6 / 2 / 2 |
| Sensory output blocked | 2,200 | 0 | 0 / 0 / 0 |

All numerical fixtures matched spike times, with maximum membrane discrepancy
7.11e-13 mV. The stimulated full graph had 383 neurons that spiked. The standalone
solver used about 0.213 CPU seconds for 150 ms of neural time. The budgeted assay
service took 1.552 seconds elapsed / 0.233 CPU seconds, and its published readouts
and 30 timeline bins matched the validated solver. These short, sparse-input
measurements used the earlier 0.5 CPU / 512 MiB container and do not predict
continuous whole-animal performance.

Reports live locally in `out/neural-reference/validation.json` and
`service-validation.json`. A subsequent publication check exercised all three
controls in the browser and observed the same counts and readouts. Desktop and
390×844 mobile views were inspected, with a scrollable panel and no horizontal
overflow. No JavaScript exceptions or failed requests were recorded. The
software graphics context was lost/restored during the viewport change and the
view recovered. This browser check does not measure hardware-accelerated FPS.

## Resources and preparation

The viewer and neural worker share **one** development container, limited to
2 CPUs, 1 GiB and 64 PIDs, with no GPU compute allocation. Browser rendering
separately requests its high-performance GPU. The neural worker has a
0.15-core duty budget in addition to the physics worker's 0.9-core budget.
Only one antennal or motor trial can run at a time. The motor experiment runs
inside the existing physics worker's budget, sharing the immutable graph.
Antennal limits are 90 seconds elapsed, 10 CPU
seconds and 100,000 spikes, checked every 25 steps. A limit stops the trial
explicitly with incomplete-result status instead of silently truncating it.
Small block overshoot is possible; Docker provides the outer CPU/memory limits.

Connectivity is immutable and memory-mapped, approximately 114 MiB of packed
arrays. Dynamic state belongs to the trial. Neurons never reached by input stay
at exact equilibrium and need no arithmetic; once reached, they remain in the
integration set without activity cutoffs. No neurons or stored edges are removed.
The viewer loads neither PyArrow nor Brian2. Browser rendering resources remain
separate from Docker's limits.

Preparation streams the Parquet graph in 65,536-row batches, with one Arrow
thread. Its measured peak RSS was 255.3 MiB; numerical validation peaked at
168.8 MiB. Sources are pinned to the reference Git commit, verified against Git
blob hashes, then recorded with SHA-256. Cache files and the numerical report
are checked at runtime. A missing or stale report disables the panel's controls;
there is no fake fallback.

Build the existing `fly-environment:0.1.0` image and prepare the body as described
in [browser-environment.md](browser-environment.md), then prepare the neural cache.
Dependencies and runtime stay in Docker:

```bash
mkdir -p data/neural-reference out/neural-reference

# Tiny build context, with executable CPU/RAM limits on the legacy builder.
tar -cf - Dockerfile.neural-tools requirements.neural-tools.lock |
  DOCKER_BUILDKIT=0 docker build --cpu-period=100000 --cpu-quota=50000 \
    --memory=512m --memory-swap=512m \
    -f Dockerfile.neural-tools -t fly-neural-tools:0.1.0 -

LOCAL_UID="$(id -u)" LOCAL_GID="$(id -g)" \
  docker compose --profile neural-tools run --rm --no-deps neural-tools \
  python scripts/fetch_neural_reference.py
LOCAL_UID="$(id -u)" LOCAL_GID="$(id -g)" \
  docker compose --profile neural-tools run --rm --no-deps neural-tools \
  python scripts/prepare_neural_reference.py
LOCAL_UID="$(id -u)" LOCAL_GID="$(id -g)" \
  docker compose --profile neural-tools run --rm --no-deps neural-tools \
  python scripts/validate_neural_reference.py

docker compose --profile dev up -d --no-build environment-dev
# If already running, reload the new immutable cache:
docker compose --profile dev restart environment-dev
```

The tools image extends the local base with hash-locked binary wheels for
Brian2, PyArrow and their required additions. It is a one-shot utility, not a
second persistent development stack. Its containers have 0.5 CPU / 512 MiB /
32 PIDs, no GPU, a read-only application mount and a 32 MiB temporary filesystem.
Only data/output mounts are writable, as the invoking user's UID/GID.
Downloads are capped at 4 MiB/s. No full spike raster or large state recording
is kept by the live lab.

Development edits use the same checkout and port 8089. The page reloads for
frontend changes; Python changes restart the server in Docker. Backend restart
resets the development simulation and trial. Neural core changes require the
explicit numerical validation step before that new core can run in the lab.
