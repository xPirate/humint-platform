package org.humint.field.ui

import android.content.Intent
import android.net.Uri
import android.provider.Settings as AndroidSettings
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
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
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Flag
import androidx.compose.material.icons.filled.Inbox
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.PhoneAndroid
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.WifiTethering
import androidx.compose.material.icons.outlined.Flag
import androidx.compose.material.icons.outlined.Inbox
import androidx.compose.material.icons.outlined.Lock
import androidx.compose.material.icons.outlined.PhoneAndroid
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material.icons.outlined.WifiTethering
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.FilterQuality
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.LifecycleResumeEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import kotlinx.coroutines.launch
import org.humint.field.data.AttachmentRow
import org.humint.field.data.RelayDeviceRow
import org.humint.field.data.RelayFileRow
import org.humint.field.data.RelaySubmissionRow
import org.humint.field.data.Templates
import org.humint.field.relay.Relay
import org.humint.field.relay.RelayViewModel
import org.humint.field.track.Shape
import org.humint.field.track.batteryWarning
import org.json.JSONArray
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/*
 * The relay's frame: Inbox · Phones · Relay · Lock · Settings.
 *
 * No centre "+" here. A relay's job is to take in the team's reports, not
 * to write its own; a lead who wants to file one turns relay mode off in
 * Settings, or — better — writes it on their own phone and sends it here
 * like everyone else.
 */
enum class RelayTab { Inbox, Priorities, Phones, Relay, Lock, Settings }

@Composable
fun RelayShell(current: RelayTab, inboxCount: Int, onTab: (RelayTab) -> Unit,
               content: @Composable (PaddingValues) -> Unit) {
    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        bottomBar = {
            Surface(color = MaterialTheme.colorScheme.surface, tonalElevation = 3.dp, shadowElevation = 12.dp) {
                Row(
                    Modifier.fillMaxWidth().navigationBarsPadding().height(68.dp).padding(horizontal = 6.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    RelayBarItem(RelayTab.Inbox, current, Icons.Filled.Inbox, Icons.Outlined.Inbox, "Inbox", onTab, inboxCount)
                    RelayBarItem(RelayTab.Priorities, current, Icons.Filled.Flag, Icons.Outlined.Flag, "Priorities", onTab)
                    RelayBarItem(RelayTab.Phones, current, Icons.Filled.PhoneAndroid, Icons.Outlined.PhoneAndroid, "Phones", onTab)
                    RelayBarItem(RelayTab.Relay, current, Icons.Filled.WifiTethering, Icons.Outlined.WifiTethering, "Relay", onTab)
                    RelayBarItem(RelayTab.Lock, current, Icons.Filled.Lock, Icons.Outlined.Lock, "Lock", onTab)
                    RelayBarItem(RelayTab.Settings, current, Icons.Filled.Settings, Icons.Outlined.Settings, "Settings", onTab)
                }
            }
        },
        content = content,
    )
}

@Composable
private fun androidx.compose.foundation.layout.RowScope.RelayBarItem(
    tab: RelayTab, current: RelayTab, selectedIcon: ImageVector, icon: ImageVector,
    label: String, onTab: (RelayTab) -> Unit, badge: Int = 0,
) {
    val selected = tab == current
    val tint = if (selected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant
    Column(
        Modifier.weight(1f).clip(RoundedCornerShape(16.dp))
            .clickable(role = Role.Tab) { onTab(tab) }.padding(vertical = 6.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Box {
            Box(Modifier.clip(CircleShape)
                .background(if (selected) MaterialTheme.colorScheme.primary.copy(alpha = 0.14f) else Color.Transparent)
                .padding(horizontal = 16.dp, vertical = 4.dp)) {
                Icon(if (selected) selectedIcon else icon, contentDescription = null, tint = tint)
            }
            if (badge > 0) {
                Box(Modifier.align(Alignment.TopEnd).size(18.dp).clip(CircleShape)
                    .background(MaterialTheme.colorScheme.primary), contentAlignment = Alignment.Center) {
                    Text(if (badge > 99) "99+" else "$badge", fontSize = 9.sp, fontWeight = FontWeight.Bold,
                         color = MaterialTheme.colorScheme.onPrimary)
                }
            }
        }
        Spacer(Modifier.height(2.dp))
        Text(label, fontSize = 12.sp, color = tint,
             fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal)
    }
}

/** A column that stays readable on a 12-inch tablet held landscape. */
@Composable
private fun Page(padding: PaddingValues, content: @Composable () -> Unit) {
    Box(Modifier.fillMaxSize().padding(padding), contentAlignment = Alignment.TopCenter) {
        Box(Modifier.widthIn(max = 760.dp).fillMaxWidth()) { content() }
    }
}

// ----------------------------------------------------------------- inbox

@Composable
fun RelayInboxScreen(vm: RelayViewModel, padding: PaddingValues, onOpen: (Int) -> Unit) {
    val inbox by vm.inbox.collectAsStateWithLifecycle()
    val counts by vm.fileCounts.collectAsStateWithLifecycle()
    val devices by vm.devices.collectAsStateWithLifecycle()
    val state by vm.state.collectAsStateWithLifecycle()
    val names = devices.associateBy { it.id }
    val unsent = inbox.count { it.forwardedAt == null }
    val priorities by vm.priorities.collectAsStateWithLifecycle()
    // null = all, -1 = not looked at yet, otherwise a priority id.
    var filter by remember { mutableStateOf<Int?>(null) }
    val untagged = inbox.count { it.priorities == null }
    val shown = when (filter) {
        null -> inbox
        -1 -> inbox.filter { it.priorities == null }
        else -> inbox.filter { filter in RelayViewModel.tagsOf(it) }
    }

    Page(padding) {
        LazyColumn(
            contentPadding = PaddingValues(start = 16.dp, end = 16.dp, bottom = 32.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            item {
                Column(Modifier.padding(top = 18.dp, bottom = 4.dp)) {
                    Text("Inbox", style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold)
                    Text(
                        when {
                            inbox.isEmpty() -> if (state.running) "Relay on · waiting for the team" else "Nothing received yet"
                            else -> "${inbox.size} received · $unsent not yet sent home"
                        },
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            if (!state.running) {
                item {
                    Banner("The relay is off", "Turn it on from the Relay tab so phones can send.", FieldAmber)
                }
            }
            if (inbox.isNotEmpty()) {
                item {
                    androidx.compose.foundation.lazy.LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        item { FilterChipX("All  ${inbox.size}", filter == null) { filter = null } }
                        item { FilterChipX("Untagged  $untagged", filter == -1) { filter = -1 } }
                        items(priorities, key = { it.id }) { p ->
                            val n = inbox.count { p.id in RelayViewModel.tagsOf(it) }
                            FilterChipX("P${p.rank}  $n", filter == p.id) { filter = p.id }
                        }
                    }
                }
            }
            if (inbox.isEmpty()) {
                item {
                    Text(
                        "Reports from the team's phones land here. Each phone joins this tablet's " +
                        "hotspot and scans its code from the Phones tab.",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(vertical = 24.dp),
                    )
                }
            }
            items(shown, key = { it.id }) { row ->
                InboxCard(row, names[row.deviceId], counts[row.id] ?: 0, Modifier.animateItem()) { onOpen(row.id) }
            }
        }
    }
}

@Composable
private fun FilterChipX(label: String, selected: Boolean, onClick: () -> Unit) {
    androidx.compose.material3.FilterChip(
        selected = selected, onClick = onClick, label = { Text(label) }, shape = CircleShape,
        colors = androidx.compose.material3.FilterChipDefaults.filterChipColors(
            selectedContainerColor = MaterialTheme.colorScheme.primary.copy(alpha = 0.16f),
            selectedLabelColor = MaterialTheme.colorScheme.primary),
    )
}

@Composable
private fun Banner(title: String, line: String, colour: Color) {
    Column(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp))
            .background(colour.copy(alpha = 0.12f)).padding(14.dp),
    ) {
        Text(title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
        Text(line, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun InboxCard(row: RelaySubmissionRow, device: RelayDeviceRow?, files: Int,
                      modifier: Modifier, onClick: () -> Unit) {
    val template = row.template?.let { Templates.byKey(it) }
    Row(
        modifier.fillMaxWidth().clip(RoundedCornerShape(20.dp))
            .background(MaterialTheme.colorScheme.surface).clickable(onClick = onClick).padding(14.dp),
        verticalAlignment = Alignment.Top,
    ) {
        TemplateBadge(row.template ?: "note")
        Spacer(Modifier.width(14.dp))
        Column(Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    listOfNotNull(template?.label, device?.analyst).joinToString(" · "),
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.weight(1f),
                )
                row.criticality?.takeIf { it != "Routine" }?.let { CriticalityPill(it) }
            }
            Spacer(Modifier.height(2.dp))
            Text(row.title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold,
                 maxLines = 2, overflow = TextOverflow.Ellipsis)
            Spacer(Modifier.height(4.dp))
            Text(
                buildString {
                    append("Received ").append(clock(row.receivedAt))
                    if (files == 1) append(" · 1 attachment") else if (files > 1) append(" · $files attachments")
                    if (row.forwardedAt != null) append(" · sent home")
                    val tags = RelayViewModel.tagsOf(row)
                    if (row.priorities == null) append(" · untagged")
                    else if (tags.isNotEmpty()) append(" · tagged")
                },
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun CriticalityPill(c: String) {
    val colour = when (c) {
        "Flash", "Immediate" -> MaterialTheme.colorScheme.error
        else -> FieldAmber
    }
    Text(c, style = MaterialTheme.typography.labelMedium, color = colour, fontWeight = FontWeight.SemiBold,
         modifier = Modifier.clip(CircleShape).background(colour.copy(alpha = 0.14f))
             .padding(horizontal = 9.dp, vertical = 3.dp))
}

private fun clock(ms: Long): String =
    SimpleDateFormat("EEE HH:mm", Locale.getDefault()).format(Date(ms))

// ---------------------------------------------------------------- detail

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun RelayReportScreen(vm: RelayViewModel, id: Int, onBack: () -> Unit) {
    val row by vm.submission(id).collectAsStateWithLifecycle(initialValue = null)
    val files by vm.files(id).collectAsStateWithLifecycle(initialValue = emptyList())
    val devices by vm.devices.collectAsStateWithLifecycle()
    var full by remember { mutableStateOf<AttachmentRow?>(null) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(row?.template?.let { Templates.byKey(it)?.label } ?: "Report",
                               fontWeight = FontWeight.SemiBold) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back to the inbox")
                    }
                },
            )
        },
    ) { padding ->
        val r = row ?: return@Scaffold
        val device = devices.firstOrNull { it.id == r.deviceId }
        Page(padding) {
            Column(
                Modifier.verticalScroll(rememberScrollState()).padding(horizontal = 20.dp).padding(bottom = 32.dp),
                verticalArrangement = Arrangement.spacedBy(14.dp),
            ) {
                Text(r.title, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
                Text(
                    buildString {
                        append(device?.let { "${it.analyst} · ${it.label}" } ?: "Phone ${r.deviceId}")
                        append(" · received ").append(clock(r.receivedAt))
                        RelayViewModel.parseIso(r.observedAt)?.let { append(" · seen ").append(clock(it)) }
                    },
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                r.criticality?.let { CriticalityPill(it) }

                if (r.lat != null && r.lng != null) {
                    Text(
                        "%.5f, %.5f".format(r.lat, r.lng) +
                            (r.accuracyM?.let { " (±${it.toInt()} m)" } ?: "") +
                            (r.locationNote?.let { " · $it" } ?: ""),
                        style = MaterialTheme.typography.bodyMedium.merge(MonoStyle),
                    )
                }

                r.geometry?.let { g ->
                    val kind = if (g.contains("Polygon")) "perimeter" else "track"
                    val shape = remember(g) { Shape.parse(g, kind) }
                    if (!shape.isEmpty) {
                        ShapeSketch(shape, Modifier.fillMaxWidth().height(200.dp))
                    }
                }

                FieldList(r)

                TagSection(vm, r)

                r.body?.let {
                    Text(it, style = MaterialTheme.typography.bodyLarge)
                }

                if (files.isNotEmpty()) {
                    Text("Attachments", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp),
                            verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        files.forEach { f ->
                            val a = f.asAttachment()
                            when (a.kind) {
                                "image" -> AttachmentThumb(a, onOpen = { full = a }, size = 104)
                                else -> MediaThumb(a, onOpen = { full = a }, size = 104)
                            }
                        }
                    }
                }
            }
        }
    }
    full?.let {
        if (it.kind == "image") FullImage(it, onClose = { full = null })
        else FullMedia(it, onClose = { full = null })
    }
}

/** The lead's half of a report: which priorities it answers, and a note. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun TagSection(vm: RelayViewModel, r: RelaySubmissionRow) {
    val priorities by vm.priorities.collectAsStateWithLifecycle()
    val tags = RelayViewModel.tagsOf(r)
    val suggested = remember(r.id, priorities) { RelayViewModel.suggest(r, priorities) }
    var note by remember(r.id) { mutableStateOf(r.leadNote.orEmpty()) }
    Column(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp))
            .background(MaterialTheme.colorScheme.primary.copy(alpha = 0.06f)).padding(14.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Text("Answers which priority?", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
        if (priorities.isEmpty()) {
            Text("No priorities yet. Add the team's on the Priorities tab.",
                 style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        } else {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                priorities.forEach { p ->
                    androidx.compose.material3.FilterChip(
                        selected = p.id in tags,
                        onClick = { vm.toggleTag(r, p.id) },
                        label = {
                            Text("P${p.rank} · ${p.statement.take(40)}" +
                                 if (p.id !in tags && p.id in suggested) "  · suggested" else "")
                        },
                    )
                }
            }
            if (r.priorities == null) {
                TextButton(onClick = { vm.markBackground(r) }) { Text("Background — answers none") }
            } else if (tags.isEmpty()) {
                Text("Marked as background.", style = MaterialTheme.typography.labelMedium,
                     color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
        OutlinedTextField(note, { note = it }, label = { Text("Lead's note (goes home with it)") },
                          modifier = Modifier.fillMaxWidth(), minLines = 2)
        if (note.trim() != r.leadNote.orEmpty()) {
            TextButton(onClick = { vm.saveNote(r, note) }) { Text("Save note") }
        }
    }
}

/** The form's fields under their own labels, in the form's order; anything
 *  the template does not know is shown under its key, never dropped. */
@Composable
private fun FieldList(r: RelaySubmissionRow) {
    val values = remember(r.fields) { runCatching { JSONObject(r.fields) }.getOrDefault(JSONObject()) }
    val template = r.template?.let { Templates.byKey(it) }
    val known = template?.fields.orEmpty()
    val rows = buildList {
        known.forEach { f -> show(values.opt(f.key))?.let { add(f.label to it) } }
        values.keys().forEach { k -> if (known.none { it.key == k }) show(values.opt(k))?.let { add(k to it) } }
    }
    if (rows.isEmpty()) return
    Column(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp))
            .background(MaterialTheme.colorScheme.surface).padding(14.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        rows.forEach { (label, value) ->
            Column {
                Text(label, style = MaterialTheme.typography.labelMedium,
                     color = MaterialTheme.colorScheme.onSurfaceVariant)
                Text(value, style = MaterialTheme.typography.bodyLarge)
            }
        }
    }
}

private fun show(v: Any?): String? = when (v) {
    null, JSONObject.NULL -> null
    is Boolean -> if (v) "Yes" else null
    is JSONArray -> (0 until v.length()).joinToString(", ") { v.optString(it) }.takeIf { it.isNotBlank() }
    else -> v.toString().takeIf { it.isNotBlank() }
}

private fun RelayFileRow.asAttachment() = AttachmentRow(
    id = "relay-$id", reportId = "relay-$submissionId",
    kind = when {
        mimeType.startsWith("image/") -> "image"
        mimeType.startsWith("video/") -> "video"
        mimeType.startsWith("audio/") -> "audio"
        else -> "image"
    },
    filename = filename, mimeType = mimeType, path = path,
    sizeBytes = sizeBytes, durationMs = durationMs,
)

// ------------------------------------------------------------ priorities

/**
 * What the team is here to find out, and how well the reports are
 * answering it. A priority with nothing new in a day is flagged, so the gap
 * shows before tomorrow's tasking rather than at the debrief.
 */
@Composable
fun RelayPrioritiesScreen(vm: RelayViewModel, padding: PaddingValues) {
    val priorities by vm.priorities.collectAsStateWithLifecycle()
    val inbox by vm.inbox.collectAsStateWithLifecycle()
    var editing by remember { mutableStateOf<org.humint.field.data.RelayPriorityRow?>(null) }
    var adding by remember { mutableStateOf(false) }
    val now = System.currentTimeMillis()

    Page(padding) {
        LazyColumn(
            contentPadding = PaddingValues(start = 16.dp, end = 16.dp, bottom = 32.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            item {
                Row(Modifier.padding(top = 18.dp, bottom = 4.dp).fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text("Priorities", style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold)
                        Text("What the team is here to find out.",
                             style = MaterialTheme.typography.bodyMedium,
                             color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    Button(onClick = { adding = true }, modifier = Modifier.heightIn(min = TapTarget)) { Text("Add") }
                }
            }
            if (priorities.isEmpty()) {
                item {
                    Text("Write the team's priorities before the event — one line each, ranked. " +
                         "Reports coming in are then tagged against them, and this screen shows which " +
                         "ones the team is answering.",
                         style = MaterialTheme.typography.bodyMedium,
                         color = MaterialTheme.colorScheme.onSurfaceVariant,
                         modifier = Modifier.padding(vertical = 24.dp))
                }
            }
            items(priorities, key = { it.id }) { p ->
                val tagged = inbox.filter { p.id in RelayViewModel.tagsOf(it) }
                val last = tagged.maxOfOrNull { it.receivedAt }
                val quiet = p.status in listOf("Open", "Partly answered") && (last == null || now - last > 24 * 3600_000L) &&
                    inbox.isNotEmpty()
                Column(
                    Modifier.fillMaxWidth().clip(RoundedCornerShape(20.dp))
                        .background(if (quiet) FieldAmber.copy(alpha = 0.10f) else MaterialTheme.colorScheme.surface)
                        .clickable { editing = p }.padding(14.dp),
                    verticalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("P${p.rank}", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold,
                             color = MaterialTheme.colorScheme.primary)
                        Spacer(Modifier.width(10.dp))
                        Text(p.statement, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold,
                             modifier = Modifier.weight(1f))
                        StatusTag(p.status)
                    }
                    p.answers?.let {
                        Text(it, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    Text(
                        buildString {
                            append(if (tagged.isEmpty()) "No reports yet" else "${tagged.size} report${if (tagged.size == 1) "" else "s"}")
                            last?.let { append(" · last ").append(clock(it)) }
                            if (quiet) append(" · nothing new in 24 h")
                        },
                        style = MaterialTheme.typography.labelMedium,
                        color = if (quiet) FieldAmber else MaterialTheme.colorScheme.onSurfaceVariant,
                        fontWeight = if (quiet) FontWeight.SemiBold else FontWeight.Normal,
                    )
                }
            }
        }
    }
    if (adding) {
        PriorityDialog(null, nextRank = (priorities.maxOfOrNull { it.rank } ?: 0) + 1,
                       onSave = { vm.savePriority(it); adding = false }, onDelete = {}, onDismiss = { adding = false })
    }
    editing?.let { p ->
        PriorityDialog(p, nextRank = p.rank, onSave = { vm.savePriority(it); editing = null },
                       onDelete = { vm.deletePriority(p.id); editing = null }, onDismiss = { editing = null })
    }
}

@Composable
private fun StatusTag(status: String) {
    val colour = when (status) {
        "Answered" -> MaterialTheme.colorScheme.primary
        "Partly answered" -> FieldAmber
        "Dropped" -> MaterialTheme.colorScheme.onSurfaceVariant
        else -> MaterialTheme.colorScheme.onSurface
    }
    Text(status, style = MaterialTheme.typography.labelMedium, color = colour, fontWeight = FontWeight.SemiBold,
         modifier = Modifier.clip(CircleShape).background(colour.copy(alpha = 0.12f))
             .padding(horizontal = 9.dp, vertical = 3.dp))
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun PriorityDialog(
    row: org.humint.field.data.RelayPriorityRow?, nextRank: Int,
    onSave: (org.humint.field.data.RelayPriorityRow) -> Unit, onDelete: () -> Unit, onDismiss: () -> Unit,
) {
    var statement by remember { mutableStateOf(row?.statement.orEmpty()) }
    var answers by remember { mutableStateOf(row?.answers.orEmpty()) }
    var rank by remember { mutableStateOf((row?.rank ?: nextRank).toString()) }
    var status by remember { mutableStateOf(row?.status ?: "Open") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(if (row == null) "New priority" else "Priority ${row.rank}") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                OutlinedTextField(statement, { statement = it }, label = { Text("What the team needs to find out") },
                                  modifier = Modifier.fillMaxWidth(), minLines = 2)
                OutlinedTextField(answers, { answers = it }, label = { Text("What would answer it (names, places, words)") },
                                  modifier = Modifier.fillMaxWidth(), minLines = 2)
                OutlinedTextField(rank, { v -> rank = v.filter { it.isDigit() }.take(2) }, label = { Text("Rank") },
                                  singleLine = true,
                                  keyboardOptions = androidx.compose.foundation.text.KeyboardOptions(
                                      keyboardType = androidx.compose.ui.text.input.KeyboardType.Number))
                if (row != null) {
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        listOf("Open", "Partly answered", "Answered", "Dropped").forEach { st ->
                            androidx.compose.material3.FilterChip(selected = status == st, onClick = { status = st },
                                                                  label = { Text(st) })
                        }
                    }
                    TextButton(onClick = onDelete) { Text("Delete this priority", color = MaterialTheme.colorScheme.error) }
                }
            }
        },
        confirmButton = {
            TextButton(enabled = statement.isNotBlank(), onClick = {
                onSave((row ?: org.humint.field.data.RelayPriorityRow(rank = 0, statement = "")).copy(
                    rank = rank.toIntOrNull() ?: nextRank, statement = statement.trim(),
                    answers = answers.trim().ifBlank { null }, status = status))
            }) { Text("Save") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

// ---------------------------------------------------------------- phones

@Composable
fun RelayPhonesScreen(vm: RelayViewModel, padding: PaddingValues) {
    val devices by vm.devices.collectAsStateWithLifecycle()
    val bundle by vm.bundle.collectAsStateWithLifecycle()
    val scope = rememberCoroutineScope()
    var adding by remember { mutableStateOf(false) }
    var code by remember { mutableStateOf<RelayViewModel.Code?>(null) }
    var revoking by remember { mutableStateOf<RelayDeviceRow?>(null) }

    Page(padding) {
        LazyColumn(
            contentPadding = PaddingValues(start = 16.dp, end = 16.dp, bottom = 32.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            item {
                Row(Modifier.padding(top = 18.dp, bottom = 4.dp).fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text("Phones", style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold)
                        Text("Each phone scans its own code to send here.",
                             style = MaterialTheme.typography.bodyMedium,
                             color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    Button(onClick = { adding = true }, modifier = Modifier.heightIn(min = TapTarget)) {
                        Text("Add a phone")
                    }
                }
            }
            items(devices, key = { it.id }) { d ->
                Row(
                    Modifier.fillMaxWidth().clip(RoundedCornerShape(20.dp))
                        .background(MaterialTheme.colorScheme.surface).padding(14.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(Modifier.weight(1f)) {
                        Text(d.analyst, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                        Text(if (d.revoked) "${d.label} · revoked" else d.label,
                             style = MaterialTheme.typography.labelMedium,
                             color = if (d.revoked) MaterialTheme.colorScheme.error
                                     else MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    if (!d.revoked) {
                        OutlinedButton(onClick = { scope.launch { code = vm.reissue(d) } },
                                       modifier = Modifier.heightIn(min = 48.dp)) { Text("Show code") }
                        TextButton(onClick = { revoking = d }) {
                            Text("Revoke", color = MaterialTheme.colorScheme.error)
                        }
                    }
                }
            }
        }
    }

    if (adding) {
        AddPhoneDialog(
            roster = bundle?.roster.orEmpty(),
            onAdd = { label, analyst, userId ->
                adding = false
                scope.launch { code = vm.addPhone(label, analyst, userId) }
            },
            onDismiss = { adding = false },
        )
    }
    code?.let { CodeDialog(it, onDismiss = { code = null }) }
    revoking?.let { d ->
        AlertDialog(
            onDismissRequest = { revoking = null },
            title = { Text("Revoke ${d.analyst}'s phone?") },
            text = { Text("It can no longer send to this relay. What it already sent stays.") },
            confirmButton = {
                TextButton(onClick = { vm.revoke(d); revoking = null }) {
                    Text("Revoke", color = MaterialTheme.colorScheme.error)
                }
            },
            dismissButton = { TextButton(onClick = { revoking = null }) { Text("Keep it") } },
        )
    }
}

/** Whose phone. With a provisioned roster, the analyst is picked from the
 *  team — which is what lets the console credit their reports to them. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun AddPhoneDialog(roster: List<org.humint.field.relay.RelayLink.Member>,
                           onAdd: (String, String, Int?) -> Unit, onDismiss: () -> Unit) {
    var analyst by remember { mutableStateOf("") }
    var userId by remember { mutableStateOf<Int?>(null) }
    var label by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Add a phone") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                if (roster.isNotEmpty()) {
                    Text("Whose phone", style = MaterialTheme.typography.labelLarge)
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        roster.forEach { m ->
                            androidx.compose.material3.FilterChip(
                                selected = userId == m.id,
                                onClick = { userId = m.id; analyst = m.name },
                                label = { Text(m.name) },
                            )
                        }
                    }
                } else {
                    OutlinedTextField(analyst, { analyst = it; userId = null },
                                      label = { Text("Analyst") }, singleLine = true)
                }
                OutlinedTextField(label, { label = it }, label = { Text("Phone (e.g. Sonim 3)") }, singleLine = true)
            }
        },
        confirmButton = {
            TextButton(enabled = analyst.isNotBlank(),
                       onClick = { onAdd(label.ifBlank { "${analyst.trim()}'s phone" }, analyst, userId) }) {
                Text("Add and show code")
            }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

/** The phone's code. A new token each time it is shown: only the hash is
 *  kept, so the old code stops working, exactly as on the console. */
@Composable
private fun CodeDialog(code: RelayViewModel.Code, onDismiss: () -> Unit) {
    val addresses = remember { Relay.addresses() }
    var pick by remember { mutableStateOf(addresses.firstOrNull()) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("${code.analyst} · ${code.label}") },
        text = {
            Column(horizontalAlignment = Alignment.CenterHorizontally,
                   verticalArrangement = Arrangement.spacedBy(10.dp)) {
                val a = pick
                if (a == null) {
                    Text("This tablet has no network address. Turn on its hotspot, then show the code again.",
                         color = MaterialTheme.colorScheme.error)
                } else {
                    val payload = Relay.enrollmentPayload(a, code.token, code.label, code.analyst)
                    val bitmap = remember(payload) { qrBitmap(payload) }
                    Box(Modifier.clip(RoundedCornerShape(12.dp)).background(Color.White).padding(12.dp)) {
                        Image(bitmap, contentDescription = "Code for ${code.analyst}'s phone",
                              filterQuality = FilterQuality.None, modifier = Modifier.size(260.dp))
                    }
                    Text("On the phone: Send → Scan the console's code.",
                         style = MaterialTheme.typography.bodyMedium)
                    Text(a.url, style = MaterialTheme.typography.labelMedium.merge(MonoStyle),
                         color = MaterialTheme.colorScheme.onSurfaceVariant)
                    if (addresses.size > 1) {
                        FlowRow2 {
                            addresses.forEach { x ->
                                TextButton(onClick = { pick = x }) {
                                    Text(if (x == pick) "● ${x.iface}" else x.iface)
                                }
                            }
                        }
                    }
                }
            }
        },
        confirmButton = { TextButton(onClick = onDismiss) { Text("Done") } },
    )
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun FlowRow2(content: @Composable () -> Unit) {
    FlowRow(horizontalArrangement = Arrangement.spacedBy(4.dp)) { content() }
}

/** A QR code as a crisp bitmap: one pixel per module, scaled up with no
 *  smoothing, so a phone held up to a tablet screen reads it first time. */
private fun qrBitmap(text: String): ImageBitmap {
    val hints = mapOf(com.google.zxing.EncodeHintType.MARGIN to 4,
                      com.google.zxing.EncodeHintType.ERROR_CORRECTION to
                          com.google.zxing.qrcode.decoder.ErrorCorrectionLevel.M)
    val m = com.google.zxing.qrcode.QRCodeWriter()
        .encode(text, com.google.zxing.BarcodeFormat.QR_CODE, 0, 0, hints)
    val bmp = android.graphics.Bitmap.createBitmap(m.width, m.height, android.graphics.Bitmap.Config.ARGB_8888)
    for (y in 0 until m.height) for (x in 0 until m.width) {
        bmp.setPixel(x, y, if (m[x, y]) android.graphics.Color.BLACK else android.graphics.Color.WHITE)
    }
    return bmp.asImageBitmap()
}

// ---------------------------------------------------------------- backup

/** An encrypted copy of everything on the relay, to a USB stick. For the
 *  night the tablet might not make it home. */
@Composable
private fun BackupCard(vm: RelayViewModel) {
    val state by vm.backup.collectAsStateWithLifecycle()
    val bundle by vm.bundle.collectAsStateWithLifecycle()
    var asking by remember { mutableStateOf(false) }
    var pin by remember { mutableStateOf<CharArray?>(null) }
    val pick = androidx.activity.compose.rememberLauncherForActivityResult(
        androidx.activity.result.contract.ActivityResultContracts.CreateDocument("application/octet-stream"),
    ) { uri ->
        val p = pin; pin = null
        if (uri != null && p != null) vm.backup(uri, p) else p?.let { java.util.Arrays.fill(it, '\u0000') }
    }

    Column(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(20.dp))
            .background(MaterialTheme.colorScheme.surface).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Text("Back up to USB", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold)
        Text(
            if (bundle != null) "Everything on the relay, encrypted. It opens with a team PIN, or at the " +
                "console with no PIN — so the reports survive the tablet."
            else "Everything on the relay, encrypted under a team PIN. Provision the relay first and the " +
                "console can open its backups too.",
            style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        when (val b = state) {
            null -> OutlinedButton(onClick = { asking = true }, modifier = Modifier.heightIn(min = TapTarget)) {
                Text("Back up now")
            }
            is RelayViewModel.Backup.Writing -> Text("Writing the backup…")
            is RelayViewModel.Backup.Done -> {
                Text("Backed up ${b.reports} report${if (b.reports == 1) "" else "s"} and ${b.files} file${if (b.files == 1) "" else "s"}." +
                     if (b.consoleCanOpen) " The console can open it." else "",
                     style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                Text("Keep the stick apart from the tablet, or there is no point.",
                     style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                TextButton(onClick = { vm.dismissBackup() }) { Text("Done") }
            }
            is RelayViewModel.Backup.Failed -> {
                Text(b.message, color = MaterialTheme.colorScheme.error)
                TextButton(onClick = { vm.dismissBackup() }) { Text("OK") }
            }
        }
    }

    if (asking) {
        var typed by remember { mutableStateOf("") }
        var wrong by remember { mutableStateOf(false) }
        AlertDialog(
            onDismissRequest = { asking = false },
            title = { Text("Back up to USB") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text("Type a team PIN. The backup opens with that PIN on a relay. Next, choose the USB drive.")
                    PinField(typed, { typed = it; wrong = false }, "Team PIN")
                    if (wrong) Text("That is not a team PIN.", color = MaterialTheme.colorScheme.error)
                }
            },
            confirmButton = {
                TextButton(onClick = {
                    val chars = typed.toCharArray()
                    if (!vm.checkPin(chars)) { wrong = true; return@TextButton }
                    pin = chars; asking = false
                    val day = java.text.SimpleDateFormat("yyyyMMdd-HHmm", Locale.US).format(Date())
                    pick.launch("humint-relay-$day.hrb")
                }) { Text("Choose where to save") }
            },
            dismissButton = { TextButton(onClick = { asking = false }) { Text("Cancel") } },
        )
    }
}

// ------------------------------------------------------------- team PINs

/**
 * A relay belongs to a team, not one person: the lead's PIN, a second team
 * member's, and a duress PIN that erases the relay and opens it empty.
 * Every change here asks for the lead's PIN, so a borrowed, unlocked tablet
 * cannot be given a PIN its team does not know about.
 */
@Composable
private fun TeamPinsCard() {
    val context = LocalContext.current
    var tick by remember { mutableStateOf(0) }
    val second = remember(tick) { org.humint.field.data.Vault.hasSecondPin(context) }
    val duress = remember(tick) { org.humint.field.data.Vault.hasDuressPin(context) }
    var editing by remember { mutableStateOf<String?>(null) }

    Column(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(20.dp))
            .background(MaterialTheme.colorScheme.surface).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Text("Team PINs", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold)
        PinRow("Lead's PIN", "Set. Change it in Settings.", null, null)
        PinRow("Second team member", if (second) "Set — opens the same relay and can Sync." else "Not set.",
               if (second) "Remove" else "Set", if (second) "remove-second" else "second") { editing = it }
        PinRow("Duress PIN", if (duress) "Set. Typed at the lock screen, it erases this relay and opens it empty."
                             else "Not set.",
               if (duress) "Remove" else "Set", if (duress) "remove-duress" else "duress") { editing = it }
        if (!second || !duress) {
            Text("Set both before the team deploys.", style = MaterialTheme.typography.labelMedium, color = FieldAmber)
        }
    }

    editing?.let { what ->
        PinDialog(what, onDone = { editing = null; tick++ })
    }
}

@Composable
private fun PinRow(title: String, line: String, action: String?, key: String?, onAction: (String) -> Unit = {}) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.bodyLarge, fontWeight = FontWeight.Medium)
            Text(line, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        if (action != null && key != null) {
            TextButton(onClick = { onAction(key) }) { Text(action) }
        }
    }
}

@Composable
private fun PinDialog(what: String, onDone: () -> Unit) {
    val context = LocalContext.current
    val removing = what.startsWith("remove")
    var lead by remember { mutableStateOf("") }
    var new1 by remember { mutableStateOf("") }
    var new2 by remember { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }
    val min = org.humint.field.data.Vault.MIN_PIN_LENGTH
    val max = org.humint.field.data.Vault.MAX_PIN_LENGTH
    val title = when (what) {
        "second" -> "Second team member's PIN"
        "duress" -> "Duress PIN"
        "remove-second" -> "Remove the second PIN"
        else -> "Remove the duress PIN"
    }
    AlertDialog(
        onDismissRequest = onDone,
        title = { Text(title) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                if (what == "duress") {
                    Text("Typed at the lock screen, this erases every report, photo, phone and key on " +
                         "this relay, then opens it empty under the same PIN. It cannot be undone. Pick " +
                         "something no one will type by accident — not a near-miss of a real PIN.",
                         style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.error)
                }
                PinField(lead, { lead = it }, "Lead's PIN")
                if (!removing) {
                    PinField(new1, { new1 = it }, "New PIN ($min–$max digits)")
                    PinField(new2, { new2 = it }, "Same again")
                }
                error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            }
        },
        confirmButton = {
            TextButton(onClick = {
                if (!removing && (new1.length !in min..max || new1 != new2)) {
                    error = if (new1 != new2) "The two new PINs differ." else "Use $min to $max digits."
                    return@TextButton
                }
                val r = when (what) {
                    "second" -> org.humint.field.data.Vault.setSecondPin(context, lead.toCharArray(), new1.toCharArray())
                    "duress" -> org.humint.field.data.Vault.setDuressPin(context, lead.toCharArray(), new1.toCharArray())
                    "remove-second" -> org.humint.field.data.Vault.removeSecondPin(context, lead.toCharArray())
                    else -> org.humint.field.data.Vault.removeDuressPin(context, lead.toCharArray())
                }
                when (r) {
                    is org.humint.field.data.Vault.PinResult.Ok -> onDone()
                    is org.humint.field.data.Vault.PinResult.Refused -> error = r.why
                }
            }) { Text(if (removing) "Remove" else "Set") }
        },
        dismissButton = { TextButton(onClick = onDone) { Text("Cancel") } },
    )
}

@Composable
private fun PinField(value: String, onChange: (String) -> Unit, label: String) {
    OutlinedTextField(
        value, { v -> onChange(v.filter { it.isDigit() }.take(org.humint.field.data.Vault.MAX_PIN_LENGTH)) },
        label = { Text(label) }, singleLine = true,
        visualTransformation = androidx.compose.ui.text.input.PasswordVisualTransformation(),
        keyboardOptions = androidx.compose.foundation.text.KeyboardOptions(
            keyboardType = androidx.compose.ui.text.input.KeyboardType.NumberPassword),
    )
}

// ------------------------------------------------------------------ sync

/**
 * Sending home, and the key's clock. The countdown is the thing the lead
 * most needs to see on this screen: past it, the console has dropped this
 * relay's key and Sync stops working until the tablet is re-provisioned.
 */
@Composable
private fun SyncCard(
    bundle: org.humint.field.relay.RelayLink.Bundle?,
    sync: org.humint.field.relay.RelayLink.Progress?,
    unsent: Int, videoLater: Boolean,
    onVideoLater: (Boolean) -> Unit, onSync: () -> Unit, onDismiss: () -> Unit,
    onProvision: () -> Unit,
) {
    Column(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(20.dp))
            .background(MaterialTheme.colorScheme.surface).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Text("Send home", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold)
        if (bundle == null) {
            Text("This relay has not been provisioned. At the office, on the console: " +
                 "Admin → Field devices → Team relays → Register a relay, then scan its code here.",
                 style = MaterialTheme.typography.bodyMedium)
            Button(onClick = onProvision, modifier = Modifier.heightIn(min = TapTarget)) {
                Text("Provision from the console")
            }
            return@Column
        }
        val expires = bundle.expiresAt
        val left = expires?.let { it - System.currentTimeMillis() }
        Text(bundle.label, style = MaterialTheme.typography.titleMedium)
        Text(
            when {
                left == null -> "Keep-alive ${bundle.keepaliveDays} days."
                left <= 0 -> "The key has expired. The console no longer accepts this relay: " +
                    "re-provision it at the office. Nothing on the tablet has been lost."
                left < 24 * 3600_000L -> "Check in within ${left / 3600_000L} h, or the console drops this relay's key."
                else -> "Check in within ${left / (24 * 3600_000L)} days, or the console drops this relay's key."
            },
            style = MaterialTheme.typography.bodyMedium,
            color = if (left != null && left < 24 * 3600_000L) FieldAmber else MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Text("Console fingerprint ${bundle.fingerprint}",
             style = MaterialTheme.typography.labelMedium.merge(MonoStyle),
             color = MaterialTheme.colorScheme.onSurfaceVariant)

        when (val p = sync) {
            null -> {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    androidx.compose.material3.Checkbox(checked = videoLater, onCheckedChange = onVideoLater)
                    Text("Reports and photos now, video later", style = MaterialTheme.typography.bodyMedium)
                }
                Button(onClick = onSync, modifier = Modifier.heightIn(min = TapTarget)) {
                    Text(if (unsent == 0) "Sync (check in)" else "Sync $unsent report${if (unsent == 1) "" else "s"}")
                }
                Text("Needs the VPN, or the office network. Each report is erased from this tablet " +
                     "once the console has confirmed it.",
                     style = MaterialTheme.typography.labelMedium,
                     color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            is org.humint.field.relay.RelayLink.Progress.Finding ->
                Text("Looking for the console at ${p.address}…", style = MaterialTheme.typography.bodyMedium)
            is org.humint.field.relay.RelayLink.Progress.Sending ->
                Text("Sending ${p.index} of ${p.total}: ${p.title}", style = MaterialTheme.typography.bodyMedium)
            is org.humint.field.relay.RelayLink.Progress.SendingFile ->
                Text("Sending ${p.name}…", style = MaterialTheme.typography.bodyMedium)
            is org.humint.field.relay.RelayLink.Progress.Done -> {
                Text(
                    buildString {
                        append(if (p.sent == 0) "Checked in." else "Sent ${p.sent} home and erased them from this tablet.")
                        if (p.heldBack > 0) append(" ${p.heldBack} held back until their video goes.")
                    },
                    style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold,
                )
                TextButton(onClick = onDismiss) { Text("Done") }
            }
            is org.humint.field.relay.RelayLink.Progress.Failed -> {
                Text(p.message, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodyMedium)
                TextButton(onClick = onDismiss) { Text("OK") }
            }
        }
        if (left != null && left <= 0) {
            OutlinedButton(onClick = onProvision, modifier = Modifier.heightIn(min = TapTarget)) {
                Text("Re-provision from the console")
            }
        }
    }
}

// ------------------------------------------------------------ relay status

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun RelayHomeScreen(vm: RelayViewModel, padding: PaddingValues, onProvision: () -> Unit) {
    val context = LocalContext.current
    val state by vm.state.collectAsStateWithLifecycle()
    val bundle by vm.bundle.collectAsStateWithLifecycle()
    val sync by vm.sync.collectAsStateWithLifecycle()
    val inbox by vm.inbox.collectAsStateWithLifecycle()
    var videoLater by remember { mutableStateOf(false) }
    val waiting by vm.waiting.collectAsStateWithLifecycle()
    val devices by vm.devices.collectAsStateWithLifecycle()
    var problem by remember { mutableStateOf<String?>(null) }
    var addresses by remember { mutableStateOf(Relay.addresses()) }
    var battery by remember { mutableStateOf<String?>(null) }
    LifecycleResumeEffect(Unit) {
        addresses = Relay.addresses()
        battery = runCatching { batteryWarning(context) }.getOrNull()
        onPauseOrDispose { }
    }

    Page(padding) {
        Column(
            Modifier.verticalScroll(rememberScrollState()).padding(horizontal = 16.dp).padding(bottom = 32.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Text("Relay", style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold,
                 modifier = Modifier.padding(top = 18.dp))

            Column(
                Modifier.fillMaxWidth().clip(RoundedCornerShape(20.dp))
                    .background(if (state.running) MaterialTheme.colorScheme.primary.copy(alpha = 0.12f)
                                else MaterialTheme.colorScheme.surface)
                    .padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Box(Modifier.size(12.dp).clip(CircleShape)
                        .background(if (state.running) MaterialTheme.colorScheme.primary
                                    else MaterialTheme.colorScheme.onSurfaceVariant))
                    Spacer(Modifier.width(10.dp))
                    Text(if (state.running) "On — taking reports" else "Off",
                         style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold)
                }
                Text(
                    if (state.running)
                        "${state.received} received since it started" +
                            (if (state.lastReceivedAt > 0) " · last at ${clock(state.lastReceivedAt)}" else "") +
                            ". It keeps running with the screen off and the app locked."
                    else "Turn it on when the team is ready to send.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                if (state.running) {
                    Button(onClick = { Relay.stop(context) },
                           colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error),
                           modifier = Modifier.heightIn(min = TapTarget)) { Text("Turn off") }
                } else {
                    Button(onClick = { problem = Relay.start(context) },
                           modifier = Modifier.heightIn(min = TapTarget)) { Text("Turn on") }
                }
                (problem ?: state.problem)?.let {
                    Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodyMedium)
                }
            }

            if (waiting > 0) {
                Banner("$waiting waiting to be opened",
                       "Arrived while the relay was locked. They open as soon as it is unlocked.", FieldAmber)
            }

            TeamPinsCard()

            BackupCard(vm)

            SyncCard(bundle, sync, inbox.count { it.forwardedAt == null }, videoLater,
                     onVideoLater = { videoLater = it },
                     onSync = { vm.sync(videoLater) }, onDismiss = { vm.dismissSync() },
                     onProvision = onProvision)

            Text("Where phones send", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            if (addresses.isEmpty()) {
                Text("No network yet. Turn on this tablet's hotspot (Settings → Connections → Mobile Hotspot), " +
                     "then come back here.",
                     style = MaterialTheme.typography.bodyMedium, color = FieldAmber)
            } else {
                addresses.forEach { a ->
                    Text("${a.url}   (${a.iface})", style = MaterialTheme.typography.bodyMedium.merge(MonoStyle))
                }
                Text("Phones join this tablet's hotspot — not hotel Wi-Fi, which usually stops " +
                     "devices reaching each other.",
                     style = MaterialTheme.typography.labelMedium,
                     color = MaterialTheme.colorScheme.onSurfaceVariant)
            }

            Text("Team", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            Text("${devices.count { !it.revoked }} phone(s) can send here. Add them on the Phones tab.",
                 style = MaterialTheme.typography.bodyMedium)

            battery?.let { why ->
                Text(why, style = MaterialTheme.typography.bodyMedium, color = FieldAmber)
                OutlinedButton(
                    onClick = {
                        val intent = if (why.startsWith("Battery Saver")) Intent(AndroidSettings.ACTION_BATTERY_SAVER_SETTINGS)
                            else Intent(AndroidSettings.ACTION_APPLICATION_DETAILS_SETTINGS,
                                        Uri.fromParts("package", context.packageName, null))
                        runCatching { context.startActivity(intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
                    },
                    modifier = Modifier.heightIn(min = TapTarget),
                ) { Text("Open battery settings") }
            }
        }
    }
}
