#!/usr/bin/env bash
# The installer on the HUMINT USB stick: copies the field server onto this
# computer's internal disk, erasing it, with no network needed.
#
# Runs on the stick's live system (booted with humint.install on the kernel
# command line — the stick's GRUB menu adds it), on the first console, as
# humint-installer.service. The system it installs is the stick's own
# read-only image (/run/live/rootfs), not the running RAM copy, so nothing
# from this session ends up on the disk.
#
#   humint-install.sh                ask which disk, then install
#   humint-install.sh --disk /dev/X --yes   no questions (tests)
set -euo pipefail

SRC=/run/live/rootfs
MEDIUM=/run/live/medium
TARGET=/mnt/humint-target
LOG=/run/humint-install.log
MIN_DISK_GB=16
TITLE="HUMINT field server — install"
export TERM="${TERM:-linux}" NEWT_COLORS='root=green,black window=green,black border=green,black textbox=green,black button=black,green actbutton=black,green entry=green,black listbox=green,black actlistbox=black,green title=green,black'

DISK="" YES=0
# Unattended installs (many machines, or the automated test): add
#   humint.install.disk=/dev/nvme0n1 humint.install.auto
# to the stick's GRUB line. It erases that disk without asking, then powers off.
for word in $(cat /proc/cmdline 2>/dev/null); do
    case "$word" in
        humint.install.disk=*) DISK="${word#humint.install.disk=}" ;;
        humint.install.auto) YES=1 ;;
    esac
done
[ -n "$DISK" ] || YES=0
while [ $# -gt 0 ]; do
    case "$1" in
        --disk) DISK="$2"; shift 2 ;;
        --yes) YES=1; shift ;;
        *) echo "unknown option $1" >&2; exit 2 ;;
    esac
done

log() { printf '%s %s\n' "$(date +%T)" "$*" >>"$LOG"; }
say() { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; log "$*"; }
ask() { [ "$YES" = 1 ] || whiptail --title "$TITLE" "$@" 3>&1 1>&2 2>&3; }

fail() {
    log "FAILED: $*"
    if [ "$YES" = 1 ]; then echo "FAILED: $*" >&2; exit 1; fi
    local choice
    choice="$(whiptail --title "$TITLE" --menu "The install stopped:\n\n$*\n\nThe last lines of the log are in $LOG." 20 74 3 \
        retry "Start again" shell "Open a shell (advanced)" off "Power off" 3>&1 1>&2 2>&3)" || choice=off
    case "$choice" in
        retry) exec "$0" ;;
        shell) clear; echo "Type 'exit' to return to the installer."; bash -l || true; exec "$0" ;;
        *) systemctl poweroff; exit 1 ;;
    esac
}
trap 'fail "an unexpected error at line $LINENO (see $LOG)"' ERR

cleanup_mounts() {
    for m in "$TARGET/sys/firmware/efi/efivars" "$TARGET/sys" "$TARGET/proc" "$TARGET/dev/pts" \
             "$TARGET/dev" "$TARGET/run" "$TARGET/boot/efi" "$TARGET" /mnt/humint-usb-boot; do
        mountpoint -q "$m" 2>/dev/null && umount -l "$m" 2>/dev/null || true
    done
}

# The disk the stick itself is on, so it is never offered.
stick_disk() {
    local part
    part="$(findmnt -no SOURCE "$MEDIUM" 2>/dev/null || true)"
    [ -n "$part" ] && lsblk -no PKNAME "$part" 2>/dev/null | head -1
}

candidate_disks() {
    local stick; stick="$(stick_disk || true)"
    lsblk -dnpbo NAME,SIZE,TYPE,TRAN,MODEL | while read -r name size type tran model; do
        [ "$type" = disk ] || continue
        case "$name" in /dev/loop*|/dev/zram*|/dev/sr*|/dev/ram*) continue ;; esac
        [ -n "$stick" ] && [ "$name" = "/dev/$stick" ] && continue
        [ "$size" -ge $((MIN_DISK_GB * 1000 * 1000 * 1000)) ] || continue
        printf '%s\t%s\t%s\t%s\n' "$name" "$((size / 1000 / 1000 / 1000))" "${tran:-}" "${model:-}"
    done
}

partitions_of() { lsblk -lnpo NAME,TYPE "$1" | awk '$2 == "part" {print $1}'; }

main() {
    : >"$LOG"
    [ -d "$SRC/etc" ] || fail "This is not the HUMINT USB stick's installer (no system image at $SRC)."
    [ -d /sys/firmware/efi ] || fail "This computer started the stick in legacy (BIOS) mode. Turn on UEFI boot in its firmware settings and start from the stick again."

    if [ -z "$DISK" ]; then
        local rows=() line name gb tran model
        while IFS=$'\t' read -r name gb tran model; do
            rows+=("$name" "${gb} GB  ${tran:+$tran  }${model:-disk}")
        done < <(candidate_disks)
        [ "${#rows[@]}" -gt 0 ] || fail "No internal disk of at least ${MIN_DISK_GB} GB was found to install on."
        DISK="$(ask --menu "Install the HUMINT field server on which disk?\n\nEVERYTHING on the disk you choose will be erased — Windows, files, all of it." \
            18 74 6 "${rows[@]}")" || { systemctl poweroff; exit 0; }
        line="$(ask --inputbox "This erases ALL of $DISK.\n\nType ERASE to continue." 12 60)" || exec "$0"
        [ "$line" = ERASE ] || exec "$0"
    fi
    [ -b "$DISK" ] || fail "$DISK is not a disk."
    clear || true

    say "Erasing $DISK"
    cleanup_mounts
    for p in $(partitions_of "$DISK"); do umount -l "$p" 2>/dev/null || true; done
    wipefs -af "$DISK" >>"$LOG" 2>&1
    sgdisk --zap-all "$DISK" >>"$LOG" 2>&1 || true
    sgdisk -n1:0:+512M -t1:EF00 -c1:HUMINT-EFI -n2:0:0 -t2:8300 -c2:humint-root "$DISK" >>"$LOG" 2>&1 ||
        fail "Could not partition $DISK."
    partprobe "$DISK" >>"$LOG" 2>&1 || true
    udevadm settle
    local parts esp root
    for _ in 1 2 3 4 5 6 7 8 9 10; do
        mapfile -t parts < <(partitions_of "$DISK")
        [ "${#parts[@]}" -ge 2 ] && [ -b "${parts[1]}" ] && break
        sleep 1
    done
    [ "${#parts[@]}" -ge 2 ] || fail "The new partitions on $DISK did not appear."
    esp="${parts[0]}" root="${parts[1]}"

    say "Formatting"
    mkfs.vfat -F 32 -n HUMINT-EFI "$esp" >>"$LOG" 2>&1 || fail "Could not format $esp."
    mkfs.ext4 -F -q -L humint-root "$root" >>"$LOG" 2>&1 || fail "Could not format $root."
    mkdir -p "$TARGET"
    mount "$root" "$TARGET"

    say "Copying the system (a few minutes)"
    local bytes
    bytes="$(du -sbx "$SRC" 2>/dev/null | cut -f1)"
    tar -C "$SRC" --numeric-owner --xattrs --xattrs-include='*' --acls -cf - . |
        pv -f -s "$bytes" -w 70 |
        tar -C "$TARGET" --numeric-owner --xattrs --xattrs-include='*' --acls -xpf - ||
        fail "Copying the system failed (is the disk failing?)."
    mkdir -p "$TARGET/boot/efi"
    mount "$esp" "$TARGET/boot/efi"

    say "Setting up the disk"
    local root_uuid esp_uuid
    root_uuid="$(blkid -s UUID -o value "$root")"
    esp_uuid="$(blkid -s UUID -o value "$esp")"
    cat >"$TARGET/etc/fstab" <<EOF
# Written by the HUMINT installer.
UUID=$root_uuid  /          ext4  errors=remount-ro  0 1
UUID=$esp_uuid   /boot/efi  vfat  umask=0077         0 1
EOF
    : >"$TARGET/etc/machine-id"
    # Started from the troubleshooting entry (boot messages on a serial
    # console)? Then the installed system keeps that console too.
    local consoles
    consoles="$(tr ' ' '\n' </proc/cmdline | grep '^console=' | tr '\n' ' ' || true)"
    if [ -n "$consoles" ]; then
        printf 'GRUB_CMDLINE_LINUX="%s"\n' "${consoles% }" >"$TARGET/etc/default/grub.d/humint-console.cfg"
    fi

    # The optional settings file, put on the stick's boot partition by
    # whoever made it, goes where first boot reads it.
    mkdir -p /mnt/humint-usb-boot
    if mount -o ro LABEL=HUMINT-BOOT /mnt/humint-usb-boot 2>>"$LOG"; then
        if [ -f /mnt/humint-usb-boot/humint-appliance.conf ]; then
            install -m 600 /mnt/humint-usb-boot/humint-appliance.conf "$TARGET/boot/efi/humint-appliance.conf"
            say "Using the settings file from the USB stick"
        fi
        umount /mnt/humint-usb-boot
    fi
    [ -f "$TARGET/boot/efi/humint-appliance.conf.example" ] ||
        install -m 644 "$TARGET/opt/humint/humint-appliance.conf.example" "$TARGET/boot/efi/humint-appliance.conf.example" 2>/dev/null || true

    say "Installing the boot loader"
    for d in dev dev/pts proc sys run; do mount --bind "/$d" "$TARGET/$d"; done
    if [ -d /sys/firmware/efi/efivars ]; then
        mount --bind /sys/firmware/efi/efivars "$TARGET/sys/firmware/efi/efivars" 2>/dev/null || true
    fi
    # --force-extra-removable also writes EFI/BOOT/BOOTX64.EFI, so machines
    # whose firmware forgets boot entries still find it.
    if ! chroot "$TARGET" grub-install --target=x86_64-efi --efi-directory=/boot/efi \
            --bootloader-id=humint --uefi-secure-boot --force-extra-removable >>"$LOG" 2>&1; then
        log "grub-install could not write a boot entry; retrying without one"
        chroot "$TARGET" grub-install --target=x86_64-efi --efi-directory=/boot/efi \
            --bootloader-id=humint --uefi-secure-boot --force-extra-removable --no-nvram >>"$LOG" 2>&1 ||
            fail "Installing the boot loader failed."
    fi
    chroot "$TARGET" update-grub >>"$LOG" 2>&1 || fail "Writing the boot menu failed."
    sync
    cp "$LOG" "$TARGET/var/log/humint-install.log" 2>/dev/null || true
    cleanup_mounts
    sync
    trap - ERR

    say "Installed."
    if [ "$YES" = 1 ]; then
        echo "HUMINT-INSTALL-COMPLETE" >/dev/console 2>/dev/null || true
        grep -qw humint.install.auto /proc/cmdline 2>/dev/null && systemctl poweroff
        return 0
    fi
    whiptail --title "$TITLE" --msgbox "The HUMINT field server is installed on $DISK.\n\nRemove the USB stick, then press Enter to restart. First-time setup (setting the PIN) starts on the screen." 12 70 || true
    systemctl reboot
}

main "$@"
