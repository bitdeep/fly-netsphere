"""Render recorded physical states inside the same 3D collision world using EGL."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

import mujoco
import numpy as np
from PIL import Image
from dm_control.mujoco.engine import MovableCamera
from dm_control import mujoco as dm_mujoco

from city_world import City
from city_navigation import Navigator
from flight_runtime import make_environment


def comfort_headings(physics, states, head_id, ns, sigma_seconds=.25):
    """Offline gaze from measured displacement; never feeds the physical model.

    Instantaneous flapping velocity aliases badly at video rate. Average each
    exposure's actual head positions, smooth that path symmetrically, and use
    its tangent for yaw. Only orientation is filtered; the eye stays at the
    integrated head position in every exposure sample.
    """
    poses = states["shutter_qpos"] if "shutter_qpos" in states else states["qpos"]
    samples = []
    for pose in poses:
        physics.data.qpos[:] = pose
        mujoco.mj_kinematics(physics.model.ptr, physics.data.ptr)
        samples.append(physics.data.xpos[head_id].copy())
    positions = np.asarray(samples).reshape(-1, ns, 3).mean(axis=1)
    if len(positions) < 3:
        raise ValueError("Comfort camera needs at least three recorded frames")
    dt = 1/30
    radius = int(np.ceil(4*sigma_seconds/dt))
    offsets = np.arange(-radius, radius+1)
    kernel = np.exp(-.5*(offsets*dt/sigma_seconds)**2)
    kernel /= kernel.sum()
    # Linear extension preserves constant flight speed at the two endpoints.
    padded = np.concatenate([
        positions[0]+np.arange(-radius, 0)[:, None]*(positions[1]-positions[0]),
        positions,
        positions[-1]+np.arange(1, radius+1)[:, None]*(positions[-1]-positions[-2])])
    smooth = np.stack([np.convolve(padded[:, j], kernel, "valid")
                       for j in range(3)], axis=-1)
    velocity = np.gradient(smooth, dt, axis=0)
    return np.unwrap(np.arctan2(velocity[:, 1], velocity[:, 0]))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("take", type=Path)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--distance", type=float, default=2.3)
    parser.add_argument("--azimuth-offset", type=float, default=85,
                        help="Three-quarter side view makes body attitude readable")
    parser.add_argument("--elevation", type=float, default=2)
    parser.add_argument("--view", choices=["third-person", "first-person"], default="third-person")
    parser.add_argument("--fov", type=float, default=65,
                        help="Vertical field of view for the head-mounted first-person camera")
    parser.add_argument("--stabilization", choices=["comfort", "legacy"], default="comfort",
                        help="First-person gaze: level horizon and averaged displacement, or original velocity following")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    metrics = json.loads((args.take/"metrics.json").read_text())
    states = np.load(args.take/"states.npz")
    out = args.output or args.take/"fly_city.mp4"
    if out.exists():
        raise FileExistsError(out)
    env = None
    if (args.take/"model.mjb").exists():
        physics = dm_mujoco.Physics.from_binary_path(str(args.take/"model.mjb"))
    else:
        city = City(obstacle_shift=metrics["obstacle_shift"])
        env = make_environment(Navigator(city), 1, city)
        env.reset()
        physics = env.physics
    first_person = args.view == "first-person"
    head_id = physics.model.name2id("walker/head", "body")
    if first_person:
        physics.model.vis.global_.fovy = args.fov
    ns = metrics.get("shutter_samples", 1)
    comfort = first_person and args.stabilization == "comfort"
    headings = comfort_headings(physics, states, head_id, ns) if comfort else None
    cam = MovableCamera(physics, height=args.height, width=args.width)
    cam.scene.flags[mujoco.mjtRndFlag.mjRND_FOG] = True
    cam.option.flags[mujoco.mjtVisFlag.mjVIS_CONTACTPOINT] = False
    cam.option.flags[mujoco.mjtVisFlag.mjVIS_CONVEXHULL] = False
    if first_person:
        # Hide the inside of our own head only in the observer's render buffer.
        # Anatomical collision, saved poses and the simulation model are untouched.
        cam.option.geomgroup[1:] = 0
    # Object IDs are categorical: MSAA blends their RGB encoding at edges
    # (e.g. ID 256 becomes 320). Use a separate, unfiltered visibility buffer,
    # preserving the original world's four-sample antialiasing in the video.
    visibility_physics = physics.copy(share_model=False)
    visibility_physics.model.vis.quality.offsamples = 0
    visibility_cam = MovableCamera(visibility_physics, height=args.height, width=args.width)
    visibility_cam.scene.flags[mujoco.mjtRndFlag.mjRND_FOG] = False
    visibility_cam.option.flags[:] = cam.option.flags
    visibility_cam.option.geomgroup[:] = cam.option.geomgroup
    encoder = subprocess.Popen([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
        "-f", "rawvideo", "-pixel_format", "rgb24", "-video_size", f"{args.width}x{args.height}",
        "-framerate", "30", "-i", "-", "-an", "-c:v", "libx264",
        "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", str(out)], stdin=subprocess.PIPE)
    yaw = 0.
    gaze_pitch = 0.
    camera_distance = args.distance
    ray_group = np.array([1, 0, 0, 0, 0, 0], dtype=np.uint8)
    hit_geom = np.array([-1], dtype=np.int32)
    visible_pixels = []
    world_pixels, camera_positions, head_positions, luminance = [], [], [], []
    camera_forwards, camera_ups = [], []
    try:
        for i, (t, qpos, qvel) in enumerate(zip(states["time"], states["qpos"], states["qvel"])):
            if comfort:
                yaw = headings[i]
                gaze_pitch = 0.
            else:
                target_yaw = np.arctan2(qvel[1], qvel[0])
                yaw += (.5 if first_person else .13)*np.arctan2(np.sin(target_yaw-yaw), np.cos(target_yaw-yaw))
                target_pitch = np.arctan2(qvel[2], np.linalg.norm(qvel[:2]))
                gaze_pitch += .25*(target_pitch-gaze_pitch)
            azimuth = np.rad2deg(yaw)+args.azimuth_offset
            az, el = np.deg2rad([azimuth, args.elevation])
            toward_camera = -np.array([np.cos(az)*np.cos(el), np.sin(az)*np.cos(el), np.sin(el)])
            physics.data.qpos[:] = qpos
            mujoco.mj_kinematics(physics.model.ptr, physics.data.ptr)
            obstruction = mujoco.mj_ray(physics.model.ptr, physics.data.ptr, qpos[:3],
                                        toward_camera, ray_group, 1, -1, hit_geom)
            safe_distance = args.distance if obstruction < 0 else min(args.distance, obstruction*.82)
            if not first_person and safe_distance < .5:
                raise RuntimeError(f"Camera corridor too narrow at frame {i}: {safe_distance}")
            camera_distance = min(camera_distance+.12*(safe_distance-camera_distance), safe_distance)
            subframes = states["shutter_qpos"][i*ns:(i+1)*ns] if "shutter_qpos" in states else [qpos]
            if not len(subframes):
                break
            accumulated = np.zeros((args.height, args.width, 3), dtype=np.float32)
            for sample in subframes:
                physics.data.qpos[:] = sample
                physics.data.qvel[:] = qvel
                physics.data.time = t
                mujoco.mj_forward(physics.model.ptr, physics.data.ptr)
                if first_person:
                    # Real head position with a human viewing direction.
                    # Gaze stabilization never changes the integrated anatomy.
                    forward = np.array([np.cos(yaw)*np.cos(gaze_pitch),
                                        np.sin(yaw)*np.cos(gaze_pitch), np.sin(gaze_pitch)])
                    eye = physics.data.xpos[head_id].copy()
                    cam.set_pose(lookat=eye+forward, distance=1,
                                 azimuth=np.rad2deg(yaw), elevation=np.rad2deg(gaze_pitch))
                else:
                    cam.set_pose(lookat=sample[:3], distance=camera_distance,
                                 azimuth=azimuth, elevation=args.elevation)
                accumulated += cam.render().astype(np.float32)
            image = np.rint(accumulated/len(subframes)).astype(np.uint8)
            encoder.stdin.write(image.tobytes())
            if first_person:
                camera_positions.append(np.mean([c.pos for c in cam.scene.camera], axis=0).tolist())
                camera_forwards.append(np.mean([c.forward for c in cam.scene.camera], axis=0).tolist())
                camera_ups.append(np.mean([c.up for c in cam.scene.camera], axis=0).tolist())
                head_positions.append(eye.tolist())
                luminance.append(float(image.mean()))
            visibility_physics.data.qpos[:] = subframes[-1]
            visibility_physics.data.qvel[:] = qvel
            visibility_physics.data.time = t
            mujoco.mj_forward(visibility_physics.model.ptr, visibility_physics.data.ptr)
            if first_person:
                visibility_cam.set_pose(lookat=eye+forward, distance=1,
                                        azimuth=np.rad2deg(yaw), elevation=np.rad2deg(gaze_pitch))
            else:
                visibility_cam.set_pose(lookat=subframes[-1][:3], distance=camera_distance,
                                        azimuth=azimuth, elevation=args.elevation)
            segmentation = visibility_cam.render(segmentation=True)
            geom_ids = segmentation[..., 0]
            is_geom = segmentation[..., 1] == int(mujoco.mjtObj.mjOBJ_GEOM)
            ids = np.clip(geom_ids, 0, physics.model.ngeom-1)
            fly_mask = is_geom & (geom_ids >= 0) & (physics.model.geom_bodyid[ids] > 0)
            visible_pixels.append(int(fly_mask.sum()))
            world_pixels.append(int((is_geom & (geom_ids >= 0) & (physics.model.geom_bodyid[ids] == 0)).sum()))
            if i in (0, len(states["time"])//4, len(states["time"])//2, len(states["time"])-1):
                prefix = f"{out.stem}_" if args.output else ""
                Image.fromarray(image).save(out.parent/f"{prefix}frame_{i:04d}.png")
            if i % 300 == 0:
                print(f"render {i}/{len(states['time'])} time={t:.3f}s", flush=True)
    finally:
        encoder.stdin.close()
        code = encoder.wait()
        visibility_physics.free()
        if env:
            env.close()
        else:
            physics.free()
    if code:
        raise RuntimeError(f"ffmpeg exited {code}")
    qa = dict(renderer="MuJoCo EGL", view=args.view, camera_distance_cm=args.distance,
              azimuth_offset_deg=args.azimuth_offset, elevation_deg=args.elevation,
              camera_collision_avoidance="static-world ray; shorten before an obstruction",
              visibility_method="unfiltered object-ID render of the same geometry and camera",
              minimum_visible_fly_pixels=min(visible_pixels),
              visible_fly_pixels=visible_pixels,
              minimum_visible_world_pixels=min(world_pixels), visible_world_pixels=world_pixels,
              renderer_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    if first_person:
        for key in ("camera_distance_cm", "azimuth_offset_deg", "elevation_deg",
                    "camera_collision_avoidance"):
            qa.pop(key)
        qa.update(camera_position_source="integrated walker/head body position",
                  stabilization=args.stabilization,
                  gaze_source=("tangent of Gaussian-smoothed measured head displacement; fixed level horizon"
                               if comfort else "smoothed instantaneous velocity, horizon stabilized"),
                  gaze_sigma_seconds=.25 if comfort else None,
                  gaze_offline_symmetric=comfort,
                  anatomy_hidden_in_observer=True, vertical_fov_deg=args.fov,
                  camera_positions_cm=camera_positions, head_positions_cm=head_positions,
                  camera_forwards=camera_forwards, camera_ups=camera_ups,
                  source_states_sha256=metrics["states_sha256"],
                  source_model_sha256=metrics["model_sha256"],
                  minimum_mean_luminance=min(luminance),
                  maximum_head_camera_error_cm=float(np.linalg.norm(
                      np.asarray(camera_positions)-head_positions, axis=1).max()))
    out.with_suffix(".render.json").write_text(json.dumps(qa, indent=2)+"\n")
    if first_person:
        if qa["maximum_head_camera_error_cm"] > .001 or min(world_pixels) < args.width*args.height*.25:
            raise RuntimeError("First-person camera detached or world view obstructed")
        if min(luminance) < 8:
            raise RuntimeError("First-person view too dark to read")
    elif min(visible_pixels) < 600:
        raise RuntimeError("Fly occluded or too small in one or more frames; review camera")
    print(out, flush=True)


if __name__ == "__main__":
    main()
