import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Humint
import ".."

// Signing in to the case file on this machine: the same accounts as the web
// console and the phones. On a brand-new case file, it creates the first
// admin account instead. Two-factor codes, and enrolment when an admin
// requires it, as in the console.
Rectangle {
    id: root
    color: Theme.bg
    signal openBox()
    property string step: "loading"     // loading | bootstrap | login | otp | enrol | codes
    property string note: ""
    property bool busy: false
    property var enrolData: null
    property var recoveryCodes: []
    property var pendingUser: null

    // Typing goes straight into the first field (a laptop with no mouse).
    Component.onCompleted: { check(); Qt.callLater(function() { user.forceActiveFocus() }) }
    function check() {
        Net.get("/api/auth/bootstrap-status").then(function(r) {
            root.step = r.needs_bootstrap ? "bootstrap" : "login"
        }).catch(function(e) {
            root.step = "loading"; root.note = e.message
            retry.start()
        })
    }
    Timer { id: retry; interval: 2000; onTriggered: root.check() }

    function finish(user) {
        Net.get("/api/me/preferences").then(function(r) {
            var p = (r.preferences || {})
            if (p.palette) Theme.palette = p.palette
            if (p.theme) Theme.light = (p.theme === "light")
        }).catch(function() {})
        Net.me = user
    }

    function signIn() {
        if (root.busy) return
        root.busy = true; root.note = ""
        var body = { username: user.text.trim(), password: pass.text, client_epoch_ms: Date.now() }
        if (root.step === "otp") body.otp = otp.text.replace(/\s+/g, "")
        Net.post("/api/auth/login", body).then(function(u) {
            root.busy = false
            pass.text = ""; otp.text = ""
            if (u.needs_2fa_setup) { root.pendingUser = u; startEnrol(); return }
            finish(u)
        }).catch(function(e) {
            root.busy = false
            var d = e.data && e.data.detail
            if (d && d.otp_required) { root.step = "otp"; root.note = d.message; otp.forceActiveFocus(); return }
            root.note = e.message
            if (root.step === "otp") otp.text = ""
            else pass.text = ""
        })
    }

    function createFirstAdmin() {
        if (pass.text !== pass2.text) { root.note = "The passwords don't match"; return }
        root.busy = true; root.note = ""
        Net.post("/api/auth/register", { username: user.text.trim(), password: pass.text }).then(function(u) {
            root.busy = false; pass.text = ""; pass2.text = ""
            finish(u)
        }).catch(function(e) { root.busy = false; root.note = e.message })
    }

    function startEnrol() {
        Net.post("/api/auth/2fa/setup", {}).then(function(r) {
            root.enrolData = r; root.step = "enrol"; root.note = ""
        }).catch(function(e) { root.note = e.message })
    }
    function finishEnrol() {
        root.busy = true
        Net.post("/api/auth/2fa/enable", { code: enrolCode.text.replace(/\s+/g, "") }).then(function(r) {
            root.busy = false; enrolCode.text = ""
            root.recoveryCodes = r.recovery_codes || []
            root.step = "codes"
        }).catch(function(e) { root.busy = false; root.note = e.message })
    }

    StatusStrip {
        id: strip
        anchors.top: parent.top; width: parent.width
        rightItems: [
            Btn { compact: true; text: "Box"; onClicked: root.openBox() }
        ]
    }

    Flickable {
        anchors.fill: parent; anchors.topMargin: strip.height
        contentHeight: Math.max(height, form.implicitHeight + 4 * Theme.pad)
        clip: true
        ColumnLayout {
            id: form
            anchors.horizontalCenter: parent.horizontalCenter
            y: Math.max(2 * Theme.pad, (parent.height - implicitHeight) / 2 - 40 * Theme.s)
            width: Math.min(root.width - 4 * Theme.pad, 480 * Theme.s)
            spacing: Theme.gap

            Txt { Layout.fillWidth: true; kind: "huge"; text: "HUMINT"; color: Theme.accent
                  horizontalAlignment: Text.AlignHCenter }
            Txt {
                Layout.fillWidth: true; horizontalAlignment: Text.AlignHCenter; kind: "muted"
                text: root.step === "bootstrap" ? "A new case file. Create the first admin account."
                    : root.step === "otp" ? "Two-factor sign-in"
                    : root.step === "enrol" ? "Your admin requires two-factor sign-in. Scan this with an authenticator app, then type the code it shows."
                    : root.step === "codes" ? "Recovery codes — each signs you in once if the phone is lost. Write them down now; they are not shown again."
                    : root.step === "loading" ? "Waiting for the console…"
                    : "Sign in to the case file"
            }

            Field { id: user; Layout.fillWidth: true; placeholderText: "Username"
                    visible: root.step === "login" || root.step === "bootstrap"
                    inputMethodHints: Qt.ImhNoAutoUppercase | Qt.ImhNoPredictiveText
                    onAccepted: pass.forceActiveFocus() }
            Field { id: pass; Layout.fillWidth: true; placeholderText: "Password"
                    visible: root.step === "login" || root.step === "bootstrap"
                    echoMode: TextInput.Password
                    inputMethodHints: Qt.ImhSensitiveData | Qt.ImhNoPredictiveText | Qt.ImhNoAutoUppercase
                    onAccepted: root.step === "bootstrap" ? pass2.forceActiveFocus() : root.signIn() }
            Field { id: pass2; Layout.fillWidth: true; placeholderText: "Password again (at least 10 characters)"
                    visible: root.step === "bootstrap"
                    echoMode: TextInput.Password
                    inputMethodHints: Qt.ImhSensitiveData | Qt.ImhNoPredictiveText | Qt.ImhNoAutoUppercase
                    onAccepted: root.createFirstAdmin() }
            Field { id: otp; Layout.fillWidth: true; placeholderText: "6-digit code, or a recovery code"
                    visible: root.step === "otp"; mono: true
                    inputMethodHints: Qt.ImhNoPredictiveText | Qt.ImhNoAutoUppercase
                    onAccepted: root.signIn() }

            // Enrolment: the QR code and the secret to type by hand.
            Rectangle {
                visible: root.step === "enrol"
                Layout.alignment: Qt.AlignHCenter
                width: 240 * Theme.s; height: width; color: "white"; radius: Theme.radius
                Image {
                    anchors.fill: parent; anchors.margins: 8 * Theme.s
                    source: root.enrolData ? "image://qr/" + encodeURIComponent(root.enrolData.uri) : ""
                    smooth: false; fillMode: Image.PreserveAspectFit
                }
            }
            Txt { visible: root.step === "enrol"; Layout.fillWidth: true; kind: "mono"
                  horizontalAlignment: Text.AlignHCenter
                  text: root.enrolData ? root.enrolData.secret.replace(/(.{4})/g, "$1 ").trim() : "" }
            Field { id: enrolCode; Layout.fillWidth: true; visible: root.step === "enrol"; mono: true
                    placeholderText: "Code from the app"; onAccepted: root.finishEnrol() }

            GridLayout {
                visible: root.step === "codes"
                Layout.alignment: Qt.AlignHCenter
                columns: 2; columnSpacing: 2 * Theme.pad; rowSpacing: 6 * Theme.s
                Repeater { model: root.recoveryCodes
                           Txt { kind: "mono"; text: modelData; font.pixelSize: 18 * Theme.s; color: Theme.accent } }
            }

            Txt { Layout.fillWidth: true; visible: root.note !== ""; text: root.note; color: Theme.amber
                  horizontalAlignment: Text.AlignHCenter }

            Btn {
                Layout.fillWidth: true
                kind: "primary"
                visible: root.step !== "loading"
                enabled: !root.busy
                text: root.busy ? "Working…"
                    : root.step === "bootstrap" ? "Create admin account"
                    : root.step === "enrol" ? "Turn on two-factor"
                    : root.step === "codes" ? "I've written them down"
                    : "Sign in"
                onClicked: {
                    if (root.step === "bootstrap") root.createFirstAdmin()
                    else if (root.step === "enrol") root.finishEnrol()
                    else if (root.step === "codes") root.finish(root.pendingUser)
                    else root.signIn()
                }
            }
            Btn {
                Layout.fillWidth: true; kind: "ghost"
                visible: root.step === "otp"
                text: "Back"
                onClicked: { root.step = "login"; root.note = ""; otp.text = "" }
            }
        }
    }
}
