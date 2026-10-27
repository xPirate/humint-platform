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
            out[k.strip()] = v.strip().strip('"').strip("'")
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
    d["psk"] = env.get("AP_PSK") if d["net_mode"] == "hotspot" else env.get("CLIENT_PSK")
    d["hidden"] = env.get("AP_HIDDEN", "false") == "true"
    d["clients"] = slow["clients"]
    d["services"] = slow["services"]
    d["battery"] = read_json(BATTERY, {}) or {}
    d["clock"] = read_json(CLOCK, {}) or {}
    d["login_secret"] = read_json(LOGIN_SECRET, None)
    # The last update's progress or outcome (bundle or system), for the screen.
    d["update"] = read_json(UPDATE_STATUS, None)
    d["duress_set"] = os.path.exists(DURESS)
    try:
        u = shutil.disk_usage(DATA if d["unlocked"] else "/")
        d["disk"] = [round(u.free / 1e9, 1), round(u.total / 1e9, 1)]
    except OSError:
        d["disk"] = None
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
