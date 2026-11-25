import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Humint
import ".."

// The language model the worker and the assistant use (Ollama), if any.
Rectangle {
    color: Theme.bg
    property var status: null
    Component.onCompleted: Net.get("/api/ollama-status").then(function(r) { status = r }).catch(function() {})
    Flickable {
        anchors.fill: parent; anchors.margins: Theme.pad
        contentHeight: mcol.implicitHeight
        clip: true
        Column {
            id: mcol
            width: parent.width; spacing: Theme.gap
            PageHeader { width: parent.width; title: "Model"
                         subtitle: "Reading documents for names and links, comparing records, and the assistant use a model server (Ollama). Without one, everything else works." }
            Txt { width: parent.width; color: status && status.reachable ? Theme.accent : Theme.amber
                  text: !status ? "" : status.enabled === false ? "Switched off." : status.reachable ? "The model server is answering." : "The model server is not answering." }
            SettingsFields {
                endpoint: "/api/admin/ollama-settings"
                labels: ({ ollama_enabled: "Use a model", ollama_base_url: "Model server address", ollama_model: "Assistant model",
                           ollama_extract_model: "Document-reading model", ollama_embed_model: "Comparison model",
                           ollama_timeout_seconds: "Time limit (seconds)", assistant_thinking: "Assistant thinks first",
                           assistant_context_tokens: "Assistant context (tokens)", assistant_max_lookups: "Assistant look-ups per answer" })
            }

            // ---- web research (api/web_research.py) ----
            Card {
                id: wr
                width: parent.width; title: "Web research"
                property var w: null
                function load() { Net.get("/api/admin/web-research").then(function(r) { wr.w = r; wrApply() }).catch(function() {}) }
                function wrApply() {
                    wrOn.checked = w.enabled; wrProvider.value = w.provider; wrSearx.text = w.searxng_url || ""
                    wrProxy.text = w.proxy_url || ""; wrApprove.checked = w.require_approval; wrWho.value = w.allowed
                    wrNs.text = String(w.max_searches); wrNp.text = String(w.max_pages); wrKey.text = ""
                }
                Component.onCompleted: load()
                implicitHeight: wrc.implicitHeight + 2 * padding + Theme.gap + 20 * Theme.s
                ColumnLayout {
                    id: wrc
                    width: parent.width; spacing: 8 * Theme.s
                    Txt { Layout.fillWidth: true; kind: "muted"
                          text: "Let the assistant search the web and read pages, for questions where the person asking allows it. Searches leave this machine — names and all — so it is off until turned on here. Every search and page read is in the audit log." }
                    Check { id: wrOn; text: "Allow web research (each question still has to allow it)" }
                    Labeled { Layout.fillWidth: true; label: "Search with"
                              Select { id: wrProvider; width: parent.width
                                       options: [["searxng", "SearXNG — self-hosted, no key or account"], ["brave", "Brave Search API — needs a key"],
                                                 ["duckduckgo", "DuckDuckGo — nothing to set up; light use, may refuse"]]
                                       onPicked: function(v) { value = v } } }
                    Labeled { Layout.fillWidth: true; visible: wrProvider.value === "searxng"; label: "SearXNG address"
                              hint: "Its settings.yml must allow the json format."
                              Field { id: wrSearx; width: parent.width; placeholderText: "http://searxng:8080" } }
                    Labeled { Layout.fillWidth: true; visible: wrProvider.value === "brave"; label: "Brave API key"
                              hint: wr.w && wr.w.has_brave_key ? "Set — leave empty to keep it." : "From Brave's API dashboard."
                              Field { id: wrKey; width: parent.width; echoMode: TextInput.Password } }
                    Labeled { Layout.fillWidth: true; label: "Through a proxy (optional)"
                              hint: "A VPN's proxy, or Tor as socks5h://127.0.0.1:9050 (names resolved there). Empty: straight out."
                              Field { id: wrProxy; width: parent.width; placeholderText: "socks5h://127.0.0.1:9050" } }
                    Check { id: wrApprove; text: "Show each search to the person before it is sent (recommended)" }
                    RowLayout {
                        Layout.fillWidth: true; spacing: Theme.gap
                        Labeled { Layout.fillWidth: true; Layout.preferredWidth: 1; label: "Who may use it"
                                  Select { id: wrWho; width: parent.width; options: [["analysts", "Analysts and admins"], ["admins", "Admins only"]]
                                           onPicked: function(v) { value = v } } }
                        Labeled { Layout.fillWidth: true; Layout.preferredWidth: 1; label: "Searches per question"
                                  Field { id: wrNs; width: parent.width; inputMethodHints: Qt.ImhDigitsOnly } }
                        Labeled { Layout.fillWidth: true; Layout.preferredWidth: 1; label: "Pages per question"
                                  Field { id: wrNp; width: parent.width; inputMethodHints: Qt.ImhDigitsOnly } }
                    }
                    Flow {
                        Layout.fillWidth: true; spacing: 6 * Theme.s
                        Btn { kind: "primary"; text: "Save web research"
                              onClicked: {
                                  var b = { enabled: wrOn.checked, provider: wrProvider.value, searxng_url: wrSearx.text.trim(),
                                            proxy_url: wrProxy.text.trim(), require_approval: wrApprove.checked, allowed: wrWho.value,
                                            max_searches: parseInt(wrNs.text, 10), max_pages: parseInt(wrNp.text, 10) }
                                  if (wrKey.text.trim()) b.brave_key = wrKey.text.trim()
                                  Net.put("/api/admin/web-research", b).then(function(r) { wr.w = r; wr.wrApply(); ui.toast("Saved") })
                                      .catch(function(e) { ui.toast(e.message, true) })
                              } }
                        Btn { text: "Test with a harmless search"
                              onClicked: Net.post("/api/admin/web-research/test", {}).then(function(r) {
                                  wrTest.text = r.results.length + " result(s): " + r.results.map(function(x) { return x.title }).join(" · ")
                              }).catch(function(e) { wrTest.text = e.message }) }
                    }
                    Txt { id: wrTest; Layout.fillWidth: true; kind: "muted"; text: "" }
                }
            }
        }
    }
}
