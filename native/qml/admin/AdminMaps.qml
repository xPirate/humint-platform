import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Humint
import ".."
import "../lib/fmt.js" as Fmt

// Offline maps: download an area of a map source while there is internet,
// so the map works without it. Move the small map to the area, choose how
// far in, check the estimate, download. Sources can be added (an XYZ tile
// address whose terms allow downloading).
Rectangle {
    id: page
    color: Theme.bg
    property var sources: []
    property var packs: []
    property var source: null
    property var estimate: null
    property int minZoom: 8
    property int maxZoom: 14

    function load() {
        Net.get("/api/admin/map/sources").then(function(r) {
            page.sources = r.items || []
            if (!page.source && page.sources.length) page.source = page.sources.filter(function(s) { return s.allow_download })[0] || page.sources[0]
        }).catch(function(e) { ui.toast(e.message, true) })
        Net.get("/api/admin/map/packs").then(function(r) { page.packs = r.items || [] }).catch(function() {})
    }
    Component.onCompleted: load()
    Timer { interval: 3000; repeat: true
            running: page.packs.some(function(p) { return p.status === "queued" || p.status === "downloading" })
            onTriggered: Net.get("/api/admin/map/packs").then(function(r) { page.packs = r.items || [] }) }

    function area() {
        var a = mini.toLatLng(0, mini.height), b = mini.toLatLng(mini.width, 0)
        return { source_id: page.source.id, min_lat: Math.max(-85, a.lat), min_lon: Math.max(-180, a.lng),
                 max_lat: Math.min(85, b.lat), max_lon: Math.min(180, b.lng), min_zoom: page.minZoom, max_zoom: page.maxZoom }
    }
    function doEstimate() {
        if (!page.source) return
        Net.post("/api/admin/map/packs/estimate", area()).then(function(r) { page.estimate = r }).catch(function(e) { ui.toast(e.message, true) })
    }
    Timer { id: estDelay; interval: 600; onTriggered: page.doEstimate() }

    RowLayout {
        anchors.fill: parent; anchors.margins: Theme.pad
        spacing: Theme.gap * 1.5
        ColumnLayout {
            Layout.fillWidth: true; Layout.fillHeight: true
            spacing: Theme.gap
            PageHeader { Layout.fillWidth: true; title: "Offline maps"
                         subtitle: "Download areas now, while there is internet, so the map works without it." }
            Flow {
                Layout.fillWidth: true; spacing: 6 * Theme.s
                Repeater { model: page.sources
                    Btn { compact: true; text: modelData.name; sub: modelData.allow_download ? "can download" : "view only"
                          kind: page.source && page.source.id === modelData.id ? "primary" : "normal"
                          onClicked: { page.source = modelData; estDelay.restart() } } }
                Btn { compact: true; kind: "ghost"; text: "+ Add a source"; onClicked: addSource.open() }
            }
            SlippyMap {
                id: mini
                Layout.fillWidth: true; Layout.fillHeight: true
                tileSource: function(z, x, y) {
                    if (!page.source) return ""
                    var subs = page.source.subdomains || ""
                    return page.source.url_template.replace("{z}", z).replace("{x}", x).replace("{y}", y)
                               .replace("{s}", subs.length ? subs.charAt((x + y) % subs.length) : "").replace("{r}", "")
                }
                onCenterLatChanged: estDelay.restart()
                onZoomChanged: estDelay.restart()
                Rectangle { anchors.fill: parent; color: "transparent"; border.color: Theme.amber; border.width: 3 * Theme.s }
            }
            RowLayout {
                Layout.fillWidth: true; spacing: 8 * Theme.s
                Txt { text: "Zoom " + page.minZoom + "–" + page.maxZoom }
                RangeSlider {
                    Layout.fillWidth: true
                    from: 0; to: page.source ? page.source.max_zoom : 19; stepSize: 1; snapMode: RangeSlider.SnapAlways
                    first.value: page.minZoom; second.value: page.maxZoom
                    first.onMoved: { page.minZoom = first.value; estDelay.restart() }
                    second.onMoved: { page.maxZoom = second.value; estDelay.restart() }
                }
            }
            Txt { Layout.fillWidth: true
                  color: page.estimate && (page.estimate.over_limit || !page.estimate.allow_download) ? Theme.amber : Theme.text
                  text: !page.estimate ? "Move the map to the area to download."
                        : !page.estimate.allow_download ? "This source's terms do not allow downloading. Choose another, or add one that does."
                        : page.estimate.tiles + " tiles, about " + Fmt.fileSize(page.estimate.estimated_bytes)
                          + (page.estimate.over_limit ? " — more than the " + page.estimate.max_tiles + " allowed; zoom in or lower the top zoom" : "") }
            RowLayout {
                Layout.fillWidth: true
                Field { id: packName; Layout.fillWidth: true; placeholderText: "Name for this area (e.g. Docks and river)" }
                Btn { kind: "primary"; text: "Download this area"
                      enabled: !!page.estimate && page.estimate.allow_download && !page.estimate.over_limit && packName.text.trim() !== ""
                      onClicked: Net.post("/api/admin/map/packs", Object.assign({ name: packName.text.trim() }, page.area())).then(function() {
                          packName.text = ""; ui.toast("Downloading — it carries on in the background"); page.load()
                      }).catch(function(e) { ui.toast(e.message, true) }) }
            }
        }
        // Downloaded areas
        Rectangle {
            Layout.preferredWidth: 330 * Theme.s; Layout.fillHeight: true
            radius: Theme.radius * 1.4; color: Theme.panel; border.color: Theme.border
            ColumnLayout {
                anchors.fill: parent; anchors.margins: Theme.pad
                Txt { kind: "label"; text: "Downloaded areas" }
                Txt { visible: page.packs.length === 0; kind: "muted"; text: "None yet." }
                ListView {
                    Layout.fillWidth: true; Layout.fillHeight: true
                    clip: true; spacing: 8 * Theme.s
                    model: page.packs
                    delegate: Column {
                        width: ListView.view.width; spacing: 4 * Theme.s
                        Txt { width: parent.width; text: modelData.name; font.weight: Font.DemiBold }
                        Txt { width: parent.width; kind: "muted"
                              text: modelData.status + " · z" + modelData.min_zoom + "–" + modelData.max_zoom + " · "
                                    + modelData.tiles_done + "/" + modelData.tiles_total + " tiles" + (modelData.bytes_total ? " · " + Fmt.fileSize(modelData.bytes_total) : "") }
                        ProgressBar { width: parent.width; visible: modelData.status === "downloading" || modelData.status === "queued"
                                      value: modelData.tiles_total ? modelData.tiles_done / modelData.tiles_total : 0 }
                        Txt { width: parent.width; visible: !!modelData.last_error; color: Theme.amber; text: modelData.last_error || "" }
                        Row { spacing: 6 * Theme.s
                              Btn { compact: true; kind: "ghost"; text: "Show"
                                    onClicked: mini.fit(modelData.min_lat, modelData.min_lon, modelData.max_lat, modelData.max_lon) }
                              Btn { compact: true; kind: "ghost"; text: "Stop"; visible: modelData.status === "downloading" || modelData.status === "queued"
                                    onClicked: Net.post("/api/admin/map/packs/" + modelData.id + "/cancel", {}).then(page.load) }
                              Btn { compact: true; kind: "ghost"; text: "Delete"; visible: modelData.status !== "downloading"
                                    onClicked: ui.confirm("Delete " + modelData.name + "?", "The map goes blank there without internet.", function() {
                                        Net.del("/api/admin/map/packs/" + modelData.id).then(page.load).catch(function(e) { ui.toast(e.message, true) }) }) } }
                    }
                }
            }
        }
    }

    FormDialog {
        id: addSource
        title: "Add a map source"
        okText: "Add"
        onOpened: { sName.text = ""; sUrl.text = ""; sAttr.text = ""; sDl.checked = false }
        onAccepted: {
            busy = true
            Net.post("/api/admin/map/sources", { name: sName.text.trim(), url_template: sUrl.text.trim(), attribution: sAttr.text.trim() || null,
                                                 allow_download: sDl.checked }).then(function() { busy = false; close(); page.load() })
                .catch(function(e) { busy = false; error = e.message })
        }
        Labeled { label: "Name"; Field { id: sName; width: parent.width } }
        Labeled { label: "Tile address"; hint: "An XYZ template with {z}, {x} and {y}, e.g. https://tiles.example.org/{z}/{x}/{y}.png"
                  Field { id: sUrl; width: parent.width; mono: true } }
        Labeled { label: "Attribution"; Field { id: sAttr; width: parent.width } }
        Check { id: sDl; text: "Its terms allow downloading areas for offline use" }
    }
}
