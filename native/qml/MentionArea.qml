import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Humint
import "lib/fmt.js" as Fmt

// A writing box where @ and a name mentions a record: an existing one, or a
// new one made on the spot. The mention goes into the text as a link; each
// record mentioned is reported through mentioned(entity).
ColumnLayout {
    id: ma
    property alias text: area.text
    property string placeholder: ""
    property alias area: area
    property real boxHeight: 220 * Theme.s
    property var menu: []
    property int menuStart: -1
    property string mentionQuery: ""
    readonly property var mentionTypes: ["person", "organization", "location", "event", "source"]
    signal mentioned(var entity)
    signal edited()
    spacing: 6 * Theme.s

    function insertAtCursor(s) {
        var at = area.cursorPosition
        area.insert(at, s)
        area.cursorPosition = at + s.length
        area.forceActiveFocus()
        ma.edited()
    }
    function detect() {
        var upto = area.text.slice(0, area.cursorPosition)
        var m = /(^|[\s(\[{,;:>—–-])@([^\s@]{0,30}(?:[  ][^\s@]{1,30}){0,2})$/.exec(upto)
        if (!m) { ma.menu = []; ma.menuStart = -1; return }
        ma.menuStart = area.cursorPosition - m[2].length - 1
        var q = m[2]
        ma.mentionQuery = q
        if (q.length < 1) { ma.menu = []; return }
        Net.get("/api/entities" + Net.qs({ q: q, limit: 6 })).then(function(r) {
            if (q !== ma.mentionQuery) return
            var items = (r.items || []).map(function(e) { return { kind: "entity", entity: e } })
            var exact = items.some(function(i) { return i.entity.name.toLowerCase() === q.toLowerCase() })
            if (!exact) items = items.concat(ma.mentionTypes.map(function(t) { return { kind: "new", type: t, name: q } }))
            ma.menu = items
        }).catch(function() { ma.menu = [] })
    }
    function insertMention(e) {
        var start = ma.menuStart, end = area.cursorPosition
        var link = "[" + String(e.name).replace(/[\[\]]/g, "") + "](#/entities/" + e.id + ")"
        area.remove(start, end)
        area.insert(start, link + " ")
        area.cursorPosition = start + link.length + 1
        ma.menu = []; ma.menuStart = -1
        ma.mentioned(e)
        ma.edited()
        area.forceActiveFocus()
    }
    function choose(item) {
        if (item.kind === "entity") { insertMention(item.entity); return }
        Net.post("/api/entities", { entity_type: item.type, name: item.name.trim() }).then(function(e) {
            e.isNew = true; insertMention(e); ui.toast("Created " + item.type + ": " + e.name)
        }).catch(function(err) { ma.menu = []; ui.toast("Couldn't create that record: " + err.message, true) })
    }

    ScrollView {
        Layout.fillWidth: true
        Layout.preferredHeight: ma.boxHeight
        TextArea {
            id: area
            placeholderText: ma.placeholder
            placeholderTextColor: Theme.muted
            color: Theme.text
            selectionColor: Theme.accentDim
            font.family: Theme.prose; font.pixelSize: 16 * Theme.s
            wrapMode: TextEdit.Wrap
            padding: 14 * Theme.s
            background: Rectangle { radius: Theme.radius; color: Theme.panel2
                                    border.color: area.activeFocus ? Theme.accent : Theme.border }
            onTextChanged: if (activeFocus) { ma.edited(); ma.detect() }
            onCursorPositionChanged: if (activeFocus && ma.menuStart >= 0) ma.detect()
            Keys.onEscapePressed: ma.menu = []
        }
    }
    Rectangle {
        Layout.fillWidth: true
        visible: ma.menu.length > 0
        implicitHeight: menuFlow.implicitHeight + 12 * Theme.s
        radius: Theme.radius; color: Theme.panel; border.color: Theme.accentDim
        Flow {
            id: menuFlow
            x: 6 * Theme.s; y: 6 * Theme.s; width: parent.width - 12 * Theme.s
            spacing: 6 * Theme.s
            Repeater {
                model: ma.menu
                Btn {
                    compact: true
                    kind: modelData.kind === "entity" ? "normal" : "ghost"
                    text: modelData.kind === "entity" ? modelData.entity.name : "+ New " + Fmt.typeLabel(modelData.type).toLowerCase()
                    sub: modelData.kind === "entity" ? Fmt.typeLabel(modelData.entity.entity_type) : "“" + modelData.name + "”"
                    onClicked: ma.choose(modelData)
                }
            }
        }
    }
}
