import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Humint
import ".."
import "../lib/fmt.js" as Fmt

// News feeds (RSS) read while there is internet; what they bring is on the
// Feeds page.
Rectangle {
    id: page
    color: Theme.bg
    property var feeds: []
    function load() { Net.get("/api/rss-feeds").then(function(r) { page.feeds = r.items || r || [] }).catch(function(e) { ui.toast(e.message, true) }) }
    Component.onCompleted: load()
    ColumnLayout {
        anchors.fill: parent; anchors.margins: Theme.pad
        spacing: Theme.gap
        PageHeader { Layout.fillWidth: true; title: "RSS feeds"; subtitle: "Read while there is internet."
                     Btn { compact: true; kind: "primary"; text: "+ Add a feed"; onClicked: add.open() } }
        ListView {
            Layout.fillWidth: true; Layout.fillHeight: true
            clip: true; spacing: 8 * Theme.s
            model: page.feeds
            delegate: Rectangle {
                width: ListView.view.width; implicitHeight: frow.implicitHeight + 24 * Theme.s
                radius: Theme.radius; color: Theme.panel; border.color: Theme.border
                opacity: modelData.is_active ? 1 : 0.55
                RowLayout {
                    id: frow
                    x: 14 * Theme.s; y: 12 * Theme.s; width: parent.width - 28 * Theme.s
                    Column { Layout.fillWidth: true
                        Txt { text: modelData.label; font.weight: Font.DemiBold }
                        Txt { width: parent.width; kind: "muted"; text: modelData.url; elide: Text.ElideMiddle; wrapMode: Text.NoWrap }
                        Txt { kind: "muted"; visible: !!modelData.last_error; color: Theme.amber; text: modelData.last_error || "" } }
                    Btn { compact: true; text: modelData.is_active ? "Pause" : "Resume"
                          onClicked: Net.patch("/api/rss-feeds/" + modelData.id, { is_active: !modelData.is_active }).then(page.load) }
                    Btn { compact: true; kind: "danger"; text: "Delete"
                          onClicked: ui.confirm("Delete " + modelData.label + "?", "", function() {
                              Net.del("/api/rss-feeds/" + modelData.id).then(page.load).catch(function(e) { ui.toast(e.message, true) }) }) }
                }
            }
        }
    }
    FormDialog {
        id: add
        title: "Add a feed"
        okText: "Add"
        onOpened: { flabel.text = ""; furl.text = "" }
        onAccepted: { busy = true
            Net.post("/api/rss-feeds", { label: flabel.text.trim(), url: furl.text.trim() }).then(function() { busy = false; close(); page.load() })
                .catch(function(e) { busy = false; error = e.message }) }
        Labeled { label: "Name"; Field { id: flabel; width: parent.width } }
        Labeled { label: "Address"; Field { id: furl; width: parent.width; mono: true; placeholderText: "https://example.org/feed.xml" } }
    }
}
