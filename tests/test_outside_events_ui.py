"""Outside events in the web console, in Chromium: the zone form's checkbox,
Admin → Outside events (rates, "fastest the terms allow", refusing to go under
GDELT's floors), the Outside events page, and the map layer."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import PASSWORD, Console, check, finish  # noqa: E402

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("SKIP: playwright is not installed (pip install playwright)")
    finish()

c = Console("outside_ui").start()
admin = c.register_admin()
zone = admin.post(c.url + "/api/map/zones", json={
    "name": "Baltimore AOR", "environment": "Semi-permissive",
    "geometry": {"shape": "rectangle", "points": [[39.37, -76.72], [39.37, -76.52], [39.19, -76.52], [39.19, -76.72]]}}).json()
shots = os.environ.get("SHOTS_DIR")


def sign_in(page):
    page.goto(c.url)
    page.fill("#login-username", "admin")
    page.fill("#login-password", PASSWORD)
    page.click("#login-form button[type=submit]")
    page.wait_for_selector("#app:not([hidden])")


with sync_playwright() as pw:
    browser = pw.chromium.launch(executable_path=os.environ.get("CHROMIUM") or None)
    page = browser.new_page(viewport={"width": 1400, "height": 950})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    sign_in(page)
    check(page.is_hidden("#outside-tab"), "no Outside events tab while no zone is marked")

    # ---- the zone form ----
    zone_full = admin.get(c.url + f"/api/map/zones/{zone['id']}").json()
    page.evaluate("z => openZoneForm(z, null)", zone_full)
    page.wait_for_selector("#zone-outside")
    page.check("#zone-outside")
    page.click("#zone-form button[type=submit]")
    page.wait_for_function("() => !document.getElementById('zone-form')")
    check(c.sql(f"SELECT outside_events FROM map_zones WHERE id = {zone['id']}")[0][0] is True,
          "the zone form marks a zone as an area")

    # ---- admin settings ----
    page.evaluate("() => { switchView('admin'); showAdminSection('outside'); }")
    page.wait_for_selector("#oe-g-on")
    check("Baltimore AOR" in page.inner_text("#outside-settings"), "the marked areas are listed")
    page.check("#oe-g-on")
    page.fill("#oe-g-sp", "2")
    page.click("#outside-form button[type=submit]")
    page.wait_for_timeout(500)
    check(page.evaluate("() => document.getElementById('oe-g-sp').validity.rangeUnderflow")
          and c.sql("SELECT gdelt_enabled FROM outside_event_settings")[0][0] is False,
          "under GDELT's 5 s the form will not submit (and the API refuses it too)")
    page.fill("#oe-g-sp", "30")
    page.click("#outside-fastest")
    page.wait_for_timeout(800)
    row = c.sql("SELECT gdelt_enabled, gdelt_interval_minutes, gdelt_request_spacing_seconds FROM outside_event_settings")[0]
    check(row == (True, 15, 5), f"\"Fastest the terms allow\": on, every 15 minutes, 5 s apart ({row})")
    if shots:
        page.screenshot(path=os.path.join(shots, "outside-admin.png"), full_page=True)

    # ---- events, as the worker leaves them ----
    for i, t in enumerate(["Demonstrate or rally: Protester → Police",
                           "Arrest, detain, or charge with legal action: Police → Suspect"]):
        c.sql(f"INSERT INTO outside_events (source, source_id, occurred_on, title, category, lat, lon, place, "
              f"precision, num_sources, url, zone_ids) VALUES ('gdelt', 'W{i}', current_date, '{t}', 'Protest', "
              f"39.29, -76.61, 'Baltimore, Maryland, United States', 'city', 3, 'https://news.example.org/{i}', "
              f"ARRAY[{zone['id']}])")
    page.goto(c.url)
    page.wait_for_selector("#outside-tab:not([hidden])")
    check(page.inner_text("#outside-badge") == "2", "the tab appears, with the unread count")
    page.click("#outside-tab")
    page.wait_for_selector("#outside-items .feed-item")
    check(page.locator("#outside-items .feed-item").count() == 2, "the page lists them")
    check("GDELT Project" in page.inner_text("#outside-credit")
          and page.get_attribute("#outside-credit a", "href") == "https://www.gdeltproject.org/",
          "GDELT credited, with a link")
    if shots:
        page.screenshot(path=os.path.join(shots, "outside-page.png"), full_page=True)
    page.click("[data-oe-status=dismissed] >> nth=0")
    page.wait_for_function("() => document.querySelectorAll('#outside-items .feed-item').length === 1")
    page.click("[data-oe-send]")
    page.uncheck("#oe-fetch")
    page.click("#send-oe-submit")
    page.wait_for_function("() => !document.getElementById('send-oe-form')")
    check(c.sql("SELECT count(*) FROM outside_events WHERE status = 'sent'")[0][0] == 1, "sent to Documents")

    # ---- the map layer ----
    page.evaluate("() => switchView('map')")
    page.wait_for_selector("#map-container .leaflet-container, #map-container.leaflet-container", timeout=15000)
    page.wait_for_timeout(1500)
    check(page.locator(".outside-pin").count() >= 1, "the map shows outside events")
    page.uncheck("#outside-show")
    page.wait_for_timeout(300)
    check(page.locator(".outside-pin").count() == 0, "and the layer can be switched off")
    check(not errors, f"no page errors ({errors[:3]})")
    browser.close()
finish()
