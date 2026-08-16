from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
import sys


MODULE_PATH = Path(__file__).resolve().parents[1] / "native-ui" / "pulsearc_ui.py"
sys.path.insert(0, str(MODULE_PATH.parent))
try:
    import pygame  # noqa: F401
except ModuleNotFoundError:
    NATIVE_UI = None
else:
    SPEC = importlib.util.spec_from_file_location("pulsearc_native_ui", MODULE_PATH)
    assert SPEC is not None and SPEC.loader is not None
    NATIVE_UI = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(NATIVE_UI)


@unittest.skipIf(NATIVE_UI is None, "pygame is not installed on the build host")
class NativeUiDetectionTests(unittest.TestCase):
    def test_music_accepts_scanner_platform_and_extension(self) -> None:
        self.assertTrue(NATIVE_UI.is_music_entry({"platform": "music", "path": "/media/song.bin"}))
        self.assertTrue(NATIVE_UI.is_music_entry({"system": "audio", "path": "/media/song.bin"}))
        self.assertTrue(NATIVE_UI.is_music_entry({"platform": "unknown", "path": "/media/song.wav"}))
        self.assertFalse(NATIVE_UI.is_music_entry({"platform": "nintendo-64", "path": "/media/game.z64"}))

    def test_library_only_includes_installed_games(self) -> None:
        internal = {
            "source_root": "/var/lib/pulsearc/library",
            "path": "/var/lib/pulsearc/library/games/nintendo-64/game.z64",
            "platform": "nintendo-64",
            "media_kind": "rom",
        }
        external = {**internal, "source_root": "/run/media/gamer/USB", "path": "/run/media/gamer/USB/game.z64"}
        music = {**internal, "platform": "music", "media_kind": "music", "path": "/var/lib/pulsearc/library/music/song.mp3"}
        self.assertTrue(NATIVE_UI.is_installed_game(internal))
        self.assertFalse(NATIVE_UI.is_installed_game(external))
        self.assertFalse(NATIVE_UI.is_installed_game(music))
        self.assertTrue(NATIVE_UI.is_external_entry(external))
        self.assertFalse(NATIVE_UI.is_external_entry(internal))

    def test_fit_size_preserves_cover_aspect_ratio(self) -> None:
        self.assertEqual(NATIVE_UI.PulseArcUI._fit_size((600, 900), (200, 200)), (133, 200))

    def test_library_groups_installed_games_by_system(self) -> None:
        ui = object.__new__(NATIVE_UI.PulseArcUI)
        ui.library = [
            {"platform": "nes", "source_root": "/var/lib/pulsearc/library", "path": "/var/lib/pulsearc/library/games/nes/a.nes", "media_kind": "rom"},
            {"platform": "nes", "source_root": "/var/lib/pulsearc/library", "path": "/var/lib/pulsearc/library/games/nes/b.nes", "media_kind": "rom"},
            {"platform": "nintendo-64", "source_root": "/var/lib/pulsearc/library", "path": "/var/lib/pulsearc/library/games/nintendo-64/c.z64", "media_kind": "rom"},
        ]
        ui.library_system = "nes"
        self.assertEqual(ui._library_systems(), [("nintendo-64", 1), ("nes", 2)])
        self.assertEqual(len(ui._library_games_for_system()), 2)

    def test_dvd_video_requires_video_ts_marker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertIsNone(NATIVE_UI.detected_dvd_video(root))
            marker = root / "MY_MOVIE" / "VIDEO_TS" / "VIDEO_TS.IFO"
            marker.parent.mkdir(parents=True)
            marker.write_bytes(b"DVDVIDEO")
            entry = NATIVE_UI.detected_dvd_video(root)
            self.assertIsNotNone(entry)
            assert entry is not None
            self.assertEqual(entry["platform"], "dvd-video")
            self.assertEqual(entry["title"], "My Movie")
            self.assertTrue(str(entry["content_id"]).startswith("pulsearc-dvd-video-"))

    def test_playstation_disc_uses_system_cnf(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            disc = root / "GAME_ONE"
            disc.mkdir()
            marker = disc / "SYSTEM.CNF"
            marker.write_text("BOOT = cdrom:\\\\SCUS_123.45;1\n", encoding="ascii")
            entry = NATIVE_UI.detected_playstation_disc(root)
            self.assertIsNotNone(entry)
            assert entry is not None
            self.assertEqual(entry["platform"], "playstation")
            self.assertEqual(entry["disc_serial"], "SCUS-12345")
            self.assertEqual(entry["source_root"], str(disc))
            self.assertIn("Game One", entry["title"])
            marker.write_text("BOOT2 = cdrom0:\\\\SLUS_999.01;1\n", encoding="ascii")
            entry = NATIVE_UI.detected_playstation_disc(root)
            self.assertIsNotNone(entry)
            assert entry is not None
            self.assertEqual(entry["platform"], "playstation-2")

    def test_playstation_disc_accepts_iso9660_versioned_system_cnf(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            marker = root / "PS2_DISC" / "SYSTEM.CNF;1"
            marker.parent.mkdir()
            marker.write_text("BOOT2 = cdrom0:\\\\SLUS_202.67;1\n", encoding="ascii")
            entry = NATIVE_UI.detected_playstation_disc(root)
            self.assertIsNotNone(entry)
            assert entry is not None
            self.assertEqual(entry["platform"], "playstation-2")
            self.assertEqual(entry["disc_serial"], "SLUS-20267")

    def test_playstation_disc_falls_back_to_boot_executable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            disc = root / "PS1_DISC"
            disc.mkdir()
            (disc / "SLUS_005.23").write_bytes(b"PS-X EXE")
            entry = NATIVE_UI.detected_playstation_disc(root)
            self.assertIsNotNone(entry)
            assert entry is not None
            self.assertEqual(entry["platform"], "playstation")
            self.assertEqual(entry["disc_serial"], "SLUS-00523")

    def test_emulator_yaml_title_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "gamedb.yaml"
            database.write_text(
                'SLUS-00523:\n  name: "NBA Live 98"\n  metadata:\n    genre: "Sports"\n',
                encoding="utf-8",
            )
            self.assertEqual(
                NATIVE_UI._read_disc_title_database(database, "SLUS-00523"),
                "NBA Live 98",
            )

    def test_single_external_game_play_launches_directly(self) -> None:
        ui = object.__new__(NATIVE_UI.PulseArcUI)
        game = {
            "content_id": "one",
            "title": "One Game",
            "platform": "nes",
            "source_root": "/run/media/gamer/USB",
            "path": "/run/media/gamer/USB/one.nes",
        }
        ui.boot_finished = True
        ui.screen_name = "home"
        ui.selection = 0
        ui.library = [game]
        ui.status = ""
        ui._sound = lambda _name: None
        launched = []
        ui._launch = launched.append
        ui._open = lambda _name: self.fail("single game should not open the browser")
        ui._accept()
        self.assertEqual(launched, [game])

    def test_theme_animation_pause_is_nested_and_balanced(self) -> None:
        class FakeThemeVideo:
            def __init__(self) -> None:
                self.pause_calls = 0
                self.resume_calls = 0

            def pause(self) -> None:
                self.pause_calls += 1

            def resume(self) -> None:
                self.resume_calls += 1

        ui = object.__new__(NATIVE_UI.PulseArcUI)
        ui.theme_pause_depth = 0
        ui.theme_video = FakeThemeVideo()
        ui._pause_theme_animation()
        ui._pause_theme_animation()
        self.assertEqual(ui.theme_pause_depth, 2)
        self.assertEqual(ui.theme_video.pause_calls, 1)
        ui._resume_theme_animation()
        self.assertEqual(ui.theme_video.resume_calls, 0)
        ui._resume_theme_animation()
        self.assertEqual(ui.theme_pause_depth, 0)
        self.assertEqual(ui.theme_video.resume_calls, 1)

    def test_radio_catalog_has_distinct_supported_genres(self) -> None:
        genres = {station["genre"] for station in NATIVE_UI.RADIO_STATIONS}
        self.assertTrue({"ROCK", "POP", "HIP-HOP / R&B", "80'S"}.issubset(genres))

    def test_tv_menu_exposes_free_tv_and_source_management(self) -> None:
        ui = object.__new__(NATIVE_UI.PulseArcUI)
        ui.tv_actions = ("FREE LIVE TV", "TV SOURCES", "BACK")
        ui.screen_name = "tv"
        self.assertEqual(ui._count(), 3)

    def test_tv_epg_request_reads_initialized_state_without_restarting_ui(self) -> None:
        ui = object.__new__(NATIVE_UI.PulseArcUI)
        ui.tv_active_source = {"type": "xtream"}
        ui.tv_epg_cache = {"42": (float("inf"), [{"title": "Now Playing"}])}
        ui.tv_epg_pending = set()
        self.assertEqual(
            ui._request_tv_epg({"stream_id": "42", "media_type": "live"}),
            [{"title": "Now Playing"}],
        )


if __name__ == "__main__":
    unittest.main()
