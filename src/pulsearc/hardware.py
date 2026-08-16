from __future__ import annotations

import json
import re
import subprocess
from dataclasses import asdict
from pathlib import Path

from .graphics import GraphicsCapabilities, GraphicsPolicy, select_graphics_policy


VERSION = re.compile(r"Vulkan Instance Version:\s*(\d+)\.(\d+)", re.I)


def _run(command: list[str], timeout: float = 5.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)


def probe() -> GraphicsCapabilities:
    opengl = False
    vulkan_version: tuple[int, int] | None = None
    try:
        gl = _run(["glxinfo", "-B"])
        opengl = gl.returncode == 0 and "OpenGL renderer" in gl.stdout
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        vk = _run(["vulkaninfo", "--summary"])
        match = VERSION.search(vk.stdout + vk.stderr)
        if vk.returncode == 0 and match:
            vulkan_version = (int(match.group(1)), int(match.group(2)))
    except (OSError, subprocess.SubprocessError):
        pass
    return GraphicsCapabilities(opengl, vulkan_version, False)


def write_policy(destination: Path) -> GraphicsPolicy:
    policy = select_graphics_policy(probe())
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(json.dumps(asdict(policy), indent=2), encoding="utf-8")
    temporary.replace(destination)
    return policy


if __name__ == "__main__":
    write_policy(Path("/run/pulsearc/graphics.json"))

