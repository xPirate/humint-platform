import QtQuick
import QtQuick.Controls

// A drop-down. model: [[value, label], ...]; `value` is the chosen value.
ComboBox {
    id: sel
    property var options: []
    property var value: ""
    signal picked(var value)
    model: options.map(function(o) { return o[1] })
    textRole: ""
    currentIndex: Math.max(0, options.findIndex(function(o) { return String(o[0]) === String(sel.value) }))
    onActivated: function(i) { sel.value = options[i][0]; sel.picked(options[i][0]) }
    implicitHeight: Theme.touch
    implicitWidth: Math.max(160 * Theme.s, (contentItem ? contentItem.implicitWidth : 0) + 60 * Theme.s)
    font.family: Theme.ui
    font.pixelSize: Theme.fs
    contentItem: Text {
        leftPadding: 12 * Theme.s; rightPadding: 30 * Theme.s
        text: sel.displayText; color: Theme.text
        font: sel.font; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight
    }
    indicator: Text { x: sel.width - width - 12 * Theme.s; anchors.verticalCenter: parent.verticalCenter
                      text: "▾"; color: Theme.muted; font.pixelSize: Theme.fs }
    background: Rectangle { radius: Theme.radius; color: Theme.panel2
                            border.color: sel.activeFocus ? Theme.accent : Theme.border; border.width: Math.max(1, Theme.s) }
    delegate: ItemDelegate {
        width: sel.popup.width
        height: Theme.touch
        highlighted: sel.highlightedIndex === index
        contentItem: Text { text: modelData; color: highlighted ? Theme.onAccent : Theme.text; font: sel.font
                            verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight }
        background: Rectangle { color: highlighted ? Theme.accentDim : Theme.panel }
    }
    popup: Popup {
        y: sel.height + 2 * Theme.s
        width: Math.max(sel.width, 220 * Theme.s)
        implicitHeight: Math.min(contentItem.implicitHeight + 2, 420 * Theme.s)
        padding: 1
        contentItem: ListView { clip: true; implicitHeight: contentHeight; model: sel.popup.visible ? sel.delegateModel : null }
        background: Rectangle { color: Theme.panel; border.color: Theme.borderStrong; radius: Theme.radius }
    }
}
