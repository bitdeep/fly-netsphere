"""Independent acceptance checks on saved state, compiled geometry and video."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

import mujoco
import numpy as np


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("take", type=Path)
    parser.add_argument("--seconds", type=float, default=60)
    parser.add_argument("--video", default="fly_city.mp4")
    args = parser.parse_args()
    take = args.take
    video_path = take/args.video
    meta = json.loads((take/"metrics.json").read_text())
    state = np.load(take/"states.npz")
    check(meta["completed"] and meta["failure"] is None, "Incomplete/failed simulation")
    check(meta["backend"] == "cuda" and meta["device"] == "cuda:0", "GPU physics required")
    check(meta["simulated_seconds"] == args.seconds, "Wrong simulated duration")
    check(meta["control_steps"] == round(args.seconds/.0002), "Wrong control step count")
    check(meta["physics_steps"] == round(args.seconds/.00005), "Wrong physical step count")
    check(meta["episode_resets"] == 0, "Episode reset")
    check(meta["world_contacts"] == 0 and not any(meta["overflow"]), "Collision/solver limit")
    check(meta["maximum_tracking_error_cm"] < .10, "Poor tracking")
    check(meta["distance_travelled_cm"] > args.seconds*10, "Insufficient physical movement")
    check(len(state["qpos"]) == round(args.seconds*30), "Wrong frame count")
    check(np.isfinite(state["qpos"]).all() and np.isfinite(state["qvel"]).all(), "Nonfinite state")
    check(np.all(np.diff(state["time"]) > 0), "Nonmonotonic state timestamps")
    check(np.max(np.abs(state["time"] - np.arange(len(state["time"]))/30)) <= .000101,
          "Video clock differs from physical clock")
    check(np.max(np.abs(np.linalg.norm(state["qpos"][:, 3:7], axis=1)-1)) < .0001,
          "Invalid physical orientation")
    check(hashlib.sha256((take/"states.npz").read_bytes()).hexdigest() == meta["states_sha256"],
          "State artifact changed")
    check(hashlib.sha256((take/"model.mjb").read_bytes()).hexdigest() == meta["model_sha256"],
          "Compiled physical world changed")
    ns = meta["shutter_samples"]
    check(len(state["shutter_qpos"]) == len(state["qpos"])*ns, "Incomplete exposure samples")
    check(np.array_equal(state["shutter_qpos"][::ns], state["qpos"]), "Exposure/frame state mismatch")
    check(np.isfinite(state["shutter_qpos"]).all(), "Nonfinite exposure state")
    model = mujoco.MjModel.from_binary_path(str(take/"model.mjb"))
    data = mujoco.MjData(model)
    fly_geoms = model.geom_bodyid > 0
    head = model.body("walker/head").id
    abdomen = model.body("walker/abdomen_6").id
    anatomical_pitch = []
    max_radius = 0.
    for pose in state["shutter_qpos"]:
        data.qpos[:] = pose
        mujoco.mj_kinematics(model, data)
        axis = data.xpos[head]-data.xpos[abdomen]
        anatomical_pitch.append(float(np.rad2deg(np.arctan2(axis[2], np.linalg.norm(axis[:2])))))
        radius = np.max(np.linalg.norm(data.geom_xpos[fly_geoms]-pose[:3], axis=1)
                        + model.geom_rbound[fly_geoms])
        max_radius = max(max_radius, float(radius))
    conservative_margin = meta["minimum_root_surface_clearance_cm"] - max_radius
    check(conservative_margin > .10, "Insufficient anatomical clearance margin")
    pitch_percentiles = np.percentile(anatomical_pitch, [0, 50, 95, 100]).tolist()
    if meta.get("body_pitch_command_deg", 47.5) <= 30:
        check(pitch_percentiles[1] < 40 and pitch_percentiles[2] < 45,
              "Persistent upright posture despite the cruise command")
    probe = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate,nb_read_frames,duration",
        "-of", "json", str(video_path)]))
    video = probe["streams"][0]
    check(video["r_frame_rate"] == "30/1", "Unexpected video rate")
    check(int(video["nb_read_frames"]) == len(state["qpos"]), "Video missing frames")
    check(abs(float(video["duration"])-args.seconds) < .0001, "Wrong video duration")
    check((video["width"], video["height"]) == (1280, 720), "Wrong video resolution")
    render = json.loads(video_path.with_suffix(".render.json").read_text())
    first_person = render.get("view") == "first-person"
    if first_person:
        camera_positions = np.asarray(render["camera_positions_cm"])
        check(camera_positions.shape == (len(state["qpos"]), 3), "Missing first-person poses")
        head_errors = []
        for camera_pos, pose in zip(camera_positions, state["shutter_qpos"][ns-1::ns]):
            data.qpos[:] = pose
            mujoco.mj_kinematics(model, data)
            head_errors.append(np.linalg.norm(camera_pos-data.xpos[head]))
        check(max(head_errors) < .001, "Camera detached from physical head")
        check(len(render["visible_world_pixels"]) == len(state["qpos"]), "Incomplete POV visibility check")
        check(render["minimum_visible_world_pixels"] >= 1280*720*.25, "POV world not readable")
        check(render["minimum_mean_luminance"] >= 8, "POV too dark")
    else:
        check(len(render["visible_fly_pixels"]) == len(state["qpos"]), "Incomplete visibility check")
        check(render["minimum_visible_fly_pixels"] >= 600, "Fly not visible throughout video")
    report = dict(passed=True, simulated_seconds=args.seconds, video=video,
                  physical_steps=meta["physics_steps"], world_contacts=0,
                  maximum_anatomy_bounding_radius_cm=max_radius,
                  conservative_surface_margin_cm=conservative_margin,
                  anatomical_pitch_deg=dict(zip(("minimum", "median", "p95", "maximum"), pitch_percentiles)),
                  minimum_visible_fly_pixels=render["minimum_visible_fly_pixels"],
                  exposure_samples=len(state["shutter_qpos"]),
                  view=render.get("view", "third-person"),
                  video_sha256=hashlib.sha256(video_path.read_bytes()).hexdigest())
    if first_person:
        report.update(maximum_head_camera_error_cm=float(max(head_errors)),
                      minimum_visible_world_pixels=render["minimum_visible_world_pixels"])
    report_path = take/"validation.json" if args.video == "fly_city.mp4" else video_path.with_suffix(".validation.json")
    report_path.write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
