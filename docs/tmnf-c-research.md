# TMNF-C: relevance to the browser fly

TMNF-C provides useful methods for checking sensory pathways, testing visual
responses and exploring reward-dependent plasticity. The immediate opportunity
is its pathway audit: adapt the analysis to our FlyWire 630 candidates while
working on the [continuous sensory gate](embodied-roadmap.md#delivery-order).
Its racing controller is not ready to supply our fly's seeking behavior.

Reviewed on 2026-09-13 at commit
[`eb6be045970e1f490aa02b92b2b39c560782503a`](https://github.com/adonis-singh/TMNF-C/tree/eb6be045970e1f490aa02b92b2b39c560782503a).
This assessment comes from reading pinned source files and documentation.
Upstream code, training, benchmarks and videos were not reproduced locally;
no controller, dependency or neural dataset was integrated.

## What the project actually implements

The main project is a C11 TrackMania Forever simulator with CPU/CUDA execution
and conventional reinforcement-learning policies. That vehicle simulator and
its race results are separate from the experimental fly circuits under
`python/tmnf_fly`. TrackMania physics does not supply insect joints, muscles,
flight or landing. [Main project description](https://github.com/adonis-singh/TMNF-C/blob/eb6be045970e1f490aa02b92b2b39c560782503a/README.md).

The fly experiment has two distinct control paths:

| Path | Inputs and computation | Output and limitation |
|---|---|---|
| Mushroom-body learner | Vehicle state and route lookahead, plus candidate actions, enter a selected MaleCNS mushroom-body circuit | Learns values for discrete steering/throttle/brake actions; does not learn from the rendered eyes |
| Visual reflex driver | Ray-cast luminance → pretrained flyvis optic lobe → MaleCNS rate network | Engineered population readouts control the car; this is separate from the learner |

The upstream report describes successful training episodes but weak frozen
policies. For the five-minute A04 run, it lists 191 finishes in 75,108 training
episodes, then **0/2,048 finishes with frozen greedy action selection** and
5/2,000 with 2% random exploration. The visual reflex reportedly stalls after
150–320 m on the tested tracks. These are author-reported results, not our
measurements. They do not establish reliable autonomous navigation.
[Experiment description and results](https://github.com/adonis-singh/TMNF-C/blob/eb6be045970e1f490aa02b92b2b39c560782503a/python/tmnf_fly/README.md).

## Useful parts and their boundaries

### Pathway analysis: useful for the current gate

[`pathway_audit.py`](https://github.com/adonis-singh/TMNF-C/blob/eb6be045970e1f490aa02b92b2b39c560782503a/python/tmnf_fly/pathway_audit.py)
compares synapse counts, neurotransmitter-derived signs and same-side versus
opposite-side connections. It examines visual paths involving LC4/LPLC2,
DNp01, T4/T5, HS and descending candidates. This is a useful way to inspect
whether a proposed readout has anatomical support before interpreting a trace.
It is descriptive analysis, not a functional intervention test.

Apply that method to our existing sensory and descending candidates using
[the versioned ID inventory](connectome-data.md). Preserve all stored v630
connections, record ambiguous cell names and retain the individual bilateral
IDs. MaleCNS body IDs and column assignments cannot be substituted for FAFB
root IDs. Anatomical support must still be followed by repeated-cue and
blocked-path measurements.

### Learning: a bounded model experiment

[`mushroom_body.py`](https://github.com/adonis-singh/TMNF-C/blob/eb6be045970e1f490aa02b92b2b39c560782503a/python/tmnf_fly/mushroom_body.py)
extracts projection-neuron, Kenyon-cell, mushroom-body-output-neuron and
dopaminergic-neuron populations from MaleCNS. It uses normalized anatomical
matrices, fixed random feature projections and a top-200 Kenyon-cell selection.
The winner selection is an algorithmic approximation, rather than simulated
APL inhibition. A reward-prediction error modifies KC→MBON weights within
calibrated bounds, preserving absent connections; approach/avoid output gains
are assigned by the implementation. This is a selected circuit with engineered
plasticity, not a continuously spiking full brain.

[`train_mb.py`](https://github.com/adonis-singh/TMNF-C/blob/eb6be045970e1f490aa02b92b2b39c560782503a/python/tmnf_fly/train_mb.py)
evaluates candidate actions, uses exploration and feeds back a scaled, clipped
race reward. Its logs include KC-code overlap, weight saturation, episode
failures and action values. These diagnostics could help distinguish learning
from indiscriminate activation in our separate model experiments.

For our fly, the feedback candidate remains measured replenishment of the
reserve in deficit. Route lookahead and race progress cannot become food
coordinates or hidden target directions. First pass repeated sensory responses;
then specify plastic synapses, feedback timing and bounds, and compare paired
feedback with learning-off and unpaired controls. Report all trials and
performance on unseen placements, including evaluation with frozen weights.
An isolated learning assay cannot close the full-graph foraging gate.

### Vision: retain for later investigation

[`eye.py`](https://github.com/adonis-singh/TMNF-C/blob/eb6be045970e1f490aa02b92b2b39c560782503a/python/tmnf_fly/eye.py)
constructs viewing directions from a micro-CT right-eye map, mirrors them for
the left eye and registers the hexagonal lattice to MaleCNS columns.
[`retina.py`](https://github.com/adonis-singh/TMNF-C/blob/eb6be045970e1f490aa02b92b2b39c560782503a/python/tmnf_fly/retina.py)
uses 19 weighted rays per ommatidium: 852 × 2 × 19 = 32,376 rays per frame.
That is a useful explicit sensor model, with symmetry and rendering assumptions
that would need documenting and measuring on our body.

[`flyvis_periphery.py`](https://github.com/adonis-singh/TMNF-C/blob/eb6be045970e1f490aa02b92b2b39c560782503a/python/tmnf_fly/flyvis_periphery.py)
maps a pretrained optic-flow model onto the eye/brain columns. The learned
visual model comes from a different connectome source; the mapping is an
engineered cross-dataset interface. It also calls private flyvis APIs, so reuse
requires a pinned compatibility check.

[`flyvis_validate.py`](https://github.com/adonis-singh/TMNF-C/blob/eb6be045970e1f490aa02b92b2b39c560782503a/python/tmnf_fly/flyvis_validate.py)
provides useful stimulus fixtures: drifting gratings, ON/OFF bars, looming,
dark flashes and gray baselines. It resets before individual stimuli. Our
continuous-state acceptance additionally needs a second cue, side reversal and
removal without resets. Learned vision remains deferred in the delivery plan.

### Control and replay: inspect the actual source of motion

In [`drive.py`](https://github.com/adonis-singh/TMNF-C/blob/eb6be045970e1f490aa02b92b2b39c560782503a/python/tmnf_fly/drive.py),
DNp01 activity gates braking, while steering uses LC4/LPLC2 and HS asymmetries
directly. DNa02 and DNp15 are logged but do not supply that steering command.
Gains, running averages and a vehicle-speed guard are engineered. The
`--replay-inputs` mode instead applies a recorded command schedule while vision
and neural activity run as observers.

[`mb_replay.py`](https://github.com/adonis-singh/TMNF-C/blob/eb6be045970e1f490aa02b92b2b39c560782503a/python/tmnf_fly/mb_replay.py)
can also force recorded decisions. It verifies the resulting finish time
against a fresh single-car environment and records input hashes. That is useful
replay discipline; it proves reproduction of those decisions, not that the
displayed circuit independently selected them. Our evidence must identify the
causal command source and show that blocking neural motor commands removes
commanded movement.

## Compatibility, data and cost

The visual driver changes both graph semantics and neuron dynamics.
[`brain_graph.py`](https://github.com/adonis-singh/TMNF-C/blob/eb6be045970e1f490aa02b92b2b39c560782503a/python/tmnf_fly/brain_graph.py)
keeps traced MaleCNS cells and connections with at least two synapses by default,
then applies signed `log1p` weights and normalizes postsynaptic input.
[`brain_model.py`](https://github.com/adonis-singh/TMNF-C/blob/eb6be045970e1f490aa02b92b2b39c560782503a/python/tmnf_fly/brain_model.py)
implements a float32 ReLU rate model with 1 ms Euler steps and externally
clamped visual populations. It cannot replace our float64, 0.1 ms FlyWire 630
LIF core as a numerically equivalent optimization. Its adaptation settings
likewise do not establish a remedy for our failed second-cue response.

The training entry point uses CUDA and batches many cars. Compatibility and
performance within our one-fly CPU budget are unmeasured. Any later prototype
needs isolated Docker dependencies and a measured single-animal workload before
integration; retain the current resource limits and flybody motor boundary.

The [data fetcher](https://github.com/adonis-singh/TMNF-C/blob/eb6be045970e1f490aa02b92b2b39c560782503a/python/tmnf_fly/fetch_data.py)
pins file sizes and SHA-256 digests. Its MaleCNS v1.0 annotation file is already
in our offline catalog: 14,483,314 bytes, SHA-256
`2177e246113e4cfbf1e7772ec37c6da1955ff22e8063d0b1f833101f99a9a3b2`.
Reuse that verified file for analysis. Its roughly 1.05 GB connectivity table
and visual-model assets were not fetched for this review.

Original code has an [MIT license](https://github.com/adonis-singh/TMNF-C/blob/eb6be045970e1f490aa02b92b2b39c560782503a/LICENSE).
[Third-party notices](https://github.com/adonis-singh/TMNF-C/blob/eb6be045970e1f490aa02b92b2b39c560782503a/THIRD_PARTY_NOTICES.md)
exclude game assets from that grant; datasets and dependencies retain their own
terms. Selected source files are preserved locally as inert text under
`data/research/tmnf-c-eb6be045/`, with URLs, Git blob IDs and SHA-256 digests in
`sources.json`. This is an ignored research cache, not an installed runtime.
