from __future__ import annotations

import struct
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pulsearc.media import detect, stable_content_id  # noqa: E402


class MediaDetectionTests(unittest.TestCase):
    def test_nes_signature_overrides_filename(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "game.dat"
            path.write_bytes(b"NES\x1a" + bytes(1024))
            self.assertEqual(detect(path).platform, "nes")

    def test_ps1_eboot_pbp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "EBOOT.PBP"
            offsets = (40, 44, 48, 52, 56, 60, 64, 80)
            header = b"\x00PBP" + struct.pack("<I", 1) + struct.pack("<8I", *offsets)
            path.write_bytes(header + bytes(40) + b"PSISOIMG0000" + bytes(128))
            result = detect(path)
            self.assertEqual(result.platform, "playstation")
            self.assertEqual(result.runner, "duckstation")

    def test_psp_pbp_is_not_misclassified_as_ps1(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "EBOOT.PBP"
            offsets = (40, 44, 48, 52, 56, 60, 64, 80)
            header = b"\x00PBP" + struct.pack("<I", 1) + struct.pack("<8I", *offsets)
            path.write_bytes(header + bytes(40) + b"PSP GAME DATA" + bytes(128))
            self.assertEqual(detect(path).platform, "psp")

    def test_content_id_survives_rename(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.rom"
            second = Path(directory) / "renamed.rom"
            first.write_bytes(bytes(range(256)) * 100)
            second.write_bytes(first.read_bytes())
            self.assertEqual(stable_content_id(first), stable_content_id(second))


if __name__ == "__main__":
    unittest.main()

