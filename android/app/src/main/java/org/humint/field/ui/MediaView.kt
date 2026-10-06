package org.humint.field.ui

import android.content.Context
import android.graphics.Bitmap
import android.media.MediaDataSource
import android.media.MediaMetadataRetriever
import android.net.Uri
import android.view.ViewGroup
import androidx.annotation.OptIn
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.GraphicEq
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.media3.common.MediaItem
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.ByteArrayDataSource
import androidx.media3.datasource.DataSource
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.ProgressiveMediaSource
import androidx.media3.ui.PlayerView
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.humint.field.data.AttachmentRow
import org.humint.field.media.Capture

/**
 * Playing back a clip or a voice memo that has not been sent yet.
 *
 * The same reasoning as the photo viewer (AttachmentView.kt): a recording you
 * cannot play back is one you find out was wind noise, or the inside of a
 * pocket, hours later and miles away. And the same rule: the file is
 * encrypted on disk and stays that way. It is decrypted into memory and the
 * player reads it from there -- Media3's ByteArrayDataSource -- so there is
 * never a plaintext copy for another app, a crash dump or a cache to keep.
 * Clips are capped at two minutes of SD video, so holding one in memory is
 * fine.
 */

/** A tile for a clip or a memo: the first frame of a video, or a sound icon,
 *  with a play mark, the length, and a tap to play. */
@Composable
fun MediaThumb(row: AttachmentRow, onOpen: () -> Unit, size: Int = 56) {
    val context = LocalContext.current
    var frame by remember(row.id) { mutableStateOf<ImageBitmap?>(null) }
    val isVideo = row.kind == "video"

    if (isVideo) {
        LaunchedEffect(row.id) {
            frame = withContext(Dispatchers.IO) {
                runCatching {
                    val plain = Capture.open(context, row.path) ?: return@runCatching null
                    firstFrame(plain, maxEdge = size * 4)?.asImageBitmap()
                }.getOrNull()
            }
        }
    }

    Box(
        Modifier
            .size(size.dp)
            .clip(RoundedCornerShape(6.dp))
            .background(if (isVideo) Color.Black else MaterialTheme.colorScheme.surfaceVariant)
            .clickable(onClick = onOpen),
        contentAlignment = Alignment.Center,
    ) {
        frame?.let {
            Image(it, contentDescription = "Video attached to this report",
                  contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
        }
        if (!isVideo) {
            Icon(Icons.Filled.GraphicEq, contentDescription = "Voice memo attached to this report",
                 tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.5f),
                 modifier = Modifier.size((size * 0.6f).dp))
        }
        Box(
            Modifier.size((size * 0.46f).dp).clip(CircleShape)
                .background(Color.Black.copy(alpha = 0.55f)),
            contentAlignment = Alignment.Center,
        ) {
            Icon(Icons.Filled.PlayArrow, contentDescription = null, tint = Color.White,
                 modifier = Modifier.size((size * 0.34f).dp))
        }
    }
}

/** The clip or memo, full screen, with a player's controls -- the same shape
 *  as the photo viewer, so the two feel like one thing. */
@OptIn(UnstableApi::class)
@Composable
fun FullMedia(row: AttachmentRow, onClose: () -> Unit) {
    val context = LocalContext.current
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    var player by remember(row.id) { mutableStateOf<ExoPlayer?>(null) }
    var failed by remember(row.id) { mutableStateOf(false) }
    val isVideo = row.kind == "video"

    LaunchedEffect(row.id) {
        val bytes = withContext(Dispatchers.IO) {
            runCatching { Capture.open(context, row.path) }.getOrNull()
        }
        if (bytes == null) { failed = true; return@LaunchedEffect }
        player = buildPlayer(context, bytes)
    }
    // Released when the viewer closes, and paused if the app goes to the
    // background mid-clip: nothing should keep playing out of a phone that has
    // just been put in a pocket.
    DisposableEffect(row.id) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_STOP) player?.pause()
        }
        lifecycle.addObserver(observer)
        onDispose {
            lifecycle.removeObserver(observer)
            player?.release()
            player = null
        }
    }

    Dialog(
        onDismissRequest = onClose,
        properties = DialogProperties(usePlatformDefaultWidth = false),
    ) {
        Box(Modifier.fillMaxSize().background(Color.Black)) {
            val p = player
            when {
                failed -> Text(
                    "This recording cannot be played on this phone.",
                    color = Color.White,
                    style = MaterialTheme.typography.bodyLarge,
                    modifier = Modifier.align(Alignment.Center).padding(32.dp),
                )
                p == null -> CircularProgressIndicator(
                    color = Color.White, modifier = Modifier.align(Alignment.Center))
                isVideo -> PlayerSurface(
                    p, alwaysShowControls = false,
                    modifier = Modifier.fillMaxSize().statusBarsPadding().padding(bottom = 96.dp))
                else -> Column(
                    Modifier.align(Alignment.Center).fillMaxWidth().padding(horizontal = 16.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    Icon(Icons.Filled.GraphicEq, contentDescription = null,
                         tint = Color.White.copy(alpha = 0.7f), modifier = Modifier.size(96.dp))
                    Spacer(Modifier.height(16.dp))
                    // A voice memo has nothing to look at; the controls are
                    // the whole screen's worth of use, so they never hide.
                    PlayerSurface(p, alwaysShowControls = true,
                                  modifier = Modifier.fillMaxWidth().height(140.dp))
                }
            }
            Column(
                Modifier.align(Alignment.BottomCenter).navigationBarsPadding()
                    .fillMaxWidth().padding(16.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text(
                    buildString {
                        append(row.filename)
                        row.durationMs?.let { append(" · ${it / 1000}s") }
                        append(" · ${row.sizeBytes / 1024} KB · not sent yet")
                    },
                    color = Color.White.copy(alpha = 0.8f),
                    style = MaterialTheme.typography.labelMedium,
                )
                Spacer(Modifier.height(6.dp))
                TextButton(onClick = onClose, modifier = Modifier.heightIn(min = TapTarget)) {
                    Text("Close", color = Color.White)
                }
            }
            TextButton(
                onClick = onClose,
                modifier = Modifier.align(Alignment.TopStart).statusBarsPadding()
                    .heightIn(min = TapTarget),
            ) { Text("Back", color = Color.White) }
        }
    }
}

@OptIn(UnstableApi::class)
@Composable
private fun PlayerSurface(player: ExoPlayer, alwaysShowControls: Boolean, modifier: Modifier) {
    AndroidView(
        factory = { ctx ->
            PlayerView(ctx).apply {
                layoutParams = ViewGroup.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT)
                this.player = player
                useController = true
                setShowNextButton(false)
                setShowPreviousButton(false)
                setShowShuffleButton(false)
                setBackgroundColor(android.graphics.Color.BLACK)
                if (alwaysShowControls) {
                    controllerShowTimeoutMs = 0
                    controllerHideOnTouch = false
                    showController()
                }
            }
        },
        update = { it.player = player },
        modifier = modifier,
    )
}

@OptIn(UnstableApi::class)
private fun buildPlayer(context: Context, bytes: ByteArray): ExoPlayer {
    val factory = DataSource.Factory { ByteArrayDataSource(bytes) }
    // The URI is a label only; ByteArrayDataSource ignores it.
    val source = ProgressiveMediaSource.Factory(factory)
        .createMediaSource(MediaItem.fromUri(Uri.parse("memory://attachment")))
    return ExoPlayer.Builder(context).build().apply {
        setMediaSource(source)
        prepare()
        playWhenReady = true
    }
}

/** The first frame of a video held in memory, scaled down for a thumbnail. */
private fun firstFrame(bytes: ByteArray, maxEdge: Int): Bitmap? {
    val retriever = MediaMetadataRetriever()
    return try {
        retriever.setDataSource(BytesMediaSource(bytes))
        val frame = retriever.getFrameAtTime(0, MediaMetadataRetriever.OPTION_CLOSEST_SYNC)
            ?: return null
        val scale = maxEdge.toFloat() / maxOf(frame.width, frame.height)
        if (scale >= 1f) frame
        else Bitmap.createScaledBitmap(frame, (frame.width * scale).toInt().coerceAtLeast(1),
                                       (frame.height * scale).toInt().coerceAtLeast(1), true)
    } catch (e: Exception) {
        null
    } finally {
        runCatching { retriever.release() }
    }
}

/** MediaMetadataRetriever reads through this rather than a file, for the same
 *  reason the player does: there is no plaintext file to give it. */
private class BytesMediaSource(private val bytes: ByteArray) : MediaDataSource() {
    override fun readAt(position: Long, buffer: ByteArray, offset: Int, size: Int): Int {
        if (position >= bytes.size) return -1
        val n = minOf(size.toLong(), bytes.size - position).toInt()
        System.arraycopy(bytes, position.toInt(), buffer, offset, n)
        return n
    }

    override fun getSize(): Long = bytes.size.toLong()
    override fun close() = Unit
}
