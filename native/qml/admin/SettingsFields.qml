import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Humint
import ".."

// An editor for the console's "fields" settings pages (model, appearance):
// each field shows its value, whether it is overridden here, and what the
// machine's own setting would be. Save sends only what changed; Reset sends
// null (back to the machine's setting).
Column {
    id: sf
    property string endpoint: ""
    property var labels: ({})
    property var cfg: null
    property var edits: ({})
    spacing: 8 * Theme.s
    width: parent ? parent.width : 400
    function load() { Net.get(endpoint).then(function(r) { sf.cfg = r; sf.edits = {} }).catch(function(e) { ui.toast(e.message, true) }) }
    Component.onCompleted: load()
    function save(body) { Net.patch(endpoint, body).then(function() { ui.toast("Saved"); sf.load() }).catch(function(e) { ui.toast(e.message, true) }) }
    Repeater {
        model: sf.cfg ? Object.keys(sf.cfg.fields).filter(function(k) { return !!sf.labels[k] }) : []
        RowLayout {
            width: sf.width
            readonly property var f: sf.cfg.fields[modelData]
            Txt { Layout.preferredWidth: 240 * Theme.s; text: sf.labels[modelData] }
            Loader {
                Layout.fillWidth: true
                sourceComponent: typeof parent.f.value === "boolean" ? boolC : textC
                property string key: modelData
                property var f: parent.f
            }
            Txt { kind: "muted"; text: parent.f.overridden ? "set here" : "machine default"; wrapMode: Text.NoWrap }
            Btn { compact: true; kind: "ghost"; text: "Reset"; visible: parent.f.overridden
                  onClicked: { var b = {}; b[modelData] = null; sf.save(b) } }
        }
    }
    Component {
        id: textC
        RowLayout {
            Field { id: tf; Layout.fillWidth: true; text: f.value === null || f.value === undefined ? "" : String(f.value) }
            Btn { compact: true; text: "Save"
                  onClicked: { var b = {}; var v = tf.text.trim(); b[key] = (typeof f.env_default === "number" ? Number(v) : v) || null; sf.save(b) } }
        }
    }
    Component {
        id: boolC
        Check { checked: !!f.value; text: checked ? "On" : "Off"; onToggled: { var b = {}; b[key] = checked; sf.save(b) } }
    }
}
