#!/usr/bin/env python3
"""Upload and atomically install an extracted-disc PS3 game archive."""

from __future__ import annotations

import argparse
import hashlib
import os
import shlex
import sys
import time
from pathlib import Path

import paramiko


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(8 * 1024 * 1024):
            result.update(chunk)
    return result.hexdigest()


def remote(client: paramiko.SSHClient, command: str, timeout: int = 3600) -> str:
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
    parser.add_argument("archive", type=Path)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--user", default="gamer")
    parser.add_argument("--reuse-upload", action="store_true",
                        help="verify and reuse the already uploaded archive")
    args = parser.parse_args()
    archive = args.archive.resolve()
    if not archive.is_file():
        raise SystemExit(f"archive is missing: {archive}")
    password = os.environ.get("PULSEARC_REMOTE_PASSWORD")
    if not password:
        raise SystemExit("PULSEARC_REMOTE_PASSWORD is required")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(args.host, username=args.user, password=password, timeout=15,
                   banner_timeout=15, auth_timeout=15, allow_agent=False, look_for_keys=False)
    remote_archive = f"/home/{args.user}/.cache/pulsearc/{args.slug}.7z.new"
    stage = f"/var/lib/pulsearc/library/games/playstation-3/.{args.slug}.new"
    destination = f"/var/lib/pulsearc/library/games/playstation-3/{args.slug}"
    try:
        remote(client, "install -d -m 0755 ~/.cache/pulsearc /var/lib/pulsearc/library/games/playstation-3")
        total = archive.stat().st_size
        started = time.monotonic()
        last_report = 0.0

        def progress(sent: int, _total: int) -> None:
            nonlocal last_report
            now = time.monotonic()
            if sent < total and now - last_report < 2.0:
                return
            last_report = now
            elapsed = max(0.01, now - started)
            speed = sent / elapsed / (1024 * 1024)
            print(f"UPLOAD {sent * 100 / total:6.2f}%  {speed:6.1f} MiB/s", flush=True)

        if not args.reuse_upload:
            with client.open_sftp() as sftp:
                sftp.put(str(archive), remote_archive, callback=progress)
                sftp.chmod(remote_archive, 0o644)
        expected = digest(archive)
        actual = remote(client, f"sha256sum {shlex.quote(remote_archive)}").split()[0]
        if actual != expected:
            raise RuntimeError("uploaded PS3 archive checksum mismatch")
        command = f'''set -euo pipefail
rm -rf {shlex.quote(stage)}
mkdir -p {shlex.quote(stage)}
bsdtar -xf {shlex.quote(remote_archive)} -C {shlex.quote(stage)}
game_root=$(find {shlex.quote(stage)} -mindepth 1 -maxdepth 1 -type d -print -quit)
test -n "$game_root"
test -f "$game_root/PS3_GAME/USRDIR/EBOOT.BIN"
backup={shlex.quote(destination)}.backup-$(date +%Y%m%d-%H%M%S)
if [ -e {shlex.quote(destination)} ]; then mv {shlex.quote(destination)} "$backup"; fi
mv "$game_root" {shlex.quote(destination)}
# Archives commonly include a small readme beside the game directory. The
# validated game root is already promoted, so remove only this exact staging
# directory rather than treating harmless sibling files as an install error.
rm -rf {shlex.quote(stage)}
cp {shlex.quote(destination)}/PS3_GAME/ICON0.PNG {shlex.quote(destination)}/cover.png 2>/dev/null || true
rm -f {shlex.quote(remote_archive)}
PULSEARC_STATE_ROOT=/var/lib/pulsearc PYTHONPATH=$HOME/.local/share/pulsearc/core \
  $HOME/.local/share/pulsearc/venv/bin/python -c \
  'from pulsearc.scanner import scan,write_index; write_index(scan("/var/lib/pulsearc/library"), "/run/pulsearc/library.json")'
test -f {shlex.quote(destination)}/PS3_GAME/USRDIR/EBOOT.BIN
du -sh {shlex.quote(destination)}
'''
        print(remote(client, "/usr/bin/bash -lc " + shlex.quote(command), timeout=7200), end="")
        print("PULSEARC_PS3_GAME_INSTALL_OK")
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
