# How to set up field devices

A **field device** is a phone that can *send* reports into the console's
review queue and do nothing else. Its token is refused by every read endpoint,
so a lost or seized phone gives up whatever unsent reports are on it — still
encrypted — and no route into the case file.

The app doesn't store the console's address or token either. It **scans a QR
code at the moment it uploads** and forgets it when the upload finishes. So
someone has to be able to show the analyst a code when they come back in
range. That's what **Show a code** and **Print a card** are for.

Only admins enroll devices. Any analyst can work the queue
([Handle field reports](field-reports.md)).

---

## Enroll a phone

1. Account menu → **Admin settings → Field devices → Enroll a device**.
2. **Name** it something you'll recognise in a list (*"Sonim — J. Neal"*).
3. **Account:** whose reports these are. Submissions are attributed to that
   person, and deactivating that account stops the device too.
4. **Address the app should connect to:** the address the *phone* can reach —
   the machine's LAN or VPN address, e.g. `http://192.168.1.20:8080`. Never
   `localhost`. It's pre-filled with what your browser is using, which is
   usually right on a LAN.
5. **Enroll.** A QR code and a token appear **once**.
6. **Print a card** now while it's on screen (below), or have the analyst scan
   it straight away to test.

## Show a device's code again

Press **Show a code** next to the device. It issues a **fresh** code for the
same device — same name, account and history. The console only ever kept a
hash, so the old one can't be shown.

This costs nothing on the phone: the app never stored the old code. The only
thing it breaks is a **printed card** for that device — reprint it.

## Print a card

On any screen showing a code (after enrolling or **Show a code**), press
**Print a card**. One page with the device name, account, address, QR, token,
and a line on what the code can and can't do.

Keep it wherever the team keeps keys, so an analyst back in range can scan it
without anyone logging in. It prints rather than downloads on purpose: paper
doesn't end up synced to someone's cloud drive.

## Revoke or remove a device

- **Revoke** stops it immediately; the next upload is refused. What it already
  sent stays.
- **Remove** takes it off the list; its past submissions still say which
  device they came from.

**Lost a phone?** Revoke it. The queue on it can't be read without the phone's
own hardware key and the analyst's PIN, and nothing on it points anywhere.

The list shows how much each device has sent and when it last checked in. A
device that has never checked in hasn't been set up yet. Everything is in the
audit log under `field.device.*` and `field.submission.*`.

## Limits

The `FIELD_*` lines in `.env` set the photo size, attachments per report, and
writes per minute per device. The defaults are sensible; the rate limit is a
guard against a phone stuck retrying, not a quota (30 a minute is plenty).

---

## Put the app on a phone

The app is **HUMINT Field**, Android 10 or later. There are two ways to get it.
**Pick one per phone and stick to it** — see the warning below.

### From Google Play

Once it's published, install **HUMINT Field** from the Play Store link your
admin sends. Updates arrive like any other app. This avoids the "unknown app"
and Play Protect warnings that sideloaded files get.

### From GitHub (sideload)

1. On the phone, open the
   [latest release](https://github.com/xPirate/humint-platform/releases/latest)
   and download `humint-field-<version>.apk`.
2. If you can, check the download against the SHA-256 in the release notes
   (`shasum -a 256 file.apk` on a Mac, `sha256sum` on Linux, `Get-FileHash` in
   PowerShell).
3. Open the file. Android asks you to allow installs from the app you used
   (Chrome, Files). Allow it, go back, **Install**. You can turn that
   permission off afterwards.
4. If Play Protect warns about an unknown developer, choose
   **More details → Install anyway**. (This warning is why the Play listing
   exists.)

Or from a computer with `adb`:

```bash
adb install -r humint-field-1.4.apk
```

### Don't mix Play and GitHub installs on one phone

Android only installs an update over an app signed with the same key. Unless
the Play listing was set up with the project's own signing key (see
[Release the field app](release-the-field-app.md#2-set-up-signing-the-decision-you-cant-undo)),
a Play install and a GitHub APK are signed differently, and switching means
**uninstalling first — which deletes every unsent report on the phone.**
Send everything before switching.

### First launch

1. **Set a PIN.** It *is* the encryption key. **A forgotten PIN can't be
   recovered** by anyone; unsent reports are lost (sent ones are safe on the
   console). Use more than six digits — up to twelve.
2. Optionally turn on **Settings → Fingerprint shortcut**.
3. Allow camera, microphone and location when first asked. Location is only
   read while a report is open.

## Update the app on a phone

**Send everything first** (Send tab → scan the code) — belt and braces.

- **Play:** updates itself, or Play Store → Manage apps → Update.
- **GitHub:** download the new APK and install it over the old one. Same
  signing key, so the queue and PIN survive. If Android says the app
  "conflicts with an existing package", it was installed from the other
  channel (or is a debug build) — see the warning above.
