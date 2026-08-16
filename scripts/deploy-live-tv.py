#!/usr/bin/env python3
"""Atomically deploy PulseArc TV/radio/DVR changes to a live console."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import sys
from pathlib import Path

import paramiko


ROOT = Path(__file__).resolve().parents[1]
FILES = {
    ROOT / "native-ui/pulsearc_ui.py": "/home/gamer/.local/share/pulsearc/native-ui/pulsearc_ui.py.new",
    ROOT / "native-ui/pulsearc_tv.py": "/home/gamer/.local/share/pulsearc/native-ui/pulsearc_tv.py.new",
    ROOT / "native-ui/pulsearc_network.py": "/home/gamer/.local/share/pulsearc/native-ui/pulsearc_network.py.new",
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


def install_private_source(client: paramiko.SSHClient) -> None:
    server = os.environ.get("PULSEARC_XTREAM_SERVER", "").strip()
    username = os.environ.get("PULSEARC_XTREAM_USERNAME", "")
    password = os.environ.get("PULSEARC_XTREAM_PASSWORD", "")
    if not (server and username and password):
        return
    destination = "/home/gamer/.local/share/pulsearc/tv/sources.json"
    sources: list[dict[str, object]] = []
    with client.open_sftp() as sftp:
        try:
            with sftp.open(destination, "r") as handle:
                payload = json.loads(handle.read().decode("utf-8", errors="replace"))
            if isinstance(payload, dict) and isinstance(payload.get("sources"), list):
                sources = [dict(item) for item in payload["sources"] if isinstance(item, dict)]
        except (FileNotFoundError, OSError, ValueError, TypeError):
            pass
        replacement = {
            "name": "One Xtreme IPTV",
            "type": "xtream",
            "server": server,
            "username": username,
            "password": password,
            "output": "ts",
        }
        sources = [item for item in sources if str(item.get("name", "")).casefold() != "one xtreme iptv"]
        sources.append(replacement)
        temporary = destination + ".new"
        with sftp.open(temporary, "w") as handle:
            handle.write((json.dumps({"sources": sources}, indent=2) + "\n").encode("utf-8"))
        sftp.chmod(temporary, 0o600)
    remote(client, f"mv {shlex.quote(destination + '.new')} {shlex.quote(destination)}; chmod 0600 {shlex.quote(destination)}")


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
        timeout=15,
        banner_timeout=15,
        auth_timeout=15,
        allow_agent=False,
        look_for_keys=False,
    )
    try:
        remote(
            client,
            "install -d -m 0755 ~/.local/share/pulsearc/native-ui ~/.local/share/pulsearc/tv "
            "~/.local/share/pulsearc/rollback ~/.cache/pulsearc/tv",
        )
        with client.open_sftp() as sftp:
            for source, destination in FILES.items():
                sftp.put(str(source), destination)
                sftp.chmod(destination, 0o755)
        for source, destination in FILES.items():
            actual = remote(client, f"sha256sum {shlex.quote(destination)}").split()[0]
            if actual != digest(source):
                raise RuntimeError(f"checksum mismatch: {source.name}")
        remote(
            client,
            "set -e; stamp=$(date +%Y%m%d-%H%M%S); backup=~/.local/share/pulsearc/rollback/$stamp-tv; "
            "mkdir -p \"$backup\"; "
            "cp -a ~/.local/share/pulsearc/native-ui/pulsearc_ui.py \"$backup/\" 2>/dev/null || true; "
            "cp -a ~/.local/share/pulsearc/native-ui/pulsearc_tv.py \"$backup/\" 2>/dev/null || true; "
            "cp -a ~/.local/share/pulsearc/native-ui/pulsearc_network.py \"$backup/\" 2>/dev/null || true; "
            "mv ~/.local/share/pulsearc/native-ui/pulsearc_ui.py.new ~/.local/share/pulsearc/native-ui/pulsearc_ui.py; "
            "mv ~/.local/share/pulsearc/native-ui/pulsearc_tv.py.new ~/.local/share/pulsearc/native-ui/pulsearc_tv.py; "
            "mv ~/.local/share/pulsearc/native-ui/pulsearc_network.py.new ~/.local/share/pulsearc/native-ui/pulsearc_network.py; "
            "chmod 0755 ~/.local/share/pulsearc/native-ui/pulsearc_ui.py ~/.local/share/pulsearc/native-ui/pulsearc_tv.py ~/.local/share/pulsearc/native-ui/pulsearc_network.py; "
            "~/.local/share/pulsearc/venv/bin/python -m py_compile "
            "~/.local/share/pulsearc/native-ui/pulsearc_ui.py ~/.local/share/pulsearc/native-ui/pulsearc_tv.py "
            "~/.local/share/pulsearc/native-ui/pulsearc_network.py; "
            "command -v ffmpeg >/dev/null; command -v mpv >/dev/null; "
            "printf 'PULSEARC_TV_FILES_OK\\n'",
        )
        install_private_source(client)
        print(remote(
            client,
            "~/.local/share/pulsearc/venv/bin/python ~/.local/share/pulsearc/native-ui/pulsearc_ui.py --self-test",
        ))
        print(remote(
            client,
            "cd ~/.local/share/pulsearc/native-ui && ~/.local/share/pulsearc/venv/bin/python - <<'PY'\n"
            "from pathlib import Path\n"
            "from pulsearc_tv import BUILTIN_TV_SOURCES, fetch_source, load_saved_sources\n"
            "sources=[*BUILTIN_TV_SOURCES,*load_saved_sources(Path.home()/'.local/share/pulsearc/tv/sources.json')]\n"
            "for source in sources:\n"
            "    channels,cached=fetch_source(source,Path.home()/'.cache/pulsearc/tv',timeout=45)\n"
            "    groups=len({item.get('group','OTHER') for item in channels})\n"
            "    print('%s: channels=%d groups=%d cached=%s' % (source.get('name','SOURCE'),len(channels),groups,cached))\n"
            "PY",
            timeout=90,
        ))
        print("PULSEARC_LIVE_TV_READY")
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
