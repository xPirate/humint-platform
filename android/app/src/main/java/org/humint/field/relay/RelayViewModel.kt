package org.humint.field.relay

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import org.humint.field.data.Crypto
import org.humint.field.data.FieldDatabase
import org.humint.field.data.RelayDao
import org.humint.field.data.RelayDeviceRow
import org.humint.field.data.RelayFileRow
import org.humint.field.data.RelaySubmissionRow
import org.humint.field.data.Vault
import org.humint.field.data.mediaDir
import org.json.JSONObject
import java.io.File
import java.text.SimpleDateFormat
import java.util.Locale
import java.util.TimeZone

/**
 * The relay's screens' half: what has come in, the team's phones, and
 * moving sealed arrivals into the vault whenever it is open.
 */
class RelayViewModel(app: Application) : AndroidViewModel(app) {

    private fun dao(): RelayDao = FieldDatabase.get(getApplication()).relay()
    private val context get() = getApplication<Application>()

    val state = Relay.state

    @OptIn(ExperimentalCoroutinesApi::class)
    val inbox: StateFlow<List<RelaySubmissionRow>> = Vault.state
        .flatMapLatest { if (it is Vault.State.Open) dao().submissions() else flowOf(emptyList()) }
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    @OptIn(ExperimentalCoroutinesApi::class)
    val devices: StateFlow<List<RelayDeviceRow>> = Vault.state
        .flatMapLatest { if (it is Vault.State.Open) dao().devices() else flowOf(emptyList()) }
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    @OptIn(ExperimentalCoroutinesApi::class)
    val fileCounts: StateFlow<Map<Int, Int>> = Vault.state
        .flatMapLatest { if (it is Vault.State.Open) dao().fileCounts() else flowOf(emptyList()) }
        .map { l -> l.associate { it.reportId.toInt() to it.n } }
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyMap())

    fun submission(id: Int) = dao().submissionFlow(id)
    fun files(id: Int) = dao().filesFlow(id)

    /** Items still sealed in the landing area — arrived while locked. */
    private val _waiting = MutableStateFlow(0)
    val waiting: StateFlow<Int> = _waiting

    // ------------------------------------------------------------- set-up

    /** Turn this install into a relay. Needs the vault open (the private
     *  key is sealed under it). */
    fun enable(): String? = runCatching {
        Relay.ensureKeys(context)
        org.humint.field.data.Settings.setRelayMode(context, true)
        null
    }.getOrElse { "Could not set up the relay: ${it.message}" }

    fun disable() {
        Relay.stop(context)
        org.humint.field.data.Settings.setRelayMode(context, false)
    }

    // ------------------------------------------------------------- phones

    data class Code(val deviceId: Int, val label: String, val analyst: String, val token: String)

    /** A new phone and its first code. The token is shown once and kept
     *  nowhere: only its hash is stored, as on the console. */
    suspend fun addPhone(label: String, analyst: String): Code = withContext(Dispatchers.IO) {
        val token = RelayLanding.newToken()
        val id = Relay.landing(context).addDevice(token)
        dao().insert(RelayDeviceRow(id, label.trim(), analyst.trim(), System.currentTimeMillis()))
        refreshNames()
        Code(id, label.trim(), analyst.trim(), token)
    }

    /** "Show its code again" mints a new token; the last code stops working. */
    suspend fun reissue(device: RelayDeviceRow): Code = withContext(Dispatchers.IO) {
        val token = RelayLanding.newToken()
        Relay.landing(context).rotateToken(device.id, token)
        Code(device.id, device.label, device.analyst, token)
    }

    fun revoke(device: RelayDeviceRow) = viewModelScope.launch(Dispatchers.IO) {
        Relay.landing(context).revokeDevice(device.id)
        dao().revokeDevice(device.id)
        refreshNames()
    }

    private suspend fun refreshNames() {
        Relay.names.value = dao().allDevices().filterNot { it.revoked }
            .associate { it.id to (it.label to it.analyst) }
    }

    // ------------------------------------------------------- moving it in

    private val ingestLock = Mutex()

    /**
     * Open whatever arrived while the vault was shut and move it in: each
     * report into relay_submissions, each file re-sealed under the vault
     * key into the media directory. An item is shredded from the landing
     * area only after its row is written.
     */
    fun ingest() = viewModelScope.launch(Dispatchers.IO) {
        ingestLock.withLock {
            if (Vault.state.value !is Vault.State.Open) return@withLock
            val own = Relay.privateKey(context) ?: return@withLock
            val landing = Relay.landing(context)
            val dao = dao()
            landing.drain(own) { item ->
                runCatching { runBlocking { take(dao, item) } }.getOrDefault(false)
            }
            _waiting.value = landing.pendingCount()
        }
    }

    private suspend fun take(dao: RelayDao, item: RelayLanding.Landed): Boolean {
        val h = item.header
        when (item.kind) {
            "submission" -> {
                val s = h.getJSONObject("submission")
                dao.insert(RelaySubmissionRow(
                    id = h.getInt("relay_id"),
                    deviceId = h.getInt("device_id"),
                    receivedAt = h.getLong("received_at"),
                    title = s.optString("title").trim().ifBlank { "Untitled" },
                    body = s.str("body"),
                    criticality = s.str("criticality"),
                    observedAt = s.str("observed_at"),
                    lat = s.num("lat"), lng = s.num("lng"),
                    accuracyM = s.num("location_accuracy_m"),
                    locationNote = s.str("location_note"),
                    clientRef = s.str("client_ref"),
                    template = s.str("template"),
                    templateVersion = if (s.has("template_version") && !s.isNull("template_version"))
                        s.optInt("template_version") else null,
                    fields = s.optJSONObject("fields")?.toString() ?: "{}",
                    geometry = s.optJSONObject("geometry")?.toString(),
                ))
            }
            "file" -> {
                val fileId = h.getInt("file_id")
                val subId = h.getInt("relay_id")
                val out = File(mediaDir(context), "relay-$subId-$fileId.bin")
                out.writeBytes(Crypto.sealBytes(context, item.content))
                dao.insert(RelayFileRow(
                    id = fileId, submissionId = subId,
                    clientRef = h.str("client_ref"),
                    filename = h.optString("filename", "file"),
                    mimeType = h.optString("mime", "application/octet-stream"),
                    path = out.absolutePath,
                    sizeBytes = item.content.size.toLong(),
                    durationMs = if (h.isNull("duration_ms")) null else h.optLong("duration_ms"),
                ))
            }
            else -> return false
        }
        return true
    }

    private fun JSONObject.str(k: String): String? =
        if (!has(k) || isNull(k)) null else optString(k).takeIf { it.isNotBlank() }

    private fun JSONObject.num(k: String): Double? =
        if (!has(k) || isNull(k)) null else optDouble(k).takeUnless { it.isNaN() }

    init {
        // Whenever the vault opens: refresh the names /hello answers with,
        // and move in whatever arrived while it was shut.
        viewModelScope.launch {
            Vault.state.collectLatest { st ->
                if (st is Vault.State.Open && Relay.isSetUp(context)) {
                    withContext(Dispatchers.IO) { runCatching { refreshNames() } }
                    ingest()
                }
                _waiting.value = runCatching { Relay.landing(context).pendingCount() }.getOrDefault(0)
            }
        }
        // And whenever something arrives while it is open.
        viewModelScope.launch {
            Relay.arrivals.collect {
                if (Vault.state.value is Vault.State.Open) ingest()
                else _waiting.value = runCatching { Relay.landing(context).pendingCount() }.getOrDefault(0)
            }
        }
    }

    companion object {
        fun parseIso(s: String?): Long? = s?.let {
            runCatching {
                SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.US)
                    .apply { timeZone = TimeZone.getTimeZone("UTC") }.parse(it.take(19))?.time
            }.getOrNull()
        }
    }
}
