from __future__ import annotations

import tomllib
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


MAX_ANTIMICROX_PROFILE_SIZE = 2 * 1024 * 1024
BLOCKED_ANTIMICROX_MODES = {"execute", "loadprofile"}


def validate_antimicrox_profile(path: str | Path) -> Path:
    """Validate a cart-supplied mapper profile as input-only data.

    AntiMicroX also supports launching programs and loading arbitrary profiles.
    Portable media does not receive either capability.
    """
    profile = Path(path).resolve()
    if profile.suffix.lower() not in {".amgp", ".xml"} or not profile.is_file():
        raise ValueError("AntiMicroX profile is missing or unsupported")
    if profile.stat().st_size > MAX_ANTIMICROX_PROFILE_SIZE:
        raise ValueError("AntiMicroX profile is unexpectedly large")
    try:
        document = ET.parse(profile)
    except ET.ParseError as exc:
        raise ValueError("AntiMicroX profile is not valid XML") from exc
    if document.getroot().tag.lower() not in {"gamecontroller", "joystick", "antimicroconfig"}:
        raise ValueError("unrecognized AntiMicroX profile root")
    modes = {
        (element.text or "").strip().lower()
        for element in document.iter()
        if element.tag.lower() == "mode"
    }
    blocked = sorted(modes & BLOCKED_ANTIMICROX_MODES)
    if blocked:
        raise ValueError(f"unsafe AntiMicroX mode is not allowed: {', '.join(blocked)}")
    return profile


@dataclass(frozen=True)
class ControllerProfile:
    profile_id: str
    name: str
    buttons: dict[str, str]
    axes: dict[str, str]
    hotkeys: dict[str, tuple[str, ...]]


def load_controller_profile(path: str | Path) -> ControllerProfile:
    with Path(path).open("rb") as handle:
        doc = tomllib.load(handle)
    profile_id = str(doc.get("id", "")).strip()
    name = str(doc.get("name", "")).strip()
    if not profile_id or not name:
        raise ValueError("controller profile requires id and name")
    return ControllerProfile(
        profile_id=profile_id,
        name=name,
        buttons={str(key): str(value) for key, value in doc.get("buttons", {}).items()},
        axes={str(key): str(value) for key, value in doc.get("axes", {}).items()},
        hotkeys={str(key): tuple(str(item) for item in value) for key, value in doc.get("hotkeys", {}).items()},
    )


def profile_search_order(state_root: Path, profile_id: str, system_id: str, content_id: str) -> tuple[Path, ...]:
    """Return override order from most specific to universal default."""
    player = state_root / "profiles" / profile_id / "controllers"
    return (
        player / "games" / f"{content_id}.toml",
        player / "systems" / f"{system_id}.toml",
        player / "default.toml",
        Path("/usr/share/pulsearc/controllers/xbox-default.toml"),
    )
