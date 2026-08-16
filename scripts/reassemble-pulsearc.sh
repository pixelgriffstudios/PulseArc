#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
image=PulseArc-0.1.0-beta.1-Installer.img
parts=("$image".part-*)
[[ -e "${parts[0]}" ]] || { echo "No $image.part-* files found" >&2; exit 1; }

cat "${parts[@]}" > "$image"
sha256sum -c "$image.sha256"
printf 'Verified: %s/%s\n' "$PWD" "$image"
