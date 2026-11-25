import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Humint
import ".."
import "../lib/fmt.js" as Fmt

// The case-aware assistant (api/assistant.py): ask about anything in the
// case file. It looks things up as it goes, shown as it works, and the
// answer cites the records it used. The conversation is yours alone.
Rectangle {
    id: page
    color: Theme.bg
    property var messages: []
    property bool working: false
    property string statusText: ""
    property var steps: []
    property string thinking: ""
    property var notes: []
    property real startedAt: 0
    property real now: 0
    property string error: ""

    function load() {
        Net.get("/api/assistant/messages").then(function(r) { page.messages = r.items || []; toEnd() })
            .catch(function() {})
    }
    Component.onCompleted: { load(); input.forceActiveFocus() }
    function toEnd() { Qt.callLater(function() { list.positionViewAtEnd() }) }

    function seconds(s) {
        var n = Math.round(Number(s) || 0)
        return n < 60 ? n + " s" : Math.floor(n / 60) + " min " + (n % 60) + " s"
    }

    function ask() {
        var q = input.text.trim()
        if (!q || page.working) return
        page.error = ""
        page.messages = page.messages.concat([{ role: "user", content: q }])
        input.text = ""
        page.working = true; page.statusText = "Starting…"; page.steps = []; page.thinking = ""; page.notes = []
        page.startedAt = Date.now(); page.now = page.startedAt
        toEnd()
        var answered = false
        Net.stream("/api/assistant/ask", { question: q }, function(ev) {
            if (ev.type === "status") page.statusText = ev.text
            else if (ev.type === "step") {
                var s = page.steps.slice()
                if (s.length && s[s.length - 1].running) s[s.length - 1] = ev; else s.push(ev)
                page.steps = s
            } else if (ev.type === "thinking") page.thinking = (page.thinking ? page.thinking + "\n\n" : "") + ev.text
            else if (ev.type === "note") page.notes = page.notes.concat([ev.text])
            else if (ev.type === "answer") {
                answered = true
                page.working = false
                page.messages = page.messages.concat([ev.message])
            } else if (ev.type === "error") {
                page.error = ev.detail
            }
            toEnd()
        }).then(function() {
            page.working = false
            // A failed question is not saved; take it back off the screen so
            // what is shown matches what was kept.
            if (!answered) {
                if (!page.error) page.error = "The assistant stopped before answering. Try again."
                page.messages = page.messages.slice(0, -1)
                input.text = q
            }
        }).catch(function(e) {
            page.working = false; page.error = e.message
            page.messages = page.messages.slice(0, -1)
            input.text = q
        })
    }
    Timer { interval: 1000; repeat: true; running: page.working; onTriggered: page.now = Date.now() }

    function openCitation(c) {
        var num = Number((String(c.id).match(/(\d+)$/) || [0, 0])[1])
        if (c.kind === "entity") shell.go("entity", c.id)
        else if (c.kind === "document") shell.go("document", num)
        else if (c.kind === "outside_event") shell.go("outside")
        else shell.go("report", c.id)
    }
    // The assistant's drafts (api/assistant_drafts.py): made only when applied.
    function decide(d, action) {
        Net.post("/api/assistant/drafts/" + d.id + "/" + action, {}).then(function(nd) {
            var msgs = page.messages.slice()
            for (var i = 0; i < msgs.length; i++) {
                var ds = msgs[i].drafts || []
                for (var j = 0; j < ds.length; j++)
                    if (ds[j].id === nd.id) {
                        var copy = ds.slice(); copy[j] = nd
                        msgs[i] = Object.assign({}, msgs[i], { drafts: copy })
                    }
            }
            page.messages = msgs
            ui.toast(action === "apply" ? "Made" : "Discarded")
        }).catch(function(e) { ui.toast(e.message, true) })
    }
    function draftKind(d) {
        var p = d.payload || {}
        return ({ report: "DRAFT REPORT", priority: "PRIORITY P" + (p.priority || 2),
                  outside_to_document: "OUTSIDE EVENT → DOCUMENTS", link: "PROPOSED LINK" })[d.kind] || d.kind
    }
    function draftText(d) {
        var p = d.payload || {}
        if (d.kind === "report") return "<b>" + Fmt.escapeHtml(p.title || "") + "</b>" + (p.criticality ? " · " + p.criticality : "")
                                        + "<br>" + Fmt.escapeHtml(Fmt.plainText(p.body_markdown || "").slice(0, 400))
        if (d.kind === "priority") return "<b>" + Fmt.escapeHtml(p.title || "") + "</b>" + (p.question ? "<br>" + Fmt.escapeHtml(p.question) : "")
                                          + ((p.indicators || []).length ? "<br>• " + p.indicators.map(Fmt.escapeHtml).join("<br>• ") : "")
        if (d.kind === "outside_to_document") return "<b>" + Fmt.escapeHtml(p.title || "") + "</b>"
        if (d.kind === "link") return "<b>" + Fmt.escapeHtml((p.from || {}).name || "") + "</b> — " + Fmt.escapeHtml(p.relationship || "")
                                      + " — <b>" + Fmt.escapeHtml((p.to || {}).name || "") + "</b>"
        return Fmt.escapeHtml(d.summary || "")
    }
    function applyText(d) {
        return ({ report: "Make the draft report", priority: "Add the priority", outside_to_document: "Send to Documents" })[d.kind] || "Apply"
    }
    function openMade(d) {
        var r = d.result || {}
        if (d.kind === "report" && r.report_id) shell.go("report", r.report_id)
        else if (d.kind === "priority") shell.go("priorities")
        else if (d.kind === "outside_to_document" && r.document_id) shell.go("document", r.document_id)
        else if (d.kind === "link") shell.go("review")
    }

    ColumnLayout {
        anchors.fill: parent; anchors.margins: Theme.pad
        spacing: Theme.gap
        PageHeader {
            Layout.fillWidth: true
            title: "Assistant"
            subtitle: "Answers come only from this case file, with the records they rest on. Your conversation is yours alone."
            Btn { compact: true; text: "Clear conversation"; visible: page.messages.length > 0 && !page.working
                  onClicked: ui.confirm("Clear this conversation?", "It cannot be brought back.", function() {
                      Net.del("/api/assistant/messages").then(function() { page.messages = []; ui.toast("Conversation cleared") })
                          .catch(function(e) { ui.toast(e.message, true) })
                  }, true, "Clear") }
        }

        ListView {
            id: list
            Layout.fillWidth: true; Layout.fillHeight: true
            clip: true; spacing: Theme.gap
            model: page.messages
            ScrollBar.vertical: ScrollBar {}
            header: Txt {
                width: list.width; visible: page.messages.length === 0 && !page.working; kind: "muted"
                height: visible ? implicitHeight + Theme.gap : 0
                text: "Ask about anything in this case file — “how is John Smith connected to Acme?”, “what came in from the field this week?”, “what is still missing for our open priorities?”. It looks things up as it goes and shows what it checked."
            }
            delegate: Item {
                width: list.width
                implicitHeight: bubble.implicitHeight
                readonly property bool mine: modelData.role === "user"
                Rectangle {
                    id: bubble
                    width: Math.min(list.width * (mine ? 0.75 : 0.92), Math.max(body.implicitWidth, (!mine && (modelData.drafts || []).length) ? 560 * Theme.s : 200 * Theme.s) + 2 * Theme.pad)
                    anchors.right: mine ? parent.right : undefined
                    implicitHeight: bc.implicitHeight + 2 * Theme.pad * 0.8
                    radius: Theme.radius * 1.4
                    color: mine ? Theme.panel2 : Theme.panel
                    border.color: mine ? Theme.borderStrong : Theme.border
                    ColumnLayout {
                        id: bc
                        x: Theme.pad; y: Theme.pad * 0.8; width: parent.width - 2 * Theme.pad
                        spacing: 8 * Theme.s
                        Txt {
                            id: body
                            Layout.fillWidth: true
                            textFormat: mine ? Text.PlainText : Text.RichText
                            font.family: Theme.prose
                            text: mine ? modelData.content : Fmt.mdToHtml(modelData.content, Theme.accent)
                            onLinkActivated: function(link) {
                                var id = Fmt.mentionId(link)
                                if (id) shell.go("entity", id)
                            }
                        }
                        Flow {
                            Layout.fillWidth: true; spacing: 6 * Theme.s
                            visible: !mine && (modelData.citations || []).length > 0
                            Repeater { model: modelData.citations || []
                                       Btn { compact: true; kind: "ghost"; text: modelData.label; onClicked: page.openCitation(modelData) } }
                        }
                        Repeater {
                            model: mine ? [] : (modelData.drafts || [])
                            delegate: Rectangle {
                                required property var modelData
                                Layout.fillWidth: true
                                implicitHeight: dc.implicitHeight + 16 * Theme.s
                                radius: Theme.radius; color: Theme.panel2; border.color: Theme.borderStrong
                                opacity: modelData.status === "applied" || modelData.status === "discarded" ? 0.75 : 1
                                ColumnLayout {
                                    id: dc
                                    x: 10 * Theme.s; y: 8 * Theme.s; width: parent.width - 20 * Theme.s; spacing: 4 * Theme.s
                                    RowLayout {
                                        Layout.fillWidth: true
                                        Txt { Layout.fillWidth: true; kind: "label"; text: page.draftKind(modelData) }
                                        Txt { kind: "muted"; visible: modelData.status === "applied" || modelData.status === "discarded"
                                              text: modelData.status === "applied" ? "Made" : "Discarded" }
                                    }
                                    Txt { Layout.fillWidth: true; textFormat: Text.StyledText; text: page.draftText(modelData)
                                          font.strikeout: modelData.status === "discarded" }
                                    Flow {
                                        Layout.fillWidth: true; spacing: 6 * Theme.s
                                        Btn { compact: true; kind: "primary"; visible: modelData.status === "pending" && !shell.viewer
                                              text: page.applyText(modelData); onClicked: page.decide(modelData, "apply") }
                                        Btn { compact: true; kind: "ghost"; visible: modelData.status === "pending" && !shell.viewer
                                              text: "Discard"; onClicked: page.decide(modelData, "discard") }
                                        Btn { compact: true; kind: "ghost"; visible: modelData.status === "applied" || modelData.status === "queued"
                                              text: modelData.status === "queued" ? "In the Review queue" : "Open"
                                              onClicked: page.openMade(modelData) }
                                    }
                                }
                            }
                        }
                        Repeater { model: mine ? [] : ((modelData.trail || {}).notes || [])
                                   Txt { Layout.fillWidth: true; color: Theme.amber; text: modelData } }
                        // What it looked up, folded away under the answer.
                        Column {
                            id: trailBox
                            Layout.fillWidth: true
                            readonly property var trail: modelData.trail || null
                            property bool open: false
                            visible: !mine && !!trail && (((trail.steps || []).length > 0) || !!trail.thinking)
                            spacing: 4 * Theme.s
                            AbstractButton {
                                width: parent.width; implicitHeight: tl.implicitHeight + 6 * Theme.s
                                onClicked: trailBox.open = !trailBox.open
                                contentItem: Txt {
                                    id: tl; kind: "muted"
                                    text: {
                                        var t = trailBox.trail || {}
                                        var n = t.lookups !== undefined && t.lookups !== null ? t.lookups : (t.steps || []).length
                                        var what = t.mode === "single" ? "Answered from one search"
                                                 : n ? "Looked up " + n + (n === 1 ? " thing" : " things") : "Answered without looking anything up"
                                        return (trailBox.open ? "▾ " : "▸ ") + what + " · " + (t.thinking ? "thought for " : "") + page.seconds(t.seconds)
                                    }
                                }
                                background: Item {}
                            }
                            Repeater {
                                model: trailBox.open && trailBox.trail ? (trailBox.trail.steps || []) : []
                                Txt { width: trailBox.width; kind: "muted"
                                      text: (index + 1) + ". " + (modelData.label || "") + (modelData.summary ? " — " + modelData.summary : "") }
                            }
                            Txt { width: trailBox.width; visible: trailBox.open && !!(trailBox.trail || {}).thinking
                                  kind: "muted"; font.italic: true; text: (trailBox.trail || {}).thinking || "" }
                        }
                    }
                }
            }
            // The answer being worked on: each lookup as it runs, then the answer replaces this.
            footer: Item {
                width: list.width
                height: page.working ? wk.implicitHeight + Theme.gap : 0
                visible: page.working
                Rectangle {
                    y: Theme.gap
                    width: list.width * 0.92
                    implicitHeight: wc.implicitHeight + 2 * Theme.pad * 0.8
                    radius: Theme.radius * 1.4; color: Theme.panel; border.color: Theme.accent
                    id: wk
                    ColumnLayout {
                        id: wc
                        x: Theme.pad; y: Theme.pad * 0.8; width: parent.width - 2 * Theme.pad
                        spacing: 6 * Theme.s
                        RowLayout {
                            Layout.fillWidth: true; spacing: 8 * Theme.s
                            Spinner { visible: page.working }
                            Txt { Layout.fillWidth: true; text: page.statusText }
                            Txt { kind: "muted"; text: page.seconds((page.now - page.startedAt) / 1000) }
                        }
                        Repeater { model: page.steps
                                   Txt { Layout.fillWidth: true; kind: modelData.running ? "body" : "muted"
                                         text: (modelData.running ? "… " : "✓ ") + (modelData.label || "") + (modelData.summary ? " — " + modelData.summary : "") } }
                        Repeater { model: page.notes; Txt { Layout.fillWidth: true; color: Theme.amber; text: modelData } }
                        Txt { Layout.fillWidth: true; visible: page.thinking !== ""; kind: "muted"; font.italic: true
                              maximumLineCount: 6; elide: Text.ElideLeft
                              text: page.thinking.slice(-800) }
                    }
                }
            }
        }

        Txt { Layout.fillWidth: true; visible: page.error !== ""; color: Theme.amber; text: page.error }
        RowLayout {
            Layout.fillWidth: true; spacing: 8 * Theme.s
            TextArea {
                id: input
                Layout.fillWidth: true
                Layout.preferredHeight: Math.min(160 * Theme.s, Math.max(56 * Theme.s, contentHeight + 22 * Theme.s))
                enabled: !page.working
                wrapMode: TextEdit.Wrap; color: Theme.text
                font.family: Theme.prose; font.pixelSize: Theme.fs; padding: 11 * Theme.s
                placeholderText: "Ask about the case file — Enter sends, Shift+Enter for a new line"
                placeholderTextColor: Theme.muted
                background: Rectangle { color: Theme.panel2; radius: Theme.radius; border.color: input.activeFocus ? Theme.accent : Theme.border }
                Keys.onReturnPressed: function(e) { if (e.modifiers & Qt.ShiftModifier) e.accepted = false; else page.ask() }
                Keys.onEnterPressed: function(e) { if (e.modifiers & Qt.ShiftModifier) e.accepted = false; else page.ask() }
            }
            Btn { kind: "primary"; text: page.working ? "Working…" : "Ask"; enabled: !page.working && input.text.trim() !== ""
                  onClicked: page.ask() }
        }
    }
}
