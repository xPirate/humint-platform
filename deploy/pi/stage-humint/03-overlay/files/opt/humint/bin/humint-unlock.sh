#!/usr/bin/env bash
# Unlock the encrypted case store at boot. Runs on every boot AFTER the store
# exists (first boot creates it). It owns tty1, so the operator types the PIN
# on the attached keyboard; the OLED tells them when, because a headless box
# in a bag has no monitor to prompt from.
#
# On success it mounts the store, starts Docker (whose data-root lives inside
# it) and leaves the compose + status services to bring the console up. On
# too many wrong PINs it stops, so the console never comes up on a box whose
# case file could not be opened.
set -euo pipefail
# shellcheck source=/dev/null
. /opt/humint/lib/humint-common.sh

TRIES="${HUMINT_UNLOCK_TRIES:-5}"

already_open() { [ -e "/dev/mapper/$HUMINT_MAP" ]; }

mount_store() {
    mkdir -p "$HUMINT_DATA"
    mountpoint -q "$HUMINT_DATA" || mount "/dev/mapper/$HUMINT_MAP" "$HUMINT_DATA"
    mkdir -p "$HUMINT_DATA/docker"
    touch "$HUMINT_READY"
}

start_docker() {
    systemctl unmask docker >/dev/null 2>&1 || true
    systemctl start docker
    for _ in $(seq 1 30); do docker info >/dev/null 2>&1 && break; sleep 1; done
}

main() {
    load_config "$HUMINT_ENV"

    if [ ! -f "$HUMINT_IMG" ]; then
        log "no store yet — first boot will create it"; exit 0
    fi
    if already_open; then
        log "store already open"; mount_store; start_docker; exit 0
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
            start_docker
            oled "HUMINT field" "Unlocked" "starting console"
            log "store unlocked and mounted"
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
