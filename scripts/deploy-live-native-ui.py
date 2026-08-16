#!/usr/bin/env python3
"""Install the native shell into a development console's user-owned paths."""

from __future__ import annotations

import argparse
import hashlib
import os
import shlex
import sys
from pathlib import Path

import paramiko


ROOT = Path(__file__).resolve().parents[1]
FILES = {
    ROOT / "native-ui" / "pulsearc_ui.py": "/home/gamer/.local/share/pulsearc/native-ui/pulsearc_ui.py.new",
    ROOT / "native-ui" / "pulsearc_tv.py": "/home/gamer/.local/share/pulsearc/native-ui/pulsearc_tv.py.new",
    ROOT / "native-ui" / "pulsearc_network.py": "/home/gamer/.local/share/pulsearc/native-ui/pulsearc_network.py.new",
    ROOT / "native-ui" / "pulsearc_3d_library.py": "/home/gamer/.local/share/pulsearc/native-ui/pulsearc_3d_library.py.new",
    ROOT / "native-ui" / "assets" / "parking-lot-dusk.png": "/home/gamer/.local/share/pulsearc/native-ui/assets/parking-lot-dusk.png.new",
    ROOT / "native-ui" / "assets" / "ceiling-white.webp": "/home/gamer/.local/share/pulsearc/native-ui/assets/ceiling-white.webp.new",
    ROOT / "native-ui" / "assets" / "ceiling-lights.jpg": "/home/gamer/.local/share/pulsearc/native-ui/assets/ceiling-lights.jpg.new",
    ROOT / "native-ui" / "assets" / "carpet-dark.webp": "/home/gamer/.local/share/pulsearc/native-ui/assets/carpet-dark.webp.new",
    ROOT / "native-ui" / "assets" / "wall-yellow-plaster.webp": "/home/gamer/.local/share/pulsearc/native-ui/assets/wall-yellow-plaster.webp.new",
    ROOT / "native-ui" / "assets" / "wall-yellow-brick.webp": "/home/gamer/.local/share/pulsearc/native-ui/assets/wall-yellow-brick.webp.new",
    ROOT / "native-ui" / "assets" / "wall-blue-brick.webp": "/home/gamer/.local/share/pulsearc/native-ui/assets/wall-blue-brick.webp.new",
    ROOT / "native-ui" / "assets" / "plaza-asphalt.png": "/home/gamer/.local/share/pulsearc/native-ui/assets/plaza-asphalt.png.new",
    ROOT / "native-ui" / "assets" / "plaza-sky-mountains.png": "/home/gamer/.local/share/pulsearc/native-ui/assets/plaza-sky-mountains.png.new",
    ROOT / "native-ui" / "assets" / "plaza-sky-clouds.png": "/home/gamer/.local/share/pulsearc/native-ui/assets/plaza-sky-clouds.png.new",
    ROOT / "native-ui" / "assets" / "plaza-lounge-01.mp3": "/home/gamer/.local/share/pulsearc/native-ui/assets/plaza-lounge-01.mp3.new",
    ROOT / "native-ui" / "assets" / "plaza-lounge-02.mp3": "/home/gamer/.local/share/pulsearc/native-ui/assets/plaza-lounge-02.mp3.new",
    ROOT / "live-update" / "pulsearc-session": "/home/gamer/.local/bin/pulsearc-session.new",
    ROOT / "live-update" / "pulsearc-kodi-dvd": "/home/gamer/.local/bin/pulsearc-kodi-dvd.new",
    ROOT / "live-update" / "pulsearc-vlc": "/home/gamer/.local/bin/pulsearc-vlc.new",
    ROOT / "archiso" / "airootfs" / "usr" / "local" / "bin" / "pulsearc-audio-select": "/home/gamer/.local/bin/pulsearc-audio-select.new",
    ROOT / "live-update" / "xinitrc": "/home/gamer/.xinitrc.pulsearc-new",
}

for model_root in (
    ROOT / "native-ui" / "assets" / "models" / "kenney-car-kit",
    ROOT / "native-ui" / "assets" / "models" / "quaternius-people",
    ROOT / "native-ui" / "assets" / "models" / "kenney-pets",
    ROOT / "native-ui" / "assets" / "models" / "pulsearc-community" / "passenger-cars",
    ROOT / "native-ui" / "assets" / "models" / "pulsearc-community" / "retro-office",
    ROOT / "native-ui" / "assets" / "models" / "pulsearc-community" / "dvd-case",
):
    for model_file in model_root.iterdir():
        if model_file.is_file():
            relative = model_file.relative_to(ROOT / "native-ui" / "assets").as_posix()
            FILES[model_file] = f"/home/gamer/.local/share/pulsearc/native-ui/assets/{relative}.new"

for model_file in (
    ROOT / "native-ui" / "assets" / "models" / "pulsearc-community" / "asset-manifest.json",
    ROOT / "native-ui" / "assets" / "models" / "pulsearc-community" / "ASSET-CREDITS.md",
):
    relative = model_file.relative_to(ROOT / "native-ui" / "assets").as_posix()
    FILES[model_file] = f"/home/gamer/.local/share/pulsearc/native-ui/assets/{relative}.new"

private_actor_root = ROOT / ".private-assets" / "plaza-actors"
if private_actor_root.is_dir():
    for model_file in private_actor_root.iterdir():
        if model_file.is_file():
            FILES[model_file] = (
                "/home/gamer/.local/share/pulsearc/native-ui/assets/models/"
                f"pulsearc-local/{model_file.name}.new"
            )


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def remote(client: paramiko.SSHClient, command: str, timeout: int = 60) -> str:
    _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    output = stdout.read().decode("utf-8", errors="replace")
    error = stderr.read().decode("utf-8", errors="replace")
    status = stdout.channel.recv_exit_status()
    if status:
        raise RuntimeError(f"remote command failed ({status}): {command}\n{output}\n{error}")
    return output + error


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("host")
    parser.add_argument("--user", default="gamer")
    args = parser.parse_args()
    password = os.environ.get("PULSEARC_REMOTE_PASSWORD")
    if not password:
        raise SystemExit("PULSEARC_REMOTE_PASSWORD is required")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        args.host,
        username=args.user,
        password=password,
        timeout=15,
        banner_timeout=15,
        auth_timeout=15,
        allow_agent=False,
        look_for_keys=False,
    )
    try:
        remote(
            client,
            "install -d -m 0755 ~/.local/bin ~/.local/share/pulsearc/native-ui "
            "~/.local/share/pulsearc/native-ui/assets "
            "~/.local/share/pulsearc/native-ui/assets/models/kenney-car-kit "
            "~/.local/share/pulsearc/native-ui/assets/models/quaternius-people "
            "~/.local/share/pulsearc/native-ui/assets/models/kenney-pets "
            "~/.local/share/pulsearc/native-ui/assets/models/pulsearc-community/passenger-cars "
            "~/.local/share/pulsearc/native-ui/assets/models/pulsearc-community/retro-office "
            "~/.local/share/pulsearc/native-ui/assets/models/pulsearc-community/dvd-case "
            "~/.local/share/pulsearc/native-ui/assets/models/pulsearc-local "
            "~/.local/share/pulsearc/rollback",
        )
        with client.open_sftp() as sftp:
            for local, target in FILES.items():
                sftp.put(str(local), target)
                sftp.chmod(target, 0o755)
        for local, target in FILES.items():
            actual = remote(client, f"sha256sum {shlex.quote(target)}").split()[0]
            if actual != sha256(local):
                raise RuntimeError(f"checksum mismatch: {target}")

        remote(
            client,
            "stamp=$(date +%Y%m%d-%H%M%S); "
            "backup=$HOME/.local/share/pulsearc/rollback/$stamp; mkdir -p \"$backup\"; "
            "cp -a ~/.xinitrc \"$backup/xinitrc\" 2>/dev/null || true; "
            "cp -a ~/.local/bin/pulsearc-session \"$backup/pulsearc-session\" 2>/dev/null || true; "
            "cp -a ~/.local/bin/pulsearc-kodi-dvd \"$backup/pulsearc-kodi-dvd\" 2>/dev/null || true; "
            "cp -a ~/.local/bin/pulsearc-vlc \"$backup/pulsearc-vlc\" 2>/dev/null || true; "
            "cp -a ~/.local/bin/pulsearc-audio-select \"$backup/pulsearc-audio-select\" 2>/dev/null || true; "
            "cp -a ~/.local/share/pulsearc/native-ui/pulsearc_ui.py \"$backup/pulsearc_ui.py\" 2>/dev/null || true; "
            "cp -a ~/.local/share/pulsearc/native-ui/pulsearc_tv.py \"$backup/pulsearc_tv.py\" 2>/dev/null || true; "
            "cp -a ~/.local/share/pulsearc/native-ui/pulsearc_network.py \"$backup/pulsearc_network.py\" 2>/dev/null || true; "
            "cp -a ~/.local/share/pulsearc/native-ui/pulsearc_3d_library.py \"$backup/pulsearc_3d_library.py\" 2>/dev/null || true; "
            "cp -a ~/.local/share/pulsearc/native-ui/assets/parking-lot-dusk.png \"$backup/parking-lot-dusk.png\" 2>/dev/null || true; "
            "mv ~/.xinitrc.pulsearc-new ~/.xinitrc; "
            "mv ~/.local/bin/pulsearc-session.new ~/.local/bin/pulsearc-session; "
            "mv ~/.local/bin/pulsearc-kodi-dvd.new ~/.local/bin/pulsearc-kodi-dvd; "
            "mv ~/.local/bin/pulsearc-vlc.new ~/.local/bin/pulsearc-vlc; "
            "mv ~/.local/bin/pulsearc-audio-select.new ~/.local/bin/pulsearc-audio-select; "
            "mv ~/.local/share/pulsearc/native-ui/pulsearc_ui.py.new "
            "~/.local/share/pulsearc/native-ui/pulsearc_ui.py; "
            "mv ~/.local/share/pulsearc/native-ui/pulsearc_tv.py.new "
            "~/.local/share/pulsearc/native-ui/pulsearc_tv.py; "
            "mv ~/.local/share/pulsearc/native-ui/pulsearc_network.py.new "
            "~/.local/share/pulsearc/native-ui/pulsearc_network.py; "
            "mv ~/.local/share/pulsearc/native-ui/pulsearc_3d_library.py.new "
            "~/.local/share/pulsearc/native-ui/pulsearc_3d_library.py; "
            "for asset in parking-lot-dusk.png ceiling-white.webp ceiling-lights.jpg carpet-dark.webp "
            "wall-yellow-plaster.webp wall-yellow-brick.webp wall-blue-brick.webp "
            "plaza-asphalt.png plaza-sky-mountains.png plaza-sky-clouds.png plaza-lounge-01.mp3 plaza-lounge-02.mp3; do "
            "mv ~/.local/share/pulsearc/native-ui/assets/$asset.new "
            "~/.local/share/pulsearc/native-ui/assets/$asset; done; "
            "for group in kenney-car-kit quaternius-people kenney-pets "
            "pulsearc-community/passenger-cars pulsearc-community/retro-office "
            "pulsearc-community/dvd-case pulsearc-community; do "
            "for model in ~/.local/share/pulsearc/native-ui/assets/models/$group/*.new; do "
            "[ -e \"$model\" ] || continue; mv \"$model\" \"${model%.new}\"; done; done; "
            "for model in ~/.local/share/pulsearc/native-ui/assets/models/pulsearc-local/*.new; do "
            "[ -e \"$model\" ] || continue; mv \"$model\" \"${model%.new}\"; done; "
            "chmod 0755 ~/.xinitrc ~/.local/bin/pulsearc-session ~/.local/bin/pulsearc-kodi-dvd ~/.local/bin/pulsearc-vlc ~/.local/bin/pulsearc-audio-select "
            "~/.local/share/pulsearc/native-ui/pulsearc_ui.py "
            "~/.local/share/pulsearc/native-ui/pulsearc_tv.py "
            "~/.local/share/pulsearc/native-ui/pulsearc_network.py "
            "~/.local/share/pulsearc/native-ui/pulsearc_3d_library.py; "
            "find ~/.local/share/pulsearc/native-ui/assets -maxdepth 1 -type f -exec chmod 0644 {} +; "
            "find ~/.local/share/pulsearc/native-ui/assets/models -type d -exec chmod 0755 {} +; "
            "find ~/.local/share/pulsearc/native-ui/assets/models -type f -exec chmod 0644 {} +",
        )
        print(
            remote(
                client,
                "~/.local/share/pulsearc/venv/bin/python "
                "~/.local/share/pulsearc/native-ui/pulsearc_ui.py --self-test",
            )
        )
        print(
            remote(
                client,
                "SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy PYGAME_HIDE_SUPPORT_PROMPT=1 "
                "~/.local/share/pulsearc/venv/bin/python -c "
                "'import sys; "
                "sys.path.insert(0, \"/home/gamer/.local/share/pulsearc/native-ui\"); "
                "import pulsearc_ui; "
                "ui=pulsearc_ui.PulseArcUI(self_test=True); "
                "ui.boot_finished=True; ui._refresh_state(force=True); "
                "games=ui._query_cheat_games(); "
                "assert games, \"cheat manager returned no selectable games\"; "
                "ui.cheat_content_id=str(games[0][\"content_id\"]); "
                "entries=ui._query_cheat_entries(); "
                "assert entries, \"selected game returned no cheat codes\"; "
                "print(\"PULSEARC_CHEAT_UI_TEST_OK games=%d first_game_codes=%d\" % "
                "(len(games), len(entries)))'",
            )
        )
        print(
            remote(
                client,
                "DISPLAY=:0 XAUTHORITY=/home/gamer/.Xauthority "
                "PYTHONPATH=/home/gamer/.local/share/pulsearc/core timeout 20 "
                "~/.local/share/pulsearc/venv/bin/python "
                "~/.local/share/pulsearc/native-ui/pulsearc_3d_library.py --self-test",
                timeout=30,
            )
        )
        print(remote(client, "~/.local/bin/pulsearc-audio-select; wpctl status -n | sed -n '/Sinks:/,/Sources:/p'"))
        print("PULSEARC_LIVE_NATIVE_UI_STAGED_OK")
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
