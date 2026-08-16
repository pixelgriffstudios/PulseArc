#!/usr/bin/env python3
"""Stage PyOpenGL in a development console's user core.

Release images install Arch's signed ``python-opengl`` package.  This helper is
only for testing a new renderer on an already-installed development console
whose root filesystem is intentionally immutable.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

import paramiko


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

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(args.host, username=args.user, password=password, timeout=15,
                   banner_timeout=15, auth_timeout=15, allow_agent=False, look_for_keys=False)
    try:
        check = remote(
            client,
            "PYTHONPATH=$HOME/.local/share/pulsearc/core "
            "$HOME/.local/share/pulsearc/venv/bin/python -c 'import OpenGL; print(OpenGL.__version__)' "
            "2>/dev/null || true",
        ).strip()
        if check:
            print(f"PyOpenGL already staged: {check}")
            return 0
        with tempfile.TemporaryDirectory(prefix="pulsearc-opengl-") as temporary:
            root = Path(temporary)
            subprocess.run(
                [sys.executable, "-m", "pip", "download", "--quiet", "--only-binary=:all:",
                 "--no-deps", "PyOpenGL==3.1.10", "-d", str(root)],
                check=True,
            )
            wheel = next(root.glob("PyOpenGL-*.whl"))
            extracted = root / "extracted"
            with zipfile.ZipFile(wheel) as package:
                for member in package.namelist():
                    if member.startswith("OpenGL/"):
                        package.extract(member, extracted)
            archive = root / "pyopengl.tar.gz"
            with tarfile.open(archive, "w:gz") as package:
                package.add(extracted / "OpenGL", arcname="OpenGL")
            remote(client, "install -d -m 0755 ~/.cache/pulsearc-deploy ~/.local/share/pulsearc/core")
            with client.open_sftp() as sftp:
                sftp.put(str(archive), "/home/gamer/.cache/pulsearc-deploy/pyopengl.tar.gz")
            remote(
                client,
                "tar -xzf ~/.cache/pulsearc-deploy/pyopengl.tar.gz -C ~/.local/share/pulsearc/core; "
                "PYTHONPATH=$HOME/.local/share/pulsearc/core "
                "$HOME/.local/share/pulsearc/venv/bin/python -c 'import OpenGL; print(OpenGL.__version__)'",
            )
        print("PULSEARC_LIVE_OPENGL_STAGED_OK")
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
