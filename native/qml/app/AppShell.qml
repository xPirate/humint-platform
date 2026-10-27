import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Humint
import ".."

// The case file is open: sign in, then the console's sections down the side.
Item {
    id: shell
    property bool boxOpen: false
    property string section: "dashboard"
    // The record a section is showing (e.g. a report id), and how we got here.
    property var arg: null
    property var history: []

    // Go somewhere: shell.go("reports"), shell.go("report", 42)
    function go(name, a) {
        history.push({ section: section, arg: arg })
        if (history.length > 50) history.shift()
        section = name; arg = (a === undefined ? null : a); boxOpen = false
    }
    function back() {
        if (!history.length) { section = "dashboard"; arg = null; return }
        var h = history.pop(); section = h.section; arg = h.arg
    }

    readonly property bool admin: !!(Net.me && Net.me.role === "admin")
    readonly property bool viewer: !!(Net.me && Net.me.role === "viewer")

    // section → page file, nav label, who sees it
    readonly property var pages: ({
        dashboard: { file: "Dashboard.qml", label: "Dashboard" },
        review:    { file: "Review.qml", label: "Review inbox", noViewer: true },
        reports:   { file: "Reports.qml", label: "Reports" },
        report:    { file: "ReportDetail.qml", parent: "reports" },
        reportEdit:{ file: "ReportEditor.qml", parent: "reports" },
        entities:  { file: "Entities.qml", label: "Records" },
        entity:    { file: "EntityDetail.qml", parent: "entities" },
        map:       { file: "MapPage.qml", label: "Map" },
        documents: { file: "Documents.qml", label: "Documents" },
        document:  { file: "DocumentDetail.qml", parent: "documents" },
        bolo:      { file: "Bolo.qml", label: "BOLO" },
        priorities:{ file: "Priorities.qml", label: "Priorities" },
        feeds:     { file: "Feeds.qml", label: "Feeds" },
        roster:    { file: "Roster.qml", label: "Roster" },
        analyst:   { file: "Analyst.qml", parent: "roster" },
        debrief:   { file: "Debrief.qml", parent: "reports" },
        assistant: { file: "Assistant.qml", label: "Assistant", noViewer: true },
        audit:     { file: "Audit.qml", label: "Audit log", adminOnly: true },
        admin:     { file: "Admin.qml", label: "Admin", adminOnly: true },
        account:   { file: "Account.qml", label: "Account" }
    })
    readonly property var navOrder: ["dashboard", "review", "reports", "entities", "map", "documents", "bolo",
                                     "priorities", "feeds", "roster", "assistant", "audit", "admin"]

    Connections {
        target: Net
        function onSignedOut() { shell.boxOpen = false; shell.section = "dashboard"; shell.history = [] }
    }

    Loader {
        anchors.fill: parent
        active: !Net.me && !shell.boxOpen
        sourceComponent: SignIn { onOpenBox: shell.boxOpen = true }
    }

    // ---- signed in ----------------------------------------------------------------
    Item {
        anchors.fill: parent
        visible: !!Net.me && !shell.boxOpen

        StatusStrip {
            id: strip
            anchors.top: parent.top; width: parent.width
            title: (Box.state && Box.state.name) || "HUMINT"
            rightItems: [
                Btn { compact: true; kind: "ghost"; text: Net.me ? Net.me.username : ""
                      onClicked: shell.go("account") }
            ]
        }

        Rectangle {
            id: rail
            anchors.top: strip.bottom; anchors.bottom: parent.bottom
            width: 210 * Theme.s
            color: Theme.panel2
            Rectangle { anchors.right: parent.right; width: Math.max(1, Theme.s); height: parent.height; color: Theme.border }
            Flickable {
                anchors.fill: parent; anchors.margins: 8 * Theme.s
                contentHeight: navCol.implicitHeight
                clip: true
                Column {
                    id: navCol
                    width: parent.width
                    spacing: 2 * Theme.s
                    Repeater {
                        model: shell.navOrder.filter(function(k) {
                            var p = shell.pages[k]
                            return !(p.adminOnly && !shell.admin) && !(p.noViewer && shell.viewer)
                        })
                        delegate: AbstractButton {
                            width: navCol.width
                            height: 42 * Theme.s
                            readonly property bool current: shell.section === modelData
                                || shell.pages[shell.section].parent === modelData
                            background: Rectangle {
                                radius: Theme.radius
                                color: parent.current ? Theme.panel : parent.hovered ? Qt.lighter(Theme.panel2, 1.15) : "transparent"
                                border.color: parent.current ? Theme.border : "transparent"
                                Rectangle { visible: parent.parent.current; width: 3 * Theme.s; height: parent.height - 12 * Theme.s
                                            anchors.verticalCenter: parent.verticalCenter; color: Theme.accent; radius: width }
                            }
                            contentItem: Txt {
                                leftPadding: 14 * Theme.s
                                verticalAlignment: Text.AlignVCenter
                                wrapMode: Text.NoWrap
                                text: shell.pages[modelData].label
                                color: parent.current ? Theme.accent : Theme.text
                                font.weight: parent.current ? Font.DemiBold : Font.Normal
                            }
                            onClicked: { shell.history = []; shell.section = modelData; shell.arg = null }
                        }
                    }
                    Item { width: 1; height: Theme.gap }
                    Btn {
                        width: navCol.width
                        text: "Box"
                        sub: "lock, network, power"
                        onClicked: shell.boxOpen = true
                    }
                }
            }
        }

        Loader {
            id: page
            anchors.top: strip.bottom; anchors.bottom: parent.bottom
            anchors.left: rail.right; anchors.right: parent.right
            source: Net.me ? shell.pages[shell.section].file : ""
            onStatusChanged: if (status === Loader.Error) source = "Missing.qml"
        }
    }

    // ---- the machine itself -------------------------------------------------------------
    Loader {
        anchors.fill: parent
        active: shell.boxOpen
        source: "../box/BoxPanel.qml"
    }
}
