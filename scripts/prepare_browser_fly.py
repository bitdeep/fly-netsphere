"""Build a bounded-memory flybody physics/visual cache, one source geom at a time.

Mass properties are computed by MuJoCo from original, full-resolution geoms.
Only the separately rendered, non-colliding surfaces are vertex-clustered.
"""
import argparse
import copy
import gc
import hashlib
import json
from pathlib import Path
import resource
import time
import xml.etree.ElementTree as ET

import mujoco
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "flybody/flybody/fruitfly/assets/fruitfly.xml"
CACHE = ROOT / "out/browser-fly"
VERSION = 1


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b""):
            result.update(chunk)
    return result.hexdigest()


def matrix(quat):
    result = np.empty(9)
    mujoco.mju_quat2Mat(result, quat)
    return result.reshape(3, 3)


def text(values):
    return " ".join(format(float(value), ".17g") for value in np.atleast_1d(values))


def cluster(vertices, faces, target=1000):
    """Bound vertex displacement explicitly; retain distinct material surfaces."""
    if len(faces) <= target:
        return vertices.copy(), faces.copy(), 0.
    cell = .00025  # centimetres: start at 2.5 micrometres.
    low = vertices.min(axis=0)
    while True:
        keys = np.floor((vertices-low)/cell).astype(np.int32)
        _, inverse = np.unique(keys, axis=0, return_inverse=True)
        counts = np.bincount(inverse)
        points = np.column_stack([
            np.bincount(inverse, weights=vertices[:, axis])/counts for axis in range(3)
        ]).astype(np.float32)
        triangles = inverse[faces]
        keep = ((triangles[:, 0] != triangles[:, 1])
                & (triangles[:, 0] != triangles[:, 2])
                & (triangles[:, 1] != triangles[:, 2]))
        triangles = triangles[keep]
        _, unique = np.unique(np.sort(triangles, axis=1), axis=0, return_index=True)
        triangles = triangles[np.sort(unique)]
        error = float(np.linalg.norm(vertices-points[inverse], axis=1).max())
        if len(triangles) <= target or cell >= .0015:
            if not len(triangles) or error > .0027:
                raise ValueError("Visual simplification exceeded its 27 µm displacement bound")
            used, remap = np.unique(triangles, return_inverse=True)
            return points[used], remap.reshape(-1, 3).astype(np.int32), error
        cell *= 1.35


def defaults_by_class(root):
    result = {}

    def visit(node, inherited):
        current = dict(inherited)
        geom = node.find("geom")
        if geom is not None:
            current.update(geom.attrib)
        result[node.get("class", "")] = current
        for child in node.findall("default"):
            visit(child, current)
    visit(root.find("default"), {})
    return result


def prepare(destination=CACHE):
    destination.mkdir(parents=True, exist_ok=True)
    document = ET.parse(SOURCE)
    root = document.getroot()
    meshes = {mesh.get("name"): mesh for mesh in root.findall("asset/mesh")}
    materials = root.findall("asset/material")
    inherited = defaults_by_class(root)
    manifest = {
        "version": VERSION, "generator_sha256": digest(__file__),
        "source_xml_sha256": digest(SOURCE), "source_meshes": {},
        "visual_geoms": [], "inertias": {}, "meshes": [],
        "original_faces": 0, "visual_faces": 0, "max_vertex_displacement_cm": 0.,
    }
    # An incomplete build is never advertised as usable.
    output = destination / "surfaces.bin"
    started = time.monotonic()
    count = 0
    with output.open("wb") as binary:
        def visit(body, childclass="body"):
            nonlocal count
            childclass = body.get("childclass", childclass)
            properties = []
            for geom in list(body.findall("geom")):
                effective = dict(inherited[geom.get("class", childclass)])
                effective.update(geom.attrib)
                massless = (float(effective.get("mass", "-1")) == 0
                            or ("mass" not in effective and float(effective.get("density", "1000")) == 0))
                mesh_name = effective.get("mesh")
                if massless and mesh_name is None:
                    continue
                mini = ET.Element("mujoco")
                compiler = copy.deepcopy(root.find("compiler"))
                compiler.set("meshdir", str(SOURCE.parent))
                mini.append(compiler)
                mini.append(copy.deepcopy(root.find("default")))
                asset = ET.SubElement(mini, "asset")
                for material in materials:
                    asset.append(copy.deepcopy(material))
                if mesh_name:
                    asset.append(copy.deepcopy(meshes[mesh_name]))
                    source_mesh = SOURCE.parent/meshes[mesh_name].get("file")
                    manifest["source_meshes"][source_mesh.name] = digest(source_mesh)
                sample = ET.SubElement(ET.SubElement(mini, "worldbody"), "body",
                                       name="sample", childclass=childclass)
                sample.append(copy.deepcopy(geom))
                # Static sample bodies allow zero-mass cosmetic geoms.
                model = mujoco.MjModel.from_xml_string(ET.tostring(mini, encoding="unicode"))
                if not massless:
                    mass = float(model.body_mass[1])
                    com = model.body_ipos[1].copy()
                    rotation = matrix(model.body_iquat[1])
                    inertia = rotation @ np.diag(model.body_inertia[1]) @ rotation.T
                    properties.append((mass, com, inertia))
                if mesh_name:
                    if int(model.geom_contype[0]) or int(model.geom_conaffinity[0]):
                        raise ValueError("Refusing to simplify collision geometry")
                    # Native compiled mesh coordinates include centering/alignment.
                    vertices, faces, error = cluster(model.mesh_vert, model.mesh_face)
                    vertices = (vertices @ matrix(model.geom_quat[0]).T
                                + model.geom_pos[0]).astype("<f4")
                    faces = faces.astype("<u4")
                    mesh_index = len(manifest["meshes"])
                    descriptor = {
                        "id": mesh_index, "vertex_offset": binary.tell(),
                        "vertex_count": len(vertices),
                    }
                    binary.write(vertices.tobytes())
                    descriptor.update(index_offset=binary.tell(), index_count=int(faces.size))
                    binary.write(faces.tobytes())
                    manifest["meshes"].append(descriptor)
                    material_id = int(model.geom_matid[0])
                    rgba = (model.mat_rgba[material_id] if material_id >= 0 else model.geom_rgba[0])
                    manifest["visual_geoms"].append({
                        "name": geom.get("name"), "body": body.get("name"),
                        "mesh": mesh_index, "rgba": rgba.tolist(),
                        "material": model.material(material_id).name if material_id >= 0 else "body",
                    })
                    manifest["original_faces"] += int(model.nmeshface)
                    manifest["visual_faces"] += len(faces)
                    manifest["max_vertex_displacement_cm"] = max(
                        manifest["max_vertex_displacement_cm"], error)
                    body.remove(geom)
                del model
                gc.collect()
                count += 1
                if count % 15 == 0:
                    print(f"Prepared {count} anatomy geoms; "
                          f"peak RSS {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024:.0f} MiB",
                          flush=True)
            if properties:
                total = sum(p[0] for p in properties)
                com = sum(p[0]*p[1] for p in properties)/total
                inertia = np.zeros((3, 3))
                for mass, center, tensor in properties:
                    delta = center-com
                    inertia += tensor+mass*(np.dot(delta, delta)*np.eye(3)-np.outer(delta, delta))
                # MuJoCo's fullinertia eigensolver uses an absolute tolerance
                # that is too coarse for the fly's ~1e-13 g·cm² foot inertias.
                # Store principal axes explicitly to avoid a second lossy solve.
                diagonal, axes = np.linalg.eigh(inertia)
                if np.linalg.det(axes) < 0:
                    axes[:, 0] *= -1
                quaternion = np.empty(4)
                mujoco.mju_mat2Quat(quaternion, axes.ravel())
                ET.SubElement(body, "inertial", pos=text(com), mass=text(total),
                              quat=text(quaternion), diaginertia=text(diagonal))
                manifest["inertias"][body.get("name")] = {
                    "mass": total, "com": com.tolist(), "tensor": inertia.tolist(),
                }
            for child in body.findall("body"):
                visit(child, childclass)
        for body in root.findall("worldbody/body"):
            visit(body)
    for mesh in list(root.findall("asset/mesh")):
        root.find("asset").remove(mesh)
    physical = destination / "physics.xml"
    ET.indent(document)
    document.write(physical, encoding="unicode")
    # Independent recompilation must reproduce the unsimplified mass properties.
    model = mujoco.MjModel.from_xml_path(str(physical))
    for name, original in manifest["inertias"].items():
        body = model.body(name)
        rotation = matrix(body.iquat)
        np.testing.assert_allclose(body.mass, original["mass"], rtol=1e-10)
        np.testing.assert_allclose(body.ipos, original["com"], rtol=1e-10, atol=1e-12)
        tensor = np.asarray(original["tensor"])
        difference = rotation @ np.diag(body.inertia) @ rotation.T-tensor
        if np.linalg.norm(difference) > 1e-10*np.linalg.norm(tensor):
            raise ValueError(f"Inertia changed for {name}")
    manifest.update(
        mass_grams=float(model.body_mass.sum()), bodies=int(model.nbody)-1,
        joints=int(model.njnt), physics_sha256=digest(physical), surfaces_sha256=digest(output),
        surface_bytes=output.stat().st_size, seconds=time.monotonic()-started,
        peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
    )
    temporary = destination / "manifest.pending.json"
    temporary.write_text(json.dumps(manifest, separators=(",", ":")))
    temporary.replace(destination / "manifest.json")
    print(json.dumps({key: manifest[key] for key in (
        "bodies", "joints", "mass_grams", "original_faces", "visual_faces",
        "surface_bytes", "max_vertex_displacement_cm", "peak_rss_mib", "seconds")}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=CACHE)
    prepare(parser.parse_args().output)
