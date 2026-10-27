import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Humint
import ".."
import "../lib/fmt.js" as Fmt

// Link signals: rules that propose links between records (shared contact
// details, the same parent, named together) into the review inbox.
Rectangle {
    id: page
    color: Theme.bg
    property var st: null
    function load() { Net.get("/api/admin/link-signals").then(function(r) { page.st = r }).catch(function(e) { ui.toast(e.message, true) }) }
    Component.onCompleted: load()
    ColumnLayout {
        anchors.fill: parent; anchors.margins: Theme.pad
        spacing: Theme.gap
        PageHeader { Layout.fillWidth: true; title: "Link signals"
                     subtitle: "Rules that propose links between records into the review inbox. No model involved." }
        Check { text: "Running"; checked: !!(page.st && page.st.enabled)
                onToggled: Net.put("/api/admin/link-signals", { enabled: checked }).then(page.load).catch(function(e) { ui.toast(e.message, true) }) }
        Txt { kind: "muted"; text: page.st && page.st.last_run ? "Last ran " + Fmt.relativeTime(page.st.last_run) : "Not run yet" }
        Btn { text: "Run now"; onClicked: Net.post("/api/admin/link-signals/run", {}).then(function() { ui.toast("Running — proposals land in the review inbox"); page.load() })
                                              .catch(function(e) { ui.toast(e.message, true) }) }
        Item { Layout.fillHeight: true }
    }
}
