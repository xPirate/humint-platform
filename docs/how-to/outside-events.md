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
- Unread and dismissed events are deleted after the retention window
  (90 days by default). Ones sent to Documents stay.

## On a field server

It works the same. The server pulls only while it has internet, so join a
network before deploying (Box → Actions → Join Wi-Fi), let it fill in, and
what it gathered stays on the server, inside the encrypted case file.
