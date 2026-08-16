from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from .media import detect, stable_content_id


MAX_KZI_SIZE = 64 * 1024
SAFE_LEGACY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


@dataclass(frozen=True)
class LegacyCart:
    content_id: str
    title: str
    platform: str
    runner: str
    media_kind: str
    entrypoint: Path
    icon: Path | None
    runtime: str
    controller_profile: Path | None


# Kazeta runtime releases have used several versioned names for the same
# platform. PulseArc intentionally maps the family name, not a particular
# legacy runtime image, to its maintained internal runner.
RUNTIME_FAMILIES: tuple[tuple[str, str, str, str], ...] = (
    ("windows", "windows", "wine-ge", "windows-program"),
    ("snes", "snes", "retroarch:snes9x", "rom"),
    ("nes", "nes", "retroarch:mesen", "rom"),
    ("n64", "nintendo-64", "retroarch:mupen64plus-next", "rom"),
    ("genesis", "mega-drive", "retroarch:genesis-plus-gx", "rom"),
    ("megadrive", "mega-drive", "retroarch:genesis-plus-gx", "rom"),
    ("gba", "gameboy-advance", "retroarch:mgba", "rom"),
    ("gameboy", "gameboy", "retroarch:mgba", "rom"),
    ("ps1", "playstation", "duckstation", "disc-image"),
    ("playstation", "playstation", "duckstation", "disc-image"),
    ("ps2", "playstation-2", "pcsx2", "disc-image"),
    ("pcsx2", "playstation-2", "pcsx2", "disc-image"),
    ("psp", "psp", "ppsspp", "disc-image"),
    ("dolphin", "dolphin-disc", "dolphin", "disc-image"),
    ("gamecube", "gamecube", "dolphin", "disc-image"),
    ("wii", "wii", "dolphin", "disc-image"),
)


def _inside(root: Path, value: str, field: str) -> Path:
    candidate = (root / value.replace("\\", "/")).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"legacy {field} must stay inside the cartridge") from exc
    return candidate


def _runtime_target(runtime: str) -> tuple[str, str, str]:
    normalized = re.sub(r"[^a-z0-9]+", "", runtime.lower())
    for family, platform, runner, media_kind in RUNTIME_FAMILIES:
        if normalized.startswith(family):
            return platform, runner, media_kind
    raise ValueError(f"unsupported legacy runtime: {runtime}")


def load_legacy_kzi(path: str | os.PathLike[str]) -> LegacyCart:
    manifest = Path(path).resolve()
    if manifest.stat().st_size > MAX_KZI_SIZE:
        raise ValueError("legacy cart metadata is unexpectedly large")
    root = manifest.parent.resolve()
    values: dict[str, str] = {}
    for raw_line in manifest.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", ";")) or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip().lower()] = value.strip()

    title = values.get("name", "").strip()
    executable = values.get("exec", "").strip()
    runtime = values.get("runtime", "").strip()
    if not title or not executable or not runtime:
        raise ValueError("legacy cart requires Name, Exec, and Runtime")

    entrypoint = _inside(root, executable, "Exec")
    if not entrypoint.is_file():
        raise FileNotFoundError(entrypoint)

    platform, runner, media_kind = _runtime_target(runtime)
    detected = detect(entrypoint)
    if detected.platform not in {"unknown", "optical-disc", "dolphin-disc"}:
        platform, runner, media_kind = detected.platform, detected.runner, detected.media_kind

    icon: Path | None = None
    icon_value = values.get("icon", "").strip()
    if icon_value:
        candidate = _inside(root, icon_value, "Icon")
        if candidate.is_file():
            icon = candidate

    controller_profile: Path | None = None
    controller_value = (values.get("controller") or values.get("antimicrox") or "").strip()
    if controller_value:
        candidate = _inside(root, controller_value, "Controller")
        if candidate.suffix.lower() not in {".amgp", ".xml"}:
            raise ValueError("legacy Controller must be an AntiMicroX .amgp or .xml profile")
        if not candidate.is_file():
            raise FileNotFoundError(candidate)
        controller_profile = candidate

    legacy_id = values.get("id", "").strip()
    content_id = legacy_id if SAFE_LEGACY_ID.fullmatch(legacy_id) else stable_content_id(entrypoint)
    return LegacyCart(
        content_id=content_id,
        title=title,
        platform=platform,
        runner=runner,
        media_kind=media_kind,
        entrypoint=entrypoint,
        icon=icon,
        runtime=runtime,
        controller_profile=controller_profile,
    )
