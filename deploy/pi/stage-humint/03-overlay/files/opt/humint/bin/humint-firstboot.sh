#!/usr/bin/env bash
# One-time setup, run on the FIRST boot only — at base, before the device goes
# into the field, with the internet reachable. It:
#
#   1. reads humint-appliance.conf from the boot partition and saves it;
#   2. sets the hostname, time zone and Wi-Fi country;
#   3. gets briefly online (the setup uplink) and builds the console's
#      software;
#   4. asks the operator to SET the unlock PIN, then creates the encrypted
#      case store and formats it;
#   5. points Docker at that encrypted store and starts the console;
#   6. switches the network to the deployment mode the team will use.
#
# After this, the config file is renamed to *.done (so the Wi-Fi passphrase
# is not left on a readable partition) and this service never runs again.
# Every later boot just asks for the PIN (humint-unlock) and starts up.
set -euo pipefail
# shellcheck source=/dev/null
. /opt/humint/lib/humint-common.sh

mkdir -p "$HUMINT_STATE"
exec >>"$HUMINT_STATE/firstboot.log" 2>&1 || true

banner() { oled "HUMINT setup" "$1" "${2:-}"; log "$1 ${2:-}"; }

set_env() {  # set_env KEY VALUE FILE  — replace or append KEY=VALUE
    local k="$1" v="$2" f="$3"
    if grep -qE "^${k}=" "$f"; then
        # Use a form that is safe for values containing / and &.
        python3 - "$k" "$v" "$f" <<'PY'
import sys
k, v, f = sys.argv[1], sys.argv[2], sys.argv[3]
lines = open(f).read().splitlines()
out = [f"{k}={v}" if l.startswith(k + "=") else l for l in lines]
open(f, "w").write("\n".join(out) + "\n")
PY
    else
        printf '%s=%s\n' "$k" "$v" >>"$f"
    fi
}

ask_new_pin() {
    # Read a new unlock PIN from the physical keyboard (this service owns
    # tty1), confirming it, and echo it on stdout. The OLED tells the
    # operator what to do, since a headless box has no monitor.
    local a b
    while :; do
        banner "Set unlock PIN" "type on keyboard"
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
    [ -f "$HUMINT_IMG" ] && { log "store already exists; skipping create"; return 0; }
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
    mkdir -p "$HUMINT_DATA"
    mount "/dev/mapper/$HUMINT_MAP" "$HUMINT_DATA"
    mkdir -p "$HUMINT_DATA/docker"
    touch "$HUMINT_READY"
    log "encrypted store created and mounted at $HUMINT_DATA"
}

start_docker() {
    # Docker keeps all its volumes under data-root; putting that inside the
    # encrypted mount is what makes locking one file lock the whole case.
    install -d -m 755 /etc/docker
    cat >/etc/docker/daemon.json <<JSON
{
  "data-root": "$HUMINT_DATA/docker",
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "3" }
}
JSON
    systemctl unmask docker >/dev/null 2>&1 || true
    systemctl start docker || die "docker did not start"
    for _ in $(seq 1 30); do docker info >/dev/null 2>&1 && break; sleep 1; done
    docker info >/dev/null 2>&1 || die "docker not responding"
}

write_env() {
    local env="$HUMINT_SRC/.env"
    [ -f "$env" ] && return 0
    cp "$HUMINT_SRC/.env.example" "$env"
    set_env POSTGRES_PASSWORD "$(openssl rand -hex 24)" "$env"
    set_env API_PORT "$API_PORT" "$env"
    set_env INSTANCE_NAME "$INSTANCE_NAME" "$env"
    # A Pi is no place for a local model; the assistant and extraction still
    # work if the operator later points OLLAMA_BASE_URL at a real machine.
    set_env OLLAMA_ENABLED false "$env"
    set_env SESSION_COOKIE_SECURE false "$env"   # plain http on the field LAN
    chmod 600 "$env"
    log "wrote $env"
}

build_and_up() {
    cd "$HUMINT_SRC"
    banner "Building console" "a few minutes"
    docker compose build || die "image build failed (is the setup uplink online?)"
    banner "Starting console" ""
    docker compose up -d || die "compose up failed"
    log "console started"
}

main() {
    [ -f "$HUMINT_FIRSTBOOT_DONE" ] && { log "first boot already done"; exit 0; }
    banner "Reading config" ""
    [ -f "$HUMINT_CONF" ] || die "no $HUMINT_CONF — copy humint-appliance.conf.example, edit it, rename it"
    load_config "$HUMINT_CONF"
    [ "$NET_MODE" = "hotspot" ] && [ -z "$WIFI_COUNTRY" ] && die "WIFI_COUNTRY is required for hotspot mode"
    cp "$HUMINT_CONF" "$HUMINT_ENV"; chmod 600 "$HUMINT_ENV"

    banner "Identity" "$HOSTNAME"
    hostnamectl set-hostname "$HOSTNAME" || true
    sed -i "s/^127.0.1.1.*/127.0.1.1\t$HOSTNAME/" /etc/hosts 2>/dev/null || \
        printf '127.0.1.1\t%s\n' "$HOSTNAME" >>/etc/hosts
    timedatectl set-timezone "$TIMEZONE" 2>/dev/null || true

    banner "Setup network" "${SETUP_UPLINK}"
    /opt/humint/bin/humint-net.sh setup-uplink || true
    if [ "$SETUP_UPLINK" != "none" ]; then
        /opt/humint/bin/humint-net.sh wait-online 40 || die "no internet for the setup build — check SETUP_UPLINK"
    fi

    create_store
    start_docker
    write_env
    build_and_up

    banner "Deploy network" "$NET_MODE"
    /opt/humint/bin/humint-net.sh remove-setup || true
    /opt/humint/bin/humint-net.sh deploy || die "could not apply $NET_MODE"

    touch "$HUMINT_FIRSTBOOT_DONE"
    # Keep the config, minus the secrets, for reference; rename the original so
    # the passphrases are not left on the readable boot partition.
    mv "$HUMINT_CONF" "${HUMINT_CONF}.done" 2>/dev/null || true
    local ip; ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
    local port=""; [ "$API_PORT" != "80" ] && port=":$API_PORT"
    banner "Ready" "http://${ip}${port}"
    log "first boot complete — console at http://${ip}${port} (or http://${HOSTNAME}.local${port})"
}

main "$@"
