import QtQuick
import QtQuick.Controls
import Humint
import ".."
import "../lib/fmt.js" as Fmt

// Updates online (api/field_update.py): with internet, look for a newer
// release, show what changed since this build, and install it. The download
// goes into the same inbox as an uploaded bundle; root checks its signature
// against this machine's key before anything changes.
FormDialog {
    id: ud
    title: "Update online"
    okText: info && info.available ? "Download and install build " + info.available.build : "Check again"
    property var info: null
    property bool checking: false
    property bool installing: false
    property string progress: ""

    function check(refresh) {
        checking = true; info = null; error = ""
        Net.get("/api/admin/field-update/online" + (refresh ? "?refresh=true" : "")).then(function(r) {
            checking = false; info = r
        }).catch(function(e) { checking = false; error = e.message })
    }
    function poll() {
        Net.get("/api/admin/field-update").then(function(st) {
            var d = st.download || {}
            if (d.state === "downloading")
                progress = "Downloading… " + (d.done / 1048576).toFixed(1) + (d.size ? " of " + (d.size / 1048576).toFixed(1) : "") + " MB"
            else if (d.state === "failed") { installing = false; busy = false; error = d.message; return }
            else if (d.message) progress = d.message
            pollTimer.start()
        }).catch(function() { progress = "Restarting on the new version…"; pollTimer.start() })
    }
    Timer { id: pollTimer; interval: 3000; onTriggered: ud.poll() }

    onOpened: { progress = ""; installing = false; busy = false; check(true) }
    onClosed: pollTimer.stop()
    onAccepted: {
        if (!info || !info.available) { check(true); return }
        if (!info.managed) { error = "This console is updated with git pull and docker compose."; return }
        installing = true; busy = true
        Net.post("/api/admin/field-update/online", { build: info.available.build }).then(function(r) {
            progress = r.message || "Downloading…"; pollTimer.start()
        }).catch(function(e) { installing = false; busy = false; error = e.message })
    }

    Txt { width: parent.width; visible: ud.checking; kind: "muted"; text: "Asking GitHub…" }
    Txt { width: parent.width; visible: !!ud.info && !ud.info.available
          text: ud.info ? "Up to date: build " + ud.info.installed_build + " is the newest release for this machine." : "" }
    Txt { width: parent.width; visible: !!(ud.info && ud.info.available); font.weight: Font.DemiBold
          text: ud.info && ud.info.available ? "Build " + ud.info.available.build + " is available — this machine has build "
                + ud.info.installed_build + (ud.info.available.size ? " · " + (ud.info.available.size / 1048576).toFixed(1) + " MB" : "") : "" }
    Txt { width: parent.width; visible: !!(ud.info && ud.info.available); kind: "label"; text: "What changed" }
    Rectangle {
        width: parent.width; visible: !!(ud.info && ud.info.available)
        height: Math.min(notes.implicitHeight + 2 * Theme.gap, 380 * Theme.s)
        radius: Theme.radius; color: Theme.panel2; border.color: Theme.border
        Flickable {
            anchors.fill: parent; anchors.margins: Theme.gap
            clip: true; contentHeight: notes.implicitHeight
            ScrollBar.vertical: ScrollBar {}
            Txt {
                id: notes
                width: parent.width
                textFormat: Text.RichText
                text: ud.info && ud.info.changes ? ud.info.changes.map(function(c) {
                    return "<h3>" + (c.name || "Build " + c.build).replace(/&/g, "&amp;").replace(/</g, "&lt;") + "</h3>"
                         + Fmt.mdToHtml(c.notes || "No notes.", Theme.accent)
                }).join("") : ""
            }
        }
    }
    Txt { width: parent.width; visible: !!(ud.info && ud.info.available) && !ud.installing; kind: "muted"
          text: "The database is backed up first. The console restarts on the new version — or is put back as it was if it does not come up." }
    Txt { width: parent.width; visible: ud.progress !== ""; text: ud.progress }
}
