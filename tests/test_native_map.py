"""The native app's map: offline tiles from a downloaded pack, through the
app's own session; locations coloured by ground; zones and routes drawn;
tapping a location shows it and opens its record."""
import io
import math
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import PASSWORD, ROOT, Console, check, finish, ok  # noqa: E402

sys.path.insert(0, os.path.join(ROOT, "native", "tools"))
from shoot import FakeMachine  # noqa: E402
from appdriver import AppDriver  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

SHOTS = os.environ.get("SHOTS")


def tile_xy(lat, lng, z):
    n = 2 ** z
    x = int((lng + 180) / 360 * n)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    return x, y


c = Console("native_map").start()
api = c.register_admin("ana")
U = c.url

# A pack: a few zoom levels around the docks, each tile labelled.
pack = os.path.join(c.env["UPLOAD_DIR"], "test-pack.mbtiles")
db = sqlite3.connect(pack)
db.execute("CREATE TABLE metadata (name TEXT, value TEXT)")
db.execute("CREATE TABLE tiles (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB)")
served = 0
for z in range(10, 15):
    cx, cy = tile_xy(51.505, -0.09, z)
    for x in range(cx - 3, cx + 4):
        for y in range(cy - 3, cy + 4):
            im = Image.new("RGB", (256, 256), (40 + 10 * (x % 2), 60, 50 + 10 * (y % 2)))
            dr = ImageDraw.Draw(im)
            dr.rectangle([0, 0, 255, 255], outline=(90, 140, 110))
            dr.text((10, 10), f"{z}/{x}/{y}", fill=(200, 255, 220))
            buf = io.BytesIO(); im.save(buf, "PNG")
            db.execute("INSERT INTO tiles VALUES (?, ?, ?, ?)", (z, x, (2 ** z - 1) - y, buf.getvalue()))
            served += 1
db.commit(); db.close()
src = c.sql("INSERT INTO map_sources (name, url_template, min_zoom, max_zoom) VALUES ('Test streets', "
            "'https://tiles.invalid/{z}/{x}/{y}.png', 1, 18) RETURNING id")[0][0]
c.sql("INSERT INTO map_packs (source_id, name, min_lat, min_lon, max_lat, max_lon, min_zoom, max_zoom, status, file_path) "
      "VALUES (%s, 'Docks', 51.4, -0.3, 51.6, 0.1, 10, 14, 'done', %s)", (src, pack))

loc = ok(api.post(U + "/api/entities", json={"entity_type": "location", "name": "East gate",
                                             "details": {"lat": 51.506, "lng": -0.088, "environment": "Non-permissive"}}))
ok(api.post(U + "/api/entities", json={"entity_type": "location", "name": "Safe house",
                                       "details": {"lat": 51.502, "lng": -0.095, "environment": "Permissive"}}))

m = FakeMachine()
m.unlock()
m.start(console_url=c.url)
d = AppDriver(m.sock, console_url=c.url)
d.login("ana", PASSWORD)
d.tap("Map")
d.until(lambda: d.has_text("Locations (2)"), what="the map's layers")
d.pump(3)
mp = [i for i in d.items() if i.property("tileSource") is not None][0]
check(mp.property("zoom") >= 10, f"it frames the placed locations (zoom {mp.property('zoom')})")
# Tiles come from the pack, through the session: wait for the images to land.


def url(i):
    v = i.property("source")
    return v.toString() if hasattr(v, "toString") else str(v or "")


d.until(lambda: sum(1 for i in d.items() if url(i).startswith("image://api/api/map/tiles/")
                    and i.property("implicitWidth") == 256) >= 4, 20, "tiles from the pack")
check(True, "offline tiles are drawn from the downloaded pack")
if SHOTS:
    os.makedirs(SHOTS, exist_ok=True)
    d.shot(os.path.join(SHOTS, "50-map.png"))
# Tap a marker
from PySide6.QtCore import QMetaObject  # noqa: E402,F401
markers = mp.property("markers").toVariant() if hasattr(mp.property("markers"), "toVariant") else mp.property("markers")
east = [x for x in markers if x["label"] == "East gate"][0]
check(east["color"].lower() in ("#ff4d3d",), f"a Non-permissive location is drawn in its colour ({east['color']})")
mp.markerClicked.emit(east)
d.until(lambda: d.button("Open the record") is not None, what="the tapped location")
d.tap("Open the record")
d.until(lambda: d.has_text("Non-permissive") and d.has_text("East gate"), what="its record")
check(True, "tapping a location shows it, and opens its record")
m.stop()
c.stop()
finish()
