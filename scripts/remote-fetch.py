#!/usr/bin/env python3
"""Fetch one diagnostic file from a PulseArc console over SFTP."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import paramiko


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("host")
    parser.add_argument("remote_path")
    parser.add_argument("local_path", type=Path)
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
        args.local_path.parent.mkdir(parents=True, exist_ok=True)
        with client.open_sftp() as sftp:
            sftp.get(args.remote_path, str(args.local_path))
        print(args.local_path)
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
