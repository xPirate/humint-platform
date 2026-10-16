#!/usr/bin/env python3
"""Port 80 when the console is on HTTPS: hand out the CA certificate, and send
everything else to https://.

The trust page and the certificate are served over plain HTTP on purpose —
it is how a phone gets the certificate it needs before HTTPS can work for it.
That is only as safe as the network it is fetched over (the field Wi-Fi, with
its passphrase), so the page shows the fingerprint to compare against the box's
own screen or `humint-ctl tls`.

Standard library only; runs as humintd with CAP_NET_BIND_SERVICE.
"""
import html
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CA = "/var/lib/humint/ca.crt"
FP = "/var/lib/humint/ca.fingerprint"
PORT = int(os.environ.get("HTTP_PORT", "80"))
HTTPS_PORT = os.environ.get("HTTPS_PORT", "443")
NAME = os.environ.get("INSTANCE_NAME", "HUMINT field server")

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Trust this console</title>
<style>
 body{{font:16px/1.5 system-ui,sans-serif;margin:0;padding:24px 16px;background:#0f1411;color:#dfe8e2}}
 main{{max-width:620px;margin:auto}} h1{{font-size:22px;margin:0 0 4px}}
 a.btn{{display:inline-block;background:#2f9e5f;color:#fff;padding:12px 18px;border-radius:8px;text-decoration:none;font-weight:600;margin:12px 0}}
 code{{font:13px ui-monospace,monospace;word-break:break-all;background:#1b231e;padding:8px;display:block;border-radius:6px}}
 h2{{font-size:16px;margin:22px 0 4px}} li{{margin:4px 0}} .muted{{color:#93a69a}}
</style></head><body><main>
<h1>Trust {name}</h1>
<p class="muted">Do this once per phone or laptop. After it, the console opens over HTTPS with no warnings.</p>
<a class="btn" href="/ca.crt">Download the certificate</a>
<p>Check that this fingerprint matches the one on the box's screen (or <code style="display:inline;padding:2px 4px">humint-ctl tls</code>):</p>
<code>{fp}</code>
<p class="muted">This certificate can only vouch for this kind of local console — <em>.local</em> names and private addresses. It cannot be used to impersonate any public website.</p>
<h2>Android</h2><ol><li>Download it above.</li><li>Settings → Security → Encryption &amp; credentials → Install a certificate → <b>CA certificate</b> → choose the file.</li></ol>
<h2>iPhone / iPad</h2><ol><li>Download it above in Safari and allow the profile.</li><li>Settings → General → VPN &amp; Device Management → install the profile.</li><li>Settings → General → About → Certificate Trust Settings → turn on full trust for it.</li></ol>
<h2>Windows</h2><ol><li>Open the file → Install Certificate → Current User → <b>Trusted Root Certification Authorities</b>.</li></ol>
<h2>macOS</h2><ol><li>Open the file (Keychain Access) → double-click it → Trust → <b>Always Trust</b>.</li></ol>
<p><a href="{https}" style="color:#7fd6a2">Continue to the console →</a></p>
</main></body></html>"""


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

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/ca.crt", "/humint-ca.crt"):
            try:
                body = open(CA, "rb").read()
            except OSError:
                return self._text(503, "The certificate is not ready yet. Unlock the console first.")
            self.send_response(200)
            self.send_header("Content-Type", "application/x-x509-ca-cert")
            self.send_header("Content-Disposition", 'attachment; filename="humint-console-ca.crt"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path in ("/trust", "/trust/"):
            try:
                fp = open(FP).read().strip()
            except OSError:
                fp = "(not ready yet)"
            body = PAGE.format(name=html.escape(NAME), fp=html.escape(fp),
                               https=html.escape(self._https())).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
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

    def _text(self, code, msg):
        body = msg.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
