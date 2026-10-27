"""Drawing on the native app's map: zones by their corners, as a box and as a
circle; a route point by point (with undo); then changing a zone's ground
with a reason, and redrawing a route. Taps reach the map as they would from
a finger (the map's own tapped signal); what they hit is tested too."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import PASSWORD, ROOT, Console, check, finish, ok  # noqa: E402

sys.path.insert(0, os.path.join(ROOT, "native", "tools"))
from shoot import FakeMachine  # noqa: E402
from appdriver import AppDriver  # noqa: E402
from PySide6.QtCore import Q_ARG, Q_RETURN_ARG, QMetaObject  # noqa: E402

SHOTS = os.environ.get("SHOTS")


def shot(d, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        d.shot(os.path.join(SHOTS, name + ".png"))


c = Console("native_mapdraw").start()
api = c.register_admin("ana")
m = FakeMachine()
m.unlock()
m.start(console_url=c.url)
d = AppDriver(m.sock, console_url=c.url)
d.login("ana", PASSWORD)
d.tap("Map")


def themap():
    return next(i for i in d.items() if i.metaObject().indexOfSignal("zoneClicked(QVariant)") >= 0 and d.visible(i))


d.until(lambda: themap() is not None, what="the map")
mp = themap()
mp.setProperty("centerLat", 51.5); mp.setProperty("centerLng", -0.1); mp.setProperty("zoom", 14)
d.pump(0.3)


def tap(lat, lng):
    QMetaObject.invokeMethod(mp, "tapped", Q_ARG(float, lat), Q_ARG(float, lng))
    d.pump(0.15)


def var(x):
    return x.toVariant() if hasattr(x, "toVariant") else x


# ---- a zone, corner by corner ----------------------------------------------------------------
d.tap("Zone: shape")
d.until(lambda: d.has_text("Tap each corner of the zone, then Finish."), what="draw bar")
tap(51.500, -0.100); tap(51.502, -0.100)
d.tap("Finish")
check(d.has_text("A zone needs at least three corners"), "two corners are not yet a zone")
tap(51.502, -0.097)
check(d.has_text("3 points"), "each tap is a corner")
shot(d, "98-map-drawing")
d.tap("Finish")
d.until(lambda: d.has_text("New zone"), what="zone form")
d.type_into("e.g. Riverside protest", "Bridge cordon")
d.choose("Ground", "Non-permissive")
d.type_into("e.g. Riverside protest, 17 Sep", "Bridge protest")
d.tap("Create zone")
d.until(lambda: c.sql("SELECT count(*) FROM map_zones")[0][0] == 1, what="zone saved")
row = c.sql("SELECT z.environment, z.shape, e.name FROM map_zones z LEFT JOIN entities e ON e.id = z.event_id")[0]
check(row == ("Non-permissive", "polygon", "Bridge protest"), f"the zone is saved, with a new Event tied to it ({row})")

# ---- a box and a circle: two taps each ---------------------------------------------------------
d.tap("Zone: box")
tap(51.505, -0.110); tap(51.507, -0.105)
d.until(lambda: d.has_text("New zone"), what="box form")
d.type_into("e.g. Riverside protest", "Depot yard")
d.tap("Create zone")
d.until(lambda: c.sql("SELECT count(*) FROM map_zones")[0][0] == 2, what="box saved")
d.tap("Zone: circle")
tap(51.495, -0.090); tap(51.495, -0.0886)           # ~100 m east
d.until(lambda: d.has_text("New zone"), what="circle form")
d.type_into("e.g. Riverside protest", "Checkpoint radius")
d.tap("Create zone")
d.until(lambda: c.sql("SELECT count(*) FROM map_zones")[0][0] == 3, what="circle saved")
shapes = dict(c.sql("SELECT shape, round(radius_m) FROM map_zones"))
check(set(shapes) == {"polygon", "rectangle", "circle"} and 90 <= (shapes["circle"] or 0) <= 110,
      f"two taps make a box, or a circle from its centre and edge ({shapes})")

# ---- a route, with an undo ------------------------------------------------------------------------
d.tap("Route")
tap(51.490, -0.120); tap(51.491, -0.118); tap(51.600, 0.500)      # the last one a slip
d.tap("Undo point")
tap(51.492, -0.115)
check(d.has_text("3 points"), "Undo takes back the last point")
d.tap("Finish")
d.until(lambda: d.has_text("New route"), what="route form")
d.type_into("e.g. Safe route to the north gate", "Back way to the depot")
d.choose("Travelled by", "On foot")
d.tap("Create route")
d.until(lambda: c.sql("SELECT count(*) FROM entities WHERE entity_type = 'route'")[0][0] == 1, what="route saved")
route_id = c.sql("SELECT id FROM entities WHERE entity_type = 'route'")[0][0]
rt = ok(api.get(c.url + f"/api/routes/{route_id}"))
check(rt["point_count"] == 3 and 300 < rt["length_m"] < 600 and rt["travel_mode"] == "On foot",
      f"the route is saved with its points and length ({rt['point_count']}, {rt['length_m']:.0f} m)")

# ---- what a tap hits ------------------------------------------------------------------------------------
d.until(lambda: len(var(mp.property("zones"))) == 3 and len(var(mp.property("routes"))) == 1, what="layers loaded")
pt = mp.toView if False else None
inside = QMetaObject.invokeMethod(mp, "toView", Q_RETURN_ARG("QVariant"), Q_ARG("QVariant", 51.5012), Q_ARG("QVariant", -0.0995))
hit = QMetaObject.invokeMethod(mp, "zoneAt", Q_RETURN_ARG("QVariant"), Q_ARG("QVariant", inside.x()), Q_ARG("QVariant", inside.y()))
hit = var(hit)
check(hit and hit["data"]["name"] == "Bridge cordon", "a tap inside a zone finds it")
on = QMetaObject.invokeMethod(mp, "toView", Q_RETURN_ARG("QVariant"), Q_ARG("QVariant", 51.4905), Q_ARG("QVariant", -0.119))
rh = var(QMetaObject.invokeMethod(mp, "routeAt", Q_RETURN_ARG("QVariant"), Q_ARG("QVariant", on.x()), Q_ARG("QVariant", on.y())))
check(rh and rh["data"]["name"] == "Back way to the depot", "a tap on a route's line finds it")

# ---- change a zone's ground, with why --------------------------------------------------------------------
QMetaObject.invokeMethod(mp, "zoneClicked", Q_ARG("QVariant", hit))
d.until(lambda: d.button("Edit") is not None and d.has_text("Bridge cordon"), what="zone card")
d.tap("Edit")
d.until(lambda: d.has_text("Edit zone"), what="edit form")
d.choose("Ground", "Denied")
d.type_into("e.g. police line moved onto the bridge", "Police closed the bridge")
d.tap("Save")
d.until(lambda: c.sql("SELECT environment FROM map_zones WHERE shape = 'polygon'") == [("Denied",)], what="zone updated")
note = c.sql("SELECT note FROM map_zone_changes ORDER BY id DESC LIMIT 1")
check(note == [("Police closed the bridge",)], f"the change is kept with its reason ({note})")

# ---- redraw the route ----------------------------------------------------------------------------------------
d.until(lambda: len(var(mp.property("routes"))) == 1, what="routes again")
QMetaObject.invokeMethod(mp, "routeClicked", Q_ARG("QVariant", var(mp.property("routes"))[0]))
d.until(lambda: d.button("Redraw") is not None, what="route card")
d.tap("Redraw")
d.until(lambda: d.has_text("Redraw the route:"), what="redraw bar")
tap(51.490, -0.120); tap(51.4905, -0.119); tap(51.491, -0.118); tap(51.492, -0.115)
d.tap("Finish")
d.until(lambda: ok(api.get(c.url + f"/api/routes/{route_id}"))["point_count"] == 4, what="redrawn")
check(True, "Redraw replaces the route's line")
d.tap("Zone: shape")
d.tap("Cancel")
check(not d.has_text("Tap each corner"), "Cancel leaves drawing")
finish()
