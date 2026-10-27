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
        }
    }
}
