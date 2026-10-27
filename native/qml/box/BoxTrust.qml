import QtQuick
import QtQuick.Layouts
import Humint
import ".."

// The certificate each phone and laptop installs once, and its fingerprint
// to check against what the device shows.
RowLayout {
    readonly property var st: Box.state || ({})
    spacing: Theme.gap * 2
    Card {
        Layout.fillWidth: true; Layout.fillHeight: true
        title: "Install the certificate"
        Column {
            width: parent.width; spacing: Theme.gap
            Rectangle {
                anchors.horizontalCenter: parent.horizontalCenter
                width: Math.min(parent.width, 300 * Theme.s); height: width; color: "white"; radius: Theme.radius
                Image { anchors.fill: parent; anchors.margins: 10 * Theme.s; smooth: false
                        fillMode: Image.PreserveAspectFit
                        source: st.trust_url ? "image://qr/" + encodeURIComponent(st.trust_url) : "" }
            }
            Txt { width: parent.width; horizontalAlignment: Text.AlignHCenter; kind: "mono"; color: Theme.accent
                  font.pixelSize: 20 * Theme.s; text: st.trust_url || "" }
        }
    }
    Card {
        Layout.fillWidth: true; Layout.fillHeight: true
        title: "Check its fingerprint"
        Column {
            width: parent.width; spacing: Theme.gap
            Txt { width: parent.width; kind: "muted"
                  text: "When a device asks whether to trust the certificate, it shows a fingerprint. It must match this exactly; if it does not, do not install it." }
            Txt { width: parent.width; kind: "mono"; font.pixelSize: 17 * Theme.s
                  text: (st.fingerprint || "not issued yet").replace(/:/g, ":​") }
        }
    }
}
