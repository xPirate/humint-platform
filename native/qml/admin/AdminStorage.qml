import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Humint
import ".."

// The case file's size, and making it larger. It grows in place, open and in
// use: nothing is copied, nothing stops. It cannot be made smaller. The PIN,
// because extending the encryption needs it (and growing takes disk that
// cannot be had back without a wipe).
Rectangle {
    id: page
    color: Theme.bg
    readonly property var st: Box.state || ({})
    readonly property var store: st.store || null
    readonly property var disk: st.disk || null        // [free GB, total GB] inside the case file
    property bool working: false
    property string error: ""

    readonly property int want: parseInt(size.text, 10)
    readonly property bool valid: !!store && want > store.size_gb && want <= store.max_gb

    function grow() {
        error = ""
        if (!valid) { error = store ? "Choose between " + (store.size_gb + 1) + " and " + store.max_gb + " GB" : "No case file"; return }
        if (!pin.text) { error = "Enter the PIN"; return }
        working = true
        ui.busy("Growing the case file to " + want + " GB…")
        Net.box("store_grow", { size_gb: want, pin: pin.text }).then(function(r) {
            working = false; ui.busy(""); pin.text = ""
            if (r.rc === 0) { ui.toast("The case file is now " + page.want + " GB"); size.text = "" }
            else error = r.error || ("It did not grow (" + r.rc + ")")
        }).catch(function(e) { working = false; ui.busy(""); pin.text = ""; error = e.message })
    }

    ColumnLayout {
        anchors.fill: parent; anchors.margins: Theme.pad
        spacing: Theme.gap
        PageHeader { Layout.fillWidth: true; title: "Storage"
                     subtitle: "Everything in the case — records, files, offline maps — lives in one encrypted file on this machine's disk." }
        Card {
            Layout.fillWidth: true
            title: "The case file"
            implicitHeight: info.implicitHeight + 2 * padding + Theme.gap + 20 * Theme.s
            Column {
                id: info
                width: parent.width; spacing: 6 * Theme.s
                Txt { width: parent.width; font.pixelSize: 26 * Theme.s; font.weight: Font.DemiBold
                      text: page.store ? page.store.size_gb + " GB" : "—" }
                Txt { width: parent.width; kind: "muted"; visible: !!page.disk
                      text: page.disk ? (page.disk[1] - page.disk[0]).toFixed(1) + " GB in use, " + page.disk[0] + " GB free inside it" : "" }
                Txt { width: parent.width; kind: "muted"; visible: !!page.store
                      text: page.store ? (page.store.max_gb > page.store.size_gb
                                          ? "It can grow to " + page.store.max_gb + " GB (4 GB of the disk stays free for updates and logs)."
                                          : "The disk has no room for it to grow.") : "" }
            }
        }
        Card {
            Layout.fillWidth: true
            title: "Make it larger"
            visible: !!page.store && page.store.max_gb > page.store.size_gb
            implicitHeight: g.implicitHeight + 2 * padding + Theme.gap + 20 * Theme.s
            Column {
                id: g
                width: parent.width; spacing: Theme.gap
                Txt { width: parent.width; wrapMode: Text.Wrap
                      text: "It grows in place, while in use — nothing is copied and nobody is signed out. It cannot be made smaller again." }
                Row {
                    spacing: 8 * Theme.s
                    Repeater {
                        model: page.store ? [16, 32, 64].map(function(n) { return page.store.size_gb + n })
                                                       .filter(function(n) { return n < page.store.max_gb }) : []
                        Btn { compact: true; text: modelData + " GB"; onClicked: size.text = String(modelData) }
                    }
                    Btn { compact: true; text: "Largest (" + (page.store ? page.store.max_gb : 0) + " GB)"
                          onClicked: size.text = String(page.store.max_gb) }
                }
                Labeled { label: "New size, GB"
                          Field { id: size; width: 200 * Theme.s; placeholderText: "e.g. " + (page.store ? page.store.size_gb + 32 : 64)
                                  inputMethodHints: Qt.ImhDigitsOnly; validator: IntValidator { bottom: 1; top: 100000 } } }
                Labeled { label: "Unlock PIN"
                          Field { id: pin; width: 200 * Theme.s; echoMode: TextInput.Password; placeholderText: "PIN"
                                  onAccepted: page.grow() } }
                Txt { width: parent.width; visible: page.error !== ""; color: Theme.amber; text: page.error; wrapMode: Text.Wrap }
                Btn { kind: "primary"; enabled: !page.working && page.valid && pin.text !== ""
                      text: page.valid ? "Grow to " + page.want + " GB" : "Grow"
                      onClicked: page.grow() }
            }
        }
        Item { Layout.fillHeight: true }
    }
}
