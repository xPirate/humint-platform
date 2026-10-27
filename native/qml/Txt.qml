import QtQuick

// Text in the app's face and colours. kind: "body" | "muted" | "label" |
// "title" | "huge" | "mono" | "prose".
Text {
    property string kind: "body"
    color: kind === "muted" || kind === "label" ? Theme.muted : Theme.text
    font.family: kind === "mono" ? "IBM Plex Mono" : kind === "prose" ? Theme.prose : Theme.ui
    readonly property real size: kind === "huge" ? Theme.fsHuge : kind === "title" ? Theme.fsTitle
                               : kind === "label" ? Theme.fsLabel : kind === "muted" ? Theme.fsSmall : Theme.fs
    font.pixelSize: size
    font.weight: kind === "title" || kind === "huge" ? Font.DemiBold : kind === "label" ? Font.Medium : Font.Normal
    font.capitalization: kind === "label" && Theme.caps ? Font.AllUppercase : Font.MixedCase
    font.letterSpacing: kind === "label" && Theme.caps ? 0.07 * size : 0
    wrapMode: Text.Wrap
    textFormat: Text.PlainText
    elide: wrapMode === Text.NoWrap ? Text.ElideRight : Text.ElideNone
}
