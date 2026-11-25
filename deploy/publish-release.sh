#!/usr/bin/env bash
# Publish a release that field servers can find and install by themselves
# (Admin → Updates → Check for updates, when they have internet).
#
#   deploy/publish-release.sh [--pi] [--no-x86] [--with-os] [--notes FILE] [--yes] [--dry-run]
#
# On the builder (the machine with the update-signing key):
#   1. checks this checkout is clean and pushed (a release is a commit
#      everyone can see);
#   2. writes the change log since the last release (deploy/release-notes.py:
#      each commit's message, without trailers), or takes --notes FILE, and
#      shows it;
#   3. builds the signed bundles: x86 (deploy/x86/make-update.sh, code only
#      unless --with-os: a machine online fetches Ubuntu's updates itself) and,
#      with --pi, the Pi's (deploy/pi/make-update.sh);
#   4. creates the GitHub release build-<n> on that commit, with the change
#      log as its notes and the bundles attached (gh, signed in).
#
# The bundles are signed here, with the key that never leaves this machine;
# a box checks the signature before it changes anything, so publishing them
# on GitHub gives nobody a way to push code to a box.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
X86=1; PI=0; WITH_OS=0; NOTES=""; YES=0; DRY=0
while [ $# -gt 0 ]; do
    case "$1" in
        --pi) PI=1; shift ;;
        --no-x86) X86=0; shift ;;
        --with-os) WITH_OS=1; shift ;;
        --notes) NOTES="$(cd "$(dirname "$2")" && pwd)/$(basename "$2")"; shift 2 ;;
        --yes) YES=1; shift ;;
        --dry-run) DRY=1; shift ;;
        -h|--help) sed -n '2,21p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
done
MAKE_X86="${HUMINT_MAKE_X86:-$REPO/deploy/x86/make-update.sh}"
MAKE_PI="${HUMINT_MAKE_PI:-$REPO/deploy/pi/make-update.sh}"
say() { printf '\n== %s\n' "$*"; }
die() { echo "publish-release: $*" >&2; exit 1; }

[ "$X86" = 1 ] || [ "$PI" = 1 ] || die "nothing to build (--no-x86 without --pi)"
command -v gh >/dev/null || die "needs the GitHub CLI (gh), signed in: gh auth login"
gh auth status >/dev/null 2>&1 || die "gh is not signed in: gh auth login"

cd "$REPO"
git diff --quiet HEAD -- api worker frontend db native deploy || die "the checkout has uncommitted changes: commit them first"
git fetch -q --tags origin 2>/dev/null || die "HEAD is not pushed: there is no remote 'origin' to release from"
branch="$(git rev-parse --abbrev-ref HEAD)"
git merge-base --is-ancestor HEAD "origin/$branch" 2>/dev/null || die "HEAD is not pushed to origin/$branch: push it first"

count="$(git rev-list --count HEAD)"
commit="$(git rev-parse --short=10 HEAD)"
tag="build-$count"
git rev-parse -q --verify "refs/tags/$tag" >/dev/null && die "$tag is already released"
prev="$(git tag -l 'build-*' | sort -V | tail -1 || true)"

say "Build $count ($commit) — changes since ${prev:-the start}"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
if [ -n "$NOTES" ]; then cp "$NOTES" "$work/notes.md"
else python3 "$HERE/release-notes.py" --repo "$REPO" ${prev:+--since "$prev"} >"$work/notes.md"; fi
cat "$work/notes.md"
if [ "$YES" != 1 ] && [ "$DRY" != 1 ]; then
    read -r -p "Publish build $count with these notes? [y/N] " ans
    [ "$ans" = y ] || [ "$ans" = Y ] || die "not published (edit the notes with --notes FILE)"
fi

mkdir -p "$work/out"
if [ "$X86" = 1 ]; then
    say "x86 bundle"
    if [ "$WITH_OS" = 1 ]; then "$MAKE_X86" --out "$work/out"; else "$MAKE_X86" --out "$work/out" --no-os; fi
fi
if [ "$PI" = 1 ]; then
    say "Pi bundle"
    "$MAKE_PI" --out "$work/out"
fi
mapfile -t assets < <(find "$work/out" -maxdepth 1 -name "humint-update-$count-*.tar" | sort)
[ "${#assets[@]}" -gt 0 ] || die "no bundle was made"
for a in "${assets[@]}"; do
    case "$(basename "$a")" in *-dirty*) die "$(basename "$a") is from a dirty checkout" ;; esac
done

say "Releasing $tag"
if [ "$DRY" = 1 ]; then
    echo "(dry run) gh release create $tag --target $(git rev-parse HEAD) with:"
    printf '  %s\n' "${assets[@]##*/}"
    exit 0
fi
gh release create "$tag" "${assets[@]}" --target "$(git rev-parse HEAD)" \
    --title "Build $count — $(date +%Y-%m-%d)" --notes-file "$work/notes.md"
echo "Published. Field servers with internet see it under Admin → Updates."
