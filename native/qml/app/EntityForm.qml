import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Humint
import ".."
import "../lib/fmt.js" as Fmt
import "../lib/schema.js" as Schema

// A new record, or editing one: its kind, name, description and the fields
// that kind has (lib/schema.js, as the console). A blank field is left as it
// was, except the few that blank on purpose (coordinates, expiry dates).
Rectangle {
    id: page
    color: Theme.bg
    readonly property var entity: shell.arg && shell.arg.id ? shell.arg : null
    readonly property var prefill: shell.arg && !shell.arg.id ? shell.arg : null
    property string type: entity ? entity.entity_type : (prefill && prefill.entity_type) || "person"
    property var values: ({})
    property string error: ""
    property bool busy: false
    readonly property var fields: Schema.DETAIL_FIELDS[type] || []

    Component.onCompleted: {
        var d = entity ? (entity.details || {}) : (prefill && prefill.details) || {}
        var v = {}
        for (var k in d) v[k] = (d[k] && typeof d[k] === "object" && d[k].length !== undefined) ? Array.prototype.join.call(d[k], ", ") : (d[k] === null || d[k] === undefined ? "" : String(d[k]))
        values = v
        name.text = entity ? entity.name : (prefill && prefill.name) || ""
        desc.text = entity ? (entity.description || "") : ""
        name.forceActiveFocus()
    }

    function setValue(k, v) { var x = values; x[k] = v; values = x }

    function collect() {
        var out = {}
        fields.forEach(function(f) {
            var v = (values[f.key] === undefined ? "" : String(values[f.key])).trim()
            if (v === "") { if (f.clearable) out[f.key] = null; return }
            if (f.type === "text-list") out[f.key] = v.split(",").map(function(s) { return s.trim() }).filter(function(s) { return s })
            else if (f.type === "number") out[f.key] = parseFloat(v)
            else out[f.key] = v
        })
        return out
    }
    function save() {
        var body = { name: name.text.trim(), description: desc.text.trim() || null, details: collect() }
        if (!body.name) { error = "Give it a name."; return }
        busy = true
        var req = entity ? Net.patch("/api/entities/" + entity.id, body)
                         : Net.post("/api/entities", { entity_type: type, name: body.name, description: body.description, details: body.details })
        req.then(function(r) {
            busy = false
            ui.toast(entity ? "Record updated" : "Record created")
            shell.replace("entity", entity ? entity.id : r.id)
        }).catch(function(e) { busy = false; error = e.message })
    }

    Flickable {
        anchors.fill: parent
        contentHeight: col.implicitHeight + 2 * Theme.pad
        clip: true
        ScrollBar.vertical: ScrollBar {}
        ColumnLayout {
            id: col
            x: Theme.pad; y: Theme.pad
            width: Math.min(parent.width - 2 * Theme.pad, 760 * Theme.s)
            spacing: Theme.gap
            PageHeader {
                Layout.fillWidth: true
                back: true; onBackClicked: shell.back()
                title: page.entity ? "Edit " + page.entity.name : "New record"
                Btn { compact: true; kind: "primary"; text: page.busy ? "Saving…" : page.entity ? "Save" : "Create"
                      enabled: !page.busy; onClicked: page.save() }
            }
            Labeled {
                Layout.fillWidth: true
                label: "Kind"
                visible: !page.entity
                Flow {
                    width: parent.width; spacing: 6 * Theme.s
                    Repeater {
                        model: Object.keys(Schema.DETAIL_FIELDS).filter(function(t) { return Schema.GEOMETRY_TYPES.indexOf(t) < 0 })
                        Btn { compact: true; text: Fmt.typeLabel(modelData); kind: page.type === modelData ? "primary" : "normal"
                              onClicked: page.type = modelData }
                    }
                }
            }
            Labeled { Layout.fillWidth: true; label: "Name"; Field { id: name; width: parent.width } }
            Labeled {
                Layout.fillWidth: true; label: "Description"
                TextArea { id: desc; width: parent.width; wrapMode: TextEdit.Wrap; color: Theme.text
                           font.family: Theme.prose; font.pixelSize: Theme.fs; padding: 12 * Theme.s
                           background: Rectangle { color: Theme.panel2; radius: Theme.radius
                                                   border.color: desc.activeFocus ? Theme.accent : Theme.border } }
            }
            Repeater {
                model: page.fields
                Labeled {
                    Layout.fillWidth: true
                    label: page.type === "communication" && modelData.key === "medium_detail"
                           ? (Schema.COMMUNICATION_MEDIUM_DETAIL_LABELS[page.values.medium] || modelData.label) : modelData.label
                    hint: (modelData.hint || "") + (modelData.type === "date" ? (modelData.hint ? " " : "") + "YYYY-MM-DD"
                                                    : modelData.type === "datetime" ? (modelData.hint ? " " : "") + "YYYY-MM-DD HH:MM" : "")
                    Loader {
                        width: parent.width
                        property var f: modelData
                        sourceComponent: f.type === "select" ? selectC : (f.type === "textarea" ? areaC : fieldC)
                    }
                }
            }
            Txt { Layout.fillWidth: true; visible: page.error !== ""; color: Theme.amber; text: page.error }
        }
    }

    Component {
        id: fieldC
        Field {
            width: parent ? parent.width : 300
            mono: Schema.MONO_FIELDS.indexOf(f.key) >= 0
            placeholderText: f.placeholder || ""
            text: page.values[f.key] || ""
            inputMethodHints: f.type === "number" ? Qt.ImhFormattedNumbersOnly : Qt.ImhNone
            onTextEdited: page.setValue(f.key, text)
        }
    }
    Component {
        id: areaC
        TextArea {
            width: parent ? parent.width : 300
            height: Math.max(implicitHeight, (f.rows || 3) * 22 * Theme.s)
            wrapMode: TextEdit.Wrap; color: Theme.text; font.family: Theme.prose; font.pixelSize: Theme.fs
            padding: 12 * Theme.s
            text: page.values[f.key] || ""
            onTextChanged: if (activeFocus) page.setValue(f.key, text)
            background: Rectangle { color: Theme.panel2; radius: Theme.radius; border.color: parent.activeFocus ? Theme.accent : Theme.border }
        }
    }
    Component {
        id: selectC
        Select {
            width: parent ? parent.width : 300
            options: f.options.concat(page.values[f.key] && f.options.indexOf(page.values[f.key]) < 0 ? [page.values[f.key]] : [])
                      .map(function(o) { return [o, o || "—"] })
            value: page.values[f.key] || ""
            onPicked: function(v) { page.setValue(f.key, v) }
        }
    }
}
