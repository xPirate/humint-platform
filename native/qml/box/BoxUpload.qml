import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Humint
import ".."

// A phone upload code from the machine itself: pick the person, the phone,
// scan. The code is a working credential, so it leaves the screen after
// three minutes or when closed. (api/panel.py; audited as the touch panel.)
Item {
    id: up
    property var people: []
    property var person: null
    property var code: null
    property string error: ""
    property int secondsLeft: 0
    readonly property int showSeconds: 180

    Component.onCompleted: load()
    function load() {
        up.error = ""
        Net.box("upload_people", {}).then(function(r) { up.people = r.items || [] })
            .catch(function(e) { up.error = e.message })
    }
    function issue(deviceId, userId) {
        ui.busy("Making a code…")
        var args = {}
        if (deviceId !== null) args.device_id = deviceId
        if (userId !== null) args.user_id = userId
        Net.box("upload_code", args).then(function(r) {
            ui.busy(""); up.code = r; up.secondsLeft = up.showSeconds
        }).catch(function(e) { ui.busy(""); ui.toast(e.message, true) })
    }
    function close() { up.code = null; up.person = null }
    Timer {
        running: up.code !== null; interval: 1000; repeat: true
        onTriggered: { up.secondsLeft -= 1; if (up.secondsLeft <= 0) up.close() }
    }

    Txt { visible: up.error !== ""; anchors.centerIn: parent; color: Theme.amber; text: up.error }

    // 1. who
    Column {
        visible: !up.code && !up.person && up.error === ""
        anchors.fill: parent
        spacing: Theme.gap
        Txt { width: parent.width; kind: "muted"
              text: "Who is the code for? It lets their phone post field reports as them, into the review inbox." }
        Flow {
            width: parent.width; spacing: Theme.gap
            Repeater {
                model: up.people
                Btn {
                    width: 230 * Theme.s
                    text: modelData.username
                    sub: modelData.devices.length ? modelData.devices.length + (modelData.devices.length === 1 ? " phone" : " phones") : "no phone yet"
                    onClicked: {
                        if (modelData.devices.length) up.person = modelData
                        else up.issue(null, modelData.id)
                    }
                }
            }
        }
    }
    // 2. which phone
    Column {
        visible: !up.code && up.person !== null
        anchors.fill: parent
        spacing: Theme.gap
        Row {
            spacing: Theme.gap
            Btn { compact: true; text: "← Back"; onClicked: up.person = null }
            Txt { anchors.verticalCenter: parent.verticalCenter; kind: "title"
                  text: up.person ? "Which of " + up.person.username + "'s phones?" : "" }
        }
        Flow {
            width: parent.width; spacing: Theme.gap
            Repeater {
                model: up.person ? up.person.devices : []
                Btn { width: 260 * Theme.s; text: modelData.label
                      sub: modelData.last_seen_at ? "last seen " + modelData.last_seen_at.slice(0, 10) : "never synced"
                      onClicked: up.issue(modelData.id, null) }
            }
            Btn { width: 260 * Theme.s; text: "A new phone"; sub: "adds one for " + (up.person ? up.person.username : "")
                  onClicked: up.issue(null, up.person.id) }
        }
    }
    // 3. the code
    RowLayout {
        visible: up.code !== null
        anchors.fill: parent
        spacing: Theme.gap * 2
        Rectangle {
            Layout.preferredWidth: Math.min(parent.height, 420 * Theme.s); Layout.preferredHeight: Layout.preferredWidth
            color: "white"; radius: Theme.radius
            Image { anchors.fill: parent; anchors.margins: 12 * Theme.s; smooth: false; fillMode: Image.PreserveAspectFit
                    source: up.code ? "image://qr/" + encodeURIComponent(JSON.stringify(up.code.enrollment)) : "" }
        }
        Column {
            Layout.fillWidth: true
            spacing: Theme.gap
            Txt { width: parent.width; kind: "title"; text: up.code ? up.code.label : "" }
            Txt { width: parent.width; kind: "muted"
                  text: "In the HUMINT field app: Upload → Scan code. The phone sends its reports to "
                        + (up.code && up.code.enrollment.url ? up.code.enrollment.url : "this machine") + "." }
            Txt { width: parent.width; color: Theme.amber
                  text: "Anyone who scans this can post as " + (up.code ? up.code.username : "") + ". It closes in "
                        + Math.floor(up.secondsLeft / 60) + ":" + ("0" + up.secondsLeft % 60).slice(-2) + "." }
            Btn { kind: "primary"; text: "Done"; onClicked: up.close() }
        }
    }
}
