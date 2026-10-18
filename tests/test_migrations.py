"""Every migration applies to a database built from the previous release, and
twice in a row; and a fresh install and an upgraded one end with the same
columns."""
import glob
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import ROOT, Console, check, finish  # noqa: E402

# The schema as of the last release, from git: what an existing install has.
BASE = os.environ.get("MIGRATION_BASE", "v1.4")
old = subprocess.run(["git", "-C", ROOT, "show", f"{BASE}:db/init.sql"], capture_output=True, text=True)
if old.returncode != 0:
    print(f"(no {BASE} in git history here; using the schema from HEAD~1)")
    old = subprocess.run(["git", "-C", ROOT, "show", "HEAD~1:db/init.sql"], capture_output=True, text=True)
import tempfile  # noqa: E402
fd, path = tempfile.mkstemp(prefix="humint-old-init-", suffix=".sql")
with os.fdopen(fd, "w") as fh:
    fh.write(old.stdout)

def columns(console):
    return set(console.sql("SELECT table_name || '.' || column_name FROM information_schema.columns "
                           "WHERE table_schema = 'public'"))

upgraded = Console("upgraded", schema=path)
migrations = sorted(glob.glob(os.path.join(ROOT, "db", "migrate-v*.sql")),
                    key=lambda p: [int(x) for x in os.path.basename(p).split("-")[1][1:].split(".")])
for m in migrations:
    for attempt in (1, 2):
        try:
            upgraded.sql_file(m)
            ok = True
        except Exception as e:  # noqa: BLE001
            ok = False
            print("   ", type(e).__name__, str(e).splitlines()[0])
        check(ok, f"{os.path.basename(m)} applies (run {attempt})")

fresh = Console("fresh")
missing = columns(fresh) - columns(upgraded)
check(not missing, f"an upgraded database has every column a fresh one has {sorted(missing)[:10]}")
finish()
