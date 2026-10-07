# HUMINT Field — privacy policy

*Applies to the Android app **HUMINT Field** (`org.humint.field`).
Last updated: 5 October 2026.*

HUMINT Field is a reporting tool for teams that run their own HUMINT Platform
console. It is open source: everything below can be checked in the code at
<https://github.com/xPirate/humint-platform/tree/main/android>.

## The short version

- The developer of this app **receives no data from it**, ever.
- The app has **no analytics, no advertising, no crash reporting** and does
  not use Google Play Services.
- What you write stays **encrypted on your phone** until you choose to send it
  to **your own team's console**, by scanning that console's QR code.

## What the app handles

Only what you put into a report:

| Data | When | Why |
|---|---|---|
| Report text (the form you fill in) | When you type it | It is the report. |
| Precise location | While a report is open on screen, if you allow it | To record where the observation was made. |
| A route's track (location over time) | Only while you are recording a route you started yourself — a notification shows the whole time, and it stops when you press Stop | To record the way you went, for a Route report. |
| An area's corners | When you press "Drop a corner here" | To mark the edge of an area, for an Area report. |
| Photos and video | When you take them with the app's camera | Attached to the report. |
| Voice recordings | When you press record | Attached to the report. |
| Images you pick ("Add image") | When you choose them in Android's photo picker | Attached to the report. The app sees only the images you pick, once; it cannot browse your gallery. |

## Where it is kept

- **On your phone**, in the app's private storage, encrypted with a key that
  needs both your PIN and the phone's hardware keystore. The app excludes this
  data from Android cloud backups. While a route is being recorded with the
  app locked, its points are encrypted under the phone's hardware keystore
  alone, and moved under your PIN the next time you open the app.
- **On your team's console**, once you send it. The console is a server your
  own team or organisation runs; it is not operated by the app's developer.
  Your team decides how long it keeps reports and who can see them. Ask your
  team's administrator about that data.

The app does **not** store the console's address or access token. They are
read from the QR code at the moment of sending and discarded when sending
finishes.

## Sharing

The app sends report data to one place only: the console whose QR code you
scan. It is not sold, not shared with third parties, and not sent to the
developer.

**In transit:** the connection is encrypted when your team's console uses
HTTPS. Consoles on a private local network may use plain HTTP; ask your
administrator which yours uses.

## Retention and deletion

- **Sent reports** are erased from the phone after a successful upload.
- **Unsent reports** stay on the phone until you send or discard them.
- **Discarding a report** deletes it and its attachments from the phone.
- **Uninstalling the app**, or using *Erase and start again* on the lock
  screen, deletes everything the app holds on the phone.
- Data already on a console is controlled by the team that runs it.

## Permissions

| Permission | Used for |
|---|---|
| Camera | Taking photos and video for a report, and scanning the console's QR code. |
| Microphone | Voice memos and video sound. |
| Location (precise) | Recording where an observation was made, while a report is open; recording a route you start. |
| Foreground service (location) | Keeping a route recording running with the screen off, with a notification. |
| Notifications | Showing that a route is being recorded, with a Stop button. |
| Prevent phone from sleeping | Keeping GPS readings arriving while a route records with the screen off. Released when you press Stop. |
| Internet | Sending reports to your team's console. |

## Children

The app is intended for adults working in teams and is not directed at
children.

## Changes and contact

Changes to this policy are published at this address with a new date, and are
visible in the repository's history. Questions: open an issue at
<https://github.com/xPirate/humint-platform/issues>.
