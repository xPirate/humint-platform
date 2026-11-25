"""Web research for the assistant (v1.19).

Off until an admin turns it on; offered only on a question the person allows
the web on; by default each search is queued and shown, and nothing goes out
until the person approves it (edited, or some struck out) — then the searches
run, audited, and the question continues with their results; a page from
them can be read and kept as a document (a draft the person applies).
Through a proxy when one is set; SearXNG, Brave or DuckDuckGo.

The search engines, the news site, the proxy and the model are stand-ins."""
import http.server
import json
import os
import sys
import threading
from urllib.parse import parse_qs, quote, urlparse
from urllib.request import urlopen

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import ROOT, Console, check, finish, ok  # noqa: E402

searches, brave_calls, ddg_calls, proxied, page_hits = [], [], [], [], []


class Engines(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        base = f"http://127.0.0.1:{self.server.server_port}"
        if u.path == "/search":                                     # SearXNG
            searches.append(q["q"][0])
            if q.get("format") != ["json"]:
                return self._send(403, "{}")
            return self._send(200, json.dumps({"results": [
                {"title": "Acme Freight Ltd — <b>company</b> profile", "url": f"{base}/page/acme",
                 "content": "Acme Freight Ltd is a haulage firm based in Baltimore."},
                {"title": "Port news", "url": f"{base}/page/port", "content": "Shipping news."},
                {"title": "Not a web page", "url": "ftp://example.org/x", "content": ""}]}))
        if u.path == "/brave":
            brave_calls.append((q["q"][0], self.headers.get("X-Subscription-Token")))
            return self._send(200, json.dumps({"web": {"results": [
                {"title": "Brave result", "url": "https://example.org/b", "description": "From Brave."}]}}))
        if u.path.startswith("/page/"):
            page_hits.append((u.path, self.headers.get("User-Agent")))
            body = ("<html><head><title>Acme Freight Ltd | Baltimore Business</title></head><body><nav>Menu</nav>"
                    "<article><p>Acme Freight Ltd is a haulage firm based in Baltimore, founded in 2009 by Ana Kovac "
                    "and run from a yard near the east docks.</p><p>The firm operates twelve trucks and holds "
                    "contracts at the container terminal, according to state filings.</p></article></body></html>")
            return self._send(200, body, "text/html; charset=utf-8")
        self._send(404, "{}")

    def do_POST(self):
        if self.path == "/ddg":
            ddg_calls.append(self.rfile.read(int(self.headers["Content-Length"])).decode())
            page = ('<div class="result"><a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg='
                    + quote("https://example.org/ddg-1", safe="") + '&amp;rut=x">First <b>result</b></a>'
                    '<a class="result__snippet" href="#">The first snippet.</a></div>'
                    '<div class="result"><a class="result__a" href="https://duckduckgo.com/y.js?ad=1">Advert</a></div>'
                    '<div class="result"><a class="result__a" href="https://example.org/ddg-2">Second</a>'
                    '<a class="result__snippet" href="#">Second snippet.</a></div>')
            return self._send(200, page, "text/html")
        self._send(404, "{}")


class Proxy(http.server.BaseHTTPRequestHandler):
    """A forward proxy for http:// addresses: records and passes them on."""
    def log_message(self, *a):
        pass

    def do_GET(self):
        proxied.append(self.path)
        with urlopen(self.path, timeout=10) as r:
            data, ctype, code = r.read(), r.headers.get("Content-Type"), r.status
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


SCRIPT, ANSWER, model_reqs = [], ["Done."], []


class FakeOllama(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send({"models": [{"name": "fake:1b"}]})

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        model_reqs.append(req)
        msgs = req.get("messages") or []
        q = max(i for i, m in enumerate(msgs) if m["role"] == "user")
        # Tool results after the question that this script has made (the
        # approved lookups given to it count as made already).
        made = [m for m in msgs[q:] if m["role"] == "assistant" and m.get("tool_calls")]
        n_calls = sum(len(m["tool_calls"]) for m in made)
        pre = len(PRELOADED[0]) if PRELOADED[0] else 0
        i = n_calls - pre
        if req.get("tools") and i < len(SCRIPT):
            name, args = SCRIPT[i]
            self._send({"message": {"role": "assistant", "content": "",
                                    "tool_calls": [{"function": {"name": name, "arguments": args}}]}})
        else:
            self._send({"message": {"role": "assistant", "content": ANSWER[0]}})


PRELOADED = [None]

servers = []
for H in (Engines, Proxy, FakeOllama):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    servers.append(srv)
ENG = f"http://127.0.0.1:{servers[0].server_port}"
PROXY = f"http://127.0.0.1:{servers[1].server_port}"

c = Console("web_research", env={"OLLAMA_ENABLED": "true", "OLLAMA_BASE_URL": f"http://127.0.0.1:{servers[2].server_port}",
                                 "OLLAMA_MODEL": "fake:1b", "ASSISTANT_MAX_LOOKUPS": "10",
                                 "FEED_FETCH_ALLOW_PRIVATE": "true",
                                 "WEB_BRAVE_URL": f"{ENG}/brave", "WEB_DDG_URL": f"{ENG}/ddg"}).start()
admin = c.register_admin("ana")
ben = c.add_user(admin, "ben")                     # an analyst
ok(admin.post(c.url + "/api/entities", json={"entity_type": "organization", "name": "Acme Freight",
                                             "description": "Haulage firm."}))


def ask(question, script, answer="Done.", web=False, approve=None, who=None, preloaded=0):
    SCRIPT[:] = script
    ANSWER[0] = answer
    PRELOADED[0] = [None] * preloaded if preloaded else None
    body = {"question": question, "web": web}
    if approve:
        body["approve"] = approve
    return (who or admin).post(c.url + "/api/assistant/messages", json=body)


def audit(action):
    return [r[0] for r in c.sql(f"SELECT detail FROM audit_log WHERE action = '{action}' ORDER BY id")]


# ---- off until an admin turns it on ----
s = ok(admin.get(c.url + "/api/admin/web-research"))
check(s["enabled"] is False and s["require_approval"] is True and s["provider"] == "searxng",
      "off by default, with approval on")
check(ben.get(c.url + "/api/admin/web-research").status_code == 403, "only admins see the settings")
check(ok(ben.get(c.url + "/api/assistant/web"))["available"] is False, "not offered while off")
check(ask("Who is Acme?", [], web=True).status_code == 403, "a question cannot ask for the web while it is off")
r = admin.put(c.url + "/api/admin/web-research", json={"proxy_url": "ftp://x"})
check(r.status_code == 400, "a proxy must be http(s):// or socks5(h)://")
s = ok(admin.put(c.url + "/api/admin/web-research", json={"enabled": True, "searxng_url": ENG + "/",
                                                          "brave_key": "secret-key"}))
check(s["enabled"] and s["has_brave_key"] and "brave_key" not in s, "turned on; the API key is never sent back")
check("secret-key" not in json.dumps(audit("web.settings")), "nor written to the audit log")
check(ok(ben.get(c.url + "/api/assistant/web"))["available"] is True, "offered to analysts")

# ---- a question without the web ----
r = ok(ask("Who is Acme?", [("web_search", {"query": "Acme Freight"})]))
tools = {t["function"]["name"] for t in model_reqs[-1].get("tools") or model_reqs[-2]["tools"]}
check("web_search" not in tools, "a question without the web is not offered the web lookups")
check(not searches and "web" not in (r.get("trail") or {}), "and nothing goes out")

# ---- with the web: searches queued for approval ----
r = ok(ask("Who is Acme Freight?", [("search_case", {"query": "Acme"}),
                                    ("web_search", {"query": "Acme Freight Baltimore"}),
                                    ("read_page", {"url": "https://example.org/acme"})],
           answer="The file has Acme Freight as a haulage firm. I would search the web for its owners.", web=True))
w = r["trail"]["web"]
check(w["status"] == "pending" and [q["kind"] for q in w["queued"]] == ["search", "page"]
      and w["queued"][0]["text"] == "Acme Freight Baltimore", f"the search and the page are queued ({w})")
check(not searches and not page_hits and not audit("web.search"), "nothing has gone out")
sys_prompt = [m for m in model_reqs if m.get("tools")][-1]["messages"][0]["content"]
check("THE WEB IS ALLOWED" in sys_prompt and "queued, not sent" in sys_prompt, "the model is told, and told it queues")
mid = r["id"]
check(ok(admin.get(c.url + "/api/assistant/messages"))["items"][-1]["trail"]["web"]["status"] == "pending",
      "the queue comes back with the conversation")
check(ask("", [], approve={"message_id": mid, "items": [{"kind": "search", "text": "x"}]}, who=ben).status_code == 404,
      "only the person who asked can approve")

# ---- approved, as edited: the search runs, and the question continues ----
r = ask("", [("read_page", {"url": f"{ENG}/page/acme"}),
             ("save_web_page", {"url": f"{ENG}/page/acme", "title": "Acme Freight — company profile",
                                "note": "Founded by Ana Kovac"}),
             ("web_search", {"query": "Ana Kovac Baltimore"})],
        answer="The web says Acme Freight Ltd was founded in 2009 by Ana Kovac (Baltimore Business).",
        approve={"message_id": mid, "items": [{"kind": "search", "text": "Acme Freight Ltd Baltimore"}]}, preloaded=1)
r = ok(r)
check(searches == ["Acme Freight Ltd Baltimore"], f"exactly the search as the person edited it went out ({searches})")
check(page_hits and page_hits[0][0] == "/page/acme" and "humint" not in (page_hits[0][1] or "").lower(),
      "a page from the approved results is read — with an ordinary browser's identity")
cont = [m for m in model_reqs if m.get("tools")][-1]["messages"]
check(any(m["role"] == "tool" and "Acme Freight Ltd is a haulage firm" in m["content"] for m in cont),
      "the model continues with the approved search's results")
check([s_["label"] for s_ in r["trail"]["steps"]][0].startswith("Searched the web for “Acme Freight Ltd Baltimore”"),
      "the trail shows the web search")
check(r["trail"]["web"]["status"] == "pending" and r["trail"]["web"]["queued"] == [{"kind": "search", "text": "Ana Kovac Baltimore"}],
      "a new search is queued again, not sent")
check(any(cc["kind"] == "web" for cc in r["citations"]), "web sources are cited, as web sources")
hist = ok(admin.get(c.url + "/api/assistant/messages"))["items"]
check(hist[-2]["content"].startswith("Go ahead on the web: search “Acme Freight Ltd Baltimore”"),
      "the conversation records what was approved")
first = next(m for m in hist if m["id"] == mid)
check(first["trail"]["web"]["status"] == "approved", "the earlier answer's queue is marked approved")
check(ask("", [], approve={"message_id": mid, "items": [{"kind": "search", "text": "again"}]}).status_code == 409,
      "approved once only")
a = audit("web.search")
check(len(a) == 1 and a[0]["query"] == "Acme Freight Ltd Baltimore" and a[0]["provider"] == "searxng",
      "the search is in the audit log, word for word")
check(len(audit("web.read")) == 1, "and the page read")

# Skip.
ok(admin.post(c.url + f"/api/assistant/messages/{r['id']}/web-skip"))
check(searches == ["Acme Freight Ltd Baltimore"], "Skip sends nothing")
check(admin.post(c.url + f"/api/assistant/messages/{r['id']}/web-skip").status_code == 404, "and is final")

# The page kept as a document.
d = next(x for x in r["drafts"] if x["kind"] == "web_to_document")
out = ok(admin.post(c.url + f"/api/assistant/drafts/{d['id']}/apply", json={}))
row = c.sql(f"SELECT title, source_note FROM attachments WHERE id = {out['result']['document_id']}")[0]
check(row[0] == "Acme Freight — company profile" and "open source, unverified" in row[1] and "/page/acme" in row[1],
      "Keep as a document: the page, with its address and 'unverified'")

# ---- without approval; limits ----
admin.put(c.url + "/api/admin/web-research", json={"require_approval": False, "max_searches": 1})
n = len(searches)
r = ok(ask("Anything on the web about Acme?", [("web_search", {"query": "Acme haulage"}),
                                                ("web_search", {"query": "Acme trucks"})], web=True, who=ben))
check(searches[n:] == ["Acme haulage"] and not r["trail"]["web"]["queued"],
      "with approval off, a search goes out at once — up to the limit per question")

# ---- the proxy ----
admin.put(c.url + "/api/admin/web-research", json={"proxy_url": PROXY, "max_searches": 4})
t = ok(admin.post(c.url + "/api/admin/web-research/test", json={}))
check(t["results"] and any("/search?" in p for p in proxied), "searches go through the proxy when one is set")
r = ok(ask("Read it", [("web_search", {"query": "Acme profile"}), ("read_page", {"url": f"{ENG}/page/acme"})],
           web=True))
check(any("/page/acme" in p for p in proxied), "and page reads too")
admin.put(c.url + "/api/admin/web-research", json={"proxy_url": ""})

# ---- Brave and DuckDuckGo ----
admin.put(c.url + "/api/admin/web-research", json={"provider": "brave"})
t = ok(admin.post(c.url + "/api/admin/web-research/test", json={"query": "lighthouses"}))
check(brave_calls == [("lighthouses", "secret-key")] and t["results"][0]["title"] == "Brave result",
      "Brave: the key goes in its header")
admin.put(c.url + "/api/admin/web-research", json={"provider": "duckduckgo"})
t = ok(admin.post(c.url + "/api/admin/web-research/test", json={"query": "lighthouses"}))
check([x["url"] for x in t["results"]] == ["https://example.org/ddg-1", "https://example.org/ddg-2"]
      and t["results"][0]["snippet"] == "The first snippet.", "DuckDuckGo: results read, redirects undone, adverts left out")

# ---- who may use it ----
admin.put(c.url + "/api/admin/web-research", json={"allowed": "admins"})
check(ok(ben.get(c.url + "/api/assistant/web"))["available"] is False
      and ask("x", [], web=True, who=ben).status_code == 403, "admins only, when set so")

# ---- in the web console ----
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None
if sync_playwright:
    from harness import PASSWORD  # noqa: E402
    admin.put(c.url + "/api/admin/web-research", json={"allowed": "analysts", "provider": "searxng",
                                                      "require_approval": True})
    acme = c.sql("SELECT id FROM entities WHERE name = 'Acme Freight'")[0][0]
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.environ.get("CHROMIUM") or None)
        page = browser.new_page(viewport={"width": 1400, "height": 950})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(c.url)
        page.fill("#login-username", "ana")
        page.fill("#login-password", PASSWORD)
        page.click("#login-form button[type=submit]")
        page.wait_for_selector("#app:not([hidden])")
        page.evaluate(f"() => openEntityDetail('{acme}')")
        page.wait_for_selector("#web-entity-btn:not([hidden])")
        SCRIPT[:] = [("web_search", {"query": "Acme Freight owners"})]
        ANSWER[0] = "I would search the web for Acme Freight's owners."
        PRELOADED[0] = None
        page.click("#web-entity-btn")
        page.wait_for_selector("#assistant-web-toggle:not([hidden])")
        check(page.is_checked("#assistant-web") and "Acme Freight" in page.input_value("#assistant-input"),
              "\"Search the web\" on a record asks about it, with the web allowed for that question")
        page.press("#assistant-input", "Enter")
        page.wait_for_selector(".assistant-web-queue", timeout=30000)
        check(not page.is_checked("#assistant-web"), "the web box unticks itself after the question")
        if os.environ.get("SHOTS_DIR"):
            page.screenshot(path=os.path.join(os.environ["SHOTS_DIR"], "web-approval.png"))
        n = len(searches)
        page.fill(".assistant-web-queue [data-web-text='0']", "Acme Freight Ltd owners")
        SCRIPT[:] = []
        ANSWER[0] = "Acme Freight Ltd was founded by Ana Kovac."
        PRELOADED[0] = [None]
        page.click(".assistant-web-queue button[type=submit]")
        page.wait_for_function("() => document.body.innerText.includes('founded by Ana Kovac')", timeout=30000)
        check(searches[n:] == ["Acme Freight Ltd owners"], "approved in the panel, as edited")
        check(not errors, f"no page errors ({errors[:3]})")
        page.evaluate("() => { switchView('admin'); showAdminSection('model'); }")
        page.wait_for_selector("#wr-on")
        check(page.is_checked("#wr-on") and page.input_value("#wr-searx").startswith(ENG), "Admin shows the web research settings")
        browser.close()

# ---- the migration ----
old = Console("web_research_mig")
old.sql("DROP TABLE web_research_settings")
mig = os.path.join(ROOT, "db", "migrate-v1.19-web-research.sql")
old.sql_file(mig)
old.sql_file(mig)
check(old.sql("SELECT enabled, require_approval FROM web_research_settings") == [(False, True)],
      "the migration adds it, off, and can run twice")
finish()
