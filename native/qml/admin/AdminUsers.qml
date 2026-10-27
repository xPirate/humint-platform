import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Humint
import ".."
import "../lib/fmt.js" as Fmt

// Accounts: create, set the role, reset a password or two-factor, deactivate.
// Whether everyone must use two-factor sign-in.
Rectangle {
    id: page
    color: Theme.bg
    property var users: []
    property bool require2fa: false

    function load() {
        Net.get("/api/users").then(function(r) { page.users = r.items || r || [] }).catch(function(e) { ui.toast(e.message, true) })
        Net.get("/api/admin/security-settings").then(function(r) { page.require2fa = !!r.require_2fa }).catch(function() {})
    }
    Component.onCompleted: load()
    function locked(u) { return u.locked_until && new Date(u.locked_until) > new Date() }

    ColumnLayout {
        anchors.fill: parent; anchors.margins: Theme.pad
        spacing: Theme.gap
        PageHeader {
            Layout.fillWidth: true
            title: "Users"
            subtitle: "There must always be one active admin."
            Btn { compact: true; kind: "primary"; text: "+ New user"; onClicked: newUser.open() }
        }
        Check { text: "Require two-factor sign-in for every account"; checked: page.require2fa
                onToggled: Net.patch("/api/admin/security-settings", { require_2fa: checked }).then(function() {
                    ui.toast(checked ? "Two-factor is now required" : "Two-factor is optional") }).catch(function(e) { ui.toast(e.message, true); page.load() }) }
        ListView {
            Layout.fillWidth: true; Layout.fillHeight: true
            clip: true; spacing: 8 * Theme.s
            model: page.users
            ScrollBar.vertical: ScrollBar {}
            delegate: Rectangle {
                width: ListView.view.width
                implicitHeight: urow.implicitHeight + 2 * 12 * Theme.s
                radius: Theme.radius; color: Theme.panel; border.color: Theme.border
                opacity: modelData.is_active ? 1 : 0.6
                RowLayout {
                    id: urow
                    x: 14 * Theme.s; y: 12 * Theme.s; width: parent.width - 28 * Theme.s
                    spacing: 8 * Theme.s
                    Column {
                        Layout.fillWidth: true
                        Txt { text: modelData.username + (Net.me && modelData.id === Net.me.id ? "  (you)" : ""); font.weight: Font.DemiBold }
                        Txt { kind: "muted"
                              text: (modelData.is_active ? "" : "Deactivated · ") + (page.locked(modelData) ? "Locked out (too many failed logins) · " : "")
                                    + (modelData.totp_enabled_at ? "Two-factor on · " : "") + "Created " + Fmt.relativeTime(modelData.created_at) }
                    }
                    Select { value: modelData.role
                             options: [["analyst", "Analyst"], ["admin", "Admin"], ["viewer", "Read-only"]]
                             onPicked: function(v) { Net.patch("/api/users/" + modelData.id, { role: v }).then(function() { ui.toast("Role changed"); page.load() })
                                                         .catch(function(e) { ui.toast(e.message, true); page.load() }) } }
                    Btn { compact: true; text: "Reset password"; onClicked: resetPw.open(modelData) }
                    Btn { compact: true; text: "Reset two-factor"; visible: !!modelData.totp_enabled_at
                          onClicked: ui.confirm("Reset two-factor sign-in for " + modelData.username + "?", "They are signed out everywhere.", function() {
                              Net.post("/api/admin/users/" + modelData.id + "/2fa/reset", {}).then(function() { ui.toast("Two-factor reset"); page.load() })
                                  .catch(function(e) { ui.toast(e.message, true) }) }) }
                    Btn { compact: true; kind: modelData.is_active ? "danger" : "normal"; text: modelData.is_active ? "Deactivate" : "Reactivate"
                          onClicked: Net.patch("/api/users/" + modelData.id, { is_active: !modelData.is_active }).then(page.load)
                                         .catch(function(e) { ui.toast(e.message, true) }) }
                }
            }
        }
    }

    FormDialog {
        id: newUser
        title: "New user"
        okText: "Create"
        onOpened: { nuName.text = ""; nuPw.text = ""; nuRole.value = "analyst" }
        onAccepted: {
            busy = true
            Net.post("/api/auth/register", { username: nuName.text.trim(), password: nuPw.text, role: nuRole.value })
                .then(function() { busy = false; close(); ui.toast("Account created"); page.load() })
                .catch(function(e) { busy = false; error = e.message })
        }
        Labeled { label: "Username"; Field { id: nuName; width: parent.width; inputMethodHints: Qt.ImhNoAutoUppercase } }
        Labeled { label: "Password"; hint: "At least 10 characters. Tell them in person; they can turn on two-factor themselves."
                  Field { id: nuPw; width: parent.width; echoMode: TextInput.Password } }
        Labeled { label: "Role"; Select { id: nuRole; width: parent.width; value: "analyst"
                                          options: [["analyst", "Analyst"], ["admin", "Admin"], ["viewer", "Read-only"]] } }
    }
    FormDialog {
        id: resetPw
        property var u: null
        title: "New password for " + (u ? u.username : "")
        okText: "Set password"
        function open(x) { u = x; rpw.text = ""; visible = true }
        onAccepted: {
            busy = true
            Net.post("/api/users/" + u.id + "/password", { password: rpw.text }).then(function() {
                busy = false; close(); ui.toast("Password set") }).catch(function(e) { busy = false; error = e.message })
        }
        Labeled { label: "Password"; hint: "At least 10 characters."; Field { id: rpw; width: parent.width; echoMode: TextInput.Password } }
    }
}
