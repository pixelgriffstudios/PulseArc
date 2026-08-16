#!/usr/bin/env bash
set -euo pipefail

project_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
payload_root=${PULSEARC_RECOVERY_PAYLOAD_ROOT:-/root/pulsearc-recovery}
build_root=${PULSEARC_RECOVERY_BUILD_ROOT:-$project_root/build}
profile="$build_root/recovery-profile"
work="$build_root/recovery-work"
output="$build_root/recovery-output"
publish_output="$project_root/build/recovery-output"
base_iso="$output/pulsearc-recovery-base.iso"
final_image="$output/PulseArc-SSD-Recovery.img"
payload_image="$output/pulsearc-payload.ext4"
payload_stage="$output/pulsearc-payload-files"
releng_profile=/usr/share/archiso/configs/releng

for command in mkarchiso xorriso sha256sum mkfs.ext4; do
    command -v "$command" >/dev/null || {
        echo "$command is required" >&2
        exit 1
    }
done
[[ -d "$releng_profile" ]] || { echo "ArchISO releng profile is missing" >&2; exit 1; }
[[ -r "$payload_root/pulsearc-disk.img.zst" ]] || { echo "Recovery payload is missing" >&2; exit 1; }
[[ -r "$payload_root/pulsearc-disk.img" ]] || { echo "Raw golden image is missing" >&2; exit 1; }

rm -rf -- "$profile" "$work"
install -d "$profile" "$output" "$payload_root/iso-metadata"
rsync -a "$releng_profile/" "$profile/"
rsync -a "$project_root/recovery/archiso/" "$profile/"
install -Dm755 "$project_root/recovery/profiledef.sh" "$profile/profiledef.sh"

# Remove ArchISO's installer branding and choices.  This media has one job and
# boots straight into the PulseArc SSD recovery application.
sed -i \
    -e 's/^title .*/title    PulseArc SSD Recovery/' \
    "$profile/efiboot/loader/entries/01-archiso-linux.conf"
rm -f -- "$profile/efiboot/loader/entries/02-archiso-speech-linux.conf" \
    "$profile/efiboot/loader/entries/03-archiso-memtest86+x64.conf"
sed -i -e 's/^timeout .*/timeout 0/' -e 's/^beep .*/beep off/' \
    "$profile/efiboot/loader/loader.conf"
sed -i \
    -e 's/MENU TITLE Arch Linux/MENU TITLE PulseArc SSD Recovery/' \
    -e '/MENU BACKGROUND/d' \
    "$profile/syslinux/archiso_head.cfg"
sed -i \
    -e 's/Boot the Arch Linux install medium on BIOS\./Start the PulseArc SSD recovery environment./' \
    -e 's/It allows you to install Arch Linux or perform system maintenance\./It restores the verified PulseArc system image to an internal SSD./' \
    -e 's/MENU LABEL Arch Linux install medium (%ARCH%, BIOS)/MENU LABEL Start PulseArc SSD Recovery/' \
    "$profile/syslinux/archiso_sys-linux.cfg"
sed -i -e 's/^TIMEOUT .*/TIMEOUT 1/' "$profile/syslinux/archiso_sys.cfg"
sed -i \
    -e 's/default=archlinux/default=pulsearc-recovery/' \
    -e 's/timeout=15/timeout=0/' \
    -e 's/timeout_style=menu/timeout_style=hidden/' \
    -e 's/menuentry "Arch Linux install medium (%ARCH%, ${archiso_platform})"/menuentry "PulseArc SSD Recovery"/' \
    -e "s/--id 'archlinux'/--id 'pulsearc-recovery'/" \
    "$profile/grub/grub.cfg" "$profile/grub/loopback.cfg"

# Releng supplies the proven ArchISO boot stack. Add only the recovery tools
# that are not already present and keep this environment independent of the
# much larger PulseArc gaming runtime payload.
awk 'NF && $1 !~ /^#/ && !seen[$1]++ { print $1 }' \
    "$releng_profile/packages.x86_64" "$project_root/recovery/packages.x86_64" \
    > "$profile/packages.x86_64"

raw_size=$(stat -c %s "$payload_root/pulsearc-disk.img")
printf '%s\n' "$raw_size" > "$payload_root/iso-metadata/pulsearc-disk.img.size"
(
    cd "$payload_root"
    sha256sum pulsearc-disk.img.zst > iso-metadata/pulsearc-disk.img.zst.sha256
)

mkarchiso -v -r -w "$work" -o "$output" "$profile"
built_iso=$(find "$output" -maxdepth 1 -type f -name 'pulsearc-recovery-*.iso' -printf '%T@ %p\n' |
    sort -nr | head -n 1 | cut -d' ' -f2-)
[[ -n "$built_iso" ]] || { echo "Base recovery ISO was not produced" >&2; exit 1; }
mv -f "$built_iso" "$base_iso"

# Put the verified golden disk in its own labeled filesystem.  A second ISO
# session works when QEMU presents the image as a CD, but is not reliably
# visible after Balena Etcher writes the image to a real USB drive.
rm -rf -- "$payload_stage"
install -d "$payload_stage"
install -m 0644 "$payload_root/pulsearc-disk.img.zst" \
    "$payload_root/iso-metadata/pulsearc-disk.img.zst.sha256" \
    "$payload_root/iso-metadata/pulsearc-disk.img.size" \
    "$payload_stage/"
payload_bytes=$(stat -c %s "$payload_root/pulsearc-disk.img.zst")
payload_fs_bytes=$(( (payload_bytes + 268435456 + 4095) / 4096 * 4096 ))
rm -f -- "$payload_image"
truncate -s "$payload_fs_bytes" "$payload_image"
mkfs.ext4 -q -F -T largefile4 -m 0 -L PULSEARC_PAYLOAD \
    -d "$payload_stage" "$payload_image"

rm -f "$final_image"
xorriso -indev "$base_iso" -outdev "$final_image" \
    -boot_image any replay \
    -boot_image any appended_part_as=gpt \
    -append_partition 4 0x83 "$payload_image" \
    -commit

# xorriso pads regular files after the backup GPT.  A raw USB should end at
# that GPT so firmware and disk tools do not report a mismatched disk size.
gpt_last_lba=$(xorriso -indev "$final_image" -report_system_area plain 2>/dev/null |
    awk '/GPT lba range/ { print $NF; exit }')
[[ "$gpt_last_lba" =~ ^[0-9]+$ ]] || {
    echo 'Unable to determine the final GPT sector' >&2
    exit 1
}
truncate -s "$(( (gpt_last_lba + 1) * 512 ))" "$final_image"

sha256sum "$final_image" > "$final_image.sha256"
du -h "$final_image"
if [[ $(realpath -m "$output") != $(realpath -m "$publish_output") ]]; then
    install -d "$publish_output"
    install -m 0644 "$final_image" "$final_image.sha256" "$publish_output/"
fi
