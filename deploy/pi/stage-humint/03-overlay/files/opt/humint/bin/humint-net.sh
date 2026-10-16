#!/usr/bin/env bash
# Apply a network mode with NetworkManager (the default on Raspberry Pi OS
# Bookworm). Three modes:
#
#   hotspot  — the Pi's Wi-Fi becomes an access point. NetworkManager's
#              "shared" IPv4 method runs its own DHCP/DNS, so joiners get an
#              address (10.42.0.0/24) and the Pi (10.42.0.1) is the gateway.
#   client   — the Pi joins an existing Wi-Fi and takes an address from it.
#   wired     — Ethernet only, Wi-Fi switched off. Optionally the Pi serves
#              DHCP on the wire for a switch full of laptops.
#   setup-*   — the same, but used only for the one-time online setup boot;
#              named apart so they are easy to tear down afterwards.
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
        autoconnect yes ssid "$AP_SSID" >/dev/null
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
        ipv6.method disabled >/dev/null
    nm connection up humint-ap >/dev/null
    log "hotspot up: SSID '$AP_SSID' on $WIFI_DEV (${AP_BAND:-bg})"
}

mode_client() {
    local ssid="$1" psk="$2" name="${3:-humint-client}"
    set_country
    [ -n "$ssid" ] || die "client mode needs an SSID"
    nm device wifi rescan >/dev/null 2>&1 || true
    if [ -n "$psk" ]; then
        nm device wifi connect "$ssid" password "$psk" ifname "$WIFI_DEV" name "$name" >/dev/null
    else
        nm device wifi connect "$ssid" ifname "$WIFI_DEV" name "$name" >/dev/null
    fi
    log "joined Wi-Fi '$ssid' on $WIFI_DEV"
}

mode_wired() {
    # Wi-Fi fully off — nothing radiates from the box.
    nm radio wifi off >/dev/null 2>&1 || true
    local ipv4=auto
    [ "${WIRED_DHCP_SERVER:-false}" = "true" ] && ipv4=shared
    nm connection add type ethernet ifname "$ETH_DEV" con-name humint-wired \
        autoconnect yes ipv4.method "$ipv4" ipv6.method disabled >/dev/null
    nm connection up humint-wired >/dev/null 2>&1 || true
    log "wired mode on $ETH_DEV (DHCP server: ${WIRED_DHCP_SERVER:-false})"
}

apply_deployment_mode() {
    clear_humint_profiles
    case "${NET_MODE:-hotspot}" in
        hotspot) mode_hotspot ;;
        client)  mode_client "$CLIENT_SSID" "$CLIENT_PSK" humint-client ;;
        wired)   mode_wired ;;
        *)       die "unknown NET_MODE '$NET_MODE'" ;;
    esac
}

# A temporary uplink for the one-time setup build only.
apply_setup_uplink() {
    case "${SETUP_UPLINK:-ethernet}" in
        ethernet) log "setup uplink: using Ethernet (plug in a cable)";;
        wifi)     set_country; mode_client "$SETUP_WIFI_SSID" "$SETUP_WIFI_PSK" humint-setup ;;
        none)     log "setup uplink: none";;
        *)        die "unknown SETUP_UPLINK '$SETUP_UPLINK'" ;;
    esac
}

remove_setup_uplink() { nm connection delete humint-setup >/dev/null 2>&1 || true; }

# Wait until we can actually reach the internet (for the setup build).
wait_online() {
    local tries="${1:-30}"
    for _ in $(seq 1 "$tries"); do
        if curl -fsS --max-time 4 https://github.com >/dev/null 2>&1; then return 0; fi
        sleep 2
    done
    return 1
}

case "${1:-}" in
    deploy)        load_config "$HUMINT_ENV"; apply_deployment_mode ;;
    setup-uplink)  load_config "$HUMINT_ENV"; apply_setup_uplink ;;
    remove-setup)  remove_setup_uplink ;;
    wait-online)   wait_online "${2:-30}" ;;
    *) echo "usage: humint-net.sh {deploy|setup-uplink|remove-setup|wait-online [tries]}" >&2; exit 2 ;;
esac
