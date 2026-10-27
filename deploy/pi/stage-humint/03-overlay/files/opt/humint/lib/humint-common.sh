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
HUMINT_DURESS_FILE="$HUMINT_STATE/duress"   # hash of the duress PIN, if one is set

# Inside the store: the database cluster and the console's settings (which
# hold the database password, so they are encrypted at rest too).
PG_VERSION=16
PG_CLUSTER=main
PG_UNIT="postgresql@${PG_VERSION}-${PG_CLUSTER}.service"
PG_DATA="$HUMINT_DATA/postgresql"
APP_ENV="$HUMINT_DATA/humint.env"
APP_USER=humintd

# Asking the touch panel for a PIN (first boot). The script writes what it
# wants into PIN_SETUP_REQ ("new": set and confirm one; "existing": the one
# set on an earlier, interrupted first boot) and reads the answer from a FIFO
# only root can open. Nothing is ever written to disk.
HUMINT_RUN=/run/humint
PIN_SETUP_REQ="$HUMINT_RUN/pin-setup"
PIN_SETUP_FIFO="$HUMINT_RUN/pin-setup.fifo"
PIN_MIN_LENGTH=4

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
    # Empty = decided at first boot: the image's own time zone, the country
    # that time zone is in, and a generated hotspot password (see
    # resolve_open_settings). The config file is optional.
    TIMEZONE=""
    WIFI_COUNTRY=""
    NET_MODE=hotspot
    AP_SSID=humint-field ; AP_PSK="" ; AP_BAND="bg" ; AP_CHANNEL=6 ; AP_HIDDEN=false
    CLIENT_SSID="" ; CLIENT_PSK=""
    WIRED_DHCP_SERVER=true
    DATA_SIZE=16G
    API_PORT=80
    TLS=on
    SCREEN=auto ; OLED=auto ; STATUS_ROTATE_SECONDS=6 ; SCREEN_SLEEP_MINUTES=5
    BATTERY=auto ; BATTERY_SHUTDOWN_PERCENT=8 ; BATTERY_CELLS=2
    LOGIN_PASSWORD=random ; SSH_AUTHORIZED_KEY=""

    local f="$1"
    if [ -r "$f" ]; then
        set -a
        # shellcheck disable=SC1090
        . "$f"
        set +a
    fi
}

# The address to hand the team: https://<ip> with TLS on, else http://<ip>[:port].
console_url() {
    local ip="${1:-}"
    # The network's own address; a self-assigned 169.254 one only if alone.
    [ -n "$ip" ] || ip="$(hostname -I 2>/dev/null | awk '{for (i = 1; i <= NF; i++) if ($i !~ /^169\.254\./) {print $i; exit}; print $1}')"
    if [ "${TLS:-on}" = "on" ]; then
        echo "https://${ip}"
    else
        local port=""; [ "${API_PORT:-80}" != "80" ] && port=":${API_PORT}"
        echo "http://${ip}${port}"
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

# One wrong-PIN count for every way a PIN can be entered (keyboard, touch
# screen), so having two inputs never means twice the guesses. Kept in /run:
# a reboot starts the count again, as it always has.
UNLOCK_TRIES_FILE=/run/humint/unlock-tries
UNLOCK_MAX_TRIES="${HUMINT_UNLOCK_TRIES:-5}"

unlock_tries() { cat "$UNLOCK_TRIES_FILE" 2>/dev/null || echo 0; }
unlock_locked_out() { [ "$(unlock_tries)" -ge "$UNLOCK_MAX_TRIES" ]; }

# try_unlock: PIN on stdin. 0 opened and console starting, 1 wrong PIN,
# 3 locked out (too many tries), 4 no store yet, 5 already open.
try_unlock() {
    mkdir -p /run/humint
    exec 9>/run/humint/unlock.lock
    flock 9
    [ -f "$HUMINT_IMG" ] || return 4
    if [ -e "/dev/mapper/$HUMINT_MAP" ]; then return 5; fi
    unlock_locked_out && return 3
    local pin
    IFS= read -r pin || true
    [ -n "$pin" ] || return 1
    # The duress PIN (humint-ctl duress set): erase the case file and open an
    # empty one instead, as if this were the right PIN. Checked first, and
    # the same way whatever is typed, so it takes no noticeably longer.
    if [ -f "$HUMINT_DURESS_FILE" ] &&
       printf '%s\n' "$pin" | /usr/bin/python3 "$HUMINT_HOME/bin/humint-duress.py" check; then
        printf '%s\n' "$pin" | "$HUMINT_HOME/bin/humint-wipe.sh" duress >/dev/null 2>&1 || true
        unset pin
        echo 0 >"$UNLOCK_TRIES_FILE"
        return 0
    fi
    if printf '%s' "$pin" | cryptsetup open --key-file=- "$HUMINT_IMG" "$HUMINT_MAP" 2>/dev/null; then
        unset pin
        echo 0 >"$UNLOCK_TRIES_FILE"
        mount_store
        start_console
        return 0
    fi
    unset pin
    echo $(( $(unlock_tries) + 1 )) >"$UNLOCK_TRIES_FILE"
    unlock_locked_out && return 3
    return 1
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

# ---- the touch panel -------------------------------------------------------

# The touch panel (Pi) or the native app's helper (x86, humint-boxd) — either
# takes the PIN on screen.
panel_running() {
    systemctl -q is-active humint-panel.service 2>/dev/null ||
        systemctl -q is-active humint-boxd.service 2>/dev/null
}

# humint-display found a screen the panel will drive, or this machine has
# the native app.
panel_expected() {
    grep -q '"panel": {' "$HUMINT_RUN/display.json" 2>/dev/null ||
        systemctl -q is-enabled humint-boxd.service 2>/dev/null
}

# Wait (briefly) for the panel to come up when one is fitted.
wait_for_panel() {
    local i
    for i in $(seq 1 "${1:-15}"); do
        panel_running && return 0
        panel_expected || return 1
        sleep 1
    done
    panel_running
}

# panel_ask_pin new|existing — the panel asks on screen; prints the PIN on
# stdout. Returns 1 (having printed nothing) if there is no panel or it stops
# while waiting, so the caller can fall back to the keyboard.
panel_ask_pin() {
    local stage="$1" pin=""
    panel_running || return 1
    install -d -m 755 "$HUMINT_RUN"
    rm -f "$PIN_SETUP_FIFO"
    mkfifo -m 600 "$PIN_SETUP_FIFO"
    # Held open read-write, so the panel's open never blocks and a read
    # never sees end-of-file between its attempts.
    exec 3<>"$PIN_SETUP_FIFO"
    printf '%s\n' "$stage" >"$PIN_SETUP_REQ"
    chmod 644 "$PIN_SETUP_REQ"
    while :; do
        if IFS= read -r -t 3 pin <&3; then
            break
        fi
        if ! panel_running; then
            exec 3<&-
            rm -f "$PIN_SETUP_REQ" "$PIN_SETUP_FIFO"
            return 1
        fi
    done
    exec 3<&-
    rm -f "$PIN_SETUP_REQ" "$PIN_SETUP_FIFO"
    [ -n "$pin" ] || return 1
    printf '%s' "$pin"
}

# ---- the operator login ----------------------------------------------------
# Every box flashed from one image starts with the login password chosen when
# the image was built — the same on all of them, and recoverable from anyone's
# copy of the image. First boot replaces it with one of this box's own and
# shows it once (panel, OLED, the keyboard console).

LOGIN_SECRET_FILE="$HUMINT_RUN/login-password.json"

# The account the image was built with (pi-gen's FIRST_USER_NAME): uid 1000.
login_user() { getent passwd 1000 | cut -d: -f1; }

# 16 characters from 32 that cannot be mistaken for each other (no 0/o, 1/l/i)
# — 80 bits — grouped in fours so it can be read off a screen and typed.
# random_chars N — N easy-to-read random characters (no 0/o, 1/l/i).
# Reads a fixed amount of randomness first and filters it afterwards: the
# obvious `tr </dev/urandom | head -c N` kills tr with SIGPIPE, which under
# `set -euo pipefail` (first boot) silently aborts the whole script.
random_chars() {
    local n="$1" out=""
    while [ "${#out}" -lt "$n" ]; do
        out+="$(head -c 4096 /dev/urandom | LC_ALL=C tr -dc 'abcdefghjkmnpqrstuvwxyz23456789')"
    done
    printf '%s' "${out:0:$n}"
}

random_login_password() {
    local raw
    raw="$(random_chars 16)"
    printf '%s-%s-%s-%s' "${raw:0:4}" "${raw:4:4}" "${raw:8:4}" "${raw:12:4}"
}

# Set a new random password for the login and leave it for the panel to show
# until someone confirms they have written it down. Prints it.
new_login_password() {
    local user pw
    user="$(login_user)"
    [ -n "$user" ] || { log "no login account (uid 1000) to set a password for"; return 1; }
    pw="$(random_login_password)"
    printf '%s:%s\n' "$user" "$pw" | chpasswd
    install -d -m 755 "$HUMINT_RUN"
    ( umask 077; printf '{"user": "%s", "password": "%s", "time": %s}\n' \
        "$user" "$pw" "$(date +%s)" >"$LOGIN_SECRET_FILE" )
    log "set a new login password for $user (shown on the screen until confirmed)"
    printf '%s' "$pw"
}

# SSH_AUTHORIZED_KEY in the config: install it, and switch SSH to keys only.
install_ssh_key() {
    local key="$1" user home
    [ -n "$key" ] || return 0
    user="$(login_user)"; home="$(getent passwd "$user" | cut -d: -f6)"
    install -d -m 700 -o "$user" -g "$user" "$home/.ssh"
    printf '%s\n' "$key" >>"$home/.ssh/authorized_keys"
    chown "$user:$user" "$home/.ssh/authorized_keys"; chmod 600 "$home/.ssh/authorized_keys"
    install -d /etc/ssh/sshd_config.d
    printf '# humint first boot: an SSH key was configured, so no passwords over SSH.\nPasswordAuthentication no\nKbdInteractiveAuthentication no\n' \
        >/etc/ssh/sshd_config.d/10-humint-keys-only.conf
    systemctl try-reload-or-restart ssh.service 2>/dev/null || true
    log "installed an SSH key for $user; SSH now accepts keys only"
}

# ---- settings nobody wrote down ---------------------------------------------

# The country a time zone belongs to ("America/Chicago" -> US), from tzdata.
country_for_timezone() {
    awk -F'\t' -v tz="$1" '$1 !~ /^#/ && $3 == tz {print $1; exit}' /usr/share/zoneinfo/zone.tab 2>/dev/null
}

# Fill in what the config file left open (or the whole lot, with no file):
#   TIMEZONE      the image's own (the builder's, see build-image.sh), else UTC
#   WIFI_COUNTRY  the country of that time zone — the hotspot may not
#                 transmit without one
#   AP_PSK        generated (and shown on the panel with the login password)
# Sets AP_PSK_GENERATED=1 when it made one up.
resolve_open_settings() {
    AP_PSK_GENERATED=0
    if [ -z "${TIMEZONE:-}" ]; then
        TIMEZONE="$(cat /etc/timezone 2>/dev/null || true)"
        [ -n "$TIMEZONE" ] || TIMEZONE=UTC
    fi
    if [ -z "${WIFI_COUNTRY:-}" ]; then
        WIFI_COUNTRY="$(country_for_timezone "$TIMEZONE")"
    fi
    if [ -z "${AP_PSK:-}" ] || [ "$AP_PSK" = changeme-now ]; then
        local raw
        raw="$(random_chars 12)"
        AP_PSK="${raw:0:4}-${raw:4:4}-${raw:8:4}"
        AP_PSK_GENERATED=1
    fi
}

# set_env_value FILE KEY VALUE — replace KEY's line, or add it. For the
# values resolve_open_settings makes (no quotes or $ in them).
set_env_value() {
    local file="$1" key="$2" value="$3"
    touch "$file"
    K="$key" V="$value" awk '
        $0 ~ "^"ENVIRON["K"]"=" { print ENVIRON["K"] "=\"" ENVIRON["V"] "\""; done=1; next }
        { print }
        END { if (!done) print ENVIRON["K"] "=\"" ENVIRON["V"] "\"" }' "$file" >"$file.tmp"
    # Keep the file's mode: env is 600 (it holds the Wi-Fi passwords).
    chmod --reference="$file" "$file.tmp" 2>/dev/null || true
    mv "$file.tmp" "$file"
}

# set_env_quoted FILE KEY VALUE — the same, for a value typed by a person (a
# Wi-Fi name or password: spaces, quotes, $ and backslashes all possible).
# Written single-quoted, a ' as '\'' — the file is sourced by root, so it
# must come back as exactly the text typed and never run as anything. The
# Python readers undo the same quoting (shlex). No line breaks or other
# control characters: the caller refuses those.
set_env_quoted() {
    local file="$1" key="$2" value="$3" q
    q="'${value//\'/\'\\\'\'}'"
    touch "$file"
    K="$key" V="$q" awk '
        $0 ~ "^"ENVIRON["K"]"=" { print ENVIRON["K"] "=" ENVIRON["V"]; done=1; next }
        { print }
        END { if (!done) print ENVIRON["K"] "=" ENVIRON["V"] }' "$file" >"$file.tmp"
    chmod --reference="$file" "$file.tmp" 2>/dev/null || true
    mv "$file.tmp" "$file"
}
