package org.humint.field.relay

import org.json.JSONArray
import org.json.JSONObject
import java.io.DataInputStream
import java.io.DataOutputStream
import java.io.FilterOutputStream
import java.io.InputStream
import java.io.OutputStream
import java.security.PublicKey
import java.security.SecureRandom
import java.util.Base64
import javax.crypto.Cipher
import javax.crypto.CipherOutputStream
import javax.crypto.SecretKeyFactory
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.PBEKeySpec
import javax.crypto.spec.SecretKeySpec

/**
 * A relay's backup to USB media: one encrypted file, openable two ways.
 *
 *     "HUMINTRB" 0x01 | u32 header length | header JSON | AES-256-GCM body + tag
 *
 * A random key encrypts the body. The header carries that key twice:
 *
 *   - "pin": wrapped under a key derived from the lead's PIN (PBKDF2-SHA256,
 *     310,000 rounds, as the vault uses) — so a replacement relay can open
 *     it with the team's PIN;
 *   - "console": sealed to the console's public key with the same ECIES as
 *     RelayCrypto — so the office can open it with no PIN at all, which is
 *     the case that matters when the tablet itself is lost or broken.
 *
 * The header is the GCM additional data: editing a byte of it (to swap in a
 * different wrap, say) makes the whole body fail to open.
 *
 * The body is: u32 manifest length | manifest JSON | each file's bytes, in
 * the order the manifest lists them, each `length` long. Streamed, so a
 * backup with an hour of video never has to fit in memory.
 *
 * Plain JCA, so a JVM test writes one and both this reader and the
 * console's Python reader (api/relays.py) open it.
 */
object BackupFormat {

    private val MAGIC = "HUMINTRB".toByteArray() + byteArrayOf(1)
    private const val PBKDF2_ITERATIONS = 310_000
    private val random = SecureRandom()

    class Wrongkey(message: String) : Exception(message)

    /**
     * Write a backup. [files] are produced one at a time, in manifest
     * order, and each must be exactly the length its manifest entry says.
     */
    fun write(
        out: OutputStream,
        meta: JSONObject,
        manifest: JSONObject,
        files: List<() -> ByteArray>,
        pin: CharArray?,
        console: PublicKey?,
        consoleFingerprint: String?,
    ) {
        val key = ByteArray(32).also { random.nextBytes(it) }
        val iv = ByteArray(12).also { random.nextBytes(it) }
        val wraps = JSONArray()
        if (pin != null) {
            val salt = ByteArray(16).also { random.nextBytes(it) }
            val wIv = ByteArray(12).also { random.nextBytes(it) }
            val wrapped = gcm(Cipher.ENCRYPT_MODE, pinKey(pin, salt), wIv).doFinal(key)
            wraps.put(JSONObject().put("kind", "pin").put("iter", PBKDF2_ITERATIONS)
                .put("salt", b64(salt)).put("iv", b64(wIv)).put("key", b64(wrapped)))
        }
        if (console != null) {
            wraps.put(JSONObject().put("kind", "console")
                .put("fingerprint", consoleFingerprint ?: "")
                .put("blob", b64(RelayCrypto.seal(console, key))))
        }
        require(wraps.length() > 0) { "A backup needs at least one way to open it." }
        val header = JSONObject(meta.toString()).put("v", 1).put("wraps", wraps).put("iv", b64(iv))
        val headerBytes = header.toString().toByteArray()

        val raw = DataOutputStream(out)
        raw.write(MAGIC)
        raw.writeInt(headerBytes.size)
        raw.write(headerBytes)
        raw.flush()

        val cipher = gcm(Cipher.ENCRYPT_MODE, key, iv).apply { updateAAD(headerBytes) }
        // CipherOutputStream writes the tag when closed, and closes what it
        // wraps; the caller owns [out], so it is shielded from that close.
        val body = DataOutputStream(CipherOutputStream(Unclosing(out), cipher))
        val m = manifest.toString().toByteArray()
        body.writeInt(m.size)
        body.write(m)
        for (next in files) {
            val bytes = next()
            body.write(bytes)
            java.util.Arrays.fill(bytes, 0)
        }
        body.close()
        java.util.Arrays.fill(key, 0)
        out.flush()
    }

    data class Opened(val header: JSONObject, val manifest: JSONObject, val files: InputStream)

    /**
     * Read a backup's header without opening it — the relay it came from,
     * when it was made, how many reports.
     */
    fun header(input: InputStream): JSONObject {
        val d = DataInputStream(input)
        val magic = ByteArray(MAGIC.size).also { d.readFully(it) }
        if (!magic.contentEquals(MAGIC)) throw IllegalArgumentException("That is not a relay backup.")
        val len = d.readInt()
        require(len in 1..1_000_000) { "That backup's header is damaged." }
        return JSONObject(String(ByteArray(len).also { d.readFully(it) }))
    }

    /**
     * Open with a PIN. The whole body is authenticated before anything is
     * returned: GCM's tag is at the end, so [bytes] is read whole. Restore
     * is a rare, deliberate act on a tablet with memory to spare.
     */
    fun openWithPin(bytes: ByteArray, pin: CharArray): Opened {
        val (header, headerBytes, bodyStart) = parse(bytes)
        val w = (0 until header.getJSONArray("wraps").length())
            .map { header.getJSONArray("wraps").getJSONObject(it) }
            .firstOrNull { it.getString("kind") == "pin" }
            ?: throw Wrongkey("This backup cannot be opened with a PIN — open it at the console.")
        val key = runCatching {
            gcm(Cipher.DECRYPT_MODE, pinKey(pin, unb64(w.getString("salt")), w.optInt("iter", PBKDF2_ITERATIONS)),
                unb64(w.getString("iv"))).doFinal(unb64(w.getString("key")))
        }.getOrElse { throw Wrongkey("That PIN does not open this backup.") }
        return openBody(header, headerBytes, bytes, bodyStart, key)
    }

    /** Open with the console's private key — the JVM test's stand-in for
     *  api/relays.py, so the two readers are held to one format. */
    fun openWithConsoleKey(bytes: ByteArray, priv: java.security.PrivateKey): Opened {
        val (header, headerBytes, bodyStart) = parse(bytes)
        val w = (0 until header.getJSONArray("wraps").length())
            .map { header.getJSONArray("wraps").getJSONObject(it) }
            .first { it.getString("kind") == "console" }
        val key = RelayCrypto.open(priv, unb64(w.getString("blob")))
        return openBody(header, headerBytes, bytes, bodyStart, key)
    }

    private fun parse(bytes: ByteArray): Triple<JSONObject, ByteArray, Int> {
        require(bytes.size > MAGIC.size + 4 && bytes.copyOfRange(0, MAGIC.size).contentEquals(MAGIC)) {
            "That is not a relay backup."
        }
        val len = java.nio.ByteBuffer.wrap(bytes, MAGIC.size, 4).int
        val start = MAGIC.size + 4
        val headerBytes = bytes.copyOfRange(start, start + len)
        return Triple(JSONObject(String(headerBytes)), headerBytes, start + len)
    }

    private fun openBody(header: JSONObject, headerBytes: ByteArray, bytes: ByteArray, bodyStart: Int, key: ByteArray): Opened {
        val plain = runCatching {
            gcm(Cipher.DECRYPT_MODE, key, unb64(header.getString("iv")))
                .apply { updateAAD(headerBytes) }
                .doFinal(bytes, bodyStart, bytes.size - bodyStart)
        }.getOrElse { throw IllegalArgumentException("That backup is damaged or has been altered.") }
        val d = DataInputStream(plain.inputStream())
        val m = ByteArray(d.readInt()).also { d.readFully(it) }
        return Opened(header, JSONObject(String(m)), d)
    }

    private fun pinKey(pin: CharArray, salt: ByteArray, iterations: Int = PBKDF2_ITERATIONS): ByteArray {
        val spec = PBEKeySpec(pin, salt, iterations, 256)
        return SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256").generateSecret(spec).encoded
            .also { spec.clearPassword() }
    }

    private fun gcm(mode: Int, key: ByteArray, iv: ByteArray): Cipher =
        Cipher.getInstance("AES/GCM/NoPadding").apply {
            init(mode, SecretKeySpec(key, "AES"), GCMParameterSpec(128, iv))
        }

    private fun b64(b: ByteArray) = Base64.getEncoder().encodeToString(b)
    private fun unb64(s: String) = Base64.getDecoder().decode(s)

    private class Unclosing(out: OutputStream) : FilterOutputStream(out) {
        override fun write(b: ByteArray, off: Int, len: Int) { out.write(b, off, len) }
        override fun close() { flush() }
    }
}
