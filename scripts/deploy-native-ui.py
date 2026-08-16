#!/usr/bin/env python3
"""Stage and install the PulseArc native shell on a development console."""

from __future__ import annotations

import argparse
import hashlib
import os
import shlex
import time
from pathlib import Path

import paramiko


ROOT = Path(__file__).resolve().parents[1]
FILES = {
    ROOT / "native-ui" / "pulsearc_ui.py": "/tmp/pulsearc-native-ui.py",
    ROOT / "native-ui" / "pulsearc_tv.py": "/tmp/pulsearc-tv.py",
    ROOT / "native-ui" / "pulsearc_network.py": "/tmp/pulsearc-network.py",
    ROOT / "native-ui" / "pulsearc_3d_library.py": "/tmp/pulsearc-3d-library.py",
    ROOT / "native-ui" / "assets" / "parking-lot-dusk.png": "/tmp/pulsearc-parking-lot-dusk.png",
    ROOT / "native-ui" / "assets" / "ceiling-white.webp": "/tmp/pulsearc-ceiling-white.webp",
    ROOT / "native-ui" / "assets" / "ceiling-lights.jpg": "/tmp/pulsearc-ceiling-lights.jpg",
    ROOT / "native-ui" / "assets" / "carpet-dark.webp": "/tmp/pulsearc-carpet-dark.webp",
    ROOT / "native-ui" / "assets" / "wall-yellow-plaster.webp": "/tmp/pulsearc-wall-yellow-plaster.webp",
    ROOT / "native-ui" / "assets" / "wall-yellow-brick.webp": "/tmp/pulsearc-wall-yellow-brick.webp",
    ROOT / "native-ui" / "assets" / "wall-blue-brick.webp": "/tmp/pulsearc-wall-blue-brick.webp",
    ROOT / "native-ui" / "assets" / "plaza-lounge-01.mp3": "/tmp/pulsearc-plaza-lounge-01.mp3",
    ROOT / "native-ui" / "assets" / "plaza-lounge-02.mp3": "/tmp/pulsearc-plaza-lounge-02.mp3",
    ROOT / "archiso" / "airootfs" / "usr" / "local" / "bin" / "pulsearc-session": "/tmp/pulsearc-session",
    ROOT / "archiso" / "airootfs" / "usr" / "local" / "bin" / "pulsearc-audio-select": "/tmp/pulsearc-audio-select",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(client: paramiko.SSHClient, command: str, password: str | None = None, timeout: int = 900) -> str:
    stdin, stdout, stderr = client.exec_command(command, timeout=timeout, get_pty=password is not None)
    if password is not None:
        # sudo deliberately flushes input queued before it begins reading a
        # password on a PTY. Wait for its reader instead of racing it.
        time.sleep(0.6)
        stdin.write(password + "\n")
        stdin.flush()
        stdin.channel.shutdown_write()
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
    client.connect(
        args.host,
        username=args.user,
        password=password,
        timeout=15,
        banner_timeout=15,
        auth_timeout=15,
        allow_agent=False,
        look_for_keys=False,
    )
    try:
        with client.open_sftp() as sftp:
            for local, remote in FILES.items():
                sftp.put(str(local), remote)
                sftp.chmod(remote, 0o755)
        for local, remote in FILES.items():
            remote_hash = run(client, f"sha256sum {shlex.quote(remote)}").split()[0]
            if remote_hash != digest(local):
                raise RuntimeError(f"checksum mismatch after upload: {local}")

        install_script = r'''set -euo pipefail
pacman -Sy --needed --noconfirm python-pygame python-opengl projectm projectm-sdl projectm-pulseaudio xdotool mpv vlc libdvdcss
stamp=$(date +%Y%m%d-%H%M%S)
backup=/var/lib/pulsearc/rollback/native-shell-$stamp
install -d -m 0755 "$backup" /usr/share/pulsearc/native-ui/assets
cp -a /usr/local/bin/pulsearc-session "$backup/pulsearc-session" || true
cp -a /usr/local/bin/pulsearc-audio-select "$backup/pulsearc-audio-select" || true
cp -a /usr/share/pulsearc/native-ui/pulsearc_3d_library.py "$backup/pulsearc_3d_library.py" || true
cp -a /usr/share/pulsearc/native-ui/assets/parking-lot-dusk.png "$backup/parking-lot-dusk.png" || true
install -Dm755 /tmp/pulsearc-native-ui.py /usr/share/pulsearc/native-ui/pulsearc_ui.py
install -Dm755 /tmp/pulsearc-tv.py /usr/share/pulsearc/native-ui/pulsearc_tv.py
install -Dm755 /tmp/pulsearc-network.py /usr/share/pulsearc/native-ui/pulsearc_network.py
install -Dm755 /tmp/pulsearc-3d-library.py /usr/share/pulsearc/native-ui/pulsearc_3d_library.py
install -Dm644 /tmp/pulsearc-parking-lot-dusk.png /usr/share/pulsearc/native-ui/assets/parking-lot-dusk.png
install -Dm644 /tmp/pulsearc-ceiling-white.webp /usr/share/pulsearc/native-ui/assets/ceiling-white.webp
install -Dm644 /tmp/pulsearc-ceiling-lights.jpg /usr/share/pulsearc/native-ui/assets/ceiling-lights.jpg
install -Dm644 /tmp/pulsearc-carpet-dark.webp /usr/share/pulsearc/native-ui/assets/carpet-dark.webp
install -Dm644 /tmp/pulsearc-wall-yellow-plaster.webp /usr/share/pulsearc/native-ui/assets/wall-yellow-plaster.webp
install -Dm644 /tmp/pulsearc-wall-yellow-brick.webp /usr/share/pulsearc/native-ui/assets/wall-yellow-brick.webp
install -Dm644 /tmp/pulsearc-wall-blue-brick.webp /usr/share/pulsearc/native-ui/assets/wall-blue-brick.webp
install -Dm644 /tmp/pulsearc-plaza-lounge-01.mp3 /usr/share/pulsearc/native-ui/assets/plaza-lounge-01.mp3
install -Dm644 /tmp/pulsearc-plaza-lounge-02.mp3 /usr/share/pulsearc/native-ui/assets/plaza-lounge-02.mp3
install -Dm755 /tmp/pulsearc-session /usr/local/bin/pulsearc-session
install -Dm755 /tmp/pulsearc-audio-select /usr/local/bin/pulsearc-audio-select
chown -R root:root /usr/share/pulsearc/native-ui
'''
        sudo_command = "sudo -S -p '' /usr/bin/bash -lc " + shlex.quote(install_script)
        print(run(client, sudo_command, password=password))
        print(run(client, "/usr/bin/python /usr/share/pulsearc/native-ui/pulsearc_ui.py --self-test"))
        print(run(client, "DISPLAY=:0 /usr/bin/python /usr/share/pulsearc/native-ui/pulsearc_3d_library.py --self-test"))
        print(run(client, "/usr/local/bin/pulsearc-audio-select; wpctl status -n | sed -n '/Sinks:/,/Sources:/p'"))
        print("PULSEARC_NATIVE_UI_STAGED_OK")
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
