"""Outside events, reading and duplicates.

Reading: an event's article opens in reader form (headline and paragraphs,
no menus) through the API, fetched once by the server and kept; the worker
fetches ahead. Links come from outside data, so private addresses — and
redirects to them — are refused.

Duplicates: events from the same article, the same kind of event at the same
place on the same day, and near-identical headlines are folded under the
first; with an embedding model, the same story worded differently too. A
dismissed story stays dismissed when another site reports it; "Not the same"
separates a wrong match for good."""
import filecmp
import http.server
import os
import sys
import threading
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import ROOT, Console, check, finish  # noqa: E402

check(filecmp.cmp(os.path.join(ROOT, "api", "reader.py"), os.path.join(ROOT, "worker", "reader.py"), shallow=False),
      "api/reader.py and worker/reader.py are the same file")

# ---- a stand-in news site ---------------------------------------------------------------------
STORIES = {
    1: ("Police arrest two after downtown protest | The Banner",
        ["Baltimore police arrested two people Sunday evening after a protest outside City Hall turned tense, officials said.",
         "About 200 people gathered at the plaza around 5 p.m., according to a department spokesperson."]),
    2: ("Police arrest two after protest downtown - WBAL",       # the same wire story, another site
        ["Two people were arrested Sunday evening after a protest outside Baltimore City Hall turned tense, police said.",
         "Roughly 200 demonstrators had gathered at the plaza in the late afternoon, a spokesperson said."]),
    3: ("Harbor tunnel closed after truck fire | The Banner",
        ["The Harbor Tunnel was closed in both directions on Monday after a truck caught fire near the south portal.",
         "No injuries were reported, and crews expected to reopen the tunnel by evening, the transportation authority said."]),
    4: ("City Hall demonstration ends with detentions | Local Wire",   # same story, other words
        ["Officers detained a pair of demonstrators as a rally at City Hall grew heated on Sunday night.",
         "The crowd, estimated at two hundred, had assembled in the square during the afternoon."]),
}
hits = []


def page(n):
    title, paras = STORIES[n]
    return f"""<html><head><title>{title}</title><meta property="og:site_name" content="News {n}"></head><body>
<header><nav><a href="/">Home</a> <a href="/x">A long menu entry that should not appear in the reader at all</a></nav></header>
<main><article><h1>{title.split(' | ')[0].split(' - ')[0]}</h1>
{''.join(f'<p>{p}</p>' for p in paras)}
<aside><p>Related: a different story that the reader view should leave out entirely, however long it runs.</p></aside>
</article></main><footer><p>Copyright 2026 News {n}. All rights reserved. Terms, privacy, cookies and more.</p></footer>
</body></html>"""


class News(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        hits.append(self.path)
        if self.path.startswith("/story/"):
            n = int(self.path.rsplit("/", 1)[1])
            body = page(n).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
        elif self.path.startswith("/to-private"):
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/story/1")
            self.end_headers()
            return
        elif self.path == "/script-only":
            body = b"<html><body><div id=app></div><script>render()</script></body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), News)
threading.Thread(target=srv.serve_forever, daemon=True).start()
NEWS = f"http://localhost:{srv.server_port}"

# ---- the reader, and its guard against private addresses ----------------------------------------
sys.path.insert(0, os.path.join(ROOT, "worker"))
import reader  # noqa: E402  (the worker's copy, identical)

real_public = reader._public
reader.ALLOW_PRIVATE = False
reader._public = lambda h: h == "localhost"      # "localhost" plays a public news site here
art, err = reader.fetch(f"{NEWS}/story/1")
check(art and art["title"] == "Police arrest two after downtown protest" and art["site"] == "News 1",
      f"reader form: the headline without the site's name ({art and art['title']})")
check(art and len(art["paragraphs"]) == 2 and "menu" not in art["text"] and "Related" not in art["text"]
      and "Copyright" not in art["text"], "just the article: no menu, no aside, no footer")
art, err = reader.fetch(f"http://127.0.0.1:{srv.server_port}/story/1")
check(art is None and "private" in err, "a link to a private address is refused")
art, err = reader.fetch(f"{NEWS}/to-private")
check(art is None and "private" in err, "and so is a redirect to one")
art, err = reader.fetch(f"{NEWS}/script-only")
check(art is None and "scripts" in err, "a page built by scripts says so")
reader._public = real_public
reader.ALLOW_PRIVATE = True

# ---- the console ---------------------------------------------------------------------------------
c = Console("outside_reading", env={"FEED_FETCH_ALLOW_PRIVATE": "true"}).start()
admin = c.register_admin()
z = admin.post(c.url + "/api/map/zones", json={
    "name": "Baltimore AOR", "environment": "Semi-permissive", "outside_events": True,
    "geometry": {"shape": "rectangle", "points": [[39.37, -76.72], [39.37, -76.52], [39.19, -76.52], [39.19, -76.72]]}}).json()
ZID = z["id"]
today = date.today().isoformat()


def add(sid, title, code, lat, lon, url, source="gdelt", notes=None, day=today):
    u = f"'{url}'" if url else "NULL"
    n = "NULL" if notes is None else "'" + notes.replace("'", "''") + "'"
    return c.sql(f"INSERT INTO outside_events (source, source_id, occurred_on, title, category, code, lat, lon, place, "
                 f"precision, url, notes, zone_ids) VALUES ('{source}', '{sid}', '{day}', '{title}', 'Coerce', '{code}', "
                 f"{lat}, {lon}, 'Baltimore, Maryland, United States', 'city', {u}, {n}, ARRAY[{ZID}]) RETURNING id")[0][0]


e1 = add("G1", "Arrest, detain: Police → Protester", "173", 39.2904, -76.6122, f"{NEWS}/story/1")
e1b = add("G2", "Demonstrate or rally: Protester", "141", 39.2904, -76.6122, f"{NEWS}/story/1")     # same article
e2 = add("G3", "Arrest, detain: Police", "1731", 39.2904, -76.6122, f"{NEWS}/story/2")              # same place, kind, day
e3 = add("G4", "Use conventional military force", "190", 39.25, -76.60, f"{NEWS}/story/3")         # something else
e4 = add("G5", "Arrest, detain: Police → Demonstrator", "173", 39.30, -76.65, f"{NEWS}/story/4")    # other words, other spot
e5 = add("G6", "Demonstrate: Protester", "141", 39.26, -76.70, f"{NEWS}/story/2")                  # story 2 again, elsewhere

# ---- reading through the API ----
r = admin.get(c.url + f"/api/outside-events/{e3}/article")
a = r.json()
check(r.ok and a["article"]["title"] == "Harbor tunnel closed after truck fire" and "south portal" in a["article"]["text"],
      "the article, in reader form, from the API")
n = len([h for h in hits if h == "/story/3"])
a = admin.get(c.url + f"/api/outside-events/{e3}/article").json()
check(a["article"] and len([h for h in hits if h == "/story/3"]) == n, "fetched once, then kept")

# ---- the worker: articles ahead, then duplicates ----
c.worker_env()
import outside_events as W  # noqa: E402
W.reader.ALLOW_PRIVATE = True
c.sql("UPDATE outside_event_settings SET article_spacing_seconds = 1, dedupe_model = false")
st = W.load_settings()
check(W.dedupe_rules() == 2, "rules: the same article folds; the same kind at the same place on the same day folds")
dup = dict(c.sql("SELECT id, dup_of FROM outside_events"))
reason = dict(c.sql("SELECT id, dup_reason FROM outside_events WHERE dup_of IS NOT NULL"))
check(dup[e1b] == e1 and reason[e1b] == "same_article", "events from one article: one incident")
check(dup[e2] == e1 and reason[e2] == "same_place_type_day", "the same arrest at the same spot, same day: one incident")
check(dup[e3] is None and dup[e4] is None, "a tunnel fire and an arrest elsewhere stay apart")
W.prefetch_articles(st)
fetched = {r[0] for r in c.sql("SELECT url FROM outside_articles WHERE body IS NOT NULL")}
check(f"{NEWS}/story/4" in fetched and f"{NEWS}/story/2" in fetched,
      "the worker reads ahead the articles of incidents")
W.dedupe_headlines(st)
dup = dict(c.sql("SELECT id, dup_of FROM outside_events"))
check(dup[e5] == e1 and dict(c.sql("SELECT id, dup_reason FROM outside_events"))[e5] in ("same_headline", "same_article"),
      "the same wire story on another site folds by its headline")
check(dup[e4] is None, "worded differently, the rules leave it apart (that is the model's job)")

# ---- the model: the same story in other words ----
class FakeModel:
    enabled, embed_model = True, "nomic-embed-text"
    calls = 0

    def embed(self, text):
        FakeModel.calls += 1
        t = text.lower()
        # A toy embedding: the arrest-at-City-Hall story points one way, the tunnel another.
        protest = sum(w in t for w in ("arrest", "detain", "protest", "demonstrat", "rally", "city hall", "crowd"))
        tunnel = sum(w in t for w in ("tunnel", "truck", "fire", "portal"))
        return [float(protest), float(tunnel), 0.1]

c.sql(f"UPDATE outside_events SET headline_checked = false WHERE id = {e4}")
c.sql("UPDATE outside_event_settings SET dedupe_model = true")
W.dedupe_headlines(W.load_settings(), client=FakeModel())
dup = dict(c.sql("SELECT id, dup_of FROM outside_events"))
check(dup[e4] == e1 and dict(c.sql("SELECT id, dup_reason FROM outside_events"))[e4] == "model",
      "with an embedding model, the same story in other words folds too")
check(dup[e3] is None, "and a different story does not")
check(c.sql(f"SELECT embedding IS NOT NULL FROM outside_articles WHERE url = '{NEWS}/story/4'")[0][0],
      "an article's embedding is kept, not computed again")

# ---- the page: grouped ----
body = admin.get(c.url + "/api/outside-events").json()
ids = [i["id"] for i in body["items"]]
lead = next(i for i in body["items"] if i["id"] == e1)
check(set(ids) == {e1, e3} and lead["similar"] == 4 and lead["headline"] == "Police arrest two after downtown protest",
      f"the page shows two incidents, the first with its four similar reports and its headline ({ids}, {lead.get('similar')})")
check(body["unread_total"] == 2, "unread counts incidents, not reports")
sim = admin.get(c.url + f"/api/outside-events/{e1}/similar").json()["items"]
check(len(sim) == 4 and all(s_.get("dup_reason_text") for s_ in sim), "the similar reports, each with why it matched")
check(len(admin.get(c.url + "/api/outside-events/map").json()["items"]) == 2, "the map shows each incident once")

# Dismissing the incident dismisses its reports; a new report of it arrives dismissed.
admin.post(c.url + f"/api/outside-events/{e1}/status", json={"status": "dismissed"})
check(c.sql(f"SELECT count(*) FROM outside_events WHERE dup_of = {e1} AND status <> 'dismissed'")[0][0] == 0,
      "dismissing an incident dismisses the reports folded under it")
e6 = add("G7", "Arrest, detain: Police", "173", 39.2905, -76.6121, f"{NEWS}/story/1")
W.dedupe_rules()
check(c.sql(f"SELECT dup_of, status FROM outside_events WHERE id = {e6}")[0] == (e1, "dismissed"),
      "a later report of a dismissed story arrives dismissed — it does not come back as new")

# "Not the same": separated for good.
r = admin.post(c.url + f"/api/outside-events/{e4}/separate")
check(r.ok and c.sql(f"SELECT dup_of, dedupe_locked, status FROM outside_events WHERE id = {e4}")[0] == (None, True, "new"),
      "\"Not the same\" takes it out, back to new")
c.sql(f"UPDATE outside_events SET headline_checked = false, rules_checked = false WHERE id = {e4}")
W.dedupe_rules()
W.dedupe_headlines(W.load_settings(), client=FakeModel())
check(c.sql(f"SELECT dup_of FROM outside_events WHERE id = {e4}")[0][0] is None, "and it is never matched again")
check(c.sql("SELECT count(*) FROM audit_log WHERE action = 'outside_event.separate'")[0][0] == 1, "audited")

# Sending an incident uses the kept article, and marks its reports read.
admin.post(c.url + f"/api/outside-events/{e3}/status", json={"status": "new"})
n = len(hits)
r = admin.post(c.url + f"/api/outside-events/{e3}/to-document", json={"fetch_article": True})
check(r.status_code == 201 and len(hits) == n, "Send to Documents uses the article already read (no second fetch)")
doc = r.json()["document_id"]
check("south portal" in open(os.path.join(c.env["UPLOAD_DIR"], c.sql(f"SELECT storage_path FROM attachments WHERE id = {doc}")[0][0])).read(),
      "and the document holds it")

# ---- settings ----
s = admin.get(c.url + "/api/admin/outside-events/settings").json()
check(s["prefetch_articles"] is True and s["dedupe_rules"] is True and s["folded"] >= 4 and s["articles"]["read"] >= 3,
      "the settings show what has been read and folded")
r = admin.put(c.url + "/api/admin/outside-events/settings", json={"article_spacing_seconds": 0.2})
check(r.status_code == 400, "a news site gets at least a second between requests")

# ---- the migration on a database from before ----
old = Console("outside_reading_mig")
old.sql("DROP TABLE outside_articles")
for col in ("dup_of", "dup_reason", "dedupe_locked", "rules_checked", "headline_checked"):
    old.sql(f"ALTER TABLE outside_events DROP COLUMN {col}")
for col in ("prefetch_articles", "article_spacing_seconds", "articles_per_pass", "dedupe_rules", "dedupe_model",
            "dedupe_model_threshold"):
    old.sql(f"ALTER TABLE outside_event_settings DROP COLUMN {col}")
mig = os.path.join(ROOT, "db", "migrate-v1.16-outside-reading.sql")
old.sql_file(mig)
old.sql_file(mig)
check(old.sql("SELECT prefetch_articles, dedupe_rules, dedupe_model FROM outside_event_settings") == [(True, True, False)],
      "the migration adds it all, and can run twice")
finish()
