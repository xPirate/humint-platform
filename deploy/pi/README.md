# HUMINT field server — a Raspberry Pi appliance (v1)

A flashable image that turns a Raspberry Pi into a self-contained, offline
console the whole team connects to: the Pi provides the Wi-Fi, runs the full
platform, and keeps the case file in an encrypted store that a PIN unlocks at
boot. It is meant to live in a bag on a battery while a team works off-site,
instead of the platform running on one person's laptop.

This is **v1**: the full console on the box, the data encrypted at rest, a
hotspot (or wired) network set up on first boot, and a small status screen.
What is **not** here yet is listed under [Roadmap](#roadmap) — most
importantly, getting a field case file merged back into the home console.

---

## What you need

| | |
|---|---|
| **Board** | Raspberry Pi 4 (8 GB) or Pi 5. 64-bit. |
| **Storage** | An SD card to boot. **Strongly recommended:** run the case store on a USB-3 SSD (Pi 4) or NVMe (Pi 5) — Postgres writes wear SD cards out, and a card that loses power mid-write can corrupt the case file. |
| **Keyboard** | **Required for field use.** The box is headless; the unlock PIN is typed on a USB keyboard at boot. A tiny foldable one lives in the bag. |
| **Screen (optional)** | A 0.96" SSD1306 I2C OLED on the GPIO header shows the address, PIN prompt and status. Everything works without it. |
| **Battery (optional)** | Any USB-C power bank. A UPS HAT lets the screen show battery % and shut down cleanly (not wired up in v1). |
| **Build machine** | A Debian/Ubuntu x86-64 box (or Docker) to run pi-gen. The Pi cannot build its own image. |

A keyboard is required because the case store is encrypted and the PIN is
typed to open it. The OLED only tells the operator *when* to type; with no
OLED, you type the PIN blind a few seconds after power-on.

---

## How it works

**Before deployment (once, at base, with internet):**

1. Flash the image, edit one config file on the card, boot the Pi on your
   normal network.
2. First boot sets the hostname and network, asks you to **set the unlock
   PIN**, creates the encrypted case store, builds the console's software,
   and brings it up.
3. You open the console in a browser, create the admin account, add the
   analysts, load or start a case, and download the offline map packs you'll
   need.
4. Power off.

**In the field (every day):**

1. Power on. The OLED (or, after a few seconds, the blank console) is waiting.
2. Type the PIN on the keyboard. The case store unlocks and the console
   starts.
3. The team joins the Pi's Wi-Fi and works at `http://<name>.local` (or the
   IP the screen shows). Phones submit field reports to it exactly as they do
   to the home console.
4. At the end, power off — or run `humint-ctl lock` to re-lock the case file
   without shutting down.

If the Pi is lost while off, the case file is a LUKS-encrypted volume that
needs the PIN; whoever finds it gets an OS and the app's code, not the case.

---

## Building the image

```bash
# On a Debian/Ubuntu x86-64 machine (or use pi-gen's ./build-docker.sh):
git clone https://github.com/RPi-Distro/pi-gen
cd pi-gen

# Bring in this appliance's stage and config.
cp -r /path/to/humint-platform/deploy/pi/stage-humint ./stage-humint
cp /path/to/humint-platform/deploy/pi/config.example ./config

# Edit ./config — at minimum set:
#   HUMINT_SRC_DIR=/path/to/humint-platform   (your checkout; its code is baked in)
#   FIRST_USER_PASS=...                        (do not ship a shared default)

sudo ./build.sh
# The image lands in ./deploy/  e.g. image_*-humint-field.img
```

The console's **code** is baked into the image; the **Docker images** are
built on the first boot, which is why that boot needs internet. (An
all-offline image that pre-builds the containers is a later improvement — see
Roadmap.)

Flash with [Raspberry Pi Imager](https://www.raspberrypi.com/software/) or
balenaEtcher. In Imager, skip the OS customisation — this image does its own.

---

## Configuring before first boot

After flashing, the card has a small **boot partition** readable on any
computer. On it, copy `humint-appliance.conf.example` to
`humint-appliance.conf` and edit it. The important settings:

- `WIFI_COUNTRY` — **required** for the hotspot to transmit (e.g. `US`).
- `NET_MODE` — `hotspot` (the Pi is the access point), `client` (join an
  existing Wi-Fi), or `wired` (Ethernet only).
- `AP_SSID` / `AP_PSK` — the field network's name and passphrase. **Change
  the passphrase.**
- `SETUP_UPLINK` — how the Pi reaches the internet for the one-time setup
  build: `ethernet` (plug in a cable — simplest) or `wifi` (fill in
  `SETUP_WIFI_*`).
- `DATA_SIZE` — how big the encrypted case store is. It cannot grow later, so
  size it for the deployment and leave room on the card.

The file is read once and then renamed to `*.done`, so your passphrases are
not left sitting on a partition any computer can read.

---

## Operating it: `humint-ctl`

Run over SSH (enabled by default) or on an attached keyboard+monitor:

```
humint-ctl status          # address, services, case-file state, temperature
humint-ctl url             # just the address to read out to the team
humint-ctl net hotspot     # switch to being the access point
humint-ctl net client SSID [PSK]   # join a Wi-Fi and serve on it
humint-ctl net wired       # Ethernet only, Wi-Fi off
humint-ctl pin             # change the unlock PIN (case file must be open)
humint-ctl lock            # stop the console and re-lock the case file now
humint-ctl up | down | restart
humint-ctl rebuild         # rebuild the console (needs internet)
humint-ctl shutdown | reboot
humint-ctl logs [service]  # console logs, or `logs firstboot`
```

The status screen cycles three pages (network, services, system). Wire a
push-button to a GPIO pin and set `STATUS_BUTTON_GPIO` to advance pages on a
tap and shut down safely on a long press.

---

## Security notes (v1)

- **Encrypted at rest, data only.** The database, uploads and map packs live
  in a LUKS2 volume (argon2id) unlocked by the PIN. The OS and the app code
  are not encrypted — they aren't secret, and encrypting them would mean
  unlocking in the initramfs before the keyboard and screen services exist.
- **A PIN is only as strong as it is long.** LUKS's key-stretching makes
  guessing costly, and an attacker needs the physical box to try, but a
  longer passphrase is stronger than four digits. The unlock accepts any
  passphrase, not just digits.
- **Plain HTTP on the field LAN.** The console is served over http on the
  hotspot, as the project's other LAN deployments are. Anyone on the Wi-Fi
  can reach it, so the Wi-Fi passphrase is the perimeter. Self-signed TLS is
  a later improvement.
- **No duress PIN yet.** The tablet relay's duress-wipe idea is a good fit
  here and is on the roadmap, not in v1.

---

## What still needs real hardware

I built and wired all of this, but these parts can only be verified on an
actual Pi, and are the first things to check:

- The **OLED** driver (I2C address, wiring) and the **PIN prompt** appearing
  on it at the right moments.
- **Hotspot mode** actually transmitting and handing out addresses, at usable
  range, with several phones joined. The Pi's built-in Wi-Fi has a small
  antenna; a USB Wi-Fi adapter with an external antenna is better for a team.
- The **unlock flow** owning the keyboard on `tty1` and Docker starting only
  after the store mounts.
- The **first-boot build** completing over your chosen setup uplink.
- Power draw and runtime on your actual battery.

---

## Roadmap

- **Field → HQ case sync.** The one piece that makes extended deployments
  real: export the field case file and import it at HQ as Review-queue
  proposals, so analysts accept and de-duplicate it into the home case rather
  than overwriting it. (The relay only carries phone reports home; a field
  server where analysts create records needs this.)
- **Kiwix** as an on-box service (offline Wikipedia and reference), reached
  from a link in the console, served over the same hotspot.
- **Duress PIN** that wipes the case store, as the tablet relay has.
- **Encryption of the whole root**, and **self-signed TLS** on the console.
- **Battery gauge** on the screen for common UPS HATs.
- **An all-offline image** that pre-builds the containers, and a **PC/x86
  ISO** for mini-PC field servers.
