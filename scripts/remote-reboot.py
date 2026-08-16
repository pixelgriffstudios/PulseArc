#!/usr/bin/env python3
"""Safely reboot a PulseArc development console over SSH."""

from __future__ import annotations

import argparse
import os

import paramiko


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
        allow_agent=False,
        look_for_keys=False,
        timeout=15,
    )
    try:
        stdin, stdout, stderr = client.exec_command(
            "sudo -S -p '' /usr/bin/systemctl reboot",
            get_pty=True,
            timeout=15,
        )
        stdin.write(password + "\n")
        stdin.flush()
        stdout.channel.recv_exit_status()
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
