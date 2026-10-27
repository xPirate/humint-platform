pragma Singleton
import QtQuick
import Humint

// Promises over the two Python links, so screens can write
//   Net.get("/api/reports").then(r => ...).catch(e => toast(e.message))
//   Net.box("unlock", {pin: pin}).then(...)
QtObject {
    id: net
    property var _api: ({})
    property var _box: ({})
    // The signed-in person ({id, username, role}), or null.
    property var me: null
    // A new report being written, kept in memory if its editor is left
    // before saving (never written to disk: it is case material).
    property var draft: null
    // The same for a guided debrief left unfinished.
    property var debriefDraft: null
    // Drafts belong to whoever wrote them: gone when they sign out (or are
    // signed out), never offered to the next person at this screen.
    onMeChanged: if (!me) { draft = null; debriefDraft = null }
    signal signedOut()

    function req(method, path, body) {
        return new Promise(function(resolve, reject) {
            var id = Api.call(method, path, body === undefined ? null : body)
            net._api[id] = { resolve: resolve, reject: reject }
        })
    }
    function get(path, query) { return req("GET", path, query === undefined ? null : query) }
    function post(path, body) { return req("POST", path, body === undefined ? {} : body) }
    function patch(path, body) { return req("PATCH", path, body === undefined ? {} : body) }
    function put(path, body) { return req("PUT", path, body === undefined ? {} : body) }
    function del(path, body) { return req("DELETE", path, body === undefined ? null : body) }
    function upload(path, file, fields) {
        return new Promise(function(resolve, reject) {
            var id = Api.upload(path, file, fields || {})
            net._api[id] = { resolve: resolve, reject: reject }
        })
    }
    function download(path, file) {
        return new Promise(function(resolve, reject) {
            var id = Api.download(path, file)
            net._api[id] = { resolve: resolve, reject: reject }
        })
    }

    function downloadPost(path, body, file) {
        return new Promise(function(resolve, reject) {
            var id = Api.downloadPost(path, body || {}, file)
            net._api[id] = { resolve: resolve, reject: reject }
        })
    }

    // POST and read the reply as it streams (newline-delimited JSON): onEvent
    // for each line as it arrives; resolves when the stream ends.
    function stream(path, body, onEvent) {
        return new Promise(function(resolve, reject) {
            var id = Api.stream(path, body || {})
            net._api[id] = { resolve: resolve, reject: reject, onEvent: onEvent }
        })
    }

    function box(op, args) {
        return new Promise(function(resolve, reject) {
            var id = Box.request(op, args || {})
            net._box[id] = { resolve: resolve, reject: reject }
        })
    }

    // Query strings for GET paths: Net.qs({q: "x", limit: 50}) → "?q=x&limit=50"
    function qs(o) {
        var parts = []
        for (var k in o) {
            var v = o[k]
            if (v === undefined || v === null || v === "") continue
            if (Array.isArray(v)) v.forEach(function(x) { parts.push(encodeURIComponent(k) + "=" + encodeURIComponent(x)) })
            else parts.push(encodeURIComponent(k) + "=" + encodeURIComponent(v))
        }
        return parts.length ? "?" + parts.join("&") : ""
    }

    property Connections _apiConn: Connections {
        target: Api
        function onStreamed(id, ev) {
            var p = net._api[id]
            if (p && p.onEvent) p.onEvent(ev)
        }
        function onFinished(id, status, data, error) {
            var p = net._api[id]
            if (!p) return
            delete net._api[id]
            if (status >= 200 && status < 300) {
                if (status === 204) data = null
                p.resolve(data)
            } else {
                // A session that ended (expired, signed out elsewhere, account
                // disabled) sends the app back to sign-in.
                if (status === 401 && net.me) { net.me = null; net.signedOut() }
                p.reject({ status: status, data: data, message: error || ("Error " + status) })
            }
        }
    }
    property Connections _boxConn: Connections {
        target: Box
        function onReplied(id, ok, data, error) {
            var p = net._box[id]
            if (!p) return
            delete net._box[id]
            if (ok) p.resolve(data)
            else p.reject({ message: error })
        }
    }
}
