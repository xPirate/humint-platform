#!/usr/bin/env bash
# Apply a network mode with NetworkManager (the default on Raspberry Pi OS
# Bookworm). Three modes:
#
#   hotspot  — the Pi's Wi-Fi becomes an access point. NetworkManager's
#              "shared" IPv4 method runs its own DHCP/DNS, so joiners get an
#              address (10.42.0.0/24) and the Pi (10.42.0.1) is the gateway.
#   client   — the Pi joins an existing Wi-Fi and takes an address from it.
#   wired    — Ethernet only, Wi-Fi switched off. Optionally the Pi serves
#              DHCP on the wire for a switch full of laptops.
#
# Nothing here needs the internet: the appliance is built complete, so even
# its first boot runs offline.
#
# All connection profiles we create are prefixed "humint-" so switching mode
# can cleanly remove the previous one without touching anything the operator
# added by hand.
set -euo pipefail
# shellcheck source=/dev/null
. /opt/humint/lib/humint-common.sh

WIFI_DEV="${WIFI_DEV:-wlan0}"
ETH_DEV="${ETH_DEV:-eth0}"

nm() { nmcli --wait 20 "$@"; }

# Remove every profile we have previously created (prefix humint-), so each
# apply starts from a known state. Hand-made profiles are left alone.
clear_humint_profiles() {
    local name
    while read -r name; do
        [ -n "$name" ] && nm connection delete "$name" >/dev/null 2>&1 || true
    done < <(nmcli -t -f NAME connection show | grep '^humint-' || true)
}

set_country() {
    [ -n "${WIFI_COUNTRY:-}" ] || { log "WIFI_COUNTRY not set; Wi-Fi will not transmit"; return; }
    raspi-config nonint do_wifi_country "$WIFI_COUNTRY" >/dev/null 2>&1 \
        || iw reg set "$WIFI_COUNTRY" >/dev/null 2>&1 || true
    rfkill unblock wifi >/dev/null 2>&1 || true
}

mode_hotspot() {
    set_country
    local hidden=no; [ "${AP_HIDDEN:-false}" = "true" ] && hidden=yes
    nm connection add type wifi ifname "$WIFI_DEV" con-name humint-ap \
        autoconnect yes ssid "$AP_SSID" >/dev/null || return 1
    # (Each step returns on failure itself: called from an `if`, set -e
    # does not stop the function.)
    nm connection modify humint-ap \
        802-11-wireless.mode ap \
        802-11-wireless.band "${AP_BAND:-bg}" \
        802-11-wireless.channel "${AP_CHANNEL:-6}" \
        802-11-wireless.hidden "$hidden" \
        wifi-sec.key-mgmt wpa-psk \
        wifi-sec.proto rsn \
        wifi-sec.pairwise ccmp \
        wifi-sec.group ccmp \
        wifi-sec.psk "$AP_PSK" \
        ipv4.method shared \
        ipv6.method disabled >/dev/null || return 1
    nm connection up humint-ap >/dev/null || return 1
    log "hotspot up: SSID '$AP_SSID' on $WIFI_DEV (${AP_BAND:-bg})"
}

mode_client() {
    local ssid="$1" psk="$2" name="${3:-humint-client}"
    set_country
    [ -n "$ssid" ] || die "client mode needs an SSID"
    nm device wifi rescan >/dev/null 2>&1 || true
    if [ -n "$psk" ]; then
        nm device wifi connect "$ssid" password "$psk" ifname "$WIFI_DEV" name "$name" >/dev/null || return 1
    else
        nm device wifi connect "$ssid" ifname "$WIFI_DEV" name "$name" >/dev/null || return 1
    fi
    log "joined Wi-Fi '$ssid' on $WIFI_DEV"
}

mode_wired() {
    # Wi-Fi fully off — nothing radiates from the box.
    nm radio wifi off >/dev/null 2>&1 || true
    local ipv4=auto
    [ "${WIRED_DHCP_SERVER:-false}" = "true" ] && ipv4=shared
    # Taking an address: from the network's DHCP, or with none there (a bare
    # switch of laptops), a self-assigned 169.254 one as well, as laptops pick.
    # ("enabled": NetworkManager before 1.52 has no "fallback".)
    local ll=()
    [ "$ipv4" = auto ] && ll=(ipv4.link-local enabled)
    nm connection add type ethernet ifname "$ETH_DEV" con-name humint-wired \
        autoconnect yes ipv4.method "$ipv4" "${ll[@]}" ipv6.method disabled >/dev/null
    nm connection up humint-wired >/dev/null 2>&1 || true
    log "wired mode on $ETH_DEV (DHCP server: ${WIRED_DHCP_SERVER:-false})"
}

# Is there a Wi-Fi device by that name? (USB adapters and some laptop
# chips appear a few seconds into boot, so wait a little for one.)
wifi_present() {
    local _
    for _ in $(seq 20); do
        nmcli -t -f DEVICE,TYPE device 2>/dev/null | grep -qx "$WIFI_DEV:wifi" && return 0
        sleep 1
    done
    return 1
}

# Can it be an access point? (Most can; some laptop chips cannot.)
wifi_can_ap() {
    [ "$(nmcli -g WIFI-PROPERTIES.AP device show "$WIFI_DEV" 2>/dev/null)" != no ]
}

# The Wi-Fi mode cannot work on this machine — no Wi-Fi (most desktops and
# mini PCs, every VM), one that cannot host a hotspot, or one that would not
# start. Rather than leave the box unreachable (or first boot failed), use
# the Ethernet port, taking an address from the network it is plugged into,
# and record that this is the mode in use so the screen says so. Choosing
# hotspot or Wi-Fi again later tries again.
fall_back_to_wired() {
    log "WARNING: $1 — using the wired network instead"
    clear_humint_profiles
    # Never a DHCP server here: nobody chose to serve addresses on whatever
    # network this is plugged into (choose wired mode for that).
    WIRED_DHCP_SERVER=false mode_wired
    set_env_value "$HUMINT_ENV" NET_MODE wired
    set_env_value "$HUMINT_ENV" WIRED_DHCP_SERVER false
    echo "$1" >/run/humint/net-fallback 2>/dev/null || true
}

apply_deployment_mode() {
    clear_humint_profiles
    rm -f /run/humint/net-fallback 2>/dev/null || true
    case "${NET_MODE:-hotspot}" in
        hotspot)
            if ! wifi_present; then fall_back_to_wired "no Wi-Fi on this machine for the hotspot"
            elif ! wifi_can_ap; then fall_back_to_wired "this machine's Wi-Fi cannot host a hotspot"
            elif ! mode_hotspot; then fall_back_to_wired "the hotspot would not start"
            fi ;;
        client)
            if ! wifi_present; then fall_back_to_wired "no Wi-Fi on this machine to join $CLIENT_SSID with"
            elif ! mode_client "$CLIENT_SSID" "$CLIENT_PSK" humint-client; then
                fall_back_to_wired "could not join Wi-Fi '$CLIENT_SSID'"
            fi ;;
        wired)   mode_wired ;;
        *)       die "unknown NET_MODE '$NET_MODE'" ;;
    esac
}

case "${1:-}" in
    deploy)        load_config "$HUMINT_ENV"; apply_deployment_mode ;;
    *) echo "usage: humint-net.sh deploy" >&2; exit 2 ;;
esac
