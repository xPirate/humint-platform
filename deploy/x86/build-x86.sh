#!/usr/bin/env bash
# Build the HUMINT field server for x86 laptops and mini PCs: a USB stick
# image that installs it, with no network needed on the machine.
#
#   git clone https://github.com/xPirate/humint-platform
#   humint-platform/deploy/x86/build-x86.sh
#
# Run it on any 64-bit x86 Debian or Ubuntu machine with internet access and
# ~25 GB free. The result is out/humint-x86-installer.img.xz: write it to a
# USB stick (Raspberry Pi Imager → "Use custom", balenaEtcher, Rufus, dd),
# boot the laptop from the stick, choose the disk, type ERASE. It installs
# Ubuntu 24.04 LTS with the field server — the same appliance as the Pi
# (encrypted case file, PIN, duress, hotspot, signed updates) — and restarts
# into first-time setup.
#
# Options:
#   --clean       rebuild the base system from scratch (otherwise it is
#                 reused while the package list is unchanged)
#   --no-tmux     do not wrap the build in tmux when on SSH
#   --no-compress leave out/humint-x86-installer.img uncompressed (tests)
#   --quick       reuse the last build's system and only refresh the code,
#                 scripts and app in it (for changes to those; a change to
#                 Python requirements or packages needs a full build)
#   HUMINT_X86_DIR=...   where the build goes (default ~/humint-x86)
#   UBUNTU_MIRROR=...    package mirror (default archive.ubuntu.com)
set -euo pipefail

CLEAN=0 USE_TMUX=1 COMPRESS=1 AS_ROOT=0 QUICK=0
ARGS=("$@")
for a in "$@"; do
    case "$a" in
        --clean) CLEAN=1 ;;
        --no-tmux) USE_TMUX=0 ;;
        --no-compress) COMPRESS=0 ;;
        --quick) QUICK=1 ;;
        --as-root) AS_ROOT=1 ;;
        -h|--help) sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $a (see --help)" >&2; exit 2 ;;
    esac
done

HERE="$(cd "$(dirname "$0")" && pwd)"
SELF="$HERE/$(basename "$0")"
REPO="$(cd "$HERE/../.." && pwd)"
PI_FILES="$REPO/deploy/pi/stage-humint/03-overlay/files"
SUITE=noble
MIRROR="${UBUNTU_MIRROR:-http://archive.ubuntu.com/ubuntu}"
SESSION=humint-x86-build

say()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
warn() { printf '  !! %s\n' "$*" >&2; }
die()  { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

# =============================================================================
# Part 1 — as you: tools, password, signing key. Then the rest runs as root.
# =============================================================================
if [ "$AS_ROOT" = 0 ]; then
    [ "$(uname -m)" = x86_64 ] || die "build this on a 64-bit x86 machine (this is $(uname -m))"
    command -v apt-get >/dev/null || die "this needs a Debian-based system (Debian, Ubuntu)"
    WORK="${HUMINT_X86_DIR:-$HOME/humint-x86}"
    SUDO=""; [ "$(id -u)" -eq 0 ] || SUDO=sudo

    say "Installing the build tools${SUDO:+ (sudo may ask for your password)}"
    $SUDO apt-get update -qq
    keyring=ubuntu-keyring
    grep -qi '^ID=ubuntu' /etc/os-release || keyring=ubuntu-archive-keyring
    $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
        debootstrap "$keyring" squashfs-tools dosfstools mtools gdisk e2fsprogs rsync \
        xz-utils openssl tmux curl git >/dev/null

    if [ "$USE_TMUX" = 1 ] && [ -z "${TMUX:-}" ] && [ -n "${SSH_CONNECTION:-}" ]; then
        if tmux has-session -t "$SESSION" 2>/dev/null; then exec tmux attach -t "$SESSION"; fi
        say "Continuing inside tmux (session '$SESSION') so a dropped SSH connection doesn't stop the build"
        echo "  Detach: Ctrl-b then d.   Reattach later: tmux attach -t $SESSION"
        sleep 2
        exec tmux new-session -s "$SESSION" \
            "$(printf '%q ' "$SELF" "${ARGS[@]}") --no-tmux; echo; echo 'Press Enter to close.'; read -r _"
    fi

    mkdir -p "$WORK"
    free_gb=$(df -Pk "$WORK" | awk 'NR==2 {print int($4/1048576)}')
    [ "$free_gb" -ge 15 ] || die "only ${free_gb} GB free in $WORK; the build needs about 15 GB (25 GB to keep a few builds around)"

    CONF="$WORK/build.conf"
    if [ ! -f "$CONF" ]; then
        say "Choose the password for the 'humint' login on installed machines"
        echo "  (SSH and keyboard login until first boot — which replaces it with one of the machine's own"
        echo "   and shows it on screen. Not the PIN.)"
        while :; do
            read -r -s -p "  Password: " p1; echo
            read -r -s -p "  Again:    " p2; echo
            if [ "${#p1}" -lt 8 ]; then echo "  Use at least 8 characters."
            elif [ "$p1" != "$p2" ]; then echo "  They don't match — try again."
            else break; fi
        done
        tz="$(timedatectl show -p Timezone --value 2>/dev/null || cat /etc/timezone 2>/dev/null || echo Etc/UTC)"
        ( umask 077
          printf 'LOGIN_HASH=%q\nTIMEZONE_DEFAULT=%q\n' "$(openssl passwd -6 -stdin <<<"$p1")" "${tz:-Etc/UTC}" >"$CONF" )
        unset p1 p2
        echo "  Saved (hashed) in $CONF; delete it to choose again."
    fi

    KEY="${HUMINT_SIGNING_KEY:-$HOME/.config/humint/update-signing.key}"
    if [ ! -f "$KEY" ]; then
        say "Creating the update-signing key ($KEY)"
        install -d -m 700 "$(dirname "$KEY")"
        ( umask 077; openssl genpkey -algorithm ed25519 -out "$KEY" )
        echo "  Machines built here accept only updates signed with it. Back it up somewhere safe."
    fi
    openssl pkey -in "$KEY" -pubout -out "$WORK/update-signing.pub"

    # What this build is, for the update system (as prepare-pigen.sh does).
    python3 - "$WORK/BUILD.json" "$REPO" <<'PY'
import json, subprocess, sys, time, hashlib
repo = sys.argv[2]
git = lambda *a: subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True).stdout.strip()
req = b"".join(open(f"{repo}/{p}/requirements.txt", "rb").read() for p in ("api", "worker"))
json.dump({"build": int(git("rev-list", "--count", "HEAD") or 0), "commit": git("rev-parse", "--short=10", "HEAD"),
           "requirements_sha256": hashlib.sha256(req).hexdigest(), "platform": "x86_64",
           "installed": int(time.time())}, open(sys.argv[1], "w"), indent=1)
PY

    # A builder behind a proxy (or one that inspects HTTPS) passes its
    # settings on to the image build's downloads.
    ca="${PIP_CERT:-${SSL_CERT_FILE:-${REQUESTS_CA_BUNDLE:-}}}"
    exec $SUDO env HUMINT_X86_DIR="$WORK" UBUNTU_MIRROR="$MIRROR" BUILD_CA="$ca" \
        HTTPS_PROXY="${HTTPS_PROXY:-${https_proxy:-}}" HTTP_PROXY="${HTTP_PROXY:-${http_proxy:-}}" \
        NO_PROXY="${NO_PROXY:-${no_proxy:-}}" "$SELF" "${ARGS[@]}" --as-root
fi

# =============================================================================
# Part 2 — as root: the system, the app, the installer stick
# =============================================================================
[ "$(id -u)" -eq 0 ] || die "--as-root is internal"
WORK="${HUMINT_X86_DIR:?}"
BASE="$WORK/base"          # Ubuntu + packages (cached)
ROOT="$WORK/rootfs"        # this build's system
OUT="$WORK/out"
# shellcheck disable=SC1091
. "$WORK/build.conf"
PKGS="$(grep -v '^\s*#' "$HERE/packages" | awk 'NF {print $1}' | sort -u | tr '\n' ' ')"
PKGS_HASH="$(printf '%s %s' "$SUITE" "$PKGS" | sha256sum | cut -c1-16)"

mounted=()
chroot_mount() {   # chroot_mount DIR — /proc, /sys, /dev for a chroot
    local d="$1"
    for m in proc sys dev dev/pts; do
        mkdir -p "$d/$m"
        case "$m" in
            proc) mount -t proc proc "$d/proc" ;;
            sys) mount -t sysfs sys "$d/sys" ;;
            *) mount --bind "/$m" "$d/$m" ;;
        esac
        mounted+=("$d/$m")
    done
}
unmount_all() {
    local i
    for ((i=${#mounted[@]}-1; i>=0; i--)); do umount -l "${mounted[$i]}" 2>/dev/null || true; done
    mounted=()
    [ -n "${LOOPDEV:-}" ] && losetup -d "$LOOPDEV" 2>/dev/null || true
}
trap unmount_all EXIT
# The builder's HTTPS certificate authority, if it set one (see part 1).
copy_build_ca() {
    if [ -n "${BUILD_CA:-}" ] && [ -f "$BUILD_CA" ]; then install -m 644 "$BUILD_CA" "$1/tmp/build-ca.crt"; fi
}
in_root() {
    local ca=()
    [ -f "$1/tmp/build-ca.crt" ] && ca=(PIP_CERT=/tmp/build-ca.crt SSL_CERT_FILE=/tmp/build-ca.crt)
    chroot "$1" /usr/bin/env -i HOME=/root PATH=/usr/sbin:/usr/bin:/sbin:/bin \
        DEBIAN_FRONTEND=noninteractive LC_ALL=C.UTF-8 "${ca[@]}" \
        HTTPS_PROXY="${HTTPS_PROXY:-}" HTTP_PROXY="${HTTP_PROXY:-}" NO_PROXY="${NO_PROXY:-}" \
        /bin/bash -euo pipefail -c "$2"
}

# ---- 1. the base system --------------------------------------------------------
if [ "$CLEAN" = 1 ] || [ "$(cat "$BASE/.humint-base" 2>/dev/null)" != "$PKGS_HASH" ]; then
    say "Building the base system: Ubuntu 24.04 LTS + packages (20–40 minutes; cached for later builds)"
    rm -rf "$BASE"
    debootstrap --variant=minbase --arch=amd64 --components=main,restricted,universe,multiverse \
        "$SUITE" "$BASE" "$MIRROR" || die "debootstrap failed (see $BASE/debootstrap/debootstrap.log)"
    cat >"$BASE/etc/apt/sources.list" <<EOF
deb $MIRROR $SUITE main restricted universe multiverse
deb $MIRROR $SUITE-updates main restricted universe multiverse
deb $MIRROR $SUITE-security main restricted universe multiverse
EOF
    # No snaps, nothing that phones home, no services starting in the chroot.
    cat >"$BASE/etc/apt/preferences.d/humint-no-snap" <<'EOF'
Package: snapd ubuntu-advantage-tools ubuntu-pro-client cloud-init
Pin: release *
Pin-Priority: -1
EOF
    printf '#!/bin/sh\nexit 101\n' >"$BASE/usr/sbin/policy-rc.d"; chmod 755 "$BASE/usr/sbin/policy-rc.d"
    printf 'APT::Install-Recommends "false";\nAPT::Install-Suggests "false";\n' >"$BASE/etc/apt/apt.conf.d/90humint"
    chroot_mount "$BASE"
    in_root "$BASE" "
        echo 'grub-efi-amd64 grub2/update_nvram boolean false' | debconf-set-selections
        echo 'grub-efi-amd64-signed grub2/update_nvram boolean false' | debconf-set-selections
        apt-get update -qq
        apt-get -y -qq dist-upgrade >/dev/null
        apt-get install -y -qq $PKGS
        apt-get clean
    " || die "installing packages failed"
    unmount_all
    echo "$PKGS_HASH" >"$BASE/.humint-base"
else
    say "Reusing the base system (package list unchanged; --clean rebuilds it)"
fi

# ---- 2. this build's system: base + app + appliance files -----------------------------
if [ "$QUICK" = 1 ] && [ -d "$ROOT/opt/humint/ui-venv" ]; then
    say "Reusing the last build's system (--quick): refreshing the code and the app"
else
    QUICK=0
    say "Copying the base system"
    rm -rf "$ROOT"
    mkdir -p "$ROOT"
    rsync -aHAX "$BASE/" "$ROOT/"
fi
chroot_mount "$ROOT"
cp /etc/resolv.conf "$ROOT/etc/resolv.conf"
copy_build_ca "$ROOT"
# Python packages are cached between builds, outside the image.
mkdir -p "$WORK/pip-cache" "$ROOT/var/cache/humint-pip"
mount --bind "$WORK/pip-cache" "$ROOT/var/cache/humint-pip"; mounted+=("$ROOT/var/cache/humint-pip")

say "Installing the console (API, worker, frontend)"
install -d "$ROOT/opt/humint-platform"
for part in api worker frontend db; do
    rsync -a --delete --exclude '__pycache__' "$REPO/$part/" "$ROOT/opt/humint-platform/$part/"
done
install -m 644 "$REPO/.env.example" "$ROOT/opt/humint-platform/.env.example"
install -m 644 "$WORK/BUILD.json" "$ROOT/opt/humint-platform/BUILD.json"
[ "$QUICK" = 1 ] || in_root "$ROOT" "
    id humintd >/dev/null 2>&1 || adduser --system --group --home /var/lib/humintd --no-create-home humintd
    python3 -m venv /opt/humint/venv
    /opt/humint/venv/bin/pip install -q --cache-dir /var/cache/humint-pip --upgrade pip wheel
    /opt/humint/venv/bin/pip install -q --cache-dir /var/cache/humint-pip \
        -r /opt/humint-platform/api/requirements.txt -r /opt/humint-platform/worker/requirements.txt
    /opt/humint/venv/bin/python -m compileall -q /opt/humint-platform/api /opt/humint-platform/worker || true
" || die "installing the console's Python packages failed"
say "Installing the native app (the machine's own screen)"
rsync -a --delete --exclude '__pycache__' --exclude 'tools' "$REPO/native/" "$ROOT/opt/humint/native/"
[ "$QUICK" = 1 ] || in_root "$ROOT" "
    getent group humint-ui >/dev/null || groupadd --system humint-ui
    id humint-ui >/dev/null 2>&1 || useradd --system --gid humint-ui --groups video,render,input \
        --home-dir /var/lib/humint-ui --create-home --shell /usr/sbin/nologin humint-ui
    python3 -m venv /opt/humint/ui-venv
    /opt/humint/ui-venv/bin/pip install -q --cache-dir /var/cache/humint-pip --upgrade pip
    /opt/humint/ui-venv/bin/pip install -q --cache-dir /var/cache/humint-pip -r /opt/humint/native/requirements.txt
    /opt/humint/ui-venv/bin/python -m compileall -q /opt/humint/native || true
" || die "installing the native app failed"
date +%s >"$ROOT/opt/humint/build-epoch"
# Which kind of machine: update bundles are made for one or the other.
echo x86 >"$ROOT/opt/humint/platform"
install -d -m 755 "$ROOT/var/lib/humint"
( cd "$REPO/db" && ls migrate-v*.sql 2>/dev/null | sort -V ) >"$ROOT/var/lib/humint/migrations-applied"

say "Laying in the appliance (shared with the Pi) and the x86 parts"
rsync -a --exclude '__pycache__' "$PI_FILES/opt/" "$ROOT/opt/"
rsync -a "$PI_FILES/etc/" "$ROOT/etc/"
rsync -a --exclude '__pycache__' "$HERE/files/" "$ROOT/"
install -m 644 "$HERE/humint-appliance.conf.example" "$ROOT/opt/humint/humint-appliance.conf.example"
install -m 644 "$WORK/update-signing.pub" "$ROOT/opt/humint/update-signing.pub"
chmod 0755 "$ROOT"/opt/humint/bin/*.sh "$ROOT"/opt/humint/bin/*.py "$ROOT"/opt/humint/bin/humint-ctl \
    "$ROOT"/opt/humint/bin/humint-api-run "$ROOT"/opt/humint/bin/humint-unlock-try \
    "$ROOT"/etc/initramfs-tools/hooks/humint-live "$ROOT"/opt/humint/bin/humint-install.sh "$ROOT"/opt/humint/bin/humint-ui-launch
chown root:root "$ROOT"/etc/NetworkManager/dispatcher.d/90-humint-tls
chmod 0755 "$ROOT"/etc/NetworkManager/dispatcher.d/90-humint-tls
ln -sf /opt/humint/bin/humint-ctl "$ROOT/usr/local/bin/humint-ctl"
install -d "$ROOT/srv/humint-data" "$ROOT/boot/efi"
# The scripts (shared with the Pi) read their settings from /boot/firmware;
# here that is the EFI partition, which any computer can open too.
rm -rf "$ROOT/boot/firmware"; ln -s efi "$ROOT/boot/firmware"
# Pi-only pieces: the OLED, its screen finder and the framebuffer panel.
rm -f "$ROOT"/etc/systemd/system/humint-{status,display,panel}.service

say "Settings, accounts and services"
in_root "$ROOT" "
    echo humint >/etc/hostname
    printf '127.0.0.1 localhost\n127.0.1.1 humint\n::1 localhost ip6-localhost ip6-loopback\n' >/etc/hosts
    ln -sf /usr/share/zoneinfo/${TIMEZONE_DEFAULT:-Etc/UTC} /etc/localtime
    echo ${TIMEZONE_DEFAULT:-Etc/UTC} >/etc/timezone
    printf 'LANG=C.UTF-8\n' >/etc/default/locale
    id humint >/dev/null 2>&1 || useradd -m -u 1000 -s /bin/bash -G sudo,adm humint
    usermod -p '$LOGIN_HASH' humint
    : >/etc/fstab
    for u in NetworkManager avahi-daemon ssh humint-ssh-hostkeys humint-firstboot humint-unlock \
             humint-battery humint-clock humint-installer humint-boxd humint-ui; do
        systemctl enable \$u.service >/dev/null
    done
    systemctl enable humint-update-inbox.path >/dev/null
    systemctl disable postgresql.service >/dev/null 2>&1 || true
    if pg_lsclusters -h | awk '{print \$1\" \"\$2}' | grep -q '^16 main\$'; then pg_dropcluster 16 main; fi
"
# On the installer stick, nothing of the field server runs — only the installer.
for unit in humint-firstboot.service humint-unlock.service humint-battery.service humint-clock.service \
            humint-update-inbox.path humint-ssh-hostkeys.service humint-boxd.service humint-ui.service \
            ssh.service ssh.socket; do
    install -d "$ROOT/etc/systemd/system/$unit.d"
    printf '[Unit]\nConditionKernelCommandLine=!humint.install\n' >"$ROOT/etc/systemd/system/$unit.d/x86-installer.conf"
done

say "Boot files"
in_root "$ROOT" "
    update-initramfs -u -k all >/dev/null
"
rm -f "$ROOT"/etc/ssh/ssh_host_* "$ROOT/usr/sbin/policy-rc.d"
: >"$ROOT/etc/machine-id"
rm -f "$ROOT/var/lib/dbus/machine-id"
# NetworkManager writes it from the network in use (see its conf.d/90-humint-dns.conf).
rm -f "$ROOT/etc/resolv.conf"
printf '# Written by NetworkManager.\n' >"$ROOT/etc/resolv.conf"
rm -rf "$ROOT"/var/cache/apt/archives/*.deb "$ROOT"/var/lib/apt/lists/* "$ROOT"/tmp/* "$ROOT"/root/.cache
unmount_all

# ---- 3. the installer stick ---------------------------------------------------------
say "Packing the system image"
mkdir -p "$OUT"
# The image's package versions: give this to make-update.sh --os-since, once
# every machine has at least this image, to carry only what is newer.
dpkg-query --admindir="$ROOT/var/lib/dpkg" -W -f '${Package} ${Version}\n' >"$OUT/humint-x86-packages.txt"
rm -f "$OUT/rootfs.squashfs"
mksquashfs "$ROOT" "$OUT/rootfs.squashfs" -comp zstd -Xcompression-level 15 -noappend -quiet \
    -wildcards -e 'proc/*' 'sys/*' 'dev/*' 'run/*' 'tmp/*' >/dev/null
sq_mb=$(( $(stat -c %s "$OUT/rootfs.squashfs") / 1048576 ))

say "Making the USB stick image (${sq_mb} MB system)"
# Both partitions are built as plain files and spliced into the image: no
# mounting and no loop devices, so this works in a container or CI too.
STICK="$WORK/stick"
MNT="$STICK"
rm -rf "$STICK"
mkdir -p "$STICK/boot" "$STICK/usb/humint"

# Secure Boot chain: Microsoft-signed shim → Canonical-signed GRUB →
# Canonical-signed kernel, all from the image itself.
shim="$ROOT/usr/lib/shim/shimx64.efi.signed.latest"
[ -f "$shim" ] || shim="$ROOT/usr/lib/shim/shimx64.efi.signed"
install -d "$MNT/boot/EFI/BOOT" "$MNT/boot/EFI/ubuntu" "$MNT/boot/boot/grub" "$MNT/boot/.disk" "$MNT/boot/humint"
install -m 644 "$shim" "$MNT/boot/EFI/BOOT/BOOTX64.EFI"
install -m 644 "$ROOT/usr/lib/grub/x86_64-efi-signed/grubx64.efi.signed" "$MNT/boot/EFI/BOOT/grubx64.efi"
install -m 644 "$ROOT/usr/lib/shim/mmx64.efi" "$MNT/boot/EFI/BOOT/mmx64.efi"
kernel="$(readlink -f "$ROOT/boot/vmlinuz")"; initrd="$(readlink -f "$ROOT/boot/initrd.img")"
install -m 644 "$kernel" "$MNT/boot/humint/vmlinuz"
install -m 644 "$initrd" "$MNT/boot/humint/initrd.img"
echo "HUMINT field server installer" >"$MNT/boot/.disk/info"
cat >"$WORK/grub.cfg" <<'EOF'
set timeout=5
set default=0
insmod all_video
search --no-floppy --set=root --label HUMINT-BOOT
menuentry "Install the HUMINT field server on this computer" {
    linux /humint/vmlinuz boot=humint humint.live=HUMINT-USB humint.install quiet loglevel=3 net.ifnames=0
    initrd /humint/initrd.img
}
menuentry "Install (show boot messages, for troubleshooting)" {
    linux /humint/vmlinuz boot=humint humint.live=HUMINT-USB humint.install net.ifnames=0 console=tty0 console=ttyS0,115200
    initrd /humint/initrd.img
}
menuentry "Firmware settings (UEFI)" {
    fwsetup
}
EOF
# Signed GRUB looks in a few places depending on how it was started; be in all.
for d in EFI/BOOT EFI/ubuntu boot/grub; do install -m 644 "$WORK/grub.cfg" "$MNT/boot/$d/grub.cfg"; done
install -m 644 "$HERE/humint-appliance.conf.example" "$MNT/boot/humint-appliance.conf.example"
cat >"$MNT/boot/README.txt" <<'EOF'
HUMINT field server installer

Optional: copy humint-appliance.conf.example to humint-appliance.conf on
this drive and edit it (Wi-Fi country, hotspot name and password, time zone,
SSH key...). The installer copies it onto the machine; without it, first
boot picks safe defaults and shows the hotspot password on screen.

Boot the laptop from this stick (UEFI; Secure Boot can stay on), choose
the disk, type ERASE. Everything on that disk is replaced.
EOF
mv "$OUT/rootfs.squashfs" "$STICK/usb/humint/rootfs.squashfs"

ESP_MB=300
rm -f "$WORK/esp.img" "$WORK/usb.img"
truncate -s "${ESP_MB}M" "$WORK/esp.img"
mkfs.vfat -F 32 -n HUMINT-BOOT "$WORK/esp.img" >/dev/null
for entry in "$STICK/boot/"* "$STICK/boot/.disk"; do
    mcopy -s -o -i "$WORK/esp.img" "$entry" ::/
done
usb_mb=$(( $(du -sm "$STICK/usb" | cut -f1) * 105 / 100 + 64 ))
truncate -s "${usb_mb}M" "$WORK/usb.img"
mkfs.ext4 -q -F -L HUMINT-USB -m 0 -d "$STICK/usb" "$WORK/usb.img"

IMG="$OUT/humint-x86-installer.img"
rm -f "$IMG" "$IMG.xz"
truncate -s "$(( 1 + ESP_MB + usb_mb + 2 ))M" "$IMG"
sgdisk -n1:2048:+${ESP_MB}M -t1:EF00 -c1:HUMINT-BOOT \
       -n2:0:+${usb_mb}M -t2:8300 -c2:HUMINT-USB "$IMG" >/dev/null
first_sector() { sgdisk -i "$1" "$IMG" | awk '/^First sector/ {print $3}'; }
dd if="$WORK/esp.img" of="$IMG" bs=1M oflag=seek_bytes seek="$(( $(first_sector 1) * 512 ))" \
    conv=notrunc,sparse status=none
dd if="$WORK/usb.img" of="$IMG" bs=4M oflag=seek_bytes seek="$(( $(first_sector 2) * 512 ))" \
    conv=notrunc,sparse status=none
rm -rf "$WORK/esp.img" "$WORK/usb.img" "${STICK:?}"
sync

if [ "$COMPRESS" = 1 ]; then
    say "Compressing"
    xz -T0 -3 -f "$IMG"
    IMG="$IMG.xz"
fi

say "Done."
ls -lh "$IMG" | awk '{print "  " $5 "  " $9}'
cat <<EOF

  Copy it to your Mac, from the Mac's Terminal:
    scp '${SUDO_USER:-$(id -un)}@$(hostname).local:$IMG' ~/Downloads/
  Write it to a USB stick (8 GB or larger) with Raspberry Pi Imager → "Use custom",
  then boot the laptop from it (usually F12, F11, Esc or F7 at power-on).
EOF
