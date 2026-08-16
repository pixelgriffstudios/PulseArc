from __future__ import annotations

import json
import re
import shutil
import tempfile
import tomllib
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MAX_PROFILES = 4
MAX_THEME_ARCHIVE = 256 * 1024 * 1024
THEME_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


@dataclass(frozen=True)
class Theme:
    theme_id: str
    name: str
    root: Path
    author: str = ""
    description: str = ""
    accent: str = "#50e8ff"
    secondary: str = "#ff55c8"
    text: str = "#ebf1ff"
    selection: str = "#50e8ff"
    muted: str = "#acbee6"
    positive: str = "#67d9b5"
    background: Path | None = None
    preview: Path | None = None
    boot_animation: Path | None = None
    music: Path | None = None
    font: Path | None = None
    sfx: Path | None = None
    menu_position: str = "left"
    profile_position: str = "right"
    background_style: str = ""
    panel: str = "#0a0d1f"
    panel_opacity: int = 68


def _asset(root: Path, value: Any, suffixes: set[str] | None = None) -> Path | None:
    text = str(value or "").strip().replace("\\", "/")
    if not text:
        return None
    candidate = (root / text).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    if not candidate.exists() or (suffixes and candidate.suffix.casefold() not in suffixes):
        return None
    return candidate


def _opacity(value: Any, default: int = 68) -> int:
    try:
        return max(0, min(255, int(value)))
    except (TypeError, ValueError):
        return default


def load_theme(folder: Path) -> Theme | None:
    manifest = folder / "theme.toml"
    try:
        with manifest.open("rb") as handle:
            document = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return None
    theme_id = str(document.get("id") or folder.name).strip().casefold()
    if not THEME_ID.fullmatch(theme_id):
        return None
    return Theme(
        theme_id=theme_id,
        name=str(document.get("name") or theme_id.replace("-", " ").title()),
        root=folder.resolve(),
        author=str(document.get("author") or ""),
        description=str(document.get("description") or ""),
        accent=str(document.get("accent") or "#50e8ff"),
        secondary=str(document.get("secondary") or "#ff55c8"),
        text=str(document.get("text") or "#ebf1ff"),
        selection=str(document.get("selection") or document.get("accent") or "#50e8ff"),
        muted=str(document.get("muted") or "#acbee6"),
        positive=str(document.get("positive") or document.get("accent") or "#67d9b5"),
        background=_asset(folder, document.get("background") or document.get("background_selection"), {".png", ".jpg", ".jpeg", ".webp", ".mp4", ".webm"}),
        preview=_asset(folder, document.get("preview"), {".png", ".jpg", ".jpeg", ".webp"}),
        boot_animation=_asset(folder, document.get("boot_animation"), {".mp4", ".webm"}),
        music=_asset(folder, document.get("music") or document.get("bgm_track"), {".mp3", ".ogg", ".wav", ".flac"}),
        font=_asset(folder, document.get("font") or document.get("font_selection"), {".ttf", ".otf"}),
        sfx=_asset(folder, document.get("sfx") or document.get("sfx_pack")),
        menu_position=str(document.get("menu_position") or "left").casefold(),
        profile_position=str(document.get("profile_position") or document.get("profile_badge_position") or "right").casefold(),
        background_style=str(document.get("background_style") or document.get("background_native") or "").strip().casefold(),
        panel=str(document.get("panel") or "#0a0d1f"),
        panel_opacity=_opacity(document.get("panel_opacity", 68)),
    )


def discover_themes(*roots: Path) -> list[Theme]:
    found: dict[str, Theme] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for folder in sorted((item for item in root.iterdir() if item.is_dir()), key=lambda item: item.name.casefold()):
            theme = load_theme(folder)
            if theme is not None:
                found[theme.theme_id] = theme
    return sorted(found.values(), key=lambda item: item.name.casefold())


def import_theme_archive(archive: Path, destination: Path) -> str:
    if not archive.is_file() or archive.suffix.casefold() != ".zip":
        raise ValueError("theme must be a ZIP archive")
    if archive.stat().st_size > MAX_THEME_ARCHIVE:
        raise ValueError("theme archive is too large")
    with tempfile.TemporaryDirectory(prefix="pulsearc-theme-") as temporary:
        staging = Path(temporary)
        with zipfile.ZipFile(archive) as package:
            total = 0
            for member in package.infolist():
                target = (staging / member.filename).resolve()
                try:
                    target.relative_to(staging.resolve())
                except ValueError as exc:
                    raise ValueError("unsafe path in theme archive") from exc
                total += member.file_size
                if total > MAX_THEME_ARCHIVE * 2:
                    raise ValueError("expanded theme is too large")
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with package.open(member) as source, target.open("wb") as output:
                        shutil.copyfileobj(source, output)
        candidates = [path.parent for path in staging.rglob("theme.toml")]
        themes = [theme for folder in candidates if (theme := load_theme(folder)) is not None]
        if len(themes) != 1:
            raise ValueError("theme archive must contain exactly one valid theme")
        theme = themes[0]
        target = destination / theme.theme_id
        replacement = destination / f".{theme.theme_id}.new"
        if replacement.exists():
            shutil.rmtree(replacement)
        shutil.copytree(theme.root, replacement)
        destination.mkdir(parents=True, exist_ok=True)
        if target.exists():
            shutil.rmtree(target)
        replacement.replace(target)
        return theme.theme_id


def load_profiles(path: Path) -> list[dict[str, str]]:
    defaults = [{"id": "default", "name": "Default Profile", "icon": "orb-01"}]
    try:
        values = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return defaults
    if not isinstance(values, list):
        return defaults
    result: list[dict[str, str]] = []
    for value in values[:MAX_PROFILES]:
        if not isinstance(value, dict):
            continue
        profile_id = str(value.get("id", "")).strip().casefold()
        if profile_id != "default" and not re.fullmatch(r"profile-[1-3]", profile_id):
            continue
        result.append({
            "id": profile_id,
            "name": str(value.get("name") or profile_id.replace("-", " ").title())[:28],
            "icon": str(value.get("icon") or "orb-01")[:32],
        })
    if not any(value["id"] == "default" for value in result):
        result.insert(0, defaults[0])
    return result[:MAX_PROFILES]


def save_profiles(path: Path, profiles: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(profiles[:MAX_PROFILES], indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
