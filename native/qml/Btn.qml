import QtQuick
import QtQuick.Controls

// A button. kind: "normal" | "primary" | "danger" | "ghost". `sub` is an
// optional second, smaller line.
AbstractButton {
    id: b
    property string kind: "normal"
    property string sub: ""
    property real minWidth: 96 * Theme.s
    property bool compact: false
    focusPolicy: Qt.StrongFocus
    hoverEnabled: true
    implicitHeight: Math.max(compact ? 36 * Theme.s : Theme.touch, contentItem.implicitHeight + (compact ? 10 : 18) * Theme.s)
    implicitWidth: Math.max(minWidth, contentItem.implicitWidth + (compact ? 22 : 36) * Theme.s)
    opacity: enabled ? 1 : 0.4

    readonly property color fill: kind === "primary" ? Theme.accentDim
                                : kind === "danger" ? Qt.darker(Theme.red, Theme.light ? 1.0 : 2.6)
                                : kind === "ghost" ? "transparent" : Theme.panel2
    readonly property color ink: kind === "primary" ? Theme.onAccent
                               : kind === "danger" ? (Theme.light ? Theme.onDanger : Theme.red)
                               : kind === "ghost" ? Theme.accent : Theme.text

    background: Rectangle {
        radius: Theme.radius
        color: b.down ? Qt.darker(b.fill, 1.25) : (b.hovered && b.kind !== "ghost" ? Qt.lighter(b.fill, 1.12) : b.fill)
        border.width: b.kind === "ghost" ? 0 : Math.max(1, Theme.s)
        border.color: b.activeFocus ? Theme.accent
                    : b.kind === "danger" ? Qt.darker(Theme.red, Theme.light ? 1 : 1.6)
                    : b.kind === "primary" ? Theme.accentDim : Theme.border
    }
    contentItem: Item {
        implicitWidth: Math.max(label.implicitWidth, subLabel.visible ? subLabel.implicitWidth : 0)
        implicitHeight: label.implicitHeight + (subLabel.visible ? subLabel.implicitHeight + 2 * Theme.s : 0)
        Column {
            anchors.centerIn: parent
            spacing: 2 * Theme.s
            Text {
                id: label
                anchors.horizontalCenter: parent.horizontalCenter
                width: Math.min(implicitWidth, b.availableWidth)
                horizontalAlignment: Text.AlignHCenter
                text: b.text
                color: b.ink
                font.family: Theme.ui
                font.pixelSize: b.compact ? Theme.fsSmall : Theme.fs
                font.weight: Font.DemiBold
                elide: Text.ElideRight
            }
            Text {
                id: subLabel
                visible: b.sub !== ""
                anchors.horizontalCenter: parent.horizontalCenter
                width: Math.min(implicitWidth, b.availableWidth)
                horizontalAlignment: Text.AlignHCenter
                text: b.sub
                color: b.kind === "primary" ? b.ink : Theme.muted
                font.family: Theme.ui
                font.pixelSize: Theme.fsSmall
                elide: Text.ElideRight
            }
        }
    }
    Keys.onReturnPressed: clicked()
    Keys.onEnterPressed: clicked()
}
