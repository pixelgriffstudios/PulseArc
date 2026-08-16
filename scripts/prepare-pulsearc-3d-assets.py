#!/usr/bin/env python3
"""Convert downloaded author-approved 3D packs into PulseArc's tiny OBJ subset.

This is an offline build tool.  PulseArc never needs Assimp at runtime: models
are triangulated, normalized, and written as plain OBJ/MTL files, then compiled
into OpenGL display lists once when the 3D Plaza starts.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Iterable

import assimp_py  # type: ignore[import-not-found]
import numpy as np


FLAGS = (
    assimp_py.Process_Triangulate
    | assimp_py.Process_PreTransformVertices
    | assimp_py.Process_JoinIdenticalVertices
    | assimp_py.Process_ImproveCacheLocality
)


def safe_name(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", value.strip()).strip("-").lower() or "material"


def material_color(name: str, source: Iterable[float]) -> tuple[float, float, float]:
    """Make texture-heavy models readable on the fixed-function fallback."""
    lowered = name.lower()
    if "glass" in lowered or "window" in lowered:
        return (0.055, 0.105, 0.16)
    if any(word in lowered for word in ("wheel", "tyre", "tire", "black")):
        return (0.035, 0.04, 0.05)
    if any(word in lowered for word in ("optics", "light", "paper", "white")):
        return (0.88, 0.90, 0.88)
    if any(word in lowered for word in ("monitor cream", "pc creme", "keyboard creme")):
        return (0.72, 0.68, 0.54)
    if any(word in lowered for word in ("monitor", "pc ", "keyboard", "mouse")):
        return (0.16, 0.18, 0.22)
    if "chair" in lowered:
        return (0.12, 0.16, 0.22)
    if any(word in lowered for word in ("table", "drawer", "wenge", "wood")):
        return (0.34, 0.19, 0.09)
    if any(word in lowered for word in ("plant", "pot")):
        return (0.12, 0.42, 0.18)
    values = list(source)
    if len(values) >= 3:
        return tuple(max(0.025, min(0.95, float(v))) for v in values[:3])  # type: ignore[return-value]
    return (0.56, 0.58, 0.62)


def export_group(
    scene: object,
    indices: list[int],
    target: Path,
    *,
    target_horizontal: float,
    vertical_axis: int = 1,
) -> dict[str, object]:
    meshes = [scene.meshes[index] for index in indices]  # type: ignore[attr-defined]
    all_vertices = np.concatenate(
        [np.asarray(mesh.vertices, dtype=np.float64).reshape(-1, 3) for mesh in meshes], axis=0
    )
    horizontal_axes = [axis for axis in range(3) if axis != vertical_axis]
    low = all_vertices.min(axis=0)
    high = all_vertices.max(axis=0)
    center = (low + high) / 2.0
    center[vertical_axis] = low[vertical_axis]
    horizontal_span = max(float(high[axis] - low[axis]) for axis in horizontal_axes)
    scale = target_horizontal / max(horizontal_span, 1e-9)

    target.parent.mkdir(parents=True, exist_ok=True)
    mtl_path = target.with_suffix(".mtl")
    material_names: dict[int, str] = {}
    with mtl_path.open("w", encoding="utf-8", newline="\n") as mtl:
        for mesh in meshes:
            material_index = int(mesh.material_index)
            if material_index in material_names:
                continue
            material = scene.materials[material_index]  # type: ignore[attr-defined]
            name = safe_name(str(material.get("NAME") or f"material-{material_index}"))
            # The same material name can occur several times in imported FBX.
            name = f"{name}-{material_index}"
            material_names[material_index] = name
            red, green, blue = material_color(name, material.get("COLOR_DIFFUSE") or ())
            mtl.write(f"newmtl {name}\nKd {red:.6f} {green:.6f} {blue:.6f}\n\n")

    vertex_offset = 0
    uv_offset = 0
    triangle_count = 0
    with target.open("w", encoding="utf-8", newline="\n") as obj:
        obj.write(f"mtllib {mtl_path.name}\n")
        for mesh in meshes:
            vertices = (np.asarray(mesh.vertices, dtype=np.float64).reshape(-1, 3) - center) * scale
            texcoords_raw = np.asarray(mesh.texcoords, dtype=np.float64)
            if texcoords_raw.size:
                components = max(2, texcoords_raw.size // max(1, len(vertices)))
                texcoords = texcoords_raw.reshape(-1, components)[:, :2]
            else:
                texcoords = np.zeros((len(vertices), 2), dtype=np.float64)
            indices_raw = np.asarray(mesh.indices, dtype=np.int64).reshape(-1)
            faces = indices_raw[: len(indices_raw) // 3 * 3].reshape(-1, 3)
            obj.write(f"o {safe_name(mesh.name)}\n")
            obj.write(f"usemtl {material_names[int(mesh.material_index)]}\n")
            for x, y, z in vertices:
                obj.write(f"v {x:.7f} {y:.7f} {z:.7f}\n")
            for u, v in texcoords:
                obj.write(f"vt {u:.7f} {v:.7f}\n")
            for a, b, c in faces:
                values = [
                    f"{int(index) + 1 + vertex_offset}/{int(index) + 1 + uv_offset}"
                    for index in (a, b, c)
                ]
                obj.write("f " + " ".join(values) + "\n")
            vertex_offset += len(vertices)
            uv_offset += len(texcoords)
            triangle_count += len(faces)
    return {
        "file": target.name,
        "triangles": triangle_count,
        "scale": scale,
        "source_meshes": [str(mesh.name) for mesh in meshes],
    }


def load(path: Path) -> object:
    return assimp_py.import_file(str(path), FLAGS)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--staging", type=Path, default=Path(".asset-staging"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("native-ui/assets/models/pulsearc-community"),
    )
    args = parser.parse_args()

    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, object] = {"models": {}, "sources": {}}

    generic = load(args.staging / "generic/source/fab.fbx")
    car_groups = {
        "compact": [0, 1, 2, 3],
        "coupe": [4, 5, 6, 7],
        "hatchback": [8, 9, 10, 11],
        "minivan": [12, 13, 14, 15],
        "offroad": [16, 17, 18, 19],
        "pickup": [20, 21, 22, 23],
        "sedan": [24, 25, 26, 27],
        "sport": [28, 29, 30, 31],
        "suv": [32, 33, 34, 35],
        "wagon": [36, 37, 38, 39],
    }
    cars_dir = output / "passenger-cars"
    manifest["models"]["passenger-cars"] = {
        name: export_group(generic, indices, cars_dir / f"{name}.obj", target_horizontal=4.1)
        for name, indices in car_groups.items()
    }

    office = load(args.staging / "office/source/90s Retro Office Pack.glb")
    office_groups = {
        "retro-pc-cream": [34, 35, 36, 37, 38],
        "retro-pc-black": [39, 40, 41, 42, 43],
        "retro-pc-white": [44, 45, 46, 47, 48],
        "office-chair": [51, 52, 53],
        "water-cooler": [11],
    }
    office_dir = output / "retro-office"
    manifest["models"]["retro-office"] = {
        name: export_group(office, indices, office_dir / f"{name}.obj", target_horizontal=1.25)
        for name, indices in office_groups.items()
    }

    dvd = load(args.staging / "dvd/source/case.fbx")
    dvd_dir = output / "dvd-case"
    manifest["models"]["dvd-case"] = {
        "case": export_group(dvd, [0, 2], dvd_dir / "case.obj", target_horizontal=0.37)
    }

    manifest["sources"] = {
        "passenger-cars": {
            "title": "Generic passenger car pack",
            "author": "Comrade1280",
            "license": "CC BY 4.0",
            "url": "https://sketchfab.com/3d-models/generic-passenger-car-pack-20f9af9b8a404d5cb022ac6fe87f21f5",
        },
        "retro-office": {
            "title": "90s Retro Office Pack",
            "author": "MadeByYeshe",
            "license": "CC BY 4.0",
            "url": "https://sketchfab.com/3d-models/90s-retro-office-pack-dadca97505214b9481d35e22c48e18df",
        },
        "dvd-case": {
            "title": "DVD/Game Case",
            "author": "Raphael Frei",
            "license": "CC BY 4.0",
            "url": "https://sketchfab.com/3d-models/dvdgame-case-d5c542e24bee490fbdf130413983f124",
            "note": "Disc geometry is intentionally excluded.",
        },
    }
    (output / "asset-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
