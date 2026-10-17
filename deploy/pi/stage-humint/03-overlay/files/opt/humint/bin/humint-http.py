#!/usr/bin/env python3
"""Port 80 when the console is on HTTPS: hand out the CA certificate, and send
everything else to https://.

The trust page and the certificate are served over plain HTTP on purpose —
it is how a device gets the certificate it needs before HTTPS can work for it.
That is only as safe as the network it is fetched over (the field Wi-Fi, with
its passphrase), so the page shows the fingerprints to compare against the
box's own screen or `humint-ctl tls`.

The page puts the visitor's own platform first, read from the browser's
User-Agent: Windows, macOS, Linux (Arch, Ubuntu/Debian, others), Android,
iPhone/iPad. Every other platform's steps sit folded underneath, so a
misdetected device (an iPad reports itself as a Mac) is one click from the
right ones. Firefox keeps its own list of authorities on most systems, so a
Firefox visitor also gets Firefox's own import steps up front.

  /trust          the page
  /ca.crt         the CA certificate, PEM (phones, macOS, Linux, Firefox)
  /ca.cer         the same certificate, DER (Windows, Group Policy, Intune)
  anything else   308 to https://, method and body kept

Standard library only; runs as humintd with CAP_NET_BIND_SERVICE.
"""
import base64
import hashlib
import html
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CA = "/var/lib/humint/ca.crt"
PORT = int(os.environ.get("HTTP_PORT", "80"))
HTTPS_PORT = os.environ.get("HTTPS_PORT", "443")
NAME = os.environ.get("INSTANCE_NAME", "HUMINT field server")
FILE = "humint-console-ca"


# ---------------------------------------------------------------------------
# The certificate, in both encodings, and its fingerprints
# ---------------------------------------------------------------------------

def load_ca():
    """(pem bytes, der bytes, sha256 'AA:BB…', sha1 'AA:BB…'), or None."""
    try:
        pem = open(CA, "rb").read()
    except OSError:
        return None
    m = re.search(rb"-----BEGIN CERTIFICATE-----(.+?)-----END CERTIFICATE-----", pem, re.S)
    if not m:
        return None
    der = base64.b64decode(b"".join(m.group(1).split()))

    def fp(algo):
        return ":".join(f"{b:02X}" for b in hashlib.new(algo, der).digest())
    return pem, der, fp("sha256"), fp("sha1")


def fp_rows(fp, per_row=8):
    pairs = fp.split(":")
    return [":".join(pairs[i:i + per_row]) for i in range(0, len(pairs), per_row)]


# ---------------------------------------------------------------------------
# Which platform is asking
# ---------------------------------------------------------------------------

def detect(ua: str):
    """(platform key, is_firefox). Best effort — the page lists the rest."""
    ua = ua or ""
    firefox = "Firefox/" in ua and "Seamonkey" not in ua
    if re.search(r"iPhone|iPad|iPod", ua):
        return "ios", False                    # Firefox on iOS uses the system's list
    if "Android" in ua:
        return "android", firefox
    if "Windows" in ua:
        return "windows", firefox
    if "Macintosh" in ua or "Mac OS X" in ua:
        return "macos", firefox
    if "Linux" in ua or "X11" in ua:
        return "linux", firefox
    return "unknown", firefox


# ---------------------------------------------------------------------------
# The steps, per platform
# ---------------------------------------------------------------------------

def code(cmd):
    return f'<pre class="cmd"><code>{html.escape(cmd)}</code></pre>'


def steps_windows(host):
    return f"""
<ol>
<li><a href="/ca.cer">Download the certificate</a> (<code>{FILE}.cer</code>) and open it.</li>
<li><b>Install Certificate…</b> → <b>Current User</b> → Next.</li>
<li>Choose <b>Place all certificates in the following store</b> → <b>Browse…</b> →
    <b>Trusted Root Certification Authorities</b> → OK → Next → Finish.</li>
<li>Windows shows a security warning with a <b>thumbprint (sha1)</b>. Check it matches
    the SHA-1 line above, then <b>Yes</b>.</li>
<li>Restart the browser. Edge and Chrome use this list; for Firefox see its section.</li>
</ol>
<p class="muted">Or in PowerShell (no admin needed), from the folder it downloaded to:</p>
{code(f"Import-Certificate -FilePath .\\{FILE}.cer -CertStoreLocation Cert:\\CurrentUser\\Root")}
<p class="muted"><b>Many managed laptops?</b> Push <code>{FILE}.cer</code> once instead, as a trusted
root: Group Policy (Computer Configuration → Policies → Windows Settings → Security Settings →
Public Key Policies → Trusted Root Certification Authorities → Import) or an Intune
<i>Trusted certificate</i> profile.</p>"""


def steps_macos(host):
    return f"""
<ol>
<li><a href="/ca.crt">Download the certificate</a> and open it. Keychain Access asks where to
    add it: <b>login</b>.</li>
<li>In Keychain Access, find <b>HUMINT field console CA</b> and double-click it.</li>
<li>Check the <b>SHA-256</b> fingerprint at the bottom against the one above.</li>
<li>Open <b>Trust</b> → <b>When using this certificate</b> → <b>Always Trust</b>. Close the window
    and enter your password.</li>
<li>Restart the browser. Safari and Chrome use this; for Firefox see its section.</li>
</ol>
<p class="muted">Or in Terminal, for every account on the Mac (needs an admin password):</p>
{code(f"sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain ~/Downloads/{FILE}.crt")}"""


def _linux_chrome():
    return f"""
<h3>Chrome, Chromium, Brave, Vivaldi</h3>
<p>On Linux these read their own certificate database, not the system's, so add it there too
(<code>certutil</code> is in <code>nss</code> on Arch, <code>libnss3-tools</code> on
Ubuntu/Debian, <code>nss-tools</code> on Fedora):</p>
{code(f'certutil -d sql:$HOME/.pki/nssdb -A -t "C,," -n "HUMINT field console" -i {FILE}.crt')}
<p class="muted">Then restart the browser. Firefox has its own section.</p>"""


LINUX_DISTROS = [
    ("arch", "Arch (and Manjaro, EndeavourOS)",
     f"sudo cp {FILE}.crt /etc/ca-certificates/trust-source/anchors/\nsudo update-ca-trust extract"),
    ("debian", "Ubuntu / Debian (and Mint, Pop!_OS)",
     f"sudo cp {FILE}.crt /usr/local/share/ca-certificates/{FILE}.crt\nsudo update-ca-certificates"),
    ("fedora", "Fedora / RHEL / Rocky",
     f"sudo cp {FILE}.crt /etc/pki/ca-trust/source/anchors/\nsudo update-ca-trust"),
    ("suse", "openSUSE",
     f"sudo cp {FILE}.crt /etc/pki/trust/anchors/\nsudo update-ca-certificates"),
]


def steps_linux(host, first=None):
    """One section for every distro: browsers do not say which one they run
    on, so all of them are shown, the detected one (if any) first."""
    distros = sorted(LINUX_DISTROS, key=lambda d: d[0] != first)
    parts = "".join(f"<p><b>{label}</b></p>{code(cmd)}" for _, label, cmd in distros)
    return f"""
<p>Fetch it and check the fingerprint against the box:</p>
{code(f"curl -fsSo {FILE}.crt http://{host}/ca.crt\nopenssl x509 -in {FILE}.crt -noout -fingerprint -sha256")}
<h3>Trust it system-wide</h3>
<p class="muted">curl, wget, Python and most apps use this. Run the lines for your distribution:</p>
{parts}
{_linux_chrome()}"""


def steps_firefox(host):
    return """
<p>Firefox keeps its own list of authorities on most systems, so add it there as well:</p>
<ol>
<li><a href="/ca.crt">Download the certificate</a>.</li>
<li>Settings → <b>Privacy &amp; Security</b> → scroll to <b>Certificates</b> →
    <b>View Certificates…</b> → <b>Authorities</b> → <b>Import…</b></li>
<li>Choose the file, tick <b>Trust this CA to identify websites</b> → OK.</li>
</ol>"""


def steps_android(host):
    return """
<ol>
<li><a href="/ca.crt">Download the certificate</a>.</li>
<li>Settings → <b>Security &amp; privacy</b> → <b>More security settings</b> →
    <b>Encryption &amp; credentials</b> → <b>Install a certificate</b> → <b>CA certificate</b> →
    <b>Install anyway</b> → choose the file. (Menu names vary by maker — searching Settings
    for <i>CA certificate</i> finds it.)</li>
<li>Chrome and the HUMINT Field app both trust it from then on.</li>
</ol>"""


def steps_ios(host):
    return """
<ol>
<li>In <b>Safari</b>, <a href="/ca.crt">download the certificate</a> and allow the profile.</li>
<li>Settings → General → <b>VPN &amp; Device Management</b> → the HUMINT profile → <b>Install</b>.</li>
<li>Settings → General → About → <b>Certificate Trust Settings</b> → turn on
    <b>HUMINT field console CA</b>.</li>
</ol>"""


PLATFORMS = [
    ("windows", "Windows", steps_windows),
    ("macos", "macOS", steps_macos),
    ("linux", "Linux (Arch, Ubuntu/Debian, Fedora, openSUSE)", steps_linux),
    ("firefox", "Firefox (any system)", steps_firefox),
    ("android", "Android", steps_android),
    ("ios", "iPhone / iPad", steps_ios),
]
LABEL = {k: label for k, label, _ in PLATFORMS}

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Trust {name}</title>
<style>
 :root{{color-scheme:dark}}
 body{{font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif;margin:0;padding:28px 16px 48px;background:#0f1411;color:#dfe8e2}}
 main{{max-width:680px;margin:auto}} h1{{font-size:24px;margin:0 0 6px}} h2{{font-size:17px;margin:28px 0 8px}}
 a{{color:#7fd6a2}} .muted{{color:#93a69a}} b{{color:#f1f7f3}}
 .btns{{display:flex;flex-wrap:wrap;gap:10px;margin:18px 0 6px}}
 .btn{{display:inline-block;background:#2f9e5f;color:#fff;padding:11px 18px;border-radius:8px;text-decoration:none;font-weight:600}}
 .btn.alt{{background:#1b231e;border:1px solid #2f3d34;color:#dfe8e2}}
 .fp{{background:#1b231e;border:1px solid #2f3d34;border-radius:8px;padding:12px 14px;margin:8px 0}}
 .fp div{{font:13.5px/1.7 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;white-space:nowrap;letter-spacing:.02em}}
 .fp .lbl{{font:12px system-ui,sans-serif;color:#93a69a;letter-spacing:0;margin-top:6px}}
 .fp .lbl:first-child{{margin-top:0}}
 pre.cmd{{background:#1b231e;border:1px solid #2f3d34;border-radius:8px;padding:10px 12px;overflow-x:auto;margin:8px 0}}
 pre.cmd code{{font:13px/1.5 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;white-space:pre-wrap;overflow-wrap:anywhere}}
 h3{{font-size:15px;margin:18px 0 4px}}
 code{{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:.92em;white-space:nowrap}}
 li{{margin:6px 0}} ol{{padding-left:22px}}
 .yours{{border:1px solid #2f9e5f;border-radius:10px;padding:4px 18px 10px;margin-top:22px}}
 .yours h2{{margin-top:14px}} .tag{{font-size:12px;font-weight:600;color:#7fd6a2;text-transform:uppercase;letter-spacing:.06em}}
 details{{border-top:1px solid #2a352e;padding:10px 0}} details:last-of-type{{border-bottom:1px solid #2a352e}}
 summary{{cursor:pointer;font-weight:600}} summary::marker{{color:#93a69a}}
 .note{{font-size:14px}}
</style></head><body><main>
<h1>Trust {name}</h1>
<p class="muted">Do this once on each phone or computer. Afterwards the console opens over HTTPS with no warnings, on any address the box moves to.</p>
<div class="btns"><a class="btn" href="/ca.crt">Download certificate (.crt)</a><a class="btn alt" href="/ca.cer">Windows / Group Policy (.cer)</a></div>
<p class="note">Check the fingerprint matches the one on the box's screen (Trust tab) or <code>humint-ctl tls</code> before you trust it:</p>
<div class="fp">{fingerprints}</div>
<p class="muted note">It can only vouch for local consoles like this one — <i>.local</i> names and private addresses. It cannot be used to impersonate any public website.</p>
{yours}
<h2>Other devices</h2>
{others}
<p style="margin-top:26px"><a href="{https}">Continue to the console →</a></p>
</main></body></html>"""


def render(host, ua, https_url):
    ca = load_ca()
    if ca:
        _, _, sha256, sha1 = ca
        rows = "".join(f"<div>{r}</div>" for r in fp_rows(sha256))
        fingerprints = (f'<div class="lbl">SHA-256</div>{rows}'
                        f'<div class="lbl">SHA-1 — the thumbprint Windows shows</div><div>{sha1}</div>')
    else:
        fingerprints = '<div class="lbl">Not ready yet — unlock the console first.</div>'
    platform, firefox = detect(ua)
    distro = None
    if platform == "linux":
        for key, pattern in (("debian", r"Ubuntu|Debian|Mint|Pop!_OS"),
                             ("arch", r"Arch|Manjaro|EndeavourOS"), ("fedora", r"Fedora|Red Hat"),
                             ("suse", r"SUSE")):
            if re.search(pattern, ua or "", re.I):
                distro = key
                break
    shown = []
    yours = ""
    if platform in LABEL:
        fn = dict((k, f) for k, _, f in PLATFORMS)[platform]
        if platform == "linux":
            fn = lambda h, d=distro: steps_linux(h, d)  # noqa: E731
        extra = ""
        if firefox:
            extra = f"<h2>…and in Firefox</h2>{steps_firefox(host)}"
            shown.append("firefox")
        yours = (f'<div class="yours"><div class="tag" style="margin-top:12px">Looks like your device</div>'
                 f"<h2>{LABEL[platform]}</h2>{fn(host)}{extra}</div>")
        shown.append(platform)
    others = "".join(f"<details><summary>{label}</summary>{fn(host)}</details>"
                     for key, label, fn in PLATFORMS if key not in shown)
    return PAGE.format(name=html.escape(NAME), fingerprints=fingerprints, yours=yours,
                       others=others, https=html.escape(https_url)).encode()


# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "humint-http"

    def log_message(self, fmt, *args):      # journald has enough noise
        pass

    def _host(self):
        host = (self.headers.get("Host") or "").split(":")[0] or "humint.local"
        return host if all(c.isalnum() or c in ".-" for c in host) else "humint.local"

    def _https(self, path="/"):
        port = "" if HTTPS_PORT == "443" else f":{HTTPS_PORT}"
        return f"https://{self._host()}{port}{path}"

    def _send(self, code, body, ctype, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/ca.crt", "/humint-ca.crt", "/ca.cer"):
            ca = load_ca()
            if not ca:
                return self._send(503, b"The certificate is not ready yet. Unlock the console first.",
                                  "text/plain; charset=utf-8")
            pem, der, _, _ = ca
            if path == "/ca.cer":
                return self._send(200, der, "application/pkix-cert",
                                  {"Content-Disposition": f'attachment; filename="{FILE}.cer"'})
            return self._send(200, pem, "application/x-x509-ca-cert",
                              {"Content-Disposition": f'attachment; filename="{FILE}.crt"'})
        if path in ("/trust", "/trust/"):
            body = render(self._host(), self.headers.get("User-Agent", ""), self._https())
            return self._send(200, body, "text/html; charset=utf-8")
        # 308 keeps the method, so a phone that still posts to http:// lands
        # on https:// with its report intact (once it trusts the CA).
        self.send_response(308)
        self.send_header("Location", self._https(self.path))
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_HEAD = do_GET

    def do_POST(self):
        self.send_response(308)
        self.send_header("Location", self._https(self.path))
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_PUT = do_PATCH = do_DELETE = do_POST


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
