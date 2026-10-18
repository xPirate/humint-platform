"""The field server sets its clock from the devices that use it."""
import importlib.util
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import ROOT, Console, check, finish, ok  # noqa: E402

BIN = os.path.join(ROOT, "deploy/pi/stage-humint/03-overlay/files/opt/humint/bin")
tmp = tempfile.mkdtemp()
hint_file = os.path.join(tmp, "clock", "hint.json")
state_file = os.path.join(tmp, "clock.json")

# ---- the console: Docker (unmanaged) and appliance (managed) -----------------
plain = Console("clock_plain").start()
a = plain.register_admin()
r = a.post(plain.url + "/api/system/time-hint", json={"client_epoch_ms": int((time.time() + 86400 * 3) * 1000)})
check(ok(r)["managed"] is False and not os.path.exists(hint_file),
      "a console that keeps its own time ignores the hint")
import requests  # noqa: E402
r = requests.post(plain.url + "/api/system/time-hint", json={"client_epoch_ms": 1})
check(r.ok and r.json()["managed"] is False, "nor from the sign-in page")
plain.stop()

box = Console("clock_box", env={"CLOCK_HINT_FILE": hint_file, "CLOCK_STATE_FILE": state_file}).start()
a = box.register_admin()
r = ok(a.post(box.url + "/api/system/time-hint", json={"client_epoch_ms": int(time.time() * 1000) + 5000}))
check(r["hint"] == "not needed" and not os.path.exists(hint_file), "a clock within a minute is left alone")
ahead = time.time() + 3 * 86400
r = ok(a.post(box.url + "/api/system/time-hint", json={"client_epoch_ms": int(ahead * 1000)}))
hint = json.load(open(hint_file))
check(r["hint"] == "sent" and abs(hint["client_epoch"] - ahead) < 2 and hint["username"] == "admin",
      "a box three days behind leaves a hint naming who sent it")
audit = box.sql("SELECT action, detail FROM audit_log WHERE action = 'system.clock_hint'")
check(len(audit) == 1 and abs(audit[0][1]["offset_seconds"] - 3 * 86400) < 5, "the hint is audited, with the offset")
# From the sign-in page (nobody signed in): two-factor codes need the time
# before anyone can sign in, so it is taken — but only forward, and only while
# nothing has set the clock this boot.
os.unlink(hint_file)
anon = requests.Session()
json.dump({"source": "unset"}, open(state_file, "w"))
r = anon.post(box.url + "/api/system/time-hint", json={"client_epoch_ms": int((time.time() - 86400) * 1000)})
check(r.json()["hint"] == "not accepted" and not os.path.exists(hint_file),
      "the sign-in page cannot wind the clock back")
r = anon.post(box.url + "/api/system/time-hint", json={"client_epoch_ms": int(ahead * 1000)})
hint = json.load(open(hint_file))
check(r.json()["hint"] == "sent" and hint["anonymous"] is True and hint["username"].startswith("sign-in page"),
      "it can move an unset clock forward, marked as anonymous")
os.unlink(hint_file)
json.dump({"source": "device"}, open(state_file, "w"))
r = anon.post(box.url + "/api/system/time-hint", json={"client_epoch_ms": int(ahead * 1000)})
check(r.json()["hint"] == "not accepted", "but not once a signed-in device has set it")
json.dump({"source": "ntp"}, open(state_file, "w"))
r = ok(a.post(box.url + "/api/system/time-hint", json={"client_epoch_ms": int(ahead * 1000)}))
check(r["hint"] == "not needed" and not os.path.exists(hint_file), "once network time is in sync, devices are not asked")
box.stop()

# ---- humint-clock: when it will and will not move the clock -------------------
spec = importlib.util.spec_from_file_location("hclock", os.path.join(BIN, "humint-clock.py"))
H = importlib.util.module_from_spec(spec)
spec.loader.exec_module(H)
now, mono, floor = 1_800_000_000.0, 5000.0, 1_790_000_000.0
check(H.decide({"client_epoch": now + 7200, "monotonic": mono - 10}, now, mono, floor)[0] == now + 7210,
      "the device's time is carried forward by how long ago it was sent")
check(H.decide({"client_epoch": now + 30, "monotonic": mono}, now, mono, floor)[0] is None,
      "under a minute out, the clock is not touched")
check(H.decide({"client_epoch": floor - 86400, "monotonic": mono}, now, mono, floor)[0] is None,
      "never earlier than the image was built")
check(H.decide({"client_epoch": now + 7200, "monotonic": mono - 3600}, now, mono, floor)[0] is None,
      "a stale hint (an hour old) is ignored")
check(H.decide({"oops": 1}, now, mono, floor)[0] is None, "an unreadable hint is ignored")
check(H.decide({"client_epoch": now - 7200, "monotonic": mono, "anonymous": True}, now, mono, floor)[0] is None
      and H.decide({"client_epoch": now + 7200, "monotonic": mono, "anonymous": True}, now, mono, floor)[0],
      "an anonymous hint only ever moves the clock forward (enforced again as root)")

# apply(), with the actual clock-setting stubbed out
H.STATE = state_file
H.HINT = hint_file
set_to, calls = [], []
H.time.clock_settime = lambda clk, t: set_to.append(t)
H.save_clock = lambda: calls.append("saved")
H.ntp_synced = lambda: False
H.build_epoch = lambda: 0
os.makedirs(os.path.dirname(hint_file), exist_ok=True)
os.unlink(state_file)
json.dump({"client_epoch": time.time() + 86400, "monotonic": time.monotonic(), "username": "ana"},
          open(hint_file, "w"))
H.tick({})
st = json.load(open(state_file))
check(len(set_to) == 1 and abs(set_to[0] - (time.time() + 86400)) < 5, "the clock is set to the device's time")
check(st["source"] == "device" and st["by"] == "ana" and calls == ["saved"],
      "it records who set it and saves the time for the next boot")
check(not os.path.exists(hint_file), "the hint is used once")
H.ntp_synced = lambda: True
H.tick({})
check(json.load(open(state_file))["source"] == "ntp", "network time, when it appears, takes over")

# ---- the panel shows an unconfirmed clock -----------------------------------
os.environ["SDL_VIDEODRIVER"] = "dummy"
spec = importlib.util.spec_from_file_location("panel", os.path.join(BIN, "humint-panel.py"))
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)
import pygame  # noqa: E402
import queue  # noqa: E402
pygame.display.init(); pygame.font.init()
shown = []
real_text = P.text
P.text = lambda surf, s, *a, **k: (shown.append(s), real_text(surf, s, *a, **k))[1]


class St:
    def __init__(self, src): self.src = src
    def get(self): return {"unlocked": True, "clock": {"source": self.src}, "battery": {}, "services": [],
                           "name": "x", "url": "https://10.42.0.1", "net_mode": "hotspot", "tls": True}
    def refresh(self): pass


for src in ("unset", "device"):
    shown.clear()
    P.Panel((800, 480), St(src), queue.Queue(), P.Calibration(800, 480), None).draw(pygame.Surface((800, 480)))
    unsure = any(str(t).endswith("?") and ":" in str(t) for t in shown) and \
        any("Clock not confirmed" in str(t) for t in shown)
    check(unsure == (src == "unset"), f"panel marks the time unconfirmed only when nothing has set it ({src})")
finish()
