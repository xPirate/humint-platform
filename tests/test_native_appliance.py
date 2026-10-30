"""The x86 native app's machine screens, end to end: the real app (off-screen),
the real machine helper (humint-boxd, against a fake machine's files) and a
real console — first boot's PIN, unlock, the first admin account, the Box
panel and a phone upload code."""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import ROOT, Console, check, finish  # noqa: E402

sys.path.insert(0, os.path.join(ROOT, "native", "tools"))
from shoot import FakeMachine  # noqa: E402
from appdriver import AppDriver  # noqa: E402

SHOTS = os.environ.get("SHOTS")


def shot(d, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        d.shot(os.path.join(SHOTS, name + ".png"))


m = FakeMachine()
token = "panel-token-for-tests"
m.write("srv/humint-data/panel.token", token + "\n")
tf = os.path.join(m.root, "console-panel.token")
open(tf, "w").write(token + "\n")
c = Console("native_app", env={"PANEL_TOKEN_FILE": tf}).start()
m.start(console_url=c.url)
d = AppDriver(m.sock, console_url=c.url)

# ---- first boot -------------------------------------------------------------------
m.write("run/humint/message.json", json.dumps({"lines": ["Making store", "12G"], "time": time.time()}))
d.until(lambda: d.has_text("Making store"), what="setup progress")
check(d.has_text("First-time setup"), "first boot shows what it is doing, and that it is first-time setup")

# First boot asks for the PIN: the app takes it twice and hands it over.
os.mkfifo(m.path("run/humint/pin-setup.fifo"), 0o600)
fifo = os.open(m.path("run/humint/pin-setup.fifo"), os.O_RDWR | os.O_NONBLOCK)
m.write("run/humint/pin-setup", "new\n")
d.until(lambda: d.has_text("Choose the unlock PIN"), what="set-PIN screen")
shot(d, "01-setpin")
for k in "12":
    d.tap(k)
d.tap("Next")
check(d.has_text("Use at least 4 characters"), "a PIN under four characters is refused before it goes anywhere")
for k in "2468":
    d.tap(k)
d.tap("Next")
d.until(lambda: d.has_text("Type it again"), what="confirm")
for k in "2469":
    d.tap(k)
d.tap("Set PIN")
check(d.has_text("didn't match"), "a mismatch starts again")
for k in "2468":
    d.tap(k)
d.tap("Next")
for k in "2468":
    d.tap(k)
d.tap("Set PIN")
time.sleep(0.3)
d.pump(0.3)
got = os.read(fifo, 100).decode()
check(got == "2468\n", f"the PIN goes to first boot through its pipe, once ({got!r})")
m.remove("run/humint/pin-setup")

# ---- later boots: unlock ----------------------------------------------------------
m.write("srv/humint.img", "x")
m.write("var/lib/humint/firstboot.done", "")
d.until(lambda: d.has_text("Unlock the case file"), what="unlock")
for k in "5555":
    d.tap(k)
d.tap("Unlock")
d.until(lambda: d.has_text("Wrong PIN"), what="wrong PIN")
check(d.has_text("4 tries left"), "a wrong PIN says how many tries are left")
for k in "1234":
    d.tap(k)
d.tap("Unlock")
d.until(lambda: d.has_text("A new case file"), timeout=20, what="sign-in (bootstrap)")
check(m.calls()[:2] == ["try 5555", "try 1234"], "both tries went through humint-unlock-try")

# ---- the first admin account ----------------------------------------------------------
shot(d, "02-bootstrap")
check(d.field("Username").property("activeFocus"), "typing goes straight into the username (a laptop with no mouse)")
d.type_into("Username", "ana")
d.type_into("Password", "correct horse battery")
d.type_into("Password again (at least 10 characters)", "correct horse battery")
d.tap("Create admin account")
d.until(lambda: d.button("Box") is not None and d.has_text("Dashboard"), timeout=15, what="signed in")
check(c.sql("SELECT username, role FROM users") == [("ana", "admin")], "it creates the first admin account")
shot(d, "03-shell")

# ---- first boot's secrets: shown until confirmed (Enter, on a laptop) -----------------
m.write("run/humint/login-password.json", json.dumps({"user": "humint", "password": "abcd-efgh-ijkl", "time": time.time()}))
d.until(lambda: d.has_text("Write these down"), what="the secrets screen")
check(d.has_text("abcd-efgh-ijkl") and not d.has_text("Wi-Fi password"),
      "the new machine login is shown, with no Wi-Fi password when there is no hotspot one")
d.key("Return")
d.until(lambda: not os.path.exists(m.path("run/humint/login-password.json")), what="dismissed")
d.until(lambda: d.has_text("Dashboard"), what="back to the app")
check(True, "Enter confirms it is written down, and the app comes back")

# ---- the Box panel ----------------------------------------------------------------------
d.tap("Box")
d.until(lambda: d.has_text("Team address"), what="box status")
shot(d, "04-box-status")
d.tap("Join")
d.until(lambda: d.has_text("Join the field Wi-Fi"), what="join")
shot(d, "05-box-join")
d.tap("Trust")
d.until(lambda: d.has_text("Check its fingerprint"), what="trust")
d.tap("Actions")
d.until(lambda: d.button("Lock case file") is not None, what="actions")
shot(d, "06-box-actions")
d.tap("Restart console")
d.until(lambda: "ctl restart" in m.calls(), what="restart")
check(True, "Restart console runs humint-ctl restart")
d.tap("Wipe case file")
d.tap("Yes")
check(d.has_text("This cannot be undone."), "the wipe asks twice")
d.tap("Cancel")
check("ctl wipe --yes" not in m.calls(), "and cancelling the second question wipes nothing")

# Joining a Wi-Fi (internet before deploying): from the hotspot, after a
# question; the networks in range, best signal once each; the password goes
# to humint-ctl on stdin, never on its command line.
d.tap("Join Wi-Fi")
d.tap("Yes")
d.until(lambda: d.button("Jordan's iPhone") is not None, what="networks in range")
shot(d, "06b-box-wifi")
check(d.button("Cafe:Guest") is not None, "names with a colon come through whole")
nets = [i for i in d.items() if i.property("text") == "Jordan's iPhone" and i.metaObject().indexOfSignal("clicked()") >= 0]
check(len(nets) == 1 and nets[0].property("sub").endswith("strong"), "each network once, with its best signal")
d.tap("Jordan's iPhone")
check(d.field("the Wi-Fi's name, exactly").property("text") == "Jordan's iPhone", "tapping one fills in its name")
d.set_field("Password", "short")
d.tap("Join")
check(d.has_text("8 to 63 characters") and not any(c.startswith("ctl net") for c in m.calls()),
      "a too-short password is refused on the screen")
d.set_field("Password", "pa$$ 'word' `x`")
d.tap("Join")
d.until(lambda: "ctl net client Jordan's iPhone" in m.calls(), what="join")
check("psk pa$$ 'word' `x`" in m.calls() and not any("word" in c for c in m.calls() if c.startswith("ctl")),
      "the password reaches humint-ctl exactly, on stdin and not on the command line")
d.until(lambda: d.has_text("Joined “Jordan's iPhone”"), what="joined")
check(True, "it says it joined")
# What humint-ctl refuses comes back in words.
d.tap("Join Wi-Fi")
d.tap("Yes")
d.type_into("the Wi-Fi's name, exactly", "Bad")
d.tap("Join")
d.until(lambda: d.has_text("nope"), what="refusal")
check(True, "a refusal from humint-ctl is shown in its own words")
d.tap("Cancel")
from humint_ui.box import call as _call  # noqa: E402
os.environ["HUMINT_BOX_SOCK"] = m.sock
check(not _call("wifi_join", {"ssid": "x\nNET_MODE=evil", "psk": ""})["ok"],
      "the helper refuses a name with a line break in it")
check(not _call("wifi_join", {"ssid": "x" * 33, "psk": ""})["ok"], "or one longer than Wi-Fi allows")
m.write("var/lib/humint/env", open(m.path("var/lib/humint/env")).read().replace("NET_MODE=hotspot", "NET_MODE=client")
        + "CLIENT_SSID='Jordan'\\''s iPhone'\nCLIENT_PSK='secret pw'\n")
time.sleep(1.2)   # past the helper's one-second status cache
st = _call("status")["data"]
check(st["ssid"] == "Jordan's iPhone" and st["psk"] is None,
      "joined: the network's name read back exactly, and its password never sent to the screen")
time.sleep(1.2)
m.write("var/lib/humint/env", open(m.path("var/lib/humint/env")).read().replace("NET_MODE=client", "NET_MODE=hotspot"))

# ---- Admin → Storage: growing the case file ----------------------------------------
# A 16 GB case file (sparse here); the disk's free space decides the most.
with open(m.path("srv/humint.img"), "wb") as f:
    f.truncate(16 * 2**30)
d.tap("← Done")
d.tap("Admin")
d.tap("Storage")
d.until(lambda: d.has_text("16 GB"), what="storage page")
shot(d, "08-admin-storage")
check(d.has_text("It can grow to"), "it shows the size, and how far it can grow")
d.set_field("New size, GB", "17")
d.set_field("Unlock PIN", "9999")
d.tap("Grow to 17 GB")
d.until(lambda: d.has_text("Wrong PIN"), what="wrong PIN")
check("ctl store grow 17G" in m.calls() and "pin 9999" in m.calls() and not any("9999" in c for c in m.calls() if c.startswith("ctl")),
      "the size goes to humint-ctl store grow, the PIN on stdin only; a refusal comes back in words")
d.set_field("Unlock PIN", "1234")
d.tap("Grow to 17 GB")
d.until(lambda: d.has_text("The case file is now 17 GB"), what="grown")
check(True, "and with the right PIN it says it grew")
from humint_ui.box import call as _c2  # noqa: E402
os.environ["HUMINT_BOX_SOCK"] = m.sock
check(not _c2("store_grow", {"size_gb": "lots", "pin": "1234"})["ok"], "the helper refuses a size that is not a number")
d.tap("Box")
d.until(lambda: d.has_text("Team address"), what="box again")
d.tap("Actions")

# Phone upload codes, through the helper and the panel's token.
d.tap("Phone upload")
d.until(lambda: d.button("ana") is not None, what="people")
d.tap("ana")
d.until(lambda: d.has_text("It closes in"), timeout=10, what="upload code")
shot(d, "07-box-upload")
audit = c.sql("SELECT actor_username, actor_kind, action FROM audit_log WHERE action LIKE 'field.device.%%'")
check(audit == [("touch panel", "panel", "field.device.enroll")], f"the code is issued as the touch panel ({audit})")
d.tap("Done")
check(not d.has_text("It closes in"), "Done takes the code off the screen")

# The helper refuses anything outside its list.
from humint_ui.box import call  # noqa: E402
os.environ["HUMINT_BOX_SOCK"] = m.sock
check(not call("ctl", {"action": "net", "args": ["client", "evil"]})["ok"], "the helper refuses commands it does not know")
check(not call("ctl", {"action": "logs", "args": []})["ok"], "including real humint-ctl commands not offered to the app")

# ---- the quick settings: tap the status at the top right ---------------------------------
from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402


def item(name):
    for i in d.items():
        if i.objectName() == name and d.visible(i):
            return i
    return None


def click(it):
    p = it.mapToScene(QPointF(it.width() / 2, it.height() / 2)).toPoint()
    QTest.mouseClick(d.win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p)
    d.pump(0.3)


BL = "sys/class/backlight/intel_backlight/"
d.until(lambda: item("statusButton") is not None, what="status button")
click(item("statusButton"))
d.until(lambda: d.has_text("Screen sleeps after"), what="quick settings")
shot(d, "09-quick-settings")
check(d.has_text("Brightness") and d.has_text("Volume") and d.has_text("40%"),
      "tapping the status opens the machine's controls, with the volume as it is")
sl = item("brightness")
sl.setProperty("value", 30)
sl.metaObject().invokeMethod(sl, "moved")
d.until(lambda: open(m.path(BL + "brightness")).read().strip() == "300", what="brightness")
check(True, "the brightness slider sets the backlight")
vl = item("volume")
vl.setProperty("value", 65)
vl.metaObject().invokeMethod(vl, "moved")
d.until(lambda: open(m.mixer_state).read().split()[0] == "65", what="volume")
check(any(c.startswith("alsactl store") for c in m.calls()), "the volume slider sets the sound card, and it is kept for the next start")
d.tap("Mute")
d.until(lambda: open(m.mixer_state).read().split()[1] == "off", what="mute")
d.until(lambda: d.button("Unmute") is not None, what="unmute button")
d.tap("Unmute")
d.until(lambda: open(m.mixer_state).read().split()[1] == "on", what="unmute")
check(True, "mute and unmute")
d.tap("2 m")
d.until(lambda: "SCREEN_SLEEP_MINUTES=2" in open(m.path("var/lib/humint/env")).read(), what="sleep setting")
d.until(lambda: d.objs["idle"].property("minutes") == 2, what="idle minutes")
check(True, "choosing when the screen sleeps saves it, and the app follows it")

# Sleep now: the panel off and black over everything; a tap wakes it and only wakes it.
d.tap("Sleep now")
d.until(lambda: d.objs["idle"].property("asleep"), what="asleep")
d.until(lambda: open(m.path(BL + "bl_power")).read().strip() == "4", what="panel off")
check(item("sleepCover") is not None and not d.has_text("Screen sleeps after"),
      "sleeping switches the panel off and covers the screen")
d.pump(0.8)
before = len(m.calls())
click(item("statusButton") or d.win.contentItem())
d.until(lambda: not d.objs["idle"].property("asleep"), what="awake")
d.until(lambda: open(m.path(BL + "bl_power")).read().strip() == "0", what="panel on")
check(not d.has_text("Screen sleeps after"), "a tap wakes it, and does not also press what was under it")

# Untouched for the chosen time, it sleeps by itself.
idle = d.objs["idle"]
import time as _t  # noqa: E402
idle._last = _t.monotonic() - 2 * 60 - 1
d.until(lambda: idle.property("asleep"), timeout=6, what="sleeps by itself")
check(True, "left untouched for its minutes, the screen sleeps by itself")
idle.wake()
d.pump(0.9)

# The keyboard's own keys.
QTest.keyClick(d.win, Qt.Key.Key_VolumeUp)
d.until(lambda: open(m.mixer_state).read().split()[0] == "70", what="volume key")
QTest.keyClick(d.win, Qt.Key.Key_MonBrightnessDown)
d.until(lambda: open(m.path(BL + "brightness")).read().strip() == "200", what="brightness key")
check(True, "the volume and brightness keys work, in steps")

# Signing out when it sleeps, if chosen.
click(item("statusButton"))
d.until(lambda: d.has_text("Screen sleeps after"), what="quick settings again")
d.tap("Sign out of the console when it sleeps")
d.until(lambda: "SCREEN_SLEEP_SIGNOUT=true" in open(m.path("var/lib/humint/env")).read(), what="signout setting")
d.pump(1.5)
d.tap("Sleep now")
d.until(lambda: idle.property("asleep"), what="asleep again")
d.pump(0.8)
idle.wake()
d.until(lambda: d.button("Box") is None or d.has_text("Sign in"), what="signed out")
check(not d.has_text("Dashboard") or d.has_text("Sign in"), "with sign-out chosen, sleeping signs the console out")

# Locking from elsewhere signs the app out.
m.remove("run/humint-data.ready")
d.until(lambda: d.has_text("Unlock the case file"), what="locked again")
check(not d.has_text("Dashboard"), "when the case file locks, nobody stays signed in")
m.stop()
c.stop()
finish()
