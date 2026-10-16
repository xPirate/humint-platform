# Shared helpers for the HUMINT field-server scripts. Sourced, not run.
# shellcheck shell=bash
# Variables here are used by the scripts that source this file.
# shellcheck disable=SC2034

# Where things live on the device.
HUMINT_HOME=/opt/humint                  # appliance scripts + the Python venv
HUMINT_SRC=/opt/humint-platform          # the console's code, baked into the image
HUMINT_BOOT=/boot/firmware               # the readable FAT partition (Bookworm path)
HUMINT_CONF="$HUMINT_BOOT/humint-appliance.conf"
HUMINT_STATE=/var/lib/humint             # our own state, on the (unencrypted) root
HUMINT_ENV="$HUMINT_STATE/env"           # the appliance config, after first boot parses it

# The encrypted case store.
HUMINT_IMG=/srv/humint.img               # the LUKS container file
HUMINT_MAP=humint                        # /dev/mapper/humint when open
HUMINT_DATA=/srv/humint-data             # where it mounts
HUMINT_READY=/run/humint-data.ready      # marker: the store is open and mounted
HUMINT_FIRSTBOOT_DONE="$HUMINT_STATE/firstboot.done"

# Inside the store: the database cluster and the console's settings (which
# hold the database password, so they are encrypted at rest too).
PG_VERSION=16
PG_CLUSTER=main
PG_UNIT="postgresql@${PG_VERSION}-${PG_CLUSTER}.service"
PG_DATA="$HUMINT_DATA/postgresql"
APP_ENV="$HUMINT_DATA/humint.env"
APP_USER=humintd

# The OLED helper. Each call draws a frame and returns; it never holds the
# display, so the unlock script and the status loop can take turns.
OLED_SHOW="$HUMINT_HOME/venv/bin/python3 $HUMINT_HOME/bin/oled_show.py"

log()  { printf '%s humint: %s\n' "$(date '+%H:%M:%S')" "$*" >&2; }
die()  { log "ERROR: $*"; exit 1; }

# Draw up to a few short lines on the OLED. Silently does nothing when no
# screen is attached or the display libraries are missing — the scripts must
# work on a bare Pi with no HAT.
oled() {
    $OLED_SHOW "$@" 2>/dev/null || true
}

# Read the appliance config into the environment, with defaults for anything
# the operator left out. Used by first boot (from the boot partition) and by
# every later boot (from the copy first boot saved).
load_config() {
    # Defaults first, so a short config file still yields a complete set.
    HOSTNAME=humint
    INSTANCE_NAME="HUMINT Field Server"
    TIMEZONE=UTC
    WIFI_COUNTRY=""
    NET_MODE=hotspot
    AP_SSID=humint-field ; AP_PSK=changeme-now ; AP_BAND="bg" ; AP_CHANNEL=6 ; AP_HIDDEN=false
    CLIENT_SSID="" ; CLIENT_PSK=""
    WIRED_DHCP_SERVER=true
    DATA_SIZE=16G
    API_PORT=80
    OLED=auto ; STATUS_ROTATE_SECONDS=6

    local f="$1"
    if [ -r "$f" ]; then
        set -a
        # shellcheck disable=SC1090
        . "$f"
        set +a
    fi
}

# Is the encrypted store open and mounted?
data_ready() { [ -f "$HUMINT_READY" ] && mountpoint -q "$HUMINT_DATA"; }

# Mount the (already opened) store and mark it ready.
mount_store() {
    mkdir -p "$HUMINT_DATA"
    mountpoint -q "$HUMINT_DATA" || mount "/dev/mapper/$HUMINT_MAP" "$HUMINT_DATA"
    touch "$HUMINT_READY"
}

# Bring the console up: database, then API and worker (ordering is in the
# units). Only ever called with the store open.
start_console() {
    data_ready || die "case store is not open"
    systemctl start humint.target
}

# Stop everything that holds files in the store, then unmount and close it.
lock_store() {
    systemctl stop humint.target humint-api.service humint-worker.service "$PG_UNIT" 2>/dev/null || true
    rm -f "$HUMINT_READY"
    sync
    if mountpoint -q "$HUMINT_DATA"; then
        umount "$HUMINT_DATA" || die "store still in use — cannot unmount (see: fuser -vm $HUMINT_DATA)"
    fi
    cryptsetup close "$HUMINT_MAP" 2>/dev/null || true
}
