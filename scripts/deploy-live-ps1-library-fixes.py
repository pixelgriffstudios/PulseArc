#!/usr/bin/env python3
"""Atomically deploy the PS1, synopsis, and 3D shelf fixes to a test console."""

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
    ROOT / "native-ui/pulsearc_3d_library.py":
        "/home/gamer/.local/share/pulsearc/native-ui/pulsearc_3d_library.py.new",
    ROOT / "src/pulsearc/control.py":
        "/home/gamer/.local/share/pulsearc/core/pulsearc/control.py.new",
    ROOT / "src/pulsearc/metadata_daemon.py":
        "/home/gamer/.local/share/pulsearc/core/pulsearc/metadata_daemon.py.new",
    ROOT / "config/systems.toml":
        "/home/gamer/.config/pulsearc/systems.toml.new",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def remote(client: paramiko.SSHClient, command: str, timeout: int = 90) -> str:
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
        args.host, username=args.user, password=password, allow_agent=False,
        look_for_keys=False, timeout=15, banner_timeout=15, auth_timeout=15,
    )
    try:
        remote(
            client,
            "install -d -m 0755 ~/.local/share/pulsearc/native-ui "
            "~/.local/share/pulsearc/core/pulsearc ~/.config/pulsearc "
            "~/.local/share/pulsearc/rollback ~/.cache/pulsearc",
        )
        with client.open_sftp() as sftp:
            for local, target in FILES.items():
                sftp.put(str(local), target)
                sftp.chmod(target, 0o644)
        for local, target in FILES.items():
            actual = remote(client, f"sha256sum {shlex.quote(target)}").split()[0]
            if actual != digest(local):
                raise RuntimeError(f"checksum mismatch: {target}")

        remote(
            client,
            "stamp=$(date +%Y%m%d-%H%M%S); backup=$HOME/.local/share/pulsearc/rollback/$stamp; "
            "mkdir -p \"$backup\"; "
            "cp -a ~/.local/share/pulsearc/native-ui/pulsearc_3d_library.py \"$backup/\" 2>/dev/null || true; "
            "cp -a ~/.local/share/pulsearc/core/pulsearc/control.py \"$backup/\" 2>/dev/null || true; "
            "cp -a ~/.local/share/pulsearc/core/pulsearc/metadata_daemon.py \"$backup/\" 2>/dev/null || true; "
            "cp -a ~/.config/pulsearc/systems.toml \"$backup/\" 2>/dev/null || true; "
            "mv ~/.local/share/pulsearc/native-ui/pulsearc_3d_library.py.new "
            "~/.local/share/pulsearc/native-ui/pulsearc_3d_library.py; "
            "mv ~/.local/share/pulsearc/core/pulsearc/control.py.new "
            "~/.local/share/pulsearc/core/pulsearc/control.py; "
            "mv ~/.local/share/pulsearc/core/pulsearc/metadata_daemon.py.new "
            "~/.local/share/pulsearc/core/pulsearc/metadata_daemon.py; "
            "mv ~/.config/pulsearc/systems.toml.new ~/.config/pulsearc/systems.toml; "
            "chmod 0644 ~/.local/share/pulsearc/native-ui/pulsearc_3d_library.py "
            "~/.local/share/pulsearc/core/pulsearc/control.py "
            "~/.local/share/pulsearc/core/pulsearc/metadata_daemon.py "
            "~/.config/pulsearc/systems.toml",
        )
        print(remote(
            client,
            "PYTHONPATH=$HOME/.local/share/pulsearc/core "
            "$HOME/.local/share/pulsearc/venv/bin/python -m py_compile "
            "$HOME/.local/share/pulsearc/native-ui/pulsearc_3d_library.py "
            "$HOME/.local/share/pulsearc/core/pulsearc/control.py "
            "$HOME/.local/share/pulsearc/core/pulsearc/metadata_daemon.py; "
            "PYTHONPATH=$HOME/.local/share/pulsearc/core "
            "/usr/bin/python -c "
            "'from pulsearc.control import REGISTRY; from pulsearc.registry import RuntimeRegistry; "
            "r=RuntimeRegistry.load(REGISTRY); "
            "assert r.systems[\"playstation\"].primary == \"duckstation\"; "
            "print(\"PULSEARC_PS1_PRIMARY_OK\")'",
        ))
        print(remote(
            client,
            "PYTHONPATH=$HOME/.local/share/pulsearc/core "
            "PULSEARC_COVERS_PATH=$HOME/.cache/pulsearc/covers.json "
            "PULSEARC_SYNOPSIS_PATH=$HOME/.cache/pulsearc/synopses.json "
            "PULSEARC_OFFLINE_ARTWORK=$HOME/.local/share/pulsearc/artwork/offline "
            "/usr/bin/python -c "
            "'from pulsearc.metadata import MetadataCache; "
            "from pulsearc.metadata_daemon import process_once, STATE; "
            "c=MetadataCache(STATE / \"metadata/library.db\"); process_once(c); c.close(); "
            "print(\"PULSEARC_SYNOPSIS_REFRESH_OK\")'",
            timeout=120,
        ))
        print(remote(
            client,
            "if [ -s ~/.cache/pulsearc/metadata.pid ]; then "
            "pid=$(cat ~/.cache/pulsearc/metadata.pid); kill \"$pid\" 2>/dev/null || true; fi; "
            "PYTHONPATH=$HOME/.local/share/pulsearc/core "
            "PULSEARC_COVERS_PATH=$HOME/.cache/pulsearc/covers.json "
            "PULSEARC_SYNOPSIS_PATH=$HOME/.cache/pulsearc/synopses.json "
            "PULSEARC_OFFLINE_ARTWORK=$HOME/.local/share/pulsearc/artwork/offline "
            "nohup /usr/bin/python -m pulsearc.metadata_daemon "
            ">/tmp/pulsearc-user-metadata.log 2>&1 </dev/null & "
            "echo $! > ~/.cache/pulsearc/metadata.pid; sleep 1; "
            "kill -0 $(cat ~/.cache/pulsearc/metadata.pid); "
            "echo PULSEARC_METADATA_DAEMON_OK",
        ))
        print("PULSEARC_LIVE_PS1_LIBRARY_FIXES_OK")
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
