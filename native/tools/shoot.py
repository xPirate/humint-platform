"""Render the native app off-screen and save screenshots — for development
and the tests. Drives a real humint-boxd against a fake machine (files under
a temporary root) and, optionally, a real console.

    python native/tools/shoot.py OUTDIR [scenario ...]
"""
import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
NATIVE = os.path.dirname(HERE)
REPO = os.path.dirname(NATIVE)
BOXD = os.path.join(REPO, "deploy/x86/files/opt/humint/bin/humint-boxd.py")


class FakeMachine:
    """A temporary root that humint-boxd reads as the machine's state, and
    fake humint-ctl / humint-unlock-try that record what they were asked."""

    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="humint-fake-")
        for d in ("run/humint", "var/lib/humint", "srv/humint-data", "opt/humint-platform"):
            os.makedirs(os.path.join(self.root, d), exist_ok=True)
        self.log = os.path.join(self.root, "calls.log")
        # A password handed over on stdin (net client) is recorded too.
        self.ctl = self._script("ctl", 'echo "ctl $*" >> "%s"; '
                                       'if [ "${HUMINT_PSK_STDIN:-}" = 1 ]; then IFS= read -r p; echo "psk $p" >> "%s"; fi; '
                                       'if [ "${HUMINT_PIN_STDIN:-}" = 1 ]; then IFS= read -r p; echo "pin $p" >> "%s"; '
                                       '  [ "$p" = 1234 ] || { echo "humint: ERROR: Wrong PIN" >&2; exit 1; }; fi; '
                                       'case "$*" in *"net client Bad"*) echo "humint: ERROR: nope" >&2; exit 1;; esac; exit 0'
                                % (self.log, self.log, self.log))
        # nmcli, for the Wi-Fi scan: a Wi-Fi device and three networks.
        self.nmcli = self._script("nmcli", r"""case "$*" in
  *"DEVICE,TYPE device"*) printf 'eth0:ethernet\nwlan0:wifi\n';;
  "radio wifi") echo enabled;;
  *"wifi list"*) printf ' :Jordan\x27s iPhone:71:WPA2\n :Cafe\\:Guest:40:--\n :Jordan\x27s iPhone:30:WPA2\n :::WPA2\n';;
esac""")
        self.try_ = self._script("try", 'read -r pin; echo "try $pin" >> "%s"; '
                                        '[ "$pin" = 1234 ] && { touch "%s/run/humint-data.ready"; exit 0; }; '
                                        'n=$(cat "%s/run/humint/unlock-tries" 2>/dev/null || echo 0); '
                                        'echo $((n+1)) > "%s/run/humint/unlock-tries"; exit 1'
                                 % (self.log, self.root, self.root, self.root))
        # A laptop's backlight and sound card.
        bl = os.path.join(self.root, "sys/class/backlight/intel_backlight")
        os.makedirs(bl, exist_ok=True)
        for name, val in (("type", "raw"), ("max_brightness", "1000"), ("brightness", "600"), ("bl_power", "0")):
            open(os.path.join(bl, name), "w").write(val + "\n")
        os.makedirs(os.path.join(self.root, "proc/asound"), exist_ok=True)
        open(os.path.join(self.root, "proc/asound/cards"), "w").write(
            " 0 [PCH            ]: HDA-Intel - HDA Intel PCH\n                      HDA Intel PCH at 0xf7f10000 irq 32\n")
        self.mixer_state = os.path.join(self.root, "mixer")
        open(self.mixer_state, "w").write("40 on\n")
        self.amixer = self._script("amixer", r"""st=%s; read -r vol sw < "$st"
case "$*" in
  *scontrols*) printf "Simple mixer control 'Master',0\nSimple mixer control 'PCM',0\n";;
  *sget*) printf "Simple mixer control 'Master',0\n  Front Left: Playback 26214 [%%s%%%%] [%%s]\n  Front Right: Playback 26214 [%%s%%%%] [%%s]\n" "$vol" "$sw" "$vol" "$sw";;
  *sset*) for a in "$@"; do case "$a" in *%%) vol=${a%%\%%};; mute) sw=off;; unmute) sw=on;; esac; done
          echo "$vol $sw" > "$st";;
esac""" % self.mixer_state)
        self.alsactl = self._script("alsactl", 'echo "alsactl $*" >> "%s"' % self.log)
        self.sock = os.path.join(self.root, "box.sock")
        # Folders standing in for USB sticks.
        self.usb = os.path.join(self.root, "usb")
        os.makedirs(os.path.join(self.usb, "KINGSTON"), exist_ok=True)
        self.write("var/lib/humint/env", "HOSTNAME=humint\nINSTANCE_NAME=\"Field Kit 1\"\nNET_MODE=hotspot\n"
                   "AP_SSID=humint-field\nAP_PSK=abcd-efgh-jkmn\nTLS=on\n")
        self.write("opt/humint-platform/BUILD.json", json.dumps({"build": 412, "commit": "3a746e4c1d"}))
        self.write("var/lib/humint/ca.fingerprint", "AB:CD:EF:01:23:45:67:89:AB:CD:EF:01:23:45:67:89:AB:CD:EF:01:23:45:67:89:AB:CD:EF:01:23:45:67:89")
        self.write("run/humint/battery.json", json.dumps({"present": True, "percent": 64, "ac_present": True,
                                                          "charging": True, "on_battery": False}))

    def _script(self, name, body):
        p = os.path.join(self.root, name)
        open(p, "w").write("#!/bin/bash\n" + body + "\n")
        os.chmod(p, 0o755)
        return p

    def path(self, rel):
        return os.path.join(self.root, rel)

    def write(self, rel, text):
        open(self.path(rel), "w").write(text)

    def remove(self, rel):
        try:
            os.unlink(self.path(rel))
        except OSError:
            pass

    def start(self, console_url=""):
        env = dict(os.environ, HUMINT_TEST_ROOT=self.root, HUMINT_BOX_SOCK=self.sock,
                   HUMINT_CTL=self.ctl, HUMINT_NMCLI=self.nmcli, HUMINT_AMIXER=self.amixer, HUMINT_ALSACTL=self.alsactl, HUMINT_TRY=self.try_, HUMINT_BOX_ALLOW_UID=str(os.getuid()),
                   HUMINT_CONSOLE_URL=console_url, HUMINT_USB_FAKE=self.usb, PYTHONUNBUFFERED="1")
        self.proc = subprocess.Popen([sys.executable, BOXD], env=env,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        for _ in range(50):
            if os.path.exists(self.sock):
                break
            time.sleep(0.1)
        return self

    def stop(self):
        self.proc.terminate()

    def unlock(self):
        """Straight to an open case file (first boot done, PIN given)."""
        self.write("srv/humint.img", "x")
        self.write("var/lib/humint/firstboot.done", "")
        self.write("run/humint-data.ready", "")

    def calls(self):
        try:
            return open(self.log).read().splitlines()
        except OSError:
            return []


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "."
    os.makedirs(out, exist_ok=True)
    sys.path.insert(0, HERE)
    from appdriver import AppDriver
    m = FakeMachine().start()
    d = AppDriver(m.sock)
    # first boot, setting up
    m.write("run/humint/message.json", json.dumps({"lines": ["Encrypting store", "please wait"], "time": time.time()}))
    d.until(lambda: d.has_text("Encrypting store"), what="the setup message")
    d.shot(f"{out}/01-message.png")
    # first boot asks for the PIN
    m.write("run/humint/pin-setup", "new\n")
    d.until(lambda: d.has_text("Choose the unlock PIN"), what="set PIN")
    d.shot(f"{out}/02-setpin.png")
    m.remove("run/humint/pin-setup")
    # later boots: locked
    m.write("srv/humint.img", "x"); m.write("var/lib/humint/firstboot.done", "")
    d.until(lambda: d.has_text("Unlock the case file"), what="unlock")
    for k in "99":
        d.tap(k)
    d.tap("Unlock")
    d.until(lambda: d.has_text("Wrong PIN"), what="wrong PIN")
    d.shot(f"{out}/03-unlock-wrong.png")
    for k in "1234":
        d.tap(k)
    d.tap("Unlock")
    d.until(lambda: d.has_text("Write these down") or d.has_text("Waiting for the console") or d.has_text("Sign in"),
            what="unlocked")
    d.shot(f"{out}/04-after-unlock.png")
    print("calls:", m.calls())
    m.stop()


if __name__ == "__main__":
    main()
