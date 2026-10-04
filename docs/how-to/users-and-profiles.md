# How to manage users and profiles

Account menu → **Admin settings → Users** for everything here except your
own profile.

---

## Add someone

1. **Admin settings → Users → + New User**.
2. Pick a role:

   | Role | Can |
   |---|---|
   | **analyst** | Everything in the case file: records, reports, documents, review, merging, exports, posting to boards. |
   | **admin** | All of that, plus users, backup and restore, the audit log, settings, field devices, and deleting records permanently. |

   Give people **analyst** unless they run the instance. Every account sees
   the whole case file; if two pieces of work must not see each other, run two
   instances.
3. Tell them their password over a channel you trust, and ask them to fill in
   their profile (account menu → **My profile**).

## Remove someone

Set the account **inactive**. Don't delete it — the audit trail points at it.
Deactivating also stops every field device enrolled to that account. The app
won't let you deactivate or demote the last active admin.

## Reset a password

1. **Admin settings → Users → Reset password** on their row.
2. Type a new password, or press **Generate** for four random words and a
   number — easy to read out over a radio.
3. Pass it on, then close the dialog. It's shown in the clear only there.

Resetting also clears a lockout and signs that account out everywhere
(resetting your own keeps your current session). The audit log records who
reset whose password as `user.password_reset`; the password itself is never
logged. There's no self-service or email reset — people who forget ask an
admin.

## Recover the last admin password

Only when the sole admin is the one locked out, so nobody can use the button
above. On the host:

```bash
set -a; . ./.env; set +a

# 1. Make a bcrypt hash of the new password (you'll be prompted for it).
docker compose exec api python3 -c \
  "import bcrypt,getpass; print(bcrypt.hashpw(getpass.getpass().encode(), bcrypt.gensalt()).decode())"

# 2. Write it in and clear any lockout.
docker compose exec db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
  "UPDATE users SET password_hash = '<the hash>', failed_login_attempts = 0,
   locked_until = NULL WHERE username = '<the user>';"
```

Then sign in and make a second admin so this doesn't happen again.

## Unlock an account

Five failed logins lock an account for 15 minutes; it clears itself. To clear
it now, reset the password.

## Fill in or edit a profile

A profile keeps team members out of the case file: a colleague is not an
Entity.

- **Your own:** account menu → **My profile → Edit profile**.
- **Someone else's (admin):** **Admin settings → Users → Profile** on their
  row, or open their analyst page and press **Edit profile**.

What's in it:

- **Name, callsign, role.**
- **Status:** At liberty, Under duress, Incapacitated, Captured or Deceased.
- **Contacts:** press **+ Add contact** once per way to reach them. Pick a
  kind (Mobile, Email, Radio, Meshtastic, MeshCore, Signal, Telegram, Social…)
  or type your own, then the value and an optional note — e.g.
  *Radio · 146.520 simplex · evenings*. Add as many or as few as the person
  uses; up to 40.
- **Notes.**

Everyone signed in can read every profile — that's what makes it useful as a
team directory.

## Change someone's status

Edit the profile, pick the new status, and write a short note on why
(*"missed 1800 check-in, last seen north gate"*). Then save.

- The profile shows who changed it and when.
- Anyone not *At liberty* shows their status on the Users list.
- The audit log records it as `profile.status`, with old value, new value and
  the note. Contact details are never written to the log.

Keep it honest: it's what the team looks at when someone misses a check-in.
