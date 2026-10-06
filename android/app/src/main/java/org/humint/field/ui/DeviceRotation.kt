package org.humint.field.ui

import android.view.OrientationEventListener
import android.view.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext

/**
 * Which way up the phone is being held, as a Surface rotation.
 *
 * The app's screens are locked to portrait, so the display never rotates and
 * CameraX, left alone, assumes every photo and clip is portrait -- a building
 * shot with the phone held sideways came out on its side. This reads the
 * accelerometer instead, the way CameraX's own documentation recommends for a
 * portrait-locked app, and the camera screens hand it to the capture as its
 * target rotation. The controls stay where they are; only the picture knows
 * which way is up.
 *
 * Forty-five degrees either side of each edge, so a phone held roughly
 * upright is upright and a tilt has to be meant.
 */
@Composable
fun rememberDeviceRotation(): Int {
    val context = LocalContext.current
    var rotation by remember { mutableIntStateOf(Surface.ROTATION_0) }
    DisposableEffect(Unit) {
        val listener = object : OrientationEventListener(context) {
            override fun onOrientationChanged(degrees: Int) {
                if (degrees == ORIENTATION_UNKNOWN) return       // flat on a table: keep the last
                val next = when (degrees) {
                    in 45 until 135 -> Surface.ROTATION_270
                    in 135 until 225 -> Surface.ROTATION_180
                    in 225 until 315 -> Surface.ROTATION_90
                    else -> Surface.ROTATION_0
                }
                if (next != rotation) rotation = next
            }
        }
        if (listener.canDetectOrientation()) listener.enable()
        onDispose { listener.disable() }
    }
    return rotation
}
