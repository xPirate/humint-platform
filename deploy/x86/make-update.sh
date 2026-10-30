#!/usr/bin/env bash
# Build a signed update bundle for x86 field servers, from this checkout —
# the x86 counterpart of deploy/pi/make-update.sh, applied the same way.
#
#   deploy/x86/make-update.sh [--out DIR] [--key FILE] [--no-os] [--os-since FILE] [--no-wheels]
#
# The bundle (humint-update-<n>-<commit>-x86.tar) holds:
#   manifest.json      what it is: build, commit, platform "x86", hashes
#   manifest.sig       an Ed25519 signature of manifest.json
#   payload.tar.gz     the console (api, worker, frontend, db), the appliance's
#                      scripts and units (shared with the Pi, then the x86
#                      ones), the native app, and Python wheels for both
#   os-packages.tar    Ubuntu's updated packages — the security fixes — so a
#                      machine that never sees the internet still gets them
#
# OS PACKAGES. By default the bundle carries the newest version of every
# package in the image that Ubuntu has updated since 24.04 was released —
# enough for any machine installed from any image of this release, whatever
# it has had since. That is several hundred MB (kernels and firmware are most
# of it). --os-since FILE carries only what is newer than a list of versions:
# give it the humint-x86-packages.txt an image build leaves in out/ (or the
# humint-os-<n>.txt a previous bundle left) when every machine has at least
# that. --no-os leaves the OS out (a code-only update, small).
#
# A machine with internet can instead fetch Ubuntu's updates itself:
# `sudo humint-ctl os-update`, or Box → Actions → Update the system.
#
# Needs the builder's last image tree (~/humint-x86/rootfs, from build-x86.sh)
# for an Ubuntu 24.04 to fetch with, internet, and root (sudo is used).
# Signed with the same key as the images (~/.config/humint/update-signing.key);
# a machine applies only bundles that key signed, and only x86 ones.
#
# Apply on the machine: a USB stick with the bundle in any folder, then
# Box → Actions → Update from USB (or `sudo humint-ctl update usb`). Through
# the console's upload (Admin → Backup & restore) only bundles under
# MAX_UPDATE_MB (600 MB) fit — use --no-os for those, or the stick.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
OUT="$PWD"
KEY="${HUMINT_SIGNING_KEY:-$HOME/.config/humint/update-signing.key}"
WITH_OS=1
OS_SINCE=""
WHEELS=1
args=("$@")
while [ $# -gt 0 ]; do
    case "$1" in
        --out) OUT="$(cd "$2" && pwd)"; shift 2 ;;
        --key) KEY="$(cd "$(dirname "$2")" && pwd)/$(basename "$2")"; shift 2 ;;
        --no-os) WITH_OS=0; shift ;;
        --os-since) OS_SINCE="$(cd "$(dirname "$2")" && pwd)/$(basename "$2")"; shift 2 ;;
        --no-wheels) WHEELS=0; shift ;;
        --as-root) shift ;;
        -h|--help) sed -n '2,36p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
done
WORK="${HUMINT_X86_DIR:-$HOME/humint-x86}"
ROOTFS="$WORK/rootfs"
# Behind a proxy with its own certificate (as build-x86.sh finds it).
BUILD_CA="${BUILD_CA:-${PIP_CERT:-${SSL_CERT_FILE:-${REQUESTS_CA_BUNDLE:-}}}}"

say() { printf '\033[1m==> %s\033[0m\n' "$*"; }
die() { printf 'make-update: %s\n' "$*" >&2; exit 1; }

[ -f "$KEY" ] || die "No signing key at $KEY — build an image first (build-x86.sh makes one), or pass --key."
[ -n "$OS_SINCE" ] && [ ! -f "$OS_SINCE" ] && die "no such file: $OS_SINCE"

# The chroot (wheels, OS packages) needs root: come back as root, keeping
# where things are. A code-only bundle does not.
if [ "$(id -u)" != 0 ] && { [ "$WHEELS" = 1 ] || [ "$WITH_OS" = 1 ]; }; then
    exec sudo env HUMINT_X86_DIR="$WORK" HUMINT_SIGNING_KEY="$KEY" \
        HTTPS_PROXY="${HTTPS_PROXY:-}" HTTP_PROXY="${HTTP_PROXY:-}" NO_PROXY="${NO_PROXY:-}" \
        BUILD_CA="${BUILD_CA:-}" "$0" --out "$OUT" "${args[@]}"
fi

if [ "$WHEELS" = 1 ] || [ "$WITH_OS" = 1 ]; then
    [ -x "$ROOTFS/usr/bin/apt-get" ] || die "no image tree at $ROOTFS — run build-x86.sh once first (or --no-os --no-wheels)"
fi

STAGE="$(mktemp -d)"
mounted=()
cleanup() {
    local i
    for ((i = ${#mounted[@]} - 1; i >= 0; i--)); do umount -l "${mounted[$i]}" 2>/dev/null || true; done
    rm -rf "$ROOTFS/var/tmp/humint-bundle" "$STAGE"
}
trap cleanup EXIT

count="$(git -C "$REPO" rev-list --count HEAD)"
commit="$(git -C "$REPO" rev-parse --short=10 HEAD)"
dirty=""
git -C "$REPO" diff --quiet HEAD -- api worker frontend db native deploy || dirty="-dirty"

say "Collecting build $count ($commit$dirty) for x86"
P="$STAGE/payload"
mkdir -p "$P/app" "$P/overlay"
for part in api worker frontend db; do
    rsync -a --exclude __pycache__ "$REPO/$part/" "$P/app/$part/"
done
cp "$REPO/.env.example" "$P/app/.env.example"
# The appliance: the scripts and units shared with the Pi, then the x86 ones
# over them — as build-x86.sh lays them into the image.
PI_FILES="$REPO/deploy/pi/stage-humint/03-overlay/files"
rsync -a --exclude __pycache__ "$PI_FILES/opt/" "$P/overlay/opt/"
rsync -a "$PI_FILES/etc/" "$P/overlay/etc/"
rsync -a --exclude __pycache__ "$HERE/files/opt/" "$P/overlay/opt/"
rsync -a "$HERE/files/etc/" "$P/overlay/etc/"
rm -f "$P/overlay/etc/systemd/system/"humint-{status,display,panel}.service
rm -f "$P/overlay/opt/humint/update-signing.pub"
# The image's package lists (as build-x86.sh writes them), for os-update.
grep -v '^\s*#' "$HERE/packages" | awk 'NF {print $1}' | sort -u >"$P/overlay/opt/humint/os-packages.txt"
sed -n '/^# ---- added after the first images/,$p' "$HERE/packages" | grep -v '^\s*#' | awk 'NF {print $1}' \
    >"$P/overlay/opt/humint/os-added.txt"
# The machine's own screen.
rsync -a --exclude __pycache__ --exclude tools "$REPO/native/" "$P/native/"

req_hash="$(cat "$REPO/api/requirements.txt" "$REPO/worker/requirements.txt" | sha256sum | cut -d' ' -f1)"
native_hash="$(sha256sum "$REPO/native/requirements.txt" | cut -d' ' -f1)"

# ---- inside the builder's Ubuntu 24.04 -----------------------------------------------
in_rootfs() {
    local ca=()
    [ -f "$ROOTFS/tmp/build-ca.crt" ] && ca=(PIP_CERT=/tmp/build-ca.crt SSL_CERT_FILE=/tmp/build-ca.crt)
    chroot "$ROOTFS" /usr/bin/env -i HOME=/root PATH=/usr/sbin:/usr/bin:/sbin:/bin \
        DEBIAN_FRONTEND=noninteractive LC_ALL=C.UTF-8 "${ca[@]}" \
        HTTPS_PROXY="${HTTPS_PROXY:-}" HTTP_PROXY="${HTTP_PROXY:-}" NO_PROXY="${NO_PROXY:-}" \
        /bin/bash -euo pipefail -c "$1"
}
if [ "$WHEELS" = 1 ] || [ "$WITH_OS" = 1 ]; then
    for m in proc sys dev dev/pts; do
        case "$m" in
            proc) mount -t proc proc "$ROOTFS/proc" ;;
            sys) mount -t sysfs sys "$ROOTFS/sys" ;;
            *) mount --bind "/$m" "$ROOTFS/$m" ;;
        esac
        mounted+=("$ROOTFS/$m")
    done
    cp /etc/resolv.conf "$ROOTFS/etc/resolv.conf"
    if [ -n "${BUILD_CA:-}" ] && [ -f "$BUILD_CA" ]; then install -m 644 "$BUILD_CA" "$ROOTFS/tmp/build-ca.crt"; fi
    B="$ROOTFS/var/tmp/humint-bundle"
    mkdir -p "$B/req" "$B/wheels" "$B/native-wheels" "$B/debs" "$B/lists/partial" "$B/archives/partial" "$WORK/pip-cache"
    mkdir -p "$ROOTFS/var/cache/humint-pip"
    mount --bind "$WORK/pip-cache" "$ROOTFS/var/cache/humint-pip"; mounted+=("$ROOTFS/var/cache/humint-pip")
fi

wheels=False native_wheels=False
if [ "$WHEELS" = 1 ]; then
    say "Python wheels for x86 (Ubuntu 24.04, Python 3.12)"
    cp "$REPO/api/requirements.txt" "$B/req/api.txt"
    cp "$REPO/worker/requirements.txt" "$B/req/worker.txt"
    cp "$REPO/native/requirements.txt" "$B/req/native.txt"
    in_rootfs "
        /opt/humint/venv/bin/pip wheel -q --cache-dir /var/cache/humint-pip -w /var/tmp/humint-bundle/wheels \
            -r /var/tmp/humint-bundle/req/api.txt -r /var/tmp/humint-bundle/req/worker.txt
        /opt/humint/ui-venv/bin/pip wheel -q --cache-dir /var/cache/humint-pip -w /var/tmp/humint-bundle/native-wheels \
            -r /var/tmp/humint-bundle/req/native.txt
    " || die "fetching the Python wheels failed"
    cp -a "$B/wheels" "$P/wheels"
    cp -a "$B/native-wheels" "$P/native-wheels"
    wheels=True native_wheels=True
else
    echo "  (--no-wheels: a machine refuses this bundle if its Python requirements differ from what it has)"
fi

os_sha="" os_count=0
if [ "$WITH_OS" = 1 ]; then
    say "Ubuntu's updated packages (the security fixes)"
    [ -n "$OS_SINCE" ] && cp "$OS_SINCE" "$B/since.txt"
    # Packages added after the first images: carried whole (with what they
    # need), so a machine installed before gets them — see deploy/x86/packages.
    sed -n '/^# ---- added after the first images/,$p' "$HERE/packages" | grep -v '^\s*#' | awk 'NF {print $1}' \
        >"$B/added.txt"
    # Apt's lists and downloads kept apart from the image tree's own, so the
    # next image build is not changed by this.
    # shellcheck disable=SC2016  # expanded inside the chroot
    in_rootfs '
        B=/var/tmp/humint-bundle
        apt=(apt-get -q -o Dir::State::Lists=$B/lists -o Dir::Cache::Archives=$B/archives -o APT::Sandbox::User=root)
        "${apt[@]}" update >/dev/null
        since=(); [ -f $B/since.txt ] && since=($B/since.txt)
        : >$B/pick.txt
        # Every package in the image whose newest version is not the one 24.04
        # shipped (or that only the updates carry: each new kernel is a new
        # package) — less anything a --os-since list already has.
        dpkg-query -W -f "\${Package}\n" | while read -r p; do
            pol="$(apt-cache -o Dir::State::Lists=$B/lists policy "$p" 2>/dev/null)"
            cand="$(printf "%s\n" "$pol" | awk "/Candidate:/ {print \$2; exit}")"
            [ -n "$cand" ] && [ "$cand" != "(none)" ] || continue
            rel="$(apt-cache -o Dir::State::Lists=$B/lists madison "$p" 2>/dev/null |
                   awk "/ noble\/(main|restricted|universe|multiverse) amd64 Packages/ {print \$3; exit}")"
            [ "$rel" = "$cand" ] && continue
            if [ ${#since[@]} -gt 0 ] && grep -qx "$p $cand" "${since[0]}"; then continue; fi
            echo "$p=$cand" >>$B/pick.txt
        done
        # The added packages, and everything they depend on that is not part
        # of every Ubuntu system (priority required/important).
        if [ -s $B/added.txt ]; then
            apt-cache -o Dir::State::Lists=$B/lists depends --recurse --no-recommends --no-suggests \
                --no-conflicts --no-breaks --no-replaces --no-enhances $(cat $B/added.txt) 2>/dev/null |
                awk "/^[a-z0-9]/ {print \$1}" | sort -u | while read -r p; do
                    prio="$(apt-cache -o Dir::State::Lists=$B/lists show --no-all-versions "$p" 2>/dev/null |
                            awk "/^Priority:/ {print \$2; exit}")"
                    [ -n "$prio" ] || continue                  # virtual
                    case "$prio" in required|important) continue ;; esac
                    grep -q "^$p=" $B/pick.txt || grep -qx "$p" $B/pick.txt || echo "$p" >>$B/pick.txt
                done
        fi
        # And anything those now depend on that the image lacks.
        if [ -s $B/pick.txt ]; then
            "${apt[@]}" -s install --no-install-recommends $(cat $B/pick.txt) 2>/dev/null |
                awk "/^Inst / {print \$2}" | while read -r p; do
                    grep -q "^$p=" $B/pick.txt || echo "$p" >>$B/pick.txt
                done
            cd $B/debs
            "${apt[@]}" download $(cat $B/pick.txt) >/dev/null
            dpkg-scanpackages --multiversion . /dev/null 2>/dev/null | gzip -9 >Packages.gz
        fi
        dpkg-query -W -f "\${Package} \${Version}\n" >$B/image.txt
    ' || die "fetching the system packages failed"
    os_count="$(find "$B/debs" -name '*.deb' | wc -l)"
    if [ "$os_count" -gt 0 ]; then
        tar -C "$B/debs" -cf "$STAGE/os-packages.tar" .
        os_sha="$(sha256sum "$STAGE/os-packages.tar" | cut -d' ' -f1)"
        echo "  $os_count packages, $(du -h "$STAGE/os-packages.tar" | cut -f1)"
    else
        echo "  nothing newer than what was asked for — no system packages in this bundle"
    fi
    # What this bundle carries, for the next one's --os-since.
    ( cd "$B/debs" && for f in *.deb; do [ -e "$f" ] && dpkg-deb -f "$f" Package Version | paste -sd' '; done ) \
        >"$OUT/humint-os-$count.txt" 2>/dev/null || true
fi

migrations="$(cd "$REPO/db" && ls migrate-v*.sql | sort -V | python3 -c 'import json,sys; print(json.dumps([l.strip() for l in sys.stdin if l.strip()]))')"

say "Packing"
tar -C "$P" -czf "$STAGE/payload.tar.gz" .
sha="$(sha256sum "$STAGE/payload.tar.gz" | cut -d' ' -f1)"
python3 - "$STAGE/manifest.json" <<PY
import json, os, sys, time
m = {
    "format": "humint-field-update", "format_version": 1,
    "platform": "x86",
    "build": $count, "commit": "$commit$dirty",
    "created": int(time.time()),
    "payload_sha256": "$sha",
    "requirements_sha256": "$req_hash",
    "wheels": $wheels,
    "native_requirements_sha256": "$native_hash",
    "native_wheels": $native_wheels,
    "migrations": $migrations,
}
if "$os_sha":
    m.update(os_sha256="$os_sha", os_packages=$os_count,
             os_added=" ".join(open("${B:-}/added.txt").read().split()) if os.path.exists("${B:-}/added.txt") else "")
json.dump(m, open(sys.argv[1], "w"), indent=1)
PY
openssl pkeyutl -sign -inkey "$KEY" -rawin -in "$STAGE/manifest.json" -out "$STAGE/manifest.sig"

name="humint-update-${count}-${commit}${dirty}-x86.tar"
members=(manifest.json manifest.sig payload.tar.gz)
[ -n "$os_sha" ] && members+=(os-packages.tar)
tar -C "$STAGE" -cf "$OUT/$name" "${members[@]}"
[ -n "${SUDO_UID:-}" ] && chown "$SUDO_UID:${SUDO_GID:-$SUDO_UID}" "$OUT/$name" "$OUT/humint-os-$count.txt" 2>/dev/null || true
say "Done: $OUT/$name ($(du -h "$OUT/$name" | cut -f1))"
echo "  Put it on a USB stick (any folder), then on the machine: Box → Actions → Update from USB."
