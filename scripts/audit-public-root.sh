#!/usr/bin/env bash
set -euo pipefail

root=${1:?usage: audit-public-root.sh ROOT}
[[ -e "$root/etc/pulsearc/installed" ]]

fail() { printf 'PUBLIC BUILD AUDIT FAILED: %s\n' "$*" >&2; exit 1; }

mapfile -t games < <(find "$root/var/lib/pulsearc/library/games" -mindepth 3 -maxdepth 3 -type f -name pulsearc.toml -printf '%h\n' | sort -u)
[[ ${#games[@]} -eq 1 ]] || fail "expected exactly one bundled game; found ${#games[@]}"
[[ ${games[0]} == */windows/hell-on-rails ]] || fail "unexpected bundled game: ${games[0]}"
[[ -e "${games[0]}/content/hell-on-rails.exe" ]] || fail "Hell on Rails executable is missing"

[[ ! -s "$root/etc/machine-id" ]] || fail "machine-id was not reset"
compgen -G "$root/etc/ssh/ssh_host_*" >/dev/null && fail "SSH host keys are present"
find "$root/etc/NetworkManager/system-connections" -mindepth 1 -type f -print -quit 2>/dev/null | \
    grep -q . && fail "saved network credentials are present"
find "$root/home/gamer" -mindepth 1 -maxdepth 1 ! -name .bash_profile ! -name .xinitrc -print -quit | \
    grep -q . && fail "development user home was not factory-cleaned"
find "$root/var/lib/pulsearc" -type f \( \
    -iname 'sources.json' -o -iname '*bios*' -o -iname 'keys.txt' -o \
    -iname '*.bin' -o -iname '*.rom' -o -iname '*.pup' -o -iname '*.key' \
    \) -print -quit | grep -q . && fail "private source, BIOS, firmware, or key material is present"

grep -RIlE --exclude='*.AppImage' --exclude='*.so*' \
    '(cf\.layerseven|username=.{6,}.*password=|xtream[^a-z].*password)' \
    "$root/etc/pulsearc" "$root/usr/share/pulsearc" "$root/var/lib/pulsearc" 2>/dev/null | \
    grep -q . && fail "private IPTV credentials or endpoints were detected"

printf 'PULSEARC_PUBLIC_ROOT_AUDIT_OK\n'
