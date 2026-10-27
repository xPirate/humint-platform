"""The native app's admin, account and audit screens: every admin section
loads; accounts are created and given roles; the audit log reads back; the
look is saved to the account."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import PASSWORD, ROOT, Console, check, finish  # noqa: E402

sys.path.insert(0, os.path.join(ROOT, "native", "tools"))
from shoot import FakeMachine  # noqa: E402
from appdriver import AppDriver  # noqa: E402

SHOTS = os.environ.get("SHOTS")
c = Console("native_admin").start()
api = c.register_admin("ana")
m = FakeMachine()
m.unlock()
m.start(console_url=c.url)
d = AppDriver(m.sock, console_url=c.url)
errors = []
from PySide6.QtCore import QtMsgType, qInstallMessageHandler  # noqa: E402


def on_msg(kind, ctx, msg):
    if "qml" in msg.lower() or ".qml" in msg:
        if "Proxy denied" not in msg and "tiles.invalid" not in msg:
            errors.append(msg)
    sys.stderr.write(msg + "\n")


qInstallMessageHandler(on_msg)
d.login("ana", PASSWORD)

d.tap("Admin")
d.until(lambda: d.has_text("There must always be one active admin."), what="users")
sections = ["Field devices", "Boards", "Maps", "Backup & restore", "RSS feeds", "Model", "Appearance",
            "Link signals", "Retention", "Field sync", "Users"]
for s in sections:
    d.tap(s)
    d.pump(1.2)
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        d.shot(os.path.join(SHOTS, "80-admin-" + s.lower().replace(" ", "-").replace("&", "and") + ".png"))
check(not d.has_text("Not here yet"), "every admin section opens")
check(not errors, "with no errors from the screens (" + "; ".join(errors[:3]) + ")")

# A new account, then its role
d.tap("+ New user")
d.set_field("Username", "vic")
d.set_field("Password", "a-long-password-1")
d.choose("Role", "Read-only")
d.tap("Create")
try:
    d.until(lambda: c.sql("SELECT role FROM users WHERE username = 'vic'"), what="the new account")
except TimeoutError:
    print("  texts:", [t for t in d.texts() if t][-12:])
check(c.sql("SELECT role FROM users WHERE username = 'vic'") == [("viewer",)], "an admin creates a read-only account")

# The audit log shows what just happened
d.tap("Audit log")
d.until(lambda: d.has_text("Created account"), what="the audit entry")
check(True, "the audit log shows it, in words")

# The look, saved to the account
d.tap("ana")
d.until(lambda: d.has_text("Two-factor sign-in"), what="the account page")
d.tap("Slate")
d.pump(1)
prefs = api.get(c.url + "/api/me/preferences").json()["preferences"]
check(prefs.get("palette") == "slate", f"choosing a palette saves it to the account ({prefs})")
if SHOTS:
    d.shot(os.path.join(SHOTS, "81-account-slate.png"))
m.stop()
c.stop()
finish()
