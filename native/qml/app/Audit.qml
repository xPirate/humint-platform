import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Humint
import ".."
import "../lib/fmt.js" as Fmt
import "../lib/audit.js" as Audit

// Who did what, when (admins only): sign-ins, changes, exports, deletions.
// Failed and refused actions stand out. Export as CSV to a USB stick.
Rectangle {
    id: page
    color: Theme.bg
    property var items: []
    property int total: 0
    property int offset: 0
    readonly property int pageSize: 100

    function query() { return Net.qs({ q: search.text.trim(), outcome: outcome.value, actor: actor.text.trim() }) }
    function load() {
        var q = query()
        Net.get("/api/admin/audit-log" + q + (q ? "&" : "?") + "limit=" + pageSize + "&offset=" + offset).then(function(r) {
            page.items = r.items || []; page.total = r.total || 0
        }).catch(function(e) { ui.toast(e.message, true) })
    }
    Component.onCompleted: load()
    Timer { id: delay; interval: 300; onTriggered: { page.offset = 0; page.load() } }

    ColumnLayout {
        anchors.fill: parent; anchors.margins: Theme.pad
        spacing: Theme.gap
        PageHeader {
            Layout.fillWidth: true
            title: "Audit log"
            subtitle: page.total ? (page.offset + 1) + "–" + Math.min(page.offset + page.items.length, page.total) + " of " + page.total : ""
            Btn { compact: true; text: "CSV to USB"; onClicked: usb.exportFile("/api/admin/audit-log.csv" + page.query(), "audit-log.csv") }
        }
        RowLayout {
            Layout.fillWidth: true; spacing: 8 * Theme.s
            Field { id: search; Layout.fillWidth: true; placeholderText: "Search what was touched or done"; onTextChanged: delay.restart() }
            Field { id: actor; Layout.preferredWidth: 200 * Theme.s; placeholderText: "Who"; onTextChanged: delay.restart() }
            Select { id: outcome; options: [["", "Any outcome"], ["success", "Succeeded"], ["failure", "Failed"], ["denied", "Refused"]]
                     onPicked: { page.offset = 0; page.load() } }
        }
        ListView {
            Layout.fillWidth: true; Layout.fillHeight: true
            clip: true; spacing: 2 * Theme.s
            model: page.items
            ScrollBar.vertical: ScrollBar {}
            delegate: Rectangle {
                width: ListView.view.width
                implicitHeight: row.implicitHeight + 12 * Theme.s
                color: index % 2 ? Theme.panel : Theme.panel2
                radius: Theme.radius
                border.color: modelData.outcome !== "success" ? Theme.red : "transparent"
                RowLayout {
                    id: row
                    x: 10 * Theme.s; y: 6 * Theme.s; width: parent.width - 20 * Theme.s
                    spacing: Theme.gap
                    Txt { Layout.preferredWidth: 150 * Theme.s; kind: "muted"; text: Fmt.exactTime(modelData.occurred_at); wrapMode: Text.NoWrap }
                    Column {
                        Layout.fillWidth: true
                        Txt { width: parent.width
                              text: (modelData.actor_kind === "system" ? "system" : (modelData.actor_username || "unknown")) + "  ·  "
                                    + Audit.label(modelData.action) + (modelData.object_label ? "  ·  " + Fmt.truncate(modelData.object_label, 80)
                                                                       : modelData.object_id ? "  ·  " + modelData.object_id : "") }
                    }
                    Pill { visible: modelData.outcome !== "success"; text: modelData.outcome; tone: Theme.red }
                    Txt { visible: !!modelData.ip_address; kind: "muted"; text: modelData.ip_address || ""; wrapMode: Text.NoWrap; font.family: "IBM Plex Mono" }
                }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Item { Layout.fillWidth: true }
            Btn { compact: true; text: "← Newer"; enabled: page.offset > 0
                  onClicked: { page.offset = Math.max(0, page.offset - page.pageSize); page.load() } }
            Btn { compact: true; text: "Older →"; enabled: page.offset + page.items.length < page.total
                  onClicked: { page.offset += page.pageSize; page.load() } }
        }
    }
}
