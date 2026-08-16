from __future__ import annotations

import importlib.util
import hashlib
import json
from pathlib import Path

from pulsearc.rpcs3_patches import discover_patches


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/deploy-live-rpcs3-patches.py"
CUSTOM = ROOT / "assets/rpcs3-patches/demons-souls-blus30443-v1.00.yml"


def _deployment_module():
    spec = importlib.util.spec_from_file_location("deploy_live_rpcs3_patches", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_demons_souls_gameplay_cheats_merge_and_discover(tmp_path: Path) -> None:
    module = _deployment_module()
    official = """Version: 1.2

Anchors:
  Existing: &Existing
    - [ be32, 0x1, 0x2 ]
PPU-0000000000000000000000000000000000000000:
  \"Existing Patch\":
    Games:
      \"Existing Game\":
        BCUS98174: [ 01.00 ]
    Patch Version: 1.2
    Patch:
      - [ load, *Existing ]
"""
    merged = module.merge_custom_database(
        official,
        CUSTOM.read_text(encoding="utf-8"),
    )
    database = tmp_path / "patch.yml"
    database.write_text(merged, encoding="utf-8")

    cheats = discover_patches(database, "BLUS30443")
    names = {cheat.name for cheat in cheats}
    assert names == {
        "Infinite HP + Infinite MP + Infinite SP (Artemis)",
        "Max Player Status (W.I.P.) (Artemis)",
        "Max Souls On Gain - 999,999,999 (Artemis)",
        "Infinite Items (Artemis)",
    }
    assert all(not cheat.enabled for cheat in cheats)


def test_obtain_database_normalizes_windows_line_endings(monkeypatch, tmp_path: Path) -> None:
    module = _deployment_module()
    source = (
        b"Version: 1.2\r\n\r\nAnchors:\r\n"
        + (b"  # padding for deployment size validation\r\n" * 3000)
        + b"BCUS98174:\r\n"
    )
    monkeypatch.setattr(module, "CUSTOM_DATABASES", (CUSTOM,))
    database = tmp_path / "patch.yml"
    database.write_bytes(source)
    merged = module.obtain_database(database).decode("utf-8")
    assert "\r" not in merged
    assert "Infinite HP + Infinite MP + Infinite SP (Artemis)" in merged


def test_obtain_database_decodes_rpc3_api_json(monkeypatch, tmp_path: Path) -> None:
    module = _deployment_module()
    patch = (
        "Version: 1.2\n\nAnchors:\n"
        + ("  # padding for deployment size validation\n" * 3000)
        + "BCUS98174:\n"
    )
    payload = {
        "return_code": 0,
        "version": "1.2",
        "sha256": hashlib.sha256(patch.encode("utf-8")).hexdigest(),
        "patch": patch,
    }
    monkeypatch.setattr(module, "CUSTOM_DATABASES", (CUSTOM,))
    database = tmp_path / "api.json"
    database.write_text(json.dumps(payload), encoding="utf-8")
    merged = module.obtain_database(database).decode("utf-8")
    assert merged.startswith("Version: 1.2\n")
    assert "Infinite Items (Artemis)" in merged
