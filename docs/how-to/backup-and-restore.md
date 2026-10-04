# How to back up and restore

**There is no other copy of your case file.** The Docker volume is not a
backup.

A backup is one `.zip` with every record and every uploaded attachment —
enough to rebuild the instance somewhere else. It includes **user accounts
and their password hashes**, so guard the file like the database itself.
Offline map packs are deliberately left out (they can be downloaded again).

---

## Take a backup by hand

Account menu → **Admin settings → Backup & restore → Download backup**. Big
cases take a moment.

## Back up every night automatically

The app has no scheduler on purpose — the host has one and knows where the
disk is.

1. Save this as `/usr/local/bin/humint-backup.sh` and `chmod +x` it:

   ```bash
   #!/bin/bash
   set -euo pipefail
   BASE="http://localhost:8080"
   DEST="/var/backups/humint"
   JAR="$(mktemp)"
   trap 'rm -f "$JAR"' EXIT

   mkdir -p "$DEST"
   curl -sS -c "$JAR" -X POST "$BASE/api/auth/login" \
     -H 'Content-Type: application/json' \
     -d "{\"username\":\"$HUMINT_USER\",\"password\":\"$HUMINT_PASS\"}" \
     -o /dev/null
   curl -sS -b "$JAR" "$BASE/api/admin/backup" \
     -o "$DEST/humint-$(date +%F).zip"
   curl -sS -b "$JAR" -X POST "$BASE/api/auth/logout" -o /dev/null

   find "$DEST" -name 'humint-*.zip' -mtime +31 -delete   # keep a month
   ```

2. Put the admin credentials in a root-only file, not in the script:

   ```bash
   sudo install -m 600 /dev/stdin /etc/humint-backup.env <<'EOF'
   HUMINT_USER=admin
   HUMINT_PASS=your-admin-password
   EOF
   ```

3. Add a cron line (`sudo crontab -e`):

   ```
   15 2 * * *  . /etc/humint-backup.env && /usr/local/bin/humint-backup.sh
   ```

4. **Copy backups off the machine.** A backup that only lives on the Pi dies
   with the Pi.
5. **Test a restore now** (below). An untested backup is a rumour.

## Restore a backup

**Restore replaces everything** — records, reports, attachments and user
accounts. There's no undo. Everyone, including you, is signed out and signs
back in with an account from the restored file.

1. **Admin settings → Backup & restore**.
2. Choose the file → **Restore from this file…**
3. Type the confirmation phrase it asks for.

Backups from older builds restore fine: missing new columns are left empty,
and old values (such as link grades written as words) are converted. If the
file can't fit, the restore refuses with a reason before changing anything —
see [Fix common problems → Restore refuses the file](troubleshooting.md#restore-refuses-the-file).

## Test a restore without touching the real instance

Stand up a scratch copy on another port with its own database volume:

```bash
cp -r humint-platform humint-scratch && cd humint-scratch
cp ../humint-platform/.env .
sed -i 's/^API_PORT=.*/API_PORT=8081/' .env
docker compose -p humint-scratch up -d --build
```

Open `http://<machine>:8081`, create a throwaway admin, restore last night's
backup, and sign in with a real account from it. `-p` is what keeps the
databases apart. Tear it down afterwards:

```bash
docker compose -p humint-scratch down -v
```

## Rebuild after losing the machine

1. Install on the new machine — [Install](install.md), steps 1–5.
2. Create an admin account when asked. The restore will replace it.
3. Restore your most recent backup.
4. Sign in with an account from the backup.

Install the same version as the backup or newer. A fresh install needs no
migrations, and an older backup fits a newer schema; a backup from a *newer*
build than the code you installed won't restore until you upgrade.

Practise this once before you need it.

## Monthly ten minutes

- [ ] Backups exist and aren't zero bytes
- [ ] Last month's restores into a scratch deployment and you can sign in
- [ ] `git pull` and read what changed
- [ ] Skim the audit log for anything you don't recognise
- [ ] `docker system df` — the disk isn't filling
