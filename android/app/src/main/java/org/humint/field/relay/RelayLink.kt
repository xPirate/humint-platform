package org.humint.field.relay

import android.content.Context
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.humint.field.data.Crypto
import org.humint.field.data.RelayDao
import org.humint.field.data.RelaySubmissionRow
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.IOException
import java.security.SecureRandom
import java.security.Signature
import java.text.SimpleDateFormat
import java.util.Base64
import java.util.Date
import java.util.Locale
import java.util.TimeZone
import java.util.concurrent.TimeUnit

/**
 * The relay's side of talking to the console: provisioning, and Sync.
 *
 * UNLIKE A PHONE, A RELAY KEEPS ITS CREDENTIAL
 *
 * A phone forgets the console's address and token the moment an upload
 * ends. A relay cannot: it has to reach home days later, from a hotel, with
 * nobody there to show it a code. So the bundle the console hands it at
 * provisioning — its token, the addresses to try, the console's public key,
 * the team roster — is kept, sealed under the vault key like the reports.
 * Without a team PIN it is unreadable; and the console drops the token on
 * its own if the relay goes quiet for longer than its keep-alive.
 *
 * PROVING IT IS THE CONSOLE
 *
 * Before Sync sends a byte of a report — or its token — it challenges
 * whatever answered: a random nonce, signed by the console with the key
 * whose public half arrived at provisioning. A signature that does not
 * check out ends the sync with nothing sent.
 */
class RelayLink(private val context: Context) {

    data class Bundle(val json: JSONObject) {
        val relayId get() = json.getInt("relay_id")
        val label get() = json.getString("label")
        val token get() = json.getString("token")
        val keepaliveDays get() = json.optInt("keepalive_days", 3)
        val expiresAt: Long? get() = parseIso(json.optString("expires_at"))
        val addresses: List<String> get() = json.optJSONArray("addresses").strings()
        val fingerprint get() = json.optJSONObject("console")?.optString("fingerprint").orEmpty()
        val consoleKey: ByteArray get() = Base64.getDecoder().decode(
            json.getJSONObject("console").getString("public_key"))
        val roster: List<Member> get() = json.optJSONArray("roster")?.let { a ->
            (0 until a.length()).map { a.getJSONObject(it) }.map {
                Member(it.getInt("id"), it.optString("username"), it.optString("name"))
            }
        }.orEmpty()
    }

    data class Member(val id: Int, val username: String, val name: String)

    private val file get() = File(Relay.dir(context), "provision.sealed")

    private val client = OkHttpClient.Builder()
        .connectTimeout(6, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .writeTimeout(10, TimeUnit.MINUTES)
        .build()

    // ---------------------------------------------------------- the bundle

    /** The stored bundle, or null if never provisioned or the vault is shut. */
    fun bundle(): Bundle? = runCatching {
        Bundle(JSONObject(String(Crypto.openBytes(context, file.readBytes()))))
    }.getOrNull()

    private fun save(b: JSONObject) {
        Relay.dir(context).mkdirs()
        file.writeBytes(Crypto.sealBytes(context, b.toString().toByteArray()))
    }

    fun forget() { RelayLanding.shred(file) }

    /**
     * Swap the console's one-time code for this relay's bundle. The QR
     * carries {"kind":"relay-provision","url":…,"code":…}. Done on the
     * office network, in front of the admin, who compares the fingerprint
     * this returns with the one on the console's screen.
     */
    fun provision(qrPayload: String): Result<Bundle> = runCatching {
        val q = JSONObject(qrPayload)
        require(q.optString("kind") == "relay-provision") {
            "That is not a relay provisioning code. On the console: Admin → Field devices → Team relays."
        }
        val url = q.optString("url").trim().trimEnd('/')
        require(url.startsWith("http")) { "That code has no console address in it." }
        val code = q.optString("code")
        val body = JSONObject().put("code", code).toString()
            .toRequestBody("application/json".toMediaType())
        val json = call(Request.Builder().url("$url/api/relay/provision").post(body).build())
        // Sanity check now, while the admin is watching: the key that came
        // in the bundle is the key that signs this console's challenge.
        val bundle = Bundle(json.put("provisioned_from", url).put("provisioned_at", isoNow()))
        verify(url, bundle.consoleKey)
        save(bundle.json)
        bundle
    }

    // ---------------------------------------------------------------- sync

    sealed interface Progress {
        data class Finding(val address: String) : Progress
        data class Sending(val index: Int, val total: Int, val title: String) : Progress
        data class SendingFile(val name: String) : Progress
        data class Done(val sent: Int, val heldBack: Int, val expiresAt: Long?, val console: String) : Progress
        data class Failed(val message: String) : Progress
    }

    /**
     * Find the console, prove it, check in, and send everything not yet
     * sent. [videoLater] holds clips back for a better connection; their
     * reports go now and the clips follow on a later Sync. A report is
     * erased from the tablet only once the console has confirmed it and all
     * of its files.
     */
    suspend fun sync(
        dao: RelayDao, videoLater: Boolean, onProgress: (Progress) -> Unit,
    ): Progress {
        val b = bundle() ?: return Progress.Failed("This relay has not been provisioned.")
        val auth = "Bearer ${b.token}"

        return try {
            val base = find(b, onProgress) ?: return Progress.Failed(
                "Could not reach the console at any of its addresses. Is the VPN connected?")
            val check = call(Request.Builder().url("$base/api/relay/checkin").header("Authorization", auth)
                .post(ByteArray(0).toRequestBody(null)).build())
            b.json.put("expires_at", check.optString("expires_at"))
            b.json.put("last_checkin", isoNow())
            save(b.json)

            val devices = dao.allDevices().associateBy { it.id }
            val pmap = dao.allPriorities().associateBy { it.id }
            val queue = dao.unforwarded()
            var sent = 0
            var held = 0
            queue.forEachIndexed { i, row ->
                onProgress(Progress.Sending(i + 1, queue.size, row.title))
                val consoleId = sendReport(base, auth, row, devices[row.deviceId], pmap)
                var allFiles = true
                for (f in dao.files(row.id).filterNot { it.forwarded }) {
                    if (videoLater && f.mimeType.startsWith("video/")) { allFiles = false; continue }
                    onProgress(Progress.SendingFile(f.filename))
                    sendFile(base, auth, consoleId, f)
                    dao.update(f.copy(forwarded = true))
                }
                if (allFiles) {
                    erase(dao, row)
                    sent++
                } else held++
            }
            Progress.Done(sent, held, parseIso(check.optString("expires_at")), base)
        } catch (e: IOException) {
            Progress.Failed(e.message ?: "The sync was cut off. Press Sync again; nothing is sent twice.")
        }
    }

    /** Whether the console answers and is who it says — without sending. */
    fun ping(): Result<String> = runCatching {
        val b = bundle() ?: error("Not provisioned.")
        find(b) {} ?: error("Could not reach the console at any of its addresses.")
    }

    private fun find(b: Bundle, onProgress: (Progress) -> Unit): String? {
        for (raw in b.addresses + listOfNotNull(b.json.optString("provisioned_from").takeIf { it.isNotBlank() })) {
            val base = raw.trimEnd('/')
            onProgress(Progress.Finding(base))
            val ok = runCatching { verify(base, b.consoleKey) }
            if (ok.isSuccess) return base
            // A signature failure is not "try the next one quietly": something
            // answered at our console's address and could not prove it. Say so.
            if (ok.exceptionOrNull() is ImpostorException) throw IOException(ok.exceptionOrNull()!!.message)
        }
        return null
    }

    class ImpostorException(message: String) : Exception(message)

    private fun verify(base: String, consoleKey: ByteArray) {
        val nonce = ByteArray(32).also { SecureRandom().nextBytes(it) }
        val body = JSONObject().put("nonce", Base64.getEncoder().encodeToString(nonce)).toString()
            .toRequestBody("application/json".toMediaType())
        val json = call(Request.Builder().url("$base/api/relay/hello").post(body).build())
        val sig = Base64.getDecoder().decode(json.getString("signature"))
        val pub = java.security.KeyFactory.getInstance("EC")
            .generatePublic(java.security.spec.X509EncodedKeySpec(consoleKey))
        val good = runCatching {
            Signature.getInstance("SHA256withECDSA").run {
                initVerify(pub); update("humint-relay-hello:v1:".toByteArray()); update(nonce); verify(sig)
            }
        }.getOrDefault(false)
        if (!good) throw ImpostorException(
            "Something at $base answered but could not prove it is your console. Nothing was sent. " +
            "Check the VPN, and tell the console's admin.")
    }

    private fun sendReport(base: String, auth: String, r: RelaySubmissionRow,
                           device: org.humint.field.data.RelayDeviceRow?,
                           pmap: Map<Int, org.humint.field.data.RelayPriorityRow>): Int {
        val body = reportJson(r, device, pmap)
        val json = call(Request.Builder().url("$base/api/relay/submissions").header("Authorization", auth)
            .post(body.toString().toRequestBody("application/json; charset=utf-8".toMediaType())).build())
        return json.getInt("id")
    }

    private fun sendFile(base: String, auth: String, consoleId: Int, f: org.humint.field.data.RelayFileRow) {
        val plain = Crypto.openBytes(context, File(f.path).readBytes())
        val form = MultipartBody.Builder().setType(MultipartBody.FORM)
            .addFormDataPart("client_ref", f.clientRef ?: "relay-file-${f.id}")
            .apply { f.durationMs?.let { addFormDataPart("duration_ms", it.toString()) } }
            .addFormDataPart("file", f.filename, plain.toRequestBody(f.mimeType.toMediaType()))
            .build()
        call(Request.Builder().url("$base/api/relay/submissions/$consoleId/files")
            .header("Authorization", auth).post(form).build())
    }

    private suspend fun erase(dao: RelayDao, row: RelaySubmissionRow) {
        dao.files(row.id).forEach { RelayLanding.shred(File(it.path)) }
        dao.deleteFiles(row.id)
        dao.deleteSubmission(row.id)
    }

    private fun call(req: Request): JSONObject = client.newCall(req).execute().use { resp ->
        val text = resp.body?.string().orEmpty()
        if (!resp.isSuccessful) {
            val detail = runCatching { JSONObject(text).optString("detail") }.getOrNull()
            throw IOException(detail?.takeIf { it.isNotBlank() } ?: "The console refused it (${resp.code}).")
        }
        JSONObject(text)
    }

    companion object {
        /** One report as the console's /api/relay/submissions takes it —
         *  the same JSON a Sync sends and a USB backup carries. */
        fun reportJson(r: RelaySubmissionRow, device: org.humint.field.data.RelayDeviceRow?,
                       pmap: Map<Int, org.humint.field.data.RelayPriorityRow>): JSONObject = JSONObject().apply {
            put("title", r.title)
            r.body?.let { put("body", it) }
            r.criticality?.let { put("criticality", it) }
            r.observedAt?.let { put("observed_at", it) }
            r.lat?.let { put("lat", it) }; r.lng?.let { put("lng", it) }
            r.accuracyM?.let { put("location_accuracy_m", it) }
            r.locationNote?.let { put("location_note", it) }
            r.clientRef?.let { put("client_ref", it) }
            r.template?.let { put("template", it) }
            r.templateVersion?.let { put("template_version", it) }
            put("fields", JSONObject(r.fields))
            r.geometry?.let { runCatching { put("geometry", JSONObject(it)) } }
            put("relay_submission_id", r.id)
            put("relay_device_id", r.deviceId)
            device?.let { put("phone_label", it.label); put("analyst_name", it.analyst) }
            device?.consoleUserId?.let { put("analyst_user_id", it) }
            put("received_at", iso(r.receivedAt))
            // The priorities themselves, not the relay's ids for them: the
            // console has never seen this relay's numbering.
            val tags = RelayViewModel.tagsOf(r).mapNotNull { pmap[it] }
            if (tags.isNotEmpty()) put("priorities", JSONArray(tags.map {
                JSONObject().put("rank", it.rank).put("statement", it.statement).put("status", it.status)
            }))
            r.leadNote?.let { put("lead_note", it) }
        }

        private fun JSONArray?.strings(): List<String> =
            this?.let { a -> (0 until a.length()).map { a.getString(it) } }.orEmpty()

        fun iso(ms: Long): String = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US)
            .apply { timeZone = TimeZone.getTimeZone("UTC") }.format(Date(ms))

        fun isoNow() = iso(System.currentTimeMillis())

        /** Python's isoformat, with or without fractions and an offset. */
        fun parseIso(s: String?): Long? {
            if (s.isNullOrBlank()) return null
            return runCatching { java.time.OffsetDateTime.parse(s).toInstant().toEpochMilli() }
                .recoverCatching { java.time.Instant.parse(s).toEpochMilli() }
                .getOrNull()
        }
    }
}
