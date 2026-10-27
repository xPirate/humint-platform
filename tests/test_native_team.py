"""The native app's Team page: a team member's profile and status, and
everything they have entered; an admin updating someone's status and
contacts; the report byline leading there."""
import os
import sys

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


c = Console("native_team").start()
admin = c.register_admin("ana")
c.add_user(admin, "bob")
bob, r = c.login("bob")
ok(r)
truck = ok(bob.post(c.url + "/api/entities", json={"entity_type": "vehicle", "name": "Red box truck"}))
ok(bob.post(c.url + "/api/entities", json={"entity_type": "person", "name": "Lee Marsh"}))
rep = ok(bob.post(c.url + "/api/reports", json={"title": "Truck at the depot", "body_markdown": "Seen twice.",
                                                  "entity_ids": [truck["id"]]}))

m = FakeMachine()
m.unlock()
m.start(console_url=c.url)
d = AppDriver(m.sock, console_url=c.url)
d.login("ana", PASSWORD)

# ---- the byline leads to the author's page ----------------------------------------------
d.tap("Reports")
d.until(lambda: d.button("Truck at the depot") is not None or d.has_text("Truck at the depot"), what="the report")
d.tap("Truck at the depot")
d.until(lambda: d.button("bob") is not None, what="byline")
d.tap("bob")
d.until(lambda: d.has_text("What bob has entered"), what="bob's page")
check(d.has_text("Red box truck") and d.has_text("Lee Marsh") and d.has_text("Truck at the depot"),
      "the report's author links to everything they have entered")
check(d.button("Records  2") is not None and d.button("Reports  1") is not None and d.button("Everything  3") is not None,
      "with a count for each kind")
d.tap("Reports  1")
d.until(lambda: not d.has_text("Lee Marsh"), what="filtered")
check(d.has_text("Truck at the depot"), "a kind narrows the list")
shot(d, "95-team")

# ---- an admin updates someone's status and how to reach them -------------------------------------
d.tap("Edit profile")
d.until(lambda: d.has_text("Profile — bob"), what="editor")
check(d.has_text("You are editing as an admin"), "an admin editing someone else is told it is logged")
d.type_into("How the team knows them", "Bob Ortiz")
d.choose("Status", "Under duress")
d.type_into("What is known, and when it was last confirmed", "Missed the 0600 check-in")
d.type_into("Kind", "Radio")
d.type_into("Number, address, node, handle…", "Ch 14")        # typed, not tabbed out of
d.tap("+ Add contact")
d.until(lambda: len([i for i in d.items() if i.property("placeholderText") == "Kind" and d.visible(i)]) == 2, what="second row")
kinds = [i for i in d.items() if i.property("placeholderText") == "Kind" and d.visible(i)]
vals = [i for i in d.items() if i.property("placeholderText") == "Number, address, node, handle…" and d.visible(i)]
check(kinds[0].property("text") == "Radio" and vals[0].property("text") == "Ch 14",
      "adding a row keeps what was typed in the others")
kinds[1].setProperty("text", "Mobile")
vals[1].setProperty("text", "+44 7700 900123")
d.tap("Save")
d.until(lambda: c.sql("SELECT status FROM user_profiles p JOIN users u ON u.id = p.user_id WHERE u.username = 'bob'") == [("Under duress",)],
        what="saved")
p = ok(admin.get(c.url + "/api/profiles/bob"))
check(p["display_name"] == "Bob Ortiz" and p["status_note"] == "Missed the 0600 check-in"
      and p["status_changed_by"] == "ana", f"the status is saved, with who set it ({p['status_changed_by']})")
check([(x["kind"], x["value"]) for x in p["contacts"]] == [("Radio", "Ch 14"), ("Mobile", "+44 7700 900123")],
      f"and the contacts as typed ({p['contacts']})")
d.until(lambda: d.has_text("Missed the 0600 check-in"), what="the card")
check(d.has_text("Under duress") and d.has_text("Ch 14"), "the card shows the new status and contacts")

# ---- an item opens its record; your own page from the menu ---------------------------------------------
d.tap("Everything  3")
d.until(lambda: d.has_text("Lee Marsh"), what="all items")
d.tap("Red box truck")
d.until(lambda: d.has_text("Red box truck") and d.button("Edit") is not None, what="the record")
check(True, "an item opens its record")
d.tap("Analysts")
d.until(lambda: d.has_text("What ana has entered"), what="own page")
check(True, "Analysts opens on your own page")
finish()
