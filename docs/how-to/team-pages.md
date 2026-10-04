# How to use the team pages

Your profile, the analyst search, the three optional boards, feeds and the
assistant. A board's tab only appears once an admin switches it on
([Configure the instance → Boards](configure-the-instance.md#boards)).

---

## Keep your profile up to date

Account menu → **My profile → Edit profile**.

- Name, callsign, role.
- **Contacts:** **+ Add contact** for each way to reach you — a radio channel,
  a Meshtastic node, a MeshCore address, email, mobile, a social handle. Pick
  a kind or type your own. As many or as few as you use.
- **Status:** At liberty, Under duress, Incapacitated, Captured, Deceased.
  Keep it honest; it's what the team checks when someone misses a check-in.

Everyone signed in can see your profile; an admin can edit it. More in
[Manage users and profiles](users-and-profiles.md#fill-in-or-edit-a-profile).

## Find everything one analyst entered

Either:

- type their username in the top search box and pick **Everything entered by
  …**, or
- account menu → **Search by analyst**, or
- click **Entered by …** on any record.

The page lists every entity, report, link, document and field report they
created, newest first, grouped by day, with counts per kind at the top and
their profile card above. Filter by title or date range; click a row to open
it. It has its own address (`#analyst/<name>`) — open it in a new tab,
bookmark it, or send it.

## Roster

Cards for the team: portrait, callsign, role, how to reach them. Click to open
the record. The photo is the record's portrait — upload an image to it and
press **Use as portrait**.

## BOLO — post a lookout

1. BOLO tab → **Post a lookout**.
2. Pick the record (any type — person, vehicle, place).
3. Write **what to do if you see it**. That's the content, not the fact that
   it's wanted.
4. Set the **urgency** (the coloured band across the photo).
5. Give it a **drop-off date** if it has a natural end. Past that it shows as
   lapsed rather than vanishing.
6. Make sure the record has a portrait — the board, the record page and the
   printed sheet all lead with it.

A record on a board says so at the top of its own page, with the reason.

**Print it:** **Print sheet** — see
[Print the BOLO sheet](reports-and-exports.md#print-the-bolo-sheet).

**When it's over:** **Close out** and say what happened. It moves under
*Show closed*. Don't just remove it — the next person learns nothing from an
entry that disappeared.

## Priorities — track what the team is looking for

1. Give it a **rank** and write the question in full.
2. List **what would tell us**, one per line: `146.520 MHz simplex`,
   `carrier without ID, 5+ seconds`.
3. **Link** anything that already exists as a record — the area, the
   frequency, a vehicle — instead of retyping it.
4. When answered, **Answer it** and write what the answer was. Don't delete
   it; that note is the point.

## Feeds

The **Feeds** tab appears once an admin adds a feed. Nothing from a feed
enters the case file on its own.

- **Send to Documents** on anything worth keeping. It fetches the full
  article (untick **Fetch the full article** for the summary only), then the
  document goes through the usual read → propose → review route. If the fetch
  fails, the document is made from the summary and says why.
- **Dismiss** the rest. Dismissed items stay searchable and never come back
  as unread. After a week away: skim, send the two that matter, **Dismiss all
  shown**.
- A red **!** beside a feed means its last poll failed; the admin page says
  why.

Old items are pruned on a per-feed schedule. Anything you sent is a document
and never pruned.

## Ask the assistant (needs a model)

- **Propose links:** the box at the top of Review — "link the Smiths",
  "connect everyone at the rail yard". Proposals land in the queue.
- **Ask questions:** the **AI Assistant** panel. It sees only your records and
  can't write anything.

It's a reader and a proposer, not a source. Check anything it says against
the record before it goes in a report.

## The dashboard

Check it once a day: urgent reports, forgotten drafts, records lapsing, and
people whose disposition isn't *at liberty* — all computed from your own
records, no model involved.
