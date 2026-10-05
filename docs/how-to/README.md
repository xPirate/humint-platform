# How-to guides

Short, task-by-task instructions. Each page starts with what you want to get
done and walks through the clicks or commands to do it. When you want to know
*why* something works the way it does, read the
[design notes](../DESIGN.md) instead.

These replace the old SOP 01–03. Everything that was in them is here, sorted
by the job you are trying to do.

## Setting up and keeping it running (admins)

| Guide | Covers |
|---|---|
| [Install and first run](install.md) | Docker, `.env`, starting the stack, the optional model, the admin account, a five-minute smoke test, HTTPS. |
| [Upgrade the console](upgrade.md) | `git pull`, rebuilding, running database migrations in order, rolling back. |
| [Back up and restore](backup-and-restore.md) | Manual and nightly backups, restoring, testing a restore, rebuilding after losing the machine. |
| [Manage users and profiles](users-and-profiles.md) | Adding people, roles, resetting a password, recovering the last admin, profiles, status, lockouts. |
| [Set up field devices](field-devices.md) | Enrolling a phone, showing and printing its code, revoking it, putting the app on the handset. |
| [Configure the instance](configure-the-instance.md) | Admin settings: feeds, maps, boards, link signals, retention, appearance, the model, the audit log. |
| [Release the field app](release-the-field-app.md) | Building and signing an APK, publishing on GitHub, and publishing on Google Play. |
| [Fix common problems](troubleshooting.md) | What to check when something misbehaves, and the commands to check it. |

## Working the case (analysts)

| Guide | Covers |
|---|---|
| [Bring material in and review it](review-and-merge.md) | Documents, pasted text, the review queues, merging duplicates, clearing noise. |
| [Work with records and links](records-and-links.md) | Grading links 1–6, expiring them, alignment, the network, right-click actions, retention holds. |
| [Handle field reports](field-reports.md) | Writing and sending a report on the phone, then reviewing it on the console. |
| [Write reports and export packages](reports-and-exports.md) | Reports, the guided debrief, target packages and dossiers, the BOLO sheet, the executive summary. |
| [Use the map, zones and routes](maps-and-zones.md) | Basemaps, dropping a pin, zones as records, routes, KML/KMZ/GPX import and export, printing a map. |
| [Use the team pages](team-pages.md) | Your profile, searching by analyst, the Roster, BOLO and Priorities boards, feeds. |

## New here?

1. [Install it](install.md), on a laptop if you are only looking.
2. Work through the exercise in [`docs/exercise/`](../exercise/BRIEFING.md):
   eight invented documents that take an empty instance to a finished
   assessment. Follow [Bring material in and review it](review-and-merge.md)
   as you go. Mistakes there cost nothing.
3. [Set up backups](backup-and-restore.md) before any real data goes in.
