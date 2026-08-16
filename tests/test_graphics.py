from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pulsearc.graphics import GraphicsCapabilities, select_graphics_policy  # noqa: E402


class GraphicsPolicyTests(unittest.TestCase):
    def test_modern_vulkan_uses_gamescope(self) -> None:
        policy = select_graphics_policy(GraphicsCapabilities(True, (1, 4), True))
        self.assertEqual(policy.session_backend, "gamescope")
        self.assertEqual(policy.windows_d3d8_11, "dxvk-modern")

    def test_modern_vulkan_survives_gamescope_failure(self) -> None:
        policy = select_graphics_policy(GraphicsCapabilities(True, (1, 4), False))
        self.assertEqual(policy.session_backend, "x11")
        self.assertEqual(policy.windows_d3d8_11, "dxvk-modern")
        self.assertEqual(policy.windows_d3d12, "vkd3d-proton")

    def test_legacy_vulkan_does_not_require_gamescope(self) -> None:
        policy = select_graphics_policy(GraphicsCapabilities(True, (1, 1), False))
        self.assertEqual(policy.session_backend, "x11")
        self.assertEqual(policy.windows_d3d8_11, "dxvk-legacy")

    def test_vulkan_13_uses_legacy_dxvk(self) -> None:
        policy = select_graphics_policy(GraphicsCapabilities(True, (1, 3), False))
        self.assertEqual(policy.session_backend, "x11")
        self.assertEqual(policy.windows_d3d8_11, "dxvk-legacy")

    def test_ivy_bridge_style_fallback_uses_opengl(self) -> None:
        policy = select_graphics_policy(GraphicsCapabilities(True, None, False))
        self.assertEqual(policy.session_backend, "x11")
        self.assertEqual(policy.windows_d3d8_11, "wined3d")


if __name__ == "__main__":
    unittest.main()
