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
import org.json.JSONArray
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

    @OptIn(ExperimentalCoroutinesApi::class)
    val priorities: StateFlow<List<org.humint.field.data.RelayPriorityRow>> = Vault.state
        .flatMapLatest { if (it is Vault.State.Open) dao().priorities() else flowOf(emptyList()) }
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    fun savePriority(row: org.humint.field.data.RelayPriorityRow) = viewModelScope.launch(Dispatchers.IO) {
        if (row.id == 0) dao().insert(row) else dao().update(row)
    }

    fun deletePriority(id: Int) = viewModelScope.launch(Dispatchers.IO) {
        dao().deletePriority(id)
        // Take the tag off every report that carried it.
        dao().allSubmissions().forEach { r ->
            val ids = tagsOf(r)
            if (id in ids) dao().update(r.copy(priorities = JSONArray(ids - id).toString()))
        }
    }

    /** Tag or untag a report against a priority. */
    fun toggleTag(report: RelaySubmissionRow, priorityId: Int) = viewModelScope.launch(Dispatchers.IO) {
        val current = dao().submission(report.id) ?: return@launch
        val ids = tagsOf(current)
        val next = if (priorityId in ids) ids - priorityId else ids + priorityId
        dao().update(current.copy(priorities = JSONArray(next).toString()))
    }

    /** Marked as background: looked at, answers no priority. Stored as an
     *  empty array, which is different from null (not looked at yet). */
    fun markBackground(report: RelaySubmissionRow) = viewModelScope.launch(Dispatchers.IO) {
        dao().submission(report.id)?.let { dao().update(it.copy(priorities = "[]")) }
    }

    fun saveNote(report: RelaySubmissionRow, note: String) = viewModelScope.launch(Dispatchers.IO) {
        dao().submission(report.id)?.let { dao().update(it.copy(leadNote = note.trim().ifBlank { null })) }
    }

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
    suspend fun addPhone(label: String, analyst: String, consoleUserId: Int? = null): Code = withContext(Dispatchers.IO) {
        val token = RelayLanding.newToken()
        val id = Relay.landing(context).addDevice(token)
        dao().insert(RelayDeviceRow(id, label.trim(), analyst.trim(), System.currentTimeMillis(),
                                    consoleUserId = consoleUserId))
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

    // ------------------------------------------------- provisioning, sync

    private val link = RelayLink(app)

    /** The provisioning bundle, re-read whenever it may have changed. */
    private val _bundle = MutableStateFlow<RelayLink.Bundle?>(null)
    val bundle: StateFlow<RelayLink.Bundle?> = _bundle
    fun refreshBundle() { _bundle.value = if (Vault.state.value is Vault.State.Open) link.bundle() else null }

    /** For the provisioning scanner: true if the code worked. */
    fun provision(payload: String, onResult: (Boolean) -> Unit) = viewModelScope.launch {
        val r = withContext(Dispatchers.IO) { link.provision(payload) }
        r.onSuccess { _bundle.value = it; _provisionError.value = null }
         .onFailure { _provisionError.value = it.message ?: "That did not work." }
        onResult(r.isSuccess)
    }

    private val _provisionError = MutableStateFlow<String?>(null)
    val provisionError: StateFlow<String?> = _provisionError
    fun clearProvisionError() { _provisionError.value = null }

    private val _sync = MutableStateFlow<RelayLink.Progress?>(null)
    val sync: StateFlow<RelayLink.Progress?> = _sync

    fun sync(videoLater: Boolean) = viewModelScope.launch(Dispatchers.IO) {
        // Anything still sealed is opened first, so it goes home too.
        ingest().join()
        _sync.value = RelayLink.Progress.Finding("…")
        _sync.value = link.sync(dao(), videoLater) { _sync.value = it }
        refreshBundle()
    }

    fun dismissSync() { _sync.value = null }

    // ------------------------------------------------------------- backup

    sealed interface Backup {
        data object Writing : Backup
        data class Done(val reports: Int, val files: Int, val consoleCanOpen: Boolean) : Backup
        data class Failed(val message: String) : Backup
    }

    private val _backup = MutableStateFlow<Backup?>(null)
    val backup: StateFlow<Backup?> = _backup
    fun dismissBackup() { _backup.value = null }

    fun checkPin(pin: CharArray) = Vault.checkPin(context, pin)

    /**
     * Everything on the relay, encrypted, to wherever [uri] points — a USB
     * stick chosen in Android's file picker. Opens with [pin] on a relay,
     * and at the console with no PIN (if this relay has been provisioned).
     */
    fun backup(uri: android.net.Uri, pin: CharArray) = viewModelScope.launch(Dispatchers.IO) {
        _backup.value = Backup.Writing
        _backup.value = runCatching {
            ingest().join()
            val dao = dao()
            val b = link.bundle()
            val devices = dao.allDevices().associateBy { it.id }
            val pmap = dao.allPriorities().associateBy { it.id }
            val reports = JSONArray()
            val producers = mutableListOf<() -> ByteArray>()
            var fileCount = 0
            val rows = dao.allSubmissions().sortedBy { it.receivedAt }
            for (r in rows) {
                val json = RelayLink.reportJson(r, devices[r.deviceId], pmap)
                val files = JSONArray()
                for (f in dao.files(r.id)) {
                    files.put(JSONObject().put("filename", f.filename).put("mime", f.mimeType)
                        .put("client_ref", f.clientRef ?: "relay-file-${f.id}")
                        .put("duration_ms", f.durationMs ?: JSONObject.NULL)
                        .put("length", f.sizeBytes))
                    producers += { Crypto.openBytes(context, File(f.path).readBytes()) }
                    fileCount++
                }
                reports.put(json.put("files", files))
            }
            val meta = JSONObject()
                .put("relay_id", b?.relayId ?: JSONObject.NULL)
                .put("label", b?.label ?: "Unprovisioned relay")
                .put("created_at", RelayLink.isoNow())
                .put("reports", rows.size).put("files", fileCount)
            val manifest = JSONObject().put("reports", reports)
                .put("priorities", JSONArray(pmap.values.map {
                    JSONObject().put("rank", it.rank).put("statement", it.statement)
                        .put("answers", it.answers ?: JSONObject.NULL).put("status", it.status)
                }))
            val console = b?.let { RelayCrypto.publicFrom(it.consoleKey) }
            context.contentResolver.openOutputStream(uri, "w")!!.use { out ->
                BackupFormat.write(out, meta, manifest, producers, pin, console, b?.fingerprint)
            }
            Backup.Done(rows.size, fileCount, console != null)
        }.getOrElse { Backup.Failed(it.message ?: "The backup could not be written.") }
        java.util.Arrays.fill(pin, '\u0000')
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
                    withContext(Dispatchers.IO) { runCatching { refreshNames() }; refreshBundle() }
                    ingest()
                } else if (st !is Vault.State.Open) _bundle.value = null
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
        fun tagsOf(r: RelaySubmissionRow): List<Int> = runCatching {
            val a = JSONArray(r.priorities ?: "[]"); (0 until a.length()).map { a.getInt(it) }
        }.getOrDefault(emptyList())

        /**
         * Which priorities a report seems to bear on: any priority whose
         * "what would answer it" shares a meaningful word with the report.
         * A suggestion for the lead, never a tag — matching words is not
         * judgement, and a wrong tag would mislead the debrief.
         */
        fun suggest(r: RelaySubmissionRow, ps: List<org.humint.field.data.RelayPriorityRow>): List<Int> {
            val text = (r.title + " " + (r.body ?: "") + " " + r.fields + " " + (r.locationNote ?: "")).lowercase()
            val words = Regex("[a-z0-9]{4,}").findAll(text).map { it.value }.toSet()
            return ps.filter { it.status != "Dropped" }.filter { p ->
                val keys = Regex("[a-z0-9]{4,}").findAll(((p.answers ?: "") + " " + p.statement).lowercase())
                    .map { it.value }.filterNot { it in STOP }.toSet()
                keys.any { it in words }
            }.map { it.id }
        }

        private val STOP = setOf("what", "when", "where", "which", "with", "from", "that", "this", "they",
            "them", "their", "there", "have", "about", "near", "into", "over", "after", "before", "would",
            "should", "could", "report", "reports", "anyone", "anything", "whether")

        fun parseIso(s: String?): Long? = s?.let {
            runCatching {
                SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.US)
                    .apply { timeZone = TimeZone.getTimeZone("UTC") }.parse(it.take(19))?.time
            }.getOrNull()
        }
    }
}
