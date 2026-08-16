#!/usr/bin/env python3
"""Atomically install the official RPCS3 patch database on a live console."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.request
from pathlib import Path

import paramiko


ROOT = Path(__file__).resolve().parents[1]
SOURCE_URL = "https://rpcs3.net/compatibility?patch&api=v1&v=1.2"
REMOTE_ROOT = "/home/gamer/.local/share/pulsearc/rpcs3-patches"
REMOTE_DATABASE = REMOTE_ROOT + "/patch.yml"
CUSTOM_DATABASES = (
    ROOT / "assets/rpcs3-patches/demons-souls-blus30443-v1.00.yml",
)


def remote(client: paramiko.SSHClient, command: str, timeout: int = 180) -> str:
    _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    output = stdout.read().decode("utf-8", errors="replace")
    error = stderr.read().decode("utf-8", errors="replace")
    status = stdout.channel.recv_exit_status()
    if status:
        raise RuntimeError(f"remote command failed ({status}): {command}\n{output}\n{error}")
    return output + error


def merge_custom_database(official: str, custom: str) -> str:
    """Merge a small RPCS3 patch file into the official 1.2 database."""
    custom_lines = custom.splitlines()
    try:
        first_patch = next(
            index for index, line in enumerate(custom_lines)
            if line.startswith(("PPU-", "SPU-", "PRX-", "OVL-"))
        )
    except StopIteration as exc:
        raise RuntimeError("custom RPCS3 database has no patch records") from exc
    anchor_lines = custom_lines[1:first_patch] if custom_lines and custom_lines[0].strip() == "Anchors:" else []
    patch_lines = custom_lines[first_patch:]
    marker = "Anchors:\n"
    if marker not in official:
        raise RuntimeError("official RPCS3 database has no Anchors section")
    if anchor_lines:
        official = official.replace(marker, marker + "\n".join(anchor_lines) + "\n", 1)
    return official.rstrip() + "\n\n" + "\n".join(patch_lines).rstrip() + "\n"


def obtain_database(path: Path | None) -> bytes:
    if path is not None:
        data = path.read_bytes()
    else:
        request = urllib.request.Request(SOURCE_URL, headers={"User-Agent": "PulseArc/1.0"})
        with urllib.request.urlopen(request, timeout=60) as response:
            data = response.read(8 * 1024 * 1024)
    if not (100_000 <= len(data) <= 8 * 1024 * 1024):
        raise RuntimeError(f"unexpected RPCS3 patch database size: {len(data)} bytes")
    text = data.decode("utf-8")
    if text.lstrip().startswith("{"):
        payload = json.loads(text)
        if not isinstance(payload, dict) or not isinstance(payload.get("patch"), str):
            raise RuntimeError("RPCS3 patch API returned an invalid JSON payload")
        text = payload["patch"]
        advertised = str(payload.get("sha256", ""))
        actual = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if advertised and advertised != actual:
            raise RuntimeError("RPCS3 patch API checksum mismatch")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if not (100_000 <= len(text.encode("utf-8")) <= 8 * 1024 * 1024):
        raise RuntimeError(f"unexpected decoded RPCS3 patch size: {len(text)} characters")
    if "Version: 1.2" not in text or "BCUS98174:" not in text:
        raise RuntimeError("RPCS3 patch database failed its format/content checks")
    for custom_path in CUSTOM_DATABASES:
        custom = custom_path.read_text(encoding="utf-8")
        text = merge_custom_database(text, custom)
    if "Infinite HP + Infinite MP + Infinite SP (Artemis)" not in text:
        raise RuntimeError("Demon's Souls gameplay cheats were not merged")
    return text.encode("utf-8")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("host")
    parser.add_argument("--user", default="gamer")
    parser.add_argument("--database", type=Path)
    args = parser.parse_args()
    password = os.environ.get("PULSEARC_REMOTE_PASSWORD")
    if not password:
        raise SystemExit("PULSEARC_REMOTE_PASSWORD is required")
    data = obtain_database(args.database)
    expected = hashlib.sha256(data).hexdigest()

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(args.host, username=args.user, password=password, allow_agent=False,
                   look_for_keys=False, timeout=15, banner_timeout=15, auth_timeout=15)
    try:
        stage = "/home/gamer/.cache/pulsearc/rpcs3-patch.yml.new"
        remote(client, f"install -d -m 0755 ~/.cache/pulsearc {REMOTE_ROOT}")
        with client.open_sftp() as sftp:
            with sftp.open(stage, "wb") as output:
                output.write(data)
            sftp.chmod(stage, 0o644)
        actual = remote(client, f"sha256sum {stage}").split()[0]
        if actual != expected:
            raise RuntimeError("RPCS3 patch database checksum mismatch after upload")
        remote(
            client,
            "set -e; stamp=$(date +%Y%m%d-%H%M%S); "
            "backup=$HOME/.local/share/pulsearc/rollback/$stamp-rpcs3-patches; "
            f"mkdir -p \"$backup\"; cp -a {REMOTE_DATABASE} \"$backup/\" 2>/dev/null || true; "
            f"mv {stage} {REMOTE_DATABASE}; chmod 0644 {REMOTE_DATABASE}",
        )
        raw = remote(
            client,
            "PYTHONPATH=$HOME/.local/share/pulsearc/core "
            "$HOME/.local/share/pulsearc/venv/bin/python -m pulsearc.control "
            "manager-json cheats --profile default",
        )
        games = json.loads(raw)
        demon_souls = next(
            (
                game for game in games
                if str(game.get("title", "")).casefold() == "demon's souls"
                and game.get("platform") == "playstation-3"
            ),
            None,
        )
        if not demon_souls or int(demon_souls.get("cheat_count", 0)) < 13:
            raise RuntimeError("Demon's Souls gameplay cheats were not discovered after deployment")
        if int(demon_souls.get("enabled_count", 0)) != 0:
            raise RuntimeError("patch deployment unexpectedly enabled a cheat")
        print(json.dumps({
            "database_sha256": expected,
            "demons_souls": demon_souls,
        }, indent=2))
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
