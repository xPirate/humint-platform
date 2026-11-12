import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Humint
import ".."
import "../lib/fmt.js" as Fmt

// Outside events (api/outside_events.py): what GDELT and ACLED say is
// happening inside the zones marked as areas of responsibility. Like feed
// items, they stop here: open-source, machine-gathered, unverified. The ones
// that matter go to Documents; the rest are dismissed.
Rectangle {
    id: page
    color: Theme.bg
    property var zones: []
    property int unreadTotal: 0
    property var zoneId: null          // null: every area
    property string status: "open"
    property string days: "7"
    property string source: ""
    property var items: []
    property int total: 0
    property bool loading: false
    property var credit: ({})

    function load() {
        page.loading = true
        var q = { status: page.status, limit: 100, q: search.text.trim() }
        if (page.zoneId !== null) q.zone_id = page.zoneId
        if (page.days) q.days = page.days
        if (page.source) q.source = page.source
        Net.get("/api/outside-events" + Net.qs(q)).then(function(r) {
            page.items = r.items || []; page.total = r.total || 0; page.zones = r.zones || []
            page.unreadTotal = r.unread_total || 0; page.credit = r.credit || {}; page.loading = false
        }).catch(function(e) { page.loading = false; ui.toast(e.message, true) })
    }
    Component.onCompleted: load()
    Timer { id: searchDelay; interval: 300; onTriggered: page.load() }

    function setStatus(item, st) {
        Net.post("/api/outside-events/" + item.id + "/status", { status: st }).then(page.load)
            .catch(function(e) { ui.toast(e.message, true) })
    }
    function srcName(s) { return s === "acled" ? "ACLED" : "GDELT" }
    readonly property string zoneName: {
        if (page.zoneId === null) return "every area"
        var z = page.zones.filter(function(x) { return x.id === page.zoneId })[0]
        return z ? z.name : "this area"
    }

    RowLayout {
        anchors.fill: parent; anchors.margins: Theme.pad
        spacing: Theme.gap * 1.5

        // The areas, with what is waiting in each
        Rectangle {
            Layout.preferredWidth: 260 * Theme.s; Layout.fillHeight: true
            radius: Theme.radius * 1.4; color: Theme.panel; border.color: Theme.border
            ListView {
                id: rail
                anchors.fill: parent; anchors.margins: 8 * Theme.s
                clip: true; spacing: 4 * Theme.s
                model: [{ id: null, name: "Every area", unread: page.unreadTotal }].concat(page.zones)
                footer: Txt { width: rail.width; visible: page.zones.length === 0; kind: "muted"; topPadding: Theme.gap
                              text: "No areas yet. On the map, draw a zone (or edit one) and tick “Pull outside events”. An admin turns the sources on under Admin → Outside events." }
                delegate: AbstractButton {
                    width: rail.width
                    implicitHeight: 44 * Theme.s
                    onClicked: { page.zoneId = modelData.id; page.load() }
                    background: Rectangle { radius: Theme.radius
                                            color: page.zoneId === modelData.id ? Theme.panel2 : "transparent"
                                            border.color: page.zoneId === modelData.id ? Theme.accent : "transparent" }
                    contentItem: RowLayout {
                        spacing: 6 * Theme.s
                        Txt { Layout.fillWidth: true; leftPadding: 6 * Theme.s; text: modelData.name; elide: Text.ElideRight; wrapMode: Text.NoWrap }
                        Pill { visible: modelData.unread > 0; text: String(modelData.unread); tone: Theme.accent; filled: true }
                        Item { width: 4 * Theme.s }
                    }
                }
            }
        }

        ColumnLayout {
            Layout.fillWidth: true; Layout.fillHeight: true
            spacing: Theme.gap
            PageHeader {
                Layout.fillWidth: true
                title: "Outside events"
                subtitle: "What open sources say is happening in your areas. Machine-gathered and unverified: send what matters to Documents, dismiss the rest."
                Btn { compact: true; text: "Dismiss all"; visible: (page.status === "open" || page.status === "new") && page.items.length > 0 && !shell.viewer
                      onClicked: ui.confirm("Dismiss everything open in " + page.zoneName + "?",
                                            "They stay findable under Dismissed until the retention window.", function() {
                          Net.post("/api/outside-events/dismiss-all", { zone_id: page.zoneId }).then(function(r) {
                              ui.toast("Dismissed " + r.dismissed); page.load()
                          }).catch(function(e) { ui.toast(e.message, true) })
                      }, false, "Dismiss all") }
            }
            RowLayout {
                Layout.fillWidth: true; spacing: 8 * Theme.s
                Field { id: search; Layout.fillWidth: true; placeholderText: "Search titles, places and notes"; onTextChanged: searchDelay.restart() }
                Select { Layout.preferredWidth: 170 * Theme.s; value: page.days
                         options: [["1", "Last day"], ["7", "Last week"], ["30", "Last month"], ["", "Any time"]]
                         onPicked: function(v) { page.days = v; page.load() } }
                Select { Layout.preferredWidth: 150 * Theme.s; value: page.source
                         options: [["", "Every source"], ["gdelt", "GDELT"], ["acled", "ACLED"]]
                         onPicked: function(v) { page.source = v; page.load() } }
                Select { Layout.preferredWidth: 200 * Theme.s; value: page.status
                         options: [["open", "Open"], ["new", "Unread"], ["sent", "Sent to Documents"], ["dismissed", "Dismissed"], ["all", "Everything"]]
                         onPicked: function(v) { page.status = v; page.load() } }
            }
            Txt { visible: page.total > 0; kind: "muted"
                  text: page.total + (page.total === 1 ? " event" : " events") + (page.total > page.items.length ? ", showing " + page.items.length : "") }
            Txt { visible: !page.loading && page.items.length === 0; kind: "muted"
                  text: page.zones.length === 0 ? "No area is set to pull outside events yet." : "Nothing here." }
            ListView {
                id: list
                Layout.fillWidth: true; Layout.fillHeight: true
                clip: true; spacing: 10 * Theme.s
                model: page.items
                ScrollBar.vertical: ScrollBar {}
                delegate: Rectangle {
                    width: list.width
                    implicitHeight: ic.implicitHeight + 2 * Theme.pad
                    radius: Theme.radius * 1.4; color: Theme.panel
                    border.color: modelData.status === "new" ? Theme.borderStrong : Theme.border
                    opacity: modelData.status === "dismissed" ? 0.6 : 1
                    ColumnLayout {
                        id: ic
                        x: Theme.pad; y: Theme.pad; width: parent.width - 2 * Theme.pad
                        spacing: 6 * Theme.s
                        RowLayout {
                            Layout.fillWidth: true; spacing: 8 * Theme.s
                            Pill { text: page.srcName(modelData.source); tone: modelData.source === "acled" ? Theme.amber : Theme.accent }
                            Txt { kind: "label"; text: modelData.category || "" }
                            Txt { kind: "muted"; text: modelData.occurred_on || "" }
                            Item { Layout.fillWidth: true }
                            Pill { visible: modelData.status === "sent"; text: "in Documents"; tone: Theme.accent }
                            Pill { visible: modelData.status === "dismissed"; text: "dismissed"; tone: Theme.muted }
                        }
                        Txt { Layout.fillWidth: true; text: modelData.title; font.weight: Font.DemiBold; font.pixelSize: 17 * Theme.s }
                        Txt { Layout.fillWidth: true; kind: "muted"
                              text: (modelData.place || "") + (modelData.precision ? " · placed at " + modelData.precision + " level" : "")
                                    + (modelData.num_sources ? " · " + modelData.num_sources + (modelData.num_sources === 1 ? " source" : " sources") : "")
                                    + (modelData.fatalities ? " · " + modelData.fatalities + " killed" : "")
                                    + (modelData.sources_named ? " · " + modelData.sources_named : "") }
                        Txt { Layout.fillWidth: true; visible: !!modelData.notes; font.family: Theme.prose
                              text: Fmt.truncate(modelData.notes || "", 400) }
                        Flow {
                            Layout.fillWidth: true; spacing: 6 * Theme.s
                            Btn { compact: true; kind: "primary"; visible: modelData.status !== "sent" && !shell.viewer
                                  text: "Send to Documents"; onClicked: send.open(modelData) }
                            Btn { compact: true; visible: modelData.status === "sent" && !!modelData.attachment_id
                                  text: "See the document"; onClicked: shell.go("document", modelData.attachment_id) }
                            Btn { compact: true; text: "On the map"
                                  onClicked: shell.go("map", { lat: modelData.lat, lng: modelData.lon }) }
                            Btn { compact: true; kind: "ghost"; visible: (modelData.status === "new" || modelData.status === "read") && !shell.viewer
                                  text: "Dismiss"; onClicked: page.setStatus(modelData, "dismissed") }
                            Btn { compact: true; kind: "ghost"; visible: modelData.status === "new" && !shell.viewer
                                  text: "Mark read"; onClicked: page.setStatus(modelData, "read") }
                            Btn { compact: true; kind: "ghost"; visible: modelData.status === "dismissed" && !shell.viewer
                                  text: "Put back"; onClicked: page.setStatus(modelData, "new") }
                            Btn { compact: true; kind: "ghost"; visible: !!modelData.url
                                  text: "The article"; onClicked: linkDlg.open(modelData) }
                        }
                    }
                }
            }
            // The sources' terms: say where it came from, with a link.
            Txt { Layout.fillWidth: true; kind: "muted"
                  text: "Data: GDELT Project (gdeltproject.org)" + (page.items.some(function(i) { return i.source === "acled" })
                        ? " · ACLED, Armed Conflict Location & Event Data (acleddata.com)" : "") }
        }
    }

    FormDialog {
        id: send
        property var item: null
        title: "Send to Documents"
        okText: busy ? "Fetching…" : "Send"
        function open(x) { item = x; fetch.checked = !!x.url; note.text = ""; visible = true }
        onAccepted: {
            busy = true
            Net.post("/api/outside-events/" + item.id + "/to-document",
                     { fetch_article: fetch.checked, source_note: note.text.trim() || null }).then(function(r) {
                busy = false; close()
                ui.toast(r.fetch_error ? "Sent, without the article — " + r.fetch_error : "Sent to Documents", !!r.fetch_error)
                page.load()
            }).catch(function(e) { busy = false; error = e.message })
        }
        Txt { width: parent.width; font.weight: Font.DemiBold; text: send.item ? send.item.title : "" }
        Txt { width: parent.width; kind: "muted"
              text: "It becomes a document like any other — marked as an outside event, with its source — and extraction proposes records for Review." }
        Check { id: fetch; visible: !!(send.item && send.item.url); text: "Fetch the article it came from"; checked: true }
        Labeled { label: "Where it came from"; hint: "Leave blank for the source's name."
                  Field { id: note; width: parent.width } }
    }

    // No browser here: the link, and a code to open it on a phone.
    FormDialog {
        id: linkDlg
        property var item: null
        title: "The article"
        okText: "Done"
        function open(x) { item = x; visible = true }
        onAccepted: close()
        Txt { width: parent.width; font.weight: Font.DemiBold; text: linkDlg.item ? linkDlg.item.title : "" }
        Row {
            width: parent.width; spacing: Theme.gap
            Rectangle {
                width: 200 * Theme.s; height: width; color: "white"; radius: Theme.radius
                Image { anchors.fill: parent; anchors.margins: 8 * Theme.s; smooth: false; fillMode: Image.PreserveAspectFit
                        source: linkDlg.item && linkDlg.item.url ? "image://qr/" + encodeURIComponent(linkDlg.item.url) : "" }
            }
            Column {
                width: parent.width - 200 * Theme.s - Theme.gap; spacing: 8 * Theme.s
                Txt { width: parent.width; text: "Scan to open it on a phone. This machine has no web browser." }
                Txt { width: parent.width; kind: "mono"; wrapMode: Text.WrapAnywhere; text: linkDlg.item ? (linkDlg.item.url || "") : "" }
            }
        }
    }
}
