import QtQuick
import QtQuick.VirtualKeyboard

// Qt's on-screen keyboard. It slides up whenever a text field is focused and
// no hardware keyboard is typing.
InputPanel {
    id: panel
    width: parent ? parent.width : 0
    y: active ? 0 : height
    visible: active
}
