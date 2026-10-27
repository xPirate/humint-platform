import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Humint
import ".."
import "../lib/fmt.js" as Fmt

// Fold records that are the same thing into one. The one kept takes the
// others' links, reports, files and contacts; they are archived, pointing
// at it. (api/merge.py)
FormDialog {
    id: md
    property var records: []
    property string survivorId: ""
    signal merged()
    title: "Merge into one record"
    okText: "Merge"
    danger: true

    function weight(r) {
        var d = r.details || {}
        return (r.relationships || []).length * 2 + (r.attachments || []).length + (r.contacts || []).length
             + Object.keys(d).filter(function(k) { var v = d[k]; return v !== null && v !== "" && !(v && v.length === 0) }).length
             + (r.description ? 1 : 0)
    }
    function open(ids) {
        records = []; survivorId = ""; name.text = ""
        Promise.all(ids.map(function(id) { return Net.get("/api/entities/" + id) })).then(function(rs) {
            md.records = rs
            var best = rs.slice().sort(function(a, b) { return md.weight(b) - md.weight(a) })[0]
            md.survivorId = best.id; name.text = best.name
            md.visible = true
        }).catch(function(e) { ui.toast(e.message, true) })
    }
    onAccepted: {
        busy = true
        var body = { survivor_id: survivorId, merge_ids: records.map(function(r) { return r.id }).filter(function(i) { return i !== survivorId }) }
        var kept = records.filter(function(r) { return r.id === survivorId })[0]
        if (name.text.trim() && kept && name.text.trim() !== kept.name) body.survivor_name = name.text.trim()
        Net.post("/api/entities/merge", body).then(function() {
            busy = false; close(); ui.toast("Merged into " + (name.text.trim() || kept.name)); merged()
        }).catch(function(e) { busy = false; error = e.message })
    }

    Txt { width: parent.width; text: "Which one to keep? It takes the others' links, reports, files and contacts; the others are archived, pointing at it." }
    Repeater {
        model: md.records
        Btn {
            width: parent.width
            kind: md.survivorId === modelData.id ? "primary" : "normal"
            text: modelData.name + "  ·  " + Fmt.typeLabel(modelData.entity_type)
            sub: (modelData.relationships || []).length + " links · " + (modelData.reports || []).length + " reports · "
                 + (modelData.attachments || []).length + " files"
            onClicked: { md.survivorId = modelData.id; name.text = modelData.name }
        }
    }
    Labeled { label: "Name of the merged record"; Field { id: name; width: parent.width } }
}
