"""The native app and outside events: marking a zone on the map, the
Admin → Outside events settings (with the fastest-allowed rates), the Outside
events page (filter by area, dismiss, send to Documents), and the map layer."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import PASSWORD, ROOT, Console, check, finish  # noqa: E402

sys.path.insert(0, os.path.join(ROOT, "native", "tools"))
from shoot import FakeMachine  # noqa: E402
from appdriver import AppDriver  # noqa: E402

SHOTS = os.environ.get("SHOTS")
c = Console("native_outside").start()
api = c.register_admin("ana")
zone = api.post(c.url + "/api/map/zones", json={
    "name": "Baltimore AOR", "environment": "Semi-permissive",
    "geometry": {"shape": "rectangle", "points": [[39.37, -76.72], [39.37, -76.52], [39.19, -76.52], [39.19, -76.72]]}}).json()
# Events as the worker would leave them.
for i, (title, src, lat, lon) in enumerate([
        ("Demonstrate or rally: Protester → Police", "gdelt", 39.2904, -76.6122),
        ("Arrest, detain, or charge with legal action: Police → Suspect", "gdelt", 39.285, -76.605),
        ("Peaceful protest: Protesters (United States)", "acled", 39.30, -76.61)]):
    c.sql(f"INSERT INTO outside_events (source, source_id, occurred_on, title, category, lat, lon, place, precision, "
          f"num_sources, url, zone_ids) VALUES ('{src}', 'X{i}', current_date, '{title}', 'Protest', {lat}, {lon}, "
          f"'Baltimore, Maryland, United States', 'city', 3, 'https://news.example.org/{i}', ARRAY[{zone['id']}])")

m = FakeMachine()
m.unlock()
m.start(console_url=c.url)
d = AppDriver(m.sock, console_url=c.url)
errors = []
from PySide6.QtCore import qInstallMessageHandler  # noqa: E402


def on_msg(kind, ctx, msg):
    if ("qml" in msg.lower() or ".qml" in msg) and "Proxy denied" not in msg and "tiles.invalid" not in msg:
        errors.append(msg)
    sys.stderr.write(msg + "\n")


qInstallMessageHandler(on_msg)


def shot(name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        d.shot(os.path.join(SHOTS, name + ".png"))


d.login("ana", PASSWORD)

# ---- the zone, marked on the map --------------------------------------------------------
d.tap("Map")
d.until(lambda: d.has_text("Zones (1)"), what="map")
check(d.has_text("Outside events, last week (3)"), "the map has an outside-events layer")
# Edit the zone (selecting it through the page, as a tap on it would).
page = next(i for i in d.items() if i.property("zoneItems") is not None and i.property("outsideItems") is not None)
page.setProperty("selected", {"kind": "zone", "data": page.property("zoneItems")[0]})
d.until(lambda: d.button("Edit") is not None, what="zone card")
d.tap("Edit")
d.until(lambda: d.has_text("Pull outside events for this area (GDELT, ACLED)"), what="zone form")
d.tap("Pull outside events for this area (GDELT, ACLED)")
shot("90-zone-outside")
d.tap("Save")
d.until(lambda: c.sql(f"SELECT outside_events FROM map_zones WHERE id = {zone['id']}")[0][0] is True, what="zone marked")
check(True, "a zone is marked as an area from its edit form")

# ---- Admin → Outside events ---------------------------------------------------------------
d.tap("Admin")
d.until(lambda: d.button("Outside events") is not None, what="admin")
d.tap("Outside events")
d.until(lambda: d.has_text("Pull events from GDELT"), what="outside settings")
check(d.has_text("Baltimore AOR") and d.has_text("At least 15: GDELT publishes every 15 minutes.")
      and d.has_text("At least 5: GDELT's limit."), "the areas, and GDELT's floors, are on the page")
d.tap("Pull events from GDELT")
d.set_field("Check every (minutes)", "5")
d.tap("Save")
d.until(lambda: d.has_text("between 15 and 10080"), what="refusal")
check(c.sql("SELECT gdelt_enabled FROM outside_event_settings")[0][0] is False,
      "going under GDELT's interval is refused, and nothing is saved")
d.tap("Fastest the terms allow")
d.until(lambda: c.sql("SELECT gdelt_enabled, gdelt_interval_minutes, gdelt_request_spacing_seconds "
                      "FROM outside_event_settings")[0] == (True, 15, 5), what="fastest")
shot("91-admin-outside")
check(True, "\"Fastest the terms allow\" saves GDELT at every 15 minutes, 5 s apart")

# ---- the page -------------------------------------------------------------------------------------
d.tap("Dashboard")            # out of Admin (its section has the same name)
d.pump(0.5)
d.tap("Outside events")
d.until(lambda: d.has_text("What open sources say is happening in your areas."), what="page")
d.until(lambda: d.has_text("3 events"), what="events")
shot("92-outside-events")
check(d.has_text("Data: GDELT Project (gdeltproject.org)") and d.has_text("ACLED, Armed Conflict Location"),
      "GDELT and ACLED are credited")
check(d.has_text("Baltimore, Maryland, United States · placed at city level · 3 sources"), "with where and how sure")
d.tap("Dismiss")
d.until(lambda: d.has_text("2 events"), what="dismissed")
d.tap("Send to Documents")
d.until(lambda: d.has_text("Fetch the article it came from"), what="send dialog")
d.tap("Fetch the article it came from")      # no internet here: no fetch
d.tap("Send")
d.until(lambda: c.sql("SELECT count(*) FROM outside_events WHERE status = 'sent'")[0][0] == 1, what="sent")
check(c.sql("SELECT source_note FROM attachments")[0][0].startswith("Outside event:"),
      "sent to Documents, saying where it came from")
check(not errors, f"no QML errors ({errors[:3]})")
finish()
