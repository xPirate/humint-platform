import QtQuick
import Humint
import ".."

// The case file is locked: the PIN opens it.
Rectangle {
    id: root
    color: Theme.bg
    readonly property var st: Box.state || ({})
    property string note: ""
    property bool busy: false
    StatusStrip { anchors.top: parent.top; width: parent.width }
    PinPad {
        id: pad
        anchors.fill: parent
        anchors.topMargin: 52 * Theme.s
        title: "Unlock the case file"
        detail: root.st.tries_left < 5 ? root.st.tries_left + " tries left before the machine refuses" : ""
        note: root.note
        busy: root.busy
        submitText: "Unlock"
        onSubmitted: function(pin) {
            root.busy = true; root.note = ""
            Net.box("unlock", { pin: pin }).then(function(r) {
                root.busy = false
                if (r.result === "unlocked") ui.toast("Unlocked — the console is starting")
                else if (r.result === "wrong") root.note = "Wrong PIN — " + r.tries_left + " tries left"
                else if (r.result === "locked_out") root.note = "Too many wrong PINs"
                else root.note = "Could not unlock (" + r.rc + ")"
            }).catch(function(e) { root.busy = false; root.note = e.message })
        }
    }
}
