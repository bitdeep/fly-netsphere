# Sensory feasibility: adaptation recovers rest, but does not steer

The experimental adaptive model stopped persistent activity in six odor trials,
but produced no reliable left/right command. It is **not connected to the browser
body**. Food seeking and flight remain incomplete. These measurements, made on
2026-09-13, explain the failed first gate in the [delivery plan](embodied-roadmap.md).

## What was tested

Every run retained FlyWire 630's 127,400 neurons, all 14,687,178 stored directed
connections, signed weights and delays. Neural state persisted within each run.
The original `neural_reference.py`, browser assays and physical body were not
modified. No source coordinates or scripted direction entered the model.

The odor probe stimulated the annotated ORN_DM1 and ORN_VA2 cohorts: 69 left and
66 right sensory neurons. It tested ten candidate descending readouts, keeping
the annotation columns distinct: `cell_type` DNa01, DNae003 and DNpe060, and
`hemibrain_type` DNa02 and DNp09, each bilateral. These labels are not
interchangeable. The scripts record every selected root ID.

Annotations come from the
[v1.1.0 source at commit df6bb13](https://github.com/flyconnectome/flywire_annotations/tree/df6bb136f5b3d91c3992df4e8de2642329e2a384/supplemental_files),
whose [schema](https://github.com/flyconnectome/flywire_annotations/blob/df6bb136f5b3d91c3992df4e8de2642329e2a384/supplemental_files/Supplemental_files_columns.md)
identifies FlyWire 630 root IDs. The 21,714,061-byte TSV is SHA-256 checked:
`55c99c61eecf8db6cc36f1a684b35e4c4208afbab02197d753ccc8dc2a6e2e76`.
The graph remains the [published reference](neural-reference.md), not a new release.

The protocol was 200 ms left input, 200 ms right input and 400 ms without input,
using the reference's direct Bernoulli encoder and seed `20260913`. Results use
100 ms bins. Each case had limits of 20 CPU seconds, 60 wall seconds and 200,000
spikes, checked every 25 steps. A stopped run is incomplete, not a pass.

## Why the original model failed this probe

At 10, 50 and 150 Hz per sensory neuron, the original model reached the spike
ceiling after 480, 455 and 442.5 ms respectively. Candidate readouts did not
provide a dependable directional reversal. Zero input produced no spikes;
blocking sensory outgoing weights produced no downstream spikes.

An independent comparison used a shorter protocol: 50 ms left at 10 Hz,
50 ms right, then 200 ms without input. NumPy and Brian2 matched all **118,085
spike IDs and ticks**. After input ended, the final four 50 ms bins contained
22,809, 22,493, 22,515 and 22,443 spikes. This reproduces persistent activity in
our v630 model; it is not a conclusion inferred from another project's v783.

A separate taste probe used the notebook's literal `neu_sugar_left` (10) and
`neu_sugar` (21) IDs, extracted without executing notebook cells. At 150 Hz it
produced 3,786 spikes, including MN9 counts of 23/18, then returned to silence.
The candidate directional readouts remained almost silent. A feeding response
does not establish steering, and distal sugar input is not a validated odor model.

## Adaptive model and results

`scripts/adaptive_neural.py` adds a decaying threshold offset to non-input neurons:

```text
da/dt = -a / tau
spike when v > -45 mV + a
after a spike: a += jump
```

Adaptation decays during refractoriness; the externally encoded sensory neurons
retain zero offset. All other reference update rules remain the same. This is
an engineering hypothesis, not fitted fruit-fly physiology.
[Adaptive spiking-network research](https://arxiv.org/abs/1803.09574) motivates the
mechanism, but its trained-network results do not establish that adaptation alone
provides useful behavior on this connectome.

Four settings were fixed before the screen, each at 50 Hz:

| Jump / decay | Total spikes in 800 ms | Downstream spikes in final 100 ms | Recovered | Directional pair |
|---|---:|---:|---|---|
| 1 mV / 100 ms | 142,617 | 16,507 | No | None |
| 5 mV / 100 ms | 43,394 | 4,680 | No | None |
| 5 mV / 500 ms | 9,918 | 0 | Yes | None |
| 20 mV / 200 ms | 3,688 | 0 | Yes | None; all candidate readouts silent |

The recovery criterion was a final downstream count no greater than the larger
of five spikes or 5% of the peak driven bin. Direction required at least three
spikes across a bilateral pair and an ipsilateral count advantage in the last
100 ms of **each** cue. These are screening criteria, not biological validation.

The 5 mV / 500 ms variant was repeated with seeds `20260913–20260915`, each in
both left→right and right→left order. All six recovered; **none passed direction**.
For the first seed in left→right order, downstream counts were:

| Input | Left | Left | Right | Right | Off | Off | Off | Off |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Downstream spikes / 100 ms | 7,903 | 683 | 7 | 8 | 0 | 0 | 0 | 0 |

The same pattern appeared in reverse order: most propagation belonged to the
initial transient. The second cue barely propagated, and no candidate descending
neuron fired during it in any repeat. The model suppresses the response needed
for continued steering. Zero-input and blocked-path controls passed.

The final six repeats took 3.57–4.09 CPU seconds each for 0.8 seconds of neural time,
with a 164.9 MiB process peak across the confirmation suite. Even before physics
or duty budgeting, that is only about 0.20–0.22× simulated/CPU time.
The current implementation does not meet the combined 0.5× delivery target.

## Numerical checks and reproduction

Six small fixtures use native Brian2 neurons and synapses, exercising inhibition,
delay, refractory boundaries, recovery and accumulating adaptation. Spike IDs
and ticks matched exactly; state errors stayed below 1e-8 mV. Chunked and dense
execution agreed, and zero adaptation reproduced the original model exactly.

The full-population adaptive comparison also matched all **8,427 spike IDs and
ticks**, with maximum state errors below 8e-13 mV. It used the same 300 ms protocol
as the original comparison. Brian2 integrates every neuron; an independent
vectorized CSR callback delivers every delayed connection. This avoids allocating
14.7 million Brian2 `Synapses` objects and is **not** a test of that synapse engine.
The full-population comparisons peaked below 235 MiB.

Use the existing [neural tooling container](neural-reference.md#resources-and-preparation)
and prepared graph. Run these one at a time; none starts or changes the live animal:

```bash
docker compose --profile neural-tools run --rm --no-deps neural-tools \
  python scripts/foraging_feasibility.py --fetch-annotations \
  --output /out/foraging-odor-probe.json
# Expected exit 2: the original odor runs hit their spike ceiling.

docker compose --profile neural-tools run --rm --no-deps neural-tools \
  python scripts/foraging_feasibility.py --family taste \
  --output /out/foraging-taste-probe.json

docker compose --profile neural-tools run --rm --no-deps neural-tools \
  python scripts/validate_adaptive_neural.py \
  --output /out/adaptive-numerical-validation.json

docker compose --profile neural-tools run --rm --no-deps neural-tools \
  python scripts/probe_adaptive_senses.py --output /out/adaptive-senses-screen.json

docker compose --profile neural-tools run --rm --no-deps neural-tools \
  python scripts/probe_adaptive_senses.py --variant 2 --confirm \
  --output /out/adaptive-senses-confirmation.json

docker compose --profile neural-tools run --rm --no-deps neural-tools \
  python scripts/compare_foraging_reference.py --output /out/foraging-brian-comparison.json

docker compose --profile neural-tools run --rm --no-deps neural-tools \
  python scripts/compare_foraging_reference.py --adaptive \
  --output /out/adaptive-full-population-comparison.json
```

Reports in `out/neural-reference/` record source/code hashes, IDs, bins, limits
and runtime. A completed probe can document a rejected candidate:
`confirmation_passed` is **false** here even though measurements completed.
These data are local; CI checks syntax and existing lightweight regressions,
not the full neural experiments.

Gate 1 remains failed. The next neural investigation must resolve the sensory
path and bilateral readout mapping, and preserve a response to a second cue.
This adaptive variant is not promoted to the motor controller.
