package org.humint.field.relay

import java.nio.ByteBuffer
import java.security.KeyFactory
import java.security.KeyPair
import java.security.KeyPairGenerator
import java.security.PrivateKey
import java.security.PublicKey
import java.security.SecureRandom
import java.security.spec.ECGenParameterSpec
import java.security.spec.PKCS8EncodedKeySpec
import java.security.spec.X509EncodedKeySpec
import javax.crypto.Cipher
import javax.crypto.KeyAgreement
import javax.crypto.Mac
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

/**
 * Sealing what arrives at a relay so the relay itself cannot read it back.
 *
 * WHY A PUBLIC KEY
 *
 * A relay serves all night in a hotel room with its screen off, and the
 * vault — the PIN-wrapped key everything else in this app is encrypted
 * under — locks ninety seconds after the screen goes dark. So the server
 * cannot use the vault key to encrypt what phones send: it does not have it,
 * and keeping the vault open all night would undo the reason it locks.
 *
 * Instead the relay holds a key pair. The public half sits on disk in the
 * clear; the private half is sealed under the vault key. Anything a phone
 * sends is encrypted to the public key the moment it arrives. The server can
 * write a report and can never read one back — only someone who unlocks the
 * relay with a team PIN gets the private key, and with it the reports. A
 * relay seized while serving holds nothing readable without a PIN.
 *
 * THE CONSTRUCTION
 *
 * ECIES in its plainest form, on P-256 because every Android since 4.x has
 * it in the platform provider (no Bouncy Castle, no native code):
 *
 *     ephemeral key pair e
 *     shared = ECDH(e.private, relay.public)
 *     key    = HKDF-SHA256(shared, salt = e.public, info = "humint-relay-v1")
 *     blob   = len(e.public) | e.public | iv | AES-256-GCM(key, iv, plain)
 *
 * A fresh ephemeral key per blob means no two blobs share a key, so the
 * random 96-bit GCM nonce never has to be unique across blobs, only within
 * one — which it trivially is.
 *
 * Plain JCA throughout, so the unit tests run this exact code on the JVM.
 */
object RelayCrypto {

    private const val CURVE = "secp256r1"
    private const val IV_BYTES = 12
    private const val TAG_BITS = 128
    private val INFO = "humint-relay-v1".toByteArray()
    private val random = SecureRandom()

    fun newKeyPair(): KeyPair =
        KeyPairGenerator.getInstance("EC").apply { initialize(ECGenParameterSpec(CURVE), random) }
            .generateKeyPair()

    fun publicFrom(encoded: ByteArray): PublicKey =
        KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(encoded))

    fun privateFrom(encoded: ByteArray): PrivateKey =
        KeyFactory.getInstance("EC").generatePrivate(PKCS8EncodedKeySpec(encoded))

    fun seal(recipient: PublicKey, plain: ByteArray): ByteArray {
        val eph = newKeyPair()
        val ephPub = eph.public.encoded
        val key = derive(eph.private, recipient, ephPub)
        val iv = ByteArray(IV_BYTES).also { random.nextBytes(it) }
        val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply {
            init(Cipher.ENCRYPT_MODE, SecretKeySpec(key, "AES"), GCMParameterSpec(TAG_BITS, iv))
        }
        val body = cipher.doFinal(plain)
        return ByteBuffer.allocate(2 + ephPub.size + IV_BYTES + body.size)
            .putShort(ephPub.size.toShort()).put(ephPub).put(iv).put(body).array()
    }

    /** Throws on a wrong key or a damaged blob — GCM cannot tell them apart,
     *  and the caller treats both as "this one cannot be read". */
    fun open(own: PrivateKey, sealed: ByteArray): ByteArray {
        val buf = ByteBuffer.wrap(sealed)
        val ephLen = buf.short.toInt()
        require(ephLen in 1..512 && sealed.size > 2 + ephLen + IV_BYTES) { "Not a relay blob." }
        val ephPub = ByteArray(ephLen).also { buf.get(it) }
        val iv = ByteArray(IV_BYTES).also { buf.get(it) }
        val body = ByteArray(buf.remaining()).also { buf.get(it) }
        val key = derive(own, publicFrom(ephPub), ephPub)
        return Cipher.getInstance("AES/GCM/NoPadding").apply {
            init(Cipher.DECRYPT_MODE, SecretKeySpec(key, "AES"), GCMParameterSpec(TAG_BITS, iv))
        }.doFinal(body)
    }

    private fun derive(mine: PrivateKey, theirs: PublicKey, salt: ByteArray): ByteArray {
        val shared = KeyAgreement.getInstance("ECDH").apply {
            init(mine); doPhase(theirs, true)
        }.generateSecret()
        return hkdf(shared, salt, INFO, 32)
    }

    /** RFC 5869, one block — 32 bytes out of SHA-256 is exactly one. */
    internal fun hkdf(ikm: ByteArray, salt: ByteArray, info: ByteArray, length: Int): ByteArray {
        require(length <= 32)
        val prk = Mac.getInstance("HmacSHA256").apply { init(SecretKeySpec(salt, "HmacSHA256")) }
            .doFinal(ikm)
        val okm = Mac.getInstance("HmacSHA256").apply { init(SecretKeySpec(prk, "HmacSHA256")) }
            .run { update(info); update(1); doFinal() }
        return okm.copyOf(length)
    }
}
