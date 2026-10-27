import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Humint
import ".."
import "../lib/fmt.js" as Fmt
import "../lib/schema.js" as Schema

// One record: who or what it is, how to reach it, who it is connected to,
// the reports that name it, its files. Edit, export, archive, delete.
Rectangle {
    id: page
    color: Theme.bg
    property var e: null
    property string error: ""
    readonly property var d: e ? (e.details || {}) : ({})

    function load() {
        Net.get("/api/entities/" + shell.arg).then(function(r) { page.e = r; page.error = "" })
            .catch(function(err) { page.error = err.message })
    }
    Component.onCompleted: load()

    function exportShape(shape) {
        usb.exportFile("/api/entities/" + e.id + "/dossier.pdf?shape=" + shape,
                       e.name.replace(/[^A-Za-z0-9._-]+/g, "-") + "-" + shape + ".pdf")
    }
    readonly property var shapeOrder: e ? (({ organization: ["org", "target", "plain"], person: ["target", "plain", "org"] })[e.entity_type]
                                           || ["plain", "target", "org"]) : []
    readonly property var shapes: ({ org: "Organisation report", target: "Target package", plain: "Plain dossier" })

    Flickable {
        anchors.fill: parent
        contentHeight: col.implicitHeight + 2 * Theme.pad
        clip: true
        ScrollBar.vertical: ScrollBar {}
        ColumnLayout {
            id: col
            x: Theme.pad; y: Theme.pad
            width: Math.min(parent.width - 2 * Theme.pad, 1040 * Theme.s)
            spacing: Theme.gap

            PageHeader {
                Layout.fillWidth: true
                back: true; onBackClicked: shell.back()
                title: page.e ? page.e.name : (page.error || "Loading…")
                Btn { compact: true; text: "Network around this"; visible: !!page.e; onClicked: shell.go("network", { focus: page.e.id }) }
                Btn { compact: true; text: "Edit"; visible: !!page.e && !shell.viewer; onClicked: shell.go("entityEdit", page.e) }
                Btn { compact: true; text: "Export ▾"; visible: !!page.e; onClicked: exportMenu.open() }
                Btn { compact: true; text: page.e && page.e.is_active ? "Archive" : "Reactivate"; visible: !!page.e && !shell.viewer
                      onClicked: Net.patch("/api/entities/" + page.e.id, { is_active: !page.e.is_active }).then(function() {
                          ui.toast(page.e.is_active ? "Archived" : "Reactivated"); page.load()
                      }).catch(function(err) { ui.toast(err.message, true) }) }
                Btn { compact: true; kind: "danger"; text: "Delete"; visible: !!page.e && shell.admin
                      onClicked: ui.deleteRecords({ entity_ids: [page.e.id] }, function() { shell.back() }) }
            }
            Menu {
                id: exportMenu
                Repeater {
                    model: page.shapeOrder
                    MenuItem { text: page.shapes[modelData] + (index === 0 ? "  (suggested)" : ""); onTriggered: page.exportShape(modelData) }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                visible: !!page.e
                spacing: Theme.gap * 1.5
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 8 * Theme.s
                    Flow {
                        Layout.fillWidth: true; spacing: 6 * Theme.s
                        Pill { text: page.e ? Fmt.typeLabel(page.e.entity_type) : ""; tone: Theme.kindColor(page.e ? page.e.entity_type : "") }
                        Pill { visible: !!page.e && !page.e.is_active; text: "archived"; tone: Theme.muted }
                        Pill { visible: !!page.d.alignment; text: page.d.alignment || ""
                               tone: ({ Hostile: Theme.red, Friendly: Theme.accent, Neutral: Theme.teal })[page.d.alignment] || Theme.muted }
                        Repeater { model: page.e ? Schema.badges(page.e) : []; Pill { text: modelData; tone: Theme.amber } }
                    }
                    Txt { Layout.fillWidth: true; visible: !!(page.e && page.e.description); text: page.e ? (page.e.description || "") : ""
                          font.family: Theme.prose }
                    Txt { Layout.fillWidth: true; visible: !!(page.e && page.e.retention_due_at); color: Theme.amber
                          text: page.e && page.e.retention_due_at
                                ? "Nobody has touched this record inside its type's retention window, so it is due to be archived on "
                                  + Fmt.exactDate(page.e.retention_due_at) + ". Editing it, linking it, or naming it in a report calls that off." : "" }
                    Btn { compact: true; visible: !!page.e && !shell.viewer
                          text: page.e && page.e.retention_hold ? "Let it age" : "Keep indefinitely"
                          onClicked: Net.post("/api/entities/" + page.e.id + "/retention-hold", { hold: !page.e.retention_hold }).then(function() {
                              ui.toast(page.e.retention_hold ? "No longer held — the retention policy applies again" : "Held — this record will not age out")
                              page.load()
                          }).catch(function(err) { ui.toast(err.message, true) }) }
                }
                // Portrait
                Rectangle {
                    visible: !!(page.e && page.e.portrait_attachment_id)
                    Layout.preferredWidth: 160 * Theme.s; Layout.preferredHeight: 200 * Theme.s
                    radius: Theme.radius; color: Theme.panel2; border.color: Theme.border; clip: true
                    Image { anchors.fill: parent; fillMode: Image.PreserveAspectCrop; asynchronous: true
                            source: page.e && page.e.portrait_attachment_id
                                    ? "image://api/api/attachments/" + page.e.portrait_attachment_id + "/file?inline=1" : "" }
                }
            }

            // Details
            Card {
                Layout.fillWidth: true
                visible: !!page.e
                title: "Details"
                implicitHeight: detailsCol.implicitHeight + 2 * padding + Theme.gap + 20 * Theme.s
                Column {
                    id: detailsCol
                    width: parent.width
                    spacing: 6 * Theme.s
                    readonly property var rows: page.e ? Schema.detailRows(page.e.entity_type, page.d) : []
                    Txt { visible: detailsCol.rows.length === 0; kind: "muted"; text: "No additional details." }
                    Repeater {
                        model: detailsCol.rows
                        RowLayout {
                            width: detailsCol.width
                            Txt { Layout.preferredWidth: 220 * Theme.s; kind: "muted"; text: modelData.label }
                            Txt { Layout.fillWidth: true; text: modelData.value
                                  font.family: modelData.mono ? "IBM Plex Mono" : Theme.ui
                                  textFormat: Text.PlainText }
                        }
                    }
                    Btn { compact: true; visible: !!page.e && page.e.entity_type === "location" && page.d.lat !== undefined && page.d.lat !== null
                          text: "Show on the map"; onClicked: shell.go("map", { lat: page.d.lat, lng: page.d.lng, focus: page.e.id }) }
                }
            }

            // Source protection (sources only)
            Loader {
                Layout.fillWidth: true
                active: !!page.e && page.e.entity_type === "source"
                source: "SourceProtection.qml"
            }

            // Contacts
            Card {
                Layout.fillWidth: true
                visible: !!page.e && Schema.CONTACTABLE_TYPES.indexOf(page.e.entity_type) >= 0
                title: "Contact"
                implicitHeight: contactCol.implicitHeight + 2 * padding + Theme.gap + 20 * Theme.s
                Column {
                    id: contactCol
                    width: parent.width
                    spacing: 6 * Theme.s
                    Txt { visible: !page.e || !(page.e.contacts || []).length; kind: "muted"; text: "None recorded." }
                    Repeater {
                        model: page.e ? (page.e.contacts || []) : []
                        RowLayout {
                            width: contactCol.width
                            Pill { text: modelData.kind; tone: Theme.teal }
                            Txt { visible: !!modelData.label; kind: "muted"; text: modelData.label || ""; wrapMode: Text.NoWrap }
                            Txt { Layout.fillWidth: true; text: modelData.value + (modelData.notes ? "  — " + modelData.notes : ""); font.family: "IBM Plex Mono" }
                            Pill { visible: modelData.is_preferred; text: "preferred"; tone: Theme.accent }
                            Btn { compact: true; kind: "ghost"; text: "Edit"; visible: !shell.viewer
                                  onClicked: contactForm.open(page.e, modelData) }
                            Btn { compact: true; kind: "ghost"; text: "Remove"; visible: !shell.viewer
                                  onClicked: ui.confirm("Remove this contact detail?", modelData.value, function() {
                                      Net.del("/api/contacts/" + modelData.id).then(page.load).catch(function(err) { ui.toast(err.message, true) })
                                  }) }
                        }
                    }
                    Btn { compact: true; text: "+ Add contact"; visible: !shell.viewer; onClicked: contactForm.open(page.e, null) }
                }
            }

            // Relationships
            Card {
                Layout.fillWidth: true
                visible: !!page.e
                title: "Relationships"
                implicitHeight: relCol.implicitHeight + 2 * padding + Theme.gap + 20 * Theme.s
                Column {
                    id: relCol
                    width: parent.width
                    spacing: 6 * Theme.s
                    Txt { visible: !page.e || !page.e.relationships.length; kind: "muted"; text: "None yet." }
                    Repeater {
                        model: page.e ? page.e.relationships : []
                        RowLayout {
                            width: relCol.width
                            opacity: modelData.expired ? 0.55 : 1
                            Txt { text: modelData.direction === "outgoing" ? "→" : "←"; color: Theme.muted; wrapMode: Text.NoWrap }
                            Txt { text: Schema.relWording(modelData); font.weight: Font.DemiBold; wrapMode: Text.NoWrap }
                            Btn { compact: true; kind: "ghost"; text: modelData.other_entity_name
                                  onClicked: shell.go("entity", modelData.other_entity_id) }
                            Pill { text: Fmt.typeLabel(modelData.other_entity_type); tone: Theme.kindColor(modelData.other_entity_type) }
                            Pill { visible: !!modelData.confidence; text: modelData.confidence + " · " + Schema.confidenceLabel(modelData.confidence)
                                   tone: Number(modelData.confidence) <= 2 ? Theme.accent : Number(modelData.confidence) <= 3 ? Theme.teal : Theme.amber }
                            Txt { visible: !!modelData.expired; kind: "muted"; text: "expired " + (modelData.expires_on || ""); wrapMode: Text.NoWrap }
                            Item { Layout.fillWidth: true }
                            Btn { compact: true; kind: "ghost"; text: "Remove"; visible: !shell.viewer
                                  onClicked: ui.confirm("Remove this relationship?", "", function() {
                                      Net.del("/api/relationships/" + modelData.id).then(page.load).catch(function(err) { ui.toast(err.message, true) })
                                  }) }
                        }
                    }
                    Btn { compact: true; text: "+ Add relationship"; visible: !shell.viewer; onClicked: relForm.open(page.e) }
                }
            }

            // Linked reports
            Card {
                Layout.fillWidth: true
                visible: !!page.e
                title: "Linked reports"
                implicitHeight: repCol.implicitHeight + 2 * padding + Theme.gap + 20 * Theme.s
                Column {
                    id: repCol
                    width: parent.width
                    spacing: 6 * Theme.s
                    Txt { visible: !page.e || !page.e.reports.length; kind: "muted"; text: "None yet." }
                    Repeater {
                        model: page.e ? page.e.reports : []
                        RowLayout {
                            width: repCol.width
                            Pill { text: modelData.status; tone: Theme.statusColor(modelData.status) }
                            Btn { compact: true; kind: "ghost"; text: modelData.title; onClicked: shell.go("report", modelData.id) }
                            Item { Layout.fillWidth: true }
                        }
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                visible: !!page.e
                Txt { kind: "label"; text: "Attachments"; Layout.fillWidth: true }
                Btn { compact: true; text: "+ From USB"; visible: !shell.viewer
                      onClicked: usb.pickFile(function(path) {
                          ui.busy("Uploading…")
                          Net.upload("/api/attachments", path, { entity_id: String(page.e.id) }).then(function() {
                              ui.busy(""); ui.toast("Uploaded"); page.load()
                          }).catch(function(err) { ui.busy(""); ui.toast(err.message, true) })
                      }) }
            }
            AttachmentList {
                Layout.fillWidth: true
                visible: !!page.e
                items: page.e ? (page.e.attachments || []) : []
                canDelete: !shell.viewer
                portraitFor: page.e ? page.e.id : ""
                portraitId: page.e ? (page.e.portrait_attachment_id || 0) : 0
                onChanged: page.load()
            }
        }
    }

    ContactForm { id: contactForm; onSaved: page.load() }
    RelationshipForm { id: relForm; onSaved: page.load() }
}
