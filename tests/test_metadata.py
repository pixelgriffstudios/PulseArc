from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pulsearc.metadata import (  # noqa: E402
    canonical_system_id,
    cover_title_candidates,
    offline_cover_path,
    release_year,
    title_key,
    wikipedia_cover_url,
)
from pulsearc.metadata import MetadataCache  # noqa: E402
from pulsearc import metadata_daemon  # noqa: E402
from pulsearc.metadata_daemon import mounted_dvd_entry  # noqa: E402


class _Response:
    def __init__(self, value: dict) -> None:
        self.payload = json.dumps(value).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self, _size: int) -> bytes:
        return self.payload


class MetadataTests(unittest.TestCase):
    def test_mounted_dvd_gets_title_specific_artwork_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            marker = root / "THE_DAY_AFTER_TOMORROW" / "VIDEO_TS" / "VIDEO_TS.IFO"
            marker.parent.mkdir(parents=True)
            marker.write_bytes(b"DVDVIDEO")
            entry = mounted_dvd_entry(root)
            self.assertIsNotNone(entry)
            assert entry is not None
            self.assertEqual(entry["title"], "The Day After Tomorrow")
            self.assertTrue(entry["content_id"].startswith("pulsearc-dvd-video-"))

    def test_title_key_ignores_region_and_punctuation(self) -> None:
        self.assertEqual(title_key("WinBack - Covert Operations (USA)"), "winbackcovertoperations")

    def test_title_key_preserves_trailing_title_number(self) -> None:
        self.assertEqual(title_key("Super Mario Bros. 3"), "supermariobros3")
        self.assertEqual(title_key("Super Mario Bros. 3 (USA) (Rev 1).nes"), "supermariobros3")
        self.assertEqual(release_year("The Day After Tomorrow (2004).mkv"), 2004)

    def test_offline_cover_uses_title_index(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cover = root / "nintendo-64/winback.png"
            cover.parent.mkdir(parents=True)
            cover.write_bytes(b"png")
            (root / "index.json").write_text(json.dumps({
                "nintendo-64": {"winbackcovertoperations": "nintendo-64/winback.png"}
            }), encoding="utf-8")
            self.assertEqual(offline_cover_path("WinBack - Covert Operations (USA)", "nintendo-64", root), cover)

    def test_offline_cover_accepts_common_platform_alias(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cover = root / "mega-drive/sonic.png"
            cover.parent.mkdir(parents=True)
            cover.write_bytes(b"png")
            (root / "index.json").write_text(json.dumps({
                "mega-drive": {"sonicthehedgehog": "mega-drive/sonic.png"}
            }), encoding="utf-8")
            self.assertEqual(offline_cover_path("Sonic the Hedgehog (USA)", "Genesis", root), cover)
            self.assertEqual(canonical_system_id("PSX"), "playstation")

    def test_cover_candidates_strip_rom_suffix_but_keep_exact_region_title(self) -> None:
        self.assertEqual(
            cover_title_candidates("Super Mario Bros. 3 (USA) (Rev 1).nes"),
            ("Super Mario Bros. 3 (USA) (Rev 1)", "Super Mario Bros. 3", "Super Mario Bros 3"),
        )

    def test_developer_game_does_not_keep_unrelated_web_synopsis(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            index = root / "library.json"
            output = root / "covers.json"
            synopses = root / "synopses.json"
            index.write_text(json.dumps([{
                "content_id": "hell-on-rails",
                "title": "Hell on Rails",
                "platform": "windows",
                "path": "/var/lib/pulsearc/library/games/windows/hell-on-rails/game.exe",
            }]), encoding="utf-8")
            synopses.write_text(json.dumps({"hell-on-rails": "Unrelated rail shooter article"}), encoding="utf-8")
            with (
                patch.object(metadata_daemon, "INDEX", index),
                patch.object(metadata_daemon, "OUTPUT", output),
                patch.object(metadata_daemon, "SYNOPSES_OUTPUT", synopses),
                patch.object(metadata_daemon, "STATE", root / "state"),
                patch.object(metadata_daemon, "OFFLINE_ARTWORK", root / "offline"),
                patch.object(metadata_daemon, "libretro_cover_url", return_value=None),
                MetadataCache(root / "metadata.db") as cache,
            ):
                metadata_daemon.process_once(cache)
            self.assertNotIn("hell-on-rails", json.loads(synopses.read_text(encoding="utf-8")))

    def test_exact_game_synopses_override_ambiguous_web_matches(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            index = root / "library.json"
            output = root / "covers.json"
            synopses = root / "synopses.json"
            index.write_text(json.dumps([
                {"content_id": "beyond", "title": "Beyond the Beyond (USA)",
                 "platform": "playstation", "path": "/games/beyond.chd"},
                {"content_id": "speed", "title": "Speed Devils (USA)",
                 "platform": "dreamcast", "path": "/games/speed.gdi"},
            ]), encoding="utf-8")
            synopses.write_text(json.dumps({
                "beyond": "Beyond Good & Evil",
                "speed": "Need for Speed",
            }), encoding="utf-8")
            with (
                patch.object(metadata_daemon, "INDEX", index),
                patch.object(metadata_daemon, "OUTPUT", output),
                patch.object(metadata_daemon, "SYNOPSES_OUTPUT", synopses),
                patch.object(metadata_daemon, "STATE", root / "state"),
                patch.object(metadata_daemon, "OFFLINE_ARTWORK", root / "offline"),
                patch.object(metadata_daemon, "libretro_cover_url", return_value=None),
                MetadataCache(root / "metadata.db") as cache,
            ):
                metadata_daemon.process_once(cache)
            values = json.loads(synopses.read_text(encoding="utf-8"))
            self.assertIn("young knight Finn", values["beyond"])
            self.assertIn("arcade racing game", values["speed"])

    @patch("pulsearc.metadata.urllib.request.urlopen")
    def test_wikipedia_film_poster_lookup(self, mocked) -> None:
        mocked.side_effect = [
            _Response({"query": {"pages": {"1": {
                "index": 1,
                "images": [{"title": "File:The Day After Tomorrow movie.jpg"}],
            }}}}),
            _Response({"query": {"pages": {"2": {"imageinfo": [{
                "thumburl": "https://upload.wikimedia.org/poster.jpg"
            }]}}}}),
        ]
        self.assertEqual(
            wikipedia_cover_url("The Day After Tomorrow (2004).mkv", "movie"),
            "https://upload.wikimedia.org/poster.jpg",
        )


if __name__ == "__main__":
    unittest.main()
