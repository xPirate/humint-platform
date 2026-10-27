import QtQuick
import Humint
import ".."

// First boot asks for the PIN to set (twice), or for an existing store's
// PIN; Box → Duress PIN asks for that one the same way.
Rectangle {
    id: root
    color: Theme.bg
    readonly property var st: Box.state || ({})
    readonly property string stage: st.pin_setup || "new"
    property string first: ""
    property string note: ""
    property bool busy: false
    readonly property int minLength: 4

    StatusStrip { anchors.top: parent.top; width: parent.width
                  title: stage === "duress" ? "Duress PIN" : "First-time setup" }
    PinPad {
        anchors.fill: parent
        anchors.topMargin: 52 * Theme.s
        busy: root.busy
        cancellable: root.stage === "duress"
        note: root.note
        noteColor: root.note.indexOf("match") >= 0 || root.note.indexOf("least") >= 0 ? Theme.amber : Theme.muted
        title: root.stage === "existing" ? "Enter the case file's PIN"
             : root.first === "" ? (root.stage === "duress" ? "Choose a duress PIN" : "Choose the unlock PIN")
             : "Type it again"
        detail: root.stage === "existing"
                ? "This machine already has an encrypted case file. Its PIN opens it."
                : root.stage === "duress"
                  ? "Typed at unlock instead of the real PIN, it erases the case file and opens an empty one."
                  : root.first === ""
                    ? "You will type this every time the machine starts. At least " + root.minLength
                      + " characters; longer is stronger. It cannot be recovered."
                    : ""
        submitText: root.stage === "existing" ? "Open" : root.first === "" ? "Next" : "Set PIN"
        onCancelled: { root.first = ""; Net.box("setup_pin_cancel", {}) }
        onSubmitted: function(pin) {
            if (root.stage !== "existing") {
                if (root.first === "") {
                    if (pin.length < root.minLength) { root.note = "Use at least " + root.minLength + " characters"; return }
                    root.first = pin; root.note = ""; return
                }
                if (pin !== root.first) { root.first = ""; root.note = "They didn't match — start again"; return }
            }
            root.busy = true; root.note = ""
            var stage = root.stage
            Net.box("setup_pin", { pin: pin }).then(function() {
                root.busy = false; root.first = ""
                if (stage === "new") ui.toast("PIN set — setting up the case file")
            }).catch(function(e) { root.busy = false; root.first = ""; root.note = e.message })
        }
    }
}
