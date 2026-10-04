package org.humint.field.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.CloudUpload
import androidx.compose.material.icons.filled.ErrorOutline
import androidx.compose.material.icons.outlined.Inbox
import androidx.compose.material3.Button
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import org.humint.field.FieldViewModel
import org.humint.field.data.ReportRow
import org.humint.field.data.Templates
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale

/**
 * The queue: what is on this phone and not yet sent.
 *
 * The screen the analyst sees on opening the app. It answers, in order: is
 * anything waiting to go (and if so, the one-tap way to send it), and what
 * have I written. Starting a report is the centre of the bottom bar, not a
 * button here.
 */
@Composable
fun QueueScreen(
    vm: FieldViewModel,
    padding: PaddingValues,
    onOpen: (String) -> Unit,
    onSend: () -> Unit,
    onNew: () -> Unit,
) {
    val queue by vm.queue.collectAsStateWithLifecycle()
    val ready by vm.readyCount.collectAsStateWithLifecycle()
    var filter by rememberSaveable { mutableStateOf("all") }
    val drafts = queue.count { it.status == "draft" }
    val shown = when (filter) {
        "draft" -> queue.filter { it.status == "draft" }
        "ready" -> queue.filter { it.status == "ready" }
        else -> queue
    }

    LazyColumn(
        Modifier.fillMaxSize().padding(padding),
        contentPadding = PaddingValues(start = 16.dp, end = 16.dp, bottom = 32.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item {
            Column(Modifier.padding(top = 18.dp, bottom = 4.dp)) {
                Text("Reports", style = MaterialTheme.typography.headlineMedium,
                     fontWeight = FontWeight.Bold)
                Text(
                    when {
                        queue.isEmpty() -> "Nothing on this phone"
                        else -> "${queue.size} on this phone · encrypted"
                    },
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }

        if (ready > 0) {
            item { ReadyBanner(ready, onSend) }
        }

        if (queue.isNotEmpty()) {
            item {
                LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    item { Chip("All", queue.size, filter == "all") { filter = "all" } }
                    item { Chip("Drafts", drafts, filter == "draft") { filter = "draft" } }
                    item { Chip("Ready", ready, filter == "ready") { filter = "ready" } }
                }
            }
        }

        if (queue.isEmpty()) {
            item { EmptyQueue(onNew) }
        } else if (shown.isEmpty()) {
            item {
                Text(if (filter == "draft") "No drafts — everything is ready to send."
                     else "Nothing is ready yet. Finish a draft to send it.",
                     style = MaterialTheme.typography.bodyMedium,
                     color = MaterialTheme.colorScheme.onSurfaceVariant,
                     modifier = Modifier.padding(vertical = 24.dp))
            }
        } else {
            items(shown, key = { it.id }) { row -> QueueCard(row) { onOpen(row.id) } }
        }
    }
}

@Composable
private fun Chip(label: String, count: Int, selected: Boolean, onClick: () -> Unit) {
    FilterChip(
        selected = selected,
        onClick = onClick,
        label = { Text("$label  $count") },
        shape = CircleShape,
        colors = FilterChipDefaults.filterChipColors(
            selectedContainerColor = MaterialTheme.colorScheme.primary.copy(alpha = 0.16f),
            selectedLabelColor = MaterialTheme.colorScheme.primary,
        ),
    )
}

/** The one thing worth doing when anything is ready: send it. */
@Composable
private fun ReadyBanner(ready: Int, onSend: () -> Unit) {
    Row(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(20.dp))
            .background(MaterialTheme.colorScheme.primary.copy(alpha = 0.12f))
            .clickable(onClick = onSend)
            .padding(16.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            Modifier.size(44.dp).clip(CircleShape).background(MaterialTheme.colorScheme.primary),
            contentAlignment = Alignment.Center,
        ) {
            Icon(Icons.Filled.CloudUpload, contentDescription = null,
                 tint = MaterialTheme.colorScheme.onPrimary)
        }
        Column(Modifier.weight(1f).padding(horizontal = 14.dp)) {
            Text("$ready ready to send", style = MaterialTheme.typography.titleMedium,
                 fontWeight = FontWeight.SemiBold)
            Text("Scan the console's code when you're in range",
                 style = MaterialTheme.typography.labelMedium,
                 color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, contentDescription = "Send",
             tint = MaterialTheme.colorScheme.primary)
    }
}

@Composable
private fun EmptyQueue(onNew: () -> Unit) {
    Column(
        Modifier.fillMaxWidth().padding(top = 64.dp, start = 16.dp, end = 16.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Box(
            Modifier.size(88.dp).clip(CircleShape)
                .background(MaterialTheme.colorScheme.surfaceVariant),
            contentAlignment = Alignment.Center,
        ) {
            Icon(Icons.Outlined.Inbox, contentDescription = null,
                 tint = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.size(40.dp))
        }
        Spacer(Modifier.height(18.dp))
        Text("No reports yet", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold)
        Spacer(Modifier.height(6.dp))
        Text(
            "Reports are written here and stay here, encrypted, until you're back in " +
            "range of the console.",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = androidx.compose.ui.text.style.TextAlign.Center,
        )
        Spacer(Modifier.height(20.dp))
        Button(onClick = onNew, shape = CircleShape,
               modifier = Modifier.heightIn(min = 52.dp)) { Text("Start a report") }
    }
}

@Composable
private fun QueueCard(row: ReportRow, onClick: () -> Unit) {
    val template = Templates.byKey(row.template)
    Row(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(20.dp))
            .background(MaterialTheme.colorScheme.surface)
            .clickable(onClick = onClick)
            .padding(14.dp),
        verticalAlignment = Alignment.Top,
    ) {
        TemplateBadge(row.template)
        Spacer(Modifier.width(14.dp))
        Column(Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    template?.label ?: row.template,
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.weight(1f),
                )
                StatusPill(row.status)
            }
            Spacer(Modifier.height(2.dp))
            Text(row.title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold,
                 maxLines = 2, overflow = TextOverflow.Ellipsis)
            Spacer(Modifier.height(4.dp))
            Text(
                friendlyTime(row.observedAt ?: row.createdAt),
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            // A failed send keeps its reason on the card rather than in a
            // toast that has long since gone. The analyst comes back to this
            // screen an hour later and needs to know why it is still here.
            row.lastError?.let {
                Spacer(Modifier.height(8.dp))
                Row(
                    Modifier.clip(RoundedCornerShape(12.dp))
                        .background(MaterialTheme.colorScheme.error.copy(alpha = 0.12f))
                        .padding(horizontal = 10.dp, vertical = 6.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Icon(Icons.Filled.ErrorOutline, contentDescription = null,
                         tint = MaterialTheme.colorScheme.error, modifier = Modifier.size(18.dp))
                    Spacer(Modifier.width(6.dp))
                    Text(it, style = MaterialTheme.typography.labelMedium,
                         color = MaterialTheme.colorScheme.error)
                }
            }
        }
    }
}

@Composable
private fun StatusPill(status: String) {
    val (label, colour) = when (status) {
        "ready" -> "Ready" to MaterialTheme.colorScheme.primary
        "sent" -> "Sent" to MaterialTheme.colorScheme.onSurfaceVariant
        else -> "Draft" to FieldAmber
    }
    Row(
        Modifier.clip(CircleShape).background(colour.copy(alpha = 0.14f))
            .padding(horizontal = 9.dp, vertical = 3.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(Modifier.size(6.dp).clip(CircleShape).background(colour))
        Spacer(Modifier.width(5.dp))
        Text(label, style = MaterialTheme.typography.labelMedium, color = colour,
             fontWeight = FontWeight.SemiBold)
    }
}

/** "Today 14:05", "Yesterday 09:12", "3 Oct 22:40". */
private fun friendlyTime(at: Long): String {
    val then = Calendar.getInstance().apply { timeInMillis = at }
    val now = Calendar.getInstance()
    val time = SimpleDateFormat("HH:mm", Locale.getDefault()).format(Date(at))
    val sameYear = then.get(Calendar.YEAR) == now.get(Calendar.YEAR)
    val dayDiff = now.get(Calendar.DAY_OF_YEAR) - then.get(Calendar.DAY_OF_YEAR)
    return when {
        sameYear && dayDiff == 0 -> "Today $time"
        sameYear && dayDiff == 1 -> "Yesterday $time"
        else -> SimpleDateFormat("d MMM, HH:mm", Locale.getDefault()).format(Date(at))
    }
}
