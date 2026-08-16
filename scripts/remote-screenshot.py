#!/usr/bin/env python3
"""Capture the active X11 desktop over SSH and download it."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import paramiko


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--user", default="gamer")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    password = os.environ.get("PULSEARC_REMOTE_PASSWORD")
    if not password:
        raise SystemExit("PULSEARC_REMOTE_PASSWORD is required")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(args.host, username=args.user, password=password,
                   allow_agent=False, look_for_keys=False, timeout=15)
    remote_path = "/tmp/pulsearc-remote-screen.png"
    try:
        command = (
            "DISPLAY=:0 XAUTHORITY=/home/gamer/.Xauthority "
            "ffmpeg -nostdin -loglevel error -f x11grab -video_size 1920x1080 "
            f"-i :0 -frames:v 1 -y {remote_path}"
        )
        _stdin, stdout, stderr = client.exec_command(command, timeout=30)
        error = stderr.read().decode("utf-8", errors="replace")
        status = stdout.channel.recv_exit_status()
        if status:
            raise RuntimeError(error)
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        with client.open_sftp() as sftp:
            sftp.get(remote_path, str(output))
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
