import QtQuick
import QtQuick.Controls

// A checkbox in the app's style: a box, then its label.
CheckBox {
    id: cb
    spacing: 10 * Theme.s
    padding: 4 * Theme.s
    indicator: Rectangle {
        x: cb.leftPadding; y: (cb.height - height) / 2
        width: 22 * Theme.s; height: width; radius: 3 * Theme.s
        color: cb.checked ? Theme.accentDim : Theme.panel2
        border.color: cb.activeFocus ? Theme.accent : cb.checked ? Theme.accentDim : Theme.borderStrong
        border.width: Math.max(1, 1.5 * Theme.s)
        Text { anchors.centerIn: parent; visible: cb.checked; text: "✓"; color: Theme.onAccent
               font.pixelSize: 16 * Theme.s; font.bold: true }
    }
    contentItem: Txt {
        leftPadding: cb.indicator.width + cb.spacing
        text: cb.text
        verticalAlignment: Text.AlignVCenter
    }
}
