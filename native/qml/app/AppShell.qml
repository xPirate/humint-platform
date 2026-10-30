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
        arg = (a === undefined ? null : a); section = name; boxOpen = false
    }
    // Swap the current screen (a form) for another without a history step:
    // after saving, Back goes where it would have before the form opened.
    function replace(name, a) {
        a = (a === undefined ? null : a)
        var top = history.length ? history[history.length - 1] : null
        if (top && top.section === name && JSON.stringify(top.arg) === JSON.stringify(a)) history.pop()
        arg = a; section = name
    }
    function back() {
        if (!history.length) { section = "dashboard"; arg = null; return }
        var h = history.pop(); arg = h.arg; section = h.section
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
        entityEdit:{ file: "EntityForm.qml", parent: "entities" },
        network:   { file: "Network.qml", parent: "entities" },
        map:       { file: "MapPage.qml", label: "Map" },
        documents: { file: "Documents.qml", label: "Documents" },
        document:  { file: "DocumentDetail.qml", parent: "documents" },
        bolo:      { file: "Bolo.qml", label: "BOLO", board: "bolo" },
        priorities:{ file: "Priorities.qml", label: "Priorities", board: "priorities" },
        feeds:     { file: "Feeds.qml", label: "Feeds" },
        roster:    { file: "Roster.qml", label: "Roster", board: "roster" },
        analyst:   { file: "Analyst.qml", label: "Analysts" },
        debrief:   { file: "Debrief.qml", parent: "reports" },
        assistant: { file: "Assistant.qml", label: "Assistant", noViewer: true },
        audit:     { file: "Audit.qml", label: "Audit log", adminOnly: true },
        admin:     { file: "Admin.qml", label: "Admin", adminOnly: true },
        account:   { file: "Account.qml", label: "Account" }
    })
    readonly property var navOrder: ["dashboard", "review", "reports", "entities", "map", "documents", "bolo",
                                     "priorities", "feeds", "roster", "analyst", "assistant", "audit", "admin"]

    // Which boards an admin has switched on, and what they are called.
    property var boards: ({})
    function loadBoards() {
        Net.get("/api/boards").then(function(r) { shell.boards = r.boards || {} }).catch(function() {})
    }
    Connections {
        target: Net
        function onMeChanged() { if (Net.me) shell.loadBoards() }
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
                            if (p.board && !(shell.boards[p.board] && shell.boards[p.board].enabled)) return false
                            return !(p.adminOnly && !shell.admin) && !(p.noViewer && shell.viewer)
                        })
                        delegate: AbstractButton {
                            text: shell.pages[modelData].board && shell.boards[shell.pages[modelData].board]
                                  ? shell.boards[shell.pages[modelData].board].label : shell.pages[modelData].label
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
                                text: parent.text
                                color: parent.current ? Theme.accent : Theme.text
                                font.weight: parent.current ? Font.DemiBold : Font.Normal
                            }
                            onClicked: { shell.history = []; shell.arg = null; shell.section = modelData }
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
            // A section whose screen is missing or broken shows a placeholder
            // instead (without breaking this binding).
            property string failed: ""
            source: !Net.me ? "" : failed === shell.section ? "Missing.qml" : shell.pages[shell.section].file
            onStatusChanged: if (status === Loader.Error) { var f = shell.section; Qt.callLater(function() { page.failed = f }) }
        }
    }

    // ---- the machine itself -------------------------------------------------------------
    property string boxTab: "status"
    Loader {
        anchors.fill: parent
        active: shell.boxOpen
        source: "../box/BoxPanel.qml"
        onLoaded: item.tab = shell.boxTab
    }
    // The quick settings' "Network…": the machine panel, at that tab.
    Connections {
        target: ui
        function onBoxRequested(tab) {
            shell.boxTab = tab
            if (shell.boxOpen) { shell.boxOpen = false }
            shell.boxOpen = true
        }
    }
}
