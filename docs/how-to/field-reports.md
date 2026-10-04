# How to handle field reports

Two halves: an analyst writes a report on the **HUMINT Field** app with no
signal, then sends it when back in range; somebody on the console reviews it.

Setting up phones is in [Set up field devices](field-devices.md).

---

## On the phone

The bottom bar: **Reports** · **Send** · **+** (new report) · **Lock** ·
**Settings**.

### Write a report

1. Unlock with your PIN (or fingerprint).
2. Press the **+** in the middle of the bottom bar and pick a form:

   | Form | For |
   |---|---|
   | Signal | Something heard — frequency, band, mode, what was said. |
   | Person | Someone to describe. |
   | Vehicle | Plate, colour, make, model. |
   | Activity | A SALUTE report: Size, Activity, Location, Unit, Time, Equipment. |
   | Bearing | A DF cut. |
   | Place | Somewhere worth recording. |
   | Note | Anything else. |

3. Fill it in. Everything saves as you type — there's no Save button. Set the
   urgency — **Routine, Priority, Immediate or Flash**; the console sorts its
   queue by it.
4. Location is captured while the report is open, if the phone has a fix. Add
   **Where you were, in words** if it helps.
5. Attach what you have:
   - **Photo** — opens the camera (see tips below).
   - **Video** / **Record** — a clip or voice memo.
   - **Add image** — a screenshot or saved picture, for something seen on a
     screen. Pick up to 10 from Android's photo picker (25 MB each). The app
     only sees the images you pick; the originals stay in your gallery —
     delete them yourself if they shouldn't stay there.
6. Press **Mark ready to send**. If something required is missing, it tells
   you what.

Reports stay on the phone, encrypted, until sent. Back out and it stays a
draft. To throw one away, use the discard option on the report.

### Camera tips

- **Flash** is **off** by default. Tap the flash button to cycle through
  **Flash auto**, **Flash on** and **Light** (the torch stays on while you
  frame).
- **Zoom:** pinch, double-tap for 2×, or tap the **1 / 2 / 5 / 10** chips
  (whatever the camera can reach).
- **Focus:** tap where you want it sharp.

### Send what's ready

1. Get in range of the console's network.
2. **Send** tab → **Scan the console's code**.
3. Point the camera at the QR on the console screen or a printed card, inside
   the bracket. It turns amber with **"Code found — hold steady"** when it
   sees a code, and **green** with a buzz when it has read it.
4. Ready reports upload. Drafts stay on the phone.

If a send fails, the reason stays on the report's card on the Reports tab.

The code is forgotten as soon as the upload finishes. Next time, scan again.

### Lock it

Press **Lock** on the bottom bar. It also locks itself 90 seconds after you
leave the app.

**Forgot the PIN?** The lock screen offers **Erase and start again**. Unsent
reports are gone for good; sent ones are safe on the console.

---

## On the console

**Review → From the field.** The tab appears once a device is enrolled or
anything has arrived.

Nothing here is in the case file yet, or searchable. The most urgent are at
the top.

### Review one

Each card shows the device, whose account it belongs to, when the sender saw
it, and — if the phone had a fix — position, accuracy and their own words
about where they were. It's laid out by form: a Vehicle sighting shows plate,
colour, make; a Signal shows frequency, band and mode above what was heard.

- **Photos** — click a thumbnail for the full frame.
- **Clips** — play in the card; nothing downloads until you press play.
- **Look it up on the map** — jumps to the spot with the address and nearby
  businesses, usually how coordinates become a Location.

If a field shows in amber under an odd name, the report came from an app
newer than the console. The value is correct; accept as normal and ask an
admin to upgrade the console.

### Accept it

1. Decide on **Also start a … record** (ticked when the form describes a
   thing — a Vehicle, Person or Location with the details filled in, linked to
   the draft and marked as needing a check). Untick it if the record already
   exists or the sighting is too thin. A **Bearing** never offers one — a
   single cut is a line, not a place.
2. Press **Accept as a draft report**. The report opens with a provenance block
   (device, time, place, accuracy) and the photos attached.
3. If a record was created, **all photos and video go onto it too**, and the
   first photo becomes its portrait if it hasn't one.
4. Finish the report: add what you know, link the records it touches, and
   confirm it the normal way ([Write reports](reports-and-exports.md)).

### Set it aside

**Set aside**, with a reason if it's worth recording. Nothing is deleted; it
moves to *Set aside* and stays findable. What the team was told — including
what turned out to be nothing — is part of the record.

An accepted submission keeps a link to the report it became.
