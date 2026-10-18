"""Phone upload codes from the field server's touch panel, end to end: the
real panel code asking a real console."""
import hashlib
import importlib.util
import json
import os
import queue
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import ROOT, Console, check, finish, ok  # noqa: E402
import requests  # noqa: E402

tmp = tempfile.mkdtemp()
token_file = os.path.join(tmp, "panel.token")
open(token_file, "w").write("s3cret-panel-token\n")
c = Console("panel_upload", env={"PANEL_TOKEN_FILE": token_file}).start()
U = c.url
admin = c.register_admin()
c.add_user(admin, "ana")
c.add_user(admin, "vic", role="viewer")
ok(admin.post(U + "/api/field/devices", json={"label": "Ana's Pixel",
                                              "user_id": c.sql("SELECT id FROM users WHERE username='ana'")[0][0]}))

# ---- the console end ------------------------------------------------------------
check(requests.get(U + "/api/panel/upload/people").status_code == 403, "without the panel's token: refused")
check(requests.get(U + "/api/panel/upload/people", headers={"X-Panel-Token": "guess"}).status_code == 403,
      "with a wrong one: refused")
check(admin.get(U + "/api/panel/upload/people").status_code == 403, "an admin's session is not the panel either")
plain = Console("panel_plain").start()
check(requests.get(plain.url + "/api/panel/upload/people", headers={"X-Panel-Token": "x"}).status_code == 404,
      "the Docker console has no panel at all")
plain.stop()

# ---- the panel end, driven like a person would ------------------------------------
os.environ["SDL_VIDEODRIVER"] = "dummy"
spec = importlib.util.spec_from_file_location(
    "panel", os.path.join(ROOT, "deploy/pi/stage-humint/03-overlay/files/opt/humint/bin/humint-panel.py"))
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)
P.PANEL_TOKEN = token_file
port = U.rsplit(":", 1)[1]
P.read_env = lambda path=None: {"TLS": "off", "API_PORT": port}
import pygame  # noqa: E402
pygame.display.init(); pygame.font.init()


class St:
    def get(self):
        return {"unlocked": True, "battery": {}, "services": [], "name": "Kit", "net_mode": "hotspot",
                "url": "https://10.42.0.1"}

    def refresh(self):
        pass


ui = P.Panel((800, 480), St(), queue.Queue(), P.Calibration(800, 480), None)
surf = pygame.Surface((800, 480))


def settle():
    for _ in range(100):
        if ui.busy is None:
            return
        time.sleep(0.05)


def tap(label):
    ui.draw(surf)
    found = [b for b in ui.buttons if b.label == label and b.enabled]
    assert found, f"no {label!r} on {ui.current(ui.status.get())}: {[b.label for b in ui.buttons]}"
    ui.handle(("tap", found[0].rect.centerx, found[0].rect.centery, (0, 0)))
    settle()


ui.screen = "menu"
tap("Phone upload")
check(ui.current(ui.status.get()) == "upload_people", "Menu → Phone upload lists who can upload")
ui.draw(surf)
names = [b.label for b in ui.buttons]
check("ana" in names and "admin" in names and "vic" not in names, "everyone who can — not read-only accounts")
tap("ana")
check(ui.current(ui.status.get()) == "upload_devices", "a person with a phone is asked which phone")
tap("Ana's Pixel")
qr = ui.upload["qr"]
check(ui.current(ui.status.get()) == "upload_qr" and qr["enrollment"]["url"] == "https://10.42.0.1",
      "it shows a code that sends the phone to the box's address")
ui.draw(surf)
pygame.image.save(surf, os.path.join(tmp, "upload-qr.png"))
token = qr["enrollment"]["token"]
stored = c.sql("SELECT token_hash FROM field_devices WHERE label = %s", ("Ana's Pixel",))[0][0]
check(stored == hashlib.sha256(token.encode()).hexdigest(), "the code is that phone's new upload token")
audit = c.sql("SELECT actor_username, actor_kind FROM audit_log WHERE action = 'field.device.reissue'")
check(audit == [("touch panel", "panel")], "and the audit log says the touch panel issued it")
tap("Done")
check(ui.upload["qr"] is None and ui.current(ui.status.get()) == "menu", "Done takes the code off the screen")

tap("Phone upload")
tap("admin")
check(ui.current(ui.status.get()) == "upload_qr" and
      c.sql("SELECT count(*) FROM field_devices WHERE label = 'admin''s phone (from the panel)'")[0][0] == 1,
      "someone with no phone gets one made, and its code straight away")
ui.upload["qr"]["shown_at"] -= P.UPLOAD_QR_SECONDS + 1
ui.draw(surf)
check(ui.upload["qr"] is None, "a code left on screen clears itself after three minutes")

ok(admin.patch(U + "/api/admin/panel-settings", json={"panel_upload_codes": False}))
ui.screen = "menu"
flashes = []
ui.flash = lambda msg, secs=3: flashes.append(msg)
tap("Phone upload")
check(ui.current(ui.status.get()) == "menu" and flashes and "switched off" in flashes[0],
      "switched off by an admin, the panel says so")
print("screenshot:", os.path.join(tmp, "upload-qr.png"))
finish()
