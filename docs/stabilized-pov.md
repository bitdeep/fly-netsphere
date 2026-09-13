# Recorded flight — stabilized POV

This is an offline flight recording with a learned motor policy and geometric
navigator. Browser food seeking and flight remain unfinished; see the
[delivery plan](embodied-roadmap.md). The measurements below apply to this take.

[**Watch the full 60-second video · 720p · 30 fps**](https://github.com/bitdeep/fly-netsphere/releases/download/pov-stabilization-preview-1/blame_pov_60s-fly_city_stabilized.mp4)

[![Frames from the continuous recording inside the NETSPHERE](https://github.com/bitdeep/fly-netsphere/releases/download/pov-stabilization-preview-1/blame_pov_60s-contact_sheet.png)](https://github.com/bitdeep/fly-netsphere/releases/download/pov-stabilization-preview-1/blame_pov_60s-fly_city_stabilized.mp4)

An anatomically detailed fruit fly flies through a collidable, BLAME!-inspired interior. The official flybody flight policy drives its actuators on CUDA, MuJoCo Warp integrates its body and wing aerodynamics, and a geometric navigator chooses reference commands around obstacles. This recording follows the fly from the position of its physical head.

The previous first-person camera followed instantaneous flight velocity. Sampling that rapidly oscillating signal at video rate produced distracting changes in viewing direction. The new `comfort` mode reduces yaw acceleration by **97.18%** on this take and keeps the horizon level. Both recordings use the same integrated flight states and compiled world.

## What changed

The renderer averages the measured head positions within each exposure, smooths that recorded path with a symmetric Gaussian (σ = 0.25 s), and uses its tangent for yaw. Pitch and roll stay at zero. Only the viewing direction is filtered: the camera remains at the integrated head position in every exposure sample.

This is an offline camera for human viewers. The symmetric filter uses neighboring past and future recorded states; it is not a real-time controller, a model of compound-eye vision, or a claim about what a fly perceives. The navigator uses known geometry, not learned vision or a connectome. The fly's anatomy is hidden from this camera to avoid rendering the inside of its head; its physical body, wings and collision geometry remain active.

The world in this preview is the updated 542-geom interior, including the fly: a deep shaft, stacked galleries, concrete pillars, metal ducts and sagging cables. It is already part of the simulation; this camera change does not modify its geometry or the flight controller. The earlier third-person district remains available in the [v0.1.0 release](https://github.com/bitdeep/fly-netsphere/releases/tag/v0.1.0).

## Measured result

Take: `blame_pov_60s`, seed 0, continuous GPU simulation on an RTX 4090.

| Measure | Result |
|---|---:|
| Simulated time / decoded video duration | 60.000 s / 60.000 s |
| Video | 1280 × 720, 30 fps, 1,800 frames |
| Exposure | 8 physical sub-poses per frame, 1/120 s |
| Physics steps / controller steps | 1,200,000 / 300,000 |
| World contacts / episode resets / solver overflow flags | 0 / 0 / 0 |
| Distance flown | 12.014 m |
| Altitude range | 3.21–7.18 cm |
| Maximum reference tracking error | 0.671 mm |
| Minimum conservative whole-body clearance | 8.44 mm |
| Median anatomical pitch | 35.32° |
| Navigator goals reached / avoidance updates | 16 / 5,532 |
| Maximum checked camera-to-head position error | 0.0000381 mm |
| Yaw acceleration RMS, previous → comfort | 1,624.89 → 45.89 °/s² |
| Pitch acceleration RMS, previous → comfort | 1,469.42 → 0.00 °/s² |

The angular comparison reconstructs the previous camera's exact yaw/pitch recurrence from the saved velocities and measures the new gaze from the recorded OpenGL camera forward vectors. Acceleration is the second difference of unwrapped angles at 30 fps. The percentage describes this recording and this metric; it is not a perceptual comfort study.

`verify_take.py` checks the decoded frame count and duration, physical continuity, saved-state and model hashes, whole-body clearance, head attachment, per-frame world visibility, level camera basis and yaw acceleration RMS below 150 °/s². All 1,800 frames passed. A separate six-second preview also passed before rendering the complete minute.

## Download and verify

The [preview release](https://github.com/bitdeep/fly-netsphere/releases/tag/pov-stabilization-preview-1) includes the original MP4 bytes, the physical states and compiled world, simulation metrics, camera measurements, validation, comparison and a contact sheet. Filenames use the `blame_pov_60s-` prefix; `SHA256SUMS` covers every asset except itself.

| Evidence | Download |
|---|---|
| Simulation and source hashes | [metrics.json](https://github.com/bitdeep/fly-netsphere/releases/download/pov-stabilization-preview-1/blame_pov_60s-metrics.json) |
| Physical and video acceptance | [fly_city_stabilized.validation.json](https://github.com/bitdeep/fly-netsphere/releases/download/pov-stabilization-preview-1/blame_pov_60s-fly_city_stabilized.validation.json) |
| Per-frame camera measurements | [fly_city_stabilized.render.json](https://github.com/bitdeep/fly-netsphere/releases/download/pov-stabilization-preview-1/blame_pov_60s-fly_city_stabilized.render.json) |
| Previous/comfort angular comparison | [stabilization_comparison.json](https://github.com/bitdeep/fly-netsphere/releases/download/pov-stabilization-preview-1/blame_pov_60s-stabilization_comparison.json) |
| Asset integrity | [SHA256SUMS](https://github.com/bitdeep/fly-netsphere/releases/download/pov-stabilization-preview-1/SHA256SUMS) |

Video SHA-256:

```text
b7b88f119f66ceaf782f92d5bcbedbe7b3b22d258d8416f0bd260323e60786f7
```

After the [recording setup](../README.md#watch-it-fly), download the published take and restore its filenames:

```bash
mkdir -p out/pov-preview
base=https://github.com/bitdeep/fly-netsphere/releases/download/pov-stabilization-preview-1
curl -fL "$base/SHA256SUMS" -o out/pov-preview/SHA256SUMS
for asset in fly_city_stabilized.mp4 fly_city_stabilized.render.json \
  fly_city_stabilized.validation.json metrics.json states.npz model.mjb \
  stabilization_comparison.json contact_sheet.png; do
  curl -fL "$base/blame_pov_60s-$asset" -o "out/pov-preview/blame_pov_60s-$asset"
done
(cd out/pov-preview && sha256sum -c SHA256SUMS)
for asset in out/pov-preview/blame_pov_60s-*; do
  mv "$asset" "out/pov-preview/${asset##*/blame_pov_60s-}"
done
docker compose run --rm fly python scripts/verify_take.py out/pov-preview \
  --seconds 60 --video fly_city_stabilized.mp4
```

Re-render those states with the comfort camera, without recomputing physics:

```bash
docker compose run --rm fly python scripts/render_city.py out/pov-preview \
  --view first-person --stabilization comfort --output out/pov-preview/rerender.mp4
docker compose run --rm fly python scripts/verify_take.py out/pov-preview \
  --seconds 60 --video rerender.mp4
```

Use `--stabilization legacy` to compare the previous gaze. Rendering on different drivers or encoders may produce different MP4 bytes; the published SHA identifies the original recording. The state and model hashes identify the physical take independently of the camera.
