#!/usr/bin/env python3
"""Restore a private Xtream cache atomically without exposing its credentials."""

from __future__ import annotations

import argparse
import json
import os
import posixpath
import sys
from pathlib import Path

import paramiko


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("host")
    parser.add_argument("cache", type=Path)
    parser.add_argument("--user", default="gamer")
    args = parser.parse_args()
    password = os.environ.get("PULSEARC_REMOTE_PASSWORD")
    if not password:
        raise SystemExit("PULSEARC_REMOTE_PASSWORD is required")
    payload = json.loads(args.cache.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise SystemExit("cache is not a channel list")
    live = sum(str(item.get("group", "")).startswith("LIVE / ") for item in payload if isinstance(item, dict))
    vod = sum(str(item.get("group", "")).startswith("VOD / ") for item in payload if isinstance(item, dict))
    if not live or not vod:
        raise SystemExit("refusing cache without both Live and VOD entries")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(args.host, username=args.user, password=password, allow_agent=False,
                   look_for_keys=False, timeout=15, banner_timeout=15, auth_timeout=15)
    try:
        root = "/home/gamer/.cache/pulsearc/tv"
        with client.open_sftp() as sftp:
            candidates = [name for name in sftp.listdir(root) if name.endswith(".xtream.json")]
            if len(candidates) != 1:
                raise RuntimeError(f"expected one private Xtream cache, found {len(candidates)}")
            target = posixpath.join(root, candidates[0])
            temporary = target + ".restore"
            sftp.put(str(args.cache), temporary)
            sftp.chmod(temporary, 0o600)
            sftp.posix_rename(temporary, target)
        print(f"PRIVATE_TV_CACHE_RESTORED entries={len(payload)} live={live} vod={vod}")
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
