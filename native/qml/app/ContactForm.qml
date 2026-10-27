import QtQuick
import QtQuick.Controls
import Humint
import ".."
import "../lib/schema.js" as Schema

// How to reach a person, organisation or place: one contact point.
FormDialog {
    id: f
    property var entity: null
    property var existing: null
    signal saved()
    title: (existing ? "Edit" : "Add") + " contact — " + (entity ? entity.name : "")
    okText: existing ? "Save" : "Add"
    function open(ent, c) {
        entity = ent; existing = c
        kind.value = c ? c.kind : "Phone"; label.text = c ? (c.label || "") : ""
        value.text = c ? c.value : ""; notes.text = c ? (c.notes || "") : ""; preferred.checked = c ? c.is_preferred : false
        visible = true
    }
    onAccepted: {
        var body = { kind: kind.value, label: label.text.trim() || null, value: value.text.trim(),
                     notes: notes.text.trim() || null, is_preferred: preferred.checked }
        if (!body.value) { error = "Enter the number, address or handle."; return }
        busy = true
        var req = existing ? Net.patch("/api/contacts/" + existing.id, body) : Net.post("/api/entities/" + entity.id + "/contacts", body)
        req.then(function() { busy = false; close(); ui.toast(existing ? "Contact updated" : "Contact added"); saved() })
           .catch(function(e) { busy = false; error = e.message })
    }
    Labeled { label: "Type"; Select { id: kind; width: parent.width; options: Schema.CONTACT_KINDS.map(function(k) { return [k, k] }) } }
    Labeled { label: "Label"; hint: "Optional — “work”, “switchboard”, “after hours”"
              Field { id: label; width: parent.width } }
    Labeled { label: "Value"; Field { id: value; width: parent.width; mono: true } }
    Labeled { label: "Notes"; Field { id: notes; width: parent.width } }
    Check { id: preferred; text: "Preferred — include this one in exported PDFs" }
}
