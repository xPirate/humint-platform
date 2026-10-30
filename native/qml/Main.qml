import QtQuick
import QtQuick.Controls
import QtQuick.Window
import QtCore
import Humint

ApplicationWindow {
    id: win
    visible: true
    width: 1280; height: 800
    visibility: Util.windowed ? Window.Windowed : Window.FullScreen
    title: "HUMINT"
    color: Theme.bg

    readonly property real scaleEnv: parseFloat(Util.env("HUMINT_UI_SCALE")) || 1
    Binding {
        target: Theme; property: "s"
        value: Math.max(0.7, Math.min(win.width / 1280, win.height / 800) * 1.0) * win.scaleEnv
    }

    readonly property var st: Box.state || ({})
    // Light or dark, chosen on this machine (Account); not case data.
    Settings { id: looks; category: "look"; property bool light: false }
    Component.onCompleted: Theme.light = looks.light

    // Which screen the machine needs right now — the same decision the Pi's
    // touch panel makes (humint-panel.py, Panel.current).
    readonly property string mode: {
        if (!Box.connected && !st.time) return "starting"
        if (st.pin_setup === "duress" && st.unlocked) return "setpin"
        if (st.unlocked && st.login_secret) return "secret"
        if (!st.unlocked) {
            if (st.pin_setup === "new" || st.pin_setup === "existing") return "setpin"
            if (st.store_exists && st.firstboot_done) return st.tries_left <= 0 ? "lockout" : "unlock"
            return "message"
        }
        return "app"
    }
    onModeChanged: {
        // The case file closed (locked, wiped, restarted): nobody stays signed in.
        if (mode !== "app" && mode !== "secret" && mode !== "setpin" && Net.me) {
            Net.me = null           // drops any drafts too (Net.qml)
            Api.signOut()
        }
    }

    // ---- what every screen can use ------------------------------------------
    QtObject {
        id: ui
        signal boxRequested(string tab)
        function openBox(tab) { boxRequested(tab || "status") }
        function quickSettings() { if (quick.opened) quick.close(); else quick.open() }
        // The keyboard's own keys (volume, brightness): a step, and a word on screen.
        function stepVolume(d) {
            var a = (Box.state || {}).audio || {}
            if (!a.present) return
            var v = Math.max(0, Math.min(100, (a.volume || 0) + d))
            Net.box("audio_set", { volume: v, muted: false }).then(function() { ui.toast("Volume " + v + "%") })
        }
        function toggleMute() {
            var a = (Box.state || {}).audio || {}
            if (!a.present) return
            Net.box("audio_set", { muted: !a.muted }).then(function(r) { ui.toast(r.muted ? "Sound off" : "Sound on") })
        }
        function stepBrightness(d) {
            var dp = (Box.state || {}).display || {}
            if (!dp.backlight) return
            var b = Math.max(5, Math.min(100, (dp.brightness || 100) + d))
            Net.box("display_set", { brightness: b }).then(function(r) { ui.toast("Brightness " + r.brightness + "%") })
        }
        property string busyText: ""
        property string toastText: ""
        property bool toastError: false
        property var confirmData: null
        function toast(msg, error) { ui.toastText = msg; toastError = !!error; toastTimer.restart() }
        function busy(text) { busyText = text || "" }
        function deleteRecords(body, onDone) { deleteDialog.open(body, onDone) }
        function confirm(title, detail, action, danger, okText) {
            confirmData = { title: title, detail: detail || "", action: action,
                            danger: danger === undefined ? true : danger, ok: okText || "Yes" }
        }
    }
    property alias ui: ui

    Loader {
        id: screen
        anchors.fill: parent
        focus: true             // keys reach the screen (Enter, the PIN)
        source: ({
            starting: "screens/Starting.qml",
            message: "screens/Message.qml",
            setpin: "screens/SetPin.qml",
            unlock: "screens/Unlock.qml",
            lockout: "screens/Lockout.qml",
            secret: "screens/Secret.qml",
            app: "app/AppShell.qml"
        })[win.mode] || "screens/Starting.qml"
    }

    // ---- overlays ----------------------------------------------------------------
    Rectangle {
        anchors.fill: parent
        visible: ui.busyText !== ""
        color: Theme.scrim
        MouseArea { anchors.fill: parent }     // nothing behind is tappable
        Column {
            anchors.centerIn: parent
            spacing: Theme.gap * 1.5
            Txt { anchors.horizontalCenter: parent.horizontalCenter; kind: "title"; text: ui.busyText }
            Spinner { anchors.horizontalCenter: parent.horizontalCenter }
            // An update in progress says what it is doing.
            Txt { anchors.horizontalCenter: parent.horizontalCenter; kind: "muted"
                  readonly property var u: (Box.state || {}).update || null
                  visible: !!u && u.state === "applying"
                  text: u && u.message ? u.message : "" }
        }
    }

    QuickSettings { id: quick }
    // (By name: Qt's Shortcut does not take these keys as numbers.)
    Shortcut { sequence: "Volume Up"; context: Qt.ApplicationShortcut; onActivated: ui.stepVolume(5) }
    Shortcut { sequence: "Volume Down"; context: Qt.ApplicationShortcut; onActivated: ui.stepVolume(-5) }
    Shortcut { sequence: "Volume Mute"; context: Qt.ApplicationShortcut; onActivated: ui.toggleMute() }
    Shortcut { sequence: "Monitor Brightness Up"; context: Qt.ApplicationShortcut; onActivated: ui.stepBrightness(10) }
    Shortcut { sequence: "Monitor Brightness Down"; context: Qt.ApplicationShortcut; onActivated: ui.stepBrightness(-10) }

    // The screen's sleep: after the chosen minutes untouched (Idle, in
    // humint_ui/idle.py) the panel switches off and this covers everything.
    // Signing out when it sleeps is a choice in the quick settings.
    // (Not while something is in progress: an update's progress stays lit.)
    Binding { target: Idle; property: "minutes"
              value: { if (ui.busyText !== "") return 0
                       var d = (Box.state || {}).display; return d && d.sleep_minutes !== undefined ? d.sleep_minutes : 10 } }
    Connections {
        target: Idle
        function onChanged() {
            if (Idle.asleep) {
                quick.close()
                var d = (Box.state || {}).display || {}
                if (d.sleep_signout && Net.me) { Net.me = null; Api.signOut() }
            }
        }
    }

    Viewer { id: fileViewer }
    UsbPicker { id: usb }
    DeleteDialog { id: deleteDialog }

    Rectangle {
        anchors.fill: parent
        visible: ui.confirmData !== null
        color: Theme.scrim
        MouseArea { anchors.fill: parent; onClicked: ui.confirmData = null }
        Rectangle {
            anchors.centerIn: parent
            width: Math.min(parent.width - 2 * Theme.pad, 560 * Theme.s)
            height: confirmCol.implicitHeight + 2 * Theme.pad * 1.5
            radius: Theme.radius * 1.5
            color: Theme.panel
            border.color: ui.confirmData && ui.confirmData.danger ? Theme.red : Theme.borderStrong
            MouseArea { anchors.fill: parent }
            Column {
                id: confirmCol
                anchors.fill: parent; anchors.margins: Theme.pad * 1.5
                spacing: Theme.gap * 1.5
                Txt { width: parent.width; kind: "title"; text: ui.confirmData ? ui.confirmData.title : "" }
                Txt { width: parent.width; kind: "muted"; text: ui.confirmData ? ui.confirmData.detail : ""
                      visible: text !== "" }
                Row {
                    anchors.right: parent.right
                    spacing: Theme.gap
                    Btn { text: "Cancel"; onClicked: ui.confirmData = null }
                    Btn {
                        text: ui.confirmData ? ui.confirmData.ok : "Yes"
                        kind: ui.confirmData && ui.confirmData.danger ? "danger" : "primary"
                        onClicked: { var a = ui.confirmData.action; ui.confirmData = null; a() }
                    }
                }
            }
        }
    }

    Rectangle {
        id: toast
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: (keyboard.item && keyboard.item.active ? keyboard.item.height : 0) + 28 * Theme.s
        visible: ui.toastText !== ""
        width: Math.min(toastLabel.implicitWidth + 2 * Theme.pad, parent.width - 2 * Theme.pad)
        height: toastLabel.implicitHeight + Theme.pad
        radius: Theme.radius
        color: ui.toastError ? Qt.darker(Theme.red, Theme.light ? 1 : 2.4) : Theme.panel
        border.color: ui.toastError ? Theme.red : Theme.accentDim
        Txt {
            id: toastLabel
            anchors.centerIn: parent
            width: Math.min(implicitWidth, win.width - 4 * Theme.pad)
            text: ui.toastText
            color: ui.toastError && !Theme.light ? Theme.red : Theme.text
            horizontalAlignment: Text.AlignHCenter
        }
        Timer { id: toastTimer; interval: 4000; onTriggered: ui.toastText = "" }
    }

    // The on-screen keyboard, for machines with no keyboard attached. Loaded
    // separately so a missing keyboard module never stops the app.
    Loader {
        id: keyboard
        anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
        source: Util.env("QT_IM_MODULE") === "qtvirtualkeyboard" ? "Keyboard.qml" : ""
    }

    // Asleep: black over everything, dialogs included. The touch that wakes
    // it never reaches what is underneath (Idle swallows it).
    Rectangle {
        objectName: "sleepCover"
        parent: Overlay.overlay
        anchors.fill: parent
        z: 1000000
        visible: Idle.asleep
        color: "black"
        MouseArea { anchors.fill: parent; hoverEnabled: true }
    }
}
