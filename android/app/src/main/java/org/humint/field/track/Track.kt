package org.humint.field.track

import org.json.JSONArray
import org.json.JSONObject
import kotlin.math.asin
import kotlin.math.cos
import kotlin.math.min
import kotlin.math.sin
import kotlin.math.sqrt

/**
 * A route or an area, as the report keeps it and the console receives it.
 *
 * GeoJSON, [longitude, latitude] -- the same shape the console stores, so the
 * upload is the stored string with nothing translated on the way out. Two
 * kinds:
 *
 *   * A **track**: a LineString, or a MultiLineString once a recording has
 *     been stopped and continued (the gap between is not drawn as a straight
 *     line nobody walked). Every point carries its time, in "times", flattened
 *     in the order of the coordinates.
 *   * A **perimeter**: a Polygon whose single ring is the corners in the order
 *     they were dropped. Left open here; the console closes it.
 *
 * Plain Kotlin and org.json, no Android, so the unit tests exercise it on the
 * JVM.
 */
data class TrackPoint(
    val lat: Double,
    val lon: Double,
    val timeMs: Long,
    val accuracyM: Float = Float.NaN,
    val altitudeM: Double? = null,
)

data class Shape(
    /** "track" or "perimeter". */
    val kind: String,
    /** One list per segment for a track; exactly one list for a perimeter. */
    val segments: List<List<TrackPoint>>,
) {
    val points: Int get() = segments.sumOf { it.size }
    val isEmpty: Boolean get() = points == 0

    /** Metres along the track, or around the perimeter. */
    val lengthM: Double get() = segments.sumOf { seg ->
        val open = seg.zipWithNext { a, b -> metres(a, b) }.sum()
        if (kind == "perimeter" && seg.size >= 3) open + metres(seg.last(), seg.first()) else open
    }

    val durationMs: Long? get() {
        val all = segments.flatten()
        if (all.size < 2) return null
        return all.last().timeMs - all.first().timeMs
    }

    fun toJson(): String {
        val coords = { seg: List<TrackPoint> ->
            JSONArray(seg.map { p ->
                JSONArray().apply {
                    put(round7(p.lon)); put(round7(p.lat))
                    p.altitudeM?.let { put(Math.round(it * 10) / 10.0) }
                }
            })
        }
        val json = JSONObject()
        if (kind == "perimeter") {
            json.put("type", "Polygon")
            json.put("coordinates", JSONArray().put(coords(segments.firstOrNull().orEmpty())))
        } else {
            val live = segments.filter { it.isNotEmpty() }
            if (live.size <= 1) {
                json.put("type", "LineString")
                json.put("coordinates", coords(live.firstOrNull().orEmpty()))
            } else {
                json.put("type", "MultiLineString")
                json.put("coordinates", JSONArray(live.map(coords)))
            }
            json.put("times", JSONArray(live.flatten().map { it.timeMs }))
        }
        return json.toString()
    }

    /** This track with another recording run added as a new segment. */
    fun plusSegment(more: List<TrackPoint>): Shape =
        if (more.isEmpty()) this else copy(segments = segments.filter { it.isNotEmpty() } + listOf(more))

    companion object {
        fun empty(kind: String) = Shape(kind, if (kind == "perimeter") listOf(emptyList()) else emptyList())

        /** Read what [toJson] wrote. Anything unreadable is an empty shape:
         *  a corrupt geometry must never stop the rest of a report opening. */
        fun parse(json: String?, kind: String): Shape {
            if (json.isNullOrBlank()) return empty(kind)
            return runCatching {
                val o = JSONObject(json)
                val times = o.optJSONArray("times")
                var t = 0
                fun seg(arr: JSONArray): List<TrackPoint> = (0 until arr.length()).map { i ->
                    val c = arr.getJSONArray(i)
                    val time = times?.optLong(t++, 0L) ?: 0L
                    TrackPoint(lat = c.getDouble(1), lon = c.getDouble(0), timeMs = time,
                               altitudeM = if (c.length() > 2) c.getDouble(2) else null)
                }
                when (o.getString("type")) {
                    "LineString" -> Shape("track", listOf(seg(o.getJSONArray("coordinates"))))
                    "MultiLineString" -> {
                        val parts = o.getJSONArray("coordinates")
                        Shape("track", (0 until parts.length()).map { seg(parts.getJSONArray(it)) })
                    }
                    "Polygon" -> Shape("perimeter",
                                       listOf(seg(o.getJSONArray("coordinates").getJSONArray(0))))
                    else -> empty(kind)
                }
            }.getOrElse { empty(kind) }
        }

        fun metres(a: TrackPoint, b: TrackPoint): Double = haversine(a.lat, a.lon, b.lat, b.lon)

        fun haversine(lat1: Double, lon1: Double, lat2: Double, lon2: Double): Double {
            val r = 6_371_000.0
            val p1 = Math.toRadians(lat1)
            val p2 = Math.toRadians(lat2)
            val dp = Math.toRadians(lat2 - lat1)
            val dl = Math.toRadians(lon2 - lon1)
            val a = sin(dp / 2) * sin(dp / 2) + cos(p1) * cos(p2) * sin(dl / 2) * sin(dl / 2)
            return 2 * r * asin(min(1.0, sqrt(a)))
        }

        private fun round7(v: Double) = Math.round(v * 1e7) / 1e7
    }
}

/**
 * Which fixes a recording keeps.
 *
 * A phone in a pocket reports a fix every second or two, most of them a few
 * metres from the last and some of them wild. Keeping every one makes a
 * track that zig-zags on the spot; keeping too few cuts corners off the
 * route somebody actually walked. So:
 *
 *   * a fix of [maxAccuracyM] or better is good enough to keep;
 *   * a rougher fix, up to [fallbackAccuracyM], is kept only once nothing
 *     has been kept for [fallbackAfterMs] **and** it is further from the last
 *     kept point than its own error -- so a phone in a pocket, where GPS
 *     often sits at 40-60 m, still draws the way somebody went rather than a
 *     straight line from start to finish, but a rough fix never scribbles
 *     around a point somebody is standing at;
 *   * anything worse than [fallbackAccuracyM] is dropped -- a route drawn
 *     through an 80 m fix goes through walls;
 *   * a fix closer to the last kept one than the larger of [minSpacingM] and
 *     half its own accuracy is dropped as standing still.
 *
 * It also counts what it saw and why it dropped it, so a thin track can be
 * explained on the phone instead of guessed at afterwards.
 */
class TrackFilter(
    private val maxAccuracyM: Float = 35f,
    private val minSpacingM: Double = 5.0,
    private val fallbackAccuracyM: Float = 100f,
    private val fallbackAfterMs: Long = 20_000L,
) {
    private var last: TrackPoint? = null
    /** When the filter started waiting -- the first fix seen, or the last kept. */
    private var waitingSince: Long? = null

    var seen = 0; private set
    var tooRough = 0; private set
    var standingStill = 0; private set
    var keptRough = 0; private set

    fun reset(lastKept: TrackPoint? = null) {
        last = lastKept; waitingSince = lastKept?.timeMs
        seen = 0; tooRough = 0; standingStill = 0; keptRough = 0
    }

    fun accept(p: TrackPoint): Boolean {
        seen++
        val since = waitingSince ?: p.timeMs.also { waitingSince = it }
        val acc = if (p.accuracyM.isNaN()) 0f else p.accuracyM
        val prev = last
        val good = acc <= maxAccuracyM
        if (!good) {
            val overdue = p.timeMs - since >= fallbackAfterMs
            val clearOfLast = prev == null || Shape.metres(prev, p) > acc
            if (acc > fallbackAccuracyM || !overdue || !clearOfLast) { tooRough++; return false }
        }
        if (prev != null) {
            val spacing = maxOf(minSpacingM, acc / 2.0)
            if (Shape.metres(prev, p) < spacing) { standingStill++; return false }
        }
        if (!good) keptRough++
        last = p
        waitingSince = p.timeMs
        return true
    }
}

fun formatLength(m: Double): String = when {
    m < 1000 -> "${m.toInt()} m"
    m < 10_000 -> "%.2f km".format(m / 1000)
    else -> "%.1f km".format(m / 1000)
}

fun formatDuration(ms: Long): String {
    val s = ms / 1000
    val h = s / 3600
    val m = (s % 3600) / 60
    return if (h > 0) "${h} h ${m} min" else if (m > 0) "$m min" else "${s % 60} s"
}
