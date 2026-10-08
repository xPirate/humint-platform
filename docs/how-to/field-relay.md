# How to run a team relay

A **team relay** is a tablet a team takes on a deployment. Each night the
team's phones send their reports to the tablet over its own hotspot, exactly
as they would send to the console. The team lead reviews them on the tablet,
tags them against the team's priorities, and presses **Sync** to send
everything home — over the VPN when there is a connection, or back at the
office.

It exists so a lost phone costs at most a day's reports, not the whole trip.

| | |
|---|---|
| **Needs** | Field app 1.7 or later on the tablet and the phones; console v1.10 or later (run `db/migrate-v1.10-relays.sql`). |
| **Tablet** | Any Android 10+ tablet with a hotspot. Tested on a Galaxy Tab S9+. |
| **Who** | An admin to register and provision it; a team lead to hold it. |

---

## Before the team leaves

### 1. Register the relay on the console

**Admin settings → Field devices → Team relays → Register a relay.**

- **What to call it** — e.g. *Team Alpha tablet*.
- **Keep-alive** — how long the relay may go without syncing before the
  console drops its key. **3 days** by default; 1 to 14 allowed.

  | Engagement | Check-ins | Keep-alive |
  |---|---|---|
  | 2-day protest, hotel with internet | Nightly | 3 days |
  | Week-long event, patchy connection | Every 2–3 days | 4–5 days |
  | Weeks, little or no connection | Rarely | Short (2–3 days); plan to re-provision on return |

- **Team** — the analysts whose phones will send to it. Reports are credited
  to these accounts, and only these.
- **Where the tablet looks for this console** — one address per line, tried
  in order when the lead presses Sync. **The VPN address first**, the office
  address second.

Press **Register and show its code**. A provisioning QR appears, valid for
30 minutes, usable once.

If several relays are needed, register and provision each one before the
team leaves. Each has its own key and keep-alive and syncs on its own.

### 2. Make the tablet a relay

1. Install the Field app and set the **lead's PIN** on first launch.
2. **Settings → Team relay → Use this device as a team relay.** The app
   switches to the relay's screens: **Inbox · Priorities · Phones · Relay**.
3. With the tablet on the office network: **Relay → Provision from the
   console**, and scan the QR.
4. **Check the fingerprint.** The Relay tab shows *Console fingerprint
   ABCD EF01 …*; it must match the one on the console's Team relays page. If
   it does not, stop and tell the console's admin.

### 3. Set the team's PINs

**Relay → Team PINs.** Every change asks for the lead's PIN.

- **Second team member** — their own PIN onto the same relay, so the relay
  can still be opened and synced if the lead cannot.
- **Duress PIN** — typed at the lock screen, it **erases every report,
  photo, phone and key on the relay** and then opens it empty, under the same
  PIN, as if nothing were wrong. It cannot be undone. Choose a PIN nobody will
  type by accident — not a near-miss of a real one.

### 4. Write the team's priorities

**Priorities → Add.** One line each, ranked, plus *what would answer it* —
the names, places and words to look for. The relay uses those words to
suggest which priority an incoming report answers. It never tags on its own.

### 5. Add the team's phones

**Phones → Add a phone.** Pick the analyst from the team list, name the
phone, and the relay shows its code. Each phone gets its own code, so every
report says whose phone it came from. **Show code** issues a fresh one at any
time; the old code stops working.

---

## On site

### Start the relay

1. Turn on the tablet's hotspot: **Settings → Connections → Mobile Hotspot**.
   Use the hotspot, not hotel Wi-Fi — hotel networks usually stop devices
   reaching each other.
2. **Relay → Turn on.** A **Team relay is on** notification shows while it
   runs. It keeps running with the screen off and the app locked.
3. If the Relay tab shows an amber battery warning, press **Open battery
   settings** and set HUMINT Field to **Unrestricted**, or Samsung may stop
   the relay overnight.
4. Keep the tablet on a charger.

### Each night

1. Analysts join the tablet's hotspot.
2. On each phone: **Send → Scan the console's code**, and scan that phone's
   code from the relay's **Phones** tab. The phone says **Sent to the team
   relay** and clears its queue, as it does after sending to the console.

Reports arrive encrypted to a key only a team PIN can open. If they arrive
while the relay is locked, the Relay tab shows **N waiting to be opened**;
they open the moment someone unlocks it.

### Review

- **Inbox** — everything received, newest first. Filter by **Untagged** to
  see what nobody has looked at yet, or by priority.
- **Open a report** — the form's fields, the position, a route's sketch,
  photos and clips. Under **Answers which priority?** tap each priority it
  answers (suggestions are marked), or **Background — answers none**. Add a
  **lead's note**; it goes home with the report.
- **Priorities** — each priority's reports and last report time, and its
  status (*Open, Partly answered, Answered, Dropped*). A priority with nothing
  new in 24 hours is flagged amber, so the gap shows before tomorrow's
  tasking.

### Sync whenever you can

With the VPN connected: **Relay → Sync**.

1. The relay tries each console address in turn.
2. It asks the console to sign a random challenge and checks the signature
   against the key from provisioning. **Something that cannot prove it is
   your console gets nothing** — not a report, not the relay's token.
3. It checks in, which resets the keep-alive.
4. It sends each report and its files, and erases each from the tablet once
   the console confirms it.

On a slow link, tick **Reports and photos now, video later**: reports go
home now and their clips follow on a later Sync.

A Sync with nothing to send still counts as a check-in. The Relay tab shows
how long is left before one is due.

### Back up to USB

**Relay → Back up to USB → Back up now.** Type a team PIN, then pick the USB
drive in the file picker. The backup is encrypted and opens two ways:

- **At the console, with no PIN** — Admin → Field devices → Team relays →
  **Import a USB backup**. Its reports go into *From the field* exactly as a
  Sync would put them, and anything already there is skipped. This is the way
  back for a tablet that broke or did not come home.
- **With the team PIN** it was made with.

Keep the stick apart from the tablet, or there is no point. A backup made
before the relay was provisioned opens only with the PIN.

---

## Coming home

1. On the office network, **Relay → Sync**. Everything left goes home.
2. On the console, **Review → From the field**. Relayed reports say
   *Sonim 3 (via Team Alpha tablet)*, are credited to the analyst, and show
   the lead's priority tags and note.

### If the key expired

If the relay did not check in within its keep-alive, the console dropped its
key and Sync says so. **Nothing on the tablet is lost.** At the office, on the
console's Team relays page, press **Re-provision** with the tablet and the
team in front of you, and scan the new code on the tablet. The old key stops
working that moment. Then Sync.

An admin can also **Extend** a live relay's keep-alive (restart the clock
from now) when the team has checked in some other way, or **Revoke** it at
once if the tablet is lost.

---

## What protects what

| If… | Then… |
|---|---|
| A phone is lost | It holds at most what it had not yet sent to the relay. |
| The relay is seized while running | Reports on it are sealed to a key that needs a team PIN; the server that took them in cannot read them back. |
| Someone is made to unlock it | The duress PIN erases it instead of opening it. A real PIN given up still opens it. |
| The relay goes quiet | Its key is dropped after the keep-alive; it cannot reach the console again until re-provisioned in person. |
| Something on the hotel network poses as the console | Sync refuses it: the signature check fails before anything is sent. |
| The tablet breaks | Import its latest USB backup at the console. |

What a relay does **not** do: extract, merge or create records. That stays at
the console, so there is only ever one place deciding what the case file says.

## Troubleshooting

- **Phones cannot reach the relay** — they must be on the tablet's hotspot,
  and the relay must be on. Show the phone's code again: the address in it is
  the hotspot's.
- **"Could not reach the console at any of its addresses"** — the VPN is not
  connected, or the console's addresses changed. Edit them on the console's
  Team relays page and re-provision.
- **"Something … could not prove it is your console"** — stop. Do not retry
  on that network. Tell the console's admin.
- **"This relay's key expired"** — see *If the key expired* above.
- **The relay stopped overnight** — set battery use to *Unrestricted*. It
  restarts itself if Android kills it, but Samsung's battery manager can stop
  it starting again.
