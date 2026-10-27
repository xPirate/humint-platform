import QtQuick
import QtQuick.Controls

// A tappable row in a list: pills on top, a title, a line of detail.
AbstractButton {
    id: lc
    property alias pills: pillRow.data
    property string title: ""
    property string meta: ""
    property string snippet: ""
    property color accent: "transparent"
    text: title          // for screen readers and the tests
    hoverEnabled: true
    implicitHeight: col.implicitHeight + 2 * 12 * Theme.s
    background: Rectangle {
        radius: Theme.radius
        color: lc.down ? Qt.darker(Theme.panel, 1.1) : lc.hovered ? Qt.lighter(Theme.panel, 1.1) : Theme.panel
        border.color: lc.activeFocus ? Theme.accent : Theme.border
        border.width: Math.max(1, Theme.s)
        Rectangle { visible: lc.accent.a > 0; width: 3 * Theme.s; height: parent.height - 2 * Theme.s; y: Theme.s; x: Theme.s
                    color: lc.accent; radius: width }
    }
    contentItem: Item {
        Column {
            id: col
            x: 14 * Theme.s; y: 12 * Theme.s
            width: lc.width - 28 * Theme.s
            spacing: 5 * Theme.s
            Flow { id: pillRow; width: parent.width; spacing: 6 * Theme.s; visible: children.length > 0 }
            Txt { width: parent.width; text: lc.title; font.weight: Font.DemiBold; maximumLineCount: 2; elide: Text.ElideRight }
            Txt { width: parent.width; visible: lc.snippet !== ""; kind: "muted"; text: lc.snippet
                  maximumLineCount: 2; elide: Text.ElideRight; font.family: Theme.prose }
            Txt { width: parent.width; visible: lc.meta !== ""; kind: "muted"; text: lc.meta; wrapMode: Text.NoWrap }
        }
    }
}
