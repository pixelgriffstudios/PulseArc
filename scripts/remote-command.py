#!/usr/bin/env python3
"""Run one diagnostic command on a PulseArc development console."""

from __future__ import annotations

import argparse
import os
import sys

import paramiko


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("host")
    parser.add_argument("command")
    parser.add_argument("--user", default="gamer")
    args = parser.parse_args()
    password = os.environ.get("PULSEARC_REMOTE_PASSWORD")
    if not password:
        raise SystemExit("PULSEARC_REMOTE_PASSWORD is required")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(args.host, username=args.user, password=password, allow_agent=False,
                   look_for_keys=False, timeout=15)
    try:
        _stdin, stdout, stderr = client.exec_command(args.command, timeout=60)
        print(stdout.read().decode("utf-8", errors="replace"), end="")
        print(stderr.read().decode("utf-8", errors="replace"), end="", file=sys.stderr)
        return stdout.channel.recv_exit_status()
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
