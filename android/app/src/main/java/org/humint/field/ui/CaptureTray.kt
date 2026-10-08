package org.humint.field.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.launch
import org.humint.field.FieldViewModel
import org.humint.field.data.AttachmentRow
import org.humint.field.data.ReportRow
import org.humint.field.data.Templates

/**
 * Captures taken before any report existed.
 *
 * The camera button exists because field work happens in the other order
 * from the forms: the van is in front of you *now*, and the report can be
 * written at the rally point. So a quick capture lands here, on the Reports
 * tab, until it is filed to a report — new or existing — or discarded.
 *
 * Deliberately a tray and not a gallery: nothing here can be sent. The
 * uploader only ever reads attachments by report, so the only way out of
 * this tray is into a report (or the bin), and the tray says so.
 */
@Composable
fun UnfiledTray(
    vm: FieldViewModel,
    unfiled: List<AttachmentRow>,
    drafts: List<ReportRow>,
    onOpenReport: (String) -> Unit,
) {
    var picked by remember { mutableStateOf<AttachmentRow?>(null) }

    Column(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(20.dp))
            .background(FieldAmber.copy(alpha = 0.10f))
            .padding(14.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Unfiled captures", style = MaterialTheme.typography.titleMedium,
                 fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
            Text("${unfiled.size}", style = MaterialTheme.typography.titleMedium,
                 fontWeight = FontWeight.SemiBold, color = FieldAmber)
        }
        Text(
            "Tap one to file it to a report. Nothing is sent from here.",
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.height(10.dp))
        LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            items(unfiled, key = { it.id }) { a ->
                when (a.kind) {
                    "image" -> AttachmentThumb(a, onOpen = { picked = a }, size = 76)
                    else -> MediaThumb(a, onOpen = { picked = a }, size = 76)
                }
            }
        }
    }

    picked?.let { capture ->
        FileCaptureSheet(
            vm = vm, capture = capture, drafts = drafts,
            onOpenReport = { id -> picked = null; onOpenReport(id) },
            onDismiss = { picked = null },
        )
    }
}

/** Everything that can happen to one unfiled capture: check it, file it to
 *  a draft, start a new report from it, or discard it. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun FileCaptureSheet(
    vm: FieldViewModel,
    capture: AttachmentRow,
    drafts: List<ReportRow>,
    onOpenReport: (String) -> Unit,
    onDismiss: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    var checking by remember { mutableStateOf(false) }
    var pickingTemplate by remember { mutableStateOf(false) }
    var confirmDiscard by remember { mutableStateOf(false) }
    val sheet = rememberModalBottomSheetState(skipPartiallyExpanded = true)

    if (checking) {
        if (capture.kind == "image") FullImage(capture, onClose = { checking = false })
        else FullMedia(capture, onClose = { checking = false })
    }

    if (pickingTemplate) {
        TemplatePickerSheet(
            templates = Templates.all,
            onPick = { t ->
                scope.launch {
                    val id = vm.newReportFrom(t.key, capture.id)
                    pickingTemplate = false
                    onOpenReport(id)
                }
            },
            onDismiss = { pickingTemplate = false },
        )
    }

    if (confirmDiscard) {
        AlertDialog(
            onDismissRequest = { confirmDiscard = false },
            title = { Text("Discard this capture?") },
            text = { Text("It is deleted from this phone. It was never sent anywhere.") },
            confirmButton = {
                TextButton(onClick = {
                    vm.removeAttachment(capture); confirmDiscard = false; onDismiss()
                }) { Text("Discard", color = MaterialTheme.colorScheme.error) }
            },
            dismissButton = { TextButton(onClick = { confirmDiscard = false }) { Text("Keep it") } },
        )
    }

    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = sheet,
                     containerColor = MaterialTheme.colorScheme.surface) {
        Column(Modifier.padding(horizontal = 18.dp).padding(bottom = 28.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                when (capture.kind) {
                    "image" -> AttachmentThumb(capture, onOpen = { checking = true }, size = 64)
                    else -> MediaThumb(capture, onOpen = { checking = true }, size = 64)
                }
                Column(Modifier.weight(1f).padding(horizontal = 12.dp)) {
                    Text(capture.filename, style = MaterialTheme.typography.titleSmall,
                         fontWeight = FontWeight.SemiBold, maxLines = 1,
                         overflow = TextOverflow.Ellipsis)
                    Text(
                        buildString {
                            capture.durationMs?.let { append("${it / 1000}s · ") }
                            append("${capture.sizeBytes / 1024} KB · not filed to a report")
                        },
                        style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                TextButton(onClick = { checking = true }) { Text("Check it") }
            }

            Spacer(Modifier.height(14.dp))
            Text("File it to", style = MaterialTheme.typography.labelLarge,
                 color = MaterialTheme.colorScheme.onSurfaceVariant)
            Spacer(Modifier.height(8.dp))

            // The newest few drafts: the report it belongs to was almost
            // certainly started this outing, not last week's.
            drafts.take(5).forEach { row ->
                Row(
                    Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(14.dp))
                        .clickable {
                            vm.fileCapture(capture.id, row.id)
                            onOpenReport(row.id)
                        }
                        .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f))
                        .padding(horizontal = 12.dp, vertical = 10.dp)
                        .heightIn(min = TapTarget),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    TemplateBadge(row.template, size = 36)
                    Text(
                        row.title, style = MaterialTheme.typography.bodyLarge,
                        maxLines = 1, overflow = TextOverflow.Ellipsis,
                        modifier = Modifier.weight(1f).padding(horizontal = 10.dp),
                    )
                    Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, contentDescription = null,
                         tint = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                Spacer(Modifier.height(6.dp))
            }

            OutlinedButton(
                onClick = { pickingTemplate = true },
                modifier = Modifier.fillMaxWidth().heightIn(min = 52.dp),
            ) { Text(if (drafts.isEmpty()) "Start a report with this" else "New report with this") }

            Spacer(Modifier.height(4.dp))
            TextButton(onClick = { confirmDiscard = true },
                       modifier = Modifier.align(Alignment.CenterHorizontally)) {
                Text("Discard it", color = MaterialTheme.colorScheme.error)
            }
        }
    }
}
