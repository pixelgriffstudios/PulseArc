#!/usr/bin/env python3
"""Deploy PulseArc metadata code and the compact offline cover pack."""

from __future__ import annotations

import argparse
import hashlib
import os
import tarfile
import tempfile
from pathlib import Path

import paramiko


ROOT = Path(__file__).resolve().parents[1]
CORE_FILES = tuple(sorted((ROOT / "src/pulsearc").glob("*.py")))
ARTWORK = ROOT / "archiso/airootfs/usr/share/pulsearc/artwork/offline"


def remote(client: paramiko.SSHClient, command: str, timeout: int = 120) -> str:
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
    args = parser.parse_args()
    password = os.environ.get("PULSEARC_REMOTE_PASSWORD")
    if not password:
        raise SystemExit("PULSEARC_REMOTE_PASSWORD is required")
    if not (ARTWORK / "index.json").is_file():
        raise SystemExit("offline artwork pack has not been built")

    with tempfile.TemporaryDirectory(prefix="pulsearc-artwork-") as temporary:
        archive = Path(temporary) / "offline-artwork.tar"
        with tarfile.open(archive, "w") as package:
            package.add(ARTWORK, arcname="offline")
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(args.host, username=args.user, password=password, timeout=15,
                       banner_timeout=15, auth_timeout=15, allow_agent=False, look_for_keys=False)
        try:
            remote(client, "install -d -m 0755 ~/.cache/pulsearc-deploy")
            existing = remote(
                client,
                "sha256sum ~/.cache/pulsearc-deploy/offline-artwork.tar 2>/dev/null | cut -d' ' -f1 || true",
            ).strip()
            with client.open_sftp() as sftp:
                if existing != digest:
                    sftp.put(str(archive), "/home/gamer/.cache/pulsearc-deploy/offline-artwork.tar")
                for source in CORE_FILES:
                    sftp.put(str(source), f"/home/gamer/.cache/pulsearc-deploy/{source.name}")
            actual = remote(client, "sha256sum ~/.cache/pulsearc-deploy/offline-artwork.tar").split()[0]
            if actual != digest:
                raise RuntimeError("offline artwork transfer checksum mismatch")
            remote(client,
                 "install -d -m 0755 ~/.local/share/pulsearc/artwork ~/.local/share/pulsearc/core/pulsearc; "
                 "rm -rf ~/.local/share/pulsearc/artwork/offline.new; "
                 "install -d -m 0755 ~/.local/share/pulsearc/artwork/offline.new; "
                 "tar -xf /home/gamer/.cache/pulsearc-deploy/offline-artwork.tar "
                 "--strip-components=1 -C ~/.local/share/pulsearc/artwork/offline.new; "
                 "rm -rf ~/.local/share/pulsearc/artwork/offline; "
                 "mv ~/.local/share/pulsearc/artwork/offline.new ~/.local/share/pulsearc/artwork/offline; "
                 "install -m 0644 ~/.cache/pulsearc-deploy/*.py ~/.local/share/pulsearc/core/pulsearc/")
            print(remote(client,
                "test -s ~/.local/share/pulsearc/artwork/offline/index.json && "
                "find ~/.local/share/pulsearc/artwork/offline -type f | wc -l"))
        finally:
            client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
