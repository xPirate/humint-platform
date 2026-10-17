#!/usr/bin/env python3
"""The field server's little screen.

Runs after the console is up and cycles through a few status pages on the
0.96" SSD1306 OLED: how to reach it on the network, whether its services are
running, and how the box itself is doing. If no screen is attached it logs
once and exits cleanly, so a box with no HAT simply has no display rather
than a crash-looping service.

Optional: one push-button wired to a GPIO pin (BCM numbering, set
STATUS_BUTTON_GPIO) advances the page on a tap and shuts the box down safely
on a long press. Without a button the pages auto-rotate.
"""
import os
import shutil
import socket
import subprocess
import sys
import time

WIDTH, HEIGHT = 128, 64
ADDR = int(os.environ.get("HUMINT_OLED_ADDR", "0x3C"), 16)
PORT = int(os.environ.get("HUMINT_OLED_I2C", "1"))
DATA = "/srv/humint-data"


def cfg():
    out = {}
    try:
        for line in open("/var/lib/humint/env"):
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                out[k] = v.strip().strip('"')
    except OSError:
        pass
    return out


CONF = cfg()


def ip_address():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.42.0.1", 1))  # never sends a packet; just picks the iface
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        try:
            return subprocess.check_output(["hostname", "-I"], text=True).split()[0]
        except Exception:
            return "?"


def url():
    ip = ip_address()
    if CONF.get("TLS", "on") == "on":
        return f"https://{ip}"
    port = CONF.get("API_PORT", "80")
    return f"http://{ip}" + ("" if port == "80" else f":{port}")


def battery():
    try:
        import json
        return json.load(open("/run/humint/battery.json"))
    except Exception:
        return None


def fingerprint_short():
    try:
        fp = open("/var/lib/humint/ca.fingerprint").read().strip().split(":")
        return ":".join(fp[:4]), ":".join(fp[4:8])
    except OSError:
        return None


def case_state():
    try:
        return "open" if os.path.ismount(DATA) else "LOCKED"
    except Exception:
        return "?"


SERVICES = {"db": "postgresql@16-main", "api": "humint-api", "worker": "humint-worker"}


def services():
    """Which of the console's systemd services are running."""
    state = {}
    for key, unit in SERVICES.items():
        try:
            r = subprocess.run(["systemctl", "is-active", "--quiet", unit],
                               timeout=5, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
            state[key] = r.returncode == 0
        except Exception:
            state[key] = False
    return state


def cpu_temp():
    try:
        return int(open("/sys/class/thermal/thermal_zone0/temp").read()) / 1000.0
    except Exception:
        return None


def disk_free():
    try:
        u = shutil.disk_usage(DATA if os.path.ismount(DATA) else "/")
        return u.free / 1e9, u.total / 1e9
    except Exception:
        return None, None


def uptime():
    try:
        s = float(open("/proc/uptime").read().split()[0])
        h, m = int(s // 3600), int((s % 3600) // 60)
        return f"{h}h{m:02d}m"
    except Exception:
        return "?"


def pages():
    net = ["Network"]
    host = CONF.get("HOSTNAME", "humint")
    net.append(url())
    net.append(f"{host}.local")
    if CONF.get("NET_MODE") == "hotspot":
        net.append(f"SSID {CONF.get('AP_SSID', '?')}")
    elif CONF.get("NET_MODE") == "client":
        net.append(f"on {CONF.get('CLIENT_SSID', 'wifi')}")
    else:
        net.append("wired")

    svc_map = services()
    svc = ["Services", f"Case file: {case_state()}"]
    svc.append("DB  " + ("up" if svc_map.get("db") else "DOWN"))
    svc.append("API " + ("up" if svc_map.get("api") else "DOWN") +
               "  Wkr " + ("up" if svc_map.get("worker") else "DOWN"))

    free, total = disk_free()
    t = cpu_temp()
    sysp = ["System"]
    b = battery()
    if b and b.get("present"):
        # "AC" while plugged in; the time left while on battery.
        tail = " AC" if b.get("ac_present") else (
            f" {b['minutes_left'] // 60}h{b['minutes_left'] % 60:02d}" if b.get("minutes_left") is not None else "")
        sysp.append(f"Batt {b['percent']:.0f}%{tail}")
    elif b and b.get("mains"):
        sysp.append("Power: AC, no batt")
    if free is not None:
        sysp.append(f"Disk {free:.1f}/{total:.0f} GB")
    if t is not None:
        sysp.append(f"Temp {t:.0f} C")
    sysp.append(f"Up {uptime()}")
    pages_out = [net, svc, sysp]
    fp = fingerprint_short() if CONF.get("TLS", "on") == "on" else None
    if fp:
        # Enough of the CA fingerprint to check a phone downloaded the right
        # certificate from http://<box>/trust.
        pages_out.append(["Trust", f"{CONF.get('HOSTNAME', 'humint')}.local/trust", fp[0], fp[1]])
    return pages_out


def open_device():
    if CONF.get("OLED", "auto").lower() == "none":
        return None, None
    try:
        from luma.core.interface.serial import i2c
        from luma.oled.device import ssd1306
        from PIL import ImageFont
    except Exception:
        print("humint-status: display libraries not installed", file=sys.stderr)
        return None, None
    try:
        dev = ssd1306(i2c(port=PORT, address=ADDR), width=WIDTH, height=HEIGHT)
    except Exception as e:
        print(f"humint-status: no OLED found ({e})", file=sys.stderr)
        return None, None
    try:
        fonts = (
            ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 13),
            ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 11),
        )
    except Exception:
        fonts = (ImageFont.load_default(), ImageFont.load_default())
    return dev, fonts


def draw(dev, fonts, lines):
    from luma.core.render import canvas
    big, small = fonts
    with canvas(dev) as d:
        y = 0
        for i, line in enumerate(lines[:5]):
            d.text((0, y), str(line)[:21], font=(big if i == 0 else small), fill=255)
            y += 15 if i == 0 else 12


def make_button():
    pin = CONF.get("STATUS_BUTTON_GPIO")
    if not pin:
        return None
    try:
        from gpiozero import Button
        return Button(int(pin), hold_time=2)
    except Exception as e:
        print(f"humint-status: button disabled ({e})", file=sys.stderr)
        return None


def main():
    dev, fonts = open_device()
    if dev is None:
        # No screen: nothing to show. Exit 0 so systemd does not respawn us.
        return 0
    rotate = int(CONF.get("STATUS_ROTATE_SECONDS", "6") or 6)
    button = make_button()
    state = {"page": 0, "advance": False, "shutdown": False}
    if button is not None:
        button.when_released = lambda: state.__setitem__("advance", True)
        button.when_held = lambda: state.__setitem__("shutdown", True)

    while True:
        pgs = pages()
        state["page"] %= len(pgs)
        draw(dev, fonts, pgs[state["page"]])
        waited = 0.0
        while waited < rotate:
            if state["shutdown"]:
                draw(dev, fonts, ["Shutting down", "safe to unplug", "after it clears"])
                subprocess.run(["systemctl", "poweroff"])
                return 0
            if state["advance"]:
                state["advance"] = False
                state["page"] += 1
                break
            time.sleep(0.2)
            waited += 0.2
        else:
            state["page"] += 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
