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
            selectedId: page.selected && page.selected.kind === "location" ? page.selected.data.id : (shell.arg ? shell.arg.focus : null)
            markers: page.showLocations ? page.locations.map(function(l) {
                return { id: l.id, lat: l.lat, lng: l.lng, color: page.envColor(l.environment), label: l.name, data: l }
            }) : []
            zones: page.showZones ? page.zoneItems.map(function(zn) {
                var g = zn.geometry || {}
                var z = { id: zn.id, color: page.envColor(zn.environment), dim: !!zn.expired, data: zn }
                if (zn.shape === "circle" && g.coordinates) { z.center = [g.coordinates[1], g.coordinates[0]]; z.radius_m = zn.radius_m }
                else z.ring = ((g.coordinates || [])[0] || []).map(function(c) { return [c[1], c[0]] })
                return z
            }) : []
            routes: page.showRoutes ? page.routeItems.map(function(rt) {
                var g = rt.geometry || {}
                var lines = g.type === "LineString" ? [g.coordinates || []] : (g.coordinates || [])
                return { id: rt.id, color: rt.environment ? page.envColor(rt.environment) : page.routeColor, data: rt,
                         lines: lines.map(function(line) { return line.map(function(c) { return [c[1], c[0]] }) }) }
            }) : []
            onMarkerClicked: function(m) { page.selected = { kind: "location", data: m.data } }
            onTapped: page.selected = null
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
                        title: "Location"
                        implicitHeight: selCol.implicitHeight + 2 * padding + Theme.gap + 20 * Theme.s
                        Column {
                            id: selCol
                            width: parent.width; spacing: 6 * Theme.s
                            readonly property var d: page.selected ? page.selected.data : ({})
                            Txt { width: parent.width; text: selCol.d.name || ""; font.weight: Font.DemiBold }
                            Txt { width: parent.width; visible: !!selCol.d.address; kind: "muted"; text: selCol.d.address || "" }
                            Txt { width: parent.width; visible: !!selCol.d.description; text: selCol.d.description || ""; font.family: Theme.prose }
                            Txt { width: parent.width; font.family: "IBM Plex Mono"; kind: "muted"
                                  text: selCol.d.lat !== undefined ? selCol.d.lat.toFixed(5) + ", " + selCol.d.lng.toFixed(5) : "" }
                            Pill { visible: !!selCol.d.environment; text: selCol.d.environment || ""; tone: page.envColor(selCol.d.environment) }
                            Btn { compact: true; text: "Open the record"; onClicked: shell.go("entity", selCol.d.id) }
                        }
                    }
                }
            }
        }
    }
}
