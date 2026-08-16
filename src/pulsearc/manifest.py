from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


VALID_RENDERERS = {"auto", "vulkan", "opengl", "wined3d"}


@dataclass(frozen=True)
class PortableGame:
    title: str
    platform: str
    entrypoint: Path
    working_directory: Path
    arguments: tuple[str, ...] = field(default_factory=tuple)
    runner: str = "auto"
    renderer: str = "auto"
    controller_profile: Path | None = None
    serial: str = ""


def load_manifest(path: str | os.PathLike[str]) -> PortableGame:
    manifest = Path(path).resolve()
    root = manifest.parent
    with manifest.open("rb") as handle:
        document = tomllib.load(handle)
    game = document.get("game", {})
    title = str(game.get("title", "")).strip()
    platform = str(game.get("platform", "")).strip().lower()
    entry = str(game.get("entrypoint", "")).strip()
    if not title or not platform or not entry:
        raise ValueError("[game] title, platform, and entrypoint are required")
    entrypoint = (root / entry).resolve()
    try:
        entrypoint.relative_to(root)
    except ValueError as exc:
        raise ValueError("entrypoint must stay inside the portable game folder") from exc
    if not entrypoint.is_file():
        raise FileNotFoundError(entrypoint)
    working_value = str(game.get("working_directory", "."))
    working_directory = (root / working_value).resolve()
    try:
        working_directory.relative_to(root)
    except ValueError as exc:
        raise ValueError("working_directory must stay inside the portable game folder") from exc
    renderer = str(game.get("renderer", "auto")).lower()
    if renderer not in VALID_RENDERERS:
        raise ValueError(f"renderer must be one of {sorted(VALID_RENDERERS)}")
    arguments = tuple(str(value) for value in game.get("arguments", []))
    input_settings = document.get("input", {})
    controller_profile: Path | None = None
    controller_value = str(input_settings.get("antimicrox_profile", "")).strip()
    if controller_value:
        controller_profile = (root / controller_value).resolve()
        try:
            controller_profile.relative_to(root)
        except ValueError as exc:
            raise ValueError("antimicrox_profile must stay inside the portable game folder") from exc
        if controller_profile.suffix.lower() not in {".amgp", ".xml"}:
            raise ValueError("antimicrox_profile must be an .amgp or .xml profile")
        if not controller_profile.is_file():
            raise FileNotFoundError(controller_profile)
    return PortableGame(
        title=title,
        platform=platform,
        entrypoint=entrypoint,
        working_directory=working_directory,
        arguments=arguments,
        runner=str(game.get("runner", "auto")),
        renderer=renderer,
        controller_profile=controller_profile,
        serial=str(game.get("serial", "")).strip().replace("-", "").upper(),
    )
