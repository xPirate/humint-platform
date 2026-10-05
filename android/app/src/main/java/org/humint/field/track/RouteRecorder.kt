package org.humint.field.track

import android.content.Context
import android.content.Intent
import androidx.core.content.ContextCompat
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow

/**
 * The one route being recorded, if any. The service does the work; this is
 * what the screens read and what they call.
 *
 * One at a time, on purpose: a phone records one walk. Starting a second
 * report's recording while another runs is refused in words, not by quietly
 * stopping the first.
 */
object RouteRecorder {

    data class State(
        val reportId: String? = null,
        val running: Boolean = false,
        /** Points kept in this run (not counting earlier runs already merged). */
        val points: Int = 0,
        val lengthM: Double = 0.0,
        val startedAt: Long = 0L,
        val lastFixAt: Long = 0L,
        val lastAccuracyM: Float? = null,
        /** Set when the service could not start or lost the GPS. */
        val problem: String? = null,
    )

    private val _state = MutableStateFlow(State())
    val state: StateFlow<State> = _state

    internal fun update(change: (State) -> State) { _state.value = change(_state.value) }

    fun isRecording(reportId: String) = _state.value.running && _state.value.reportId == reportId

    /** Returns a reason it cannot start, or null when it has. */
    fun start(context: Context, reportId: String): String? {
        val current = _state.value
        if (current.running && current.reportId != reportId) {
            return "Another route is being recorded. Stop it first."
        }
        if (current.running) return null
        _state.value = State(reportId = reportId, running = true,
                             startedAt = System.currentTimeMillis())
        val intent = Intent(context, RouteRecorderService::class.java)
            .setAction(RouteRecorderService.ACTION_START)
            .putExtra(RouteRecorderService.EXTRA_REPORT, reportId)
        return runCatching {
            ContextCompat.startForegroundService(context, intent)
            null
        }.getOrElse {
            _state.value = State(problem = "Could not start recording: ${it.message}")
            _state.value.problem
        }
    }

    fun stop(context: Context) {
        if (!_state.value.running) return
        runCatching {
            context.startService(Intent(context, RouteRecorderService::class.java)
                .setAction(RouteRecorderService.ACTION_STOP))
        }
        _state.value = _state.value.copy(running = false)
    }
}
