"""The native app's documents: bring one in from a USB stick, see the text
read from it, accept what it proposes, file it under a record; paste text."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import PASSWORD, ROOT, Console, check, finish, ok  # noqa: E402

sys.path.insert(0, os.path.join(ROOT, "native", "tools"))
from shoot import FakeMachine  # noqa: E402
from appdriver import AppDriver  # noqa: E402

SHOTS = os.environ.get("SHOTS")
c = Console("native_docs").start()
api = c.register_admin("ana")
target = ok(api.post(c.url + "/api/entities", json={"entity_type": "organization", "name": "Harbour Logistics"}))
m = FakeMachine()
m.unlock()
m.start(console_url=c.url)
open(os.path.join(m.usb, "KINGSTON", "manifest.txt"), "w").write("Consignment for Harbour Logistics, driver Marek Hale.")
d = AppDriver(m.sock, console_url=c.url)
d.login("ana", PASSWORD)

d.tap("Documents")
d.tap("+ From USB")
d.until(lambda: d.button("manifest.txt") is not None, what="the file on the stick")
d.tap("manifest.txt")
d.until(lambda: d.has_text("manifest.txt") and d.has_text("Waiting"), 15, "the document in the inbox")
doc = c.sql("SELECT id, report_id, entity_id FROM attachments WHERE filename = 'manifest.txt'")
check(len(doc) == 1 and doc[0][1] is None and doc[0][2] is None, "a file from the stick lands in the document inbox")
doc_id = doc[0][0]
# What the worker would do: read it and propose a record.
c.sql("UPDATE attachments SET extraction_status = 'done', extracted_text = %s WHERE id = %s",
      ("Consignment for Harbour Logistics, driver Marek Hale.", doc_id))
c.sql("INSERT INTO extraction_suggestions (attachment_id, suggestion_type, suggested_entity_type, suggested_name, confidence, status, source) "
      "VALUES (%s, 'entity', 'person', 'Marek Hale', 0.9, 'pending', 'extraction')", (doc_id,))
d.tap("← Back") if d.button("← Back") else None
d.tap("Documents")
d.until(lambda: d.has_text("1 to review"), what="the proposal count")
d.tap("manifest.txt")
d.until(lambda: d.has_text("Proposed (1 waiting)"), what="the document page")
check(any("Consignment for Harbour Logistics" in t for t in d.texts()), "the text read from it is shown")
if SHOTS:
    os.makedirs(SHOTS, exist_ok=True); d.shot(os.path.join(SHOTS, "60-document.png"))
d.tap("Accept")
d.until(lambda: d.has_text("Proposed (0 waiting)"), what="accepted")
check(c.sql("SELECT entity_type FROM entities WHERE name = 'Marek Hale'") == [("person",)], "accepting a proposal makes the record")
d.tap("File under…")
d.type("Search records", "Harbour")
d.until(lambda: d.button("Harbour Logistics") is not None, what="the record")
d.tap("Harbour Logistics")
d.tap("File it")
d.until(lambda: d.has_text("Relationships") and d.has_text("manifest.txt"), what="the record page")
check(c.sql("SELECT entity_id FROM attachments WHERE id = %s", (doc_id,))[0][0] == target["id"],
      "filing it under a record moves it into that record's files")

d.tap("Documents")
d.tap("Paste text")
d.set_field("Title", "Phone note")
box = d._under_label("Text")
for ch in d._descendants(box):
    if ch.metaObject().indexOfProperty("cursorPosition") >= 0:
        ch.setProperty("text", "Gate code changed to 4471.")
d.tap("Add")
d.until(lambda: d.has_text("Phone note"), what="the pasted document")
check(c.sql("SELECT is_pasted FROM attachments WHERE title = 'Phone note'") == [(True,)], "pasted text becomes a document")
m.stop()
c.stop()
finish()
