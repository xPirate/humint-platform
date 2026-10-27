import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Humint
import ".."
import "../lib/fmt.js" as Fmt
import "../lib/schema.js" as Schema

// Records: everyone and everything in the case file. Search, filter by
// kind, include archived ones, leave out expired events.
Rectangle {
    id: page
    color: Theme.bg
    property var items: []
    property bool loading: true
    property string error: ""

    function load() {
        page.loading = true
        Net.get("/api/entities" + Net.qs({ limit: 200, active_only: archived.checked ? "false" : "true",
                                           q: search.text.trim(), entity_type: type.value,
                                           hide_expired: hideExpired.checked ? "true" : "" })).then(function(r) {
            page.items = r.items || []; page.loading = false; page.error = ""
        }).catch(function(e) { page.loading = false; page.error = e.message })
    }
    Component.onCompleted: load()
    Timer { id: searchDelay; interval: 300; onTriggered: page.load() }

    ColumnLayout {
        anchors.fill: parent; anchors.margins: Theme.pad
        spacing: Theme.gap
        PageHeader {
            Layout.fillWidth: true
            title: "Records"
            subtitle: page.loading ? "" : page.items.length + (page.items.length === 200 ? "+" : "") + " shown"
            Btn { compact: true; text: "Network"; onClicked: shell.go("network", null) }
            Btn { compact: true; kind: "primary"; text: "+ New record"; visible: !shell.viewer
                  onClicked: shell.go("entityEdit", null) }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 8 * Theme.s
            Field { id: search; Layout.fillWidth: true; placeholderText: "Search names, aliases, descriptions"
                    onTextChanged: searchDelay.restart() }
            Select { id: type; options: [["", "Every kind"]].concat(Fmt.ENTITY_TYPES.map(function(t) { return [t, Fmt.typeLabel(t)] }))
                     onPicked: page.load() }
            Check { id: archived; text: "Archived too"; onToggled: page.load() }
            Check { id: hideExpired; text: "Hide expired events"; onToggled: page.load() }
        }
        Txt { visible: page.error !== ""; color: Theme.amber; text: page.error }
        Txt { visible: !page.loading && page.items.length === 0 && page.error === ""; kind: "muted"; text: "No records found." }
        GridView {
            id: grid
            Layout.fillWidth: true; Layout.fillHeight: true
            clip: true
            readonly property int cols: Math.max(1, Math.floor(width / (360 * Theme.s)))
            cellWidth: width / cols
            cellHeight: 108 * Theme.s
            model: page.items
            ScrollBar.vertical: ScrollBar {}
            delegate: Item {
                width: grid.cellWidth; height: grid.cellHeight
                ListCard {
                    anchors.fill: parent; anchors.margins: 4 * Theme.s
                    title: modelData.name + (modelData.is_active === false ? "  (archived)" : "")
                    snippet: modelData.description || ""
                    accent: Theme.kindColor(modelData.entity_type)
                    pills: [
                        Pill { text: Fmt.typeLabel(modelData.entity_type); tone: Theme.kindColor(modelData.entity_type) },
                        Repeater { model: Schema.badges(modelData); Pill { text: modelData; tone: Theme.amber } }
                    ]
                    onClicked: shell.go("entity", modelData.id)
                }
            }
        }
    }
}
