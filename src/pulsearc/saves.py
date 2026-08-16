from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SaveRecord:
    profile_id: str
    content_id: str
    path: Path
    size: int
    modified: float


def game_save_root(state_root: Path, profile_id: str, content_id: str) -> Path:
    return state_root / "profiles" / profile_id / "games" / content_id


def inventory(state_root: Path, profile_id: str) -> list[SaveRecord]:
    games_root = state_root / "profiles" / profile_id / "games"
    if not games_root.exists():
        return []
    records: list[SaveRecord] = []
    for game in sorted(path for path in games_root.iterdir() if path.is_dir()):
        files = [path for path in game.rglob("*") if path.is_file()]
        records.append(SaveRecord(
            profile_id, game.name, game,
            sum(path.stat().st_size for path in files),
            max((path.stat().st_mtime for path in files), default=game.stat().st_mtime),
        ))
    return records


def backup_save(record: SaveRecord, backup_root: Path) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    destination = backup_root / record.profile_id / record.content_id / stamp
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(record.path, destination)
    manifest = {
        "profile_id": record.profile_id,
        "content_id": record.content_id,
        "created": stamp,
    }
    (destination / "pulsearc-save.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return destination


def restore_save(backup: Path, destination: Path) -> None:
    manifest = backup / "pulsearc-save.json"
    if not manifest.is_file():
        raise ValueError("not a PulseArc save backup")
    temporary = destination.with_name(destination.name + ".restore-new")
    previous = destination.with_name(destination.name + ".restore-old")
    if temporary.exists():
        shutil.rmtree(temporary)
    shutil.copytree(backup, temporary, ignore=shutil.ignore_patterns("pulsearc-save.json"))
    if previous.exists():
        shutil.rmtree(previous)
    if destination.exists():
        destination.replace(previous)
    temporary.replace(destination)

