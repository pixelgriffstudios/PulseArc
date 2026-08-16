from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from .cheats import Cheat


HASH = re.compile(r"^(?:PPU|SPU|PRX|OVL)-[0-9a-fA-F]+:")
SERIAL = re.compile(r"^[A-Z]{4}[0-9]{5}$")


@dataclass
class _Patch:
    hash: str
    description: str
    games: list[tuple[str, str, list[str]]]


def _value(text: str) -> str:
    value = text.strip().rstrip(":").strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        value = value[1:-1].replace('\\"', '"')
    return value


def _versions(text: str) -> list[str]:
    match = re.search(r"\[([^]]*)\]", text)
    if not match:
        return ["All"]
    values = [_value(item) for item in match.group(1).split(",") if _value(item)]
    return values or ["All"]


def _anchor_games(lines: list[str]) -> dict[str, list[tuple[str, str, list[str]]]]:
    aliases: dict[str, list[tuple[str, str, list[str]]]] = {}
    alias = ""
    title = ""
    for line in lines:
        indent = len(line) - len(line.lstrip(" "))
        anchor = re.match(r"^  .+?:\s*&([A-Za-z0-9_.-]+)\s*$", line)
        if anchor:
            alias = anchor.group(1)
            aliases.setdefault(alias, [])
            title = ""
            continue
        if alias and indent <= 2 and line.strip():
            alias = ""
            title = ""
            continue
        if not alias:
            continue
        if indent == 4 and line.strip().endswith(":"):
            title = _value(line.strip())
        elif indent == 6 and title and ":" in line:
            serial, versions = line.strip().split(":", 1)
            serial = _value(serial)
            if SERIAL.fullmatch(serial):
                aliases[alias].append((title, serial, _versions(versions)))
    return aliases


def discover_patches(database: Path, serial: str) -> list[Cheat]:
    """Return RPCS3 patches applicable to one title ID, disabled by default."""
    if not database.is_file() or not SERIAL.fullmatch(serial.upper()):
        return []
    lines = database.read_text(encoding="utf-8", errors="replace").splitlines()
    aliases = _anchor_games(lines)
    patches: list[_Patch] = []
    current_hash = ""
    description = ""
    games: list[tuple[str, str, list[str]]] = []
    in_games = False
    game_title = ""

    def finish() -> None:
        nonlocal description, games
        if current_hash and description and games:
            patches.append(_Patch(current_hash, description, list(games)))
        description = ""
        games = []

    for line in lines:
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        if HASH.match(line):
            finish()
            current_hash = line.split(":", 1)[0]
            in_games = False
            game_title = ""
            continue
        if not current_hash:
            continue
        if indent == 0 and stripped and not HASH.match(line):
            finish()
            current_hash = ""
            in_games = False
            continue
        if indent == 2 and stripped.endswith(":"):
            finish()
            description = _value(stripped)
            in_games = False
            game_title = ""
            continue
        if not description:
            continue
        if indent == 4 and stripped.startswith("Games:"):
            in_games = True
            game_title = ""
            alias = stripped.partition("*")[2].split()[0] if "*" in stripped else ""
            if alias:
                games.extend(aliases.get(alias, []))
            continue
        if in_games and indent == 6 and stripped.endswith(":"):
            game_title = _value(stripped)
            continue
        if in_games and indent == 8 and game_title and ":" in stripped:
            game_serial, version_text = stripped.split(":", 1)
            game_serial = _value(game_serial)
            if SERIAL.fullmatch(game_serial):
                games.append((game_title, game_serial, _versions(version_text)))
            continue
        if in_games and indent <= 4 and stripped and not stripped.startswith("Games:"):
            in_games = False
            game_title = ""
    finish()

    wanted = serial.upper()
    result: list[Cheat] = []
    for patch in patches:
        matches = [game for game in patch.games if game[1] == wanted]
        if not matches:
            continue
        code = json.dumps({
            "hash": patch.hash,
            "description": patch.description,
            "games": [
                {"title": title, "serial": game_serial, "versions": versions}
                for title, game_serial, versions in matches
            ],
        }, separators=(",", ":"), sort_keys=True)
        identity = hashlib.sha1(f"{patch.hash}\0{patch.description}".encode()).hexdigest()[:12]
        result.append(Cheat(f"rpcs3-{identity}", patch.description, code, False))
    return result


def export_patch_config(cheats: list[Cheat], destination: Path) -> None:
    """Write RPCS3's patch_config.yml with only explicitly enabled patches."""
    tree: dict[str, dict[str, list[dict[str, object]]]] = {}
    for cheat in cheats:
        if not cheat.enabled:
            continue
        try:
            record = json.loads(cheat.code)
        except (TypeError, ValueError):
            continue
        patch_hash = str(record.get("hash", ""))
        description = str(record.get("description", ""))
        games = record.get("games", [])
        if not HASH.match(patch_hash + ":") or not description or not isinstance(games, list):
            continue
        tree.setdefault(patch_hash, {}).setdefault(description, []).extend(
            game for game in games if isinstance(game, dict)
        )
    lines: list[str] = []
    for patch_hash, descriptions in tree.items():
        lines.append(f"{json.dumps(patch_hash)}:")
        for description, games in descriptions.items():
            lines.append(f"  {json.dumps(description)}:")
            for game in games:
                title = str(game.get("title", "Unknown"))
                serial = str(game.get("serial", ""))
                versions = game.get("versions", ["All"])
                if not SERIAL.fullmatch(serial) or not isinstance(versions, list):
                    continue
                lines.append(f"    {json.dumps(title)}:")
                lines.append(f"      {json.dumps(serial)}:")
                for version in versions or ["All"]:
                    lines.append(f"        {json.dumps(str(version))}:")
                    lines.append("          Enabled: true")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text("\n".join(lines) + ("\n" if lines else "{}\n"), encoding="utf-8")
    temporary.replace(destination)
