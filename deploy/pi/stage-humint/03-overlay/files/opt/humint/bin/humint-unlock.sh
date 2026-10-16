#!/usr/bin/env bash
# Unlock the encrypted case store at boot. Runs on every boot AFTER the store
# exists (first boot creates it and starts up by itself).
#
# Where the PIN comes from depends on the screen:
#   touch panel   the panel shows a PIN pad (and takes an attached keyboard);
#                 this script waits for it, and falls back to the keyboard
#                 prompt below if the panel stops
#   OLED / none   this script owns tty1 and reads the PIN from the keyboard;
#                 the OLED says when to type
# Either way the same try_unlock does the work and keeps one count of wrong
# PINs. Too many, and the console stays down until a reboot.
set -euo pipefail
# shellcheck source=/dev/null
. /opt/humint/lib/humint-common.sh

panel_running() { systemctl -q is-active humint-panel.service 2>/dev/null; }

keyboard_prompt() {
    local pin rc
    while :; do
        if unlock_locked_out; then
            oled "HUMINT field" "LOCKED" "too many tries"
            die "too many wrong PINs; not starting the console"
        fi
        oled "HUMINT field" "Enter unlock PIN" "keyboard + Enter"
        printf '\n\nHUMINT field server — enter the unlock PIN (%d tries left): ' \
            "$((UNLOCK_MAX_TRIES - $(unlock_tries)))" >/dev/tty1
        IFS= read -rs pin </dev/tty1; printf '\n' >/dev/tty1
        [ -n "$pin" ] || continue
        oled "HUMINT field" "Unlocking..." ""
        rc=0; printf '%s\n' "$pin" | try_unlock || rc=$?
        unset pin
        case "$rc" in
            0|5) oled "HUMINT field" "Unlocked" "console starting"
                 log "store unlocked; console started"; return 0 ;;
            1)   printf 'Wrong PIN.\n' >/dev/tty1; oled "HUMINT field" "Wrong PIN" "try again"; sleep 1 ;;
            3)   continue ;;
            *)   die "unlock failed ($rc)" ;;
        esac
    done
}

main() {
    load_config "$HUMINT_ENV"
    if [ ! -f "$HUMINT_IMG" ]; then
        log "no store yet — first boot will create it"; exit 0
    fi
    if [ -e "/dev/mapper/$HUMINT_MAP" ]; then
        log "store already open"; mount_store; start_console; exit 0
    fi

    # Give the panel a moment to come up and claim the PIN entry.
    for _ in $(seq 1 15); do panel_running && break; sleep 1; done
    if panel_running; then
        stty -echo </dev/tty1 2>/dev/null || true     # nothing typed here is shown
        printf '\n\nHUMINT field server — unlock on the touch screen (or its keyboard).\n' >/dev/tty1
        while ! data_ready; do
            if unlock_locked_out; then
                oled "HUMINT field" "LOCKED" "too many tries"
                die "too many wrong PINs; not starting the console"
            fi
            if ! panel_running; then
                log "touch panel stopped; asking on the keyboard instead"
                stty echo </dev/tty1 2>/dev/null || true
                keyboard_prompt
                exit 0
            fi
            sleep 1
        done
        log "unlocked from the touch panel"
        exit 0
    fi
    keyboard_prompt
}

main "$@"
