from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

from .graphics import GraphicsPolicy
from .registry import RuntimeRegistry


@dataclass(frozen=True)
class LaunchPlan:
    runner_id: str
    command: tuple[str, ...]
    environment: dict[str, str]
    working_directory: Path
    save_root: Path


def _expand(value: str, content: Path) -> str:
    return value.replace("{content}", str(content)).replace("{content_dir}", str(content.parent))


def create_launch_plan(
    content: str | os.PathLike[str],
    system_id: str,
    content_id: str,
    profile_id: str,
    registry: RuntimeRegistry,
    graphics: GraphicsPolicy,
    state_root: str | os.PathLike[str] = "/var/lib/pulsearc",
    installed_executables: set[str] | None = None,
) -> LaunchPlan:
    source = Path(content).resolve()
    try:
        source_mode = source.stat().st_mode
    except OSError as exc:
        raise FileNotFoundError(source) from exc
    if not (source.is_file() or stat.S_ISBLK(source_mode)):
        raise FileNotFoundError(source)
    candidates = registry.runner_candidates(system_id)
    if installed_executables is None:
        selected = candidates[0]
    else:
        selected = next((runner for runner in candidates if runner.executable in installed_executables), None)
        if selected is None:
            names = ", ".join(runner.runner_id for runner in candidates)
            raise RuntimeError(f"No installed runner for {system_id}; tried {names}")

    save_root = Path(state_root) / "profiles" / profile_id / "games" / content_id
    environment = {
        "PULSEARC_CONTENT_ID": content_id,
        "PULSEARC_PROFILE": profile_id,
        "PULSEARC_SAVE_ROOT": str(save_root),
        "XDG_CONFIG_HOME": str(save_root / "config"),
        "XDG_DATA_HOME": str(save_root / "data"),
        "XDG_CACHE_HOME": str(save_root / "cache"),
    }
    command = (selected.executable, *(_expand(arg, source) for arg in selected.arguments))
    if selected.kind == "windows":
        environment["WINEPREFIX"] = str(save_root / "wineprefix")
        if graphics.windows_d3d8_11 == "dxvk-modern":
            environment["PULSEARC_DXVK"] = "modern"
        elif graphics.windows_d3d8_11 == "dxvk-legacy":
            environment["PULSEARC_DXVK"] = "legacy-1.10.3"
        else:
            # WineD3D uses Wine's built-in Direct3D DLLs. "n" means native
            # Windows DLL and fails when a cart does not bundle those files.
            environment["WINEDLLOVERRIDES"] = "dxgi,d3d8,d3d9,d3d10core,d3d11=b"
            environment["PULSEARC_DXVK"] = "disabled"
    if graphics.session_backend == "gamescope":
        command = ("/usr/bin/gamescope", "--fullscreen", "--adaptive-sync", "--", *command)
    return LaunchPlan(selected.runner_id, command, environment, source.parent, save_root)
