#!/usr/bin/env bash
set -euo pipefail

test_root=/tmp/pulsearc-update-rollback-root
archive=/tmp/PulseArc-rollback-test.update.zip
outside=/tmp/pulsearc-update-outside
rm -rf -- "$test_root" "$outside"
mkdir -p "$test_root/usr/share/pulsearc/native-ui" "$test_root/usr/lib" "$outside"
printf 'ORIGINAL\n' > "$test_root/usr/share/pulsearc/native-ui/first.txt"
ln -s "$outside" "$test_root/usr/lib/pulsearc"
set +e
PYTHONPATH=/tmp /usr/bin/python - "$archive" "$test_root" <<'PY'
import sys
from pathlib import Path
from pulsearc_updater import apply_archive

apply_archive(Path(sys.argv[1]), Path(sys.argv[2]))
PY
status=$?
set -e
[[ $status -ne 0 ]]
[[ $(cat "$test_root/usr/share/pulsearc/native-ui/first.txt") == ORIGINAL ]]
[[ ! -e "$outside/core/pulsearc/second.txt" ]]
printf 'PULSEARC_LIVE_ROLLBACK_TEST_OK\n'
