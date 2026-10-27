import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Humint
import ".."

// Which boards this case file has, and what they are called here.
Rectangle {
    id: page
    color: Theme.bg
    property var boards: ({})
    function load() { Net.get("/api/boards").then(function(r) { page.boards = r.boards || {} }).catch(function(e) { ui.toast(e.message, true) }) }
    Component.onCompleted: load()
    function save(kind, patch) {
        var b = page.boards[kind]
        var body = {}
        body[kind] = { enabled: patch.enabled !== undefined ? patch.enabled : b.enabled,
                       label: patch.label !== undefined ? patch.label : b.custom_label,
                       blurb: b.custom_blurb }
        Net.put("/api/admin/boards", body).then(function() { ui.toast("Saved"); page.load(); shell.loadBoards() })
            .catch(function(e) { ui.toast(e.message, true) })
    }
    ColumnLayout {
        anchors.fill: parent; anchors.margins: Theme.pad
        spacing: Theme.gap
        PageHeader { Layout.fillWidth: true; title: "Boards"; subtitle: "Switched off, a board is hidden from everyone; nothing on it is lost." }
        Repeater {
            model: ["bolo", "roster", "priorities"]
            Card {
                id: bc
                Layout.fillWidth: true
                readonly property string kind: modelData
                readonly property var b: page.boards[modelData] || ({})
                title: kind
                implicitHeight: bcol.implicitHeight + 2 * padding + Theme.gap + 20 * Theme.s
                Column {
                    id: bcol
                    width: parent.width; spacing: 8 * Theme.s
                    Check { text: "Shown"; checked: !!bc.b.enabled; onToggled: page.save(bc.kind, { enabled: checked }) }
                    RowLayout { width: parent.width
                        Field { id: lbl; Layout.fillWidth: true; text: bc.b.custom_label || ""; placeholderText: bc.b.label || "" }
                        Btn { compact: true; text: "Rename"; onClicked: page.save(bc.kind, { label: lbl.text.trim() || null }) } }
                }
            }
        }
        Item { Layout.fillHeight: true }
    }
}
