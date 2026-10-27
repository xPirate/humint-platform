import QtQuick

// A small coloured label: a status, a record type, a criticality.
Rectangle {
    id: pill
    property string text: ""
    property color tone: Theme.muted
    property bool filled: false
    implicitWidth: label.implicitWidth + 14 * Theme.s
    implicitHeight: label.implicitHeight + 6 * Theme.s
    radius: Theme.radius
    color: filled ? tone : Qt.rgba(tone.r, tone.g, tone.b, Theme.light ? 0.12 : 0.16)
    border.color: Qt.rgba(tone.r, tone.g, tone.b, 0.55)
    border.width: Math.max(1, Theme.s)
    Text {
        id: label
        anchors.centerIn: parent
        text: pill.text
        color: pill.filled ? Theme.onAccent : pill.tone
        font.family: Theme.ui
        font.pixelSize: Theme.fsLabel
        font.weight: Font.DemiBold
        font.capitalization: Theme.caps ? Font.AllUppercase : Font.MixedCase
        font.letterSpacing: Theme.caps ? 0.05 * Theme.fsLabel : 0
    }
}
