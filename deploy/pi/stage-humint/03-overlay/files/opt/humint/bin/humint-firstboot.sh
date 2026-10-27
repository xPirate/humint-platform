#!/usr/bin/env bash
# One-time setup, run on the FIRST boot only — at base, before the device goes
# into the field. Everything the console needs is already in the image, so
# this needs no internet. It:
#
#   1. reads humint-appliance.conf from the boot partition and saves it;
#   2. sets the hostname and time zone;
#   3. asks the operator to SET the unlock PIN, then creates the encrypted
#      case store and formats it;
#   4. creates the PostgreSQL cluster INSIDE that store, the console's
#      database and account, and loads the schema;
#   5. writes the console's settings (also inside the store) and starts it;
#   6. switches the network to the deployment mode the team will use.
#
# After this, the config file is renamed to *.done (so the Wi-Fi passphrase
# is not left on a readable partition) and this service never runs again.
# Every later boot just asks for the PIN (humint-unlock) and starts up.
set -euo pipefail
# shellcheck source=/dev/null
. /opt/humint/lib/humint-common.sh
# shellcheck source=/dev/null
. /opt/humint/lib/humint-store.sh

mkdir -p "$HUMINT_STATE"
cd /
exec 2>>"$HUMINT_STATE/firstboot.log" || true


banner() { oled "HUMINT setup" "$1" "${2:-}"; log "$1 ${2:-}"; printf '%s %s\n' "$1" "${2:-}" >/dev/tty1; }

ask_new_pin() {
    # Ask for a new unlock PIN, confirmed, and echo it on stdout. On the
    # touch panel when one is fitted (it asks twice and checks they match);
    # otherwise — or if the panel stops — on the physical keyboard (this
    # service owns tty1), with the OLED saying what to do.
    local a b
    if wait_for_panel && a="$(panel_ask_pin new)"; then
        printf '%s' "$a"; return 0
    fi
    while :; do
        oled "HUMINT setup" "Set unlock PIN" "type on keyboard"
        printf '\n\nHUMINT field server — set the unlock PIN.\n' >/dev/tty1
        printf 'You will type this at every boot to open the case file.\n' >/dev/tty1
        printf 'New PIN: ' >/dev/tty1
        IFS= read -rs a </dev/tty1; printf '\n' >/dev/tty1
        printf 'Confirm: ' >/dev/tty1
        IFS= read -rs b </dev/tty1; printf '\n' >/dev/tty1
        if [ "${#a}" -lt "$PIN_MIN_LENGTH" ]; then
            printf 'Use at least %d characters — try again.\n' "$PIN_MIN_LENGTH" >/dev/tty1
            oled "Set unlock PIN" "too short" "try again"; continue
        fi
        if [ "$a" != "$b" ]; then
            printf 'Did not match — try again.\n' >/dev/tty1
            oled "Set unlock PIN" "did not match" "try again"; continue
        fi
        printf '%s' "$a"; return 0
    done
}

create_store() {
    # The space is set aside before the PIN is asked for, so power lost while
    # the machine waits at "set a PIN" leaves a file that was never
    # encrypted — no PIN opens it. Without a LUKS header it is only that
    # leftover: discard it and set up afresh, rather than asking for a PIN
    # nobody ever chose.
    if [ -f "$HUMINT_IMG" ] && [ ! -e "/dev/mapper/$HUMINT_MAP" ] && ! cryptsetup isLuks "$HUMINT_IMG" 2>/dev/null; then
        log "found an unfinished store from an interrupted first boot (never encrypted); starting it again"
        rm -f "$HUMINT_IMG"
    fi
    if [ -f "$HUMINT_IMG" ]; then
        # A previous attempt got this far and then failed. The store exists;
        # it must be opened with the PIN set then.
        log "store already exists; opening it"
        if [ ! -e "/dev/mapper/$HUMINT_MAP" ]; then
            local pin
            if ! { wait_for_panel && pin="$(panel_ask_pin existing)"; }; then
                oled "HUMINT setup" "Enter unlock PIN" "(set earlier)"
                printf '\nThe case store was already created. Enter its PIN: ' >/dev/tty1
                IFS= read -rs pin </dev/tty1; printf '\n' >/dev/tty1
            fi
            printf '%s' "$pin" | cryptsetup open --key-file=- "$HUMINT_IMG" "$HUMINT_MAP" \
                || die "wrong PIN for the existing store (delete $HUMINT_IMG to start over)"
            unset pin
        fi
        mount_store
        return 0
    fi

    if [ "${DATA_SIZE:-}" = auto ]; then
        # Most of the free space, leaving room for updates and logs.
        local free_mb
        free_mb="$(df -Pm "$(dirname "$HUMINT_IMG")" | awk 'NR==2 {print $4}')"
        DATA_SIZE="$(( free_mb * 7 / 10 ))M"
        [ "${DATA_SIZE%M}" -ge 4096 ] || DATA_SIZE=4096M
    fi
    banner "Making store" "$DATA_SIZE"
    mkdir -p "$(dirname "$HUMINT_IMG")"
    # Real (not sparse) allocation: a half-written encrypted volume that ran
    # out of card space mid-deployment is the worst time to find out.
    fallocate -l "$DATA_SIZE" "$HUMINT_IMG" || die "could not allocate $DATA_SIZE for the store"
    chmod 600 "$HUMINT_IMG"

    local pin; pin="$(ask_new_pin)"
    banner "Encrypting store" "please wait"
    printf '%s' "$pin" | format_store
    unset pin
}

main() {
    [ -f "$HUMINT_FIRSTBOOT_DONE" ] && { log "first boot already done"; exit 0; }
    banner "Reading config" ""
    # The config file is optional: without one, every setting takes its
    # default, and what nobody wrote down is filled in below.
    load_config "$HUMINT_CONF"
    resolve_open_settings
    if [ "$NET_MODE" = "hotspot" ] && [ -z "$WIFI_COUNTRY" ]; then
        oled "HUMINT setup" "Set WIFI_COUNTRY" "see README"
        die "no Wi-Fi country: set WIFI_COUNTRY (or TIMEZONE) in $HUMINT_CONF on the card"
    fi
    if [ -f "$HUMINT_CONF" ]; then
        cp "$HUMINT_CONF" "$HUMINT_ENV"
    elif [ -f "$HUMINT_BOOT/humint-appliance.conf.example" ]; then
        log "no $HUMINT_CONF — using the defaults"
        cp "$HUMINT_BOOT/humint-appliance.conf.example" "$HUMINT_ENV"
    else
        : >"$HUMINT_ENV"
    fi
    chmod 600 "$HUMINT_ENV"
    # What was decided here is recorded, so later boots read the same values.
    set_env_value "$HUMINT_ENV" TIMEZONE "$TIMEZONE"
    set_env_value "$HUMINT_ENV" WIFI_COUNTRY "$WIFI_COUNTRY"
    set_env_value "$HUMINT_ENV" AP_PSK "$AP_PSK"
    chmod 600 "$HUMINT_ENV"

    banner "Identity" "$HOSTNAME"
    # Set it directly as well: hostnamectl can fail this early in boot
    # (hostnamed not reachable yet), which left the old name live while
    # /etc/hosts below already named the new one.
    printf '%s\n' "$HOSTNAME" >/etc/hostname
    hostname "$HOSTNAME" || true
    hostnamectl set-hostname "$HOSTNAME" 2>/dev/null || true
    if grep -q '^127.0.1.1' /etc/hosts; then
        sed -i "s/^127.0.1.1.*/127.0.1.1\t$HOSTNAME/" /etc/hosts
    else
        printf '127.0.1.1\t%s\n' "$HOSTNAME" >>/etc/hosts
    fi
    # Announce the new name as <name>.local.
    systemctl try-restart avahi-daemon.service 2>/dev/null || true
    timedatectl set-timezone "$TIMEZONE" 2>/dev/null || true

    create_store
    make_store_dirs
    create_database

    banner "Starting console" ""
    start_console || die "console did not start"

    banner "Deploy network" "$NET_MODE"
    /opt/humint/bin/humint-net.sh deploy || die "could not apply $NET_MODE"
    # No usable Wi-Fi: it fell back to the wired network (humint-net.sh).
    [ -s /run/humint/net-fallback ] && NET_MODE=wired

    # This box's own login, replacing the one every copy of the image shares.
    local login_pw=""
    install_ssh_key "${SSH_AUTHORIZED_KEY:-}"
    if [ "${LOGIN_PASSWORD:-random}" = random ]; then
        banner "Login password" "new for this box"
        login_pw="$(new_login_password)" || login_pw=""
    fi

    touch "$HUMINT_FIRSTBOOT_DONE"
    # Rename the original so the passphrases are not left on the readable
    # boot partition. (The working copy lives in $HUMINT_ENV, root-only.)
    mv "$HUMINT_CONF" "${HUMINT_CONF}.done" 2>/dev/null || true
    sleep 3   # let the hotspot come up before reading the address
    if [ "$TLS" = on ]; then
        # The address may have changed with the network; cover it now.
        /opt/humint/bin/humint-tls.sh ensure --restart || true
    fi
    local url; url="$(console_url)"
    banner "Ready" "$url"
    printf '\nOpen %s (or %s) and create the admin account.\n' \
        "$url" "$(console_url "${HOSTNAME}.local")" >/dev/tty1
    if [ "$TLS" = on ]; then
        printf 'First, on each phone and laptop: open http://%s.local/trust and install the certificate.\n' \
            "$HOSTNAME" >/dev/tty1
        printf 'Its fingerprint: %s\n' "$(/opt/humint/bin/humint-tls.sh fingerprint)" >/dev/tty1
    fi
    # A generated hotspot password goes on the same "write these down" screen.
    if [ "$AP_PSK_GENERATED" = 1 ] && [ "$NET_MODE" = hotspot ]; then
        install -d -m 755 "$HUMINT_RUN"
        ( umask 077; python3 - "$LOGIN_SECRET_FILE" "$AP_SSID" "$AP_PSK" <<'PY'
import json, os, sys, time
path, ssid, psk = sys.argv[1:4]
try:
    d = json.load(open(path))
except (OSError, ValueError):
    d = {"time": int(time.time())}
d.update({"ap_ssid": ssid, "ap_psk": psk})
json.dump(d, open(path, "w"))
PY
        )
        printf '\nThe field Wi-Fi is "%s", password: %s\n' "$AP_SSID" "$AP_PSK" >/dev/tty1
    fi
    if [ -n "$login_pw" ]; then
        printf '\nThis box'"'"'s login (SSH and keyboard) is now: %s / %s\n' "$(login_user)" "$login_pw" >/dev/tty1
        printf 'Write it down. It is shown once; Menu -> New login on the panel, or humint-ctl login-password, replaces it.\n' >/dev/tty1
        oled "Login: $(login_user)" "${login_pw:0:9}" "${login_pw:10}"
    fi
    log "first boot complete — console at $url"
}

main "$@"
