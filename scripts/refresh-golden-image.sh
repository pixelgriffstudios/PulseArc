#!/usr/bin/env bash
set -euo pipefail

project_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
image=${1:-/root/pulsearc-recovery/pulsearc-disk.img}
compressed=${2:-/root/pulsearc-recovery/pulsearc-disk.img.zst}
root=/mnt/golden-root
efi=/mnt/golden-efi

[[ -f "$image" ]]
[[ -f "$compressed" ]]
zstd -q -t "$compressed"

loop=$(losetup --find --show -P "$image")
cleanup() {
    sync
    umount "$root/var/lib/pulsearc" 2>/dev/null || true
    umount "$root/home" 2>/dev/null || true
    umount "$root" 2>/dev/null || true
    umount "$efi" 2>/dev/null || true
    losetup -d "$loop" 2>/dev/null || true
}
trap cleanup EXIT

mkdir -p "$root" "$efi"
mount -o subvol=@ "${loop}p3" "$root"
mount -o subvol=@home "${loop}p3" "$root/home"
mount -o subvol=@state "${loop}p3" "$root/var/lib/pulsearc"
mount "${loop}p2" "$efi"

"$project_root/scripts/prepare-golden-image.sh" "$root" "$efi"
"$project_root/scripts/audit-public-root.sh" "$root"
sync
printf 'PULSEARC_GOLDEN_REFRESH_OK\n'
