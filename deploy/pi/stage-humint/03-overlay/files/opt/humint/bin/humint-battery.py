#!/usr/bin/env python3
"""Battery gauge for the Waveshare UPS HAT (INA219 current/voltage monitor).

Reads the pack voltage and current every few seconds and writes
/run/humint/battery.json, which the OLED, the touch panel and `humint-ctl
status` all read — one reader of the I2C chip, many readers of a file.

When the pack runs low on battery power it does what a person would do with
a box about to die mid-write: stops the console, re-locks the case file, and
powers off. A database cut off mid-write can be repaired; one shut down
cleanly never needs to be.

Charge is estimated from voltage, the way Waveshare's own code does it: the
HAT has no fuel-gauge chip. Under load the voltage sags, so the figure reads
low while working and recovers at idle — treat it as a guide, and the
shutdown threshold as deliberately conservative.

  BATTERY=auto      look for the HAT at 0x42 (and 0x43, 0x40, 0x41)
  BATTERY=waveshare require it
  BATTERY=none      do nothing
  BATTERY_CELLS=2   18650 cells in series: 2 for the UPS HAT and UPS HAT (B),
                    1 for the UPS HAT (C)
  BATTERY_SHUTDOWN_PERCENT=8
"""
import json
import os
import subprocess
import sys
import time

CONF = "/var/lib/humint/env"
OUT_DIR = "/run/humint"
OUT = os.path.join(OUT_DIR, "battery.json")
ADDRESSES = (0x42, 0x43, 0x40, 0x41)

REG_CONFIG, REG_BUS, REG_CURRENT, REG_CAL = 0x00, 0x02, 0x04, 0x05
# 32 V bus range, ±320 mV shunt, 12-bit 32-sample averaging on both,
# continuous — Waveshare's own settings for this board.
CONFIG_VALUE = (0x01 << 13) | (0x03 << 11) | (0x0D << 7) | (0x0D << 3) | 0x07
CAL_VALUE = 4096          # with the board's 0.1 Ω shunt: 0.1 mA per bit
CURRENT_LSB_MA = 0.1

POLL_SECONDS = 5
LOW_READINGS = 3          # consecutive low readings before acting (~15 s)


def config() -> dict:
    out = {"BATTERY": "auto", "BATTERY_CELLS": "2", "BATTERY_SHUTDOWN_PERCENT": "8"}
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


class INA219:
    def __init__(self, bus, addr):
        self.bus, self.addr = bus, addr

    def _write(self, reg, value):
        self.bus.write_i2c_block_data(self.addr, reg, [(value >> 8) & 0xFF, value & 0xFF])

    def _read(self, reg):
        hi, lo = self.bus.read_i2c_block_data(self.addr, reg, 2)
        return (hi << 8) | lo

    def setup(self):
        self._write(REG_CAL, CAL_VALUE)
        self._write(REG_CONFIG, CONFIG_VALUE)

    def looks_right(self) -> bool:
        """An INA219 reads its configuration back as written. Anything else
        at that address (or nothing) does not."""
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


def find(bus_number=1, forced=False):
    try:
        from smbus2 import SMBus
        bus = SMBus(bus_number)
    except Exception as exc:
        if forced:
            print(f"humint-battery: no I2C bus: {exc}", file=sys.stderr)
        return None
    for addr in ADDRESSES:
        dev = INA219(bus, addr)
        if dev.looks_right():
            return dev
    return None


def percent(volts: float, cells: int) -> float:
    empty, full = 3.0 * cells, 4.2 * cells
    return max(0.0, min(100.0, (volts - empty) / (full - empty) * 100.0))


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
    print(f"humint-battery: battery at {pct:.0f}% and falling — locking the case file "
          "and powering off", flush=True)
    write({"present": True, "shutting_down": True, "percent": pct})
    oled("BATTERY LOW", "locking case file", "powering off")
    subprocess.run(["/opt/humint/bin/humint-ctl", "lock"], timeout=180,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["systemctl", "poweroff"])


def main() -> int:
    once = "--once" in sys.argv
    cfg = config()
    mode = cfg.get("BATTERY", "auto")
    if mode == "none":
        write({"present": False, "disabled": True})
        return 0
    cells = max(1, int(cfg.get("BATTERY_CELLS") or 2))
    threshold = float(cfg.get("BATTERY_SHUTDOWN_PERCENT") or 8)

    dev = find(forced=(mode == "waveshare"))
    if dev is None:
        write({"present": False})
        if once:
            print("No UPS HAT found on I2C (looked at 0x40-0x43).")
        if mode == "waveshare":
            print("humint-battery: BATTERY=waveshare but no INA219 answered", file=sys.stderr)
            return 1
        return 0       # auto, nothing fitted: not an error, and nothing to restart

    history, low = [], 0
    while True:
        try:
            v, ma = dev.volts(), dev.milliamps()
        except OSError as exc:
            print(f"humint-battery: read failed: {exc}", file=sys.stderr)
            time.sleep(POLL_SECONDS)
            continue
        history = (history + [v])[-6:]           # ~30 s of smoothing
        v_avg = sum(history) / len(history)
        pct = percent(v_avg, cells)
        charging = ma > 20                         # the HAT reads negative on battery
        state = {"present": True, "percent": round(pct, 1), "voltage": round(v_avg, 3),
                 "current_ma": round(ma, 1), "charging": charging, "cells": cells,
                 "updated": int(time.time())}
        if not charging and ma < -20:
            # A rough time-left: 18650s are ~2500 mAh, and the estimate is
            # only shown once the draw has settled.
            hours = (2500 * pct / 100) / abs(ma)
            if len(history) >= 6:
                state["minutes_left"] = int(hours * 60)
        write(state)
        if once:
            how = "charging" if charging else "on battery"
            print(f"Battery: {pct:.0f}% ({how}), {v_avg:.2f} V, {ma:+.0f} mA, {cells}S pack")
            return 0
        low = low + 1 if (not charging and pct <= threshold and len(history) >= 3) else 0
        if low >= LOW_READINGS:
            shut_down(pct)
            return 0
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    sys.exit(main())
