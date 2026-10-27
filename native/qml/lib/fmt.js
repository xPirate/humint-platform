.pragma library
// Formatting shared by every screen, ported from the web console's own
// helpers (frontend/app.js) so the two read the same.

function escapeHtml(str) {
    if (str === null || str === undefined) return ""
    return String(str).replace(/[&<>"']/g, function(c) {
        return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]
    })
}

function truncate(s, n) {
    s = String(s || "")
    return s.length > n ? s.slice(0, n) + "…" : s
}

var RELATIVE_UNITS = [["year", 31536000], ["month", 2592000], ["week", 604800], ["day", 86400],
                      ["hour", 3600], ["minute", 60]]

// "3 days ago" — for activity (when something was created, seen, saved).
function relativeTime(value) {
    if (!value) return ""
    var then = new Date(value)
    if (isNaN(then.getTime())) return ""
    var seconds = (Date.now() - then.getTime()) / 1000
    var abs = Math.abs(seconds)
    if (abs < 45) return seconds >= 0 ? "just now" : "in a moment"
    for (var i = 0; i < RELATIVE_UNITS.length; i++) {
        var u = RELATIVE_UNITS[i]
        if (abs >= u[1]) {
            var n = Math.round(abs / u[1])
            var label = n + " " + u[0] + (n === 1 ? "" : "s")
            return seconds >= 0 ? label + " ago" : "in " + label
        }
    }
    return seconds >= 0 ? "just now" : "in a moment"
}

// "12 Mar 2026, 14:05" — for facts (when something happened).
function exactTime(value) {
    if (!value) return ""
    var d = new Date(value)
    if (isNaN(d.getTime())) return String(value)
    var m = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][d.getMonth()]
    return d.getDate() + " " + m + " " + d.getFullYear() + ", " + ("0" + d.getHours()).slice(-2) + ":" + ("0" + d.getMinutes()).slice(-2)
}

function exactDate(value) {
    if (!value) return ""
    var d = new Date(value)
    if (isNaN(d.getTime())) return String(value)
    var m = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][d.getMonth()]
    return d.getDate() + " " + m + " " + d.getFullYear()
}

function fileSize(bytes) {
    if (bytes === null || bytes === undefined) return ""
    if (bytes < 1024) return bytes + " B"
    if (bytes < 1048576) return (bytes / 1024).toFixed(0) + " KB"
    if (bytes < 1073741824) return (bytes / 1048576).toFixed(1) + " MB"
    return (bytes / 1073741824).toFixed(2) + " GB"
}

var CREDIBILITY = { "1": "Confirmed by other sources", "2": "Probably true", "3": "Possibly true",
                    "4": "Doubtful", "5": "Improbable", "6": "Truth cannot be judged" }
var CRITICALITY = ["Flash", "Immediate", "Priority", "Routine"]
var ENTITY_TYPES = ["person", "organization", "location", "event", "source", "communication",
                    "vehicle", "record", "zone", "route"]

function typeLabel(t) {
    return ({ organization: "Organisation" })[t] || (t ? t.charAt(0).toUpperCase() + t.slice(1).replace(/_/g, " ") : "")
}

// ---- markdown -----------------------------------------------------------------
// The console's own small renderer (mdToHtml), producing the HTML subset
// Qt's rich text draws. Input is escaped before any markup is built; the only
// links kept are record mentions (#/entities/<id>) and http(s) URLs.

function mdInline(t, linkColor) {
    t = t.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, function(m, label, href) {
        if (/^#\/entities\/[A-Za-z0-9_-]+$/.test(href))
            return '<a href="' + href + '" style="color:' + linkColor + ';text-decoration:none"><b>' + label + '</b></a>'
        if (/^https?:\/\/[^"'<>]+$/.test(href)) return '<a href="' + href + '" style="color:' + linkColor + '">' + label + '</a>'
        return m
    })
    t = t.replace(/`([^`]+)`/g, "<code>$1</code>")
    t = t.replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
    t = t.replace(/(^|[\s(])\*([^*\n]+)\*(?=[\s).,;:!?]|$)/g, "$1<i>$2</i>")
    t = t.replace(/(^|[\s(])_([^_\n]+)_(?=[\s).,;:!?]|$)/g, "$1<i>$2</i>")
    return t
}

function mdToHtml(src, linkColor) {
    linkColor = linkColor || "#39ff88"
    var lines = escapeHtml(src || "").split(/\r?\n/)
    var out = [], para = [], list = null, quote = []
    function flushPara() { if (para.length) { out.push("<p>" + mdInline(para.join(" "), linkColor) + "</p>"); para = [] } }
    function flushList() {
        if (list) {
            out.push("<" + list.tag + ">" + list.items.map(function(i) { return "<li>" + mdInline(i, linkColor) + "</li>" }).join("") + "</" + list.tag + ">")
            list = null
        }
    }
    function flushQuote() { if (quote.length) { out.push("<blockquote><i>" + mdInline(quote.join(" "), linkColor) + "</i></blockquote>"); quote = [] } }
    function flushAll() { flushPara(); flushList(); flushQuote() }
    for (var k = 0; k < lines.length; k++) {
        var line = lines[k]
        var h = line.match(/^(#{1,6})\s+(.*)$/)
        if (h) { flushAll(); var n = Math.min(h[1].length + 2, 6); out.push("<h" + n + ">" + mdInline(h[2], linkColor) + "</h" + n + ">"); continue }
        if (/^(\*{3,}|-{3,}|_{3,})\s*$/.test(line)) { flushAll(); out.push("<hr/>"); continue }
        var ul = line.match(/^\s*[-*+]\s+(.*)$/)
        var ol = line.match(/^\s*\d+[.)]\s+(.*)$/)
        if (ul || ol) {
            flushPara(); flushQuote()
            var tag = ul ? "ul" : "ol"
            if (!list || list.tag !== tag) { flushList(); list = { tag: tag, items: [] } }
            list.items.push((ul || ol)[1])
            continue
        }
        var q = line.match(/^&gt;\s?(.*)$/)
        if (q) { flushPara(); flushList(); quote.push(q[1]); continue }
        if (!line.trim()) { flushAll(); continue }
        if (list && list.items.length) { list.items[list.items.length - 1] += " " + line.trim(); continue }
        flushList(); flushQuote()
        para.push(line.trim())
    }
    flushAll()
    return out.join("\n")
}

// A link from rich text: a record mention → its id, else null.
function mentionId(href) {
    var m = /^#\/entities\/([A-Za-z0-9_-]+)$/.exec(href || "")
    return m ? m[1] : null
}

// Plain text of a markdown body (for list snippets).
function plainText(md) {
    return String(md || "").replace(/\[([^\]]+)\]\([^)]+\)/g, "$1").replace(/[*_`#>]/g, "").replace(/\s+/g, " ").trim()
}
