#!/usr/bin/env python3
"""Deploy the fullscreen, optical-disc, cheat, cover, and IPTV stability fixes."""

from __future__ import annotations

import argparse
import hashlib
import os
import shlex
import sys
from pathlib import Path

import paramiko


ROOT = Path(__file__).resolve().parents[1]
FILES = {
    ROOT / "native-ui/pulsearc_ui.py":
        "/home/gamer/.local/share/pulsearc/native-ui/pulsearc_ui.py.new",
    ROOT / "src/pulsearc/control.py":
        "/home/gamer/.local/share/pulsearc/core/pulsearc/control.py.new",
    ROOT / "src/pulsearc/cheat_export.py":
        "/home/gamer/.local/share/pulsearc/core/pulsearc/cheat_export.py.new",
    ROOT / "archiso/airootfs/usr/share/pulsearc/artwork/offline/nes/516.png":
        "/home/gamer/.cache/pulsearc/smb1-cover.png.new",
    ROOT / "archiso/airootfs/usr/share/pulsearc/artwork/offline/nes/518.png":
        "/home/gamer/.cache/pulsearc/smb3-cover.png.new",
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
            "~/.cache/pulsearc",
        )
        with client.open_sftp() as sftp:
            for local, target in FILES.items():
                if not local.is_file():
                    raise FileNotFoundError(local)
                sftp.put(str(local), target)
                sftp.chmod(target, 0o644)
        for local, target in FILES.items():
            actual = remote(client, f"sha256sum {shlex.quote(target)}").split()[0]
            if actual != digest(local):
                raise RuntimeError(f"checksum mismatch: {target}")

        # Compile staged Python before replacing any working file.
        print(remote(
            client,
            "PYTHONPATH=$HOME/.local/share/pulsearc/core "
            "$HOME/.local/share/pulsearc/venv/bin/python -m py_compile "
            "$HOME/.local/share/pulsearc/native-ui/pulsearc_ui.py.new "
            "$HOME/.local/share/pulsearc/core/pulsearc/control.py.new "
            "$HOME/.local/share/pulsearc/core/pulsearc/cheat_export.py.new; "
            "echo PULSEARC_STAGED_COMPILE_OK",
        ))

        print(remote(
            client,
            "stamp=$(date +%Y%m%d-%H%M%S); backup=$HOME/.local/share/pulsearc/rollback/$stamp-launch-stability; "
            "mkdir -p \"$backup\"; "
            "cp -a ~/.local/share/pulsearc/native-ui/pulsearc_ui.py \"$backup/\"; "
            "cp -a ~/.local/share/pulsearc/core/pulsearc/control.py \"$backup/\"; "
            "cp -a ~/.local/share/pulsearc/core/pulsearc/cheat_export.py \"$backup/\"; "
            "cp -a /var/lib/pulsearc/library/games/nes/super-mario-bros/cover.png \"$backup/smb1-cover.png\"; "
            "cp -a /var/lib/pulsearc/library/games/nes/super-mario-bros-3/cover.png \"$backup/smb3-cover.png\"; "
            "mv ~/.local/share/pulsearc/native-ui/pulsearc_ui.py.new ~/.local/share/pulsearc/native-ui/pulsearc_ui.py; "
            "mv ~/.local/share/pulsearc/core/pulsearc/control.py.new ~/.local/share/pulsearc/core/pulsearc/control.py; "
            "mv ~/.local/share/pulsearc/core/pulsearc/cheat_export.py.new ~/.local/share/pulsearc/core/pulsearc/cheat_export.py; "
            "mv ~/.cache/pulsearc/smb1-cover.png.new /var/lib/pulsearc/library/games/nes/super-mario-bros/cover.png; "
            "mv ~/.cache/pulsearc/smb3-cover.png.new /var/lib/pulsearc/library/games/nes/super-mario-bros-3/cover.png; "
            "chmod 0644 ~/.local/share/pulsearc/native-ui/pulsearc_ui.py "
            "~/.local/share/pulsearc/core/pulsearc/control.py "
            "~/.local/share/pulsearc/core/pulsearc/cheat_export.py "
            "/var/lib/pulsearc/library/games/nes/super-mario-bros/cover.png "
            "/var/lib/pulsearc/library/games/nes/super-mario-bros-3/cover.png; "
            "echo PULSEARC_ATOMIC_INSTALL_OK",
        ))

        # Regenerate the two affected emulator cheat files immediately. The
        # normal launch path will repeat this safely on every later launch.
        regenerate = r'''PYTHONPATH=$HOME/.local/share/pulsearc/core /usr/bin/python - <<'PY'
import json
from pathlib import Path
from pulsearc.cheats import cheat_file, load_cheats
from pulsearc.control import (
    STATE, _duckstation_serial, _prepare_duckstation_cheats,
    _prepare_duckstation_config,
    _prepare_retroarch_config,
)

entries = {item["content_id"]: item for item in json.loads(Path("/run/pulsearc/library.json").read_text())}
profile = "default"

nes_id = "bcc54ca396b1cc7815939fd4"
nes = entries[nes_id]
nes_cheats = load_cheats(cheat_file(STATE, profile, "nes", nes_id))
_prepare_retroarch_config(
    STATE / "profiles" / profile / "games" / nes_id,
    "retroarch-mesen", Path(nes["path"]), nes_cheats,
)

ps1_id = "6027bdc27c0fbd6fb8ba7e31"
ps1 = entries[ps1_id]
ps1_cheats = load_cheats(cheat_file(STATE, profile, "playstation", ps1_id))
_prepare_duckstation_config(STATE / "profiles" / profile / "games" / ps1_id)
_prepare_duckstation_cheats(
    STATE / "profiles" / profile / "games" / ps1_id,
    _duckstation_serial(ps1), ps1_cheats,
)
print("PULSEARC_CHEAT_REGEN_OK")
PY'''
        print(remote(client, regenerate))

        print(remote(
            client,
            "PYTHONPATH=$HOME/.local/share/pulsearc/core "
            "$HOME/.local/share/pulsearc/venv/bin/python -m py_compile "
            "$HOME/.local/share/pulsearc/native-ui/pulsearc_ui.py "
            "$HOME/.local/share/pulsearc/core/pulsearc/control.py "
            "$HOME/.local/share/pulsearc/core/pulsearc/cheat_export.py; "
            "grep -q 'cheat0_handler = \"0\"' "
            "'/var/lib/pulsearc/profiles/default/games/bcc54ca396b1cc7815939fd4/config/retroarch/cheats/Mesen/Super Mario Bros. 3 (USA) (Rev 1).cht'; "
            "grep -q 'cheat0_cheat_type = \"1\"' "
            "'/var/lib/pulsearc/profiles/default/games/bcc54ca396b1cc7815939fd4/config/retroarch/cheats/Mesen/Super Mario Bros. 3 (USA) (Rev 1).cht'; "
            "test $(grep -c '^\\[Cheats\\]$' "
            "/var/lib/pulsearc/profiles/default/games/6027bdc27c0fbd6fb8ba7e31/config/duckstation/gamesettings/SCUS-94702.ini) -eq 1; "
            "grep -q '^EnableCheats = true$' "
            "/var/lib/pulsearc/profiles/default/games/6027bdc27c0fbd6fb8ba7e31/config/duckstation/gamesettings/SCUS-94702.ini; "
            "grep -q '^Enable = ' "
            "/var/lib/pulsearc/profiles/default/games/6027bdc27c0fbd6fb8ba7e31/config/duckstation/gamesettings/SCUS-94702.ini; "
            "echo PULSEARC_LIVE_VALIDATION_OK",
        ))
        print("PULSEARC_LIVE_LAUNCH_STABILITY_OK")
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
