import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Humint
import ".."

// The whole case file — records, reports, files — as one zip on a USB stick,
// and putting one back. A restore replaces everything here.
Rectangle {
    id: page
    color: Theme.bg
    readonly property string phrase: "REPLACE ALL DATA"
    ColumnLayout {
        anchors.fill: parent; anchors.margins: Theme.pad
        spacing: Theme.gap
        PageHeader { Layout.fillWidth: true; title: "Backup & restore" }
        Card {
            Layout.fillWidth: true
            title: "Back up"
            implicitHeight: bcol.implicitHeight + 2 * padding + Theme.gap + 20 * Theme.s
            Column {
                id: bcol
                width: parent.width; spacing: 8 * Theme.s
                Txt { width: parent.width
                      text: "Everything in the case file, files included, in one zip. It is NOT encrypted: a stick holding it is the case file. Keep it like one." }
                Btn { kind: "primary"; text: "Back up to a USB stick"
                      onClicked: usb.exportFile("/api/admin/backup", "humint-backup-" + new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-") + ".zip") }
            }
        }
        Card {
            Layout.fillWidth: true
            title: "Restore"
            implicitHeight: rcol.implicitHeight + 2 * padding + Theme.gap + 20 * Theme.s
            Column {
                id: rcol
                width: parent.width; spacing: 8 * Theme.s
                Txt { width: parent.width; color: Theme.amber
                      text: "A restore replaces everything in this case file with the backup's contents. Take a backup of what is here first." }
                Field { id: confirm; width: parent.width; placeholderText: "Type " + page.phrase + " to confirm" }
                Btn { kind: "danger"; text: "Restore from a USB stick…"; enabled: confirm.text.trim() === page.phrase
                      onClicked: usb.pickFile(function(path) {
                          ui.busy("Restoring — this can take a while…")
                          Net.upload("/api/admin/restore", path, { confirm: page.phrase }).then(function(r) {
                              ui.busy(""); confirm.text = ""; ui.toast("Restored. Sign in again.")
                              Api.signOut(); Net.me = null; Net.signedOut()
                          }).catch(function(e) { ui.busy(""); ui.toast(e.message, true) })
                      }) }
            }
        }
        Item { Layout.fillHeight: true }
    }
}
