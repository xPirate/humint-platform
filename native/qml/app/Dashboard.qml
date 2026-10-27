import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Humint
import ".."
import "../lib/fmt.js" as Fmt

// The case file at a glance, as the console's dashboard: what needs
// attention, where activity clusters, how busy reporting is, which names
// are rising, what came in last.
Rectangle {
    id: page
    color: Theme.bg
    property var summary: null
    property var ins: null
    property int days: 14
    property date now: new Date()
    Timer { interval: 1000; running: true; repeat: true; onTriggered: page.now = new Date() }

    function load() {
        Net.get("/api/dashboard/summary").then(function(r) { page.summary = r }).catch(function(e) { ui.toast(e.message, true) })
        Net.get("/api/dashboard/insights" + Net.qs({ days: page.days })).then(function(r) { page.ins = r }).catch(function() {})
    }
    Component.onCompleted: load()
    Timer { interval: 60000; running: true; repeat: true; onTriggered: page.load() }

    readonly property var na: ins ? ins.needs_attention : null

    component Section: Card {
        Layout.fillWidth: true
        Layout.alignment: Qt.AlignTop
        implicitHeight: inner_.implicitHeight + 2 * padding + Theme.gap + 20 * Theme.s
        default property alias body: inner_.data
        Column { id: inner_; width: parent.width; spacing: 6 * Theme.s }
    }
    component LinkRow: AbstractButton {
        id: lr
        property string label: ""
        property string meta: ""
        property alias pills: pillRow.data
        width: parent ? parent.width : 300
        implicitHeight: lrCol.implicitHeight + 8 * Theme.s
        hoverEnabled: true
        background: Rectangle { color: lr.hovered ? Theme.panel2 : "transparent"; radius: Theme.radius }
        contentItem: Item {
            Column {
                id: lrCol
                x: 4 * Theme.s; y: 4 * Theme.s; width: lr.width - 8 * Theme.s
                Row { spacing: 6 * Theme.s
                    Row { id: pillRow; spacing: 4 * Theme.s }
                    Txt { text: lr.label; wrapMode: Text.NoWrap; elide: Text.ElideRight; width: Math.min(implicitWidth, lrCol.width - pillRow.width - 10 * Theme.s) } }
                Txt { width: parent.width; visible: lr.meta !== ""; kind: "muted"; text: lr.meta; wrapMode: Text.NoWrap; elide: Text.ElideRight }
            }
        }
    }

    Flickable {
        anchors.fill: parent
        contentHeight: col.implicitHeight + 2 * Theme.pad
        clip: true
        ScrollBar.vertical: ScrollBar {}
        ColumnLayout {
            id: col
            x: Theme.pad; y: Theme.pad
            width: parent.width - 2 * Theme.pad
            spacing: Theme.gap

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.gap
                // Clock
                Card {
                    Layout.preferredWidth: 280 * Theme.s; Layout.fillHeight: true
                    implicitHeight: 130 * Theme.s
                    Column {
                        width: parent.width
                        Txt { text: Qt.formatTime(page.now, "HH:mm:ss"); font.pixelSize: 38 * Theme.s; color: Theme.accent; font.family: "IBM Plex Mono" }
                        Txt { kind: "muted"; text: Qt.formatDate(page.now, "dddd d MMMM yyyy") }
                        Txt { kind: "muted"; font.family: "IBM Plex Mono"
                              text: "UTC " + page.now.toISOString().slice(11, 16) }
                    }
                }
                // At a glance
                Card {
                    Layout.fillWidth: true; Layout.fillHeight: true
                    title: "At a glance"
                    implicitHeight: 130 * Theme.s
                    RowLayout {
                        width: parent.width
                        Repeater {
                            model: page.summary ? [[page.summary.counts.entities, "Records", "entities", false],
                                                   [page.summary.counts.reports, "Reports", "reports", false],
                                                   [page.summary.counts.pending_extraction, "Suggestions waiting", "review", true],
                                                   [page.summary.counts.pending_correlation, "Possible duplicates", "review", true]] : []
                            AbstractButton {
                                Layout.fillWidth: true
                                onClicked: shell.go(modelData[2])
                                contentItem: Column {
                                    Txt { text: String(modelData[0]); font.pixelSize: 30 * Theme.s
                                          color: modelData[3] && modelData[0] > 0 ? Theme.amber : Theme.text }
                                    Txt { kind: "label"; text: modelData[1] }
                                }
                                background: Item {}
                            }
                        }
                    }
                }
            }

            // Needs attention
            GridLayout {
                Layout.fillWidth: true
                columns: width > 1000 * Theme.s ? 4 : 2
                columnSpacing: Theme.gap; rowSpacing: Theme.gap
                Section {
                    title: "Urgent (" + (page.na ? page.na.urgent_reports.length : 0) + ")"
                    Txt { width: parent.width; visible: !!page.na && !page.na.urgent_reports.length; kind: "muted"; text: "Nothing filed Flash or Immediate." }
                    Repeater { model: page.na ? page.na.urgent_reports.slice(0, 6) : []
                        LinkRow { label: modelData.title; meta: Fmt.relativeTime(modelData.created_at)
                                  pills: [ Pill { text: modelData.criticality || ""; tone: Theme.critColor(modelData.criticality); filled: modelData.criticality === "Flash" } ]
                                  onClicked: shell.go("report", modelData.id) } }
                }
                Section {
                    title: "Forgotten drafts (" + (page.na ? page.na.stale_drafts.length : 0) + ")"
                    Txt { width: parent.width; visible: !!page.na && !page.na.stale_drafts.length; kind: "muted"
                          text: page.na ? "No draft untouched for " + page.na.stale_draft_days + " days." : "" }
                    Repeater { model: page.na ? page.na.stale_drafts.slice(0, 6) : []
                        LinkRow { label: modelData.title; meta: "last touched " + Fmt.relativeTime(modelData.updated_at)
                                  onClicked: shell.go("report", modelData.id) } }
                }
                Section {
                    title: "Ageing out (" + (page.na ? page.na.expiring_events.length : 0) + ")"
                    Txt { width: parent.width; visible: !!page.na && !page.na.expiring_events.length; kind: "muted"
                          text: page.na ? "Nothing lapsing within " + page.na.expiring_within_days + " days." : "" }
                    Repeater { model: page.na ? page.na.expiring_events.slice(0, 6) : []
                        LinkRow { label: modelData.name; meta: (modelData.already_expired ? "expired " : "relevant until ") + Fmt.exactDate(modelData.expires_at)
                                  onClicked: shell.go("entity", modelData.id) } }
                }
                Section {
                    title: "People (" + (page.na ? page.na.people_of_concern.length : 0) + ")"
                    Txt { width: parent.width; visible: !!page.na && !page.na.people_of_concern.length; kind: "muted"
                          text: "Nobody recorded as captured, detained, missing or evading." }
                    Repeater { model: page.na ? page.na.people_of_concern.slice(0, 6) : []
                        LinkRow { label: modelData.name; meta: [modelData.disposition, modelData.life_status].filter(function(x) { return x }).join(" · ")
                                  onClicked: shell.go("entity", modelData.id) } }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.gap
                Txt { kind: "label"; text: "Window" }
                Repeater {
                    model: [7, 14, 30, 90]
                    Btn { compact: true; text: modelData + " days"; kind: page.days === modelData ? "primary" : "normal"
                          onClicked: { page.days = modelData; page.load() } }
                }
                Item { Layout.fillWidth: true }
            }

            GridLayout {
                Layout.fillWidth: true
                columns: width > 1000 * Theme.s ? 3 : 1
                columnSpacing: Theme.gap; rowSpacing: Theme.gap
                // Hotspots
                Section {
                    title: "Hotspots"
                    Txt { width: parent.width; kind: "muted"; text: "Locations that several records point at in this period." }
                    Txt { width: parent.width; visible: !!page.ins && !page.ins.hotspots.length; kind: "muted"; text: "No location stands out in this window." }
                    Repeater {
                        model: page.ins ? page.ins.hotspots.slice(0, 6) : []
                        Column {
                            width: parent.width
                            RowLayout {
                                width: parent.width
                                LinkRow { Layout.fillWidth: true; label: modelData.name; onClicked: shell.go("entity", modelData.id) }
                                Rectangle { Layout.preferredWidth: 90 * Theme.s; height: 8 * Theme.s; radius: height / 2; color: Theme.panel2
                                    Rectangle { height: parent.height; radius: height / 2; color: Theme.amber
                                                width: parent.width * modelData.total / Math.max(1, page.ins.hotspots[0].total) } }
                                Txt { text: String(modelData.total); wrapMode: Text.NoWrap }
                                Btn { compact: true; text: "PDF"
                                      onClicked: usb.exportFile("/api/exports/hotspots/" + encodeURIComponent(modelData.id) + "/package.pdf?days=" + page.days,
                                                                "hotspot-" + modelData.name.replace(/[^A-Za-z0-9._-]+/g, "-") + ".pdf") }
                            }
                        }
                    }
                }
                // Tempo
                Section {
                    title: "Reporting tempo"
                    Row {
                        width: parent.width; height: 80 * Theme.s
                        spacing: 3 * Theme.s
                        readonly property var weeks: page.ins ? page.ins.tempo.weeks || [] : []
                        readonly property int peak: Math.max(1, page.ins ? page.ins.tempo.peak || 0 : 1)
                        Repeater {
                            model: parent.weeks
                            Rectangle {
                                width: Math.max(4 * Theme.s, (parent.width - parent.weeks.length * 3 * Theme.s) / Math.max(1, parent.weeks.length))
                                height: parent.height; color: "transparent"
                                Rectangle { anchors.bottom: parent.bottom; width: parent.width; radius: 2 * Theme.s
                                            height: Math.max(modelData.reports ? 6 : 2, parent.height * modelData.reports / parent.parent.peak)
                                            color: index === parent.parent.weeks.length - 1 ? Theme.accent : Theme.accentDim }
                            }
                        }
                    }
                    Txt {
                        width: parent.width; kind: "muted"
                        readonly property int cur: page.ins ? page.ins.tempo.current || 0 : 0
                        readonly property int med: page.ins ? page.ins.tempo.median || 0 : 0
                        text: "This week: " + cur + " · median of the previous weeks: " + med + " — "
                              + (cur > med * 2 && cur >= 3 ? "well above the recent norm" : cur > med ? "above the recent norm"
                                 : cur < med ? "below the recent norm" : "in line with the last few weeks") + "."
                    }
                }
                // Rising
                Section {
                    title: "Rising"
                    Txt { visible: !!page.ins && !page.ins.rising.length; width: parent.width; kind: "muted"
                          text: "Nothing named more often than in the previous window." }
                    Repeater { model: page.ins ? page.ins.rising.slice(0, 6) : []
                        LinkRow { label: modelData.name
                                  meta: modelData.current + " this " + page.days + " days, " + modelData.previous + " the " + page.days + " before — +" + modelData.delta
                                  pills: [ Pill { text: Fmt.typeLabel(modelData.entity_type); tone: Theme.kindColor(modelData.entity_type) } ]
                                  onClicked: shell.go("entity", modelData.id) } }
                }
            }

            GridLayout {
                Layout.fillWidth: true
                columns: width > 900 * Theme.s ? 2 : 1
                columnSpacing: Theme.gap; rowSpacing: Theme.gap
                Section {
                    title: "Recent reports"
                    Txt { width: parent.width; visible: !!page.summary && !page.summary.recent_reports.length; kind: "muted"; text: "No reports yet." }
                    Repeater { model: page.summary ? page.summary.recent_reports : []
                        LinkRow { label: modelData.title; meta: Fmt.relativeTime(modelData.created_at)
                                  pills: [ Pill { text: modelData.status; tone: Theme.statusColor(modelData.status) } ]
                                  onClicked: shell.go("report", modelData.id) } }
                }
                Section {
                    title: "Recent records"
                    Txt { width: parent.width; visible: !!page.summary && !page.summary.recent_entities.length; kind: "muted"; text: "No records yet." }
                    Repeater { model: page.summary ? page.summary.recent_entities : []
                        LinkRow { label: modelData.name; meta: Fmt.relativeTime(modelData.created_at)
                                  pills: [ Pill { text: Fmt.typeLabel(modelData.entity_type); tone: Theme.kindColor(modelData.entity_type) } ]
                                  onClicked: shell.go("entity", modelData.id) } }
                }
            }
        }
    }
}
