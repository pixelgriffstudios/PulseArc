#!/usr/bin/env python3
"""Prepare a verified PulseArc internal-game import from user-owned archives."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from pulsearc.cheats import import_retroarch_cheats, save_cheats
from pulsearc.media import stable_content_id
from pulsearc.metadata import download_cover, libretro_cover_url, offline_cover_path


@dataclass(frozen=True)
class Game:
    archive: str
    title: str
    platform: str
    extension: str
    cheat_file: str = ""


GAMES = (
    Game("Tecmo Super Bowl (USA).zip", "Tecmo Super Bowl", "nes", ".nes", "Tecmo Super Bowl (USA).cht"),
    Game("Baseball Stars II (USA).zip", "Baseball Stars II", "nes", ".nes", "Baseball Stars II (USA).cht"),
    Game("Contra (USA).zip", "Contra", "nes", ".nes", "Contra (USA).cht"),
    Game("Double Dragon II - The Revenge (USA) (Rev 1).zip", "Double Dragon II: The Revenge", "nes", ".nes", "Double Dragon II - The Revenge (USA) (Rev 1).cht"),
    Game("DuckTales (USA).zip", "DuckTales", "nes", ".nes", "DuckTales (USA).cht"),
    Game("Kirby's Adventure (USA) (Rev 1).zip", "Kirby's Adventure", "nes", ".nes", "Kirby's Adventure (USA) (Rev 1).cht"),
    Game("Legend of Zelda, The (USA) (Rev 1).zip", "The Legend of Zelda", "nes", ".nes", "Legend of Zelda, The (USA) (Rev 1).cht"),
    Game("Metroid (USA).zip", "Metroid", "nes", ".nes", "Metroid (USA).cht"),
    Game("Mike Tyson's Punch-Out!! (Japan, USA) (En) (Rev 1).zip", "Mike Tyson's Punch-Out!!", "nes", ".nes", "Mike Tyson's Punch-Out!! (Japan, USA).cht"),
    Game("R.C. Pro-Am II (USA).zip", "R.C. Pro-Am II", "nes", ".nes", "R.C. Pro-Am II (USA).cht"),
    Game("Super Mario Bros. (World).zip", "Super Mario Bros.", "nes", ".nes", "Super Mario Bros. (World).cht"),
    Game("Super Mario Bros. 3 (USA) (Rev 1).zip", "Super Mario Bros. 3", "nes", ".nes", "Super Mario Bros. 3 (USA) (Rev 1).cht"),
    Game("Super Mario 64 (USA).zip", "Super Mario 64", "nintendo-64", ".z64", "Super Mario 64 (USA).cht"),
    Game("Mario Kart 64 (USA).zip", "Mario Kart 64", "nintendo-64", ".z64", "Mario Kart 64 (USA).cht"),
    Game("GoldenEye 007 (USA).zip", "GoldenEye 007", "nintendo-64", ".z64", "GoldenEye 007 (USA).cht"),
    Game("Pilotwings 64 (USA).zip", "Pilotwings 64", "nintendo-64", ".z64", "Pilotwings 64 (USA).cht"),
    Game("Beyond the Beyond (USA).7z", "Beyond the Beyond", "playstation", ".cue"),
    Game("Speed Devils (USA).7z", "Speed Devils", "dreamcast", ".gdi", "Speed Devils.cht"),
)


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def extract_zip_member(archive: Path, extension: str, destination: Path) -> Path:
    with zipfile.ZipFile(archive) as package:
        matches = [item for item in package.infolist() if not item.is_dir() and Path(item.filename).suffix.lower() == extension]
        if len(matches) != 1:
            raise ValueError(f"{archive.name}: expected one {extension} file, found {len(matches)}")
        item = matches[0]
        if Path(item.filename).is_absolute() or ".." in Path(item.filename).parts:
            raise ValueError(f"{archive.name}: unsafe archive member")
        output = destination / Path(item.filename).name
        with package.open(item) as source, output.open("wb") as target:
            shutil.copyfileobj(source, target)
        return output


def extract_ps1(archive: Path, destination: Path) -> Path:
    with tempfile.TemporaryDirectory() as temporary:
        result = subprocess.run(["tar", "-xf", str(archive), "-C", temporary], check=False)
        if result.returncode != 0:
            raise RuntimeError(f"could not extract {archive.name}")
        root = Path(temporary)
        cues = list(root.rglob("*.cue"))
        bins = list(root.rglob("*.bin"))
        if len(cues) != 1 or not bins:
            raise ValueError(f"{archive.name}: expected one CUE and at least one BIN")
        cue = destination / cues[0].name
        shutil.copy2(cues[0], cue)
        for source in bins:
            shutil.copy2(source, destination / source.name)
        return cue


def extract_dreamcast(archive: Path, destination: Path) -> Path:
    with tempfile.TemporaryDirectory() as temporary:
        result = subprocess.run(["tar", "-xf", str(archive), "-C", temporary], check=False)
        if result.returncode != 0:
            raise RuntimeError(f"could not extract {archive.name}")
        root = Path(temporary)
        gdis = list(root.rglob("*.gdi"))
        bins = list(root.rglob("*.bin"))
        if len(gdis) != 1 or not bins:
            raise ValueError(f"{archive.name}: expected one GDI and at least one BIN")
        for source in [*bins, *root.rglob("*.cue"), gdis[0]]:
            shutil.copy2(source, destination / source.name)
        return destination / gdis[0].name


def copy_cover(game: Game, offline: Path, destination: Path, ps1_cover: Path) -> None:
    if game.platform == "playstation" and ps1_cover.is_file():
        from PIL import Image
        with Image.open(ps1_cover) as image:
            image.convert("RGB").save(destination, format="PNG", optimize=True)
        return
    local = offline_cover_path(game.title, game.platform, offline)
    if local is None and game.title == "The Legend of Zelda":
        local = offline_cover_path("Legend of Zelda, The", game.platform, offline)
    if local is not None:
        shutil.copy2(local, destination)
        return
    url = libretro_cover_url(f"{game.title} (USA)", game.platform)
    if url:
        download_cover(url, destination)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--downloads", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--offline-artwork", type=Path, required=True)
    parser.add_argument("--cheat-database", type=Path, required=True)
    parser.add_argument("--ps1-cover", type=Path, required=True)
    args = parser.parse_args()

    if args.output.exists():
        shutil.rmtree(args.output)
    games_root = args.output / "games"
    cheats_root = args.output / "cheats"
    summary: list[dict[str, object]] = []
    cheat_folders = {
        "nes": args.cheat_database / "Nintendo - Nintendo Entertainment System",
        "nintendo-64": args.cheat_database / "Nintendo - Nintendo 64",
        "dreamcast": args.cheat_database / "Sega - Dreamcast",
    }
    for game in GAMES:
        archive = args.downloads / game.archive
        if not archive.is_file():
            raise FileNotFoundError(archive)
        game_root = games_root / game.platform / slug(game.title)
        content_root = game_root / (".disc" if game.platform in {"playstation", "dreamcast"} else "content")
        content_root.mkdir(parents=True)
        if archive.suffix.lower() == ".zip":
            entrypoint = extract_zip_member(archive, game.extension, content_root)
            runner = "retroarch-mesen" if game.platform == "nes" else "retroarch-mupen64plus-next"
            (game_root / "pulsearc.toml").write_text(
                "[game]\n"
                f'title = "{game.title}"\n'
                f'platform = "{game.platform}"\n'
                f'entrypoint = "content/{entrypoint.name}"\n'
                'working_directory = "content"\n'
                f'runner = "{runner}"\n',
                encoding="utf-8",
            )
        elif game.platform == "playstation":
            entrypoint = extract_ps1(archive, content_root)
            (game_root / "pulsearc.toml").write_text(
                "[game]\n"
                f'title = "{game.title}"\n'
                'platform = "playstation"\n'
                f'entrypoint = "{entrypoint.relative_to(game_root).as_posix()}"\n'
                f'working_directory = "{content_root.relative_to(game_root).as_posix()}"\n'
                'runner = "duckstation"\n',
                encoding="utf-8",
            )
        else:
            entrypoint = extract_dreamcast(archive, content_root)
            (game_root / "pulsearc.toml").write_text(
                "[game]\n"
                f'title = "{game.title}"\n'
                'platform = "dreamcast"\n'
                f'entrypoint = "{entrypoint.relative_to(game_root).as_posix()}"\n'
                f'working_directory = "{content_root.relative_to(game_root).as_posix()}"\n'
                'runner = "retroarch-flycast"\n',
                encoding="utf-8",
            )
        content_id = stable_content_id(entrypoint)
        copy_cover(game, args.offline_artwork, game_root / "cover.png", args.ps1_cover)
        cheat_count = 0
        if game.cheat_file:
            source = cheat_folders[game.platform] / game.cheat_file
            if source.is_file():
                cheats = import_retroarch_cheats(source)
                if cheats:
                    save_cheats(cheats_root / game.platform / f"{content_id}.json", cheats)
                cheat_count = len(cheats)
        summary.append({
            "title": game.title,
            "platform": game.platform,
            "content_id": content_id,
            "entrypoint": str(entrypoint.relative_to(args.output)),
            "cover": (game_root / "cover.png").is_file(),
            "cheats": cheat_count,
        })
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
