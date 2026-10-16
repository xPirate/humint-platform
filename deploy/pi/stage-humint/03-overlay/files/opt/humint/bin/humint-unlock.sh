#!/usr/bin/env bash
# Unlock the encrypted case store at boot. Runs on every boot AFTER the store
# exists (first boot creates it and starts up by itself). It owns tty1, so the
# operator types the PIN on the attached keyboard; the OLED tells them when,
# because a headless box in a bag has no monitor to prompt from.
#
# On success it mounts the store and starts humint.target — PostgreSQL (whose
# data lives inside the store), then the API and worker. On too many wrong
# PINs it stops, so the console never comes up on a box whose case file could
# not be opened.
set -euo pipefail
# shellcheck source=/dev/null
. /opt/humint/lib/humint-common.sh

TRIES="${HUMINT_UNLOCK_TRIES:-5}"

already_open() { [ -e "/dev/mapper/$HUMINT_MAP" ]; }

main() {
    load_config "$HUMINT_ENV"

    if [ ! -f "$HUMINT_IMG" ]; then
        log "no store yet — first boot will create it"; exit 0
    fi
    if already_open; then
        log "store already open"; mount_store; start_console; exit 0
    fi

    local n=0 pin
    while [ "$n" -lt "$TRIES" ]; do
        n=$((n + 1))
        oled "HUMINT field" "Enter unlock PIN" "keyboard + Enter"
        printf '\n\nHUMINT field server — enter the unlock PIN (try %d/%d): ' "$n" "$TRIES" >/dev/tty1
        IFS= read -rs pin </dev/tty1; printf '\n' >/dev/tty1
        if [ -z "$pin" ]; then continue; fi
        oled "HUMINT field" "Unlocking..." ""
        if printf '%s' "$pin" | cryptsetup open --key-file=- "$HUMINT_IMG" "$HUMINT_MAP" 2>/dev/null; then
            unset pin
            mount_store
            oled "HUMINT field" "Unlocked" "starting console"
            start_console
            log "store unlocked; console started"
            exit 0
        fi
        unset pin
        printf 'Wrong PIN.\n' >/dev/tty1
        oled "HUMINT field" "Wrong PIN" "try again"
        sleep 1
    done

    oled "HUMINT field" "LOCKED" "too many tries"
    die "too many wrong PINs; not starting the console"
}

main "$@"
