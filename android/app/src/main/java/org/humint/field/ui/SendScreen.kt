package org.humint.field.ui

import androidx.compose.foundation.background
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
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.QrCodeScanner
import androidx.compose.material.icons.outlined.CloudDone
import androidx.compose.material.icons.outlined.Shield
import androidx.compose.material3.Button
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import org.humint.field.FieldViewModel

/**
 * Sending, as a place of its own on the bar.
 *
 * What is going, what is not (drafts stay until they are finished), and the
 * one button that starts it. Sending begins with a scan because the phone
 * never holds the console's address — this screen says so, so the QR is
 * expected rather than a surprise.
 */
@Composable
fun SendScreen(vm: FieldViewModel, padding: PaddingValues, onScan: () -> Unit) {
    val queue by vm.queue.collectAsStateWithLifecycle()
    val ready = queue.filter { it.status == "ready" }
    val drafts = queue.count { it.status == "draft" }

    LazyColumn(
        Modifier.fillMaxSize().padding(padding),
        contentPadding = PaddingValues(start = 16.dp, end = 16.dp, bottom = 32.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item {
            Column(Modifier.padding(top = 18.dp, bottom = 6.dp)) {
                Text("Send", style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold)
                Text(
                    if (ready.isEmpty()) "Nothing ready yet"
                    else "${ready.size} report${if (ready.size == 1) "" else "s"} ready",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }

        if (ready.isEmpty()) {
            item {
                Column(Modifier.fillMaxWidth().padding(top = 56.dp),
                       horizontalAlignment = Alignment.CenterHorizontally) {
                    Box(Modifier.size(88.dp).clip(CircleShape)
                            .background(MaterialTheme.colorScheme.surfaceVariant),
                        contentAlignment = Alignment.Center) {
                        Icon(Icons.Outlined.CloudDone, contentDescription = null,
                             tint = MaterialTheme.colorScheme.onSurfaceVariant,
                             modifier = Modifier.size(40.dp))
                    }
                    Spacer(Modifier.height(18.dp))
                    Text("All caught up", style = MaterialTheme.typography.titleLarge,
                         fontWeight = FontWeight.SemiBold)
                    Spacer(Modifier.height(6.dp))
                    Text(
                        if (drafts > 0) "$drafts draft${if (drafts == 1) " is" else "s are"} still " +
                            "being written. Mark a report ready to send it."
                        else "Reports you mark ready will wait here until you send them.",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        textAlign = TextAlign.Center,
                    )
                }
            }
        } else {
            item {
                Button(
                    onClick = onScan,
                    shape = RoundedCornerShape(20.dp),
                    modifier = Modifier.fillMaxWidth().heightIn(min = 64.dp),
                ) {
                    Icon(Icons.Filled.QrCodeScanner, contentDescription = null)
                    Spacer(Modifier.width(10.dp))
                    Text("Scan the console's code", style = MaterialTheme.typography.titleMedium,
                         fontWeight = FontWeight.SemiBold)
                }
            }
            item {
                Row(
                    Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp))
                        .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f))
                        .padding(12.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Icon(Icons.Outlined.Shield, contentDescription = null,
                         tint = MaterialTheme.colorScheme.onSurfaceVariant)
                    Spacer(Modifier.width(10.dp))
                    Text(
                        "The console's address isn't kept on this phone. It comes from the code, " +
                        "is used for this send, and is forgotten when it finishes.",
                        style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            item {
                Text("Going", style = MaterialTheme.typography.labelLarge,
                     color = MaterialTheme.colorScheme.onSurfaceVariant,
                     modifier = Modifier.padding(top = 8.dp))
            }
            items(ready, key = { it.id }) { row ->
                Row(
                    Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp))
                        .background(MaterialTheme.colorScheme.surface).padding(12.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    TemplateBadge(row.template, 36)
                    Spacer(Modifier.width(12.dp))
                    Text(row.title, style = MaterialTheme.typography.bodyLarge,
                         maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
            }
            if (drafts > 0) {
                item {
                    Text("$drafts draft${if (drafts == 1) "" else "s"} will stay on the phone.",
                         style = MaterialTheme.typography.labelMedium,
                         color = MaterialTheme.colorScheme.onSurfaceVariant,
                         modifier = Modifier.padding(top = 4.dp))
                }
            }
        }
    }
}
