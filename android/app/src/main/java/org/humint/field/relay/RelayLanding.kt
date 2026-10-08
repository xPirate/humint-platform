package org.humint.field.relay

import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.DataInputStream
import java.io.DataOutputStream
import java.io.File
import java.security.MessageDigest
import java.security.PrivateKey
import java.security.PublicKey

/**
 * Where phone uploads land on a relay, before anyone with a PIN has looked.
 *
 * The same shape as track/TrackBuffer.kt, for the same reason: the thing
 * writing runs while the vault is shut. Every submission and every file is
 * sealed to the relay's public key (RelayCrypto) the moment it arrives and
 * written here; when the vault is next open, [drain] hands each one over to
 * be moved into the encrypted database and shreds it.
 *
 * What is on disk in the clear, and why each is harmless:
 *
 *  - `devices.idx` — each phone's number, a SHA-256 of its token, and whether
 *    it is revoked. No names: a phone's label and its analyst live in the
 *    vault. The server needs the hashes to check a token while locked.
 *  - `index.json` — counters and dedupe keys. A dedupe key is a hash of a
 *    phone number and the random id the phone gave its report, so it says
 *    how many reports arrived and nothing about any of them.
 *  - `pub.der` — the public key. Public by definition.
 *
 * Plain java.io and org.json, so the unit tests exercise it on the JVM.
 */
class RelayLanding(private val dir: File) {

    data class Accepted(val id: Int, val duplicate: Boolean)

    /** One sealed item, opened. [kind] is "submission" or "file". */
    data class Landed(
        val file: File,
        val kind: String,
        val header: JSONObject,
        /** The file's bytes; empty for a submission, whose content is [header]. */
        val content: ByteArray,
    )

    class Refused(val status: Int, message: String) : Exception(message)

    private val landing get() = File(dir, "landing").apply { mkdirs() }
    private val indexFile get() = File(dir, "index.json")
    private val devicesFile get() = File(dir, "devices.idx")
    private val pubFile get() = File(dir, "pub.der")

    init { dir.mkdirs() }

    // ------------------------------------------------------------- the key

    fun hasKey(): Boolean = pubFile.exists() && pubFile.length() > 0

    fun publicKey(): PublicKey? =
        runCatching { RelayCrypto.publicFrom(pubFile.readBytes()) }.getOrNull()

    fun setPublicKey(key: PublicKey) { pubFile.writeBytes(key.encoded) }

    // ------------------------------------------------------------- phones

    data class DeviceEntry(val id: Int, val tokenHash: String, val revoked: Boolean)

    @Synchronized
    fun devices(): List<DeviceEntry> = runCatching {
        devicesFile.readLines().mapNotNull { line ->
            val p = line.split('\t')
            if (p.size < 3) null else DeviceEntry(p[0].toInt(), p[1], p[2] == "1")
        }
    }.getOrDefault(emptyList())

    private fun writeDevices(list: List<DeviceEntry>) {
        val tmp = File(dir, "devices.idx.tmp")
        tmp.writeText(list.joinToString("\n") { "${it.id}\t${it.tokenHash}\t${if (it.revoked) 1 else 0}" })
        tmp.renameTo(devicesFile)
    }

    /** A new phone. Returns its number; the caller keeps the name in the vault. */
    @Synchronized
    fun addDevice(token: String): Int {
        val list = devices()
        val id = (list.maxOfOrNull { it.id } ?: 0) + 1
        writeDevices(list + DeviceEntry(id, hash(token), false))
        return id
    }

    /** A fresh token for an existing phone — the same as "show its code
     *  again" on the console: the old code stops working. */
    @Synchronized
    fun rotateToken(id: Int, token: String) {
        writeDevices(devices().map { if (it.id == id) it.copy(tokenHash = hash(token)) else it })
    }

    @Synchronized
    fun revokeDevice(id: Int) {
        writeDevices(devices().map { if (it.id == id) it.copy(revoked = true) else it })
    }

    /** The phone a bearer token belongs to, or null for unknown or revoked. */
    fun authenticate(token: String?): Int? {
        if (token.isNullOrBlank()) return null
        val h = hash(token)
        val hit = devices().firstOrNull {
            MessageDigest.isEqual(it.tokenHash.toByteArray(), h.toByteArray())
        } ?: return null
        return if (hit.revoked) null else hit.id
    }

    // -------------------------------------------------------------- intake

    /**
     * A report's text. [body] is the JSON the phone posted, kept whole: the
     * relay does not interpret a report, it carries it.
     */
    @Synchronized
    fun acceptSubmission(deviceId: Int, body: JSONObject, receivedAt: Long): Accepted {
        val key = publicKey() ?: throw Refused(503, "This relay is not set up yet.")
        val idx = readIndex()
        val ref = body.optString("client_ref").takeIf { it.isNotBlank() }
        if (ref != null) {
            val k = hash("$deviceId:$ref")
            idx.optJSONObject("subs")?.optInt(k, 0)?.takeIf { it > 0 }?.let {
                return Accepted(it, duplicate = true)
            }
        }
        val id = idx.optInt("next", 1)
        idx.put("next", id + 1)
        if (ref != null) idx.getJSONObject("subs").put(hash("$deviceId:$ref"), id)
        idx.getJSONObject("owner").put(id.toString(), deviceId)

        val header = JSONObject()
            .put("kind", "submission").put("relay_id", id).put("device_id", deviceId)
            .put("received_at", receivedAt).put("submission", body)
        writeSealed(File(landing, "sub-$id.bin"), key, header, ByteArray(0))
        writeIndex(idx)
        return Accepted(id, duplicate = false)
    }

    /** A photo, clip or memo for a submission this same phone sent. */
    @Synchronized
    fun acceptFile(
        deviceId: Int, submissionId: Int, clientRef: String?, filename: String,
        mime: String, durationMs: Long?, bytes: ByteArray, receivedAt: Long,
        maxFiles: Int, maxSubmissionBytes: Long,
    ): Accepted {
        val key = publicKey() ?: throw Refused(503, "This relay is not set up yet.")
        val idx = readIndex()
        val owner = idx.getJSONObject("owner").optInt(submissionId.toString(), 0)
        // Same answer for "no such submission" and "not yours", as the
        // console gives: a phone must not be able to probe for others' ids.
        if (owner != deviceId) throw Refused(404, "No such submission.")

        val files = idx.getJSONObject("files").optJSONArray(submissionId.toString()) ?: JSONArray()
        val refKey = clientRef?.takeIf { it.isNotBlank() }?.let { hash("$submissionId:$it") }
        if (refKey != null) {
            for (i in 0 until files.length()) {
                val f = files.getJSONObject(i)
                if (f.optString("ref") == refKey) return Accepted(f.getInt("id"), duplicate = true)
            }
        }
        if (files.length() >= maxFiles) {
            throw Refused(409, "A submission may carry $maxFiles files.")
        }
        val soFar = idx.getJSONObject("bytes").optLong(submissionId.toString(), 0L)
        if (soFar + bytes.size > maxSubmissionBytes) {
            throw Refused(413, "That would take the submission past " +
                "${maxSubmissionBytes / (1024 * 1024)} MB of media.")
        }
        val fileId = idx.optInt("next_file", 1)
        idx.put("next_file", fileId + 1)
        files.put(JSONObject().put("id", fileId).put("ref", refKey ?: ""))
        idx.getJSONObject("files").put(submissionId.toString(), files)
        idx.getJSONObject("bytes").put(submissionId.toString(), soFar + bytes.size)

        val header = JSONObject()
            .put("kind", "file").put("file_id", fileId).put("relay_id", submissionId)
            .put("device_id", deviceId).put("received_at", receivedAt)
            .put("client_ref", clientRef ?: JSONObject.NULL)
            .put("filename", filename).put("mime", mime)
            .put("duration_ms", durationMs ?: JSONObject.NULL)
        writeSealed(File(landing, "file-$submissionId-$fileId.bin"), key, header, bytes)
        writeIndex(idx)
        return Accepted(fileId, duplicate = false)
    }

    /** How many items are waiting to be opened. */
    fun pendingCount(): Int = landing.listFiles()?.count { it.name.endsWith(".bin") } ?: 0

    /**
     * Open everything waiting, oldest first, submissions before their files,
     * and hand each to [take]. An item is shredded only after [take] returns
     * true — if moving it into the vault fails, it stays here for next time.
     * One that cannot be opened at all (wrong key, cut-off write) is left
     * alone and reported, never deleted: it may be the only copy.
     */
    fun drain(own: PrivateKey, take: (Landed) -> Boolean): DrainResult {
        val items = synchronized(this) {
            landing.listFiles()?.filter { it.name.endsWith(".bin") }.orEmpty()
        }.sortedWith(compareBy({ if (it.name.startsWith("sub-")) 0 else 1 }, { it.lastModified() }))
        var moved = 0
        var unreadable = 0
        for (f in items) {
            val landed = runCatching { readSealed(f, own) }.getOrNull()
            if (landed == null) { unreadable++; continue }
            if (take(landed)) {
                shred(f)
                moved++
            }
        }
        return DrainResult(moved, unreadable)
    }

    data class DrainResult(val moved: Int, val unreadable: Int)

    /** End of a deployment: forget every phone, every dedupe key and
     *  anything not yet opened. Called after a successful sync, or by the
     *  duress PIN. The key pair is replaced separately. */
    @Synchronized
    fun wipe() {
        landing.listFiles()?.forEach { shred(it) }
        listOf(indexFile, devicesFile, pubFile).forEach { shred(it) }
    }

    // ------------------------------------------------------------- on disk

    private fun readIndex(): JSONObject {
        val o = runCatching { JSONObject(indexFile.readText()) }.getOrElse { JSONObject() }
        for (k in listOf("subs", "owner", "files", "bytes")) if (!o.has(k)) o.put(k, JSONObject())
        return o
    }

    private fun writeIndex(o: JSONObject) {
        val tmp = File(dir, "index.json.tmp")
        tmp.writeText(o.toString())
        tmp.renameTo(indexFile)
    }

    private fun writeSealed(target: File, key: PublicKey, header: JSONObject, content: ByteArray) {
        val plain = ByteArrayOutputStream(content.size + 512).also { out ->
            DataOutputStream(out).use { d ->
                val h = header.toString().toByteArray()
                d.writeInt(h.size); d.write(h); d.write(content)
            }
        }.toByteArray()
        val sealed = RelayCrypto.seal(key, plain)
        java.util.Arrays.fill(plain, 0)
        // Written beside, then renamed: a write cut off by a dying battery
        // leaves a .part nobody reads, never a half-file that looks whole.
        val part = File(target.parentFile, target.name + ".part")
        part.outputStream().use { it.write(sealed); it.fd.sync() }
        part.renameTo(target)
    }

    private fun readSealed(f: File, own: PrivateKey): Landed {
        val plain = RelayCrypto.open(own, f.readBytes())
        DataInputStream(plain.inputStream()).use { d ->
            val h = ByteArray(d.readInt()).also { d.readFully(it) }
            val content = d.readBytes()
            val header = JSONObject(String(h))
            return Landed(f, header.getString("kind"), header, content)
        }
    }

    companion object {
        fun hash(s: String): String =
            MessageDigest.getInstance("SHA-256").digest(s.toByteArray())
                .joinToString("") { "%02x".format(it) }

        fun newToken(): String {
            val bytes = ByteArray(32).also { java.security.SecureRandom().nextBytes(it) }
            return java.util.Base64.getUrlEncoder().withoutPadding().encodeToString(bytes)
        }

        /** Overwrite, then delete. See Crypto.shred for what that is worth
         *  on flash, which is less than it sounds and more than nothing. */
        fun shred(f: File) {
            runCatching {
                if (f.exists() && f.length() > 0) {
                    val zeros = ByteArray(minOf(f.length(), 1L shl 20).toInt())
                    f.outputStream().use { out ->
                        var left = f.length()
                        while (left > 0) {
                            val n = minOf(left, zeros.size.toLong()).toInt()
                            out.write(zeros, 0, n); left -= n
                        }
                    }
                }
            }
            runCatching { f.delete() }
        }
    }
}
