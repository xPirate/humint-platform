import QtQuick
import QtQuick.Controls
import Humint
import ".."
import "../lib/schema.js" as Schema

// A link from this record to another: what kind, how sure, since when,
// until when it counts.
FormDialog {
    id: f
    property var entity: null
    property var suggested: []
    signal saved()
    title: "Add relationship — " + (entity ? entity.name : "")
    okText: "Add"
    function open(ent) {
        entity = ent; to.reset(); relType.text = ""; conf.value = "3"
        discovered.text = new Date().toISOString().slice(0, 10); expires.text = ""; notes.text = ""
        Net.get("/api/relationship-types").then(function(r) { f.suggested = r.suggested || [] }).catch(function() {})
        visible = true
    }
    onAccepted: {
        if (!to.picked) { error = "Pick the other record."; return }
        var t = relType.text.trim().toLowerCase().replace(/\s+/g, "_")
        if (!t) { error = "Say what the relationship is."; return }
        busy = true
        Net.post("/api/relationships", { from_entity_id: entity.id, to_entity_id: to.picked.id, relationship_type: t,
                                         confidence: conf.value, discovery_date: discovered.text || null,
                                         expires_on: expires.text || null, notes: notes.text.trim() || null })
            .then(function() { busy = false; close(); ui.toast("Relationship added"); saved() })
            .catch(function(e) { busy = false; error = e.message })
    }
    Labeled { label: "To"; EntityPicker { id: to; width: parent.width; allowCreate: true } }
    Labeled {
        label: "Relationship"
        hint: "e.g. employed_by, member_of, family_of, located_at"
        Column {
            width: parent.width; spacing: 6 * Theme.s
            Field { id: relType; width: parent.width; mono: true }
            Flow {
                width: parent.width; spacing: 4 * Theme.s
                Repeater { model: f.suggested.filter(function(s) { return !relType.text || s.indexOf(relType.text.toLowerCase().replace(/\s+/g, "_")) >= 0 }).slice(0, 12)
                           Btn { compact: true; kind: "ghost"; text: modelData.replace(/_/g, " "); onClicked: relType.text = modelData } }
            }
        }
    }
    Labeled { label: "Confidence"
              Select { id: conf; width: parent.width; value: "3"
                       options: Schema.CONFIDENCE_SCALE.map(function(c) { return [c[0], c[0] + " — " + c[1]] }) } }
    Labeled { label: "Discovered (YYYY-MM-DD)"; Field { id: discovered; width: parent.width; mono: true } }
    Labeled { label: "Expires (YYYY-MM-DD)"; hint: "When it stops counting. Blank for never."
              Field { id: expires; width: parent.width; mono: true } }
    Labeled { label: "Notes"; Field { id: notes; width: parent.width } }
}
