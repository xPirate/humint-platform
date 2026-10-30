#!/usr/bin/env python3
"""The native app's hands on the machine.

The app (humint-ui) runs as its own unprivileged account and draws the
screen; this small service runs as root and does, on its behalf, exactly
what the Pi's touch panel does as root — and nothing else:

  status            the machine's state (locked, network, battery, ...)
  unlock PIN        open the case file (humint-unlock-try: one shared count
                    of wrong PINs with every other way in)
  setup_pin PIN     answer first boot's / the duress-PIN prompt
  setup_pin_cancel
  ctl ACTION        lock, restart, reboot, shutdown, net, update usb, wipe,
                    duress set, login-password — through humint-ctl
  store_grow GB PIN  make the case file larger (humint-ctl store grow, PIN on stdin)
  display_set PCT   the screen's brightness (its backlight), 5-100
  screen_power ON   the panel on or off (the screen sleeping; brightness kept)
  audio_set         the volume (0-100) and/or mute
  screen_settings   minutes until the screen sleeps (0 = never), and whether
                    sleeping signs the console out
  wifi_scan         the Wi-Fi networks in range (to join one)
  wifi_join SSID PSK  join one — humint-ctl net client, the password on stdin
  dismiss_secret    the new login password has been written down
  upload_people     phone upload codes (api/panel.py), with the panel's token,
  upload_code       which the app itself never sees

It listens on /run/humint/box.sock, which only root and the humint-ui group
can open, and checks each caller's account as well (SO_PEERCRED). One JSON
request per line, one JSON answer per line.

Keeping the app out of root matters: it renders whatever the case file
holds (reports, documents, images). A flaw in that cannot reach the PIN, the
wipe or the network settings except through these few verbs.
"""
import grp
import json
import os
import pwd
import re
import shlex
import shutil
import socket
import socketserver
import ssl
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

SOCK = os.environ.get("HUMINT_BOX_SOCK", "/run/humint/box.sock")
UI_GROUP = os.environ.get("HUMINT_UI_GROUP", "humint-ui")
ROOT = os.environ.get("HUMINT_TEST_ROOT", "")

ENV = ROOT + "/var/lib/humint/env"
MESSAGE = ROOT + "/run/humint/message.json"
BATTERY = ROOT + "/run/humint/battery.json"
CLOCK = ROOT + "/run/humint/clock.json"
LOGIN_SECRET = ROOT + "/run/humint/login-password.json"
UPDATE_STATUS = ROOT + "/run/humint/update.json"
PANEL_TOKEN = ROOT + "/srv/humint-data/panel.token"
TRIES = ROOT + "/run/humint/unlock-tries"
PIN_SETUP_REQ = ROOT + "/run/humint/pin-setup"
PIN_SETUP_FIFO = ROOT + "/run/humint/pin-setup.fifo"
FP = ROOT + "/var/lib/humint/ca.fingerprint"
NET_FALLBACK = ROOT + "/run/humint/net-fallback"
BACKLIGHT = ROOT + "/sys/class/backlight"
ASOUND_CARDS = ROOT + "/proc/asound/cards"
AMIXER = os.environ.get("HUMINT_AMIXER", "amixer")
ALSACTL = os.environ.get("HUMINT_ALSACTL", "alsactl")
SLEEP_CHOICES = (0, 1, 2, 5, 10, 15, 30, 60)
NMCLI = os.environ.get("HUMINT_NMCLI", "nmcli")
WIFI_DEV = os.environ.get("WIFI_DEV", "wlan0")
STORE_IMG = ROOT + "/srv/humint.img"
DATA = ROOT + "/srv/humint-data"
READY = ROOT + "/run/humint-data.ready"
FIRSTBOOT_DONE = ROOT + "/var/lib/humint/firstboot.done"
DURESS = ROOT + "/var/lib/humint/duress"
BUILD = ROOT + "/opt/humint-platform/BUILD.json"
CTL = os.environ.get("HUMINT_CTL", "/opt/humint/bin/humint-ctl")
TRY = os.environ.get("HUMINT_TRY", "/opt/humint/bin/humint-unlock-try")
SERVICES = (("Database", "postgresql@16-main"), ("Console", "humint-api"),
            ("Worker", "humint-worker"), ("HTTPS", "humint-http"))
PIN_MIN_LENGTH = 4
STORE_RESERVE = 4096 * 2**20      # as humint-ctl's STORE_RESERVE_MB

# What the app may ask humint-ctl to do: action → allowed argument lists.
CTL_ALLOWED = {
    "lock": [[]],
    "restart": [[]],
    "reboot": [[]],
    "shutdown": [[]],
    "net": [["wired"], ["hotspot"]],
    "update": [["usb"]],
    "os-update": [[]],
    "wipe": [["--yes"]],
    "duress": [["set", "--panel"], ["clear"]],
    "login-password": [[]],
}


def read_env(path=None) -> dict:
    out = {}
    try:
        for line in open(path or ENV):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.strip()
            # Values a person typed (the Wi-Fi to join) are shell-quoted
            # (set_env_quoted); the rest are plain or "double-quoted".
            try:
                parts = shlex.split(v)
                v = parts[0] if len(parts) == 1 else v.strip('"').strip("'")
            except ValueError:
                v = v.strip('"').strip("'")
            out[k.strip()] = v
    except OSError:
        pass
    return out


def read_json(path, default=None):
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return default


def out(cmd, timeout=5) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def run(cmd, stdin=None, timeout=300) -> int:
    try:
        return subprocess.run(cmd, input=stdin, timeout=timeout, text=True,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
    except subprocess.TimeoutExpired:
        return 124
    except OSError:
        return 127


# ---- status -----------------------------------------------------------------

_cache = {"at": 0.0, "data": None}
_cache_lock = threading.Lock()
# The facts that cost a process each to learn (addresses, who is on the
# hotspot, which services run) change rarely; the screen asks every two
# seconds. Learned at most every SLOW_EVERY seconds — on battery, fewer
# wake-ups — and at once after anything done through here (invalidate()).
SLOW_EVERY = 10.0
_slow = {"at": 0.0, "key": None, "data": None}


def slow_facts(tls: bool, hotspot: bool) -> dict:
    key = (tls, hotspot)
    with _cache_lock:
        if _slow["data"] is not None and _slow["key"] == key and time.time() - _slow["at"] < SLOW_EVERY:
            return _slow["data"]
    f = {}
    # The network's own address first; a self-assigned 169.254 one (kept for
    # a bare switch with no DHCP) only when there is nothing else.
    f["ips"] = sorted(out(["hostname", "-I"]).split(), key=lambda a: a.startswith("169.254."))
    f["hostname"] = out(["hostname", "-s"]).strip()
    f["clients"] = out(["iw", "dev", "wlan0", "station", "dump"]).count("Station ") if hotspot else None
    units = [(label, unit) for label, unit in SERVICES if tls or unit != "humint-http"]
    # One systemctl for all of them: a line per unit, in order.
    states = out(["systemctl", "is-active"] + [u for _, u in units]).split()
    f["services"] = [[label, states[i] if i < len(states) else "unknown"] for i, (label, _) in enumerate(units)]
    f["audio"] = audio_facts()
    with _cache_lock:
        _slow.update(at=time.time(), key=key, data=f)
    return f


def status() -> dict:
    with _cache_lock:
        if _cache["data"] is not None and time.time() - _cache["at"] < 1.0:
            return _cache["data"]
    env = read_env()
    d = {"env_ok": bool(env)}
    d["store_exists"] = os.path.exists(STORE_IMG)
    d["firstboot_done"] = os.path.exists(FIRSTBOOT_DONE)
    try:
        d["pin_setup"] = open(PIN_SETUP_REQ).read().strip() or None
    except OSError:
        d["pin_setup"] = None
    d["unlocked"] = os.path.exists(READY) and (bool(ROOT) or os.path.ismount(DATA))
    max_tries = int(os.environ.get("HUMINT_UNLOCK_TRIES", "5"))
    try:
        used = int(open(TRIES).read().strip() or 0)
    except (OSError, ValueError):
        used = 0
    d["tries_left"] = max(0, max_tries - used)
    msg = read_json(MESSAGE, {}) or {}
    d["message"] = msg if time.time() - msg.get("time", 0) < 600 else {}
    d["tls"] = env.get("TLS", "on") == "on"
    d["net_mode"] = env.get("NET_MODE", "hotspot")
    slow = slow_facts(d["tls"], d["net_mode"] == "hotspot")
    ips = slow["ips"]
    d["ip"] = ips[0] if ips else ""
    d["host"] = env.get("HOSTNAME") or slow["hostname"] or "humint"
    d["name"] = env.get("INSTANCE_NAME") or "HUMINT field server"
    if d["tls"]:
        d["url"] = f"https://{d['ip']}" if d["ip"] else ""
    else:
        port = env.get("API_PORT", "80")
        d["url"] = (f"http://{d['ip']}" + ("" if port == "80" else f":{port}")) if d["ip"] else ""
    # Where the app reaches the console on this machine.
    d["api_base"] = os.environ.get("HUMINT_CONSOLE_URL") or (
        f"https://127.0.0.1:{env.get('HTTPS_PORT', '443')}" if d["tls"]
        else f"http://127.0.0.1:{env.get('API_PORT', '80')}")
    d["local_url"] = ("https://" if d["tls"] else "http://") + f"{d['host']}.local"
    d["trust_url"] = f"http://{d['ip'] or d['host'] + '.local'}/trust"
    d["ssid"] = env.get("AP_SSID") if d["net_mode"] == "hotspot" else env.get("CLIENT_SSID")
    # The hotspot's password is for showing to the team; a network this
    # machine joined is someone else's, and its password stays in the file.
    d["psk"] = env.get("AP_PSK") if d["net_mode"] == "hotspot" else None
    try:
        d["net_fallback"] = open(NET_FALLBACK).read().strip() or None
    except OSError:
        d["net_fallback"] = None
    d["hidden"] = env.get("AP_HIDDEN", "false") == "true"
    d["clients"] = slow["clients"]
    d["services"] = slow["services"]
    d["battery"] = read_json(BATTERY, {}) or {}
    d["clock"] = read_json(CLOCK, {}) or {}
    d["login_secret"] = read_json(LOGIN_SECRET, None)
    # The last update's progress or outcome (bundle or system), for the screen.
    d["update"] = read_json(UPDATE_STATUS, None)
    d["display"] = display_facts(env)
    d["audio"] = slow["audio"]
    d["duress_set"] = os.path.exists(DURESS)
    try:
        u = shutil.disk_usage(DATA if d["unlocked"] else "/")
        d["disk"] = [round(u.free / 1e9, 1), round(u.total / 1e9, 1)]
    except OSError:
        d["disk"] = None
    # The case file's size, and how far it could grow: the disk's free space
    # less what humint-ctl keeps free (STORE_RESERVE_MB there).
    try:
        size = os.path.getsize(STORE_IMG)
        free = shutil.disk_usage(os.path.dirname(STORE_IMG) or "/").free
        d["store"] = {"size_gb": size // 2**30, "max_gb": (size + max(0, free - STORE_RESERVE)) // 2**30}
    except OSError:
        d["store"] = None
    temps = []
    for zone in sorted(os.listdir("/sys/class/thermal")) if os.path.isdir("/sys/class/thermal") else []:
        try:
            temps.append(int(open(f"/sys/class/thermal/{zone}/temp").read()) / 1000)
        except (OSError, ValueError):
            pass
    d["temp"] = max(temps) if temps else None
    try:
        secs = float(open("/proc/uptime").read().split()[0])
        d["uptime"] = f"{int(secs // 3600)}h {int(secs % 3600 // 60):02d}m"
    except (OSError, ValueError):
        d["uptime"] = "?"
    try:
        d["fingerprint"] = open(FP).read().strip()
    except OSError:
        d["fingerprint"] = ""
    d["build"] = read_json(BUILD, {}) or {}
    d["time"] = int(time.time())
    with _cache_lock:
        _cache.update(at=time.time(), data=d)
    return d


# ---- the screen and the sound ---------------------------------------------------
# What a laptop's own controls do: the backlight (brightness, and switched off
# while the screen sleeps — the panel itself goes dark, not just black pixels)
# and the sound card's volume (ALSA; there is no sound server). Both are
# remembered across restarts by the system itself: systemd-backlight and
# alsa-restore.

def backlight_dev():
    """The backlight to drive: the firmware's interface first, then the
    platform's, then the raw one (as desktops choose) — the one that
    tracks the brightness keys."""
    try:
        names = sorted(os.listdir(BACKLIGHT))
    except OSError:
        return None
    rank = {"firmware": 0, "platform": 1, "raw": 2}
    best = None
    for n in names:
        try:
            kind = open(f"{BACKLIGHT}/{n}/type").read().strip()
            mx = int(open(f"{BACKLIGHT}/{n}/max_brightness").read())
        except (OSError, ValueError):
            continue
        if mx <= 0:
            continue
        key = (rank.get(kind, 3), -mx)
        if best is None or key < best[0]:
            best = (key, n, mx)
    return (f"{BACKLIGHT}/{best[1]}", best[2]) if best else None


def display_facts(env) -> dict:
    try:
        minutes = int(env.get("SCREEN_SLEEP_MINUTES", "10"))
    except ValueError:
        minutes = 10
    d = {"backlight": False, "brightness": None, "sleep_minutes": minutes,
         "sleep_signout": env.get("SCREEN_SLEEP_SIGNOUT", "false") == "true"}
    b = backlight_dev()
    if b:
        path, mx = b
        try:
            d["brightness"] = max(0, min(100, round(int(open(path + "/brightness").read()) * 100 / mx)))
            d["backlight"] = True
        except (OSError, ValueError):
            pass
    return d


def op_display_set(req):
    try:
        pct = int(req.get("brightness"))
    except (TypeError, ValueError):
        raise Refused("Brightness: a percentage")
    b = backlight_dev()
    if not b:
        raise Refused("This screen's brightness cannot be set from here (no backlight control)")
    path, mx = b
    # Never all the way off by a slider: a black screen nobody can find the
    # slider on. (Sleeping switches the panel off instead — screen_power.)
    pct = max(5, min(100, pct))
    with open(path + "/brightness", "w") as f:
        f.write(str(max(1, round(mx * pct / 100))))
    invalidate()
    return {"brightness": pct}


def op_screen_power(req):
    on = bool(req.get("on"))
    b = backlight_dev()
    if b:
        try:
            with open(b[0] + "/bl_power", "w") as f:
                f.write("0" if on else "4")     # FB_BLANK_UNBLANK / FB_BLANK_POWERDOWN
        except OSError:
            pass                                # the app's black cover still sleeps it
    return {"on": on, "backlight": bool(b)}


_mixer = {"at": 0.0, "where": None}


def mixer():
    """(card, control) to drive: the first sound card with a playback volume,
    preferring Master. Looked up again now and then (a USB headset)."""
    if time.time() - _mixer["at"] < 60:
        return _mixer["where"]
    found = None
    try:
        cards = [l.split()[0] for l in open(ASOUND_CARDS) if l[:3].strip().isdigit()]
    except OSError:
        cards = []
    for card in cards:
        controls = re.findall(r"Simple mixer control '([^']+)',0", out([AMIXER, "-c", card, "scontrols"]))
        for want in ("Master", "Speaker", "PCM", "Headphone"):
            if want in controls:
                found = (card, want)
                break
        if found:
            break
    _mixer.update(at=time.time(), where=found)
    return found


def audio_facts() -> dict:
    where = mixer()
    if not where:
        return {"present": False}
    text = out([AMIXER, "-M", "-c", where[0], "sget", where[1]])
    vols = [int(v) for v in re.findall(r"\[(\d+)%\]", text)]
    switches = re.findall(r"\[(on|off)\]", text)
    if not vols:
        return {"present": False}
    return {"present": True, "volume": round(sum(vols) / len(vols)),
            "muted": bool(switches) and all(sw == "off" for sw in switches), "control": where[1]}


def op_audio_set(req):
    where = mixer()
    if not where:
        raise Refused("No sound card")
    card, ctl = where
    args = []
    if req.get("volume") is not None:
        try:
            vol = max(0, min(100, int(req.get("volume"))))
        except (TypeError, ValueError):
            raise Refused("Volume: a percentage")
        args.append(f"{vol}%")
    if req.get("muted") is not None:
        args.append("mute" if req.get("muted") else "unmute")
    if not args:
        raise Refused("Nothing to change")
    if run([AMIXER, "-q", "-M", "-c", card, "sset", ctl, *args], timeout=10) != 0:
        # A control with no switch: mute/unmute refused; the volume alone then.
        if req.get("volume") is None or run([AMIXER, "-q", "-M", "-c", card, "sset", ctl, args[0]], timeout=10) != 0:
            raise Refused("The sound card did not take it")
    # Remembered for the next start (alsa-restore reads it), in the background.
    threading.Thread(target=run, args=([ALSACTL, "store"],), kwargs={"timeout": 20}, daemon=True).start()
    invalidate()
    return audio_facts()


def write_env_values(values: dict):
    """Plain values (digits, true/false) into the settings file, keeping
    its mode (600) and every other line."""
    lines, seen = [], set()
    try:
        old = open(ENV).read().splitlines()
    except OSError:
        old = []
    for line in old:
        k = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else None
        if k in values:
            lines.append(f"{k}={values[k]}")
            seen.add(k)
        else:
            lines.append(line)
    lines += [f"{k}={v}" for k, v in values.items() if k not in seen]
    tmp = ENV + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(lines) + "\n")
    try:
        st = os.stat(ENV)
        os.chmod(tmp, st.st_mode & 0o777)
        os.chown(tmp, st.st_uid, st.st_gid)
    except OSError:
        pass
    os.replace(tmp, ENV)


def op_screen_settings(req):
    values = {}
    if req.get("sleep_minutes") is not None:
        try:
            m = int(req.get("sleep_minutes"))
        except (TypeError, ValueError):
            m = -1
        if m not in SLEEP_CHOICES:
            raise Refused("Screen sleep: one of " + ", ".join(map(str, SLEEP_CHOICES)) + " minutes")
        values["SCREEN_SLEEP_MINUTES"] = str(m)
    if req.get("sleep_signout") is not None:
        values["SCREEN_SLEEP_SIGNOUT"] = "true" if req.get("sleep_signout") else "false"
    if not values:
        raise Refused("Nothing to change")
    write_env_values(values)
    invalidate()
    return display_facts(read_env())


def invalidate():
    with _cache_lock:
        _cache["data"] = None
        _slow["data"] = None


# ---- actions ------------------------------------------------------------------

class Refused(Exception):
    pass


def write_fifo(text: str):
    try:
        fd = os.open(PIN_SETUP_FIFO, os.O_WRONLY | os.O_NONBLOCK)
    except OSError as e:
        raise Refused(f"Nothing is waiting for a PIN ({e.strerror})")
    try:
        os.write(fd, text.encode())
    finally:
        os.close(fd)


def op_setup_pin(req):
    pin = str(req.get("pin") or "")
    stage = status().get("pin_setup")
    if not stage:
        raise Refused("Nothing is waiting for a PIN")
    if "\n" in pin or "\r" in pin or "\0" in pin:
        raise Refused("A PIN cannot contain line breaks")
    if stage in ("new", "duress") and len(pin) < PIN_MIN_LENGTH:
        raise Refused(f"Use at least {PIN_MIN_LENGTH} characters")
    write_fifo(pin + "\n")
    for _ in range(40):
        if not os.path.exists(PIN_SETUP_REQ):
            break
        time.sleep(0.25)
    invalidate()
    return {"stage": stage}


def op_setup_pin_cancel(req):
    try:
        write_fifo("\n")
    except Refused:
        pass
    invalidate()
    return {}


def op_unlock(req):
    pin = str(req.get("pin") or "")
    if not pin or "\n" in pin or "\0" in pin:
        raise Refused("Enter the PIN")
    rc = run([TRY], stdin=pin + "\n", timeout=600)
    invalidate()
    d = status()
    result = {0: "unlocked", 5: "unlocked", 1: "wrong", 3: "locked_out"}.get(rc, "failed")
    return {"result": result, "rc": rc, "tries_left": d.get("tries_left")}


def op_ctl(req):
    action = str(req.get("action") or "")
    args = [str(a) for a in (req.get("args") or [])]
    if action not in CTL_ALLOWED or args not in CTL_ALLOWED[action]:
        raise Refused(f"Not allowed: {action} {' '.join(args)}".strip())
    timeout = 3600 if action in ("update", "os-update") else 900 if action == "duress" else 300
    rc = run([CTL, action, *args], timeout=timeout)
    invalidate()
    return {"rc": rc}


# ---- joining a Wi-Fi --------------------------------------------------------------

def _terse(line: str) -> list:
    """nmcli -t fields: ':'-separated, with ':' and '\\' escaped."""
    fields, cur, i = [], "", 0
    while i < len(line):
        c = line[i]
        if c == "\\" and i + 1 < len(line):
            cur += line[i + 1]
            i += 2
            continue
        if c == ":":
            fields.append(cur)
            cur = ""
        else:
            cur += c
        i += 1
    return fields + [cur]


def check_wifi(ssid: str, psk: str):
    if not ssid:
        raise Refused("Choose or type the Wi-Fi's name")
    if len(ssid.encode()) > 32:
        raise Refused("That Wi-Fi name is too long (32 bytes at most)")
    if any(ord(c) < 32 or ord(c) == 127 for c in ssid + psk):
        raise Refused("The name and password cannot contain control characters")
    if psk and not (8 <= len(psk) <= 63 or re.fullmatch(r"[0-9A-Fa-f]{64}", psk)):
        raise Refused("A Wi-Fi password is 8 to 63 characters")


def op_wifi_scan(req):
    devs = out([NMCLI, "-t", "-f", "DEVICE,TYPE", "device"], timeout=10)
    if f"{WIFI_DEV}:wifi" not in devs.splitlines():
        return {"wifi": False, "networks": []}
    # Wired mode turns the radio off; on for the scan, and off again after
    # unless the machine goes on to join one (which turns it on itself).
    was_off = out([NMCLI, "radio", "wifi"], timeout=10).strip() == "disabled"
    if was_off:
        run([NMCLI, "radio", "wifi", "on"], timeout=15)
        time.sleep(3)
    # A radio busy being the hotspot sees next to nothing but itself: the
    # hotspot pauses for the scan (a few seconds — the screen has already
    # said the hotspot stops to join another network), and comes back after,
    # so cancelling leaves things as they were.
    env = read_env()
    active = out([NMCLI, "-t", "-f", "NAME", "connection", "show", "--active"], timeout=10).split()
    paused = "humint-ap" in active
    if paused:
        run([NMCLI, "connection", "down", "humint-ap"], timeout=30)
        time.sleep(2)
    try:
        raw = ""
        for _ in range(2):      # the first scan after the radio frees up can come back short
            raw = out([NMCLI, "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list",
                       "ifname", WIFI_DEV, "--rescan", "yes"], timeout=40)
            if any(_terse(l)[1:2] not in ([""], [env.get("AP_SSID", "")]) for l in raw.splitlines()):
                break
            time.sleep(3)
    finally:
        if paused:
            run([NMCLI, "connection", "up", "humint-ap"], timeout=60)
        if was_off:
            run([NMCLI, "radio", "wifi", "off"], timeout=15)
        invalidate()
    best = {}
    for line in raw.splitlines():
        f = _terse(line)
        if len(f) < 4 or not f[1]:
            continue           # hidden networks have no name to show
        if paused and f[1] == env.get("AP_SSID"):
            continue           # this machine's own hotspot
        try:
            signal = int(f[2])
        except ValueError:
            signal = 0
        n = {"ssid": f[1], "signal": signal, "secure": f[3] not in ("", "--"), "in_use": f[0] == "*"}
        if f[1] not in best or signal > best[f[1]]["signal"]:
            best[f[1]] = n
    nets = sorted(best.values(), key=lambda n: (-n["in_use"], -n["signal"], n["ssid"].lower()))
    return {"wifi": True, "networks": nets, "hotspot": env.get("NET_MODE") == "hotspot"}


def op_wifi_join(req):
    ssid = str(req.get("ssid") or "")
    psk = str(req.get("psk") or "")
    check_wifi(ssid, psk)
    env = dict(os.environ, HUMINT_PSK_STDIN="1")
    try:
        p = subprocess.run([CTL, "net", "client", ssid], input=psk + "\n", text=True, env=env,
                           capture_output=True, timeout=300)
        rc, err = p.returncode, p.stderr
    except subprocess.TimeoutExpired:
        rc, err = 124, ""
    except OSError:
        rc, err = 127, ""
    invalidate()
    # Why, in words: what humint-ctl refused, or why the join fell back.
    reason = None
    for line in reversed(err.splitlines()):
        m = re.search(r"ERROR: (.*)", line)
        if m:
            reason = m.group(1).strip()
            break
    try:
        fallback = open(NET_FALLBACK).read().strip() or None
    except OSError:
        fallback = None
    return {"rc": rc, "error": reason, "fallback": fallback if rc == 3 else None}


def op_store_grow(req):
    try:
        gb = int(req.get("size_gb"))
    except (TypeError, ValueError):
        raise Refused("Choose the new size in GB")
    pin = str(req.get("pin") or "")
    if not pin or "\n" in pin or "\0" in pin:
        raise Refused("Enter the PIN")
    if not 1 <= gb <= 100000:
        raise Refused("Choose the new size in GB")
    env = dict(os.environ, HUMINT_PIN_STDIN="1")
    try:
        p = subprocess.run([CTL, "store", "grow", f"{gb}G"], input=pin + "\n", text=True, env=env,
                           capture_output=True, timeout=1800)
        rc, err = p.returncode, p.stderr
    except subprocess.TimeoutExpired:
        rc, err = 124, ""
    except OSError:
        rc, err = 127, ""
    invalidate()
    reason = None
    for line in reversed(err.splitlines()):
        m = re.search(r"ERROR: (.*)", line)
        if m:
            reason = m.group(1).strip()
            break
    return {"rc": rc, "error": reason}


def op_dismiss_secret(req):
    try:
        os.unlink(LOGIN_SECRET)
    except OSError:
        pass
    invalidate()
    return {}


def console_api(method, path, body=None):
    base = status()["api_base"]
    try:
        token = open(PANEL_TOKEN).read().strip()
    except OSError:
        raise Refused("Unlock the case file first")
    req = urllib.request.Request(base + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"X-Panel-Token": token, "Content-Type": "application/json"})
    # 127.0.0.1 is this machine; its certificate names its network addresses.
    ctx = ssl._create_unverified_context() if base.startswith("https") else None
    try:
        with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            detail = json.load(e).get("detail")
        except ValueError:
            detail = None
        raise Refused(detail if isinstance(detail, str) else f"The console said {e.code}")
    except (urllib.error.URLError, OSError):
        raise Refused("The console is not answering")


def op_upload_people(req):
    return console_api("GET", "/api/panel/upload/people")


def op_upload_code(req):
    def num(v):
        return int(v) if v is not None else None
    body = {"device_id": num(req.get("device_id")), "user_id": num(req.get("user_id")),
            "base_url": status().get("url") or None}
    return console_api("POST", "/api/panel/upload/code", body)


# ---- USB sticks --------------------------------------------------------------
# There is no desktop to mount sticks, so the helper does: every partition on
# a removable or USB disk, under /media/humint/<name>, owned by the app's
# account where the filesystem allows it, never executable. Files come in
# from them (attachments, documents) and go out to them (PDFs, exports).

USB_BASE = os.environ.get("HUMINT_USB_BASE", "/media/humint")
USB_FAKE = os.environ.get("HUMINT_USB_FAKE")       # tests: folders standing in for sticks


def _usb_partitions():
    try:
        raw = subprocess.run(["lsblk", "-J", "-b", "-o", "NAME,PATH,RM,HOTPLUG,TRAN,TYPE,FSTYPE,LABEL,SIZE,MOUNTPOINT"],
                             capture_output=True, text=True, timeout=10).stdout
        devs = json.loads(raw).get("blockdevices", [])
    except (OSError, ValueError, subprocess.SubprocessError):
        return []
    out = []
    for disk in devs:
        removable = disk.get("tran") == "usb" or str(disk.get("rm")) in ("1", "True", "true") \
            or str(disk.get("hotplug")) in ("1", "True", "true")
        if not removable or disk.get("type") != "disk":
            continue
        for p in (disk.get("children") or [disk]):
            if p.get("fstype") in ("vfat", "exfat", "ntfs", "ext4", "ext3", "ext2"):
                out.append(p)
    return out


def op_usb_list(req):
    if USB_FAKE:
        return {"sticks": [{"name": n, "label": n, "path": os.path.join(USB_FAKE, n), "writable": True}
                           for n in sorted(os.listdir(USB_FAKE))]}
    sticks = []
    try:
        gid = grp.getgrnam(UI_GROUP).gr_gid
        uid = pwd.getpwnam(UI_GROUP).pw_uid
    except KeyError:
        uid = gid = 0
    for p in _usb_partitions():
        name = "".join(c if c.isalnum() or c in "-_" else "_" for c in (p.get("label") or p["name"]))
        where = os.path.join(USB_BASE, name)
        if not os.path.ismount(where):
            os.makedirs(where, exist_ok=True)
            opts = "nosuid,nodev,noexec"
            if p["fstype"] in ("vfat", "exfat", "ntfs"):
                opts += f",uid={uid},gid={gid},umask=007"
            fstype = "ntfs3" if p["fstype"] == "ntfs" else p["fstype"]
            if subprocess.run(["mount", "-t", fstype, "-o", opts, p["path"], where],
                              capture_output=True, timeout=30).returncode != 0:
                continue
            if p["fstype"].startswith("ext"):
                # A Linux-formatted stick: let the app write a folder of its own.
                d = os.path.join(where, "HUMINT")
                try:
                    os.makedirs(d, exist_ok=True)
                    os.chown(d, uid, gid)
                except OSError:
                    pass
        sticks.append({"name": name, "label": p.get("label") or p["name"], "path": where,
                       "size": int(p.get("size") or 0), "fstype": p["fstype"],
                       "writable": os.access(where, os.W_OK)})
    return {"sticks": sticks}


def op_usb_eject(req):
    if USB_FAKE:
        return {"ejected": True}
    subprocess.run(["sync"], timeout=120)
    left = []
    if os.path.isdir(USB_BASE):
        for name in os.listdir(USB_BASE):
            where = os.path.join(USB_BASE, name)
            if os.path.ismount(where):
                if subprocess.run(["umount", where], capture_output=True, timeout=60).returncode != 0:
                    left.append(name)
                    continue
            try:
                os.rmdir(where)
            except OSError:
                pass
    if left:
        raise Refused("Still in use: " + ", ".join(left) + " — close what is open on it and try again")
    return {"ejected": True}


OPS = {
    "usb_list": op_usb_list,
    "usb_eject": op_usb_eject,
    "status": lambda req: status(),
    "unlock": op_unlock,
    "setup_pin": op_setup_pin,
    "setup_pin_cancel": op_setup_pin_cancel,
    "ctl": op_ctl,
    "store_grow": op_store_grow,
    "display_set": op_display_set,
    "screen_power": op_screen_power,
    "audio_set": op_audio_set,
    "screen_settings": op_screen_settings,
    "wifi_scan": op_wifi_scan,
    "wifi_join": op_wifi_join,
    "dismiss_secret": op_dismiss_secret,
    "upload_people": op_upload_people,
    "upload_code": op_upload_code,
}


# ---- the socket ---------------------------------------------------------------

def allowed_uids() -> set:
    uids = {0}
    try:
        g = grp.getgrnam(UI_GROUP)
        uids.update(pwd.getpwnam(m).pw_uid for m in g.gr_mem)
        uids.update(p.pw_uid for p in pwd.getpwall() if p.pw_gid == g.gr_gid)
    except KeyError:
        pass
    extra = os.environ.get("HUMINT_BOX_ALLOW_UID")
    if extra:
        uids.add(int(extra))
    return uids


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        creds = self.request.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        _pid, uid, _gid = struct.unpack("3i", creds)
        if uid not in allowed_uids():
            self.reply({"ok": False, "error": "not allowed"})
            return
        for line in self.rfile:
            try:
                req = json.loads(line)
                op = OPS.get(req.get("op"))
                if op is None:
                    raise Refused(f"unknown request {req.get('op')!r}")
                self.reply({"ok": True, "id": req.get("id"), "data": op(req)})
            except Refused as e:
                self.reply({"ok": False, "id": req.get("id") if isinstance(req, dict) else None,
                            "error": str(e)})
            except (ValueError, AttributeError):
                self.reply({"ok": False, "error": "bad request"})
            except Exception as e:  # never let one request take the service down
                print(f"humint-boxd: {e!r}", file=sys.stderr, flush=True)
                self.reply({"ok": False, "error": "internal error"})

    def reply(self, obj):
        try:
            self.wfile.write((json.dumps(obj) + "\n").encode())
            self.wfile.flush()
        except OSError:
            pass


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def main() -> int:
    os.makedirs(os.path.dirname(SOCK), exist_ok=True)
    try:
        os.unlink(SOCK)
    except OSError:
        pass
    old = os.umask(0o117)
    srv = Server(SOCK, Handler)
    os.umask(old)
    try:
        os.chown(SOCK, 0, grp.getgrnam(UI_GROUP).gr_gid)
    except (KeyError, PermissionError):
        pass
    os.chmod(SOCK, 0o660)
    print(f"humint-boxd: listening on {SOCK}", flush=True)
    srv.serve_forever(poll_interval=5)   # only for shutdown checks; requests wake it at once
    return 0


if __name__ == "__main__":
    sys.exit(main())
