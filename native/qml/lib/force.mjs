// Lays out a network away from the screen's thread (a QML WorkerScript), so
// a few hundred records never freeze the app while they settle.
//
// In:  {nodes: [{id, degree}], edges: [{from, to}], focus: id|null, run: n}
// Out: {run, positions: {id: [x, y]}, done: bool} — sent every few steps, so
//      the picture settles in front of you, and once more when finished.
//
// A plain force model: every pair pushes apart, every link pulls together,
// a weak pull to the middle keeps islands on screen, and it cools as it
// goes. All pairs, not Barnes-Hut: at the console's cap (400 records) that
// is quick enough on a worker thread and needs no tree.

function hash(s) {
    var h = 2166136261
    for (var i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619) }
    return (h >>> 0) / 4294967296
}

WorkerScript.onMessage = function(msg) {
    var nodes = msg.nodes || [], edges = msg.edges || []
    var n = nodes.length
    var index = {}
    for (var i = 0; i < n; i++) index[nodes[i].id] = i
    var x = new Float64Array(n), y = new Float64Array(n), dx = new Float64Array(n), dy = new Float64Array(n)
    var k = 60                                       // the natural link length
    var radius = k * Math.sqrt(n) * 0.6 + 1
    // The same start every time for the same records (by id), so the
    // picture does not reshuffle on every visit.
    for (i = 0; i < n; i++) {
        var a = hash(String(nodes[i].id)) * Math.PI * 2, r = radius * Math.sqrt(hash(nodes[i].id + "r"))
        x[i] = Math.cos(a) * r; y[i] = Math.sin(a) * r
    }
    var fixed = msg.focus !== null && msg.focus !== undefined && index[msg.focus] !== undefined ? index[msg.focus] : -1
    if (fixed >= 0) { x[fixed] = 0; y[fixed] = 0 }
    var links = [], linked = new Uint8Array(n)
    for (var e = 0; e < edges.length; e++) {
        var s = index[edges[e].from], t = index[edges[e].to]
        if (s !== undefined && t !== undefined && s !== t) { links.push([s, t]); linked[s] = 1; linked[t] = 1 }
    }
    // Records with no links have nothing holding them in but the middle's
    // pull; a firmer one keeps them near the picture instead of flung to its
    // edge, where they would shrink everything else to fit.
    var gravity = new Float64Array(n)
    for (i = 0; i < n; i++) gravity[i] = linked[i] ? 0.03 : 0.25
    var steps = n > 250 ? 220 : 320
    var temp = radius / 4, cool = Math.pow(0.02, 1 / steps)

    function send(done) {
        var pos = {}
        for (var i = 0; i < n; i++) pos[nodes[i].id] = [x[i], y[i]]
        WorkerScript.sendMessage({ run: msg.run, positions: pos, done: done })
    }

    for (var step = 0; step < steps; step++) {
        for (i = 0; i < n; i++) { dx[i] = 0; dy[i] = 0 }
        for (i = 0; i < n; i++) {
            for (var j = i + 1; j < n; j++) {
                var ddx = x[i] - x[j], ddy = y[i] - y[j]
                var d2 = ddx * ddx + ddy * ddy + 0.01
                var f = (k * k) / d2
                dx[i] += ddx * f; dy[i] += ddy * f
                dx[j] -= ddx * f; dy[j] -= ddy * f
            }
        }
        for (var l = 0; l < links.length; l++) {
            var p = links[l][0], q = links[l][1]
            var lx = x[p] - x[q], ly = y[p] - y[q]
            var d = Math.sqrt(lx * lx + ly * ly) + 0.01
            var pull = d / k
            dx[p] -= lx * pull; dy[p] -= ly * pull
            dx[q] += lx * pull; dy[q] += ly * pull
        }
        for (i = 0; i < n; i++) {
            if (i === fixed) continue
            dx[i] -= x[i] * gravity[i]; dy[i] -= y[i] * gravity[i]      // toward the middle
            var len = Math.sqrt(dx[i] * dx[i] + dy[i] * dy[i]) + 0.01
            var move = Math.min(len, temp)
            x[i] += dx[i] / len * move; y[i] += dy[i] / len * move
        }
        temp *= cool
        if (step % 25 === 24) send(false)
    }
    send(true)
}
