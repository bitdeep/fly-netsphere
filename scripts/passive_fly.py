"""Attach one flybody anatomy with zero actuator drive and cached visual surfaces."""
import json
from pathlib import Path

from dm_control import mjcf
import numpy as np

from prepare_browser_fly import CACHE, SOURCE, VERSION, digest

FLY_ID = "fly_001"
FLY_START = [-44., -10., -7.41]


def attach_fly(city):
    manifest_path = CACHE / "manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError("Prepare the bounded browser fly cache first; see docs/browser-environment.md")
    manifest = json.loads(manifest_path.read_text())
    for key, path in (
        ("source_xml_sha256", SOURCE),
        ("generator_sha256", Path(__file__).with_name("prepare_browser_fly.py")),
        ("physics_sha256", CACHE/"physics.xml"),
        ("surfaces_sha256", CACHE/"surfaces.bin"),
    ):
        if manifest[key] != digest(path):
            raise RuntimeError(f"Browser fly cache mismatch: {key}; rebuild the cache")
    if manifest["version"] != VERSION:
        raise RuntimeError("Unsupported browser fly cache version")
    anatomy = mjcf.from_path(str(CACHE/"physics.xml"))
    anatomy.model = FLY_ID
    anatomy.find("joint", "free").remove()
    frame = city.mjcf_model.attach(anatomy)
    frame.pos = FLY_START
    free = frame.add("freejoint")
    city.mjcf_model.compiler.boundmass = 0.
    city.mjcf_model.compiler.boundinertia = 0.
    # Walking contact parameters from flybody's Walking task, on the host surface.
    city.mjcf_model.find("geom", "bridge_0").solref = [.001, 1]
    city.mjcf_model.find("geom", "bridge_0").solimp = [.95, .99, .01]
    return manifest, free.full_identifier


def initialize_fly(model, data):
    # Fold the wings using their anatomical spring reference at initialization.
    for joint in range(model.njnt):
        if model.joint(joint).name.startswith(FLY_ID+"/wing_"):
            address = int(model.jnt_qposadr[joint])
            data.qpos[address] = model.qpos_spring[address]


def describe_fly(model, manifest):
    names = list(manifest["inertias"])
    body_ids = np.array([model.body(f"{FLY_ID}/{name}").id for name in names], dtype=np.int32)
    body_index = {name: i for i, name in enumerate(names)}
    surfaces = [
        {**geom, "body": body_index[geom["body"]]} for geom in manifest["visual_geoms"]
    ]
    return {
        "id": FLY_ID, "label": "Fly 001", "source": "flybody",
        "neural_controller": "disconnected", "actuator_drive": "disabled",
        "bodies": names, "meshes": manifest["meshes"], "geoms": surfaces,
        "surface_url": "/assets/fly-surfaces.bin",
        "surface_bytes": manifest["surface_bytes"],
        "surface_sha256": manifest["surfaces_sha256"],
        "visual_triangles": manifest["visual_faces"],
        "mass_mg": manifest["mass_grams"]*1000,
        "max_visual_displacement_um": manifest["max_vertex_displacement_cm"]*10000,
        "focus_body": body_index["thorax"],
    }, body_ids
