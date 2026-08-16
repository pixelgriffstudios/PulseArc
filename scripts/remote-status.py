#!/usr/bin/env python3
"""Report the health of a running PulseArc development console."""

from __future__ import annotations

import argparse
import os
import sys

import paramiko


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
        args.host,
        username=args.user,
        password=password,
        allow_agent=False,
        look_for_keys=False,
        timeout=15,
    )
    try:
        command = """
pgrep -af pulsearc_ui || true
pgrep -af pulsearc.metadata_daemon || true
test -x ~/.local/share/pulsearc/native-ui/pulsearc_3d_library.py && echo 3D_RENDERER_READY
wpctl status -n | sed -n '/Sinks:/,/Sources:/p'
DISPLAY=:0 glxinfo -B 2>/dev/null | grep -E 'direct rendering|OpenGL vendor|OpenGL renderer|OpenGL core profile version|OpenGL version' || true
tail -n 15 /tmp/pulsearc-user-metadata.log 2>/dev/null || true
PYGAME_HIDE_SUPPORT_PROMPT=1 ~/.local/share/pulsearc/venv/bin/python - <<'PY'
import pygame
pygame.joystick.init()
for index in range(pygame.joystick.get_count()):
    stick = pygame.joystick.Joystick(index)
    stick.init()
    print(f"CONTROLLER name={stick.get_name()!r} guid={stick.get_guid()} axes={stick.get_numaxes()} hats={stick.get_numhats()}")
pygame.quit()
PY
"""
        _stdin, stdout, stderr = client.exec_command(command, timeout=20)
        print(stdout.read().decode("utf-8", errors="replace"), end="")
        print(stderr.read().decode("utf-8", errors="replace"), end="")
        return stdout.channel.recv_exit_status()
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
