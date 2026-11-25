#!/usr/bin/env bash
# Update a Docker deployment of the platform to the latest code, in one go.
#
#   ./update.sh              show what changed, then update (asks first)
#   ./update.sh --check      only show what changed since this server's version
#   ./update.sh --yes        update without asking
#   ./update.sh --rollback   put back the code and the database from before
#                            the last update
#
# Run it from the project folder on the server. It:
#   1. fetches the latest code and shows the change log (the commits since
#      this server's version) and the database migrations it would run;
#   2. backs up the database (backups/pre-update-<when>-<commit>.dump);
#   3. moves the code forward (git, fast-forward only — never over your own
#      changes to tracked files);
#   4. rebuilds the api and worker images, stops them, runs the migrations
#      this database has not had (oldest first, each once — the list is kept
#      in the database, in schema_migrations), and starts everything again;
#   5. waits for the console to answer on /health.
#
# If anything fails after the code moved, it says so and how to put it back:
# ./update.sh --rollback restores the backup and the previous code.
#
# The field box updates differently (signed bundles: Admin → Backup & restore,
# or Box → Actions → Update online); this is for the Docker deployment only.
set -euo pipefail

cd "$(dirname "$0")"
CHECK=0; YES=0; ROLLBACK=0
for a in "$@"; do
    case "$a" in
        --check) CHECK=1 ;;
        --yes|-y) YES=1 ;;
        --rollback) ROLLBACK=1 ;;
        -h|--help) sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "update.sh: unknown option $a (see --help)" >&2; exit 2 ;;
    esac
done

say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
die() { echo "update.sh: $*" >&2; exit 1; }

command -v git >/dev/null || die "needs git"
docker compose version >/dev/null 2>&1 || die "needs Docker Compose v2 (docker compose)"
[ -f .env ] || die "no .env here — run this from the project folder of a configured install"
[ -d .git ] || die "this folder is not a git checkout (clone the repository to update this way)"
set -a; . ./.env; set +a
: "${POSTGRES_USER:?POSTGRES_USER is not set in .env}"
: "${POSTGRES_DB:?POSTGRES_DB is not set in .env}"
PORT="${API_PORT:-8080}"
STATE="backups/last-update.env"
mkdir -p backups

psql_db() { docker compose exec -T db psql -q -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"; }

wait_db() {
    docker compose up -d db >/dev/null
    for _ in $(seq 1 60); do
        docker compose exec -T db pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1 && return 0
        sleep 2
    done
    die "the database did not come up"
}

wait_health() {
    for _ in $(seq 1 60); do
        if curl -fsS "http://localhost:$PORT/health" >/dev/null 2>&1; then return 0; fi
        sleep 2
    done
    return 1
}

pending_migrations() {
    # The migrations this database has not had. A database from before this
    # script has no record of any: they all run once — each one checks
    # before it changes anything, so that is safe.
    local done_list
    done_list="$(psql_db -At -c "SELECT name FROM schema_migrations" 2>/dev/null || true)"
    ls db/migrate-v*.sql 2>/dev/null | sort -V | while read -r f; do
        n="$(basename "$f")"
        grep -qxF "$n" <<<"$done_list" || echo "$n"
    done
}

write_build_info() {
    # Baked into the api image: what this server runs, for Admin → Backup &
    # restore → Check for updates (which compares it with GitHub).
    printf '{"build": %s, "commit": "%s", "updated_at": "%s"}\n' \
        "$(git rev-list --count HEAD)" "$(git rev-parse HEAD)" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >api/build-info.json
}

# ---- rollback ----------------------------------------------------------------------------
if [ "$ROLLBACK" = 1 ]; then
    [ -f "$STATE" ] || die "no update to roll back (no $STATE)"
    . "$STATE"
    [ -f "$DUMP" ] || die "the backup $DUMP is gone"
    say "Rolling back to $(git rev-parse --short "$PREV") and the database as it was at $(basename "$DUMP")"
    if [ "$YES" != 1 ]; then
        read -r -p "This replaces the current database with that backup. Continue? [y/N] " a
        [ "$a" = y ] || [ "$a" = Y ] || die "not rolled back"
    fi
    wait_db
    docker compose stop api worker >/dev/null
    git reset -q --hard "$PREV"
    # Everything the update added goes too: the schema is emptied, then the
    # backup restored into it.
    psql_db -c "SET client_min_messages = warning" -c "DROP SCHEMA public CASCADE" -c "CREATE SCHEMA public" || die "could not empty the database for the restore"
    docker compose exec -T db pg_restore --no-owner -U "$POSTGRES_USER" -d "$POSTGRES_DB" <"$DUMP" ||
        echo "(pg_restore reported problems above; the data is usually restored regardless — check the console)"
    write_build_info
    docker compose up -d --build
    wait_health && echo "Rolled back. Hard-reload the browser (Ctrl-Shift-R)." || die "the console did not answer on /health after the rollback: docker compose logs api"
    rm -f "$STATE"
    exit 0
fi

# ---- what changed ------------------------------------------------------------------------
branch="$(git rev-parse --abbrev-ref HEAD)"
[ "$branch" != HEAD ] || die "the checkout is not on a branch (git checkout main)"
say "Fetching the latest code ($branch)"
git fetch -q origin "$branch" || die "could not fetch from origin — is this server online?"
behind="$(git rev-list --count "HEAD..origin/$branch")"
ahead="$(git rev-list --count "origin/$branch..HEAD")"
[ "$ahead" = 0 ] || die "this checkout has $ahead commit(s) GitHub does not — it cannot be moved forward safely"

wait_db
built="$(python3 -c 'import json;print(json.load(open("api/build-info.json"))["commit"])' 2>/dev/null || echo "")"
if [ "$behind" = 0 ]; then
    echo "The code is up to date ($(git rev-parse --short HEAD))."
else
    echo "$behind change(s) since this server's version ($(git rev-parse --short HEAD)):"
    echo
    git log --no-merges --reverse --format='  • %s' "HEAD..origin/$branch"
fi
# The migrations the new code carries that this database has not had.
newm="$( { pending_migrations; git diff --name-only --diff-filter=A "HEAD..origin/$branch" -- 'db/migrate-v*.sql' | xargs -rn1 basename; } | sort -uV)"
if [ -n "$newm" ]; then
    echo; echo "Database migrations to run:"; sed 's/^/  • /' <<<"$newm"
fi
if [ "$CHECK" = 1 ]; then
    [ "$behind" = 0 ] && [ -z "$newm" ] && [ "$built" = "$(git rev-parse HEAD)" ] && echo "Nothing to do."
    exit 0
fi
if [ "$behind" = 0 ] && [ -z "$newm" ] && [ "$built" = "$(git rev-parse HEAD)" ]; then
    echo "Nothing to do."; exit 0
fi
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
    git status --short --untracked-files=no
    die "tracked files have local changes (above): commit or undo them first (git stash), then run this again"
fi
if [ "$YES" != 1 ]; then
    read -r -p $'\nUpdate now? The database is backed up first. [y/N] ' a
    [ "$a" = y ] || [ "$a" = Y ] || die "not updated"
fi

# ---- backup ------------------------------------------------------------------------------
prev="$(git rev-parse HEAD)"
dump="backups/pre-update-$(date +%Y%m%d-%H%M%S)-$(git rev-parse --short HEAD).dump"
say "Backing up the database to $dump"
docker compose exec -T db pg_dump -Fc -U "$POSTGRES_USER" -d "$POSTGRES_DB" >"$dump" || die "the backup failed — nothing was changed"
[ -s "$dump" ] || die "the backup is empty — nothing was changed"
printf 'PREV=%s\nDUMP=%s\n' "$prev" "$dump" >"$STATE"
echo "(uploaded files live in their own volume and are not touched by an update)"

failed() {
    echo
    echo "update.sh: $1 failed." >&2
    echo "  Put everything back as it was:  ./update.sh --rollback" >&2
    echo "  Or look first:                  docker compose logs api worker" >&2
    exit 1
}

# ---- code, images, migrations ------------------------------------------------------------
say "Moving the code forward"
git merge -q --ff-only "origin/$branch" || failed "moving the code forward"
git log -1 --format='  now at %h — %s'
write_build_info

say "Rebuilding the api and worker"
docker compose build api worker || failed "the rebuild"

say "Running database migrations"
docker compose stop api worker >/dev/null
psql_db -c "CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())" ||
    failed "recording migrations"
todo="$(pending_migrations)"
if [ -z "$todo" ]; then
    echo "  none needed"
else
    first_time="$(psql_db -At -c "SELECT count(*) FROM schema_migrations")"
    [ "$first_time" = 0 ] && echo "  (first update with this script: every migration runs once — each checks before it changes anything)"
    while read -r m; do
        [ -n "$m" ] || continue
        echo "  $m"
        psql_db -c "SET client_min_messages = warning" -f - <"db/$m" >/dev/null || failed "migration $m"
        psql_db -c "INSERT INTO schema_migrations (name) VALUES ('$m') ON CONFLICT DO NOTHING" || failed "recording $m"
    done <<<"$todo"
fi

say "Starting"
docker compose up -d || failed "starting"
if wait_health; then
    echo
    echo "Updated to $(git rev-parse --short HEAD). Hard-reload the browser once (Ctrl-Shift-R / Cmd-Shift-R)."
    echo "The database backup from before is $dump (./update.sh --rollback puts it back)."
else
    failed "the console answering on http://localhost:$PORT/health"
fi
