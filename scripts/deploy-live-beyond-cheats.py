#!/usr/bin/env python3
"""Install the official CHTDB Beyond the Beyond cheat set on a live console."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import paramiko


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pulsearc.cheats import import_duckstation_cheats  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("host")
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    password = os.environ.get("PULSEARC_REMOTE_PASSWORD")
    if not password:
        raise SystemExit("PULSEARC_REMOTE_PASSWORD is required")
    cheats = import_duckstation_cheats(args.source)
    if not cheats:
        raise SystemExit("source did not contain concrete DuckStation cheats")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(args.host, username="gamer", password=password, allow_agent=False,
                   look_for_keys=False, timeout=15, banner_timeout=15, auth_timeout=15)
    try:
        _stdin, stdout, stderr = client.exec_command("cat /run/pulsearc/library.json", timeout=30)
        document = stdout.read().decode("utf-8")
        if stdout.channel.recv_exit_status():
            raise RuntimeError(stderr.read().decode("utf-8", errors="replace"))
        entries = json.loads(document)
        entry = next(
            item for item in entries
            if str(item.get("title", "")).casefold() == "beyond the beyond"
            and item.get("platform") == "playstation"
        )
        content_id = str(entry["content_id"])
        destination = (
            "/var/lib/pulsearc/profiles/default/cheats/playstation/"
            f"{content_id}.json"
        )
        payload = json.dumps([
            {"id": item.cheat_id, "name": item.name, "code": item.code, "enabled": False}
            for item in cheats
        ], indent=2).encode("utf-8")
        with client.open_sftp() as sftp:
            try:
                sftp.stat("/var/lib/pulsearc/profiles/default/cheats/playstation")
            except OSError:
                client.exec_command(
                    "mkdir -p /var/lib/pulsearc/profiles/default/cheats/playstation"
                )[1].channel.recv_exit_status()
            temporary = destination + ".new"
            with sftp.open(temporary, "wb") as output:
                output.write(payload)
            sftp.rename(temporary, destination)
        print(f"PULSEARC_PS1_CHEATS_OK {len(cheats)} {content_id}")
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
