import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Humint
import ".."
import "../lib/fmt.js" as Fmt

// A board of records with a photo each (api/boards.py): BOLO — who and what
// to look out for, how urgently — or the roster — who is on the team, their
// role, callsign, how to reach them. The record itself is untouched by
// anything done here.
Rectangle {
    id: page
    color: Theme.bg
    property string board: "bolo"
    readonly property bool isRoster: board === "roster"
    property var items: []
    property var config: ({})
    property bool showClosed: false

    function load() {
        Net.get("/api/boards/" + board + "/entries" + Net.qs({ status: isRoster ? "" : (showClosed ? "all" : "active") })).then(function(r) {
            page.items = r.items || []; page.config = r.config || {}
        }).catch(function(e) { ui.toast(e.message, true) })
    }
    Component.onCompleted: load()
    function urgencyColor(u) { return ({ Critical: Theme.red, Urgent: Theme.amber, Caution: Theme.teal })[u] || Theme.muted }
    function initials(n) { return (n || "?").split(/\s+/).map(function(w) { return w.charAt(0) }).join("").slice(0, 2).toUpperCase() }

    ColumnLayout {
        anchors.fill: parent; anchors.margins: Theme.pad
        spacing: Theme.gap
        PageHeader {
            Layout.fillWidth: true
            title: page.config.label || (page.isRoster ? "Roster" : "BOLO")
            subtitle: page.isRoster ? "Who is on the team, and how to reach them." : "Who and what to look out for, and what to do on seeing them."
            Check { visible: !page.isRoster; text: "Closed too"; checked: page.showClosed
                    onToggled: { page.showClosed = checked; page.load() } }
            Btn { compact: true; text: "PDF"; visible: !page.isRoster
                  onClicked: usb.exportFile("/api/exports/bolo.pdf", "bolo.pdf") }
            Btn { compact: true; kind: "primary"; visible: !shell.viewer
                  text: page.isRoster ? "+ Add to the roster" : "+ Post a lookout"
                  onClicked: entryForm.open(null) }
        }
        Txt { visible: page.items.length === 0; kind: "muted"
              text: page.isRoster ? "Nobody on the roster yet." : "Nothing on the board. That is the good state." }
        GridView {
            id: grid
            Layout.fillWidth: true; Layout.fillHeight: true
            clip: true
            readonly property int cols: Math.max(1, Math.floor(width / (300 * Theme.s)))
            cellWidth: width / cols
            cellHeight: (page.isRoster ? 330 : 400) * Theme.s
            model: page.items
            ScrollBar.vertical: ScrollBar {}
            delegate: Item {
                width: grid.cellWidth; height: grid.cellHeight
                Rectangle {
                    anchors.fill: parent; anchors.margins: 6 * Theme.s
                    radius: Theme.radius * 1.4; color: Theme.panel
                    border.color: page.isRoster ? Theme.border : page.urgencyColor(modelData.urgency)
                    border.width: page.isRoster ? 1 : 2 * Theme.s
                    opacity: !page.isRoster && modelData.status !== "active" ? 0.55 : 1
                    ColumnLayout {
                        anchors.fill: parent; anchors.margins: 10 * Theme.s
                        spacing: 6 * Theme.s
                        // Photo, or initials
                        AbstractButton {
                            Layout.fillWidth: true; Layout.preferredHeight: (page.isRoster ? 160 : 170) * Theme.s
                            onClicked: shell.go("entity", modelData.entity_id)
                            background: Rectangle { color: Theme.panel2; radius: Theme.radius; clip: true
                                Image { anchors.fill: parent; fillMode: Image.PreserveAspectCrop; asynchronous: true
                                        visible: !!modelData.portrait_attachment_id
                                        source: modelData.portrait_attachment_id ? "image://api/api/attachments/" + modelData.portrait_attachment_id + "/file?inline=1" : "" }
                                Txt { anchors.centerIn: parent; visible: !modelData.portrait_attachment_id
                                      text: page.initials(modelData.name); font.pixelSize: 44 * Theme.s; color: Theme.muted }
                                Rectangle { visible: !page.isRoster && !!modelData.urgency; anchors.bottom: parent.bottom; width: parent.width
                                            height: 26 * Theme.s; color: page.urgencyColor(modelData.urgency)
                                            Txt { anchors.centerIn: parent; text: (modelData.urgency || "").toUpperCase(); color: "#000"; font.weight: Font.Bold } }
                            }
                        }
                        Row { spacing: 6 * Theme.s
                              Pill { text: Fmt.typeLabel(modelData.entity_type); tone: Theme.kindColor(modelData.entity_type) }
                              Pill { visible: page.isRoster && !modelData.entity_active; text: "archived"; tone: Theme.muted } }
                        Txt { Layout.fillWidth: true; text: modelData.name; font.weight: Font.DemiBold; font.pixelSize: 17 * Theme.s }
                        Txt { Layout.fillWidth: true; visible: page.isRoster && !!modelData.callsign; text: modelData.callsign || ""
                              color: Theme.accent; font.family: "IBM Plex Mono" }
                        Txt { Layout.fillWidth: true; visible: page.isRoster && !!modelData.role; text: modelData.role || ""; kind: "muted" }
                        Txt { Layout.fillWidth: true; visible: page.isRoster && !!modelData.contact_note; text: modelData.contact_note || ""; kind: "muted" }
                        Txt { Layout.fillWidth: true; Layout.fillHeight: true; visible: !page.isRoster; text: modelData.reason || ""
                              elide: Text.ElideRight; font.family: Theme.prose }
                        Txt { Layout.fillWidth: true; visible: !page.isRoster && modelData.status !== "active"; kind: "muted"
                              text: (modelData.status || "") + (modelData.resolved_note ? " — " + modelData.resolved_note : "") }
                        Txt { Layout.fillWidth: true; visible: !page.isRoster && !!modelData.expires_at && modelData.status === "active"; kind: "muted"
                              text: "until " + Fmt.exactDate(modelData.expires_at) }
                        Flow {
                            Layout.fillWidth: true; spacing: 4 * Theme.s
                            visible: !shell.viewer
                            Btn { compact: true; visible: !page.isRoster && modelData.status === "active"; text: "Close out"; onClicked: closeOut.open(modelData) }
                            Btn { compact: true; kind: "ghost"; visible: page.isRoster || modelData.status === "active"; text: "Edit"; onClicked: entryForm.open(modelData) }
                            Btn { compact: true; kind: "ghost"; visible: !page.isRoster && modelData.status !== "active"; text: "Reopen"
                                  onClicked: Net.patch("/api/boards/" + page.board + "/entries/" + modelData.id, { status: "active" }).then(page.load)
                                                 .catch(function(e) { ui.toast(e.message, true) }) }
                            Btn { compact: true; kind: "ghost"; text: "Remove"
                                  onClicked: ui.confirm("Take this off the board?", "The record itself is untouched.", function() {
                                      Net.del("/api/boards/" + page.board + "/entries/" + modelData.id).then(page.load).catch(function(e) { ui.toast(e.message, true) })
                                  }) }
                        }
                    }
                }
            }
        }
    }

    FormDialog {
        id: entryForm
        property var entry: null
        title: entry ? "Edit this entry" : (page.isRoster ? "Add to the roster" : "Post a lookout")
        okText: entry ? "Save" : "Add"
        function open(e) {
            entry = e; pick.reset()
            role.text = e ? (e.role || "") : ""; callsign.text = e ? (e.callsign || "") : ""; contact.text = e ? (e.contact_note || "") : ""
            reason.text = e ? (e.reason || "") : ""; urgency.value = e ? (e.urgency || "Info") : "Info"; expires.text = e ? (e.expires_at || "") : ""
            visible = true
        }
        onAccepted: {
            var body = page.isRoster ? { role: role.text.trim() || null, callsign: callsign.text.trim() || null, contact_note: contact.text.trim() || null }
                                     : { reason: reason.text.trim() || null, urgency: urgency.value, expires_at: expires.text.trim() || null }
            if (!entry && !pick.picked) { error = "Pick a record first."; return }
            busy = true
            var req = entry ? Net.patch("/api/boards/" + page.board + "/entries/" + entry.id, body)
                            : Net.post("/api/boards/" + page.board + "/entries", Object.assign({ entity_id: pick.picked.id }, body))
            req.then(function() { busy = false; close(); page.load() }).catch(function(e) { busy = false; error = e.message })
        }
        Labeled { label: "Which record"; visible: !entryForm.entry; EntityPicker { id: pick; width: parent.width; allowCreate: true } }
        Labeled { label: "Role"; visible: page.isRoster; Field { id: role; width: parent.width; placeholderText: "Team lead" } }
        Labeled { label: "Callsign"; visible: page.isRoster; Field { id: callsign; width: parent.width; placeholderText: "Alpha Six" } }
        Labeled { label: "How to reach them"; visible: page.isRoster; hint: "One line for the card. Full contact detail belongs on the record."
                  Field { id: contact; width: parent.width; placeholderText: "cell, then the repeater" } }
        Labeled { label: "What to do if you see it"; visible: !page.isRoster
                  TextArea { id: reason; width: parent.width; height: 100 * Theme.s; wrapMode: TextEdit.Wrap; color: Theme.text
                             font.family: Theme.prose; font.pixelSize: Theme.fs; padding: 10 * Theme.s
                             placeholderText: "Seen leaving the yard at 0340. Do not approach — call it in."; placeholderTextColor: Theme.muted
                             background: Rectangle { color: Theme.panel2; radius: Theme.radius; border.color: reason.activeFocus ? Theme.accent : Theme.border } } }
        Labeled { label: "Urgency"; visible: !page.isRoster
                  Select { id: urgency; width: parent.width; options: [["Info", "Info"], ["Caution", "Caution"], ["Urgent", "Urgent"], ["Critical", "Critical"]] } }
        Labeled { label: "Drop off the board on (YYYY-MM-DD)"; visible: !page.isRoster
                  hint: "Optional. Past this it shows as lapsed rather than vanishing."
                  Field { id: expires; width: parent.width; mono: true } }
    }

    FormDialog {
        id: closeOut
        property var entry: null
        title: "Close this out"
        okText: "Close out"
        function open(e) { entry = e; note.text = ""; outcome.value = "resolved"; visible = true }
        onAccepted: {
            busy = true
            Net.patch("/api/boards/" + page.board + "/entries/" + entry.id, { status: outcome.value, resolved_note: note.text.trim() || null })
                .then(function() { busy = false; close(); page.load() }).catch(function(e) { busy = false; error = e.message })
        }
        Txt { width: parent.width; kind: "muted"
              text: "It leaves the live board and stays in the history. Say what happened." }
        Labeled { label: "What happened"; Field { id: note; width: parent.width; placeholderText: "Recovered in Jackson, 14 Mar" } }
        Labeled { label: "Outcome"
                  Select { id: outcome; width: parent.width
                           options: [["resolved", "Resolved — it was found or dealt with"], ["cancelled", "Cancelled — it should not have been posted"]] } }
    }
}
