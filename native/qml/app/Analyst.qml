import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Humint
import ".."
import "../lib/fmt.js" as Fmt

// One team member: who they are, their status and how to reach them
// (api/profiles.py — not a record in the case file), and everything they
// have entered, newest first (api/analysts.py). Editable by them and by an
// admin. Opens on your own page when nobody is named.
Rectangle {
    id: page
    color: Theme.bg
    property string who: shell.arg || (Net.me ? Net.me.username : "")
    property var directory: []
    property var profile: null
    property var analyst: null
    property var counts: ({})
    property var items: []
    property int total: 0
    property string kind: ""
    readonly property var kinds: [["", "Everything"], ["entity", "Records"], ["report", "Reports"],
                                  ["relationship", "Links"], ["document", "Documents"], ["field", "Field reports"]]
    readonly property var kindLabel: ({ entity: "Record", report: "Report", relationship: "Link", document: "Document", field: "Field report" })

    function statusColor(s) {
        return ({ "At liberty": Theme.accent, "Under duress": Theme.amber, "Incapacitated": Theme.amber,
                  "Captured": Theme.red, "Deceased": Theme.muted })[s] || Theme.accent
    }

    function loadProfile() {
        Net.get("/api/profiles/" + encodeURIComponent(page.who)).then(function(p) { page.profile = p })
            .catch(function(e) { page.profile = null; ui.toast(e.message, true) })
    }
    function loadItems(reset) {
        if (reset) page.items = []
        var q = { limit: 100, offset: page.items.length, kind: page.kind, q: search.text.trim(),
                  since: since.text.trim(), until: until.text.trim() }
        Net.get("/api/analysts/" + encodeURIComponent(page.who) + "/activity" + Net.qs(q)).then(function(r) {
            page.analyst = r.analyst; page.counts = r.counts || {}; page.total = r.total || 0
            page.items = page.items.concat(r.items || [])
        }).catch(function(e) { ui.toast(e.message, true) })
    }
    function open(name) { page.who = name; page.kind = ""; loadProfile(); loadItems(true) }
    Component.onCompleted: {
        Net.get("/api/analysts").then(function(r) { page.directory = r.items || [] }).catch(function() {})
        loadProfile(); loadItems(true)
    }
    Timer { id: delay; interval: 300; onTriggered: page.loadItems(true) }

    function openItem(it) {
        if (it.kind === "entity") shell.go("entity", it.id)
        else if (it.kind === "report") shell.go("report", it.id)
        else if (it.kind === "relationship") shell.go("entity", it.from_entity_id)
        else if (it.kind === "document") shell.go("document", Number(it.id))
        else if (it.kind === "field") { if (it.report_id) shell.go("report", it.report_id); else shell.go("review") }
    }
    function dayOf(t) { return new Date(t).toLocaleDateString(Qt.locale(), "ddd d MMM yyyy") }

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
                Layout.fillWidth: true; spacing: 8 * Theme.s
                Txt { kind: "label"; text: "Team member" }
                Select {
                    Layout.preferredWidth: 300 * Theme.s
                    value: page.analyst ? page.analyst.username : page.who
                    options: page.directory.map(function(u) { return [u.username, u.username + (u.is_active ? "" : " (deactivated)")] })
                    onPicked: function(v) { page.open(v) }
                }
                Item { Layout.fillWidth: true }
                Txt { kind: "muted"; visible: !!page.analyst
                      text: page.analyst ? (page.analyst.role === "admin" ? "Administrator" : page.analyst.role === "viewer" ? "Read-only" : "Analyst")
                                           + (page.analyst.is_active ? "" : " · deactivated") + " · account made " + Fmt.exactDate(page.analyst.created_at) : "" }
            }

            // Who they are
            Rectangle {
                Layout.fillWidth: true
                visible: !!page.profile
                implicitHeight: pc.implicitHeight + 2 * Theme.pad
                radius: Theme.radius * 1.4; color: Theme.panel
                border.color: page.profile ? page.statusColor(page.profile.status) : Theme.border
                border.width: page.profile && page.profile.status !== "At liberty" ? 2 * Theme.s : 1
                ColumnLayout {
                    id: pc
                    x: Theme.pad; y: Theme.pad; width: parent.width - 2 * Theme.pad
                    spacing: 8 * Theme.s
                    readonly property var p: page.profile || ({})
                    RowLayout {
                        Layout.fillWidth: true; spacing: Theme.gap
                        Rectangle {
                            width: 64 * Theme.s; height: width; radius: width / 2; color: Theme.panel2
                            border.color: page.statusColor(pc.p.status)
                            Txt { anchors.centerIn: parent; font.pixelSize: 24 * Theme.s; font.weight: Font.DemiBold
                                  text: String(pc.p.display_name || pc.p.username || "?").split(/\s+/).slice(0, 2).map(function(w) { return w.charAt(0) }).join("").toUpperCase() }
                        }
                        ColumnLayout {
                            Layout.fillWidth: true; spacing: 2 * Theme.s
                            Txt { Layout.fillWidth: true; kind: "title"; text: pc.p.display_name || pc.p.username || "" }
                            Txt { Layout.fillWidth: true; kind: "muted"
                                  text: [pc.p.display_name ? "@" + pc.p.username : null, pc.p.role_title,
                                         pc.p.callsign ? "callsign " + pc.p.callsign : null].filter(function(x) { return x }).join(" · ") }
                        }
                        ColumnLayout {
                            spacing: 2 * Theme.s
                            Pill { Layout.alignment: Qt.AlignRight; text: pc.p.status || "At liberty"; tone: page.statusColor(pc.p.status)
                                   filled: !!pc.p.status && pc.p.status !== "At liberty" }
                            Txt { Layout.alignment: Qt.AlignRight; kind: "muted"; visible: !!pc.p.status_changed_at
                                  text: "set " + Fmt.relativeTime(pc.p.status_changed_at) + (pc.p.status_changed_by ? " by " + pc.p.status_changed_by : "") }
                        }
                        Btn { compact: true; visible: !!pc.p.can_edit; text: "Edit profile"; onClicked: editor.open(page.profile) }
                    }
                    Txt { Layout.fillWidth: true; visible: !!pc.p.status_note; color: page.statusColor(pc.p.status); text: pc.p.status_note || "" }
                    Grid {
                        Layout.fillWidth: true
                        visible: (pc.p.contacts || []).length > 0
                        columns: 2; columnSpacing: Theme.gap; rowSpacing: 4 * Theme.s
                        Repeater {
                            model: (pc.p.contacts || []).length * 2
                            Txt {
                                readonly property var c: (pc.p.contacts || [])[Math.floor(index / 2)] || ({})
                                kind: index % 2 ? "mono" : "label"
                                text: index % 2 ? c.value + (c.note ? "   " + c.note : "") : c.kind
                            }
                        }
                    }
                    Txt { Layout.fillWidth: true; visible: (pc.p.contacts || []).length === 0; kind: "muted"
                          text: "No contact details yet." + (pc.p.can_edit ? " Edit profile adds them." : "") }
                    Txt { Layout.fillWidth: true; visible: !!pc.p.notes; font.family: Theme.prose; text: pc.p.notes || "" }
                }
            }

            // What they have entered
            Txt { kind: "title"; text: "What " + (page.analyst ? page.analyst.username : page.who) + " has entered" }
            Flow {
                Layout.fillWidth: true; spacing: 6 * Theme.s
                Repeater {
                    model: page.kinds
                    Btn {
                        compact: true
                        kind: page.kind === modelData[0] ? "primary" : "normal"
                        readonly property int n: modelData[0] ? (page.counts[modelData[0]] || 0)
                                                 : Object.keys(page.counts).reduce(function(a, k) { return a + page.counts[k] }, 0)
                        text: modelData[1] + "  " + n
                        onClicked: { page.kind = modelData[0]; page.loadItems(true) }
                    }
                }
            }
            RowLayout {
                Layout.fillWidth: true; spacing: 8 * Theme.s
                Field { id: search; Layout.fillWidth: true; placeholderText: "Search titles"; onTextChanged: delay.restart() }
                Field { id: since; Layout.preferredWidth: 170 * Theme.s; placeholderText: "From YYYY-MM-DD"; mono: true
                        onTextChanged: if (!text || /^\d{4}-\d{2}-\d{2}$/.test(text)) delay.restart() }
                Field { id: until; Layout.preferredWidth: 170 * Theme.s; placeholderText: "To YYYY-MM-DD"; mono: true
                        onTextChanged: if (!text || /^\d{4}-\d{2}-\d{2}$/.test(text)) delay.restart() }
            }
            Txt { visible: page.items.length === 0; kind: "muted"
                  text: "Nothing" + (page.kind ? " of this kind" : "") + " entered" + (search.text || since.text || until.text ? " matches these filters." : " yet.") }
            Repeater {
                model: page.items
                Column {
                    Layout.fillWidth: true
                    spacing: 4 * Theme.s
                    readonly property bool newDay: index === 0 || page.dayOf(page.items[index - 1].created_at) !== page.dayOf(modelData.created_at)
                    Txt { visible: newDay; kind: "label"; topPadding: index ? Theme.gap : 0; text: page.dayOf(modelData.created_at) }
                    AbstractButton {
                        width: parent.width; implicitHeight: row.implicitHeight + 14 * Theme.s
                        text: modelData.title || ""
                        onClicked: page.openItem(modelData)
                        background: Rectangle { radius: Theme.radius; color: parent.hovered ? Theme.panel2 : Theme.panel; border.color: Theme.border }
                        contentItem: RowLayout {
                            id: row
                            spacing: Theme.gap
                            Item { width: 2 }
                            Txt { Layout.preferredWidth: 120 * Theme.s; kind: "label"; text: page.kindLabel[modelData.kind] || modelData.kind }
                            Txt { Layout.fillWidth: true; text: modelData.title || ""; elide: Text.ElideRight; wrapMode: Text.NoWrap }
                            Pill { visible: modelData.kind === "entity"; text: Fmt.typeLabel(modelData.subtype); tone: Theme.kindColor(modelData.subtype) }
                            Pill { visible: modelData.kind !== "entity" && !!modelData.subtype; text: String(modelData.subtype || ""); tone: Theme.muted }
                            Txt { visible: !!modelData.archived || !!modelData.expired; kind: "muted"; text: modelData.archived ? "archived" : "expired" }
                            Txt { kind: "muted"; text: new Date(modelData.created_at).toLocaleTimeString(Qt.locale(), "HH:mm") }
                            Item { width: 2 }
                        }
                    }
                }
            }
            Btn { visible: page.items.length < page.total; text: "Show more"; onClicked: page.loadItems(false) }
        }
    }

    FormDialog {
        id: editor
        property var p: null
        property var contacts: []
        title: "Profile — " + (p ? p.username : "")
        function open(x) {
            p = x
            pName.text = x.display_name || ""; pCall.text = x.callsign || ""; pRole.text = x.role_title || ""
            pStatus.value = x.status || "At liberty"; pNote.text = x.status_note || ""; pNotes.text = x.notes || ""
            contacts = (x.contacts || []).map(function(c) { return { kind: c.kind, value: c.value, note: c.note || "" } })
            if (!contacts.length) contacts = [{ kind: "", value: "", note: "" }]
            visible = true
        }
        // The rows as typed (read from the fields themselves, so nothing
        // depends on a field having lost focus first).
        function rows() {
            var out = []
            for (var i = 0; i < contactRows.count; i++) {
                var r = contactRows.itemAt(i)
                out.push({ kind: r.kindText, value: r.valueText, note: r.noteText })
            }
            return out
        }
        onAccepted: {
            var cs = rows().map(function(c) { return { kind: c.kind.trim(), value: c.value.trim(), note: c.note.trim() || null } })
                             .filter(function(c) { return c.kind || c.value })
            if (cs.some(function(c) { return !c.kind || !c.value })) { error = "Each contact needs both a kind and a value."; return }
            busy = true
            Net.put("/api/profiles/" + encodeURIComponent(p.username), {
                display_name: pName.text, callsign: pCall.text, role_title: pRole.text, status: pStatus.value,
                status_note: pNote.text, contacts: cs, notes: pNotes.text
            }).then(function() { busy = false; close(); ui.toast("Profile saved"); page.loadProfile() })
              .catch(function(e) { busy = false; error = e.message })
        }
        Labeled { label: "Name"; Field { id: pName; width: parent.width; placeholderText: "How the team knows them" } }
        Labeled { label: "Callsign"; Field { id: pCall; width: parent.width } }
        Labeled { label: "Role"; Field { id: pRole; width: parent.width; placeholderText: "e.g. Radio operator" } }
        Labeled { label: "Status"
                  Select { id: pStatus; width: parent.width
                           options: ((editor.p && editor.p.statuses) || ["At liberty"]).map(function(s) { return [s, s] }) } }
        Labeled { label: "Status note"; Field { id: pNote; width: parent.width; placeholderText: "What is known, and when it was last confirmed" } }
        Labeled {
            label: "Contact details"
            hint: "As many or as few as they use. " + ((editor.p && editor.p.suggested_kinds) || []).join(", ") + " — or any kind you type."
            Column {
                width: parent.width; spacing: 6 * Theme.s
                Repeater {
                    id: contactRows
                    model: editor.contacts
                    RowLayout {
                        width: parent.width; spacing: 6 * Theme.s
                        property alias kindText: kf.text
                        property alias valueText: vf.text
                        property alias noteText: nf.text
                        Field { id: kf; Layout.preferredWidth: 130 * Theme.s; placeholderText: "Kind"; text: modelData.kind }
                        Field { id: vf; Layout.fillWidth: true; placeholderText: "Number, address, node, handle…"; text: modelData.value }
                        Field { id: nf; Layout.preferredWidth: 150 * Theme.s; placeholderText: "Note"; text: modelData.note }
                        Btn { compact: true; kind: "ghost"; text: "×"; minWidth: 36 * Theme.s
                              onClicked: { var i = index; editor.contacts = editor.rows().filter(function(x, j) { return j !== i }) } }
                    }
                }
                Btn { compact: true; text: "+ Add contact"; onClicked: editor.contacts = editor.rows().concat([{ kind: "", value: "", note: "" }]) }
            }
        }
        Labeled { label: "Notes"
                  TextArea { id: pNotes; width: parent.width; height: 80 * Theme.s; wrapMode: TextEdit.Wrap; color: Theme.text
                             font.family: Theme.prose; font.pixelSize: Theme.fs; padding: 10 * Theme.s
                             background: Rectangle { color: Theme.panel2; radius: Theme.radius; border.color: pNotes.activeFocus ? Theme.accent : Theme.border } } }
        Txt { width: parent.width; kind: "muted"
              visible: !!editor.p && !!Net.me && Net.me.role === "admin" && editor.p.user_id !== Net.me.id
              text: "You are editing as an admin. The change is logged under your name." }
    }
}
