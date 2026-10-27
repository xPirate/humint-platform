import QtQuick
import QtQuick.Shapes
import "lib/geo.js" as Geo

// A tile map: drag to move, wheel / pinch / buttons to zoom. Tiles come from
// tileSource(z, x, y) (a URL — image://api/... for the console's offline
// packs). Overlays are given in lat/lng: markers, zones (rings, circles) and
// routes (lines). Everything is drawn here; no map plugin, no network of its
// own.
Item {
    id: map
    clip: true
    property real centerLat: 20
    property real centerLng: 0
    property int zoom: 3
    property int minZoom: 1
    property int maxZoom: 18
    property var tileSource: function(z, x, y) { return "" }
    property var markers: []        // [{id, lat, lng, color, label}]
    property var zones: []          // [{id, ring:[[lat,lng]...] | center:[lat,lng], radius_m, color, dim}]
    property var routes: []         // [{id, lines:[[[lat,lng]...]...], color}]
    property var selectedId: null
    signal markerClicked(var marker)
    signal zoneClicked(var zone)
    signal routeClicked(var route)
    signal tapped(real lat, real lng)
    // Off while something is being drawn: every tap is then a point.
    property bool picking: true

    // What is under a tap: a route (within a finger's width of its line),
    // else a zone (inside its shape), else nothing.
    function routeAt(px, py) {
        var tol = 12 * Theme.s
        for (var i = routes.length - 1; i >= 0; i--) {
            var lines = routes[i].lines || []
            for (var l = 0; l < lines.length; l++) {
                for (var k = 1; k < lines[l].length; k++) {
                    var a = toView(lines[l][k - 1][0], lines[l][k - 1][1]), b = toView(lines[l][k][0], lines[l][k][1])
                    var vx = b.x - a.x, vy = b.y - a.y, len2 = vx * vx + vy * vy
                    var t = len2 ? Math.max(0, Math.min(1, ((px - a.x) * vx + (py - a.y) * vy) / len2)) : 0
                    if (Math.hypot(px - (a.x + t * vx), py - (a.y + t * vy)) <= tol) return routes[i]
                }
            }
        }
        return null
    }
    function zoneAt(px, py) {
        for (var i = zones.length - 1; i >= 0; i--) {
            var z = zones[i]
            if (z.center) {
                var c = toView(z.center[0], z.center[1])
                var r = z.radius_m / (156543.03392 * Math.cos(z.center[0] * Math.PI / 180) / Math.pow(2, zoom))
                if (Math.hypot(px - c.x, py - c.y) <= r) return z
            } else if (z.ring && z.ring.length >= 3) {
                var inside = false, pts = z.ring.map(function(p) { return toView(p[0], p[1]) })
                for (var j = 0, k = pts.length - 1; j < pts.length; k = j++) {
                    if ((pts[j].y > py) !== (pts[k].y > py) &&
                        px < (pts[k].x - pts[j].x) * (py - pts[j].y) / (pts[k].y - pts[j].y) + pts[j].x) inside = !inside
                }
                if (inside) return z
            }
        }
        return null
    }

    // The centre in world pixels at the current zoom.
    readonly property real cx: Geo.lngToX(centerLng, zoom)
    readonly property real cy: Geo.latToY(centerLat, zoom)
    function toView(lat, lng) {
        return Qt.point(Geo.lngToX(lng, zoom) - cx + width / 2, Geo.latToY(lat, zoom) - cy + height / 2)
    }
    function toLatLng(px, py) {
        return { lat: Geo.yToLat(cy + py - height / 2, zoom), lng: Geo.xToLng(cx + px - width / 2, zoom) }
    }
    function setZoom(z, px, py) {
        z = Math.max(minZoom, Math.min(maxZoom, z))
        if (z === zoom) return
        // Keep the point under the finger where it is.
        px = px === undefined ? width / 2 : px; py = py === undefined ? height / 2 : py
        var at = toLatLng(px, py)
        var nx = Geo.lngToX(at.lng, z) - (px - width / 2)
        var ny = Geo.latToY(at.lat, z) - (py - height / 2)
        zoom = z
        centerLng = Geo.xToLng(nx, z); centerLat = Geo.yToLat(ny, z)
    }
    function centerOn(lat, lng, z) { if (z !== undefined) zoom = Math.max(minZoom, Math.min(maxZoom, z)); centerLat = lat; centerLng = lng }
    function fit(minLat, minLng, maxLat, maxLng) {
        zoom = Math.min(maxZoom, Geo.fitZoom(minLat, minLng, maxLat, maxLng, width, height, maxZoom))
        centerLat = (minLat + maxLat) / 2; centerLng = (minLng + maxLng) / 2
    }

    Rectangle { anchors.fill: parent; color: Theme.light ? "#dfe5e0" : "#0b120e" }

    // ---- tiles ------------------------------------------------------------------
    readonly property var tiles: {
        var n = Math.pow(2, zoom), out = []
        var x0 = Math.floor((cx - width / 2) / Geo.TILE), x1 = Math.floor((cx + width / 2) / Geo.TILE)
        var y0 = Math.max(0, Math.floor((cy - height / 2) / Geo.TILE)), y1 = Math.min(n - 1, Math.floor((cy + height / 2) / Geo.TILE))
        for (var ty = y0; ty <= y1; ty++)
            for (var tx = x0; tx <= x1; tx++)
                out.push({ z: zoom, x: ((tx % n) + n) % n, y: ty, px: tx * Geo.TILE - cx + width / 2, py: ty * Geo.TILE - cy + height / 2 })
        return out
    }
    Repeater {
        model: map.tiles
        Image {
            x: modelData.px; y: modelData.py
            width: Geo.TILE; height: Geo.TILE
            asynchronous: true
            cache: true
            smooth: false
            source: map.tileSource(modelData.z, modelData.x, modelData.y)
        }
    }

    // ---- zones and routes ------------------------------------------------------------
    Repeater {
        model: map.zones
        Shape {
            id: zs
            anchors.fill: parent
            opacity: modelData.dim ? 0.45 : 1
            readonly property var pts: (modelData.ring || []).map(function(p) { return map.toView(p[0], p[1]) })
            readonly property point c: modelData.center ? map.toView(modelData.center[0], modelData.center[1]) : Qt.point(0, 0)
            readonly property real r: modelData.center ? modelData.radius_m / (156543.03392 * Math.cos(modelData.center[0] * Math.PI / 180) / Math.pow(2, map.zoom)) : 0
            ShapePath {
                strokeColor: modelData.color; strokeWidth: 2 * Theme.s
                fillColor: Qt.rgba(Qt.color(modelData.color).r, Qt.color(modelData.color).g, Qt.color(modelData.color).b, 0.18)
                // A circle zone has no ring: one point draws nothing (an empty path warns).
                PathPolyline { path: zs.pts.length ? zs.pts : [Qt.point(-1, -1)] }
            }
            ShapePath {
                strokeColor: modelData.center ? modelData.color : "transparent"; strokeWidth: 2 * Theme.s
                fillColor: modelData.center ? Qt.rgba(Qt.color(modelData.color).r, Qt.color(modelData.color).g, Qt.color(modelData.color).b, 0.18) : "transparent"
                PathAngleArc { centerX: zs.c.x; centerY: zs.c.y; radiusX: zs.r; radiusY: zs.r
                               startAngle: 0; sweepAngle: 360 }
            }
        }
    }
    Repeater {
        model: map.routes
        Shape {
            anchors.fill: parent
            ShapePath {
                strokeColor: modelData.color; strokeWidth: 3.5 * Theme.s; fillColor: "transparent"
                capStyle: ShapePath.RoundCap; joinStyle: ShapePath.RoundJoin
                PathMultiline { paths: modelData.lines.map(function(line) { return line.map(function(p) { return map.toView(p[0], p[1]) }) }) }
            }
        }
    }

    // ---- moving and zooming ----------------------------------------------------------------
    property point dragStart
    property real startLat
    property real startLng
    DragHandler {
        id: drag
        target: null
        onActiveChanged: if (active) { map.startLat = map.centerLat; map.startLng = map.centerLng }
        onTranslationChanged: {
            var x = Geo.lngToX(map.startLng, map.zoom) - translation.x
            var y = Geo.latToY(map.startLat, map.zoom) - translation.y
            map.centerLng = Geo.xToLng(x, map.zoom)
            map.centerLat = Math.max(-85, Math.min(85, Geo.yToLat(y, map.zoom)))
        }
    }
    WheelHandler {
        onWheel: function(ev) { map.setZoom(map.zoom + (ev.angleDelta.y > 0 ? 1 : -1), ev.x, ev.y) }
    }
    PinchHandler {
        target: null
        property int startZoom
        onActiveChanged: if (active) startZoom = map.zoom
        onActiveScaleChanged: map.setZoom(startZoom + Math.round(Math.log(activeScale) / Math.LN2), centroid.position.x, centroid.position.y)
    }
    TapHandler {
        onTapped: function(ev) {
            var x = ev.position.x, y = ev.position.y
            if (map.picking) {
                var r = map.routeAt(x, y)
                if (r) { map.routeClicked(r); return }
                var z = map.zoneAt(x, y)
                if (z) { map.zoneClicked(z); return }
            }
            var ll = map.toLatLng(x, y); map.tapped(ll.lat, ll.lng)
        }
    }

    // ---- markers ---------------------------------------------------------------------------
    Repeater {
        model: map.markers
        Item {
            readonly property point p: map.toView(modelData.lat, modelData.lng)
            x: p.x; y: p.y
            visible: p.x > -40 && p.y > -40 && p.x < map.width + 40 && p.y < map.height + 40
            z: map.selectedId === modelData.id ? 2 : 1
            Rectangle {
                width: (map.selectedId === modelData.id ? 22 : 16) * Theme.s; height: width; radius: width / 2
                x: -width / 2; y: -height / 2
                color: modelData.color || Theme.accent
                border.color: Theme.light ? "#ffffff" : "#000000"; border.width: 2 * Theme.s
                TapHandler { enabled: map.picking; onTapped: map.markerClicked(modelData) }
            }
            Txt {
                visible: map.zoom >= 12 || map.selectedId === modelData.id
                x: 12 * Theme.s; y: -height / 2
                text: modelData.label || ""
                font.pixelSize: Theme.fsSmall
                style: Text.Outline; styleColor: Theme.bg
                wrapMode: Text.NoWrap
            }
        }
    }

    // ---- zoom buttons and scale ------------------------------------------------------------------
    Column {
        anchors.right: parent.right; anchors.top: parent.top; anchors.margins: Theme.gap
        spacing: 6 * Theme.s
        Btn { compact: true; text: "+"; minWidth: 44 * Theme.s; onClicked: map.setZoom(map.zoom + 1) }
        Btn { compact: true; text: "−"; minWidth: 44 * Theme.s; onClicked: map.setZoom(map.zoom - 1) }
    }
    Rectangle {
        anchors.left: parent.left; anchors.bottom: parent.bottom; anchors.margins: Theme.gap
        color: Qt.rgba(0, 0, 0, 0.55); radius: Theme.radius
        width: coord.implicitWidth + 16 * Theme.s; height: coord.implicitHeight + 8 * Theme.s
        Txt { id: coord; anchors.centerIn: parent; font.family: "IBM Plex Mono"; font.pixelSize: Theme.fsSmall; color: "#e6efe9"
              text: map.centerLat.toFixed(5) + ", " + map.centerLng.toFixed(5) + "  ·  " + Geo.maidenhead(map.centerLat, map.centerLng)
                    + "  ·  z" + map.zoom }
    }
}
