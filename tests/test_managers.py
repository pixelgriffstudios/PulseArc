import tempfile
import unittest
from pathlib import Path

from pulsearc.cheats import (
    Cheat, import_duckstation_cheats, import_retroarch_cheats,
    load_cheats, save_cheats, set_cheat_enabled,
)
from pulsearc.cheat_export import export_duckstation, export_pcsx2, export_retroarch
from pulsearc.controllers import load_controller_profile, validate_antimicrox_profile
from pulsearc.metadata import (
    MetadataCache, MetadataResult, libretro_cover_url,
    libretro_fuzzy_cover_url, normalized_title,
)
from pulsearc.saves import SaveRecord, backup_save, restore_save
from pulsearc.rpcs3_patches import discover_patches, export_patch_config


ROOT = Path(__file__).resolve().parents[1]


class ManagerTests(unittest.TestCase):
    def test_antimicrox_profile_rejects_executable_slots(self):
        with tempfile.TemporaryDirectory() as folder:
            profile = Path(folder) / "unsafe.amgp"
            profile.write_text(
                "<gamecontroller><slot><code>/tmp/tool</code><mode>execute</mode>"
                "</slot></gamecontroller>",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                validate_antimicrox_profile(profile)

    def test_xbox_profile_hotkeys(self):
        profile = load_controller_profile(ROOT / "config" / "controllers" / "xbox-default.toml")
        self.assertEqual(profile.buttons["south"], "a")
        self.assertEqual(profile.hotkeys["exit_game"], ("select", "start"))

    def test_cheats_default_disabled(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cheats.json"
            save_cheats(path, [Cheat("infinite-lives", "Infinite lives", "AAAA-BBBB")])
            self.assertFalse(load_cheats(path)[0].enabled)

    def test_cheat_exports_only_enable_when_requested(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cheats = [Cheat("off", "Off", "patch=0", False), Cheat("on", "On", "patch=1", True)]
            export_retroarch(cheats, root / "game.cht")
            self.assertIn('cheat0_enable = "false"', (root / "game.cht").read_text(encoding="utf-8"))
            export_pcsx2(cheats, root / "game.pnach")
            text = (root / "game.pnach").read_text(encoding="utf-8")
            self.assertNotIn("patch=0", text)
            self.assertIn("patch=1", text)

    def test_rpcs3_patches_are_disabled_until_explicitly_enabled(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            database = root / "patch.yml"
            database.write_text(
                'Version: 1.2\n\nAnchors:\n  game: &game\n'
                '    "Example Game":\n      BLUS12345: [ 01.00 ]\n\n'
                'PPU-0123456789abcdef:\n  "Infinite Health":\n'
                '    Games: *game\n    Author: "Tester"\n    Patch Version: 1.0\n'
                '    Patch:\n      - [ be32, 0x1, 0x2 ]\n',
                encoding="utf-8",
            )
            patches = discover_patches(database, "BLUS12345")
            self.assertEqual([item.name for item in patches], ["Infinite Health"])
            self.assertFalse(patches[0].enabled)
            destination = root / "patch_config.yml"
            export_patch_config([
                Cheat(patches[0].cheat_id, patches[0].name, patches[0].code, True)
            ], destination)
            config = destination.read_text(encoding="utf-8")
            self.assertIn('"BLUS12345"', config)
            self.assertIn("Enabled: true", config)

    def test_libretro_cheat_import_is_disabled_and_toggleable(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.cht"
            source.write_text(
                'cheats = 1\ncheat0_desc = "Infinite Lives"\n'
                'cheat0_code = "AAAA-BBBB"\ncheat0_enable = true\n',
                encoding="utf-8",
            )
            imported = import_retroarch_cheats(source)
            self.assertEqual(imported[0].name, "Infinite Lives")
            self.assertFalse(imported[0].enabled)
            destination = Path(folder) / "managed.json"
            save_cheats(destination, imported)
            self.assertTrue(set_cheat_enabled(destination, 0).enabled)

    def test_duckstation_gameshark_import_and_enabled_export(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "SCUS-94702.cht"
            source.write_text(
                "; comment\n[Max Gold]\nType = Gameshark\n"
                "Activation = EndFrame\n90103884 0001869F\n\n"
                "[Unsupported Option]\nType = Gameshark\n801FFE02 ????\n",
                encoding="utf-8",
            )
            imported = import_duckstation_cheats(source)
            self.assertEqual([item.name for item in imported], ["Max Gold"])
            self.assertFalse(imported[0].enabled)
            destination = root / "exported.cht"
            export_duckstation(imported, destination)
            self.assertNotIn("90103884", destination.read_text(encoding="utf-8"))
            export_duckstation([
                Cheat(imported[0].cheat_id, imported[0].name, imported[0].code, True)
            ], destination)
            text = destination.read_text(encoding="utf-8")
            self.assertIn("[Max Gold]", text)
            self.assertIn("90103884 0001869F", text)

    def test_retroarch_export_uses_emulator_handler_for_game_genie_codes(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "mario.cht"
            export_retroarch([
                Cheat("lives", "Infinite Lives", "OLUXYVOO", True),
            ], destination)
            text = destination.read_text(encoding="utf-8")
            self.assertIn('cheat0_enable = "true"', text)
            self.assertIn('cheat0_handler = "0"', text)
            self.assertIn('cheat0_cheat_type = "1"', text)
            self.assertIn('cheat0_memory_search_size = "3"', text)
            self.assertIn('cheat0_repeat_count = "1"', text)

    def test_save_backup_restore(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "live"
            source.mkdir()
            (source / "memory.card").write_text("save", encoding="utf-8")
            record = SaveRecord("default", "game-id", source, 4, 0)
            backup = backup_save(record, root / "backups")
            destination = root / "restored"
            restore_save(backup, destination)
            self.assertEqual((destination / "memory.card").read_text(encoding="utf-8"), "save")

    def test_manual_artwork_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            with MetadataCache(Path(folder) / "metadata.db") as cache:
                cache.store("id", MetadataResult("Manual", "nes"), "manual.png", "user", manual=True)
                cache.store("id", MetadataResult("Automatic", "nes"), "auto.png", "provider")
                row = cache.connection.execute("SELECT title,cover_path FROM metadata WHERE content_id='id'").fetchone()
            self.assertEqual(row, ("Manual", "manual.png"))
            self.assertEqual(normalized_title("Game (USA) (Rev 2).nes"), "Game")

    def test_cover_url_uses_system_repository(self):
        url = libretro_cover_url("Super Mario Bros. 3", "nes")
        self.assertIsNotNone(url)
        self.assertIn("Nintendo_-_Nintendo_Entertainment_System", url)
        self.assertTrue(url.endswith("Super%20Mario%20Bros.%203.png"))

    def test_wii_u_cover_fuzzy_matches_region_tagged_official_art(self):
        from pulsearc import metadata

        metadata._libretro_boxart_names.cache_clear()
        original = metadata._libretro_boxart_names
        metadata._libretro_boxart_names = lambda _system: (
            "Super Mario 3D World (USA) (En,Fr,Es).png",
        )
        try:
            url = libretro_fuzzy_cover_url("Super Mario 3D World", "wii-u")
        finally:
            metadata._libretro_boxart_names = original
        self.assertIsNotNone(url)
        self.assertIn("Super%20Mario%203D%20World%20%28USA%29", url)
