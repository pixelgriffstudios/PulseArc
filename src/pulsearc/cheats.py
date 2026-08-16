from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Cheat:
    cheat_id: str
    name: str
    code: str
    enabled: bool = False


def cheat_file(state_root: Path, profile_id: str, system_id: str, content_id: str) -> Path:
    return state_root / "profiles" / profile_id / "cheats" / system_id / f"{content_id}.json"


def load_cheats(path: Path) -> list[Cheat]:
    if not path.exists():
        return []
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, list):
        raise ValueError("cheat file must contain a list")
    return [Cheat(
        cheat_id=str(item["id"]),
        name=str(item["name"]),
        code=str(item["code"]),
        enabled=bool(item.get("enabled", False)),
    ) for item in document]


def save_cheats(path: Path, cheats: list[Cheat]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [
        {"id": item.cheat_id, "name": item.name, "code": item.code, "enabled": item.enabled}
        for item in cheats
    ]
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary.replace(path)


RETROARCH_FIELD = re.compile(r'^cheat(\d+)_(desc|code)\s*=\s*"(.*)"\s*$')


def import_retroarch_cheats(path: Path) -> list[Cheat]:
    """Read a Libretro ``.cht`` file with every imported code disabled.

    PulseArc never trusts an upstream enabled flag. This makes importing a
    database safe: a player must explicitly opt in to each code in the UI.
    """
    values: dict[int, dict[str, str]] = {}
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        match = RETROARCH_FIELD.match(line.strip())
        if match is None:
            continue
        index = int(match.group(1))
        values.setdefault(index, {})[match.group(2)] = match.group(3).replace("'", '"')
    cheats: list[Cheat] = []
    for index in sorted(values):
        item = values[index]
        name = item.get("desc", "").strip()
        code = item.get("code", "").strip()
        if name and code:
            cheat_id = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-") or f"cheat-{index}"
            cheats.append(Cheat(f"{cheat_id}-{index}", name, code, False))
    return cheats


def import_duckstation_cheats(path: Path) -> list[Cheat]:
    """Import DuckStation/CHTDB GameShark sections, disabled by default."""
    cheats: list[Cheat] = []
    name = ""
    code_lines: list[str] = []

    def commit() -> None:
        nonlocal name, code_lines
        if name and code_lines:
            base = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-") or "cheat"
            cheats.append(Cheat(f"{base}-{len(cheats)}", name, "\n".join(code_lines), False))
        code_lines = []

    for raw_line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = raw_line.strip()
        if line.startswith("[") and line.endswith("]"):
            commit()
            name = line[1:-1].strip()
            continue
        if not name or not line or line.startswith((";", "#")):
            continue
        if "=" in line and line.partition("=")[0].strip() in {"Type", "Activation", "Option"}:
            # Options are retained in CHTDB but require an interactive value
            # selector. PulseArc imports the concrete GameShark codes only.
            continue
        if re.fullmatch(r"[0-9A-Fa-f?]{8}\s+[0-9A-Fa-f?]{4,8}", line):
            if "?" not in line:
                code_lines.append(line.upper())
    commit()
    return cheats


def set_cheat_enabled(path: Path, index: int, enabled: bool | None = None) -> Cheat:
    cheats = load_cheats(path)
    if not 0 <= index < len(cheats):
        raise IndexError(index)
    current = cheats[index]
    replacement = Cheat(
        current.cheat_id,
        current.name,
        current.code,
        not current.enabled if enabled is None else bool(enabled),
    )
    cheats[index] = replacement
    save_cheats(path, cheats)
    return replacement
