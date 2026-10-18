#!/usr/bin/env bash
# Build the HUMINT field-server image, start to finish, on a builder Pi
# (64-bit Raspberry Pi OS) or any Debian/Ubuntu machine.
#
#   git clone https://github.com/xPirate/humint-platform
#   humint-platform/deploy/pi/build-image.sh
#
# It installs pi-gen's tools, sets up pi-gen (prepare-pigen.sh), asks for the
# image's login password the first time, clears out a stale or half-finished
# build, and runs the build — inside tmux when you are on SSH, so a dropped
# connection does not kill it (reattach with: tmux attach -t humint-build).
#
# Options:
#   --clean         throw away the previous build's work and start fresh
#                   (otherwise, if the base system — pi-gen's stages 0-2 —
#                   finished last time, it is reused and only the HUMINT
#                   stage is rebuilt)
#   --prepare-only  set everything up but do not build
#   --no-tmux       do not wrap the build in tmux
#   PIGEN_DIR=...   where pi-gen goes (default ~/pi-gen)
#
# After `git pull`, just run it again: it refreshes the code in pi-gen and
# keeps your config (and password).
set -euo pipefail

CLEAN=0 PREPARE_ONLY=0 USE_TMUX=1
ARGS=("$@")
for a in "$@"; do
    case "$a" in
        --clean) CLEAN=1 ;;
        --prepare-only) PREPARE_ONLY=1 ;;
        --no-tmux) USE_TMUX=0 ;;
        -h|--help) sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $a (see --help)" >&2; exit 2 ;;
    esac
done

HERE="$(cd "$(dirname "$0")" && pwd)"
SELF="$HERE/$(basename "$0")"
PIGEN="${PIGEN_DIR:-$HOME/pi-gen}"
BRANCH="${PIGEN_BRANCH:-bookworm-arm64}"
SESSION=humint-build

say()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
warn() { printf '  !! %s\n' "$*" >&2; }
die()  { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -ne 0 ] || die "run this as your normal user, not with sudo — it asks for sudo when it needs it"
command -v apt-get >/dev/null || die "this needs a Debian-based system (Raspberry Pi OS, Debian, Ubuntu)"

# ---- 1. tools --------------------------------------------------------------
say "Installing the build tools (sudo may ask for your password)"
sudo -v
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    git tmux coreutils quilt parted qemu-user-static debootstrap zerofree zip \
    dosfstools e2fsprogs libcap2-bin grep rsync xz-utils curl xxd file kmod \
    bc gpg pigz arch-test libarchive-tools debian-archive-keyring >/dev/null

# ---- 2. on SSH, move into tmux before the long part -------------------------
if [ "$USE_TMUX" = 1 ] && [ "$PREPARE_ONLY" = 0 ] && [ -z "${TMUX:-}" ] && [ -n "${SSH_CONNECTION:-}" ]; then
    if tmux has-session -t "$SESSION" 2>/dev/null; then
        echo "A build session already exists — attaching to it."
        exec tmux attach -t "$SESSION"
    fi
    say "Continuing inside tmux (session '$SESSION') so a dropped SSH connection doesn't stop the build"
    echo "  Detach: Ctrl-b then d.   Reattach later: tmux attach -t $SESSION"
    sleep 2
    exec tmux new-session -s "$SESSION" \
        "$(printf '%q ' "$SELF" "${ARGS[@]}") --no-tmux; echo; echo 'Press Enter to close.'; read -r _"
fi

# ---- 3. sanity checks --------------------------------------------------------
arch="$(dpkg --print-architecture)"
case "$arch" in
    arm64) ;;
    amd64) echo "  Building on x86-64: the ARM parts run under emulation, so expect 2–3 hours." ;;
    armhf) warn "this is 32-bit Raspberry Pi OS. Building a 64-bit image works best from 64-bit Raspberry Pi OS — reflash the builder card with the 64-bit version if the build fails." ;;
    *) warn "untested builder architecture: $arch" ;;
esac
mkdir -p "$(dirname "$PIGEN")"
free_gb=$(df -Pk "$(dirname "$PIGEN")" | awk 'NR==2 {print int($4/1048576)}')
[ "$free_gb" -ge 12 ] || die "only ${free_gb} GB free where pi-gen goes; the build needs about 15 GB (use a 32 GB+ card or set PIGEN_DIR to a USB drive)"

# ---- 3b. the key that signs updates for boxes built here --------------------
KEY="${HUMINT_SIGNING_KEY:-$HOME/.config/humint/update-signing.key}"
if [ ! -f "$KEY" ]; then
    say "Creating the update-signing key ($KEY)"
    install -d -m 700 "$(dirname "$KEY")"
    ( umask 077; openssl genpkey -algorithm ed25519 -out "$KEY" )
    echo "  Boxes built here accept only updates signed with it (deploy/pi/make-update.sh)."
    echo "  Back it up somewhere safe: lose it and boxes can only be updated by re-imaging."
fi

# ---- 4. pi-gen + our stage + the app ---------------------------------------
say "Setting up pi-gen"
"$HERE/prepare-pigen.sh" "$PIGEN" >/dev/null || die "setting up pi-gen failed"
PIGEN="$(cd "$PIGEN" && pwd)"
CONFIG="$PIGEN/config"
echo "  pi-gen ($BRANCH) is ready at $PIGEN"

# ---- 5. config: password, timezone -----------------------------------------
set_config() {   # set_config KEY VALUE — single-quoted, so any character is safe
    local q; q="'$(printf '%s' "$2" | sed "s/'/'\\\\''/g")'"
    K="$1" V="$q" awk '
        $0 ~ "^"ENVIRON["K"]"=" { print ENVIRON["K"] "=" ENVIRON["V"]; done=1; next }
        { print }
        END { if (!done) print ENVIRON["K"] "=" ENVIRON["V"] }' "$CONFIG" >"$CONFIG.tmp"
    mv "$CONFIG.tmp" "$CONFIG"
}

if grep -q 'change-me-before-building' "$CONFIG"; then
    say "Choose the password for the 'humint' login on the finished box"
    echo "  (SSH and keyboard login until first boot — which replaces it with one of the box's own and"
    echo "   shows it on screen; set LOGIN_PASSWORD=keep in the card's config to keep this one. Not the PIN.)"
    while :; do
        read -r -s -p "  Password: " p1; echo
        read -r -s -p "  Again:    " p2; echo
        if [ -z "$p1" ]; then echo "  It can't be empty."
        elif [ "$p1" != "$p2" ]; then echo "  They don't match — try again."
        elif [ "${#p1}" -lt 8 ]; then echo "  Use at least 8 characters."
        else break; fi
    done
    set_config FIRST_USER_PASS "$p1"
    unset p1 p2
    chmod 600 "$CONFIG"

    tz="$(timedatectl show -p Timezone --value 2>/dev/null || cat /etc/timezone 2>/dev/null || true)"
    if [ -n "$tz" ] && [ "$tz" != "Etc/UTC" ] && grep -q '^TIMEZONE_DEFAULT="Etc/UTC"' "$CONFIG"; then
        set_config TIMEZONE_DEFAULT "$tz"
        echo "  Timezone set to $tz (from this machine). Keyboard: US — change KEYBOARD_* in $CONFIG if needed."
    fi
fi

# ---- 6. clear a stale build -------------------------------------------------
MARK="$PIGEN/.humint-built-from"
if [ -d "$PIGEN/work" ] || [ -d "$PIGEN/deploy" ]; then
    if [ "$CLEAN" = 1 ] || [ "$(cat "$MARK" 2>/dev/null)" != "$BRANCH" ]; then
        say "Clearing the previous build's work files"
        sudo rm -rf "$PIGEN/work" "$PIGEN/deploy"
    fi
fi

if [ "$PREPARE_ONLY" = 1 ]; then
    say "Prepared. Review $CONFIG if you like, then run this script again to build."
    exit 0
fi

# ---- 7. build ---------------------------------------------------------------
cd "$PIGEN"
# The base system (stage0-2) takes most of the time and never changes between
# our builds. If it finished last time, skip it and rebuild only our stage
# (CLEAN=1 recopies it fresh from stage2).
RESUME=0
if [ "$CLEAN" = 0 ] && [ -f build.log ] && grep -q " End $PIGEN/stage2\$" build.log &&
   compgen -G "$PIGEN/work/*/stage2/rootfs/etc" >/dev/null; then
    RESUME=1
fi
cleanup_skip() { rm -f "$PIGEN"/stage0/SKIP "$PIGEN"/stage1/SKIP "$PIGEN"/stage2/SKIP; }
trap cleanup_skip EXIT
if [ "$RESUME" = 1 ]; then
    say "Reusing the base system from the last build; rebuilding only the HUMINT stage. Log: $PIGEN/build.log"
    touch stage0/SKIP stage1/SKIP stage2/SKIP
else
    say "Building the image — about an hour on a Pi 5, longer on a Pi 4. Log: $PIGEN/build.log"
fi
echo "$BRANCH" >"$MARK"
set +e
sudo env CLEAN=1 ./build.sh 2>&1 | tee build.log.new
rc=${PIPESTATUS[0]}
set -e
mv -f build.log.new build.log
if [ "$rc" -ne 0 ] || grep -q 'Build failed' build.log; then
    echo
    warn "the build failed. The error is just above '[..] Build failed' in $PIGEN/build.log:"
    grep -n -B 15 'Build failed' build.log | tail -16 >&2 || tail -20 build.log >&2
    echo "  Fix it and run this script again (add --clean to start from scratch)."
    exit 1
fi

say "Done."
ls -lh "$PIGEN"/deploy/*.zip "$PIGEN"/deploy/*.img* 2>/dev/null | awk '{print "  " $5 "  " $9}' || true
cat <<EOF

  Copy the image to your Mac, from the Mac's Terminal:
    scp '$(whoami)@$(hostname).local:$PIGEN/deploy/*.zip' ~/Downloads/
  Then flash it with Raspberry Pi Imager → "Use custom" (skip OS customisation).
EOF
