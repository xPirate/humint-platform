"""The native app's Box → Actions → Update online: it asks the console for a
newer release (GitHub is a stand-in), shows what changed, and Download and
install puts the bundle in the inbox root checks and applies."""
import http.server
import json
import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import PASSWORD, ROOT, Console, check, finish  # noqa: E402

sys.path.insert(0, os.path.join(ROOT, "native", "tools"))
from shoot import FakeMachine  # noqa: E402
from appdriver import AppDriver  # noqa: E402

REPO = "xPirate/humint-platform"
BUNDLE = os.urandom(50_000)


class FakeGitHub(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        base = f"http://127.0.0.1:{self.server.server_port}"
        if self.path.startswith(f"/repos/{REPO}/releases"):
            name = "humint-update-130-cccccccccc-x86.tar"
            data = json.dumps([{"tag_name": "build-130", "name": "Build 130", "draft": False, "prerelease": False,
                                "published_at": "2026-11-20T12:00:00Z", "html_url": "https://github.com/x",
                                "body": "### Online updates\n\nCheck GitHub from the box.",
                                "assets": [{"name": name, "size": len(BUNDLE),
                                            "browser_download_url": f"{base}/{REPO}/releases/download/build-130/{name}"}]}]).encode()
        else:
            data = BUNDLE
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeGitHub)
threading.Thread(target=srv.serve_forever, daemon=True).start()
GH = f"http://127.0.0.1:{srv.server_port}"
tmp = tempfile.mkdtemp()
inbox = os.path.join(tmp, "inbox", "incoming.tar")
build_file = os.path.join(tmp, "BUILD.json")
json.dump({"build": 128, "commit": "aaaaaaaaaa"}, open(build_file, "w"))
plat = os.path.join(tmp, "platform")
open(plat, "w").write("x86\n")
c = Console("native_online_update", env={
    "UPDATE_INBOX": inbox, "UPDATE_STATUS_FILE": os.path.join(tmp, "st.json"), "BUILD_FILE": build_file,
    "UPDATE_GITHUB_API": GH, "UPDATE_DOWNLOAD_BASE": GH, "PLATFORM_FILE": plat}).start()
c.register_admin("ana")

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
d.tap("Box")
d.until(lambda: d.button("Actions") is not None, what="box")
d.tap("Actions")
d.until(lambda: d.button("Update online") is not None, what="actions")
d.tap("Update online")
d.until(lambda: d.has_text("Build 130 is available"), what="check")
check(d.has_text("this machine has build 128") and any("Check GitHub from the box." in t for t in d.texts()),
      "Update online: the newer build, with what changed")
if os.environ.get("SHOTS"):
    d.shot(os.path.join(os.environ["SHOTS"], "98-update-online.png"))
d.tap("Download and install build 130")
deadline = time.time() + 15
while time.time() < deadline and not os.path.exists(inbox):
    d.pump(0.2)
check(os.path.exists(inbox) and open(inbox, "rb").read() == BUNDLE, "Download and install puts the bundle in the inbox")
d.until(lambda: any("Downloaded." in t for t in d.texts()), what="progress")
check(True, "and says it is being checked and applied")
check(not errors, f"no QML errors ({errors[:3]})")
finish()
