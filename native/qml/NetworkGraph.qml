import QtQuick

// The case file as a network: a dot for each record, sized by how many links
// it has, coloured by its type; a line for each link. Drag to move around,
// wheel or pinch to zoom, tap a record to select it. Laid out on a worker
// thread (lib/force.mjs) and drawn on a canvas.
Item {
    id: g
    property var nodes: []           // [{id, name, entity_type, degree, alignment, steps?}]
    property var edges: []           // [{from, to, relationship_type, expired}]
    property int maxDegree: 1
    property var focusId: null
    property int labelCount: 8       // names drawn for the most-linked records
    property var selectedId: null
    property bool settling: false
    signal picked(var node)
    signal doubleTapped(var node)

    property var pos: ({})
    property real camX: 0
    property real camY: 0
    property real zoom: 1
    property int run: 0
    property bool fitted: false

    function radiusOf(n) { return (5 + 13 * Math.sqrt((n.degree || 0) / Math.max(1, g.maxDegree))) * Theme.s }
    function toScreen(px, py) { return Qt.point(width / 2 + (px - camX) * zoom, height / 2 + (py - camY) * zoom) }
    function nodeAt(sx, sy) {
        var best = null, bestD = 1e9
        for (var i = 0; i < nodes.length; i++) {
            var p = pos[nodes[i].id]; if (!p) continue
            var s = toScreen(p[0], p[1])
            var d = Math.hypot(s.x - sx, s.y - sy)
            if (d < Math.max(radiusOf(nodes[i]) * Math.max(zoom, 0.6), 14 * Theme.s) && d < bestD) { best = nodes[i]; bestD = d }
        }
        return best
    }
    function fit() {
        var ids = Object.keys(pos)
        if (!ids.length || width <= 0) return
        var minX = 1e9, minY = 1e9, maxX = -1e9, maxY = -1e9
        ids.forEach(function(id) { var p = pos[id]; minX = Math.min(minX, p[0]); maxX = Math.max(maxX, p[0]); minY = Math.min(minY, p[1]); maxY = Math.max(maxY, p[1]) })
        camX = (minX + maxX) / 2; camY = (minY + maxY) / 2
        zoom = Math.max(0.15, Math.min(2.5, Math.min((width - 80 * Theme.s) / Math.max(1, maxX - minX), (height - 80 * Theme.s) / Math.max(1, maxY - minY))))
    }
    function zoomAt(f, sx, sy) {
        var wx = camX + (sx - width / 2) / zoom, wy = camY + (sy - height / 2) / zoom
        zoom = Math.max(0.1, Math.min(6, zoom * f))
        camX = wx - (sx - width / 2) / zoom; camY = wy - (sy - height / 2) / zoom
    }
    property bool pending: false
    function layout() {
        run += 1; fitted = false; settling = nodes.length > 0
        // The worker loads its script in the background: wait for it.
        if (!worker.ready) { pending = true; return }
        pending = false
        worker.sendMessage({ run: run, focus: focusId,
                             nodes: nodes.map(function(n) { return { id: n.id, degree: n.degree } }),
                             edges: edges.map(function(e) { return { from: e.from, to: e.to } }) })
    }
    onNodesChanged: layout()

    WorkerScript {
        id: worker
        source: "lib/force.mjs"
        onReadyChanged: if (ready && g.pending) g.layout()
        onMessage: function(m) {
            if (m.run !== g.run) return
            g.pos = m.positions
            if (!g.fitted || m.done) { g.fit(); g.fitted = m.done }
            if (m.done) g.settling = false
            canvas.requestPaint()
        }
    }

    // The names worth drawing: the most-linked (or, focused, the direct
    // links), the selected record, and more as you zoom in.
    readonly property var labelled: {
        var set = {}
        var sorted = nodes.slice().sort(function(a, b) { return (b.degree || 0) - (a.degree || 0) })
        var limit = Math.round(labelCount * Math.max(1, zoom * zoom))
        sorted.slice(0, limit).forEach(function(n) { set[n.id] = true })
        if (focusId !== null) nodes.forEach(function(n) { if (n.steps !== undefined && n.steps <= 1) set[n.id] = true })
        if (selectedId !== null) set[selectedId] = true
        return set
    }

    Canvas {
        id: canvas
        anchors.fill: parent
        renderStrategy: Canvas.Cooperative
        onPaint: {
            var ctx = getContext("2d")
            ctx.reset()
            ctx.clearRect(0, 0, width, height)
            var byId = {}
            g.nodes.forEach(function(n) { byId[n.id] = n })
            // Links: those touching the selected record stand out.
            for (var i = 0; i < g.edges.length; i++) {
                var e = g.edges[i], a = g.pos[e.from], b = g.pos[e.to]
                if (!a || !b) continue
                var sa = g.toScreen(a[0], a[1]), sb = g.toScreen(b[0], b[1])
                var hot = g.selectedId !== null && (e.from === g.selectedId || e.to === g.selectedId)
                ctx.strokeStyle = hot ? Theme.accent : Theme.borderStrong
                ctx.globalAlpha = e.expired ? 0.3 : (hot ? 0.95 : 0.55)
                ctx.lineWidth = (hot ? 2 : 1) * Theme.s
                ctx.beginPath(); ctx.moveTo(sa.x, sa.y); ctx.lineTo(sb.x, sb.y); ctx.stroke()
            }
            ctx.globalAlpha = 1
            // Records.
            for (i = 0; i < g.nodes.length; i++) {
                var n = g.nodes[i], p = g.pos[n.id]
                if (!p) continue
                var s = g.toScreen(p[0], p[1])
                if (s.x < -40 || s.y < -40 || s.x > width + 40 || s.y > height + 40) continue
                var r = g.radiusOf(n) * Math.max(0.6, Math.min(1.6, g.zoom))
                ctx.globalAlpha = n.is_active === false ? 0.45 : (n.steps === 2 ? 0.7 : 1)
                ctx.fillStyle = Theme.kindColor(n.entity_type)
                ctx.beginPath(); ctx.arc(s.x, s.y, r, 0, Math.PI * 2); ctx.fill()
                if (n.alignment === "hostile" || n.alignment === "Hostile") {
                    ctx.strokeStyle = Theme.red; ctx.lineWidth = 3 * Theme.s
                    ctx.beginPath(); ctx.arc(s.x, s.y, r + 3 * Theme.s, 0, Math.PI * 2); ctx.stroke()
                }
                if (n.id === g.selectedId || n.id === g.focusId) {
                    ctx.strokeStyle = Theme.text; ctx.lineWidth = 2 * Theme.s
                    ctx.beginPath(); ctx.arc(s.x, s.y, r + 6 * Theme.s, 0, Math.PI * 2); ctx.stroke()
                }
            }
            ctx.globalAlpha = 1
            // Names.
            ctx.font = Math.round(13 * Theme.s) + "px '" + Theme.ui + "'"
            ctx.textAlign = "center"
            for (i = 0; i < g.nodes.length; i++) {
                n = g.nodes[i]; p = g.pos[n.id]
                if (!p || !g.labelled[n.id]) continue
                s = g.toScreen(p[0], p[1])
                r = g.radiusOf(n) * Math.max(0.6, Math.min(1.6, g.zoom))
                var label = n.name.length > 28 ? n.name.slice(0, 27) + "…" : n.name
                ctx.lineWidth = 4 * Theme.s; ctx.strokeStyle = Theme.bg; ctx.lineJoin = "round"
                ctx.strokeText(label, s.x, s.y + r + 15 * Theme.s)
                ctx.fillStyle = Theme.text
                ctx.fillText(label, s.x, s.y + r + 15 * Theme.s)
            }
        }
    }
    onCamXChanged: canvas.requestPaint()
    onCamYChanged: canvas.requestPaint()
    onZoomChanged: canvas.requestPaint()
    onSelectedIdChanged: canvas.requestPaint()
    onWidthChanged: { if (g.fitted) g.fit(); canvas.requestPaint() }
    onHeightChanged: canvas.requestPaint()
    Connections { target: Theme; function onPaletteChanged() { canvas.requestPaint() } function onLightChanged() { canvas.requestPaint() } }

    // Moving around: drag, wheel, pinch; tap to pick.
    MouseArea {
        anchors.fill: parent
        property point last
        property bool moved: false
        onPressed: function(m) { last = Qt.point(m.x, m.y); moved = false }
        onPositionChanged: function(m) {
            if (Math.abs(m.x - last.x) + Math.abs(m.y - last.y) > 2) moved = true
            g.camX -= (m.x - last.x) / g.zoom; g.camY -= (m.y - last.y) / g.zoom
            last = Qt.point(m.x, m.y)
        }
        onClicked: function(m) {
            if (moved) return
            var n = g.nodeAt(m.x, m.y)
            g.selectedId = n ? n.id : null
            g.picked(n)
        }
        onDoubleClicked: function(m) { var n = g.nodeAt(m.x, m.y); if (n) g.doubleTapped(n) }
        onWheel: function(w) { g.zoomAt(w.angleDelta.y > 0 ? 1.15 : 1 / 1.15, w.x, w.y) }
    }
    PinchHandler {
        target: null
        property real base: 1
        onActiveChanged: if (active) base = g.zoom
        onActiveScaleChanged: if (active) g.zoomAt(base * activeScale / g.zoom, centroid.position.x, centroid.position.y)
    }
}
