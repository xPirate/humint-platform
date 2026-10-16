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

mkdir -p "$HUMINT_STATE"
cd /
exec 2>>"$HUMINT_STATE/firstboot.log" || true

DB_USER=intel
DB_NAME=humint_platform

banner() { oled "HUMINT setup" "$1" "${2:-}"; log "$1 ${2:-}"; printf '%s %s\n' "$1" "${2:-}" >/dev/tty1; }

ask_new_pin() {
    # Read a new unlock PIN from the physical keyboard (this service owns
    # tty1), confirming it, and echo it on stdout. The OLED tells the
    # operator what to do, since a headless box has no monitor.
    local a b
    while :; do
        oled "HUMINT setup" "Set unlock PIN" "type on keyboard"
        printf '\n\nHUMINT field server — set the unlock PIN.\n' >/dev/tty1
        printf 'You will type this at every boot to open the case file.\n' >/dev/tty1
        printf 'New PIN: ' >/dev/tty1
        IFS= read -rs a </dev/tty1; printf '\n' >/dev/tty1
        printf 'Confirm: ' >/dev/tty1
        IFS= read -rs b </dev/tty1; printf '\n' >/dev/tty1
        if [ -z "$a" ]; then printf 'Empty — try again.\n' >/dev/tty1; continue; fi
        if [ "$a" != "$b" ]; then
            printf 'Did not match — try again.\n' >/dev/tty1
            oled "Set unlock PIN" "did not match" "try again"; continue
        fi
        printf '%s' "$a"; return 0
    done
}

create_store() {
    if [ -f "$HUMINT_IMG" ]; then
        # A previous attempt got this far and then failed. The store exists;
        # it must be opened with the PIN set then.
        log "store already exists; opening it"
        if [ ! -e "/dev/mapper/$HUMINT_MAP" ]; then
            local pin
            oled "HUMINT setup" "Enter unlock PIN" "(set earlier)"
            printf '\nThe case store was already created. Enter its PIN: ' >/dev/tty1
            IFS= read -rs pin </dev/tty1; printf '\n' >/dev/tty1
            printf '%s' "$pin" | cryptsetup open --key-file=- "$HUMINT_IMG" "$HUMINT_MAP" \
                || die "wrong PIN for the existing store (delete $HUMINT_IMG to start over)"
            unset pin
        fi
        mount_store
        return 0
    fi

    banner "Making store" "$DATA_SIZE"
    mkdir -p "$(dirname "$HUMINT_IMG")"
    # Real (not sparse) allocation: a half-written encrypted volume that ran
    # out of card space mid-deployment is the worst time to find out.
    fallocate -l "$DATA_SIZE" "$HUMINT_IMG" || die "could not allocate $DATA_SIZE for the store"
    chmod 600 "$HUMINT_IMG"

    local pin; pin="$(ask_new_pin)"
    banner "Encrypting store" "please wait"
    # LUKS2 with argon2id: the key-stretching that makes a short PIN costly to
    # guess. The PIN never touches disk or the log — it is piped in.
    printf '%s' "$pin" | cryptsetup luksFormat --type luks2 --pbkdf argon2id \
        --batch-mode --key-file=- "$HUMINT_IMG" || die "luksFormat failed"
    printf '%s' "$pin" | cryptsetup open --key-file=- "$HUMINT_IMG" "$HUMINT_MAP" \
        || die "could not open the new store"
    unset pin
    mkfs.ext4 -q -L humint-data "/dev/mapper/$HUMINT_MAP" || die "mkfs failed"
    mount_store
    log "encrypted store created and mounted at $HUMINT_DATA"
}

make_store_dirs() {
    install -d -m 750 -o "$APP_USER" -g "$APP_USER" \
        "$HUMINT_DATA/uploads" "$HUMINT_DATA/map-packs" "$HUMINT_DATA/tmp"
}

create_database() {
    # The cluster's data directory lives in the encrypted store, so the case
    # database is only ever readable after the PIN. It listens on localhost
    # only; the console is the only thing that talks to it.
    if ! pg_lsclusters -h 2>/dev/null | awk '{print $1" "$2}' | grep -q "^${PG_VERSION} ${PG_CLUSTER}$"; then
        banner "Creating database" ""
        install -d -m 700 -o postgres -g postgres "$PG_DATA"
        pg_createcluster "$PG_VERSION" "$PG_CLUSTER" -d "$PG_DATA" \
            --start-conf=manual -p 5432 \
            -o listen_addresses=localhost \
            -o shared_buffers=128MB \
            -- --auth-host=scram-sha-256 --auth-local=peer \
            || die "pg_createcluster failed"
    fi
    systemctl start "$PG_UNIT" || die "PostgreSQL did not start"
    for _ in $(seq 1 30); do
        pg_isready -q -h 127.0.0.1 -p 5432 && break; sleep 1
    done
    pg_isready -q -h 127.0.0.1 -p 5432 || die "PostgreSQL not answering"

    local pw
    if [ -f "$APP_ENV" ]; then
        pw="$(sed -n 's/^POSTGRES_PASSWORD=//p' "$APP_ENV")"
    else
        pw="$(openssl rand -hex 24)"   # hex: no quoting surprises anywhere
    fi

    runuser -u postgres -- psql -q -v ON_ERROR_STOP=1 -d postgres <<SQL
DO \$\$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${DB_USER}') THEN
    CREATE ROLE ${DB_USER} LOGIN PASSWORD '${pw}';
  ELSE
    ALTER ROLE ${DB_USER} LOGIN PASSWORD '${pw}';
  END IF;
END \$\$;
SQL
    if ! runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -q 1; then
        runuser -u postgres -- createdb -O "$DB_USER" "$DB_NAME"
        banner "Loading schema" ""
        PGPASSWORD="$pw" psql -q -h 127.0.0.1 -U "$DB_USER" -d "$DB_NAME" \
            -v ON_ERROR_STOP=1 -f "$HUMINT_SRC/db/init.sql" >/dev/null \
            || die "loading the schema failed"
    fi
    write_app_env "$pw"
}

write_app_env() {
    # A minimal, generated settings file — the console's defaults cover the
    # rest. It lives inside the store (it holds the database password), and
    # only root and the service account can read it.
    local pw="$1"
    local tmp="$APP_ENV.tmp"
    umask 027
    cat >"$tmp" <<ENV
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
POSTGRES_USER=${DB_USER}
POSTGRES_PASSWORD=${pw}
POSTGRES_DB=${DB_NAME}
API_PORT=${API_PORT}
INSTANCE_NAME="${INSTANCE_NAME//\"/}"
UPLOAD_DIR=${HUMINT_DATA}/uploads
MAP_PACK_DIR=${HUMINT_DATA}/map-packs
FRONTEND_DIR=${HUMINT_SRC}/frontend
# Plain http on the field LAN.
SESSION_COOKIE_SECURE=false
# Nothing on the box reaches the internet. Point OLLAMA_BASE_URL at a model
# server on the same network and set OLLAMA_ENABLED=true to use the assistant.
OLLAMA_ENABLED=false
GEOCODE_ENABLED=false
OVERPASS_ENABLED=false
ENV
    chown root:"$APP_USER" "$tmp"
    chmod 640 "$tmp"
    mv "$tmp" "$APP_ENV"
    log "wrote $APP_ENV"
}

main() {
    [ -f "$HUMINT_FIRSTBOOT_DONE" ] && { log "first boot already done"; exit 0; }
    banner "Reading config" ""
    [ -f "$HUMINT_CONF" ] || {
        oled "HUMINT setup" "No config file" "see README"
        die "no $HUMINT_CONF — copy humint-appliance.conf.example, edit it, rename it"
    }
    load_config "$HUMINT_CONF"
    [ "$NET_MODE" = "hotspot" ] && [ -z "$WIFI_COUNTRY" ] && die "WIFI_COUNTRY is required for hotspot mode"
    cp "$HUMINT_CONF" "$HUMINT_ENV"; chmod 600 "$HUMINT_ENV"

    banner "Identity" "$HOSTNAME"
    hostnamectl set-hostname "$HOSTNAME" || true
    if grep -q '^127.0.1.1' /etc/hosts; then
        sed -i "s/^127.0.1.1.*/127.0.1.1\t$HOSTNAME/" /etc/hosts
    else
        printf '127.0.1.1\t%s\n' "$HOSTNAME" >>/etc/hosts
    fi
    timedatectl set-timezone "$TIMEZONE" 2>/dev/null || true

    create_store
    make_store_dirs
    create_database

    banner "Starting console" ""
    start_console || die "console did not start"

    banner "Deploy network" "$NET_MODE"
    /opt/humint/bin/humint-net.sh deploy || die "could not apply $NET_MODE"

    touch "$HUMINT_FIRSTBOOT_DONE"
    # Rename the original so the passphrases are not left on the readable
    # boot partition. (The working copy lives in $HUMINT_ENV, root-only.)
    mv "$HUMINT_CONF" "${HUMINT_CONF}.done" 2>/dev/null || true
    sleep 3   # let the hotspot come up before reading the address
    local ip; ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
    local port=""; [ "$API_PORT" != "80" ] && port=":$API_PORT"
    banner "Ready" "http://${ip}${port}"
    printf '\nOpen http://%s%s (or http://%s.local%s) and create the admin account.\n' \
        "$ip" "$port" "$HOSTNAME" "$port" >/dev/tty1
    log "first boot complete — console at http://${ip}${port} (or http://${HOSTNAME}.local${port})"
}

main "$@"
