import QtQuick
import QtQuick.Layouts

// A page's title row: optional back button, title, then actions on the right.
RowLayout {
    id: ph
    property string title: ""
    property string subtitle: ""
    property bool back: false
    signal backClicked()
    default property alias actions: actionRow.data
    spacing: Theme.gap
    Btn { visible: ph.back; compact: true; text: "← Back"; onClicked: ph.backClicked() }
    Column {
        Layout.fillWidth: true
        Txt { width: parent.width; kind: "title"; text: ph.title; wrapMode: Text.Wrap }
        Txt { width: parent.width; kind: "muted"; text: ph.subtitle; visible: text !== "" }
    }
    Row { id: actionRow; spacing: 8 * Theme.s; Layout.alignment: Qt.AlignVCenter }
}
