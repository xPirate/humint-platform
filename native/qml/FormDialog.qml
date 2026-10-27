import QtQuick
import QtQuick.Controls

// A dialog over the page: a title, the form, an error line, Cancel / OK.
Popup {
    id: fd
    property string title: ""
    property string okText: "Save"
    property string error: ""
    property bool busy: false
    property bool danger: false
    default property alias content: body.data
    signal accepted()
    parent: Overlay.overlay
    anchors.centerIn: parent
    modal: true
    focus: true
    width: Math.min((parent ? parent.width : 800) - 2 * Theme.pad, 640 * Theme.s)
    height: Math.min((parent ? parent.height : 600) - 2 * Theme.pad, col.implicitHeight + 3 * Theme.pad)
    padding: 1.5 * Theme.pad
    closePolicy: Popup.CloseOnEscape
    Overlay.modal: Rectangle { color: Theme.scrim }
    background: Rectangle { radius: Theme.radius * 1.5; color: Theme.panel; border.color: fd.danger ? Theme.red : Theme.borderStrong }
    onOpened: error = ""
    contentItem: Flickable {
        contentHeight: col.implicitHeight
        clip: true
        Column {
            id: col
            width: parent.width
            spacing: Theme.gap
            Txt { width: parent.width; kind: "title"; text: fd.title }
            Column { id: body; width: parent.width; spacing: Theme.gap }
            Txt { width: parent.width; visible: fd.error !== ""; color: Theme.amber; text: fd.error }
            Row {
                anchors.right: parent.right
                spacing: Theme.gap
                Btn { text: "Cancel"; onClicked: fd.close() }
                Btn { text: fd.busy ? "Working…" : fd.okText; kind: fd.danger ? "danger" : "primary"; enabled: !fd.busy
                      onClicked: fd.accepted() }
            }
        }
    }
}
