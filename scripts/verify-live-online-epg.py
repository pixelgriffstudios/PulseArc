#!/usr/bin/env python3
"""Verify PulseArc's online US EPG fallback on a live console."""

from __future__ import annotations

import argparse
import os
import sys

import paramiko


REMOTE_CHECK = r"""
cd ~/.local/share/pulsearc/native-ui && ~/.local/share/pulsearc/venv/bin/python - <<'PY'
from pathlib import Path
from pulsearc_tv import fetch_source, fetch_us_online_epg, load_saved_sources
source = next(item for item in load_saved_sources(Path.home()/'.local/share/pulsearc/tv/sources.json') if item.get('type') == 'xtream')
channels, _cached = fetch_source(source, Path.home()/'.cache/pulsearc/tv', timeout=45)
for wanted in ('US: AMC HD', 'US: MTV HD'):
    channel = next((item for item in channels if item.get('name') == wanted), None)
    programs = fetch_us_online_epg(channel or {'name': wanted}, Path.home()/'.cache/pulsearc/tv')
    print('ONLINE_EPG channel=%s programs=%d title=%s' % (wanted, len(programs), programs[0].get('title', '')[:80] if programs else 'NONE'))
PY
"""


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
    client.connect(args.host, username=args.user, password=password, allow_agent=False,
                   look_for_keys=False, timeout=15, banner_timeout=15, auth_timeout=15)
    try:
        _stdin, stdout, stderr = client.exec_command(REMOTE_CHECK, timeout=180)
        output = stdout.read().decode("utf-8", errors="replace")
        error = stderr.read().decode("utf-8", errors="replace")
        status = stdout.channel.recv_exit_status()
        if status:
            raise RuntimeError(error or output)
        print(output.strip())
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
