"""The native app's boards and priorities: post a lookout and close it out,
put someone on the roster, set a priority and answer it."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import PASSWORD, ROOT, Console, check, finish, ok  # noqa: E402

sys.path.insert(0, os.path.join(ROOT, "native", "tools"))
from shoot import FakeMachine  # noqa: E402
from appdriver import AppDriver  # noqa: E402

SHOTS = os.environ.get("SHOTS")
c = Console("native_boards").start()
api = c.register_admin("ana")
ok(api.put(c.url + "/api/admin/boards", json={"bolo": {"enabled": True}, "roster": {"enabled": True, "label": "Team"},
                                               "priorities": {"enabled": True}}))
van = ok(api.post(c.url + "/api/entities", json={"entity_type": "vehicle", "name": "Grey Transit van"}))
ok(api.post(c.url + "/api/entities", json={"entity_type": "person", "name": "Jo Reyes"}))
m = FakeMachine()
m.unlock()
m.start(console_url=c.url)
d = AppDriver(m.sock, console_url=c.url)
d.login("ana", PASSWORD)

# ---- BOLO -------------------------------------------------------------------------------
d.tap("BOLO")
d.until(lambda: d.has_text("That is the good state"), what="the empty board")
d.tap("+ Post a lookout")
d.type("Search records", "Grey")
d.until(lambda: d.button("Grey Transit van") is not None, what="the record")
d.tap("Grey Transit van")
box = d._under_label("What to do if you see it")
for ch in d._descendants(box):
    if ch.metaObject().indexOfProperty("cursorPosition") >= 0:
        ch.setProperty("text", "Do not approach. Call it in.")
d.choose("Urgency", "Urgent")
d.tap("Add")
d.until(lambda: d.has_text("Do not approach. Call it in."), what="the lookout")
row = c.sql("SELECT urgency, reason, status FROM board_entries WHERE entity_id = %s", (van["id"],))
check(row == [("Urgent", "Do not approach. Call it in.", "active")], f"a lookout is posted ({row})")
if SHOTS:
    os.makedirs(SHOTS, exist_ok=True); d.shot(os.path.join(SHOTS, "70-bolo.png"))
d.tap("Close out")
d.set_field("What happened", "Recovered at the yard")
d.tap("Close out")
d.until(lambda: d.has_text("That is the good state"), what="closed out")
check(c.sql("SELECT status, resolved_note FROM board_entries WHERE entity_id = %s", (van["id"],)) == [("resolved", "Recovered at the yard")],
      "closing it out records what happened")

# ---- roster (the board an admin renamed "Team") ------------------------------------------------
d.tap("Team")
d.tap("+ Add to the roster")
d.type("Search records", "Jo")
d.until(lambda: d.button("Jo Reyes") is not None, what="the person")
d.tap("Jo Reyes")
d.set_field("Callsign", "Alpha Six")
d.tap("Add")
d.until(lambda: d.has_text("Alpha Six"), what="the roster card")
check(True, "someone is put on the roster with a callsign")

# ---- priorities ------------------------------------------------------------------------------
d.tap("Priorities")
d.tap("+ New priority")
d.set_field("Title", "Who runs the night shift at the docks?")
d.choose("How badly", "P1 — drop other work")
d.tap("Save")
d.until(lambda: d.has_text("Who runs the night shift at the docks?"), what="the priority")
check(c.sql("SELECT priority, status FROM intel_priorities") == [(1, "open")], "a priority is set")
d.tap("Answer it")
box = d._under_label("What we found")
for ch in d._descendants(box):
    if ch.metaObject().indexOfProperty("cursorPosition") >= 0:
        ch.setProperty("text", "Marek Hale, since March.")
d.tap("Mark answered")
d.until(lambda: not d.has_text("Who runs the night shift at the docks?"), what="answered")
check(c.sql("SELECT status, answered_note FROM intel_priorities") == [("answered", "Marek Hale, since March.")], "and answered")
m.stop()
c.stop()
finish()
