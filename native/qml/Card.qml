import QtQuick

// A titled panel.
Rectangle {
    id: card
    property string title: ""
    default property alias content: inner.data
    property real padding: Theme.pad
    color: Theme.panel
    radius: Theme.radius * 1.4
    border.color: Theme.border
    border.width: Math.max(1, Theme.s)
    implicitHeight: inner.childrenRect.height + (title ? head.height + Theme.gap : 0) + padding * 2
    Txt {
        id: head
        visible: card.title !== ""
        x: card.padding; y: card.padding
        width: card.width - card.padding * 2
        kind: "label"
        text: card.title
        wrapMode: Text.NoWrap
    }
    Item {
        id: inner
        x: card.padding
        y: card.padding + (card.title ? head.height + Theme.gap : 0)
        width: card.width - card.padding * 2
        height: card.height - y - card.padding
    }
}
