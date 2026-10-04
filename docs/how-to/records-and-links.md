# How to work with records and links

---

## Grade a link

Every relationship carries a grade on the same 1–6 scale used for reporting.
Machine proposals arrive as **3**; review moves them up as you corroborate and
down as things conflict.

1. Open either record.
2. Press **Edit** on the relationship.
3. Set the **grade**, and write in **Notes** *why* — that's what you'll need
   in three weeks.
4. **Save.**

| Grade | Use it when |
|---|---|
| **1 — Confirmed** | Corroborated by other sources. You'd defend it in a report. |
| **2 — Probably true** | More than one source, or one trusted source with something to lose. |
| **3 — Possibly true** | One source said so, or a machine inferred it. |
| **4 — Doubtful** | Said, but at odds with what else you hold. |
| **5 — Improbable** | Said, and contradicted. Kept so you know it was said. |
| **6 — Cannot be judged** | No basis yet. |

On the network a 1 is drawn heavier than a 3; 4 and worse are dashed. Links
from before v1.7 were converted: confirmed → 1, probable → 2, possible → 3.

The same Edit form changes the link's type, discovery date and expiry.

## Make a link expire

For links that are true for a while, not forever — seen at a café once, a car
parked outside last week.

1. **Edit** the relationship (or set it when adding one).
2. Set **Expires** — or use a quick pick: **1 week, 1 month, 3 months,
   1 year**.
3. **Save.**

After that date the link stays on both records, faded and marked **Expired**,
and expired links sort to the bottom. It drops off the network so one
sighting doesn't become a permanent strand.

- **See expired links on the network:** tick **Show expired links** above it.
  They're drawn faint and dashed.
- **Make it current again:** clear the date, or press **Never**.

Expiry never deletes anything. Exports mark expired links as such.

## Set alignment (and environment for places)

**Alignment** — Friendly, Neutral, Unknown, Hostile — is your call on whose
side a person, organization, source or vehicle is on. The model never
proposes it.

- **Named groups are records**, not a dropdown value. Make "Iron Horse
  Militia" an Organization, give *it* an alignment, link members with
  `member_of`. A member can then be aligned differently from the group.
- A source's alignment is separate from its A–F reliability. Hostile and
  grade A is a real combination.
- **Hostile names show in red** everywhere — tree, page, link lists, search,
  network. Nothing else is coloured.

**Locations get an environment instead:** Permissive, Semi-permissive,
Non-permissive, Denied (not an option at all), Unknown.

Older builds had *Faction* with a *Family* value; kinship now belongs on a
`family_of` link. Records that had Family keep it, shown as retired.

## Give a record a picture

1. On the record, upload an image under **Attachments**.
2. Press **Use as portrait** on it.

The portrait shows in the record's header, on the BOLO board, on the Roster,
on the printed BOLO sheet and on the cover of exported packages. Records
created from a field report get the first photo automatically.

## Read the Entities page

- **The tree** — one branch per type, folded as you leave it, with each
  record's link count.
- **The network** — a dot per record, sized by how many links it has, so the
  thing everything points at stands out. *Hide unconnected* is on by default.
  Search and the type filter drive both panes.

**Arrange it:**

- **Drag** a dot to pin it (dashed ring); the rest makes room.
- **Double-click** a pinned dot to release it.
- **Refit** releases everything and re-runs the layout.

**Click a dot** for a summary card: type, alias, alignment, key fields, link
and report counts, nearest connections with their grades. Click a connection
on the card to walk the chain; **Open record** for the full page;
**Actions ▾** for the right-click menu. Escape closes it.

## Right-click a record

Anywhere a record's name appears — tree, card, network, map, a report's list —
right-click it. On the record's page it's the **Actions** button.

| Item | Use it to |
|---|---|
| **Look for links** | Have the model propose links. They go to Review. |
| **Ask the assistant about this** | Get the file's answer about one subject. |
| **What is missing on this record?** | Decide what to chase next. |
| **Find similar records** | Look for a second file or an alias; flag a duplicate or go straight to merge. |
| **Add a relationship / Write a report about this** | Skip navigating back. |
| **Select to merge** | Start a merge with this one picked. |
| **Export a dossier / Show on the map / Copy name / Copy record ID** | Housekeeping. |

The first four need the model; without it they're greyed out.

## See who entered a record

Each record's page says **Entered by …**. Click the name for everything that
analyst entered ([Use the team pages](team-pages.md#find-everything-one-analyst-entered)).

## Keep a record from being archived

If the instance has a retention policy, a record nobody has touched in a long
time gets an amber **DUE TO ARCHIVE** badge with a date.

- **Any edit, link or report mention** calls that off.
- **Keep indefinitely** (on the page or the right-click menu) makes it
  **HELD** — the policy leaves it alone for good. Any analyst can do this.
- If it was archived anyway: nothing's lost. Find it with **Show archived**
  and press **Reactivate**.

## Closing forms

Click outside a dialog or press Escape to close it. Once you've typed
something, both ask first.
