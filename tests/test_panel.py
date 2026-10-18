"""The field server's touch panel: every screen renders, and taps, keys,
rotation and touch calibration do what they should. (Set SHOTS_DIR to keep
the screenshots.)"""
import importlib.util, os, queue, sys, tempfile, time
os.environ["SDL_VIDEODRIVER"] = "dummy"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location(
    "panel", os.path.join(ROOT, "deploy/pi/stage-humint/03-overlay/files/opt/humint/bin/humint-panel.py"))
P = importlib.util.module_from_spec(spec); spec.loader.exec_module(P)
import pygame
pygame.display.init(); pygame.font.init()
# The Pi's fonts live in /opt and /usr/share; point at the console's own.
P.FONT_CANDIDATES["sans"].insert(0, os.path.join(ROOT, "frontend/vendor/fonts/inter-latin-wght-normal.woff2"))
P.FONT_CANDIDATES["mono"].insert(0, os.path.join(ROOT, "frontend/vendor/fonts/ibm-plex-mono-latin-500-normal.woff2"))
OUT = os.environ.get("SHOTS_DIR") or tempfile.mkdtemp()
W, H = 800, 480

BASE = {"env": {}, "store_exists": True, "firstboot_done": True, "unlocked": True, "tries_left": 5,
        "message": {}, "ip": "10.42.0.1", "host": "humint", "name": "Field Kit Alpha", "tls": True,
        "url": "https://10.42.0.1", "local_url": "https://humint.local", "trust_url": "http://10.42.0.1/trust",
        "net_mode": "hotspot", "ssid": "humint-field", "psk": "correct horse battery", "hidden": False,
        "clients": 4, "services": [("Database", "active"), ("Console", "active"), ("Worker", "active"), ("HTTPS", "active")],
        "battery": {"present": True, "percent": 72.4, "charging": False, "on_battery": True, "ac_present": False, "minutes_left": 236, "voltage": 7.7, "current_ma": -980},
        "disk": (11.4, 16.0), "temp": 51.2, "uptime": "3h 07m",
        "fingerprint": "74:DF:2B:BA:18:01:CC:9A:3E:55:10:7B:C2:04:A1:9F:6D:22:E8:4C:3B:90:17:AA:5E:61:F0:2D:88:C4:19:B7", "fingerprint_sha1": "87:81:DF:EC:12:49:C8:6D:24:86:FB:9F:55:67:64:62:62:F3:80:92"}

class FakeStatus:
    def __init__(s, **kw): s.d = dict(BASE, **kw)
    def get(s): return dict(s.d)
    def refresh(s): pass

def mk(**kw):
    ui = P.Panel((W, H), FakeStatus(**kw), queue.Queue(), P.Calibration(W, H), None)
    return ui

def shot(ui, name):
    surf = pygame.Surface((W, H)); ui.draw(surf)
    pygame.image.save(surf, os.path.join(OUT, f"{name}.png")); return ui

fails = 0
def check(c, label):
    global fails
    print(("PASS " if c else "FAIL ") + label); fails += 0 if c else 1

shot(mk(), "home")
shot(mk(battery={"present": True, "percent": 9, "charging": False, "on_battery": True, "ac_present": False}), "home-lowbatt")
shot(mk(battery={}), "home-nobattery")
shot(mk(battery={"present": True, "percent": 64, "charging": True, "ac_present": True, "on_battery": False, "board": "Geekworm X1203"}), "home-charging")
shot(mk(battery={"present": True, "percent": 100, "charging": False, "ac_present": True, "on_battery": False}), "home-pluggedfull")
shot(mk(battery={"present": False, "mains": True}), "home-mains")
ui = mk(battery={"present": False, "mains": True}, unlocked=False); shot(ui, "pin-mains")
ui = mk(); ui.screen = "join"; shot(ui, "join-hidden")
ui.show_wifi_secret = True; shot(ui, "join")
ui = mk(); ui.screen = "trust"; shot(ui, "trust")
ui = mk(); ui.screen = "menu"; shot(ui, "menu")
ui = mk(unlocked=False, tries_left=4); ui.pin = "1234"; shot(ui, "pin")
ui = mk(unlocked=False, tries_left=2); ui.pin_mode = "text"; ui.pin = "abc"; ui.pin_note = "Wrong PIN — 2 tries left"; shot(ui, "pin-text")
shot(mk(unlocked=False, tries_left=0), "lockout")
shot(mk(unlocked=False, store_exists=False, firstboot_done=False,
        message={"lines": ["Set unlock PIN", "type on keyboard"], "time": time.time()}), "firstboot")
ui = mk(); ui.ask("Lock the case file?", "The console stops and the PIN is needed to open it again.", lambda: None); shot(ui, "confirm")
ui = mk(); ui.start_calibration(); shot(ui, "calibrate")

# --- driving it ------------------------------------------------------------
def tap_label(ui, label):
    surf = pygame.Surface((W, H)); ui.draw(surf)
    for b in ui.buttons:
        if b.label == label and b.enabled:
            ui.handle(("tap", b.rect.centerx, b.rect.centery, (0, 0))); return True
    return False

ui = mk(unlocked=False)
submitted = []
ui.submit_pin = lambda: submitted.append(ui.pin)
for k in "2468":
    tap_label(ui, k)
check(ui.pin == "2468", "keypad taps type the PIN")
tap_label(ui, "BACK"); check(ui.pin == "246", "backspace")
tap_label(ui, "OK"); check(submitted == ["246"], "OK submits")
ui.pin = ""; surf = pygame.Surface((W, H)); ui.draw(surf)
check(not [b for b in ui.buttons if b.label == "OK"][0].enabled, "OK disabled with nothing typed")
ui.handle(("key", "char", "x")); ui.handle(("key", "char", "Y")); ui.handle(("key", "back", None))
check(ui.pin == "x", "physical keyboard types into the PIN")
tap_label(ui, "ABC"); check(ui.pin_mode == "text", "ABC opens the full keyboard")
tap_label(ui, "SHIFT"); tap_label(ui, "Q"); tap_label(ui, "q")
check(ui.pin == "xQq", f"shift applies to one letter ({ui.pin})")
tap_label(ui, "space"); check(ui.pin.endswith(" "), "space")

ui = mk()
for tab in ("Join", "Trust", "Menu", "Home"):
    tap_label(ui, tab)
    check(ui.current(ui.status.get()) == tab.lower(), f"nav to {tab}")
ui.screen = "menu"; tap_label(ui, "Lock case file")
check(ui.confirm and ui.confirm[0].startswith("Lock"), "Lock asks first")
ran = []
ui.ctl = lambda label, *a, **k: ran.append(a)
tap_label(ui, "Yes"); check(ran == [("lock",)], "confirm runs humint-ctl lock")
ui.handle(("key", "right", None)); check(ui.current(ui.status.get()) == "home", "arrow keys move between tabs (menu wraps to home)")

# rotation: a tap on the physical top-left lands on the drawn bottom-right
ui = mk(); ui.rotate = 180
surf = pygame.Surface((W, H)); ui.draw(surf)
home_btn = [b for b in ui.buttons if b.label == "Menu"][0]
ui.handle(("tap", W - 1 - home_btn.rect.centerx, H - 1 - home_btn.rect.centery, (0, 0)))
check(ui.screen == "menu", "180° mounting maps taps correctly")

# calibration: an XPT2046 with X inverted and axes swapped, raw 200..3900
def raw_for(sx, sy):
    return (200 + (1 - sy / H) * 3700, 200 + (sx / W) * 3700)
pts = [(96, 58), (704, 58), (704, 422), (96, 422)]
m = P.Calibration.solve([raw_for(*p) for p in pts], pts)
c = P.Calibration(W, H); c.m = m
x, y = c.map(*raw_for(400, 240)); check(abs(x - 400) < 1 and abs(y - 240) < 1, f"calibration un-swaps and un-inverts ({x:.1f},{y:.1f})")
ui = mk(); ui.cal.save = lambda mm: setattr(ui.cal, "m", mm); ui.start_calibration()
for p in ui.cal_points:
    ui.handle(("tap", 0, 0, raw_for(*p)))
check(ui.screen == "menu" and ui.cal.m is not None, "4-tap calibration wizard completes")
x, y = ui.cal.map(*raw_for(123, 321)); check(abs(x - 123) < 1 and abs(y - 321) < 1, "wizard result maps correctly")

check(P.wifi_qr_payload("My;Net", 'p"w', True) == 'WIFI:T:WPA;S:My\\;Net;P:p\\"w;H:true;;', "Wi-Fi QR escaping")
check(P.keychar("KEY_A", True) == "A" and P.keychar("KEY_1", True) == "!" and P.keychar("KEY_KP7", False) == "7", "keymap")

ui = mk(); ui.last_input = 0; ui.asleep = True; ui.handle(("tap", 10, 10, (0, 0)))
check(not ui.asleep and ui.screen == "auto", "first touch only wakes the screen")
print(f"{'OK' if not fails else 'FAILED'}: {fails} failure(s)")
sys.exit(1 if fails else 0)
