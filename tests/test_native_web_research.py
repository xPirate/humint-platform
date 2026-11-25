"""The native app's assistant with web research: the "May use the web" box,
the queued searches shown for approval, and Run these and continue — the
search goes out only then. Search engine and model are stand-ins."""
import http.server
import json
import os
import sys
import threading
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import PASSWORD, ROOT, Console, check, finish  # noqa: E402

sys.path.insert(0, os.path.join(ROOT, "native", "tools"))
from shoot import FakeMachine  # noqa: E402
from appdriver import AppDriver  # noqa: E402

searches = []


class Searx(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        searches.append(parse_qs(urlparse(self.path).query)["q"][0])
        data = json.dumps({"results": [{"title": "Acme Freight Ltd profile", "url": "https://example.org/acme",
                                        "content": "A haulage firm founded by Ana Kovac."}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


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
        msgs = req.get("messages") or []
        q = max(i for i, m in enumerate(msgs) if m["role"] == "user")
        tools_seen = [m for m in msgs[q:] if m["role"] == "tool"]
        if any("haulage firm founded by Ana Kovac" in m["content"] for m in tools_seen):
            return self._send({"message": {"role": "assistant", "content": "The web says Ana Kovac founded Acme Freight."}})
        if req.get("tools") and not tools_seen:
            return self._send({"message": {"role": "assistant", "content": "", "tool_calls": [
                {"function": {"name": "web_search", "arguments": {"query": "Acme Freight owners"}}}]}})
        self._send({"message": {"role": "assistant", "content": "I would search the web for Acme Freight's owners."}})


srvs = []
for H in (Searx, FakeOllama):
    s = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    srvs.append(s)
c = Console("native_web", env={"OLLAMA_ENABLED": "true", "OLLAMA_BASE_URL": f"http://127.0.0.1:{srvs[1].server_port}",
                               "OLLAMA_MODEL": "fake:1b"}).start()
api = c.register_admin("ana")
api.put(c.url + "/api/admin/web-research", json={"enabled": True, "searxng_url": f"http://127.0.0.1:{srvs[0].server_port}"})

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
d.login("ana", PASSWORD)
d.tap("Assistant")
d.until(lambda: d.has_text("May use the web for this question"), what="web box")
d.tap("May use the web for this question")
d.type("Ask about the case file — Enter sends, Shift+Enter for a new line", "Who owns Acme Freight?")
d.key("Return")
d.until(lambda: any("would like to look on the web" in t for t in d.texts()), timeout=30, what="the queue")
check(not searches, "the search is queued, not sent")
if os.environ.get("SHOTS"):
    d.shot(os.path.join(os.environ["SHOTS"], "99-web-approval.png"))
d.tap("Run these and continue")
d.until(lambda: d.has_text("The web says Ana Kovac founded Acme Freight."), timeout=30, what="continued")
check(searches == ["Acme Freight owners"], "Run these and continue sends it, and the question continues")
check(d.has_text("Approved: 1 web lookup(s)"), "the queue is marked approved")
d.tap("Admin")
d.until(lambda: d.button("Model") is not None, what="admin")
d.tap("Model")
d.until(lambda: d.has_text("Allow web research (each question still has to allow it)"), what="web card")
d.tap("Show each search to the person before it is sent (recommended)")
d.tap("Save web research")
d.until(lambda: c.sql("SELECT require_approval FROM web_research_settings")[0][0] is False, what="saved")
check(True, "Admin → Model → Web research saves")
if os.environ.get("SHOTS"):
    d.shot(os.path.join(os.environ["SHOTS"], "99-web-admin.png"))
check(not errors, f"no QML errors ({errors[:3]})")
finish()
