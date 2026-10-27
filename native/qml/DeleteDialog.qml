import QtQuick
import QtQuick.Controls
import Humint
import "lib/fmt.js" as Fmt

// Permanent deletion (admins only), as in the console: the server says what
// would go first, a confirmed report naming a record blocks it, and DELETE
// must be typed. open({entity_ids:[...]} | {report_ids:[...]} | {attachment_ids:[...]}, onDone)
Rectangle {
    id: dlg
    anchors.fill: parent
    visible: body !== null
    color: Theme.scrim
    property var body: null
    property var preview: null
    property var onDone: null
    property bool busy: false
    readonly property string word: "DELETE"

    function open(b, done) {
        dlg.preview = null; dlg.body = b; dlg.onDone = done || null; confirmField.text = ""
        Net.post("/api/admin/delete-preview", b).then(function(p) { dlg.preview = p })
            .catch(function(e) { dlg.body = null; ui.toast(e.message, true) })
    }
    function close() { dlg.body = null; dlg.preview = null }

    readonly property int total: preview ? preview.entities.length + preview.reports.length + preview.documents.length : 0
    function sum(key) { return preview ? preview.entities.reduce(function(n, e) { return n + (e.removes[key] || 0) }, 0) : 0 }
    readonly property var lines: {
        if (!preview) return []
        var L = []
        if (preview.entities.length) {
            L.push(preview.entities.length + " record(s): " + preview.entities.map(function(e) { return e.name }).join(", "))
            L.push(sum("relationships") + " relationship(s)")
            L.push(sum("contacts") + " contact detail(s)")
            L.push(sum("attachments") + " attachment(s), files and all")
            L.push((sum("suggestions") + sum("correlation_rows")) + " queued or historical suggestion(s) about them")
            var merged = sum("merged_into_this")
            if (merged) L.push(merged + " merged into " + (preview.entities.length === 1 ? "this one" : "these") + " stay archived")
        }
        if (preview.reports.length) {
            L.push(preview.reports.length + " report(s): " + preview.reports.map(function(r) { return r.title }).join(", "))
            var conf = preview.reports.filter(function(r) { return r.warn_confirmed }).length
            if (conf) L.push(conf + " of them " + (conf === 1 ? "is" : "are") + " confirmed, not a draft")
        }
        if (preview.documents.length) {
            L.push(preview.documents.length + " document(s) and the uploaded file(s) on disk")
            var kept = preview.documents.reduce(function(n, d) { return n + (d.accepted_records_kept || 0) }, 0)
            if (kept) L.push(kept + " record(s) already accepted from them are kept")
        }
        var cited = [].concat.apply([], preview.entities.map(function(e) { return e.cited_by || [] }))
                      .filter(function(r) { return r.status !== "confirmed" })
        if (cited.length) L.push(cited.length + " draft report(s) lose the link, keeping their text")
        return L
    }

    MouseArea { anchors.fill: parent; onClicked: dlg.close() }
    Rectangle {
        anchors.centerIn: parent
        width: Math.min(parent.width - 2 * Theme.pad, 620 * Theme.s)
        height: col.implicitHeight + 3 * Theme.pad
        radius: Theme.radius * 1.5
        color: Theme.panel
        border.color: Theme.red
        MouseArea { anchors.fill: parent }
        Column {
            id: col
            x: 1.5 * Theme.pad; y: 1.5 * Theme.pad
            width: parent.width - 3 * Theme.pad
            spacing: Theme.gap
            Txt { width: parent.width; kind: "title"
                  text: !dlg.preview ? "Checking…" : dlg.preview.blocked.length ? "Can't delete"
                        : "Permanently delete " + dlg.total + (dlg.total === 1 ? " item" : " items") }
            Txt { width: parent.width; kind: "muted"; visible: !!dlg.preview && !dlg.preview.blocked.length
                  text: "This removes them and their files permanently. Only a backup restore can bring them back." }
            Repeater {
                model: dlg.preview ? dlg.preview.blocked : []
                Txt { width: col.width; color: Theme.amber
                      text: modelData.name + " is named by a confirmed report: "
                            + modelData.reports.map(function(r) { return "“" + r.title + "”" }).join(", ")
                            + ". Archive it instead, or unlink it from the report first." }
            }
            Repeater {
                model: dlg.preview && !dlg.preview.blocked.length ? dlg.lines : []
                Txt { width: col.width; text: "• " + modelData }
            }
            Field {
                id: confirmField
                width: parent.width
                visible: !!dlg.preview && !dlg.preview.blocked.length
                placeholderText: "Type " + dlg.word + " to confirm"
                inputMethodHints: Qt.ImhUppercaseOnly | Qt.ImhNoPredictiveText
            }
            Row {
                anchors.right: parent.right
                spacing: Theme.gap
                Btn { text: dlg.preview && dlg.preview.blocked.length ? "Close" : "Cancel"; onClicked: dlg.close() }
                Btn {
                    visible: !!dlg.preview && !dlg.preview.blocked.length
                    kind: "danger"
                    enabled: confirmField.text.trim() === dlg.word && !dlg.busy
                    text: "Delete " + (dlg.total === 1 ? "it" : "them") + " permanently"
                    onClicked: {
                        dlg.busy = true
                        Net.post("/api/admin/delete", dlg.body).then(function(res) {
                            dlg.busy = false
                            var parts = []
                            if (res.entities.length) parts.push(res.entities.length + " record(s)")
                            if (res.reports.length) parts.push(res.reports.length + " report(s)")
                            if (res.documents.length) parts.push(res.documents.length + " document(s)")
                            ui.toast("Deleted " + parts.join(", ") + " for good")
                            var done = dlg.onDone
                            dlg.close()
                            if (done) done(res)
                        }).catch(function(e) { dlg.busy = false; ui.toast(e.message, true) })
                    }
                }
            }
        }
    }
}
