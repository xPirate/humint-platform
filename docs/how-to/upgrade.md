# How to upgrade the console

**You end up with:** the latest code running against your existing data.
**Takes:** five minutes, plus any migrations.
Run every command from the project directory.

---

## Upgrade

1. **Take a backup.** Every time, before anything else —
   [Back up and restore](backup-and-restore.md).
2. **Pull and rebuild:**

   ```bash
   cd humint-platform
   git pull
   docker compose up -d --build
   ```

   Don't skip `--build`. The API and worker code is baked into their images;
   the frontend updates straight from disk. Without `--build` you get new
   pages talking to old code.
3. **Run any migrations you skipped** (next section).
4. **Check it:** `curl http://localhost:8080/health`, then open the app.
5. **Hard-reload the browser** (Ctrl-Shift-R / Cmd-Shift-R) once if anything
   looks half-applied.
6. **Update the field app** if the release notes say so. Its forms are built
   into the APK, so handsets only learn about a new form when they install a
   new build. Older builds keep working; they just don't have the new form.
   See [Set up field devices → Update the app](field-devices.md#update-the-app-on-a-phone).

A fresh install needs no migrations — `db/init.sql` already has everything.

## Run the migrations

Each schema change ships as a file in `db/`, named for the version that
introduced it. Run each one once; the header of each file says what it
needs to come after.

| File | Adds |
|---|---|
| `db/migrate-v1.4-field.sql` | Field devices and the field-report intake queue. |
| `db/migrate-v1.5-templates.sql` | Structured field reports (the seven forms). |
| `db/migrate-v1.6-device-codes.sql` | Showing a device's code again. |
| `db/migrate-v1.7-relationship-grading.sql` | 1–6 link grading (converts confirmed→1, probable→2, possible→3) and link expiry dates. |
| `db/migrate-v1.8-analyst-profiles.sql` | Analyst profiles: status, callsign, contacts. |
| `db/migrate-v1.9-zones-routes.sql` | Zones become records (existing zones are converted), Routes, and route/area field reports. |

**Run them in version order, oldest you haven't run first.** For example,
coming from v1.6:

```bash
set -a; . ./.env; set +a         # puts POSTGRES_USER / POSTGRES_DB in the shell
docker compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" < db/migrate-v1.7-relationship-grading.sql
docker compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" < db/migrate-v1.8-analyst-profiles.sql
docker compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" < db/migrate-v1.9-zones-routes.sql
```

The `-T` matters — without it, compose swallows the redirected file. List
what's available with `ls db/migrate-*.sql`. The exact SQL and the reasoning
for each change are under "Upgrading an existing deployment" in
[DESIGN.md](../DESIGN.md).

## Roll back

```bash
git checkout <previous-tag>
docker compose up -d --build
```

A rollback does **not** undo a migration. Migrations here only add, and old
code ignores a column it doesn't know, so this usually works. If it doesn't,
restore the backup you took in step 1.

## Upgrade checklist

- [ ] Backup downloaded and not zero bytes
- [ ] `git pull` and `docker compose up -d --build`
- [ ] Migrations run in order
- [ ] `/health` says ok
- [ ] Browser hard-reloaded
- [ ] Field app updated if the release notes say so
