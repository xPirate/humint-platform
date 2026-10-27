import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Humint
import ".."
import "../lib/fmt.js" as Fmt

// RSS feeds (api/feeds.py). Items stop here: the few that matter go to
// Documents and take the normal route in (extraction, then Review); the rest
// are dismissed. There is no browser on this machine, so an item's link is
// shown with a QR code, to open on a phone.
Rectangle {
    id: page
    color: Theme.bg
    property var feeds: []
    property int unreadTotal: 0
    property var feedId: null          // null: all feeds
    property string status: "new"
    property var items: []
    property int total: 0
    property bool loading: false

    function loadFeeds() {
        Net.get("/api/feeds").then(function(r) { page.feeds = r.items || []; page.unreadTotal = r.unread_total || 0 })
            .catch(function(e) { ui.toast(e.message, true) })
    }
    function loadItems() {
        page.loading = true
        var q = { status: page.status, limit: 100, q: search.text.trim() }
        if (page.feedId !== null) q.feed_id = page.feedId
        Net.get("/api/feeds/items" + Net.qs(q)).then(function(r) {
            page.items = r.items || []; page.total = r.total || 0; page.loading = false
        }).catch(function(e) { page.loading = false; ui.toast(e.message, true) })
    }
    function reload() { loadFeeds(); loadItems() }
    Component.onCompleted: reload()
    Timer { id: searchDelay; interval: 300; onTriggered: page.loadItems() }

    function setStatus(item, st) {
        Net.post("/api/feeds/items/" + item.id + "/status", { status: st }).then(page.reload)
            .catch(function(e) { ui.toast(e.message, true) })
    }
    readonly property string feedName: {
        if (page.feedId === null) return "every feed"
        var f = page.feeds.filter(function(x) { return x.id === page.feedId })[0]
        return f ? f.label : "this feed"
    }

    RowLayout {
        anchors.fill: parent; anchors.margins: Theme.pad
        spacing: Theme.gap * 1.5

        // The feeds, with what is waiting on each
        Rectangle {
            Layout.preferredWidth: 260 * Theme.s; Layout.fillHeight: true
            radius: Theme.radius * 1.4; color: Theme.panel; border.color: Theme.border
            ListView {
                id: rail
                anchors.fill: parent; anchors.margins: 8 * Theme.s
                clip: true; spacing: 4 * Theme.s
                model: [{ id: null, label: "All feeds", unread: page.unreadTotal, is_active: true }].concat(page.feeds)
                header: Item { width: 1; height: 0 }
                footer: Txt { width: rail.width; visible: page.feeds.length === 0; kind: "muted"; topPadding: Theme.gap
                              text: "No feeds yet. An admin adds them under Admin → RSS feeds." }
                delegate: AbstractButton {
                    width: rail.width
                    implicitHeight: 44 * Theme.s
                    onClicked: { page.feedId = modelData.id; page.loadItems() }
                    background: Rectangle { radius: Theme.radius
                                            color: page.feedId === modelData.id ? Theme.panel2 : "transparent"
                                            border.color: page.feedId === modelData.id ? Theme.accent : "transparent" }
                    contentItem: RowLayout {
                        spacing: 6 * Theme.s
                        Txt { Layout.fillWidth: true; leftPadding: 6 * Theme.s; text: modelData.label; elide: Text.ElideRight
                              wrapMode: Text.NoWrap; opacity: modelData.is_active ? 1 : 0.55 }
                        Txt { visible: !!modelData.last_error; text: "!"; color: Theme.amber; font.weight: Font.Bold }
                        Txt { visible: !modelData.is_active; kind: "muted"; text: "paused" }
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
                title: "Feeds"
                subtitle: "Send what matters to Documents; dismiss the rest. Nothing reaches the case file until it is accepted in Review."
                Btn { compact: true; text: "Dismiss all unread"; visible: page.status === "new" && page.items.length > 0
                      onClicked: ui.confirm("Dismiss everything unread in " + page.feedName + "?",
                                            "They stay findable under Dismissed.", function() {
                          Net.post("/api/feeds/items/dismiss-all", { feed_id: page.feedId }).then(function(r) {
                              ui.toast("Dismissed " + r.dismissed); page.reload()
                          }).catch(function(e) { ui.toast(e.message, true) })
                      }, false, "Dismiss all") }
            }
            RowLayout {
                Layout.fillWidth: true; spacing: 8 * Theme.s
                Field { id: search; Layout.fillWidth: true; placeholderText: "Search titles and summaries"; onTextChanged: searchDelay.restart() }
                Select { id: statusPick; Layout.preferredWidth: 220 * Theme.s; value: page.status
                         options: [["new", "Unread"], ["sent", "Sent to Documents"], ["dismissed", "Dismissed"], ["all", "Everything"]]
                         onPicked: function(v) { page.status = v; page.loadItems() } }
            }
            Txt { visible: page.total > 0; kind: "muted"
                  text: page.total + (page.total === 1 ? " item" : " items") + (page.total > page.items.length ? ", showing " + page.items.length : "") }
            Txt { visible: !page.loading && page.items.length === 0; kind: "muted"
                  text: page.status === "new" ? "Nothing waiting. That is the good state." : "Nothing here." }
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
                            Txt { kind: "label"; text: modelData.feed_label }
                            Txt { kind: "muted"; text: Fmt.relativeTime(modelData.published_at || modelData.created_at) }
                            Item { Layout.fillWidth: true }
                            Pill { visible: modelData.status === "sent"; text: "in Documents"; tone: Theme.accent }
                            Pill { visible: modelData.status === "dismissed"; text: "dismissed"; tone: Theme.muted }
                        }
                        Txt { Layout.fillWidth: true; text: modelData.title || "Untitled item"
                              font.weight: Font.DemiBold; font.pixelSize: 17 * Theme.s }
                        Txt { Layout.fillWidth: true; visible: !!modelData.summary; font.family: Theme.prose
                              text: Fmt.truncate(modelData.summary || "", 400) }
                        Flow {
                            Layout.fillWidth: true; spacing: 6 * Theme.s
                            Btn { compact: true; kind: "primary"; visible: modelData.status !== "sent" && !shell.viewer
                                  text: "Send to Documents"; onClicked: send.open(modelData) }
                            Btn { compact: true; visible: modelData.status === "sent" && !!modelData.attachment_id
                                  text: "See the document"; onClicked: shell.go("document", modelData.attachment_id) }
                            Btn { compact: true; kind: "ghost"; visible: modelData.status === "new" && !shell.viewer
                                  text: "Dismiss"; onClicked: page.setStatus(modelData, "dismissed") }
                            Btn { compact: true; kind: "ghost"; visible: modelData.status === "dismissed" && !shell.viewer
                                  text: "Put back"; onClicked: page.setStatus(modelData, "new") }
                            Btn { compact: true; kind: "ghost"; visible: !!modelData.link
                                  text: "The original"; onClicked: linkDlg.open(modelData) }
                            Txt { visible: modelData.status === "sent" && !!modelData.sent_by_name; kind: "muted"
                                  text: "sent by " + (modelData.sent_by_name || "") }
                        }
                    }
                }
            }
        }
    }

    FormDialog {
        id: send
        property var item: null
        title: "Send to Documents"
        okText: busy ? "Fetching…" : "Send"
        function open(x) { item = x; fetch.checked = true; note.text = ""; visible = true }
        onAccepted: {
            busy = true
            Net.post("/api/feeds/items/" + item.id + "/to-document",
                     { fetch_article: fetch.checked, source_note: note.text.trim() || null }).then(function(r) {
                busy = false; close()
                ui.toast(r.fetch_error ? "Sent, with the summary only — " + r.fetch_error
                                       : "Sent to Documents (" + Number(r.chars).toLocaleString() + " characters)", !!r.fetch_error)
                page.reload()
            }).catch(function(e) { busy = false; error = e.message })
        }
        Txt { width: parent.width; font.weight: Font.DemiBold; text: send.item ? (send.item.title || "Untitled item") : "" }
        Txt { width: parent.width; kind: "muted"
              text: "It becomes a document like any other: the worker reads it, extraction proposes records, and you accept them in Review." }
        Check { id: fetch; text: "Fetch the full article"; checked: true }
        Txt { width: parent.width; kind: "muted"
              text: "Pulls the linked page so the document holds the article, not the one-paragraph summary. If that fails (paywall, script-only page, no internet) the summary is used and the document says why." }
        Labeled { label: "Where it came from"; hint: "Leave blank for the feed's name."
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
        Txt { width: parent.width; font.weight: Font.DemiBold; text: linkDlg.item ? (linkDlg.item.title || "") : "" }
        Row {
            width: parent.width; spacing: Theme.gap
            Rectangle {
                width: 200 * Theme.s; height: width; color: "white"; radius: Theme.radius
                Image { anchors.fill: parent; anchors.margins: 8 * Theme.s; smooth: false; fillMode: Image.PreserveAspectFit
                        source: linkDlg.item && linkDlg.item.link ? "image://qr/" + encodeURIComponent(linkDlg.item.link) : "" }
            }
            Column {
                width: parent.width - 200 * Theme.s - Theme.gap; spacing: 8 * Theme.s
                Txt { width: parent.width; text: "Scan to open it on a phone. This machine has no web browser." }
                Txt { width: parent.width; kind: "mono"; wrapMode: Text.WrapAnywhere; text: linkDlg.item ? (linkDlg.item.link || "") : "" }
            }
        }
    }
}
