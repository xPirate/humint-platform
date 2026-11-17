# Fill in your areas with outside events (GDELT, ACLED)

You want to know what open sources say is happening inside an area you are
responsible for — a box over Baltimore, a district, a route corridor —
without reading the news all day.

Mark the area as a zone, turn on a source, and the server pulls the events
placed inside it whenever it has internet. They arrive on the **Outside
events** page and as violet dots on the map. Like feed items, they stop
there: machine-gathered, unverified. The ones that matter go to Documents.

## The sources

| | GDELT | ACLED |
|---|---|---|
| What | The world's news coded into events (who did what to whom, where) by machine | Political violence and protest, coded by hand and checked |
| How fresh | A new file every 15 minutes | Weekly |
| Account | None | myACLED, at a level that includes the API (Research and up). A personal email gets Open, which has none. |
| Terms | Any use; cite GDELT and link to it (the page does) | Its licence decides what you may keep and how |
| Noise | High: one story becomes several events, places get guessed | Low |
| US cities | Yes | In ACLED's US monitor (Partner level and up) |

UCDP is not included: it covers armed conflict with at least 25 deaths a
year, updated yearly — next to nothing for a city.

## Turn it on

1. **Mark an area.** On the map, draw a zone (or open one and choose
   **Edit**) and tick **Pull outside events for this area**. Any shape works;
   events are kept only if they fall inside it. An expired zone stops pulling.
2. **Admin → Outside events.** Tick **Pull events from GDELT**. For the
   quickest updates GDELT's terms allow, press **Fastest the terms allow**
   (check every 15 minutes, 5 seconds between requests). Save.
3. For ACLED, enter the myACLED email and password, tick **Pull events from
   ACLED**, and save. The password stays on the server, is never shown again,
   and is left out of backups.
4. **Pull now** asks at once instead of waiting for the next check.

The first pull fills in the last day (**Fill in after time offline**, up to
a week). After time offline it catches up the same way.

## The rates, and why

| Setting | Fastest allowed | Why |
|---|---|---|
| GDELT: check every | 15 minutes | GDELT publishes a new file every 15 minutes; checking more often finds nothing new. |
| GDELT: between requests | 5 seconds | GDELT's API allows one request every 5 seconds. Applied to every request this server makes to GDELT, files included. |
| ACLED: check every | 60 minutes | ACLED updates weekly; daily (the default) is plenty. |
| ACLED: between requests | 1 second | ACLED publishes no number; this keeps it polite. |

These floors are enforced by the settings form, the API, the database and
the worker. Nothing can set a faster rate, even by editing the database by hand.

## Cutting the noise (GDELT)

- **Event types kept**: CAMEO categories. The default is the conflict end:
  threaten, protest, show of force, coerce (arrests), assault, fight, mass
  violence. Add *Provide aid* or *Investigate* if they matter to you.
- **Reported by at least**: raise to 2 or 3 to drop single-source stories, at the cost of the first reports.
- **Only events placed at a city or finer** (on by default): a story GDELT
  can only place at "Maryland" lands on the middle of the state, which is
  noise inside a city box.

## Working the page

- The left rail lists your areas and what is unread in each.
- Each event shows its source (GDELT/ACLED), type, date, place, how precisely
  it was placed and how many sources reported it.
- **Send to Documents** makes it a document: where it came from is written
  at the top, and the article is fetched when there is one. Extraction and
  Review follow as for any document. This is the only way an outside event
  reaches the case file.
- **Dismiss** keeps it from coming back as new. **Mark read** keeps it open
  without the unread count.
- **On the map** centres the map on it.
- **Read** (or the headline) opens the article in a panel beside the list,
  in reader form: the headline and paragraphs, without the site's menus and
  adverts. **Next** and **Previous** (or → and ←) walk the list without
  closing it, **Esc** closes it, and opening one marks it read. The panel has
  Send to Documents and Dismiss too, and **The original** for the publisher's
  page (on the box, a QR code to open it on a phone).
- Unread and dismissed events are deleted after the retention window
  (90 days by default). Ones sent to Documents stay.

## Reading and duplicates

The server fetches each article itself and keeps the text, so it opens at
once, reads offline later (on a field server, after it has left Wi-Fi), and
the headline can be compared. **Admin → Outside events → Reading and
duplicates**:

- **Read each new incident's article ahead** (on by default). The worker
  fetches them in batches, waiting at least **2 seconds between two requests
  to the same news site** (1 at the least), up to **60 per pass**. Only
  public addresses are fetched, checked again at every redirect. A page built
  by scripts or behind a paywall says so; open the original instead.
- **Fold duplicates by rule** (on by default). One incident is often many
  rows: GDELT codes every article separately, and wire stories run on dozens
  of sites. Folded under the first report are
  - rows from the same article;
  - the same kind of event (CAMEO code, or ACLED sub-event type) at the same
    place (within about 1 km) on the same day, from the same source;
  - near-identical headlines in the same areas within a day.
- **Also ask the model** (off by default): the headline and opening of each
  article are turned into an embedding by the Ollama embedding model set
  under Admin → Model (`nomic-embed-text`, say), and reports that are close
  enough are folded, which catches the same story in other words, and GDELT
  and ACLED reporting the same incident. **How alike** sets how close
  (0.86 by default; higher folds less). Check a few groups after turning it
  on and adjust.

On the page, an incident shows **+N similar reports**; opening it lists
them, with why each was matched. **Not the same** takes a wrong match out
for good. Nothing is deleted by folding, and what you do to the incident
(read, dismiss, send) applies to its reports; a story you dismissed stays
dismissed when another site reports it later. Unread counts and the map count
incidents, not rows.

## On a field server

It works the same. The server pulls only while it has internet, so join a
network before deploying (Box → Actions → Join Wi-Fi), let it fill in, and
what it gathered stays on the server, inside the encrypted case file.
