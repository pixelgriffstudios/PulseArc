#!/usr/bin/env python3
"""Atomically deploy and validate the complete PulseArc Python core package."""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

import paramiko


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src/pulsearc"
DESTINATION = "/home/gamer/.local/share/pulsearc/core/pulsearc"
STAGE_ROOT = "/home/gamer/.cache/pulsearc/core-package.new"
STAGE = STAGE_ROOT + "/pulsearc"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def remote(client: paramiko.SSHClient, command: str, timeout: int = 180) -> str:
    _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    output = stdout.read().decode("utf-8", errors="replace")
    error = stderr.read().decode("utf-8", errors="replace")
    status = stdout.channel.recv_exit_status()
    if status:
        raise RuntimeError(f"remote command failed ({status}): {command}\n{output}\n{error}")
    return output + error


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("host")
    parser.add_argument("--user", default="gamer")
    args = parser.parse_args()
    password = os.environ.get("PULSEARC_REMOTE_PASSWORD")
    if not password:
        raise SystemExit("PULSEARC_REMOTE_PASSWORD is required")
    sources = sorted(SOURCE.glob("*.py"))
    if not sources:
        raise SystemExit("PulseArc core package is empty")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(args.host, username=args.user, password=password, allow_agent=False,
                   look_for_keys=False, timeout=15, banner_timeout=15, auth_timeout=15)
    try:
        remote(client, f"rm -rf {STAGE_ROOT}; mkdir -p {STAGE}")
        with client.open_sftp() as sftp:
            for source in sources:
                sftp.put(str(source), f"{STAGE}/{source.name}")
        for source in sources:
            actual = remote(client, f"sha256sum '{STAGE}/{source.name}'").split()[0]
            if actual != digest(source):
                raise RuntimeError(f"checksum mismatch: {source.name}")
        print(remote(client,
            f"set -e; /usr/bin/python -m compileall -q {STAGE}; "
            f"PYTHONPATH={STAGE_ROOT} $HOME/.local/share/pulsearc/venv/bin/python -c "
            "'import pulsearc.control,pulsearc.scanner,pulsearc.rpcs3_patches; "
            "print(\"PULSEARC_CORE_IMPORT_OK\")'; "
            "stamp=$(date +%Y%m%d-%H%M%S); backup=$HOME/.local/share/pulsearc/rollback/$stamp-core; "
            "mkdir -p \"$backup\"; cp -a " + DESTINATION + " \"$backup/\"; "
            f"mv {DESTINATION} {DESTINATION}.old; mv {STAGE} {DESTINATION}; "
            f"rm -rf {DESTINATION}.old {STAGE_ROOT}; "
            f"PYTHONPATH={DESTINATION}/.. $HOME/.local/share/pulsearc/venv/bin/python -c "
            "'from pulsearc.control import _prepare_cemu_config; from pathlib import Path; "
            "p=_prepare_cemu_config(Path(\"/tmp/pulsearc-cemu-test\")); "
            "assert \"<api>1</api>\" in p.read_text(); print(\"PULSEARC_CORE_DEPLOY_OK\")'"), end="")
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
