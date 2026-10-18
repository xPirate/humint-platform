#!/usr/bin/env bash
# Build a signed update bundle for field servers, from this checkout.
#
#   deploy/pi/make-update.sh [--out DIR] [--key FILE]
#
# The bundle (humint-update-<n>-<commit>.tar) holds:
#   manifest.json   what it is: build number, commit, the payload's SHA-256,
#                   the migrations it carries, the Python requirements' hash
#   manifest.sig    an Ed25519 signature of manifest.json
#   payload.tar.gz  the console (api, worker, frontend, db), the appliance's
#                   own scripts and units, and — when built on a 64-bit Pi —
#                   Python wheels, so a box with no internet can install them
#
# A field server applies it only if the signature checks against the public
# key baked into its image (/opt/humint/update-signing.pub), so the signing
# key must be the one the image was built with. build-image.sh creates it the
# first time (~/.config/humint/update-signing.key) and puts the public half in
# every image it builds. Keep the private key on the builder; back it up. If
# it is lost, boxes can only be updated by re-imaging.
#
# Apply on the box with `sudo humint-ctl update FILE`, the panel's Menu →
# Update from USB, or Admin → Backup & restore → Update this field server.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="$PWD"
KEY="${HUMINT_SIGNING_KEY:-$HOME/.config/humint/update-signing.key}"
while [ $# -gt 0 ]; do
    case "$1" in
        --out) OUT="$2"; shift 2 ;;
        --key) KEY="$2"; shift 2 ;;
        -h|--help) sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
done
[ -f "$KEY" ] || { echo "No signing key at $KEY — build an image first (build-image.sh makes one), or pass --key." >&2; exit 1; }

say() { printf '==> %s\n' "$*"; }
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
OVERLAY="$REPO/deploy/pi/stage-humint/03-overlay/files"

count="$(git -C "$REPO" rev-list --count HEAD)"
commit="$(git -C "$REPO" rev-parse --short=10 HEAD)"
dirty=""
git -C "$REPO" diff --quiet HEAD -- api worker frontend db deploy/pi || dirty="-dirty"

say "Collecting build $count ($commit$dirty)"
mkdir -p "$STAGE/payload/app" "$STAGE/payload/overlay"
for part in api worker frontend db; do
    cp -R "$REPO/$part" "$STAGE/payload/app/$part"
done
cp "$REPO/.env.example" "$STAGE/payload/app/.env.example"
find "$STAGE/payload/app" -name __pycache__ -type d -prune -exec rm -rf {} +
# The appliance's scripts, units and network hook — not the boot-partition
# template, which only first boot reads.
cp -R "$OVERLAY/opt" "$STAGE/payload/overlay/opt"
cp -R "$OVERLAY/etc" "$STAGE/payload/overlay/etc"
find "$STAGE/payload/overlay" -name __pycache__ -type d -prune -exec rm -rf {} +
rm -f "$STAGE/payload/overlay/opt/humint/update-signing.pub"

req_hash="$(cat "$REPO/api/requirements.txt" "$REPO/worker/requirements.txt" | sha256sum | cut -d' ' -f1)"
wheels=false
if [ "$(uname -m)" = aarch64 ] && python3 -c 'import sys; sys.exit(sys.version_info[:2] != (3, 11))'; then
    say "Building Python wheels for the box (arm64, Python 3.11)"
    python3 -m pip wheel -q -w "$STAGE/payload/wheels" \
        -r "$REPO/api/requirements.txt" -r "$REPO/worker/requirements.txt" \
        "luma.oled==3.13.0" "gpiozero>=2.0" "smbus2>=0.4"
    wheels=true
else
    echo "  (not on a 64-bit Pi with Python 3.11: no wheels. A box will refuse this bundle if its"
    echo "   Python requirements differ from what it has; build on the builder Pi for those.)"
fi

migrations="$(cd "$REPO/db" && ls migrate-v*.sql | sort -V | python3 -c 'import json,sys; print(json.dumps([l.strip() for l in sys.stdin if l.strip()]))')"

say "Packing"
tar -C "$STAGE/payload" -czf "$STAGE/payload.tar.gz" .
sha="$(sha256sum "$STAGE/payload.tar.gz" | cut -d' ' -f1)"
python3 - "$STAGE/manifest.json" <<PY
import json, sys, time
json.dump({
    "format": "humint-field-update", "format_version": 1,
    "build": $count, "commit": "$commit$dirty",
    "created": int(time.time()),
    "payload_sha256": "$sha",
    "requirements_sha256": "$req_hash",
    "wheels": $([ "$wheels" = true ] && echo True || echo False),
    "migrations": $migrations,
}, open(sys.argv[1], "w"), indent=1)
PY
openssl pkeyutl -sign -inkey "$KEY" -rawin -in "$STAGE/manifest.json" -out "$STAGE/manifest.sig"

name="humint-update-${count}-${commit}${dirty}.tar"
tar -C "$STAGE" -cf "$OUT/$name" manifest.json manifest.sig payload.tar.gz
say "Done: $OUT/$name ($(du -h "$OUT/$name" | cut -f1))"
echo "  Copy it to a USB stick (any folder), or upload it in the console: Admin → Backup & restore."
