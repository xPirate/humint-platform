#!/usr/bin/env bash
# Set up a pi-gen checkout to build the HUMINT field-server image.
#
#   deploy/pi/prepare-pigen.sh [PI_GEN_DIR]            native build (on a Pi or Linux)
#   deploy/pi/prepare-pigen.sh --docker [PI_GEN_DIR]   for pi-gen's build-docker.sh
#
# It clones pi-gen (64-bit branch) if it is not there yet, copies in the
# HUMINT stage and a slim copy of the app (api, worker, frontend, db — not the
# 300 MB Android project), writes ./config from config.example the first time
# (it never overwrites yours: it holds your password), points HUMINT_SRC_DIR
# at the copied app, and skips the plain Lite image so only one image is made.
#
# Run it again after pulling new code: it refreshes the stage and the app copy
# and leaves your config alone.
set -euo pipefail

MODE=native
if [ "${1:-}" = "--docker" ]; then MODE=docker; shift; fi
PIGEN="${1:-$HOME/pi-gen}"
# pi-gen keeps one branch per release; the image is 64-bit Bookworm (config:
# RELEASE, ARCH). Its default branch (master) builds 32-bit Trixie, and
# building Bookworm from it fails in stage0 on Debian's archive signatures.
BRANCH="${PIGEN_BRANCH:-bookworm-arm64}"
REPO="$(cd "$(dirname "$0")/../.." && pwd)"

say() { printf '\n==> %s\n' "$*"; }

if [ ! -d "$PIGEN/.git" ]; then
    say "Cloning pi-gen ($BRANCH branch) into $PIGEN"
    git clone --depth 1 --branch "$BRANCH" https://github.com/RPi-Distro/pi-gen "$PIGEN"
else
    current="$(git -C "$PIGEN" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')"
    if [ "$current" != "$BRANCH" ]; then
        say "Switching the pi-gen at $PIGEN from '$current' to '$BRANCH'"
        git -C "$PIGEN" fetch --depth 1 origin "$BRANCH"
        git -C "$PIGEN" checkout -B "$BRANCH" FETCH_HEAD
        if [ -d "$PIGEN/work" ] || [ -d "$PIGEN/deploy" ]; then
            echo "  !! Clear the old build first:  cd $PIGEN && sudo rm -rf work deploy"
        fi
    else
        say "Using the pi-gen already at $PIGEN ($BRANCH)"
    fi
fi
PIGEN="$(cd "$PIGEN" && pwd)"

say "Copying the HUMINT stage"
rm -rf "$PIGEN/stage-humint"
cp -R "$REPO/deploy/pi/stage-humint" "$PIGEN/stage-humint"

say "Copying the app (api, worker, frontend, db)"
mkdir -p "$PIGEN/humint-src"
for part in api worker frontend db; do
    rm -rf "$PIGEN/humint-src/$part"
    cp -R "$REPO/$part" "$PIGEN/humint-src/$part"
done
find "$PIGEN/humint-src" -name __pycache__ -type d -prune -exec rm -rf {} +
cp "$REPO/.env.example" "$PIGEN/humint-src/.env.example"

# Which build this is, for signed updates later (humint-update.sh refuses
# anything not newer). humint-src is a plain copy, so git is asked here.
python3 - "$PIGEN/humint-src/BUILD.json" <<PY
import json, sys, time
json.dump({"build": int("$(git -C "$REPO" rev-list --count HEAD)"),
           "commit": "$(git -C "$REPO" rev-parse --short=10 HEAD)",
           "requirements_sha256": "$(cat "$REPO/api/requirements.txt" "$REPO/worker/requirements.txt" | sha256sum | cut -d' ' -f1)",
           "installed": int(time.time())}, open(sys.argv[1], "w"), indent=1)
PY

# The public half of the update-signing key (see make-update.sh), so boxes
# built from this image accept bundles signed on this machine and no other.
SIGNING_KEY="${HUMINT_SIGNING_KEY:-$HOME/.config/humint/update-signing.key}"
if [ -f "$SIGNING_KEY" ]; then
    openssl pkey -in "$SIGNING_KEY" -pubout \
        -out "$PIGEN/stage-humint/03-overlay/files/opt/humint/update-signing.pub"
else
    echo "  !! No update-signing key ($SIGNING_KEY): this image will not accept update bundles."
    echo "     build-image.sh creates one; or: openssl genpkey -algorithm ed25519 -out $SIGNING_KEY"
fi

# Only the HUMINT image, not the plain Lite one stage2 would also export.
touch "$PIGEN/stage2/SKIP_IMAGES"

if [ "$MODE" = docker ]; then
    SRC="/pi-gen/humint-src"     # where build-docker.sh puts the pi-gen folder inside its container
else
    SRC="$PIGEN/humint-src"
fi

if [ ! -f "$PIGEN/config" ]; then
    say "Writing $PIGEN/config from config.example — edit it before building"
    cp "$REPO/deploy/pi/config.example" "$PIGEN/config"
    NEW_CONFIG=1
fi
# Point HUMINT_SRC_DIR at the copied app, in place (portable: no sed -i).
# "export": pi-gen passes only its own settings on to the stages.
awk -v src="$SRC" '/^(export )?HUMINT_SRC_DIR=/{print "export HUMINT_SRC_DIR=\"" src "\""; next} {print}' \
    "$PIGEN/config" >"$PIGEN/config.tmp" && mv "$PIGEN/config.tmp" "$PIGEN/config"

say "Ready."
echo "  pi-gen:         $PIGEN"
echo "  HUMINT_SRC_DIR: $SRC"
if grep -q 'change-me-before-building' "$PIGEN/config"; then
    echo
    echo "  !! Set FIRST_USER_PASS in $PIGEN/config before building."
fi
echo
if [ "$MODE" = docker ]; then
    echo "  Build with:  cd $PIGEN && ./build-docker.sh"
else
    echo "  Build with:  cd $PIGEN && sudo ./build.sh"
fi
[ -n "${NEW_CONFIG:-}" ] && echo "  (first run: review $PIGEN/config first)"
exit 0
