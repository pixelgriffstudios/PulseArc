#!/usr/bin/env bash
set -euo pipefail

output=/root/pulsearc/build/vm/hell-on-rails-pulsearc.img
source_root=/mnt/helllegacy
mount_root=/mnt/hellpulse
loop_device=/dev/loop7

[[ ! -e "$output" ]] || {
    printf 'Refusing to overwrite existing test image: %s\n' "$output" >&2
    exit 1
}
[[ -f "$source_root/content/hell-on-rails.exe" ]]
[[ ! -e "$loop_device" || -z "$(losetup "$loop_device" 2>/dev/null || true)" ]]

cleanup() {
    mountpoint -q "$mount_root" && umount "$mount_root" || true
    losetup "$loop_device" >/dev/null 2>&1 && losetup -d "$loop_device" || true
}
trap cleanup EXIT

truncate -s 512M "$output"
printf 'label: gpt\n2048,,L\n' | sfdisk "$output"
losetup --partscan "$loop_device" "$output"
udevadm settle
mkfs.ext4 -q -L HELLONRAILS_NEW "${loop_device}p1"
mkdir -p "$mount_root"
mount "${loop_device}p1" "$mount_root"
mkdir -p "$mount_root/content"
cp "$source_root/content/hell-on-rails.exe" "$mount_root/content/"
cp "$source_root/icon.png" "$mount_root/icon.png"
cp /root/pulsearc/examples/hell-on-rails/pulsearc.toml "$mount_root/pulsearc.toml"
sync
ls -lh "$mount_root" "$mount_root/content"
cleanup
trap - EXIT
sha256sum "$output"
