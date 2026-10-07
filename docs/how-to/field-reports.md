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
   | Route | A way you walk or drive, recorded as you go (1.6). |
   | Area | The edge of something, marked corner by corner (1.6). |
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

   Tap any attachment on the report to check it before you send: a photo
   opens full screen, a clip or voice memo opens a player (it pauses if you
   leave the app). The recording is decrypted into memory to play — no
   unencrypted copy is ever written to the phone.
6. Press **Mark ready to send**. If something required is missing, it tells
   you what.

Reports stay on the phone, encrypted, until sent. Back out and it stays a
draft. To throw one away, use the discard option on the report.

### Record a route

1. **+** → **Route**. Give it a name and say **why** you are recording it —
   what it avoids, when it works, who uses it.
2. If the screen shows an amber battery warning, fix it first with
   **Open battery settings** — otherwise many phones stop GPS once the
   screen is off and the route comes out as a straight line.
   Press **Start recording**. Allow notifications if asked; a **Recording a
   route** notification stays up the whole time.
3. Put the phone away and walk (or drive). It keeps recording with the screen
   off and the app locked.
4. When you arrive, press **Stop** — in the notification, or on the report.
5. Check the sketch, length and time. **Continue recording** adds another leg
   (the gap is kept, not drawn as a straight line); **Clear** starts again.
6. **Mark ready to send.**

The app asks GPS for a fix every two seconds and keeps one whenever you
have moved at least 5 m (more when the fix is rough), so standing at a
checkpoint does not scribble on the track. Fixes within about 35 m are kept
as they come; rougher ones, up to 100 m, are used only when nothing better
has come for 20 seconds and you have clearly moved. After **Stop**, the
report says how many fixes arrived and were kept, and warns if GPS stopped —
see [troubleshooting](troubleshooting.md#a-route-didnt-record-or-is-a-straight-line).

**Security:** while a route is recording, and until you next open the app,
its points are held under a key on the phone but not under your PIN. Stop and
open the app to put them under the PIN with the rest of the report.

### Mark an area

1. **+** → **Area**. Name it and set **How workable**.
2. Walk to the first corner and press **Drop a corner here**. Wait for a GPS
   accuracy of 25 m or better if you can — the screen tells you.
3. Walk the edge, dropping a corner at each turn, in order. **Undo last** if
   you misplace one.
4. Three corners at least. **Mark ready to send.**

Keep the app open while you walk the edge: it reads position only while it is
on screen. (The fingerprint shortcut saves retyping the PIN if it locks.)

### Camera tips

- **Flash** is **off** by default. Tap the flash button to cycle through
  **Flash auto**, **Flash on** and **Light** (the torch stays on while you
  frame).
- **Zoom:** pinch, double-tap for 2×, or tap the **1 / 2 / 5 / 10** chips
  (whatever the camera can reach).
- **Focus:** tap where you want it sharp.
- **Landscape:** turn the phone sideways and shoot. The buttons stay where
  they are, but the photo or clip is saved the way you held the phone — a
  wide building comes out wide. For video, turn the phone *before* you press
  record; the orientation is fixed when recording starts.

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

A Route or Area report shows a drawing of the shape and its length, points
and time on the card.

Each card shows the device, whose account it belongs to, when the sender saw
it, and — if the phone had a fix — position, accuracy and their own words
about where they were. It's laid out by form: a Vehicle sighting shows plate,
colour, make; a Signal shows frequency, band and mode above what was heard.

- **Photos** — click a thumbnail for the full frame.
- **Clips and voice memos** — play in the card, or open them full size from
  the attachment preview; nothing downloads until you press play, and you
  can skip around a long clip without downloading all of it.
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
   first photo becomes its portrait if it hasn't one. A **Route** report
   makes a Route record with the walked line and its times; an **Area** report
   makes a Zone with the corners as its edge.
4. Finish the report: add what you know, link the records it touches, and
   confirm it the normal way ([Write reports](reports-and-exports.md)).

### Set it aside

**Set aside**, with a reason if it's worth recording. Nothing is deleted; it
moves to *Set aside* and stays findable. What the team was told — including
what turned out to be nothing — is part of the record.

An accepted submission keeps a link to the report it became.
