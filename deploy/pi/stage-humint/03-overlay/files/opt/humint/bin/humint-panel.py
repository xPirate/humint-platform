#!/usr/bin/env python3
"""The touch control panel, for an HDMI/DSI screen on the field server.

What a 5" touch screen can do that a 1" OLED cannot:

  Locked     a PIN pad (digits, or a full keyboard for a passphrase), with
             the tries left; an attached keyboard works too. No keyboard is
             needed in the field once a touch screen is fitted.
  Home       the address to give the team, network and how many devices have
             joined, the console's services, battery, storage, temperature.
  Join       QR codes: one joins the field Wi-Fi, one opens the console.
  Trust      a QR code to the certificate page, and its fingerprint to check.
  Menu       lock the case file, restart the console, switch hotspot/wired,
             calibrate touch, sleep the screen, restart, shut down — the
             destructive ones behind a confirmation.

Before the PIN (first boot, starting up) it shows whatever the setup scripts
are saying — the same lines the OLED shows (/run/humint/message.json).

It draws with pygame into memory and copies each frame straight into the
Linux framebuffer (/dev/fb0) — no desktop, no X, no GPU libraries, which
Raspberry Pi OS Lite does not have (SDL's KMS/DRM mode needs EGL; it is only
a fallback here) — and reads touch and keyboards through evdev, so the same code drives a
resistive Elecrow, the official DSI display, or a USB-touch HDMI screen.
Resistive screens need calibrating; Menu → Calibrate touch (4 taps) stores it
in /var/lib/humint/touch-cal.json.

Runs as root: it opens the case store (via humint-unlock-try, which keeps one
shared count of wrong PINs with the keyboard prompt) and runs humint-ctl.
"""
import fcntl
import json
import mmap
import os
import queue
import shutil
import subprocess
import sys
import struct
import threading
import time

# Frames go to the framebuffer ourselves (FramebufferScreen), so SDL needs no
# video output of its own; "dummy" still gives pygame its event queue.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame  # noqa: E402

ENV = "/var/lib/humint/env"
DISPLAY = "/run/humint/display.json"
MESSAGE = "/run/humint/message.json"
BATTERY = "/run/humint/battery.json"
CLOCK = "/run/humint/clock.json"
# A new login password, shown until someone confirms it is written down.
LOGIN_SECRET = "/run/humint/login-password.json"
TRIES = "/run/humint/unlock-tries"
# First boot asks the panel for the PIN to set (see panel_ask_pin in
# humint-common.sh): the request names the stage, the answer goes to the FIFO.
PIN_SETUP_REQ = "/run/humint/pin-setup"
PIN_SETUP_FIFO = "/run/humint/pin-setup.fifo"
PIN_MIN_LENGTH = 4
CAL = "/var/lib/humint/touch-cal.json"
FP = "/var/lib/humint/ca.fingerprint"
STORE_IMG = "/srv/humint.img"
DATA = "/srv/humint-data"
READY = "/run/humint-data.ready"
FIRSTBOOT_DONE = "/var/lib/humint/firstboot.done"
CTL = "/opt/humint/bin/humint-ctl"
TRY = "/opt/humint/bin/humint-unlock-try"
SERVICES = (("Database", "postgresql@16-main"), ("Console", "humint-api"),
            ("Worker", "humint-worker"), ("HTTPS", "humint-http"))

# The console's own "terminal" palette, so the box and the browser look like
# one product.
BG = (11, 16, 13)
PANEL = (20, 28, 23)
PANEL_HI = (29, 40, 33)
LINE = (44, 61, 51)
TEXT = (214, 255, 226)
MUTED = (110, 150, 124)
ACCENT = (57, 255, 136)
ACCENT_DIM = (35, 160, 90)
WARN = (255, 196, 71)
DANGER = (255, 92, 92)
BLACK = (0, 0, 0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def read_env(path=ENV) -> dict:
    out = {}
    try:
        for line in open(path):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return out


def read_json(path, default=None):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def run(cmd, stdin=None, timeout=120) -> int:
    try:
        return subprocess.run(cmd, input=stdin, timeout=timeout, text=True,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
    except Exception:
        return 99


def out(cmd, timeout=5) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# What the box is doing (polled in the background)
# ---------------------------------------------------------------------------

class Status:
    def __init__(self):
        self.lock = threading.Lock()
        self.data = {}
        self.refresh()

    def refresh(self):
        env = read_env()
        d = {"env": env}
        d["store_exists"] = os.path.exists(STORE_IMG)
        d["firstboot_done"] = os.path.exists(FIRSTBOOT_DONE)
        try:
            d["pin_setup"] = open(PIN_SETUP_REQ).read().strip() or None
        except OSError:
            d["pin_setup"] = None
        d["unlocked"] = os.path.exists(READY) and os.path.ismount(DATA)
        max_tries = int(os.environ.get("HUMINT_UNLOCK_TRIES", "5"))
        try:
            used = int(open(TRIES).read().strip() or 0)
        except (OSError, ValueError):
            used = 0
        d["tries_left"] = max(0, max_tries - used)
        msg = read_json(MESSAGE, {}) or {}
        d["message"] = msg if time.time() - msg.get("time", 0) < 600 else {}
        ips = out(["hostname", "-I"]).split()
        d["ip"] = ips[0] if ips else ""
        d["host"] = env.get("HOSTNAME") or out(["hostname", "-s"]).strip() or "humint"
        d["name"] = env.get("INSTANCE_NAME") or "HUMINT field server"
        d["tls"] = env.get("TLS", "on") == "on"
        if d["tls"]:
            d["url"] = f"https://{d['ip']}" if d["ip"] else ""
        else:
            port = env.get("API_PORT", "80")
            d["url"] = (f"http://{d['ip']}" + ("" if port == "80" else f":{port}")) if d["ip"] else ""
        d["local_url"] = ("https://" if d["tls"] else "http://") + f"{d['host']}.local"
        d["trust_url"] = f"http://{d['ip'] or d['host'] + '.local'}/trust"
        d["net_mode"] = env.get("NET_MODE", "hotspot")
        d["ssid"] = env.get("AP_SSID") if d["net_mode"] == "hotspot" else env.get("CLIENT_SSID")
        d["psk"] = env.get("AP_PSK") if d["net_mode"] == "hotspot" else env.get("CLIENT_PSK")
        d["hidden"] = env.get("AP_HIDDEN", "false") == "true"
        d["clients"] = None
        if d["net_mode"] == "hotspot":
            dump = out(["iw", "dev", "wlan0", "station", "dump"])
            d["clients"] = dump.count("Station ")
        d["services"] = []
        for label, unit in SERVICES:
            if unit == "humint-http" and not d["tls"]:
                continue
            state = out(["systemctl", "is-active", unit]).strip() or "unknown"
            d["services"].append((label, state))
        d["battery"] = read_json(BATTERY, {}) or {}
        # "unset": nothing has confirmed the time this boot (no network time,
        # no device has opened the console yet) — see humint-clock.py.
        d["clock"] = read_json(CLOCK, {}) or {}
        d["login_secret"] = read_json(LOGIN_SECRET, None)
        try:
            u = shutil.disk_usage(DATA if d["unlocked"] else "/")
            d["disk"] = (u.free / 1e9, u.total / 1e9)
        except OSError:
            d["disk"] = None
        try:
            d["temp"] = int(open("/sys/class/thermal/thermal_zone0/temp").read()) / 1000
        except (OSError, ValueError):
            d["temp"] = None
        try:
            secs = float(open("/proc/uptime").read().split()[0])
            d["uptime"] = f"{int(secs // 3600)}h {int(secs % 3600 // 60):02d}m"
        except (OSError, ValueError):
            d["uptime"] = "?"
        try:
            d["fingerprint"] = open(FP).read().strip()
            d["fingerprint_sha1"] = open(FP + ".sha1").read().strip() if os.path.exists(FP + ".sha1") else ""
        except OSError:
            d["fingerprint"] = ""
        with self.lock:
            self.data = d

    def get(self) -> dict:
        with self.lock:
            return dict(self.data)

    def loop(self, stop):
        while not stop.is_set():
            try:
                self.refresh()
            except Exception as exc:          # never let a bad read kill the panel
                print(f"humint-panel: status: {exc}", file=sys.stderr)
            stop.wait(3)


# ---------------------------------------------------------------------------
# Input: touch and keyboards, through evdev
# ---------------------------------------------------------------------------

class Calibration:
    """Raw touch coordinates → screen pixels, as an affine map. Handles swapped
    and inverted axes and any rotation, which resistive screens arrive with
    in every combination."""

    def __init__(self, w, h):
        self.w, self.h = w, h
        self.m = None
        saved = read_json(CAL)
        if saved and all(k in saved for k in "abcdef"):
            self.m = [saved[k] for k in "abcdef"]

    def default_from(self, xr, yr):
        if self.m is None and xr and yr:
            (x0, x1), (y0, y1) = xr, yr
            sx = self.w / max(1, x1 - x0)
            sy = self.h / max(1, y1 - y0)
            self.m = [sx, 0, -x0 * sx, 0, sy, -y0 * sy]

    def map(self, x, y):
        if self.m is None:
            return x, y
        a, b, c, d, e, f = self.m
        return (min(self.w - 1, max(0, a * x + b * y + c)),
                min(self.h - 1, max(0, d * x + e * y + f)))

    @staticmethod
    def solve(raw, screen):
        """Least-squares affine fit from 3+ raw→screen pairs."""
        def fit(targets):
            # normal equations for [x y 1] · [p q r] = t
            s = [[0.0] * 3 for _ in range(3)]
            v = [0.0] * 3
            for (x, y), t in zip(raw, targets):
                row = (x, y, 1.0)
                for i in range(3):
                    v[i] += row[i] * t
                    for j in range(3):
                        s[i][j] += row[i] * row[j]
            # Gaussian elimination
            for i in range(3):
                piv = max(range(i, 3), key=lambda r: abs(s[r][i]))
                s[i], s[piv] = s[piv], s[i]
                v[i], v[piv] = v[piv], v[i]
                if abs(s[i][i]) < 1e-12:
                    raise ValueError("taps too close together")
                for r in range(i + 1, 3):
                    k = s[r][i] / s[i][i]
                    for c in range(i, 3):
                        s[r][c] -= k * s[i][c]
                    v[r] -= k * v[i]
            sol = [0.0] * 3
            for i in (2, 1, 0):
                sol[i] = (v[i] - sum(s[i][j] * sol[j] for j in range(i + 1, 3))) / s[i][i]
            return sol
        p = fit([sx for sx, _ in screen])
        q = fit([sy for _, sy in screen])
        return p + q

    def save(self, m):
        self.m = m
        os.makedirs(os.path.dirname(CAL), exist_ok=True)
        with open(CAL, "w") as fh:
            json.dump(dict(zip("abcdef", m)), fh)


class Input:
    """Turns evdev events into ("tap", x, y, raw) and ("key", name, char)."""

    def __init__(self, events: queue.Queue, cal: Calibration, touch_path):
        self.q, self.cal, self.touch_path = events, cal, touch_path
        self.keyboards = []
        self.grabbed = False

    def start(self, stop):
        try:
            import evdev
        except ImportError:
            print("humint-panel: python3-evdev missing; touch and keys disabled", file=sys.stderr)
            return
        self.evdev = evdev
        threading.Thread(target=self._watch_devices, args=(stop,), daemon=True).start()

    def _watch_devices(self, stop):
        """Open the touch screen and every keyboard; keep looking, because a
        keyboard plugged in at the PIN prompt has to work."""
        ev = self.evdev
        opened = set()
        while not stop.is_set():
            for path in ev.list_devices():
                if path in opened:
                    continue
                try:
                    dev = ev.InputDevice(path)
                    caps = dev.capabilities()
                except OSError:
                    continue
                keys = caps.get(ev.ecodes.EV_KEY, [])
                absol = dict(caps.get(ev.ecodes.EV_ABS, []))
                is_touch = (path == self.touch_path or
                            (ev.ecodes.ABS_X in absol or ev.ecodes.ABS_MT_POSITION_X in absol)
                            and ev.ecodes.EV_REL not in caps)
                is_kbd = ev.ecodes.KEY_A in keys and ev.ecodes.KEY_ENTER in keys
                if is_touch:
                    opened.add(path)
                    threading.Thread(target=self._read_touch, args=(dev, absol, stop), daemon=True).start()
                elif is_kbd:
                    opened.add(path)
                    self.keyboards.append(dev)
                    if self.grabbed:
                        self._grab(dev, True)
                    threading.Thread(target=self._read_kbd, args=(dev, stop), daemon=True).start()
            stop.wait(2)

    def _read_touch(self, dev, absol, stop):
        e = self.evdev.ecodes
        xi = absol.get(e.ABS_MT_POSITION_X) or absol.get(e.ABS_X)
        yi = absol.get(e.ABS_MT_POSITION_Y) or absol.get(e.ABS_Y)
        if xi and yi:
            self.cal.default_from((xi.min, xi.max), (yi.min, yi.max))
        x = y = None
        down = False
        try:
            for event in dev.read_loop():
                if stop.is_set():
                    return
                if event.type == e.EV_ABS:
                    if event.code in (e.ABS_X, e.ABS_MT_POSITION_X):
                        x = event.value
                    elif event.code in (e.ABS_Y, e.ABS_MT_POSITION_Y):
                        y = event.value
                    elif event.code == e.ABS_MT_TRACKING_ID:
                        down = event.value != -1
                        if not down and x is not None:
                            self._tap(x, y)
                elif event.type == e.EV_KEY and event.code == e.BTN_TOUCH:
                    if event.value == 1:
                        down = True
                    elif down and x is not None:
                        down = False
                        self._tap(x, y)
        except OSError:
            return                           # unplugged

    def _tap(self, x, y):
        sx, sy = self.cal.map(x, y)
        self.q.put(("tap", int(sx), int(sy), (x, y)))

    SPECIAL = {"KEY_BACKSPACE": "back", "KEY_ENTER": "enter", "KEY_KPENTER": "enter",
               "KEY_ESC": "esc", "KEY_TAB": "tab", "KEY_UP": "up", "KEY_DOWN": "down",
               "KEY_LEFT": "left", "KEY_RIGHT": "right"}

    def _read_kbd(self, dev, stop):
        e = self.evdev.ecodes
        shift = False
        try:
            for event in dev.read_loop():
                if stop.is_set():
                    return
                if event.type != e.EV_KEY:
                    continue
                name = e.KEY.get(event.code)
                if isinstance(name, list):
                    name = name[0]
                if name in ("KEY_LEFTSHIFT", "KEY_RIGHTSHIFT"):
                    shift = event.value != 0
                    continue
                if event.value != 1:          # key down only
                    continue
                if name in self.SPECIAL:
                    self.q.put(("key", self.SPECIAL[name], None))
                    continue
                ch = keychar(name, shift)
                if ch:
                    self.q.put(("key", "char", ch))
        except OSError:
            return

    def _grab(self, dev, on):
        try:
            dev.grab() if on else dev.ungrab()
        except OSError:
            pass

    def grab_keyboards(self, on: bool):
        """While the PIN pad is up, keep keystrokes away from the text console
        (where they would echo). Released otherwise, so a keyboard still
        reaches a login prompt on another console."""
        if on == self.grabbed:
            return
        self.grabbed = on
        for dev in self.keyboards:
            self._grab(dev, on)


_SHIFTED = {"1": "!", "2": "@", "3": "#", "4": "$", "5": "%", "6": "^", "7": "&", "8": "*",
            "9": "(", "0": ")", "MINUS": "_", "EQUAL": "+", "SEMICOLON": ":", "APOSTROPHE": '"',
            "COMMA": "<", "DOT": ">", "SLASH": "?", "GRAVE": "~", "LEFTBRACE": "{",
            "RIGHTBRACE": "}", "BACKSLASH": "|"}
_PLAIN = {"MINUS": "-", "EQUAL": "=", "SEMICOLON": ";", "APOSTROPHE": "'", "COMMA": ",",
          "DOT": ".", "SLASH": "/", "GRAVE": "`", "LEFTBRACE": "[", "RIGHTBRACE": "]",
          "BACKSLASH": "\\", "SPACE": " "}


def keychar(name, shift):
    """US layout, which is what the image is built with (KEYBOARD_KEYMAP)."""
    if not name or not name.startswith("KEY_"):
        return None
    k = name[4:]
    if k.startswith("KP") and k[2:].isdigit():
        return k[2:]
    if len(k) == 1 and k.isalpha():
        return k.upper() if shift else k.lower()
    if len(k) == 1 and k.isdigit():
        return _SHIFTED[k] if shift else k
    if shift and k in _SHIFTED:
        return _SHIFTED[k]
    return _PLAIN.get(k)


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------

FONT_CANDIDATES = {
    "sans": ["/opt/humint-platform/frontend/vendor/fonts/inter-latin-wght-normal.woff2",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
    "bold": ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
    "mono": ["/opt/humint-platform/frontend/vendor/fonts/ibm-plex-mono-latin-500-normal.woff2",
             "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"],
}
_fonts = {}


def font(size, kind="sans"):
    key = (size, kind)
    if key not in _fonts:
        f = None
        for path in FONT_CANDIDATES[kind]:
            if os.path.exists(path):
                try:
                    f = pygame.font.Font(path, size)
                    break
                except Exception:
                    continue
        if f is None:
            f = pygame.font.Font(None, int(size * 1.3))
        if kind == "bold" and f is not None:
            f.set_bold(not any(os.path.exists(p) for p in FONT_CANDIDATES["bold"]))
        _fonts[key] = f
    return _fonts[key]


class Button:
    def __init__(self, rect, label, action, style="normal", sub=None, enabled=True):
        self.rect = pygame.Rect(rect)
        self.label, self.action, self.style, self.sub, self.enabled = label, action, style, sub, enabled

    def draw(self, surf, s):
        fill = {"primary": ACCENT_DIM, "danger": (90, 26, 26), "ghost": PANEL,
                "key": PANEL_HI, "active": (30, 70, 46)}.get(self.style, PANEL_HI)
        edge = {"primary": ACCENT, "danger": DANGER, "active": ACCENT}.get(self.style, LINE)
        if not self.enabled:
            fill, edge = PANEL, LINE
        pygame.draw.rect(surf, fill, self.rect, border_radius=int(10 * s))
        pygame.draw.rect(surf, edge, self.rect, width=max(1, int(2 * s)), border_radius=int(10 * s))
        color = TEXT if self.enabled else MUTED
        size = int((30 if self.style == "key" else 21) * s)
        if self.style == "key" and len(self.label) > 2:
            size = int(19 * s)
        cy = self.rect.centery - (int(9 * s) if self.sub else 0)
        if self.label in ICONS:
            ICONS[self.label](surf, (self.rect.centerx, cy), s, color)
        else:
            f = font(size, "bold" if self.style in ("primary", "danger") else "sans")
            img = f.render(self.label, True, color)
            surf.blit(img, img.get_rect(center=(self.rect.centerx, cy)))
        if self.sub:
            simg = font(int(14 * s)).render(self.sub, True, MUTED)
            surf.blit(simg, simg.get_rect(center=(self.rect.centerx, self.rect.centery + int(15 * s))))


# Drawn, not typed: ⌫ ⇧ ⚡ are missing from most fonts, and a key showing a
# box is a key nobody trusts.
def _icon_back(surf, c, s, color):
    x, y = c
    w, h = int(34 * s), int(24 * s)
    pts = [(x - w // 2, y), (x - w // 2 + int(11 * s), y - h // 2), (x + w // 2, y - h // 2),
           (x + w // 2, y + h // 2), (x - w // 2 + int(11 * s), y + h // 2)]
    pygame.draw.polygon(surf, color, pts, width=max(2, int(3 * s)))
    k = int(5 * s)
    cx = x + int(5 * s)
    pygame.draw.line(surf, color, (cx - k, y - k), (cx + k, y + k), max(2, int(3 * s)))
    pygame.draw.line(surf, color, (cx - k, y + k), (cx + k, y - k), max(2, int(3 * s)))


def _icon_shift(surf, c, s, color):
    x, y = c
    k = int(13 * s)
    pts = [(x, y - k), (x + k, y), (x + k // 2, y), (x + k // 2, y + k), (x - k // 2, y + k),
           (x - k // 2, y), (x - k, y)]
    pygame.draw.polygon(surf, color, pts, width=max(2, int(3 * s)))


def bolt(surf, c, s, color):
    x, y = c
    k = int(8 * s)
    pts = [(x + k // 3, y - k), (x - k // 2, y + k // 6), (x, y + k // 6), (x - k // 3, y + k),
           (x + k // 2, y - k // 6), (x, y - k // 6)]
    pygame.draw.polygon(surf, color, pts)


def plug(surf, c, s, color, scale=1.0):
    """A mains plug, prongs up: the box is on external power."""
    x, y = c
    k = s * scale
    body = pygame.Rect(0, 0, int(16 * k), int(12 * k))
    body.center = (x, y)
    pygame.draw.rect(surf, color, body, border_radius=max(1, int(3 * k)))
    for dx in (-4, 4):                                    # prongs
        pygame.draw.rect(surf, color, (x + int(dx * k) - max(1, int(1.5 * k)), body.top - int(6 * k),
                                       max(2, int(3 * k)), int(6 * k)))
    pygame.draw.line(surf, color, (x, body.bottom), (x, body.bottom + int(6 * k)),
                     max(2, int(3 * k)))                  # the cord


ICONS = {"BACK": _icon_back, "SHIFT": _icon_shift}


def text(surf, msg, pos, size, color=TEXT, kind="sans", anchor="topleft", maxw=None):
    f = font(size, kind)
    msg = str(msg)
    if maxw:
        while msg and f.size(msg)[0] > maxw:
            msg = msg[:-2] + "…" if len(msg) > 2 else ""
    img = f.render(msg, True, color)
    r = img.get_rect(**{anchor: pos})
    surf.blit(img, r)
    return r


def qr_surface(data, size):
    try:
        import qrcode
    except ImportError:
        return None
    q = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
    q.add_data(data)
    q.make(fit=True)
    m = q.get_matrix()
    n = len(m)
    cell = max(1, size // n)
    surf = pygame.Surface((n * cell, n * cell))
    surf.fill((255, 255, 255))
    for y, row in enumerate(m):
        for x, on in enumerate(row):
            if on:
                surf.fill(BLACK, (x * cell, y * cell, cell, cell))
    return surf


def wifi_qr_payload(ssid, psk, hidden):
    def esc(v):
        return "".join("\\" + c if c in '\\;,:"' else c for c in v or "")
    return f"WIFI:T:WPA;S:{esc(ssid)};P:{esc(psk)};" + ("H:true;" if hidden else "") + ";"


# ---------------------------------------------------------------------------
# The panel
# ---------------------------------------------------------------------------

KEY_ROWS = ["1234567890", "qwertyuiop", "asdfghjkl", "zxcvbnm"]


class Panel:
    def __init__(self, surface_size, status: Status, events: queue.Queue, cal: Calibration,
                 inp: Input = None, rotate=0):
        self.W, self.H = surface_size
        self.s = min(self.W / 800, self.H / 480)
        self.status, self.q, self.cal, self.inp, self.rotate = status, events, cal, inp, rotate
        self.screen = "auto"
        self.pin = ""
        self.pin_mode = "digits"        # or "text"
        self.shift = False
        self.pin_note = ""
        self.setpin_first = None        # first entry while setting a new PIN
        self.busy = None                # text while a long action runs
        self.confirm = None             # (title, detail, action)
        self.show_wifi_secret = False
        self.cal_points, self.cal_raw = [], []
        self.toast, self.toast_until = "", 0
        self.last_input = time.time()
        self.asleep = False
        self.buttons = []

    # ---- state ------------------------------------------------------------

    def current(self, d):
        if self.screen == "calibrate":
            return "calibrate"
        if self.confirm:
            return "confirm"
        if self.busy:
            return "busy"
        if d.get("pin_setup") == "duress" and d.get("unlocked"):
            return "setpin"
        if d.get("unlocked") and d.get("login_secret"):
            return "secret"
        if not d.get("unlocked"):
            if d.get("pin_setup") in ("new", "existing"):
                return "setpin"
            if d.get("store_exists") and d.get("firstboot_done"):
                return "lockout" if d.get("tries_left", 1) <= 0 else "pin"
            return "message"
        return self.screen if self.screen in ("home", "join", "trust", "menu") else "home"

    def flash(self, msg, secs=3):
        self.toast, self.toast_until = msg, time.time() + secs

    def in_background(self, label, fn):
        self.busy = label

        def work():
            try:
                fn()
            finally:
                self.busy = None
                self.status.refresh()
        threading.Thread(target=work, daemon=True).start()

    # ---- actions ----------------------------------------------------------

    def submit(self):
        """OK / Enter on the PIN pad: unlock, or (first boot) set the PIN."""
        if self.current(self.status.get()) == "setpin":
            self.submit_setpin()
        else:
            self.submit_pin()

    def submit_setpin(self):
        stage = self.status.get().get("pin_setup")
        pin = self.pin
        if not pin:
            return
        if stage in ("new", "duress"):
            if self.setpin_first is None:
                if len(pin) < PIN_MIN_LENGTH:
                    self.pin_note = f"Use at least {PIN_MIN_LENGTH} characters"
                    return
                self.setpin_first, self.pin, self.pin_note = pin, "", ""
                return
            if pin != self.setpin_first:
                self.setpin_first, self.pin = None, ""
                self.pin_note = "They didn't match — start again"
                return
        self.pin, self.setpin_first, self.pin_note = "", None, ""

        def work():
            try:
                fd = os.open(PIN_SETUP_FIFO, os.O_WRONLY | os.O_NONBLOCK)
                try:
                    os.write(fd, (pin + "\n").encode())
                finally:
                    os.close(fd)
            except OSError as e:
                self.pin_note = f"Could not hand the PIN over ({e.strerror})"
                return
            # First boot takes it from here; wait for it to drop the request.
            for _ in range(20):
                if not os.path.exists(PIN_SETUP_REQ):
                    break
                time.sleep(0.25)
            if stage != "duress":      # humint-ctl reports how that one went
                self.flash("PIN set — setting up the case file" if stage == "new" else "Opening the case file")
        self.in_background({"new": "Saving PIN…", "duress": "Saving…"}.get(stage, "Opening…"), work)

    def cancel_setpin(self):
        """Duress PIN setup only: an empty answer tells humint-ctl to stop."""
        self.pin, self.setpin_first, self.pin_note = "", None, ""
        try:
            fd = os.open(PIN_SETUP_FIFO, os.O_WRONLY | os.O_NONBLOCK)
            os.write(fd, b"\n")
            os.close(fd)
        except OSError:
            pass

    def ctl_waiting(self, label, args, messages):
        """Run humint-ctl for something that will ask on this screen (the PIN
        pad), so without the busy overlay that would cover it."""
        def work():
            rc = run([CTL, *args], timeout=900)
            self.flash(messages.get(rc, f"{label}: failed ({rc})"))
            self.status.refresh()
        threading.Thread(target=work, daemon=True).start()

    def submit_pin(self):
        if not self.pin:
            return
        pin, self.pin = self.pin, ""

        def work():
            rc = run([TRY], stdin=pin + "\n", timeout=600)
            self.status.refresh()
            d = self.status.get()
            if rc in (0, 5):
                self.pin_note = ""
                self.screen = "home"
                self.flash("Unlocked — console starting")
            elif rc == 1:
                self.pin_note = f"Wrong PIN — {d.get('tries_left', '?')} tries left"
            elif rc == 3:
                self.pin_note = "Too many wrong PINs"
            else:
                self.pin_note = f"Could not unlock ({rc})"
        self.in_background("Unlocking…", work)

    def ctl(self, label, *args, after=None):
        def work():
            # An update can install Python packages and run migrations.
            rc = run([CTL, *args], timeout=1800 if args[:1] == ("update",) else 300)
            self.flash(f"{label}: done" if rc == 0 else f"{label}: failed ({rc})")
            if after:
                after()
        self.in_background(label + "…", work)

    def ask(self, title, detail, action, danger=True):
        self.confirm = (title, detail, action, danger)

    def start_calibration(self):
        m = 0.12
        self.cal_points = [(self.W * m, self.H * m), (self.W * (1 - m), self.H * m),
                           (self.W * (1 - m), self.H * (1 - m)), (self.W * m, self.H * (1 - m))]
        self.cal_raw = []
        self.screen = "calibrate"

    # ---- input ------------------------------------------------------------

    def handle(self, ev):
        self.last_input = time.time()
        if self.asleep:
            self.asleep = False           # the first touch only wakes it
            return
        kind = ev[0]
        state = self.current(self.status.get())
        if kind == "tap" and state == "calibrate":
            self.cal_raw.append(ev[3])
            if len(self.cal_raw) == len(self.cal_points):
                try:
                    self.cal.save(Calibration.solve(self.cal_raw, self.cal_points))
                    self.flash("Touch calibrated")
                except ValueError:
                    self.flash("Calibration failed — try again")
                self.screen = "menu"
            return
        if kind == "tap":
            x, y = ev[1], ev[2]
            if self.rotate == 180:
                x, y = self.W - 1 - x, self.H - 1 - y
            for b in reversed(self.buttons):
                if b.enabled and b.rect.collidepoint(x, y):
                    b.action()
                    return
            return
        if kind == "key" and state in ("pin", "setpin"):
            name, ch = ev[1], ev[2]
            if name == "char" and len(self.pin) < 128:
                self.pin += ch
                self.pin_note = ""
            elif name == "back":
                self.pin = self.pin[:-1]
            elif name == "enter":
                self.submit()
            elif name == "esc":
                self.pin = ""
        elif kind == "key" and state in ("home", "join", "trust", "menu"):
            order = ["home", "join", "trust", "menu"]
            if ev[1] in ("right", "tab"):
                self.screen = order[(order.index(state) + 1) % 4]
            elif ev[1] == "left":
                self.screen = order[(order.index(state) - 1) % 4]
        elif kind == "key" and state == "confirm" and ev[1] in ("esc",):
            self.confirm = None

    # ---- drawing ----------------------------------------------------------

    def draw(self, surf):
        d = self.status.get()
        s = self.s
        self.buttons = []
        if self.asleep:
            surf.fill(BLACK)
            return
        surf.fill(BG)
        state = self.current(d)
        if self.inp:
            self.inp.grab_keyboards(state in ("pin", "setpin"))
        getattr(self, "draw_" + state)(surf, d)
        if state in ("home", "join", "trust", "menu"):
            self.draw_nav(surf, state)
        if self.toast and time.time() < self.toast_until:
            f = font(int(18 * s))
            w = f.size(self.toast)[0] + int(40 * s)
            r = pygame.Rect(0, 0, w, int(44 * s))
            r.midbottom = (self.W // 2, self.H - int(84 * s))
            pygame.draw.rect(surf, PANEL_HI, r, border_radius=int(22 * s))
            pygame.draw.rect(surf, ACCENT, r, width=1, border_radius=int(22 * s))
            text(surf, self.toast, r.center, int(18 * s), anchor="center")

    def top_bar(self, surf, d, title=None):
        s = self.s
        pygame.draw.rect(surf, PANEL, (0, 0, self.W, int(52 * s)))
        pygame.draw.line(surf, LINE, (0, int(52 * s)), (self.W, int(52 * s)))
        pygame.draw.circle(surf, ACCENT if d.get("unlocked") else WARN,
                           (int(24 * s), int(26 * s)), int(6 * s))
        text(surf, title or d.get("name", ""), (int(40 * s), int(26 * s)), int(20 * s),
             anchor="midleft", kind="bold", maxw=int(self.W * 0.5))
        x = self.W - int(16 * s)
        unsure = (d.get("clock") or {}).get("source") == "unset"
        r = text(surf, time.strftime("%H:%M") + ("?" if unsure else ""), (x, int(26 * s)), int(20 * s),
                 WARN if unsure else MUTED, kind="mono", anchor="midright")
        x = r.left - int(18 * s)
        b = d.get("battery") or {}
        if b.get("present"):
            self.battery_icon(surf, b, (x, int(26 * s)))
        elif b.get("mains"):
            # No battery module: running on external power, so pulling the
            # cable turns it off. A plug says so at a glance.
            r = text(surf, "AC", (x, int(26 * s)), int(18 * s), MUTED, kind="mono", anchor="midright")
            plug(surf, (r.left - int(14 * s), int(25 * s)), s, MUTED)

    def battery_icon(self, surf, b, right_mid):
        s = self.s
        pct = b.get("percent", 0)
        color = DANGER if pct < 15 and not b.get("charging") else (WARN if pct < 35 else ACCENT)
        r = text(surf, f"{pct:.0f}%", right_mid, int(18 * s), color, kind="mono", anchor="midright")
        if b.get("ac_present"):
            # Plugged in: the plug, and the bolt too while it is charging.
            plug(surf, (r.left - int(17 * s), right_mid[1] - int(1 * s)), s, ACCENT)
            r = r.move(-int(32 * s), 0)
            if b.get("charging"):
                bolt(surf, (r.left - int(8 * s), right_mid[1]), s, ACCENT)
                r = r.move(-int(16 * s), 0)
        body = pygame.Rect(0, 0, int(34 * s), int(16 * s))
        body.midright = (r.left - int(10 * s), right_mid[1])
        pygame.draw.rect(surf, color, body, width=max(1, int(2 * s)), border_radius=int(3 * s))
        pygame.draw.rect(surf, color, (body.right, body.centery - int(4 * s), int(3 * s), int(8 * s)))
        inner = body.inflate(-int(6 * s), -int(6 * s))
        inner.width = max(0, int(inner.width * pct / 100))
        pygame.draw.rect(surf, color, inner)

    def draw_nav(self, surf, state):
        s = self.s
        h = int(68 * s)
        y = self.H - h
        pygame.draw.rect(surf, PANEL, (0, y, self.W, h))
        pygame.draw.line(surf, LINE, (0, y), (self.W, y))
        tabs = [("home", "Home"), ("join", "Join"), ("trust", "Trust"), ("menu", "Menu")]
        w = self.W // len(tabs)
        for i, (key, label) in enumerate(tabs):
            rect = (i * w + int(8 * s), y + int(8 * s), w - int(16 * s), h - int(16 * s))
            b = Button(rect, label, lambda k=key: setattr(self, "screen", k),
                       style="active" if key == state else "ghost")
            b.draw(surf, s)
            self.buttons.append(b)

    def card(self, surf, rect, title):
        s = self.s
        r = pygame.Rect(rect)
        pygame.draw.rect(surf, PANEL, r, border_radius=int(12 * s))
        pygame.draw.rect(surf, LINE, r, width=1, border_radius=int(12 * s))
        text(surf, title.upper(), (r.x + int(16 * s), r.y + int(12 * s)), int(13 * s), MUTED, kind="bold")
        return r

    # -- screens ----

    def draw_message(self, surf, d):
        s = self.s
        msg = d.get("message") or {}
        lines = msg.get("lines") or (["Starting up"] if d.get("firstboot_done") else ["Setting up"])
        self.top_bar(surf, d)
        text(surf, lines[0], (self.W // 2, int(self.H * 0.40)), int(40 * s), kind="bold", anchor="center",
             maxw=self.W - int(60 * s))
        y = int(self.H * 0.40) + int(48 * s)
        for line in lines[1:5]:
            text(surf, line, (self.W // 2, y), int(24 * s), MUTED, anchor="center", maxw=self.W - int(60 * s))
            y += int(34 * s)
        dots = "•" * (int(time.time() * 2) % 4)
        text(surf, dots, (self.W // 2, self.H - int(60 * s)), int(28 * s), ACCENT, anchor="center")
        if not d.get("firstboot_done"):
            text(surf, "First-time setup — this takes a few minutes.",
                 (self.W // 2, self.H - int(28 * s)), int(16 * s), MUTED, anchor="center")

    def draw_setpin(self, surf, d):
        if d.get("pin_setup") == "duress":
            if self.setpin_first is None:
                words = ("Set duress PIN", "if typed, erases all",
                         "Not a near-miss of the real PIN.", "Set duress passphrase")
            else:
                words = ("Confirm duress PIN", "enter the same PIN again", "Enter it again to confirm.",
                         "Confirm duress passphrase")
            self.draw_pin(surf, d, words)
            s = self.s
            b = Button((int(230 * s), self.H - int(92 * s), int(110 * s), int(60 * s)), "Cancel",
                       self.cancel_setpin)
            b.draw(surf, s); self.buttons.append(b)
            return
        if d.get("pin_setup") == "existing":
            words = ("Enter your PIN", "the one set before the restart",
                     "Setup was interrupted; the case file already exists.", "Enter your passphrase")
        elif self.setpin_first is None:
            words = ("Set unlock PIN", "you'll enter it at every start",
                     f"At least {PIN_MIN_LENGTH} digits or characters.",
                     "Set unlock passphrase")
        else:
            words = ("Confirm PIN", "enter the same PIN again", "Enter it again to confirm.",
                     "Confirm passphrase")
        self.draw_pin(surf, d, words)

    def draw_pin(self, surf, d, words=None):
        s = self.s
        title, sub, hint, text_title = words or (
            "Enter unlock PIN", "to open the case file",
            f"{d.get('tries_left', '?')} tries before it locks until restart", "Enter unlock passphrase")
        self.top_bar(surf, d, title=("Duress PIN" if d.get("pin_setup") == "duress" else "First-time setup")
                     if words else None)
        if self.pin_mode == "digits":
            left_w = int(self.W * 0.46)
            text(surf, title, (int(36 * s), int(96 * s)), int(32 * s), kind="bold")
            text(surf, sub, (int(36 * s), int(138 * s)), int(19 * s), MUTED)
            self.pin_field(surf, (int(36 * s), int(186 * s), left_w - int(56 * s), int(64 * s)))
            note = self.pin_note or hint
            text(surf, note, (int(36 * s), int(266 * s)), int(17 * s),
                 DANGER if self.pin_note else MUTED, maxw=left_w - int(40 * s))
            b = Button((int(36 * s), self.H - int(92 * s), int(180 * s), int(60 * s)),
                       "ABC", lambda: setattr(self, "pin_mode", "text"), sub="letters too")
            b.draw(surf, s); self.buttons.append(b)
            # keypad
            kx, ky = left_w + int(10 * s), int(76 * s)
            kw = (self.W - kx - int(26 * s)) // 3
            kh = (self.H - ky - int(20 * s)) // 4
            keys = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "BACK", "0", "OK"]
            for i, k in enumerate(keys):
                r = (kx + (i % 3) * kw + int(6 * s), ky + (i // 3) * kh + int(6 * s),
                     kw - int(12 * s), kh - int(12 * s))
                if k == "BACK":
                    act, style = (lambda: setattr(self, "pin", self.pin[:-1])), "key"
                elif k == "OK":
                    act, style = self.submit, "primary"
                else:
                    act, style = (lambda c=k: self.type_char(c)), "key"
                b = Button(r, k, act, style=style, enabled=(k != "OK" or bool(self.pin)))
                b.draw(surf, s); self.buttons.append(b)
        else:
            text(surf, text_title, (int(28 * s), int(70 * s)), int(24 * s), kind="bold")
            self.pin_field(surf, (int(28 * s), int(108 * s), self.W - int(56 * s), int(54 * s)))
            if self.pin_note:
                text(surf, self.pin_note, (self.W - int(28 * s), int(84 * s)), int(16 * s), DANGER,
                     anchor="midright")
            top = int(176 * s)
            rows = KEY_ROWS
            kh = int(58 * s)
            for ri, row in enumerate(rows):
                kw = (self.W - int(40 * s)) // 10
                x0 = (self.W - kw * len(row)) // 2
                for ci, ch in enumerate(row):
                    shown = ch.upper() if self.shift and ch.isalpha() else ch
                    r = (x0 + ci * kw + int(3 * s), top + ri * kh + int(3 * s), kw - int(6 * s), kh - int(6 * s))
                    b = Button(r, shown, lambda c=shown: self.type_char(c), style="key")
                    b.draw(surf, s); self.buttons.append(b)
            y = top + 4 * kh + int(4 * s)
            bh = self.H - y - int(10 * s)
            specs = [("123", 1.3, lambda: setattr(self, "pin_mode", "digits"), "normal"),
                     ("SHIFT", 1.3, lambda: setattr(self, "shift", not self.shift), "active" if self.shift else "normal"),
                     ("space", 3.4, lambda: self.type_char(" "), "key"),
                     ("BACK", 1.4, lambda: setattr(self, "pin", self.pin[:-1]), "key"),
                     ("OK", 2.0, self.submit, "primary")]
            unit = (self.W - int(40 * s)) / sum(w for _, w, _, _ in specs)
            x = int(20 * s)
            for label, w, act, style in specs:
                r = (x + int(3 * s), y, int(unit * w) - int(6 * s), bh)
                b = Button(r, label, act, style=style, enabled=(label != "OK" or bool(self.pin)))
                b.draw(surf, s); self.buttons.append(b)
                x += int(unit * w)

    def type_char(self, c):
        if len(self.pin) < 128:
            self.pin += c
            self.pin_note = ""
            if self.shift and c.isalpha():
                self.shift = False

    def pin_field(self, surf, rect):
        s = self.s
        r = pygame.Rect(rect)
        pygame.draw.rect(surf, PANEL, r, border_radius=int(10 * s))
        pygame.draw.rect(surf, ACCENT if self.pin else LINE, r, width=max(1, int(2 * s)),
                         border_radius=int(10 * s))
        n = len(self.pin)
        if n == 0:
            text(surf, "—", r.center, int(22 * s), MUTED, anchor="center")
            return
        gap = min(int(30 * s), (r.width - int(30 * s)) // max(1, n))
        x0 = r.centerx - gap * (n - 1) // 2
        for i in range(n):
            pygame.draw.circle(surf, TEXT, (x0 + i * gap, r.centery), int(7 * s))

    def draw_lockout(self, surf, d):
        s = self.s
        self.top_bar(surf, d)
        text(surf, "Locked", (self.W // 2, int(self.H * 0.38)), int(48 * s), DANGER, kind="bold", anchor="center")
        text(surf, "Too many wrong PINs.", (self.W // 2, int(self.H * 0.38) + int(56 * s)), int(22 * s),
             anchor="center")
        text(surf, "The case file stays closed until the box is restarted.",
             (self.W // 2, int(self.H * 0.38) + int(92 * s)), int(18 * s), MUTED, anchor="center")
        b = Button((self.W // 2 - int(130 * s), self.H - int(110 * s), int(260 * s), int(70 * s)),
                   "Restart", lambda: self.ask("Restart the box?", "It will ask for the PIN again.",
                                               lambda: self.ctl("Restarting", "reboot"), danger=False))
        b.draw(surf, s); self.buttons.append(b)

    def draw_busy(self, surf, d):
        s = self.s
        self.top_bar(surf, d)
        text(surf, self.busy, (self.W // 2, self.H // 2 - int(20 * s)), int(34 * s), kind="bold", anchor="center")
        phase = time.time() * 3
        for i in range(8):
            import math
            a = phase + i * math.pi / 4
            c = tuple(int(v * (0.25 + 0.75 * ((i + int(phase * 1.3)) % 8) / 7)) for v in ACCENT)
            pygame.draw.circle(surf, c, (self.W // 2 + int(math.cos(a) * 26 * s),
                                         self.H // 2 + int(50 * s) + int(math.sin(a) * 26 * s)), int(5 * s))

    def draw_confirm(self, surf, d):
        s = self.s
        title, detail, action, danger = self.confirm
        self.top_bar(surf, d)
        text(surf, title, (self.W // 2, int(self.H * 0.34)), int(34 * s), kind="bold", anchor="center")
        text(surf, detail, (self.W // 2, int(self.H * 0.34) + int(48 * s)), int(19 * s), MUTED, anchor="center",
             maxw=self.W - int(60 * s))
        bw, bh = int(250 * s), int(76 * s)
        y = self.H - int(140 * s)

        def go():
            self.confirm = None
            action()
        b1 = Button((self.W // 2 - bw - int(12 * s), y, bw, bh), "Cancel", lambda: setattr(self, "confirm", None))
        b2 = Button((self.W // 2 + int(12 * s), y, bw, bh), "Yes", go, style="danger" if danger else "primary")
        for b in (b1, b2):
            b.draw(surf, s); self.buttons.append(b)

    def draw_home(self, surf, d):
        s = self.s
        self.top_bar(surf, d)
        top, bottom = int(64 * s), self.H - int(78 * s)
        pad = int(12 * s)
        b = d.get("battery") or {}
        if b.get("present") and b.get("percent", 100) < 15 and b.get("on_battery", not b.get("charging")):
            r = pygame.Rect(0, int(53 * s), self.W, int(30 * s))
            pygame.draw.rect(surf, (90, 26, 26), r)
            text(surf, "Battery low — plug in, or the box will lock and power off",
                 r.center, int(16 * s), anchor="center")
            top = r.bottom + int(8 * s)
        cols, rows = 3, 2
        cw = (self.W - pad * (cols + 1)) // cols
        ch = (bottom - top - pad * (rows - 1)) // rows

        def cell(c, r, span=1):
            return (pad + c * (cw + pad), top + r * (ch + pad), cw * span + pad * (span - 1), ch)

        # address (two columns wide)
        r = self.card(surf, cell(0, 0, 2), "Console address")
        text(surf, d.get("url") or "no network yet", (r.x + int(16 * s), r.y + int(44 * s)), int(36 * s),
             ACCENT, kind="mono", maxw=r.width - int(32 * s))
        text(surf, d.get("local_url", ""), (r.x + int(16 * s), r.y + int(92 * s)), int(19 * s), TEXT,
             kind="mono", maxw=r.width - int(32 * s))
        if (d.get("clock") or {}).get("source") == "unset":
            text(surf, "Clock not confirmed — opening the console on any device sets it",
                 (r.x + int(16 * s), r.bottom - int(30 * s)), int(15 * s), WARN, maxw=r.width - int(32 * s))
        elif d.get("tls"):
            text(surf, "HTTPS · devices trust it once, from the Trust tab",
                 (r.x + int(16 * s), r.bottom - int(30 * s)), int(15 * s), MUTED, maxw=r.width - int(32 * s))

        # network
        r = self.card(surf, cell(2, 0), "Network")
        mode = {"hotspot": "Hotspot", "client": "Wi-Fi client", "wired": "Wired"}.get(d.get("net_mode"), "?")
        text(surf, mode, (r.x + int(16 * s), r.y + int(40 * s)), int(24 * s), kind="bold")
        if d.get("ssid"):
            text(surf, d["ssid"], (r.x + int(16 * s), r.y + int(74 * s)), int(17 * s), MUTED,
                 maxw=r.width - int(32 * s))
        if d.get("clients") is not None:
            text(surf, f"{d['clients']} joined", (r.x + int(16 * s), r.bottom - int(36 * s)), int(20 * s), ACCENT)

        # services
        r = self.card(surf, cell(0, 1), "Services")
        y = r.y + int(40 * s)
        for label, state in d.get("services", []):
            ok = state == "active"
            pygame.draw.circle(surf, ACCENT if ok else (DANGER if d.get("unlocked") else MUTED),
                               (r.x + int(24 * s), y + int(10 * s)), int(6 * s))
            text(surf, label, (r.x + int(40 * s), y), int(17 * s))
            text(surf, "up" if ok else state, (r.right - int(16 * s), y), int(15 * s), MUTED, anchor="topright")
            y += int(27 * s)

        # power: the battery, or the plug when there is no battery module
        r = self.card(surf, cell(1, 1), "Battery" if b.get("present") else "Power")
        if b.get("present"):
            pct = b.get("percent", 0)
            on_batt = b.get("on_battery")
            color = DANGER if pct < 15 and on_batt else (WARN if pct < 35 and on_batt else ACCENT)
            text(surf, f"{pct:.0f}%", (r.x + int(16 * s), r.y + int(36 * s)), int(44 * s), color, kind="bold")
            if b.get("ac_present"):
                plug(surf, (r.right - int(34 * s), r.y + int(62 * s)), s, ACCENT, scale=1.8)
            if b.get("ac_present"):
                how = "plugged in · charging" if b.get("charging") else "plugged in"
            elif on_batt:
                ml = b.get("minutes_left")
                how = f"on battery · ~{ml // 60}h {ml % 60:02d}m" if ml is not None else "on battery"
            else:
                how = "source unknown"
            text(surf, how, (r.x + int(16 * s), r.bottom - int(34 * s)), int(17 * s), MUTED,
                 maxw=r.width - int(32 * s))
        else:
            plug(surf, (r.x + int(40 * s), r.y + int(64 * s)), s, ACCENT, scale=2.2)
            text(surf, "External", (r.x + int(76 * s), r.y + int(42 * s)), int(24 * s), kind="bold")
            text(surf, "power", (r.x + int(76 * s), r.y + int(70 * s)), int(24 * s), kind="bold")
            text(surf, "no battery module fitted", (r.x + int(16 * s), r.bottom - int(34 * s)),
                 int(15 * s), MUTED, maxw=r.width - int(32 * s))

        # system
        r = self.card(surf, cell(2, 1), "System")
        lines = []
        if d.get("temp") is not None:
            lines.append(("Temp", f"{d['temp']:.0f} °C"))
        lines.append(("Up", d.get("uptime", "?")))
        disk = d.get("disk")
        if disk:
            lines.append(("Free", f"{disk[0]:.1f} GB"))
        y = r.y + int(40 * s)
        for k, v in lines:
            text(surf, k, (r.x + int(16 * s), y), int(17 * s), MUTED)
            text(surf, v, (r.right - int(16 * s), y), int(19 * s), anchor="topright", kind="mono")
            y += int(30 * s)

    def draw_join(self, surf, d):
        s = self.s
        self.top_bar(surf, d, "Join the console")
        top, bottom = int(64 * s), self.H - int(78 * s)
        half = self.W // 2
        qsize = min(bottom - top - int(70 * s), half - int(60 * s))
        # Wi-Fi
        if d.get("net_mode") == "hotspot" and d.get("ssid"):
            if self.show_wifi_secret:
                img = qr_surface(wifi_qr_payload(d["ssid"], d.get("psk"), d.get("hidden")), qsize)
                if img:
                    surf.blit(img, img.get_rect(midtop=(half // 2, top + int(6 * s))))
                text(surf, f"1 · Join “{d['ssid']}”", (half // 2, bottom - int(46 * s)), int(18 * s),
                     anchor="center", maxw=half - int(30 * s))
                b = Button((half // 2 - int(80 * s), bottom - int(30 * s), int(160 * s), int(30 * s)),
                           "Hide", lambda: setattr(self, "show_wifi_secret", False), style="ghost")
            else:
                box = pygame.Rect(0, 0, qsize, qsize)
                box.midtop = (half // 2, top + int(6 * s))
                pygame.draw.rect(surf, PANEL, box, border_radius=int(12 * s))
                text(surf, "Wi-Fi QR", box.center, int(22 * s), MUTED, anchor="center")
                text(surf, "contains the passphrase", (box.centerx, box.centery + int(30 * s)), int(15 * s),
                     MUTED, anchor="center")
                text(surf, f"1 · Join “{d['ssid']}”", (half // 2, bottom - int(46 * s)), int(18 * s),
                     anchor="center", maxw=half - int(30 * s))
                b = Button((half // 2 - int(80 * s), bottom - int(30 * s), int(160 * s), int(30 * s)),
                           "Show", lambda: setattr(self, "show_wifi_secret", True), style="ghost")
            b.draw(surf, s); self.buttons.append(b)
        else:
            text(surf, "Not running a hotspot", (half // 2, (top + bottom) // 2), int(20 * s), MUTED, anchor="center")
        # console
        url = d.get("url") or d.get("local_url")
        img = qr_surface(url, qsize) if url else None
        if img:
            surf.blit(img, img.get_rect(midtop=(half + half // 2, top + int(6 * s))))
        text(surf, "2 · Open the console", (half + half // 2, bottom - int(46 * s)), int(18 * s), anchor="center")
        text(surf, url or "", (half + half // 2, bottom - int(20 * s)), int(16 * s), ACCENT, kind="mono",
             anchor="center", maxw=half - int(30 * s))
        pygame.draw.line(surf, LINE, (half, top + int(10 * s)), (half, bottom - int(10 * s)))

    def draw_trust(self, surf, d):
        s = self.s
        self.top_bar(surf, d, "Trust this console")
        top, bottom = int(64 * s), self.H - int(78 * s)
        if not d.get("tls"):
            text(surf, "HTTPS is off (TLS=off).", (self.W // 2, (top + bottom) // 2), int(22 * s), MUTED,
                 anchor="center")
            return
        qsize = min(bottom - top - int(20 * s), int(self.W * 0.38))
        img = qr_surface(d["trust_url"], qsize)
        if img:
            surf.blit(img, img.get_rect(topleft=(int(24 * s), top + int(8 * s))))
        x = int(24 * s) + qsize + int(26 * s)
        w = self.W - x - int(20 * s)
        text(surf, "Once per phone or laptop", (x, top + int(10 * s)), int(22 * s), kind="bold")
        y = top + int(48 * s)
        for line in ("Scan, then install the certificate.", "The page has steps for each device."):
            text(surf, line, (x, y), int(17 * s), MUTED, maxw=w)
            y += int(25 * s)
        text(surf, d["trust_url"], (x, y + int(8 * s)), int(16 * s), ACCENT, kind="mono", maxw=w)
        y += int(46 * s)
        text(surf, "SHA-256 — check it matches:", (x, y), int(15 * s), MUTED)
        fp = d.get("fingerprint") or "(unlock to create it)"
        parts = fp.split(":")
        for i in range(0, len(parts), 8):
            y += int(23 * s)
            text(surf, ":".join(parts[i:i + 8]), (x, y), int(16 * s), TEXT, kind="mono", maxw=w)
        if d.get("fingerprint_sha1"):
            # Windows' install dialog shows only this one.
            y += int(30 * s)
            text(surf, "SHA-1 — what Windows shows:", (x, y), int(15 * s), MUTED)
            parts = d["fingerprint_sha1"].split(":")
            for i in range(0, len(parts), 10):
                y += int(23 * s)
                text(surf, ":".join(parts[i:i + 10]), (x, y), int(16 * s), TEXT, kind="mono", maxw=w)

    def draw_menu(self, surf, d):
        s = self.s
        self.top_bar(surf, d, "Menu")
        top, bottom = int(68 * s), self.H - int(82 * s)
        cols, rows = 4, 3
        pad = int(12 * s)
        bw = (self.W - pad * (cols + 1)) // cols
        bh = (bottom - top - pad * (rows - 1)) // rows
        hot = d.get("net_mode") == "hotspot"
        items = [
            ("Lock case file", "stop console, close store",
             lambda: self.ask("Lock the case file?", "The console stops and the PIN is needed to open it again.",
                              lambda: self.ctl("Locking", "lock")), "danger"),
            ("Restart console", "API and worker",
             lambda: self.ctl("Restarting console", "restart"), "normal"),
            ("Wired network" if hot else "Hotspot", "switch to Ethernet" if hot else "be the access point",
             lambda: self.ask("Switch network?",
                              "Devices on the current network will lose the console." if hot else
                              "The box becomes the Wi-Fi access point again.",
                              lambda: self.ctl("Switching network", "net", "wired" if hot else "hotspot"),
                              danger=False), "normal"),
            ("Calibrate touch", "tap 4 targets", self.start_calibration, "normal"),
            ("Sleep screen", "touch to wake", lambda: setattr(self, "asleep", True), "normal"),
            ("Renew certificate", "after a network change",
             lambda: self.ctl("Renewing certificate", "tls", "renew"), "normal"),
            ("Restart box", "asks for the PIN again",
             lambda: self.ask("Restart the box?", "The case file locks; the PIN opens it again.",
                              lambda: self.ctl("Restarting", "reboot")), "danger"),
            ("Shut down", "safe to unplug after",
             lambda: self.ask("Shut down?", "Wait for the screen to go dark before unplugging.",
                              lambda: self.ctl("Shutting down", "shutdown")), "danger"),
            ("Update from USB", "a signed update bundle",
             lambda: self.ask("Update from the USB stick?",
                              "The console restarts on the new version; if it does not come back, it is "
                              "put back as it was.",
                              lambda: self.ctl("Updating", "update", "usb"), danger=False), "normal"),
            ("Wipe case file", "erase everything, for good",
             lambda: self.ask("Wipe the case file?",
                              "Every record, report and file on this box is destroyed. It restarts into setup.",
                              lambda: self.ask("This cannot be undone.",
                                               "Copies on USB sticks or other devices are not touched.",
                                               lambda: self.ctl("Wiping", "wipe", "--yes"))), "danger"),
            ("Duress PIN", "erases if typed at unlock",
             lambda: self.ctl_waiting("Duress PIN", ["duress", "set", "--panel"],
                                      {0: "Duress PIN set", 1: "Duress PIN not changed",
                                       3: "That's the real PIN — choose another",
                                       4: "Too short — at least 4 characters"}), "normal"),
            ("New login", "password for SSH, keyboard",
             lambda: self.ask("New login password?",
                              "The old one stops working. The new one is shown here once.",
                              lambda: self.ctl("New login password", "login-password"), danger=False),
             "normal"),
        ]
        for i, (label, sub, act, style) in enumerate(items):
            r = (pad + (i % cols) * (bw + pad), top + (i // cols) * (bh + pad), bw, bh)
            b = Button(r, label, act, style=style, sub=sub,
                       enabled=not (label == "Renew certificate" and not d.get("tls")))
            b.draw(surf, s); self.buttons.append(b)

    def draw_secret(self, surf, d):
        s = self.s
        sec = d.get("login_secret") or {}
        self.top_bar(surf, d, "Login password")
        text(surf, "This box's login", (self.W // 2, int(96 * s)), int(26 * s), kind="bold", anchor="center")
        text(surf, "for SSH and the keyboard console — not the PIN, not the web console",
             (self.W // 2, int(132 * s)), int(16 * s), MUTED, anchor="center", maxw=self.W - int(40 * s))
        text(surf, sec.get("user", ""), (self.W // 2, int(186 * s)), int(24 * s), MUTED, kind="mono",
             anchor="center")
        text(surf, sec.get("password", ""), (self.W // 2, int(240 * s)), int(46 * s), ACCENT, kind="mono",
             anchor="center", maxw=self.W - int(40 * s))
        text(surf, "Write it down now. It is shown once; Menu → New login replaces it.",
             (self.W // 2, int(300 * s)), int(16 * s), WARN, anchor="center", maxw=self.W - int(40 * s))
        b = Button((self.W // 2 - int(170 * s), self.H - int(110 * s), int(340 * s), int(72 * s)),
                   "I've written it down", self.dismiss_secret, style="primary")
        b.draw(surf, s); self.buttons.append(b)

    def dismiss_secret(self):
        try:
            os.unlink(LOGIN_SECRET)
        except OSError:
            pass
        self.screen = "home"
        self.status.refresh()

    def draw_calibrate(self, surf, d):
        s = self.s
        surf.fill(BG)
        i = len(self.cal_raw)
        text(surf, "Calibrate touch", (self.W // 2, self.H // 2 - int(30 * s)), int(28 * s), kind="bold",
             anchor="center")
        text(surf, f"Tap the centre of each cross, precisely ({i + 1} of {len(self.cal_points)})",
             (self.W // 2, self.H // 2 + int(10 * s)), int(17 * s), MUTED, anchor="center")
        if i < len(self.cal_points):
            x, y = map(int, self.cal_points[i])
            k = int(22 * s)
            pygame.draw.line(surf, ACCENT, (x - k, y), (x + k, y), max(2, int(3 * s)))
            pygame.draw.line(surf, ACCENT, (x, y - k), (x, y + k), max(2, int(3 * s)))
            pygame.draw.circle(surf, ACCENT, (x, y), int(10 * s), width=max(1, int(2 * s)))


# ---------------------------------------------------------------------------
# Output: the Linux framebuffer
# ---------------------------------------------------------------------------

class FramebufferScreen:
    """Copies finished frames into /dev/fb0 (the KMS driver's console
    framebuffer), converting to its 16- or 32-bit pixel format. Puts tty1 in
    graphics mode while it runs, so login prompts and kernel messages do not
    scribble over the panel, and gives the console back when it stops."""

    FBIOGET_VSCREENINFO = 0x4600
    KDSETMODE, KD_TEXT, KD_GRAPHICS = 0x4B3A, 0x00, 0x01

    def __init__(self, dev="/dev/fb0", tty="/dev/tty1", geometry=None):
        self.fd = os.open(dev, os.O_RDWR)
        if geometry is None:
            geometry = self._probe(dev)
        self.w, self.h, self.bpp, self.stride, self.yoffset = geometry
        masks = {16: (0xF800, 0x07E0, 0x001F, 0), 32: (0xFF0000, 0x00FF00, 0x0000FF, 0)}.get(self.bpp)
        if masks is None:
            os.close(self.fd)
            raise RuntimeError(f"unsupported framebuffer depth {self.bpp} bpp")
        self.frame = pygame.Surface((self.w, self.h), 0, self.bpp, masks)
        self.offset = self.yoffset * self.stride
        self.mm = mmap.mmap(self.fd, self.offset + self.stride * self.h)
        self.tty = None
        try:
            self.tty = os.open(tty, os.O_RDWR | os.O_NOCTTY)
            fcntl.ioctl(self.tty, self.KDSETMODE, self.KD_GRAPHICS)
        except OSError:
            if self.tty is not None:
                os.close(self.tty)
            self.tty = None

    def _probe(self, dev):
        info = fcntl.ioctl(self.fd, self.FBIOGET_VSCREENINFO, bytes(160))
        xres, yres, _xv, _yv, _xo, yoffset, bpp = struct.unpack_from("7I", info)
        name = os.path.basename(dev)
        try:
            stride = int(open(f"/sys/class/graphics/{name}/stride").read())
        except (OSError, ValueError):
            stride = xres * bpp // 8
        return xres, yres, bpp, stride, yoffset

    def show(self, canvas):
        self.frame.blit(canvas, (0, 0))
        raw = self.frame.get_buffer().raw
        pitch = self.frame.get_pitch()
        if pitch == self.stride:
            self.mm[self.offset:self.offset + pitch * self.h] = raw
        else:
            row = self.w * self.bpp // 8
            for y in range(self.h):
                at = self.offset + y * self.stride
                self.mm[at:at + row] = raw[y * pitch:y * pitch + row]

    def close(self):
        try:
            if self.tty is not None:
                fcntl.ioctl(self.tty, self.KDSETMODE, self.KD_TEXT)
                os.close(self.tty)
        except OSError:
            pass
        self.tty = None
        try:
            self.mm.close()
            os.close(self.fd)
        except (OSError, ValueError):
            pass


class SDLScreen:
    """Fallback: SDL's own KMS/DRM output (needs EGL/Mesa installed)."""

    def __init__(self, size):
        pygame.display.quit()
        os.environ["SDL_VIDEODRIVER"] = "kmsdrm"
        pygame.display.init()
        self.screen = pygame.display.set_mode(size, pygame.FULLSCREEN)
        self.w, self.h = self.screen.get_size()

    def show(self, canvas):
        self.screen.blit(canvas, (0, 0))
        pygame.display.flip()

    def close(self):
        pass


def open_screen(panel):
    want = (panel.get("width") or 800, panel.get("height") or 480)
    errors = []
    if os.path.exists("/dev/fb0"):
        try:
            return FramebufferScreen()
        except (OSError, RuntimeError, ValueError) as e:
            errors.append(f"framebuffer: {e}")
    try:
        return SDLScreen(want)
    except pygame.error as e:
        errors.append(f"kmsdrm: {e}")
    raise RuntimeError("no way to draw on the screen — " + "; ".join(errors))


# ---------------------------------------------------------------------------

def main() -> int:
    disp = read_json(DISPLAY, {}) or {}
    panel = disp.get("panel")
    if not panel:
        print("humint-panel: no panel screen detected; nothing to do")
        return 0
    env = read_env()
    rotate = 180 if env.get("SCREEN_ROTATE") == "180" else 0
    sleep_after = max(0, int(env.get("SCREEN_SLEEP_MINUTES", "5") or 0)) * 60

    pygame.display.init()          # dummy driver: just the event queue
    pygame.font.init()
    out = open_screen(panel)
    w, h = out.w, out.h
    print(f"humint-panel: drawing {w}x{h} via {type(out).__name__}", flush=True)
    canvas = pygame.Surface((w, h))

    stop = threading.Event()
    status = Status()
    threading.Thread(target=status.loop, args=(stop,), daemon=True).start()
    events = queue.Queue()
    cal = Calibration(w, h)
    touch = (panel.get("touch") or {}).get("event")
    inp = Input(events, cal, touch)
    inp.start(stop)
    ui = Panel((w, h), status, events, cal, inp, rotate)

    clock = pygame.time.Clock()
    try:
        while True:
            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    return 0
            while True:
                try:
                    ui.handle(events.get_nowait())
                except queue.Empty:
                    break
            d = status.get()
            if sleep_after and not ui.asleep and d.get("unlocked") and ui.current(d) in ("home", "join", "trust") \
                    and time.time() - ui.last_input > sleep_after:
                ui.asleep = True
            ui.draw(canvas)
            out.show(pygame.transform.rotate(canvas, 180) if rotate == 180 else canvas)
            clock.tick(4 if ui.asleep else 15)
    finally:
        stop.set()
        inp.grab_keyboards(False)
        out.close()
        pygame.quit()


if __name__ == "__main__":
    sys.exit(main())
