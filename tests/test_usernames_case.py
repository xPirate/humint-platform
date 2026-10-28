"""Usernames ignore case: "Thomas" and "thomas", "TPain" and "tpain" are one
account — for signing in, and for taking a name — while each is still shown
as it was typed. And the migration for databases from before (v1.14)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import PASSWORD, ROOT, Console, check, finish  # noqa: E402

c = Console("usernames").start()
admin = c.register_admin("Thomas")

r = admin.post(c.url + "/api/auth/register", json={"username": "TPain", "password": PASSWORD, "role": "analyst"})
check(r.ok, "an account TPain is made")
for name in ("tpain", "TPAIN", "tPaIn", "  tpain  ", "thomas"):
    r = admin.post(c.url + "/api/auth/register", json={"username": name, "password": PASSWORD, "role": "analyst"})
    check(r.status_code == 409, f"{name.strip()!r} is the same name: refused ({r.status_code})")
check("TPain" in r.text or "Thomas" in r.text, f"and the refusal says which account has it ({r.json().get('detail')})")
check(c.sql("SELECT count(*) FROM users")[0][0] == 2, "no second account was made")

for typed, shown in (("tpain", "TPain"), ("TPAIN", "TPain"), ("thomas", "Thomas"), ("  THOMAS ", "Thomas")):
    s, r = c.login(typed)
    check(r.status_code == 200 and r.json()["username"] == shown,
          f"signing in as {typed.strip()!r} works, as {shown} ({r.status_code})")
me = s.get(c.url + "/api/auth/me").json()
check(me["username"] == "Thomas", "the session is the account's own spelling")
audit = c.sql("SELECT actor_username FROM audit_log WHERE action = 'auth.login' ORDER BY id DESC LIMIT 1")
check(audit == [("Thomas",)], f"and so is the audit log ({audit})")
s, r = c.login("tpain", "wrong-password-123")
check(r.status_code == 401, "a wrong password is still wrong")

# The database itself refuses a second account that differs only in case.
try:
    c.sql("INSERT INTO users (username, password_hash) VALUES ('THOMAS', 'x')")
    check(False, "the database refuses a case-only duplicate")
except Exception as e:
    check("users_username_lower_key" in str(e), "the database refuses a case-only duplicate")

# ---- the migration, on a database from before -----------------------------------
old = Console("usernames_old")
old.sql("DROP INDEX users_username_lower_key")
old.sql("INSERT INTO users (username, password_hash) VALUES ('Alpha', 'x'), ('bravo', 'x'), ('alpha', 'x'), "
        "('ALPHA', 'x'), ('Bravo', 'x')")
mig = os.path.join(ROOT, "db", "migrate-v1.14-usernames.sql")
old.sql_file(mig)
names = [r[0] for r in old.sql("SELECT username FROM users ORDER BY id")]
ids = [r[0] for r in old.sql("SELECT id FROM users ORDER BY id")]
check(names == ["Alpha", "bravo", f"alpha-{ids[2]}", f"ALPHA-{ids[3]}", f"Bravo-{ids[4]}"],
      f"the oldest of each keeps its name; the newer get name-<id> ({names})")
renames = old.sql("SELECT object_label, detail->>'from' FROM audit_log WHERE action = 'user.rename' ORDER BY id")
check(len(renames) == 3 and renames[0] == (f"alpha-{ids[2]}", "alpha"), f"each rename is in the audit log ({renames})")
old.sql_file(mig)
check([r[0] for r in old.sql("SELECT username FROM users ORDER BY id")] == names, "running it twice changes nothing")
finish()
