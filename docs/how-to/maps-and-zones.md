# How to use the map and zones

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

## Load public reference places in bulk

Police, fire, hospitals and jails for an area, from OpenStreetMap:

1. Run `tools/osm_places_to_csv.py` for a bounding box — see
   [`tools/README.md`](../../tools/README.md).
2. **Entities → Import** → choose **Location** → pick the CSV.

The importer **doesn't deduplicate**: keep the CSV and use `--skip-ids-from`
next time rather than importing twice. OSM is volunteer-made — treat it as a
starting set to correct.
