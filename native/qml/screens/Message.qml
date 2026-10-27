import QtQuick
import Humint
import ".."

// Whatever first boot or start-up is doing (the lines the Pi's OLED shows).
Rectangle {
    color: Theme.bg
    readonly property var st: Box.state || ({})
    readonly property var lines: (st.message && st.message.lines && st.message.lines.length)
                                 ? st.message.lines : [st.firstboot_done ? "Starting up" : "Setting up"]
    StatusStrip { id: strip; anchors.top: parent.top; width: parent.width }
    Column {
        anchors.centerIn: parent
        width: parent.width - 4 * Theme.pad
        spacing: Theme.gap
        Txt { width: parent.width; kind: "huge"; text: lines[0]; horizontalAlignment: Text.AlignHCenter }
        Repeater {
            model: lines.slice(1, 5)
            Txt { width: parent.width; kind: "muted"; font.pixelSize: Theme.fsTitle; text: modelData
                  horizontalAlignment: Text.AlignHCenter }
        }
        Item { width: 1; height: Theme.gap }
        Spinner { anchors.horizontalCenter: parent.horizontalCenter }
    }
    Txt {
        visible: !st.firstboot_done
        anchors.bottom: parent.bottom; anchors.bottomMargin: Theme.pad * 2
        width: parent.width; horizontalAlignment: Text.AlignHCenter
        kind: "muted"; text: "First-time setup — this takes a few minutes."
    }
}
