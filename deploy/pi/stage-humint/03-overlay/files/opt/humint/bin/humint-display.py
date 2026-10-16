#!/usr/bin/env python3
"""What screen is attached, and what the appliance should show on it.

  SCREEN=auto       (default) look, and pick the richest thing that is there
  SCREEN=elecrow5   the 5" 800x480 HDMI screen with resistive touch on the
                    GPIO header (Elecrow, and the Waveshare 5" (B) and other
                    boards wired the same way: XPT2046 on SPI CE1, pen IRQ on
                    GPIO 25)
  SCREEN=hdmi       any HDMI or DSI screen (official Pi Touch Display, USB-touch
                    HDMI screens) — touch is used if the kernel sees one
  SCREEN=oled       only the 0.96" SSD1306 OLED
  SCREEN=none       nothing; the PIN is typed blind

What each gets:
  OLED (128x64)     status pages and the PIN prompt, as before
  touch panel       the control panel (humint-panel.py): on-screen PIN pad,
                    dashboard, QR codes to join and to trust the console,
                    menus for network, lock and power, touch calibration
  panel, no touch   the same panel, driven by an attached keyboard
Both an OLED and a panel may be fitted; both are used.

How "auto" finds things, and its limits:
  - an HDMI/DSI screen is seen through DRM once the Pi detects it. The cheap
    5" HDMI screens often report no EDID, so the Pi may not notice them at
    all; that is what SCREEN=elecrow5 is for.
  - touch is any input device reporting absolute X/Y. The Elecrow's touch
    controller cannot be probed until its driver is loaded, so auto loads
    that driver only when an HDMI screen reports itself as 800x480 — the
    signature of this class of screen — and reboots once to bring it up.
  - an OLED is a device answering at I2C 0x3C/0x3D.

  humint-display.py detect [--explain]   write /run/humint/display.json
  humint-display.py boot                  detect, and set the Elecrow driver up
                                          (rebooting once) when needed
Standard library only, so it runs before anything else is up.
"""
import fcntl
import glob
import hashlib
import json
import os
import re
import subprocess
import sys

CONF_FILES = ("/var/lib/humint/env", "/boot/firmware/humint-appliance.conf")
OUT_DIR = "/run/humint"
OUT = os.path.join(OUT_DIR, "display.json")
STATE = "/var/lib/humint"
BOOT = "/boot/firmware" if os.path.isdir("/boot/firmware") else "/boot"
CONFIG_TXT = os.path.join(BOOT, "config.txt")
CMDLINE_TXT = os.path.join(BOOT, "cmdline.txt")

BEGIN, END = "# >>> humint screen (managed by humint-display.py)", "# <<< humint screen"
ELECROW_BLOCK = """dtparam=spi=on
# Resistive touch: XPT2046 (ADS7846-compatible) on SPI CE1, pen IRQ on GPIO 25.
dtoverlay=ads7846,cs=1,penirq=25,penirq_pull=2,speed=50000,keep_vref_on=0,swapxy=0,pmax=255,xohms=150,xmin=200,xmax=3900,ymin=200,ymax=3900
# Drive the HDMI port even when the screen sends no EDID.
hdmi_force_hotplug=1"""
ELECROW_VIDEO = "video=HDMI-A-1:800x480M@60D"

I2C_SLAVE = 0x0703


def setting() -> str:
    for path in CONF_FILES:
        try:
            for line in open(path):
                if line.startswith("SCREEN="):
                    return line.split("=", 1)[1].strip().strip('"').lower() or "auto"
        except OSError:
            continue
    return "auto"


def panels() -> list[dict]:
    found = []
    for status in sorted(glob.glob("/sys/class/drm/card*-*/status")):
        conn = os.path.basename(os.path.dirname(status)).split("-", 1)[1]
        if not conn.startswith(("HDMI", "DSI", "DPI")):
            continue
        try:
            if open(status).read().strip() != "connected":
                continue
            modes = open(os.path.join(os.path.dirname(status), "modes")).read().split()
        except OSError:
            continue
        w, h = (0, 0)
        if modes:
            m = re.match(r"(\d+)x(\d+)", modes[0])
            if m:
                w, h = int(m.group(1)), int(m.group(2))
        found.append({"connector": conn, "width": w, "height": h, "modes": modes[:4]})
    return found


def _abs_bits(dev_dir: str) -> int:
    try:
        words = open(os.path.join(dev_dir, "capabilities", "abs")).read().split()
    except OSError:
        return 0
    value = 0
    for w in words:                       # most significant word first
        value = (value << 64) | int(w, 16)
    return value


def touch_devices() -> list[dict]:
    out = []
    for ev in sorted(glob.glob("/sys/class/input/event*")):
        dev = os.path.join(ev, "device")
        bits = _abs_bits(dev)
        has_xy = bool(bits & 0b11)                      # ABS_X, ABS_Y
        has_mt = bool(bits & (1 << 0x35))               # ABS_MT_POSITION_X
        if not (has_xy or has_mt):
            continue
        try:
            name = open(os.path.join(dev, "name")).read().strip()
            rel = open(os.path.join(dev, "capabilities", "rel")).read().strip()
        except OSError:
            name, rel = "?", "0"
        if rel not in ("0", ""):                       # a mouse or a tablet pen with wheels
            continue
        if re.search(r"joystick|gamepad|accel", name, re.I):
            continue
        out.append({"event": "/dev/input/" + os.path.basename(ev), "name": name})
    return out


def oled_present(bus: int = 1) -> int | None:
    path = f"/dev/i2c-{bus}"
    if not os.path.exists(path):
        return None
    for addr in (0x3C, 0x3D):
        try:
            fd = os.open(path, os.O_RDWR)
            try:
                fcntl.ioctl(fd, I2C_SLAVE, addr)
                os.read(fd, 1)
                return addr
            finally:
                os.close(fd)
        except OSError:
            continue
    return None


def elecrow_configured() -> bool:
    try:
        return BEGIN in open(CONFIG_TXT).read()
    except OSError:
        return False


def detect() -> dict:
    want = setting()
    found = panels()
    touch = touch_devices()
    oled = None if want in ("none",) else oled_present()
    panel = found[0] if found else None
    if want == "elecrow5" and panel is None and elecrow_configured():
        # Forced on and driven, even if the screen never said hello.
        panel = {"connector": "HDMI-A-1", "width": 800, "height": 480, "modes": []}
    if want in ("oled", "none"):
        panel = None
    if want == "none":
        oled = None
    if panel is not None:
        panel["touch"] = touch[0] if touch else None
        if (panel["width"], panel["height"]) == (800, 480) and panel["connector"].startswith("HDMI"):
            panel["profile"] = "elecrow5"
        else:
            panel["profile"] = "dsi" if panel["connector"].startswith("DSI") else "hdmi"
    kinds = [k for k, v in (("panel", panel), ("oled", oled)) if v]
    return {"setting": want, "panel": panel, "oled": oled is not None,
            "oled_addr": oled, "mode": "+".join(kinds) or "none",
            "elecrow_driver": elecrow_configured()}


def write(state: dict) -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    tmp = OUT + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(state, fh, indent=1)
    os.chmod(tmp, 0o644)
    os.replace(tmp, OUT)


def needs_elecrow(state: dict) -> bool:
    if elecrow_configured():
        return False
    if state["setting"] == "elecrow5":
        return True
    p = state["panel"]
    # auto: an untouchable 800x480 HDMI screen is this class of screen.
    return (state["setting"] == "auto" and p is not None and p["profile"] == "elecrow5"
            and p["connector"].startswith("HDMI") and not p.get("touch"))


def install_elecrow() -> None:
    text = open(CONFIG_TXT).read() if os.path.exists(CONFIG_TXT) else ""
    if BEGIN not in text:
        text = text.rstrip("\n") + f"\n\n{BEGIN}\n[all]\n{ELECROW_BLOCK}\n{END}\n"
        with open(CONFIG_TXT, "w") as fh:
            fh.write(text)
    try:
        cmd = open(CMDLINE_TXT).read().strip()
        if "video=HDMI-A-1:" not in cmd:
            with open(CMDLINE_TXT, "w") as fh:
                fh.write(cmd + " " + ELECROW_VIDEO + "\n")
    except OSError:
        pass


def remove_elecrow() -> None:
    try:
        text = open(CONFIG_TXT).read()
    except OSError:
        return
    if BEGIN in text:
        text = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n?", "", text, flags=re.S)
        open(CONFIG_TXT, "w").write(text.rstrip("\n") + "\n")
    try:
        cmd = open(CMDLINE_TXT).read().strip()
        if ELECROW_VIDEO in cmd:
            open(CMDLINE_TXT, "w").write(cmd.replace(" " + ELECROW_VIDEO, "").replace(ELECROW_VIDEO, "") + "\n")
    except OSError:
        pass


def boot() -> int:
    state = detect()
    write(state)
    if state["setting"] in ("oled", "none", "hdmi") and elecrow_configured():
        # The operator changed their mind; take the driver back out.
        remove_elecrow()
        state["elecrow_driver"] = False
        write(state)
        return 0
    if needs_elecrow(state):
        # Reboot at most once per configuration, so a screen that never
        # comes up cannot put the box in a reboot loop.
        key = hashlib.sha256(json.dumps([state["setting"], state["panel"]], sort_keys=True,
                                        default=str).encode()).hexdigest()[:16]
        flag = os.path.join(STATE, f"display-reboot-{key}")
        if os.path.exists(flag):
            print("humint-display: Elecrow driver set up already once for this; not rebooting again")
            return 0
        install_elecrow()
        os.makedirs(STATE, exist_ok=True)
        open(flag, "w").close()
        print("humint-display: set up the 5\" touch screen driver; rebooting once to load it", flush=True)
        subprocess.run(["/opt/humint/venv/bin/python3", "/opt/humint/bin/oled_show.py",
                        "Screen found", "setting up touch", "rebooting once"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["systemctl", "reboot"])
    return 0


def explain(state: dict) -> None:
    print(f"Setting  : SCREEN={state['setting']}")
    p = state["panel"]
    if p:
        print(f"Panel    : {p['connector']} {p['width']}x{p['height']} ({p['profile']})")
        print(f"Touch    : {p['touch']['name'] + ' at ' + p['touch']['event'] if p.get('touch') else 'none — keyboard drives the panel'}")
    else:
        print("Panel    : none detected")
    print(f"OLED     : {'SSD1306 at 0x%02X' % state['oled_addr'] if state['oled'] else 'none'}")
    print(f"5\" driver: {'installed in config.txt' if state['elecrow_driver'] else 'not installed'}")
    shows = {"panel+oled": "touch control panel and OLED status pages",
             "panel": "touch control panel", "oled": "OLED status pages and PIN prompt",
             "none": "nothing — the PIN is typed blind on the keyboard"}[state["mode"]]
    print(f"Shows    : {shows}")


def main(argv) -> int:
    cmd = argv[1] if len(argv) > 1 else "detect"
    if cmd == "boot":
        return boot()
    state = detect()
    write(state)
    if "--explain" in argv:
        explain(state)
    else:
        print(json.dumps(state))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
