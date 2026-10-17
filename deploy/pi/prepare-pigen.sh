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
BRANCH="${PIGEN_BRANCH:-arm64}"
REPO="$(cd "$(dirname "$0")/../.." && pwd)"

say() { printf '\n==> %s\n' "$*"; }

if [ ! -d "$PIGEN/.git" ]; then
    say "Cloning pi-gen ($BRANCH branch) into $PIGEN"
    git clone --depth 1 --branch "$BRANCH" https://github.com/RPi-Distro/pi-gen "$PIGEN"
else
    say "Using the pi-gen already at $PIGEN"
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
awk -v src="$SRC" '/^HUMINT_SRC_DIR=/{print "HUMINT_SRC_DIR=\"" src "\""; next} {print}' \
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
