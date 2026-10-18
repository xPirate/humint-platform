#!/usr/bin/env python3
"""Keep the field server's clock right with no network time.

A Pi has no battery-backed clock (a Pi 5 only with a cell fitted), and in the
field there is usually no network to ask. At boot it believes it is whenever
fake-hwclock last saved — the last shutdown, which may be days ago.

So the console asks each signed-in browser for its clock (api/clock.py) and
leaves a hint in the store; this service, as root, applies it:

  * never while the system has network time (NTPSynchronized=yes) — that wins;
  * only when the box is more than a minute out;
  * never to a time before this image was built, or from a hint more than ten
    minutes old;
  * from the sign-in page (no one signed in yet — two-factor codes need the
    right time before anyone can sign in), only forward, and only while
    nothing has set it this boot.

After setting it, it saves the time (fake-hwclock, and the real-time clock if
one is fitted) so the next boot starts close, re-issues the HTTPS certificate
if the correction left it not-yet-valid, and records what it did in
/run/humint/clock.json, which the panel shows: the time is marked unconfirmed
until network time or a device has set it this boot.

Standard library only.
"""
import json
import os
import shutil
import subprocess
import sys
import time

HINT = os.environ.get("CLOCK_HINT_FILE", "/srv/humint-data/clock/hint.json")
STATE = "/run/humint/clock.json"
BUILD_EPOCH_FILE = "/opt/humint/build-epoch"
THRESHOLD = 60
MAX_HINT_AGE = 600
POLL = 5


def log(msg):
    print(f"humint-clock: {msg}", flush=True)


def ntp_synced() -> bool:
    try:
        out = subprocess.run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
        return out == "yes"
    except (OSError, subprocess.SubprocessError):
        return False


def build_epoch() -> float:
    try:
        return float(open(BUILD_EPOCH_FILE).read().strip())
    except (OSError, ValueError):
        return 1_760_000_000.0          # Oct 2025: older than any image of this


def write_state(state: dict) -> None:
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(state, fh)
    os.chmod(tmp, 0o644)
    os.replace(tmp, STATE)


def read_state() -> dict:
    try:
        return json.load(open(STATE))
    except (OSError, ValueError):
        return {}


def save_clock() -> None:
    if shutil.which("fake-hwclock"):
        subprocess.run(["fake-hwclock", "save", "force"], capture_output=True)
    if os.path.exists("/dev/rtc0") and shutil.which("hwclock"):
        subprocess.run(["hwclock", "--systohc"], capture_output=True)


def decide(hint: dict, now_real: float, now_mono: float, floor: float):
    """(new_epoch, reason) — new_epoch None when the hint is not to be used."""
    try:
        client, mono = float(hint["client_epoch"]), float(hint["monotonic"])
    except (KeyError, TypeError, ValueError):
        return None, "unreadable hint"
    age = now_mono - mono
    if age < 0 or age > MAX_HINT_AGE:
        return None, f"hint is {age:.0f}s old"
    target = client + age            # what the device's clock reads now
    if target < floor:
        return None, "hint is earlier than this image was built"
    if abs(target - now_real) < THRESHOLD:
        return None, "already within a minute"
    if hint.get("anonymous") and target < now_real:
        # From the sign-in page: forward only (see api/clock.py).
        return None, "an anonymous hint may only move the clock forward"
    return target, "ok"


def apply(hint: dict) -> bool:
    target, why = decide(hint, time.time(), time.monotonic(), build_epoch())
    if target is None:
        log(f"not applying the hint: {why}")
        return False
    before = time.time()
    time.clock_settime(time.CLOCK_REALTIME, target)
    offset = target - before
    log(f"clock set from {hint.get('username', '?')}'s device: moved {offset:+.0f}s")
    save_clock()
    write_state({"source": "device", "set_at": time.time(), "by": hint.get("username"),
                 "offset_seconds": round(offset)})
    # A certificate issued while the clock ran fast would now be not-yet-valid;
    # the TLS script notices and re-issues (and restarts the console).
    if os.path.exists("/run/humint-data.ready"):
        subprocess.run(["/opt/humint/bin/humint-tls.sh", "ensure", "--restart"], capture_output=True)
    return True


def tick(seen: dict) -> None:
    if ntp_synced():
        if read_state().get("source") != "ntp":
            write_state({"source": "ntp", "set_at": time.time()})
            save_clock()
            log("network time is synchronised")
        return
    if not os.path.exists(STATE):
        write_state({"source": "unset", "since": time.time()})
    try:
        mtime = os.stat(HINT).st_mtime_ns
    except OSError:
        return
    if seen.get("mtime") == mtime:
        return
    seen["mtime"] = mtime
    try:
        hint = json.load(open(HINT))
    except (OSError, ValueError):
        return
    apply(hint)
    try:
        os.unlink(HINT)
    except OSError:
        pass


def main(argv) -> int:
    if argv[1:2] == ["--once"]:
        tick({})
        return 0
    seen = {}
    while True:
        try:
            tick(seen)
        except Exception as exc:          # noqa: BLE001 - keep watching
            log(f"error: {exc}")
        time.sleep(POLL)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
