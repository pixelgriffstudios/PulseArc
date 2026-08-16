import tempfile
import unittest
from pathlib import Path

from pulsearc.scanner import scan


class ScannerTests(unittest.TestCase):
    def test_pulsearc_manifest_claims_nested_entrypoint_before_loose_scan(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            content = root / "content"
            content.mkdir()
            executable = content / "hell-on-rails.exe"
            executable.write_bytes(b"MZ" + bytes(64))
            cover = root / "cover.png"
            cover.write_bytes(b"png")
            (root / "pulsearc.toml").write_text(
                '[game]\n'
                'title = "Hell on Rails"\n'
                'platform = "windows"\n'
                'entrypoint = "content/hell-on-rails.exe"\n'
                'working_directory = "content"\n'
                'runner = "wine-ge"\n'
                'renderer = "opengl"\n',
                encoding="utf-8",
            )
            entries = scan(root)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].title, "Hell on Rails")
            self.assertEqual(entries[0].path, str(executable))
            self.assertEqual(entries[0].cover_state, "local")
            self.assertEqual(entries[0].cover_path, str(cover))

    def test_legacy_kzi_cart_uses_internal_runner_and_preserves_safe_id(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            content = root / "content"
            content.mkdir()
            executable = content / "hell-on-rails.exe"
            executable.write_bytes(b"MZ" + bytes(64))
            (root / "icon.png").write_bytes(b"png")
            (root / "controls.amgp").write_text("<antimicroconfig/>", encoding="utf-8")
            (root / "cart.kzi").write_text(
                "Name=Hell on Rails\nId=hell-on-rails\n"
                "Exec=content/hell-on-rails.exe\nIcon=icon.png\nRuntime=windows-1.0\n"
                "Controller=controls.amgp\n",
                encoding="utf-8",
            )
            entries = scan(root)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].content_id, "hell-on-rails")
            self.assertEqual(entries[0].platform, "windows")
            self.assertEqual(entries[0].runner, "wine-ge")
            self.assertTrue(entries[0].read_only)
            self.assertEqual(entries[0].cover_state, "local")
            self.assertEqual(entries[0].cover_path, str(root / "icon.png"))
            self.assertEqual(entries[0].controller_profile, str(root / "controls.amgp"))

    def test_legacy_kzi_manifest_can_have_a_game_specific_filename(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            executable = root / "game.nes"
            executable.write_bytes(b"NES\x1a" + bytes(64))
            (root / "Super Mario Bros.kzi").write_text(
                "Name=Super Mario Bros.\nId=super-mario-bros\n"
                "Exec=game.nes\nRuntime=nes-1.0\n",
                encoding="utf-8",
            )
            entries = scan(root)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].title, "Super Mario Bros.")
            self.assertEqual(entries[0].content_id, "super-mario-bros")
            self.assertEqual(entries[0].runner, "retroarch:mesen")

    def test_legacy_kzi_rejects_entrypoint_path_traversal(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            outside = root.parent / "outside.exe"
            outside.write_bytes(b"MZ")
            try:
                (root / "cart.kzi").write_text(
                    "Name=Unsafe\nId=unsafe\nExec=../outside.exe\nRuntime=windows-1.0\n",
                    encoding="utf-8",
                )
                self.assertEqual(scan(root), [])
            finally:
                outside.unlink(missing_ok=True)

    def test_cue_tracks_are_not_listed_as_separate_games(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "track.bin").write_bytes(b"track")
            (root / "game.cue").write_text('FILE "track.bin" BINARY\n  TRACK 01 MODE2/2352\n', encoding="utf-8")
            self.assertEqual([entry.title for entry in scan(root)], ["game"])

    def test_gdi_tracks_and_companion_cue_are_not_separate_games(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "track01.bin").write_bytes(b"track one")
            (root / "track02.bin").write_bytes(b"track two")
            (root / "disc.gdi").write_text(
                '2\n1 0 4 2352 "track01.bin" 0\n2 45000 0 2352 "track02.bin" 0\n',
                encoding="utf-8",
            )
            (root / "disc.cue").write_text('FILE "track01.bin" BINARY\n', encoding="utf-8")
            entries = scan(root)
            self.assertEqual([entry.title for entry in entries], ["disc"])
            self.assertEqual(entries[0].platform, "optical-disc")

    def test_windows_noise_is_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "game.nes").write_bytes(b"NES\x1a")
            noise = root / "System Volume Information"
            noise.mkdir()
            (noise / "copy.nes").write_bytes(b"NES\x1a")
            self.assertEqual(len(scan(root)), 1)

    def test_extracted_ps3_disc_uses_rpcs3_eboot(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            game = root / "Sample PS3 Game"
            usrdir = game / "PS3_GAME/USRDIR"
            usrdir.mkdir(parents=True)
            eboot = usrdir / "EBOOT.BIN"
            eboot.write_bytes(b"SCE\x00" + bytes(128))
            (game / "PS3_GAME/PARAM.SFO").write_bytes(b"\x00PSF" + bytes(64))
            entries = scan(root)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].title, "Sample PS3 Game")
            self.assertEqual(entries[0].platform, "playstation-3")
            self.assertEqual(entries[0].runner, "rpcs3")
            self.assertEqual(entries[0].path, str(eboot))
