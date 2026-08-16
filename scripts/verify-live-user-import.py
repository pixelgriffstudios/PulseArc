#!/usr/bin/env python3
"""Verify imported games, cheats, launch plans, and physical-disc detection live."""

from __future__ import annotations

import argparse
import os

import paramiko


REMOTE_HELPER = r'''import importlib.util
import json
import tempfile
from pathlib import Path

from pulsearc.control import manager_json
from pulsearc.graphics import GraphicsPolicy
from pulsearc.launch import create_launch_plan
from pulsearc.registry import RuntimeRegistry

library = json.loads(Path("/run/pulsearc/library.json").read_text(encoding="utf-8"))
by_title = {item["title"]: item for item in library}
expected = {
    "Tecmo Super Bowl", "Baseball Stars II", "Contra", "Double Dragon II: The Revenge",
    "DuckTales", "Kirby's Adventure", "The Legend of Zelda", "Metroid",
    "Mike Tyson's Punch-Out!!", "R.C. Pro-Am II", "Super Mario Bros.",
    "Super Mario Bros. 3", "Super Mario 64", "Mario Kart 64", "GoldenEye 007",
    "Pilotwings 64", "Beyond the Beyond", "Speed Devils",
}
missing = sorted(expected - by_title.keys())
assert not missing, f"missing games: {missing}"
assert not any("Track " in item["title"] for item in library), "disc tracks leaked into library"

cheat_games = json.loads(manager_json("cheats", "default"))
assert sum(item["cheat_count"] > 0 for item in cheat_games) == 16
assert sum(item["enabled_count"] for item in cheat_games) == 0

registry = RuntimeRegistry.load("/usr/share/pulsearc/config/systems.toml")
policy = GraphicsPolicy("x11", "wined3d", "unsupported", "verification")
installed = {"/usr/bin/retroarch", "/usr/local/bin/pulsearc-appimage"}
plans = {}
for title in ("Beyond the Beyond", "Speed Devils"):
    entry = by_title[title]
    plan = create_launch_plan(entry["path"], entry["platform"], entry["content_id"],
                              "default", registry, policy, installed_executables=installed)
    plans[title] = {"runner": plan.runner_id, "command": list(plan.command)}

spec = importlib.util.spec_from_file_location(
    "pulsearc_native_ui", "/home/gamer/.local/share/pulsearc/native-ui/pulsearc_ui.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    disc = root / "PS_DISC"
    disc.mkdir()
    marker = disc / "SYSTEM.CNF"
    marker.write_text("BOOT = cdrom:\\\\SCUS_123.45;1\n", encoding="ascii")
    assert module.detected_playstation_disc(root)["platform"] == "playstation"
    marker.write_text("BOOT2 = cdrom0:\\\\SLUS_999.01;1\n", encoding="ascii")
    assert module.detected_playstation_disc(root)["platform"] == "playstation-2"
assert module.ssh_password() != "generating"
assert "GB free" in module.internal_free_space()
print(json.dumps({
    "library_entries": len(library), "new_games": len(expected),
    "cheat_games": 16, "enabled_cheats": 0, "launch_plans": plans,
    "disc_detection": ["playstation", "playstation-2"],
    "free_space": module.internal_free_space(),
}, indent=2))
'''


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
    client.connect(args.host, username=args.user, password=password, allow_agent=False,
                   look_for_keys=False, timeout=15, banner_timeout=15, auth_timeout=15)
    try:
        target = "/home/gamer/.cache/pulsearc-verify-import.py"
        with client.open_sftp() as sftp:
            with sftp.open(target, "w") as output:
                output.write(REMOTE_HELPER)
        command = (
            "PYTHONPATH=$HOME/.local/share/pulsearc/core "
            "$HOME/.local/share/pulsearc/venv/bin/python " + target
        )
        _stdin, stdout, stderr = client.exec_command(command, timeout=900)
        print(stdout.read().decode("utf-8", errors="replace"), end="")
        print(stderr.read().decode("utf-8", errors="replace"), end="")
        status = stdout.channel.recv_exit_status()
        client.exec_command(f"rm -f {target}")
        return status
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
