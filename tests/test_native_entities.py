"""The native app's records: create one with its kind's fields, add a contact
and a relationship (to a record made on the spot), archive it, and protect a
source behind a code name."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import PASSWORD, ROOT, Console, check, finish  # noqa: E402

sys.path.insert(0, os.path.join(ROOT, "native", "tools"))
from shoot import FakeMachine  # noqa: E402
from appdriver import AppDriver  # noqa: E402

SHOTS = os.environ.get("SHOTS")


def shot(d, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        d.shot(os.path.join(SHOTS, name + ".png"))


c = Console("native_entities").start()
api = c.register_admin("ana")
m = FakeMachine()
m.unlock()
m.start(console_url=c.url)
d = AppDriver(m.sock, console_url=c.url)
d.login("ana", PASSWORD)

# ---- a new person -------------------------------------------------------------------
d.tap("Records")
d.tap("+ New record")
d.until(lambda: d.has_text("New record"), what="the form")
d.set_field("Name", "Marek Hale")
d.set_field("Aliases (comma-separated)", "The Driver, MH")
d.choose("Alignment", "Hostile")
d.set_field("Occupation", "Night driver")
shot(d, "20-entity-form")
d.tap("Create")
d.until(lambda: d.has_text("Night driver"), what="the new record")
row = c.sql("SELECT id, entity_type FROM entities WHERE name = 'Marek Hale'")
check(len(row) == 1 and row[0][1] == "person", "it creates a person")
det = api.get(c.url + "/api/entities/" + row[0][0]).json()["details"]
check(det.get("aliases") == ["The Driver", "MH"] and det.get("alignment") == "Hostile" and det.get("occupation") == "Night driver",
      f"with the person's own fields, aliases as a list ({det})")
marek = row[0][0]

# ---- contact -----------------------------------------------------------------------------
d.tap("+ Add contact")
d.choose("Type", "Mobile")
d.set_field("Value", "+1 555 0100")
d.tap("Add")
d.until(lambda: d.has_text("+1 555 0100"), what="the contact")
check(c.sql("SELECT kind, value FROM contact_points WHERE entity_id = %s", (marek,)) == [("Mobile", "+1 555 0100")],
      "a contact is added")

# ---- relationship, to a record made on the spot ------------------------------------------------
d.tap("+ Add relationship")
d.until(lambda: d.has_text("Add relationship"), what="the relationship form")
d.type("Search records", "Harbour Logistics")
d.until(lambda: d.button("+ New organisation") is not None, what="create offer")
d.tap("+ New organisation")
d.set_field("Relationship", "employed by")
d.tap("Add")
d.until(lambda: d.has_text("employed by"), what="the relationship")
rel = c.sql("SELECT r.relationship_type, e.name, e.entity_type FROM relationships r JOIN entities e ON e.id = r.to_entity_id "
            "WHERE r.from_entity_id = %s", (marek,))
check(rel == [("employed_by", "Harbour Logistics", "organization")], f"the relationship and the new organisation ({rel})")
shot(d, "21-entity")

# ---- archive -------------------------------------------------------------------------------
d.tap("Archive")
d.until(lambda: d.button("Reactivate") is not None, what="archived")
check(c.sql("SELECT is_active FROM entities WHERE id = %s", (marek,))[0][0] is False, "Archive archives it")
d.tap("Reactivate")
d.until(lambda: d.button("Archive") is not None, what="reactivated")

# ---- protect a source -----------------------------------------------------------------------------
d.tap("← Back")
d.tap("+ New record")
d.tap("Source")
d.set_field("Name", "Jana Novak")
d.tap("Create")
d.until(lambda: d.button("Protect this source…") is not None, what="source page")
d.tap("Protect this source…")
d.set_field("Code name", "KESTREL")
d.tap("Protect")
d.until(lambda: d.has_text("Known here by its code name"), what="protected")
src = c.sql("SELECT e.name, si.true_name FROM entities e JOIN source_identity si ON si.entity_id = e.id")
check(src == [("KESTREL", "Jana Novak")], f"the record now carries the code name, the identity holds the true name ({src})")
d.tap("Show identity")
d.until(lambda: any(t == "Jana Novak" for t in d.texts()), what="identity")
check(True, "its handler can read the true name")
shot(d, "22-source")
m.stop()
c.stop()
finish()
