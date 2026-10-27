import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Humint
import ".."
import "../lib/fmt.js" as Fmt

// Guided debrief: someone is sitting in front of you and the report does not
// exist yet. Five steps, each asking for one thing; every name given along
// the way becomes a real record the moment it is given. What comes out is an
// ordinary report, with its sections (source, when and where, who, what
// happened, assessment) and everyone gathered linked to it.
//
// A place the source points at on the map is held here and only becomes a
// Location when the report is filed, so an abandoned debrief leaves nothing
// half-named behind. An unfinished debrief is kept in memory (never on disk —
// it is case material) for when you come back to it.
Rectangle {
    id: page
    color: Theme.bg
    property int step: 0
    readonly property var stepNames: ["Source", "When & where", "Who was involved", "What happened", "Assessment"]
    property var source: null
    property var location: null
    property var eventRec: null
    property var involved: []          // [{id, name, entity_type, isNew, role}]
    property var mentioned: []
    property var place: null           // {lat, lng}
    property bool showMap: false
    property bool titleTouched: false
    property bool dirty: false
    property bool saving: false
    property string error: ""

    readonly property var reliabilityText: ({ A: "Completely reliable", B: "Usually reliable", C: "Fairly reliable",
                                              D: "Not usually reliable", E: "Unreliable", F: "Reliability cannot be judged" })
    readonly property var prompts: ["What did you see?", "When did it start and when did it end?", "Who else was there?",
                                    "What were they wearing, driving, carrying?", "What was said, and by whom?",
                                    "How do you know this?", "Has this happened before?", "What did you not see or hear?",
                                    "Is there anything you're unsure about?"]

    function pad(n) { return (n < 10 ? "0" : "") + n }
    function nowText() {
        var d = new Date()
        return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) + " " + pad(d.getHours()) + ":" + pad(d.getMinutes())
    }
    function isoLocal(t) { return (t || "").trim().replace(" ", "T") }

    // ---- the cast list ---------------------------------------------------------------
    function gathered() {
        var all = []
        function push(e) { if (e && !all.some(function(x) { return x.id === e.id })) all.push(e) }
        push(page.source); push(page.location); push(page.eventRec)
        page.involved.forEach(push); page.mentioned.forEach(push)
        return all
    }
    readonly property var cast: { page.source; page.location; page.eventRec; page.involved; page.mentioned; return gathered() }

    function changed() {
        page.dirty = true
        if (!page.titleTouched) titleField.text = defaultTitle()
    }
    function defaultTitle() {
        var d = (when.text || "").slice(0, 10)
        return "Debrief — " + (page.source ? page.source.name : "source") + (d ? " — " + d : "")
    }
    function setRole(id, role) {
        var item = page.involved.filter(function(x) { return x.id === id })[0]
        if (!item || (item.role || "") === role) return
        page.involved = page.involved.map(function(x) { return x.id === id ? Object.assign({}, x, { role: role }) : x })
        page.changed()
        // Only ever fills in a new record's description, never overwrites one.
        if (item.isNew && role) Net.patch("/api/entities/" + id, { description: role }).catch(function() {})
    }
    function mentionLink(e) { return "[" + String(e.name).replace(/[\[\]]/g, "").trim() + "](#/entities/" + e.id + ")" }

    // ---- the report it becomes ---------------------------------------------------------
    function markdown() {
        var parts = []
        var src = []
        if (page.source) src.push(mentionLink(page.source) + (rel.value ? " — reliability " + rel.value + " (" + page.reliabilityText[rel.value] + ")" : ""))
        if (when.text.trim()) src.push("Debriefed " + when.text.trim() + " by " + (Net.me ? Net.me.username : "an analyst"))
        if (src.length) parts.push("## Source\n\n" + src.map(function(l) { return "- " + l }).join("\n"))
        var where = []
        if (occurred.text.trim()) where.push("Occurred " + occurred.text.trim())
        if (page.location) where.push("Location: " + mentionLink(page.location))
        if (page.eventRec) where.push("Event: " + mentionLink(page.eventRec))
        if (where.length) parts.push("## When and where\n\n" + where.map(function(l) { return "- " + l }).join("\n"))
        if (page.involved.length)
            parts.push("## Who was involved\n\n" + page.involved.map(function(e) {
                return "- " + mentionLink(e) + ((e.role || "").trim() ? " — " + e.role.trim() : "") }).join("\n"))
        if (narrative.text.trim()) parts.push("## Narrative\n\n" + narrative.text.trim())
        if (assessment.text.trim()) parts.push("## Assessment\n\n" + assessment.text.trim())
        return parts.join("\n\n")
    }

    // ---- kept in memory if left unfinished --------------------------------------------
    function snapshot() {
        return { step: page.step, source: page.source, location: page.location, eventRec: page.eventRec,
                 involved: page.involved, mentioned: page.mentioned, place: page.place, placeName: placeName.text,
                 rel: rel.value, saveRel: saveRel.checked, when: when.text, occurred: occurred.text, address: address.text,
                 narrative: narrative.text, assessment: assessment.text, cred: cred.value, crit: crit.value,
                 status: statusSel.value, title: titleField.text, titleTouched: page.titleTouched, at: Date.now() }
    }
    function restore(d) {
        page.source = d.source; page.location = d.location; page.eventRec = d.eventRec
        page.involved = d.involved || []; page.mentioned = d.mentioned || []; page.place = d.place
        placeName.text = d.placeName || ""; rel.value = d.rel || ""; saveRel.checked = d.saveRel !== false
        when.text = d.when || ""; occurred.text = d.occurred || ""; address.text = d.address || ""
        narrative.text = d.narrative || ""; assessment.text = d.assessment || ""
        cred.value = d.cred || ""; crit.value = d.crit || ""; statusSel.value = d.status || "draft"
        page.titleTouched = !!d.titleTouched; titleField.text = d.title || defaultTitle()
        page.step = d.step || 0; page.dirty = true
    }
    Component.onCompleted: {
        when.text = nowText(); occurred.text = nowText(); titleField.text = defaultTitle()
        var d = Net.debriefDraft
        if (d && (d.narrative || d.assessment || d.source)) {
            ui.confirm("Pick up the unfinished debrief?", "Started " + Fmt.relativeTime(new Date(d.at).toISOString()) + ".",
                       function() { page.restore(d) }, false, "Pick it up")
        }
        Net.debriefDraft = null
        page.dirty = false
    }
    Component.onDestruction: if (page.dirty && !page.saving) Net.debriefDraft = snapshot()

    function finish() {
        if (page.saving) return
        var title = titleField.text.trim()
        if (!title) { page.error = "Give the report a title before filing it."; return }
        var body = markdown()
        if (!body.trim()) { page.error = "There is nothing in this debrief yet."; return }
        page.saving = true; page.error = ""
        var placeRec = null
        var placeReq = !page.place ? Promise.resolve(null)
            : Net.post("/api/entities", { entity_type: "location",
                                          name: placeName.text.trim() || ("Place given during debrief (" + page.place.lat.toFixed(4) + ", " + page.place.lng.toFixed(4) + ")"),
                                          description: "Pointed out on the map during a debrief; no address was given.",
                                          details: { lat: page.place.lat.toFixed(6), lng: page.place.lng.toFixed(6) } })
        placeReq.then(function(p) {
            placeRec = p
            var ids = page.cast.map(function(e) { return e.id })
            if (p) ids.push(p.id)
            return Net.post("/api/reports", { title: title, body_markdown: body, status: statusSel.value,
                                              credibility_rating: cred.value || null, criticality: crit.value || null,
                                              entity_ids: ids })
        }).then(function(report) {
            var after = Promise.resolve()
            if (page.source && page.source.entity_type === "source" && rel.value && saveRel.checked)
                after = Net.patch("/api/entities/" + page.source.id, { details: { reliability_rating: rel.value } })
                    .catch(function() { ui.toast("Report filed, but the reliability rating did not save on the source.", true) })
            after.then(function() {
                page.dirty = false; page.saving = false
                ui.toast("Debrief filed as a report")
                shell.replace("report", report.id)
            })
        }).catch(function(e) {
            page.saving = false
            page.error = placeRec ? e.message + " (The place you pointed at was saved as “" + placeRec.name + "” — it is under Records.)" : e.message
        })
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
                onBackClicked: shell.back()
                title: "Guided debrief"
                subtitle: "Each step asks for one thing. Everyone named becomes a record as they are named."
            }
            // The steps (wrapping, so a narrow screen keeps the side panel on it)
            Flow {
                Layout.fillWidth: true
                spacing: 6 * Theme.s
                Repeater {
                    model: page.stepNames
                    AbstractButton {
                        implicitWidth: stepLabel.implicitWidth + 24 * Theme.s; implicitHeight: 36 * Theme.s
                        onClicked: page.step = index
                        background: Rectangle { radius: Theme.radius
                            color: index === page.step ? Theme.accentDim : index < page.step ? Theme.panel2 : "transparent"
                            border.color: index === page.step ? Theme.accentDim : Theme.border }
                        contentItem: Txt { id: stepLabel; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
                                           wrapMode: Text.NoWrap; text: (index + 1) + "  " + modelData
                                           color: index === page.step ? Theme.onAccent : Theme.text }
                    }
                }
            }

            Flickable {
                Layout.fillWidth: true; Layout.fillHeight: true
                contentHeight: steps.implicitHeight
                clip: true
                ScrollBar.vertical: ScrollBar {}
                Item {
                    id: steps
                    width: parent.width
                    implicitHeight: [s0, s1, s2, s3, s4][page.step].implicitHeight

                    // 1 — Source
                    Column {
                        id: s0; width: parent.width; spacing: Theme.gap; visible: page.step === 0
                        Txt { kind: "title"; text: "Who are you debriefing?" }
                        Txt { width: parent.width; kind: "muted"; text: "Search for the record, or type a name to make one." }
                        EntityPicker { id: srcPick; width: parent.width; types: ["source", "person"]; allowCreate: true
                                       placeholder: "Name of the person being debriefed"
                                       picked: page.source
                                       onChosen: function(e) { page.source = e; page.changed() }
                                       onPickedChanged: if (!picked && page.source) { page.source = null; page.changed() } }
                        Labeled { label: "Source reliability (Admiralty A–F)"
                                  Select { id: rel; width: parent.width; value: ""
                                           options: [["", "— not rated"]].concat(["A", "B", "C", "D", "E", "F"].map(function(k) { return [k, k + " — " + page.reliabilityText[k]] }))
                                           onPicked: page.changed() } }
                        Check { id: saveRel; checked: true; visible: !!page.source && page.source.entity_type === "source" && rel.value !== ""
                                text: "Also save this rating on the source" }
                        Labeled { label: "Debriefed at (YYYY-MM-DD HH:MM)"
                                  Field { id: when; width: parent.width; mono: true; onTextEdited: page.changed() } }
                    }

                    // 2 — When & where
                    Column {
                        id: s1; width: parent.width; spacing: Theme.gap; visible: page.step === 1
                        Txt { kind: "title"; text: "When and where did this happen?" }
                        Txt { width: parent.width; kind: "muted"; text: "When and where it happened, not when you are talking." }
                        Labeled { label: "Occurred at (YYYY-MM-DD HH:MM)"
                                  Field { id: occurred; width: parent.width; mono: true; onTextEdited: page.changed() } }
                        Labeled { label: "Location"
                                  EntityPicker { width: parent.width; types: ["location"]; allowCreate: true; placeholder: "Where did it happen?"
                                                 picked: page.location
                                                 onChosen: function(e) { page.location = e; page.changed() }
                                                 onPickedChanged: if (!picked && page.location) { page.location = null; page.changed() } } }
                        Labeled { label: "Address, grid reference or landmark"; visible: !!page.location
                                  hint: "Saved on the location's record."
                                  Field { id: address; width: parent.width
                                          onEditingFinished: if (page.location && text.trim())
                                              Net.patch("/api/entities/" + page.location.id, { details: { address: text.trim() } })
                                                  .catch(function(e) { ui.toast("Not saved to " + page.location.name + ": " + e.message, true) }) } }
                        // A source who cannot give an address can often point at the rooftop.
                        Row {
                            spacing: 8 * Theme.s
                            Btn { compact: true; text: page.showMap ? "Hide the map" : "Point at it on the map"; onClicked: page.showMap = !page.showMap }
                            Txt { anchors.verticalCenter: parent.verticalCenter; kind: "muted"; visible: !!page.place
                                  text: page.place ? page.place.lat.toFixed(5) + ", " + page.place.lng.toFixed(5) + " — becomes a Location when the report is filed" : "" }
                            Btn { compact: true; kind: "ghost"; visible: !!page.place; text: "Clear"; onClicked: { page.place = null; page.changed() } }
                        }
                        Column {
                            width: parent.width; spacing: 8 * Theme.s; visible: page.showMap
                            Txt { width: parent.width; kind: "muted"; text: "Tap the map where it happened." }
                            Loader {
                                width: parent.width; height: 360 * Theme.s
                                active: page.showMap
                                sourceComponent: PlaceMap {
                                    place: page.place
                                    onPlaced: function(lat, lng) { page.place = { lat: lat, lng: lng }; page.changed() }
                                }
                            }
                            Labeled { label: "Call this place"
                                      Field { id: placeName; width: parent.width; placeholderText: "e.g. the yard behind the grain store"
                                              onTextEdited: page.changed() } }
                        }
                        Labeled { label: "Tie this to an event (optional)"
                                  hint: "The Event this debrief belongs to, if there is one. A new one is dated from the time above."
                                  EntityPicker { width: parent.width; types: ["event"]; allowCreate: true; placeholder: "Meeting, movement, incident…"
                                                 picked: page.eventRec
                                                 newDetails: function() { return occurred.text.trim() ? { details: { started_at: page.isoLocal(occurred.text) } } : {} }
                                                 onChosen: function(e) { page.eventRec = e; page.changed() }
                                                 onPickedChanged: if (!picked && page.eventRec) { page.eventRec = null; page.changed() } } }
                    }

                    // 3 — Who was involved
                    Column {
                        id: s2; width: parent.width; spacing: Theme.gap; visible: page.step === 2
                        Txt { kind: "title"; text: "Who else was involved?" }
                        Txt { width: parent.width; kind: "muted"
                              text: "Everyone and every channel that came up. Note each one's part — for a new record it becomes its description." }
                        EntityPicker { id: invPick; width: parent.width; types: ["person", "organization", "communication"]; allowCreate: true
                                       placeholder: "Add a person, organisation or means of communication"
                                       onChosen: function(e) {
                                           if (!page.involved.some(function(x) { return x.id === e.id }))
                                               page.involved = page.involved.concat([{ id: e.id, name: e.name, entity_type: e.entity_type, isNew: !!e.isNew, role: "" }])
                                           invPick.reset(); page.changed()
                                       } }
                        Repeater {
                            model: page.involved
                            Rectangle {
                                width: s2.width; implicitHeight: ic.implicitHeight + 16 * Theme.s
                                radius: Theme.radius; color: Theme.panel; border.color: Theme.border
                                Column {
                                    id: ic
                                    x: 10 * Theme.s; y: 8 * Theme.s; width: parent.width - 20 * Theme.s; spacing: 6 * Theme.s
                                    RowLayout {
                                        width: parent.width
                                        Pill { text: Fmt.typeLabel(modelData.entity_type); tone: Theme.kindColor(modelData.entity_type) }
                                        Txt { Layout.fillWidth: true; text: modelData.name; font.weight: Font.DemiBold }
                                        Pill { visible: modelData.isNew; text: "new"; tone: Theme.accent }
                                        Btn { compact: true; kind: "ghost"; text: "Remove"
                                              onClicked: { page.involved = page.involved.filter(function(x) { return x.id !== modelData.id }); page.changed() } }
                                    }
                                    Field {
                                        width: parent.width; placeholderText: "Their part in this"; text: modelData.role || ""
                                        // After this handler returns: updating the list rebuilds this row.
                                        onEditingFinished: Qt.callLater(page.setRole, modelData.id, text.trim())
                                    }
                                }
                            }
                        }
                    }

                    // 4 — What happened
                    RowLayout {
                        id: s3; width: parent.width; spacing: Theme.gap; visible: page.step === 3
                        ColumnLayout {
                            Layout.fillWidth: true; Layout.alignment: Qt.AlignTop; spacing: Theme.gap
                            Txt { kind: "title"; text: "What happened?" }
                            Txt { Layout.fillWidth: true; kind: "muted"; text: "In the source's own words where possible. Type @ to name anyone." }
                            MentionArea { id: narrative; Layout.fillWidth: true; boxHeight: 380 * Theme.s
                                          placeholder: "They said that…"
                                          onEdited: page.changed()
                                          onMentioned: function(e) { if (!page.mentioned.some(function(x) { return x.id === e.id }))
                                              page.mentioned = page.mentioned.concat([{ id: e.id, name: e.name, entity_type: e.entity_type, isNew: !!e.isNew }]) } }
                        }
                        Column {
                            Layout.preferredWidth: 280 * Theme.s; Layout.alignment: Qt.AlignTop; spacing: 6 * Theme.s
                            Txt { kind: "label"; text: "Questions to work through" }
                            Txt { width: parent.width; kind: "muted"; text: "Tap one to add it as a heading, then write the answer under it." }
                            Repeater { model: page.prompts
                                       Btn { width: parent.width; compact: true; kind: "ghost"; text: modelData
                                             onClicked: {
                                                 var existing = narrative.text.replace(/\s+$/, "")
                                                 narrative.text = (existing ? existing + "\n\n" : "") + "**" + modelData + "**\n\n"
                                                 narrative.area.cursorPosition = narrative.text.length
                                                 narrative.area.forceActiveFocus(); page.changed()
                                             } } }
                        }
                    }

                    // 5 — Assessment
                    Column {
                        id: s4; width: parent.width; spacing: Theme.gap; visible: page.step === 4
                        Txt { kind: "title"; text: "Your assessment" }
                        Txt { width: parent.width; kind: "muted"; text: "Your assessment, kept apart from what the source said." }
                        MentionArea { id: assessment; width: parent.width; boxHeight: 160 * Theme.s
                                      placeholder: "What this confirms, contradicts or leaves open. @ works here too."
                                      onEdited: page.changed()
                                      onMentioned: function(e) { if (!page.mentioned.some(function(x) { return x.id === e.id }))
                                          page.mentioned = page.mentioned.concat([{ id: e.id, name: e.name, entity_type: e.entity_type, isNew: !!e.isNew }]) } }
                        Column {
                            width: parent.width; spacing: Theme.gap
                            Labeled { width: parent.width; label: "Credibility of this information"
                                      Select { id: cred; width: parent.width; value: ""
                                               options: [["", "— not rated"]].concat(["1", "2", "3", "4", "5", "6"].map(function(k) { return [k, k + " — " + Fmt.CREDIBILITY[k]] }))
                                               onPicked: page.changed() } }
                            Labeled { width: parent.width; label: "Criticality"
                                      Select { id: crit; width: parent.width; value: ""
                                               options: [["", "— not set"], ["Flash", "Flash — act now"], ["Immediate", "Immediate — hours"],
                                                         ["Priority", "Priority — same day"], ["Routine", "Routine — normal handling"]]
                                               onPicked: page.changed() } }
                            Labeled { width: parent.width; label: "Save as"
                                      Select { id: statusSel; width: parent.width; value: "draft"; options: [["draft", "Draft"], ["confirmed", "Confirmed"]] } }
                        }
                        Labeled { label: "Report title"
                                  Field { id: titleField; width: parent.width; font.pixelSize: Theme.fsTitle
                                          onTextEdited: { page.titleTouched = true; page.dirty = true } } }
                        // Before you file it
                        Rectangle {
                            width: parent.width; implicitHeight: rv.implicitHeight + 2 * Theme.pad
                            radius: Theme.radius * 1.4; color: Theme.panel; border.color: Theme.border
                            Grid {
                                id: rv
                                x: Theme.pad; y: Theme.pad; width: parent.width - 2 * Theme.pad
                                columns: 2; columnSpacing: Theme.gap; rowSpacing: 6 * Theme.s
                                readonly property var rows: {
                                    page.cast; narrative.text; crit.value
                                    var words = narrative.text.trim() ? narrative.text.trim().split(/\s+/).length : 0
                                    var fresh = page.cast.filter(function(e) { return e.isNew })
                                    return [["Source", page.source ? page.source.name : "— none picked"],
                                            ["Location", page.location ? page.location.name : (page.place ? "a point on the map" : "— not recorded")],
                                            ["Event", page.eventRec ? page.eventRec.name : "— none"],
                                            ["Others involved", page.involved.length ? page.involved.map(function(e) { return e.name }).join(", ") : "— none"],
                                            ["Narrative", words ? words + " words" : "— empty"],
                                            ["Criticality", crit.value || "— not set"],
                                            ["Records linked", String(page.cast.length + (page.place ? 1 : 0))],
                                            ["Made during this debrief", fresh.length ? fresh.map(function(e) { return e.name }).join(", ") : "none"]]
                                }
                                Repeater {
                                    model: rv.rows.length * 2
                                    Txt { width: index % 2 ? rv.width - 200 * Theme.s - Theme.gap : 200 * Theme.s
                                          kind: index % 2 ? "body" : "label"
                                          text: rv.rows[Math.floor(index / 2)][index % 2] }
                                }
                            }
                        }
                    }
                }
            }

            Txt { Layout.fillWidth: true; visible: page.error !== ""; color: Theme.amber; text: page.error }
            RowLayout {
                Layout.fillWidth: true
                Btn { text: "← Back"; visible: page.step > 0; onClicked: page.step -= 1 }
                Item { Layout.fillWidth: true }
                Btn { kind: "primary"; text: "Next →"; visible: page.step < 4; onClicked: page.step += 1 }
                Btn { kind: "primary"; text: page.saving ? "Filing…" : "Create report"; visible: page.step === 4; enabled: !page.saving
                      onClicked: page.finish() }
            }
        }

        // Gathered so far
        Rectangle {
            Layout.preferredWidth: 260 * Theme.s; Layout.fillHeight: true
            radius: Theme.radius * 1.4; color: Theme.panel; border.color: Theme.border
            ColumnLayout {
                anchors.fill: parent; anchors.margins: Theme.pad
                spacing: 8 * Theme.s
                Txt { kind: "label"; text: "Gathered so far (" + page.cast.length + ")" }
                Txt { Layout.fillWidth: true; kind: "muted"; visible: page.cast.length === 0
                      text: "Everyone named during the debrief. New records are saved as soon as they are made." }
                ListView {
                    Layout.fillWidth: true; Layout.fillHeight: true
                    clip: true; spacing: 6 * Theme.s
                    model: page.cast
                    delegate: RowLayout {
                        width: ListView.view.width
                        Pill { text: Fmt.typeLabel(modelData.entity_type); tone: Theme.kindColor(modelData.entity_type) }
                        Txt { Layout.fillWidth: true; text: modelData.name; wrapMode: Text.NoWrap; elide: Text.ElideRight }
                        Pill { visible: !!modelData.isNew; text: "new"; tone: Theme.accent }
                    }
                }
            }
        }
    }
}
