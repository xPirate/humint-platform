#!/usr/bin/env python3
"""Battery gauge and power source, for the UPS boards the field server knows.

Every few seconds it reads the battery board and writes
/run/humint/battery.json, which the OLED, the touch panel and `humint-ctl
status` all read — one reader of the I2C chip, many readers of a file.

Two boards:

  Geekworm X1203 (Pi 5)   a real fuel gauge (Maxim MAX17040, I2C 0x36) that
                          reports the charge itself, and a power-loss signal
                          (GPIO 6) that says the moment wall power goes. The
                          cells are in PARALLEL — one cell's voltage.
  Waveshare UPS HAT       an INA219 voltage/current monitor (I2C 0x42) and no
                          gauge: charge is estimated from the pack voltage, as
                          Waveshare's own code does; whether it is on battery
                          is read from the direction of the current.

With neither fitted it says so ("present": false, "mains": true) and the
screens show a plug: the box is running on external power with no battery
behind it, so pulling the cable turns it off.

On battery power, when the charge falls to BATTERY_SHUTDOWN_PERCENT (or an
X1203 cell to 3.20 V, Geekworm's own cut-off), it does what a person would do
with a box about to die mid-write: stops the console, re-locks the case file,
and powers off. A database cut off mid-write can be repaired; one shut down
cleanly never needs to be.

  BATTERY=auto        look for an X1203, then a Waveshare HAT, then a
                      laptop's own battery (default)
  BATTERY=x1203       require the X1203
  BATTERY=waveshare   require the Waveshare HAT
  BATTERY=laptop      the machine's own battery (x86 laptops; auto finds it)
  BATTERY=none        no gauge
  BATTERY_SHUTDOWN_PERCENT=8
  BATTERY_CELLS=2           Waveshare only: cells in series (1 for UPS HAT (C))
  BATTERY_PLD_GPIO=6        X1203 only: the power-loss pin
  BATTERY_PLD_AC_LEVEL=1    X1203 only: the pin's level while wall power is
                            present (flip to 0 if the screens say "on
                            battery" while plugged in)
"""
import json
import os
import re
import subprocess
import sys
import time

CONF = "/var/lib/humint/env"
OUT_DIR = "/run/humint"
OUT = os.path.join(OUT_DIR, "battery.json")

POLL_SECONDS = 5
LOW_READINGS = 3          # consecutive low readings before acting (~15 s)
X1203_CUTOFF_V = 3.20     # Geekworm's own shutdown voltage for one cell


def config() -> dict:
    out = {"BATTERY": "auto", "BATTERY_CELLS": "2", "BATTERY_SHUTDOWN_PERCENT": "8",
           "BATTERY_PLD_GPIO": "6", "BATTERY_PLD_AC_LEVEL": "1"}
    try:
        for line in open(CONF):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return out


def _bus(number=1):
    from smbus2 import SMBus
    return SMBus(number)


# ---------------------------------------------------------------------------
# Geekworm X1203: MAX17040 fuel gauge + power-loss GPIO
# ---------------------------------------------------------------------------

class X1203:
    name = "Geekworm X1203"
    ADDR = 0x36
    REG_VCELL, REG_SOC, REG_VERSION = 0x02, 0x04, 0x08

    def __init__(self, bus, pld_gpio=6, ac_level=1):
        self.bus, self.pld_gpio, self.ac_level = bus, pld_gpio, ac_level
        self.cells = 1

    def _word(self, reg):
        hi, lo = self.bus.read_i2c_block_data(self.ADDR, reg, 2)
        return hi, lo

    def looks_right(self) -> bool:
        """A MAX17040 answers at 0x36 with a non-zero version and a cell
        voltage a lithium cell could have. Nothing else on this bus does."""
        try:
            hi, lo = self._word(self.REG_VERSION)
            if (hi << 8 | lo) in (0, 0xFFFF):
                return False
            return 2.0 <= self.volts() <= 4.6
        except OSError:
            return False

    def volts(self) -> float:
        hi, lo = self._word(self.REG_VCELL)
        return ((hi << 8 | lo) >> 4) * 0.00125          # 12 bits, 1.25 mV each

    def percent(self) -> float:
        hi, lo = self._word(self.REG_SOC)
        return max(0.0, min(100.0, hi + lo / 256.0))    # the chip's own estimate

    def ac_present(self):
        """Wall power present? None when the pin cannot be read."""
        level = read_gpio(self.pld_gpio)
        return None if level is None else (level == self.ac_level)

    def sample(self) -> dict:
        v = self.volts()
        return {"voltage": v, "percent": self.percent(), "current_ma": None,
                "ac_present": self.ac_present()}


def read_gpio(pin: int):
    """The level of a header GPIO (BCM numbering), without claiming it:
    `pinctrl` on Raspberry Pi OS (Pi 5's RP1 included), libgpiod as a fallback."""
    try:
        out = subprocess.run(["pinctrl", "get", str(pin)], capture_output=True, text=True,
                             timeout=3).stdout
        m = re.search(r"\|\s*(hi|lo)\b", out)
        if m:
            return 1 if m.group(1) == "hi" else 0
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        import gpiod                                     # python3-libgpiod
        for chip in ("gpiochip0", "gpiochip4"):
            try:
                c = gpiod.Chip(chip)
                line = c.get_line(pin)
                line.request(consumer="humint-battery", type=gpiod.LINE_REQ_DIR_IN)
                try:
                    return line.get_value()
                finally:
                    line.release()
            except Exception:
                continue
    except ImportError:
        pass
    return None


# ---------------------------------------------------------------------------
# Waveshare UPS HAT: INA219 voltage/current monitor
# ---------------------------------------------------------------------------

REG_CONFIG, REG_BUS, REG_CURRENT, REG_CAL = 0x00, 0x02, 0x04, 0x05
# 32 V bus range, ±320 mV shunt, 12-bit 32-sample averaging on both,
# continuous — Waveshare's own settings for this board.
CONFIG_VALUE = (0x01 << 13) | (0x03 << 11) | (0x0D << 7) | (0x0D << 3) | 0x07
CAL_VALUE = 4096          # with the board's 0.1 Ω shunt: 0.1 mA per bit
CURRENT_LSB_MA = 0.1


class INA219:
    name = "Waveshare UPS HAT"
    ADDRESSES = (0x42, 0x43, 0x40, 0x41)

    def __init__(self, bus, addr, cells=2):
        self.bus, self.addr, self.cells = bus, addr, cells

    def _write(self, reg, value):
        self.bus.write_i2c_block_data(self.addr, reg, [(value >> 8) & 0xFF, value & 0xFF])

    def _read(self, reg):
        hi, lo = self.bus.read_i2c_block_data(self.addr, reg, 2)
        return (hi << 8) | lo

    def setup(self):
        self._write(REG_CAL, CAL_VALUE)
        self._write(REG_CONFIG, CONFIG_VALUE)

    def looks_right(self) -> bool:
        """An INA219 reads its configuration back as written."""
        try:
            self.setup()
            time.sleep(0.05)
            return self._read(REG_CONFIG) == CONFIG_VALUE
        except OSError:
            return False

    def volts(self) -> float:
        return (self._read(REG_BUS) >> 3) * 0.004

    def milliamps(self) -> float:
        # The calibration register is lost on a brown-out; rewrite it each
        # time rather than report a current of zero forever after.
        self._write(REG_CAL, CAL_VALUE)
        raw = self._read(REG_CURRENT)
        if raw > 32767:
            raw -= 65536
        return raw * CURRENT_LSB_MA

    def sample(self) -> dict:
        v, ma = self.volts(), self.milliamps()
        # The HAT reads negative while the pack is feeding the Pi; anything
        # else means something upstream is.
        return {"voltage": v, "percent": None, "current_ma": ma, "ac_present": ma > -20}


def percent_from_volts(volts: float, cells: int) -> float:
    empty, full = 3.0 * cells, 4.2 * cells
    return max(0.0, min(100.0, (volts - empty) / (full - empty) * 100.0))


# ---------------------------------------------------------------------------
# Laptops and mini PCs (x86): the kernel's own battery and charger reports
# ---------------------------------------------------------------------------

class Laptop:
    """/sys/class/power_supply: every battery the firmware reports (a laptop
    with two — internal and hot-swap — shows both, and the total), and whether
    the charger is plugged in. No guessing from voltages: the machine knows."""
    name = "Laptop battery"
    cells = 1

    def __init__(self, root=None):
        self.root = root or os.environ.get("POWER_SUPPLY_ROOT", "/sys/class/power_supply")

    def _read(self, dev, key):
        try:
            return open(os.path.join(self.root, dev, key)).read().strip()
        except OSError:
            return None

    def _num(self, dev, key):
        v = self._read(dev, key)
        try:
            return float(v) if v is not None else None
        except ValueError:
            return None

    def _devices(self):
        try:
            names = sorted(os.listdir(self.root))
        except OSError:
            return [], []
        bats, mains = [], []
        for n in names:
            kind = self._read(n, "type")
            # scope=Device: a wireless mouse or keyboard's battery, not ours.
            if kind == "Battery" and self._read(n, "scope") != "Device" and self._read(n, "present") != "0":
                bats.append(n)
            elif kind in ("Mains", "USB"):
                mains.append(n)
        return bats, mains

    def looks_right(self) -> bool:
        return bool(self._devices()[0])

    def sample(self) -> dict:
        bats, mains = self._devices()
        now = full = power = 0.0
        each, statuses = [], []
        for b in bats:
            # Energy (µWh) where the firmware reports it, charge (µAh) otherwise.
            n = self._num(b, "energy_now")
            f = self._num(b, "energy_full")
            p = self._num(b, "power_now")
            if n is None or not f:
                # µAh × V → µWh, so two batteries reporting differently still add up.
                v = (self._num(b, "voltage_min_design") or self._num(b, "voltage_now") or 0) / 1e6
                cn, cf, cur = self._num(b, "charge_now"), self._num(b, "charge_full"), self._num(b, "current_now")
                n = cn * v if cn is not None and v else None
                f = cf * v if cf and v else None
                p = cur * v if cur is not None and v else None
            cap = self._num(b, "capacity")
            pct = (n / f * 100.0) if n is not None and f else cap
            each.append({"name": b, "percent": round(pct, 1) if pct is not None else None,
                         "status": self._read(b, "status") or "Unknown"})
            statuses.append(self._read(b, "status") or "Unknown")
            if n is not None and f:
                now, full = now + n, full + f
            if p:
                power += abs(p)
        if full:
            pct = now / full * 100.0
        else:
            known = [e["percent"] for e in each if e["percent"] is not None]
            pct = sum(known) / len(known) if known else None
        online = [self._read(m, "online") for m in mains]
        if any(o == "1" for o in online):
            ac = True
        elif online and all(o == "0" for o in online):
            ac = False
        elif "Discharging" in statuses:
            ac = False
        elif statuses and all(s in ("Charging", "Full", "Not charging") for s in statuses):
            ac = True
        else:
            ac = None
        if pct is None:
            raise OSError("the battery reports no charge level")
        volts = self._num(bats[0], "voltage_now") if bats else None
        out = {"voltage": (volts or 0) / 1e6, "percent": pct, "current_ma": None,
               "ac_present": ac, "batteries": each}
        # Minutes left straight from the firmware's power reading.
        if ac is False and power > 0 and full:
            out["minutes_left"] = int(now / power * 60)
        return out


# ---------------------------------------------------------------------------

def find(mode: str, cfg: dict):
    if mode in ("auto", "x1203", "waveshare"):
        try:
            bus = _bus(1)
        except Exception as exc:
            bus = None
            if mode in ("x1203", "waveshare"):
                print(f"humint-battery: no I2C bus: {exc}", file=sys.stderr)
        if bus is not None and mode in ("auto", "x1203"):
            dev = X1203(bus, int(cfg.get("BATTERY_PLD_GPIO") or 6),
                        int(cfg.get("BATTERY_PLD_AC_LEVEL") or 1))
            if dev.looks_right():
                return dev
        if bus is not None and mode in ("auto", "waveshare"):
            for addr in INA219.ADDRESSES:
                dev = INA219(bus, addr, max(1, int(cfg.get("BATTERY_CELLS") or 2)))
                if dev.looks_right():
                    return dev
    if mode in ("auto", "laptop"):
        dev = Laptop()
        if dev.looks_right():
            return dev
    return None


def write(state: dict) -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    tmp = OUT + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(state, fh)
    os.chmod(tmp, 0o644)
    os.replace(tmp, OUT)


def oled(*lines):
    try:
        subprocess.run(["/opt/humint/venv/bin/python3", "/opt/humint/bin/oled_show.py", *lines],
                       timeout=10, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def shut_down(pct: float) -> None:
    print(f"humint-battery: battery at {pct:.0f}% on battery power — locking the case file "
          "and powering off", flush=True)
    write({"present": True, "shutting_down": True, "percent": pct})
    oled("BATTERY LOW", "locking case file", "powering off")
    subprocess.run(["/opt/humint/bin/humint-ctl", "lock"], timeout=180,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["systemctl", "poweroff"])


class Tracker:
    """Smoothing, the on-battery decision and a time-left estimate, the same
    for both boards."""

    def __init__(self, dev, threshold: float):
        self.dev, self.threshold = dev, threshold
        self.volts_hist, self.pct_hist = [], []   # pct_hist: (time, pct) while on battery
        self.low = 0

    def step(self, s: dict, now: float) -> tuple[dict, bool]:
        self.volts_hist = (self.volts_hist + [s["voltage"]])[-6:]          # ~30 s
        v_avg = sum(self.volts_hist) / len(self.volts_hist)
        pct = s["percent"] if s["percent"] is not None else percent_from_volts(v_avg, self.dev.cells)
        ac = s["ac_present"]
        on_battery = ac is False
        state = {"present": True, "board": self.dev.name, "percent": round(pct, 1),
                 "voltage": round(v_avg, 3), "ac_present": ac, "on_battery": on_battery,
                 "charging": bool(ac) and pct < 99.5, "cells": self.dev.cells,
                 "updated": int(now)}
        if s["current_ma"] is not None:
            state["current_ma"] = round(s["current_ma"], 1)
        if s.get("batteries"):
            state["batteries"] = s["batteries"]

        # Time left: from the current where the board measures it, otherwise
        # from how fast the charge has been falling over the last ~10 minutes.
        if on_battery:
            self.pct_hist = [(t, p) for t, p in self.pct_hist if now - t <= 600] + [(now, pct)]
            mins = None
            if s["current_ma"] is not None and s["current_ma"] < -20 and len(self.volts_hist) >= 6:
                mins = int((2500 * pct / 100) / abs(s["current_ma"]) * 60)
            elif len(self.pct_hist) >= 2:
                (t0, p0), (t1, p1) = self.pct_hist[0], self.pct_hist[-1]
                if t1 - t0 >= 180 and p0 > p1:
                    mins = int(p1 / ((p0 - p1) / (t1 - t0)) / 60)
            if s.get("minutes_left") is not None:
                mins = s["minutes_left"]
            if mins is not None:
                state["minutes_left"] = mins
        else:
            self.pct_hist = []

        low_now = on_battery and len(self.volts_hist) >= 3 and (
            pct <= self.threshold or (isinstance(self.dev, X1203) and v_avg < X1203_CUTOFF_V))
        self.low = self.low + 1 if low_now else 0
        return state, self.low >= LOW_READINGS


def describe(state: dict) -> str:
    if not state.get("present"):
        return "No battery module — running on external power."
    how = "on battery" if state.get("on_battery") else (
        "plugged in, charging" if state.get("charging") else
        "plugged in" if state.get("ac_present") else "power source unknown")
    bits = [f"{state['percent']:.0f}% ({how})", f"{state['voltage']:.2f} V"]
    if state.get("current_ma") is not None:
        bits.append(f"{state['current_ma']:+.0f} mA")
    if state.get("minutes_left") is not None:
        bits.append(f"~{state['minutes_left'] // 60}h{state['minutes_left'] % 60:02d}m left")
    return f"{state.get('board', 'Battery')}: " + ", ".join(bits)


def main() -> int:
    once = "--once" in sys.argv
    cfg = config()
    mode = (cfg.get("BATTERY") or "auto").lower()
    if mode == "none":
        write({"present": False, "mains": True, "disabled": True})
        return 0
    dev = find(mode, cfg)
    if dev is None:
        state = {"present": False, "mains": True}
        write(state)
        if once:
            print(describe(state) + " (looked for an X1203 at 0x36 and a Waveshare HAT at 0x40-0x43)")
        if mode in ("x1203", "waveshare"):
            print(f"humint-battery: BATTERY={mode} but the board did not answer", file=sys.stderr)
            return 1
        return 0       # auto, nothing fitted: not an error, and nothing to restart

    tracker = Tracker(dev, float(cfg.get("BATTERY_SHUTDOWN_PERCENT") or 8))
    while True:
        try:
            s = dev.sample()
        except OSError as exc:
            print(f"humint-battery: read failed: {exc}", file=sys.stderr)
            time.sleep(POLL_SECONDS)
            continue
        state, act = tracker.step(s, time.time())
        write(state)
        if once:
            print(describe(state))
            return 0
        if act:
            shut_down(state["percent"])
            return 0
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    sys.exit(main())
