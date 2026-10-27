import QtQuick
import Humint

// A map to point at a place on: the basemap the Map page would use (a source
// with downloaded areas first — on a field server the internet is the
// exception), framed on the case's known locations, and a pin where it is
// tapped. `place` is {lat, lng} or null.
SlippyMap {
    id: pm
    property var place: null
    property var source: null
    property bool offline: false
    signal placed(real lat, real lng)

    tileSource: function(z, x, y) {
        if (!pm.source) return ""
        if (pm.offline) return "image://api/api/map/tiles/" + pm.source.id + "/" + z + "/" + x + "/" + y
        var subs = pm.source.subdomains || ""
        var s = subs.length ? subs.charAt((x + y) % subs.length) : ""
        return pm.source.url_template.replace("{z}", z).replace("{x}", x).replace("{y}", y).replace("{s}", s).replace("{r}", "")
    }
    markers: pm.place ? [{ id: "place", lat: pm.place.lat, lng: pm.place.lng, color: Theme.accent, label: "" }] : []
    onTapped: function(lat, lng) { pm.place = { lat: lat, lng: lng }; pm.placed(lat, lng) }

    Component.onCompleted: {
        Net.get("/api/map/sources").then(function(r) {
            var all = (r.items || []).slice().sort(function(a, b) { return (b.pack_count || 0) - (a.pack_count || 0) })
            if (all.length) {
                pm.source = all[0]; pm.offline = (all[0].pack_count || 0) > 0
                pm.minZoom = all[0].min_zoom || 1; pm.maxZoom = all[0].max_zoom || 18
            }
        }).catch(function() {})
        if (pm.place) { pm.centerOn(pm.place.lat, pm.place.lng, 15); return }
        Net.get("/api/map/locations").then(function(r) {
            var ls = (r.items || []).filter(function(l) { return l.lat !== null && l.lng !== null })
            if (!ls.length || pm.place) return
            var la = ls.map(function(l) { return l.lat }), lo = ls.map(function(l) { return l.lng })
            pm.fit(Math.min.apply(null, la), Math.min.apply(null, lo), Math.max.apply(null, la), Math.max.apply(null, lo))
            if (pm.zoom > 14) pm.zoom = 14
        }).catch(function() {})
    }
}
