"""Outside events, reading and duplicates, in the web console (Chromium): the
article opens in the side panel in reader form (not a new tab), Next and
Previous walk the list, opening one marks it read, Esc closes; an incident's
folded reports open under "+N similar reports" and "Not the same" separates
one; Admin shows the reading and duplicate settings."""
import http.server
import os
import sys
import threading
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import PASSWORD, Console, check, finish  # noqa: E402

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("SKIP: playwright is not installed (pip install playwright)")
    finish()

STORIES = {
    1: ("Police arrest two after downtown protest | The Banner",
        ["Baltimore police arrested two people Sunday evening after a protest outside City Hall turned tense, officials said.",
         "About 200 people gathered at the plaza around 5 p.m., according to a department spokesperson."]),
    3: ("Harbor tunnel closed after truck fire | The Banner",
        ["The Harbor Tunnel was closed in both directions on Monday after a truck caught fire near the south portal.",
         "No injuries were reported, and crews expected to reopen the tunnel by evening, the transportation authority said."]),
}


class News(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        n = int(self.path.rsplit("/", 1)[1]) if self.path.startswith("/story/") else 0
        if n not in STORIES:
            self.send_response(404)
            self.end_headers()
            return
        title, paras = STORIES[n]
        body = (f"<html><head><title>{title}</title><meta property='og:site_name' content='The Banner'></head><body>"
                f"<nav><a href='/'>A long menu entry that should not appear in the reader</a></nav>"
                f"<article>{''.join(f'<p>{p}</p>' for p in paras)}</article></body></html>").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), News)
threading.Thread(target=srv.serve_forever, daemon=True).start()
NEWS = f"http://127.0.0.1:{srv.server_port}"

c = Console("outside_reading_ui", env={"FEED_FETCH_ALLOW_PRIVATE": "true"}).start()
admin = c.register_admin()
z = admin.post(c.url + "/api/map/zones", json={
    "name": "Baltimore AOR", "environment": "Semi-permissive", "outside_events": True,
    "geometry": {"shape": "rectangle", "points": [[39.37, -76.72], [39.37, -76.52], [39.19, -76.52], [39.19, -76.72]]}}).json()
today = date.today().isoformat()
shots = os.environ.get("SHOTS_DIR")


def add(sid, title, url, dup_of=None):
    return c.sql(f"INSERT INTO outside_events (source, source_id, occurred_on, title, category, code, lat, lon, place, "
                 f"precision, url, zone_ids, dup_of, dup_reason) VALUES ('gdelt', '{sid}', '{today}', '{title}', 'Coerce', "
                 f"'173', 39.29, -76.61, 'Baltimore, Maryland, United States', 'city', '{url}', ARRAY[{z['id']}], "
                 f"{dup_of or 'NULL'}, {'%s' % repr('same_place_type_day') if dup_of else 'NULL'}) RETURNING id")[0][0]


e1 = add("G1", "Arrest, detain: Police → Protester", f"{NEWS}/story/1")
e1b = add("G2", "Arrest, detain: Police", f"{NEWS}/story/1b", dup_of=e1)
e3 = add("G3", "Use conventional military force", f"{NEWS}/story/3")

with sync_playwright() as pw:
    browser = pw.chromium.launch(executable_path=os.environ.get("CHROMIUM") or None)
    page = browser.new_page(viewport={"width": 1400, "height": 950})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(c.url)
    page.fill("#login-username", "admin")
    page.fill("#login-password", PASSWORD)
    page.click("#login-form button[type=submit]")
    page.wait_for_selector("#outside-tab:not([hidden])")
    check(page.inner_text("#outside-badge") == "2", "the unread count counts incidents, not every report")
    page.click("#outside-tab")
    page.wait_for_selector("#outside-items .feed-item")
    check(page.locator("#outside-items > .feed-item").count() == 2, "two incidents listed; the folded report is not")
    check("+1 similar report" in page.inner_text("#outside-items"), "with \"+1 similar report\" on the first")

    # ---- reading ----
    pages_before = len(browser.contexts[0].pages)
    first_id = page.evaluate("() => outsideState.items[0].id")
    page.click(f"#outside-items > .feed-item[data-item='{first_id}'] [data-oe-read] >> nth=0")
    page.wait_for_selector("#oe-reader .oe-reader-body p:not(.field-hint)")
    text = page.inner_text("#oe-reader")
    check(len(browser.contexts[0].pages) == pages_before, "the article opens in the side panel, not a new tab")
    check("menu entry" not in text and ("Harbor Tunnel" in text or "arrested two people" in text),
          "in reader form: the paragraphs, no menu")
    check("1 of 2" in text, "with its place in the list")
    page.wait_for_timeout(500)
    check(c.sql(f"SELECT status FROM outside_events WHERE id = {first_id}")[0][0] == "read", "opening it marks it read")
    check(c.sql(f"SELECT count(*) FROM outside_articles WHERE body IS NOT NULL")[0][0] == 1, "the text is kept")
    if shots:
        page.screenshot(path=os.path.join(shots, "outside-reader.png"))
    page.keyboard.press("ArrowRight")
    page.wait_for_function("() => document.querySelector('#oe-reader') && /2 of 2/.test(document.querySelector('#oe-reader').innerText)"
                           " && document.querySelector('#oe-reader .oe-reader-body p:not(.field-hint)')")
    check(True, "→ goes to the next one without closing")
    page.click("#oe-reader [data-oe-step='-1']")
    page.wait_for_function("() => /1 of 2/.test(document.querySelector('#oe-reader').innerText)")
    check(True, "and Previous goes back")
    check(page.get_attribute("#oe-reader a[target=_blank]", "href").startswith(NEWS), "the original is still a link away")
    page.keyboard.press("Escape")
    check(page.is_hidden("#oe-reader"), "Esc closes the panel")

    # ---- similar reports ----
    page.click(f"[data-oe-similar='{e1}']")
    page.wait_for_selector(f"#oe-group-{e1} .feed-item")
    check("matched: " in page.inner_text(f"#oe-group-{e1}"), "the folded report shows why it was matched")
    page.click(f"#oe-group-{e1} [data-oe-separate='{e1b}']")
    page.wait_for_function("() => document.querySelectorAll('#outside-items > .feed-item').length === 3")
    check(c.sql(f"SELECT dup_of, dedupe_locked FROM outside_events WHERE id = {e1b}")[0] == (None, True),
          "\"Not the same\" separates it, for good")

    # ---- admin ----
    page.evaluate("() => { switchView('admin'); showAdminSection('outside'); }")
    page.wait_for_selector("#oe-dd-model")
    check("No embedding model is set" in page.inner_text("#outside-settings")
          or "Embedding model" in page.inner_text("#outside-settings"), "the embedding model's state is shown")
    page.check("#oe-dd-model")
    page.fill("#oe-dd-th", "0.9")
    page.fill("#oe-art-sp", "3")
    page.click("#outside-form button[type=submit]")
    page.wait_for_timeout(800)
    row = c.sql("SELECT dedupe_model, dedupe_model_threshold, article_spacing_seconds FROM outside_event_settings")[0]
    check(row[0] is True and abs(row[1] - 0.9) < 1e-6 and float(row[2]) == 3, f"the settings save ({row})")
    if shots:
        page.screenshot(path=os.path.join(shots, "outside-admin-reading.png"), full_page=True)
    check(not errors, f"no page errors ({errors[:3]})")
    browser.close()
finish()
