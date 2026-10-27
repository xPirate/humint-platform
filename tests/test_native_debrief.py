"""The native app's guided debrief: five steps from a person in front of you
to a filed report, every name made into a record as it is given, a place
pointed at on the map, and an unfinished debrief kept for its writer only."""
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


c = Console("native_debrief").start()
api = c.register_admin("ana")
ok(api.post(c.url + "/api/auth/register", json={"username": "bob", "password": PASSWORD, "role": "analyst"}))
van = ok(api.post(c.url + "/api/entities", json={"entity_type": "vehicle", "name": "Grey Transit van"}))
m = FakeMachine()
m.unlock()
m.start(console_url=c.url)
d = AppDriver(m.sock, console_url=c.url)
d.login("ana", PASSWORD)

d.tap("Reports")
d.tap("Guided debrief")
d.until(lambda: d.has_text("Who are you debriefing?"), what="step 1")

# ---- 1: the source, made on the spot ------------------------------------------------
d.type("Name of the person being debriefed", "Marta Silva")
d.until(lambda: d.button("+ New source") is not None, what="create offer")
d.tap("+ New source")
d.until(lambda: c.sql("SELECT count(*) FROM entities WHERE name = 'Marta Silva' AND entity_type = 'source'")[0][0] == 1,
        what="the source record")
check(True, "a source named for the first time becomes a record at once")
d.choose("Source reliability (Admiralty A–F)", "B — Usually reliable")
check(d.has_text("Also save this rating on the source"), "a source record offers to keep the rating")
shot(d, "92-debrief-source")
d.tap("Next →")

# ---- 2: when and where, and a point on the map --------------------------------------------
d.until(lambda: d.has_text("When and where did this happen?"), what="step 2")
d.type("Where did it happen?", "Pier 4")
d.until(lambda: d.button("+ New location") is not None, what="create location")
d.tap("+ New location")
d.until(lambda: d.has_text("Address, grid reference or landmark"), what="address field")
d.tap("Point at it on the map")
d.until(lambda: any(i.metaObject().indexOfSignal("placed(double,double)") >= 0 for i in d.items()), what="the map")
pm = next(i for i in d.items() if i.metaObject().indexOfSignal("placed(double,double)") >= 0)
from PySide6.QtCore import Q_ARG, QMetaObject  # noqa: E402
QMetaObject.invokeMethod(pm, "tapped", Q_ARG(float, 51.5101), Q_ARG(float, -0.0201))
d.pump(0.3)
check(d.has_text("51.51010, -0.02010"), "tapping the map pins the place")
d.type_into("e.g. the yard behind the grain store", "The yard behind the grain store")
check(c.sql("SELECT count(*) FROM entities WHERE name = 'The yard behind the grain store'")[0][0] == 0,
      "the pinned place is not a record yet")
d.tap("Next →")

# ---- 3: who else -------------------------------------------------------------------------------
d.until(lambda: d.has_text("Who else was involved?"), what="step 3")
d.type("Add a person, organisation or means of communication", "Dan Brook")
d.until(lambda: d.button("+ New person") is not None, what="create person")
d.tap("+ New person")
d.until(lambda: d.field("Their part in this") is not None, what="role field")
f = d.field("Their part in this")
f.setProperty("text", "Drove the van")
QMetaObject.invokeMethod(f, "editingFinished")
d.until(lambda: c.sql("SELECT description FROM entities WHERE name = 'Dan Brook'") == [("Drove the van",)],
        what="description")
check(True, "a new person's part becomes their record's description")
d.tap("Next →")

# ---- 4: what happened, with a mention -----------------------------------------------------------
d.until(lambda: d.has_text("What happened?"), what="step 4")
d.tap("What did you see?")
d.type("They said that…", "The @Grey")
d.until(lambda: d.button("Grey Transit van") is not None, what="mention menu")
d.tap("Grey Transit van")
d.type("They said that…", "left at 0340.")
shot(d, "93-debrief-narrative")

# Leaving part-way keeps it — for this person, in memory.
d.tap("Dashboard")
d.tap("Reports")
d.tap("Guided debrief")
d.until(lambda: d.button("Pick it up") is not None, what="resume offer")
d.tap("Pick it up")
d.until(lambda: d.has_text("What happened?"), what="back at step 4")
check(d.has_text("left at 0340."), "an unfinished debrief is picked up where it was left")
d.tap("Next →")

# ---- 5: assessment, then file it ---------------------------------------------------------------------
d.until(lambda: d.has_text("Your assessment"), what="step 5")
d.type("What this confirms, contradicts or leaves open. @ works here too.", "Fits the yard sightings.")
d.choose("Credibility of this information", "2 — Probably true")
d.choose("Criticality", "Priority — same day")
check(d.has_text("Marta Silva") and d.has_text("Made during this debrief"), "the review lists what was gathered")
shot(d, "94-debrief-review")
d.tap("Create report")
d.until(lambda: c.sql("SELECT count(*) FROM reports")[0][0] == 1, timeout=15, what="the report")
title, body, cred, crit = c.sql("SELECT title, body_markdown, credibility_rating, criticality FROM reports")[0]
check(title.startswith("Debrief — Marta Silva — "), f"it is titled from the source and date ({title!r})")
check(all(h in body for h in ("## Source", "## When and where", "## Who was involved", "## Narrative", "## Assessment")),
      "the report has its sections")
check("reliability B (Usually reliable)" in body and "**What did you see?**" in body and "Drove the van" in body,
      "with the rating, the question worked through and each person's part")
check((cred, crit) == ("2", "Priority"), f"credibility and criticality are set ({cred}, {crit})")
place = c.sql("SELECT id, entity_type FROM entities WHERE name = 'The yard behind the grain store'")
pd = ok(api.get(c.url + f"/api/entities/{place[0][0]}"))["details"] if place else {}
check(len(place) == 1 and place[0][1] == "location" and abs(float(pd.get("lat")) - 51.5101) < 1e-5
      and abs(float(pd.get("lng")) + 0.0201) < 1e-5, f"the pinned place became a Location on filing ({place}, {pd})")
linked = {r[0] for r in c.sql("SELECT e.name FROM report_entities re JOIN entities e ON e.id = re.entity_id")}
check({"Marta Silva", "Pier 4", "Dan Brook", "Grey Transit van", "The yard behind the grain store"} <= linked,
      f"everyone gathered is linked to the report ({sorted(linked)})")
marta = c.sql("SELECT id FROM entities WHERE name = 'Marta Silva'")[0][0]
check(ok(api.get(c.url + f"/api/entities/{marta}"))["details"].get("reliability_rating") == "B",
      "the rating is saved on the source")
d.until(lambda: d.has_text("Fits the yard sightings."), what="the report page")
check(True, "and it opens the filed report")

# ---- an unfinished debrief is its writer's alone -------------------------------------------------------
d.tap("Dashboard")
d.tap("Reports")
d.tap("Guided debrief")
d.until(lambda: d.has_text("Who are you debriefing?"), what="a fresh debrief")
d.tap("Next →"); d.tap("Next →"); d.tap("Next →")
d.type("They said that…", "Half a note for ana only.")
d.tap("ana")              # your name, top right: the Account page
d.tap("Sign out")
d.login("bob", PASSWORD)
d.tap("Reports")
d.tap("Guided debrief")
d.until(lambda: d.has_text("Who are you debriefing?"), what="bob s debrief")
d.pump(0.5)
check(d.button("Pick it up") is None, "signing out drops an unfinished debrief: the next person is not offered it")
finish()
