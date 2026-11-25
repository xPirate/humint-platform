"""Updates online: the box reads the repository's GitHub releases, offers the
newest build for its kind of machine with the change log since its own, and
downloads the bundle into the inbox root checks and applies — exactly as an
uploaded one. And the builder's side: deploy/release-notes.py (the change
log, without trailers) and deploy/publish-release.sh (checks, then gh).

GitHub is a stand-in server here; the bundle is opaque bytes (root's
signature check is test_field_update.py's)."""
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import ROOT, Console, check, finish  # noqa: E402

REPO = "xPirate/humint-platform"
BUNDLE = os.urandom(300_000)
calls = []


def release(build, commit, notes, assets, prerelease=False, draft=False):
    return {"tag_name": f"build-{build}", "name": f"Build {build}", "draft": draft, "prerelease": prerelease,
            "published_at": "2026-11-20T12:00:00Z", "html_url": f"https://github.com/{REPO}/releases/tag/build-{build}",
            "body": notes, "assets": assets}


class FakeGitHub(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        calls.append(self.path)
        base = f"http://127.0.0.1:{self.server.server_port}"
        if self.path.startswith(f"/repos/{REPO}/releases"):
            def asset(name, size=len(BUNDLE)):
                return {"name": name, "size": size,
                        "browser_download_url": f"{base}/{REPO}/releases/download/{name.split('-')[2]}/{name}"}
            rels = [
                release(130, "ccc", "### Online updates\n\nCheck GitHub from the box.", [
                    asset("humint-update-130-cccccccccc-x86.tar"), asset("humint-update-130-cccccccccc.tar")]),
                release(131, "ddd", "pre", [asset("humint-update-131-dddddddddd-x86.tar")], prerelease=True),
                release(129, "bbb", "### Triage\n\nThe model reads each incident.", [
                    asset("humint-update-129-bbbbbbbbbb-x86.tar")]),
                release(128, "aaa", "older", [asset("humint-update-128-aaaaaaaaaa-dirty-x86.tar")]),
                {**release(127, "zzz", "elsewhere", []), "assets": [{
                    "name": "humint-update-200-eeeeeeeeee-x86.tar", "size": 10,
                    "browser_download_url": "https://evil.example.com/humint-update-200-eeeeeeeeee-x86.tar"}]},
            ]
            return self._send(200, json.dumps(rels).encode(), "application/json")
        if "/releases/download/" in self.path:
            return self._send(200, BUNDLE, "application/octet-stream")
        self._send(404, b"{}", "application/json")

    def _send(self, code, data, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
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
con = Console("online_update", env={
    "UPDATE_INBOX": inbox, "UPDATE_STATUS_FILE": os.path.join(tmp, "st.json"), "BUILD_FILE": build_file,
    "UPDATE_GITHUB_API": GH, "UPDATE_DOWNLOAD_BASE": GH, "PLATFORM_FILE": plat}).start()
admin = con.register_admin()
ana = con.add_user(admin, "ana")

check(ana.get(con.url + "/api/admin/field-update/online").status_code == 403, "only admins may check")
r = admin.get(con.url + "/api/admin/field-update/online?refresh=true")
o = r.json()
check(r.ok and o["installed_build"] == 128 and o["available"]["build"] == 130 and o["platform"] == "x86",
      f"the newest release for this kind of machine, newer than the installed build ({o.get('available')})")
check([c["build"] for c in o["changes"]] == [130, 129] and "The model reads each incident." in o["changes"][1]["notes"],
      "with the change log of every release since")
check(o["available"]["asset"].endswith("-x86.tar"), "the x86 bundle, not the Pi's")
check(all(c["build"] != 131 for c in o["changes"]), "pre-releases are not offered")
check(all(c["build"] != 200 for c in o["changes"]), "a download from anywhere but this repository's releases is ignored")
n = len(calls)
admin.get(con.url + "/api/admin/field-update/online")
check(len(calls) == n, "the answer is kept for a while (GitHub limits unsigned-in checks)")

check(admin.post(con.url + "/api/admin/field-update/online", json={"build": 129}).status_code == 202,
      "an older-than-newest build that is still newer can be installed")
deadline = time.time() + 15
while time.time() < deadline and not os.path.exists(inbox):
    time.sleep(0.2)
check(os.path.exists(inbox) and open(inbox, "rb").read() == BUNDLE, "the bundle is downloaded, whole, into the inbox")
check(not os.path.exists(inbox + ".part"), "through a part file, so root never sees half of it")
st = admin.get(con.url + "/api/admin/field-update").json()
check(st["download"]["state"] == "queued" and st["pending"], "the page says it is being checked and applied")
check(admin.post(con.url + "/api/admin/field-update/online", json={"build": 130}).status_code == 409,
      "a second waits for the first")
check(con.sql("SELECT count(*) FROM audit_log WHERE action = 'field_update.online'")[0][0] == 1, "audited")
os.unlink(inbox)
check(admin.post(con.url + "/api/admin/field-update/online", json={"build": 128}).status_code in (404, 409),
      "the installed build is not offered again")
check(admin.post(con.url + "/api/admin/field-update/online", json={"build": 131}).status_code == 404,
      "nor a pre-release")
con.stop()

# ---- in the web console ----
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None
if sync_playwright:
    from harness import PASSWORD  # noqa: E402
    con = Console("online_update_ui", env={
        "UPDATE_INBOX": inbox, "UPDATE_STATUS_FILE": os.path.join(tmp, "st.json"), "BUILD_FILE": build_file,
        "UPDATE_GITHUB_API": GH, "UPDATE_DOWNLOAD_BASE": GH, "PLATFORM_FILE": plat}).start()
    con.register_admin()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.environ.get("CHROMIUM") or None)
        page = browser.new_page(viewport={"width": 1300, "height": 950})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("dialog", lambda d: d.accept())
        page.goto(con.url)
        page.fill("#login-username", "admin")
        page.fill("#login-password", PASSWORD)
        page.click("#login-form button[type=submit]")
        page.wait_for_selector("#app:not([hidden])")
        page.evaluate("() => { switchView('admin'); showAdminSection('backup'); }")
        page.wait_for_selector("#online-update-check:visible")
        page.click("#online-update-check")
        page.wait_for_selector(".update-available")
        text = page.inner_text("#online-update-result")
        check("Build 130 is available" in text and "Online updates" in text and "The model reads each incident." in text,
              "Admin: the newer build, with what changed since this one")
        if os.environ.get("SHOTS_DIR"):
            page.screenshot(path=os.path.join(os.environ["SHOTS_DIR"], "online-update.png"), full_page=True)
        page.click("#online-update-install")
        deadline = time.time() + 15
        while time.time() < deadline and not os.path.exists(inbox):
            time.sleep(0.2)
        check(os.path.exists(inbox), "\"Download and install\" puts it in the inbox")
        page.wait_for_function("() => /Downloaded/.test(document.getElementById('online-update-progress').textContent)")
        check(True, "and says it is being checked and applied")
        check(not errors, f"no page errors ({errors[:3]})")
        browser.close()
    os.unlink(inbox)
    con.stop()

# A Pi takes the Pi's bundle.
open(plat, "w").write("pi\n")
con = Console("online_update_pi", env={
    "UPDATE_INBOX": inbox, "UPDATE_STATUS_FILE": os.path.join(tmp, "st.json"), "BUILD_FILE": build_file,
    "UPDATE_GITHUB_API": GH, "UPDATE_DOWNLOAD_BASE": GH, "PLATFORM_FILE": plat}).start()
pa = con.register_admin()
o = pa.get(con.url + "/api/admin/field-update/online?refresh=true").json()
check(o["available"]["asset"] == "humint-update-130-cccccccccc.tar" and [c["build"] for c in o["changes"]] == [130],
      "a Pi is offered the Pi's bundle")
con.stop()

# Offline.
con = Console("online_update_off", env={"UPDATE_INBOX": inbox, "BUILD_FILE": build_file,
                                        "UPDATE_GITHUB_API": "http://127.0.0.1:9"}).start()
pa = con.register_admin()
r = pa.get(con.url + "/api/admin/field-update/online")
check(r.status_code == 502 and "online" in r.json()["detail"], "with no internet, it says so")
con.stop()

# ---- the builder's side --------------------------------------------------------------------
g = tempfile.mkdtemp()
origin = tempfile.mkdtemp()


def sh(*a, cwd=g, env=None, check_=True):
    return subprocess.run(a, cwd=cwd, capture_output=True, text=True, env=env, check=check_)


sh("git", "init", "-q", "--bare", origin, cwd=origin)
sh("git", "init", "-q", "-b", "main")
sh("git", "config", "user.email", "t@example.org")
sh("git", "config", "user.name", "T")
for d in ("api", "deploy"):
    os.makedirs(os.path.join(g, d))
shutil.copy(os.path.join(ROOT, "deploy", "release-notes.py"), os.path.join(g, "deploy"))
shutil.copy(os.path.join(ROOT, "deploy", "publish-release.sh"), os.path.join(g, "deploy"))
open(os.path.join(g, "api", "a.py"), "w").write("1\n")
sh("git", "add", "-A")
sh("git", "commit", "-q", "-m", "First thing\n\nThe first.\n\nCo-Authored-By: X <x@example.org>")
sh("git", "tag", "build-1")
open(os.path.join(g, "api", "a.py"), "w").write("2\n")
sh("git", "commit", "-qam", "Second thing\n\nWhy it matters.\nClaude-Session: https://example.org/s")
open(os.path.join(g, "api", "a.py"), "w").write("3\n")
sh("git", "commit", "-qam", "Third thing")
notes = sh(sys.executable, "deploy/release-notes.py").stdout
check("### Second thing" in notes and "### Third thing" in notes and "First thing" not in notes,
      "the change log: the commits since the last release")
check("Why it matters." in notes and "Claude-Session" not in notes and "Co-Authored-By" not in notes,
      "each with its message, without trailers")

# publish-release.sh, with gh and the bundle makers stood in for.
bin_ = tempfile.mkdtemp()
log = os.path.join(bin_, "gh.log")
open(os.path.join(bin_, "gh"), "w").write(f"#!/bin/sh\necho \"$@\" >> {log}\nexit 0\n")
make = os.path.join(bin_, "make-x86")
open(make, "w").write("#!/bin/sh\nout=$2\ncount=$(git rev-list --count HEAD)\n"
                      "touch \"$out/humint-update-$count-$(git rev-parse --short=10 HEAD)-x86.tar\"\necho \"$@\" > "
                      f"{bin_}/make.args\n")
for f in ("gh", "make-x86"):
    os.chmod(os.path.join(bin_, f), 0o755)
env = {**os.environ, "PATH": bin_ + ":" + os.environ["PATH"], "HUMINT_MAKE_X86": make}
r = sh("bash", "deploy/publish-release.sh", "--yes", env=env, check_=False)
check(r.returncode != 0 and "not pushed" in r.stderr, "a commit not pushed is not released")
sh("git", "remote", "add", "origin", origin)
sh("git", "push", "-q", "origin", "main", "--tags")
open(os.path.join(g, "api", "a.py"), "w").write("dirty\n")
r = sh("bash", "deploy/publish-release.sh", "--yes", env=env, check_=False)
check(r.returncode != 0 and "uncommitted" in r.stderr, "nor a checkout with uncommitted changes")
sh("git", "checkout", "-q", "--", "api/a.py")
r = sh("bash", "deploy/publish-release.sh", "--yes", env=env, check_=False)
gh = open(log).read() if os.path.exists(log) else ""
check(r.returncode == 0 and "release create build-3" in gh and "humint-update-3-" in gh and "--notes-file" in gh,
      f"published as build-3 with the bundle and the notes ({r.stderr[-300:]})")
check("--no-os" in open(os.path.join(bin_, "make.args")).read(), "code only by default (an online box fetches Ubuntu's own)")
finish()
