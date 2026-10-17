#!/bin/bash -e
# Every pi-gen stage starts from a copy of the stage before it (stage2: the
# Lite image). Without this the HUMINT stage would start from an empty disk.
if [ ! -d "${ROOTFS_DIR}" ]; then
    copy_previous
fi
