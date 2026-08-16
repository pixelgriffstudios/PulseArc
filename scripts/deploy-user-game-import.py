#!/usr/bin/env python3
"""Atomically deploy a prepared game/cheat bundle and live PulseArc code."""

from __future__ import annotations

import argparse
import hashlib
import os
import posixpath
import shlex
from pathlib import Path

import paramiko


ROOT = Path(__file__).resolve().parents[1]
CODE_FILES = {
    ROOT / "native-ui/pulsearc_ui.py": "code/native-ui/pulsearc_ui.py",
    ROOT / "src/pulsearc/cheats.py": "code/core/pulsearc/cheats.py",
    ROOT / "src/pulsearc/cheat_export.py": "code/core/pulsearc/cheat_export.py",
    ROOT / "src/pulsearc/control.py": "code/core/pulsearc/control.py",
    ROOT / "src/pulsearc/launch.py": "code/core/pulsearc/launch.py",
    ROOT / "src/pulsearc/scanner.py": "code/core/pulsearc/scanner.py",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def remote(client: paramiko.SSHClient, command: str, timeout: int = 900) -> str:
    _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    output = stdout.read().decode("utf-8", errors="replace")
    error = stderr.read().decode("utf-8", errors="replace")
    status = stdout.channel.recv_exit_status()
    if status:
        raise RuntimeError(f"remote command failed ({status}): {command}\n{output}\n{error}")
    return output + error


def mkdirs(sftp: paramiko.SFTPClient, path: str, made: set[str]) -> None:
    pending: list[str] = []
    current = path
    while current and current not in made:
        try:
            sftp.stat(current)
            made.add(current)
            break
        except OSError:
            pending.append(current)
            current = posixpath.dirname(current)
    for directory in reversed(pending):
        sftp.mkdir(directory, mode=0o755)
        made.add(directory)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("host")
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--user", default="gamer")
    args = parser.parse_args()
    password = os.environ.get("PULSEARC_REMOTE_PASSWORD")
    if not password:
        raise SystemExit("PULSEARC_REMOTE_PASSWORD is required")
    bundle = args.bundle.resolve()
    if not (bundle / "games").is_dir() or not (bundle / "summary.json").is_file():
        raise SystemExit("prepared bundle is incomplete")

    uploads: list[tuple[Path, str]] = []
    for path in sorted(bundle.rglob("*")):
        if path.is_file():
            uploads.append((path, f"bundle/{path.relative_to(bundle).as_posix()}"))
    uploads.extend(CODE_FILES.items())
    total = sum(path.stat().st_size for path, _ in uploads)
    uploaded = 0

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(args.host, username=args.user, password=password, timeout=15,
                   banner_timeout=15, auth_timeout=15, allow_agent=False, look_for_keys=False)
    staging = "/home/gamer/.cache/pulsearc-deploy/user-import.new"
    try:
        remote(client, f"rm -rf {shlex.quote(staging)}; mkdir -p {shlex.quote(staging)}")
        hashes: list[str] = []
        with client.open_sftp() as sftp:
            made = {staging}
            for source, relative in uploads:
                target = f"{staging}/{relative}"
                mkdirs(sftp, posixpath.dirname(target), made)
                sftp.put(str(source), target)
                sftp.chmod(target, 0o644)
                hashes.append(f"{sha256(source)}  {relative}")
                uploaded += source.stat().st_size
                print(f"UPLOAD {uploaded * 100 / max(1, total):6.2f}%  {source.name}", flush=True)
            with sftp.open(f"{staging}/SHA256SUMS", "w") as output:
                output.write("\n".join(hashes) + "\n")
        remote(client, f"cd {shlex.quote(staging)} && sha256sum -c SHA256SUMS >/dev/null", timeout=1800)
        install = f'''set -euo pipefail
stage={shlex.quote(staging)}
stamp=$(date +%Y%m%d-%H%M%S)
backup=/var/lib/pulsearc/library-backups/user-import-$stamp
mkdir -p "$backup/games" "$backup/cheats" \
  /var/lib/pulsearc/library/games /var/lib/pulsearc/profiles/default/cheats \
  "$HOME/.local/share/pulsearc/core/pulsearc" "$HOME/.local/share/pulsearc/native-ui"
for platform in nes nintendo-64 playstation dreamcast; do
  [ -d "$stage/bundle/games/$platform" ] || continue
  mkdir -p "/var/lib/pulsearc/library/games/$platform"
  for game in "$stage/bundle/games/$platform"/*; do
    [ -d "$game" ] || continue
    name=${{game##*/}}
    if [ -e "/var/lib/pulsearc/library/games/$platform/$name" ]; then
      mv "/var/lib/pulsearc/library/games/$platform/$name" "$backup/games/$platform-$name"
    fi
    mv "$game" "/var/lib/pulsearc/library/games/$platform/$name"
  done
done
if [ -d "$stage/bundle/cheats" ]; then
  cp -a "$stage/bundle/cheats/." /var/lib/pulsearc/profiles/default/cheats/
fi
cp -a "$HOME/.local/share/pulsearc/native-ui/pulsearc_ui.py" "$backup/pulsearc_ui.py" 2>/dev/null || true
cp -a "$HOME/.local/share/pulsearc/core/pulsearc/." "$backup/core" 2>/dev/null || true
install -m 0755 "$stage/code/native-ui/pulsearc_ui.py" "$HOME/.local/share/pulsearc/native-ui/pulsearc_ui.py"
for source in "$stage/code/core/pulsearc"/*.py; do
  install -m 0644 "$source" "$HOME/.local/share/pulsearc/core/pulsearc/${{source##*/}}"
done
touch /var/lib/pulsearc/library
rm -rf "$stage"
printf 'backup=%s\n' "$backup"
'''
        print(remote(client, "/usr/bin/bash -lc " + shlex.quote(install), timeout=1800), end="")
        print(remote(client,
            "PYTHONPATH=$HOME/.local/share/pulsearc/core "
            "$HOME/.local/share/pulsearc/venv/bin/python "
            "$HOME/.local/share/pulsearc/native-ui/pulsearc_ui.py --self-test"), end="")
        print("PULSEARC_USER_IMPORT_OK")
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
