import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Humint
import ".."
import "../lib/fmt.js" as Fmt

// The document inbox: files brought in (from a USB stick here) or text
// pasted, read by the worker (OCR, text extraction) and proposing records.
// Search covers the text inside them.
Rectangle {
    id: page
    color: Theme.bg
    property var items: []
    property bool loading: true
    readonly property var statusLabels: ({ pending: "Waiting", processing: "Reading", done: "Read", failed: "Failed", skipped: "Skipped" })

    function load() {
        Net.get("/api/documents" + Net.qs({ status: status.value, archived: archived.checked ? "true" : "false",
                                            q: search.text.trim() })).then(function(r) {
            page.items = r.items || []; page.loading = false
        }).catch(function(e) { page.loading = false; ui.toast(e.message, true) })
    }
    Component.onCompleted: load()
    Timer { id: searchDelay; interval: 300; onTriggered: page.load() }
    // While anything is still being read, look again.
    Timer { interval: 4000; repeat: true
            running: page.items.some(function(d) { return d.extraction_status === "pending" || d.extraction_status === "processing" })
            onTriggered: page.load() }

    ColumnLayout {
        anchors.fill: parent; anchors.margins: Theme.pad
        spacing: Theme.gap
        PageHeader {
            Layout.fillWidth: true
            title: "Documents"
            subtitle: "Read by the machine; nothing they propose enters the case file until you accept it."
            Btn { compact: true; text: "Paste text"; visible: !shell.viewer; onClicked: paste.open() }
            Btn { compact: true; kind: "primary"; text: "+ From USB"; visible: !shell.viewer
                  onClicked: usb.pickFile(function(path) {
                      ui.busy("Bringing it in…")
                      Net.upload("/api/attachments", path, {}).then(function() {
                          ui.busy(""); ui.toast("Added — it will be read shortly"); page.load()
                      }).catch(function(e) { ui.busy(""); ui.toast(e.message, true) })
                  }) }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 8 * Theme.s
            Field { id: search; Layout.fillWidth: true; placeholderText: "Search titles and the text inside"
                    onTextChanged: searchDelay.restart() }
            Select { id: status; value: "all"
                     options: [["all", "Any state"], ["pending", "Waiting"], ["processing", "Reading"], ["done", "Read"],
                               ["failed", "Failed"], ["skipped", "Skipped"]]
                     onPicked: page.load() }
            Check { id: archived; text: "Archived"; onToggled: page.load() }
        }
        Txt { visible: !page.loading && page.items.length === 0; kind: "muted"
              text: archived.checked ? "Nothing archived." : "Nothing in the inbox. Bring a file in from a USB stick, or paste text." }
        ListView {
            Layout.fillWidth: true; Layout.fillHeight: true
            clip: true; spacing: 8 * Theme.s
            model: page.items
            ScrollBar.vertical: ScrollBar {}
            delegate: ListCard {
                width: ListView.view.width
                title: modelData.title || modelData.filename
                meta: [modelData.title && modelData.filename !== modelData.title ? modelData.filename : "",
                       Fmt.fileSize(modelData.file_size_bytes), "added " + Fmt.relativeTime(modelData.uploaded_at),
                       modelData.source_note || ""].filter(function(x) { return x }).join(" · ")
                snippet: (modelData.extraction_status === "failed" || modelData.extraction_status === "done") && modelData.extraction_error
                         ? modelData.extraction_error : ""
                pills: [
                    Pill { text: page.statusLabels[modelData.extraction_status] || modelData.extraction_status
                           tone: ({ failed: Theme.red, done: Theme.accent, pending: Theme.amber, processing: Theme.teal })[modelData.extraction_status] || Theme.muted },
                    Pill { visible: !!modelData.is_pasted; text: "pasted"; tone: Theme.teal },
                    Pill { visible: (modelData.pending_suggestion_count || 0) > 0; text: (modelData.pending_suggestion_count || 0) + " to review"; tone: Theme.amber }
                ]
                onClicked: shell.go("document", modelData.id)
            }
        }
    }

    FormDialog {
        id: paste
        title: "Paste text"
        okText: "Add"
        onOpened: { pTitle.text = ""; pText.text = ""; pSource.text = "" }
        onAccepted: {
            if (!pText.text.trim()) { error = "There is no text."; return }
            busy = true
            Net.post("/api/documents/text", { text: pText.text, title: pTitle.text.trim() || null, source_note: pSource.text.trim() || null })
                .then(function() { busy = false; close(); ui.toast("Added — it will be read shortly"); page.load() })
                .catch(function(e) { busy = false; error = e.message })
        }
        Labeled { label: "Title"; Field { id: pTitle; width: parent.width } }
        Labeled { label: "Where it came from"; Field { id: pSource; width: parent.width } }
        Labeled { label: "Text"
                  TextArea { id: pText; width: parent.width; height: 220 * Theme.s; wrapMode: TextEdit.Wrap; color: Theme.text
                             font.family: Theme.prose; font.pixelSize: Theme.fs; padding: 12 * Theme.s
                             background: Rectangle { color: Theme.panel2; radius: Theme.radius; border.color: pText.activeFocus ? Theme.accent : Theme.border } } }
    }
}
