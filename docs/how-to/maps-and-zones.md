# How to use the map, zones and routes

Admins add tile sources and download offline areas —
[Configure the instance → Maps](configure-the-instance.md#maps).

---

## Pick a basemap

**Basemap** at the top of the Map page. Sources marked *downloaded* work
offline. Tick **Downloaded only** to see exactly what someone without a
connection sees: outside downloaded areas the map is blank, not broken.

## Find out what's at a spot

1. Click the map.
2. Read the panel:
   - **The address** (reverse geocoded), with how far from your pin the match
     was — a few metres is the building, forty is next door.
   - **Named places within about a block**, nearest first, with what kind of
     place each is. Check the distance before trusting a name.
   - **An existing Location within 50 m**, if there is one — listed first.
3. Pick one:
   - an existing Location → add to that record instead of creating a second
     one for the same building;
   - an address or named place → a Location form, pre-filled;
   - **Just the coordinates** → a blank Location at that point, for when you
     know what it is and the dataset doesn't.

Whatever you pick notes where the suggestion came from. With no network, you
still get coordinates, a grid square and the nearby-records check, and the
panel says which lookup it couldn't do.

## Mark off an area with a zone

A zone is like a NOTAM for the case: an area, how workable it is, for how
long.

1. Map page → **Zone → Draw**. Choose polygon, rectangle or circle and draw.
2. **Name** it and set the **environment**: green permissive, yellow
   semi-permissive, red non-permissive, dark heavy red denied, grey unknown.
3. Give it an **end time** if it has one.
4. If it's an event (a protest), type an **Event** name. That creates the
   Event record and ties the zone to it, so reports about it gather in one
   place and stay there after the zone ends. Leave blank for standing ground.

Location pins use the same colours from their own environment, so a green pin
inside a red zone stands out. Zones may overlap.

### Update a zone as things change

Open the zone, change the environment, and **fill in why** — *"police line
moved onto the bridge"*. It goes on the zone's timeline with the time and your
name. That's what makes sense of the night when you write it up.

### When a zone ends

It goes faint and dashed but doesn't disappear; its Event keeps every report,
and Locations inside still list it as ended. **Show expired** on the map
toolbar hides ended zones. Only admins can delete a zone (with its timeline) —
letting it expire is the normal way to finish.

**What's underneath:** opening a zone lists the Locations inside it, live. A
Location's page lists the zones over it.

### Link things to a zone

Every zone is a **Zone record**, so a contested area can carry what is known
about it.

1. Click the zone → **Open the zone's record** (or find it under Entities →
   Zone).
2. **+ Add relationship**, as on any record: the organisation holding it
   (`controls`), the events inside it (`located_at`), people seen there
   (`present_at`), routes through it.
3. Link reports to it with an @-mention.

The record page shows the zone on a small map with **Edit zone**, **Timeline &
what's inside**, **Show on the map**, and **Download KML · KMZ**. Archiving the
record takes the zone off the map; deleting it (admins) removes the zone and
its timeline.

---

## Record a route

A Route is a line with a reason: the safe way across a contested city, the
track in to a site in the woods. Three ways to make one:

- **Draw it:** Map page → **+ Route** → click along the way in order (**Undo
  point** if you misclick) → double-click or **Finish** → give it a name,
  **Why** (what it avoids, when it works, who uses it), how workable it is and
  how it is travelled. Drawn routes show **dashed** — a plan, not a track.
- **Import it** from a file — below.
- **Walk it** with the field app — [Handle field reports](field-reports.md).
  Walked routes show solid and keep the time at every point.

Routes are coloured by the same environment scale as zones; blue means not
assessed. Click one for its summary card. On its record: the line on a small
map with a start dot, length, points, **Redraw on the map**, and **Download
KML · KMZ · GPX**. Link it to people, vehicles, zones and reports like any
record.

## Import a KML, KMZ or GPX file

From ATAK, Google Earth, CalTopo, Gaia or a handheld GPS.

1. Map page → **Import…** → choose the file → **Read file**.
2. Check the list. Lines become **Routes**, areas become **Zones**, points
   become **Locations**. Each row has a small drawing of the shape, its
   length or point count, and "timed" if it carries times.
3. Untick what you don't want, rename anything, set each area's environment
   and each route's travel mode.
4. **Import selected.** The map moves to what you imported.

The file is attached to every record made from it. A map file already
attached to a record or report has an **Import to map** button beside it.

## Export routes and zones

- **One record:** on its page, **Download KML · KMZ** (and **GPX** for a
  route).
- **Everything live on the map:** Map page → **Export…** → KMZ (Google Earth,
  ATAK), KML, or GPX (routes only). Ended zones are included when **Show
  expired** is ticked.

Colours carry over as KML styles; walked routes keep their times.

## Print the map

1. Pan and zoom to frame the area, and pick the basemap.
2. **Print map…** → a title, an optional note printed under it, paper size,
   orientation, and what to draw (zones, routes, pins, names, ended zones).
3. **Build PDF.**

You get one page with the map filling it, corner coordinates and grid square,
a scale bar, north arrow, a key, and where the tiles came from. It uses
downloaded areas when there are any, so it works offline; tiles it could not
get are drawn as a plain grid and the page says how many.

Target packages and dossiers include a map automatically — see
[Write reports and export packages](reports-and-exports.md#export-a-target-package-or-dossier).

## Load public reference places in bulk

Police, fire, hospitals and jails for an area, from OpenStreetMap:

1. Run `tools/osm_places_to_csv.py` for a bounding box — see
   [`tools/README.md`](../../tools/README.md).
2. **Entities → Import** → choose **Location** → pick the CSV.

The importer **doesn't deduplicate**: keep the CSV and use `--skip-ids-from`
next time rather than importing twice. OSM is volunteer-made — treat it as a
starting set to correct.
