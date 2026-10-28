import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtCore
import Humint
import ".."
import "../lib/fmt.js" as Fmt

// Everything about you rather than the case: the look (saved to your account,
// so it follows you to the browser), light or dark on this machine,
// two-factor sign-in, signing out.
Rectangle {
    id: page
    color: Theme.bg
    property var tfa: null
    property var enroll: null
    property var codes: []

    function load() { Net.get("/api/auth/2fa").then(function(r) { page.tfa = r }).catch(function() {}) }
    Component.onCompleted: load()

    function setPalette(p) {
        Theme.palette = p
        Net.patch("/api/me/preferences", { preferences: { palette: p } })
            .catch(function(e) { ui.toast("Applied, but not saved to your account: " + e.message, true) })
    }

    Flickable {
        anchors.fill: parent
        contentHeight: col.implicitHeight + 2 * Theme.pad
        clip: true
        ColumnLayout {
            id: col
            x: Theme.pad; y: Theme.pad
            width: Math.min(parent.width - 2 * Theme.pad, 760 * Theme.s)
            spacing: Theme.gap
            PageHeader {
                Layout.fillWidth: true
                title: Net.me ? Net.me.username : ""
                subtitle: Net.me ? "Role: " + Net.me.role : ""
                Btn { compact: true; text: "Your profile"; onClicked: shell.go("analyst", Net.me ? Net.me.username : null) }
                Btn { compact: true; text: "Sign out"
                      // Signed out here whether or not the console answers. (No Promise.finally in Qt's JavaScript.)
                      onClicked: {
                          function out() { Api.signOut(); Net.me = null; Net.signedOut() }
                          Net.post("/api/auth/logout", {}).then(out, out)
                      } }
            }

            Card {
                Layout.fillWidth: true
                title: "Look"
                implicitHeight: lookCol.implicitHeight + 2 * padding + Theme.gap + 20 * Theme.s
                Column {
                    id: lookCol
                    width: parent.width; spacing: Theme.gap
                    Flow {
                        width: parent.width; spacing: 8 * Theme.s
                        Repeater {
                            model: [["terminal", "Terminal"], ["slate", "Slate"], ["graphite", "Graphite"], ["archive", "Archive"]]
                            Btn { compact: true; text: modelData[1]; kind: Theme.palette === modelData[0] ? "primary" : "normal"
                                  onClicked: page.setPalette(modelData[0]) }
                        }
                    }
                    Flow {
                        width: parent.width; spacing: 8 * Theme.s
                        Repeater {
                            model: [[false, "Dark"], [true, "Light"]]
                            Btn { compact: true; text: modelData[1]; kind: Theme.light === modelData[0] ? "primary" : "normal"
                                  onClicked: { Theme.light = modelData[0]; looks.light = modelData[0] } }
                        }
                    }
                    Txt { width: parent.width; kind: "muted"
                          text: "The palette is saved to your account. Light or dark is kept on this machine." }
                }
            }

            Card {
                Layout.fillWidth: true
                title: "Two-factor sign-in"
                implicitHeight: tfaCol.implicitHeight + 2 * padding + Theme.gap + 20 * Theme.s
                Column {
                    id: tfaCol
                    width: parent.width; spacing: Theme.gap
                    Txt { width: parent.width
                          text: !page.tfa ? "…"
                                : page.tfa.enabled ? "On since " + Fmt.exactDate(page.tfa.enabled_at) + ". " + page.tfa.recovery_codes_left + " recovery codes left."
                                : "Off. Signing in takes only your password." + (page.tfa.required ? " Your admin requires it." : "") }
                    // Turning it on
                    Btn { compact: true; visible: !!page.tfa && !page.tfa.enabled && !page.enroll; text: "Turn it on"
                          onClicked: Net.post("/api/auth/2fa/setup", {}).then(function(r) { page.enroll = r }).catch(function(e) { ui.toast(e.message, true) }) }
                    Row {
                        visible: !!page.enroll
                        spacing: Theme.gap
                        Rectangle { width: 200 * Theme.s; height: width; color: "white"; radius: Theme.radius
                            Image { anchors.fill: parent; anchors.margins: 8 * Theme.s; smooth: false; fillMode: Image.PreserveAspectFit
                                    source: page.enroll ? "image://qr/" + encodeURIComponent(page.enroll.uri) : "" } }
                        Column {
                            width: tfaCol.width - 200 * Theme.s - Theme.gap; spacing: 8 * Theme.s
                            Txt { width: parent.width; text: "Scan this with an authenticator app, then type the code it shows." }
                            Txt { width: parent.width; kind: "mono"; text: page.enroll ? page.enroll.secret.replace(/(.{4})/g, "$1 ").trim() : "" }
                            Field { id: code; width: parent.width; placeholderText: "Code from the app"; mono: true }
                            Btn { compact: true; kind: "primary"; text: "Turn on two-factor"
                                  onClicked: Net.post("/api/auth/2fa/enable", { code: code.text.replace(/\s+/g, "") }).then(function(r) {
                                      page.enroll = null; page.codes = r.recovery_codes || []; code.text = ""; page.load()
                                  }).catch(function(e) { ui.toast(e.message, true) }) }
                        }
                    }
                    // On: new codes, or off — both need the password.
                    Field { id: pw; width: parent.width; visible: !!page.tfa && page.tfa.enabled; placeholderText: "Your password, to change these"
                            echoMode: TextInput.Password }
                    Flow {
                        width: parent.width; spacing: 8 * Theme.s
                        visible: !!page.tfa && page.tfa.enabled
                        Btn { compact: true; text: "New recovery codes"
                              onClicked: Net.post("/api/auth/2fa/recovery-codes", { password: pw.text }).then(function(r) {
                                  pw.text = ""; page.codes = r.recovery_codes || []; page.load()
                              }).catch(function(e) { ui.toast(e.message, true) }) }
                        Btn { compact: true; kind: "danger"; text: "Turn it off"; visible: !page.tfa || !page.tfa.required
                              onClicked: Net.post("/api/auth/2fa/disable", { password: pw.text }).then(function() {
                                  pw.text = ""; ui.toast("Two-factor sign-in is off"); page.load()
                              }).catch(function(e) { ui.toast(e.message, true) }) }
                    }
                    Column {
                        visible: page.codes.length > 0
                        width: parent.width; spacing: 6 * Theme.s
                        Txt { width: parent.width; color: Theme.amber
                              text: "Recovery codes — each signs you in once if the phone is lost. Write them down now; they are not shown again." }
                        Grid { columns: 2; columnSpacing: 2 * Theme.pad; rowSpacing: 4 * Theme.s
                               Repeater { model: page.codes; Txt { kind: "mono"; text: modelData; color: Theme.accent } } }
                        Btn { compact: true; text: "I've written them down"; onClicked: page.codes = [] }
                    }
                }
            }
        }
    }

    Settings { id: looks; category: "look"; property bool light: false }
}
