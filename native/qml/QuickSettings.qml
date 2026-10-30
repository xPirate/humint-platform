import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Humint

// The machine's own controls, pulled down from the status at the top right of
// every screen (as on a phone or a desktop): brightness, volume, the screen's
// sleep, the network and the battery at a glance, and power.
Popup {
    id: qs
    parent: Overlay.overlay
    x: (parent ? parent.width : 1280) - width - 10 * Theme.s
    y: 56 * Theme.s
    width: Math.min(420 * Theme.s, (parent ? parent.width : 1280) - 20 * Theme.s)
    height: Math.min(col.implicitHeight + 2 * padding, (parent ? parent.height : 800) - y - 10 * Theme.s)
    padding: 16 * Theme.s
    modal: false
    focus: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    background: Rectangle { radius: Theme.radius * 1.5; color: Theme.panel; border.color: Theme.borderStrong }

    readonly property var st: Box.state || ({})
    readonly property var disp: st.display || ({})
    readonly property var aud: st.audio || ({})
    readonly property var bat: st.battery || ({})
    readonly property bool inApp: !!st.unlocked && !!st.firstboot_done

    // A slider in the app's look.
    component Level: Slider {
        id: sl
        from: 0; to: 100; stepSize: 1
        Layout.fillWidth: true
        implicitHeight: Theme.touch
        background: Rectangle {
            x: sl.leftPadding; y: sl.topPadding + sl.availableHeight / 2 - height / 2
            width: sl.availableWidth; height: 8 * Theme.s; radius: height / 2
            color: Theme.panel2; border.color: Theme.border
            Rectangle { width: sl.visualPosition * parent.width; height: parent.height; radius: parent.radius
                        color: sl.enabled ? Theme.accentDim : Theme.border }
        }
        handle: Rectangle {
            x: sl.leftPadding + sl.visualPosition * (sl.availableWidth - width)
            y: sl.topPadding + sl.availableHeight / 2 - height / 2
            width: 26 * Theme.s; height: width; radius: width / 2
            color: sl.pressed ? Theme.accent : Theme.text
            border.color: Theme.accentDim; border.width: Math.max(1, 2 * Theme.s)
        }
    }
    component Head: Txt { kind: "label"; Layout.fillWidth: true }

    // Changes go out at most every 150 ms while a slider moves; the status
    // poll does not move a slider back under the finger.
    property var pending: ({})
    function send(op, args) { pending[op] = args; push.restart() }
    Timer {
        id: push; interval: 150
        onTriggered: {
            var p = qs.pending; qs.pending = ({})
            for (var op in p) Net.box(op, p[op]).catch(function(e) { ui.toast(e.message, true) })
        }
    }

    ColumnLayout {
        id: col
        width: qs.availableWidth
        spacing: 12 * Theme.s

        // ---- brightness ----------------------------------------------------------
        ColumnLayout {
            Layout.fillWidth: true; spacing: 2 * Theme.s
            RowLayout {
                Layout.fillWidth: true
                Head { text: "Brightness" }
                Txt { kind: "muted"; text: qs.disp.backlight ? Math.round(bright.value) + "%" : "set on the screen itself" }
            }
            Level {
                id: bright
                objectName: "brightness"
                enabled: !!qs.disp.backlight
                from: 5
                onMoved: qs.send("display_set", { brightness: Math.round(value) })
            }
            Binding { target: bright; property: "value"; value: qs.disp.brightness || 100
                      when: !bright.pressed && !push.running; restoreMode: Binding.RestoreNone }
        }

        // ---- sound ---------------------------------------------------------------------
        ColumnLayout {
            Layout.fillWidth: true; spacing: 2 * Theme.s
            RowLayout {
                Layout.fillWidth: true
                Head { text: "Volume" }
                Txt { kind: "muted"
                      text: !qs.aud.present ? "no sound card" : qs.aud.muted ? "muted" : Math.round(vol.value) + "%" }
            }
            RowLayout {
                Layout.fillWidth: true; spacing: Theme.gap
                Level {
                    id: vol
                    objectName: "volume"
                    enabled: !!qs.aud.present
                    onMoved: qs.send("audio_set", { volume: Math.round(value), muted: false })
                }
                Binding { target: vol; property: "value"; value: qs.aud.volume || 0
                          when: !vol.pressed && !push.running; restoreMode: Binding.RestoreNone }
                Btn { compact: true; enabled: !!qs.aud.present
                      text: qs.aud.muted ? "Unmute" : "Mute"; kind: qs.aud.muted ? "primary" : "normal"
                      onClicked: Net.box("audio_set", { muted: !qs.aud.muted }).catch(function(e) { ui.toast(e.message, true) }) }
            }
        }

        // ---- the screen sleeping -------------------------------------------------------
        ColumnLayout {
            Layout.fillWidth: true; spacing: 6 * Theme.s
            RowLayout {
                Layout.fillWidth: true
                Head { text: "Screen sleeps after" }
                Btn { compact: true; text: "Sleep now"; onClicked: { qs.close(); Idle.sleepNow() } }
            }
            RowLayout {
                Layout.fillWidth: true; spacing: 5 * Theme.s
                Repeater {
                    model: [[1, "1 m"], [2, "2 m"], [5, "5 m"], [10, "10 m"], [30, "30 m"], [60, "1 h"], [0, "Never"]]
                    Btn { compact: true; minWidth: 0; Layout.fillWidth: true; Layout.preferredWidth: modelData[0] === 0 ? 70 * Theme.s : 48 * Theme.s
                          text: modelData[1]
                          kind: (qs.disp.sleep_minutes === undefined ? 10 : qs.disp.sleep_minutes) === modelData[0] ? "primary" : "normal"
                          onClicked: Net.box("screen_settings", { sleep_minutes: modelData[0] })
                                        .catch(function(e) { ui.toast(e.message, true) }) }
                }
            }
            Check { text: "Sign out of the console when it sleeps"; checked: !!qs.disp.sleep_signout
                    onToggled: Net.box("screen_settings", { sleep_signout: checked })
                                  .catch(function(e) { ui.toast(e.message, true) }) }
        }

        Rectangle { Layout.fillWidth: true; height: Math.max(1, Theme.s); color: Theme.border }

        // ---- network and power, at a glance ----------------------------------------------
        RowLayout {
            Layout.fillWidth: true; spacing: Theme.gap
            ColumnLayout {
                Layout.fillWidth: true; spacing: 0
                Head { text: "Network" }
                Txt { Layout.fillWidth: true; elide: Text.ElideRight
                      text: qs.st.net_mode === "hotspot" ? "Hotspot “" + (qs.st.ssid || "") + "” · " + (qs.st.clients || 0) + " joined"
                          : qs.st.net_mode === "client" ? "Wi-Fi “" + (qs.st.ssid || "") + "”"
                          : qs.st.net_mode === "wired" ? "Wired" : "—" }
                Txt { kind: "muted"; text: qs.st.ip || "no address yet" }
            }
            Btn { compact: true; text: "Network…"; visible: qs.inApp
                  onClicked: { qs.close(); ui.openBox("actions") } }
        }
        RowLayout {
            Layout.fillWidth: true; spacing: Theme.gap
            visible: !!qs.bat.present
            ColumnLayout {
                Layout.fillWidth: true; spacing: 0
                Head { text: "Battery" }
                Txt { text: Math.round(qs.bat.percent || 0) + "%"
                            + (qs.bat.charging ? " · charging" : qs.bat.ac_present ? " · plugged in" : " · on battery")
                            + (qs.bat.minutes_left && qs.bat.on_battery
                               ? " · " + Math.floor(qs.bat.minutes_left / 60) + " h " + (qs.bat.minutes_left % 60) + " min left" : "") }
            }
        }

        Rectangle { Layout.fillWidth: true; height: Math.max(1, Theme.s); color: Theme.border }

        RowLayout {
            Layout.fillWidth: true; spacing: 8 * Theme.s
            Btn { Layout.fillWidth: true; compact: true; text: "Lock"; visible: !!qs.st.unlocked
                  onClicked: { qs.close(); ui.confirm("Lock the case file?",
                      "The console stops for everyone and the PIN is needed to open it again.",
                      function() { ui.busy("Locking…"); Net.box("ctl", { action: "lock", args: [] }).then(function() { ui.busy("") }) }) } }
            Btn { Layout.fillWidth: true; compact: true; text: "Restart"
                  onClicked: { qs.close(); ui.confirm("Restart the machine?", "The case file locks; the PIN opens it again.",
                      function() { ui.busy("Restarting…"); Net.box("ctl", { action: "reboot", args: [] }) }) } }
            Btn { Layout.fillWidth: true; compact: true; text: "Shut down"; kind: "danger"
                  onClicked: { qs.close(); ui.confirm("Shut down?", "Wait for the screen to go dark before unplugging.",
                      function() { ui.busy("Shutting down…"); Net.box("ctl", { action: "shutdown", args: [] }) }) } }
        }
    }
}
