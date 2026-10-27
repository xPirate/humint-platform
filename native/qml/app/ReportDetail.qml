import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Humint
import ".."
import "../lib/fmt.js" as Fmt

// One report, read as a document: its body with record mentions you can
// tap, the records it names, its files.
Rectangle {
    id: page
    color: Theme.bg
    property var report: null
    property string author: ""      // the report has the author's id; the name is looked up
    property string error: ""

    function load() {
        Net.get("/api/reports/" + shell.arg).then(function(r) {
            page.report = r; page.error = ""
            if (r.author_id) Net.get("/api/analysts").then(function(d) {
                var u = (d.items || []).filter(function(x) { return x.id === r.author_id })[0]
                page.author = u ? u.username : ""
            }).catch(function() {})
        })
            .catch(function(e) { page.error = e.message })
    }
    Component.onCompleted: load()

    Flickable {
        anchors.fill: parent
        contentHeight: col.implicitHeight + 2 * Theme.pad
        clip: true
        ScrollBar.vertical: ScrollBar {}
        ColumnLayout {
            id: col
            x: Theme.pad; y: Theme.pad
            width: Math.min(parent.width - 2 * Theme.pad, 980 * Theme.s)
            spacing: Theme.gap

            PageHeader {
                Layout.fillWidth: true
                back: true; onBackClicked: shell.back()
                title: page.report ? page.report.title : (page.error || "Loading…")
                Btn { compact: true; text: "Edit"; visible: !!page.report && !shell.viewer
                      onClicked: shell.go("reportEdit", page.report) }
                Btn { compact: true; text: "Export PDF"; visible: !!page.report
                      onClicked: usb.exportFile("/api/reports/" + page.report.id + "/export.pdf",
                                                "report-" + page.report.id + ".pdf") }
                Btn { compact: true; kind: "danger"; text: "Delete"; visible: !!page.report && shell.admin
                      onClicked: ui.deleteRecords({ report_ids: [page.report.id] }, function() { shell.back() }) }
            }

            Flow {
                Layout.fillWidth: true
                visible: !!page.report
                spacing: 8 * Theme.s
                Pill { text: page.report ? page.report.status : ""; tone: Theme.statusColor(page.report ? page.report.status : "") }
                Pill { visible: !!(page.report && page.report.criticality); text: page.report ? (page.report.criticality || "") : ""
                       tone: Theme.critColor(page.report ? page.report.criticality : ""); filled: !!page.report && page.report.criticality === "Flash" }
                Txt { visible: !!(page.report && page.report.credibility_rating); kind: "muted"
                      text: page.report && page.report.credibility_rating
                            ? "Credibility " + page.report.credibility_rating + " — " + Fmt.CREDIBILITY[page.report.credibility_rating] : "" }
                Txt { kind: "muted"; visible: !!page.report
                      text: page.report ? "Written " + Fmt.exactTime(page.report.created_at) + (page.author ? " by" : "") : "" }
                // The author: everything they have entered is a tap away.
                Btn { compact: true; kind: "ghost"; visible: page.author !== ""
                      text: page.author
                      onClicked: shell.go("analyst", page.author) }
                Txt { kind: "muted"; visible: !!(page.report && page.report.updated_at && page.report.updated_at !== page.report.created_at)
                      text: page.report && page.report.updated_at ? "· edited " + Fmt.relativeTime(page.report.updated_at) : "" }
            }

            // The body, as a document.
            Rectangle {
                Layout.fillWidth: true
                visible: !!page.report
                implicitHeight: body.implicitHeight + 2 * Theme.pad
                radius: Theme.radius * 1.4
                color: Theme.panel
                border.color: Theme.border
                Text {
                    id: body
                    x: Theme.pad * 1.5; y: Theme.pad
                    width: parent.width - 3 * Theme.pad
                    textFormat: Text.RichText
                    wrapMode: Text.Wrap
                    color: Theme.text
                    font.family: Theme.prose
                    font.pixelSize: (Theme.palette === "archive" ? 17 : 15.5) * Theme.s
                    lineHeight: Theme.palette === "archive" ? 1.5 : 1.35
                    text: page.report ? (Fmt.mdToHtml(page.report.body_markdown, Theme.accent) || "<i>No text.</i>") : ""
                    onLinkActivated: function(link) {
                        var id = Fmt.mentionId(link)
                        if (id) shell.go("entity", id)
                    }
                    HoverHandler { cursorShape: parent.hoveredLink ? Qt.PointingHandCursor : Qt.ArrowCursor }
                }
            }

            Txt { kind: "label"; text: "Linked records"; Layout.topMargin: Theme.gap }
            Flow {
                Layout.fillWidth: true
                spacing: 8 * Theme.s
                Txt { visible: !!page.report && page.report.entities.length === 0; kind: "muted"; text: "None linked." }
                Repeater {
                    model: page.report ? page.report.entities : []
                    Btn {
                        compact: true
                        text: modelData.name
                        sub: Fmt.typeLabel(modelData.entity_type)
                        onClicked: shell.go("entity", modelData.id)
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true; Layout.topMargin: Theme.gap
                Txt { kind: "label"; text: "Attachments"; Layout.fillWidth: true }
                Btn { compact: true; text: "+ From USB"; visible: !!page.report && !shell.viewer
                      onClicked: usb.pickFile(function(path) {
                          ui.busy("Uploading…")
                          Net.upload("/api/attachments", path, { report_id: String(page.report.id) }).then(function() {
                              ui.busy(""); ui.toast("Uploaded"); page.load()
                          }).catch(function(e) { ui.busy(""); ui.toast(e.message, true) })
                      }) }
            }
            AttachmentList {
                Layout.fillWidth: true
                items: page.report ? page.report.attachments : []
                canDelete: !shell.viewer
                onChanged: page.load()
            }
        }
    }
}
