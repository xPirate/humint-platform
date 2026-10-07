package org.humint.field.ui

import android.Manifest
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.Fill
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.LifecycleResumeEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import kotlinx.coroutines.delay
import org.humint.field.FieldViewModel
import org.humint.field.data.Position
import org.humint.field.data.ReportRow
import org.humint.field.track.Shape
import org.humint.field.track.batteryWarning
import org.humint.field.track.formatDuration
import org.humint.field.track.formatLength
import kotlin.math.cos
import kotlin.math.max

/**
 * The route recorder, or the corner dropper, on a Route or Area report.
 *
 * Neither draws a map. The app has no tiles and should not: a basemap is a
 * download or a network request, and both say where the phone is to someone
 * else. The sketch is the shape alone, north up, which is enough to see that
 * the recording caught the walk and the corners are in order. The console
 * draws it on the map.
 */
@Composable
fun ShapeCard(
    vm: FieldViewModel,
    report: ReportRow,
    kind: String,
    fix: Position.Fix?,
    onMessage: (String) -> Unit,
) {
    Column(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(20.dp))
            .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f))
            .padding(14.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        if (kind == "track") RouteRecorderPanel(vm, report, onMessage)
        else PerimeterPanel(vm, report, fix)
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun RouteRecorderPanel(vm: FieldViewModel, report: ReportRow, onMessage: (String) -> Unit) {
    val rec by vm.recorder.collectAsStateWithLifecycle()
    val stored = remember(report.geometry) { Shape.parse(report.geometry, "track") }
    val recording = rec.running && rec.reportId == report.id
    var confirmClear by remember { mutableStateOf(false) }
    val context = LocalContext.current

    // Re-checked every time the screen comes back, so changing the setting
    // and pressing Back clears the warning straight away.
    var battery by remember { mutableStateOf<String?>(null) }
    LifecycleResumeEffect(Unit) {
        battery = runCatching { batteryWarning(context) }.getOrNull()
        onPauseOrDispose { }
    }

    // A clock for the elapsed time while recording; nothing ticks otherwise.
    var now by remember { mutableLongStateOf(System.currentTimeMillis()) }
    LaunchedEffect(recording) {
        while (recording) { now = System.currentTimeMillis(); delay(1000) }
    }

    fun begin() {
        vm.startRecording(report.id)?.let(onMessage)
    }
    // The notification permission (Android 13+) is asked for at the moment it
    // matters. Refused, the recording still runs; the notification just does
    // not show in the shade.
    val askNotifications = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()) { begin() }

    Text("Route", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)

    if (!stored.isEmpty) ShapeSketch(stored, Modifier.fillMaxWidth().height(170.dp))

    Text(
        if (stored.isEmpty && !recording) "Not recorded yet."
        else buildString {
            if (!stored.isEmpty) {
                append(formatLength(stored.lengthM)).append(" · ").append(stored.points).append(" points")
                stored.durationMs?.let { append(" · ").append(formatDuration(it)) }
                if (stored.segments.size > 1) append(" · ").append(stored.segments.size).append(" parts")
            }
        },
        style = MaterialTheme.typography.bodyMedium,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )

    if (recording) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(10.dp).clip(CircleShape).background(MaterialTheme.colorScheme.error))
            Spacer(Modifier.width(8.dp))
            Column {
                Text("Recording · ${formatDuration(now - rec.startedAt)}",
                     style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
                Text(
                    buildString {
                        append(if (rec.points == 0) "Waiting for a GPS fix…"
                               else "${formatLength(rec.lengthM)} · ${rec.points} points this run")
                        rec.lastAccuracyM?.let { append(" · GPS ±${it.toInt()} m") }
                    },
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
    rec.problem?.takeIf { rec.reportId == null || rec.reportId == report.id }?.let {
        Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodyMedium)
    }

    // After a run: what the GPS actually did, so a thin track explains
    // itself -- "no fixes for 20 minutes" is a phone setting, "most fixes
    // too rough" is the sky, and they are fixed in different ways.
    if (!recording && rec.reportId == report.id && rec.startedAt > 0L) {
        val gapLong = rec.longestGapMs >= 60_000L
        val mostlyRough = rec.fixes >= 10 && rec.tooRough * 2 > rec.fixes
        Text(
            buildString {
                append("Last run: ${rec.fixes} GPS fixes, ${rec.points} kept")
                if (rec.tooRough > 0) append(", ${rec.tooRough} too inaccurate")
                append(".")
                if (gapLong) append(" No GPS at all for ${formatDuration(rec.longestGapMs)} — the phone stopped location, usually with the screen off.")
                else if (mostlyRough) append(" Most fixes were too rough to draw — a phone deep in a pocket or bag, or heavy cover.")
            },
            style = MaterialTheme.typography.labelMedium,
            color = if (gapLong || mostlyRough) FieldAmber else MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }

    battery?.let { why ->
        Text(why, style = MaterialTheme.typography.bodyMedium, color = FieldAmber)
        OutlinedButton(
            onClick = {
                // The app's own page in Settings: Battery → Unrestricted. The
                // direct "ignore optimisations" request needs a permission
                // Play restricts, and this is one tap further.
                val intent = if (why.startsWith("Battery Saver")) Intent(Settings.ACTION_BATTERY_SAVER_SETTINGS)
                    else Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                                Uri.fromParts("package", context.packageName, null))
                runCatching { context.startActivity(intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
            },
            modifier = Modifier.heightIn(min = TapTarget),
        ) { Text("Open battery settings") }
    }

    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        if (recording) {
            Button(
                onClick = { vm.stopRecording() },
                colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error),
                modifier = Modifier.heightIn(min = TapTarget),
            ) { Text("Stop") }
        } else {
            Button(
                onClick = {
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU)
                        askNotifications.launch(Manifest.permission.POST_NOTIFICATIONS)
                    else begin()
                },
                enabled = report.status != "ready",
                modifier = Modifier.heightIn(min = TapTarget),
            ) { Text(if (stored.isEmpty) "Start recording" else "Continue recording") }
            if (!stored.isEmpty) {
                OutlinedButton(onClick = { confirmClear = true },
                               modifier = Modifier.heightIn(min = TapTarget)) { Text("Clear") }
            }
        }
    }
    Text(
        if (recording) "Put the phone away; it keeps recording with the screen off. Press Stop, here or in the notification, when you arrive."
        else "Records with the screen off until you press Stop. A notification shows the whole time.",
        style = MaterialTheme.typography.labelMedium,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )

    if (confirmClear) {
        AlertDialog(
            onDismissRequest = { confirmClear = false },
            title = { Text("Clear the route?") },
            text = { Text("The recorded points are deleted from this phone. The rest of the report stays.") },
            confirmButton = {
                TextButton(onClick = { vm.clearShape(report.id); confirmClear = false }) {
                    Text("Clear", color = MaterialTheme.colorScheme.error)
                }
            },
            dismissButton = { TextButton(onClick = { confirmClear = false }) { Text("Keep it") } },
        )
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun PerimeterPanel(vm: FieldViewModel, report: ReportRow, fix: Position.Fix?) {
    val stored = remember(report.geometry) { Shape.parse(report.geometry, "perimeter") }
    val corners = stored.points

    Text("Corners", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
    if (corners > 0) ShapeSketch(stored, Modifier.fillMaxWidth().height(170.dp))
    Text(
        when (corners) {
            0 -> "Walk the edge and drop a point at each corner, in order."
            1, 2 -> "$corners corner${if (corners == 1) "" else "s"} — at least three make an area."
            else -> "$corners corners · ${formatLength(stored.lengthM)} around"
        },
        style = MaterialTheme.typography.bodyMedium,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
    Text(
        when {
            fix == null -> "Waiting for GPS…"
            fix.stale -> "GPS fix is old — wait for a fresh one before dropping a corner."
            fix.accuracyM > 25f -> "GPS ±${fix.accuracyM.toInt()} m — wait a moment for a better fix if you can."
            else -> "GPS ±${fix.accuracyM.toInt()} m"
        },
        style = MaterialTheme.typography.labelMedium,
        color = if (fix == null || fix.stale || fix.accuracyM > 25f) FieldAmber
                else MaterialTheme.colorScheme.onSurfaceVariant,
    )
    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Button(
            onClick = { fix?.let { vm.addCorner(report.id, it) } },
            enabled = fix != null && !fix.stale && report.status != "ready",
            modifier = Modifier.heightIn(min = TapTarget),
        ) { Text("Drop a corner here") }
        if (corners > 0) {
            OutlinedButton(onClick = { vm.undoCorner(report.id) },
                           modifier = Modifier.heightIn(min = TapTarget)) { Text("Undo last") }
        }
    }
    Text("Keep the app open while you walk the edge; it reads the position only while it is on screen.",
         style = MaterialTheme.typography.labelMedium,
         color = MaterialTheme.colorScheme.onSurfaceVariant)
}

/** The shape alone, north up, scaled to fit. */
@Composable
fun ShapeSketch(shape: Shape, modifier: Modifier = Modifier) {
    val line = MaterialTheme.colorScheme.primary
    val start = MaterialTheme.colorScheme.tertiary
    val grid = MaterialTheme.colorScheme.outlineVariant
    Canvas(modifier.clip(RoundedCornerShape(14.dp)).background(MaterialTheme.colorScheme.surface)) {
        val all = shape.segments.flatten()
        if (all.isEmpty()) return@Canvas
        // Longitude shrinks with latitude; without this a square walked in
        // the north comes out as a wide rectangle.
        val k = cos(Math.toRadians(all.sumOf { it.lat } / all.size))
        val xs = all.map { it.lon * k }
        val ys = all.map { it.lat }
        val minX = xs.min(); val maxX = xs.max(); val minY = ys.min(); val maxY = ys.max()
        val span = max(max(maxX - minX, maxY - minY), 1e-6)
        val pad = 18.dp.toPx()
        val scale = (minOf(size.width, size.height) - 2 * pad) / span
        val offX = (size.width - (maxX - minX) * scale) / 2
        val offY = (size.height - (maxY - minY) * scale) / 2
        fun at(lat: Double, lon: Double) = Offset(
            (offX + (lon * k - minX) * scale).toFloat(),
            (size.height - offY - (lat - minY) * scale).toFloat())

        // A faint grid, so a sketch reads as a drawing to scale rather than a
        // squiggle.
        val step = size.width / 6
        for (i in 1 until 6) drawLine(grid.copy(alpha = 0.35f), Offset(step * i, 0f), Offset(step * i, size.height), 1f)

        shape.segments.forEach { seg ->
            if (seg.isEmpty()) return@forEach
            val path = Path().apply {
                val first = at(seg[0].lat, seg[0].lon)
                moveTo(first.x, first.y)
                seg.drop(1).forEach { p -> at(p.lat, p.lon).let { lineTo(it.x, it.y) } }
                if (shape.kind == "perimeter" && seg.size >= 3) close()
            }
            if (shape.kind == "perimeter" && seg.size >= 3) drawPath(path, line.copy(alpha = 0.18f), style = Fill)
            drawPath(path, line, style = Stroke(width = 3.dp.toPx(), cap = StrokeCap.Round, join = StrokeJoin.Round))
            if (shape.kind == "perimeter") {
                seg.forEach { p -> drawCircle(line, 4.dp.toPx(), at(p.lat, p.lon)) }
            }
        }
        val first = all.first()
        drawCircle(start, 6.dp.toPx(), at(first.lat, first.lon))
        drawCircle(Color.White, 2.5.dp.toPx(), at(first.lat, first.lon))
    }
}
