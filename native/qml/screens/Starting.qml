import QtQuick
import ".."

// Before the machine's helper answers (the first seconds of a boot).
Rectangle {
    color: Theme.bg
    Column {
        anchors.centerIn: parent
        spacing: Theme.gap * 2
        Txt { anchors.horizontalCenter: parent.horizontalCenter; kind: "huge"; text: "HUMINT"; color: Theme.accent }
        Txt { anchors.horizontalCenter: parent.horizontalCenter; kind: "muted"; text: "Starting…" }
        Spinner { anchors.horizontalCenter: parent.horizontalCenter }
    }
}
