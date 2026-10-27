import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Humint
import ".."

// What this case file is called, and its default look.
Rectangle {
    color: Theme.bg
    Flickable {
        anchors.fill: parent; anchors.margins: Theme.pad
        contentHeight: bcol.implicitHeight
        clip: true
        Column {
            id: bcol
            width: parent.width; spacing: Theme.gap
            PageHeader { width: parent.width; title: "Appearance"
                         subtitle: "The default look. Anyone can change their own from their account." }
            SettingsFields {
                endpoint: "/api/admin/branding"
                labels: ({ instance_name: "Name of this case file", default_palette: "Default palette (terminal, slate, graphite, archive)",
                           brand_accent: "Accent colour (#rrggbb)" })
            }
        }
    }
}
