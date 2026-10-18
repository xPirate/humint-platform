"""A protected source is known by its code name; its identity only to its handlers.
And a read-only account reads, but changes nothing."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Console, check, finish, ok  # noqa: E402

c = Console("sources").start()
U = c.url
admin = c.register_admin()
ana = c.add_user(admin, "ana")
ben = c.add_user(admin, "ben")
vic = c.add_user(admin, "vic", role="viewer")
ids = {name: c.sql("SELECT id FROM users WHERE username = %s", (name,))[0][0] for name in ("admin", "ana", "ben")}

TRUE = "Marta Novakova"
src = ok(ana.post(U + "/api/entities", json={"entity_type": "source", "name": TRUE,
                                             "description": "Clerk at the port authority; meets on Thursdays."}))
sid = src["id"]
att = ok(ana.post(U + "/api/attachments", data={"entity_id": sid},
                  files={"file": ("id-card.png", b"\x89PNG\r\n\x1a\nfake", "image/png")}))
person = ok(ana.post(U + "/api/entities", json={"entity_type": "person", "name": "Dock foreman"}))
ok(ana.post(U + "/api/relationships", json={"from_entity_id": sid, "to_entity_id": person["id"],
                                            "relationship_type": "associate_of"}))
ok(ana.post(U + "/api/reports", json={"title": "Thursday meet", "body_markdown": f"{TRUE} reported a new shift.",
                                      "entity_ids": [sid]}))

# ---- protecting it ------------------------------------------------------------
check(ana.post(U + f"/api/sources/{sid}/protect", json={"code_name": TRUE}).status_code == 400,
      "the code name cannot be the true name")
r = ok(ana.post(U + f"/api/sources/{sid}/protect", json={"code_name": "KESTREL"}))
check(r["relationships"] == 1 and r["reports_naming_source"] == 1,
      "protecting says what still points at the person: a link, and a report that names them")
rec = ok(ben.get(U + f"/api/entities/{sid}"))
check(rec["name"] == "KESTREL" and not rec.get("description"), "the record now carries only the code name")
check(rec["attachments"] == [], "another analyst does not see the files attached to it")
check(ben.get(U + f"/api/attachments/{att['id']}/file").status_code == 404 and
      ben.get(U + f"/api/attachments/{att['id']}").status_code == 404, "and cannot fetch one by its number")
check(TRUE not in json.dumps(ok(ben.get(U + "/api/entities", params={"q": "Marta"}))),
      "searching for the true name finds nothing")
check(TRUE not in json.dumps(ok(ben.get(U + "/api/entities/graph"))), "the network shows the code name")
check(ben.get(U + f"/api/sources/{sid}/identity").status_code == 403, "another analyst cannot read who it is")
p = ok(ben.get(U + f"/api/sources/{sid}/protection"))
check(p["protected"] and [h["username"] for h in p["handlers"]] == ["ana"] and not p["you_are_handler"],
      "but can see that it is protected, and who to ask")

ident = ok(ana.get(U + f"/api/sources/{sid}/identity"))
check(ident["true_name"] == TRUE and "port authority" in ident["notes"],
      "its handler reads the true name and the moved description")
check(len(ok(ana.get(U + f"/api/entities/{sid}"))["attachments"]) == 1, "and still sees its files")
views = c.sql("SELECT object_label FROM audit_log WHERE action = 'source.identity_viewed'")
check(views == [("KESTREL",)], "every reading of the identity is audited — under the code name")
leaked = c.sql("SELECT count(*) FROM audit_log WHERE action LIKE 'source.%%' AND object_label ILIKE %s",
               (f"%{TRUE.split()[0]}%",))[0][0]
check(leaked == 0, "the audit trail of the protection never spells the true name")

# ---- handlers ---------------------------------------------------------------------
check(admin.get(U + f"/api/sources/{sid}/identity").status_code == 403, "an admin is not a handler by default")
check(ben.put(U + f"/api/sources/{sid}/handlers", json={"user_ids": [ids["ben"]]}).status_code == 403,
      "a non-handler cannot make themselves one")
ok(admin.put(U + f"/api/sources/{sid}/handlers", json={"user_ids": [ids["ana"], ids["admin"]]}))
check(ok(admin.get(U + f"/api/sources/{sid}/identity"))["true_name"] == TRUE,
      "an admin can add themselves as a handler, and then read it")
check(c.sql("SELECT count(*) FROM audit_log WHERE action = 'source.handlers'")[0][0] == 1, "which is audited")
ok(ana.put(U + f"/api/sources/{sid}/identity", json={"true_name": TRUE, "notes": "Moved to nights."}))
check(ok(ana.get(U + f"/api/sources/{sid}/identity"))["notes"] == "Moved to nights.", "handlers keep it current")

# ---- unprotecting -------------------------------------------------------------------
check(ben.post(U + f"/api/sources/{sid}/unprotect").status_code in (400, 403), "only a handler can lift it")
ok(ana.post(U + f"/api/sources/{sid}/unprotect"))
rec = ok(ben.get(U + f"/api/entities/{sid}"))
check(rec["name"] == TRUE and "Moved to nights." in (rec.get("description") or "") and len(rec["attachments"]) == 1,
      "lifting it puts the name, the notes and the files back on the record")

# ---- read-only accounts --------------------------------------------------------------
check(ok(vic.get(U + "/api/entities"))["items"] is not None, "a viewer can read the case file")
r = vic.post(U + "/api/entities", json={"entity_type": "person", "name": "Should not exist"})
check(r.status_code == 403 and "read-only" in r.json()["detail"], "but cannot create anything")
check(vic.patch(U + f"/api/entities/{sid}", json={"description": "x"}).status_code == 403, "or edit")
check(vic.post(U + f"/api/sources/{sid}/protect", json={"code_name": "WREN"}).status_code == 403, "or protect a source")
check(vic.post(U + "/api/assistant/messages", json={"message": "hi"}).status_code == 403,
      "or use the assistant, which can propose changes")
check(vic.patch(U + "/api/me/preferences", json={"preferences": {"x": 1}}).status_code == 200,
      "their own preferences are theirs to change")
check(vic.post(U + "/api/auth/logout").status_code == 200, "and they can sign out")
check(c.sql("SELECT count(*) FROM entities WHERE name = 'Should not exist'")[0][0] == 0, "nothing was written")
ok(admin.patch(U + f"/api/users/{c.sql('SELECT id FROM users WHERE username=%s', ('ben',))[0][0]}",
               json={"role": "viewer"}))
check(ben.post(U + "/api/entities", json={"entity_type": "person", "name": "Nope"}).status_code == 403,
      "making someone a viewer takes effect on their very next request")
finish()
