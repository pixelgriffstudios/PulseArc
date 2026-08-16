current_tty="$(tty 2>/dev/null || true)"
# XDG_VTNR is not consistently exported by every agetty/PAM combination.
# The physical tty check keeps the appliance session reliable without
# accidentally starting the frontend in SSH or on maintenance consoles.
if [[ -z "${DISPLAY:-}" && ( "${XDG_VTNR:-0}" == 1 || "$current_tty" == /dev/tty1 ) ]]; then
    if [[ ! -e /etc/pulsearc/installed ]]; then
        exec sudo /usr/local/sbin/pulsearc-install
    fi
    exec startx -- -keeptty
fi
