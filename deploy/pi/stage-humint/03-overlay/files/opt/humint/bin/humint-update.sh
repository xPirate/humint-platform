#!/usr/bin/env bash
# Update the field server from a signed bundle (deploy/pi/make-update.sh) —
# no re-imaging, no internet, no SSH needed.
#
#   humint-update.sh verify FILE        check a bundle; say what it is
#   humint-update.sh apply FILE [--force]
#   humint-update.sh usb                find the newest bundle on a USB stick and apply it
#   humint-update.sh apply-inbox        apply one uploaded through the console
#   humint-update.sh rollback           go back to before the last update (code AND database)
#   humint-update.sh status
#
# Applying, in order — and on any failure from step 4 on, everything is put
# back the way it was:
#   1. the signature must check against the key this image was built with
#      (/opt/humint/update-signing.pub), and the payload against the manifest;
#   2. it must be newer than what is installed (--force to reinstall/downgrade);
#   3. the case file must be open (migrations need the database);
#   4. the database is dumped (into the encrypted store), the console stopped;
#   5. the code is swapped in, the appliance's scripts and units refreshed, new
#      Python wheels installed if the requirements changed;
#   6. migrations this box has not had are run, oldest first;
#   7. the console is started and must answer within 90 seconds.
#
# Exit codes: 0 done, 2 usage, 3 bad signature or damaged, 4 not newer,
# 5 needs wheels it does not carry, 6 case file locked, 7 failed and rolled back.
set -euo pipefail

# Runs from a copy: step 5 replaces this very file, and bash reads a script
# from disk as it goes.
if [ "${HUMINT_UPDATE_COPY:-}" != 1 ] && [ "${1:-}" != status ] && [ "${1:-}" != verify ]; then
    mkdir -p /run/humint
    cp "$0" /run/humint/humint-update.run
    HUMINT_UPDATE_COPY=1 exec bash /run/humint/humint-update.run "$@"
fi

# shellcheck source=/dev/null
. "${HUMINT_LIB:-/opt/humint/lib}/humint-common.sh"

R="${HUMINT_TEST_ROOT:-}"            # only the tests set this
if [ -n "$R" ]; then
    HUMINT_DATA="$R$HUMINT_DATA"; HUMINT_READY="$R$HUMINT_READY"; HUMINT_ENV="$R$HUMINT_ENV"
fi
APP_DIR="$R/opt/humint-platform"
HOME_DIR="$R/opt/humint"
ETC_DIR="$R/etc"
PUBKEY="$HOME_DIR/update-signing.pub"
BUILD_FILE="$APP_DIR/BUILD.json"
APPLIED="$R/var/lib/humint/migrations-applied"
LOGFILE="$R/var/lib/humint/update.log"
STATUS="$R/run/humint/update.json"
INBOX="$HUMINT_DATA/updates/incoming.tar"
DB_NAME=humint_platform
HEALTH_TIMEOUT=90

note()   { log "update: $*"; printf '%s %s\n' "$(date -Is)" "$*" >>"$LOGFILE" 2>/dev/null || true; }
status() { # status STATE [MESSAGE]
    mkdir -p "$(dirname "$STATUS")"
    python3 - "$STATUS" "$1" "${2:-}" "${NEW_BUILD:-}" "$(installed_build)" <<'PY'
import json, sys, time
path, state, msg, new, cur = sys.argv[1:6]
json.dump({"state": state, "message": msg, "to_build": int(new) if new else None,
           "installed_build": int(cur) if cur else None, "time": time.time()}, open(path, "w"))
PY
    chmod 644 "$STATUS" 2>/dev/null || true
}
json_get() { python3 -c 'import json,sys; v=json.load(open(sys.argv[1])).get(sys.argv[2]); print("" if v is None else v)' "$1" "$2"; }
installed_build() { [ -f "$BUILD_FILE" ] && json_get "$BUILD_FILE" build || echo 0; }
installed_req() { [ -f "$BUILD_FILE" ] && json_get "$BUILD_FILE" requirements_sha256 || echo; }

WORK=""
cleanup() { if [ -n "$WORK" ]; then rm -rf "$WORK"; fi; }
trap cleanup EXIT

# unpack_and_verify FILE -> sets WORK, NEW_BUILD; exits 3 on any doubt.
unpack_and_verify() {
    local file="$1"
    [ -f "$file" ] || { echo "no such file: $file" >&2; exit 2; }
    [ -f "$PUBKEY" ] || { echo "this box has no update key ($PUBKEY): it was built before updates existed — re-image it once" >&2; exit 3; }
    WORK="$(mktemp -d "${TMPDIR:-/var/tmp}/humint-update.XXXXXX")"
    # Only the three names a bundle has: nothing else is extracted.
    tar -xf "$file" -C "$WORK" manifest.json manifest.sig payload.tar.gz 2>/dev/null ||
        { echo "not an update bundle (or damaged)" >&2; exit 3; }
    openssl pkeyutl -verify -pubin -inkey "$PUBKEY" -rawin -in "$WORK/manifest.json" \
        -sigfile "$WORK/manifest.sig" >/dev/null 2>&1 ||
        { echo "SIGNATURE DOES NOT MATCH — not made by this box's builder, or altered. Not applied." >&2; exit 3; }
    [ "$(json_get "$WORK/manifest.json" format)" = humint-field-update ] ||
        { echo "unknown bundle format" >&2; exit 3; }
    [ "$(sha256sum "$WORK/payload.tar.gz" | cut -d' ' -f1)" = "$(json_get "$WORK/manifest.json" payload_sha256)" ] ||
        { echo "payload does not match its signed manifest — damaged copy. Not applied." >&2; exit 3; }
    NEW_BUILD="$(json_get "$WORK/manifest.json" build)"
}

cmd_verify() {
    unpack_and_verify "$1"
    echo "Signed by this box's builder. Build $NEW_BUILD ($(json_get "$WORK/manifest.json" commit));" \
         "installed: build $(installed_build)."
}

# ---- rollback pieces ----------------------------------------------------------

snapshot() {   # what "put it back" needs
    rm -rf "$APP_DIR.prev"
    cp -a "$APP_DIR" "$APP_DIR.prev"
    tar -C "$HOME_DIR" --exclude=./venv -czf "$HOME_DIR.prev-overlay.tgz" .
    tar -C "$ETC_DIR" -czf "$HOME_DIR.prev-etc.tgz" systemd/system NetworkManager/dispatcher.d 2>/dev/null || true
    cp -f "$APPLIED" "$APPLIED.prev" 2>/dev/null || : >"$APPLIED.prev"
}

restore_code() {
    if [ -d "$APP_DIR.prev" ]; then
        rm -rf "$APP_DIR"
        cp -a "$APP_DIR.prev" "$APP_DIR"
    fi
    [ -f "$HOME_DIR.prev-overlay.tgz" ] && tar -C "$HOME_DIR" -xzf "$HOME_DIR.prev-overlay.tgz"
    [ -f "$HOME_DIR.prev-etc.tgz" ] && tar -C "$ETC_DIR" -xzf "$HOME_DIR.prev-etc.tgz"
    [ -f "$APPLIED.prev" ] && cp -f "$APPLIED.prev" "$APPLIED"
    systemctl daemon-reload 2>/dev/null || true
}

restore_database() {
    local dump="$1"
    [ -f "$dump" ] || return 0
    note "restoring the database from $dump"
    runuser -u postgres -- pg_restore --clean --if-exists -d "$DB_NAME" "$dump" >/dev/null 2>&1 || true
}

healthy() {
    local url
    load_config "$HUMINT_ENV"
    if [ "${TLS:-on}" = on ]; then url="https://127.0.0.1:${HTTPS_PORT:-443}"; else url="http://127.0.0.1:${API_PORT:-80}"; fi
    for _ in $(seq 1 "$HEALTH_TIMEOUT"); do
        curl -fsk -o /dev/null --max-time 3 "$url/api/auth/bootstrap-status" && return 0
        sleep 1
    done
    return 1
}

fail_and_roll_back() {   # fail_and_roll_back MESSAGE DUMP
    note "FAILED: $1 — rolling back"
    status rolling-back "$1"
    systemctl stop humint-api.service humint-worker.service humint-http.service 2>/dev/null || true
    restore_code
    restore_database "$2"
    start_console 2>/dev/null || true
    status failed "$1 — rolled back to build $(installed_build)"
    echo "Update failed: $1. Rolled back; the console is as it was." >&2
    exit 7
}

# ---- apply ----------------------------------------------------------------------

cmd_apply() {
    local file="$1" force="${2:-}"
    unpack_and_verify "$file"
    local cur; cur="$(installed_build)"
    if [ "$NEW_BUILD" -le "$cur" ] && [ "$force" != --force ]; then
        echo "Already at build $cur; this bundle is build $NEW_BUILD. (--force to install it anyway.)" >&2
        exit 4
    fi
    local new_req; new_req="$(json_get "$WORK/manifest.json" requirements_sha256)"
    local wheels; wheels="$(json_get "$WORK/manifest.json" wheels)"
    if [ "$new_req" != "$(installed_req)" ] && [ "$wheels" != True ]; then
        echo "This update changes the Python packages but carries none (it was not built on the builder Pi). Not applied." >&2
        exit 5
    fi
    data_ready || { echo "Unlock the case file first: migrations need the database." >&2; exit 6; }

    note "applying build $NEW_BUILD over $cur"
    status applying "build $NEW_BUILD"
    oled "Updating" "build $NEW_BUILD" "do not unplug"
    mkdir -p "$WORK/p"
    tar -xzf "$WORK/payload.tar.gz" -C "$WORK/p"

    local dump="$HUMINT_DATA/backups/pre-update-$cur-to-$NEW_BUILD.dump"
    install -d -m 700 "$HUMINT_DATA/backups"
    runuser -u postgres -- pg_dump -Fc "$DB_NAME" >"$dump" ||
        { status failed "could not back up the database first"; echo "could not back up the database; nothing changed" >&2; exit 7; }
    chmod 600 "$dump"
    ln -sf "$(basename "$dump")" "$HUMINT_DATA/backups/pre-update-latest.dump"

    snapshot
    systemctl stop humint-api.service humint-worker.service humint-http.service 2>/dev/null || true

    # code
    rsync -a --delete --exclude BUILD.json "$WORK/p/app/" "$APP_DIR/" || fail_and_roll_back "copying the code" "$dump"
    # appliance scripts and units (keeping the venv, this box's key and build time)
    rsync -a "$WORK/p/overlay/opt/humint/" "$HOME_DIR/" || fail_and_roll_back "copying the appliance scripts" "$dump"
    rsync -a "$WORK/p/overlay/etc/" "$ETC_DIR/" || fail_and_roll_back "copying the units" "$dump"
    chmod 0755 "$HOME_DIR"/bin/* 2>/dev/null || true
    systemctl daemon-reload 2>/dev/null || true

    if [ "$new_req" != "$(installed_req)" ]; then
        note "installing Python packages from the bundle's wheels"
        "$HOME_DIR/venv/bin/pip" install -q --no-index --find-links "$WORK/p/wheels" \
            -r "$APP_DIR/api/requirements.txt" -r "$APP_DIR/worker/requirements.txt" ||
            fail_and_roll_back "installing Python packages" "$dump"
    fi
    "$HOME_DIR/venv/bin/python" -m compileall -q "$APP_DIR/api" "$APP_DIR/worker" >/dev/null 2>&1 || true

    # migrations this box has not had, in the order the bundle lists them
    touch "$APPLIED"
    local m
    while IFS= read -r m; do
        [ -n "$m" ] || continue
        grep -qxF "$m" "$APPLIED" && continue
        note "migration $m"
        runuser -u postgres -- psql -q -v ON_ERROR_STOP=1 -d "$DB_NAME" -f "$APP_DIR/db/$m" >/dev/null ||
            fail_and_roll_back "migration $m" "$dump"
        echo "$m" >>"$APPLIED"
    done < <(python3 -c 'import json,sys; print("\n".join(json.load(open(sys.argv[1]))["migrations"]))' "$WORK/manifest.json")

    python3 - "$WORK/manifest.json" "$BUILD_FILE" <<'PY'
import json, sys, time
m = json.load(open(sys.argv[1]))
json.dump({"build": m["build"], "commit": m["commit"], "requirements_sha256": m["requirements_sha256"],
           "installed": int(time.time())}, open(sys.argv[2], "w"), indent=1)
PY
    start_console || fail_and_roll_back "starting the console" "$dump"
    healthy || fail_and_roll_back "the console did not come back" "$dump"
    # The appliance's own services, on their new scripts.
    systemctl try-restart humint-panel.service humint-status.service humint-clock.service \
        humint-battery.service 2>/dev/null || true
    note "now at build $NEW_BUILD"
    status "done" "now at build $NEW_BUILD"
    oled "Updated" "build $NEW_BUILD" ""
    echo "Updated to build $NEW_BUILD. (Before: build $cur. Undo with: humint-ctl update rollback)"
}

cmd_rollback() {
    [ -d "$APP_DIR.prev" ] || { echo "nothing to roll back to" >&2; exit 2; }
    data_ready || { echo "Unlock the case file first." >&2; exit 6; }
    note "rolling back the last update"
    systemctl stop humint-api.service humint-worker.service humint-http.service 2>/dev/null || true
    restore_code
    restore_database "$HUMINT_DATA/backups/pre-update-latest.dump"
    start_console
    status "done" "rolled back to build $(installed_build)"
    echo "Rolled back to build $(installed_build) (code and database as they were before the update)."
}

cmd_usb() {
    # Every partition that is not the SD card or the boot NVMe, mounted
    # read-only in turn; the newest bundle found anywhere is copied off first.
    local mnt=/run/humint/usb dev f b best="" best_build=-1 pick
    pick="$(mktemp -d)"
    mkdir -p "$mnt"
    for dev in $(lsblk -rpno NAME,TYPE | awk '$2=="part"{print $1}'); do
        case "$dev" in /dev/mmcblk*|/dev/nvme0n1p1|/dev/nvme0n1p2) continue ;; esac
        mount -o ro "$dev" "$mnt" 2>/dev/null || continue
        while IFS= read -r f; do
            b="$(basename "$f" | sed -n 's/^humint-update-\([0-9][0-9]*\)-.*\.tar$/\1/p')"
            [ -n "$b" ] || continue
            if [ "$b" -gt "$best_build" ]; then
                rm -f "$pick"/*
                cp "$f" "$pick/" && best="$pick/$(basename "$f")" && best_build="$b"
            fi
        done < <(find "$mnt" -maxdepth 3 -name 'humint-update-*.tar' 2>/dev/null)
        umount "$mnt" 2>/dev/null || true
    done
    if [ -z "$best" ]; then
        status failed "no update found on a USB stick"
        echo "No humint-update-*.tar on any USB stick." >&2
        exit 2
    fi
    note "found $(basename "$best") on USB"
    cmd_apply "$best"
}

cmd_inbox() {
    [ -f "$INBOX" ] || exit 0
    local f="$HUMINT_DATA/updates/applying.tar"
    mv -f "$INBOX" "$f"
    local rc=0
    ( cmd_apply "$f" ) || rc=$?
    case "$rc" in
        0) ;;
        3) status failed "rejected: the signature does not match this box's builder" ;;
        4) status failed "not newer than what is installed" ;;
        5) status failed "needs Python packages it does not carry — build it on the builder Pi" ;;
        6) status failed "unlock the case file first" ;;
    esac
    rm -f "$f"
    return 0
}

cmd_status() {
    echo "Installed: build $(installed_build) ($( [ -f "$BUILD_FILE" ] && json_get "$BUILD_FILE" commit))"
    [ -f "$STATUS" ] && python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print("Last update:", d["state"], "-", d["message"])' "$STATUS"
    [ -f "$PUBKEY" ] || echo "No update key on this box: it accepts no bundles until re-imaged."
}

main() {
    case "${1:-}" in
        verify)      [ $# -ge 2 ] || exit 2; cmd_verify "$2" ;;
        apply)       [ $# -ge 2 ] || exit 2; cmd_apply "$2" "${3:-}" ;;
        usb)         cmd_usb ;;
        apply-inbox) cmd_inbox ;;
        rollback)    cmd_rollback ;;
        status)      cmd_status ;;
        *) sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
    esac
}

main "$@"
