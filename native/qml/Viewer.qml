import QtQuick
import QtQuick.Controls
import Humint

// Looking at a file from the case file, full screen: images, PDFs (fetched
// into memory-backed storage only for as long as they are open), text.
Rectangle {
    id: v
    anchors.fill: parent
    visible: att !== null
    color: Theme.bg
    property var att: null
    property string kind: ""       // image | pdf | text | other
    property string localPath: ""
    property string textBody: ""
    property bool loading: false

    function show(a) {
        close()
        v.att = a
        var mime = (a.mime_type || "").toLowerCase()
        var name = (a.filename || "").toLowerCase()
        if (/^image\//.test(mime)) { v.kind = "image"; return }
        if (mime === "application/pdf" || /\.pdf$/.test(name)) v.kind = "pdf"
        else if (/^text\//.test(mime) || /\.(txt|md|csv|log|json)$/.test(name)) v.kind = "text"
        else { v.kind = "other"; return }
        v.loading = true
        var path = Util.tempPath("att-" + a.id + "-" + a.filename)
        Net.download("/api/attachments/" + a.id + "/file", path).then(function() {
            v.loading = false
            v.localPath = path
            if (v.kind === "text") v.textBody = Util.readText(path)
        }).catch(function(e) { v.loading = false; ui.toast(e.message, true); v.close() })
    }
    function close() {
        if (v.localPath) Util.removeFile(v.localPath)
        v.localPath = ""; v.textBody = ""; v.att = null; v.kind = ""
    }

    MouseArea { anchors.fill: parent }

    StatusStrip {
        id: strip
        anchors.top: parent.top; width: parent.width
        title: v.att ? v.att.filename : ""
        leftItems: [ Btn { compact: true; text: "← Close"; onClicked: v.close() } ]
    }

    Item {
        anchors.top: strip.bottom; anchors.bottom: parent.bottom
        anchors.left: parent.left; anchors.right: parent.right
        anchors.margins: Theme.pad

        Spinner { anchors.centerIn: parent; visible: v.loading }

        Flickable {
            id: imgFlick
            anchors.fill: parent
            visible: v.kind === "image"
            contentWidth: Math.max(width, img.width * img.scale)
            contentHeight: Math.max(height, img.height * img.scale)
            clip: true
            Image {
                id: img
                anchors.centerIn: parent
                width: imgFlick.width; height: imgFlick.height
                fillMode: Image.PreserveAspectFit
                asynchronous: true
                source: v.kind === "image" && v.att ? "image://api/api/attachments/" + v.att.id + "/file?inline=1" : ""
            }
            PinchHandler { target: img; minimumScale: 1; maximumScale: 6 }
        }

        // PDF: one page under another, drawn as they scroll into view.
        ListView {
            id: pdfView
            anchors.fill: parent
            visible: v.kind === "pdf" && !!v.localPath
            clip: true
            spacing: Theme.gap
            model: v.kind === "pdf" && v.localPath ? Pdf.pages(v.localPath) : 0
            cacheBuffer: Math.max(0, height)
            ScrollBar.vertical: ScrollBar {}
            delegate: Rectangle {
                width: pdfView.width
                height: page.status === Image.Ready ? page.paintedHeight : width * 1.3
                color: "white"
                Image {
                    id: page
                    width: parent.width
                    fillMode: Image.PreserveAspectFit
                    asynchronous: true
                    sourceSize.width: Math.min(2000, Math.round(pdfView.width * 1.5))
                    source: "image://pdf/" + (index + 1) + "/" + encodeURIComponent(v.localPath)
                }
                Txt { anchors.centerIn: parent; visible: page.status !== Image.Ready; color: "#555"; text: "Page " + (index + 1) }
            }
        }

        ScrollView {
            anchors.fill: parent
            visible: v.kind === "text" && !v.loading
            TextArea {
                readOnly: true
                text: v.textBody
                color: Theme.text
                font.family: "IBM Plex Mono"; font.pixelSize: Theme.fsSmall
                wrapMode: TextEdit.Wrap
                background: Rectangle { color: Theme.panel2; radius: Theme.radius }
            }
        }

        Column {
            anchors.centerIn: parent
            visible: v.kind === "other"
            spacing: Theme.gap
            Txt { anchors.horizontalCenter: parent.horizontalCenter; kind: "title"; text: "This kind of file can't be shown here" }
            Txt { anchors.horizontalCenter: parent.horizontalCenter; kind: "muted"
                  text: "Copy it to a USB stick to open it on another computer." }
        }
    }
}
