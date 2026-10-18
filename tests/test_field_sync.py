"""Field sync end to end: seed a field console from HQ, work in the field,
bring it home, review it, promote the report, and sync only what changed."""
import io
import json
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import PASSWORD, Console, check, finish, ok  # noqa: E402
import requests  # noqa: E402

hq_c = Console("hq").start()
field_c = Console("field", env={"INSTANCE_NAME": "Field Kit Alpha"}).start()
HQ, FIELD = hq_c.url, field_c.url


def session(url, register=False):
    s = requests.Session()
    if register:
        ok(s.post(url + "/api/auth/register", json={"username": "admin", "password": PASSWORD,
                                                    "display_name": "Admin"}))
    else:
        ok(s.post(url + "/api/auth/login", json={"username": "admin", "password": PASSWORD}))
    return s


hq = session(HQ, register=True)

# --- HQ has a case -----------------------------------------------------------
ana = ok(hq.post(HQ + "/api/entities", json={"entity_type": "person", "name": "Ana Kovac",
         "description": "Dock supervisor.", "details": {"occupation": "Supervisor"}}))
kes = ok(hq.post(HQ + "/api/entities", json={"entity_type": "organization", "name": "Kestrel Logistics"}))
ok(hq.post(HQ + "/api/reports", json={"title": "Baseline", "body_markdown": "Before deployment.",
          "entity_ids": [ana["id"]]}))

# --- seed the field console from HQ's backup ------------------------------
backup = hq.get(HQ + "/api/admin/backup"); assert backup.ok
field = session(FIELD, register=True)
r = field.post(FIELD + "/api/admin/restore", files={"file": ("b.zip", backup.content, "application/zip")}, data={"confirm": "REPLACE ALL DATA"})
check(r.ok, f"field seeded from HQ backup ({r.status_code})")
field = session(FIELD)                      # restore logs everyone out
st_field = ok(field.get(FIELD + "/api/field-sync/status"))
st_hq = ok(hq.get(HQ + "/api/field-sync/status"))
check(st_field["instance_uuid"] != st_hq["instance_uuid"], "field keeps its own identity after restore")
check(st_field["seeded_at"] is not None, "field knows when it was seeded")
check(sum(st_field["pending_export"].values()) == 0, f"nothing to export right after seeding {st_field['pending_export']}")

# --- work in the field ----------------------------------------------------
ok(field.patch(FIELD + f"/api/entities/{ana['id']}",
               json={"description": "Dock supervisor; moved to night shift.",
                     "details": {"occupation": "Night supervisor"}}))
marek = ok(field.post(FIELD + "/api/entities", json={"entity_type": "person", "name": "Marek Hale",
           "description": "Seen at the gate twice."}))
dupe = ok(field.post(FIELD + "/api/entities", json={"entity_type": "organization",
          "name": "Kestrel Logistics Ltd"}))     # HQ has "Kestrel Logistics"
ok(field.post(FIELD + "/api/relationships", json={"from_entity_id": marek["id"],
   "to_entity_id": kes["id"], "relationship_type": "employed_by", "confidence": "2"}))
ok(field.post(FIELD + "/api/relationships", json={"from_entity_id": marek["id"],
   "to_entity_id": ana["id"], "relationship_type": "associate_of"}))
rep = ok(field.post(FIELD + "/api/reports", json={"title": "Gate observation", "criticality": "Priority",
         "credibility_rating": "2", "body_markdown": "Hale met Kovac at 0200.",
         "entity_ids": [marek["id"], ana["id"]]}))
ok(field.post(FIELD + "/api/attachments", data={"report_id": rep["id"]},
              files={"file": ("gate.txt", b"photo stand-in", "text/plain")}))

st = ok(field.get(FIELD + "/api/field-sync/status"))
print("  field pending:", st["pending_export"])
pkg = field.post(FIELD + "/api/field-sync/export", json={})
check(pkg.ok and pkg.headers["content-type"] == "application/zip", "field exports a package")
z = zipfile.ZipFile(io.BytesIO(pkg.content))
man = json.loads(z.read("manifest.json")); data = json.loads(z.read("data.json"))
print("  package counts:", man["counts"], "files:", [n for n in z.namelist() if n.startswith("files/")])
check(man["counts"]["entities"] == 3, "package carries the 3 touched records (1 edit, 2 new)")
check(man["counts"]["reports"] == 1, "package carries the new report only (not the seeded one)")

# A package cannot be imported where it was made.
r = field.post(FIELD + "/api/field-sync/import", files={"file": ("p.zip", pkg.content, "application/zip")})
check(r.status_code == 400, "importing on the origin console is refused")

# --- HQ imports ------------------------------------------------------------
res = ok(hq.post(HQ + "/api/field-sync/import", files={"file": ("p.zip", pkg.content, "application/zip")}))
print("  import:", res["counts"])
r = hq.post(HQ + "/api/field-sync/import", files={"file": ("p.zip", pkg.content, "application/zip")})
check(r.status_code == 409, "the same package twice is refused")

q = ok(hq.get(HQ + "/api/extraction-suggestions?source=field&limit=50"))["items"]
by = lambda pred: [s for s in q if pred(s)]
edits = by(lambda s: (s["evidence"] or {}).get("kind") == "field_edit")
news = by(lambda s: (s["evidence"] or {}).get("kind") == "field_new")
links = by(lambda s: s["suggestion_type"] == "relationship")
check(len(edits) == 1 and len(news) == 2 and len(links) == 2,
      f"queue: 1 change, 2 new, 2 links (got {len(edits)}, {len(news)}, {len(links)})")
changed = {c["field"] for c in edits[0]["evidence"]["changes"]}
check(changed == {"description", "details.occupation"}, f"change lists exactly what moved: {changed}")
kes_new = [s for s in news if s["suggested_name"] == "Kestrel Logistics Ltd"][0]
pm = kes_new["evidence"]["possible_matches"]
check(any(m["id"] == kes["id"] for m in pm), "near-duplicate is offered HQ's Kestrel Logistics")
emp = [s for s in links if s["suggested_relationship_type"] == "employed_by"][0]
check(emp["suggested_to_entity_id"] == kes["id"] and emp["suggested_from_entity_id"] is None,
      "link to a known record is half-resolved until its other end is accepted")

# nothing has touched the case file yet
a_now = ok(hq.get(HQ + f"/api/entities/{ana['id']}"))
check(a_now["description"] == "Dock supervisor.", "HQ record untouched before review")

# accept Marek as new -> the two links resolve their 'from' end
marek_s = [s for s in news if s["suggested_name"] == "Marek Hale"][0]
acc = ok(hq.post(HQ + f"/api/extraction-suggestions/{marek_s['id']}/accept", json={}))
marek_hq = acc["resolved_entity_id"]
check(acc.get("created") is True and marek_hq != marek["id"], "Marek accepted as a new HQ record")
q2 = ok(hq.get(HQ + "/api/extraction-suggestions?source=field&suggestion_type=relationship"))["items"]
check(all(s["suggested_from_entity_id"] == marek_hq for s in q2), "both links now know Marek")

# the near-duplicate: say it is the Kestrel HQ already has
acc = ok(hq.post(HQ + f"/api/extraction-suggestions/{kes_new['id']}/accept",
                 json={"use_existing_entity_id": kes["id"]}))
check(acc["resolved_entity_id"] == kes["id"] and acc["created"] is False, "duplicate folded into HQ's record")

# apply only the occupation change
acc = ok(hq.post(HQ + f"/api/extraction-suggestions/{edits[0]['id']}/accept",
                 json={"apply": ["details.occupation"]}))
a_now = ok(hq.get(HQ + f"/api/entities/{ana['id']}"))
check(a_now["details"]["occupation"] == "Night supervisor" and a_now["description"] == "Dock supervisor.",
      "only the chosen change was applied")

for s in q2:
    acc = ok(hq.post(HQ + f"/api/extraction-suggestions/{s['id']}/accept", json={}))
rels = ok(hq.get(HQ + f"/api/entities/{marek_hq}"))
types = sorted(r.get("relationship_type") for r in rels.get("relationships", []))
print("  Marek's links at HQ:", types)
emp_rel = [r for r in rels.get("relationships", []) if r.get("relationship_type") == "employed_by"]
check(len(types) == 2, "both relationships created at HQ")
check(emp_rel and str(emp_rel[0].get("confidence")) == "2", "field grading carried (confidence 2)")

# the report is in the field inbox; promote it
subs = ok(hq.get(HQ + "/api/field/submissions?status=new"))
items = subs["items"] if isinstance(subs, dict) else subs
mine = [s for s in items if s.get("title") == "Gate observation"]
check(len(mine) == 1, "field report waiting in the HQ field inbox")
prom = ok(hq.post(HQ + f"/api/field/submissions/{mine[0]['id']}/accept", json={}))
rid = prom.get("report_id") or prom.get("id")
rpt = ok(hq.get(HQ + f"/api/reports/{rid}"))
linked = sorted(e["id"] for e in rpt.get("entities", []))
check(linked == sorted([marek_hq, ana["id"]]), f"promoted report re-linked to Marek (HQ id) and Ana: {linked}")
check(len(rpt.get("attachments", [])) == 1, "its attachment came with it")
check("Field Kit Alpha" in rpt["body_markdown"], "report says where it was written")

# --- second round: only what changed since --------------------------------
st = ok(field.get(FIELD + "/api/field-sync/status"))
check(sum(st["pending_export"].values()) == 0, f"after export, nothing pending: {st['pending_export']}")
ok(field.patch(FIELD + f"/api/entities/{marek['id']}", json={"description": "Drives a grey van."}))
pkg2 = field.post(FIELD + "/api/field-sync/export", json={}); assert pkg2.ok
res2 = ok(hq.post(HQ + "/api/field-sync/import", files={"file": ("p2.zip", pkg2.content, "application/zip")}))
print("  second import:", res2["counts"])
q3 = ok(hq.get(HQ + "/api/extraction-suggestions?source=field"))["items"]
check(len(q3) == 1 and q3[0]["evidence"]["kind"] == "field_edit"
      and q3[0]["evidence"]["entity_id"] == marek_hq,
      "a field-made record edited later comes home as a change to its HQ record")

finish()
