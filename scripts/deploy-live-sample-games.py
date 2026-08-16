#!/usr/bin/env python3
"""Install the authorized Hell on Rails sample and stage Hellborn for Android."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path

import paramiko


ROOT = Path(__file__).resolve().parents[1]
PC_EXE = Path(r"D:\CodexOutputs\Hell-on-Rails-Kazeta-2026-07-22\cart-root\content\hell-on-rails.exe")
PC_MANIFEST = ROOT / "examples/hell-on-rails/pulsearc.toml"
PC_COVER = Path(r"C:\Users\Jason\Downloads\ChatGPT Image Jul 27, 2026, 10_55_08 PM.png")
ANDROID_APK = Path(r"D:\NEW 2026 Android Apps\Ready to Publish\HellFire Back Again\HellbornUpdate.apk")


def remote(client: paramiko.SSHClient, command: str, timeout: int = 120) -> str:
    _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    output = stdout.read().decode("utf-8", errors="replace")
    error = stderr.read().decode("utf-8", errors="replace")
    status = stdout.channel.recv_exit_status()
    if status:
        raise RuntimeError(f"remote command failed ({status}): {command}\n{output}\n{error}")
    return output + error


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(4 * 1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("host")
    parser.add_argument("--user", default="gamer")
    args = parser.parse_args()
    password = os.environ.get("PULSEARC_REMOTE_PASSWORD")
    if not password:
        raise SystemExit("PULSEARC_REMOTE_PASSWORD is required")
    required = (PC_EXE, PC_MANIFEST, PC_COVER, ANDROID_APK)
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise SystemExit("missing sample files: " + ", ".join(missing))

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(args.host, username=args.user, password=password, timeout=15,
                   banner_timeout=15, auth_timeout=15, allow_agent=False, look_for_keys=False)
    try:
        remote(client,
               "rm -rf ~/.cache/pulsearc-deploy/hell-on-rails.new; "
               "mkdir -p ~/.cache/pulsearc-deploy/hell-on-rails.new/content "
               "~/.cache/pulsearc-deploy/android")
        transfers = {
            PC_EXE: "/home/gamer/.cache/pulsearc-deploy/hell-on-rails.new/content/hell-on-rails.exe",
            PC_MANIFEST: "/home/gamer/.cache/pulsearc-deploy/hell-on-rails.new/pulsearc.toml",
            PC_COVER: "/home/gamer/.cache/pulsearc-deploy/hell-on-rails.new/cover.png",
            ANDROID_APK: "/home/gamer/.cache/pulsearc-deploy/android/HellbornUpdate.apk",
        }
        with client.open_sftp() as sftp:
            for source, destination in transfers.items():
                sftp.put(str(source), destination)
        for source, destination in transfers.items():
            actual = remote(client, f"sha256sum '{destination}'").split()[0]
            if actual != digest(source):
                raise RuntimeError(f"transfer checksum mismatch: {source}")
        remote(client,
               "mkdir -p /var/lib/pulsearc/library/games/windows /var/lib/pulsearc/staged/android "
               "/var/lib/pulsearc/library-backups; "
               "if [ -e /var/lib/pulsearc/library/games/windows/hell-on-rails ]; then "
               "mv /var/lib/pulsearc/library/games/windows/hell-on-rails "
               "/var/lib/pulsearc/library-backups/hell-on-rails-$(date +%Y%m%d-%H%M%S); fi; "
               "mv ~/.cache/pulsearc-deploy/hell-on-rails.new "
               "/var/lib/pulsearc/library/games/windows/hell-on-rails; "
               "install -m 0644 ~/.cache/pulsearc-deploy/android/HellbornUpdate.apk "
               "/var/lib/pulsearc/staged/android/HellbornUpdate.apk")
        print(remote(client,
            "printf 'antimicrox='; command -v antimicrox || true; "
            "printf 'waydroid='; command -v waydroid || true; "
            "du -h /var/lib/pulsearc/library/games/windows/hell-on-rails "
            "/var/lib/pulsearc/staged/android/HellbornUpdate.apk"))
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
