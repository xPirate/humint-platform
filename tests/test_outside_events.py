"""Outside events: GDELT and ACLED events inside zones marked as areas of
responsibility. The worker runs here against a stand-in for each service
(GDELT's file server, ACLED's OAuth and API), serving files laid out exactly
as GDELT's codebook gives them; the page, the settings and sending one to
Documents go through the real API."""
import hashlib
import http.server
import io
import json
import os
import sys
import threading
import time
import urllib.parse
import zipfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import ROOT, Console, check, finish  # noqa: E402

c = Console("outside").start()
admin = c.register_admin()
ana = c.add_user(admin, "ana", role="analyst")

# ---- zones: Baltimore marked as an area, a second one not --------------------------------
BALT = [[39.37, -76.72], [39.37, -76.52], [39.19, -76.52], [39.19, -76.72]]
r = admin.post(c.url + "/api/map/zones", json={
    "name": "Baltimore AOR", "environment": "Semi-permissive",
    "geometry": {"shape": "rectangle", "points": BALT}, "outside_events": True})
check(r.status_code == 201 and r.json()["outside_events"] is True, f"a zone can be marked as an area ({r.text[:200]})")
balt = r.json()["id"]
r = admin.post(c.url + "/api/map/zones", json={
    "name": "Annapolis", "environment": "Permissive",
    "geometry": {"shape": "circle", "lat": 38.978, "lon": -76.49, "radius_m": 3000}})
anna = r.json()["id"]
check(r.json()["outside_events"] is False, "and is not, unless asked")

# ---- settings: off by default, floors from GDELT's terms -----------------------------------
s = admin.get(c.url + "/api/admin/outside-events/settings").json()
check(s["gdelt_enabled"] is False and s["acled_enabled"] is False, "nothing is fetched until an admin turns a source on")
check(s["limits"]["gdelt_interval_minutes"]["min"] == 15 and s["limits"]["gdelt_request_spacing_seconds"]["min"] == 5,
      "GDELT's floors: every 15 minutes (its publishing interval), 5 s between requests (its API's limit)")
check([z["name"] for z in s["zones"]] == ["Baltimore AOR"], "the settings list the marked zones")
for bad in ({"gdelt_interval_minutes": 5}, {"gdelt_request_spacing_seconds": 1}, {"gdelt_root_codes": ["99"]}):
    r = admin.put(c.url + "/api/admin/outside-events/settings", json=bad)
    check(r.status_code == 400, f"refused: {bad}")
try:
    c.sql("UPDATE outside_event_settings SET gdelt_request_spacing_seconds = 1")
    check(False, "the database itself refuses going under GDELT's limit")
except Exception as e:
    check("check" in str(e).lower(), "the database itself refuses going under GDELT's limit")
r = ana.put(c.url + "/api/admin/outside-events/settings", json={"gdelt_enabled": True})
check(r.status_code == 403, "settings are for admins")
r = admin.put(c.url + "/api/admin/outside-events/settings",
              json={"gdelt_enabled": True, "gdelt_interval_minutes": 60, "gdelt_request_spacing_seconds": 30})
r = admin.put(c.url + "/api/admin/outside-events/settings", json={"fastest": True, "gdelt_backfill_hours": 1})
s = r.json()
check(r.ok and s["gdelt_interval_minutes"] == 15 and s["gdelt_request_spacing_seconds"] == 5,
      "\"fastest\" sets each source to the quickest its terms allow")

# ---- a stand-in GDELT ------------------------------------------------------------------------
latest = datetime.now(timezone.utc).replace(second=0, microsecond=0)
latest = latest.replace(minute=latest.minute - latest.minute % 15)
stamps = [(latest - timedelta(minutes=15 * i)).strftime("%Y%m%d%H%M%S") for i in (4, 3, 2, 1, 0)]


def row(eid, lat, lon, root="14", code="141", base="141", geo="3", sources="3",
        a1="PROTESTER", a2="POLICE", place="Baltimore, Maryland, United States", url=None):
    r = [""] * 61
    day = latest.strftime("%Y%m%d")
    r[0], r[1], r[2], r[3], r[4] = str(eid), day, day[:6], day[:4], "2026.8630"
    r[6], r[16] = a1, a2
    r[25], r[26], r[27], r[28], r[29], r[30] = "1", code, base, root, "3", "-6.5"
    r[31], r[32], r[33], r[34] = "6", sources, "5", "-4.2"
    r[51], r[52], r[53], r[56], r[57] = geo, place, "US", str(lat), str(lon)
    r[59] = latest.strftime("%Y%m%d%H%M%S")
    r[60] = url or f"https://news.example.org/story/{eid}"
    return "\t".join(r)


files = {
    # The newest file: a protest downtown, an arrest in the harbor, a state-level
    # "Maryland" (centre of the state — dropped), a statement (type not kept),
    # one with a single source, and Annapolis (zone not marked).
    stamps[4]: [row(1001, 39.2904, -76.6122), row(1002, 39.2850, -76.6050, root="17", code="173", base="173",
                                                    a1="POLICE", a2="SUSPECT"),
                row(1003, 39.30, -76.60, geo="2", place="Maryland, United States"),
                row(1004, 39.29, -76.61, root="01", code="010", base="010"),
                row(1005, 38.978, -76.49, place="Annapolis, Maryland, United States")],
    stamps[3]: [row(1010, 39.31, -76.62, root="18", code="1823", base="182", a1="GUNMAN", a2="CIVILIAN")],
    # stamps[2] missing: GDELT skips the odd interval (404)
    stamps[1]: [row(1020, 39.25, -76.66, root="14", code="145", base="145", sources="1")],
    stamps[0]: [row(1030, 39.28, -76.58)],     # older than the 1-hour backfill: never asked for
}
zips = {}
for st, rows in files.items():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(f"{st}.export.CSV", "\n".join(rows) + "\n")
    zips[st] = buf.getvalue()
hits = []


class GDELT(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        hits.append((time.monotonic(), self.path, self.headers.get("User-Agent")))
        name = self.path.rsplit("/", 1)[-1]
        if name == "lastupdate.txt":
            z = zips[stamps[4]]
            body = (f"{len(z)} {hashlib.md5(z).hexdigest()} http://x/gdeltv2/{stamps[4]}.export.CSV.zip\n"
                    f"1 0 http://x/gdeltv2/{stamps[4]}.mentions.CSV.zip\n").encode()
        elif name.endswith(".export.CSV.zip") and name.split(".")[0] in zips:
            body = zips[name.split(".")[0]]
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


g = http.server.ThreadingHTTPServer(("127.0.0.1", 0), GDELT)
threading.Thread(target=g.serve_forever, daemon=True).start()
os.environ["GDELT_BASE"] = f"http://127.0.0.1:{g.server_port}/gdeltv2"

c.worker_env()
import outside_events as W  # noqa: E402
import zone_geo  # noqa: E402

# The worker's copy of the zone geometry agrees with the API's.
sys.path.insert(0, os.path.join(ROOT, "api"))
import importlib  # noqa: E402
api_zones = importlib.import_module("zones")
probe = {"min_lat": 0, "max_lat": 2, "min_lon": 0, "max_lon": 2, "shape": "polygon", "radius_m": None,
         "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [1, 2], [0, 0]]]}}
pts = [(0.5, 0.5), (1.9, 1.9), (0, 1), (1, 1.99), (0.0, 0.0), (1.5, 0.75), (-1, 1)]
check(all(zone_geo.zone_contains(probe, *p) == api_zones.zone_contains(probe, *p) for p in pts),
      "the worker's point-in-zone test agrees with the API's")

# Spacing: measured on a fast clock, the floor is real.
W.GDELT_MIN_SPACING_S = 5.0
slept = []
sp = W.Spacing()
sp.wait(5, sleep=slept.append)
sp.wait(5, sleep=slept.append)
check(slept and abs(slept[-1] - 5) < 0.2, "requests to GDELT are at least 5 s apart")
# Real runs here use a short spacing so the test does not take minutes; the
# floor in the settings and the database is what holds in use.
W.GDELT_MIN_SPACING_S = 0.2
c.sql("ALTER TABLE outside_event_settings DROP CONSTRAINT IF EXISTS outside_event_settings_gdelt_request_spacing_seconds_check")
c.sql("UPDATE outside_event_settings SET gdelt_request_spacing_seconds = 0.2")

c.sql("UPDATE outside_event_settings SET prefetch_articles = false, dedupe_rules = false")
done = W.run_once()
check(done.get("gdelt") == 4, f"one pull: four events inside the marked zone, after the filters ({done})")
paths = [h[1] for h in hits]
check(paths[0].endswith("lastupdate.txt") and not any(stamps[0] in p for p in paths),
      "it asks what is newest, then reads back only as far as the backfill window")
check(all(h[2] and h[2].startswith("humint-platform outside-events") for h in hits),
      "every request names the application")
gaps = [b[0] - a[0] for a, b in zip(hits, hits[1:])]
check(min(gaps) >= 0.19, f"and they are spaced ({min(gaps):.2f} s at the test's spacing)")
ev = {e[0]: e for e in c.sql("SELECT source_id, title, category, zone_ids, precision, place, url FROM outside_events")}
check(set(ev) == {"1001", "1002", "1010", "1020"},
      f"kept: the protest, the arrest, the assault, the riot; dropped: a state-level place, a statement, "
      f"Annapolis (not marked), and the file older than the window ({sorted(ev)})")
check(ev["1002"][1] == "Arrest, detain, or charge with legal action: Police → Suspect"
      and ev["1010"][1] == "Kill by physical assault: Gunman → Civilian",
      f"titled from GDELT's own code table, actors named ({ev['1002'][1]!r}, {ev['1010'][1]!r})")
check(ev["1001"][3] == [balt] and ev["1001"][4] == "city", "each knows its zone, and how precisely it was placed")
check(c.sql("SELECT gdelt_last_file FROM outside_event_settings")[0][0] == stamps[4], "progress is kept")

hits.clear()
check(not {k for k, v in W.run_once().items() if v}, "not due again until the interval has passed")
check(hits == [], "and asks nothing in between")
admin.post(c.url + "/api/admin/outside-events/pull-now")
done = W.run_once()
check(done.get("gdelt") == 0 and [h[1] for h in hits] == ["/gdeltv2/lastupdate.txt"],
      "\"Pull now\" checks at once; with nothing newer, one request and nothing more")

# Filters from the settings.
c.sql("DELETE FROM outside_events WHERE source_id = '1020'")
c.sql("UPDATE outside_event_settings SET gdelt_city_only = false, gdelt_last_file = NULL, "
      "gdelt_root_codes = '01,13,14,15,17,18,19,20', gdelt_min_sources = 2, pull_requested_at = now()")
W.run_once()
got = {e[0] for e in c.sql("SELECT source_id FROM outside_events")}
check({"1003", "1004"} <= got and "1020" not in got and "1005" not in got,
      "with state-level places and statements allowed they come in; one source under the minimum does not; "
      "outside the marked zone never")

# ---- the page ---------------------------------------------------------------------------------
r = ana.get(c.url + "/api/outside-events", params={"zone_id": balt})
body = r.json()
check(r.ok and body["total"] >= 3 and body["zones"][0]["name"] == "Baltimore AOR"
      and body["credit"]["gdelt"]["url"] == "https://www.gdeltproject.org/",
      "the page lists them by area, with GDELT credited and linked")
check(all(i["status"] == "new" for i in body["items"]), "all new")
pts = ana.get(c.url + "/api/outside-events/map", params={"days": 7}).json()["items"]
check(len(pts) >= 3 and all("lat" in p for p in pts), "the map layer gets points")
first = next(i for i in body["items"] if i["source_id"] == "1002")
r = ana.post(c.url + f"/api/outside-events/{first['id']}/status", json={"status": "dismissed"})
check(r.ok, "dismissed")
c.sql("UPDATE outside_event_settings SET gdelt_last_file = NULL, pull_requested_at = now()")
W.run_once()
check(c.sql(f"SELECT status FROM outside_events WHERE id = {first['id']}")[0][0] == "dismissed",
      "and pulled again, it stays dismissed — it does not come back as new")
prot = next(i for i in body["items"] if i["source_id"] == "1001")
r = ana.post(c.url + f"/api/outside-events/{prot['id']}/to-document", json={"fetch_article": False})
check(r.status_code == 201, f"sent to Documents ({r.text[:200]})")
doc = r.json()["document_id"]
src = c.sql(f"SELECT source_note, title FROM attachments WHERE id = {doc}")[0]
check(src[0] == "Outside event: GDELT Project", "the document says where it came from")
check(c.sql(f"SELECT status, attachment_id FROM outside_events WHERE id = {prot['id']}")[0] == ("sent", doc),
      "and the event is marked sent")
r = ana.post(c.url + f"/api/outside-events/{prot['id']}/to-document", json={"fetch_article": False})
check(r.status_code == 409, "not twice")
check(c.sql("SELECT count(*) FROM audit_log WHERE action = 'outside_event.to_document'")[0][0] == 1, "audited")

# Retention: old unread ones go, sent ones stay.
c.sql("UPDATE outside_events SET occurred_on = occurred_on - 200")
c.sql("UPDATE outside_event_settings SET retention_days = 90")
W.prune(90)
left = c.sql("SELECT status FROM outside_events")
check(left == [("sent",)], f"past the retention window unread and dismissed ones go; the one sent to Documents stays ({left})")

# ---- ACLED -----------------------------------------------------------------------------------
acled_hits = []
ACLED_DATA = [
    {"event_id_cnty": "USA99001", "event_date": latest.strftime("%Y-%m-%d"), "event_type": "Protests",
     "sub_event_type": "Peaceful protest", "actor1": "Protesters (United States)", "actor2": "",
     "latitude": "39.2904", "longitude": "-76.6122", "location": "Baltimore", "admin1": "Maryland",
     "country": "United States", "geo_precision": "1", "source": "Baltimore Sun", "notes": "On 10 November...",
     "fatalities": "0", "timestamp": "1762800000"},
    # In the bounding box, outside the zone's shape? The rectangle is the box: so use one outside both.
    {"event_id_cnty": "USA99002", "event_date": latest.strftime("%Y-%m-%d"), "event_type": "Riots",
     "sub_event_type": "Mob violence", "actor1": "Rioters", "latitude": "38.97", "longitude": "-76.49",
     "location": "Annapolis", "country": "United States", "fatalities": "0"},
]


class ACLED(http.server.BaseHTTPRequestHandler):
    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        form = urllib.parse.parse_qs(self.rfile.read(n).decode())
        acled_hits.append(("token", form))
        if form.get("password") == ["right"] and form.get("client_id") == ["acled"] and form.get("grant_type") == ["password"]:
            self._send(200, {"access_token": "tok123", "expires_in": 86400, "refresh_token": "r"})
        else:
            self._send(400, {"error": "invalid_grant"})

    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        acled_hits.append(("read", q, self.headers.get("Authorization")))
        if self.headers.get("Authorization") != "Bearer tok123":
            return self._send(401, {"error": "unauthorized"})
        self._send(200, {"status": 200, "success": True, "data": ACLED_DATA, "next_cursor": None})

    def log_message(self, *a):
        pass


a = http.server.ThreadingHTTPServer(("127.0.0.1", 0), ACLED)
threading.Thread(target=a.serve_forever, daemon=True).start()
W.ACLED_BASE = f"http://127.0.0.1:{a.server_port}"
r = admin.put(c.url + "/api/admin/outside-events/settings",
              json={"gdelt_enabled": False, "acled_enabled": True, "acled_username": "me@org.example",
                    "acled_password": "wrong"})
check(r.ok and r.json()["acled_password_set"] is True and "acled_password" not in r.json(),
      "the ACLED password is kept on the server and never sent back")
admin.post(c.url + "/api/admin/outside-events/pull-now")
done = W.run_once()
check("refused the sign-in" in done.get("acled_error", ""), f"a wrong password says so ({done})")
check("refused the sign-in" in admin.get(c.url + "/api/admin/outside-events/settings").json()["acled_last_error"],
      "and the settings page shows it")
admin.put(c.url + "/api/admin/outside-events/settings", json={"acled_password": "right"})
admin.post(c.url + "/api/admin/outside-events/pull-now")
acled_hits.clear()
done = W.run_once()
check(done.get("acled") == 1, f"ACLED: the event inside the zone is kept ({done})")
read = [h for h in acled_hits if h[0] == "read"][0][1]
check(read["latitude"] == ["39.19|39.37"] and read["latitude_where"] == ["BETWEEN"]
      and read["event_date_where"] == ["BETWEEN"], "asked for by the zone's box and a date range")
e = c.sql("SELECT title, place, fatalities, sources_named FROM outside_events WHERE source = 'acled'")[0]
check(e[0] == "Peaceful protest: Protesters (United States)" and e[1] == "Baltimore, Maryland, United States"
      and e[3] == "Baltimore Sun", f"with ACLED's type, actors, place and sources ({e})")
check(c.sql("SELECT acled_token FROM outside_event_settings")[0][0] == "tok123", "the token is kept for next time")

# Backups leave the credentials out.
r = admin.get(c.url + "/api/admin/backup")
if r.ok:
    z = zipfile.ZipFile(io.BytesIO(r.content))
    data = json.loads(z.read("data.json"))
    row0 = data["tables"]["outside_event_settings"]["rows"][0]
    check(row0["acled_password"] is None and row0["acled_token"] is None and row0["acled_username"] == "me@org.example",
          "a backup carries the settings but not the ACLED password or token")
else:
    check(False, f"backup ({r.status_code})")

# Turning a zone off stops it pulling.
admin.patch(c.url + f"/api/map/zones/{balt}", json={"outside_events": False})
admin.post(c.url + "/api/admin/outside-events/pull-now")
acled_hits.clear()
check("gdelt" not in W.run_once() and acled_hits == [], "with no zone marked, nothing is asked of anybody")

# ---- the migration, on a database from before ------------------------------------------
old = Console("outside_mig")
old.sql("DROP TABLE outside_triage_corrections")      # newer than v1.15
old.sql("DROP TABLE outside_events")
old.sql("DROP TABLE outside_event_settings")
old.sql("ALTER TABLE map_zones DROP COLUMN outside_events")
mig = os.path.join(ROOT, "db", "migrate-v1.15-outside-events.sql")
old.sql_file(mig)
old.sql_file(mig)
check(old.sql("SELECT gdelt_enabled, gdelt_interval_minutes, gdelt_request_spacing_seconds FROM outside_event_settings")
      == [(False, 15, 5)], "the migration adds it all, off, with GDELT's floors — and can run twice")
finish()
