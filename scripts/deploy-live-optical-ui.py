#!/usr/bin/env python3
"""Atomically deploy only the optical-media UI fix to a live PulseArc console."""

from __future__ import annotations

import argparse
import hashlib
import os
import shlex
from pathlib import Path

import paramiko


ROOT = Path(__file__).resolve().parents[1]
FILES = {
    ROOT / "native-ui" / "pulsearc_ui.py": "/home/gamer/.local/share/pulsearc/native-ui/pulsearc_ui.py",
    ROOT / "native-ui" / "pulsearc_personalization.py": "/home/gamer/.local/share/pulsearc/native-ui/pulsearc_personalization.py",
    ROOT / "native-ui" / "pulsearc_3d_library.py": "/home/gamer/.local/share/pulsearc/native-ui/pulsearc_3d_library.py",
}


def run(client: paramiko.SSHClient, command: str, timeout: int = 60) -> str:
    _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    output = stdout.read().decode("utf-8", errors="replace")
    error = stderr.read().decode("utf-8", errors="replace")
    status = stdout.channel.recv_exit_status()
    if status:
        raise RuntimeError(f"remote command failed ({status}): {command}\n{output}\n{error}")
    return output + error


def main() -> int:
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
        staged_files: list[tuple[Path, str, str]] = []
        with client.open_sftp() as sftp:
            for local, remote_path in FILES.items():
                staged = remote_path + ".optical-new"
                sftp.put(str(local), staged)
                sftp.chmod(staged, 0o755)
                staged_files.append((local, remote_path, staged))
        python = "/home/gamer/.local/share/pulsearc/venv/bin/python"
        for local, _remote_path, staged in staged_files:
            expected = hashlib.sha256(local.read_bytes()).hexdigest()
            actual = run(client, f"sha256sum {shlex.quote(staged)}").split()[0]
            if actual != expected:
                raise RuntimeError(f"uploaded checksum mismatch: {local.name}")
            run(client, f"{python} -m py_compile {shlex.quote(staged)}")
        run(client, "install -d -m 0755 ~/.local/share/pulsearc/rollback")
        for _local, remote_path, staged in staged_files:
            name = Path(remote_path).name
            run(
                client,
                "stamp=$(date +%Y%m%d-%H%M%S); "
                f"cp -a {shlex.quote(remote_path)} "
                f"~/.local/share/pulsearc/rollback/{shlex.quote(name)}-$stamp; "
                f"mv {shlex.quote(staged)} {shlex.quote(remote_path)}; "
                f"chmod 0755 {shlex.quote(remote_path)}",
            )
        ui = FILES[ROOT / "native-ui" / "pulsearc_ui.py"]
        plaza = FILES[ROOT / "native-ui" / "pulsearc_3d_library.py"]
        print(run(client, f"{python} {shlex.quote(ui)} --self-test"))
        print(
            run(
                client,
                "DISPLAY=:0 XAUTHORITY=/home/gamer/.Xauthority "
                f"PYTHONPATH=/home/gamer/.local/share/pulsearc/core timeout 20 {python} "
                f"{shlex.quote(plaza)} --self-test",
                timeout=30,
            )
        )
        print("PULSEARC_OPTICAL_UI_DEPLOY_OK")
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
