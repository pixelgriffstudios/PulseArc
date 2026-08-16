#!/usr/bin/env python3
"""Verify that a live PulseArc console can obtain one Xtream Now/Next guide."""

from __future__ import annotations

import argparse
import os
import sys

import paramiko


REMOTE_CHECK = r"""
cd ~/.local/share/pulsearc/native-ui && ~/.local/share/pulsearc/venv/bin/python - <<'PY'
from pathlib import Path
from pulsearc_tv import fetch_source, fetch_xtream_short_epg, load_saved_sources
sources = load_saved_sources(Path.home()/'.local/share/pulsearc/tv/sources.json')
source = next((item for item in sources if item.get('type') == 'xtream'), None)
if not source:
    raise SystemExit('NO_XTREAM_SOURCE')
channels, _cached = fetch_source(source, Path.home()/'.cache/pulsearc/tv', timeout=45)
live = [item for item in channels if item.get('media_type') == 'live' and item.get('stream_id')]
with_epg_id = [item for item in live if item.get('tvg_id')]
checked = 0
for channel in [*with_epg_id[:300], *live[:80]]:
    checked += 1
    programs = fetch_xtream_short_epg(source, channel['stream_id'], limit=4, timeout=12)
    if programs:
        print('TV_GUIDE_OK channel=%s programs=%d title=%s' % (
            channel.get('name', 'CHANNEL')[:60], len(programs), programs[0].get('title', '')[:80]))
        break
else:
    print('TV_GUIDE_NO_LISTINGS checked=%d live=%d channels_with_epg_id=%d' % (
        checked, len(live), len(with_epg_id)))
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
