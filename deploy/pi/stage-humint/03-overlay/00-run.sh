#!/bin/bash -e
# Lay the appliance's own files into the image: the scripts, the systemd
# services, the config template on the boot partition. Then enable the
# services and the networking/mDNS daemons they rely on.
#
# pi-gen runs this with the working directory set to this sub-stage folder,
# so "files/..." below refers to the tree beside this script.

# Everything under files/opt and files/etc goes straight into the rootfs.
rsync -a files/opt/ "${ROOTFS_DIR}/opt/"
rsync -a files/etc/ "${ROOTFS_DIR}/etc/"

# The editable config belongs on the FAT boot partition, where the operator
# can reach it from any computer before the first boot.
BOOT="${ROOTFS_DIR}/boot/firmware"
[ -d "$BOOT" ] || BOOT="${ROOTFS_DIR}/boot"
install -m 644 files/boot/humint-appliance.conf.example "${BOOT}/humint-appliance.conf.example"

chmod 0755 "${ROOTFS_DIR}"/opt/humint/bin/*.sh \
           "${ROOTFS_DIR}"/opt/humint/bin/*.py \
           "${ROOTFS_DIR}"/opt/humint/bin/humint-ctl
ln -sf /opt/humint/bin/humint-ctl "${ROOTFS_DIR}/usr/local/bin/humint-ctl"

install -d "${ROOTFS_DIR}/var/lib/humint" "${ROOTFS_DIR}/srv"

on_chroot <<'CHROOT'
set -e
systemctl enable NetworkManager.service || true
systemctl enable avahi-daemon.service || true
systemctl enable ssh.service || true
systemctl enable humint-firstboot.service
systemctl enable humint-unlock.service
systemctl enable humint-compose.service
systemctl enable humint-status.service
CHROOT
