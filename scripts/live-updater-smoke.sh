#!/usr/bin/env bash
set -euo pipefail

test_root=/tmp/pulsearc-update-test-root
archive=${1:-/tmp/PulseArc-0.1.0-beta.1.update.zip}
rm -rf -- "$test_root"
mkdir -p "$test_root"
PYTHONPATH=/tmp /usr/bin/python - "$archive" "$test_root" <<'PY'
import json
import sys
from pathlib import Path
from pulsearc_updater import apply_archive

print(json.dumps(apply_archive(Path(sys.argv[1]), Path(sys.argv[2]))))
PY
sha256sum "$test_root/usr/share/pulsearc/native-ui/pulsearc_ui.py"
cat "$test_root/etc/pulsearc/release.json"
