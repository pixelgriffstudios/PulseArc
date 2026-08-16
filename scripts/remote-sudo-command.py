#!/usr/bin/env python3
"""Run one root command on a PulseArc development console via sudo."""

from __future__ import annotations

import argparse
import os
import shlex
import time

import paramiko


def main() -> int:
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
                   look_for_keys=False, timeout=15, banner_timeout=15, auth_timeout=15)
    try:
        command = "sudo -S -p '' /usr/bin/bash -lc " + shlex.quote(args.command)
        stdin, stdout, stderr = client.exec_command(command, get_pty=True, timeout=900)
        time.sleep(0.5)
        stdin.write(password + "\n")
        stdin.flush()
        stdin.channel.shutdown_write()
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
