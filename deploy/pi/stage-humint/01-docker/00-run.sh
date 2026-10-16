#!/bin/bash -e
# Install Docker Engine + the compose plugin into the image, add the operator
# account to the docker group, and make sure Docker does NOT start on its own
# at boot. It must wait until the encrypted case store is unlocked and
# mounted, because that is where its data-root lives (see humint-unlock).

on_chroot <<'CHROOT'
set -e

# Docker's own convenience script supports Raspberry Pi OS (arm64/armhf).
curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
sh /tmp/get-docker.sh
rm -f /tmp/get-docker.sh

# The operator account can drive Docker without sudo.
usermod -aG docker "${FIRST_USER_NAME:-humint}" || true

# Do not auto-start: unlock starts Docker after the store is mounted.
systemctl disable docker.service || true
systemctl disable docker.socket  || true
systemctl disable containerd.service || true
CHROOT
