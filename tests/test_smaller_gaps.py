"""Edits are re-compared, model failures are shown on the document, and a CSV
uploaded twice does not double the case file."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Console, check, finish, ok  # noqa: E402

c = Console("gaps").start()
U = c.url
a = c.register_admin()

# ---- re-embedding after edits -------------------------------------------------
e = ok(a.post(U + "/api/entities", json={"entity_type": "person", "name": "Ana Kovac", "description": "Clerk."}))
c.sql("UPDATE entities SET embedding = '[1]' WHERE id = %s", (e["id"],))
ok(a.patch(U + f"/api/entities/{e['id']}", json={"details": {"occupation": "Clerk"}}))
check(c.sql("SELECT embedding FROM entities WHERE id = %s", (e["id"],))[0][0] == "[1]",
      "a change to fields correlation does not read keeps the embedding")
ok(a.patch(U + f"/api/entities/{e['id']}", json={"description": "Night-shift supervisor at the docks."}))
check(c.sql("SELECT embedding FROM entities WHERE id = %s", (e["id"],))[0][0] is None,
      "editing the description queues the record to be re-compared")
rep = ok(a.post(U + "/api/reports", json={"title": "Gate", "body_markdown": "Seen at 0200."}))
c.sql("UPDATE reports SET embedding = '[1]' WHERE id = %s", (rep["id"],))
ok(a.patch(U + f"/api/reports/{rep['id']}", json={"body_markdown": "Seen at 0200 with a grey van."}))
check(c.sql("SELECT embedding FROM reports WHERE id = %s", (rep["id"],))[0][0] is None,
      "so does editing a report's text")

# ---- a model failure is shown on the document -----------------------------------
c.worker_env()
import main as worker  # noqa: E402
import recovery  # noqa: E402
recovery.start_heartbeat()
path = "memo.txt"
open(os.path.join(c.env["UPLOAD_DIR"], path), "w").write("Ana Kovac met Marek Hale.")
doc = c.sql("INSERT INTO attachments (filename, storage_path, mime_type) VALUES (%s, %s, 'text/plain') RETURNING id",
            (path, path))[0][0]


class DownModel:
    enabled = True
    last_error = None

    def extract_entities(self, text):
        self.last_error = "the model server could not be reached"
        return None


worker.ollama = DownModel()
worker.process_one_attachment()
status, err = c.sql("SELECT extraction_status, extraction_error FROM attachments WHERE id = %s", (doc,))[0]
check(status == "done" and "could not be reached" in (err or "") and "Read again" in err,
      "a document read while the model is down says so, and what to do")
ok(a.post(U + f"/api/documents/{doc}/re-extract"))
check(c.sql("SELECT extraction_error FROM attachments WHERE id = %s", (doc,))[0][0] is None,
      "reading it again clears the message")

# ---- CSV duplicates ------------------------------------------------------------------
def upload(text, duplicates=None):
    data = {"entity_type": "person"}
    if duplicates:
        data["duplicates"] = duplicates
    return ok(a.post(U + "/api/entities/import", data=data, files={"file": ("p.csv", text.encode(), "text/csv")}))


r = upload("name,description\nMarek Hale,Driver\nJosé Álvarez,Guard\n")
check(r["created_count"] == 2, "(first upload)")
r = upload("name,description\nmarek  hale,Driver\nJose Alvarez,Guard\nNew Person,x\nNew person,dup in file\n")
check(r["created_count"] == 1 and r["skipped_count"] == 3,
      "uploading again skips names already on file — ignoring case, accents and spacing — and repeats within the file")
check(c.sql("SELECT count(*) FROM entities WHERE lower(name) LIKE 'marek%%'")[0][0] == 1, "nothing was doubled")
r = upload("name\nMarek Hale\n", duplicates="create")
check(r["created_count"] == 1 and r["possible_duplicates"] == 1 and
      r["created"][0]["possible_duplicate_of"]["name"] == "Marek Hale",
      "asked to create them anyway, it does — and flags each one")
finish()
