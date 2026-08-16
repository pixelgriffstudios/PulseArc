#!/usr/bin/env python3
"""Stage theme auto-pause support without restarting the active UI session."""

from __future__ import annotations

import argparse
import hashlib
import os
import shlex
from pathlib import Path

import paramiko


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "native-ui" / "pulsearc_ui.py"
TARGET = "/home/gamer/.local/share/pulsearc/native-ui/pulsearc_ui.py"


def remote(client: paramiko.SSHClient, command: str, timeout: int = 60) -> str:
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
    parser.add_argument("--stage-only", action="store_true", help="do not touch the running decoder")
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
        allow_agent=False,
        look_for_keys=False,
        timeout=15,
        banner_timeout=15,
        auth_timeout=15,
    )
    try:
        temporary = TARGET + ".theme-autopause-new"
        remote(client, "install -d -m 0755 ~/.local/share/pulsearc/native-ui ~/.local/share/pulsearc/rollback")
        with client.open_sftp() as sftp:
            sftp.put(str(SOURCE), temporary)
            sftp.chmod(temporary, 0o755)
        local_hash = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
        remote_hash = remote(client, f"sha256sum {shlex.quote(temporary)}").split()[0]
        if local_hash != remote_hash:
            raise RuntimeError("uploaded UI checksum does not match")
        print(remote(client, f"~/.local/share/pulsearc/venv/bin/python -m py_compile {shlex.quote(temporary)}"), end="")
        print(
            remote(
                client,
                "stamp=$(date +%Y%m%d-%H%M%S); "
                "cp -a ~/.local/share/pulsearc/native-ui/pulsearc_ui.py "
                "~/.local/share/pulsearc/rollback/pulsearc_ui-theme-autopause-$stamp.py; "
                f"mv {shlex.quote(temporary)} {shlex.quote(TARGET)}; "
                f"chmod 0755 {shlex.quote(TARGET)}; "
                f"sha256sum {shlex.quote(TARGET)}",
            ),
            end="",
        )

        # The current Python process cannot hot-load its new class methods.
        # Freeze only its ffmpeg background decoder now, then resume it when
        # the already-running Steam session exits. The next normal UI launch
        # uses the permanent automatic behavior above.
        if not args.stage_only:
            print(
                remote(
                    client,
                    "pids=$(pgrep -f '[f]fmpeg.*native-ui/themes' || true); "
                    "for pid in $pids; do kill -STOP \"$pid\"; done; "
                    "if [ -n \"$pids\" ]; then "
                    "nohup sh -c 'while pgrep -x steam >/dev/null; do sleep 5; done; "
                    "for pid in '$pids'; do kill -CONT \"$pid\" 2>/dev/null || true; done' "
                    ">~/.cache/pulsearc/theme-resume.log 2>&1 </dev/null & "
                    "fi; "
                    "ps -o pid=,stat=,pcpu=,comm=,args= -p $(echo $pids | tr ' ' ',') 2>/dev/null || true; "
                    "pgrep -af 'steam$|steam -' || true",
                ),
                end="",
            )
        print("PULSEARC_THEME_AUTOPAUSE_STAGED")
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
