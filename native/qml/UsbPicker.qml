import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Qt.labs.folderlistmodel
import Humint

// USB sticks: choose a file to bring in, or save a file out. The machine's
// helper mounts them (no programs on a stick can run) and ejects them.
//   usb.pickFile(function(path) {...})
//   usb.exportFile("/api/reports/42/export.pdf", "report-42.pdf")
Rectangle {
    id: u
    anchors.fill: parent
    visible: mode !== ""
    color: Theme.scrim
    property string mode: ""          // "" | pick | save
    property var sticks: []
    property var stick: null
    property string folder: ""
    property var onPicked: null
    property string apiPath: ""
    property string fileName: ""
    property bool busy: false

    function refresh() {
        u.busy = true
        Net.box("usb_list", {}).then(function(r) {
            u.busy = false; u.sticks = r.sticks || []
            if (u.sticks.length === 1 && !u.stick) u.openStick(u.sticks[0])
        }).catch(function(e) { u.busy = false; ui.toast(e.message, true) })
    }
    function pickFile(cb) { u.mode = "pick"; u.onPicked = cb; u.stick = null; u.refresh() }
    function exportFile(path, name) { u.mode = "save"; u.apiPath = path; u.fileName = name; u.stick = null; u.refresh() }
    function openStick(s) { u.stick = s; u.folder = "file://" + s.path }
    function close() { u.mode = ""; u.stick = null; u.onPicked = null }
    function eject() {
        Net.box("usb_eject", {}).then(function() { ui.toast("Safe to remove the stick"); u.close() })
            .catch(function(e) { ui.toast(e.message, true) })
    }
    function save() {
        var dir = u.stick.fstype && u.stick.fstype.indexOf("ext") === 0 ? u.stick.path + "/HUMINT" : u.stick.path
        var target = dir + "/" + u.fileName
        u.busy = true
        Net.download(u.apiPath, target).then(function() {
            u.busy = false
            ui.toast("Saved " + u.fileName + " to " + u.stick.label + " — eject before removing it")
        }).catch(function(e) { u.busy = false; ui.toast(e.message, true) })
    }

    FolderListModel {
        id: files
        folder: u.folder
        showDirsFirst: true
        showHidden: false
        nameFilters: ["*"]
    }

    MouseArea { anchors.fill: parent; onClicked: u.close() }
    Rectangle {
        anchors.centerIn: parent
        width: Math.min(parent.width - 2 * Theme.pad, 820 * Theme.s)
        height: Math.min(parent.height - 2 * Theme.pad, 640 * Theme.s)
        radius: Theme.radius * 1.5
        color: Theme.panel
        border.color: Theme.borderStrong
        MouseArea { anchors.fill: parent }
        ColumnLayout {
            anchors.fill: parent; anchors.margins: Theme.pad * 1.5
            spacing: Theme.gap
            RowLayout {
                Layout.fillWidth: true
                Txt { Layout.fillWidth: true; kind: "title"
                      text: u.mode === "save" ? "Save " + u.fileName + " to a USB stick" : "Choose a file on a USB stick" }
                Btn { compact: true; text: "Eject"; visible: u.sticks.length > 0; onClicked: u.eject() }
                Btn { compact: true; text: "Close"; onClicked: u.close() }
            }
            // No stick, or which stick
            Txt { visible: !u.busy && u.sticks.length === 0; kind: "muted"
                  text: "No USB stick found. Plug one in, then look again." }
            Btn { visible: !u.busy && u.sticks.length === 0; text: "Look again"; onClicked: u.refresh() }
            Flow {
                Layout.fillWidth: true
                visible: u.sticks.length > 1
                spacing: 8 * Theme.s
                Repeater { model: u.sticks
                           Btn { compact: true; text: modelData.label; kind: u.stick && u.stick.path === modelData.path ? "primary" : "normal"
                                 onClicked: u.openStick(modelData) } }
            }
            // Saving: one button.
            Column {
                visible: u.mode === "save" && !!u.stick
                Layout.fillWidth: true
                spacing: Theme.gap
                Txt { width: parent.width; kind: "muted"
                      text: u.stick ? (u.stick.writable ? "It goes in the top folder of " + u.stick.label + "."
                                                        : u.stick.label + " can't be written to (it may be locked).") : "" }
                Btn { kind: "primary"; text: u.busy ? "Saving…" : "Save to " + (u.stick ? u.stick.label : "")
                      enabled: !!u.stick && u.stick.writable && !u.busy; onClicked: u.save() }
            }
            // Picking: browse the stick.
            RowLayout {
                visible: u.mode === "pick" && !!u.stick
                Layout.fillWidth: true
                Btn { compact: true; text: "↑ Up"
                      enabled: !!u.stick && u.folder !== "file://" + u.stick.path
                      onClicked: u.folder = files.parentFolder }
                Txt { Layout.fillWidth: true; kind: "muted"; wrapMode: Text.NoWrap; elide: Text.ElideLeft
                      text: u.stick ? u.folder.replace("file://" + u.stick.path, u.stick.label) : "" }
            }
            ListView {
                visible: u.mode === "pick" && !!u.stick
                Layout.fillWidth: true; Layout.fillHeight: true
                clip: true
                model: files
                spacing: 4 * Theme.s
                ScrollBar.vertical: ScrollBar {}
                delegate: Btn {
                    width: ListView.view.width
                    compact: true
                    text: (fileIsDir ? "📁  " : "") + fileName
                    sub: fileIsDir ? "" : (fileSize < 1048576 ? Math.round(fileSize / 1024) + " KB" : (fileSize / 1048576).toFixed(1) + " MB")
                    onClicked: {
                        if (fileIsDir) { u.folder = "file://" + filePath; return }
                        var cb = u.onPicked
                        var p = filePath
                        u.close()
                        if (cb) cb(p)
                    }
                }
            }
            Item { Layout.fillHeight: true; visible: u.mode !== "pick" || !u.stick }
        }
    }
}
