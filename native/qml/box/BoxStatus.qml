import QtQuick
import QtQuick.Layouts
import Humint
import ".."

// The machine at a glance: address, network, power, services, storage.
Flickable {
    id: page
    readonly property var st: Box.state || ({})
    readonly property var b: st.battery || ({})
    contentHeight: grid.implicitHeight
    clip: true
  GridLayout {
    id: grid
    width: page.width
    columns: width > 900 * Theme.s ? 3 : 2
    columnSpacing: Theme.gap; rowSpacing: Theme.gap

    Card {
        Layout.fillWidth: true; Layout.fillHeight: true; Layout.preferredHeight: 170 * Theme.s
        title: "Team address"
        Column {
            width: parent.width; spacing: 6 * Theme.s
            Txt { width: parent.width; kind: "mono"; font.pixelSize: 22 * Theme.s; color: Theme.accent
                  text: st.url || "no network address yet" }
            Txt { width: parent.width; kind: "muted"; text: st.local_url || "" }
        }
    }
    Card {
        Layout.fillWidth: true; Layout.fillHeight: true; Layout.preferredHeight: 170 * Theme.s
        title: "Network"
        Column {
            width: parent.width; spacing: 6 * Theme.s
            Txt { width: parent.width; font.pixelSize: 20 * Theme.s; font.weight: Font.DemiBold
                  text: st.net_mode === "hotspot" ? "Hotspot “" + (st.ssid || "") + "”"
                      : st.net_mode === "client" ? "Wi-Fi “" + (st.ssid || "") + "”"
                      : st.net_mode === "wired" ? "Wired" : (st.net_mode || "") }
            Txt { width: parent.width; kind: "muted"
                  text: st.net_mode === "hotspot" ? (st.clients || 0) + " devices joined" : (st.ip || "") }
            Txt { width: parent.width; color: Theme.amber; wrapMode: Text.Wrap; visible: !!st.net_fallback
                  text: "Wi-Fi did not work (" + (st.net_fallback || "") + ")" }
        }
    }
    Card {
        Layout.fillWidth: true; Layout.fillHeight: true; Layout.preferredHeight: 170 * Theme.s
        title: b.present ? "Battery" : "Power"
        Column {
            width: parent.width; spacing: 6 * Theme.s
            Txt { width: parent.width; font.pixelSize: 30 * Theme.s; font.weight: Font.DemiBold
                  color: b.present && b.on_battery && b.percent < 15 ? Theme.red
                       : b.present && b.on_battery && b.percent < 35 ? Theme.amber : Theme.accent
                  text: b.present ? Math.round(b.percent || 0) + "%" : "External power" }
            Txt { width: parent.width; kind: "muted"
                  text: !b.present ? "no battery found"
                      : b.ac_present ? (b.charging ? "plugged in · charging" : "plugged in")
                      : b.on_battery ? ("on battery" + (b.minutes_left !== undefined
                                        ? " · ~" + Math.floor(b.minutes_left / 60) + "h "
                                          + ("0" + (b.minutes_left % 60)).slice(-2) + "m left" : ""))
                      : "power source unknown" }
            Repeater {
                model: (b.batteries && b.batteries.length > 1) ? b.batteries : []
                Txt { kind: "muted"; text: modelData.name + ": " + Math.round(modelData.percent || 0) + "% (" + modelData.status + ")" }
            }
        }
    }
    Card {
        Layout.fillWidth: true; Layout.fillHeight: true; Layout.preferredHeight: 170 * Theme.s
        title: "Services"
        Column {
            width: parent.width; spacing: 4 * Theme.s
            Repeater {
                model: st.services || []
                Row {
                    spacing: 8 * Theme.s
                    Rectangle { width: 10 * Theme.s; height: width; radius: width / 2
                                anchors.verticalCenter: parent.verticalCenter
                                color: modelData[1] === "active" ? Theme.accent : modelData[1] === "activating" ? Theme.amber : Theme.red }
                    Txt { text: modelData[0] + "  " ; wrapMode: Text.NoWrap }
                    Txt { kind: "muted"; text: modelData[1]; wrapMode: Text.NoWrap }
                }
            }
        }
    }
    Card {
        Layout.fillWidth: true; Layout.fillHeight: true; Layout.preferredHeight: 170 * Theme.s
        title: "Case file storage"
        Txt { width: parent.width; font.pixelSize: 20 * Theme.s
              text: st.disk ? st.disk[0] + " GB free of " + st.disk[1] + " GB" : "—" }
    }
    Card {
        Layout.fillWidth: true; Layout.fillHeight: true; Layout.preferredHeight: 170 * Theme.s
        title: "This machine"
        Column {
            width: parent.width; spacing: 4 * Theme.s
            Txt { kind: "muted"; text: "Up " + (st.uptime || "?") + (st.temp ? " · " + Math.round(st.temp) + "°C" : "") }
            Txt { kind: "muted"; text: "Build " + ((st.build || {}).build || "?") + " (" + ((st.build || {}).commit || "") + ")" }
            Txt { kind: "muted"; text: st.duress_set ? "Duress PIN is set" : "No duress PIN" }
            Txt { visible: (st.clock || {}).source === "unset"; color: Theme.amber
                  width: parent.width
                  text: "Clock not confirmed this boot — it is set when a phone or browser opens the console" }
        }
    }
}
}
