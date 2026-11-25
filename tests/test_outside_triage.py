"""Outside events, the model's triage.

The model reads each incident's article and says whether it is a real event,
whether it happened in the area, its category (the team's, not CAMEO's), how
much it matters, and why. A review of a war film coded as Fight is set aside;
so is a story from Tokyo filed in Baltimore, and a routine item under the
severity shown. Nothing is deleted: the filtered view shows them with the
reason. A person's correction is final, and becomes an example the model is
shown next time. One call per incident (folded duplicates are not asked).

The model is a stand-in Ollama server here, answering by keywords; the real
client is used against it, so the request it sends (the JSON schema, thinking
off, retried without it for a model that refuses) is checked too."""
import ast
import http.server
import json
import os
import sys
import threading
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import ROOT, Console, check, finish  # noqa: E402

requests_seen = []


class FakeOllama(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        requests_seen.append(body)
        if "think" in body:
            return self._send(400, {"error": "\"qwen-test\" does not support thinking"})
        text = body["messages"][1]["content"].lower()
        article = text.split("the article (opening):")[-1]
        if "film" in article:
            v = {"is_event": False, "in_area": True, "category": "other", "severity": 1,
                 "summary": "A review of a war film.", "reason": "An actor's role in a film, not an event."}
        elif "tokyo" in article:
            v = {"is_event": True, "in_area": False, "category": "protest", "severity": 2,
                 "summary": "A protest in Tokyo.", "reason": "It happened in Tokyo, not in the area."}
        elif "tunnel" in article:
            v = {"is_event": True, "in_area": True, "category": "disaster", "severity": 4,
                 "summary": "Harbor Tunnel closed after a truck fire.", "reason": "A closure affecting movement."}
        elif "ribbon" in article:
            v = {"is_event": True, "in_area": True, "category": "government", "severity": 1,
                 "summary": "A ribbon cutting at a library.", "reason": "Routine."}
        else:
            v = {"is_event": True, "in_area": True, "category": "police", "severity": 2,
                 "summary": "Police arrested two after a protest at City Hall.", "reason": "A local arrest."}
        self._send(200, {"model": body["model"], "message": {"role": "assistant", "content": json.dumps(v)},
                         "prompt_eval_count": 500, "eval_count": 60})

    def _send(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
threading.Thread(target=srv.serve_forever, daemon=True).start()
OLLAMA = f"http://127.0.0.1:{srv.server_port}"

c = Console("outside_triage").start()
admin = c.register_admin()
z = admin.post(c.url + "/api/map/zones", json={
    "name": "Baltimore AOR", "environment": "Semi-permissive", "outside_events": True,
    "geometry": {"shape": "rectangle", "points": [[39.37, -76.72], [39.37, -76.52], [39.19, -76.52], [39.19, -76.72]]}}).json()
ZID = z["id"]
today = date.today().isoformat()

STORIES = {
    "film": ("Actor recalls playing a soldier in new war film",
             "The actor, who grew up in Baltimore, spoke about his role as a soldier fighting the Germans in the "
             "new film, which opens Friday. Filming took four months in Hungary."),
    "tokyo": ("Thousands rally in Tokyo",
              "Thousands of people marched through central Tokyo on Sunday, a Baltimore-based wire service reported."),
    "fire": ("Harbor tunnel closed after truck fire",
             "The Harbor Tunnel was closed in both directions on Monday after a truck caught fire near the south "
             "portal. Crews expected to reopen it by evening."),
    "arrest": ("Police arrest two after downtown protest",
               "Baltimore police arrested two people Sunday evening after a protest outside City Hall turned tense."),
    "ribbon": ("Mayor cuts ribbon on branch library",
               "The mayor held a ribbon cutting on Tuesday for the renovated branch library in Hampden."),
}


def add(sid, key, title, category="Fight", source="gdelt", dup_of=None):
    url = f"https://news.example.org/{key}/{sid}"
    n = int(sid[1:])                         # apart in place and kind, so the duplicate rules leave them be
    eid = c.sql(f"INSERT INTO outside_events (source, source_id, occurred_on, title, category, code, lat, lon, place, "
                f"precision, url, zone_ids, dup_of) VALUES ('{source}', '{sid}', '{today}', '{title}', '{category}', "
                f"'{190 + n}', {39.20 + n * 0.02}, -76.61, 'Baltimore, Maryland, United States', 'city', '{url}', ARRAY[{ZID}], "
                f"{dup_of or 'NULL'}) RETURNING id")[0][0]
    head, body = STORIES[key]
    c.sql(f"INSERT INTO outside_articles (url, title, site, body, attempts, fetched_at) VALUES "
          f"('{url}', '{head}', 'The Banner', '{body}', 1, now())")
    return eid


e_film = add("G1", "film", "Use conventional military force: Actor → Germany")
e_tokyo = add("G2", "tokyo", "Demonstrate or rally: Protester", "Protest")
e_fire = add("G3", "fire", "Use unconventional violence", "Assault")
e_arrest = add("G4", "arrest", "Arrest, detain: Police → Protester", "Coerce")
e_ribbon = add("G5", "ribbon", "Make public statement: Mayor", "Public statement")
e_member = add("G6", "fire", "Use unconventional violence: Truck", "Assault", dup_of=e_fire)
e_acled = add("A1", "arrest", "Peaceful protest: Protesters", "Protest", source="acled")

# ---- settings ----
r = admin.put(c.url + "/api/admin/outside-events/settings",
              json={"triage_enabled": True, "triage_model": "  qwen-test  ", "triage_min_severity": 2})
s = r.json()
check(r.ok and s["triage_enabled"] is True and s["triage_model"] == "qwen-test" and s["triage_acled"] is False,
      "triage turned on, with its own model")
check(admin.put(c.url + "/api/admin/outside-events/settings", json={"triage_min_severity": 6}).status_code == 400,
      "severity runs 1 to 5")
r = admin.put(c.url + f"/api/admin/outside-events/zones/{ZID}/focus",
              json={"focus": "civil unrest, threats to the port and tunnels"})
check(r.ok and r.json()["zones"][0]["focus"] == "civil unrest, threats to the port and tunnels",
      "an area's focus, in the team's words")
check(s["triage_counts"]["waiting"] == 5, f"five incidents wait (not the folded report, not ACLED) ({s['triage_counts']})")
body = admin.get(c.url + "/api/outside-events").json()
check(body["total"] == 6 and body["filtered_total"] == 0, "not judged yet: everything shows")

# ---- the worker ----
c.worker_env()
sys.path.insert(0, os.path.join(ROOT, "worker"))
import outside_events as W  # noqa: E402
import outside_triage as T  # noqa: E402
from ollama_client import OllamaClient  # noqa: E402

api_src = open(os.path.join(ROOT, "api", "outside_events.py")).read()
api_cats = ast.literal_eval(api_src.split("TRIAGE_CATEGORIES = ", 1)[1].split("\n}", 1)[0] + "\n}")
check(list(api_cats) == list(T.CATEGORIES), "the API and the worker have the same categories")
v = T.clean({"is_event": "false", "in_area": "yes", "category": "Shooting", "severity": "9", "summary": "  a  b "})
check(v == {"is_event": False, "in_area": True, "category": "other", "severity": 5, "summary": "a b", "reason": None},
      "whatever the model says is made safe to store")

client = OllamaClient(base_url=OLLAMA, model="assistant-model")
out = T.triage(W.load_settings(), client)
check(out["checked"] == 5 and out["filtered"] == 3 and not out["error"], f"five judged, three set aside ({out})")
first = requests_seen[0]
check(first.get("think") is False and isinstance(first["format"], dict)
      and first["format"]["properties"]["category"]["enum"] == list(T.CATEGORIES),
      "asked for the schema, with thinking off")
second = requests_seen[1]
check("think" not in second and second["model"] == "qwen-test", "a model that cannot turn thinking off is asked again without it")
check(len(requests_seen) == 6 and all("think" not in rq for rq in requests_seen[1:]),
      "and is not asked the failing way again")
check(all("civil unrest, threats to the port and tunnels" in rq["messages"][1]["content"] for rq in requests_seen[1:]),
      "the area's focus is in every question")
check("war film" in requests_seen[1]["messages"][0]["content"] and "Baltimore AOR" in requests_seen[1]["messages"][1]["content"],
      "the model is told how GDELT goes wrong, and which area")
rows = {r[0]: r[1:] for r in c.sql("SELECT id, triage_is_event, triage_in_area, triage_category, triage_severity, "
                                   "triage_by FROM outside_events")}
check(rows[e_film][0] is False and rows[e_tokyo][1] is False and rows[e_fire][2:4] == ("disaster", 4),
      "the film is not an event; Tokyo is not in the area; the fire is a disaster, severity 4")
check(rows[e_member][4] is None and rows[e_acled][4] is None, "folded reports and ACLED are not asked")
n = len(requests_seen)
T.triage(W.load_settings(), client)
check(len(requests_seen) == n, "each incident is asked once")

# ---- the page ----
body = admin.get(c.url + "/api/outside-events").json()
ids = [i["id"] for i in body["items"]]
check(set(ids) == {e_fire, e_arrest, e_acled} and body["filtered_total"] == 3,
      f"the page shows what the model kept (and ACLED, not asked) ({ids})")
fire = next(i for i in body["items"] if i["id"] == e_fire)
check(fire["triage"]["category_label"] == "Disaster or emergency" and fire["triage"]["severity_label"] == "significant"
      and fire["triage"]["summary"].startswith("Harbor Tunnel"), "with its category, severity and summary")
check(body["unread_total"] == 3 and body["zones"][0]["unread"] == 3, "unread counts leave out what was set aside")
by_sev = admin.get(c.url + "/api/outside-events?sort=severity").json()["items"]
check(by_sev[0]["id"] == e_fire, "most severe first, when asked")
check([i["id"] for i in admin.get(c.url + "/api/outside-events?category=police").json()["items"]] == [e_arrest],
      "filter by category")
filt = admin.get(c.url + "/api/outside-events?view=filtered").json()["items"]
check({i["id"] for i in filt} == {e_film, e_tokyo, e_ribbon} and all(i["filtered"] and i["triage"]["reason"] for i in filt),
      "the filtered view: what was set aside, each with the reason")
check(len(admin.get(c.url + "/api/outside-events/map").json()["items"]) == 3, "the map leaves them out too")

# ---- a person's correction ----
r = admin.post(c.url + f"/api/outside-events/{e_ribbon}/triage",
               json={"is_event": True, "in_area": True, "category": "infrastructure", "severity": 3})
check(r.ok and r.json()["triage"]["by"] == "analyst" and not r.json()["filtered"], "a correction puts it back")
check(admin.post(c.url + f"/api/outside-events/{e_member}/triage", json={}).status_code == 409,
      "a folded report is corrected through its incident")
check(admin.post(c.url + f"/api/outside-events/{e_film}/triage", json={"category": "movies"}).status_code == 400,
      "only the categories there are")
ex = c.sql("SELECT text, model_verdict, verdict FROM outside_triage_corrections")
check(len(ex) == 1 and ex[0][0].startswith("Mayor cuts ribbon") and ex[0][1]["severity"] == 1
      and ex[0][2]["category"] == "infrastructure", "kept as an example, with what the model had said")
check(c.sql("SELECT count(*) FROM audit_log WHERE action = 'outside_event.triage'")[0][0] == 1, "audited")

r = admin.post(c.url + "/api/admin/outside-events/retriage", json={"days": 7})
check(r.ok and r.json()["requeued"] == 4, f"judge again: the model's calls, not the person's ({r.json().get('requeued')})")
n = len(requests_seen)
T.triage(W.load_settings(), client)
check(len(requests_seen) == n + 4, "four asked again")
check("Mayor cuts ribbon" in requests_seen[-1]["messages"][0]["content"] and "infrastructure" in requests_seen[-1]["messages"][0]["content"],
      "the team's correction is shown to the model as an example")
check(c.sql(f"SELECT triage_by, triage_severity FROM outside_events WHERE id = {e_ribbon}")[0] == ("analyst", 3),
      "and the person's call stands")

# ---- when the model is down ----
c.sql(f"UPDATE outside_events SET triaged_at = NULL, triage_by = NULL WHERE id IN ({e_fire}, {e_arrest}, {e_tokyo}, {e_film})")
down = OllamaClient(base_url="http://127.0.0.1:9", model="x", timeout=2)
out = T.triage(W.load_settings(), down)
check(out["checked"] == 0 and out["failed"] == 3 and "reached" in (out["error"] or ""),
      f"the model unreachable: stops after three tries, says why ({out})")
check(c.sql(f"SELECT count(*) FROM outside_events WHERE triage_attempts = 1")[0][0] == 3, "and they are tried again later")
body = admin.get(c.url + "/api/outside-events").json()
check(e_fire in [i["id"] for i in body["items"]], "an incident not yet judged still shows")

# ---- run_once ----
W._model_client = lambda: OllamaClient(base_url=OLLAMA, model="assistant-model")
done = W.run_once()
check(done.get("triaged") == 4, f"the worker's pass triages ({done})")
s = admin.get(c.url + "/api/admin/outside-events/settings").json()
check(s["triage_counts"]["checked"] == 4 and s["triage_counts"]["corrected"] == 1 and s["triage_counts"]["examples"] == 1,
      f"the settings show what was judged and corrected ({s['triage_counts']})")
s = admin.delete(c.url + "/api/admin/outside-events/corrections").json()
check(s["triage_counts"]["examples"] == 0 and s["triage_counts"]["corrected"] == 1,
      "the examples can be forgotten; the corrected events keep their correction")

# ---- turned off: nothing hidden ----
admin.put(c.url + "/api/admin/outside-events/settings", json={"triage_enabled": False})
body = admin.get(c.url + "/api/outside-events").json()
leads = c.sql("SELECT count(*) FROM outside_events WHERE dup_of IS NULL")[0][0]
check(body["total"] == leads and body["filtered_total"] == 0, "with triage off, nothing is hidden")

# ---- the migration on a database from before ----
old = Console("outside_triage_mig")
old.sql("DROP TABLE outside_triage_corrections")
for col in ("triage_is_event", "triage_in_area", "triage_category", "triage_severity", "triage_summary",
            "triage_reason", "triage_by", "triage_model", "triaged_at", "triage_attempts", "triage_error"):
    old.sql(f"ALTER TABLE outside_events DROP COLUMN {col}")
for col in ("triage_enabled", "triage_model", "triage_acled", "triage_per_pass", "triage_min_severity",
            "triage_examples", "triage_last_error"):
    old.sql(f"ALTER TABLE outside_event_settings DROP COLUMN {col}")
old.sql("ALTER TABLE map_zones DROP COLUMN outside_focus")
mig = os.path.join(ROOT, "db", "migrate-v1.17-outside-triage.sql")
old.sql_file(mig)
old.sql_file(mig)
check(old.sql("SELECT triage_enabled, triage_min_severity, triage_per_pass FROM outside_event_settings") == [(False, 2, 20)],
      "the migration adds it all, off, and can run twice")
finish()
