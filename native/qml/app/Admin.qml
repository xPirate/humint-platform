import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Humint
import ".."

// The console's Admin page, section by section.
Rectangle {
    id: admin
    color: Theme.bg
    property string section: "users"
    readonly property var sections: [
        ["users", "Users", "AdminUsers.qml"],
        ["devices", "Field devices", "AdminDevices.qml"],
        ["boards", "Boards", "AdminBoards.qml"],
        ["maps", "Maps", "AdminMaps.qml"],
        ["backup", "Backup & restore", "AdminBackup.qml"],
        ["feeds", "RSS feeds", "AdminFeeds.qml"],
        ["model", "Model", "AdminModel.qml"],
        ["brand", "Appearance", "AdminBrand.qml"],
        ["signals", "Link signals", "AdminSignals.qml"],
        ["retention", "Retention", "AdminRetention.qml"],
        ["fieldsync", "Field sync", "AdminFieldSync.qml"]
    ]
    RowLayout {
        anchors.fill: parent
        spacing: 0
        Rectangle {
            Layout.preferredWidth: 200 * Theme.s; Layout.fillHeight: true
            color: Theme.panel
            Column {
                anchors.fill: parent; anchors.margins: 8 * Theme.s
                spacing: 2 * Theme.s
                Txt { kind: "label"; text: "Admin"; leftPadding: 8 * Theme.s; bottomPadding: 6 * Theme.s }
                Repeater {
                    model: admin.sections
                    Btn { width: parent.width; compact: true; text: modelData[1]
                          kind: admin.section === modelData[0] ? "primary" : "ghost"
                          onClicked: admin.section = modelData[0] }
                }
            }
        }
        Loader {
            id: sec
            Layout.fillWidth: true; Layout.fillHeight: true
            property string failed: ""
            source: { var s = admin.sections.filter(function(x) { return x[0] === admin.section })[0]
                      return failed === admin.section ? "Missing.qml" : "../admin/" + s[2] }
            onStatusChanged: if (status === Loader.Error) { var f = admin.section; Qt.callLater(function() { sec.failed = f }) }
        }
    }
}
