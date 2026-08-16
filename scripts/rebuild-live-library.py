#!/usr/bin/env python3
"""Rebuild the live PulseArc library index with the user-overlay core."""

from __future__ import annotations

import argparse
import os

import paramiko


REMOTE_HELPER = b'''from pathlib import Path\nfrom pulsearc.media_daemon import rebuild_library\nrebuild_library([], Path("/run/pulsearc/library.json"))\n'''


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("host")
    parser.add_argument("--user", default="gamer")
    parser.add_argument("--hide-disc-tracks", action="store_true")
    parser.add_argument("--write-rom-manifests", action="store_true")
    args = parser.parse_args()
    password = os.environ.get("PULSEARC_REMOTE_PASSWORD")
    if not password:
        raise SystemExit("PULSEARC_REMOTE_PASSWORD is required")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(args.host, username=args.user, password=password, allow_agent=False,
                   look_for_keys=False, timeout=15, banner_timeout=15, auth_timeout=15)
    try:
        with client.open_sftp() as sftp:
            if args.write_rom_manifests:
                games = (
                    ("nes", "tecmo-super-bowl", "Tecmo Super Bowl", "Tecmo Super Bowl (USA).nes"),
                    ("nes", "baseball-stars-ii", "Baseball Stars II", "Baseball Stars II (USA).nes"),
                    ("nes", "contra", "Contra", "Contra (USA).nes"),
                    ("nes", "double-dragon-ii-the-revenge", "Double Dragon II: The Revenge", "Double Dragon II - The Revenge (USA) (Rev 1).nes"),
                    ("nes", "ducktales", "DuckTales", "DuckTales (USA).nes"),
                    ("nes", "kirby-s-adventure", "Kirby's Adventure", "Kirby's Adventure (USA) (Rev 1).nes"),
                    ("nes", "the-legend-of-zelda", "The Legend of Zelda", "Legend of Zelda, The (USA) (Rev 1).nes"),
                    ("nes", "metroid", "Metroid", "Metroid (USA).nes"),
                    ("nes", "mike-tyson-s-punch-out", "Mike Tyson's Punch-Out!!", "Mike Tyson's Punch-Out!! (Japan, USA) (En) (Rev 1).nes"),
                    ("nes", "r-c-pro-am-ii", "R.C. Pro-Am II", "R.C. Pro-Am II (USA).nes"),
                    ("nes", "super-mario-bros", "Super Mario Bros.", "Super Mario Bros. (World).nes"),
                    ("nes", "super-mario-bros-3", "Super Mario Bros. 3", "Super Mario Bros. 3 (USA) (Rev 1).nes"),
                    ("nintendo-64", "super-mario-64", "Super Mario 64", "Super Mario 64 (USA).z64"),
                    ("nintendo-64", "mario-kart-64", "Mario Kart 64", "Mario Kart 64 (USA).z64"),
                    ("nintendo-64", "goldeneye-007", "GoldenEye 007", "GoldenEye 007 (USA).z64"),
                    ("nintendo-64", "pilotwings-64", "Pilotwings 64", "Pilotwings 64 (USA).z64"),
                )
                for platform, slug, title, entrypoint in games:
                    root = f"/var/lib/pulsearc/library/games/{platform}/{slug}"
                    runner = "retroarch-mesen" if platform == "nes" else "retroarch-mupen64plus-next"
                    manifest = (
                        "[game]\n"
                        f'title = "{title}"\n'
                        f'platform = "{platform}"\n'
                        f'entrypoint = "content/{entrypoint}"\n'
                        'working_directory = "content"\n'
                        f'runner = "{runner}"\n'
                    )
                    with sftp.open(f"{root}/pulsearc.toml", "w") as output:
                        output.write(manifest)
            if args.hide_disc_tracks:
                disc_games = (
                    (
                        "/var/lib/pulsearc/library/games/playstation/beyond-the-beyond",
                        "Beyond the Beyond",
                        "playstation",
                        "Beyond the Beyond (USA).cue",
                        "duckstation",
                    ),
                    (
                        "/var/lib/pulsearc/library/games/dreamcast/speed-devils",
                        "Speed Devils",
                        "dreamcast",
                        "Speed Devils (USA).gdi",
                        "retroarch-flycast",
                    ),
                )
                for root, title, platform, entrypoint, runner in disc_games:
                    try:
                        sftp.stat(f"{root}/content")
                    except OSError:
                        pass
                    else:
                        sftp.rename(f"{root}/content", f"{root}/.disc")
                    manifest = (
                        "[game]\n"
                        f'title = "{title}"\n'
                        f'platform = "{platform}"\n'
                        f'entrypoint = ".disc/{entrypoint}"\n'
                        'working_directory = ".disc"\n'
                        f'runner = "{runner}"\n'
                    )
                    with sftp.open(f"{root}/pulsearc.toml", "w") as output:
                        output.write(manifest)
            with sftp.open("/home/gamer/.cache/pulsearc-rebuild-library.py", "wb") as output:
                output.write(REMOTE_HELPER)
        command = (
            "PYTHONPATH=$HOME/.local/share/pulsearc/core /usr/bin/python "
            "$HOME/.cache/pulsearc-rebuild-library.py && "
            "rm -f $HOME/.cache/pulsearc-rebuild-library.py && "
            "grep -c content_id /run/pulsearc/library.json"
        )
        _stdin, stdout, stderr = client.exec_command(command, timeout=900)
        print(stdout.read().decode("utf-8", errors="replace"), end="")
        print(stderr.read().decode("utf-8", errors="replace"), end="")
        return stdout.channel.recv_exit_status()
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
