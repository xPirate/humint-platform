# Creating the encrypted case store and the database inside it. Shared by
# first boot and by the duress rebuild (humint-wipe.sh), so an emptied box is
# built exactly the way a new one is. Sourced after humint-common.sh.
# shellcheck shell=bash
# shellcheck disable=SC2034

DB_USER=intel
DB_NAME=humint_platform

# A banner on the screen when first boot is talking; just the log otherwise
# (a duress rebuild must not announce itself).
store_step() {
    if declare -F banner >/dev/null; then banner "$@"; else log "$*"; fi
}

# format_store: the PIN on stdin. Encrypts $HUMINT_IMG (which must exist, at
# its full size), opens it, makes the filesystem and mounts it.
format_store() {
    local pin
    IFS= read -r pin || true
    [ -n "$pin" ] || die "format_store: no PIN"
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
        "$HUMINT_DATA/uploads" "$HUMINT_DATA/map-packs" "$HUMINT_DATA/tmp" "$HUMINT_DATA/clock"
}

create_database() {
    # The cluster's data directory lives in the encrypted store, so the case
    # database is only ever readable after the PIN. It listens on localhost
    # only; the console is the only thing that talks to it. UTF-8 explicitly:
    # under systemd the locale is often plain C, and a cluster created there
    # is SQL_ASCII — the first accented name would fail to save.
    if ! pg_lsclusters -h 2>/dev/null | awk '{print $1" "$2}' | grep -q "^${PG_VERSION} ${PG_CLUSTER}$"; then
        store_step "Creating database" ""
        install -d -m 700 -o postgres -g postgres "$PG_DATA"
        pg_createcluster "$PG_VERSION" "$PG_CLUSTER" -d "$PG_DATA" \
            --start-conf=manual -p 5432 \
            --encoding=UTF8 --locale=C.UTF-8 \
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
        store_step "Loading schema" ""
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
# HTTPS with the box's own CA (see humint-tls.sh); port 80 then serves the
# CA certificate and redirects everything else.
TLS=${TLS}
HTTPS_PORT=443
HTTP_PORT=80
INSTANCE_NAME="${INSTANCE_NAME//\"/}"
UPLOAD_DIR=${HUMINT_DATA}/uploads
MAP_PACK_DIR=${HUMINT_DATA}/map-packs
FRONTEND_DIR=${HUMINT_SRC}/frontend
SESSION_COOKIE_SECURE=$([ "$TLS" = on ] && echo true || echo false)
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

