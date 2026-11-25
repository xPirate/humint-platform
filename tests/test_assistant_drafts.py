"""The assistant, v1.18: new lookups (outside events, documents, what is near a
place, and opening outside events and documents), and drafts — a report, a
priority and sending an outside event to Documents prepared under the
answer and made only when the person applies them; a proposed link goes to
the Review queue.

The model is a stand-in that follows a script of tool calls per question."""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import ROOT, Console, check, finish, ok  # noqa: E402

SCRIPT = []          # [(tool name, args)] for the current question, then the answer
ANSWER = ["Done."]
seen_tool_results = []
requests_seen = []


class FakeOllama(BaseHTTPRequestHandler):
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
        requests_seen.append(req)
        msgs = req.get("messages") or []
        # The tool results since the question.
        q = max(i for i, m in enumerate(msgs) if m["role"] == "user")
        done = [m for m in msgs[q:] if m["role"] == "tool"]
        if done:
            seen_tool_results[:] = [m["content"] for m in done]
        if req.get("tools") and len(done) < len(SCRIPT):
            name, args = SCRIPT[len(done)]
            self._send({"message": {"role": "assistant", "content": "",
                                    "tool_calls": [{"function": {"name": name, "arguments": args}}]}})
        else:
            self._send({"message": {"role": "assistant", "content": ANSWER[0]}})


srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
threading.Thread(target=srv.serve_forever, daemon=True).start()
c = Console("assistant_drafts", env={"OLLAMA_ENABLED": "true",
                                     "OLLAMA_BASE_URL": f"http://127.0.0.1:{srv.server_port}",
                                     "OLLAMA_MODEL": "fake:1b", "ASSISTANT_MAX_LOOKUPS": "12"}).start()
api = c.register_admin("ana")
kovac = ok(api.post(c.url + "/api/entities", json={"entity_type": "person", "name": "Ana Kovac",
                                                   "description": "Courier, seen at the docks."}))
docks = ok(api.post(c.url + "/api/entities", json={"entity_type": "location", "name": "East Docks",
                                                   "description": "Container terminal."}))
c.sql(f"UPDATE location_details SET lat = 39.27, lng = -76.58 WHERE entity_id = '{docks['id']}'")
if not c.sql(f"SELECT 1 FROM location_details WHERE entity_id = '{docks['id']}'"):
    c.sql(f"INSERT INTO location_details (entity_id, lat, lng) VALUES ('{docks['id']}', 39.27, -76.58)")
zone = ok(api.post(c.url + "/api/map/zones", json={
    "name": "Baltimore AOR", "environment": "Semi-permissive", "outside_events": True,
    "geometry": {"shape": "rectangle", "points": [[39.37, -76.72], [39.37, -76.52], [39.19, -76.52], [39.19, -76.72]]}}))
ev = c.sql("INSERT INTO outside_events (source, source_id, occurred_on, title, category, lat, lon, place, precision, "
           "url, zone_ids, triage_is_event, triage_in_area, triage_category, triage_severity, triage_summary, "
           "triage_reason, triage_by, triaged_at) VALUES ('gdelt', 'G1', current_date, 'Steal: Thief', 'Coerce', "
           "39.271, -76.581, 'Baltimore, Maryland, United States', 'city', 'https://news.example.org/theft', "
           f"ARRAY[{zone['id']}], true, true, 'violent_crime', 3, 'Containers stolen at the east docks overnight.', "
           "'A local theft.', 'model', now()) RETURNING id")[0][0]
c.sql("INSERT INTO outside_events (source, source_id, occurred_on, title, category, lat, lon, place, precision, "
      "zone_ids, triage_is_event, triage_in_area, triage_category, triage_severity, triage_summary, triage_by, triaged_at) "
      "VALUES ('gdelt', 'G2', current_date, 'Fight: Actor', 'Fight', 39.28, -76.60, 'Baltimore', 'city', "
      f"ARRAY[{zone['id']}], false, true, 'other', 1, 'An actor talks about a war film.', 'model', now())")
c.sql("UPDATE outside_event_settings SET triage_enabled = true, triage_min_severity = 2")
c.sql("INSERT INTO outside_articles (url, title, site, body, attempts, fetched_at) VALUES "
      "('https://news.example.org/theft', 'Thieves take three containers from east docks', 'The Banner', "
      "'Three shipping containers were taken from the east docks overnight, port police said.', 1, now())")
doc = ok(api.post(c.url + "/api/documents/text", json={"title": "Harbour patrol log", "text": "x"}))
c.sql(f"UPDATE attachments SET extracted_text = 'Patrol saw a white van near container row C at 0300. "
      f"Driver matched Ana Kovac.', extraction_status = 'done' WHERE id = {doc['id']}")


def ask(question, script, answer="Done."):
    SCRIPT[:] = script
    ANSWER[0] = answer
    return ok(api.post(c.url + "/api/assistant/messages", json={"question": question}))


# ---- the new lookups ----
r = ask("What is going on around the docks?", [
    ("nearby", {"place": "East Docks", "radius_km": 1}),
    ("outside_events", {"days": 7}),
    ("documents", {"text": "white van"}),
    ("open_record", {"id": f"outside-{ev}"}),
    ("open_record", {"id": f"document-{doc['id']}"}),
], answer="Containers were stolen at the East Docks; a patrol log puts Ana Kovac nearby.")
res = list(seen_tool_results)
check(len(res) == 5, f"five lookups ran ({len(res)})")
check("East Docks" in res[0] and f"outside-{ev}" in res[0] and "Inside the zone(s): Baltimore AOR" in res[0],
      "nearby: the Location, the zone it is in, and the outside event within the radius")
check("Containers stolen at the east docks" in res[1] and "Violent crime, severity 3" in res[1]
      and "war film" not in res[1], "outside_events: the triaged incidents, without what the triage set aside")
check(f"document-{doc['id']}" in res[2] and "white van" in res[2], "documents: found by words in their text")
check("Three shipping containers were taken" in res[3] and "The model's triage: kept" in res[3],
      "open_record on an outside event: its article and the triage")
check("Driver matched Ana Kovac" in res[4] and "Harbour patrol log" in res[4], "open_record on a document: its text")
steps = [s["label"] for s in r["trail"]["steps"]]
check(steps[0].startswith("Looked around East Docks") and steps[1].startswith("Checked outside events"),
      f"each lookup is named in the trail ({steps[:3]})")
tools = {t["function"]["name"] for t in requests_seen[0]["tools"]}
check({"outside_events", "documents", "nearby", "draft_report", "draft_priority", "send_outside_event",
       "propose_link"} <= tools, "the model is offered the new lookups and the drafts")
check("only when the analyst asks" in requests_seen[0]["messages"][0]["content"],
      "and told to prepare things only when asked")

# ---- drafts ----
c.sql("UPDATE boards SET enabled = true WHERE kind = 'priorities'")
r = ask("Write that up, add a priority on who is stealing from the docks, link Ana to the docks and put "
        "the theft in Documents.", [
    ("draft_report", {"title": "Container theft at East Docks", "about": ["Ana Kovac", docks["id"]],
                      "body": "Three containers were taken from the [East Docks](#/entities/" + docks["id"] + ").",
                      "precedence": "priority"}),
    ("draft_priority", {"title": "Who is stealing from the docks?", "question": "Who is behind the thefts?",
                        "indicators": ["white van at container row C"], "priority": 2, "about": [docks["id"]]}),
    ("propose_link", {"from_id": "Ana Kovac", "to_id": docks["id"], "relationship": "frequents",
                      "reason": "Patrol log, 0300."}),
    ("send_outside_event", {"id": f"outside-{ev}"}),
], answer="I drafted a report and a priority, proposed the link, and prepared the theft for Documents.")
drafts = r["drafts"]
kinds = {d["kind"]: d for d in drafts}
check(set(kinds) == {"report", "priority", "link", "outside_to_document"}, f"four drafts under the answer ({list(kinds)})")
check(all(d["status"] == "pending" for k, d in kinds.items() if k != "link") and kinds["link"]["status"] == "queued",
      "pending until the person decides; the link went to Review")
check(c.sql("SELECT count(*) FROM reports")[0][0] == 0 and c.sql("SELECT count(*) FROM intel_priorities")[0][0] == 0,
      "nothing made yet")
check(c.sql("SELECT suggested_relationship_type, source FROM extraction_suggestions")
      == [("frequents", "assistant")], "the proposed link waits in the Review queue")
check(len(kinds["report"]["payload"]["entity_ids"]) == 2, "the report draft is about both records (a name resolved)")
hist = ok(api.get(c.url + "/api/assistant/messages"))["items"]
check(len(hist[-1]["drafts"]) == 4, "the drafts come back with the conversation")

out = ok(api.post(c.url + f"/api/assistant/drafts/{kinds['report']['id']}/apply", json={}))
rid = out["result"]["report_id"]
row = c.sql(f"SELECT status, criticality, title FROM reports WHERE id = '{rid}'")[0]
check(out["status"] == "applied" and row == ("draft", "Priority", "Container theft at East Docks"),
      "Apply makes a draft report, as written")
check(c.sql(f"SELECT count(*) FROM report_entities WHERE report_id = '{rid}'")[0][0] == 2, "linked to its records")
check(api.post(c.url + f"/api/assistant/drafts/{kinds['report']['id']}/apply", json={}).status_code == 409,
      "applied once only")
out = ok(api.post(c.url + f"/api/assistant/drafts/{kinds['priority']['id']}/apply",
                  json={"title": "Who is stealing containers?"}))
check(c.sql("SELECT title, question, indicators FROM intel_priorities")
      == [("Who is stealing containers?", "Who is behind the thefts?", ["white van at container row C"])],
      "a priority, with the person's change to its title")
out = ok(api.post(c.url + f"/api/assistant/drafts/{kinds['outside_to_document']['id']}/apply", json={}))
check(c.sql(f"SELECT status FROM outside_events WHERE id = {ev}")[0][0] == "sent" and out["result"]["document_id"],
      "the outside event goes to Documents")
audits = [a[0] for a in c.sql("SELECT action FROM audit_log WHERE action LIKE 'assistant.draft%' OR action IN "
                              "('report.create', 'priority.create')")]
check(audits.count("assistant.draft_apply") == 3 and "report.create" in audits and "priority.create" in audits,
      "each audited, as the person, through the usual create")

# Discard, someone else's, a board that is off.
r = ask("Draft another report.", [("draft_report", {"title": "Spare", "body": "Text."})])
spare = r["drafts"][0]
other = c.add_user(api, "ben")
check(other.post(c.url + f"/api/assistant/drafts/{spare['id']}/apply", json={}).status_code == 404,
      "only the person who asked can apply it")
check(ok(api.post(c.url + f"/api/assistant/drafts/{spare['id']}/discard"))["status"] == "discarded", "Discard")
check(c.sql("SELECT count(*) FROM reports WHERE title = 'Spare'")[0][0] == 0, "and nothing is made")
c.sql("UPDATE boards SET enabled = false WHERE kind = 'priorities'")
r = ask("Add a priority.", [("draft_priority", {"title": "X"})])
check(not r["drafts"] and "switched off" in seen_tool_results[0], "with the Priorities board off, none is drafted")
r = ask("Five reports please.", [("draft_report", {"title": f"R{i}", "body": "b"}) for i in range(7)])
check(len(r["drafts"]) == 5 and "most for one question" in seen_tool_results[-1], f"at most five drafts a question ({len(r['drafts'])}, {seen_tool_results[-2:]})")

# ---- in the web console ----
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None
if sync_playwright:
    from harness import PASSWORD  # noqa: E402
    SCRIPT[:] = [("draft_report", {"title": "Web draft", "body": "Seen at the **docks**.", "about": ["Ana Kovac"]})]
    ANSWER[0] = "I drafted a report for you to check."
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.environ.get("CHROMIUM") or None)
        page = browser.new_page(viewport={"width": 1400, "height": 950})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(c.url)
        page.fill("#login-username", "ana")
        page.fill("#login-password", PASSWORD)
        page.click("#login-form button[type=submit]")
        page.wait_for_selector("#assistant-tab-btn:not([hidden])")
        page.click("#assistant-tab-btn")
        page.fill("#assistant-input", "Write it up")
        page.press("#assistant-input", "Enter")
        page.wait_for_function("() => [...document.querySelectorAll('.assistant-draft-pending')].some((c) => c.innerText.includes('Web draft'))",
                               timeout=30000)
        card = page.locator(".assistant-draft-pending").last.inner_text()
        check("Draft report".lower() in card.lower() and "Web draft" in card and "Ana Kovac" in card,
              "the web panel shows the draft under the answer, with the records it is about")
        if os.environ.get("SHOTS_DIR"):
            page.screenshot(path=os.path.join(os.environ["SHOTS_DIR"], "assistant-draft.png"))
        page.locator(".assistant-draft-pending").last.locator("[data-draft-apply]").click()
        import time as _t
        for _ in range(50):
            if c.sql("SELECT count(*) FROM reports WHERE title = 'Web draft'")[0][0]:
                break
            _t.sleep(0.2)
        check(c.sql("SELECT count(*) FROM reports WHERE title = 'Web draft' AND status = 'draft'")[0][0] == 1,
              "\"Make the draft report\" makes it")
        page.locator("[data-draft-open-report]").last.click()
        page.wait_for_function("() => document.body.innerText.includes('Web draft')")
        check(not errors, f"no page errors ({errors[:3]})")
        browser.close()

# ---- the migration on a database from before ----
old = Console("assistant_drafts_mig")
old.sql("DROP TABLE assistant_drafts")
mig = os.path.join(ROOT, "db", "migrate-v1.18-assistant-drafts.sql")
old.sql_file(mig)
old.sql_file(mig)
check(old.sql("SELECT count(*) FROM assistant_drafts")[0][0] == 0, "the migration adds the table, and can run twice")
finish()
