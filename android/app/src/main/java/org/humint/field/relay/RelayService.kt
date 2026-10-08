package org.humint.field.relay

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import org.humint.field.MainActivity
import org.humint.field.R
import org.humint.field.data.Templates

/**
 * Keeps the relay's server up overnight with the screen off.
 *
 * A foreground service, because Android stops anything else once the screen
 * has been dark a while; a notification, because Android requires one and
 * because a tablet quietly accepting connections should say so. Type
 * "specialUse": none of the defined types fits a local server for a team's
 * own phones, and "dataSync" is capped at six hours a day on Android 15 —
 * shorter than a night.
 *
 * Sticky, unlike the route recorder. If Samsung's battery manager kills the
 * process at 3 a.m., the server should come back on its own: it needs no
 * PIN to accept reports (they are sealed to the public key), so a restart
 * with nobody there to unlock is exactly as safe as the first start.
 */
class RelayService : Service() {

    companion object {
        const val ACTION_START = "org.humint.field.relay.START"
        const val ACTION_STOP = "org.humint.field.relay.STOP"
        private const val CHANNEL = "relay"
        private const val NOTIFICATION_ID = 51
        private const val WAKE_MAX_MS = 24 * 60 * 60 * 1000L
    }

    private var server: RelayServer? = null
    private var wakeLock: PowerManager.WakeLock? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) { finish(); return START_NOT_STICKY }
        begin()
        return START_STICKY
    }

    private fun begin() {
        ensureChannel()
        try {
            ServiceCompat.startForeground(
                this, NOTIFICATION_ID, notification(Relay.state.value.received),
                if (Build.VERSION.SDK_INT >= 34) ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE else 0)
        } catch (e: Exception) {
            Relay.update { it.copy(running = false, problem = "Android would not let the relay start: ${e.message}") }
            stopSelf(); return
        }
        if (server?.running == true) return
        val landing = Relay.landing(this)
        if (!landing.hasKey()) {
            Relay.update { it.copy(running = false, problem = "Open the relay with a team PIN once to set it up.") }
            finish(); return
        }
        runCatching { Templates.load(this) }
        val s = RelayServer(
            landing,
            RelayServer.Config(templateVersion = Templates.version),
            names = { Relay.names.value },
            onReceived = { e ->
                Relay.arrived(e)
                if (e is RelayServer.Event.Submission) {
                    Relay.update { it.copy(received = it.received + 1, lastReceivedAt = System.currentTimeMillis()) }
                    getSystemService(NotificationManager::class.java)
                        ?.notify(NOTIFICATION_ID, notification(Relay.state.value.received))
                }
            },
        )
        try {
            s.start()
        } catch (e: Exception) {
            Relay.update { it.copy(running = false, problem = "Could not open port ${RelayServer.DEFAULT_PORT}: ${e.message}") }
            finish(); return
        }
        server = s
        runCatching {
            wakeLock = getSystemService(PowerManager::class.java)
                ?.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "HUMINTField:relay")
                ?.apply { setReferenceCounted(false); acquire(WAKE_MAX_MS) }
        }
        Relay.update { it.copy(running = true, startedAt = System.currentTimeMillis(), problem = null) }
    }

    private fun finish() {
        server?.stop(); server = null
        runCatching { wakeLock?.takeIf { it.isHeld }?.release() }; wakeLock = null
        Relay.update { it.copy(running = false) }
        ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    override fun onDestroy() {
        server?.stop(); server = null
        runCatching { wakeLock?.takeIf { it.isHeld }?.release() }; wakeLock = null
        Relay.update { it.copy(running = false) }
        super.onDestroy()
    }

    private fun ensureChannel() {
        val nm = getSystemService(NotificationManager::class.java) ?: return
        if (nm.getNotificationChannel(CHANNEL) != null) return
        nm.createNotificationChannel(NotificationChannel(
            CHANNEL, "Team relay", NotificationManager.IMPORTANCE_LOW).apply {
            description = "Shown while this tablet is taking reports from the team's phones."
            setShowBadge(false)
        })
    }

    /** Says that the relay is on and how many reports came in. Nothing
     *  about what they are: this shows on the lock screen. */
    private fun notification(received: Int): Notification {
        val open = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val stop = PendingIntent.getService(
            this, 1, Intent(this, RelayService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        return NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_launcher_foreground)
            .setContentTitle("Team relay is on")
            .setContentText(if (received == 0) "Waiting for the team's phones"
                            else "$received received since it started")
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setForegroundServiceBehavior(NotificationCompat.FOREGROUND_SERVICE_IMMEDIATE)
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
            .setContentIntent(open)
            .addAction(0, "Stop", stop)
            .build()
    }
}
