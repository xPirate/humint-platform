# How to configure the instance (admins)

Account menu → **Admin settings**. The rail on the left (tabs on a narrow
screen) has these sections; each loads when you open it, and the page
remembers the last one you used.

| Section | Use it to |
|---|---|
| **Users** | Add people, reset passwords, edit profiles — [Manage users](users-and-profiles.md). |
| **RSS feeds** | Add feeds and set their limits — [below](#feeds). |
| **Maps** | Add tile sources, download offline areas — [below](#maps). |
| **Appearance** | Instance name, logo, colour palette. |
| **Model** | The Ollama endpoint and model, and whether it's answering. |
| **Boards** | Switch on Roster, BOLO, Priorities — [below](#boards). |
| **Field devices** | Enroll and revoke phones — [Set up field devices](field-devices.md). |
| **Link signals** | Turn the no-model link-finding pass on or off — [below](#link-signals). |
| **Retention** | Archive records left untouched — [below](#retention). |
| **Audit log** | Every write, who and from where — [below](#audit-log). |
| **Backup & restore** | [Back up and restore](backup-and-restore.md). |

---

## Feeds

### Add a feed

1. **RSS feeds → add**: a URL and a label.
2. **Set the limits before the first poll** — the first poll sees the
   publisher's whole window:
   - **Only items from the last N days** (default 7)
   - **At most N per poll** (default 50)
   - **Keep unread items for N days** — days for a newsroom, a year for a
     monthly bulletin; blank keeps them forever. Editable straight from the
     list when a feed turns out noisier than expected.

Items land on the **Feeds** page, not in the case file. Feeds added before
limits existed have none — set them.

**Internal feeds:** article fetching refuses private and loopback addresses by
default. Set `FEED_FETCH_ALLOW_PRIVATE=true` in `.env` only if your feeds are
genuinely internal — any feed can then make the server fetch anything it can
reach.

### Delete a feed

The dialog counts what the feed put in the case file, then asks what to do
with those Events:

| Choice | Right for |
|---|---|
| **Leave them** | A feed whose records you've built on; only stops polling. |
| **Archive them** | The safe middle — hidden, reversible. |
| **Delete them** | A feed added by mistake. |

Anything cited by a confirmed report is archived rather than deleted whatever
you choose, and the result says how many.

## Maps

### Add a tile source

- **+ Source** — an XYZ template, `https://…/{z}/{x}/{y}.png`.
- **Import ATAK XML** — an ATAK/MOBAC map source file; every
  `<customMapSource>` in it is read. [joshuafuller/ATAK-Maps](https://github.com/joshuafuller/ATAK-Maps)
  is a well-known collection.

**Check the terms before caching anything.** Imported sources arrive marked
not-downloadable; tick it yourself only if you're entitled to cache. The
bundled OpenStreetMap source can't be downloaded at all (OSM's tile policy
forbids it). Put a real contact address in `MAP_TILE_USER_AGENT`.

### Download an area for offline use

1. **+ Download an area**, pick the source.
2. Drag a box over the ground you need.
3. Choose a zoom range. **Tile counts quadruple per zoom level:** 14 is
   street names, 16 is individual buildings; a town to 16 is hundreds of
   thousands of tiles and hours of downloading. Start small — packs stack,
   and repeating an area resumes rather than restarts.
4. Check the tile count and disk estimate, then start.

It runs on the worker in the background. **Stop** keeps what's done.

Packs live in the `mappacks` volume, **not in backups**. Deleting a source
deletes its packs. Watch `docker system df` — this is the one feature that can
fill a disk. Set `MAP_DOWNLOAD_ENABLED=false` on a machine that must never
connect out.

## Boards

**Boards** → switch on only what the team will use. Off takes the tab away
without losing anything.

| Board | For |
|---|---|
| **Roster** | Cards for the team, so people recognise each other. |
| **BOLO** | Anything to recognise on sight, with what to do and how urgent. Includes the printable sheet. |
| **Priorities** | Standing questions, ranked, with what would count as an answer. |

**Rename them** to what your team calls them (Watch bill, Lookouts…) and
write the one-line blurb. Any analyst can post and close entries; it's all
audited under `board.*` and `priority.*`.

## Link signals

The SQL-only pass that proposes links from shared surnames, addresses and
contact details. Proposals go to Review.

- **Switch on / Switch off** — stays that way.
- **Run it for 10 min … 8 hours** — switches itself off afterwards. Best for
  trying it.
- **Run one pass now** — does one pass immediately and reports how many it
  proposed. (The pass has its own 15-minute timer, so a short window might
  not see one.)

The state line shows what's deciding, time left, and the last pass. With no
override it follows `LINK_SIGNALS_ENABLED` in `.env`. Turning it on against an
established file produces a burst — do it on a quiet afternoon.

## Retention

Off until you set it. For standing files that would otherwise fill up with
records nobody has looked at in years.

1. **Set a window per type** — days with no activity. Blank means never.
   Activity means an edit, a new link at either end, a report naming it, or an
   attached document.
2. **Preview.** It shows how many records each window catches and how many
   each exemption spares, changing nothing.
3. Save. Records are flagged **DUE TO ARCHIVE** with a date first, and
   archived only if the grace period passes untouched.

It **archives, never deletes**; anyone can **Keep indefinitely**; **Run now**
skips the hourly wait. Audited under `retention.*`.

**A starting point:** generous windows, both exemptions on, a long grace
period. Preview until the "due" number is one you'd happily read through.
Tighten later.

## Audit log

Account menu → **Audit log**. Every write: who, what, from where. Exports to
CSV.

- **Send it to syslog:** `AUDIT_SYSLOG_ENABLED=true` and the `AUDIT_SYSLOG_*`
  settings in `.env`. Best-effort; never blocks a request.
- **Retention:** kept forever by default (`AUDIT_RETENTION_DAYS=0`). Think
  before shortening it.

Worth knowing: `user.password_reset`, `profile.status`, `export.dossier`
(with prepared-for and purpose), `export.bolo`, `field.device.*`.
