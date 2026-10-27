import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Humint
import ".."
import "../lib/fmt.js" as Fmt

// Carrying the case home on a USB stick: a field package of what changed
// here, for the headquarters console to review; and taking one in.
Rectangle {
    id: page
    color: Theme.bg
    property var st: null
    function load() { Net.get("/api/field-sync/status").then(function(r) { page.st = r }).catch(function(e) { ui.toast(e.message, true) }) }
    Component.onCompleted: load()
    Flickable {
        anchors.fill: parent; anchors.margins: Theme.pad
        contentHeight: fcol.implicitHeight
        clip: true
        Column {
            id: fcol
            width: parent.width; spacing: Theme.gap
            PageHeader { width: parent.width; title: "Field sync"
                         subtitle: "What changed here, on a USB stick, for another console to review — and taking one in. Nothing enters a case file unreviewed." }
            Card {
                width: parent.width; title: "Make a field package"
                implicitHeight: ecol.implicitHeight + 2 * padding + Theme.gap + 20 * Theme.s
                Column {
                    id: ecol
                    width: parent.width; spacing: 8 * Theme.s
                    Flow { width: parent.width; spacing: 8 * Theme.s
                        Repeater { model: [["since_last", "Since the last package"], ["since_seeded", "Since this machine was set up"], ["everything", "Everything"]]
                            Btn { compact: true; text: modelData[1]
                                  onClicked: usb.exportFile("/api/field-sync/export", "field-package-" + new Date().toISOString().slice(0, 16).replace(/[:T]/g, "-") + ".zip",
                                                            { mode: modelData[0] }) } } }
                    Repeater { model: page.st ? page.st.exports || [] : []
                        Txt { width: ecol.width; kind: "muted"; text: "Made " + Fmt.exactTime(modelData.exported_at) } }
                }
            }
            Card {
                width: parent.width; title: "Take one in"
                implicitHeight: icol.implicitHeight + 2 * padding + Theme.gap + 20 * Theme.s
                Column {
                    id: icol
                    width: parent.width; spacing: 8 * Theme.s
                    Txt { width: parent.width; text: "Its records and reports arrive in the review inbox, to accept or not." }
                    Btn { kind: "primary"; text: "Choose a package on a USB stick…"
                          onClicked: usb.pickFile(function(path) {
                              ui.busy("Reading the package…")
                              Net.upload("/api/field-sync/import", path, {}).then(function() {
                                  ui.busy(""); ui.toast("Taken in — its contents are in the review inbox"); page.load()
                              }).catch(function(e) { ui.busy(""); ui.toast(e.message, true) })
                          }) }
                }
            }
        }
    }
}
