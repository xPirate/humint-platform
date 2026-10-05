"""A map on paper: the "Print map" PDF and the map page of a package.

One page, landscape by default: a title and a line saying what the map is
for, the picture filling the page, its corner coordinates so it can be
matched to a paper map or a GPS, a legend of what is actually drawn, the
scale's caveat, and where the tiles came from. The running header and footer
are the same as every other export, so a printed map carries the handling
line like the reports it travels with.
"""

import io
from datetime import datetime, timezone
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape, letter, portrait
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import Image as RLImage, Table, TableStyle

import map_render
import report_pdf
from geo import maidenhead_locator
from report_pdf import FONT_BOLD, FONT_REGULAR

PAPERS = {"letter": letter, "a4": A4}


def _coord(lat: float, lon: float) -> str:
    return f"{abs(lat):.5f}°{'N' if lat >= 0 else 'S'} {abs(lon):.5f}°{'E' if lon >= 0 else 'W'}"


def _san(text) -> str:
    return report_pdf._sanitize_for_builtin_font(str(text or ""))


def image_px_for(paper: str, orientation: str) -> tuple:
    """Pixel size to render for a page, at about 150 dpi -- sharp in print,
    and a sane number of tiles."""
    w, h = _pagesize(paper, orientation)
    usable_w = w - 1.1 * inch
    usable_h = h - 2.35 * inch
    return int(usable_w / inch * 150), int(usable_h / inch * 150)


def _pagesize(paper: str, orientation: str):
    size = PAPERS.get(paper, letter)
    return landscape(size) if orientation != "portrait" else portrait(size)


def build_map_pdf(img, meta: dict, *, title: str, note: Optional[str], paper: str,
                  orientation: str, generated_by: str) -> bytes:
    buf = io.BytesIO()
    pagesize = _pagesize(paper, orientation)
    w, h = pagesize
    c = rl_canvas.Canvas(buf, pagesize=pagesize)
    c.setTitle(title)
    c.setAuthor(generated_by)
    margin = 0.55 * inch
    now = datetime.now(timezone.utc)

    # Running header and footer, as on every export.
    c.setFont(FONT_REGULAR, 7.5)
    c.setFillColor(colors.HexColor("#777777"))
    c.drawString(margin, h - 0.35 * inch, _san(report_pdf.header_label()))
    c.drawRightString(w - margin, h - 0.35 * inch, now.strftime("%Y-%m-%d %H:%M UTC"))
    c.drawString(margin, 0.3 * inch, _san(report_pdf.PDF_FOOTER_NOTE))

    # Title and purpose.
    c.setFillColor(colors.HexColor("#111111"))
    c.setFont(FONT_BOLD, 15)
    c.drawString(margin, h - 0.72 * inch, _san(title)[:110])
    c.setFont(FONT_REGULAR, 8.5)
    c.setFillColor(colors.HexColor("#444444"))
    sub = f"Printed {now.strftime('%Y-%m-%d %H:%M UTC')} by {generated_by}"
    if note:
        sub = f"{note}  ·  {sub}"
    c.drawString(margin, h - 0.92 * inch, _san(sub)[:180])

    # The picture.
    top = h - 1.08 * inch
    bottom = 1.15 * inch
    box_w = w - 2 * margin
    box_h = top - bottom
    iw, ih = img.size
    scale = min(box_w / iw, box_h / ih)
    dw, dh = iw * scale, ih * scale
    x = margin + (box_w - dw) / 2
    y = bottom + (box_h - dh) / 2
    c.drawImage(ImageReader(img), x, y, dw, dh)
    c.setStrokeColor(colors.HexColor("#333333"))
    c.setLineWidth(0.8)
    c.rect(x, y, dw, dh)

    # Corner coordinates, small, outside the frame.
    south, west, north, east = meta["bbox"]
    c.setFont(FONT_REGULAR, 6.5)
    c.setFillColor(colors.HexColor("#555555"))
    c.drawString(x, y + dh + 3, _coord(north, west))
    c.drawRightString(x + dw, y + dh + 3, _coord(north, east))
    c.drawString(x, y - 9, _coord(south, west))
    c.drawRightString(x + dw, y - 9, _coord(south, east))
    centre_lat, centre_lon = (south + north) / 2, (west + east) / 2
    c.drawCentredString(x + dw / 2, y - 9,
                        f"Centre {_coord(centre_lat, centre_lon)} · grid {maidenhead_locator(centre_lat, centre_lon)}")

    # Legend.
    ly = 0.72 * inch
    lx = margin
    c.setFont(FONT_BOLD, 7.5)
    c.setFillColor(colors.HexColor("#222222"))
    c.drawString(lx, ly, "Key")
    lx += 0.32 * inch
    c.setFont(FONT_REGULAR, 7.5)
    for label, hexc, kind in map_render.legend_items(meta):
        col = colors.HexColor(hexc)
        if kind == "fill":
            c.setFillColor(col)
            c.setStrokeColor(col)
            c.rect(lx, ly - 1, 9, 7, fill=1, stroke=0)
        else:
            c.setStrokeColor(col)
            c.setLineWidth(2.2)
            if kind == "dash":
                c.setDash(4, 3)
            c.line(lx, ly + 2.5, lx + 14, ly + 2.5)
            c.setDash()
        c.setFillColor(colors.HexColor("#222222"))
        step = 9 if kind == "fill" else 14
        c.drawString(lx + step + 3, ly, _san(label))
        lx += step + 10 + c.stringWidth(_san(label), FONT_REGULAR, 7.5)
        if lx > w - 2.2 * inch:
            lx = margin + 0.32 * inch
            ly -= 11

    # Provenance and caveats.
    bits = []
    if meta.get("attribution"):
        bits.append(f"Map: {meta['attribution']}")
    elif meta.get("source"):
        bits.append(f"Map: {meta['source']}")
    if meta.get("tiles_missing"):
        bits.append(f"{meta['tiles_missing']} of {meta['tiles']} map tiles were not available "
                    "(not downloaded, or no connection) and are shown as plain grid")
    bits.append("Scale bar is true at the centre of the map")
    counts = meta.get("counts") or {}
    shown = ", ".join(f"{n} {k}" for k, n in counts.items() if n)
    if shown:
        bits.append(f"Shown: {shown}")
    c.setFont(FONT_REGULAR, 6.5)
    c.setFillColor(colors.HexColor("#666666"))
    c.drawString(margin, 0.5 * inch, _san("  ·  ".join(bits))[:230])

    c.showPage()
    c.save()
    return buf.getvalue()


def map_flowables(img, meta: dict, content_width: float, styles: dict) -> list:
    """The map as a block inside a package: the picture, then its corners and
    key as one caption line."""
    iw, ih = img.size
    width = content_width
    height = width * ih / iw
    max_h = 6.3 * inch
    if height > max_h:
        height = max_h
        width = height * iw / ih
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    picture = RLImage(buf, width=width, height=height)
    picture.hAlign = "LEFT"
    south, west, north, east = meta["bbox"]
    caption = (f"North-west {_coord(north, west)}; south-east {_coord(south, east)}. "
               "Zones are coloured by environment (green permissive → red non-permissive, "
               "dark red denied, grey unknown); routes are blue unless assessed, dashed when drawn "
               "as a plan; a circle marks where a route starts and a square where it ends.")
    if meta.get("attribution"):
        caption += f" Map: {meta['attribution']}."
    if meta.get("tiles_missing"):
        caption += f" {meta['tiles_missing']} map tiles were not available and are shown as grid."
    t = Table([[picture]], colWidths=[width])
    t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#555555")),
                           ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                           ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    t.hAlign = "LEFT"
    return [t, report_pdf._plain(caption, styles["caption"] if "caption" in styles else styles["meta"])]
