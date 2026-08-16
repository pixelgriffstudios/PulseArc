import tempfile
import unittest
from pathlib import Path

from pulsearc.graphics import GraphicsPolicy
from pulsearc.launch import create_launch_plan
from pulsearc.registry import RuntimeRegistry
from pulsearc.control import (
    _duckstation_serial,
    _prepare_cemu_config,
    _prepare_duckstation_config,
    _prepare_duckstation_cheats,
    _prepare_pcsx2_config,
    _prepare_retroarch_config,
    _prepare_rpcs3_config,
)


ROOT = Path(__file__).resolve().parents[1]


class RegistryLaunchTests(unittest.TestCase):
    def setUp(self):
        self.registry = RuntimeRegistry.load(ROOT / "config" / "systems.toml")

    def test_all_systems_reference_valid_runners(self):
        self.assertGreater(len(self.registry.systems), 20)

    def test_modern_windows_plan_uses_gamescope_and_dxvk(self):
        with tempfile.TemporaryDirectory() as folder:
            exe = Path(folder) / "game.exe"
            exe.write_bytes(b"MZ")
            policy = GraphicsPolicy("gamescope", "dxvk-modern", "vkd3d-proton", "test")
            plan = create_launch_plan(exe, "windows", "abc", "default", self.registry, policy, folder)
            self.assertEqual(plan.command[0], "/usr/bin/gamescope")
            self.assertEqual(plan.environment["PULSEARC_DXVK"], "modern")

    def test_opengl_windows_plan_disables_dxvk(self):
        with tempfile.TemporaryDirectory() as folder:
            exe = Path(folder) / "game.exe"
            exe.write_bytes(b"MZ")
            policy = GraphicsPolicy("x11", "wined3d", "unsupported", "test")
            plan = create_launch_plan(exe, "windows", "abc", "default", self.registry, policy, folder)
            self.assertNotEqual(plan.command[0], "/usr/bin/gamescope")
            self.assertEqual(plan.environment["PULSEARC_DXVK"], "disabled")
            self.assertTrue(plan.environment["WINEDLLOVERRIDES"].endswith("=b"))

    def test_retroarch_defaults_enable_controller_fullscreen_and_exit_chord(self):
        with tempfile.TemporaryDirectory() as folder:
            save_root = Path(folder)
            config = save_root / "config/retroarch/retroarch.cfg"
            config.parent.mkdir(parents=True)
            config.write_text('video_fullscreen = "false"\ninput_player1_a_btn = "nul"\n', encoding="utf-8")
            _prepare_retroarch_config(save_root)
            values = config.read_text(encoding="utf-8")
            self.assertIn('video_fullscreen = "true"', values)
            self.assertIn('input_player1_a_btn = "1"', values)
            self.assertIn('input_enable_hotkey_btn = "6"', values)
            self.assertIn('input_exit_emulator_btn = "7"', values)
            self.assertIn('input_menu_toggle_btn = "0"', values)

    def test_playstation_uses_modern_duckstation_with_console_defaults(self):
        self.assertEqual(self.registry.systems["playstation"].primary, "duckstation")
        with tempfile.TemporaryDirectory() as folder:
            save_root = Path(folder)
            config = _prepare_duckstation_config(save_root).read_text(encoding="utf-8")
            self.assertIn("ResolutionScale = 4", config)
            self.assertIn("HideCursorInFullscreen = true", config)
            self.assertIn("Cross = SDL-0/A", config)
            self.assertIn("PowerOff = SDL-0/Back & SDL-0/Start", config)
            self.assertIn("OpenPauseMenu = SDL-0/Back & SDL-0/A", config)
            self.assertIn("OpenPauseMenu = Keyboard/Escape", config)

    def test_pcsx2_configuration_finishes_setup_and_maps_xbox_pad(self):
        with tempfile.TemporaryDirectory() as folder:
            config = _prepare_pcsx2_config(Path(folder)).read_text(encoding="utf-8")
            self.assertIn("SetupWizardIncomplete = false", config)
            self.assertIn("StartFullscreen = true", config)
            self.assertIn("BIOS = scph10000.bin", config)
            self.assertIn("Cross = SDL-0/A", config)
            self.assertIn("Up = SDL-0/DPadUp", config)
            self.assertIn("upscale_multiplier = 3", config)

    def test_duckstation_cheats_use_canonical_serial_and_game_settings(self):
        from pulsearc.cheats import Cheat

        self.assertEqual(_duckstation_serial({"serial": "SCUS94702"}), "SCUS-94702")
        self.assertEqual(_duckstation_serial({"disc_serial": "SLUS-20267"}), "SLUS-20267")
        with tempfile.TemporaryDirectory() as folder:
            save_root = Path(folder)
            cheats = [Cheat("gold", "Max Gold", "90103884 0001869F", True)]
            _prepare_duckstation_cheats(save_root, "SCUS-94702", cheats)
            self.assertTrue((save_root / "data/duckstation/cheats/SCUS-94702.cht").is_file())
            self.assertTrue((save_root / "config/duckstation/cheats/SCUS-94702.cht").is_file())
            for root in ("data", "config"):
                settings_path = save_root / root / "duckstation/gamesettings/SCUS-94702.ini"
                self.assertTrue(settings_path.is_file())
                settings = settings_path.read_text(encoding="utf-8")
                self.assertEqual(settings.count("[Cheats]"), 1)
                self.assertIn("EnableCheats = true", settings)
                self.assertIn("Enable = Max Gold", settings)

    def test_playstation_3_uses_rpcs3_with_720p_vulkan_defaults(self):
        self.assertEqual(self.registry.systems["playstation-3"].primary, "rpcs3")
        runner = self.registry.runners["rpcs3"]
        self.assertIn("--fullscreen", runner.arguments)
        self.assertIn("--input-config=PulseArc", runner.arguments)
        with tempfile.TemporaryDirectory() as folder:
            save_root = Path(folder)
            config = _prepare_rpcs3_config(save_root).read_text(encoding="utf-8")
            self.assertIn("Renderer: Vulkan", config)
            self.assertIn("Resolution: 1280x720", config)
            self.assertIn("Frame limit: Auto", config)
            self.assertIn("VSync Mode: Disabled", config)
            self.assertIn("Shader Mode: Async Recompiler with Shader Interpreter", config)
            controls = save_root / "config/rpcs3/input_configs/global/PulseArc.yml"
            self.assertIn("Handler: SDL", controls.read_text(encoding="utf-8"))

    def test_playstation_3_migrates_legacy_input_profile_to_global_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            save_root = Path(folder)
            legacy = save_root / "config/rpcs3/input_configs/PulseArc.yml"
            legacy.parent.mkdir(parents=True)
            legacy.write_text("Player 1 Input:\n  Handler: Keyboard\n  Device: Keyboard\n", encoding="utf-8")
            _prepare_rpcs3_config(save_root)
            controls = save_root / "config/rpcs3/input_configs/global/PulseArc.yml"
            self.assertTrue(controls.is_file())
            self.assertFalse(legacy.exists())
            text = controls.read_text(encoding="utf-8")
            self.assertIn("Handler: SDL", text)
            self.assertNotIn("Handler: Keyboard", text)

    def test_playstation_3_repairs_old_rpc3_option_names(self):
        with tempfile.TemporaryDirectory() as folder:
            save_root = Path(folder)
            config = save_root / "config/rpcs3/config.yml"
            config.parent.mkdir(parents=True)
            config.write_text(
                "Video:\n  VSync Mode: Off\n  Shader Mode: Async Shader Recompiler\n",
                encoding="utf-8",
            )
            _prepare_rpcs3_config(save_root)
            text = config.read_text(encoding="utf-8")
            self.assertIn("VSync Mode: Disabled", text)
            self.assertIn("Shader Mode: Async Recompiler with Shader Interpreter", text)
            self.assertNotIn("VSync Mode: Off", text)

    def test_last_of_us_enables_write_color_buffers(self):
        with tempfile.TemporaryDirectory() as folder:
            save_root = Path(folder)
            config = _prepare_rpcs3_config(save_root, serial="BCUS98174")
            self.assertIn("Write Color Buffers: true", config.read_text(encoding="utf-8"))

    def test_demons_souls_enables_write_color_buffers(self):
        with tempfile.TemporaryDirectory() as folder:
            save_root = Path(folder)
            config = _prepare_rpcs3_config(save_root, serial="BLUS30443")
            self.assertIn("Write Color Buffers: true", config.read_text(encoding="utf-8"))

    def test_wii_u_uses_cemu_with_vulkan_fullscreen_defaults(self):
        self.assertEqual(self.registry.systems["wii-u"].primary, "cemu")
        with tempfile.TemporaryDirectory() as folder:
            save_root = Path(folder)
            config = _prepare_cemu_config(save_root).read_text(encoding="utf-8")
            self.assertIn("<api>1</api>", config)
            self.assertIn("<fullscreen>true</fullscreen>", config)
            self.assertIn("<TVVolume>100</TVVolume>", config)
            self.assertTrue((save_root / "data/Cemu/mlc01").is_dir())
            self.assertTrue((save_root / "config/Cemu/settings.xml").is_file())
