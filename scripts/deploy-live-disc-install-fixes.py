#!/usr/bin/env python3
"""Deploy optical metadata, direct Play, batch install, and input reset fixes."""

from __future__ import annotations

import argparse
import hashlib
import os
import shlex
import sys
import time
from pathlib import Path

import paramiko


ROOT = Path(__file__).resolve().parents[1]
FILES = {
    ROOT / "native-ui/pulsearc_ui.py":
        "/home/gamer/.local/share/pulsearc/native-ui/pulsearc_ui.py.new",
    ROOT / "src/pulsearc/control.py":
        "/home/gamer/.local/share/pulsearc/core/pulsearc/control.py.new",
    ROOT / "src/pulsearc/media_daemon.py":
        "/home/gamer/.local/share/pulsearc/core/pulsearc/media_daemon.py.new",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def remote(client: paramiko.SSHClient, command: str, timeout: int = 120) -> str:
    _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    output = stdout.read().decode("utf-8", errors="replace")
    error = stderr.read().decode("utf-8", errors="replace")
    status = stdout.channel.recv_exit_status()
    if status:
        raise RuntimeError(f"remote command failed ({status}): {command}\n{output}\n{error}")
    return output + error


def remote_sudo(
    client: paramiko.SSHClient, password: str, command: str, timeout: int = 120,
) -> str:
    wrapped = "sudo -S -p '' /usr/bin/bash -lc " + shlex.quote(command)
    stdin, stdout, stderr = client.exec_command(wrapped, get_pty=True, timeout=timeout)
    time.sleep(0.3)
    stdin.write(password + "\n")
    stdin.flush()
    stdin.channel.shutdown_write()
    output = stdout.read().decode("utf-8", errors="replace")
    error = stderr.read().decode("utf-8", errors="replace")
    status = stdout.channel.recv_exit_status()
    if status:
        raise RuntimeError(f"remote sudo command failed ({status}): {command}\n{output}\n{error}")
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

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        args.host, username=args.user, password=password, allow_agent=False,
        look_for_keys=False, timeout=15, banner_timeout=15, auth_timeout=15,
    )
    try:
        remote(
            client,
            "install -d -m 0755 ~/.local/share/pulsearc/native-ui "
            "~/.local/share/pulsearc/core/pulsearc ~/.local/share/pulsearc/rollback "
            "~/.local/share/pulsearc/metadata/disc-databases",
        )
        with client.open_sftp() as sftp:
            for local, target in FILES.items():
                sftp.put(str(local), target)
                sftp.chmod(target, 0o644)
        for local, target in FILES.items():
            actual = remote(client, f"sha256sum {shlex.quote(target)}").split()[0]
            if actual != digest(local):
                raise RuntimeError(f"checksum mismatch: {target}")

        print(remote(
            client,
            "PYTHONPATH=$HOME/.local/share/pulsearc/core "
            "$HOME/.local/share/pulsearc/venv/bin/python -m py_compile "
            "$HOME/.local/share/pulsearc/native-ui/pulsearc_ui.py.new "
            "$HOME/.local/share/pulsearc/core/pulsearc/control.py.new "
            "$HOME/.local/share/pulsearc/core/pulsearc/media_daemon.py.new; "
            "echo PULSEARC_STAGED_COMPILE_OK",
        ))

        extract_databases = r'''set -e
tmp=$(mktemp -d /tmp/pulsearc-disc-db.XXXXXX)
trap 'rm -rf "$tmp"' EXIT
cd "$tmp"
$HOME/.local/share/pulsearc/runners/duckstation/duckstation.AppImage --appimage-extract >/dev/null 2>&1
cp squashfs-root/usr/bin/resources/gamedb.yaml $HOME/.local/share/pulsearc/metadata/disc-databases/duckstation-gamedb.yaml
rm -rf squashfs-root
/usr/lib/pulsearc/runners/pcsx2/pcsx2.AppImage --appimage-extract >/dev/null 2>&1
cp squashfs-root/usr/bin/resources/GameIndex.yaml $HOME/.local/share/pulsearc/metadata/disc-databases/pcsx2-game-index.yaml
chmod 0644 $HOME/.local/share/pulsearc/metadata/disc-databases/*.yaml
echo PULSEARC_DISC_DATABASES_OK
'''
        print(remote(client, extract_databases, timeout=180))

        print(remote(
            client,
            "stamp=$(date +%Y%m%d-%H%M%S); "
            "backup=$HOME/.local/share/pulsearc/rollback/$stamp-disc-install; mkdir -p \"$backup\"; "
            "cp -a ~/.local/share/pulsearc/native-ui/pulsearc_ui.py \"$backup/\"; "
            "cp -a ~/.local/share/pulsearc/core/pulsearc/control.py \"$backup/\"; "
            "cp -a ~/.local/share/pulsearc/core/pulsearc/media_daemon.py \"$backup/\"; "
            "mv ~/.local/share/pulsearc/native-ui/pulsearc_ui.py.new ~/.local/share/pulsearc/native-ui/pulsearc_ui.py; "
            "mv ~/.local/share/pulsearc/core/pulsearc/control.py.new ~/.local/share/pulsearc/core/pulsearc/control.py; "
            "mv ~/.local/share/pulsearc/core/pulsearc/media_daemon.py.new ~/.local/share/pulsearc/core/pulsearc/media_daemon.py; "
            "chmod 0644 ~/.local/share/pulsearc/native-ui/pulsearc_ui.py "
            "~/.local/share/pulsearc/core/pulsearc/control.py "
            "~/.local/share/pulsearc/core/pulsearc/media_daemon.py; "
            "echo PULSEARC_ATOMIC_INSTALL_OK",
        ))

        print(remote_sudo(
            client,
            password,
            "set -e; "
            "backup=/usr/lib/pulsearc/core/pulsearc/media_daemon.py.before-fast-optical-scan; "
            "test -e \"$backup\" || cp -a /usr/lib/pulsearc/core/pulsearc/media_daemon.py \"$backup\"; "
            "install -Dm644 /home/gamer/.local/share/pulsearc/core/pulsearc/media_daemon.py "
            "/usr/lib/pulsearc/core/pulsearc/media_daemon.py; "
            "systemctl restart pulsearc-media.service; "
            "systemctl is-active --quiet pulsearc-media.service; "
            "echo PULSEARC_FAST_OPTICAL_SCANNER_OK",
        ))

        configure = r'''PYTHONPATH=$HOME/.local/share/pulsearc/core /usr/bin/python - <<'PY'
from pathlib import Path
from pulsearc.control import _prepare_duckstation_config
root = Path("/var/lib/pulsearc/profiles")
count = 0
for settings in root.glob("*/games/*/config/duckstation/settings.ini"):
    _prepare_duckstation_config(settings.parents[2])
    count += 1
print(f"PULSEARC_DUCKSTATION_CONFIGS_OK={count}")
PY'''
        print(remote(client, configure))

        validate = r'''set -e
PYTHONPATH=$HOME/.local/share/pulsearc/native-ui:$HOME/.local/share/pulsearc/core $HOME/.local/share/pulsearc/venv/bin/python - <<'PY'
import importlib.util
import tempfile
from pathlib import Path
path = Path.home() / ".local/share/pulsearc/native-ui/pulsearc_ui.py"
spec = importlib.util.spec_from_file_location("pulsearc_ui_live", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
database_title = module._playstation_disc_title("playstation", "SLUS-00523")
print("PULSEARC_DATABASE_TITLE=" + repr(database_title))
assert database_title == "NBA Live 98"
with tempfile.TemporaryDirectory() as temporary:
    disc = Path(temporary) / "NBA_DISC"
    disc.mkdir()
    (disc / "SYSTEM.CNF").write_text("BOOT = cdrom:\\\\SLUS_005.23;1\n", encoding="ascii")
    entry = module.detected_playstation_disc(Path(temporary))
print("PULSEARC_DISC_ENTRY=" + repr(entry))
assert entry and entry["title"] == "NBA Live 98", entry
assert entry["runner"] == "duckstation"
print("PULSEARC_DISC_TITLE_OK=" + entry["title"])
PY
grep -Rqs '^CheckAtStartup = false$' /var/lib/pulsearc/profiles/*/games/*/config/duckstation/settings.ini
echo PULSEARC_LIVE_VALIDATION_OK
'''
        print(remote(client, validate))
        print("PULSEARC_LIVE_DISC_INSTALL_FIXES_OK")
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
