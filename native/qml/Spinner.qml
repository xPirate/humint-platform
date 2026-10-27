import QtQuick

// Three pulsing dots: something is happening.
Row {
    id: sp
    property color color: Theme.accent
    spacing: 8 * Theme.s
    property int tick: 0
    Timer { interval: 350; running: sp.visible; repeat: true; onTriggered: sp.tick = (sp.tick + 1) % 4 }
    Repeater {
        model: 3
        Rectangle {
            width: 10 * Theme.s; height: width; radius: width / 2
            color: sp.color
            opacity: index < sp.tick ? 1 : 0.25
        }
    }
}
