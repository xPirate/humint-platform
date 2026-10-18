"""First boot gives each field server a login password of its own."""
import importlib.util
import json
import os
import queue
import stat
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import ROOT, check, finish  # noqa: E402

OPT = os.path.join(ROOT, "deploy/pi/stage-humint/03-overlay/files/opt/humint")
tmp = tempfile.mkdtemp()
stubs = os.path.join(tmp, "bin")
os.makedirs(stubs)
# chpasswd records what it was asked to set instead of changing a real account.
with open(os.path.join(stubs, "chpasswd"), "w") as fh:
    fh.write(f"#!/bin/sh\ncat >> {tmp}/chpasswd.log\n")
os.chmod(os.path.join(stubs, "chpasswd"), 0o755)


def sh(script):
    full = f""". {OPT}/lib/humint-common.sh
HUMINT_RUN={tmp}/run; LOGIN_SECRET_FILE={tmp}/run/login-password.json
login_user() {{ echo operator; }}
{script}"""
    return subprocess.run(["bash", "-c", full], capture_output=True, text=True,
                          env={**os.environ, "PATH": stubs + ":" + os.environ["PATH"]})


pws = {sh("random_login_password").stdout for _ in range(20)}
sample = next(iter(pws))
check(len(pws) == 20, "every box gets a different password")
check(len(sample) == 19 and sample.count("-") == 3 and not set(sample) & set("01ilo"),
      f"it reads off a screen: four groups of four, no 0/o or 1/l/i ({sample})")

r = sh('pw="$(new_login_password)"; echo "$pw"')
pw = r.stdout.strip().splitlines()[-1]
log = open(f"{tmp}/chpasswd.log").read()
check(log.strip() == f"operator:{pw}", "the login's password is changed to it")
secret = f"{tmp}/run/login-password.json"
data = json.load(open(secret))
check(data["user"] == "operator" and data["password"] == pw, "it is left for the panel to show")
check(stat.S_IMODE(os.stat(secret).st_mode) == 0o600, "and only root can read it there")

# ---- the panel shows it once, after the PIN, and forgets it ----------------
os.environ["SDL_VIDEODRIVER"] = "dummy"
spec = importlib.util.spec_from_file_location("panel", os.path.join(OPT, "bin/humint-panel.py"))
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)
P.LOGIN_SECRET = secret
import pygame  # noqa: E402
pygame.display.init(); pygame.font.init()


class St:
    def __init__(self, unlocked=True):
        self.unlocked = unlocked

    def get(self):
        return {"unlocked": self.unlocked, "login_secret": P.read_json(P.LOGIN_SECRET, None), "battery": {},
                "services": [], "name": "x", "store_exists": True, "firstboot_done": True, "tries_left": 5}

    def refresh(self):
        pass


locked = P.Panel((800, 480), St(unlocked=False), queue.Queue(), P.Calibration(800, 480), None)
check(locked.current(locked.status.get()) == "pin", "a locked box never shows it — the PIN comes first")
ui = P.Panel((800, 480), St(), queue.Queue(), P.Calibration(800, 480), None)
check(ui.current(ui.status.get()) == "secret", "an unlocked box shows the new password")
surf = pygame.Surface((800, 480))
ui.draw(surf)
pygame.image.save(surf, os.path.join(tmp, "secret.png"))
btn = [b for b in ui.buttons if b.label == "I've written it down"][0]
ui.handle(("tap", btn.rect.centerx, btn.rect.centery, (0, 0)))
check(not os.path.exists(secret) and ui.current(ui.status.get()) == "home",
      "confirming it is written down removes it and returns Home")
ui.screen = "menu"
ui.draw(surf)
labels = [b.label for b in ui.buttons]
check("New login" in labels and "Shut down" in labels, "the menu offers a new login password")
ran = []
ui.ctl = lambda label, *a, **k: ran.append(a)
b = [b for b in ui.buttons if b.label == "New login"][0]
ui.handle(("tap", b.rect.centerx, b.rect.centery, (0, 0)))
check(ui.confirm is not None, "after asking first")
ui.draw(surf)
yes = [b for b in ui.buttons if b.label == "Yes"][0]
ui.handle(("tap", yes.rect.centerx, yes.rect.centery, (0, 0)))
check(ran == [("login-password",)], "which runs humint-ctl login-password")
print("screenshot:", os.path.join(tmp, "secret.png"))
finish()
