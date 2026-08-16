#!/usr/bin/env python3
"""Run one non-root command on a PulseArc development console over SSH."""

from __future__ import annotations

import argparse
import os

import paramiko


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("host")
    parser.add_argument("command")
    parser.add_argument("--user", default="gamer")
    parser.add_argument("--timeout", type=int, default=120)
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
        _stdin, stdout, stderr = client.exec_command(args.command, timeout=args.timeout)
        output = stdout.read().decode("utf-8", errors="replace")
        error = stderr.read().decode("utf-8", errors="replace")
        status = stdout.channel.recv_exit_status()
        print(output, end="")
        print(error, end="")
        return status
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
