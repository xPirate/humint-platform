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
            anchors.fill: parent
            opacity: modelData.dim ? 0.45 : 1
            readonly property var pts: (modelData.ring || []).map(function(p) { return map.toView(p[0], p[1]) })
            readonly property point c: modelData.center ? map.toView(modelData.center[0], modelData.center[1]) : Qt.point(0, 0)
            readonly property real r: modelData.center ? modelData.radius_m / (156543.03392 * Math.cos(modelData.center[0] * Math.PI / 180) / Math.pow(2, map.zoom)) : 0
            ShapePath {
                strokeColor: modelData.color; strokeWidth: 2 * Theme.s
                fillColor: Qt.rgba(Qt.color(modelData.color).r, Qt.color(modelData.color).g, Qt.color(modelData.color).b, 0.18)
                PathPolyline { path: parent.parent.pts }
            }
            ShapePath {
                strokeColor: modelData.center ? modelData.color : "transparent"; strokeWidth: 2 * Theme.s
                fillColor: modelData.center ? Qt.rgba(Qt.color(modelData.color).r, Qt.color(modelData.color).g, Qt.color(modelData.color).b, 0.18) : "transparent"
                PathAngleArc { centerX: parent.parent.c.x; centerY: parent.parent.c.y; radiusX: parent.parent.r; radiusY: parent.parent.r
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
        onTapped: function(ev) { var ll = map.toLatLng(ev.position.x, ev.position.y); map.tapped(ll.lat, ll.lng) }
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
                TapHandler { onTapped: map.markerClicked(modelData) }
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
