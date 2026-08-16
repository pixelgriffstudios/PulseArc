#!/usr/bin/env python3
"""Restart the PulseArc graphical login session without rebooting the PC."""

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
        # Restart the actual graphical login session. Restarting only the
        # getty service can leave startx and the frontend orphaned, so the old
        # Python process keeps running and staged files never take effect.
        command = (
            "session=$(loginctl list-sessions --no-legend | "
            "awk '$3 == \"gamer\" && $4 == \"seat0\" {print $1; exit}'); "
            "test -n \"$session\" && loginctl terminate-session \"$session\""
        )
        _stdin, stdout, _stderr = client.exec_command(command, timeout=15)
        try:
            stdout.channel.recv_exit_status()
        except Exception:
            pass
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
