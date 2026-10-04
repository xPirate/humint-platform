package org.humint.field.ui

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.EditNote
import androidx.compose.material.icons.automirrored.filled.ViewList
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.CloudUpload
import androidx.compose.material.icons.filled.Description
import androidx.compose.material.icons.filled.DirectionsCar
import androidx.compose.material.icons.filled.Explore
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.Place
import androidx.compose.material.icons.filled.SettingsInputAntenna
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.outlined.CloudUpload
import androidx.compose.material.icons.outlined.Lock
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import org.humint.field.data.Template

/**
 * The app's frame: a bottom bar the way every app on the phone already has
 * one, with the thing you came to do — start a report — as the big button
 * in the middle.
 *
 * Before this, the queue screen carried every way out of itself as a stack
 * of full-width buttons and a text "Settings" in the corner. It worked, and
 * it looked like a form. A bottom bar is a layout the analyst's thumb
 * already knows, it keeps every destination one tap away from every other,
 * and it puts "new report" exactly where a thumb rests.
 *
 * Lock is on the bar because in this app it is a real action, not a
 * setting: someone walks up, one tap, and the queue is shut behind the PIN.
 */
enum class Tab { Reports, Send, Lock, Settings }

@Composable
fun MainShell(
    current: Tab,
    readyCount: Int,
    onTab: (Tab) -> Unit,
    onNew: () -> Unit,
    content: @Composable (PaddingValues) -> Unit,
) {
    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        bottomBar = { BottomBar(current, readyCount, onTab, onNew) },
        content = content,
    )
}

@Composable
private fun BottomBar(current: Tab, readyCount: Int, onTab: (Tab) -> Unit, onNew: () -> Unit) {
    // The raised button sits half above the bar. It is drawn outside the
    // Surface because a Surface clips to its shape, which would cut the
    // button's top half off.
    Box(Modifier.fillMaxWidth()) {
    Surface(
        color = MaterialTheme.colorScheme.surface,
        tonalElevation = 3.dp,
        shadowElevation = 12.dp,
    ) {
        Box(Modifier.fillMaxWidth().navigationBarsPadding()) {
            Row(
                Modifier.fillMaxWidth().height(68.dp).padding(horizontal = 6.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                BarItem(Tab.Reports, current, Icons.AutoMirrored.Filled.ViewList,
                        Icons.AutoMirrored.Filled.ViewList, "Reports", onTab)
                BarItem(Tab.Send, current, Icons.Filled.CloudUpload, Icons.Outlined.CloudUpload,
                        "Send", onTab, badge = readyCount)
                // The gap the centre button sits in.
                Spacer(Modifier.width(84.dp))
                BarItem(Tab.Lock, current, Icons.Filled.Lock, Icons.Outlined.Lock, "Lock", onTab)
                BarItem(Tab.Settings, current, Icons.Filled.Settings, Icons.Outlined.Settings,
                        "Settings", onTab)
            }
        }
    }
    NewReportButton(onNew, Modifier.align(Alignment.TopCenter).offset(y = (-18).dp))
    }
}

@Composable
private fun androidx.compose.foundation.layout.RowScope.BarItem(
    tab: Tab, current: Tab, selectedIcon: ImageVector, icon: ImageVector, label: String,
    onTab: (Tab) -> Unit, badge: Int = 0,
) {
    val selected = tab == current
    val tint = if (selected) MaterialTheme.colorScheme.primary
               else MaterialTheme.colorScheme.onSurfaceVariant
    Column(
        Modifier
            .weight(1f)
            .clip(RoundedCornerShape(16.dp))
            .clickable(role = Role.Tab) { onTab(tab) }
            .padding(vertical = 6.dp)
            .semantics {
                contentDescription = label + if (badge > 0) ", $badge ready" else ""
            },
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Box {
            Box(
                Modifier
                    .clip(CircleShape)
                    .background(if (selected) MaterialTheme.colorScheme.primary.copy(alpha = 0.14f)
                                else Color.Transparent)
                    .padding(horizontal = 16.dp, vertical = 4.dp),
            ) {
                Icon(if (selected) selectedIcon else icon, contentDescription = null, tint = tint)
            }
            if (badge > 0) {
                Box(
                    Modifier
                        .align(Alignment.TopEnd)
                        .offset(x = (-4).dp, y = (-2).dp)
                        .size(18.dp)
                        .clip(CircleShape)
                        .background(MaterialTheme.colorScheme.primary),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(if (badge > 9) "9+" else "$badge", fontSize = 10.sp, fontWeight = FontWeight.Bold,
                         color = MaterialTheme.colorScheme.onPrimary)
                }
            }
        }
        Spacer(Modifier.height(2.dp))
        Text(label, fontSize = 12.sp, color = tint,
             fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal)
    }
}

@Composable
private fun NewReportButton(onNew: () -> Unit, modifier: Modifier) {
    val source = remember { MutableInteractionSource() }
    Box(
        modifier
            .size(66.dp)
            .shadow(10.dp, CircleShape)
            .clip(CircleShape)
            .background(MaterialTheme.colorScheme.primary)
            .border(4.dp, MaterialTheme.colorScheme.surface, CircleShape)
            .clickable(interactionSource = source, indication = androidx.compose.material3.ripple(),
                       role = Role.Button, onClick = onNew)
            .semantics { contentDescription = "New report" },
        contentAlignment = Alignment.Center,
    ) {
        Icon(Icons.Filled.Add, contentDescription = null,
             tint = MaterialTheme.colorScheme.onPrimary, modifier = Modifier.size(32.dp))
    }
}

/** One icon per kind of report, used on the picker, the queue and the editor. */
fun templateIcon(key: String): ImageVector = when (key) {
    "sigint" -> Icons.Filled.SettingsInputAntenna
    "individual" -> Icons.Filled.Person
    "vehicle" -> Icons.Filled.DirectionsCar
    "salute" -> Icons.Filled.Visibility
    "df" -> Icons.Filled.Explore
    "place" -> Icons.Filled.Place
    "note" -> Icons.Filled.EditNote
    else -> Icons.Filled.Description
}

/** A tint per kind, so a queue of twenty reads at a glance. Muted enough to
 *  sit on the dark theme at night without glowing. */
@Composable
fun templateTint(key: String): Color = when (key) {
    "sigint" -> Color(0xFF6EA8FE)
    "individual" -> Color(0xFFE59AF2)
    "vehicle" -> Color(0xFFFFB020)
    "salute" -> Color(0xFFFF7A6B)
    "df" -> Color(0xFF5FD4C8)
    "place" -> Color(0xFF8BD17C)
    else -> MaterialTheme.colorScheme.onSurfaceVariant
}

@Composable
fun TemplateBadge(key: String, size: Int = 44) {
    val tint = templateTint(key)
    Box(
        Modifier.size(size.dp).clip(RoundedCornerShape((size * 0.32f).dp))
            .background(tint.copy(alpha = 0.16f)),
        contentAlignment = Alignment.Center,
    ) {
        Icon(templateIcon(key), contentDescription = null, tint = tint,
             modifier = Modifier.size((size * 0.52f).dp))
    }
}

/**
 * "What are you reporting?" as a grid of tiles rather than a list of text —
 * seven choices read faster as icons, and a tile is a bigger target.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun TemplatePickerSheet(templates: List<Template>, onPick: (Template) -> Unit, onDismiss: () -> Unit) {
    val sheet = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = sheet,
                     containerColor = MaterialTheme.colorScheme.surface) {
        Text("New report", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold,
             modifier = Modifier.padding(start = 22.dp, end = 22.dp))
        Text("What are you reporting?", style = MaterialTheme.typography.bodyMedium,
             color = MaterialTheme.colorScheme.onSurfaceVariant,
             modifier = Modifier.padding(start = 22.dp, end = 22.dp, bottom = 12.dp))
        LazyVerticalGrid(
            columns = GridCells.Fixed(2),
            contentPadding = PaddingValues(start = 16.dp, end = 16.dp, bottom = 28.dp),
            horizontalArrangement = Arrangement.spacedBy(10.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            items(templates, key = { it.key }) { t -> TemplateTile(t) { onPick(t) } }
        }
    }
}

@Composable
private fun TemplateTile(t: Template, onClick: () -> Unit) {
    val source = remember { MutableInteractionSource() }
    val pressed by source.collectIsPressedAsState()
    val scale by animateFloatAsState(if (pressed) 0.97f else 1f, label = "tile")
    Column(
        Modifier
            .scale(scale)
            .clip(RoundedCornerShape(20.dp))
            .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.55f))
            .clickable(interactionSource = source, indication = androidx.compose.material3.ripple(),
                       onClick = onClick)
            .padding(14.dp)
            .height(112.dp),
    ) {
        TemplateBadge(t.key, 40)
        Spacer(Modifier.weight(1f))
        Text(t.label, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold,
             maxLines = 1, overflow = TextOverflow.Ellipsis)
        Text(t.blurb, style = MaterialTheme.typography.labelMedium,
             color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 2,
             overflow = TextOverflow.Ellipsis, lineHeight = 17.sp)
    }
}
