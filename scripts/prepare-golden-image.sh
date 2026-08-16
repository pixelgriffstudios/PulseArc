#!/usr/bin/env bash
set -euo pipefail

project_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
source_root="$project_root/archiso/airootfs"
target_root=${1:-/mnt/golden-root}
target_efi=${2:-/mnt/golden-efi}

[[ -e "$target_root/etc/pulsearc/installed" ]] || {
    echo "Refusing to modify a root that is not an installed PulseArc system" >&2
    exit 1
}
mountpoint -q "$target_root"
mountpoint -q "$target_root/home"
mountpoint -q "$target_root/var/lib/pulsearc"
mountpoint -q "$target_efi"

for source in "$source_root"/usr/local/bin/pulsearc-*; do
    install -Dm755 "$source" "$target_root/usr/local/bin/${source##*/}"
done
for source in "$source_root"/usr/local/sbin/pulsearc-*; do
    install -Dm755 "$source" "$target_root/usr/local/sbin/${source##*/}"
done
rm -rf -- "$target_root/usr/share/pulsearc/native-ui"
install -d -m 0755 "$target_root/usr/share/pulsearc/native-ui"
cp -a "$project_root/native-ui/." "$target_root/usr/share/pulsearc/native-ui/"
find "$target_root/usr/share/pulsearc/native-ui" -type d -exec chmod 0755 {} +
find "$target_root/usr/share/pulsearc/native-ui" -type f -exec chmod 0644 {} +
rm -rf -- "$target_root/usr/lib/pulsearc/core/pulsearc"
install -d -m 0755 "$target_root/usr/lib/pulsearc/core/pulsearc"
find "$project_root/src/pulsearc" -maxdepth 1 -type f -name '*.py' -exec \
    install -m 0644 -t "$target_root/usr/lib/pulsearc/core/pulsearc" {} +
rm -rf -- "$target_root/usr/share/pulsearc/config"
install -d -m 0755 "$target_root/usr/share/pulsearc/config"
cp -a "$project_root/config/." "$target_root/usr/share/pulsearc/config/"
find "$target_root/usr/share/pulsearc/config" -type d -exec chmod 0755 {} +
find "$target_root/usr/share/pulsearc/config" -type f -exec chmod 0644 {} +
for source in "$source_root"/etc/systemd/system/pulsearc-*; do
    install -Dm644 "$source" "$target_root/etc/systemd/system/${source##*/}"
done
install -Dm440 "$source_root/etc/sudoers.d/20-pulsearc-installer" \
    "$target_root/etc/sudoers.d/20-pulsearc-installer"
install -Dm644 "$source_root/etc/pulsearc/release.json" \
    "$target_root/etc/pulsearc/release.json"

# A public image must not inherit anything from the development user's home.
find "$target_root/home/gamer" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
install -Dm644 -o 1000 -g 1000 "$source_root/home/gamer/.bash_profile" \
    "$target_root/home/gamer/.bash_profile"
install -Dm755 -o 1000 -g 1000 "$source_root/home/gamer/.xinitrc" \
    "$target_root/home/gamer/.xinitrc"
install -Dm644 "$project_root/recovery/startup.nsh" "$target_efi/startup.nsh"

rm -f "$target_root/home/gamer/pulsearc-session-debug"
install -d "$target_root/etc/systemd/system/multi-user.target.wants"
ln -sfn /etc/systemd/system/pulsearc-expand-root.service \
    "$target_root/etc/systemd/system/multi-user.target.wants/pulsearc-expand-root.service"

# Factory-reset volatile and machine-specific state. The exact roots are
# validated above before any removal occurs.
find "$target_root/var/lib/pulsearc" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
install -d -m 0755 -o 1000 -g 1000 \
    "$target_root/var/lib/pulsearc/library/games/windows/hell-on-rails/content"
install -m 0644 -o 1000 -g 1000 \
    "$project_root/public-content/hell-on-rails/pulsearc.toml" \
    "$target_root/var/lib/pulsearc/library/games/windows/hell-on-rails/pulsearc.toml"
install -m 0644 -o 1000 -g 1000 \
    "$project_root/public-content/hell-on-rails/cover.png" \
    "$target_root/var/lib/pulsearc/library/games/windows/hell-on-rails/cover.png"
install -m 0755 -o 1000 -g 1000 \
    "$project_root/public-content/hell-on-rails/content/hell-on-rails.exe" \
    "$target_root/var/lib/pulsearc/library/games/windows/hell-on-rails/content/hell-on-rails.exe"
rm -f "$target_root/etc/ssh/ssh_host_"* "$target_root/var/lib/systemd/random-seed"
truncate -s 0 "$target_root/etc/machine-id"
find "$target_root/etc/NetworkManager/system-connections" -mindepth 1 -maxdepth 1 \
    -type f -delete 2>/dev/null || true
chown -R 1000:1000 "$target_root/home/gamer" "$target_root/var/lib/pulsearc"
sync
