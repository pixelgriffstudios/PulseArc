from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GraphicsCapabilities:
    opengl: bool
    vulkan_version: tuple[int, int] | None
    gamescope_self_test: bool


@dataclass(frozen=True)
class GraphicsPolicy:
    session_backend: str
    windows_d3d8_11: str
    windows_d3d12: str
    reason: str


def select_graphics_policy(capabilities: GraphicsCapabilities) -> GraphicsPolicy:
    """Choose a safe backend after probing the actual installed driver.

    Marketing names and CPU generations are deliberately not used as the final
    decision. PulseArc runs Vulkan and Gamescope self-tests and falls back
    before starting the frontend if either test fails.
    """
    version = capabilities.vulkan_version
    if version and version >= (1, 4) and capabilities.gamescope_self_test:
        return GraphicsPolicy(
            "gamescope", "dxvk-modern", "vkd3d-proton", "Vulkan 1.4 and Gamescope self-test passed"
        )
    if version and version >= (1, 4):
        return GraphicsPolicy(
            "x11", "dxvk-modern", "vkd3d-proton", "Modern Vulkan path; Gamescope self-test did not pass"
        )
    if version and version >= (1, 1):
        return GraphicsPolicy(
            "x11", "dxvk-legacy", "unsupported", "Legacy Vulkan path; Gamescope is not required"
        )
    if capabilities.opengl:
        return GraphicsPolicy(
            "x11", "wined3d", "unsupported", "OpenGL compatibility path selected"
        )
    return GraphicsPolicy(
        "framebuffer", "software", "unsupported", "No usable accelerated graphics API detected"
    )
