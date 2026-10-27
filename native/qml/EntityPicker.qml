import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Humint
import "lib/fmt.js" as Fmt

// Find a record by name. `picked` is the chosen {id, name, entity_type}.
// With allowCreate, a name with no match can be made into a new record of
// any of `types`.
Column {
    id: ep
    property var picked: null
    property var types: []
    property bool allowCreate: false
    property string placeholder: "Search records"
    // Extra fields for a record made here: function(type) → {details: …}
    property var newDetails: null
    property var results: []
    property string query: ""
    signal chosen(var entity)
    spacing: 6 * Theme.s
    width: parent ? parent.width : 300

    function reset() { picked = null; field.text = ""; results = [] }
    function search() {
        var q = field.text.trim(); ep.query = q
        if (!q) { results = []; return }
        Net.get("/api/entities" + Net.qs({ q: q, limit: 8, entity_type: ep.types.length === 1 ? ep.types[0] : "" })).then(function(r) {
            if (q !== ep.query) return
            var items = (r.items || []).filter(function(e) { return !ep.types.length || ep.types.indexOf(e.entity_type) >= 0 })
            ep.results = items
        }).catch(function() { ep.results = [] })
    }
    function choose(e) { ep.picked = e; ep.results = []; field.text = ""; ep.chosen(e) }

    RowLayout {
        width: parent.width
        visible: !!ep.picked
        Pill { text: ep.picked ? Fmt.typeLabel(ep.picked.entity_type) : ""; tone: Theme.kindColor(ep.picked ? ep.picked.entity_type : "") }
        Txt { Layout.fillWidth: true; text: ep.picked ? ep.picked.name : ""; font.weight: Font.DemiBold }
        Btn { compact: true; kind: "ghost"; text: "Change"; onClicked: ep.picked = null }
    }
    Field {
        id: field
        width: parent.width
        visible: !ep.picked
        placeholderText: ep.placeholder
        onTextChanged: delay.restart()
        Timer { id: delay; interval: 250; onTriggered: ep.search() }
    }
    Flow {
        width: parent.width
        visible: !ep.picked && (ep.results.length > 0 || (ep.allowCreate && ep.query !== ""))
        spacing: 6 * Theme.s
        Repeater {
            model: ep.results
            Btn { compact: true; text: modelData.name; sub: Fmt.typeLabel(modelData.entity_type); onClicked: ep.choose(modelData) }
        }
        Repeater {
            model: ep.allowCreate && ep.query !== "" && !ep.results.some(function(e) { return e.name.toLowerCase() === ep.query.toLowerCase() })
                   ? (ep.types.length ? ep.types : Fmt.ENTITY_TYPES.slice(0, 8)) : []
            Btn { compact: true; kind: "ghost"; text: "+ New " + Fmt.typeLabel(modelData).toLowerCase(); sub: "“" + ep.query + "”"
                  onClicked: Net.post("/api/entities", Object.assign({ entity_type: modelData, name: ep.query },
                                                     ep.newDetails ? (ep.newDetails(modelData) || {}) : {})).then(function(e) {
                      e.isNew = true; ep.choose(e) }).catch(function(err) { ui.toast(err.message, true) }) }
        }
    }
}
