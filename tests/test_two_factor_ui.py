"""Two-factor sign-in in the browser: turning it on, signing in with it, and
being made to set it up when an admin requires it. Drives Chromium."""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import PASSWORD, Console, check, finish, ok  # noqa: E402

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("SKIP: playwright is not installed (pip install playwright)")
    finish()

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "api"))
import twofactor as T  # noqa: E402

c = Console("tfa_ui").start()
admin = c.register_admin()
c.add_user(admin, "ana")
c.add_user(admin, "ben")
shots = os.environ.get("SHOTS_DIR")


def code_for(secret, ahead=0):
    return T.code_at(secret, T.current_step() + ahead)


def sign_in(page, user, otp=None):
    page.goto(c.url)
    page.fill("#login-username", user)
    page.fill("#login-password", PASSWORD)
    page.click("#login-form button[type=submit]")
    if otp is not None:
        page.wait_for_selector("#login-otp", state="visible")
        page.fill("#login-otp", otp)
        page.click("#login-form button[type=submit]")


with sync_playwright() as pw:
    browser = pw.chromium.launch(executable_path=os.environ.get("CHROMIUM") or None)

    # ---- ana turns it on from the account menu --------------------------------
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    sign_in(page, "ana")
    page.wait_for_selector("#app:not([hidden])")
    page.click("#user-menu-btn")
    page.click("#user-menu-2fa")
    page.wait_for_selector(".tfa-qr svg")
    check(page.is_visible(".tfa-qr svg"), "Account → Two-factor sign-in shows a QR code")
    secret = re.sub(r"\s", "", page.inner_text(".tfa-secret"))
    if shots:
        page.screenshot(path=os.path.join(shots, "tfa-setup.png"))
    page.fill("#tfa-code", code_for(secret))
    page.click("#tfa-enable-form button[type=submit]")
    page.wait_for_selector(".tfa-codes")
    codes = page.inner_text(".tfa-codes").split()
    check(len(codes) == 10, "turning it on shows ten recovery codes")
    if shots:
        page.screenshot(path=os.path.join(shots, "tfa-codes.png"))

    # ---- and signs in with it -------------------------------------------------
    page2 = browser.new_page()
    sign_in(page2, "ana")
    page2.wait_for_selector("#login-otp", state="visible")
    check(page2.is_hidden("#app"), "after the password, the sign-in form asks for the code")
    if shots:
        page2.screenshot(path=os.path.join(shots, "tfa-login.png"))
    page2.fill("#login-otp", "000000" if code_for(secret, 1) != "000000" else "111111")
    page2.click("#login-form button[type=submit]")
    page2.wait_for_function("document.getElementById('login-error').textContent.length > 0")
    check("not right" in page2.inner_text("#login-error"), "a wrong code says so")
    page2.fill("#login-otp", code_for(secret, 1))
    page2.click("#login-form button[type=submit]")
    page2.wait_for_selector("#app:not([hidden])")
    check(page2.is_visible("#app"), "the right code signs in")

    # ---- admin requires it; ben has to set it up first ------------------------
    ok(admin.patch(c.url + "/api/admin/security-settings", json={"require_2fa": True}))
    page3 = browser.new_page()
    sign_in(page3, "ben")
    page3.wait_for_selector("#tfa-enrol .tfa-qr svg")
    check(page3.is_hidden("#app"), "with it required, someone without it sees only the setup")
    bsecret = re.sub(r"\s", "", page3.inner_text(".tfa-secret"))
    page3.fill("#tfa-code", code_for(bsecret))
    page3.click("#tfa-enable-form button[type=submit]")
    page3.wait_for_selector("#tfa-enrol-continue")
    page3.click("#tfa-enrol-continue")
    page3.wait_for_selector("#app:not([hidden])")
    check(page3.is_visible("#app"), "and is let in once it is on")
    browser.close()
finish()
