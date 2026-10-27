"""The native app's reports: list, write one (mentioning a new record with
@), read it back, export it to a USB stick, attach a file from one."""
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


c = Console("native_reports").start()
admin = c.register_admin("ana")
U = c.url
ok(admin.post(U + "/api/reports", json={"title": "Gate watch", "body_markdown": "Seen at **0200**.",
                                        "status": "confirmed", "criticality": "Immediate"}))
m = FakeMachine()
m.unlock()
m.start(console_url=c.url)
d = AppDriver(m.sock, console_url=c.url)
d.login("ana", PASSWORD)

d.tap("Reports")
d.until(lambda: d.has_text("Gate watch"), what="the report list")
shot(d, "10-reports")
d.tap("+ New report")
d.until(lambda: d.has_text("New report"), what="editor")
d.type_into("Title", "Night at the docks")
d.type("Write what was said. Type @ and a name to mention someone, somewhere or something.",
       "Met @Marek")
d.until(lambda: d.button("+ New person") is not None, what="the mention menu")
shot(d, "11-mention")
d.tap("+ New person")
d.until(lambda: d.has_text("In this report (1)"), what="the cast list")
d.type("Write what was said. Type @ and a name to mention someone, somewhere or something.", "at the gate.")
d.tap("Save")
d.until(lambda: d.has_text("Linked records"), what="saved and opened")
row = c.sql("SELECT id, body_markdown FROM reports WHERE title = 'Night at the docks'")[0]
marek = c.sql("SELECT id FROM entities WHERE name = 'Marek'")[0][0]
check(row[1] == f"Met [Marek](#/entities/{marek}) at the gate.", f"the mention is a link in the text ({row[1]!r})")
check(c.sql("SELECT count(*) FROM report_entities WHERE report_id = %s AND entity_id = %s", (row[0], marek))[0][0] == 1,
      "and the new record is linked to the report")
shot(d, "12-report")

# Export to the stick
d.tap("Export PDF")
d.until(lambda: d.button("Save to KINGSTON") is not None, what="the stick")
d.tap("Save to KINGSTON")
pdf = os.path.join(m.usb, "KINGSTON", f"report-{row[0]}.pdf")
d.until(lambda: os.path.exists(pdf) and os.path.getsize(pdf) > 1000, what="the PDF on the stick")
check(open(pdf, "rb").read(5) == b"%PDF-", "Export PDF writes the report's PDF to the stick")
d.tap("Close")

# Attach a file from the stick
open(os.path.join(m.usb, "KINGSTON", "gate-note.txt"), "w").write("Van plate GX-41.")
d.tap("+ From USB")
d.until(lambda: d.button("gate-note.txt") is not None, what="the file on the stick")
d.tap("gate-note.txt")
d.until(lambda: d.has_text("gate-note.txt") and d.button("Open") is not None, 15, "the attachment")
check(c.sql("SELECT filename FROM attachments WHERE report_id = %s", (row[0],)) == [("gate-note.txt",)],
      "a file chosen on the stick is attached to the report")
d.tap("Open")
d.until(lambda: d.has_text("Van plate GX-41."), what="the text file shown")
check(True, "and opening it shows its text")
d.tap("← Close")

# Edit it
d.tap("Edit")
d.until(lambda: d.has_text("Edit report"), what="edit")
d.type("Write what was said. Type @ and a name to mention someone, somewhere or something.", " Grey van.")
d.tap("Save")
d.until(lambda: d.has_text("Linked records"), what="saved again")
check(c.sql("SELECT body_markdown FROM reports WHERE id = %s", (row[0],))[0][0].endswith("Grey van."), "edits are saved")
m.stop()
c.stop()
finish()
