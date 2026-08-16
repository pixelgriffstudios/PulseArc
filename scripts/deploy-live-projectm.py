#!/usr/bin/env python3
"""Install a rootless projectM runtime and music integration on PulseArc."""

from __future__ import annotations

import argparse
import hashlib
import os
import shlex
import sys
from pathlib import Path

import paramiko


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PACKAGE_DIR = (
    ROOT.parent
    / "Kazeta-Combined-Installer/final-overlay/combined/packages"
)
PACKAGE_NAMES = (
    "projectm-3.1.12-5-x86_64.pkg.tar.zst",
    "projectm-pulseaudio-3.1.12-5-x86_64.pkg.tar.zst",
    "qt5-base-5.15.17+kde+r123-1-x86_64.pkg.tar.zst",
    "ftgl-2.4.0-3-x86_64.pkg.tar.zst",
    # Qt 5.15.17 in the offline package set was linked against ICU 76. Keep
    # that ABI private to this rootless runtime instead of downgrading the OS.
    "icu-76.1-1-x86_64.pkg.tar.zst",
    "xdotool-3.20211022.1-2-x86_64.pkg.tar.zst",
)
REMOTE_STAGE = "/home/gamer/.cache/pulsearc/projectm-runtime.new"
REMOTE_ROOT = "/home/gamer/.local/share/pulsearc/runners/projectm/root"


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
    parser.add_argument("--package-dir", type=Path, default=DEFAULT_PACKAGE_DIR)
    args = parser.parse_args()
    password = os.environ.get("PULSEARC_REMOTE_PASSWORD")
    if not password:
        raise SystemExit("PULSEARC_REMOTE_PASSWORD is required")

    packages = [args.package_dir / name for name in PACKAGE_NAMES]
    missing = [str(path) for path in packages if not path.is_file()]
    if missing:
        raise SystemExit("missing projectM packages:\n" + "\n".join(missing))
    ui = ROOT / "native-ui/pulsearc_ui.py"
    wrapper = ROOT / "live-update/pulsearc-projectm"
    xdotool_wrapper = ROOT / "live-update/pulsearc-xdotool"

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        args.host,
        username=args.user,
        password=password,
        allow_agent=False,
        look_for_keys=False,
        timeout=15,
        banner_timeout=15,
        auth_timeout=15,
    )
    try:
        remote(client, f"rm -rf {REMOTE_STAGE}; mkdir -p {REMOTE_STAGE}/packages {REMOTE_STAGE}/root")
        uploads = {
            **{path: f"{REMOTE_STAGE}/packages/{path.name}" for path in packages},
            ui: f"{REMOTE_STAGE}/pulsearc_ui.py",
            wrapper: f"{REMOTE_STAGE}/pulsearc-projectm",
            xdotool_wrapper: f"{REMOTE_STAGE}/pulsearc-xdotool",
        }
        with client.open_sftp() as sftp:
            for source, destination in uploads.items():
                sftp.put(str(source), destination)
        for source, destination in uploads.items():
            actual = remote(client, f"sha256sum {shlex.quote(destination)}").split()[0]
            if actual != digest(source):
                raise RuntimeError(f"checksum mismatch: {source.name}")

        package_commands = "; ".join(
            f"bsdtar -xf {shlex.quote(f'{REMOTE_STAGE}/packages/{path.name}')} "
            f"-C {REMOTE_STAGE}/root"
            for path in packages
        )
        remote(
            client,
            "set -e; " + package_commands + "; "
            f"test -x {REMOTE_STAGE}/root/usr/bin/projectM-pulseaudio; "
            f"LD_LIBRARY_PATH={REMOTE_STAGE}/root/usr/lib "
            f"ldd {REMOTE_STAGE}/root/usr/bin/projectM-pulseaudio | "
            "tee /tmp/pulsearc-projectm-ldd; "
            "! grep -q 'not found' /tmp/pulsearc-projectm-ldd; "
            "mkdir -p ~/.projectM ~/.local/bin ~/.local/share/pulsearc/rollback "
            "~/.local/share/pulsearc/runners/projectm; "
            "stamp=$(date +%Y%m%d-%H%M%S); backup=~/.local/share/pulsearc/rollback/$stamp-projectm; "
            "mkdir -p \"$backup\"; "
            "cp -a ~/.local/share/pulsearc/native-ui/pulsearc_ui.py \"$backup/\" 2>/dev/null || true; "
            "cp -a ~/.local/bin/pulsearc-projectm \"$backup/\" 2>/dev/null || true; "
            f"rm -rf {REMOTE_ROOT}.old; "
            f"if [ -d {REMOTE_ROOT} ]; then mv {REMOTE_ROOT} {REMOTE_ROOT}.old; fi; "
            f"mv {REMOTE_STAGE}/root {REMOTE_ROOT}; "
            f"mv {REMOTE_STAGE}/pulsearc-projectm ~/.local/bin/pulsearc-projectm; "
            f"mv {REMOTE_STAGE}/pulsearc-xdotool ~/.local/bin/pulsearc-xdotool; "
            f"mv {REMOTE_STAGE}/pulsearc_ui.py ~/.local/share/pulsearc/native-ui/pulsearc_ui.py; "
            "chmod 0755 ~/.local/bin/pulsearc-projectm ~/.local/bin/pulsearc-xdotool "
            "~/.local/share/pulsearc/native-ui/pulsearc_ui.py; "
            "cat > ~/.projectM/config.inp <<'EOF'\n"
            "Texture Size = 1024\n"
            "Mesh X = 64\n"
            "Mesh Y = 48\n"
            "FPS = 60\n"
            "Fullscreen = false\n"
            "Window Width = 1280\n"
            "Window Height = 720\n"
            "Smooth Transition Duration = 3\n"
            "Preset Duration = 20\n"
            "Shuffle Enabled = true\n"
            "Hard Cut Sensitivity = 8\n"
            "Aspect Correction = true\n"
            f"Preset Path = {REMOTE_ROOT}/usr/share/projectM/presets\n"
            f"Title Font = {REMOTE_ROOT}/usr/share/projectM/fonts/Vera.ttf\n"
            f"Menu Font = {REMOTE_ROOT}/usr/share/projectM/fonts/VeraMono.ttf\n"
            "EOF\n"
            f"rm -rf {REMOTE_ROOT}.old {REMOTE_STAGE}; "
            "~/.local/share/pulsearc/venv/bin/python -m py_compile "
            "~/.local/share/pulsearc/native-ui/pulsearc_ui.py; "
            "printf 'PULSEARC_PROJECTM_DEPLOY_OK\\n'",
            timeout=300,
        )
        print(remote(client, "~/.local/bin/pulsearc-xdotool -v"))
        print("PULSEARC_LIVE_PROJECTM_READY")
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
