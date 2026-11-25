"""Updating the Docker deployment: ./update.sh, and Admin → Backup & restore →
Check for updates on a Docker console.

./update.sh runs here against a git checkout and a real database, with
`docker` stood in for (it passes psql, pg_dump and pg_restore through to the
test database and records the rest): it shows the change log and the
migrations, backs up, moves the code forward, runs each migration once
(recorded in schema_migrations), and --rollback puts code and database back.
The console's check compares its recorded commit with GitHub (a stand-in)."""
import http.server
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import ROOT, Console, check, finish, free_port  # noqa: E402

# ---- the console's check, on a Docker deployment ----------------------------------------------
REPO = "xPirate/humint-platform"


class FakeGitHub(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith(f"/repos/{REPO}/compare/abc123...main"):
            body = {"ahead_by": 2, "commits": [
                {"sha": "1111111111aa", "html_url": "https://github.com/x/1", "commit": {
                    "message": "Outside events: triage\n\nThe model reads each incident.\n\nCo-Authored-By: X <x@y>",
                    "committer": {"date": "2026-11-20T10:00:00Z"}}},
                {"sha": "2222222222bb", "html_url": "https://github.com/x/2", "commit": {
                    "message": "Web research", "committer": {"date": "2026-11-21T10:00:00Z"}}}]}
            data, code = json.dumps(body).encode(), 200
        else:
            data, code = b'{"message": "Not Found"}', 404
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


gh = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeGitHub)
threading.Thread(target=gh.serve_forever, daemon=True).start()
tmp = tempfile.mkdtemp()
binfo = os.path.join(tmp, "build-info.json")
c = Console("docker_update_check", env={"UPDATE_GITHUB_API": f"http://127.0.0.1:{gh.server_port}",
                                        "DOCKER_BUILD_FILE": binfo, "BUILD_FILE": os.path.join(tmp, "none.json")}).start()
admin = c.register_admin()
o = admin.get(c.url + "/api/admin/field-update/online").json()
check(o["docker"] and o["behind"] is None, "a Docker console with no recorded version says so")
json.dump({"build": 120, "commit": "abc123", "updated_at": "2026-11-19T00:00:00Z"}, open(binfo, "w"))
st = admin.get(c.url + "/api/admin/field-update").json()
check(st["managed"] is False and st["installed"]["commit"] == "abc123", "the status shows what ./update.sh recorded")
o = admin.get(c.url + "/api/admin/field-update/online?refresh=true").json()
check(o["behind"]["ahead_by"] == 2 and o["update_command"] == "./update.sh", "the changes on GitHub since then")
check(o["behind"]["commits"][0]["subject"] == "Web research"
      and o["behind"]["commits"][1]["body"] == "The model reads each incident.", "newest first, without trailers")
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None
if sync_playwright:
    from harness import PASSWORD  # noqa: E402
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.environ.get("CHROMIUM") or None)
        page = browser.new_page(viewport={"width": 1300, "height": 950})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(c.url)
        page.fill("#login-username", "admin")
        page.fill("#login-password", PASSWORD)
        page.click("#login-form button[type=submit]")
        page.wait_for_selector("#app:not([hidden])")
        page.evaluate("() => { switchView('admin'); showAdminSection('backup'); }")
        page.wait_for_selector("#docker-update-check:visible")
        check("abc123" in page.inner_text("#docker-update-status") and page.is_hidden("#field-update-block"),
              "Admin on a Docker server: its version, not the field-box upload")
        page.click("#docker-update-check")
        page.wait_for_selector("#docker-update-result .update-available")
        t = page.inner_text("#docker-update-result")
        check("2 changes on GitHub" in t and "Web research" in t and "./update.sh" in t,
              "Check for updates: the changes, and the command that applies them")
        if os.environ.get("SHOTS_DIR"):
            page.screenshot(path=os.path.join(os.environ["SHOTS_DIR"], "docker-update.png"), full_page=True)
        check(not errors, f"no page errors ({errors[:3]})")
        browser.close()
c.stop()

# ---- ./update.sh -------------------------------------------------------------------------------
db = Console("docker_update_db")                     # a database at today's schema (init.sql)
srv = db.server
health = http.server.ThreadingHTTPServer(("127.0.0.1", free_port()), type("H", (http.server.BaseHTTPRequestHandler,), {
    "log_message": lambda *a: None,
    "do_GET": lambda self: (self.send_response(200), self.send_header("Content-Length", "2"), self.end_headers(),
                            self.wfile.write(b"ok"))}))
threading.Thread(target=health.serve_forever, daemon=True).start()

bin_ = tempfile.mkdtemp()
log = os.path.join(bin_, "docker.log")
fake = f'''#!/usr/bin/env python3
import os, subprocess, sys
a = sys.argv[1:]
open({log!r}, "a").write(" ".join(a) + "\\n")
if a[:2] == ["compose", "version"]:
    sys.exit(0)
if a[:3] == ["compose", "exec", "-T"] and a[3] == "db":
    cmd = a[4:]
    if cmd[0] == "pg_isready":
        sys.exit(0)
    # -U/-d: the test database
    env = dict(os.environ, PGHOST={srv.host!r}, PGPORT={str(srv.port)!r}, PGPASSWORD={srv.password!r})
    sys.exit(subprocess.call(cmd, env=env))
sys.exit(0)        # build, up, stop: recorded only
'''
open(os.path.join(bin_, "docker"), "w").write(fake)
os.chmod(os.path.join(bin_, "docker"), 0o755)

origin = tempfile.mkdtemp()
work = tempfile.mkdtemp()
server = os.path.join(tempfile.mkdtemp(), "humint-platform")


def git(*a, cwd):
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, check=True).stdout


git("init", "-q", "--bare", "-b", "main", cwd=origin)
git("init", "-q", "-b", "main", cwd=work)
for k, v in (("user.email", "t@example.org"), ("user.name", "T")):
    git("config", k, v, cwd=work)
shutil.copy(os.path.join(ROOT, "update.sh"), work)
shutil.copytree(os.path.join(ROOT, "db"), os.path.join(work, "db"))
os.makedirs(os.path.join(work, "api"))
open(os.path.join(work, "api", "main.py"), "w").write("v = 1\n")
open(os.path.join(work, ".gitignore"), "w").write(".env\nbackups/\napi/build-info.json\n")
git("add", "-A", cwd=work)
git("commit", "-qm", "First version", cwd=work)
git("remote", "add", "origin", origin, cwd=work)
git("push", "-q", "origin", "main", cwd=work)
subprocess.run(["git", "clone", "-q", origin, server], check=True)
for k, v in (("user.email", "t@example.org"), ("user.name", "T")):
    git("config", k, v, cwd=server)
open(os.path.join(server, ".env"), "w").write(
    f"POSTGRES_USER={srv.user}\nPOSTGRES_DB={db.dbname}\nAPI_PORT={health.server_address[1]}\n")

# Upstream: a change, and a migration this database has not had.
open(os.path.join(work, "api", "main.py"), "w").write("v = 2\n")
open(os.path.join(work, "db", "migrate-v9.99-test.sql"), "w").write(
    "BEGIN;\nCREATE TABLE IF NOT EXISTS update_test (id INT);\nCOMMIT;\n")
git("add", "-A", cwd=work)
git("commit", "-qm", "Second version\n\nWith a migration.", cwd=work)
git("push", "-q", "origin", "main", cwd=work)

env = dict(os.environ, PATH=bin_ + ":" + os.environ["PATH"])


def run(*a):
    return subprocess.run(["./update.sh", *a], cwd=server, env=env, capture_output=True, text=True)


r = run("--check")
check(r.returncode == 0 and "Second version" in r.stdout and "migrate-v9.99-test.sql" in r.stdout,
      f"--check: the change log and the migrations to run ({r.stdout[-400:]}{r.stderr[-300:]})")
check(open(os.path.join(server, "api", "main.py")).read() == "v = 1\n", "and changes nothing")

open(os.path.join(server, "api", "main.py"), "w").write("mine\n")
r = run("--yes")
check(r.returncode != 0 and "local changes" in r.stderr, "it will not update over local changes to tracked files")
git("checkout", "--", "api/main.py", cwd=server)

r = run("--yes")
check(r.returncode == 0 and "Updated to" in r.stdout, f"--yes: updated ({r.stdout[-500:]}{r.stderr[-500:]})")
check(open(os.path.join(server, "api", "main.py")).read() == "v = 2\n", "the code moved forward")
dumps = [f for f in os.listdir(os.path.join(server, "backups")) if f.endswith(".dump")]
check(len(dumps) == 1 and os.path.getsize(os.path.join(server, "backups", dumps[0])) > 1000, "the database was backed up first")
done = {r_[0] for r_ in db.sql("SELECT name FROM schema_migrations")}
check("migrate-v9.99-test.sql" in done and "migrate-v1.19-web-research.sql" in done
      and db.sql("SELECT to_regclass('update_test') IS NOT NULL")[0][0], "every migration ran once, and is recorded")
calls = open(log).read()
check("compose build api worker" in calls and "compose stop api worker" in calls and calls.rstrip().endswith("compose up -d"),
      "rebuilt, stopped for the migrations, started again")
bi = json.load(open(os.path.join(server, "api", "build-info.json")))
check(bi["commit"] == git("rev-parse", "HEAD", cwd=server).strip() and bi["build"] == 2,
      "the version is recorded for Check for updates")
open(log, "w").close()
r = run("--yes")
check("Nothing to do" in r.stdout and "compose build" not in open(log).read(), "run again: nothing to do")

# Rollback: the code and the database from before.
db.sql("CREATE TABLE after_update (id INT)")
r = run("--rollback", "--yes")
check(r.returncode == 0 and open(os.path.join(server, "api", "main.py")).read() == "v = 1\n",
      f"--rollback: the previous code ({r.stderr[-300:]})")
check(not db.sql("SELECT to_regclass('update_test') IS NOT NULL")[0][0], "and the database as it was before the update")
check(run("--rollback", "--yes").returncode != 0, "a rollback is used once")
finish()
