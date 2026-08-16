from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pulsearc.manifest import load_manifest  # noqa: E402


class ManifestTests(unittest.TestCase):
    def test_windows_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Game.exe").write_bytes(b"MZ")
            (root / "controls.amgp").write_text("<antimicroconfig/>", encoding="utf-8")
            manifest = root / "pulsearc.toml"
            manifest.write_text(
                "[game]\n"
                "title = \"Example Game\"\n"
                "platform = \"windows\"\n"
                "entrypoint = \"Game.exe\"\n"
                "renderer = \"vulkan\"\n"
                "arguments = [\"-fullscreen\"]\n"
                "[input]\n"
                "antimicrox_profile = \"controls.amgp\"\n",
                encoding="utf-8",
            )
            game = load_manifest(manifest)
            self.assertEqual(game.title, "Example Game")
            self.assertEqual(game.renderer, "vulkan")
            self.assertEqual(game.controller_profile, root / "controls.amgp")

    def test_manifest_cannot_escape_game_folder(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "game" / "pulsearc.toml"
            manifest.parent.mkdir()
            (root / "outside.exe").write_bytes(b"MZ")
            manifest.write_text(
                "[game]\n"
                "title = \"Bad\"\n"
                "platform = \"windows\"\n"
                "entrypoint = \"../outside.exe\"\n",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                load_manifest(manifest)


if __name__ == "__main__":
    unittest.main()
