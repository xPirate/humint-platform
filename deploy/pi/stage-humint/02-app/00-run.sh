#!/bin/bash -e
# Bake the console's code into the image and build the small Python
# environment the status screen uses. The Docker images themselves are built
# on the first boot (which has internet), not here — building images inside
# the pi-gen chroot under emulation is slow and unreliable.
#
# HUMINT_SRC_DIR (set in the pi-gen config) is the path to a checkout of this
# repository on the build machine. Copying from a local checkout avoids
# needing credentials for a private repo inside the chroot.

: "${HUMINT_SRC_DIR:?set HUMINT_SRC_DIR to a checkout of the humint-platform repo}"

install -d "${ROOTFS_DIR}/opt/humint-platform"
rsync -a --delete \
    --exclude '.git' --exclude 'node_modules' --exclude '*.img' \
    --exclude 'deploy/pi/work' \
    "${HUMINT_SRC_DIR}/" "${ROOTFS_DIR}/opt/humint-platform/"

on_chroot <<'CHROOT'
set -e

# Turn on the I2C bus the OLED hangs off, and load its device node at boot.
CFG=/boot/firmware/config.txt
[ -f "$CFG" ] || CFG=/boot/config.txt
grep -q '^dtparam=i2c_arm=on' "$CFG" || echo 'dtparam=i2c_arm=on' >> "$CFG"
grep -q '^i2c-dev' /etc/modules || echo 'i2c-dev' >> /etc/modules

# A self-contained Python environment for the screen (kept out of the system
# Python, which Bookworm marks externally-managed).
python3 -m venv /opt/humint/venv
/opt/humint/venv/bin/pip install --no-cache-dir --upgrade pip
/opt/humint/venv/bin/pip install --no-cache-dir \
    "luma.oled==3.13.0" "Pillow>=10.0" "gpiozero>=2.0" "smbus2>=0.4"
CHROOT
