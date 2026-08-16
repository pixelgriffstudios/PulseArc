#!/usr/bin/env python3
"""Atomically deploy PulseArc personalization UI and bundled themes."""

from __future__ import annotations

import argparse
import hashlib
import os
import shlex
import tarfile
import tempfile
from pathlib import Path

import paramiko


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_CACHE = Path(
    os.environ.get(
        "PULSEARC_RUNTIME_CACHE",
        Path.home() / "AppData" / "Local" / "PulseArc" / "RuntimeCache",
    )
)
FILES = {
    ROOT / "native-ui/pulsearc_ui.py": "/home/gamer/.local/share/pulsearc/native-ui/pulsearc_ui.py",
    ROOT / "native-ui/pulsearc_personalization.py": "/home/gamer/.local/share/pulsearc/native-ui/pulsearc_personalization.py",
    ROOT / "native-ui/pulsearc_archive_import.py": "/home/gamer/.local/share/pulsearc/native-ui/pulsearc_archive_import.py",
    ROOT / "archiso/airootfs/usr/local/bin/pulsearc-playstation-plus-cloud": "/home/gamer/.local/bin/pulsearc-playstation-plus-cloud",
    ROOT / "archiso/airootfs/usr/local/bin/pulsearc-steam": "/home/gamer/.local/bin/pulsearc-steam",
    ROOT / "live-update/pulsearc-session": "/home/gamer/.local/bin/pulsearc-session",
}
OPTIONAL_BINARY_FILES = {
    RUNTIME_CACHE / "Heroic-2.22.1-linux-x86_64.AppImage":
        "/home/gamer/.local/share/pulsearc/apps/heroic/Heroic.AppImage",
}
THEMES = ROOT / "native-ui/themes"
AVATARS = ROOT / "native-ui/assets/profile-avatars"


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

    with tempfile.TemporaryDirectory(prefix="pulsearc-extras-") as temporary:
        archive = Path(temporary) / "personalization.tar"
        with tarfile.open(archive, "w") as package:
            package.add(THEMES, arcname="themes")
            package.add(AVATARS, arcname="assets/profile-avatars")
        expected_archive = hashlib.sha256(archive.read_bytes()).hexdigest()

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(args.host, username=args.user, password=password, timeout=15,
                       banner_timeout=15, auth_timeout=15, allow_agent=False, look_for_keys=False)
        try:
            remote(
                client,
                "install -d -m 0755 ~/.cache/pulsearc-deploy "
                "~/.local/share/pulsearc/native-ui ~/.local/share/pulsearc/apps/heroic ~/.local/bin",
            )
            staged: list[tuple[Path, str, str]] = []
            deploy_files = dict(FILES)
            for source, target in OPTIONAL_BINARY_FILES.items():
                if not source.is_file():
                    continue
                expected = hashlib.sha256(source.read_bytes()).hexdigest()
                try:
                    current = remote(
                        client,
                        f"sha256sum {shlex.quote(target)} 2>/dev/null | cut -d' ' -f1",
                    ).strip()
                except RuntimeError:
                    current = ""
                if current != expected:
                    deploy_files[source] = target
            with client.open_sftp() as sftp:
                for source, target in deploy_files.items():
                    temporary_target = target + ".extras-new"
                    sftp.put(str(source), temporary_target)
                    sftp.chmod(temporary_target, 0o755)
                    staged.append((source, target, temporary_target))
                sftp.put(str(archive), "/home/gamer/.cache/pulsearc-deploy/personalization.tar.new")
            actual_archive = remote(
                client, "sha256sum ~/.cache/pulsearc-deploy/personalization.tar.new"
            ).split()[0]
            if actual_archive != expected_archive:
                raise RuntimeError("theme archive checksum mismatch")
            python = "/home/gamer/.local/share/pulsearc/venv/bin/python"
            for source, _target, temporary_target in staged:
                expected = hashlib.sha256(source.read_bytes()).hexdigest()
                actual = remote(client, f"sha256sum {shlex.quote(temporary_target)}").split()[0]
                if actual != expected:
                    raise RuntimeError(f"uploaded checksum mismatch: {source.name}")
                if source.suffix == ".py":
                    remote(client, f"{python} -m py_compile {shlex.quote(temporary_target)}")
                elif source.name == "pulsearc-session":
                    remote(client, f"bash -n {shlex.quote(temporary_target)}")
            remote(
                client,
                "set -eu; stamp=$(date +%Y%m%d-%H%M%S); "
                "install -d -m 0755 ~/.local/share/pulsearc/rollback; "
                "rm -rf ~/.cache/pulsearc-deploy/personalization.new; "
                "install -d -m 0755 ~/.cache/pulsearc-deploy/personalization.new; "
                "tar -xf ~/.cache/pulsearc-deploy/personalization.tar.new "
                "-C ~/.cache/pulsearc-deploy/personalization.new; "
                "test -s ~/.cache/pulsearc-deploy/personalization.new/themes/pulsearc-fusion/theme.toml; "
                "test -s ~/.cache/pulsearc-deploy/personalization.new/assets/profile-avatars/avatar-01.png; "
                "if [ -d ~/.local/share/pulsearc/native-ui/themes ]; then "
                "mv ~/.local/share/pulsearc/native-ui/themes "
                "~/.local/share/pulsearc/rollback/themes-$stamp; fi; "
                "if [ -d ~/.local/share/pulsearc/native-ui/assets ]; then "
                "mv ~/.local/share/pulsearc/native-ui/assets "
                "~/.local/share/pulsearc/rollback/assets-$stamp; fi; "
                "mv ~/.cache/pulsearc-deploy/personalization.new/themes ~/.local/share/pulsearc/native-ui/themes; "
                "mv ~/.cache/pulsearc-deploy/personalization.new/assets ~/.local/share/pulsearc/native-ui/assets; "
                + " ".join(
                    f"cp -a {shlex.quote(target)} ~/.local/share/pulsearc/rollback/{Path(target).name}-$stamp 2>/dev/null || true; "
                    f"mv {shlex.quote(temporary_target)} {shlex.quote(target)}; chmod 0755 {shlex.quote(target)};"
                    for _source, target, temporary_target in staged
                ),
            )
            ui = FILES[ROOT / "native-ui/pulsearc_ui.py"]
            print(remote(client, f"{python} {shlex.quote(ui)} --self-test", timeout=30))
            print(remote(client, "find ~/.local/share/pulsearc/native-ui/themes -name theme.toml -type f | wc -l"))
            print("PULSEARC_EXTRAS_DEPLOY_OK")
        finally:
            client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
