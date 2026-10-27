import QtQuick
import QtQuick.Controls

// A text field in the app's style.
TextField {
    id: f
    property bool mono: false
    color: Theme.text
    placeholderTextColor: Theme.muted
    selectionColor: Theme.accentDim
    selectedTextColor: Theme.onAccent
    font.family: mono ? "IBM Plex Mono" : Theme.ui
    font.pixelSize: Theme.fs
    leftPadding: 12 * Theme.s; rightPadding: 12 * Theme.s
    topPadding: 10 * Theme.s; bottomPadding: 10 * Theme.s
    implicitHeight: Theme.touch
    background: Rectangle {
        radius: Theme.radius
        color: Theme.panel2
        border.width: Math.max(1, Theme.s)
        border.color: f.activeFocus ? Theme.accent : Theme.border
    }
}
