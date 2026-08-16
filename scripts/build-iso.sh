#!/usr/bin/env bash
set -euo pipefail

project_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
profile_source="$project_root/archiso"
profile="$project_root/build/profile"
work="$project_root/build/work"
output="$project_root/build/output"
frontend_target="$profile/airootfs/usr/share/pulsearc/frontend"
native_ui_target="$profile/airootfs/usr/share/pulsearc/native-ui"
core_target="$profile/airootfs/usr/lib/pulsearc/core/pulsearc"
config_target="$profile/airootfs/usr/share/pulsearc/config"
runtime_target="$profile/airootfs/usr/lib/pulsearc/runners"
compat_target="$profile/airootfs/usr/lib/pulsearc/compat"
runtime_cache="${PULSEARC_RUNTIME_CACHE:-$project_root/vendor/cache}"

if ! command -v mkarchiso >/dev/null 2>&1; then
    echo "mkarchiso is required. Install the Arch package: archiso" >&2
    exit 1
fi

if ! command -v fsck.erofs >/dev/null 2>&1; then
    echo "fsck.erofs is required. Install the Arch package: erofs-utils" >&2
    exit 1
fi

releng_profile=/usr/share/archiso/configs/releng
[[ -d "$releng_profile" ]] || {
    echo "The ArchISO releng profile is missing: $releng_profile" >&2
    exit 1
}

# Always build from a fresh copy of ArchISO's complete bootable profile. The
# repository contains only PulseArc's maintained overlay and policy files.
rm -rf -- "$profile"
# A failed mkarchiso run leaves a partially populated root filesystem behind.
# Reusing it can produce package ownership conflicts or a subtly stale image.
rm -rf -- "$work"
install -d "$profile"
rsync -a "$releng_profile/" "$profile/"
releng_packages=$(mktemp)
cp "$profile/packages.x86_64" "$releng_packages"
rsync -a "$profile_source/" "$profile/"
awk 'NF && $1 !~ /^#/ && !seen[$1]++ { print $1 }' \
    "$releng_packages" "$profile_source/packages.x86_64" > "$profile/packages.x86_64"
rm -f "$releng_packages"

rm -rf -- "$frontend_target" "$native_ui_target" "$core_target" "$config_target" "$runtime_target" "$compat_target"
install -d "$output" "$native_ui_target" "$core_target" "$config_target" "$runtime_target" "$compat_target"
rsync -a --delete "$project_root/native-ui/" "$native_ui_target/"
rsync -a --delete --exclude '__pycache__/' "$project_root/src/pulsearc/" "$core_target/"
rsync -a --delete "$project_root/config/" "$config_target/"

python "$project_root/scripts/fetch-runtime-bundles.py" --cache "$runtime_cache"
python "$project_root/scripts/extract-bundled-cores.py" \
    --cache "$runtime_cache" \
    --rootfs "$profile/airootfs"
python "$project_root/scripts/validate-runtime-matrix.py" \
    --rootfs "$profile/airootfs"
install_appimage() {
    local id=$1 filename=$2
    install -Dm755 "$runtime_cache/$filename" "$runtime_target/$id/$id.AppImage"
}
install_appimage duckstation DuckStation-x64.AppImage
install_appimage cemu Cemu-2.6-x86_64.AppImage
install_appimage azahar azahar.AppImage
install_appimage vita3k Vita3K-x86_64.AppImage
install_appimage xemu xemu-0.8.136-x86_64.AppImage
install_appimage rpcs3 rpcs3-v0.0.42-19729-db907a25_linux64.AppImage
install_appimage pcsx2 pcsx2-v2.6.3-linux-appimage-x64-Qt.AppImage
install -Dm755 "$runtime_cache/Heroic-2.22.1-linux-x86_64.AppImage" \
    "$profile/airootfs/usr/lib/pulsearc/apps/heroic/Heroic.AppImage"

install -d "$runtime_target/dosbox-staging"
tar -xf "$runtime_cache/dosbox-staging-linux-x86_64-v0.82.2.tar.xz" -C "$runtime_target/dosbox-staging" --strip-components=1

install -d "$runtime_target/wine-ge" "$compat_target/modern" "$compat_target/legacy-1.10.3" "$compat_target/vkd3d-proton"
tar -xf "$runtime_cache/wine-lutris-GE-Proton8-26-x86_64.tar.xz" -C "$runtime_target/wine-ge" --strip-components=1
tar -xf "$runtime_cache/dxvk-3.0.2.tar.gz" -C "$compat_target/modern" --strip-components=1
tar -xf "$runtime_cache/dxvk-1.10.3.tar.gz" -C "$compat_target/legacy-1.10.3" --strip-components=1
tar --zstd -xf "$runtime_cache/vkd3d-proton-3.0.1.tar.zst" -C "$compat_target/vkd3d-proton" --strip-components=1
if (( EUID == 0 )); then
    mkarchiso -v -r -w "$work" -o "$output" "$profile"
else
    sudo mkarchiso -v -r -w "$work" -o "$output" "$profile"
fi
