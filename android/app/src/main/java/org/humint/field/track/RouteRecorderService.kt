package org.humint.field.track

import android.Manifest
import android.annotation.SuppressLint
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.Build
import android.os.IBinder
import android.os.Looper
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import org.humint.field.MainActivity
import org.humint.field.R

/**
 * Records a route with the screen off.
 *
 * A foreground service of type "location": Android's own rule for an app
 * that keeps using GPS when nobody is looking at it, and the reason a
 * notification shows for the whole time. That notification is the point,
 * not a cost -- nobody should be able to start this app tracking a phone
 * without it saying so on the phone.
 *
 * It is only ever started by a person pressing Start on a route report, and
 * stops when they press Stop (here or in the notification), when the report
 * is discarded, or when the app's data is erased. There is no background
 * location permission: the service is started while the app is on screen,
 * which is what Android's "while in use" permission allows.
 *
 * Points go to [TrackBuffer], sealed one by one, because the queue is locked
 * for most of a walk. They are merged into the report when the vault is next
 * open.
 */
class RouteRecorderService : Service(), LocationListener {

    companion object {
        const val ACTION_START = "org.humint.field.track.START"
        const val ACTION_STOP = "org.humint.field.track.STOP"
        const val EXTRA_REPORT = "report"
        private const val CHANNEL = "route-recording"
        private const val NOTIFICATION_ID = 41
        /** Ask GPS for a fix this often. Two seconds walks at about 3 m a step. */
        private const val INTERVAL_MS = 2_000L
    }

    private var reportId: String? = null
    private val filter = TrackFilter()
    private var lastKept: TrackPoint? = null
    private var lastNotified = 0L

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> { finish(); return START_NOT_STICKY }
            ACTION_START -> {
                val id = intent.getStringExtra(EXTRA_REPORT) ?: run { finish(); return START_NOT_STICKY }
                begin(id)
            }
            // A restart with no intent: the recording it belonged to was cut
            // off with the process. Its points are safe in the buffer; the
            // analyst can carry on from the report.
            else -> { finish(); return START_NOT_STICKY }
        }
        // Not sticky. A system restart of a location service from the
        // background is refused on current Android anyway, and a recording
        // that silently resumed later would be a recording nobody started.
        return START_NOT_STICKY
    }

    @SuppressLint("MissingPermission")
    private fun begin(id: String) {
        reportId = id
        filter.reset()
        lastKept = null
        ensureChannel()
        try {
            ServiceCompat.startForeground(
                this, NOTIFICATION_ID, notification(0, 0.0),
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q)
                    ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION else 0)
        } catch (e: Exception) {
            RouteRecorder.update { RouteRecorder.State(problem = "Android would not let the recording start: ${e.message}") }
            stopSelf()
            return
        }
        val fine = ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION) ==
            PackageManager.PERMISSION_GRANTED
        val manager = getSystemService(LocationManager::class.java)
        if (!fine || manager == null) {
            RouteRecorder.update { RouteRecorder.State(problem = "Location permission is needed to record a route.") }
            finish()
            return
        }
        if (!runCatching { manager.isProviderEnabled(LocationManager.GPS_PROVIDER) }.getOrDefault(false)) {
            RouteRecorder.update { it.copy(problem = "GPS is switched off. Turn on location to record.") }
        }
        // GPS only. A network fix is hundreds of metres wide and would draw a
        // route through somebody's house.
        runCatching {
            manager.requestLocationUpdates(LocationManager.GPS_PROVIDER, INTERVAL_MS, 0f, this,
                                           Looper.getMainLooper())
        }
    }

    override fun onLocationChanged(location: Location) {
        val id = reportId ?: return
        val p = TrackPoint(
            lat = location.latitude, lon = location.longitude, timeMs = location.time,
            accuracyM = if (location.hasAccuracy()) location.accuracy else Float.NaN,
            altitudeM = if (location.hasAltitude()) location.altitude else null,
        )
        val now = System.currentTimeMillis()
        RouteRecorder.update { it.copy(lastFixAt = now, lastAccuracyM = p.accuracyM.takeUnless { a -> a.isNaN() },
                                       problem = null) }
        if (!filter.accept(p)) return
        runCatching { TrackBuffer.append(this, id, p) }.onFailure {
            RouteRecorder.update { s -> s.copy(problem = "Could not save a point: ${it.message}") }
            return
        }
        val step = lastKept?.let { Shape.metres(it, p) } ?: 0.0
        lastKept = p
        RouteRecorder.update { it.copy(points = it.points + 1, lengthM = it.lengthM + step) }
        // The notification is not a speedometer: every fifteen seconds is
        // plenty, and updating it every fix wakes the screen on some phones.
        if (now - lastNotified > 15_000) {
            lastNotified = now
            val s = RouteRecorder.state.value
            getSystemService(NotificationManager::class.java)
                ?.notify(NOTIFICATION_ID, notification(s.points, s.lengthM))
        }
    }

    private fun finish() {
        runCatching { getSystemService(LocationManager::class.java)?.removeUpdates(this) }
        RouteRecorder.update { it.copy(running = false) }
        ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    override fun onDestroy() {
        runCatching { getSystemService(LocationManager::class.java)?.removeUpdates(this) }
        RouteRecorder.update { it.copy(running = false) }
        super.onDestroy()
    }

    private fun ensureChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val nm = getSystemService(NotificationManager::class.java) ?: return
        if (nm.getNotificationChannel(CHANNEL) != null) return
        nm.createNotificationChannel(NotificationChannel(
            CHANNEL, "Route recording", NotificationManager.IMPORTANCE_LOW).apply {
            description = "Shown while HUMINT Field is recording a route."
            setShowBadge(false)
        })
    }

    /**
     * Says that a route is being recorded and nothing about which. It shows
     * on the lock screen, and the route's name is case material.
     */
    private fun notification(points: Int, lengthM: Double): Notification {
        val open = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val stop = PendingIntent.getService(
            this, 1, Intent(this, RouteRecorderService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        return NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_launcher_foreground)
            .setContentTitle("Recording a route")
            .setContentText(if (points == 0) "Waiting for GPS…"
                            else "${formatLength(lengthM)} · $points points")
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setForegroundServiceBehavior(NotificationCompat.FOREGROUND_SERVICE_IMMEDIATE)
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
            .setContentIntent(open)
            .addAction(0, "Stop", stop)
            .build()
    }
}
