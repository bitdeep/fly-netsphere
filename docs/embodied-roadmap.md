# From contact reflexes to embodied behavior

The current browser has a real FlyWire-derived LIF graph, a physical flybody,
direct sensory experiments and [world taste contact](habitat.md). Only the
proboscis motor link is connected. A contact response starts from neural rest
and has a finite clock; it is not an autonomous animal.
Finite apple/water portions and simplified survival reserves now close the
resource-accounting loop. Reserve deficits schedule bounded contact responses;
they are not yet encoded as neural hunger or thirst signals.

## The missing layer

The FlyWire brain alone is not a complete walking or flight controller.
Descending signals need a motor hierarchy that coordinates legs or wings and
responds to the moving body. Selecting a target position must not teleport the
fly or replace its neural response with a scripted trajectory.

Two published approaches inform the next implementation:

| Approach | Useful component | Fidelity boundary |
|---|---|---|
| Connectome decisions with learned motor execution | Identified descending signals select/steer validated body controllers | Learned coordination and chosen decoding gains are approximations |
| Mapped ventral nerve cord circuitry | Connectome-constrained premotor networks and pattern generators | Needs additional data, brain–VNC correspondence and validated body coupling |

[Eon's technical account](https://eon.systems/updates/embodied-brain-emulation)
describes a Shiu-derived brain model with NeuroMechFly, small sets of descending
readouts and learned imitation controllers for motor execution. Its sensor and
motor mappings include chosen engineering gains. It does not use flybody and
does not provide an implemented embodied escape behavior in that demonstration.
That account supports this integration pattern, not a claim that a whole motor
hierarchy emerges from FlyWire alone.

[Pugliese and colleagues' VNC study](https://pmc.ncbi.nlm.nih.gov/articles/PMC13142387/)
and [author code](https://github.com/smpuglie/Pugliese_2026) provide a candidate
for the second route: connectome simulations identify a walking pattern-generator
circuit. A neural rhythm is not yet a validated six-leg controller for this
anatomical body. Specimens, synaptic signs, neuron types, descending connections
and joint/muscle mappings need explicit provenance and checks before integration.

The repository's existing flybody flight policy is a separate learned controller.
The walking checkpoint has not been ported. Neither currently supplies a browser
behavior or a reconstructed neural motor layer. Changing that architecture must
be explicit in the product and its validation.

## Build and validate in stages

1. **World contact — implemented:** bounded taste objects, measured anatomical
   contact, full-graph neural response and one allowlisted motor link. Verify
   absence of response without contact and changed input after source removal.
   **Survival prototype — implemented:** finite source-to-reserve transfers
   during measured feeding contact, physical-time drain, Pause and persistent
   terminal death until an explicit new life. No modeled digestion or foraging.
2. **Persistent neural state:** replace discrete rest-start experiments with a
   bounded session that preserves voltages, delayed spikes and internal state.
   Measure sustained CPU/RAM before increasing activity or sensory coverage.
3. **Locomotor interface:** map identified descending outputs to a validated
   motor layer. Test standing, start/stop, bilateral turning and recovery from
   small perturbations, with zero-input and blocked-output comparisons.
4. **Finding objects:** introduce sourced olfactory receptor mappings and
   antenna-local odor sampling. Compare relocated sources, no-odor controls and
   blocked sensory pathways; object coordinates must not become a hidden pilot.
5. **Touch and escape:** map a measured stimulus to identified sensory pathways.
   Add an embodied response only after its motor circuitry/controller passes
   causal tests. Camera movement and a pointer click are not themselves neurons.
6. **Flight and landing:** validate wing coordination and aerodynamics at their
   required physical/control timestep, then test transitions and landing. The
   existing CPU viewer timestep is not evidence of controlled-flight fidelity.

User commands can eventually request a destination or a behavior through a
clearly labeled experimental input. Object seeking should instead emerge from
the connected sensory path and motor readouts. Both require measured outcomes,
explicit controller provenance and resource ceilings; realistic movement alone
does not establish biological fidelity.
