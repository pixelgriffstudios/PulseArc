#!/usr/bin/env python3
"""Atomically install only the rootless projectM launcher on a live console."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path

import paramiko


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "live-update/pulsearc-projectm"
DESTINATION = "/home/gamer/.local/bin/pulsearc-projectm"


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
    client.connect(args.host, username=args.user, password=password, allow_agent=False,
                   look_for_keys=False, timeout=15, banner_timeout=15, auth_timeout=15)
    temporary = DESTINATION + ".new"
    try:
        with client.open_sftp() as sftp:
            sftp.put(str(SOURCE), temporary)
            sftp.chmod(temporary, 0o755)
        expected = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
        command = (
            f"set -e; test \"$(sha256sum {temporary} | cut -d' ' -f1)\" = \"{expected}\"; "
            f"cp -a {DESTINATION} {DESTINATION}.previous; mv {temporary} {DESTINATION}; "
            f"sh -n {DESTINATION}; grep -q PULSE_SOURCE {DESTINATION}; "
            "echo PROJECTM_MONITOR_BIND_INSTALLED"
        )
        _stdin, stdout, stderr = client.exec_command(command, timeout=30)
        output = stdout.read().decode("utf-8", errors="replace")
        error = stderr.read().decode("utf-8", errors="replace")
        status = stdout.channel.recv_exit_status()
        if status:
            raise RuntimeError(error or output)
        print(output.strip())
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
