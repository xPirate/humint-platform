#!/bin/bash -e
# PostgreSQL, installed natively — no Docker on the appliance.
#
# Version 16 from the PostgreSQL project's own apt repository, the same major
# version the Docker deployment runs (postgres:16), so a backup taken on one
# restores on the other. Raspberry Pi OS Bookworm itself only ships 15.
#
# The package's default cluster (on the unencrypted root) is dropped. The
# real cluster is created on first boot INSIDE the encrypted case store, and
# is only ever started after the PIN has unlocked it.

on_chroot <<'CHROOT'
set -e
PG_VERSION="${HUMINT_PG_VERSION:-16}"

# Adds apt.postgresql.org (signed) for this Debian release and architecture.
/usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y
apt-get install -y --no-install-recommends "postgresql-${PG_VERSION}" "postgresql-client-${PG_VERSION}"

# No cluster on the root filesystem: the case database lives only in the
# encrypted store.
if pg_lsclusters -h | awk '{print $1" "$2}' | grep -q "^${PG_VERSION} main$"; then
    pg_dropcluster "${PG_VERSION}" main || true
fi

# Nothing starts PostgreSQL at boot. humint-unlock starts it (via
# humint.target) once the store is open.
systemctl disable postgresql.service || true
CHROOT
