#!/usr/bin/env bash
# Bring the console up once the encrypted store is mounted and Docker is
# running. The containers are marked restart:unless-stopped, so Docker usually
# restarts them itself after unlock; this makes sure, and is also what brings
# them back after `humint-ctl stop`.
set -euo pipefail
# shellcheck source=/dev/null
. /opt/humint/lib/humint-common.sh

data_ready || die "case store is not mounted; refusing to start the console"
cd "$HUMINT_SRC"
[ -f .env ] || die "no .env — has first boot run?"
docker info >/dev/null 2>&1 || { systemctl start docker; sleep 2; }
docker compose up -d
log "console containers up"
