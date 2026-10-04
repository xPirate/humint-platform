# How to release the field app

Two channels:

- **GitHub** — a signed APK on the Releases page that people sideload.
  Works on de-Googled phones; triggers "unknown app" and Play Protect warnings.
- **Google Play** — an app bundle (`.aab`) that Google signs and delivers.
  No sideloading warnings, automatic updates; needs a developer account and
  some forms filled in.

You can run both. Read
[step 2 of the Play section](#2-set-up-signing-the-decision-you-cant-undo)
before your first Play upload — it decides whether the two channels can update
each other.

Build details (JDK, SDK, tests, why never the debug APK) are in
[`android/README.md`](../../android/README.md).

---

## Before every release

1. **Bump the version** in `android/app/build.gradle.kts`:
   `versionCode` (an integer that must go up every release, on both channels)
   and `versionName` (what people see, e.g. `"1.4"`). Use the same numbers on
   GitHub and Play.
2. **Use JDK 21.** Newer JDKs (Android Studio's bundled JBR 25) break the
   Kotlin compiler with an error that is just a version number. On the Mac
   build folder, the scripts already use `.toolchain/jdk21`; by hand:

   ```bash
   export JAVA_HOME=/path/to/jdk21
   ```

3. **Have `android/keystore.properties`** pointing at the release keystore
   (`field-release.jks`, kept outside the repo). Without it, release builds
   come out unsigned.

---

## Publish on GitHub (APK)

1. **Build:**

   ```bash
   cd android
   ./gradlew clean assembleRelease
   # → app/build/outputs/apk/release/app-release.apk
   ```

   On the Mac: run `build-release.command`, then `sign-release.command` if the
   build came out unsigned.
2. **Check it** (Android build-tools on your PATH or via `$ANDROID_HOME`):

   ```bash
   apksigner verify --print-certs app-release.apk   # must NOT say "Android Debug"
   aapt dump badging app-release.apk | head -3      # org.humint.field, right version
   shasum -a 256 app-release.apk
   ```

   The signer certificate SHA-256 must be
   `47:54:2F:4F:BE:D5:5A:9C:00:A6:1E:01:98:3C:6A:A2:AA:41:F1:66:1B:DE:ED:61:01:E1:CE:4C:BB:5C:DA:A0`.
3. **Rename** to `humint-field-<version>.apk`.
4. On GitHub: **Releases → Draft a new release**. Create the tag `v<version>`
   **on the commit you built from** (usually `main`), attach the APK, and put
   in the notes:
   - the SHA-256 of the file;
   - how to allow the install (open the file, allow installs from Chrome/Files,
     go back, Install) and how to check the hash;
   - that the PIN *is* the encryption and can't be recovered, and that every
     upload starts by scanning a QR.
5. Update **"Current release"** in `android/README.md` with the version, size
   and SHA-256, and commit.

---

## Publish on Google Play (AAB)

### 0. Use 1.5 or later

Since **31 August 2026** Play requires new apps and updates to target
**Android 16 (API 36)**. Field **1.5** (versionCode 6) is the first build that
does — `compileSdk`/`targetSdk` 36 on Android Gradle Plugin 8.9.1 — so it is
the first one Play will accept. Its native libraries are also 16 KB-aligned,
which Play checks for apps targeting Android 15 and later. 1.4 and earlier are
GitHub-only.

### 1. Get a developer account

1. Sign up at [play.google.com/console](https://play.google.com/console) —
   a one-off fee, plus identity verification.
2. Choose **personal** or **organization**:
   - **Personal** accounts made after 13 Nov 2023 must run a **closed test
     with at least 12 testers opted in for 14 days in a row** before they can
     apply for public (production) release.
   - **Organization** accounts need a D-U-N-S number but skip that rule.

**For a team app, you may never need production.** The **internal testing**
track takes up to 100 testers by email, is available within minutes, and
needs no 12-tester wait. Analysts install it from Play through an opt-in link
and get updates like any other app, with no sideloading warnings. Start there.

### 2. Set up signing (the decision you can't undo)

Play signs what it delivers with its **app signing key**. You choose that key
when you create the app, and you can't change it afterwards.

| Option | Result |
|---|---|
| **Use your own key** — "Use a different key" → **Export and upload a key from Java keystore**, with `field-release.jks` | Play builds are signed with the **same certificate as the GitHub APKs** (`47:54:2F…`). Phones can move between channels and update across them without uninstalling. **Recommended.** |
| **Let Google generate a key** (the default) | Play builds and GitHub APKs have different signatures. A phone with one **must uninstall to switch to the other — deleting every unsent report.** You'd have to pick one channel per phone, permanently. |

To use your own key:

1. **Create app** in Play Console (package `org.humint.field`).
2. When it asks about Play App Signing, choose **Use a different key →
   Export and upload a key from Java keystore**.
3. Download the PEPK tool and encryption key it offers, and run the command
   Play shows, pointing at `field-release.jks` and alias `field`. Upload the
   resulting encrypted zip.
4. **Upload key:** Play asks for the certificate of the key you'll sign
   uploads with. Simplest is the same `field-release.jks`; Google recommends a
   separate upload key (a second keystore) so a leaked upload key can be reset
   without touching the app signing key. Either works.

Never lose `field-release.jks` or its passwords — it now signs both channels.

### 3. Build and sign the bundle

**On the Mac build folder:** run `build-release.command` (it now builds the
APK *and* the bundle), then `sign-bundle.command`. That signs
`app-release.aab` with `field-release.jks` and writes
`~/Downloads/humint-field-<version>.aab`. If you registered a separate upload
key, run it as
`KEYSTORE=~/humint-keys/upload.jks ALIAS=upload bash ~/Downloads/sign-bundle.command`.

**By hand:**

```bash
cd android
./gradlew clean bundleRelease
# → app/build/outputs/bundle/release/app-release.aab
```

With `keystore.properties` present, Gradle signs it with that key — which must
be the upload key you registered. Without it the bundle is unsigned; sign it
with `jarsigner`:

```bash
jarsigner -sigalg SHA256withRSA -digestalg SHA-256 \
    -keystore ~/humint-keys/field-release.jks app-release.aab field
```

### 4. Fill in the app's details

Under **Policy and programs → App content** and **Store presence**:

- **Privacy policy URL** — required because the app uses the camera,
  microphone and location. Use
  `https://github.com/xPirate/humint-platform/blob/main/docs/PRIVACY-FIELD.md`
  (edit it first if your deployment differs).
- **App access** — "All functionality is available without an account. Set
  any PIN on first launch. Sending reports requires scanning a QR code from a
  self-hosted console, which is not needed to review the app."
- **Ads** — No.
- **Content rating** — fill in the questionnaire (a utility with no
  user-to-user content).
- **Target audience** — 18 and over.
- **Data safety** — see below.
- **Store listing** — everything is ready in
  [`android/store/`](../../android/store/README.md): the name, the short and
  full descriptions, the 512×512 icon and the 1024×500 feature graphic. You
  add at least two phone screenshots.

**Screenshots:** release builds block screenshots (`FLAG_SECURE`), so take
them from a **debug** build, which leaves them on — on the phone or an
emulator, with invented data such as the exercise set, never a real case.

The prepared description says plainly what the app is. Keep it that way:
anything that reads as covert monitoring of other people's devices is not
what the app does, and Play reviews that category hard.

#### Data safety answers

The app sends data only to a console the user's own team runs, chosen by
scanning its QR code, never to the developer or any third party. Declare it
anyway — Play counts any transfer off the device:

| Question | Answer |
|---|---|
| Data collected | **Location** (precise), **Photos and videos**, **Audio** (voice recordings), **Other user-generated content** (report text). |
| Shared with third parties | No. |
| Purpose | App functionality. |
| Required or optional | Optional — the user decides what goes in each report. |
| Encrypted in transit | Answer **No** unless every console you deploy uses HTTPS: the app allows plain HTTP for LAN consoles. |
| Users can request deletion | Data on the phone is deleted by the user in the app; data on a console is held by the team that runs it. |

No crash reporting, analytics or Google Play Services are included.

Permissions to expect questions about: camera, microphone, precise location
(foreground only — **no** background location, so no extra declaration). The
photo picker needs no media permission.

### 5. Release to testers

1. **Testing → Internal testing → Create new release**.
2. Upload `app-release.aab`, write release notes, **Review release → Start
   rollout**.
3. **Testers** tab: add the analysts' Google account emails (or a Google
   Group), save, and send them the **opt-in link**.
4. Each analyst opens the link on the phone, accepts, then installs from
   Play.

Later, for a wider rollout: **Closed testing** (and, on a personal account,
the 12-testers-for-14-days run), then **Apply for production**.

### 6. Every update after that

1. Bump `versionCode`/`versionName`.
2. `./gradlew bundleRelease` (Play) and `./gradlew assembleRelease` (GitHub)
   from the same commit.
3. Upload the `.aab` to the same track; attach the `.apk` to a GitHub release.

### Android developer verification

Google is rolling out a requirement that apps on certified Android phones —
**sideloaded ones included** — come from a verified developer: from
30 September 2026 in Brazil, Indonesia, Singapore and Thailand, expanding in
2027. A verified Play Console account with this app registered is the main
route to that, and because the GitHub APK is signed with the same key (if you
chose option 1 above), it's the same registered app. Check the current rules
in Play Console when you set up.

---

## Release checklist

- [ ] `versionCode` bumped, same on both channels
- [ ] Built with JDK 21, from a clean tree on `main`
- [ ] `apksigner` shows certificate `47:54:2F…`, not Android Debug
- [ ] APK renamed with the version, SHA-256 in the GitHub notes
- [ ] Tag created on the commit you built from
- [ ] `.aab` uploaded to the Play track
- [ ] `android/README.md` "Current release" updated
