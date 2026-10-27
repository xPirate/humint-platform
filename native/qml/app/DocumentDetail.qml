import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Humint
import ".."
import "../lib/fmt.js" as Fmt

// One document: the file, the text read out of it, what it proposes; file
// it under a report or record, read it again, archive it.
Rectangle {
    id: page
    color: Theme.bg
    property var doc: null
    property string error: ""
    property string find: ""

    function load() {
        Net.get("/api/documents/" + shell.arg).then(function(d) { page.doc = d; page.error = "" })
            .catch(function(e) { page.error = e.message })
    }
    Component.onCompleted: load()
    Timer { interval: 4000; repeat: true
            running: !!page.doc && (page.doc.extraction_status === "pending" || page.doc.extraction_status === "processing")
            onTriggered: page.load() }
    function act(verb, msg) {
        Net.post("/api/documents/" + page.doc.id + "/" + verb, {}).then(function() { ui.toast(msg); page.load() })
            .catch(function(e) { ui.toast(e.message, true) })
    }
    readonly property var pending: doc ? (doc.suggestions || []).filter(function(s) { return s.status === "pending" }) : []

    RowLayout {
        anchors.fill: parent; anchors.margins: Theme.pad
        spacing: Theme.gap * 1.5

        ColumnLayout {
            Layout.fillWidth: true; Layout.fillHeight: true
            spacing: Theme.gap
            PageHeader {
                Layout.fillWidth: true
                back: true; onBackClicked: shell.back()
                title: page.doc ? (page.doc.title || page.doc.filename) : (page.error || "Loading…")
                subtitle: page.doc ? [page.doc.filename, Fmt.fileSize(page.doc.file_size_bytes), "added " + Fmt.relativeTime(page.doc.uploaded_at),
                                      page.doc.source_note || ""].filter(function(x) { return x }).join(" · ") : ""
                Btn { compact: true; text: "Open file"; visible: !!page.doc && !page.doc.is_pasted; onClicked: fileViewer.show(page.doc) }
                Btn { compact: true; text: "File under…"; visible: !!page.doc && !shell.viewer; onClicked: fileUnder.open() }
                Btn { compact: true; text: "Read again"; visible: !!page.doc && !shell.viewer; onClicked: page.act("re-extract", "Queued to be read again") }
                Btn { compact: true; visible: !!page.doc && !shell.viewer
                      text: page.doc && page.doc.archived_at ? "Restore" : "Archive"
                      onClicked: page.doc.archived_at ? page.act("restore", "Back in the inbox") : page.act("archive", "Archived") }
                Btn { compact: true; kind: "danger"; text: "Delete"; visible: !!page.doc && shell.admin
                      onClicked: ui.deleteRecords({ attachment_ids: [page.doc.id] }, function() { shell.back() }) }
            }
            Txt { Layout.fillWidth: true; visible: !!(page.doc && page.doc.extraction_error); color: Theme.amber
                  text: page.doc ? (page.doc.extraction_error || "") : "" }
            RowLayout {
                Layout.fillWidth: true
                Txt { kind: "label"; text: "Text read from it"; Layout.fillWidth: true }
                Field { Layout.preferredWidth: 260 * Theme.s; placeholderText: "Find in text"; onTextChanged: page.find = text }
            }
            ScrollView {
                Layout.fillWidth: true; Layout.fillHeight: true
                TextArea {
                    id: body
                    readOnly: true
                    wrapMode: TextEdit.Wrap
                    textFormat: TextEdit.RichText
                    color: Theme.text
                    font.family: Theme.prose; font.pixelSize: 15 * Theme.s
                    padding: 14 * Theme.s
                    background: Rectangle { color: Theme.panel; radius: Theme.radius; border.color: Theme.border }
                    text: {
                        var t = Fmt.escapeHtml(page.doc ? (page.doc.extracted_text || (page.doc.extraction_status === "done" ? "(no text found)" : "Not read yet.")) : "")
                        if (page.find.length > 1) {
                            var esc = Fmt.escapeHtml(page.find).replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
                            t = t.replace(new RegExp(esc, "gi"), function(m) { return '<span style="background-color:' + Theme.amber + ';color:#000">' + m + "</span>" })
                        }
                        return "<div style='white-space:pre-wrap'>" + t.replace(/\n/g, "<br/>") + "</div>"
                    }
                }
            }
        }

        // What it proposes
        Rectangle {
            Layout.preferredWidth: 340 * Theme.s; Layout.fillHeight: true
            radius: Theme.radius * 1.4; color: Theme.panel; border.color: Theme.border
            ColumnLayout {
                anchors.fill: parent; anchors.margins: Theme.pad
                spacing: 8 * Theme.s
                Txt { kind: "label"; text: "Proposed (" + page.pending.length + " waiting)" }
                Txt { Layout.fillWidth: true; visible: !!page.doc && !(page.doc.suggestions || []).length; kind: "muted"
                      text: "Nothing proposed from this document." }
                ListView {
                    Layout.fillWidth: true; Layout.fillHeight: true
                    clip: true; spacing: 8 * Theme.s
                    model: page.doc ? page.doc.suggestions || [] : []
                    delegate: Column {
                        width: ListView.view.width
                        spacing: 4 * Theme.s
                        opacity: modelData.status === "pending" ? 1 : 0.5
                        Flow { width: parent.width; spacing: 6 * Theme.s
                            Pill { visible: modelData.suggestion_type === "entity"; text: Fmt.typeLabel(modelData.suggested_entity_type || "")
                                   tone: Theme.kindColor(modelData.suggested_entity_type) }
                            Txt { text: modelData.suggestion_type === "entity" ? modelData.suggested_name
                                        : modelData.suggested_from_name + " — " + (modelData.suggested_relationship_type || "").replace(/_/g, " ") + " → " + modelData.suggested_to_name
                                  font.weight: Font.DemiBold; width: Math.min(implicitWidth, parent.width) } }
                        Row { spacing: 6 * Theme.s
                              visible: modelData.status === "pending" && !shell.viewer && modelData.suggestion_type === "entity"
                              Btn { compact: true; kind: "primary"; text: "Accept"
                                    onClicked: Net.post("/api/extraction-suggestions/" + modelData.id + "/accept", {}).then(function() { ui.toast("Accepted"); page.load() })
                                                  .catch(function(e) { ui.toast(e.message, true) }) }
                              Btn { compact: true; kind: "ghost"; text: "Reject"
                                    onClicked: Net.post("/api/extraction-suggestions/" + modelData.id + "/reject", {}).then(function() { page.load() })
                                                  .catch(function(e) { ui.toast(e.message, true) }) }
                              Btn { compact: true; kind: "ghost"; text: "Find"; onClicked: page.find = modelData.suggested_name || "" } }
                        Txt { visible: modelData.status === "pending" && modelData.suggestion_type !== "entity"; kind: "muted"; width: parent.width
                              text: "Settle which records these are in the Review inbox." }
                        Txt { visible: modelData.status !== "pending"; kind: "muted"; text: modelData.status }
                    }
                }
                Btn { Layout.fillWidth: true; compact: true; visible: page.pending.length > 0; text: "Open the Review inbox"; onClicked: shell.go("review") }
            }
        }
    }

    FormDialog {
        id: fileUnder
        title: "File it under a record"
        okText: "File it"
        onOpened: pick.reset()
        onAccepted: {
            if (!pick.picked) { error = "Pick the record."; return }
            busy = true
            Net.post("/api/documents/" + page.doc.id + "/file-under", { entity_id: pick.picked.id }).then(function() {
                busy = false; close(); ui.toast("Filed under " + pick.picked.name); shell.replace("entity", pick.picked.id)
            }).catch(function(e) { busy = false; error = e.message })
        }
        Txt { width: parent.width; kind: "muted"
              text: "It leaves the inbox and becomes one of that record's files. Its text and what it proposed stay with it." }
        EntityPicker { id: pick; width: parent.width }
    }
}
