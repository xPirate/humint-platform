"""The native app's Feeds and Assistant pages: send a feed item to Documents
and dismiss another; ask the assistant a question and watch it look things
up (against a stand-in for Ollama), then follow its citation to the record."""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import PASSWORD, ROOT, Console, check, finish, ok  # noqa: E402

sys.path.insert(0, os.path.join(ROOT, "native", "tools"))
from shoot import FakeMachine  # noqa: E402
from appdriver import AppDriver  # noqa: E402

SHOTS = os.environ.get("SHOTS")


def shot(d, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        d.shot(os.path.join(SHOTS, name + ".png"))


# ---- a stand-in for Ollama: one lookup, then an answer naming the record -----------
asked = []


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
        asked.append(req)
        msgs = req.get("messages") or []
        if req.get("tools") and not any(m.get("role") == "tool" for m in msgs):
            self._send({"message": {"role": "assistant", "content": "",
                                    "tool_calls": [{"function": {"name": "search_case",
                                                                 "arguments": {"query": "Kovac"}}}]}})
        else:
            self._send({"message": {"role": "assistant",
                                    "content": "**Ana Kovac** is the courier seen at the docks."}})


srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
threading.Thread(target=srv.serve_forever, daemon=True).start()

c = Console("native_assistant", env={"OLLAMA_ENABLED": "true",
                                     "OLLAMA_BASE_URL": f"http://127.0.0.1:{srv.server_port}",
                                     "OLLAMA_MODEL": "fake:1b"}).start()
api = c.register_admin("ana")
kovac = ok(api.post(c.url + "/api/entities", json={"entity_type": "person", "name": "Ana Kovac",
                                                   "description": "Courier, seen at the docks."}))
feed = c.sql("INSERT INTO rss_feeds (url, label) VALUES ('https://news.example/rss', 'Harbour News') RETURNING id")[0][0]
for guid, title in (("a", "Container theft at the east docks"), ("b", "Council approves new bus timetable")):
    c.sql("INSERT INTO rss_items (feed_id, guid, title, link, summary, published_at) "
          "VALUES (%s, %s, %s, %s, 'Summary of ' || %s, now())",
          (feed, guid, title, "https://news.example/" + guid, title))

m = FakeMachine()
m.unlock()
m.start(console_url=c.url)
d = AppDriver(m.sock, console_url=c.url)
d.login("ana", PASSWORD)

# ---- Feeds --------------------------------------------------------------------------------
d.tap("Feeds")
d.until(lambda: d.has_text("Container theft at the east docks"), what="feed items")
check(d.has_text("Harbour News") and d.has_text("Council approves new bus timetable"),
      "the unread items show, under their feed")
shot(d, "90-feeds")
# The link: no browser here, so a code to open it on a phone.
d.tap("The original")
d.until(lambda: d.has_text("https://news.example/a") or d.has_text("https://news.example/b"), what="the link")
check(d.has_text("This machine has no web browser"), "an item's link is offered as a QR code, for a phone")
d.tap("Done")
d.pump(0.4)

items = c.sql("SELECT id, title FROM rss_items ORDER BY id")
theft, bus = items[0][0], items[1][0]
d.tap("Send to Documents")
d.until(lambda: d.has_text("Fetch the full article"), what="send dialog")
d.tap("Fetch the full article")          # untick: no network in the test, and it is a choice offered
d.tap("Send")
d.until(lambda: c.sql("SELECT status FROM rss_items WHERE id IN (%s, %s) AND status = 'sent'", (theft, bus)),
        timeout=15, what="sent")
sent = c.sql("SELECT i.id, a.title FROM rss_items i JOIN attachments a ON a.id = i.attachment_id WHERE i.status = 'sent'")
check(len(sent) == 1, f"Send to Documents makes it a document ({sent})")
fetched = c.sql("SELECT detail->>'fetched_article', detail->>'fetch_error' FROM audit_log WHERE action = 'feed.to_document'")
check(fetched == [("false", None)], f"with Fetch the full article unticked, the summary alone is sent ({fetched})")
d.until(lambda: d.button("Dismiss") is not None, what="the other item")
d.tap("Dismiss")
d.until(lambda: c.sql("SELECT count(*) FROM rss_items WHERE status = 'dismissed'")[0][0] == 1, what="dismissed")
d.until(lambda: d.has_text("Nothing waiting"), what="empty unread list")
check(True, "Dismiss clears it, and the unread list ends empty")
d.choose_select("Unread", "Sent to Documents")
d.until(lambda: d.button("See the document") is not None, what="the sent item")
check(d.has_text("sent by ana"), "the sent list says who sent it")

# ---- Assistant ------------------------------------------------------------------------------
d.tap("Assistant")
d.until(lambda: d.has_text("Ask about anything in this case file"), what="assistant")
d.type("Ask about the case file — Enter sends, Shift+Enter for a new line", "Who is Kovac?")
d.key("Return")
d.until(lambda: d.has_text("the courier seen at the docks"), timeout=30, what="the answer")
check(any(r.get("tools") for r in asked) and any(any(mm.get("role") == "tool" for mm in r.get("messages", [])) for r in asked),
      "the question went to the model with its lookups, and a lookup ran")
check(d.button("Person: Ana Kovac") is not None or d.button("Ana Kovac") is not None,
      "the answer cites the record it rests on")
check(d.has_text("Looked up 1 thing"), "and says what it looked up")
shot(d, "91-assistant")
saved = c.sql("SELECT role FROM assistant_messages ORDER BY id")
check(saved == [("user",), ("assistant",)], f"the turn is saved to the conversation ({saved})")
d.tap("Person: Ana Kovac" if d.button("Person: Ana Kovac") else "Ana Kovac")
d.until(lambda: d.has_text("Courier, seen at the docks."), what="the record")
check(True, "a citation opens its record")

# A failed question is not kept: the model goes away.
srv.shutdown()
srv.server_close()
d.tap("Assistant")
d.until(lambda: d.has_text("Clear conversation"), what="assistant again")
d.type("Ask about the case file — Enter sends, Shift+Enter for a new line", "And the van?")
d.key("Return")
d.until(lambda: d.has_text("Couldn't reach Ollama") or d.has_text("hit an error") or d.has_text("stopped before answering"),
        timeout=40, what="the error")
check(c.sql("SELECT count(*) FROM assistant_messages")[0][0] == 2 and d.has_text("And the van?"),
      "a question that could not be answered is not saved, and goes back in the box to try again")

d.tap("Clear conversation")
d.tap("Clear")
d.until(lambda: c.sql("SELECT count(*) FROM assistant_messages")[0][0] == 0, what="cleared")
check(True, "Clear conversation empties it")
finish()
