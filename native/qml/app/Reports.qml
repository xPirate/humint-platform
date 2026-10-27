import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Humint
import ".."
import "../lib/fmt.js" as Fmt

// Reports: search, filter by status and precedence, newest or most urgent
// first. New report, or a guided debrief.
Rectangle {
    id: page
    color: Theme.bg
    property var items: []
    property bool loading: true
    property string error: ""

    function load() {
        page.loading = true
        Net.get("/api/reports" + Net.qs({ limit: 200, q: search.text.trim(), status: status.value,
                                          criticality: crit.value, sort: sort.value })).then(function(r) {
            page.items = r.items || []; page.loading = false; page.error = ""
        }).catch(function(e) { page.loading = false; page.error = e.message })
    }
    Component.onCompleted: load()
    Timer { id: searchDelay; interval: 300; onTriggered: page.load() }

    ColumnLayout {
        anchors.fill: parent; anchors.margins: Theme.pad
        spacing: Theme.gap
        PageHeader {
            Layout.fillWidth: true
            title: "Reports"
            Btn { compact: true; text: "Guided debrief"; visible: !shell.viewer; onClicked: shell.go("debrief") }
            Btn { compact: true; kind: "primary"; text: "+ New report"; visible: !shell.viewer; onClicked: shell.go("reportEdit", null) }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 8 * Theme.s
            Field { id: search; Layout.fillWidth: true; placeholderText: "Search titles"; onTextChanged: searchDelay.restart() }
            Select { id: status; options: [["", "Any status"], ["draft", "Draft"], ["confirmed", "Confirmed"]]; onPicked: page.load() }
            Select { id: crit; options: [["", "Any precedence"]].concat(Fmt.CRITICALITY.map(function(c) { return [c, c] }))
                     onPicked: page.load() }
            Select { id: sort; value: "recent"; options: [["recent", "Newest first"], ["criticality", "Most urgent first"]]
                     onPicked: page.load() }
        }
        Txt { visible: page.error !== ""; color: Theme.amber; text: page.error }
        Txt { visible: !page.loading && page.items.length === 0 && page.error === ""; kind: "muted"; text: "No reports found." }
        ListView {
            Layout.fillWidth: true; Layout.fillHeight: true
            clip: true
            spacing: 8 * Theme.s
            model: page.items
            ScrollBar.vertical: ScrollBar {}
            delegate: ListCard {
                width: ListView.view.width
                title: modelData.title
                meta: (modelData.credibility_rating ? "Credibility " + modelData.credibility_rating + " · " : "")
                      + Fmt.relativeTime(modelData.created_at)
                accent: modelData.criticality ? Theme.critColor(modelData.criticality) : "transparent"
                pills: [
                    Pill { text: modelData.status; tone: Theme.statusColor(modelData.status) },
                    Pill { visible: !!modelData.criticality; text: modelData.criticality || ""
                           tone: Theme.critColor(modelData.criticality); filled: modelData.criticality === "Flash" }
                ]
                onClicked: shell.go("report", modelData.id)
            }
        }
    }
}
