#!/usr/bin/env python3
"""Draw a few short lines on a 0.96" SSD1306 OLED and exit.

Each call paints one frame and returns, so the unlock script and the status
loop can take turns on the display without fighting over the I2C bus. On a Pi
with no screen attached — the common case — every call does nothing and
exits 0, so the rest of the appliance works unchanged on bare hardware.

Usage: oled_show.py "title line" "line two" "line three" ...
The first line is drawn a little larger as a heading.
"""
import os
import sys

ADDR = int(os.environ.get("HUMINT_OLED_ADDR", "0x3C"), 16)
PORT = int(os.environ.get("HUMINT_OLED_I2C", "1"))
WIDTH, HEIGHT = 128, 64


def mode():
    """auto / ssd1306 / none, from the saved appliance config."""
    try:
        for line in open("/var/lib/humint/env"):
            if line.startswith("OLED="):
                return line.split("=", 1)[1].strip().strip('"').lower() or "auto"
    except OSError:
        pass
    return "auto"


def main(lines):
    if mode() == "none":
        return 0
    try:
        from luma.core.interface.serial import i2c
        from luma.oled.device import ssd1306
        from PIL import ImageDraw, ImageFont
    except Exception:
        return 0  # libraries not installed — nothing to draw on
    try:
        device = ssd1306(i2c(port=PORT, address=ADDR), width=WIDTH, height=HEIGHT)
    except Exception:
        return 0  # no screen wired up; stay quiet

    try:
        big = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 13)
        small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 11)
    except Exception:
        big = small = ImageFont.load_default()

    from luma.core.render import canvas
    with canvas(device) as draw:  # type: ignore[arg-type]
        y = 0
        for i, line in enumerate(lines[:5]):
            font = big if i == 0 else small
            draw.text((0, y), line[:21], font=font, fill=255)
            y += 15 if i == 0 else 12
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception:
        sys.exit(0)  # the screen must never take down the caller
