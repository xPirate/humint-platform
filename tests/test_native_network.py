"""The native app's network: the case file as one picture, laid out on a
worker thread; filtering by type; focusing on one record (direct links, two
steps out, back); and the record page's way in."""
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


c = Console("native_network").start()
api = c.register_admin("ana")


def ent(t, name):
    return ok(api.post(c.url + "/api/entities", json={"entity_type": t, "name": name}))


def link(a, b, kind="associate_of"):
    ok(api.post(c.url + "/api/relationships", json={"from_entity_id": a["id"], "to_entity_id": b["id"],
                                                     "relationship_type": kind}))


hub = ent("person", "Viktor Hale")
crew = [ent("person", f"Crew member {i}") for i in range(1, 7)]
firm = ent("organization", "Hale Logistics")
yard = ent("location", "North Yard")
far = ent("person", "Distant Contact")
lone = ent("vehicle", "Unlinked Scooter")
for p in crew:
    link(p, hub)
link(hub, firm, "employed_by")
link(firm, yard, "located_at")
link(yard, far)                         # two steps from the firm, three from Viktor

m = FakeMachine()
m.unlock()
m.start(console_url=c.url)
d = AppDriver(m.sock, console_url=c.url)
d.login("ana", PASSWORD)


def graph():
    return next((i for i in d.items() if i.metaObject().indexOfProperty("settling") >= 0 and d.visible(i)), None)


def settled():
    g = graph()
    return g is not None and not g.property("settling") and len(g.property("nodes").toVariant()
                                                                  if hasattr(g.property("nodes"), "toVariant") else g.property("nodes")) > 0


def names():
    ns = graph().property("nodes")
    ns = ns.toVariant() if hasattr(ns, "toVariant") else ns
    return {n["name"] for n in ns}


d.tap("Records")
d.tap("Network")
d.until(settled, timeout=30, what="the network laid out")
check(names() == {"Viktor Hale", "Hale Logistics", "North Yard", "Distant Contact", "Unlinked Scooter"}
      | {f"Crew member {i}" for i in range(1, 7)}, "every record is in the picture")
check(d.has_text("11 records · 9 links"), "with a count of records and links")
pos = graph().property("pos")
pos = pos.toVariant() if hasattr(pos, "toVariant") else pos
check(len(pos) == 11 and len({(round(p[0]), round(p[1])) for p in pos.values()}) == 11,
      "the worker placed every record, each somewhere of its own")
shot(d, "96-network")

d.tap("Hide unconnected")
d.until(lambda: settled() and "Unlinked Scooter" not in names(), what="isolated hidden")
check(True, "Hide unconnected drops the record with no links")
d.tap("Organisations")
d.until(lambda: settled() and names() == {"Hale Logistics"}, what="organisations only")
check(True, "a type narrows the picture")
d.tap("All")
d.until(lambda: settled() and "Viktor Hale" in names(), what="all again")

# Focus: double-tap Viktor.
from PySide6.QtCore import Q_ARG, QMetaObject  # noqa: E402
g = graph()
ns = g.property("nodes"); ns = ns.toVariant() if hasattr(ns, "toVariant") else ns
viktor = next(n for n in ns if n["name"] == "Viktor Hale")
QMetaObject.invokeMethod(g, "doubleTapped", Q_ARG("QVariant", viktor))
d.until(lambda: d.has_text("Focused on") and settled() and "North Yard" not in names(), what="focused")
check(names() == {"Viktor Hale", "Hale Logistics"} | {f"Crew member {i}" for i in range(1, 7)},
      "focusing shows the record and what it links to directly")
check(d.has_text("7 linked"), "and says how many")
d.tap("Two steps out")
d.until(lambda: settled() and "North Yard" in names(), what="two steps")
check("Distant Contact" not in names() and d.has_text("1 more one step further"),
      "two steps out adds what those link to, and no further")
shot(d, "97-network-focus")

# Focus moves on, and Back returns.
g = graph()
ns = g.property("nodes"); ns = ns.toVariant() if hasattr(ns, "toVariant") else ns
yardn = next(n for n in ns if n["name"] == "North Yard")
QMetaObject.invokeMethod(g, "picked", Q_ARG("QVariant", yardn))
d.until(lambda: d.button("Focus on it") is not None, what="selection card")
check(d.has_text("2 links in the case file"), "tapping a record says what it is and how linked")
d.tap("Focus on it")
d.until(lambda: settled() and "Distant Contact" in names(), what="focus moved")
d.tap("◀ Back")
d.until(lambda: settled() and "Crew member 1" in names(), what="back to Viktor")
check(True, "Back returns to the record focused before")
d.tap("✕ Show everything")
d.until(lambda: settled() and "Unlinked Scooter" not in names() and len(names()) == 10, what="everything")
check(True, "Show everything leaves the focus")

# From a record's own page. ("Records" is also a type here: via the Dashboard.)
d.tap("Dashboard")
d.tap("Records")
d.tap("Hale Logistics")
d.until(lambda: d.button("Network around this") is not None, what="record page")
d.tap("Network around this")
d.until(lambda: d.has_text("Focused on") and settled() and names() == {"Hale Logistics", "Viktor Hale", "North Yard"},
        what="focused on the firm")
check(True, "a record's page opens the network focused on it")
finish()
