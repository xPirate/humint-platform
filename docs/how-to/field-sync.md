# Bring a field server's work home

A field server (the [Raspberry Pi appliance](../../deploy/pi/README.md), or any
console taken off-site) works on its own copy of the case for days. Field sync
brings what it learned back to HQ **without overwriting what HQ learned in the
meantime**: everything comes home as proposals a person accepts, the same way
a document's extracted names do.

Admin only, on both ends. Both consoles need v1.12 or later (run
`db/migrate-v1.12-field-sync.sql` on an existing install — see
[Upgrade](upgrade.md)).

## Before the deployment: seed the field server from HQ

1. At HQ: **Admin → Backup & restore → Download backup.**
2. On the field server: **Admin → Backup & restore → Restore**, with that file.

The field server now holds HQ's case, with the same record ids, and remembers
the moment it was loaded. Its first package home starts from there, so it
carries only the field's work, not the whole case back again. (A field server
keeps its own identity through a restore — it never claims to be HQ.)

You can skip this and start the field server empty; then everything it holds
comes home as new records, with HQ's lookalikes offered beside each one.

## In the field: export a package

**Admin → Field sync → Send home.** The panel shows what has changed since the
last package. Choose what to include:

| Option | Carries |
|---|---|
| Changes since the last package | The usual choice. Each package picks up where the last left off. |
| Everything since this server was loaded from HQ | A full re-send of the deployment's work — if a package was lost. |
| Everything on this server | For a field server that was never seeded from HQ. |

**Export field package** downloads a `.zip`. It holds case data: carry it like
a backup (encrypted USB stick), and delete it once imported.

What a package carries: records (people, organisations, locations, events,
sources, communications, vehicles, records) created or changed; new links,
with their 1–6 grading, date and notes; reports, with their attachments and
the records they were linked to; and phone reports the field server received
but had not yet promoted.

What it does not carry (v1): zones and routes (their shapes have their own
history — redraw them at HQ), documents not filed against a report, record
photos, boards and map packs. Deleting a record on the field server is not
sent home; archive it instead, and the archive comes home as a proposed change.

## At HQ: import it

**Admin → Field sync → Take in → Import field package.** Nothing in the case
file changes. The result says what is waiting:

- **New records** and **changes** go to **Review → Extraction**, marked
  *Field server*.
- **Links** go there too.
- **Reports** go to **Review → From the field**, the inbox phone reports use.

Importing the same package twice is refused, and a package cannot be imported
on the console that made it.

## Review what came home

Work down the Review queue — records come first, so links arrive with their
ends already settled.

**A new record.** If HQ has records that look like the same thing — same or
similar name, accents and *Ltd*/*Inc* ignored — they are listed with how alike
they are, and an exact match is preselected:

- **A new record** — accept it as made in the field.
- **Same as …** — it is a record HQ already has. Nothing new is created; the
  field's id is remembered as that record, so links and reports that mention
  it attach to HQ's.

**A change to a record HQ already has.** Each changed field is shown with HQ's
value beside the field's. Untick anything you disagree with, then **Apply
ticked changes** — or **Keep HQ's** to dismiss the lot. When HQ changed the
same field during the deployment, this is where you choose.

**A link.** Once both of its records are accepted (or matched) it shows both
names and is a one-click accept, keeping the grading the field gave it. If one
end is still waiting, accept that record first and the link fills in by
itself. You can also create the missing end from the link card; the record's
own proposal is then closed, so it is never made twice.

**A report.** In **From the field**, promote it as you would a phone report. It
becomes a draft report saying which field server it was written on, by whom
and when, with its attachments, and linked again to the records it was linked
to there — using HQ's record wherever the field's was matched.

## Later packages

Keep working in the field and send home again. Each package carries only what
changed since the one before. A record the field created that HQ has already
accepted comes home as a *change* to HQ's record, not as a second new one. A
newer package's word about a record replaces an older proposal still waiting
in the queue.

**Packages taken in** (under Admin → Field sync, at HQ) lists every import and
how much of it is still waiting for review.
