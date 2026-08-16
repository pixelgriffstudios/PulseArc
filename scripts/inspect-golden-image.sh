#!/usr/bin/env bash
set -euo pipefail

image=${1:-/root/pulsearc-recovery/pulsearc-disk.img}
mount_root=/mnt/pulsearc-audit
loop=$(losetup --find --show -P -r "$image")
cleanup() {
    umount "$mount_root" 2>/dev/null || true
    losetup -d "$loop" 2>/dev/null || true
}
trap cleanup EXIT
mkdir -p "$mount_root"
mount -o ro,subvolid=5 "${loop}p3" "$mount_root"
btrfs subvolume list "$mount_root"
findmnt -no FSTYPE,OPTIONS "$mount_root"
