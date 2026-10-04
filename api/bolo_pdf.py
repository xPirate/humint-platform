"""The BOLO board on paper, for a wall.

WHY THIS EXISTS

The board in the app is only seen by people looking at the app. A team that
works in a building, on a gate or in vehicles wants the lookout list where
they already look — pinned up by the door, in a folder on the dashboard —
and wants it readable at a glance from a step away: a face, a name, how
urgent, and why.

Two layouts:

  grid    six to a page, three across. The whole board on a sheet or two,
          for a noticeboard.
  single  one to a page, the photograph large, with everything that helps
          somebody recognise them and what to do if they do.

Only active entries print. A closed lookout on a wall is worse than none:
the wall is not updated when the board is, so the sheet says when it was
printed and, where an entry has one, until when it holds.
"""

import io
from datetime import date, datetime, timezone

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (KeepTogether, PageBreak, Paragraph, Spacer, Table,
                                TableStyle)

import report_pdf
from report_pdf import (FONT_BOLD, FONT_REGULAR, PAGE_SIZE, PDF_FOOTER_NOTE, _IntelDocTemplate,
                        _NumberedCanvas, _format_value, _styles, header_label)

URGENCY = {
    "Critical": ("#a01810", "CRITICAL"),
    "Urgent": ("#b35c00", "URGENT"),
    "Caution": ("#0a5f57", "CAUTION"),
    "Info": ("#44564b", "INFO"),
}
MARGIN = 0.5 * inch


def _esc(text):
    return (str(text) if text is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _age(dob) -> str | None:
    if not dob:
        return None
    if isinstance(dob, str):
        try:
            dob = date.fromisoformat(dob[:10])
        except ValueError:
            return None
    today = date.today()
    return str(today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day)))


def identifiers(entity: dict) -> list[tuple[str, str]]:
    """What helps a person recognise this record on sight, most useful first."""
    d = entity.get("details") or {}
    kind = entity.get("entity_type")
    out = []
    if kind == "person":
        if d.get("aliases"):
            out.append(("AKA", ", ".join(d["aliases"]) if isinstance(d["aliases"], list) else str(d["aliases"])))
        if d.get("date_of_birth"):
            age = _age(d["date_of_birth"])
            out.append(("Born", f"{_format_value(d['date_of_birth'])}" + (f" (age {age})" if age else "")))
        if d.get("physical_description"):
            out.append(("Description", d["physical_description"]))
        if d.get("occupation"):
            out.append(("Occupation", d["occupation"]))
    elif kind == "vehicle":
        described = " ".join(str(d[k]) for k in ("color", "make", "model", "style") if d.get(k))
        if described:
            out.append(("Vehicle", described))
        if d.get("license_plate"):
            out.append(("Plate", d["license_plate"] + (f" ({d['plate_region']})" if d.get("plate_region") else "")))
        if d.get("notes"):
            out.append(("Marks", d["notes"]))
    elif kind == "location" and d.get("address"):
        out.append(("Address", d["address"]))
    if d.get("alignment"):
        out.append(("Alignment", d["alignment"]))
    if not out and entity.get("description"):
        out.append(("Notes", entity["description"]))
    return out


def associations(entity: dict, vehicles: dict) -> list[tuple[str, str]]:
    """Live links worth putting on a lookout: what they drive, where they go,
    who they are seen with. Expired links are left off — a lookout is about
    now."""
    out = []
    for rel in entity.get("relationships") or []:
        if rel.get("expired"):
            continue
        kind = rel.get("other_entity_type")
        name = rel.get("other_entity_name")
        if kind == "vehicle":
            v = vehicles.get(rel.get("other_entity_id")) or {}
            plate = v.get("license_plate")
            out.append(("Vehicle", name + (f" — {plate}" if plate and plate not in name else "")))
        elif kind == "location":
            out.append(("Place", name))
        elif kind == "person" and entity.get("entity_type") == "vehicle":
            out.append(("Driven by", name))
    return out[:4]


def _st():
    s = _styles()
    s["banner"] = ParagraphStyle("BoloBanner", fontName=FONT_BOLD, fontSize=26, leading=30,
                                 textColor=colors.white, alignment=TA_CENTER)
    s["banner_sub"] = ParagraphStyle("BoloBannerSub", fontName=FONT_REGULAR, fontSize=9.5, leading=12,
                                     textColor=colors.white, alignment=TA_CENTER)
    s["card_name"] = ParagraphStyle("BoloName", fontName=FONT_BOLD, fontSize=13, leading=15.5)
    s["card_name_big"] = ParagraphStyle("BoloNameBig", fontName=FONT_BOLD, fontSize=28, leading=32)
    s["card_fact"] = ParagraphStyle("BoloFact", fontName=FONT_REGULAR, fontSize=8.5, leading=10.5)
    s["card_reason"] = ParagraphStyle("BoloReason", fontName=FONT_BOLD, fontSize=9, leading=11.5)
    s["band"] = ParagraphStyle("BoloBand", fontName=FONT_BOLD, fontSize=9, leading=11,
                               textColor=colors.white, alignment=TA_CENTER)
    s["band_big"] = ParagraphStyle("BoloBandBig", fontName=FONT_BOLD, fontSize=16, leading=20,
                                   textColor=colors.white, alignment=TA_CENTER)
    s["note"] = ParagraphStyle("BoloNote", fontName=FONT_BOLD, fontSize=11, leading=14, alignment=TA_CENTER)
    return s


def _banner(label: str, count: int, printed: datetime, width: float, s) -> Table:
    t = Table([[Paragraph("BE ON THE LOOKOUT", s["banner"])],
               [Paragraph(f"{_esc(label)} · {count} active · printed "
                          f"{printed.strftime('%Y-%m-%d %H:%M UTC')} — check the board for changes",
                          s["banner_sub"])]],
              colWidths=[width])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#111111")),
                           ("TOPPADDING", (0, 0), (-1, 0), 10), ("BOTTOMPADDING", (0, -1), (-1, -1), 8)]))
    return t


def _photo_or_blank(entry, width, height, s):
    img = report_pdf.portrait_flowable(entry.get("portrait_path"), width, height) \
        if entry.get("portrait_path") else None
    if img:
        return img
    initials = "".join(w[0] for w in (entry["entity"]["name"] or "?").split()[:2]).upper()
    t = Table([[Paragraph(f"<font size='{int(height / 3)}'>{_esc(initials)}</font><br/>"
                          f"<font size='8'>no photograph on file</font>",
                          ParagraphStyle("ph", fontName=FONT_BOLD, alignment=TA_CENTER,
                                         textColor=colors.HexColor("#777777"),
                                         leading=height / 3 + 4))]],
              colWidths=[width], rowHeights=[height])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#e6e6e6")),
                           ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    return t


def _band(entry, width, s, big=False):
    colour, word = URGENCY.get(entry.get("urgency") or "", ("#444444", "LOOKOUT"))
    kind = (entry["entity"].get("entity_type") or "").upper()
    t = Table([[Paragraph(f"{word} · {kind}", s["band_big" if big else "band"])]], colWidths=[width])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(colour)),
                           ("TOPPADDING", (0, 0), (-1, -1), 4 if not big else 7),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 4 if not big else 7)]))
    return t


def _card(entry, width, s):
    """One lookout in the grid: band, face, name, the few facts that matter."""
    entity = entry["entity"]
    inner = width - 12
    parts = [_band(entry, inner, s), Spacer(1, 4),
             _photo_or_blank(entry, inner, inner * 1.2, s), Spacer(1, 5),
             Paragraph(_esc(entity["name"]), s["card_name"])]
    for label, value in (identifiers(entity) + associations(entity, entry["vehicles"]))[:4]:
        text = value if len(value) <= 90 else value[:87] + "…"
        parts.append(Paragraph(f"<b>{_esc(label)}:</b> {_esc(text)}", s["card_fact"]))
    if entry.get("reason"):
        reason = entry["reason"] if len(entry["reason"]) <= 160 else entry["reason"][:157] + "…"
        parts.extend([Spacer(1, 3), Paragraph(_esc(reason), s["card_reason"])])
    until = f" · until {_format_value(entry['expires_at'])}" if entry.get("expires_at") else ""
    parts.append(Paragraph(f"<font color='#666666'>Posted {_format_value(entry['created_at'])[:10]}{until}</font>",
                           s["card_fact"]))
    t = Table([[parts]], colWidths=[width])
    colour = URGENCY.get(entry.get("urgency") or "", ("#444444",))[0]
    t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 1.2, colors.HexColor(colour)),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                           ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    return t


def _single(entry, width, s, note):
    """One lookout to a page: the photograph large and everything that helps."""
    entity = entry["entity"]
    flow = [_band(entry, width, s, big=True), Spacer(1, 10)]
    # Sized so band, photo, facts, reason and note fit one Letter or A4 page;
    # a lookout that runs onto a second sheet is half of it missing from the
    # wall.
    photo_w = min(width * 0.5, 3.4 * inch)
    photo = _photo_or_blank(entry, photo_w, photo_w * 1.25, s)
    pt = Table([[photo]], colWidths=[width])
    pt.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER")]))
    flow.extend([pt, Spacer(1, 10), Paragraph(_esc(entity["name"]), s["card_name_big"]), Spacer(1, 6)])
    rows = identifiers(entity) + associations(entity, entry["vehicles"])
    if rows:
        t = Table([[Paragraph(f"<b>{_esc(k)}</b>", s["cell"]), Paragraph(_esc(v), s["cell"])] for k, v in rows],
                  colWidths=[1.3 * inch, width - 1.3 * inch], hAlign="LEFT")
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.HexColor("#dddddd")),
                               ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
        flow.append(t)
    if entry.get("reason"):
        flow.extend([Spacer(1, 10), Paragraph(_esc(entry["reason"]),
                                              ParagraphStyle("r", parent=s["card_reason"], fontSize=13, leading=17))])
    until = f" · in force until {_format_value(entry['expires_at'])}" if entry.get("expires_at") else ""
    flow.append(Paragraph(f"<font color='#666666'>Posted {_format_value(entry['created_at'])}{until} · "
                          f"ref {_esc(entity['id'])}</font>", s["meta"]))
    if note:
        flow.extend([Spacer(1, 14), Paragraph(_esc(note), s["note"])])
    return flow


def build_bolo_sheet(label: str, entries: list, layout: str, note: str | None, generated_by: str) -> bytes:
    s = _st()
    buf = io.BytesIO()
    doc = _IntelDocTemplate(
        buf, pagesize=PAGE_SIZE, leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN + 0.15 * inch, bottomMargin=MARGIN + 0.1 * inch,
        title=f"{label} — be on the lookout", author=generated_by,
        header_label=header_label(), footer_note=PDF_FOOTER_NOTE, report_ref="BOLO")
    width = doc.width
    printed = datetime.now(timezone.utc)
    story = []

    if not entries:
        story.extend([_banner(label, 0, printed, width, s), Spacer(1, 30),
                      Paragraph("Nothing is on the board.", s["note"])])
    elif layout == "single":
        for i, e in enumerate(entries):
            if i:
                story.append(PageBreak())
            story.extend([_banner(label, len(entries), printed, width, s), Spacer(1, 10)])
            story.extend(_single(e, width, s, note))
    else:
        per_row, per_page = 3, 6
        gap = 8
        col_w = width / per_row
        card_w = col_w - gap
        for start in range(0, len(entries), per_page):
            if start:
                story.append(PageBreak())
            story.extend([_banner(label, len(entries), printed, width, s), Spacer(1, 10)])
            chunk = entries[start:start + per_page]
            rows = []
            for r in range(0, len(chunk), per_row):
                cells = [_card(e, card_w, s) for e in chunk[r:r + per_row]]
                cells += [""] * (per_row - len(cells))
                rows.append(cells)
            grid = Table(rows, colWidths=[col_w] * per_row, hAlign="LEFT")
            grid.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                      ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                      ("RIGHTPADDING", (0, 0), (-1, -1), gap),
                                      ("BOTTOMPADDING", (0, 0), (-1, -1), gap)]))
            story.append(grid)
            if note:
                story.extend([Spacer(1, 4), Paragraph(_esc(note), s["note"])])

    doc.build(story, canvasmaker=_NumberedCanvas)
    return buf.getvalue()
