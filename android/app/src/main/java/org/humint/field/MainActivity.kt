package org.humint.field

import android.os.Bundle
import android.view.WindowManager
import androidx.activity.compose.setContent
import androidx.activity.viewModels
import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.ProcessLifecycleOwner
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.compose.runtime.getValue
import androidx.compose.runtime.LaunchedEffect
import androidx.fragment.app.FragmentActivity
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import org.humint.field.data.Settings
import org.humint.field.data.Vault
import org.humint.field.ui.LockScreen
import org.humint.field.ui.SettingsScreen
import org.humint.field.net.SessionHolder
import org.humint.field.ui.FieldTheme
import org.humint.field.ui.QueueScreen
import org.humint.field.ui.ReportScreen
import org.humint.field.ui.ScanScreen
import org.humint.field.ui.UploadScreen
import org.humint.field.ui.MainShell
import org.humint.field.ui.SendScreen
import org.humint.field.ui.Tab
import org.humint.field.ui.TemplatePickerSheet
import org.humint.field.data.Templates
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.navigation.NavHostController
import kotlinx.coroutines.launch

// FragmentActivity rather than ComponentActivity: BiometricPrompt needs a
// fragment host, and there is no Compose-only way around that.
class MainActivity : FragmentActivity() {

    private val vm: FieldViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        /*
         * FLAG_SECURE does two things that matter on a handset like this: it
         * keeps the app out of the recents thumbnail, so a half-written
         * report about a person is not sitting in the task switcher for
         * whoever picks the phone up, and it blocks screenshots and screen
         * recording, including by anything else on the device.
         *
         * The cost is that the analyst cannot screenshot their own report.
         * That is the right trade here — the report is going to the console
         * anyway, and a screenshot of it would land in the gallery, outside
         * everything this app encrypts.
         */
        window.setFlags(WindowManager.LayoutParams.FLAG_SECURE,
                        WindowManager.LayoutParams.FLAG_SECURE)

        /*
         * The credentials die when the app leaves the foreground.
         *
         * Not when the activity is destroyed — that is too late and too
         * unreliable. ProcessLifecycleOwner fires onStop when the app goes
         * to the background at all: home button, task switcher, screen off,
         * a call coming in. Every one of those is a moment when the phone
         * might leave the analyst's hand, and the console's address should
         * not still be in memory when it does.
         */
        ProcessLifecycleOwner.get().lifecycle.addObserver(object : DefaultLifecycleObserver {
            override fun onStop(owner: LifecycleOwner) {
                SessionHolder.clear()
                // Starts the clock. The vault does not shut the instant the
                // screen turns off — an analyst who glances at a message and
                // comes back should not have to type a PIN — but a phone left
                // in a pocket is locked when it comes out again.
                Vault.onBackgrounded()
            }

            override fun onStart(owner: LifecycleOwner) {
                Vault.onForegrounded(applicationContext)
            }
        })

        Settings.load(this)
        Vault.refreshState(this)

        setContent {
            val theme by Settings.theme.collectAsStateWithLifecycle()
            val vault by Vault.state.collectAsStateWithLifecycle()
            FieldTheme(theme) {
                // Nothing behind the lock is composed at all while it is shut:
                // the queue screen would otherwise try to open the database,
                // which has no key until the PIN is in.
                if (vault !is Vault.State.Open) {
                    LockScreen(vault) { Vault.refreshState(applicationContext) }
                    return@FieldTheme
                }
                val nav = rememberNavController()
                val scope = rememberCoroutineScope()
                val ready by vm.readyCount.collectAsStateWithLifecycle()
                var picking by remember { mutableStateOf(false) }

                // The three bar destinations share one frame. Switching
                // between them replaces the top of the stack rather than
                // piling up, so Back from any tab leaves the app the way
                // it does from any other app's home tabs.
                fun goTab(tab: Tab) {
                    if (tab == Tab.Lock) { Vault.lock(); return }
                    val route = when (tab) {
                        Tab.Reports -> "queue"; Tab.Send -> "send"; else -> "settings"
                    }
                    nav.navigate(route) {
                        popUpTo("queue") { saveState = true }
                        launchSingleTop = true
                        restoreState = true
                    }
                }
                val shell: @androidx.compose.runtime.Composable (Tab, @androidx.compose.runtime.Composable (androidx.compose.foundation.layout.PaddingValues) -> Unit) -> Unit =
                    { tab, body -> MainShell(tab, ready, ::goTab, onNew = { picking = true }, content = body) }

                if (picking) {
                    TemplatePickerSheet(
                        templates = Templates.all,
                        onPick = { t ->
                            scope.launch {
                                val id = vm.newReport(t.key)
                                picking = false
                                nav.navigate("report/$id")
                            }
                        },
                        onDismiss = { picking = false },
                    )
                }

                NavHost(navController = nav, startDestination = "queue") {
                    composable("queue") {
                        shell(Tab.Reports) { padding ->
                            QueueScreen(
                                vm = vm,
                                padding = padding,
                                onOpen = { id -> nav.navigate("report/$id") },
                                onSend = { goTab(Tab.Send) },
                                onNew = { picking = true },
                            )
                        }
                    }
                    composable("send") {
                        shell(Tab.Send) { padding ->
                            SendScreen(vm = vm, padding = padding, onScan = { nav.navigate("scan") })
                        }
                    }
                    composable("report/{id}") { entry ->
                        ReportScreen(
                            vm = vm,
                            reportId = entry.arguments?.getString("id").orEmpty(),
                            onDone = { nav.popBackStack() },
                        )
                    }
                    composable("scan") {
                        ScanScreen(
                            vm = vm,
                            onScanned = {
                                nav.popBackStack()
                                nav.navigate("upload")
                            },
                            onCancel = { nav.popBackStack() },
                        )
                    }
                    composable("upload") {
                        UploadScreen(vm = vm, onDone = {
                            nav.popBackStack("queue", inclusive = false)
                        })
                    }
                    composable("settings") {
                        shell(Tab.Settings) { padding -> SettingsScreen(padding) }
                    }
                }
            }
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        SessionHolder.clear()
        if (isFinishing) Vault.lock()
    }
}
