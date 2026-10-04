# Google Play listing

Everything the Play Console store listing asks for, kept with the app so it
changes in the same commit as the app does. The how-to for publishing is
[docs/how-to/release-the-field-app.md](../../docs/how-to/release-the-field-app.md).

| File | Play Console field |
|---|---|
| `play-icon-512.png` | App icon (512 × 512 PNG) |
| `play-feature-1024x500.png` | Feature graphic (1024 × 500) |
| `icon.html`, `feature.html` | Sources for the two images |
| this file | App name, short description, full description |

Phone screenshots are not here: take them from a **debug** build, which
leaves screenshots on (release builds block them with `FLAG_SECURE`). Use
invented data — the exercise set in `docs/exercise/` — never a real case.

## Regenerating the images

The glyph is the same paths as `app/src/main/res/drawable/ic_launcher_foreground.xml`.
After changing either HTML file, render with Playwright's Chromium:

```bash
cd android/store
node -e "
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  for (const [f, w, h, out] of [['icon',512,512,'play-icon-512.png'],
                                ['feature',1024,500,'play-feature-1024x500.png']]) {
    const p = await b.newPage({ viewport: { width: w, height: h } });
    await p.goto('file://' + process.cwd() + '/' + f + '.html');
    await p.screenshot({ path: out });
  }
  await b.close();
})();"
```

---

## App name

    HUMINT Field

## Short description (80 characters max)

    Offline, encrypted field reports for teams running a HUMINT Platform console.

## Full description

    HUMINT Field is the reporting app for teams that run their own HUMINT
    Platform console — a self-hosted, open-source case-management server.

    Write it down where you are, with or without signal. Pick a form — signal,
    person, vehicle, activity (SALUTE), bearing, place, or a quick note — fill
    it in, and attach photos, video, voice memos, or screenshots. Everything
    is saved as you type and stays on the phone, encrypted, until you're back
    in range of your team's console. Then scan the console's QR code and the
    queue empties.

    Built for phones that might be lost or handed over:
    • Reports are encrypted with a key that needs both your PIN and the
      phone's hardware keystore.
    • The app never stores your console's address or access token. They're
      read from the QR code when you send and forgotten straight after.
    • Its device credential can send reports and nothing else — it cannot read
      anything back from the console.
    • Screenshots and the recent-apps preview are blocked.
    • Sent reports are erased from the phone.

    No accounts, no ads, no analytics, no crash reporting, and no Google Play
    Services. Location is read only while a report is open on screen.

    You need a HUMINT Platform console to send reports to. The console and
    this app are open source: github.com/xPirate/humint-platform

## Category and contact

- Category: **Productivity** (or Tools)
- Tags: field reporting, offline, encrypted
- Contact email: an address you're happy to publish
- Website: `https://github.com/xPirate/humint-platform`
- Privacy policy: `https://github.com/xPirate/humint-platform/blob/main/docs/PRIVACY-FIELD.md`
