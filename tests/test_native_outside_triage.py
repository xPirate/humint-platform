"""The native app and the model's triage of outside events: kept incidents
show its category, severity and summary; "N set aside" shows what it filtered
with its reason; "Keep it" and "Wrong call?" correct it; Admin → Outside
events has the Model triage card."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import PASSWORD, ROOT, Console, check, finish  # noqa: E402

sys.path.insert(0, os.path.join(ROOT, "native", "tools"))
from shoot import FakeMachine  # noqa: E402
from appdriver import AppDriver  # noqa: E402

SHOTS = os.environ.get("SHOTS")
c = Console("native_outside_triage").start()
api = c.register_admin("ana")
zone = api.post(c.url + "/api/map/zones", json={
    "name": "Baltimore AOR", "environment": "Semi-permissive", "outside_events": True,
    "geometry": {"shape": "rectangle", "points": [[39.37, -76.72], [39.37, -76.52], [39.19, -76.52], [39.19, -76.72]]}}).json()
ZID = zone["id"]
c.sql("UPDATE outside_event_settings SET triage_enabled = true, triage_min_severity = 2")


def add(sid, title, is_event, in_area, cat, sev, summary, reason):
    return c.sql(
        f"INSERT INTO outside_events (source, source_id, occurred_on, title, category, lat, lon, place, precision, "
        f"url, zone_ids, triage_is_event, triage_in_area, triage_category, triage_severity, triage_summary, "
        f"triage_reason, triage_by, triage_model, triaged_at) VALUES ('gdelt', '{sid}', current_date, '{title}', "
        f"'Fight', 39.29, -76.61, 'Baltimore, Maryland, United States', 'city', 'https://news.example.org/{sid}', "
        f"ARRAY[{ZID}], {is_event}, {in_area}, '{cat}', {sev}, '{summary}', '{reason}', 'model', 'qwen3:8b', now()) "
        f"RETURNING id")[0][0]


fire = add("G1", "Use unconventional violence", "true", "true", "disaster", 4,
           "Harbor Tunnel closed after a truck fire near the south portal.", "A closure affecting movement.")
arrest = add("G2", "Arrest, detain: Police", "true", "true", "police", 2,
             "Police arrested two after a protest at City Hall.", "A local arrest.")
film = add("G3", "Use conventional military force: Actor", "false", "true", "other", 1,
           "An actor talks about playing a soldier in a war film.", "A film role, not an event.")
tokyo = add("G4", "Demonstrate or rally", "true", "false", "protest", 2, "Thousands rallied in Tokyo.", "It happened in Tokyo.")

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

# ---- Admin ----
d.tap("Admin")
d.until(lambda: d.button("Outside events") is not None, what="admin")
d.tap("Outside events")
d.until(lambda: d.has_text("Have the model triage incoming GDELT incidents"), what="triage card")
check(d.has_text("2 judged by the model") or d.has_text("4 judged by the model"), "the card shows what was judged")
check(d.has_text("Each area's focus"), "with each area's focus")
d.set_field("Model", "qwen3:14b")
d.tap("Save")
d.until(lambda: c.sql("SELECT triage_model FROM outside_event_settings")[0][0] == "qwen3:14b", what="model saved")
check(True, "the triage model saves")
shot("95-admin-triage")

# ---- the page ----
d.tap("Dashboard")
d.pump(0.5)
d.tap("Outside events")
d.until(lambda: d.has_text("2 incidents"), what="page")
check(d.has_text("Harbor Tunnel closed after a truck fire near the south portal.") and d.has_text("Disaster or emergency")
      and d.has_text("4 · significant"), "kept incidents show the model's summary, category and severity")
check(not d.has_text("Thousands rallied in Tokyo."), "what it set aside is not in the list")
shot("96-outside-triage")
d.tap("2 set aside")
d.until(lambda: d.has_text("A film role, not an event."), what="set aside")
check(d.has_text("It happened in Tokyo."), "the set-aside view shows each with its reason")
shot("97-outside-set-aside")
d.tap("Keep it")
d.until(lambda: c.sql(f"SELECT count(*) FROM outside_events WHERE triage_by = 'analyst'")[0][0] == 1, what="kept")
check(True, "\"Keep it\" puts one back, as a person's call")
d.tap("← What it kept")
d.until(lambda: d.has_text("3 incidents"), what="back")
d.tap("Wrong call?")
d.until(lambda: d.has_text("The model's call"), what="dialog")
d.tap("In the area")
d.tap("Save")
d.until(lambda: c.sql("SELECT count(*) FROM outside_events WHERE triage_by = 'analyst'")[0][0] == 2, what="corrected")
check(c.sql("SELECT count(*) FROM outside_triage_corrections")[0][0] == 2, "corrections are kept as examples")
check(not errors, f"no QML errors ({errors[:3]})")
finish()
