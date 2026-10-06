package org.humint.field.ui

import android.Manifest
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.Camera
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageCapture
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.FlashAuto
import androidx.compose.material.icons.filled.FlashOff
import androidx.compose.material.icons.filled.FlashOn
import androidx.compose.material.icons.filled.FlashlightOn
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.LocalLifecycleOwner
import kotlinx.coroutines.launch
import org.humint.field.media.Capture

/**
 * Taking a photo, full screen.
 *
 * This replaces a bottom sheet. The sheet seemed right — the analyst is
 * mid-report and a sheet keeps the form underneath — but it sized itself to
 * its content, and on a handset that put the shutter button below the
 * bottom of the screen. You had to know to drag the sheet upward before you
 * could take a picture, which is not something to discover while standing in
 * the rain looking at a van.
 *
 * A camera is also a thing people have firm expectations about: a big
 * viewfinder, a shutter at the bottom under your thumb, a way out that is
 * not a gesture, a flash that is off until you want it, and zoom. None of
 * that fits in a sheet, so it is a screen.
 *
 * The flash used to be a torch toggle — a light that stayed on while you
 * framed the shot, announcing you to whoever you were photographing. It is
 * now a flash, the way every phone camera does it: Off by default, Auto, On
 * (fires at the shutter only), and Light for the rare case you need to see
 * to frame. The choice lasts for this screen, not forever — a flash left on
 * from last night's photo is not something to find out about in daylight.
 */

/** The four positions of the flash button, in the order a tap cycles them. */
private enum class FlashChoice(val label: String) {
    Off("Flash off"), Auto("Flash auto"), On("Flash on"), Light("Light");
    fun next() = entries[(ordinal + 1) % entries.size]
}
@Composable
fun PhotoCaptureScreen(
    onDone: (Capture.Captured?) -> Unit,
    onCancel: () -> Unit,
) {
    val context = LocalContext.current
    val owner = LocalLifecycleOwner.current
    val scope = rememberCoroutineScope()

    var granted by remember { mutableStateOf(
        ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) ==
            android.content.pm.PackageManager.PERMISSION_GRANTED
    ) }
    val permission = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted = it }
    LaunchedEffect(Unit) { if (!granted) permission.launch(Manifest.permission.CAMERA) }

    val capture = remember {
        ImageCapture.Builder()
            // Explicit, not left to the default: some vendor camera stacks
            // read "unset" as auto.
            .setFlashMode(ImageCapture.FLASH_MODE_OFF)
            .build()
    }
    // Landscape when the phone is held landscape. See DeviceRotation.kt.
    val rotation = rememberDeviceRotation()
    LaunchedEffect(rotation) { capture.targetRotation = rotation }
    var camera by remember { mutableStateOf<Camera?>(null) }
    var flash by remember { mutableStateOf(FlashChoice.Off) }
    var busy by remember { mutableStateOf(false) }

    fun applyFlash(choice: FlashChoice) {
        flash = choice
        capture.flashMode = when (choice) {
            FlashChoice.Auto -> ImageCapture.FLASH_MODE_AUTO
            FlashChoice.On -> ImageCapture.FLASH_MODE_ON
            else -> ImageCapture.FLASH_MODE_OFF
        }
        runCatching { camera?.cameraControl?.enableTorch(choice == FlashChoice.Light) }
    }

    Box(Modifier.fillMaxSize().background(Color.Black)) {

        if (granted) {
            AndroidView(
                factory = { ctx ->
                    val view = PreviewView(ctx).apply {
                        scaleType = PreviewView.ScaleType.FILL_CENTER
                    }
                    val future = ProcessCameraProvider.getInstance(ctx)
                    future.addListener({
                        runCatching {
                            val provider = future.get()
                            val preview = Preview.Builder().build()
                                .also { it.setSurfaceProvider(view.surfaceProvider) }
                            provider.unbindAll()
                            camera = provider.bindToLifecycle(
                                owner, CameraSelector.DEFAULT_BACK_CAMERA, preview, capture)
                        }
                    }, ContextCompat.getMainExecutor(ctx))
                    view
                },
                modifier = Modifier.fillMaxSize(),
            )
            CameraGestureLayer(camera)
        } else {
            Column(
                Modifier.fillMaxSize().padding(32.dp),
                verticalArrangement = Arrangement.Center,
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text("The camera is needed to take a photo.",
                     color = Color.White, style = MaterialTheme.typography.bodyLarge)
                Spacer(Modifier.height(10.dp))
                Text("Nothing taken here leaves the phone until you upload it.",
                     color = Color.White.copy(alpha = 0.7f),
                     style = MaterialTheme.typography.labelMedium)
            }
        }

        // --- top bar: out, and the flash --------------------------------
        Row(
            Modifier.fillMaxWidth().statusBarsPadding().padding(horizontal = 8.dp, vertical = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            RoundIcon(onClick = onCancel) {
                Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back", tint = Color.White)
            }
            Spacer(Modifier.weight(1f))
            if (camera?.cameraInfo?.hasFlashUnit() == true) {
                Row(
                    Modifier.clip(CircleShape).background(Color.Black.copy(alpha = 0.4f))
                        .padding(start = 4.dp, end = 12.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    IconButton(onClick = { applyFlash(flash.next()) },
                               modifier = Modifier.size(TapTarget)) {
                        Icon(
                            when (flash) {
                                FlashChoice.Off -> Icons.Filled.FlashOff
                                FlashChoice.Auto -> Icons.Filled.FlashAuto
                                FlashChoice.On -> Icons.Filled.FlashOn
                                FlashChoice.Light -> Icons.Filled.FlashlightOn
                            },
                            contentDescription = "${flash.label}. Tap to change.",
                            tint = if (flash == FlashChoice.Off) Color.White else FieldAmber,
                        )
                    }
                    Text(flash.label, color = Color.White, fontWeight = FontWeight.Medium,
                         style = MaterialTheme.typography.labelLarge)
                }
            }
        }

        // --- the shutter, where a thumb already is ------------------------
        Column(
            Modifier.align(Alignment.BottomCenter).navigationBarsPadding().padding(bottom = 26.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(
                if (busy) "Saving…" else "Pinch to zoom · tap to focus",
                color = Color.White.copy(alpha = 0.85f),
                style = MaterialTheme.typography.labelMedium,
            )
            Spacer(Modifier.height(10.dp))
            Box(
                Modifier
                    .size(82.dp)
                    .clip(CircleShape)
                    .border(3.dp, Color.White.copy(alpha = 0.9f), CircleShape),
                contentAlignment = Alignment.Center,
            ) {
                Button(
                    onClick = {
                        if (busy || !granted) return@Button
                        busy = true
                        scope.launch {
                            val shot = runCatching { Capture.takePhoto(context, capture) }
                            runCatching { camera?.cameraControl?.enableTorch(false) }
                            onDone(shot.getOrNull())
                        }
                    },
                    enabled = granted && !busy,
                    shape = CircleShape,
                    colors = ButtonDefaults.buttonColors(containerColor = Color.White),
                    contentPadding = androidx.compose.foundation.layout.PaddingValues(0.dp),
                    modifier = Modifier.size(68.dp),
                ) {
                    if (busy) {
                        CircularProgressIndicator(
                            strokeWidth = 2.dp,
                            color = Color.Black,
                            modifier = Modifier.size(22.dp),
                        )
                    }
                }
            }
        }
    }

    DisposableEffect(Unit) {
        onDispose {
            runCatching {
                camera?.cameraControl?.enableTorch(false)
                ProcessCameraProvider.getInstance(context).get().unbindAll()
            }
        }
    }
}


/** A round, translucent icon button for use over a viewfinder. */
@Composable
internal fun RoundIcon(onClick: () -> Unit, content: @Composable () -> Unit) {
    Box(
        Modifier.size(TapTarget).clip(CircleShape).background(Color.Black.copy(alpha = 0.4f)),
        contentAlignment = Alignment.Center,
    ) {
        IconButton(onClick = onClick, modifier = Modifier.size(TapTarget)) { content() }
    }
}
