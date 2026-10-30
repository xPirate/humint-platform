# HUMINT field server — on an ordinary laptop or mini PC

The same field server as the [Raspberry Pi appliance](../pi/README.md), built
for any 64-bit x86 machine: a laptop, a rugged tablet, a mini PC. A USB stick
installs it; the machine then runs the full platform on its own, keeps the case
file in an encrypted store that a PIN opens at boot, serves the team over its
own Wi-Fi (or the wire), and shows **its own screen as a native app** — the
whole console, not a browser in kiosk mode.

It is an **appliance**: Ubuntu 24.04 LTS underneath, nothing to administer, no
internet needed after the stick is made. Everything the Pi does, this does —
the encrypted case file, the duress PIN, the hotspot, HTTPS, field packages,
signed updates — and the screen is the console itself, with every page the
browser has.

---

## What you need

| | |
|---|---|
| **Machine** | Any 64-bit x86 (Intel or AMD) computer that boots UEFI: a laptop, tablet or mini PC from roughly 2015 on. **Secure Boot can stay on** — the stick and the installed system boot through Microsoft-signed shim, as Ubuntu does. 4 GB of memory (8 better). |
| **Disk** | 32 GB or more, an SSD. **The whole disk is erased.** The case file takes 70% of what is free after the system (`DATA_SIZE`), and can be made larger later (**Admin → Storage**). |
| **Screen** | Its own, or any HDMI screen. Touch works; with no keyboard attached, an on-screen keyboard appears. |
| **Wi-Fi** | For the hotspot, a Wi-Fi chip that can be an access point — most Intel and Atheros ones can. Without one (or no Wi-Fi at all) it uses the Ethernet port instead, by itself (see [Networking](#networking)). |
| **Battery** | A laptop's own battery is read automatically: charge, time left, and a clean lock-and-power-off before it runs out. |
| **USB stick** | 8 GB or larger, for the installer. |
| **Build machine** | Any 64-bit x86 Debian or Ubuntu machine with internet and ~25 GB free (a VM is fine). |

---

## Making the installer stick

```sh
git clone https://github.com/xPirate/humint-platform
humint-platform/deploy/x86/build-x86.sh
```

It asks once for the **login password** for the machines it makes (for SSH and
the keyboard — not the PIN, and replaced by a random one on first boot unless
you say otherwise), then builds: the first time 30–60 minutes (Ubuntu and its
packages are fetched and cached), later ones much less. It uses `sudo` for the
parts that need root, and wraps itself in `tmux` when run over SSH, so a
dropped connection does not stop it.

The result is `~/humint-x86/out/humint-x86-installer.img.xz`. Write it to a
stick with Raspberry Pi Imager (**Use custom**), balenaEtcher, Rufus, or `dd`.

| Option | |
|---|---|
| `--clean` | rebuild the Ubuntu base from scratch (otherwise it is reused while `packages` is unchanged — and rebuilt, with Ubuntu's latest fixes, when it changes) |
| `--quick` | reuse the last build's system and refresh only the code, scripts and app — for changes to those |
| `--no-compress` | leave `out/humint-x86-installer.img` uncompressed (testing in a VM) |
| `--no-tmux` | do not wrap the build in tmux |

The first build also makes the **update-signing key**
(`~/.config/humint/update-signing.key`, shared with the Pi builds). Every
machine accepts only updates that key signs. **Back it up**: without it, a
machine can only be updated by reinstalling it.

### Settings, before installing

Optional. Copy `humint-appliance.conf.example` to the stick's **HUMINT-BOOT**
partition (any computer can open it) as `humint-appliance.conf` and change
what you need: the hostname, the Wi-Fi country and hotspot name and password,
the network mode, a key for SSH, the case-file size. The installer carries it
to the machine, where first boot reads it once. Leave it out and every setting
takes its default, with the hotspot password and login password made up and
shown on the screen.

---

## Installing

1. Boot the machine from the stick — usually **F12**, **F11**, **F7** or **Esc**
   at power-on for the boot menu (on some, hold **Volume Down**).
2. Choose the disk. Type **ERASE**.
3. When it says so, remove the stick and press Enter.

It takes 5–15 minutes. Nothing on the stick changes, so one stick installs
any number of machines.

The stick's boot menu also has a troubleshooting entry that shows boot
messages on a serial console. An unattended install (for a rack of identical
mini PCs, or a test VM) is two words on the kernel line:
`humint.install.disk=/dev/nvme0n1 humint.install.auto` — it installs to that
disk without asking and powers off.

## First boot

The screen asks you to **choose the unlock PIN** (at least 4 characters —
longer is stronger; it cannot be recovered). The case file is made and
encrypted with it, the database set up, and the network started. Then the
screen shows what to **write down**: the machine's login, and the hotspot
password if one was made up — Enter, or *I've written it down*. Last, the
**first admin account** for the console, made on the screen.

From then on, every start asks for the PIN on the screen (five wrong ones and
it stays locked until restarted). If the power goes while the machine waits
for a PIN to be chosen, the next start simply asks again.

## The screen

The native app is the console: the dashboard, the review inbox, reports and
the guided debrief, records and their network, the map (with offline areas,
zones and routes, and drawing them), documents, feeds, BOLO, priorities,
analysts, the assistant, the audit log and the whole of Admin. **Box**, at
the top, has what the Pi's panel has: the address and Wi-Fi to join (with QR
codes), certificate trust, phone upload codes, and the actions — lock, restart,
network, updates, duress PIN, new login, shut down, wipe.

It runs on Wayland in the `cage` compositor, as its own unprivileged account;
a small root helper (`humint-boxd`) does the few things that need root, and
only those. The text console on Ctrl+Alt+F1 stays available.

**Quick settings.** Tap the status at the top right of any screen (network,
battery, clock) for the machine's own controls, as on a phone or a desktop:
brightness, volume and mute, when the screen sleeps (1 minute to an hour, or
never) and **Sleep now**, whether sleeping also signs the console out, the
network and the battery at a glance, and Lock / Restart / Shut down. The
keyboard's volume and brightness keys work too. Sleeping switches the panel's
backlight off; the next touch or key only wakes it (it never presses what was
under the finger). Brightness and volume are kept across restarts.

**Graphics.** The app draws with the graphics chip. Some chips crash the
drivers (and most virtual machines have none): after two crashes at start-up
it draws in software instead, by itself, until the next restart — a little
slower, works everywhere. `HUMINT_RENDER=software` (or `gpu`) in the settings
fixes the choice.

## Networking

| `NET_MODE` | |
|---|---|
| `hotspot` (default) | the machine's Wi-Fi is the access point the team joins; it hands out addresses (10.42.0.0/24) and is 10.42.0.1 |
| `client` | it joins a Wi-Fi you name and serves on it |
| `wired` | the Ethernet port only, Wi-Fi off; optionally serving addresses on it (`WIRED_DHCP_SERVER`) |

**Getting it online before deploying** — to download map areas or the
system's updates — is **Box → Actions → Join Wi-Fi**: the networks in range
(or type a name, for a hidden one), and its password. A phone's hotspot does
nicely. The machine then serves the console on that network instead of its
own; **Box → Actions → Hotspot** puts it back before you go. If it cannot
join (most often a wrong password), it says why and uses the Ethernet port
meanwhile. The password is kept in the machine's private settings and never
shown on the screen again; `sudo humint-ctl net client "Name"` does the same
from a keyboard (it asks nothing — the password goes after the name).

**When Wi-Fi cannot do it** — no Wi-Fi at all (most mini PCs and desktops),
one that cannot host a hotspot, or one that will not start — it uses the
Ethernet port instead and says so on the screen. In that case it takes an
address from the network it is plugged into, and never hands addresses out
itself (on someone else's network that would cause trouble); with no DHCP on
the wire (a bare switch of laptops) it also takes a self-assigned 169.254
address, as the laptops do, so they find each other anyway. Choosing hotspot
again later tries again.

## The clock

Unlike the Pi, every x86 machine has a battery-backed clock, and when it reads
a sane time the field server trusts it: the time is not marked unconfirmed, and
devices are not asked to set it. Network time still wins when there is any.

---

## Updating — and security fixes

The machines are meant to be left alone, and updating them is the one thing to
come back for. Two kinds of update, often together:

**The field server's own code** (console, appliance, the screen's app), and
**Ubuntu's security fixes** (kernel, OpenSSL, PostgreSQL, …).

### With no internet: a signed bundle on a USB stick

On the build machine, from an up-to-date checkout:

```sh
humint-platform/deploy/x86/make-update.sh --out ~/Desktop
```

That makes `humint-update-<build>-<commit>-x86.tar`: the code, the screen's
app, their Python packages, and **Ubuntu's updated packages** — the newest
version of everything in the image that Ubuntu has updated since 24.04 was
released, enough for any machine installed from any image of this release.
Kernels and firmware make that several hundred MB.

| Option | |
|---|---|
| `--os-since FILE` | carry only packages newer than a list — the `humint-x86-packages.txt` an image build leaves in `out/`, or the `humint-os-<build>.txt` a previous bundle left beside itself — once every machine has at least that |
| `--no-os` | code only (small; also what fits through the console's upload, which takes up to 600 MB) |
| `--no-wheels` | without Python packages (refused by a machine whose requirements differ) |

Put it on a USB stick, in any folder. On the machine: **Box → Actions →
Update from USB** (or `sudo humint-ctl update usb`). It checks the signature
— the builder's key, and an x86 bundle (Pi and x86 share the key; each refuses
the other's) — then: backs up the database into the encrypted store, installs
the Ubuntu packages, swaps in the code, runs any database migrations, and
waits for the console to answer. If the code or migrations fail, everything
is put back as it was (`humint-ctl update rollback` also undoes the last
update by hand). If the Ubuntu packages fail, it stops there with nothing else
changed. A new kernel takes effect at the next restart; the screen says when
one is needed. It unpacks inside the encrypted store (so the case file must be
open), which needs free room there of about twice the bundle's size.

### With internet: straight from Ubuntu

**Box → Actions → Update the system** (or `sudo humint-ctl os-update`)
fetches and installs Ubuntu's updates directly. Code updates still come as
bundles.

---

## Storage

Everything in the case lives in one encrypted file. **Admin → Storage** on
the screen shows its size and how much is in use, and makes it larger: choose
the size, enter the PIN, and it grows in place, open and in use — nothing is
copied, nobody is signed out. 4 GB of the disk always stays free for updates
and logs. It cannot be made smaller. From a keyboard: `sudo humint-ctl store`
and `sudo humint-ctl store grow 64G` (or `max`).

## Operating it

`humint-ctl` is the same as on the Pi — `status`, `url`, `lock`, `net`,
`pin`, `duress`, `wipe`, `update`, `os-update`, `logs`, … (`humint-ctl help`).
Log in on the text console or over SSH with the machine's login.

## Security notes

- **What is encrypted is the case file** (`/srv/humint.img`, LUKS2, the
  PIN): the database, uploads and settings that hold secrets. The system
  itself is not — it holds nothing about the case. Shut the machine down (or
  Box → Lock) to close the case file; while it is open, anyone at the screen
  who can sign in to the console can read it.
- **Secure Boot** stays on: the boot chain is Microsoft-signed shim, Ubuntu's
  signed GRUB and kernel.
- **The duress PIN**, wipe and the login password behave as on the Pi.
- **Updates** are signed with Ed25519 by the builder's key and checked before
  anything is changed; Ubuntu's packages in a bundle are covered by that
  signature.
- The screen's app runs unprivileged; its root helper accepts only a fixed
  list of actions, from the screen's account only.

## What has been tested, and what needs real hardware

Tested in QEMU with Secure Boot (OVMF, Microsoft keys): building the stick,
the install with its questions (disk, ERASE, progress) and unattended, the installed system's first boot with the PIN chosen
on the screen through the keyboard, the credentials screen, the console and
the native app, the wired fallback with no Wi-Fi, the clock, the software
drawing fallback, and update bundles (also covered by the automated tests,
with the native app's screens — `tests/test_native_*.py`).

Needs real hardware to confirm: a Wi-Fi hotspot on real chips; touch and the
on-screen keyboard on a touch screen; a laptop battery's readings and the
low-battery shutdown; GPU drawing on Intel/AMD graphics; and the boot-menu
keys of the machines you choose.
