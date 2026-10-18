#!/bin/bash -e
# Install the console itself, natively: its code under /opt/humint-platform,
# one Python virtual environment with everything the API, the worker and the
# status screen need, and a system account to run them as.
#
# Everything is installed HERE, at image build time, so the device never
# needs the internet — not even on its first boot.
#
# HUMINT_SRC_DIR (pi-gen config) is a checkout of this repository on the
# build machine. Copying from a local checkout avoids needing credentials for
# a private repo inside the build chroot.

# pi-gen only passes its own settings on to stages, so a plain
# HUMINT_SRC_DIR=... in config never arrives here; config says
# "export HUMINT_SRC_DIR=...". Without it, use the copy prepare-pigen.sh
# makes inside pi-gen (BASE_DIR is the pi-gen folder).
HUMINT_SRC_DIR="${HUMINT_SRC_DIR:-${BASE_DIR}/humint-src}"
if [ ! -d "${HUMINT_SRC_DIR}/api" ]; then
    echo "HUMINT app not found at ${HUMINT_SRC_DIR} — run deploy/pi/prepare-pigen.sh (or build-image.sh) first" >&2
    exit 1
fi

install -d "${ROOTFS_DIR}/opt/humint-platform"
# Only what runs on the box: the API, the worker, the frontend and the schema.
# The Android app, design docs and screenshots stay on the build machine.
for part in api worker frontend db; do
    rsync -a --delete --exclude '__pycache__' \
        "${HUMINT_SRC_DIR}/${part}/" "${ROOTFS_DIR}/opt/humint-platform/${part}/"
done
install -m 644 "${HUMINT_SRC_DIR}/.env.example" "${ROOTFS_DIR}/opt/humint-platform/.env.example"

on_chroot <<'CHROOT'
set -e

# The account the API and worker run as. No login, no home to speak of.
id humintd >/dev/null 2>&1 || \
    adduser --system --group --home /var/lib/humintd --no-create-home humintd

# Turn on the I2C bus the OLED hangs off, and load its device node at boot.
CFG=/boot/firmware/config.txt
[ -f "$CFG" ] || CFG=/boot/config.txt
grep -q '^dtparam=i2c_arm=on' "$CFG" || echo 'dtparam=i2c_arm=on' >> "$CFG"
grep -q '^i2c-dev' /etc/modules || echo 'i2c-dev' >> /etc/modules
# The status screen reads the I2C bus; it runs as root, but give the
# operator account access too for i2cdetect when wiring a screen.
usermod -aG i2c "${FIRST_USER_NAME:-humint}" || true

# One environment for the API, the worker and the screen. Bookworm's own
# Python is 3.11 — the same version the Docker images use. Most packages
# have prebuilt arm64 wheels; the few that do not (RPi.GPIO and spidev, via
# luma.oled; sgmllib3k, via feedparser) compile here with build-essential.
python3 -m venv /opt/humint/venv
/opt/humint/venv/bin/pip install --no-cache-dir --upgrade pip wheel
/opt/humint/venv/bin/pip install --no-cache-dir \
    -r /opt/humint-platform/api/requirements.txt \
    -r /opt/humint-platform/worker/requirements.txt \
    "luma.oled==3.13.0" "gpiozero>=2.0" "smbus2>=0.4"

# Byte-compile once now, as root, so the services (which cannot write here)
# do not try to on every start.
/opt/humint/venv/bin/python -m compileall -q /opt/humint-platform/api /opt/humint-platform/worker || true
chown -R root:root /opt/humint-platform /opt/humint
chmod -R a+rX /opt/humint-platform /opt/humint
CHROOT

# When this image was built: humint-clock never sets the clock earlier than
# this, whatever a device claims.
date +%s >"${ROOTFS_DIR}/opt/humint/build-epoch"
chmod 644 "${ROOTFS_DIR}/opt/humint/build-epoch"

# Which build this image is, and the migrations already in its schema (init.sql
# carries all of them): humint-update.sh applies only what comes after.
if [ -f "${HUMINT_SRC_DIR}/BUILD.json" ]; then
    install -m 644 "${HUMINT_SRC_DIR}/BUILD.json" "${ROOTFS_DIR}/opt/humint-platform/BUILD.json"
fi
install -d -m 755 "${ROOTFS_DIR}/var/lib/humint"
( cd "${HUMINT_SRC_DIR}/db" && ls migrate-v*.sql 2>/dev/null | sort -V ) >"${ROOTFS_DIR}/var/lib/humint/migrations-applied"
