"""Two-factor sign-in with an authenticator app."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import PASSWORD, Console, check, finish, ok  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "api"))
import twofactor as T  # noqa: E402

# RFC 6238, appendix B: SHA-1 secret "12345678901234567890" at T=59 is 94287082.
check(T.code_at("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ", 59 // 30) == "287082",
      "codes match the RFC 6238 test vector")

c = Console("twofactor").start()
admin = c.register_admin()
ana = c.add_user(admin, "ana")
U = c.url


def code(secret, offset_steps=0, at=None):
    return T.code_at(secret, T.current_step(at) + offset_steps)


st = ok(ana.get(U + "/api/auth/2fa"))
check(st["enabled"] is False and st["required"] is False, "two-factor starts off")
setup = ok(ana.post(U + "/api/auth/2fa/setup"))
secret = setup["secret"]
check(setup["uri"].startswith("otpauth://totp/") and "secret=" + secret in setup["uri"] and "<svg" in setup["qr_svg"],
      "setup gives a QR code for the authenticator app")
r = ana.post(U + "/api/auth/2fa/enable", json={"code": "000000" if code(secret) != "000000" else "111111"})
check(r.status_code == 400, "a wrong code does not switch it on")
r = ok(ana.post(U + "/api/auth/2fa/enable", json={"code": code(secret)}))
recovery = r["recovery_codes"]
check(len(recovery) == 10 and len(set(recovery)) == 10, "a right code switches it on and gives ten recovery codes")
rows = c.sql("SELECT code_hash FROM user_recovery_codes uc JOIN users u ON u.id = uc.user_id WHERE u.username='ana'")
check(not any(rc in str(rows) for rc in recovery), "recovery codes are stored only as hashes")

# ---- signing in -------------------------------------------------------------
s, r = c.login("ana")
check(r.status_code == 401 and r.json()["detail"].get("otp_required") is True and "session" not in s.cookies,
      "the password alone asks for the code and gives no session")
check(c.sql("SELECT failed_login_attempts FROM users WHERE username='ana'")[0][0] == 0,
      "asking for the code is not counted as a failed sign-in")
s, r = c.login("ana", otp=code(secret))
check(r.status_code == 401, "the code already used to switch it on does not work again")
next_code = code(secret, 1)
s, r = c.login("ana", otp=next_code)
check(r.ok and ok(s.get(U + "/api/entities")) is not None, "password and a fresh code sign in")
s, r = c.login("ana", otp=next_code)
check(r.status_code == 401 and r.json()["detail"] == "That code is not right", "no code works twice")
s, r = c.login("ana", otp=recovery[0])
check(r.ok, "a recovery code works instead of the app")
s, r = c.login("ana", otp=recovery[0])
check(r.status_code == 401, "but only once")
audit = [a for (a,) in c.sql("SELECT action FROM audit_log WHERE actor_username = 'ana' OR object_label = 'ana'")]
check("auth.2fa_enabled" in audit and "auth.recovery_code_used" in audit, "switching it on and recovery use are audited")

# a field server whose clock is still being set from this device
future = time.time() + 900
s, r = c.login("ana", otp=code(secret, at=future), client_epoch_ms=int(future * 1000))
check(r.status_code == 409 and "clock" in r.json()["detail"],
      "a code right for the device's clock but not the server's says so, rather than 'wrong code'")
s, r = c.login("ana", otp=code(secret, at=future))
check(r.status_code == 401, "and is not accepted on the device's word")

# wrong codes count towards the lockout
c.sql("UPDATE users SET failed_login_attempts = 0 WHERE username = 'ana'")
for _ in range(5):
    s, r = c.login("ana", otp="123456" if code(secret) != "123456" else "654321")
check(r.status_code in (401, 423) and c.sql("SELECT locked_until IS NOT NULL FROM users WHERE username='ana'")[0][0],
      "five wrong codes lock the account like five wrong passwords")
c.sql("UPDATE users SET failed_login_attempts = 0, locked_until = NULL WHERE username = 'ana'")

# ---- required for everyone ---------------------------------------------------
ben = c.add_user(admin, "ben")
dee = c.add_user(admin, "dee")
r = ok(admin.patch(U + "/api/admin/security-settings", json={"require_2fa": True}))
check(r["require_2fa"] is True and r["note"], "an admin can require it (and is told they will need it too)")
check(dee.get(U + "/api/entities").status_code == 403, "someone already signed in without it is held to it at once")
check(admin.get(U + "/api/entities").status_code == 200, "except the admin who switched it on, mid-task")
s, r = c.login("ben")
check(r.ok and r.json().get("needs_2fa_setup") is True, "someone without it still signs in…")
check(s.get(U + "/api/entities").status_code == 403, "…to a session that can do nothing else")
check(ok(s.get(U + "/api/auth/me")).get("needs_2fa_setup") is True, "the console can tell it must ask for setup")
bsec = ok(s.post(U + "/api/auth/2fa/setup"))["secret"]
ok(s.post(U + "/api/auth/2fa/enable", json={"code": code(bsec)}))
check(s.get(U + "/api/entities").status_code == 200, "once set up, the same session works")

# ---- an admin resets a lost phone ---------------------------------------------
ok(admin.patch(U + "/api/admin/security-settings", json={"require_2fa": False}))
s_ana, r = c.login("ana", otp=recovery[1])
check(r.ok, "(ana signed in)")
ok(admin.post(U + f"/api/admin/users/{c.sql('SELECT id FROM users WHERE username=%s', ('ana',))[0][0]}/2fa/reset"))
check(s_ana.get(U + "/api/auth/me").status_code == 401, "a reset signs them out everywhere")
s, r = c.login("ana")
check(r.ok, "and they sign in with the password alone until they set it up again")
check("auth.2fa_reset" in [a for (a,) in c.sql("SELECT action FROM audit_log")], "the reset is audited")

# ---- turning it off needs the password ---------------------------------------
s2 = c.add_user(admin, "cyd")
csec = ok(s2.post(U + "/api/auth/2fa/setup"))["secret"]
ok(s2.post(U + "/api/auth/2fa/enable", json={"code": code(csec)}))
check(s2.post(U + "/api/auth/2fa/disable", json={"password": "wrong"}).status_code == 403,
      "it cannot be turned off without the password")
check(ok(s2.post(U + "/api/auth/2fa/disable", json={"password": PASSWORD}))["enabled"] is False,
      "with the password, it can")
finish()
