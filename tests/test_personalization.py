import json
import tempfile
import unittest
import zipfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "native-ui"))
from pulsearc_personalization import discover_themes, import_theme_archive, load_profiles


class PersonalizationTests(unittest.TestCase):
    def test_theme_discovery_rejects_assets_outside_theme(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            theme = root / "safe"
            theme.mkdir()
            (theme / "theme.toml").write_text(
                'id="safe"\nname="Safe"\nbackground="../outside.mp4"\n',
                encoding="utf-8",
            )
            (root / "outside.mp4").write_bytes(b"video")
            values = discover_themes(root)
            self.assertEqual(len(values), 1)
            self.assertIsNone(values[0].background)

    def test_theme_zip_import_is_bounded_and_requires_one_manifest(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = root / "theme.zip"
            with zipfile.ZipFile(archive, "w") as package:
                package.writestr("nice/theme.toml", 'id="nice"\nname="Nice"\n')
                package.writestr("nice/preview.png", b"png")
            theme_id = import_theme_archive(archive, root / "installed")
            self.assertEqual(theme_id, "nice")
            self.assertTrue((root / "installed/nice/theme.toml").is_file())

    def test_profiles_always_retain_default_and_cap_at_four(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "profiles.json"
            path.write_text(json.dumps([
                {"id": "profile-1", "name": "One"},
                {"id": "profile-2", "name": "Two"},
                {"id": "profile-3", "name": "Three"},
                {"id": "profile-9", "name": "Invalid"},
            ]), encoding="utf-8")
            profiles = load_profiles(path)
            self.assertEqual([item["id"] for item in profiles], ["default", "profile-1", "profile-2", "profile-3"])


if __name__ == "__main__":
    unittest.main()
