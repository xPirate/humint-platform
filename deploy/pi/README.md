# HUMINT field server — a Raspberry Pi appliance (v1)

A flashable image that turns a Raspberry Pi into a self-contained, offline
console the whole team connects to. The Pi provides the Wi-Fi, runs the full
platform natively, and keeps the case file in an encrypted store that a PIN
unlocks at boot. It is meant to live in a bag on a battery while a team works
off-site, instead of the platform running on one person's laptop.

It is an **appliance**, not a server you administer: no Docker, no build step
on the device, no internet needed at any point after flashing. PostgreSQL,
the API and the background worker are ordinary systemd services, installed
into the image when it is built.

This is **v1**: the full console on the box, the data encrypted at rest, a
hotspot (or wired) network set up on first boot, and a small status screen.
What is **not** here yet is listed under [Roadmap](#roadmap) — most
importantly, getting a field case file merged back into the home console.

---

## What you need

| | |
|---|---|
| **Board** | Raspberry Pi 4 (4 GB minimum, 8 GB better) or Pi 5. 64-bit. |
| **Storage** | An SD card (32 GB+, A2-rated) to boot. **Recommended:** boot from a USB-3 SSD (Pi 4) or NVMe (Pi 5) instead — database writes wear SD cards, and a card that loses power mid-write can corrupt the case file. |
| **Keyboard** | **Required for field use.** The box is headless; the unlock PIN is typed on a USB keyboard at every boot. A small foldable one lives in the bag. |
| **Screen (optional)** | A 0.96" SSD1306 I2C OLED on the GPIO header shows the PIN prompt, the address and service status. Everything works without it. |
| **Battery (optional)** | A USB-C power bank that can supply 5 V / 3 A (Pi 4) or 5 V / 5 A (Pi 5). |
| **Build machine** | A Debian/Ubuntu x86-64 machine (or anything that runs Docker) with internet, to run pi-gen. |

A keyboard is required because the case store is encrypted and the PIN is
typed to open it. The OLED only tells the operator *when* to type; with no
OLED, wait about 30 seconds after power-on and type the PIN blind, then
Enter.

---

## How it works

```
 power on
    │
    ▼
 humint-unlock ── OLED: "Enter unlock PIN" ── keyboard ──► cryptsetup open
    │                                                     /srv/humint.img
    ▼                                                          │
 mount /srv/humint-data  ◄────────────────────────────────────┘
    │     ├── postgresql/   the case database (PostgreSQL 16 cluster)
    │     ├── humint.env    console settings + DB password
    │     ├── uploads/  map-packs/  tmp/
    ▼
 systemctl start humint.target
    ├── postgresql@16-main   (localhost only)
    ├── humint-api           (port 80, user humintd)
    └── humint-worker        (OCR, extraction, sweeps; user humintd)
```

Nothing that touches case data is enabled at boot. The database, the API and
the worker start only after the PIN has opened the store, and each unit
refuses to start if the store isn't mounted. Even the services' scratch files
(backup bundles, OCR pages) go to `tmp/` inside the store, never to the plain
SD card.

**Before deployment (once, at base):**

1. Build and flash the image, edit one config file on the card.
2. Power on with a keyboard attached. First boot sets the hostname, asks you
   to **set the unlock PIN** (twice), creates the encrypted store, creates the
   database inside it, starts the console, and switches to the field network.
   Allow 5–10 minutes; the OLED and the keyboard console show each step.
3. Join the field Wi-Fi, open the console, **create the admin account** (the
   first account made becomes admin), add the analysts, load or start a case,
   and add the map packs you'll need (see the note under Security).
4. Power off.

**In the field (every day):**

1. Power on. The OLED shows "Enter unlock PIN".
2. Type the PIN on the keyboard and press Enter. The store unlocks and the
   console starts (about a minute on a Pi 4).
3. The team joins the Pi's Wi-Fi and works at `http://<hostname>.local` (or
   the IP the screen shows). Phones submit field reports to it exactly as
   they do to the home console.
4. At the end, power off — or run `humint-ctl lock` to re-lock the case file
   without shutting down.

If the Pi is lost while off or locked, the case file is a LUKS2 volume that
needs the PIN; whoever finds it gets an OS and the app's code, not the case.

---

## Building the image

```bash
# On a Debian/Ubuntu x86-64 machine with internet:
git clone --branch arm64 https://github.com/RPi-Distro/pi-gen   # the 64-bit branch
cd pi-gen

# Bring in this appliance's stage and config.
cp -r /path/to/humint-platform/deploy/pi/stage-humint ./stage-humint
cp /path/to/humint-platform/deploy/pi/config.example ./config

# Edit ./config — at minimum set:
#   HUMINT_SRC_DIR=/path/to/humint-platform   (your checkout; its code is baked in)
#   FIRST_USER_PASS=...                        (do not ship a shared default)

# (config's STAGE_LIST already limits the build to Lite + our stage.)

sudo ./build.sh          # or ./build-docker.sh
# The image lands in ./deploy/  e.g. image_*-humint-field.img(.xz)
```

What the `stage-humint` stage adds on top of Raspberry Pi OS Lite:

| Sub-stage | What it does |
|---|---|
| `00-packages` | NetworkManager, cryptsetup, avahi, Tesseract, Poppler, Python tooling. |
| `01-postgres` | PostgreSQL 16 from the PostgreSQL project's apt repo (the same major version the Docker deployment runs, so backups move between them). Its default cluster is removed; nothing starts it at boot. |
| `02-app` | Copies `api/`, `worker/`, `frontend/` and `db/` to `/opt/humint-platform`, creates one Python venv at `/opt/humint/venv` with every dependency, creates the `humintd` service account, enables I2C. |
| `03-overlay` | The appliance scripts, the systemd units and the config template on the boot partition. |

The ARM image is built under emulation on an x86 machine, so the Python step
is slow — expect the whole build to take an hour or more the first time.

Flash with [Raspberry Pi Imager](https://www.raspberrypi.com/software/)
("Use custom") or balenaEtcher. In Imager, **skip the OS customisation** —
this image does its own.

**Updating the console's code** means building a new image (or copying the
new `api/`, `worker/` and `frontend/` over `/opt/humint-platform` and running
`humint-ctl restart`). If the new version adds a `db/migrate-*.sql`, apply it
with `sudo -u postgres psql humint_platform -f …`. A field box is meant to be
re-imaged between deployments rather than upgraded in place.

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
- `HOSTNAME`, `INSTANCE_NAME`, `TIMEZONE`.

The file is read once and then renamed to `*.done`, so your passphrases are
not left sitting on a partition any computer can read. (A root-only working
copy is kept at `/var/lib/humint/env`.)

---

## Testing the network setup at base

Before taking a box out, run through this once:

1. Flash, configure `NET_MODE=hotspot`, first boot, set the PIN.
2. On a phone and a laptop, join `AP_SSID`. You should get a `10.42.0.x`
   address; the Pi is `10.42.0.1`.
3. Open `http://10.42.0.1` and `http://<hostname>.local` (the `.local` name
   works on most laptops and iPhones; some Android versions need the IP).
4. Submit a field report from the phone; see it arrive in the console.
5. Reboot. Confirm the OLED asks for the PIN, a wrong PIN is refused, the
   right one brings the console back, and the report is still there.
6. Try `humint-ctl net wired` with a switch and a laptop, and
   `humint-ctl net hotspot` to go back.
7. Note the range and how many devices it handles before you rely on it.

---

## Operating it: `humint-ctl`

Over SSH (enabled), or on the keyboard at a login prompt on tty2
(Ctrl+Alt+F2 — tty1 belongs to the PIN prompt):

```
humint-ctl status          # address, services, case-file state, temperature
humint-ctl url             # just the address to read out to the team
humint-ctl net hotspot     # switch to being the access point
humint-ctl net client SSID [PSK]   # join a Wi-Fi and serve on it
humint-ctl net wired       # Ethernet only, Wi-Fi off
humint-ctl pin             # change the unlock PIN (case file must be open)
humint-ctl lock            # stop the console and re-lock the case file now
humint-ctl up | down | restart
humint-ctl backup [DIR]    # pg_dump the case database (default: inside the store)
humint-ctl logs [api|worker|db|firstboot|unlock]
humint-ctl shutdown | reboot
```

Under the hood these are plain systemd and journald: `systemctl status
humint-api`, `journalctl -u humint-worker -f` and so on all work.

The status screen cycles three pages (network, services, system). Wire a
push-button between a GPIO pin and ground and set `STATUS_BUTTON_GPIO` to
advance pages on a tap and shut down safely on a long press.

---

## Security notes (v1)

- **Encrypted at rest, data only.** The database cluster, the console's
  settings (which hold the database password), uploads, map packs and the
  services' scratch files all live in a LUKS2 volume (argon2id) unlocked by
  the PIN. The OS and the app code are not encrypted — they aren't secret,
  and encrypting them would mean unlocking in the initramfs, before the
  keyboard prompt and screen services exist.
- **A PIN is only as strong as it is long.** LUKS's key-stretching makes each
  guess slow, and an attacker needs the physical box to try, but a longer
  passphrase is stronger than four digits. The unlock accepts any passphrase,
  not just digits.
- **Least privilege.** The API and worker run as `humintd`, not root, with a
  read-only view of the system (`ProtectSystem=strict`) and write access only
  to their directories in the store. PostgreSQL listens on localhost only and
  uses password (SCRAM) authentication for the app's account.
- **Plain HTTP on the field LAN.** The console is served over http on the
  hotspot, as the project's other LAN deployments are. Anyone on the Wi-Fi
  can reach the login page, so the Wi-Fi passphrase is the perimeter.
  Self-signed TLS is a later improvement.
- **Offline by design.** Geocoding, Overpass lookups and the local model are
  off. Download map packs at base, before deploying — the worker needs the
  internet to fetch them, which the box has in `client` or `wired` mode on
  your home network. The assistant can be pointed at an Ollama server on the
  same network by editing `/srv/humint-data/humint.env`.
- **The clock.** A Pi 4 has no real-time clock, so with no network to set the
  time it may start with the wrong date, which skews report timestamps. Set
  it with `sudo date -s '2026-10-16 14:00'` after boot, or use a Pi 5 with
  its RTC battery fitted.

---

## What still needs real hardware

Everything has been syntax- and lint-checked, and the database path has been
exercised for real: a PostgreSQL 16 cluster created in a store directory,
the role and database created, the full schema loaded over SCRAM, and the API
and worker run natively against it with the generated settings (the admin
bootstrap works). What can only be verified on an actual Pi:

- The **image build** itself in pi-gen (package names, the PGDG repo for
  arm64, Python wheels compiling under emulation).
- The **OLED** driver (I2C address, wiring) and the **PIN prompt** appearing
  on it at the right moments.
- The **unlock flow** owning the keyboard on tty1, the LUKS open/mount, and
  `humint.target` starting only after it.
- **Hotspot mode** transmitting and handing out addresses, at usable range,
  with several phones joined. The built-in Wi-Fi has a small antenna; a
  supported USB Wi-Fi adapter with an external antenna will do better.
- **Performance** of OCR and the console on a Pi 4 vs a Pi 5.
- Power draw and runtime on your actual battery.

---

## Roadmap

- **Field → HQ case sync.** The one piece that makes extended deployments
  real: export the field case file and import it at HQ as Review-queue
  proposals, so analysts accept and de-duplicate it into the home case rather
  than overwriting it.
- **Kiwix** as an on-box service (offline Wikipedia and reference), linked
  from the console and served over the same network.
- **Duress PIN** that wipes the case store, as the tablet relay has.
- **Self-signed TLS** on the console, and optionally a fully encrypted root.
- **Battery gauge** on the screen for common UPS HATs.
- **A PC/x86 ISO** of the same appliance for mini-PC field servers.
