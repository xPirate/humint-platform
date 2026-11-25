"""Outside events, the model's triage, in the web console (Chromium): kept
incidents show the model's category, severity and summary; "N set aside"
opens what it filtered, each with its reason; "Keep it" and "Wrong call?"
correct it; Admin → Outside events → Model triage saves the model, the
severity shown and each area's focus."""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import PASSWORD, Console, check, finish  # noqa: E402

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("SKIP: playwright is not installed (pip install playwright)")
    finish()

c = Console("outside_triage_ui").start()
admin = c.register_admin()
z = admin.post(c.url + "/api/map/zones", json={
    "name": "Baltimore AOR", "environment": "Semi-permissive", "outside_events": True,
    "geometry": {"shape": "rectangle", "points": [[39.37, -76.72], [39.37, -76.52], [39.19, -76.52], [39.19, -76.72]]}}).json()
ZID = z["id"]
today = date.today().isoformat()
shots = os.environ.get("SHOTS_DIR")
c.sql("UPDATE outside_event_settings SET triage_enabled = true, triage_min_severity = 2")


def add(sid, title, is_event, in_area, cat, sev, summary, reason):
    return c.sql(
        f"INSERT INTO outside_events (source, source_id, occurred_on, title, category, lat, lon, place, precision, "
        f"url, zone_ids, triage_is_event, triage_in_area, triage_category, triage_severity, triage_summary, "
        f"triage_reason, triage_by, triage_model, triaged_at) VALUES ('gdelt', '{sid}', '{today}', '{title}', 'Fight', "
        f"39.29, -76.61, 'Baltimore, Maryland, United States', 'city', 'https://news.example.org/{sid}', "
        f"ARRAY[{ZID}], {is_event}, {in_area}, '{cat}', {sev}, '{summary}', '{reason}', 'model', 'qwen3:8b', now()) "
        f"RETURNING id")[0][0]


fire = add("G1", "Use unconventional violence", "true", "true", "disaster", 4,
           "Harbor Tunnel closed after a truck fire near the south portal.", "A closure affecting movement.")
arrest = add("G2", "Arrest, detain: Police", "true", "true", "police", 2,
             "Police arrested two after a protest at City Hall.", "A local arrest.")
film = add("G3", "Use conventional military force: Actor", "false", "true", "other", 1,
           "An actor talks about playing a soldier in a war film.", "A film role, not an event.")
tokyo = add("G4", "Demonstrate or rally", "true", "false", "protest", 2,
            "Thousands rallied in Tokyo.", "It happened in Tokyo.")

with sync_playwright() as pw:
    browser = pw.chromium.launch(executable_path=os.environ.get("CHROMIUM") or None)
    page = browser.new_page(viewport={"width": 1400, "height": 950})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(c.url)
    page.fill("#login-username", "admin")
    page.fill("#login-password", PASSWORD)
    page.click("#login-form button[type=submit]")
    page.wait_for_selector("#outside-tab:not([hidden])")
    check(page.inner_text("#outside-badge") == "2", "the unread count leaves out what the model set aside")
    page.click("#outside-tab")
    page.wait_for_selector("#outside-items > .feed-item")
    text = page.inner_text("#outside-items")
    check(page.locator("#outside-items > .feed-item").count() == 2, "two incidents kept")
    check("Harbor Tunnel closed after a truck fire" in text and "disaster or emergency" in text.lower() and "4 · significant" in text.lower(),
          "with the model's summary, category and severity")
    check(page.is_visible("#outside-category") and page.is_visible("#outside-sort"), "filters for kind and severity appear")
    page.select_option("#outside-category", "police")
    page.wait_for_function("() => document.querySelectorAll('#outside-items > .feed-item').length === 1")
    check("City Hall" in page.inner_text("#outside-items"), "filter by kind")
    page.select_option("#outside-category", "")
    page.wait_for_function("() => document.querySelectorAll('#outside-items > .feed-item').length === 2")
    if shots:
        page.screenshot(path=os.path.join(shots, "outside-triage.png"), full_page=True)

    # ---- what it set aside ----
    page.click("[data-oe-view=filtered]")
    page.wait_for_selector(".oe-viewline-filtered")
    text = page.inner_text("#outside-items")
    check(page.locator("#outside-items > .feed-item").count() == 2 and "Not an event" in text and "A film role" in text
          and "Not in the area" in text, "the set-aside view: each with the reason")
    if shots:
        page.screenshot(path=os.path.join(shots, "outside-triage-filtered.png"), full_page=True)
    page.click(f"[data-oe-keep='{film}']")
    page.wait_for_function("() => document.querySelectorAll('#outside-items > .feed-item').length === 1")
    check(c.sql(f"SELECT triage_by, triage_is_event FROM outside_events WHERE id = {film}")[0] == ("analyst", True),
          "\"Keep it\" puts it back, as a person's call")
    page.click("[data-oe-view=main]")
    page.wait_for_function("() => document.querySelectorAll('#outside-items > .feed-item').length === 3")

    # ---- a wrong call ----
    page.click(f"[data-oe-correct='{arrest}']")
    page.wait_for_selector(f"[data-oe-correct-form='{arrest}']")
    form = f"[data-oe-correct-form='{arrest}']"
    page.select_option(f"{form} select[name=category]", "protest")
    page.select_option(f"{form} select[name=severity]", "3")
    page.click(f"{form} button[type=submit]")
    page.wait_for_function(f"() => !document.querySelector(\"[data-oe-correct-form='{arrest}']\")")
    check(c.sql(f"SELECT triage_category, triage_severity, triage_by FROM outside_events WHERE id = {arrest}")[0]
          == ("protest", 3, "analyst"), "\"Wrong call?\" sets the kind and severity")
    check(c.sql("SELECT count(*) FROM outside_triage_corrections")[0][0] == 2, "both kept as examples for the model")

    # ---- admin ----
    page.evaluate("() => { switchView('admin'); showAdminSection('outside'); }")
    page.wait_for_selector("#oe-tr-on")
    check(page.is_checked("#oe-tr-on") and "2 corrected by people" in page.inner_text("#outside-settings"),
          "Admin shows the triage and what people corrected")
    page.fill("#oe-tr-model", "qwen3:14b")
    page.select_option("#oe-tr-min", "3")
    page.click("#outside-form button[type=submit]")
    page.wait_for_timeout(800)
    check(c.sql("SELECT triage_model, triage_min_severity FROM outside_event_settings")[0] == ("qwen3:14b", 3),
          "the model and the severity shown save")
    page.wait_for_selector(f"#oe-focus-{ZID}")
    page.fill(f"#oe-focus-{ZID}", "civil unrest, threats to the port and tunnels")
    page.click(f"[data-oe-focus='{ZID}']")
    page.wait_for_timeout(600)
    check(c.sql(f"SELECT outside_focus FROM map_zones WHERE id = {ZID}")[0][0] == "civil unrest, threats to the port and tunnels",
          "an area's focus saves")
    if shots:
        page.screenshot(path=os.path.join(shots, "outside-triage-admin.png"), full_page=True)
    page.click("#oe-tr-again")
    page.wait_for_timeout(600)
    check(c.sql(f"SELECT triaged_at IS NULL FROM outside_events WHERE id = {fire}")[0][0] is True
          and c.sql(f"SELECT triaged_at IS NULL FROM outside_events WHERE id = {arrest}")[0][0] is False,
          "\"Judge the last week again\" requeues the model's calls, not people's")
    check(not errors, f"no page errors ({errors[:3]})")
    browser.close()
finish()
