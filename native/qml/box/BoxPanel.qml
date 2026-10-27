import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Humint
import ".."

// The machine itself — everything the Pi's touch panel offers: its state,
// how the team joins, the certificate to trust, phone upload codes, and
// lock / network / power / update / wipe / duress / new login.
// Open to whoever is at the unlocked machine, signed in or not, as on the Pi.
Rectangle {
    id: box
    color: Theme.bg
    readonly property var st: Box.state || ({})
    property string tab: "status"

    function ctl(label, action, args, okText) {
        ui.busy(label + "…")
        Net.box("ctl", { action: action, args: args || [] }).then(function(r) {
            ui.busy("")
            ui.toast(r.rc === 0 ? (okText || label + ": done") : label + ": failed (" + r.rc + ")", r.rc !== 0)
        }).catch(function(e) { ui.busy(""); ui.toast(e.message, true) })
    }

    StatusStrip {
        id: strip
        anchors.top: parent.top; width: parent.width
        title: "Box"
        leftItems: [ Btn { compact: true; text: "← Done"; onClicked: shell.boxOpen = false } ]
    }

    // Tabs
    Row {
        id: tabs
        anchors.top: strip.bottom; anchors.topMargin: Theme.gap
        anchors.horizontalCenter: parent.horizontalCenter
        spacing: 8 * Theme.s
        Repeater {
            model: [["status", "Status"], ["join", "Join"], ["trust", "Trust"], ["upload", "Phone upload"], ["actions", "Actions"]]
            Btn {
                compact: true
                text: modelData[1]
                kind: box.tab === modelData[0] ? "primary" : "normal"
                onClicked: box.tab = modelData[0]
            }
        }
    }

    Loader {
        anchors.top: tabs.bottom; anchors.topMargin: Theme.gap
        anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
        anchors.margins: Theme.pad
        source: ({ status: "BoxStatus.qml", join: "BoxJoin.qml", trust: "BoxTrust.qml",
                   upload: "BoxUpload.qml", actions: "BoxActions.qml" })[box.tab]
    }
}
