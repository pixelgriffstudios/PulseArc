#!/usr/bin/env python3
"""Install Cemu and the locally extracted Super Mario 3D World WUX."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from pathlib import Path

import paramiko
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
APPIMAGE = ROOT / "vendor/cache/Cemu-2.6-x86_64.AppImage"
GAME = Path.home() / "Downloads/PulseArc-Super-Mario-3D-World/Super Mario 3D World (USA) (En,Fr,Es) (Rev 2).wux"
COVER_SOURCE = Path.home() / "Downloads/image.avif"
COVER = ROOT / ".asset-staging/super-mario-3d-world-cover.png"
RUNNER = "/home/gamer/.local/share/pulsearc/runners/cemu/cemu.AppImage"
REGISTRY = "/home/gamer/.config/pulsearc/systems.toml"
GAME_ROOT = "/var/lib/pulsearc/library/games/wii-u/super-mario-3d-world"


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(4 * 1024 * 1024):
            hasher.update(block)
    return hasher.hexdigest()


def remote(client: paramiko.SSHClient, command: str, timeout: int = 600) -> str:
    _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    output = stdout.read().decode("utf-8", errors="replace")
    error = stderr.read().decode("utf-8", errors="replace")
    status = stdout.channel.recv_exit_status()
    if status:
        raise RuntimeError(f"remote command failed ({status}): {command}\n{output}\n{error}")
    return output + error


def upload(sftp: paramiko.SFTPClient, source: Path, target: str, label: str) -> None:
    last = -1
    def progress(done: int, total: int) -> None:
        nonlocal last
        percent = int(done * 100 / total) if total else 100
        if percent >= last + 5 or percent == 100:
            last = percent
            print(f"{label} {percent:3d}%", flush=True)
    sftp.put(str(source), target, callback=progress)


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
    for required in (APPIMAGE, GAME, COVER_SOURCE):
        if not required.is_file():
            raise SystemExit(f"required file is missing: {required}")
    COVER.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(COVER_SOURCE) as source:
        source.convert("RGB").save(COVER, "PNG", optimize=True)

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(args.host, username=args.user, password=password, allow_agent=False,
                   look_for_keys=False, timeout=15, banner_timeout=15, auth_timeout=15)
    try:
        current_registry = remote(client, f"cat {REGISTRY}")
        cemu_section = (
            '[runners.cemu]\nkind = "standalone"\n'
            f'executable = "{RUNNER}"\n'
            'arguments = ["-f", "-g", "{content}"]\n'
            'package = "pulsearc-cemu"\n'
        )
        registry, count = re.subn(
            r"(?ms)^\[runners\.cemu\]\n.*?(?=^\[)", cemu_section + "\n", current_registry,
        )
        if count != 1:
            raise RuntimeError("live systems registry did not contain one Cemu runner")
        stage_root = "/home/gamer/.cache/pulsearc/cemu-deploy"
        remote(client, f"rm -rf {stage_root}; mkdir -p {stage_root}/game/content "
                       f"$HOME/.local/share/pulsearc/runners/cemu "
                       f"$HOME/.local/share/pulsearc/core/pulsearc $HOME/.config/pulsearc "
                       f"/var/lib/pulsearc/library/games/wii-u")
        stage_app = f"{stage_root}/cemu.AppImage"
        stage_game = f"{stage_root}/game/content/Super Mario 3D World.wux"
        stage_cover = f"{stage_root}/game/cover.png"
        stage_control = f"{stage_root}/control.py"
        stage_registry = f"{stage_root}/systems.toml"
        with client.open_sftp() as sftp:
            upload(sftp, APPIMAGE, stage_app, "CEMU")
            upload(sftp, GAME, stage_game, "WII_U_GAME")
            upload(sftp, COVER, stage_cover, "COVER")
            upload(sftp, ROOT / "src/pulsearc/control.py", stage_control, "CONTROL")
            with sftp.open(stage_registry, "w") as output:
                output.write(registry)
        expected = {
            stage_app: digest(APPIMAGE), stage_game: digest(GAME), stage_cover: digest(COVER),
            stage_control: digest(ROOT / "src/pulsearc/control.py"),
            stage_registry: hashlib.sha256(registry.encode("utf-8")).hexdigest(),
        }
        for path, checksum in expected.items():
            actual = remote(client, f"sha256sum '{path}'").split()[0]
            if actual != checksum:
                raise RuntimeError(f"checksum mismatch: {path}")
        print(remote(client, f"set -e; stamp=$(date +%Y%m%d-%H%M%S); "
            f"backup=$HOME/.local/share/pulsearc/rollback/$stamp-cemu; mkdir -p \"$backup\"; "
            f"cp -a '{RUNNER}' \"$backup/\" 2>/dev/null || true; "
            f"cp -a '{GAME_ROOT}' \"$backup/\" 2>/dev/null || true; "
            f"install -m 0755 '{stage_app}' '{RUNNER}.new'; mv '{RUNNER}.new' '{RUNNER}'; "
            f"mv '{stage_control}' $HOME/.local/share/pulsearc/core/pulsearc/control.py; "
            f"mv '{stage_registry}' '{REGISTRY}'; chmod 0644 '{REGISTRY}'; "
            f"rm -rf '{GAME_ROOT}.new'; mv '{stage_root}/game' '{GAME_ROOT}.new'; "
            f"rm -rf '{GAME_ROOT}'; mv '{GAME_ROOT}.new' '{GAME_ROOT}'; "
            f"rm -rf '{stage_root}'; "
            "mkdir -p /run/pulsearc; PULSEARC_STATE_ROOT=/var/lib/pulsearc "
            "PYTHONPATH=$HOME/.local/share/pulsearc/core "
            "$HOME/.local/share/pulsearc/venv/bin/python -c "
            "'from pulsearc.scanner import scan,write_index; "
            "write_index(scan(\"/var/lib/pulsearc/library\"), \"/run/pulsearc/library.json\")'; "
            f"test -x '{RUNNER}'; test -s '{GAME_ROOT}/content/Super Mario 3D World.wux'; "
            "PYTHONPATH=$HOME/.local/share/pulsearc/core $HOME/.local/share/pulsearc/venv/bin/python -c "
            "'from pathlib import Path; from pulsearc.control import _prepare_cemu_config; "
            "p=_prepare_cemu_config(Path(\"/tmp/pulsearc-cemu-test\")); "
            "assert \"<api>1</api>\" in p.read_text(); print(\"PULSEARC_CEMU_CONFIG_OK\")'; "
            f"du -sh '{GAME_ROOT}'; echo PULSEARC_CEMU_GAME_INSTALL_OK", timeout=900), end="")
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
