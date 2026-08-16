#!/usr/bin/env python3
"""Atomically replace the live DuckStation runner with the regular x64 build."""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

import paramiko


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "vendor/cache/DuckStation-x64.AppImage"
REMOTE_STAGE = "/home/gamer/.cache/pulsearc/DuckStation-x64.AppImage.new"
DESTINATION = "/home/gamer/.local/share/pulsearc/runners/duckstation/duckstation.AppImage"
REGISTRY = "/home/gamer/.config/pulsearc/systems.toml"


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
    expected = hashlib.sha256(SOURCE.read_bytes()).hexdigest()

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(args.host, username=args.user, password=password, allow_agent=False,
                   look_for_keys=False, timeout=15, banner_timeout=15, auth_timeout=15)
    try:
        command = (
            "install -d -m 0755 ~/.cache/pulsearc ~/.local/share/pulsearc/runners/duckstation "
            "~/.local/share/pulsearc/rollback"
        )
        client.exec_command(command, timeout=30)[1].channel.recv_exit_status()
        _stdin, checksum_out, _stderr = client.exec_command(
            f"sha256sum {DESTINATION} 2>/dev/null | cut -d' ' -f1", timeout=30,
        )
        destination_is_current = checksum_out.read().decode("ascii", errors="ignore").strip() == expected
        with client.open_sftp() as sftp:
            if not destination_is_current:
                try:
                    sftp.stat(REMOTE_STAGE)
                except OSError:
                    sftp.put(str(SOURCE), REMOTE_STAGE)
                sftp.chmod(REMOTE_STAGE, 0o755)
                try:
                    sftp.stat(DESTINATION)
                    backup = "/home/gamer/.local/share/pulsearc/rollback/duckstation-user.AppImage.bak"
                    try:
                        sftp.remove(backup)
                    except OSError:
                        pass
                    sftp.rename(DESTINATION, backup)
                except OSError:
                    pass
                sftp.rename(REMOTE_STAGE, DESTINATION)
                sftp.chmod(DESTINATION, 0o755)
            with sftp.open(REGISTRY, "r") as source:
                registry = source.read().decode("utf-8")
            registry = registry.replace(
                'executable = "/usr/local/bin/pulsearc-appimage"\n'
                'arguments = ["duckstation", "-batch", "-fullscreen", "{content}"]',
                'executable = "/home/gamer/.local/share/pulsearc/runners/duckstation/duckstation.AppImage"\n'
                'arguments = ["-batch", "-fullscreen", "{content}"]',
                1,
            )
            temporary = REGISTRY + ".new"
            with sftp.open(temporary, "w") as output:
                output.write(registry.encode("utf-8"))
            sftp.chmod(temporary, 0o644)
            sftp.posix_rename(temporary, REGISTRY)
        command = (
            f"test \"$(sha256sum {DESTINATION} | cut -d' ' -f1)\" = {expected}; "
            "PYTHONPATH=$HOME/.local/share/pulsearc/core /usr/bin/python -c "
            "'from pathlib import Path; from pulsearc.control import _prepare_duckstation_config; "
            "_prepare_duckstation_config(Path(\"/var/lib/pulsearc/profiles/default/games/6027bdc27c0fbd6fb8ba7e31\"))'; "
            "PYTHONPATH=$HOME/.local/share/pulsearc/core /usr/bin/python -c "
            "'from pulsearc.control import REGISTRY; from pulsearc.registry import RuntimeRegistry; "
            "r=RuntimeRegistry.load(REGISTRY); d=r.runners[\"duckstation\"]; "
            "assert r.systems[\"playstation\"].primary == \"duckstation\"; "
            "assert d.executable.endswith(\".local/share/pulsearc/runners/duckstation/duckstation.AppImage\"); "
            "print(\"PULSEARC_DUCKSTATION_MODERN_OK\")'"
        )
        _stdin, stdout, stderr = client.exec_command(command, timeout=120)
        output = stdout.read().decode("utf-8", errors="replace")
        error = stderr.read().decode("utf-8", errors="replace")
        status = stdout.channel.recv_exit_status()
        print(output, end="")
        print(error, end="", file=sys.stderr)
        return status
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
