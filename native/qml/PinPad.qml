import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// PIN entry: a big number pad, or a passphrase on the keyboard (on-screen
// or attached). Nothing typed is ever shown.
Item {
    id: pad
    property string title: "Enter the PIN"
    property string detail: ""
    property string note: ""
    property color noteColor: Theme.amber
    property string submitText: "Unlock"
    property bool busy: false
    property bool cancellable: false
    property string pin: ""
    property bool letters: false
    signal submitted(string pin)
    signal cancelled()

    function clear() { pin = ""; textEntry.text = "" }
    function submit() {
        var v = letters ? textEntry.text : pin
        if (!v || busy) return
        clear()
        submitted(v)
    }
    onLettersChanged: { clear(); if (letters) textEntry.forceActiveFocus(); else keyCatcher.forceActiveFocus() }
    Component.onCompleted: keyCatcher.forceActiveFocus()

    // An attached keyboard, in number mode.
    Item {
        id: keyCatcher
        focus: !pad.letters
        Keys.onPressed: function(e) {
            if (pad.busy) return
            if (e.key === Qt.Key_Return || e.key === Qt.Key_Enter) { pad.submit(); e.accepted = true }
            else if (e.key === Qt.Key_Backspace) { pad.pin = pad.pin.slice(0, -1); e.accepted = true }
            else if (e.key === Qt.Key_Escape && pad.cancellable) { pad.cancelled(); e.accepted = true }
            else if (e.text && e.text.length === 1 && e.text >= " " && pad.pin.length < 64) {
                if (!/[0-9]/.test(e.text)) pad.letters = true
                else pad.pin += e.text
                e.accepted = true
            }
        }
    }

    ColumnLayout {
        anchors.centerIn: parent
        width: Math.min(parent.width - 2 * Theme.pad, 460 * Theme.s)
        spacing: Theme.gap

        Txt { Layout.fillWidth: true; kind: "title"; text: pad.title; horizontalAlignment: Text.AlignHCenter }
        Txt {
            Layout.fillWidth: true; visible: pad.detail !== ""; kind: "muted"; text: pad.detail
            horizontalAlignment: Text.AlignHCenter
        }

        // What has been typed, as dots.
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 60 * Theme.s
            visible: !pad.letters
            radius: Theme.radius
            color: Theme.panel2
            border.color: Theme.border
            Text {
                anchors.centerIn: parent
                text: pad.pin.length ? "● ".repeat(Math.min(pad.pin.length, 16)).trim() : ""
                color: Theme.accent
                font.pixelSize: 22 * Theme.s
                font.letterSpacing: 2 * Theme.s
            }
            Txt {
                anchors.centerIn: parent
                visible: pad.pin.length === 0
                kind: "muted"; text: "Type the PIN"
            }
        }
        Field {
            id: textEntry
            Layout.fillWidth: true
            visible: pad.letters
            echoMode: TextInput.Password
            passwordCharacter: "●"
            placeholderText: "Passphrase"
            inputMethodHints: Qt.ImhSensitiveData | Qt.ImhNoPredictiveText | Qt.ImhNoAutoUppercase | Qt.ImhHiddenText
            onAccepted: pad.submit()
            Keys.onEscapePressed: if (pad.cancellable) pad.cancelled()
        }

        Txt {
            Layout.fillWidth: true
            visible: pad.note !== ""
            text: pad.note; color: pad.noteColor
            horizontalAlignment: Text.AlignHCenter
        }

        GridLayout {
            Layout.fillWidth: true
            visible: !pad.letters
            columns: 3
            rowSpacing: 10 * Theme.s; columnSpacing: 10 * Theme.s
            Repeater {
                model: ["1", "2", "3", "4", "5", "6", "7", "8", "9", "⌫", "0", "ABC"]
                Btn {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 64 * Theme.s
                    text: modelData
                    enabled: !pad.busy
                    focusPolicy: Qt.NoFocus
                    onClicked: {
                        if (modelData === "⌫") pad.pin = pad.pin.slice(0, -1)
                        else if (modelData === "ABC") pad.letters = true
                        else if (pad.pin.length < 64) pad.pin += modelData
                        keyCatcher.forceActiveFocus()
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 10 * Theme.s
            Btn {
                visible: pad.letters
                text: "123"
                focusPolicy: Qt.NoFocus
                onClicked: pad.letters = false
            }
            Btn {
                visible: pad.cancellable
                text: "Cancel"
                kind: "ghost"
                focusPolicy: Qt.NoFocus
                onClicked: pad.cancelled()
            }
            Btn {
                Layout.fillWidth: true
                Layout.preferredHeight: 64 * Theme.s
                kind: "primary"
                text: pad.busy ? "Working…" : pad.submitText
                enabled: !pad.busy && (pad.letters ? textEntry.text.length > 0 : pad.pin.length > 0)
                focusPolicy: Qt.NoFocus
                onClicked: pad.submit()
            }
        }
    }
}
