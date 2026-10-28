"""Online map tiles on the screen: fetched with a User-Agent naming the app
(tile servers' usage policies refuse Qt's bare "Mozilla/5.0"), and cached."""
import http.server
import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import ROOT, check, finish  # noqa: E402

sys.path.insert(0, os.path.join(ROOT, "native"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["HUMINT_TILE_CACHE"] = tempfile.mkdtemp()

seen = []


class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        seen.append((self.path, self.headers.get("User-Agent")))
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Cache-Control", "max-age=86400")
        self.send_header("Content-Length", str(len(PNG)))
        self.end_headers()
        self.wfile.write(PNG)

    def log_message(self, *a):
        pass


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
url = f"http://127.0.0.1:{srv.server_port}/1/0/0.png"

from PySide6.QtCore import QCoreApplication, QUrl  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlComponent, QQmlEngine  # noqa: E402

from humint_ui.tiles import WebTiles  # noqa: E402

app = QGuiApplication(sys.argv)
from PySide6.QtCore import QBuffer, QByteArray, QIODevice  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
_img = QImage(256, 256, QImage.Format_RGB32)
_img.fill(0x335533)
_ba = QByteArray()
_buf = QBuffer(_ba)
_buf.open(QIODevice.WriteOnly)
_img.save(_buf, "PNG")
PNG = bytes(_ba.data())
app.setApplicationName("HUMINT")
engine = QQmlEngine()
engine.addImageProvider("tile", WebTiles())


keep = []


def load_image():
    c = QQmlComponent(engine)
    keep.append(c)
    c.setData(f'import QtQuick\nImage {{ cache: false; source: "image://tile/" + encodeURIComponent("{url}"); property int st: status }}'.encode(), QUrl())
    img = c.create()
    keep.append(img)
    from PySide6.QtQml import QQmlEngine as _E
    _E.setObjectOwnership(img, _E.ObjectOwnership.CppOwnership)
    end = time.time() + 10
    while img.property("st") not in (1, 3) and time.time() < end:   # Ready / Error
        QCoreApplication.processEvents()
        time.sleep(0.02)
    return img


img = load_image()
check(img.property("st") == 1, "the tile loads")
check(seen and seen[0][1].startswith("HUMINT-field-server-map/"),
      f"with a User-Agent naming the app, not Qt's bare default ({seen[:1]})")
n = len(seen)
img2 = load_image()
check(img2.property("st") == 1 and len(seen) == n, "a tile seen before comes from the disk cache")
# Offline now: the cached copy still shows.
srv.shutdown()
srv.server_close()
url = url  # same tile
img3 = load_image()
check(img3.property("st") == 1, "with the tile server gone, a cached tile still shows")
finish()
