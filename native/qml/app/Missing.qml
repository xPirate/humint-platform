import QtQuick
import ".."

// A section not built yet in the native app.
Rectangle {
    color: Theme.bg
    Column {
        anchors.centerIn: parent
        spacing: Theme.gap
        Txt { anchors.horizontalCenter: parent.horizontalCenter; kind: "title"; text: "Not here yet" }
        Txt { anchors.horizontalCenter: parent.horizontalCenter; kind: "muted"
              text: "This section is still being built for the native app." }
    }
}
