package org.humint.field

import org.humint.field.track.Shape
import org.humint.field.track.TrackFilter
import org.humint.field.track.TrackPoint
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** The shapes the app keeps and sends, and which GPS fixes a recording keeps. */
class TrackTest {

    private fun p(lat: Double, lon: Double, t: Long, acc: Float = 5f) = TrackPoint(lat, lon, t, acc)

    @Test fun aSingleRunIsALineStringWithATimePerPoint() {
        val shape = Shape.empty("track").plusSegment(listOf(p(36.0, -95.0, 1000), p(36.001, -95.0, 2000)))
        val json = JSONObject(shape.toJson())
        assertEquals("LineString", json.getString("type"))
        assertEquals(2, json.getJSONArray("coordinates").length())
        // GeoJSON order: longitude first.
        assertEquals(-95.0, json.getJSONArray("coordinates").getJSONArray(0).getDouble(0), 1e-9)
        assertEquals(2, json.getJSONArray("times").length())
    }

    @Test fun aContinuedRecordingKeepsTheGapAsASecondPart() {
        val first = Shape.empty("track").plusSegment(listOf(p(36.0, -95.0, 1), p(36.001, -95.0, 2)))
        val both = Shape.parse(first.toJson(), "track")
            .plusSegment(listOf(p(36.01, -95.0, 3), p(36.011, -95.0, 4)))
        val json = JSONObject(both.toJson())
        assertEquals("MultiLineString", json.getString("type"))
        assertEquals(2, json.getJSONArray("coordinates").length())
        assertEquals(4, json.getJSONArray("times").length())
        val back = Shape.parse(both.toJson(), "track")
        assertEquals(2, back.segments.size)
        assertEquals(4L, back.segments[1][1].timeMs)
    }

    @Test fun lengthIsMeasuredAlongEachPartAndNotAcrossTheGap() {
        // 0.001 degrees of latitude is about 111 m.
        val shape = Shape("track", listOf(
            listOf(p(36.0, -95.0, 1), p(36.001, -95.0, 2)),
            listOf(p(37.0, -95.0, 3), p(37.001, -95.0, 4))))
        assertEquals(222.4, shape.lengthM, 1.0)
    }

    @Test fun aPerimeterIsAnOpenRingThatMeasuresAllTheWayRound() {
        val ring = listOf(p(36.0, -95.0, 1), p(36.001, -95.0, 2), p(36.001, -95.001, 3))
        val shape = Shape("perimeter", listOf(ring))
        val json = JSONObject(shape.toJson())
        assertEquals("Polygon", json.getString("type"))
        assertEquals(3, json.getJSONArray("coordinates").getJSONArray(0).length())
        assertTrue(shape.lengthM > 111.0 + 90.0)
        assertEquals(3, Shape.parse(shape.toJson(), "perimeter").points)
    }

    @Test fun somethingUnreadableIsAnEmptyShapeNotACrash() {
        assertTrue(Shape.parse("{not json", "track").isEmpty)
        assertTrue(Shape.parse(null, "perimeter").isEmpty)
    }

    @Test fun theFilterDropsWildFixesAndStandingStill() {
        val f = TrackFilter(maxAccuracyM = 35f, minSpacingM = 5.0)
        assertTrue(f.accept(p(36.0, -95.0, 1)))
        assertFalse("80 m fix", f.accept(p(36.0005, -95.0, 2, acc = 80f)))
        assertFalse("2 m step", f.accept(p(36.00002, -95.0, 3)))
        assertTrue("11 m step", f.accept(p(36.0001, -95.0, 4)))
    }

    @Test fun aPocketedPhoneStillDrawsTheWayItWent() {
        // GPS at ±50 m the whole walk, a fix every 2 s, walking north ~1.4 m/s.
        val f = TrackFilter()
        assertTrue("good first fix", f.accept(p(36.0, -95.0, 0)))
        var kept = 0
        for (i in 1..300) {   // ten minutes
            val lat = 36.0 + i * 2 * 1.4 / 111_000.0
            if (f.accept(p(lat, -95.0, i * 2_000L, acc = 50f))) kept++
        }
        assertTrue("kept $kept rough points over ten minutes", kept >= 10)
        assertEquals(kept, f.keptRough)
    }

    @Test fun roughFixesAroundAStandingPhoneAreNotKept() {
        val f = TrackFilter()
        assertTrue(f.accept(p(36.0, -95.0, 0)))
        // Five minutes standing still, the fixes wandering 20 m at ±50 m.
        for (i in 1..150) {
            val jitter = if (i % 2 == 0) 0.00018 else -0.00018
            assertFalse(f.accept(p(36.0 + jitter, -95.0, i * 2_000L, acc = 50f)))
        }
        assertEquals(150, f.tooRough)
    }

    @Test fun nothingWorseThanAHundredMetresIsEverKept() {
        val f = TrackFilter()
        assertTrue(f.accept(p(36.0, -95.0, 0)))
        assertFalse(f.accept(p(36.01, -95.0, 600_000L, acc = 150f)))
    }
}
