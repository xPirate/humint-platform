# HUMINT field server — a Raspberry Pi appliance

A flashable image that turns a Raspberry Pi into a self-contained, offline
console the whole team connects to. The Pi provides the Wi-Fi, runs the full
platform natively, and keeps the case file in an encrypted store that a PIN
unlocks at boot. It is meant to live in a bag on a battery while a team works
off-site, instead of the platform running on one person's laptop — and when
the team comes home, its work goes back into the HQ case through
[field sync](../../docs/how-to/field-sync.md).

It is an **appliance**, not a server you administer: no Docker, no build step
on the device, no internet needed at any point after flashing. PostgreSQL,
the API and the background worker are ordinary systemd services, installed
into the image when it is built.

What it does:

- the full console, served over **HTTPS** with a certificate the box issues
  itself (each device trusts it once);
- the case file **encrypted at rest**, opened by a PIN at boot;
- its own **Wi-Fi hotspot**, or a wired or client network;
- a **0.96" OLED** status screen, and/or a **touch-screen control panel** on a
  5" HDMI screen — PIN pad, dashboard, QR codes to join, menus — picked
  automatically from what is plugged in;
- a **battery gauge** for the Geekworm X1203 or Waveshare UPS HAT, with a clean
  lock-and-power-off before the battery dies — and a plug on screen when it
  is running on wall power;
- **field packages** that carry the deployment's work home to HQ for review.

---

## What you need

| | |
|---|---|
| **Board** | Raspberry Pi 4 (4 GB minimum, 8 GB better) or Pi 5. 64-bit. |
| **Storage** | An SD card (32 GB+, A2-rated) to boot. **Recommended:** boot from a USB-3 SSD (Pi 4) or NVMe (Pi 5) instead — database writes wear SD cards, and a card that loses power mid-write can corrupt the case file. |
| **Screen** | Any of: **none** (type the PIN blind); a **0.96" SSD1306 I2C OLED** (status pages and PIN prompt); the **Elecrow 5" 800×480 HDMI touch screen** (or another HDMI/DSI screen — the touch control panel). An OLED and a panel can both be fitted. |
| **Keyboard** | Needed for **first boot** (setting the PIN at base). In the field it is needed only **without a touch screen** — then the PIN is typed on it at every boot. A small foldable one lives in the bag. |
| **Battery** | A **Geekworm X1203** (Pi 5) or **Waveshare UPS HAT** (Pi 4) for the charge gauge and clean low-battery shutdown — or any USB-C power bank that can supply 5 V / 3 A (Pi 4) or 5 V / 5 A (Pi 5), shown on screen simply as external power. |
| **Build machine** | A Debian/Ubuntu x86-64 machine (or anything that runs Docker) with internet, to run pi-gen. |

---

## How it works

```
 power on
    │
 humint-display ── what screen is attached? (and sets up the 5" touch driver once)
    │
    ├─ touch panel ── PIN pad on screen ─┐
    └─ OLED / none ── "Enter unlock PIN", keyboard ─┤
                                                     ▼
                         try_unlock: cryptsetup open /srv/humint.img
                         (one count of wrong PINs for both; 5 and it stays locked)
                                                     │
 mount /srv/humint-data  ◄───────────────────────────┘
    │     ├── postgresql/   the case database (PostgreSQL 16 cluster)
    │     ├── humint.env    console settings + DB password
    │     ├── tls/          the box's CA and server certificate (keys)
    │     └── uploads/  map-packs/  tmp/
    ▼
 systemctl start humint.target
    ├── postgresql@16-main   (localhost only)
    ├── humint-api           (HTTPS on 443, user humintd)
    ├── humint-http          (port 80: the CA certificate, and redirects to HTTPS)
    └── humint-worker        (OCR, extraction, sweeps; user humintd)
```

Nothing that touches case data is enabled at boot. The database, the API and
the worker start only after the PIN has opened the store, and each unit
refuses to start if the store isn't mounted. Even the services' scratch files
(backup bundles, OCR pages) go to `tmp/` inside the store, never to the plain
SD card.

**Before deployment (once, at base):**

1. Build and flash the image, edit one config file on the card.
2. Power on **with a keyboard attached**. If a 5" touch screen is fitted, the
   box sets up its driver and reboots once. First boot then sets the
   hostname, asks you to **set the unlock PIN** (twice, on the keyboard),
   creates the encrypted store and the database inside it, issues the HTTPS
   certificate, starts the console, and switches to the field network. Allow
   5–10 minutes; the screen shows each step.
3. On each phone and laptop the team will use: join the field Wi-Fi, open
   `http://<hostname>.local/trust` (or scan the QR on the panel's **Trust**
   tab), and install the certificate. Check its fingerprint against the
   screen's.
4. Open the console, **create the admin account** (the first account made
   becomes admin). To work on HQ's case, restore an HQ backup
   (Admin → Backup & restore) — that also marks where the field's own work
   begins, for field sync. Add the analysts, and add the map packs you'll need
   (see Offline by design, below).
5. With a touch screen: **Menu → Calibrate touch** (four taps).
6. Power off.

**In the field (every day):**

1. Power on. The panel shows a PIN pad (or the OLED says "Enter unlock PIN").
2. Enter the PIN — on the touch screen, or on the keyboard. The store unlocks
   and the console starts (about a minute on a Pi 4).
3. The team joins the Pi's Wi-Fi (the panel's **Join** tab has a QR code for
   it) and works at `https://<hostname>.local` or the address on the screen.
   Phones submit field reports to it exactly as they do to the home console.
4. At the end, power off from the panel's **Menu → Shut down**, or
   `humint-ctl shutdown` — or **Lock case file** to re-lock without shutting
   down.

**Coming home:** Admin → Field sync → **Export field package**, carry the
`.zip` to HQ, and import it there. Everything waits in HQ's Review queue to be
accepted — see [Bring a field server's work home](../../docs/how-to/field-sync.md).

If the Pi is lost while off or locked, the case file is a LUKS2 volume that
needs the PIN; whoever finds it gets an OS and the app's code, not the case.

---

## Screens

`SCREEN=auto` (the default) looks at what is plugged in at every boot:

| Attached | Shows |
|---|---|
| Nothing | Nothing. Wait ~30 s after power-on and type the PIN blind on the keyboard, then Enter. |
| 0.96" OLED (I2C 0x3C/0x3D) | Status pages: network and address, services, system and battery, and the start of the HTTPS fingerprint. The PIN prompt and setup steps. |
| 5" Elecrow (800×480 HDMI, resistive touch) | The **touch control panel**, below. |
| Other HDMI/DSI screen | The touch control panel, sized to the screen; driven by touch if the screen has it, by the keyboard (arrow keys, Tab) if not. |
| OLED and a panel | Both. |

**The touch control panel**

| Tab | |
|---|---|
| *(locked)* | PIN pad with tries left; **ABC** opens a full keyboard for a passphrase. A plugged-in keyboard types into it too. No keyboard is needed in the field. |
| **Home** | The console address (large), the network and how many devices have joined, the services, battery (time left on battery), storage, temperature, uptime. A red banner when the battery is low. |
| **Join** | Two QR codes: one joins the field Wi-Fi (hidden until you tap **Show** — it contains the passphrase), one opens the console. |
| **Trust** | A QR code to the certificate page, and the full CA fingerprint to compare. |
| **Menu** | Lock case file · Restart console · Wired network / Hotspot · Calibrate touch · Sleep screen · Renew certificate · Restart box · Shut down · Refresh. The ones that stop things ask first. |

The screen blanks after `SCREEN_SLEEP_MINUTES` idle (a touch wakes it — the
first touch only wakes). `SCREEN_ROTATE=180` if it is mounted upside down.

**The Elecrow 5" screen.** Its touch controller (XPT2046, on SPI chip-select
1 with its interrupt on GPIO 25) needs a driver that cannot be probed for. If
the screen identifies itself as 800×480, `auto` installs the driver in
`config.txt` and reboots once. Many of these screens do not identify
themselves at all — then set **`SCREEN=elecrow5`** in the config file and the
same happens regardless. Resistive touch always needs calibrating once
(Menu → Calibrate touch). The same applies to other 5" HDMI screens wired the
same way (e.g. Waveshare 5" (B)).

`humint-ctl screen-detect` shows what was found and what it will show.

---

## HTTPS

With `TLS=on` (the default) the console is served over HTTPS on port 443.
The box makes its own small certificate authority on first boot, inside the
encrypted store, and issues itself a server certificate covering
`<hostname>.local`, its hotspot address and whatever address it has on the
network — re-issued automatically when the address changes.

Each phone and laptop installs the **CA certificate once**, from
`http://<hostname>.local/trust` (port 80 serves only that page, the
certificate, and redirects to HTTPS). After that, the console opens with no
warnings on any address the box moves to. The Android field app trusts it
too — it already accepts user-installed CAs.

Installing a certificate authority on a phone is normally a big ask. This one
is **name-constrained**: it can only vouch for `.local` names, this box's
name, and private network addresses (10.x, 172.16–31.x, 192.168.x, carrier
NAT, link-local). It cannot be used to impersonate a bank, a mail server or
any other public site — even by someone holding its private key. (On a network
that gives the box a public address, use `https://<hostname>.local`.)

The trust page puts the visitor's own platform first (read from the browser)
and folds the rest underneath. It covers Windows (with a `.cer` download, the
PowerShell one-liner, and a Group Policy / Intune note for managed laptops),
macOS, Linux (Arch, Ubuntu/Debian, Fedora/RHEL, openSUSE, plus the separate
step Chrome-family browsers need on Linux), Firefox on any system (it keeps its
own list), Android and iPhone/iPad. It shows the SHA-256 fingerprint and the
SHA-1 thumbprint Windows' install dialog displays; the panel's Trust tab and
`humint-ctl tls` show both, so either can be checked against the box itself.

`humint-ctl tls` shows the fingerprints and what the certificate covers;
`humint-ctl tls renew` re-issues it; `humint-ctl tls off` goes back to plain
HTTP.

---

## Battery

`humint-battery` reads the UPS board every few seconds and puts the result on
the panel, the OLED and `humint-ctl status`. It finds the board itself
(`BATTERY=auto`):

| Board | What it reads |
|---|---|
| **Geekworm X1203** (Pi 5) | A real fuel gauge (Maxim MAX17040, I2C **0x36**) that reports the charge itself, and the power-loss pin (**GPIO 6**) that says the moment wall power goes. Time left is worked out from how fast the charge is falling (it settles after a few minutes on battery). |
| **Waveshare UPS HAT** (Pi 4) | An INA219 monitor (I2C 0x42): charge estimated from the pack voltage, as Waveshare's own software does (it reads a little low under load); on battery or not from the direction of the current. |
| *(none)* | Nothing to read: the screens show a **plug** — the box is on external power and pulling the cable turns it off. |

What the screens show:

- **plug** — on wall power with no battery module behind it;
- **battery % and a plug** — a battery fitted and wall power present (with a
  bolt while charging);
- **battery % alone, with the time left** — running on battery;
- a **red banner** under 15% on battery.

When the box is on battery and the charge falls to `BATTERY_SHUTDOWN_PERCENT`
(8% by default) — or, on an X1203, the cell to 3.20 V, Geekworm's own cut-off —
for about 15 seconds, it stops the console, re-locks the case file and powers
off. It never does this on wall power, and never when it cannot tell (an
unreadable power-loss pin reads as "source unknown", not "on battery").

**X1203 notes.** Pi 5 only. Cells go in **parallel only** — Geekworm warns that
series wiring burns the board out — and should be cells without a built-in
protection board. When it arrives, `sudo i2cdetect -y 1` should show `36`
(if not, Geekworm's first suspect is the pogo pins' contact). If the screen
says *on battery* while plugged in, the power-loss pin reads the other way
round on your board: set `BATTERY_PLD_AC_LEVEL=0` in `/var/lib/humint/env`
and `systemctl restart humint-battery`.

`humint-ctl battery` prints a one-line reading.

---

## Building the image

Build on a Raspberry Pi running ordinary 64-bit Raspberry Pi OS (simplest: it
is the same architecture as the image, so nothing is emulated), or on any
Debian/Ubuntu machine. A step-by-step walkthrough for first-timers lives in
the "Building the field server image" guide; the short version:

```bash
git clone <this repo> humint-platform && cd humint-platform
git checkout pi-appliance
deploy/pi/prepare-pigen.sh ~/pi-gen      # clones pi-gen, copies the stage + app, writes ~/pi-gen/config
nano ~/pi-gen/config                     # set FIRST_USER_PASS (and keyboard/timezone)
cd ~/pi-gen && sudo ./build.sh           # 1–2 hours; the image lands in ~/pi-gen/deploy/
```

`prepare-pigen.sh --docker` sets the same up for pi-gen's `build-docker.sh`
instead. Run `prepare-pigen.sh` again after pulling new code; it refreshes the
stage and the app and keeps your config.

What the `stage-humint` stage adds on top of Raspberry Pi OS Lite:

| Sub-stage | What it does |
|---|---|
| `00-packages` | NetworkManager, cryptsetup, avahi, Tesseract, Poppler, Python tooling; pygame, evdev and qrcode for the touch panel. |
| `01-postgres` | PostgreSQL 16 from the PostgreSQL project's apt repo (the same major version the Docker deployment runs, so backups move between them). Its default cluster is removed; nothing starts it at boot. |
| `02-app` | Copies `api/`, `worker/`, `frontend/` and `db/` to `/opt/humint-platform`, creates one Python venv at `/opt/humint/venv` with every dependency, creates the `humintd` service account, enables I2C. |
| `03-overlay` | The appliance scripts, the systemd units, the network hook that re-issues the certificate, and the config template on the boot partition. |

The ARM image is built under emulation on an x86 machine, so the Python step
is slow — expect the whole build to take an hour or more the first time.

Flash with [Raspberry Pi Imager](https://www.raspberrypi.com/software/)
("Use custom") or balenaEtcher. In Imager, **skip the OS customisation** —
this image does its own.

**Updating the console's code** means building a new image (or copying the
new `api/`, `worker/` and `frontend/` over `/opt/humint-platform` and running
`humint-ctl restart`). If the new version adds a `db/migrate-*.sql`, apply it
with `sudo -u postgres psql humint_platform -f …`. A field box is meant to be
re-imaged between deployments rather than upgraded in place — bring its work
home with a field package first.

---

## Configuring before first boot

After flashing, the card has a small **boot partition** readable on any
computer. On it, copy `humint-appliance.conf.example` to
`humint-appliance.conf` and edit it. The important settings:

- `WIFI_COUNTRY` — **required** for the hotspot to transmit (e.g. `US`).
- `NET_MODE` — `hotspot` (the Pi is the access point), `client` (join an
  existing Wi-Fi), or `wired` (Ethernet only, optionally handing out
  addresses to a switch).
- `AP_SSID` / `AP_PSK` — the field network's name and passphrase. **Change
  the passphrase.**
- `DATA_SIZE` — how big the encrypted case store is. It cannot grow later, so
  size it for the deployment and leave room on the card for the OS (~4 GB).
- `SCREEN` — `auto`, or `elecrow5` for the 5" touch screen if auto does not
  find it (see Screens).
- `TLS` — `on` (default) or `off`.
- `BATTERY` — `auto` (default), `waveshare` or `none`; `BATTERY_CELLS`.
- `HOSTNAME`, `INSTANCE_NAME`, `TIMEZONE`.

The file is read once and then renamed to `*.done`, so your passphrases are
not left sitting on a partition any computer can read. (A root-only working
copy is kept at `/var/lib/humint/env`.)

---

## Testing at base

Before taking a box out, run through this once:

1. Flash, configure `NET_MODE=hotspot`, first boot, set the PIN.
2. On a phone and a laptop, join `AP_SSID` (or scan the panel's Join QR). You
   should get a `10.42.0.x` address; the Pi is `10.42.0.1`.
3. Open `http://10.42.0.1/trust`, install the certificate, check the
   fingerprint against the screen. Then `https://10.42.0.1` and
   `https://<hostname>.local` should open with no warning (the `.local` name
   works on most laptops and iPhones; some Android versions need the IP).
4. Submit a field report from the phone; see it arrive in the console.
5. Reboot. Confirm the PIN pad (or OLED prompt) appears, a wrong PIN is
   refused and counted, the right one brings the console back, and the report
   is still there.
6. Touch screen: calibrate, then tap through every tab; lock and unlock from
   the Menu.
7. Battery: with the charger in, the top bar shows the % and a plug; unplug
   it and the plug goes, the Home card says *on battery*, and a time estimate
   appears after a few minutes. With no battery board, just a plug and "AC". (To test the shutdown without draining a pack, set
   `BATTERY_SHUTDOWN_PERCENT=95` in `/var/lib/humint/env` and
   `systemctl restart humint-battery` — then set it back.)
8. Try `humint-ctl net wired` with a switch and a laptop — the certificate is
   re-issued for the new address — and `humint-ctl net hotspot` to go back.
9. Export a field package and import it on a test HQ console.
10. Note the range and how many devices it handles before you rely on it.

---

## Operating it: `humint-ctl`

Over SSH (enabled), or on the keyboard at a login prompt on tty2
(Ctrl+Alt+F2 — tty1 belongs to the PIN prompt):

```
humint-ctl status          # address, services, case-file state, battery, temperature
humint-ctl url             # just the address to read out to the team
humint-ctl net hotspot     # switch to being the access point
humint-ctl net client SSID [PSK]   # join a Wi-Fi and serve on it
humint-ctl net wired       # Ethernet only, Wi-Fi off
humint-ctl pin             # change the unlock PIN (case file must be open)
humint-ctl lock            # stop the console and re-lock the case file now
humint-ctl tls [renew|on|off]   # HTTPS status and fingerprint; re-issue; switch
humint-ctl battery         # charge, voltage, current
humint-ctl screen-detect   # what screen is attached and what it will show
humint-ctl up | down | restart
humint-ctl backup [DIR]    # pg_dump the case database (default: inside the store)
humint-ctl logs [api|worker|http|panel|battery|db|firstboot|unlock]
humint-ctl shutdown | reboot
```

Under the hood these are plain systemd and journald: `systemctl status
humint-api`, `journalctl -u humint-panel -f` and so on all work.

The OLED cycles its pages (network, services, system, trust). Wire a
push-button between a GPIO pin and ground and set `STATUS_BUTTON_GPIO` to
advance pages on a tap and shut down safely on a long press (not GPIO 25 if
the 5" touch screen is fitted — its touch controller uses it).

---

## Security notes

- **Encrypted at rest, data only.** The database cluster, the console's
  settings (which hold the database password), the HTTPS keys, uploads, map
  packs and the services' scratch files all live in a LUKS2 volume (argon2id)
  unlocked by the PIN. The OS and the app code are not encrypted — they
  aren't secret, and encrypting them would mean unlocking in the initramfs,
  before the PIN pad and screen services exist.
- **A PIN is only as strong as it is long.** LUKS's key-stretching makes each
  guess slow, and an attacker needs the physical box to try, but a longer
  passphrase is stronger than four digits. The PIN pad's **ABC** key takes a
  passphrase. The touch screen and the keyboard share one count of wrong
  PINs: five, and the case file stays closed until a restart.
- **Least privilege.** The API, the worker and the port-80 service run as
  `humintd`, not root, with a read-only view of the system
  (`ProtectSystem=strict`) and write access only to their directories in the
  store. PostgreSQL listens on localhost only and uses password (SCRAM)
  authentication for the app's account. The touch panel runs as root, because
  it opens the store and runs `humint-ctl`.
- **HTTPS, with a constrained CA** — see HTTPS above. The CA's private key
  never leaves the encrypted store. The Wi-Fi passphrase is still the
  perimeter for who can reach the login page.
- **The Join QR contains the Wi-Fi passphrase.** It is hidden until tapped;
  hide it again before putting the box down where others can see the screen.
- **Field packages are case data.** Carry them encrypted and delete them once
  imported at HQ.
- **Offline by design.** Geocoding, Overpass lookups and the local model are
  off. Download map packs at base, before deploying — the worker needs the
  internet to fetch them, which the box has in `client` or `wired` mode on
  your home network. The assistant can be pointed at an Ollama server on the
  same network by editing `/srv/humint-data/humint.env`.
- **The clock.** A Pi 4 has no real-time clock, so with no network to set the
  time it may start with the wrong date, which skews report timestamps (and a
  clock set far in the past can make a fresh certificate look not-yet-valid).
  Set it with `sudo date -s '2026-10-16 14:00'` after boot, or use a Pi 5 with
  its RTC battery fitted.

---

## What has been tested, and what needs real hardware

Tested off the Pi:

- **Database path:** a PostgreSQL 16 cluster created UTF-8 in a store
  directory, the role and database, the full schema over SCRAM, and the API
  and worker running natively against it with the generated settings.
- **Field sync, end to end** on two real consoles: seed from an HQ backup,
  work in the field, export, import at HQ, review (new, matched duplicate,
  partial change, links, report re-linked with its attachment), and a second
  package carrying only what changed.
- **HTTPS:** CA and server certificate issued, served by uvicorn, verified by
  a client trusting only the box's CA; a certificate for a public name forged
  with the CA's own key is rejected; the port-80 page, download and redirect.
- **Battery gauge** against simulated chips — the X1203's MAX17040 and
  power-loss pin, and the Waveshare INA219: charge, plugged in / charging /
  on battery, time left, the no-module plug, and the shutdown rules (never on
  wall power or an unreadable pin; the X1203 voltage floor).
- **Screen detection** against simulated hardware, including the reboot-once
  guard; every **touch panel** screen rendered at 800×480 and 1024×600, and
  taps, keys, rotation and calibration driven through it.
- **PIN counting** shared by keyboard and touch, including lockout.

Needs a real Pi:

- The **image build** in pi-gen (package names, the PGDG repo for arm64,
  Python wheels compiling under emulation).
- The **Elecrow screen**: the driver overlay, the reboot-once, touch through
  evdev, calibration, pygame drawing through KMS.
- The **OLED** wiring and the **PIN prompt** at the right moments.
- The **unlock flow** on real LUKS, and `humint.target` starting after it.
- **The X1203** answering at 0x36, the power-loss pin's polarity, and the
  charge figure against a real discharge (or the Waveshare HAT at 0x42).
- **Hotspot mode** at usable range with several phones; certificate
  installation on your actual phones.
- **Performance** of OCR and the console on a Pi 4 vs a Pi 5, and power draw
  and runtime on your battery.

---

## Roadmap

- **Duress PIN** that erases the case store instead of opening it, as the
  tablet relay has.
- **Fully encrypted root**, unlocked in the initramfs.
- **Battery gauges** for other UPS boards (PiSugar); charge-limit control on
  the X1203 (GPIO 16) for boxes left plugged in for weeks.
- **A PC/x86 ISO** of the same appliance for mini-PC field servers.
- **Field sync over the network** when the box can reach HQ, instead of a
  USB stick — and carrying zones, routes and record photos.
