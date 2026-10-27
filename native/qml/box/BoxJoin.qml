import QtQuick
import QtQuick.Layouts
import Humint
import ".."

// How the team gets on: scan to join the Wi-Fi, scan to open the console.
RowLayout {
    readonly property var st: Box.state || ({})
    readonly property bool hot: st.net_mode === "hotspot"
    property bool showPsk: false
    spacing: Theme.gap * 2

    Card {
        Layout.fillWidth: true; Layout.fillHeight: true
        visible: hot && !!st.ssid
        title: "1 · Join the field Wi-Fi"
        Column {
            width: parent.width; spacing: Theme.gap
            Rectangle {
                anchors.horizontalCenter: parent.horizontalCenter
                width: Math.min(parent.width, 300 * Theme.s); height: width; color: "white"; radius: Theme.radius
                Image { anchors.fill: parent; anchors.margins: 10 * Theme.s; smooth: false
                        fillMode: Image.PreserveAspectFit
                        source: "image://qr/" + encodeURIComponent(Util.wifiPayload(st.ssid || "", st.psk || "", !!st.hidden)) }
            }
            Txt { width: parent.width; horizontalAlignment: Text.AlignHCenter; font.pixelSize: 20 * Theme.s
                  text: "“" + (st.ssid || "") + "”" }
            Txt { width: parent.width; horizontalAlignment: Text.AlignHCenter; kind: "mono"
                  text: showPsk ? (st.psk || "") : "●●●●●●●●" }
            Btn { anchors.horizontalCenter: parent.horizontalCenter; compact: true
                  text: showPsk ? "Hide password" : "Show password"; onClicked: showPsk = !showPsk }
        }
    }
    Card {
        Layout.fillWidth: true; Layout.fillHeight: true
        title: (hot ? "2 · " : "") + "Open the console"
        Column {
            width: parent.width; spacing: Theme.gap
            Rectangle {
                anchors.horizontalCenter: parent.horizontalCenter
                visible: !!st.url
                width: Math.min(parent.width, 300 * Theme.s); height: width; color: "white"; radius: Theme.radius
                Image { anchors.fill: parent; anchors.margins: 10 * Theme.s; smooth: false
                        fillMode: Image.PreserveAspectFit
                        source: st.url ? "image://qr/" + encodeURIComponent(st.url) : "" }
            }
            Txt { width: parent.width; horizontalAlignment: Text.AlignHCenter; kind: "mono"
                  font.pixelSize: 20 * Theme.s; color: Theme.accent; text: st.url || "no address yet" }
            Txt { width: parent.width; horizontalAlignment: Text.AlignHCenter; kind: "muted"
                  text: st.tls ? "First time on a device: install the certificate (the Trust tab)." : "" }
        }
    }
}
