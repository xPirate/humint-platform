"""The worker recovers work a crash or power cut interrupted."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Console, check, finish, ok  # noqa: E402

c = Console("recovery").start()
admin = c.register_admin()
c.worker_env()

import recovery  # noqa: E402  (needs the database env set first)
import main as worker  # noqa: E402

upload_dir = c.env["UPLOAD_DIR"]


def add_doc(name, text="Ana Kovac met Marek Hale at the gate.", **cols):
    path = f"{name}.txt"
    with open(os.path.join(upload_dir, path), "w") as fh:
        fh.write(text)
    keys = ["filename", "storage_path", "mime_type"] + list(cols)
    vals = [path, path, "text/plain"] + list(cols.values())
    rows = c.sql(f"INSERT INTO attachments ({', '.join(keys)}) VALUES ({', '.join(['%s'] * len(vals))}) "
                 "RETURNING id", vals)
    return rows[0][0]


def doc(i):
    return c.sql("SELECT extraction_status, extraction_attempts, extraction_claimed_by, extraction_error, "
                 "extracted_text IS NOT NULL FROM attachments WHERE id = %s", (i,))[0]


# ---- recovering claims -------------------------------------------------------
c.sql("INSERT INTO worker_heartbeats (worker_id, last_seen) VALUES ('alive:1:x', now()), "
      "('dead:2:y', now() - interval '10 minutes')")
orphan = add_doc("orphan", extraction_status="processing", extraction_claimed_by="dead:2:y",
                 extraction_attempts=1)
legacy = add_doc("legacy", extraction_status="processing")           # pre-v1.13 claim, no holder
live = add_doc("live", extraction_status="processing", extraction_claimed_by="alive:1:x",
               extraction_attempts=1)
cursed = add_doc("cursed", extraction_status="processing", extraction_claimed_by="dead:2:y",
                 extraction_attempts=3)

ent = ok(admin.post(c.url + "/api/entities", json={"entity_type": "location", "name": "Depot",
                                                    "details": {"address": "1 Dock Road"}}))
c.sql("UPDATE location_details SET geocode_status = 'processing', geocode_claimed_by = 'dead:2:y' "
      "WHERE entity_id = %s", (ent["id"],))
src = c.sql("INSERT INTO map_sources (name, url_template) VALUES ('t', 'https://t/{z}/{x}/{y}.png') "
            "RETURNING id")[0][0]
pack = c.sql("INSERT INTO map_packs (source_id, name, min_lat, min_lon, max_lat, max_lon, min_zoom, max_zoom, "
             "status, claimed_by) VALUES (%s, 'p', 0, 0, 1, 1, 1, 2, 'downloading', 'dead:2:y') RETURNING id",
             (src,))[0][0]

recovery.start_heartbeat()
counts = recovery.recover_orphans()
check(doc(orphan)[0] == "pending" and doc(orphan)[2] is None,
      "a document held by a worker that stopped beating goes back in the queue")
check(doc(legacy)[0] == "pending", "a claim from before this version (no holder recorded) is recovered too")
check(doc(live)[0] == "processing", "a document a live worker is still reading is left alone")
st, attempts, _, err, _ = doc(cursed)
check(st == "failed" and "3 times" in (err or "") and "Read again" in err,
      f"the third interruption marks it failed, saying why ({err!r})")
check(c.sql("SELECT geocode_status FROM location_details WHERE entity_id = %s", (ent["id"],))[0][0] == "pending",
      "an interrupted address lookup is retried")
check(c.sql("SELECT status FROM map_packs WHERE id = %s", (pack,))[0][0] == "pending",
      "an interrupted map pack is queued to resume")
check(counts == {"documents_requeued": 2, "documents_failed": 1, "geocodes": 1, "map_packs": 1},
      f"recovery reports what it did {counts}")
check(recovery.recover_orphans() == {"documents_requeued": 0, "documents_failed": 0, "geocodes": 0,
                                     "map_packs": 0}, "running it again changes nothing")

# ---- a document is only done once its proposals are stored -------------------
c.sql("UPDATE attachments SET extraction_status = 'skipped' WHERE id <> %s", (orphan,))


class Boom(Exception):
    pass


class FakeOllama:
    enabled = True

    def __init__(self, fail):
        self.fail = fail

    def extract_entities(self, text):
        if self.fail:
            raise Boom("power cut during the model call")
        return {"entities": [{"entity_type": "person", "name": "Ana Kovac", "details": {}, "confidence": 0.9}],
                "relationships": []}


worker.ollama = FakeOllama(fail=True)
try:
    worker.process_one_attachment()
except Boom:
    pass
st, attempts, holder, _, has_text = doc(orphan)
check(st == "processing" and has_text and holder == recovery.WORKER_ID,
      "a crash during the model step leaves the document claimed, not 'done' with nothing proposed")
check(attempts == 2, "each start is counted")

# The worker that crashed is gone; a new one starts.
c.sql("DELETE FROM worker_heartbeats WHERE worker_id = %s", (recovery.WORKER_ID,))
recovery.WORKER_ID = "restarted:3:z"
worker.WORKER_ID = recovery.WORKER_ID
recovery.beat()
recovery.recover_orphans()
check(doc(orphan)[0] == "pending", "after the restart the interrupted document is back in the queue")
worker.ollama = FakeOllama(fail=False)
check(worker.process_one_attachment() is True, "the worker picks it up again")
st, attempts, holder, _, _ = doc(orphan)
n = c.sql("SELECT count(*) FROM extraction_suggestions WHERE attachment_id = %s", (orphan,))[0][0]
check(st == "done" and holder is None, "it finishes, and the claim is released")
check(n == 1, f"its proposals are stored exactly once ({n})")

# ---- a person retrying starts the count again --------------------------------
ok(admin.post(c.url + f"/api/documents/{cursed}/re-extract"))
check(doc(cursed)[:3] == ("pending", 0, None), "Read again resets the interruption count")

# ---- the heartbeat table is not part of the case file ------------------------
import io, json, zipfile  # noqa: E402,E401
b = admin.get(c.url + "/api/admin/backup")
ok(b)
manifest = json.loads(zipfile.ZipFile(io.BytesIO(b.content)).read("manifest.json"))
check("worker_heartbeats" not in manifest["row_counts"] and "attachments" in manifest["row_counts"],
      "worker heartbeats are left out of backups")

finish()
