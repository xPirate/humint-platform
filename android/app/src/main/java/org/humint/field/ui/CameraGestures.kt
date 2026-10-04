package org.humint.field.ui

import androidx.camera.core.Camera
import androidx.camera.core.FocusMeteringAction
import androidx.camera.core.SurfaceOrientedMeteringPointFactory
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import java.util.Locale
import java.util.concurrent.TimeUnit

/**
 * Pinch to zoom and tap to focus, over any CameraX preview.
 *
 * A full-frame shot is often the wrong one in the field: the plate on a van
 * across the road, the sign over a door, a face in a crowd. Walking closer is
 * not always an option, so the camera has to come closer instead.
 *
 * Zoom is the camera's own (CameraControl.setZoomRatio): optical where the
 * phone has a second lens and switches to it, digital otherwise. Either way
 * the saved photo is what the viewfinder showed, not a crop applied later.
 *
 * Drawn as an overlay the same size as the preview; it does not draw the
 * preview itself, so the photo screen and the video pane both use it.
 */
@Composable
fun BoxScope.CameraGestureLayer(camera: Camera?, showPresets: Boolean = true) {
    var ratio by remember { mutableStateOf(1f) }
    var focusAt by remember { mutableStateOf<Offset?>(null) }
    val focusRing = remember { Animatable(0f) }

    // The camera's real range. Unknown until it is bound; 1x-1x until then
    // keeps every gesture a no-op rather than an exception.
    val zoomState = camera?.cameraInfo?.zoomState?.value
    val minRatio = zoomState?.minZoomRatio ?: 1f
    val maxRatio = zoomState?.maxZoomRatio ?: 1f

    fun setZoom(target: Float) {
        val c = camera ?: return
        ratio = target.coerceIn(minRatio, maxRatio)
        runCatching { c.cameraControl.setZoomRatio(ratio) }
    }

    // A rebind (returning from the background) resets the camera to 1x;
    // put the analyst's framing back.
    LaunchedEffect(camera) { if (camera != null && ratio != 1f) setZoom(ratio) }

    LaunchedEffect(focusAt) {
        if (focusAt != null) {
            focusRing.snapTo(1f)
            focusRing.animateTo(0f, tween(900))
        }
    }

    Box(
        Modifier
            .fillMaxSize()
            .pointerInput(camera) {
                detectTransformGestures { _, _, zoom, _ ->
                    if (zoom != 1f) setZoom(ratio * zoom)
                }
            }
            .pointerInput(camera) {
                detectTapGestures(
                    onTap = { pos ->
                        val c = camera ?: return@detectTapGestures
                        focusAt = pos
                        val point = SurfaceOrientedMeteringPointFactory(
                            size.width.toFloat(), size.height.toFloat()).createPoint(pos.x, pos.y)
                        runCatching {
                            c.cameraControl.startFocusAndMetering(
                                FocusMeteringAction.Builder(point,
                                    FocusMeteringAction.FLAG_AF or FocusMeteringAction.FLAG_AE)
                                    .setAutoCancelDuration(4, TimeUnit.SECONDS).build())
                        }
                    },
                    // Double-tap toggles between 1x and 2x, the way most
                    // camera apps do — quicker than a pinch with one hand.
                    onDoubleTap = { setZoom(if (ratio < 1.9f) 2f else 1f) },
                )
            },
    ) {
        focusAt?.let { at ->
            if (focusRing.value > 0f) {
                Canvas(Modifier.fillMaxSize()) {
                    drawCircle(Color.White.copy(alpha = focusRing.value), radius = 34.dp.toPx(),
                               center = at, style = Stroke(width = 2.dp.toPx()))
                }
            }
        }

        if (showPresets && maxRatio > 1.01f) {
            ZoomPresets(
                current = ratio,
                max = maxRatio,
                onPick = { setZoom(it) },
                modifier = Modifier.align(Alignment.BottomCenter).padding(bottom = 150.dp),
            )
        }
    }
}

/**
 * 1x, 2x, 5x, 10x — whichever the camera can reach — as round chips, with
 * the current ratio shown on the nearest one. The usual camera-app control:
 * one tap to a known framing, and a readout of where you are after a pinch.
 */
@Composable
private fun ZoomPresets(current: Float, max: Float, onPick: (Float) -> Unit, modifier: Modifier) {
    val stops = listOf(1f, 2f, 5f, 10f).filter { it <= max + 0.01f }
    val nearest = stops.minBy { kotlin.math.abs(it - current) }
    Row(
        modifier
            .clip(CircleShape)
            .background(Color.Black.copy(alpha = 0.45f))
            .padding(horizontal = 6.dp, vertical = 4.dp),
        horizontalArrangement = Arrangement.spacedBy(4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        stops.forEach { stop ->
            val active = stop == nearest
            Box(
                Modifier
                    .size(if (active) 40.dp else 34.dp)
                    .clip(CircleShape)
                    .background(if (active) Color.White.copy(alpha = 0.18f) else Color.Transparent)
                    .clickable { onPick(stop) },
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    if (active) formatRatio(current) else "${stop.toInt()}",
                    color = if (active) FieldAmber else Color.White,
                    fontSize = if (active) 13.sp else 12.sp,
                    fontWeight = FontWeight.SemiBold,
                )
            }
        }
    }
}

private fun formatRatio(r: Float): String =
    if (r < 10f && kotlin.math.abs(r - Math.round(r)) > 0.05f)
        String.format(Locale.US, "%.1f×", r)
    else "${Math.round(r)}×"
