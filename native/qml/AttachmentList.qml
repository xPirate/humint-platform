import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Humint
import "lib/fmt.js" as Fmt

// A record's or report's files: a thumbnail for images, a type label for the
// rest; tap to look. Delete for those allowed.
Column {
    id: al
    property var items: []
    property bool canDelete: false
    signal changed()
    spacing: 6 * Theme.s

    function isImage(a) { return /^image\/(png|jpe?g|gif|webp|bmp)$/i.test(a.mime_type || "") }
    function typeLabel(a) {
        var ext = (a.filename || "").split(".").pop().toUpperCase()
        return ext.length <= 4 ? ext : "FILE"
    }

    Txt { visible: al.items.length === 0; kind: "muted"; text: "None yet." }
    Repeater {
        model: al.items
        delegate: Rectangle {
            width: al.width
            height: 64 * Theme.s
            radius: Theme.radius
            color: Theme.panel2
            border.color: Theme.border
            RowLayout {
                anchors.fill: parent; anchors.margins: 8 * Theme.s
                spacing: Theme.gap
                Rectangle {
                    Layout.preferredWidth: 48 * Theme.s; Layout.preferredHeight: 48 * Theme.s
                    radius: Theme.radius; color: Theme.panel; border.color: Theme.border; clip: true
                    Image {
                        anchors.fill: parent
                        visible: al.isImage(modelData)
                        source: al.isImage(modelData) ? "image://api/api/attachments/" + modelData.id + "/file?inline=1" : ""
                        sourceSize.width: 96; sourceSize.height: 96
                        fillMode: Image.PreserveAspectCrop; asynchronous: true
                    }
                    Txt { anchors.centerIn: parent; visible: !al.isImage(modelData); kind: "label"; text: al.typeLabel(modelData) }
                }
                Column {
                    Layout.fillWidth: true
                    Txt { width: parent.width; text: modelData.filename; wrapMode: Text.NoWrap; elide: Text.ElideMiddle }
                    Txt { width: parent.width; kind: "muted"; wrapMode: Text.NoWrap
                          text: [Fmt.fileSize(modelData.file_size_bytes),
                                 modelData.uploaded_at ? "uploaded " + Fmt.relativeTime(modelData.uploaded_at) : "",
                                 modelData.extraction_status || ""].filter(function(x) { return x }).join(" · ") }
                }
                Btn { compact: true; text: "Open"; onClicked: fileViewer.show(modelData) }
                Btn { compact: true; kind: "danger"; text: "Delete"; visible: al.canDelete
                      onClicked: ui.confirm("Delete this attachment?", modelData.filename, function() {
                          Net.del("/api/attachments/" + modelData.id).then(function() { ui.toast("Deleted"); al.changed() })
                              .catch(function(e) { ui.toast(e.message, true) })
                      }) }
            }
        }
    }
}
