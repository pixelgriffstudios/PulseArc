#!/usr/bin/env bash
if [[ "$(tty 2>/dev/null || true)" == /dev/tty1 ]]; then
    exec /usr/local/sbin/pulsearc-recover
fi

