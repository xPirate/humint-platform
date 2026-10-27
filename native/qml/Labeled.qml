import QtQuick

// A form field with its label above and an optional hint below.
Column {
    property string label: ""
    property string hint: ""
    default property alias field: slot.data
    width: parent ? parent.width : 300
    spacing: 4 * Theme.s
    Txt { width: parent.width; kind: "label"; text: parent.label; visible: text !== "" }
    Item { id: slot; width: parent.width; height: childrenRect.height }
    Txt { width: parent.width; kind: "muted"; text: parent.hint; visible: text !== "" }
}
