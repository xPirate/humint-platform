import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Humint
import ".."
import "../lib/fmt.js" as Fmt

// Phones that may send field reports: enroll one (its code is shown once, to
// scan), show a phone's code again (a new one — the old stops working),
// revoke, delete. The touch panel's codes (Box → Phone upload) can be
// switched off here.
Rectangle {
    id: page
    color: Theme.bg
    property var devices: []
    property var users: []
    property var code: null
    property bool panelCodes: true

    function load() {
        Net.get("/api/field/devices").then(function(r) { page.devices = r.items || [] }).catch(function(e) { ui.toast(e.message, true) })
        Net.get("/api/users").then(function(r) { page.users = (r.items || []).filter(function(u) { return u.is_active && u.role !== "viewer" }) }).catch(function() {})
        Net.get("/api/admin/panel-settings").then(function(r) { page.panelCodes = r.panel_upload_codes }).catch(function() {})
    }
    Component.onCompleted: load()
    readonly property string baseUrl: (Box.state && Box.state.url) || ""

    ColumnLayout {
        anchors.fill: parent; anchors.margins: Theme.pad
        spacing: Theme.gap
        PageHeader {
            Layout.fillWidth: true
            title: "Field devices"
            subtitle: "Phones that may send field reports, which land in the review inbox."
            Btn { compact: true; kind: "primary"; text: "+ Enroll a phone"; onClicked: enroll.open() }
        }
        Check { text: "Let the machine's own screen issue phone codes (Box → Phone upload)"; checked: page.panelCodes
                onToggled: Net.patch("/api/admin/panel-settings", { panel_upload_codes: checked }).catch(function(e) { ui.toast(e.message, true); page.load() }) }
        // A code, shown once
        Rectangle {
            Layout.fillWidth: true
            visible: !!page.code
            implicitHeight: 300 * Theme.s
            radius: Theme.radius * 1.4; color: Theme.panel; border.color: Theme.accentDim
            RowLayout {
                anchors.fill: parent; anchors.margins: Theme.pad
                spacing: Theme.gap * 2
                Rectangle { Layout.preferredWidth: 260 * Theme.s; Layout.preferredHeight: 260 * Theme.s; color: "white"; radius: Theme.radius
                    Image { anchors.fill: parent; anchors.margins: 10 * Theme.s; smooth: false; fillMode: Image.PreserveAspectFit
                            source: page.code ? "image://qr/" + encodeURIComponent(JSON.stringify(page.code.enrollment)) : "" } }
                Column {
                    Layout.fillWidth: true; spacing: 8 * Theme.s
                    Txt { width: parent.width; kind: "title"; text: page.code ? page.code.enrollment.label : "" }
                    Txt { width: parent.width; text: "In the HUMINT field app: Upload → Scan code. Shown once — Show code again makes a new one." }
                    Btn { kind: "primary"; text: "Done"; onClicked: page.code = null }
                }
            }
        }
        ListView {
            Layout.fillWidth: true; Layout.fillHeight: true
            clip: true; spacing: 8 * Theme.s
            model: page.devices
            ScrollBar.vertical: ScrollBar {}
            delegate: Rectangle {
                width: ListView.view.width
                implicitHeight: drow.implicitHeight + 24 * Theme.s
                radius: Theme.radius; color: Theme.panel; border.color: Theme.border
                opacity: modelData.revoked ? 0.55 : 1
                RowLayout {
                    id: drow
                    x: 14 * Theme.s; y: 12 * Theme.s; width: parent.width - 28 * Theme.s
                    Column {
                        Layout.fillWidth: true
                        Txt { text: modelData.label + "  ·  " + (modelData.username || ""); font.weight: Font.DemiBold }
                        Txt { kind: "muted"
                              text: (modelData.revoked ? "Revoked · " : "") + modelData.submission_count + " reports · "
                                    + (modelData.last_seen_at ? "last seen " + Fmt.relativeTime(modelData.last_seen_at) : "never synced") }
                    }
                    Btn { compact: true; text: "Show code again"; visible: !modelData.revoked
                          onClicked: Net.post("/api/field/devices/" + modelData.id + "/code", { base_url: page.baseUrl || null }).then(function(r) {
                              page.code = r; page.load() }).catch(function(e) { ui.toast(e.message, true) }) }
                    Btn { compact: true; kind: "danger"; text: "Revoke"; visible: !modelData.revoked
                          onClicked: ui.confirm("Revoke " + modelData.label + "?", "It can no longer send reports. What it already sent stays.", function() {
                              Net.post("/api/field/devices/" + modelData.id + "/revoke", {}).then(page.load).catch(function(e) { ui.toast(e.message, true) }) }) }
                    Btn { compact: true; kind: "ghost"; text: "Delete"; visible: modelData.revoked
                          onClicked: Net.del("/api/field/devices/" + modelData.id).then(page.load).catch(function(e) { ui.toast(e.message, true) }) }
                }
            }
        }
    }

    FormDialog {
        id: enroll
        title: "Enroll a phone"
        okText: "Make its code"
        onOpened: { label.text = ""; who.value = Net.me ? String(Net.me.id) : "" }
        onAccepted: {
            busy = true
            Net.post("/api/field/devices", { label: label.text.trim(), user_id: Number(who.value), base_url: page.baseUrl || null }).then(function(r) {
                busy = false; close(); page.code = r; page.load()
            }).catch(function(e) { busy = false; error = e.message })
        }
        Labeled { label: "Which phone"; Field { id: label; width: parent.width; placeholderText: "Ana's Pixel" } }
        Labeled { label: "Whose"; Select { id: who; width: parent.width
                                           options: page.users.map(function(u) { return [String(u.id), u.username] }) } }
    }
}
