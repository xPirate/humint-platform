import QtQuick
import Humint
import ".."

// Too many wrong PINs: the machine will not try again until restarted.
Rectangle {
    color: Theme.bg
    StatusStrip { anchors.top: parent.top; width: parent.width }
    Column {
        anchors.centerIn: parent
        width: Math.min(parent.width - 4 * Theme.pad, 620 * Theme.s)
        spacing: Theme.gap * 1.5
        Txt { width: parent.width; kind: "huge"; text: "Locked"; color: Theme.red; horizontalAlignment: Text.AlignHCenter }
        Txt { width: parent.width; horizontalAlignment: Text.AlignHCenter
              text: "Too many wrong PINs. Restart the machine to try again." }
        Btn {
            anchors.horizontalCenter: parent.horizontalCenter
            text: "Restart"
            onClicked: ui.confirm("Restart the machine?", "", function() {
                ui.busy("Restarting…"); Net.box("ctl", { action: "reboot", args: [] })
            }, false)
        }
    }
}
