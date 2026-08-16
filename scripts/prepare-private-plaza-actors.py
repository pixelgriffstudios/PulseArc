#!/usr/bin/env python3
"""Prepare user-supplied Plaza actors for a private live installation.

These models are intentionally emitted outside the public UI asset tree. Only
Angela contains an embedded redistribution license; the other supplied files
must not enter public release artifacts without separate license proof.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREPARER = ROOT / "scripts/prepare-pulsearc-3d-assets.py"
spec = importlib.util.spec_from_file_location("pulsearc_asset_preparer", PREPARER)
if spec is None or spec.loader is None:
    raise RuntimeError("asset preparer could not be loaded")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def main() -> int:
    staging = ROOT / ".asset-staging"
    output = ROOT / ".private-assets/plaza-actors"
    output.mkdir(parents=True, exist_ok=True)
    sources = {
        "angela": (
            staging / "angela/source/unpacked/scene.gltf",
            staging / "angela/textures/angela_bunnylove_in_game_baseColor.png",
            0.92,
            1,
        ),
        "guinevere": (
            staging / "guinevere/source/hero_Guinevere_skin09.fbx",
            staging / "guinevere/textures/Guinevere_skin_pbs_d.png",
            0.92,
            2,
        ),
        "rafaela": (
            staging / "rafaela/source/hero_Old_rafaela.fbx",
            staging / "rafaela/textures/tianshi.png",
            0.92,
            2,
        ),
        "wolf": (
            staging / "wolf/source/Wolf_1_Baby.fbx",
            staging / "wolf/textures/BabyWolf_texture.png",
            0.90,
            1,
        ),
    }
    manifest: dict[str, object] = {"private": True, "models": {}}
    for name, (model_path, texture_path, width, vertical_axis) in sources.items():
        scene = module.load(model_path)
        indices = list(range(len(scene.meshes)))
        result = module.export_group(
            scene,
            indices,
            output / f"{name}.obj",
            target_horizontal=width,
            vertical_axis=vertical_axis,
        )
        if vertical_axis == 2:
            target = output / f"{name}.obj"
            converted: list[str] = []
            for line in target.read_text(encoding="utf-8").splitlines():
                if line.startswith("v "):
                    prefix, x, y, z = line.split()
                    line = f"{prefix} {x} {z} {y}"
                converted.append(line)
            target.write_text("\n".join(converted) + "\n", encoding="utf-8")
        texture_target = output / f"{name}.png"
        shutil.copy2(texture_path, texture_target)
        result["texture"] = texture_target.name
        result["animation"] = "PulseArc route movement, sway, and bob (source contains no skeletal tracks)"
        result["vertical_axis"] = vertical_axis
        manifest["models"][name] = result
    court = module.load(staging / "court/source/BasketBall_Court.glb")
    court_result = module.export_group(
        court,
        list(range(len(court.meshes))),
        output / "basketball-court.obj",
        target_horizontal=18.0,
    )
    court_result["animation"] = "Static GPU display-list scenery"
    manifest["models"]["basketball-court"] = court_result
    monika = module.load(staging / "monika/source/scene_export.fbx")
    monika_result = module.export_group(
        monika,
        list(range(len(monika.meshes))),
        output / "monika.obj",
        target_horizontal=0.92,
    )
    monika_textures = {
        "hair05": "monikaHair05_color.png",
        "blazer": "blazer_color.png",
        "blazercollar": "blazerCollar_color.png",
        "hands": "monikaHands_color.png",
        "shoe01": "monikaShoe01_color.png",
        "eyelash": "eyelashes_color.png",
        "eyeswhites": "eyeWhites_color.png",
        "eyes": "eyes_color.png",
        "shirt": "monikaUndershirtRibbon_color.png",
        "ribbonhead": "monikaRibbon_color.png",
        "hair03": "monikaHair03_color.png",
        "hair02": "monikaHair02_color.png",
        "hair01": "monikaHair01_color.png",
        "shoe02": "monikaShoe02_color.png",
        "skirt": "skirt_color.png",
        "highlights": "highlights_color.png",
        "hair04": "monikaHair04Burned_color.png",
        "face": "face_color.png",
        "eyebrow": "eyebrows_color.png",
        "legs": "legs_color.png",
        "sweater": "monikaSweater_color.png",
        "ribbon": "monikaRibbonChest_color.png",
    }
    for material, source_name in monika_textures.items():
        shutil.copy2(
            staging / "monika/textures" / source_name,
            output / f"monika-{material}.png",
        )
    monika_result["textures"] = {
        material: f"monika-{material}.png" for material in monika_textures
    }
    monika_result["presentation"] = "Two fully textured static statues on register plinths"
    manifest["models"]["monika"] = monika_result
    (output / "private-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(f"PULSEARC_PRIVATE_PLAZA_ASSETS_OK actors={len(sources)} court=1 statues=1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
