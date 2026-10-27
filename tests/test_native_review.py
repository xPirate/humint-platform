"""The native app's review inbox: a phone report accepted as a draft report,
a suggested record accepted (as another kind), a duplicate pair merged."""
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


c = Console("native_review").start()
api = c.register_admin("ana")
U = c.url
c.sql("INSERT INTO field_submissions (device_label, title, body, criticality, lat, lng) "
      "VALUES ('Ana''s Pixel', 'Grey van at the gate', 'Two men, unloading crates.', 'Priority', 51.5, -0.12)")
c.sql("INSERT INTO extraction_suggestions (suggestion_type, suggested_entity_type, suggested_name, confidence, status, source) "
      "VALUES ('entity', 'person', 'Harbour Logistics', 0.8, 'pending', 'extraction')")
a = ok(api.post(U + "/api/entities", json={"entity_type": "person", "name": "Marek Hale", "description": "Driver"}))
b = ok(api.post(U + "/api/entities", json={"entity_type": "person", "name": "M. Hale"}))
c.sql("UPDATE entities SET description = 'Driver' WHERE id = %s", (a["id"],))
c.sql("INSERT INTO correlation_suggestions (subject_type, subject_a_id, subject_b_id, similarity_score) VALUES ('entity', %s, %s, 0.93)",
      (a["id"], b["id"]))

m = FakeMachine()
m.unlock()
m.start(console_url=c.url)
d = AppDriver(m.sock, console_url=c.url)
d.login("ana", PASSWORD)

d.tap("Review inbox")
d.until(lambda: d.has_text("Grey van at the gate"), what="the phone report")
shot(d, "30-review-phones")
d.tap("Accept as a draft report")
d.until(lambda: not d.has_text("Grey van at the gate"), what="accepted")
rep = c.sql("SELECT status FROM reports WHERE title = 'Grey van at the gate'")
check(rep == [("draft",)], f"a phone report is accepted as a draft report ({rep})")

d.tap("Suggestions")
d.until(lambda: d.has_text("Harbour Logistics"), what="the suggestion")
d.choose_select("as person", "as organisation")
d.tap("Accept")
d.until(lambda: not d.has_text("Harbour Logistics"), what="accepted suggestion")
check(c.sql("SELECT entity_type FROM entities WHERE name = 'Harbour Logistics'") == [("organization",)],
      "a suggested record is accepted, as the kind chosen")

d.tap("Possible duplicates")
d.until(lambda: d.has_text("93% similar"), what="the pair")
shot(d, "31-review-dupes")
d.tap("Merge into one")
d.until(lambda: d.has_text("Which one to keep?"), what="merge dialog")
d.tap("Merge")
d.until(lambda: not d.has_text("93% similar"), what="merged")
alive = c.sql("SELECT name FROM entities WHERE is_active AND name LIKE '%%Hale%%'")
check(alive == [("Marek Hale",)], f"the pair is merged into the record carrying more ({alive})")
m.stop()
c.stop()
finish()
