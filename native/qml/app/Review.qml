import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Humint
import ".."
import "../lib/fmt.js" as Fmt

// The review inbox: nothing enters the case file until a person accepts it.
//   From phones   — field reports, accepted as draft reports (api/field.py)
//   Suggestions   — records and links proposed by documents, rules, the
//                   assistant or a field server (api/extraction.py)
//   Duplicates    — records that look like the same thing (api/correlation.py)
Rectangle {
    id: page
    color: Theme.bg
    property string tab: "phones"
    property var subs: []
    property var suggestions: []
    property var pairs: []
    property string subStatus: "new"
    property string error: ""

    function load() {
        error = ""
        if (tab === "phones")
            Net.get("/api/field/submissions" + Net.qs({ status: subStatus })).then(function(r) { page.subs = r.items || [] })
                .catch(function(e) { page.error = e.message })
        else if (tab === "suggestions")
            Net.get("/api/extraction-suggestions" + Net.qs({ status: "pending", limit: 100 })).then(function(r) { page.suggestions = r.items || [] })
                .catch(function(e) { page.error = e.message })
        else
            Net.get("/api/correlation-suggestions" + Net.qs({ status: "pending", limit: 100 })).then(function(r) { page.pairs = r.items || [] })
                .catch(function(e) { page.error = e.message })
    }
    onTabChanged: load()
    Component.onCompleted: load()

    function act(promise, msg) {
        promise.then(function(r) { ui.toast(msg); page.load() }).catch(function(e) { ui.toast(e.message, true) })
    }

    ColumnLayout {
        anchors.fill: parent; anchors.margins: Theme.pad
        spacing: Theme.gap
        PageHeader {
            Layout.fillWidth: true
            title: "Review inbox"
            subtitle: "Nothing here is in the case file until you accept it."
            Btn { compact: true; text: "Refresh"; onClicked: page.load() }
        }
        Row {
            spacing: 8 * Theme.s
            Repeater {
                model: [["phones", "From phones"], ["suggestions", "Suggestions"], ["duplicates", "Possible duplicates"]]
                Btn { compact: true; text: modelData[1]; kind: page.tab === modelData[0] ? "primary" : "normal"
                      onClicked: page.tab = modelData[0] }
            }
            Select { visible: page.tab === "phones"; value: page.subStatus
                     options: [["new", "Waiting"], ["accepted", "Accepted"], ["rejected", "Set aside"], ["all", "All"]]
                     onPicked: function(v) { page.subStatus = v; page.load() } }
        }
        Txt { visible: page.error !== ""; color: Theme.amber; text: page.error }

        // ---- field reports from phones ----------------------------------------------------
        ListView {
            visible: page.tab === "phones"
            Layout.fillWidth: true; Layout.fillHeight: true
            clip: true; spacing: 10 * Theme.s
            model: page.subs
            ScrollBar.vertical: ScrollBar {}
            Txt { visible: parent.count === 0; kind: "muted"; text: "Nothing waiting from the phones." }
            delegate: Rectangle {
                width: ListView.view.width
                implicitHeight: subCol.implicitHeight + 2 * Theme.pad
                radius: Theme.radius * 1.4; color: Theme.panel
                border.color: modelData.criticality ? Theme.critColor(modelData.criticality) : Theme.border
                ColumnLayout {
                    id: subCol
                    x: Theme.pad; y: Theme.pad; width: parent.width - 2 * Theme.pad
                    spacing: 6 * Theme.s
                    RowLayout {
                        Layout.fillWidth: true
                        Pill { visible: !!modelData.criticality; text: modelData.criticality || ""
                               tone: Theme.critColor(modelData.criticality); filled: modelData.criticality === "Flash" }
                        Txt { Layout.fillWidth: true; text: modelData.title; font.weight: Font.DemiBold }
                        Pill { visible: modelData.status !== "new"; text: modelData.status; tone: Theme.muted }
                    }
                    Txt { Layout.fillWidth: true; kind: "muted"
                          text: (modelData.device_label || "an unknown device") + (modelData.from_user ? " · " + modelData.from_user : "")
                                + (modelData.observed_at ? " · observed " + Fmt.exactTime(modelData.observed_at) : "")
                                + " · received " + Fmt.relativeTime(modelData.received_at) }
                    Repeater {
                        model: modelData.layout && modelData.layout.rows ? modelData.layout.rows : []
                        RowLayout { Layout.fillWidth: true
                            Txt { Layout.preferredWidth: 200 * Theme.s; kind: "muted"; text: modelData.label }
                            Txt { Layout.fillWidth: true; text: String(modelData.value === null || modelData.value === undefined ? "" : modelData.value) } }
                    }
                    Txt { Layout.fillWidth: true; visible: !!modelData.body; text: modelData.body || ""; font.family: Theme.prose }
                    Txt { Layout.fillWidth: true; visible: modelData.lat !== null && modelData.lat !== undefined; font.family: "IBM Plex Mono"
                          text: modelData.lat !== null && modelData.lat !== undefined
                                ? modelData.lat.toFixed(5) + ", " + modelData.lng.toFixed(5)
                                  + (modelData.location_accuracy_m ? " ±" + Math.round(modelData.location_accuracy_m) + " m" : "")
                                  + (modelData.location_note ? " · " + modelData.location_note : "") : "" }
                    Txt { visible: (modelData.file_count || 0) > 0; kind: "muted"
                          text: (modelData.file_count || 0) + " photo(s) or file(s) come with it; accepting attaches them to the draft." }
                    Flow {
                        Layout.fillWidth: true; spacing: 8 * Theme.s
                        visible: modelData.status === "new" && !shell.viewer
                        Check { id: alsoMake; visible: !!modelData.suggests; checked: true; text: modelData.suggests ? "also start a " + modelData.suggests.entity_type + " record — "
                                                                                 + modelData.suggests.name : "" }
                        Btn { compact: true; kind: "primary"; text: "Accept as a draft report"
                              onClicked: Net.post("/api/field/submissions/" + modelData.id + "/accept",
                                                  { create_entity: !!(modelData.suggests && alsoMake.checked) }).then(function(r) {
                                  ui.toast("Accepted — a draft report"); page.load()
                              }).catch(function(e) { ui.toast(e.message, true) }) }
                        Btn { compact: true; kind: "ghost"; text: "Set aside"
                              onClicked: page.act(Net.post("/api/field/submissions/" + modelData.id + "/reject", { note: null }), "Set aside") }
                    }
                    Btn { compact: true; kind: "ghost"; visible: modelData.status === "accepted" && !!modelData.report_id
                          text: "Open the draft report"; onClicked: shell.go("report", modelData.report_id) }
                }
            }
        }

        // ---- suggestions ------------------------------------------------------------------
        ListView {
            visible: page.tab === "suggestions"
            Layout.fillWidth: true; Layout.fillHeight: true
            clip: true; spacing: 10 * Theme.s
            model: page.suggestions
            ScrollBar.vertical: ScrollBar {}
            Txt { visible: parent.count === 0; kind: "muted"; text: "No suggestions waiting." }
            delegate: Rectangle {
                id: card
                width: ListView.view.width
                implicitHeight: sCol.implicitHeight + 2 * Theme.pad
                radius: Theme.radius * 1.4; color: Theme.panel; border.color: Theme.border
                readonly property var s: modelData
                readonly property bool isEntity: s.suggestion_type === "entity"
                readonly property bool resolved: !isEntity && !!s.suggested_from_entity_id && !!s.suggested_to_entity_id
                ColumnLayout {
                    id: sCol
                    x: Theme.pad; y: Theme.pad; width: parent.width - 2 * Theme.pad
                    spacing: 8 * Theme.s
                    RowLayout {
                        Layout.fillWidth: true
                        Pill { text: ({ extraction: "from a document", signal: "correlation signal", assistant: "assistant",
                                        manual: "added by hand", field: "field server" })[card.s.source] || card.s.source || ""
                               tone: Theme.teal }
                        Pill { visible: card.isEntity; text: Fmt.typeLabel(card.s.suggested_entity_type); tone: Theme.kindColor(card.s.suggested_entity_type) }
                        Txt { Layout.fillWidth: true; font.weight: Font.DemiBold
                              text: card.isEntity ? card.s.suggested_name
                                    : (card.s.suggested_from_name + "  — " + (card.s.suggested_relationship_type || "").replace(/_/g, " ")
                                       + " →  " + card.s.suggested_to_name) }
                        Txt { kind: "muted"; visible: card.s.confidence !== null && card.s.confidence !== undefined
                              text: Math.round((card.s.confidence || 0) * 100) + "% confidence"; wrapMode: Text.NoWrap }
                    }
                    Txt { Layout.fillWidth: true; visible: !!(card.s.evidence && card.s.evidence.rule); kind: "muted"
                          text: card.s.evidence && card.s.evidence.rule ? card.s.evidence.rule : "" }
                    Txt { Layout.fillWidth: true; visible: !!card.s.looks_like; color: Theme.amber
                          text: card.s.looks_like ? "This is " + card.s.looks_like + ", not a name. Reject it, or rename it if you know whose it is." : "" }
                    Repeater {
                        model: card.isEntity ? Object.keys(card.s.details || {}) : []
                        Txt { Layout.fillWidth: true; kind: "muted"; text: modelData + ": " + String(card.s.details[modelData]) }
                    }
                    // A link whose ends are not settled: say which records they are.
                    GridLayout {
                        Layout.fillWidth: true
                        visible: !card.isEntity && !card.resolved
                        columns: 2; columnSpacing: Theme.gap; rowSpacing: 6 * Theme.s
                        Txt { text: card.s.suggested_from_name || ""; font.weight: Font.DemiBold; visible: !card.s.suggested_from_entity_id }
                        EntityPicker { id: fromPick; Layout.fillWidth: true; visible: !card.s.suggested_from_entity_id; allowCreate: true
                                       placeholder: "Which record is " + (card.s.suggested_from_name || "") + "?" }
                        Txt { text: card.s.suggested_to_name || ""; font.weight: Font.DemiBold; visible: !card.s.suggested_to_entity_id }
                        EntityPicker { id: toPick; Layout.fillWidth: true; visible: !card.s.suggested_to_entity_id; allowCreate: true
                                       placeholder: "Which record is " + (card.s.suggested_to_name || "") + "?" }
                    }
                    Flow {
                        Layout.fillWidth: true; spacing: 8 * Theme.s
                        visible: !shell.viewer
                        Select { id: asType; visible: card.isEntity; value: card.s.suggested_entity_type
                                 options: Fmt.ENTITY_TYPES.filter(function(t) { return t !== "zone" && t !== "route" })
                                             .map(function(t) { return [t, "as " + Fmt.typeLabel(t).toLowerCase()] }) }
                        Btn { compact: true; kind: "primary"; text: "Accept"
                              onClicked: {
                                  var body = {}
                                  if (card.isEntity) {
                                      if (asType.value !== card.s.suggested_entity_type) body = { entity_type: asType.value, details: {} }
                                  } else if (!card.resolved) {
                                      if (!card.s.suggested_from_entity_id) {
                                          if (!fromPick.picked) { ui.toast("Say which record " + card.s.suggested_from_name + " is", true); return }
                                          body.from_entity_id = fromPick.picked.id
                                      }
                                      if (!card.s.suggested_to_entity_id) {
                                          if (!toPick.picked) { ui.toast("Say which record " + card.s.suggested_to_name + " is", true); return }
                                          body.to_entity_id = toPick.picked.id
                                      }
                                  }
                                  page.act(Net.post("/api/extraction-suggestions/" + card.s.id + "/accept", body), "Accepted")
                              } }
                        Btn { compact: true; kind: "danger"; text: "Reject"
                              onClicked: page.act(Net.post("/api/extraction-suggestions/" + card.s.id + "/reject", {}), "Rejected") }
                    }
                }
            }
        }

        // ---- possible duplicates ---------------------------------------------------------------
        ListView {
            visible: page.tab === "duplicates"
            Layout.fillWidth: true; Layout.fillHeight: true
            clip: true; spacing: 10 * Theme.s
            model: page.pairs
            ScrollBar.vertical: ScrollBar {}
            Txt { visible: parent.count === 0; kind: "muted"; text: "No possible duplicates waiting." }
            delegate: Rectangle {
                width: ListView.view.width
                implicitHeight: pCol.implicitHeight + 2 * Theme.pad
                radius: Theme.radius * 1.4; color: Theme.panel; border.color: Theme.border
                ColumnLayout {
                    id: pCol
                    x: Theme.pad; y: Theme.pad; width: parent.width - 2 * Theme.pad
                    spacing: 8 * Theme.s
                    RowLayout {
                        Layout.fillWidth: true
                        Btn { compact: true; kind: "ghost"; text: modelData.subject_a_label || modelData.subject_a_id
                              onClicked: shell.go(modelData.subject_type === "entity" ? "entity" : "report", modelData.subject_a_id) }
                        Txt { text: "↔"; color: Theme.muted }
                        Btn { compact: true; kind: "ghost"; text: modelData.subject_b_label || modelData.subject_b_id
                              onClicked: shell.go(modelData.subject_type === "entity" ? "entity" : "report", modelData.subject_b_id) }
                        Item { Layout.fillWidth: true }
                        Txt { kind: "muted"; text: Math.round(modelData.similarity_score * 100) + "% similar"; wrapMode: Text.NoWrap }
                    }
                    Flow {
                        Layout.fillWidth: true; spacing: 8 * Theme.s
                        visible: !shell.viewer
                        Btn { compact: true; kind: "primary"; visible: modelData.subject_type === "entity"; text: "Merge into one"
                              onClicked: merge.open([modelData.subject_a_id, modelData.subject_b_id]) }
                        Btn { compact: true; text: "Same, but keep both"
                              onClicked: page.act(Net.post("/api/correlation-suggestions/" + modelData.id + "/confirm", {}), "Marked as the same") }
                        Btn { compact: true; kind: "danger"; text: "Not a match"
                              onClicked: page.act(Net.post("/api/correlation-suggestions/" + modelData.id + "/dismiss", {}), "Dismissed") }
                    }
                }
            }
        }
    }

    MergeDialog { id: merge; onMerged: page.load() }
}
