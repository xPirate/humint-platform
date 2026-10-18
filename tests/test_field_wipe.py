"""The field server's case file can be destroyed: on purpose, or under duress.

Runs the real cryptsetup against a LUKS2 container in a plain file (header
operations need no device-mapper). Opening, mounting and building a database
are the same code first boot uses, and are stubbed here.
"""
import os
import shutil
import stat
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import ROOT, check, finish  # noqa: E402

if not shutil.which("cryptsetup"):
    print("SKIP: cryptsetup is not installed (apt install cryptsetup-bin)")
    finish()

OPT = os.path.join(ROOT, "deploy/pi/stage-humint/03-overlay/files/opt/humint")
DUR = os.path.join(OPT, "bin/humint-duress.py")
tmp = tempfile.mkdtemp()
REAL, DURESS = "Real-PIN-2468", "Duress-1357"


def duress(cmd, pin=None, file=os.path.join(tmp, "duress")):
    return subprocess.run([sys.executable, DUR, cmd], input=(pin + "\n") if pin else "",
                          capture_output=True, text=True, env={**os.environ, "HUMINT_DURESS_FILE": file}).returncode


# ---- the duress PIN is only ever stored as a slow hash -----------------------
check(duress("status") == 1, "no duress PIN until one is set")
check(duress("set", DURESS) == 0, "a duress PIN can be set")
saved = open(os.path.join(tmp, "duress")).read()
check(DURESS not in saved and saved.startswith("scrypt$"), "the file holds a scrypt hash, not the PIN")
check(stat.S_IMODE(os.stat(os.path.join(tmp, "duress")).st_mode) == 0o600, "only root can read it")
check(duress("check", DURESS) == 0, "the duress PIN is recognised")
check(duress("check", REAL) == 1 and duress("check", DURESS + "0") == 1, "nothing else is")
check(duress("clear") == 0 and duress("status") == 1, "it can be removed")


# ---- a store in a file, and the scripts pointed at it -----------------------
def make_store():
    img = os.path.join(tmp, "humint.img")
    subprocess.run(["dd", "if=/dev/zero", f"of={img}", "bs=1M", "count=40", "status=none"], check=True)
    subprocess.run(["cryptsetup", "luksFormat", "--type", "luks2", "--pbkdf", "argon2id", "--pbkdf-memory",
                    "65536", "--batch-mode", "--key-file=-", img], input=REAL.encode(), check=True)
    return img


def opens(img, pin):
    return subprocess.run(["cryptsetup", "open", "--test-passphrase", "--key-file=-", img],
                          input=pin.encode(), capture_output=True).returncode == 0


stubs = os.path.join(tmp, "bin")
os.makedirs(stubs, exist_ok=True)
for name in ("systemctl", "mountpoint", "fuser", "umount", "sync"):
    with open(os.path.join(stubs, name), "w") as fh:
        fh.write("#!/bin/sh\n" + ('exit 1\n' if name == "mountpoint" else "exit 0\n"))
    os.chmod(os.path.join(stubs, name), 0o755)
state = os.path.join(tmp, "state")


def bash(script, stdin=""):
    os.makedirs(state, exist_ok=True)
    prelude = f"""
set -euo pipefail
. {OPT}/bin/humint-wipe.sh
HUMINT_IMG={tmp}/humint.img; HUMINT_DATA={tmp}/data; HUMINT_STATE={state}
HUMINT_READY={tmp}/ready; UNLOCK_TRIES_FILE={state}/tries; HUMINT_DURESS_FILE={state}/duress
HUMINT_ENV={state}/env; HUMINT_CONF={tmp}/boot.conf; HUMINT_FIRSTBOOT_DONE={state}/firstboot.done
PG_CONF_DIR={tmp}/pgconf; HUMINT_HOME={tmp}/home
oled() {{ :; }}
"""
    return subprocess.run(["bash", "-c", prelude + script], input=stdin, capture_output=True, text=True,
                          env={**os.environ, "HUMINT_LIB": os.path.join(OPT, "lib"),
                               "PATH": stubs + ":" + os.environ["PATH"],
                               "HUMINT_DURESS_FILE": os.path.join(state, "duress")})


home = os.path.join(tmp, "home", "bin")
os.makedirs(home, exist_ok=True)
shutil.copy(DUR, home)

# ---- wiping on purpose ------------------------------------------------------
img = make_store()
check(opens(img, REAL), "(setup) the store opens with the real PIN")
os.makedirs(os.path.join(tmp, "pgconf"), exist_ok=True)
os.makedirs(state, exist_ok=True)
for f in ("ca.crt", "ca.fingerprint", "firstboot.done"):
    open(os.path.join(state, f), "w").close()
open(os.path.join(state, "env"), "w").write("HOSTNAME=humint\nNET_MODE=hotspot\n")
open(os.path.join(state, "tries"), "w").write("3")
r = bash("destroy_store")
check(r.returncode == 0, f"destroy_store runs ({r.stderr[-300:]})")
check(not opens(img, REAL), "after the wipe the real PIN no longer opens anything")
with open(img, "rb") as fh:
    head = fh.read(4096)
check(not head.startswith(b"LUKS"), "the header is overwritten (no LUKS signature left)")
check(not os.path.exists(os.path.join(tmp, "pgconf")) and not os.path.exists(os.path.join(state, "ca.crt")),
      "the database registration and the old CA's public half are gone")
check(open(os.path.join(state, "tries")).read().strip() == "0", "the wrong-PIN count is reset")

img = make_store()
open(os.path.join(state, "firstboot.done"), "w").close()
r = bash("cmd_reset --no-reboot")
check(r.returncode == 0 and not os.path.exists(img), f"a reset removes the store ({r.stderr[-300:]})")
check(not os.path.exists(os.path.join(state, "firstboot.done")) and
      open(os.path.join(tmp, "boot.conf")).read().startswith("HOSTNAME=humint"),
      "and puts the box back to first-time setup with its own settings")

# ---- under duress ------------------------------------------------------------
img = make_store()
r = bash("""
log=$HUMINT_STATE/calls; : >"$log"
format_store() { IFS= read -r p; echo "format:$p" >>"$log"; }
make_store_dirs() { echo dirs >>"$log"; }
create_database() { echo database >>"$log"; }
start_console() { echo console >>"$log"; }
cmd_duress
cat "$log"
""", stdin=DURESS + "\n")
steps = r.stdout.split()
check(r.returncode == 0 and steps == [f"format:{DURESS}", "dirs", "database", "console"],
      f"duress: a new empty case file under the PIN typed, then the console ({steps}, {r.stderr[-200:]})")
check(not opens(img, REAL), "duress: the real case file is unrecoverable")

# try_unlock decides, before anything else, whether the PIN is the duress one
home = os.path.join(tmp, "home", "bin")
os.makedirs(home, exist_ok=True)
shutil.copy(DUR, home)
with open(os.path.join(home, "humint-wipe.sh"), "w") as fh:
    fh.write(f"#!/bin/sh\ncat > {tmp}/wiped-with\n")
os.chmod(os.path.join(home, "humint-wipe.sh"), 0o755)
img = make_store()
duress("set", DURESS, file=os.path.join(state, "duress"))
open(os.path.join(state, "tries"), "w").write("0")
r = bash('rc=0; printf "%s\\n" "$1" | try_unlock || rc=$?; echo "rc=$rc"'.replace("$1", "Wrong-0000"))
check("rc=1" in r.stdout and open(os.path.join(state, "tries")).read().strip() == "1",
      f"a wrong PIN is still just a wrong PIN ({r.stdout.strip()})")
r = bash('rc=0; printf "%s\\n" "' + DURESS + '" | try_unlock || rc=$?; echo "rc=$rc"')
check("rc=0" in r.stdout, f"the duress PIN 'unlocks' ({r.stdout.strip()} {r.stderr[-200:]})")
check(open(os.path.join(tmp, "wiped-with")).read().strip() == DURESS, "having run the duress wipe with it")
check(open(os.path.join(state, "tries")).read().strip() == "0", "and leaves no wrong-PIN count behind")

# ---- the panel ----------------------------------------------------------------
import importlib.util  # noqa: E402
import queue  # noqa: E402
os.environ["SDL_VIDEODRIVER"] = "dummy"
spec = importlib.util.spec_from_file_location("panel", os.path.join(OPT, "bin/humint-panel.py"))
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)
import pygame  # noqa: E402
pygame.display.init(); pygame.font.init()
req = os.path.join(tmp, "pin-setup")
P.PIN_SETUP_REQ, P.PIN_SETUP_FIFO = req, os.path.join(tmp, "pin-setup.fifo")


class St:
    def get(self):
        return {"unlocked": True, "battery": {}, "services": [], "name": "x", "net_mode": "hotspot",
                "pin_setup": open(req).read().strip() if os.path.exists(req) else None}

    def refresh(self):
        pass


ui = P.Panel((800, 480), St(), queue.Queue(), P.Calibration(800, 480), None)
surf = pygame.Surface((800, 480))


def tap(label):
    ui.draw(surf)
    found = [b for b in ui.buttons if b.label == label and b.enabled]
    assert found, f"no enabled button {label!r} on {ui.current(ui.status.get())}: {[b.label for b in ui.buttons]}"
    b = found[0]
    ui.handle(("tap", b.rect.centerx, b.rect.centery, (0, 0)))


ran = []
ui.ctl = lambda label, *a, **k: ran.append(a)
ui.screen = "menu"
tap("Wipe case file")
check(ui.confirm and ui.confirm[0] == "Wipe the case file?", "Wipe asks first")
tap("Yes")
check(ui.confirm and "cannot be undone" in ui.confirm[0] and not ran, "and then asks again")
tap("Yes")
check(ran == [("wipe", "--yes")], "only then wipes")

waiting = []
ui.ctl_waiting = lambda label, args, msgs: waiting.append(args)
ui.screen = "menu"
tap("Duress PIN")
check(waiting == [["duress", "set", "--panel"]], "Duress PIN asks humint-ctl to collect it on this screen")
open(req, "w").write("duress\n")
check(ui.current(ui.status.get()) == "setpin", "the PIN pad comes up for it, though the box is unlocked")
ui.draw(surf)
pygame.image.save(surf, os.path.join(tmp, "duress.png"))
for ch in "1357":
    tap(ch)
tap("OK")
check(ui.setpin_first == "1357", "it is entered twice, like any new PIN")
os.mkfifo(P.PIN_SETUP_FIFO)
fd = os.open(P.PIN_SETUP_FIFO, os.O_RDWR | os.O_NONBLOCK)
tap("Cancel")
check(os.read(fd, 100) == b"\n" and ui.setpin_first is None, "Cancel sends an empty answer, so nothing is set")
print("screenshot:", os.path.join(tmp, "duress.png"))
finish()
