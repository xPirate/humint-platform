.pragma library
// Web Mercator, the projection every XYZ tile set uses: world pixel
// coordinates at a zoom level (256-pixel tiles).

var TILE = 256

function worldSize(z) { return TILE * Math.pow(2, z) }

function lngToX(lng, z) { return (lng + 180) / 360 * worldSize(z) }

function latToY(lat, z) {
    var s = Math.sin(Math.max(-85.05112878, Math.min(85.05112878, lat)) * Math.PI / 180)
    return (0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * worldSize(z)
}

function xToLng(x, z) { return x / worldSize(z) * 360 - 180 }

function yToLat(y, z) {
    var n = Math.PI - 2 * Math.PI * y / worldSize(z)
    return 180 / Math.PI * Math.atan(0.5 * (Math.exp(n) - Math.exp(-n)))
}

// Zoom that fits a lat/lng box in a w×h view.
function fitZoom(minLat, minLng, maxLat, maxLng, w, h, maxZoom) {
    for (var z = maxZoom; z > 1; z--) {
        var dx = Math.abs(lngToX(maxLng, z) - lngToX(minLng, z))
        var dy = Math.abs(latToY(minLat, z) - latToY(maxLat, z))
        if (dx <= w * 0.85 && dy <= h * 0.85) return z
    }
    return 2
}

// Maidenhead locator (6 characters), as the console shows next to coordinates.
function maidenhead(lat, lng) {
    var A = "ABCDEFGHIJKLMNOPQR", a = "abcdefghijklmnopqrstuvwx"
    var x = lng + 180, y = lat + 90
    var s = A.charAt(Math.floor(x / 20)) + A.charAt(Math.floor(y / 10))
    x %= 20; y %= 10
    s += Math.floor(x / 2) + "" + Math.floor(y)
    x %= 2; y %= 1
    s += a.charAt(Math.floor(x * 12)) + a.charAt(Math.floor(y * 24))
    return s
}
