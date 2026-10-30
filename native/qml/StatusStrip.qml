import QtQuick
import QtQuick.Layouts
import Humint

// The machine at a glance, along the top of every screen: its name, the
// network, the battery and the time ("?" until something has confirmed the
// clock this boot, as on the Pi's panel).
Rectangle {
    id: strip
    property var st: Box.state || ({})
    property string title: ""
    property alias leftItems: leftSlot.data
    property alias rightItems: rightSlot.data
    implicitHeight: 52 * Theme.s
    color: Theme.panel2
    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: Math.max(1, Theme.s); color: Theme.border }

    property date now: new Date()
    Timer { interval: 1000; running: true; repeat: true; onTriggered: strip.now = new Date() }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: Theme.pad; anchors.rightMargin: Theme.pad
        spacing: Theme.gap
        Row { id: leftSlot; spacing: Theme.gap; Layout.alignment: Qt.AlignVCenter }
        Txt {
            text: strip.title || (strip.st.name || "HUMINT field server")
            font.weight: Font.DemiBold
            wrapMode: Text.NoWrap
            elide: Text.ElideRight
            Layout.fillWidth: true
        }
        Row { id: rightSlot; spacing: Theme.gap; Layout.alignment: Qt.AlignVCenter }
        // The status: tap it for the machine's controls (QuickSettings).
        Rectangle {
            id: statusBtn
            objectName: "statusButton"
            Layout.alignment: Qt.AlignVCenter
            implicitWidth: statusRow.implicitWidth + 20 * Theme.s
            implicitHeight: 40 * Theme.s
            radius: Theme.radius
            color: statusTap.pressed ? Theme.panel : statusTap.containsMouse ? Qt.lighter(Theme.panel2, 1.15) : "transparent"
            border.color: statusTap.containsMouse ? Theme.border : "transparent"
            Accessible.role: Accessible.Button
            Accessible.name: "Quick settings"
            RowLayout {
                id: statusRow
                anchors.centerIn: parent
                spacing: Theme.gap
                Txt {
                    visible: !!strip.st.net_mode
                    kind: "muted"
                    wrapMode: Text.NoWrap
                    text: strip.st.net_mode === "hotspot"
                          ? "Hotspot " + (strip.st.ssid || "") + (strip.st.clients !== null && strip.st.clients !== undefined
                                                                  ? " · " + strip.st.clients + " joined" : "")
                          : strip.st.net_mode === "wired" ? "Wired " + (strip.st.ip || "")
                          : strip.st.net_mode === "client" ? "Wi-Fi " + (strip.st.ssid || "") + " " + (strip.st.ip || "")
                          : (strip.st.ip || "")
                }
                // Battery: percent and whether the charger is in.
                Row {
                    visible: !!(strip.st.battery && strip.st.battery.present)
                    spacing: 6 * Theme.s
                    Layout.alignment: Qt.AlignVCenter
                    property var b: strip.st.battery || ({})
                    Rectangle {
                        width: 30 * Theme.s; height: 15 * Theme.s; radius: 3 * Theme.s
                        anchors.verticalCenter: parent.verticalCenter
                        color: "transparent"; border.color: Theme.muted; border.width: Math.max(1, 1.5 * Theme.s)
                        Rectangle {
                            x: 2 * Theme.s; y: 2 * Theme.s; height: parent.height - 4 * Theme.s
                            width: Math.max(0, (parent.width - 4 * Theme.s) * Math.min(100, parent.parent.b.percent || 0) / 100)
                            radius: 1.5 * Theme.s
                            color: (parent.parent.b.percent || 0) < 15 && parent.parent.b.on_battery ? Theme.red
                                 : (parent.parent.b.percent || 0) < 35 && parent.parent.b.on_battery ? Theme.amber : Theme.accent
                        }
                    }
                    Txt {
                        wrapMode: Text.NoWrap
                        kind: "muted"
                        text: Math.round(parent.b.percent || 0) + "%" + (parent.b.ac_present ? " ⚡" : "")
                    }
                }
                Txt {
                    wrapMode: Text.NoWrap
                    font.family: "IBM Plex Mono"
                    text: Qt.formatTime(strip.now, "HH:mm") + ((strip.st.clock || {}).source === "unset" ? "?" : "")
                }
                // A small chevron: this opens.
                Txt { kind: "muted"; text: "▾"; wrapMode: Text.NoWrap }
            }
            MouseArea { id: statusTap; anchors.fill: parent; hoverEnabled: true; onClicked: ui.quickSettings() }
        }
    }
}
