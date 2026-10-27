import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Humint
import ".."
import "../lib/fmt.js" as Fmt

// Writing a report as the conversation happens. Type @ and a name to mention
// a record — an existing one, or a new one of any type, made on the spot.
// Mentions are links in the text; the console links whoever is named.
// An existing report saves itself every 15 seconds while being changed; a
// new one is kept (in memory, never on disk) if you leave before saving.
Rectangle {
    id: page
    color: Theme.bg
    property var report: shell.arg
    property var linked: report ? report.entities.slice() : []
    property bool dirty: false
    property bool saving: false
    property string status: ""
    property string error: ""
    property var menu: []          // mention menu: [{kind, entity|type+name}]
    property int menuStart: -1      // where the @ is
    property string mentionQuery: ""
    readonly property var mentionTypes: ["person", "organization", "location", "event", "source",
                                         "communication", "vehicle", "record", "zone", "route"]

    Component.onCompleted: {
        if (report) {
            title.text = report.title; body.text = report.body_markdown || ""
            statusSel.value = report.status; cred.value = report.credibility_rating || ""
            crit.value = report.criticality || ""
        } else if (Net.draft) {
            var d = Net.draft
            title.text = d.title; body.text = d.body; statusSel.value = d.status
            cred.value = d.cred; crit.value = d.crit; page.linked = d.linked
            page.status = "Restored the report you were writing"
        }
        page.dirty = false
        title.forceActiveFocus()
    }
    Component.onDestruction: {
        // A new report left unsaved stays in memory for when they come back.
        if (!page.report && (title.text || body.text) && page.dirty)
            Net.draft = { title: title.text, body: body.text, status: statusSel.value, cred: cred.value,
                          crit: crit.value, linked: page.linked }
    }

    function changed() { page.dirty = true; page.status = "Unsaved changes" }

    function save(silent) {
        if (page.saving) return
        var payload = { title: title.text.trim(), body_markdown: body.text, status: statusSel.value,
                        credibility_rating: cred.value || null, criticality: crit.value || null,
                        entity_ids: page.linked.map(function(e) { return e.id }) }
        if (!payload.title) { if (!silent) page.error = "Give the report a title before saving."; return }
        page.saving = true; page.status = "Saving…"
        var req = page.report ? Net.patch("/api/reports/" + page.report.id, payload) : Net.post("/api/reports", payload)
        req.then(function(r) {
            page.saving = false; page.dirty = false; page.error = ""
            page.report = r; page.linked = r.entities.slice(); Net.draft = null
            page.status = "Saved just now"
            if (!silent) shell.replace("report", r.id)
        }).catch(function(e) { page.saving = false; page.status = "Not saved — " + e.message; if (!silent) page.error = e.message })
    }
    Timer { interval: 15000; repeat: true; running: !!page.report
            onTriggered: if (page.dirty && !page.saving) page.save(true) }

    // ---- @-mentions ----------------------------------------------------------------
    function detectMention() {
        var upto = body.text.slice(0, body.cursorPosition)
        var m = /(^|[\s(\[{,;:>—–-])@([^\s@]{0,30}(?:[  ][^\s@]{1,30}){0,2})$/.exec(upto)
        if (!m) { page.menu = []; page.menuStart = -1; return }
        page.menuStart = body.cursorPosition - m[2].length - 1
        var q = m[2]
        page.mentionQuery = q
        if (q.length < 1) { page.menu = []; return }
        Net.get("/api/entities" + Net.qs({ q: q, limit: 6 })).then(function(r) {
            if (q !== page.mentionQuery) return       // typed on since: a newer search is coming
            var items = (r.items || []).map(function(e) { return { kind: "entity", entity: e } })
            var exact = items.some(function(i) { return i.entity.name.toLowerCase() === q.toLowerCase() })
            if (!exact) items = items.concat(page.mentionTypes.slice(0, 5).map(function(t) { return { kind: "new", type: t, name: q } }))
            page.menu = items
        }).catch(function() { page.menu = [] })
    }
    function insertMention(e) {
        var start = page.menuStart, end = body.cursorPosition
        var link = "[" + e.name + "](#/entities/" + e.id + ")"
        body.remove(start, end)
        body.insert(start, link + " ")
        body.cursorPosition = start + link.length + 1
        if (!page.linked.some(function(x) { return x.id === e.id }))
            page.linked = page.linked.concat([{ id: e.id, name: e.name, entity_type: e.entity_type, isNew: !!e.isNew }])
        page.menu = []; page.menuStart = -1
        page.changed()
        body.forceActiveFocus()
    }
    function choose(item) {
        if (item.kind === "entity") { insertMention(item.entity); return }
        Net.post("/api/entities", { entity_type: item.type, name: item.name.trim() }).then(function(e) {
            e.isNew = true; insertMention(e); ui.toast("Created " + item.type + ": " + e.name)
        }).catch(function(err) { page.menu = []; ui.toast("Couldn't create that record: " + err.message, true) })
    }

    RowLayout {
        anchors.fill: parent; anchors.margins: Theme.pad
        spacing: Theme.gap * 1.5

        ColumnLayout {
            Layout.fillWidth: true; Layout.fillHeight: true
            spacing: Theme.gap
            PageHeader {
                Layout.fillWidth: true
                back: true
                onBackClicked: {
                    if (page.dirty && page.report) ui.confirm("Leave without saving?", "The latest changes are not saved yet.",
                                                             function() { page.dirty = false; shell.back() })
                    else shell.back()
                }
                title: page.report ? "Edit report" : "New report"
                subtitle: page.status
                Btn { kind: "primary"; compact: true; text: page.saving ? "Saving…" : "Save"; enabled: !page.saving
                      onClicked: page.save(false) }
            }
            Field { id: title; Layout.fillWidth: true; placeholderText: "Title"; font.pixelSize: Theme.fsTitle
                    onTextEdited: page.changed() }
            RowLayout {
                Layout.fillWidth: true; spacing: 8 * Theme.s
                Select { id: statusSel; value: "draft"; options: [["draft", "Draft"], ["confirmed", "Confirmed"]]
                         onPicked: page.changed() }
                Select { id: cred; Layout.fillWidth: true
                         options: [["", "Credibility — not rated"]].concat(["1", "2", "3", "4", "5", "6"].map(function(k) {
                             return [k, k + " — " + Fmt.CREDIBILITY[k]] }))
                         onPicked: page.changed() }
                Select { id: crit; options: [["", "No precedence"]].concat(Fmt.CRITICALITY.map(function(c) { return [c, c] }))
                         onPicked: page.changed() }
            }
            Txt { visible: page.error !== ""; color: Theme.amber; text: page.error; Layout.fillWidth: true }
            ScrollView {
                id: bodyScroll
                Layout.fillWidth: true; Layout.fillHeight: true
                TextArea {
                    id: body
                    placeholderText: "Write what was said. Type @ and a name to mention someone, somewhere or something."
                    placeholderTextColor: Theme.muted
                    color: Theme.text
                    selectionColor: Theme.accentDim
                    font.family: Theme.prose; font.pixelSize: 16 * Theme.s
                    wrapMode: TextEdit.Wrap
                    padding: 14 * Theme.s
                    background: Rectangle { radius: Theme.radius; color: Theme.panel2
                                            border.color: body.activeFocus ? Theme.accent : Theme.border }
                    onTextChanged: if (activeFocus) { page.changed(); page.detectMention() }
                    onCursorPositionChanged: if (activeFocus && page.menuStart >= 0) page.detectMention()
                    Keys.onEscapePressed: page.menu = []
                }
            }
            // The mention menu, under the text.
            Rectangle {
                Layout.fillWidth: true
                visible: page.menu.length > 0
                implicitHeight: menuCol.implicitHeight + 12 * Theme.s
                radius: Theme.radius; color: Theme.panel; border.color: Theme.accentDim
                Flow {
                    id: menuCol
                    x: 6 * Theme.s; y: 6 * Theme.s; width: parent.width - 12 * Theme.s
                    spacing: 6 * Theme.s
                    Repeater {
                        model: page.menu
                        Btn {
                            compact: true
                            kind: modelData.kind === "entity" ? "normal" : "ghost"
                            text: modelData.kind === "entity" ? modelData.entity.name : "+ New " + Fmt.typeLabel(modelData.type).toLowerCase()
                            sub: modelData.kind === "entity" ? Fmt.typeLabel(modelData.entity.entity_type) : "“" + modelData.name + "”"
                            onClicked: page.choose(modelData)
                        }
                    }
                }
            }
        }

        // The cast list, as it grows.
        Rectangle {
            Layout.preferredWidth: 280 * Theme.s; Layout.fillHeight: true
            radius: Theme.radius * 1.4; color: Theme.panel; border.color: Theme.border
            ColumnLayout {
                anchors.fill: parent; anchors.margins: Theme.pad
                spacing: 8 * Theme.s
                Txt { kind: "label"; text: "In this report (" + page.linked.length + ")" }
                Txt { visible: page.linked.length === 0; kind: "muted"; Layout.fillWidth: true
                      text: "Everyone and everything you mention appears here, and is linked to the report when it is saved." }
                ListView {
                    Layout.fillWidth: true; Layout.fillHeight: true
                    clip: true; spacing: 6 * Theme.s
                    model: page.linked
                    delegate: RowLayout {
                        width: ListView.view.width
                        Pill { text: Fmt.typeLabel(modelData.entity_type); tone: Theme.kindColor(modelData.entity_type) }
                        Txt { Layout.fillWidth: true; text: modelData.name; wrapMode: Text.NoWrap; elide: Text.ElideRight }
                        Pill { visible: !!modelData.isNew; text: "new"; tone: Theme.accent }
                        Btn { compact: true; kind: "ghost"; text: "×"; minWidth: 30 * Theme.s
                              onClicked: { page.linked = page.linked.filter(function(x) { return x.id !== modelData.id }); page.changed() } }
                    }
                }
            }
        }
    }
}
