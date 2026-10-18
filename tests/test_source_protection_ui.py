"""Protecting a source, and a read-only account, in the browser."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import PASSWORD, Console, check, finish, ok  # noqa: E402

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("SKIP: playwright is not installed (pip install playwright)")
    finish()

c = Console("sources_ui").start()
admin = c.register_admin()
ana = c.add_user(admin, "ana")
c.add_user(admin, "ben")
c.add_user(admin, "vic", role="viewer")
src = ok(ana.post(c.url + "/api/entities", json={"entity_type": "source", "name": "Marta Novakova",
                                                  "description": "Clerk at the port authority."}))
shots = os.environ.get("SHOTS_DIR")


def signed_in(browser, user):
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    page.goto(c.url)
    page.fill("#login-username", user)
    page.fill("#login-password", PASSWORD)
    page.click("#login-form button[type=submit]")
    page.wait_for_selector("#app:not([hidden])")
    return page


def open_record(page, entity_id):
    page.evaluate(f"openEntityDetail({entity_id!r})")
    page.wait_for_selector("#source-protection .source-protect-card")


with sync_playwright() as pw:
    browser = pw.chromium.launch(executable_path=os.environ.get("CHROMIUM") or None)
    page = signed_in(browser, "ana")
    open_record(page, src["id"])
    page.click("#src-protect-btn")
    page.fill("#protect-code", "KESTREL")
    page.click("#protect-form button[type=submit]")
    page.wait_for_selector(".source-protect-card.protected")
    check("KESTREL" in page.inner_text("#entity-detail-body h2"), "after protecting, the record shows the code name")
    page.click("#src-identity-btn")
    page.wait_for_selector("#src-true-name")
    check(page.input_value("#src-true-name") == "Marta Novakova", "its handler can show the identity")
    if shots:
        page.screenshot(path=os.path.join(shots, "source-protected.png"))

    other = signed_in(browser, "ben")
    open_record(other, src["id"])
    text = other.inner_text("#entity-detail-body")
    check("Marta" not in text and "ana" in other.inner_text("#source-protection"),
          "another analyst sees the code name and who handles it, not who it is")
    check(other.query_selector("#src-identity-btn") is None, "and has no way to show the identity")

    viewer = signed_in(browser, "vic")
    check(viewer.is_hidden("#new-entity-btn") and "Read-only" in viewer.inner_text("#user-menu-role"),
          "a read-only account is not offered + New Entity, and is told it is read-only")
    open_record(viewer, src["id"])
    check(viewer.is_hidden("#edit-entity-btn"), "nor Edit on a record")
    if shots:
        viewer.screenshot(path=os.path.join(shots, "viewer.png"))
    browser.close()
finish()
