# How to bring material in, review it and merge duplicates

The working loop:

```
  material in  →  review what was proposed  →  merge duplicates
       ↑                                              ↓
    export   ←   write the report   ←   grade the links
```

**Nothing a model proposes reaches the case file until a person accepts it.**

Learn it on the exercise set in [`docs/exercise/`](../exercise/BRIEFING.md)
before real material — mistakes there are free.

---

## Add a document

**Documents** tab, then either:

- **Drop a file** — PDF, image, `.docx`, `.txt`. Scans are OCR'd.
- **Paste text** into the box below — an intercept, a forwarded message, a
  transcript. Give it a name, or the first line is used.

Status goes *Waiting → Reading → Read*. Long documents on a Pi can take
minutes; carry on working meanwhile. A document doesn't need to belong to
anything yet — the inbox is for material you haven't placed.

### Record something the model missed

Open the document, then:

- **Select the name in the text** → press the button that appears under the
  selection. The entity form opens with the name filled in and the sentence
  kept as evidence.
- Or **+ Add entity** for something the document implies but never names.

You stay on the document. What you add is listed on the right under "added by
hand from this document", and **Review → From: Added by hand** finds it all
later.

### Keep a whole document as a Record

For documents that matter as documents — an insurance letter, a bank
statement, a registration printout:

1. Open it → **Save as Record**.
2. Check **name, kind, date and issuer**. Use the date printed on the
   document, not today's.
3. **Link to:** everything already accepted from the document is ticked.
   Untick what doesn't belong; search to add more.
4. Fix any OCR mistakes in **Full text** if you want. The Record keeps its own
   copy.
5. Leave **Move the original file onto the Record** ticked to take it out of
   the inbox and onto the Record's attachments.

A document can be saved as a Record once. You can also make Records by hand
(**+ New Entity → Record**) or import them from CSV.

### A document says *Read* but proposed nothing

The model was probably down when it was read. Open it → **Read again**. After
an outage that hit several, use **Read empty ones again** on the inbox
toolbar. Decisions you've already made are left alone.

---

## Work the review queue

**Review** tab. Two queues:

- **Extraction** — records and links proposed from documents, the signal
  pass, or the assistant.
- **Correlation** — "these two records look like the same thing".

Every card shows its evidence: which document and sentence, which rule, what
it matched. **Judge the evidence, not the score.**

### The order that saves time

1. Filter **Every document** to one source — review document by document, the
   way the material arrived.
2. Filter **Entities only** and work through them.
3. Then **Relationships only**. A link can only be accepted once both ends
   exist, so entities first saves constant detours.

### What to do with each card

| Press | When |
|---|---|
| **Accept** | It belongs in the file. Links arrive graded **3 — possibly true**; adjust later ([records and links](records-and-links.md#grade-a-link)). |
| **Edit**, then accept | Right idea, wrong spelling, wrong type, or wrong record on one end. |
| **Dismiss** | It doesn't belong. That's the job, not a failure — a queue where you accepted everything wasn't reviewed. |

If a proposal names a record that doesn't exist yet, the card offers to create
it as part of accepting.

### When the queue is huge

Usually after a bulk import or a new feed.

1. Filter correlation by similarity **below 80%**. That's the weak tail —
   alike in wording, not in fact.
2. Tick rows or **Select all shown** → **Not a match**. If the filter matches
   more than fits on screen, the bar offers to act on the whole set and shows
   the count twice before doing anything.
3. Work **above 90%** by hand. That's where real duplicates are.
4. If a feed caused it, fix the feed's limits
   ([Configure the instance → Feeds](configure-the-instance.md#feeds)).

### Signal-pass proposals

With link signals on, a SQL pass proposes links from shared surnames,
addresses, contact details and co-mentions. Treat the low-confidence ones
sceptically: two people on a national calling channel aren't associates; two
people sharing an unlisted mobile probably are.

---

## Merge duplicates

The same person named four ways across six documents is normal, not a bug.

**From a correlation card:**

- **Merge into one** — they're the same thing.
- **Same, but keep both** — they're the same subject but you want them kept
  apart.
- **Not a match** — the pass was wrong.

**From the Entities page:** **Select to merge** → tick two or more →
**Merge selected**.

Then, in the merge dialog:

1. **Read the preview** — how many links, report links, attachments and
   contacts move, which blanks get filled, and any link dropped because a
   record can't link to itself. **There is no one-click undo.**
2. **Pick the survivor.** It defaults to the record with the most on it.
   Blank fields on the survivor are filled from the others; filled fields are
   never overwritten.
3. **Rename it here if needed** — e.g. a street, town and postcode filed as
   three Locations: select all three, merge, and type the full address as the
   name in the same step.

The others are archived with a pointer to the survivor, so old exports and
audit entries still resolve.

### Merging records of different kinds

Say one company was filed as both a Person and an Organization. Select both;
the dialog asks you to tick a box confirming the mix. Then choose **Keep it
as** the kind you want. The preview lists exactly which kind-specific fields
the odd one loses (a date of birth has nowhere to go on an Organization).
Everything else moves.

---

## Delete noise permanently (admins)

Merging is for two records that are the same thing. Some records aren't
anything: "ATTACHMENT A", "Page 2 of 4". Archive hides; delete removes.

- **One:** open it → **Delete**.
- **Several:** Entities → **Select to merge** → tick them → **Delete
  selected**.
- **A report or document:** the **Delete** button on its own page.

The dialog counts what goes and makes you type DELETE. It **refuses** if a
confirmed report cites the record (archive it, or unlink it first); a draft
citing it is only a warning. It's audited, and **only a backup restore brings
it back.** Don't delete real records you've finished with — archive those.

---

## Habits worth having

- **Review before the queue gets long.** Twenty cards is a session; two
  hundred is skimming, and skimming lets bad proposals in.
- **Merge as you go.** Duplicates breed.
- **Write the note when you make the decision.** You won't remember why later.
- **Check the dashboard daily** — urgent reports, stale drafts, records due to
  archive, anyone whose disposition isn't *at liberty*.
- **Back up before anything large** — a bulk import, a big merge session.
