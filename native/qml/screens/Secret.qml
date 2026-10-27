import QtQuick
import Humint
import ".."

// First boot's (or Box → New login's) secrets, until someone confirms they
// are written down: the machine login, and the hotspot password when first
// boot made one up.
Rectangle {
    id: root
    color: Theme.bg
    readonly property var sec: (Box.state || {}).login_secret || ({})
    StatusStrip { anchors.top: parent.top; width: parent.width; title: "Write these down" }
    Column {
        anchors.centerIn: parent
        width: Math.min(parent.width - 4 * Theme.pad, 760 * Theme.s)
        spacing: Theme.gap * 1.5
        Card {
            width: parent.width
            visible: !!root.sec.password
            title: "Machine login (SSH, keyboard) — not the PIN"
            height: implicitHeight
            Txt { width: parent.width; kind: "mono"; font.pixelSize: 30 * Theme.s; color: Theme.accent
                  text: (root.sec.user || "") + "  /  " + (root.sec.password || "") }
        }
        Card {
            width: parent.width
            visible: !!root.sec.ap_psk
            title: "Field Wi-Fi “" + (root.sec.ap_ssid || "") + "” password"
            height: implicitHeight
            Txt { width: parent.width; kind: "mono"; font.pixelSize: 30 * Theme.s; color: Theme.accent
                  text: root.sec.ap_psk || "" }
        }
        Txt {
            width: parent.width; color: Theme.amber; horizontalAlignment: Text.AlignHCenter
            text: "The Wi-Fi password is under Box → Join any time. The login is shown once; "
                  + "Box → New login replaces it."
        }
        Btn {
            anchors.horizontalCenter: parent.horizontalCenter
            kind: "primary"; minWidth: 340 * Theme.s
            text: "I've written it down"
            onClicked: Net.box("dismiss_secret", {})
        }
    }
}
