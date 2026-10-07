# How to fix common problems

Run commands from the project directory.

## First, look

```bash
curl http://localhost:8080/health          # {"status":"ok","db":true} is healthy
docker compose ps                          # db, api, worker all running?
docker compose logs -f --tail 100 api      # requests and errors
docker compose logs -f --tail 100 worker   # OCR, extraction, correlation, geocoding, map downloads
docker compose logs -f --tail 100 db       # Postgres
docker system df                           # disk, including volumes
```

Point any uptime monitor at `/health`. It returns `"degraded"` when the
database is unreachable — the failure worth being woken for.

---

## Console

### `db` keeps restarting
Usually `POSTGRES_PASSWORD` is empty or has a character the shell ate. Check
`docker compose logs db`. If you first started with a broken password, the
volume was initialised with it. On a **fresh install with nothing to lose**,
`docker compose down -v` (this **deletes the database**) and start again.

### `/health` says `"db":false`
Postgres isn't reachable. `docker compose logs db`. On a Pi's first start it
may just still be starting — wait 30 seconds. If the stack stopped,
`docker compose up -d`.

### The page loads but buttons do nothing, or it looks half-updated
Hard-reload: Ctrl-Shift-R (Cmd-Shift-R on a Mac). Still wrong after an
upgrade? You probably skipped `--build` — run `docker compose up -d --build`.

### Uploads fail with a size error
Raise `MAX_UPLOAD_MB` in `.env`, then `docker compose up -d`.

### Documents stay at *Waiting*
The worker isn't running or can't reach the database:

```bash
docker compose ps worker
docker compose logs --tail 50 worker
docker compose restart worker
```

### Documents say *Read* but proposed nothing
The model was down when they were read. Check **Admin settings → Model**, fix
it, then **Read empty ones again** on the Documents inbox.

### The model works from the shell but not from the app
You set `OLLAMA_BASE_URL` to `localhost`. Inside a container that's the
container. Use the host's address.

### Extraction is slow
Normal on modest hardware; nothing waits on it. In order of effect: a smaller
model; `OLLAMA_EXTRACT_MODEL` set to a small one while the assistant keeps a
larger one; or Ollama on a bigger machine. **Admin settings → Model** shows
response times.

### Disk filling up
Usually attachments, then Postgres, then old images, then map packs.

```bash
docker system df
docker image prune          # safe: images nothing uses
```

**Never `docker volume prune`** — with the stack down it deletes your
database. Delete map packs from **Admin settings → Maps** instead.

### The correlation queue exploded
A bulk import or a new feed. Bulk-dismiss below 80% and work the top by hand —
[Work the review queue → When the queue is huge](review-and-merge.md#when-the-queue-is-huge).
Then set the feed's limits.

### Someone is locked out
Five bad logins = 15 minutes. Wait, or
[reset their password](users-and-profiles.md#reset-a-password). The only admin
locked out? [Recover the last admin](users-and-profiles.md#recover-the-last-admin-password).

### Restore refuses the file
Read the message; it says what didn't fit.

- **"…it contains: …"** — the zip isn't a backup; the message lists what's in
  it. You probably picked the wrong file.
- **A table or column it doesn't have** — the backup is from a newer build.
  Upgrade (with migrations), then restore.
- **`violates foreign key constraint attachments_entity_id_fkey`** — the
  database is missing the portrait-pointer migration. Run the
  `ALTER TABLE … DROP CONSTRAINT` / `ADD CONSTRAINT … DEFERRABLE INITIALLY
  DEFERRED` pair from "The portrait pointer makes the schema's only cycle" in
  [DESIGN.md](../DESIGN.md), then restore again. Re-running `init.sql` doesn't
  fix it. Your backup is fine.

A backup re-zipped by a desktop (with a wrapper folder) restores fine; a zip
holding two backups doesn't.

### Graded links or profiles give errors after an upgrade
A migration was skipped. Run `db/migrate-v1.7-relationship-grading.sql` and
`db/migrate-v1.8-analyst-profiles.sql` in order —
[Upgrade → Run the migrations](upgrade.md#run-the-migrations).

---

## Field app

### The QR won't scan
- Get the whole code inside the bracket, 15–30 cm away, and hold still. Amber
  ("Code found — hold steady") means it's seen it and is reading.
- Tap the screen to focus. Turn up the console screen's brightness, or use a
  printed card.
- **Nothing happens at all:** the code may be from a revoked device or an old
  printed card. Press **Show a code** on the console for a fresh one.

### Upload fails after scanning
The reason stays on the report's card.

- **Can't connect** — the phone can't reach the address in the code. It must
  be the console's LAN/VPN address, never `localhost`. Re-enroll or edit the
  address, then **Show a code**.
- **Refused / unauthorised** — the device was revoked, or its account was
  deactivated.
- **Too many requests** — the per-device rate limit; wait a minute.

### "App not installed" or "conflicts with an existing package"
The installed copy is signed with a different key — a debug build, or the
other channel (Play vs GitHub). **Send everything first**, then uninstall and
install the right one. See
[Don't mix Play and GitHub installs](field-devices.md#dont-mix-play-and-github-installs-on-one-phone).

### Play Protect blocks the GitHub APK
Choose **More details → Install anyway**, or install from the Play listing
instead.

### A route didn't record, or is a straight line
After you press **Stop**, the report says what the GPS did on that run —
how many fixes arrived, how many were kept, and the longest stretch with
none. That tells you which of these it was:

- **"No GPS at all for … minutes":** the phone stopped giving the app
  location with the screen off. Two settings do this, and the report screen
  warns about both before you start, with a button to fix them:
  - **Battery Saver** (its location mode turns GPS off with the screen off).
    Turn it off for the walk.
  - **Battery use** for HUMINT Field set to *Optimised*. Set it to
    *Unrestricted* (App info → Battery).
  The notification also says **No GPS for …** during the walk, so a tester
  can check it at any time.
- **"Most fixes were too rough to draw":** GPS was worse than about 35 m.
  The app still keeps a rougher fix (up to 100 m) every so often once you
  have clearly moved, so the track follows you, just less closely. Carry the
  phone higher — a chest pocket or the top of a bag rather than a trouser
  pocket.
- **Nothing recorded:** location must be allowed and GPS switched on. The
  report says why if the recorder could not start.
- **Stopped by itself:** the phone killed the app. Set battery use to
  *Unrestricted* as above. The points recorded so far are kept; press
  **Continue recording**.
- **No notification visible:** notifications were refused. The recording
  still runs; allow notifications for the app to see and stop it from there.

### Forgotten PIN
Unrecoverable by design. **Erase and start again** on the lock screen; unsent
reports are lost, sent ones are safe on the console.

### Building: the error is just a version number (e.g. `25.0.3`)
The build is using too new a JDK. Use JDK 21 —
[Release the field app → Before every release](release-the-field-app.md#before-every-release).

### Building: the APK says version 1.1 (or another old one)
You built debug, or from an old folder. Check `versionName` in
`android/app/build.gradle.kts`, run a **release** build, and confirm with
`aapt dump badging`.
