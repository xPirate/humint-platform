import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Humint
import ".."
import "../lib/fmt.js" as Fmt

// The map: every placed Location (coloured by how workable the ground is),
// zones and routes, over the basemap — the offline packs downloaded to this
// machine, or the source's own tile server when there is internet.
Rectangle {
    id: page
    color: Theme.bg
    property var sources: []
    property var source: null
    property bool offline: true
    property var locations: []
    property var zoneItems: []
    property var routeItems: []
    property bool showLocations: true
    property bool showZones: true
    property bool showRoutes: true
    property var selected: null        // {kind, data}
    // Drawing: {kind: "polygon" | "box" | "circle" | "route", points: [[lat, lng]], redraw: routeId?}
    property var draw: null
    readonly property var drawHints: ({
        polygon: "Tap each corner of the zone, then Finish.",
        box: "Tap two opposite corners.",
        circle: "Tap the centre, then a point on the edge.",
        route: "Tap along the way, in order, then Finish."
    })

    function metres(a, b) {
        var R = 6371008.8, rad = Math.PI / 180
        var dLat = (b[0] - a[0]) * rad, dLng = (b[1] - a[1]) * rad
        var h = Math.sin(dLat / 2) * Math.sin(dLat / 2) + Math.cos(a[0] * rad) * Math.cos(b[0] * rad) * Math.sin(dLng / 2) * Math.sin(dLng / 2)
        return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)))
    }
    function lengthText(m) { return m < 1000 ? Math.round(m) + " m" : (m / 1000).toFixed(m < 10000 ? 2 : 1) + " km" }
    function drawLength() {
        var pts = page.draw ? page.draw.points : [], m = 0
        for (var i = 1; i < pts.length; i++) m += metres(pts[i - 1], pts[i])
        return m
    }
    function startDraw(kind, redraw) {
        page.selected = null
        page.draw = { kind: kind, points: [], redraw: redraw || null }
    }
    function addPoint(lat, lng) {
        var d = page.draw
        var pts = d.points.concat([[lat, lng]])
        page.draw = { kind: d.kind, points: pts, redraw: d.redraw }
        if ((d.kind === "box" || d.kind === "circle") && pts.length === 2) finishDraw()
    }
    function undoPoint() {
        var d = page.draw
        if (d && d.points.length) page.draw = { kind: d.kind, points: d.points.slice(0, -1), redraw: d.redraw }
    }
    function finishDraw() {
        var d = page.draw
        if (!d) return
        var p = d.points
        if (d.kind === "polygon" && p.length < 3) { ui.toast("A zone needs at least three corners", true); return }
        if (d.kind === "route" && p.length < 2) { ui.toast("A route needs at least two points", true); return }
        page.draw = null
        if (d.kind === "route") {
            if (d.redraw) {
                Net.put("/api/routes/" + encodeURIComponent(d.redraw) + "/geometry", { points: p }).then(function() {
                    ui.toast("Route redrawn"); page.load()
                }).catch(function(e) { ui.toast(e.message, true) })
            } else routeForm.open(p)
            return
        }
        var geometry
        if (d.kind === "polygon") geometry = { shape: "polygon", points: p }
        else if (d.kind === "box") {
            var s = Math.min(p[0][0], p[1][0]), n = Math.max(p[0][0], p[1][0])
            var w = Math.min(p[0][1], p[1][1]), e = Math.max(p[0][1], p[1][1])
            if (n - s < 1e-6 || e - w < 1e-6) { ui.toast("Tap two corners apart from each other", true); return }
            geometry = { shape: "rectangle", points: [[s, w], [s, e], [n, e], [n, w]] }
        } else {
            var r = metres(p[0], p[1])
            if (r < 1) { ui.toast("Tap a point on the edge, away from the centre", true); return }
            geometry = { shape: "circle", lat: p[0][0], lon: p[0][1], radius_m: r }
        }
        zoneForm.open(null, geometry)
    }
    // What is being drawn, for the map to show.
    readonly property var drawZone: {
        var d = page.draw
        if (!d || !d.points.length) return null
        if (d.kind === "polygon" && d.points.length >= 3) return { id: "draw", ring: d.points, color: Theme.accent }
        return null
    }
    readonly property var drawRoute: {
        var d = page.draw
        if (!d || d.points.length < 2 || !(d.kind === "route" || (d.kind === "polygon" && d.points.length < 3))) return null
        return { id: "draw", lines: [d.points], color: Theme.accent }
    }
    function isoFrom(text) {
        var t = (text || "").trim()
        if (!t) return null
        var d = new Date(t.replace(" ", "T"))
        return isNaN(d.getTime()) ? null : d.toISOString()
    }
    function localText(iso) {
        if (!iso) return ""
        var d = new Date(iso)
        function pad(n) { return (n < 10 ? "0" : "") + n }
        return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) + " " + pad(d.getHours()) + ":" + pad(d.getMinutes())
    }

    function envColor(env) {
        var light = Theme.light
        return ({ "Permissive": light ? "#0f7a35" : "#2ee66b", "Semi-permissive": light ? "#9a6b00" : "#ffd21e",
                  "Non-permissive": light ? "#c62410" : "#ff4d3d", "Denied": light ? "#7d0a15" : "#c1121f",
                  "Unknown": light ? "#5b6672" : "#8b98a5" })[env] || (light ? "#5b6672" : "#8b98a5")
    }
    readonly property color routeColor: Theme.light ? "#1d4ed8" : "#4f8dff"

    function load() {
        Net.get("/api/map/sources").then(function(r) {
            page.sources = r.items || []
            // A source with downloaded areas first: on a field server the
            // internet is the exception, not the rule.
            if (!page.source && page.sources.length)
                page.pickSource(page.sources.slice().sort(function(a, b) { return (b.pack_count || 0) - (a.pack_count || 0) })[0])
        }).catch(function() {})
        Net.get("/api/map/locations").then(function(r) {
            page.locations = (r.items || []).filter(function(l) { return l.lat !== null && l.lng !== null })
            if (!shell.arg && page.locations.length) {
                var la = page.locations.map(function(l) { return l.lat }), lo = page.locations.map(function(l) { return l.lng })
                map.fit(Math.min.apply(null, la), Math.min.apply(null, lo), Math.max.apply(null, la), Math.max.apply(null, lo))
                if (map.zoom > 14) map.zoom = 14
            }
        }).catch(function(e) { ui.toast(e.message, true) })
        Net.get("/api/map/zones").then(function(r) { page.zoneItems = r.items || [] }).catch(function() {})
        Net.get("/api/map/routes").then(function(r) { page.routeItems = r.items || [] }).catch(function() {})
    }
    function pickSource(s) {
        page.source = s
        page.offline = (s.pack_count || 0) > 0
        map.minZoom = s.min_zoom || 1; map.maxZoom = s.max_zoom || 18
    }
    Component.onCompleted: {
        if (shell.arg && shell.arg.lat !== undefined) map.centerOn(shell.arg.lat, shell.arg.lng, 15)
        load()
    }

    function tileUrl(z, x, y) {
        if (!page.source) return ""
        if (page.offline) return "image://api/api/map/tiles/" + page.source.id + "/" + z + "/" + x + "/" + y
        var subs = page.source.subdomains || ""
        var s = subs.length ? subs.charAt((x + y) % subs.length) : ""
        return page.source.url_template.replace("{z}", z).replace("{x}", x).replace("{y}", y).replace("{s}", s).replace("{r}", "")
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0
        SlippyMap {
            id: map
            Layout.fillWidth: true; Layout.fillHeight: true
            tileSource: page.tileUrl
            picking: !page.draw
            selectedId: page.selected && page.selected.kind === "location" ? page.selected.data.id : (shell.arg ? shell.arg.focus : null)
            markers: (page.showLocations ? page.locations.map(function(l) {
                return { id: l.id, lat: l.lat, lng: l.lng, color: page.envColor(l.environment), label: l.name, data: l }
            }) : []).concat(page.draw ? page.draw.points.map(function(p, i) {
                return { id: "draw-" + i, lat: p[0], lng: p[1], color: Theme.accent, label: "" } }) : [])
            zones: (page.drawZone ? [page.drawZone] : []).concat(page.showZones ? page.zoneItems.map(function(zn) {
                var g = zn.geometry || {}
                var z = { id: zn.id, color: page.envColor(zn.environment), dim: !!zn.expired, data: zn }
                if (zn.shape === "circle" && g.coordinates) { z.center = [g.coordinates[1], g.coordinates[0]]; z.radius_m = zn.radius_m }
                else z.ring = ((g.coordinates || [])[0] || []).map(function(c) { return [c[1], c[0]] })
                return z
            }) : [])
            routes: (page.drawRoute ? [page.drawRoute] : []).concat(page.showRoutes ? page.routeItems.map(function(rt) {
                var g = rt.geometry || {}
                var lines = g.type === "LineString" ? [g.coordinates || []] : (g.coordinates || [])
                return { id: rt.id, color: rt.environment ? page.envColor(rt.environment) : page.routeColor, data: rt,
                         lines: lines.map(function(line) { return line.map(function(c) { return [c[1], c[0]] }) }) }
            }) : [])
            onMarkerClicked: function(m) { if (m.data) page.selected = { kind: "location", data: m.data } }
            onZoneClicked: function(z) { if (z.data) page.selected = { kind: "zone", data: z.data } }
            onRouteClicked: function(r) { if (r.data) page.selected = { kind: "route", data: r.data } }
            onTapped: function(lat, lng) { if (page.draw) page.addPoint(lat, lng); else page.selected = null }

            // While drawing: what to do, and the way out.
            Rectangle {
                visible: !!page.draw
                anchors.top: parent.top; anchors.horizontalCenter: parent.horizontalCenter; anchors.topMargin: 10 * Theme.s
                width: Math.min(parent.width - 20 * Theme.s, drawRow.implicitWidth + 24 * Theme.s)
                height: drawRow.implicitHeight + 16 * Theme.s
                radius: Theme.radius * 1.4; color: Theme.panel; border.color: Theme.accent
                Row {
                    id: drawRow
                    anchors.centerIn: parent
                    spacing: 8 * Theme.s
                    Txt { anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap
                          text: page.draw ? (page.draw.redraw ? "Redraw the route: " : "") + page.drawHints[page.draw.kind] : "" }
                    Txt { anchors.verticalCenter: parent.verticalCenter; kind: "muted"; wrapMode: Text.NoWrap
                          visible: !!page.draw && page.draw.points.length > 0
                          text: page.draw ? page.draw.points.length + (page.draw.points.length === 1 ? " point" : " points")
                                            + (page.draw.kind === "route" && page.draw.points.length > 1 ? " · " + page.lengthText(page.drawLength()) : "") : "" }
                    Btn { compact: true; text: "Undo point"; visible: !!page.draw && page.draw.points.length > 0; onClicked: page.undoPoint() }
                    Btn { compact: true; kind: "primary"; text: "Finish"; visible: !!page.draw && (page.draw.kind === "polygon" || page.draw.kind === "route")
                          onClicked: page.finishDraw() }
                    Btn { compact: true; text: "Cancel"; onClicked: page.draw = null }
                }
            }
        }

        // Side panel: basemap, layers, and what was tapped.
        Rectangle {
            Layout.preferredWidth: 300 * Theme.s; Layout.fillHeight: true
            color: Theme.panel2
            Rectangle { width: Math.max(1, Theme.s); height: parent.height; color: Theme.border }
            Flickable {
                anchors.fill: parent; anchors.margins: Theme.pad
                contentHeight: side.implicitHeight
                clip: true
                Column {
                    id: side
                    width: parent.width
                    spacing: Theme.gap
                    Txt { kind: "label"; text: "Basemap" }
                    Txt { width: parent.width; visible: page.sources.length === 0; kind: "muted"
                          text: "No map sources yet. An admin adds one, and downloads areas for offline use, in the console's Admin → Maps." }
                    Repeater {
                        model: page.sources
                        Btn { width: side.width; compact: true; text: modelData.name
                              sub: (modelData.pack_count || 0) > 0 ? "offline areas downloaded" : "needs the internet"
                              kind: page.source && page.source.id === modelData.id ? "primary" : "normal"
                              onClicked: page.pickSource(modelData) }
                    }
                    Check { visible: !!page.source && (page.source.pack_count || 0) > 0; checked: page.offline
                               onToggled: page.offline = checked; text: "Offline areas only" }
                    Txt { kind: "label"; text: "Show" }
                    Repeater {
                        model: [["showLocations", "Locations (" + page.locations.length + ")"], ["showZones", "Zones (" + page.zoneItems.length + ")"],
                                ["showRoutes", "Routes (" + page.routeItems.length + ")"]]
                        Check { checked: page[modelData[0]]; onToggled: page[modelData[0]] = checked; text: modelData[1] }
                    }
                    Txt { kind: "label"; text: "Draw"; visible: !shell.viewer }
                    Flow {
                        width: parent.width; spacing: 6 * Theme.s; visible: !shell.viewer
                        Btn { compact: true; text: "Zone: shape"; onClicked: page.startDraw("polygon") }
                        Btn { compact: true; text: "Zone: box"; onClicked: page.startDraw("box") }
                        Btn { compact: true; text: "Zone: circle"; onClicked: page.startDraw("circle") }
                        Btn { compact: true; text: "Route"; onClicked: page.startDraw("route") }
                    }
                    Txt { kind: "label"; text: "Ground" }
                    Repeater {
                        model: ["Permissive", "Semi-permissive", "Non-permissive", "Denied", "Unknown"]
                        Row { spacing: 8 * Theme.s
                              Rectangle { width: 14 * Theme.s; height: width; radius: width / 2; color: page.envColor(modelData)
                                          anchors.verticalCenter: parent.verticalCenter }
                              Txt { text: modelData; kind: "muted" } }
                    }

                    // What was tapped
                    Card {
                        width: parent.width
                        visible: !!page.selected
                        title: page.selected ? ({ location: "Location", zone: "Zone", route: "Route" })[page.selected.kind] : ""
                        implicitHeight: selCol.implicitHeight + 2 * padding + Theme.gap + 20 * Theme.s
                        Column {
                            id: selCol
                            width: parent.width; spacing: 6 * Theme.s
                            readonly property string k: page.selected ? page.selected.kind : ""
                            readonly property var d: page.selected ? page.selected.data : ({})
                            Txt { width: parent.width; text: selCol.d.name || ""; font.weight: Font.DemiBold }
                            Txt { width: parent.width; visible: selCol.k === "location" && !!selCol.d.address; kind: "muted"; text: selCol.d.address || "" }
                            Txt { width: parent.width; visible: !!selCol.d.description; text: selCol.d.description || ""; font.family: Theme.prose }
                            Txt { width: parent.width; visible: selCol.k === "zone" && !!selCol.d.notes; text: selCol.d.notes || ""; font.family: Theme.prose }
                            Txt { width: parent.width; font.family: "IBM Plex Mono"; kind: "muted"; visible: selCol.k === "location"
                                  text: selCol.k === "location" && selCol.d.lat !== undefined ? selCol.d.lat.toFixed(5) + ", " + selCol.d.lng.toFixed(5) : "" }
                            Pill { visible: !!selCol.d.environment; text: selCol.d.environment || ""; tone: page.envColor(selCol.d.environment) }
                            Txt { width: parent.width; kind: "muted"; visible: selCol.k === "zone"
                                  text: selCol.k !== "zone" ? "" : (selCol.d.shape || "") + (selCol.d.expired ? " · expired" : "")
                                        + (selCol.d.valid_until ? " · until " + Fmt.exactTime(selCol.d.valid_until) : " · open-ended")
                                        + (selCol.d.event_name ? " · part of " + selCol.d.event_name : "") }
                            Txt { width: parent.width; kind: "muted"; visible: selCol.k === "route"
                                  text: selCol.k !== "route" ? "" : page.lengthText(selCol.d.length_m || 0) + " · " + (selCol.d.point_count || 0) + " points"
                                        + (selCol.d.travel_mode ? " · " + selCol.d.travel_mode : "") }
                            Flow {
                                width: parent.width; spacing: 6 * Theme.s
                                Btn { compact: true; text: "Open the record"; visible: selCol.k !== "zone" || !!selCol.d.entity_id
                                      onClicked: shell.go("entity", selCol.k === "zone" ? selCol.d.entity_id : selCol.d.id) }
                                Btn { compact: true; text: "Edit"; visible: selCol.k === "zone" && !shell.viewer; onClicked: zoneForm.open(selCol.d, null) }
                                Btn { compact: true; text: "Redraw"; visible: selCol.k === "route" && !shell.viewer; onClicked: page.startDraw("route", selCol.d.id) }
                            }
                        }
                    }
                }
            }
        }
    }

    FormDialog {
        id: zoneForm
        property var zone: null
        property var geometry: null
        title: zone ? "Edit zone" : "New zone"
        okText: zone ? "Save" : "Create zone"
        function open(z, g) {
            zone = z; geometry = g
            zName.text = z ? z.name : ""; zEnv.value = z ? z.environment : "Semi-permissive"
            zFrom.text = page.localText(z ? z.valid_from : new Date().toISOString()); zUntil.text = page.localText(z ? z.valid_until : null)
            zNotes.text = z ? (z.notes || "") : ""; zEvent.text = ""; zWhy.text = ""
            visible = true
        }
        onAccepted: {
            var body = { name: zName.text.trim(), environment: zEnv.value, valid_from: page.isoFrom(zFrom.text),
                         valid_until: page.isoFrom(zUntil.text), notes: zNotes.text.trim() || null }
            if (!body.name) { error = "Give the zone a name."; return }
            if (zone) { if (zWhy.text.trim()) body.change_note = zWhy.text.trim() }
            else { body.geometry = geometry; if (zEvent.text.trim()) body.create_event = zEvent.text.trim() }
            busy = true
            var req = zone ? Net.patch("/api/map/zones/" + zone.id, body) : Net.post("/api/map/zones", body)
            req.then(function(saved) {
                busy = false; close()
                ui.toast(zone ? "Zone updated" : (saved.event_name ? "Zone created, tied to the event “" + saved.event_name + "”" : "Zone created"))
                page.selected = null; page.load()
            }).catch(function(e) { busy = false; error = e.message })
        }
        Labeled { label: "Name"; Field { id: zName; width: parent.width; placeholderText: "e.g. Riverside protest" } }
        Labeled { label: "Ground"; hint: "Sets the zone's colour. Denied means no access at all."
                  Select { id: zEnv; width: parent.width
                           options: ["Permissive", "Semi-permissive", "Non-permissive", "Denied", "Unknown"].map(function(v) { return [v, v] }) } }
        Labeled { label: "From (YYYY-MM-DD HH:MM)"; Field { id: zFrom; width: parent.width; mono: true } }
        Labeled { label: "Until (YYYY-MM-DD HH:MM)"; hint: "Blank for no end. An expired zone is dimmed, not removed."
                  Field { id: zUntil; width: parent.width; mono: true } }
        Labeled { label: "Why the change"; visible: !!zoneForm.zone; hint: "Kept on the zone's timeline when its ground changes."
                  Field { id: zWhy; width: parent.width; placeholderText: "e.g. police line moved onto the bridge" } }
        Labeled { label: "Event"; visible: !zoneForm.zone; hint: "Makes an Event and ties this zone to it. Blank for none."
                  Field { id: zEvent; width: parent.width; placeholderText: "e.g. Riverside protest, 17 Sep" } }
        Labeled { label: "Notes"; Field { id: zNotes; width: parent.width } }
    }

    FormDialog {
        id: routeForm
        property var points: []
        title: "New route"
        okText: "Create route"
        function open(p) { points = p; rName.text = ""; rWhy.text = ""; rEnv.value = ""; rMode.value = ""; visible = true }
        onAccepted: {
            var body = { name: rName.text.trim(), description: rWhy.text.trim() || null, environment: rEnv.value || null,
                         travel_mode: rMode.value || null, points: points }
            if (!body.name) { error = "Give the route a name."; return }
            busy = true
            Net.post("/api/routes", body).then(function(saved) {
                busy = false; close(); ui.toast("Route created · " + page.lengthText(saved.length_m || 0)); page.load()
            }).catch(function(e) { busy = false; error = e.message })
        }
        Labeled { label: "Name"; Field { id: rName; width: parent.width; placeholderText: "e.g. Safe route to the north gate" } }
        Labeled { label: "Why"; Field { id: rWhy; width: parent.width; placeholderText: "What it avoids, when it is usable, who uses it" } }
        Labeled { label: "How workable"
                  Select { id: rEnv; width: parent.width
                           options: [["", "—"]].concat(["Permissive", "Semi-permissive", "Non-permissive", "Denied", "Unknown"].map(function(v) { return [v, v] })) } }
        Labeled { label: "Travelled by"
                  Select { id: rMode; width: parent.width
                           options: [["", "—"]].concat(["On foot", "Vehicle", "Bicycle", "Boat", "Aircraft", "Other"].map(function(v) { return [v, v] })) } }
        Txt { width: parent.width; kind: "muted"
              text: routeForm.points.length + " points · " + page.lengthText((function() { var m = 0; for (var i = 1; i < routeForm.points.length; i++) m += page.metres(routeForm.points[i - 1], routeForm.points[i]); return m })())
                    + ". A drawn route is a plan, not a track." }
    }
}
