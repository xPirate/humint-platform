package org.humint.field.track

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import org.humint.field.data.Crypto
import java.io.ByteArrayOutputStream
import java.io.DataInputStream
import java.io.DataOutputStream
import java.io.EOFException
import java.io.File
import java.io.FileOutputStream
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * Where a recording writes its points while the phone is in a pocket.
 *
 * WHY NOT THE QUEUE ITSELF
 *
 * The queue's database is keyed by the PIN (see data/Vault.kt) and closes
 * when the app locks, ninety seconds after it leaves the screen. A route is
 * recorded with the screen off for an hour. So the recorder cannot write to
 * the queue while it runs -- there is no key -- and holding the vault open
 * for the length of a walk would undo the reason it locks.
 *
 * WHAT IT DOES INSTEAD
 *
 * Each point is sealed on its own, as it arrives, with AES-GCM under a key
 * that lives in the Android keystore and never leaves it (hardware-backed on
 * the fleet). The file is in the app's private storage and excluded from
 * backup. When the analyst next has the vault open, the points are moved
 * into the report -- under the PIN, like everything else -- and this file is
 * shredded.
 *
 * WHAT THAT IS WORTH, HONESTLY
 *
 * Weaker than the queue, for as long as a recording is running or waiting to
 * be merged: the keystore key needs this handset but not the PIN. A copy of
 * the app's files is useless without the phone; the phone itself, unlocked
 * by someone with root, could decrypt a track that has not been merged yet.
 * Stopping a recording and opening the app moves it under the PIN. The
 * how-to says so.
 */
object TrackBuffer {

    private const val KEYSTORE = "AndroidKeyStore"
    private const val KEY_ALIAS = "humint-field-track"
    private const val GCM_TAG_BITS = 128
    private const val IV_BYTES = 12

    private fun dir(context: Context): File = File(context.filesDir, "track").apply { mkdirs() }

    fun file(context: Context, reportId: String): File =
        File(dir(context), "${reportId.filter { it.isLetterOrDigit() || it == '-' }}.trk")

    /** Report ids with points waiting to be merged. */
    fun pending(context: Context): List<String> =
        dir(context).listFiles()?.filter { it.name.endsWith(".trk") && it.length() > 0 }
            ?.map { it.name.removeSuffix(".trk") }.orEmpty()

    @Synchronized
    fun append(context: Context, reportId: String, p: TrackPoint) {
        val plain = ByteArrayOutputStream(40).also { bytes ->
            DataOutputStream(bytes).use { out ->
                out.writeDouble(p.lat)
                out.writeDouble(p.lon)
                out.writeLong(p.timeMs)
                out.writeFloat(p.accuracyM)
                out.writeDouble(p.altitudeM ?: Double.NaN)
            }
        }.toByteArray()
        val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply {
            init(Cipher.ENCRYPT_MODE, key())
        }
        val sealed = cipher.iv + cipher.doFinal(plain)
        // Appended and flushed per point: a process killed mid-walk loses at
        // most the point it was writing, never the ones before it.
        FileOutputStream(file(context, reportId), true).use { fos ->
            DataOutputStream(fos).use { out ->
                out.writeInt(sealed.size)
                out.write(sealed)
            }
            fos.fd.sync()
        }
    }

    /** Every point recorded for this report, oldest first. A damaged record
     *  (the write that was cut off by the battery dying) ends the read; the
     *  points before it are kept. */
    @Synchronized
    fun read(context: Context, reportId: String): List<TrackPoint> {
        val f = file(context, reportId)
        if (!f.exists()) return emptyList()
        val out = mutableListOf<TrackPoint>()
        DataInputStream(f.inputStream().buffered()).use { input ->
            while (true) {
                val len = try { input.readInt() } catch (e: EOFException) { break }
                if (len <= IV_BYTES || len > 4096) break
                val sealed = ByteArray(len)
                try { input.readFully(sealed) } catch (e: EOFException) { break }
                val plain = runCatching {
                    Cipher.getInstance("AES/GCM/NoPadding").apply {
                        init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(GCM_TAG_BITS, sealed, 0, IV_BYTES))
                    }.doFinal(sealed, IV_BYTES, sealed.size - IV_BYTES)
                }.getOrNull() ?: break
                DataInputStream(plain.inputStream()).use { d ->
                    val lat = d.readDouble()
                    val lon = d.readDouble()
                    val time = d.readLong()
                    val acc = d.readFloat()
                    val alt = d.readDouble()
                    out += TrackPoint(lat, lon, time, acc, if (alt.isNaN()) null else alt)
                }
            }
        }
        return out
    }

    @Synchronized
    fun discard(context: Context, reportId: String) {
        Crypto.shred(file(context, reportId))
    }

    /** Erase-and-start-again: every buffer and the key that opens them. */
    fun destroyAll(context: Context) {
        dir(context).listFiles()?.forEach { Crypto.shred(it) }
        runCatching {
            KeyStore.getInstance(KEYSTORE).apply { load(null) }.deleteEntry(KEY_ALIAS)
        }
    }

    private fun key(): SecretKey {
        val store = KeyStore.getInstance(KEYSTORE).apply { load(null) }
        (store.getEntry(KEY_ALIAS, null) as? KeyStore.SecretKeyEntry)?.let { return it.secretKey }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, KEYSTORE)
        generator.init(
            KeyGenParameterSpec.Builder(
                KEY_ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .build())
        return generator.generateKey()
    }
}
