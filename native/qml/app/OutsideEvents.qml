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
    // The reader: an event's article, fetched by the server once and kept.
    property int readerIndex: -1        // in items; -1 for a folded report
    property var reader: null           // {event, article, error, notes}
    property var readerEvent: null
    property bool readerLoading: false
    property var groups: ({})           // lead id -> its folded reports, once opened

    function lastQuery() {
        var q = { status: page.status, limit: 100, q: search.text.trim() }
        if (page.zoneId !== null) q.zone_id = page.zoneId
        if (page.days) q.days = page.days
        if (page.source) q.source = page.source
        return q
    }
    function load() {
        page.loading = true
        Net.get("/api/outside-events" + Net.qs(page.lastQuery())).then(function(r) {
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

    function openReader(item, index, refresh) {
        page.readerEvent = item; page.readerIndex = index; page.reader = null; page.readerLoading = true
        var id = item.id
        Net.get("/api/outside-events/" + id + "/article" + (refresh ? "?refresh=true" : "")).then(function(r) {
            if (!page.readerEvent || page.readerEvent.id !== id) return
            page.reader = r; page.readerLoading = false
            if (r.event.status === "new" && !shell.viewer)
                Net.post("/api/outside-events/" + id + "/status", { status: "read" }).then(function() {
                    var copy = page.items.slice()
                    for (var i = 0; i < copy.length; i++)
                        if (copy[i].id === id) { copy[i] = Object.assign({}, copy[i], { status: "read" }) }
                    page.items = copy
                })
        }).catch(function(e) { page.readerLoading = false; page.reader = { event: item, article: null, error: e.message } })
    }
    function step(d) {
        var i = page.readerIndex + d
        if (page.readerIndex < 0 || i < 0 || i >= page.items.length) return
        page.openReader(page.items[i], i)
    }
    function closeReader() { page.readerEvent = null; page.reader = null; page.readerIndex = -1 }
    function toggleGroup(lead) {
        var g = Object.assign({}, page.groups)
        if (g[lead.id]) { delete g[lead.id]; page.groups = g; return }
        Net.get("/api/outside-events/" + lead.id + "/similar").then(function(r) {
            var g2 = Object.assign({}, page.groups); g2[lead.id] = r.items || []; page.groups = g2
        }).catch(function(e) { ui.toast(e.message, true) })
    }
    function separate(m) {
        Net.post("/api/outside-events/" + m.id + "/separate", {}).then(function() {
            ui.toast("Separated — it is now an incident of its own"); page.groups = ({}); page.load()
        }).catch(function(e) { ui.toast(e.message, true) })
    }
    Shortcut { sequence: "Esc"; enabled: page.readerEvent !== null && page.visible; onActivated: page.closeReader() }
    Shortcut { sequence: "Right"; enabled: page.readerEvent !== null && page.visible && !search.activeFocus; onActivated: page.step(1) }
    Shortcut { sequence: "Left"; enabled: page.readerEvent !== null && page.visible && !search.activeFocus; onActivated: page.step(-1) }
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
            // Folded away while reading, unless the screen is wide enough.
            visible: page.readerEvent === null || page.width > 1500 * Theme.s
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
            Layout.preferredWidth: 1; Layout.minimumWidth: 360 * Theme.s
            clip: true
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
                Field { id: search; Layout.fillWidth: true; Layout.minimumWidth: 120 * Theme.s; Layout.preferredWidth: 300 * Theme.s; placeholderText: "Search titles, places and notes"; onTextChanged: searchDelay.restart() }
                Select { Layout.preferredWidth: 170 * Theme.s; Layout.fillWidth: true; Layout.minimumWidth: 96 * Theme.s; value: page.days
                         options: [["1", "Last day"], ["7", "Last week"], ["30", "Last month"], ["", "Any time"]]
                         onPicked: function(v) { page.days = v; page.load() } }
                Select { Layout.preferredWidth: 150 * Theme.s; Layout.fillWidth: true; Layout.minimumWidth: 96 * Theme.s; value: page.source
                         options: [["", "Every source"], ["gdelt", "GDELT"], ["acled", "ACLED"]]
                         onPicked: function(v) { page.source = v; page.load() } }
                Select { Layout.preferredWidth: 200 * Theme.s; Layout.fillWidth: true; Layout.minimumWidth: 96 * Theme.s; value: page.status
                         options: [["open", "Open"], ["new", "Unread"], ["sent", "Sent to Documents"], ["dismissed", "Dismissed"], ["all", "Everything"]]
                         onPicked: function(v) { page.status = v; page.load() } }
            }
            Txt { visible: page.total > 0; kind: "muted"
                  text: page.total + (page.total === 1 ? " incident" : " incidents") + (page.total > page.items.length ? ", showing " + page.items.length : "") }
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
                    border.color: page.readerEvent && page.readerEvent.id === modelData.id ? Theme.accent
                                  : modelData.status === "new" ? Theme.borderStrong : Theme.border
                    border.width: page.readerEvent && page.readerEvent.id === modelData.id ? 2 : 1
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
                        Txt { Layout.fillWidth: true; text: modelData.headline || modelData.title; font.weight: Font.DemiBold; font.pixelSize: 17 * Theme.s
                              TapHandler { enabled: !!(modelData.url || modelData.notes); onTapped: page.openReader(modelData, index) } }
                        Txt { Layout.fillWidth: true; kind: "muted"; visible: !!modelData.headline
                              text: modelData.title + (modelData.site ? " · " + modelData.site : "") }
                        Txt { Layout.fillWidth: true; kind: "muted"
                              text: (modelData.place || "") + (modelData.precision ? " · placed at " + modelData.precision + " level" : "")
                                    + (modelData.num_sources ? " · " + modelData.num_sources + (modelData.num_sources === 1 ? " source" : " sources") : "")
                                    + (modelData.fatalities ? " · " + modelData.fatalities + " killed" : "")
                                    + (modelData.sources_named ? " · " + modelData.sources_named : "") }
                        Txt { Layout.fillWidth: true; visible: !!modelData.notes; font.family: Theme.prose
                              text: Fmt.truncate(modelData.notes || "", 400) }
                        Flow {
                            Layout.fillWidth: true; spacing: 6 * Theme.s
                            Btn { compact: true; visible: !!(modelData.url || modelData.notes)
                                  text: "Read"; onClicked: page.openReader(modelData, index) }
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
                            Btn { compact: true; kind: "ghost"; visible: modelData.similar > 0
                                  text: (page.groups[modelData.id] ? "Hide " : "+") + modelData.similar
                                        + (modelData.similar === 1 ? " similar report" : " similar reports")
                                  onClicked: page.toggleGroup(modelData) }
                        }
                        // The folded reports: the same incident as other reports have it.
                        Repeater {
                            model: page.groups[modelData.id] || []
                            delegate: Rectangle {
                                required property var modelData
                                Layout.fillWidth: true; Layout.leftMargin: 14 * Theme.s
                                implicitHeight: mc.implicitHeight + 16 * Theme.s
                                radius: Theme.radius; color: Theme.panel2; border.color: Theme.border
                                ColumnLayout {
                                    id: mc
                                    x: 10 * Theme.s; y: 8 * Theme.s; width: parent.width - 20 * Theme.s; spacing: 4 * Theme.s
                                    RowLayout {
                                        Layout.fillWidth: true; spacing: 8 * Theme.s
                                        Pill { text: page.srcName(modelData.source); tone: modelData.source === "acled" ? Theme.amber : Theme.accent }
                                        Txt { Layout.fillWidth: true; kind: "muted"; elide: Text.ElideRight; wrapMode: Text.NoWrap
                                              text: "matched: " + (modelData.dup_reason_text || "") }
                                    }
                                    Txt { Layout.fillWidth: true; font.weight: Font.DemiBold; text: modelData.headline || modelData.title }
                                    Txt { Layout.fillWidth: true; kind: "muted"; visible: !!modelData.site; text: modelData.site || "" }
                                    Flow {
                                        Layout.fillWidth: true; spacing: 6 * Theme.s
                                        Btn { compact: true; visible: !!(modelData.url || modelData.notes); text: "Read"
                                              onClicked: page.openReader(modelData, -1) }
                                        Btn { compact: true; kind: "ghost"; visible: !shell.viewer; text: "Not the same"
                                              onClicked: page.separate(modelData) }
                                    }
                                }
                            }
                        }
                    }
                }
            }
            // The sources' terms: say where it came from, with a link.
            Txt { Layout.fillWidth: true; kind: "muted"
                  text: "Data: GDELT Project (gdeltproject.org)" + (page.items.some(function(i) { return i.source === "acled" })
                        ? " · ACLED, Armed Conflict Location & Event Data (acleddata.com)" : "") }
        }

        // The reader: the article as headline and paragraphs, beside the list.
        Rectangle {
            id: readerPane
            objectName: "outsideReader"
            visible: page.readerEvent !== null
            Layout.preferredWidth: Math.min(680 * Theme.s, page.width * 0.5); Layout.fillHeight: true
            Layout.minimumWidth: Layout.preferredWidth
            radius: Theme.radius * 1.4; color: Theme.panel; border.color: Theme.border
            readonly property var ev: page.reader ? page.reader.event : page.readerEvent
            readonly property var art: page.reader ? page.reader.article : null
            ColumnLayout {
                anchors.fill: parent; anchors.margins: Theme.pad
                spacing: Theme.gap
                RowLayout {
                    Layout.fillWidth: true; spacing: 8 * Theme.s
                    Pill { visible: !!readerPane.ev; text: readerPane.ev ? page.srcName(readerPane.ev.source) : "" ; tone: Theme.accent }
                    Txt { Layout.fillWidth: true; kind: "muted"; elide: Text.ElideRight; wrapMode: Text.NoWrap
                          text: [readerPane.art ? readerPane.art.site : "", readerPane.ev ? readerPane.ev.occurred_on : "",
                                 page.readerIndex >= 0 ? (page.readerIndex + 1) + " of " + page.items.length : ""]
                                .filter(function(x) { return !!x }).join(" · ") }
                    Btn { compact: true; kind: "ghost"; text: "← Previous"; enabled: page.readerIndex > 0; onClicked: page.step(-1) }
                    Btn { compact: true; kind: "ghost"; text: "Next →"; enabled: page.readerIndex >= 0 && page.readerIndex < page.items.length - 1
                          onClicked: page.step(1) }
                    Btn { compact: true; kind: "ghost"; text: "Close"; onClicked: page.closeReader() }
                }
                Flickable {
                    id: readerFlick
                    Layout.fillWidth: true; Layout.fillHeight: true
                    clip: true; contentHeight: rc.implicitHeight; contentWidth: width
                    ScrollBar.vertical: ScrollBar {}
                    ColumnLayout {
                        id: rc
                        width: readerFlick.width - 14 * Theme.s
                        spacing: 12 * Theme.s
                        Txt { Layout.fillWidth: true; font.weight: Font.Bold; font.pixelSize: 22 * Theme.s
                              text: (readerPane.art && readerPane.art.title) || (readerPane.ev ? readerPane.ev.title : "") }
                        Txt { Layout.fillWidth: true; kind: "muted"
                              text: readerPane.ev ? readerPane.ev.title + " · " + (readerPane.ev.place || "") + " · unverified open source" : "" }
                        Txt { visible: page.readerLoading; kind: "muted"; text: "Reading…" }
                        Txt { Layout.fillWidth: true; visible: !page.readerLoading && !readerPane.art && !!page.reader
                              color: Theme.red; text: page.reader ? (page.reader.error || "") : "" }
                        Txt { Layout.fillWidth: true; visible: !page.readerLoading && !readerPane.art && !!(page.reader && page.reader.notes)
                              font.family: Theme.prose; text: page.reader ? (page.reader.notes || "") : "" }
                        Repeater {
                            model: readerPane.art ? readerPane.art.text.split(/\n\n+/) : []
                            delegate: Txt {
                                required property string modelData
                                Layout.fillWidth: true
                                readonly property bool heading: modelData.indexOf("## ") === 0
                                text: heading ? modelData.slice(3) : modelData
                                font.family: heading ? Theme.ui : Theme.prose
                                font.weight: heading ? Font.DemiBold : Font.Normal
                                font.pixelSize: (heading ? 18 : 17) * Theme.s
                                lineHeight: 1.35
                            }
                        }
                    }
                }
                Flow {
                    Layout.fillWidth: true; spacing: 6 * Theme.s
                    Btn { compact: true; kind: "primary"; visible: !!readerPane.ev && readerPane.ev.status !== "sent" && !shell.viewer
                          text: "Send to Documents"; onClicked: send.open(readerPane.ev) }
                    Btn { compact: true; visible: !!readerPane.ev && (readerPane.ev.status === "new" || readerPane.ev.status === "read") && !shell.viewer
                          text: "Dismiss"
                          onClicked: {
                              var i = page.readerIndex
                              Net.post("/api/outside-events/" + readerPane.ev.id + "/status", { status: "dismissed" }).then(function() {
                                  ui.toast("Dismissed")
                                  Net.get("/api/outside-events" + Net.qs(page.lastQuery())).then(function(r) {
                                      page.items = r.items || []; page.total = r.total || 0
                                      if (i >= 0 && page.items[i]) page.openReader(page.items[i], i); else page.closeReader()
                                  })
                              }).catch(function(e) { ui.toast(e.message, true) })
                          } }
                    Btn { compact: true; kind: "ghost"; visible: !!page.reader && !readerPane.art && !!(readerPane.ev && readerPane.ev.url)
                          text: "Try again"; onClicked: page.openReader(page.readerEvent, page.readerIndex, true) }
                    Btn { compact: true; kind: "ghost"; visible: !!(readerPane.ev && readerPane.ev.url)
                          text: "The original"; onClicked: linkDlg.open(readerPane.art ? { title: readerPane.ev.title, url: readerPane.art.url } : readerPane.ev) }
                }
            }
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
        title: "The original"
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
