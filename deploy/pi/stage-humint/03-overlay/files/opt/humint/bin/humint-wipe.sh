#!/usr/bin/env bash
# Destroy the field server's case file — on purpose, or under duress.
#
#   humint-wipe.sh reset [--no-reboot]
#       Erase the case file for good and put the box back to first-time
#       setup: it restarts and asks for a new PIN, with the same network
#       settings. (Panel: Menu → Wipe case file. humint-ctl wipe.)
#
#   humint-wipe.sh duress          (the PIN on stdin; called by try_unlock)
#       Somebody is being made to open the box. Erase the case file, build a
#       new EMPTY one under the PIN they typed, and start the console on it —
#       so the box "opens" as if nothing were wrong. Nothing is shown or
#       logged on screen.
#
# How the erasing works: the store is LUKS-encrypted, and its key exists only
# inside the LUKS header, wrapped by the PIN. luksErase destroys every key
# slot, and the header area is then overwritten with random data. From that
# moment the store's contents are noise to everyone, PIN or no PIN; nothing
# needs to overwrite the gigabytes of data itself, which is what makes this
# take seconds rather than an hour.
#
# What it does NOT reach: copies made outside the store — `humint-ctl backup`
# to a USB stick, field packages already exported, the devices that read it.
set -euo pipefail
# (HUMINT_LIB only so the tests can load these from the repository.)
# shellcheck source=/dev/null
. "${HUMINT_LIB:-/opt/humint/lib}/humint-common.sh"
# shellcheck source=/dev/null
. "${HUMINT_LIB:-/opt/humint/lib}/humint-store.sh"

# Bytes at the start of the store holding the LUKS2 header and key slots
# (16 MiB by default); overwritten after luksErase for good measure.
HEADER_BYTES_MB=32
PG_CONF_DIR="/etc/postgresql/$PG_VERSION/$PG_CLUSTER"

destroy_store() {
    # Stop everything holding files in the store; if something will not let
    # go, take it down rather than leave the store open.
    systemctl stop humint.target humint-api.service humint-worker.service "$PG_UNIT" 2>/dev/null || true
    rm -f "$HUMINT_READY"
    if mountpoint -q "$HUMINT_DATA"; then
        umount "$HUMINT_DATA" 2>/dev/null || { fuser -km "$HUMINT_DATA" 2>/dev/null || true; umount -l "$HUMINT_DATA"; }
    fi
    cryptsetup close "$HUMINT_MAP" 2>/dev/null || true
    if [ -f "$HUMINT_IMG" ]; then
        cryptsetup luksErase --batch-mode "$HUMINT_IMG" 2>/dev/null || true
        dd if=/dev/urandom of="$HUMINT_IMG" bs=1M count="$HEADER_BYTES_MB" conv=notrunc,fsync status=none
    fi
    # The cluster's registration (config only — its data lived in the store),
    # and the old CA's public half: both describe the case file just destroyed.
    rm -rf "$PG_CONF_DIR"
    rm -f "$HUMINT_STATE/ca.crt" "$HUMINT_STATE/ca.fingerprint" "$HUMINT_STATE/ca.fingerprint.sha1"
    echo 0 >"$UNLOCK_TRIES_FILE" 2>/dev/null || true
    sync
}

cmd_reset() {
    load_config "$HUMINT_ENV"
    log "wiping the case file and returning to first-time setup"
    oled "HUMINT field" "Wiping" ""
    destroy_store
    rm -f "$HUMINT_IMG"
    # First boot runs again, from the settings this box already has.
    if [ -f "$HUMINT_ENV" ]; then
        install -m 600 "$HUMINT_ENV" "$HUMINT_CONF"
    fi
    rm -f "$HUMINT_FIRSTBOOT_DONE"
    /usr/bin/python3 "$HUMINT_HOME/bin/humint-duress.py" clear || true
    log "case file destroyed"
    if [ "${1:-}" != "--no-reboot" ]; then
        oled "HUMINT field" "Wiped" "restarting"
        systemctl reboot
    fi
}

cmd_duress() {
    local pin
    IFS= read -r pin || true
    [ -n "$pin" ] || exit 2
    load_config "$HUMINT_ENV"
    destroy_store
    # A new, empty case file under the PIN that was typed, built the way a
    # new box's is. The duress PIN is spent: the PIN that opens the box now
    # is that one, and there is nothing left to protect with a second.
    printf '%s\n' "$pin" | format_store
    unset pin
    make_store_dirs
    create_database
    /usr/bin/python3 "$HUMINT_HOME/bin/humint-duress.py" clear || true
    start_console
}

main() {
    case "${1:-}" in
        reset)  shift; cmd_reset "$@" ;;
        duress) cmd_duress ;;
        *) echo "usage: humint-wipe.sh reset [--no-reboot] | duress" >&2; exit 2 ;;
    esac
}

# Sourced by the tests to call the pieces; run as a command otherwise.
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    main "$@"
fi
