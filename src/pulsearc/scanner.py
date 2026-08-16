from __future__ import annotations

import json
import os
import re
import shlex
import struct
from dataclasses import asdict, dataclass
from pathlib import Path

from .legacy_kzi import load_legacy_kzi
from .manifest import load_manifest
from .media import Detection, detect, stable_content_id


IGNORED_DIRECTORIES = {
    "$recycle.bin", "system volume information", ".trash-1000", ".spotlight-v100",
    ".fseventsd", "lost+found", "__macosx",
}
TRACK_PATTERN = re.compile(r'^\s*FILE\s+(?:"([^"]+)"|(\S+))', re.IGNORECASE)


@dataclass(frozen=True)
class LibraryEntry:
    content_id: str
    title: str
    platform: str
    runner: str
    media_kind: str
    path: str
    source_root: str
    read_only: bool
    cover_state: str = "pending"
    controller_profile: str = ""
    cover_path: str = ""
    serial: str = ""


def _read_param_sfo(path: Path) -> dict[str, str]:
    """Read the small subset of PARAM.SFO metadata used by PS3 discovery."""
    try:
        data = path.read_bytes()
        if len(data) < 20 or data[:4] != b"\x00PSF":
            return {}
        _version, keys_at, values_at, count = struct.unpack_from("<4I", data, 4)
        result: dict[str, str] = {}
        for index in range(min(count, 256)):
            offset = 20 + index * 16
            key_offset, _format, length, _maximum, value_offset = struct.unpack_from("<HHIII", data, offset)
            key_start = keys_at + key_offset
            key_end = data.find(b"\0", key_start)
            if key_end < key_start:
                continue
            key = data[key_start:key_end].decode("utf-8", errors="replace")
            value = data[values_at + value_offset:values_at + value_offset + length]
            result[key] = value.rstrip(b"\0").decode("utf-8", errors="replace")
        return result
    except (OSError, struct.error, ValueError):
        return {}


def _cue_tracks(cue: Path) -> set[Path]:
    tracks: set[Path] = set()
    try:
        lines = cue.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError:
        return tracks
    for line in lines:
        match = TRACK_PATTERN.match(line)
        if not match:
            continue
        candidate = (cue.parent / (match.group(1) or match.group(2))).resolve()
        try:
            candidate.relative_to(cue.parent.resolve())
        except ValueError:
            continue
        tracks.add(candidate)
    return tracks


def _gdi_tracks(gdi: Path) -> set[Path]:
    tracks: set[Path] = set()
    try:
        lines = gdi.read_text(encoding="utf-8-sig", errors="replace").splitlines()[1:]
    except OSError:
        return tracks
    for line in lines:
        try:
            fields = shlex.split(line)
        except ValueError:
            continue
        if len(fields) < 5:
            continue
        candidate = (gdi.parent / fields[4]).resolve()
        try:
            candidate.relative_to(gdi.parent.resolve())
        except ValueError:
            continue
        tracks.add(candidate)
    return tracks


def scan(root: str | os.PathLike[str]) -> list[LibraryEntry]:
    source_root = Path(root).resolve()
    if not source_root.is_dir():
        raise NotADirectoryError(source_root)

    def scan_priority(path: Path) -> tuple[int, str]:
        name = path.name.lower()
        if name == "pulsearc.toml" or path.suffix.lower() == ".kzi":
            return (0, str(path).lower())
        if path.suffix.lower() == ".gdi":
            return (1, str(path).lower())
        if path.suffix.lower() == ".cue":
            return (2, str(path).lower())
        return (3, str(path).lower())

    files = sorted(
        (path for path in source_root.rglob("*") if path.is_file()),
        key=scan_priority,
    )
    consumed: set[Path] = set()
    entries: list[LibraryEntry] = []
    for path in files:
        parts = path.relative_to(source_root).parts
        if any(part.lower() in IGNORED_DIRECTORIES or part.startswith(".") for part in parts):
            continue
        resolved = path.resolve()
        if resolved in consumed:
            continue
        if (
            path.name.upper() == "EBOOT.BIN"
            and path.parent.name.upper() == "USRDIR"
            and path.parent.parent.name.upper() == "PS3_GAME"
        ):
            game_root = path.parent.parent.parent
            metadata = _read_param_sfo(path.parent.parent / "PARAM.SFO")
            entries.append(LibraryEntry(
                stable_content_id(path), metadata.get("TITLE", game_root.name), "playstation-3", "rpcs3",
                "disc-image", str(path), str(source_root), not os.access(path, os.W_OK),
                serial=metadata.get("TITLE_ID", "").replace("-", "").upper(),
            ))
            continue
        if path.suffix.lower() == ".kzi":
            try:
                game = load_legacy_kzi(path)
            except (OSError, ValueError):
                continue
            entries.append(LibraryEntry(
                game.content_id, game.title, game.platform, game.runner,
                game.media_kind, str(game.entrypoint), str(source_root), True,
                "local" if game.icon else "pending",
                str(game.controller_profile) if game.controller_profile else "",
                str(game.icon) if game.icon else "",
            ))
            consumed.add(game.entrypoint.resolve())
            if game.icon:
                consumed.add(game.icon.resolve())
            continue
        if path.name.lower() == "pulsearc.toml":
            try:
                game = load_manifest(path)
            except (OSError, ValueError):
                continue
            local_cover = next(
                (candidate for candidate in (path.parent / "cover.png", path.parent / "icon.png")
                 if candidate.is_file()),
                None,
            )
            if game.platform == "windows":
                media_kind = "windows-program"
            else:
                try:
                    media_kind = detect(game.entrypoint).media_kind
                except (OSError, ValueError):
                    media_kind = "rom"
            entries.append(LibraryEntry(
                stable_content_id(game.entrypoint), game.title, game.platform, game.runner,
                media_kind, str(game.entrypoint), str(source_root), not os.access(path, os.W_OK),
                "local" if local_cover else "pending",
                str(game.controller_profile) if game.controller_profile else "",
                str(local_cover) if local_cover else "",
                game.serial,
            ))
            if local_cover:
                consumed.add(local_cover.resolve())
            consumed.add(game.entrypoint.resolve())
            if game.entrypoint.suffix.lower() == ".cue":
                consumed.update(_cue_tracks(game.entrypoint))
            elif game.entrypoint.suffix.lower() == ".gdi":
                consumed.update(_gdi_tracks(game.entrypoint))
                for cue in game.entrypoint.parent.glob("*.cue"):
                    consumed.add(cue.resolve())
                    consumed.update(_cue_tracks(cue))
            continue
        try:
            result: Detection = detect(path)
        except (OSError, ValueError):
            continue
        if result.platform == "unknown":
            continue
        if path.suffix.lower() == ".cue":
            consumed.update(_cue_tracks(path))
        elif path.suffix.lower() == ".gdi":
            consumed.update(_gdi_tracks(path))
            for cue in path.parent.glob("*.cue"):
                consumed.add(cue.resolve())
                consumed.update(_cue_tracks(cue))
        entries.append(LibraryEntry(
            stable_content_id(path), path.stem, result.platform, result.runner,
            result.media_kind, str(path), str(source_root), not os.access(path, os.W_OK),
        ))
    return entries


def write_index(entries: list[LibraryEntry], destination: str | os.PathLike[str]) -> None:
    output = Path(destination)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps([asdict(entry) for entry in entries], indent=2), encoding="utf-8")
    temporary.replace(output)
