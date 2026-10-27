import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Humint
import ".."
import "../lib/fmt.js" as Fmt

// Intelligence priorities: the questions the team is trying to answer, how
// badly, what would tell us, by when — and, once known, the answer.
Rectangle {
    id: page
    color: Theme.bg
    property var items: []
    property bool showClosed: false

    function load() {
        Net.get("/api/priorities" + Net.qs({ status: showClosed ? "all" : "open" })).then(function(r) { page.items = r.items || [] })
            .catch(function(e) { ui.toast(e.message, true) })
    }
    Component.onCompleted: load()
    function rankColor(p) { return ({ 1: Theme.red, 2: Theme.amber, 3: Theme.teal })[p] || Theme.muted }

    ColumnLayout {
        anchors.fill: parent; anchors.margins: Theme.pad
        spacing: Theme.gap
        PageHeader {
            Layout.fillWidth: true
            title: "Priorities"
            subtitle: "A good priority is a question whose answer would change what the team does."
            Check { text: "Answered and closed too"; checked: page.showClosed; onToggled: { page.showClosed = checked; page.load() } }
            Btn { compact: true; kind: "primary"; text: "+ New priority"; visible: !shell.viewer; onClicked: form.open(null) }
        }
        Txt { visible: page.items.length === 0; kind: "muted"; text: "Nothing listed." }
        ListView {
            Layout.fillWidth: true; Layout.fillHeight: true
            clip: true; spacing: 10 * Theme.s
            model: page.items
            ScrollBar.vertical: ScrollBar {}
            delegate: Rectangle {
                width: ListView.view.width
                implicitHeight: pc.implicitHeight + 2 * Theme.pad
                radius: Theme.radius * 1.4; color: Theme.panel
                border.color: modelData.status === "open" ? page.rankColor(modelData.priority) : Theme.border
                opacity: modelData.status === "open" ? 1 : 0.6
                ColumnLayout {
                    id: pc
                    x: Theme.pad; y: Theme.pad; width: parent.width - 2 * Theme.pad
                    spacing: 6 * Theme.s
                    RowLayout {
                        Layout.fillWidth: true
                        Pill { text: "P" + modelData.priority; tone: page.rankColor(modelData.priority); filled: modelData.priority === 1 }
                        Txt { Layout.fillWidth: true; text: modelData.title; font.weight: Font.DemiBold; font.pixelSize: 17 * Theme.s }
                        Pill { visible: modelData.status !== "open"; text: modelData.status; tone: Theme.muted }
                        Txt { visible: !!modelData.due_date; kind: "muted"; text: "by " + Fmt.exactDate(modelData.due_date); wrapMode: Text.NoWrap }
                    }
                    Txt { Layout.fillWidth: true; visible: !!modelData.question; text: modelData.question || ""; font.family: Theme.prose }
                    Txt { visible: modelData.indicators.length > 0; kind: "label"; text: "What would tell us" }
                    Repeater { model: modelData.indicators
                               Txt { Layout.fillWidth: true; text: "• " + modelData } }
                    Flow { Layout.fillWidth: true; spacing: 6 * Theme.s; visible: modelData.entities.length > 0
                        Txt { kind: "label"; text: "About" }
                        Repeater { model: modelData.entities
                                   Btn { compact: true; kind: "ghost"; text: modelData.name; onClicked: shell.go("entity", modelData.id) } } }
                    Txt { Layout.fillWidth: true; visible: !!modelData.answered_note; color: Theme.accent
                          text: "Answer: " + (modelData.answered_note || "") }
                    Flow {
                        Layout.fillWidth: true; spacing: 6 * Theme.s
                        visible: !shell.viewer
                        Btn { compact: true; visible: modelData.status === "open"; text: "Answer it"; onClicked: answer.open(modelData) }
                        Btn { compact: true; kind: "ghost"; visible: modelData.status === "open"; text: "Edit"; onClicked: form.open(modelData) }
                        Btn { compact: true; kind: "ghost"; visible: modelData.status !== "open"; text: "Reopen"
                              onClicked: Net.patch("/api/priorities/" + modelData.id, { status: "open" }).then(page.load).catch(function(e) { ui.toast(e.message, true) }) }
                        Btn { compact: true; kind: "ghost"; text: "Delete"
                              onClicked: ui.confirm("Delete this priority?", modelData.title, function() {
                                  Net.del("/api/priorities/" + modelData.id).then(page.load).catch(function(e) { ui.toast(e.message, true) }) }) }
                    }
                }
            }
        }
    }

    FormDialog {
        id: form
        property var existing: null
        property var linked: []
        title: existing ? "Edit priority" : "New priority"
        function open(p) {
            existing = p; linked = p ? p.entities.slice() : []
            ptitle.text = p ? p.title : ""; question.text = p ? (p.question || "") : ""; rank.value = p ? String(p.priority) : "2"
            indicators.text = p ? p.indicators.join("\n") : ""; due.text = p && p.due_date ? p.due_date.slice(0, 10) : ""
            pick.reset(); visible = true
        }
        onAccepted: {
            var body = { title: ptitle.text.trim(), question: question.text.trim() || null, priority: Number(rank.value),
                         indicators: indicators.text.split("\n").map(function(s) { return s.trim() }).filter(function(s) { return s }),
                         due_date: due.text.trim() || null, entity_ids: linked.map(function(e) { return e.id }) }
            if (!body.title) { error = "Give it a title."; return }
            busy = true
            var req = existing ? Net.patch("/api/priorities/" + existing.id, body) : Net.post("/api/priorities", body)
            req.then(function() { busy = false; close(); page.load() }).catch(function(e) { busy = false; error = e.message })
        }
        Labeled { label: "Title"; Field { id: ptitle; width: parent.width; placeholderText: "Locate the offending station" } }
        Labeled { label: "The question, in full"
                  TextArea { id: question; width: parent.width; height: 80 * Theme.s; wrapMode: TextEdit.Wrap; color: Theme.text
                             font.family: Theme.prose; font.pixelSize: Theme.fs; padding: 10 * Theme.s
                             background: Rectangle { color: Theme.panel2; radius: Theme.radius; border.color: question.activeFocus ? Theme.accent : Theme.border } } }
        Labeled { label: "How badly"
                  Select { id: rank; width: parent.width
                           options: [["1", "P1 — drop other work"], ["2", "P2 — high"], ["3", "P3 — normal"], ["4", "P4 — when there is time"]] } }
        Labeled { label: "What would tell us — one per line"
                  TextArea { id: indicators; width: parent.width; height: 90 * Theme.s; wrapMode: TextEdit.Wrap; color: Theme.text
                             font.family: Theme.prose; font.pixelSize: Theme.fs; padding: 10 * Theme.s
                             background: Rectangle { color: Theme.panel2; radius: Theme.radius; border.color: indicators.activeFocus ? Theme.accent : Theme.border } } }
        Labeled { label: "Wanted by (YYYY-MM-DD)"; Field { id: due; width: parent.width; mono: true } }
        Labeled {
            label: "About"
            Column {
                width: parent.width; spacing: 6 * Theme.s
                Flow { width: parent.width; spacing: 4 * Theme.s
                    Repeater { model: form.linked
                               Btn { compact: true; kind: "ghost"; text: modelData.name + "  ×"
                                     onClicked: form.linked = form.linked.filter(function(x) { return x.id !== modelData.id }) } } }
                EntityPicker { id: pick; width: parent.width
                               onChosen: function(e) { if (!form.linked.some(function(x) { return x.id === e.id })) form.linked = form.linked.concat([e]); pick.reset() } }
            }
        }
    }

    FormDialog {
        id: answer
        property var p: null
        title: "Answer it"
        okText: "Mark answered"
        function open(x) { p = x; note.text = ""; visible = true }
        onAccepted: {
            busy = true
            Net.patch("/api/priorities/" + p.id, { status: "answered", answered_note: note.text.trim() || null })
                .then(function() { busy = false; close(); page.load() }).catch(function(e) { busy = false; error = e.message })
        }
        Txt { width: parent.width; font.weight: Font.DemiBold; text: answer.p ? answer.p.title : "" }
        Labeled { label: "What we found"
                  TextArea { id: note; width: parent.width; height: 100 * Theme.s; wrapMode: TextEdit.Wrap; color: Theme.text
                             font.family: Theme.prose; font.pixelSize: Theme.fs; padding: 10 * Theme.s
                             background: Rectangle { color: Theme.panel2; radius: Theme.radius; border.color: note.activeFocus ? Theme.accent : Theme.border } } }
    }
}
