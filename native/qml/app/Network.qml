import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Humint
import ".."
import "../lib/fmt.js" as Fmt

// The case file as one picture (api/graph.py): the records that many things
// point at are the big dots. Filter by type or name, or focus on one record
// to see everything it links to — directly, or two steps out. Tap a record
// to see what it is; double-tap to focus on it.
Rectangle {
    id: page
    color: Theme.bg
    property string type: ""
    property var focusId: shell.arg && shell.arg.focus ? shell.arg.focus : null
    property int depth: 1
    property var history: []
    property var result: null
    property var selected: null
    property bool hideIsolated: false
    property bool archived: false
    property bool expiredLinks: false
    readonly property var types: [["", "All"], ["person", "People"], ["organization", "Organisations"], ["location", "Places"],
                                  ["event", "Events"], ["source", "Sources"], ["communication", "Channels"], ["vehicle", "Vehicles"],
                                  ["record", "Records"], ["zone", "Zones"], ["route", "Routes"]]

    function load() {
        var q = { active_only: !page.archived, include_expired_links: page.expiredLinks || "" }
        if (page.focusId) { q.focus = page.focusId; q.depth = page.depth }
        else { q.entity_type = page.type; q.q = search.text.trim() }
        Net.get("/api/entities/graph" + Net.qs(q)).then(function(r) {
            page.result = r
            page.selected = null
            graph.selectedId = null
            graph.focusId = r.focus ? r.focus.id : null
            graph.labelCount = r.focus ? Math.min(40, r.nodes.filter(function(n) { return n.steps <= 1 }).length) : 8
            graph.maxDegree = Math.max(1, r.max_degree || 1)
            graph.edges = r.edges || []
            graph.nodes = (r.nodes || []).filter(function(n) { return page.focusId || !page.hideIsolated || n.degree > 0 })
        }).catch(function(e) {
            // A record merged away or deleted since: back to the whole picture.
            if (page.focusId) { ui.toast(e.message, true); page.focusId = null; page.history = []; page.load() }
            else ui.toast(e.message, true)
        })
    }
    function focusOn(id, keepHistory) {
        if (page.focusId && !keepHistory) page.history = page.history.concat([page.focusId])
        page.focusId = id
        load()
    }
    function showAll() { page.focusId = null; page.history = []; load() }
    Component.onCompleted: load()
    Timer { id: delay; interval: 300; onTriggered: page.load() }

    readonly property int shown: graph.nodes.length
    readonly property string summary: !page.result ? "" : page.result.focus
        ? (page.result.nodes.filter(function(n) { return n.steps === 1 }).length + " linked"
           + (page.result.depth === 2 ? " · " + page.result.nodes.filter(function(n) { return n.steps === 2 }).length + " more one step further" : "")
           + (page.result.truncated ? " · trimmed to fit" : ""))
        : page.result.truncated ? page.shown + " most-linked of " + page.result.total + " · " + graph.edges.length + " links"
        : page.shown + (page.shown === 1 ? " record" : " records") + " · " + graph.edges.length + (graph.edges.length === 1 ? " link" : " links")

    ColumnLayout {
        anchors.fill: parent; anchors.margins: Theme.pad
        spacing: Theme.gap
        PageHeader {
            Layout.fillWidth: true
            back: true
            onBackClicked: shell.back()
            title: "Network"
            subtitle: page.summary
            Check { text: "Archived too"; checked: page.archived; onToggled: { page.archived = checked; page.load() } }
            Check { text: "Expired links"; checked: page.expiredLinks; onToggled: { page.expiredLinks = checked; page.load() } }
        }

        // The whole picture: by type and name.
        RowLayout {
            Layout.fillWidth: true; spacing: 8 * Theme.s
            visible: !page.focusId
            Flow {
                Layout.fillWidth: true; spacing: 4 * Theme.s
                Repeater { model: page.types
                           Btn { compact: true; text: modelData[1]; kind: page.type === modelData[0] ? "primary" : "normal"
                                 onClicked: { page.type = modelData[0]; page.load() } } }
            }
        }
        RowLayout {
            Layout.fillWidth: true; spacing: 8 * Theme.s
            visible: !page.focusId
            Field { id: search; Layout.fillWidth: true; placeholderText: "Only records named…"; onTextChanged: delay.restart() }
            Check { text: "Hide unconnected"; checked: page.hideIsolated; onToggled: { page.hideIsolated = checked; page.load() } }
        }

        // Focused on one record.
        Rectangle {
            Layout.fillWidth: true
            visible: !!page.focusId && !!page.result && !!page.result.focus
            implicitHeight: fb.implicitHeight + 16 * Theme.s
            radius: Theme.radius; color: Theme.panel; border.color: Theme.accentDim
            Flow {
                id: fb
                x: 10 * Theme.s; y: 8 * Theme.s; width: parent.width - 20 * Theme.s
                spacing: 8 * Theme.s
                readonly property var f: page.result && page.result.focus ? page.result.focus : ({})
                Btn { compact: true; kind: "ghost"; visible: page.history.length > 0; text: "◀ Back"
                      onClicked: { var h = page.history.slice(); var id = h.pop(); page.history = h; page.focusOn(id, true) } }
                Txt { height: 34 * Theme.s; verticalAlignment: Text.AlignVCenter; kind: "label"; text: "Focused on" }
                Pill { anchors.verticalCenter: undefined; y: 6 * Theme.s; text: Fmt.typeLabel(fb.f.entity_type); tone: Theme.kindColor(fb.f.entity_type) }
                Txt { height: 34 * Theme.s; verticalAlignment: Text.AlignVCenter; font.weight: Font.DemiBold; text: fb.f.name || "" }
                Btn { compact: true; text: "Direct links"; kind: page.depth === 1 ? "primary" : "normal"; onClicked: { page.depth = 1; page.load() } }
                Btn { compact: true; text: "Two steps out"; kind: page.depth === 2 ? "primary" : "normal"; onClicked: { page.depth = 2; page.load() } }
                Btn { compact: true; text: "Open record"; onClicked: shell.go("entity", fb.f.id) }
                Btn { compact: true; kind: "ghost"; text: "✕ Show everything"; onClicked: page.showAll() }
            }
        }

        Rectangle {
            Layout.fillWidth: true; Layout.fillHeight: true
            radius: Theme.radius * 1.4; color: Theme.panel2; border.color: Theme.border
            clip: true
            NetworkGraph {
                id: graph
                anchors.fill: parent
                onPicked: function(n) { page.selected = n }
                onDoubleTapped: function(n) { if (n.id !== page.focusId) page.focusOn(n.id) }
            }
            Txt { anchors.centerIn: parent; visible: !!page.result && page.shown <= (page.focusId ? 1 : 0); kind: "muted"
                  text: page.focusId ? ((page.result && page.result.focus ? page.result.focus.name : "This record") + " has no " + (page.expiredLinks ? "" : "live ") + "links yet.")
                        : page.hideIsolated && page.result && page.result.nodes.length ? "Every record here is unconnected. Untick “Hide unconnected” to see them."
                        : "Nothing to draw yet." }
            Txt { anchors.left: parent.left; anchors.top: parent.top; anchors.margins: 10 * Theme.s
                  visible: graph.settling; kind: "muted"; text: "Arranging…" }
            Txt { anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 10 * Theme.s; kind: "muted"
                  text: "Drag to move · wheel or pinch to zoom · tap a record · double-tap to focus on it" }

            // The record tapped.
            Rectangle {
                anchors.left: parent.left; anchors.bottom: parent.bottom; anchors.margins: 10 * Theme.s
                visible: !!page.selected
                width: Math.min(parent.width - 20 * Theme.s, 420 * Theme.s)
                implicitHeight: sc.implicitHeight + 2 * Theme.pad
                radius: Theme.radius * 1.4; color: Theme.panel; border.color: Theme.borderStrong
                ColumnLayout {
                    id: sc
                    x: Theme.pad; y: Theme.pad; width: parent.width - 2 * Theme.pad
                    spacing: 6 * Theme.s
                    readonly property var n: page.selected || ({})
                    RowLayout {
                        Layout.fillWidth: true
                        Pill { text: Fmt.typeLabel(sc.n.entity_type); tone: Theme.kindColor(sc.n.entity_type) }
                        Txt { Layout.fillWidth: true; font.weight: Font.DemiBold; text: sc.n.name || "" }
                        Pill { visible: !!sc.n.alignment; text: sc.n.alignment || ""; tone: sc.n.alignment === "Hostile" ? Theme.red : Theme.muted }
                    }
                    Txt { kind: "muted"
                          text: (sc.n.degree || 0) + ((sc.n.degree || 0) === 1 ? " link" : " links") + " in the case file"
                                + (sc.n.is_active === false ? " · archived" : "")
                                + (sc.n.steps === 2 ? " · two steps from the focus" : "") }
                    Row {
                        spacing: 6 * Theme.s
                        Btn { compact: true; kind: "primary"; text: "Open"; onClicked: shell.go("entity", sc.n.id) }
                        Btn { compact: true; text: "Focus on it"; visible: sc.n.id !== page.focusId; onClicked: page.focusOn(sc.n.id) }
                    }
                }
            }
        }
    }
}
