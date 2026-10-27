import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Humint
import ".."
import "../lib/fmt.js" as Fmt

// Retention: records nobody has touched for longer than their kind's window
// are archived (never deleted). Off unless switched on.
Rectangle {
    id: page
    color: Theme.bg
    property var st: null
    property var due: []
    function load() {
        Net.get("/api/admin/retention").then(function(r) { page.st = r }).catch(function(e) { ui.toast(e.message, true) })
        Net.get("/api/admin/retention/due").then(function(r) { page.due = r.items || [] }).catch(function() {})
    }
    Component.onCompleted: load()
    ColumnLayout {
        anchors.fill: parent; anchors.margins: Theme.pad
        spacing: Theme.gap
        PageHeader { Layout.fillWidth: true; title: "Retention"
                     subtitle: "Records untouched past their kind's window are archived, not deleted. Editing, linking or naming one in a report resets it." }
        Txt { Layout.fillWidth: true; text: page.st ? (page.st.enabled ? "On." : "Off.") : "" }
        Txt { Layout.fillWidth: true; kind: "muted"; text: page.due.length + " record(s) due to be archived. Set the windows in the console's Admin → Retention." }
        ListView {
            Layout.fillWidth: true; Layout.fillHeight: true
            clip: true; spacing: 4 * Theme.s
            model: page.due
            delegate: Btn { width: ListView.view.width; compact: true; kind: "ghost"
                            text: (modelData.name || modelData.id) + (modelData.due_at ? "  ·  " + Fmt.exactDate(modelData.due_at) : "")
                            onClicked: shell.go("entity", modelData.id) }
        }
    }
}
