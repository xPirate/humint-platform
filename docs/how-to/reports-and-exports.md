# How to write reports and export packages

---

## Write a report

1. **Reports → + New Report**.
2. Write it. **@-mention records** as you go; the link is made both ways —
   the report lists the record and the record lists the report.
3. Set the **credibility rating** (how good the sourcing is) and the
   **precedence** — Flash, Immediate, Priority or Routine (how fast someone
   needs to read it). They're independent: a Flash report can be poorly
   sourced, and saying so is the honest thing.
4. Leave it as **draft** while working; set **confirmed** when it's done.
   Drafts untouched for two weeks show on the dashboard.

Write what the file supports and say where it's thin. The exercise's final
assessment recommends corroborating its weakest link before acting — copy
that shape.

## Run a guided debrief

**Reports → Start a debrief** walks an interview in five steps and files an
ordinary report (plus any entities) at the end.

**When the source can't give an address:** on **When & where**, press
**Point at it on the map** and let them point. Name it in their words ("the
yard behind the grain store"); it becomes a Location with real coordinates
when you file. Nothing is written until you file, so an abandoned debrief
leaves nothing behind. Download the area's map tiles beforehand.

---

## Export something

| You want | Do this |
|---|---|
| One report as a PDF | **Export PDF** on the report's page. |
| Everything about one record, for someone outside the platform | **Export** on the record's page — see below. |
| The last N days for a briefing | **Executive summary** on the dashboard. |
| A printable most-wanted sheet | **Print sheet** on the BOLO board — see below. |
| The whole instance | Not an export — [take a backup](backup-and-restore.md). |

Set `PDF_HEADER_LABEL` and `PDF_FOOTER_NOTE` in `.env` before sending anything
to anybody; every PDF carries them.

### Export a target package or dossier

For handing a complete, stand-alone file to someone who will never log in — a
police unit, a regulator such as the FCC, a partner agency.

1. Open the record → **Export** (or right-click → **Export a dossier**).
2. Pick a shape. On an Organization the first is **Organisation report**
   (structure, membership, holdings); otherwise **Target package** or **Plain
   dossier**. They differ only in how connections are grouped.
3. Fill in, optionally:
   - **Prepared for** — e.g. *County Sheriff — Investigations*.
   - **Purpose** — e.g. *Referral of unlicensed transmissions*.
   - **Include every contact point, not only the preferred ones** — ticked by
     default.

   All three are printed on the cover and recorded in the audit log.
4. **Build PDF.**

What's in it:

- **Cover** — portrait, identifying details, a BOLO band if it's on the board,
  prepared-for and purpose, and a contents list.
- **1 · The record** in full, with contact points.
- **2 · Connections** — every directly linked record, with grades; expired
  links marked.
- **3 · Timeline** of reports, events and links.
- **4 · Reporting in full** — every report that mentions it, oldest first,
  with their photographs.
- **5 · Photographs and documents** on the record.

It does **not** go more than one step out. **Read it before handing it over**
— it carries everything in those reports.

### Print the BOLO sheet

1. Open the BOLO board → **Print sheet**.
2. Pick a layout:
   - **Grid** — six to a page, for a noticeboard.
   - **One to a page** — large photo and everything that helps recognise
     them.
3. **Printed on every page:** a line of your own, e.g. *If seen: do not
   approach, call 555-0100*. It's remembered for next time.
4. **Build PDF**, then print.

Only active lookouts are included, most urgent first. The sheet shows when it
was printed: **reprint when the board changes, and take the old one down.**
The BOLO board has to be switched on
([Configure the instance → Boards](configure-the-instance.md#boards)).
