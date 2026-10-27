import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Humint
import ".."

// A source known to the case file only by a code name; its true name is
// readable by its handlers alone (api/sources.py). Shown on a source's page.
Card {
    id: sp
    title: "Source protection"
    implicitHeight: spCol.implicitHeight + 2 * padding + Theme.gap + 20 * Theme.s
    property var p: null
    property var identity: null
    readonly property var ent: page.e

    function load() {
        if (!ent) return
        Net.get("/api/sources/" + ent.id + "/protection").then(function(r) { sp.p = r }).catch(function() {})
    }
    Component.onCompleted: load()
    onEntChanged: { identity = null; load() }

    Column {
        id: spCol
        width: parent.width
        spacing: 8 * Theme.s
        Txt { width: parent.width; visible: !!sp.p && !sp.p.protected
              text: "Not protected. Everyone who can open the case file sees this source's name." }
        RowLayout {
            width: parent.width
            visible: !!sp.p && sp.p.protected
            Pill { text: "protected"; tone: Theme.accent }
            Txt { Layout.fillWidth: true
                  text: sp.p ? "Known here by its code name. Handled by "
                               + (sp.p.handlers.map(function(h) { return h.username }).join(", ") || "nobody")
                               + (sp.p.you_are_handler ? " (you)." : ".") : "" }
        }
        Flow {
            width: parent.width; spacing: 8 * Theme.s
            Btn { compact: true; visible: !!sp.p && !sp.p.protected && !shell.viewer; text: "Protect this source…"
                  onClicked: protect.open() }
            Btn { compact: true; visible: !!sp.p && sp.p.you_are_handler; text: sp.identity ? "Hide identity" : "Show identity"
                  onClicked: {
                      if (sp.identity) { sp.identity = null; return }
                      Net.get("/api/sources/" + sp.ent.id + "/identity").then(function(i) {
                          sp.identity = i; trueName.text = i.true_name; idNotes.text = i.notes || "" })
                          .catch(function(e) { ui.toast(e.message, true) })
                  } }
            Btn { compact: true; visible: !!sp.p && sp.p.can_manage && !shell.viewer; text: "Handlers…"; onClicked: handlers.open() }
            Btn { compact: true; visible: !!sp.p && sp.p.you_are_handler && !shell.viewer; text: "Lift protection…"
                  onClicked: ui.confirm("Lift protection?", "The true name goes back on the record, where everyone can see it.", function() {
                      Net.post("/api/sources/" + sp.ent.id + "/unprotect", {}).then(function() { ui.toast("Protection lifted"); page.load() })
                          .catch(function(e) { ui.toast(e.message, true) })
                  }) }
        }
        Column {
            width: parent.width
            visible: !!sp.identity
            spacing: 8 * Theme.s
            Labeled { label: "True name"; Field { id: trueName; width: parent.width; readOnly: shell.viewer } }
            Labeled { label: "Identity notes"
                      TextArea { id: idNotes; width: parent.width; readOnly: shell.viewer; wrapMode: TextEdit.Wrap
                                 color: Theme.text; font.family: Theme.ui; font.pixelSize: Theme.fs
                                 background: Rectangle { color: Theme.panel2; radius: Theme.radius; border.color: Theme.border } } }
            Txt { width: parent.width; kind: "muted"
                  text: sp.identity ? "Protected by " + (sp.identity.protected_by || "?") + ". This reading is in the audit log." : "" }
            Btn { compact: true; visible: !shell.viewer; text: "Save identity"
                  onClicked: Net.put("/api/sources/" + sp.ent.id + "/identity", { true_name: trueName.text.trim(), notes: idNotes.text || null })
                      .then(function() { ui.toast("Identity saved") }).catch(function(e) { ui.toast(e.message, true) }) }
        }
    }

    FormDialog {
        id: protect
        title: "Protect this source"
        okText: "Protect"
        onOpened: { code.text = ""; moveDesc.checked = true }
        onAccepted: {
            busy = true
            Net.post("/api/sources/" + sp.ent.id + "/protect", { code_name: code.text.trim(), move_description: moveDesc.checked })
                .then(function(r) {
                    busy = false; close()
                    var left = []
                    if (r.reports_naming_source) left.push(r.reports_naming_source + " report(s) still name them in their text")
                    if (r.relationships) left.push(r.relationships + " link(s) to other records — check none is to a record of the same person")
                    ui.toast("Protected as " + r.code_name + (left.length ? ". Still to deal with: " + left.join("; ") : ""))
                    page.load()
                }).catch(function(e) { busy = false; error = e.message })
        }
        Txt { width: parent.width
              text: "The record will be known everywhere by a code name instead — search, the network, reports, exports, the assistant. Its true name moves to a protected identity only its handlers can read. You become its first handler." }
        Labeled { label: "Code name"; Field { id: code; width: parent.width; placeholderText: "e.g. KESTREL" } }
        CheckBox { id: moveDesc
                   contentItem: Txt { leftPadding: parent.indicator.width + 6 * Theme.s; verticalAlignment: Text.AlignVCenter
                                      text: "Move the description into the protected identity too" } }
        Txt { width: parent.width; kind: "muted"
              text: "Files attached to this source will be shown to its handlers only. It cannot hide a report whose text names the person, or a link to a Person record of the same individual." }
    }

    FormDialog {
        id: handlers
        title: "Who handles this source"
        property var users: []
        property var chosen: ({})
        onOpened: {
            var cur = {}
            ;(sp.p ? sp.p.handlers : []).forEach(function(h) { cur[h.id] = true })
            chosen = cur
            Net.get("/api/analysts").then(function(r) { handlers.users = r.items || [] }).catch(function() {})
        }
        onAccepted: {
            var ids = Object.keys(chosen).filter(function(k) { return chosen[k] }).map(Number)
            if (!ids.length) { error = "A protected source needs at least one handler."; return }
            busy = true
            Net.put("/api/sources/" + sp.ent.id + "/handlers", { user_ids: ids }).then(function() {
                busy = false; close(); ui.toast("Handlers saved"); sp.load()
            }).catch(function(e) { busy = false; error = e.message })
        }
        Repeater {
            model: handlers.users
            CheckBox {
                checked: !!handlers.chosen[modelData.id]
                onToggled: { var c = handlers.chosen; c[modelData.id] = checked; handlers.chosen = c }
                contentItem: Txt { leftPadding: parent.indicator.width + 6 * Theme.s; verticalAlignment: Text.AlignVCenter
                                   text: modelData.username + (modelData.display_name ? " — " + modelData.display_name : "") }
            }
        }
    }
}
