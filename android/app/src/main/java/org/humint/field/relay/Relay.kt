package org.humint.field.relay

import android.content.Context
import android.content.Intent
import androidx.core.content.ContextCompat
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import org.humint.field.data.Crypto
import java.io.File
import java.net.Inet4Address
import java.net.NetworkInterface
import java.security.PrivateKey

/**
 * The relay, as the rest of the app sees it.
 *
 * A tablet in relay mode collects reports from the team's phones over its
 * own hotspot, using the same protocol the console speaks, and holds them
 * until the lead syncs them home. See docs/how-to/field-relay.md for the
 * deployment, and RelayCrypto for why what arrives is sealed to a public
 * key rather than the vault's.
 */
object Relay {

    data class Address(val iface: String, val ip: String) {
        val url: String get() = "http://$ip:${RelayServer.DEFAULT_PORT}"
    }

    data class State(
        val running: Boolean = false,
        val startedAt: Long = 0L,
        /** Reports received since the server started. */
        val received: Int = 0,
        val lastReceivedAt: Long = 0L,
        val problem: String? = null,
    )

    private val _state = MutableStateFlow(State())
    val state: StateFlow<State> = _state

    internal fun update(change: (State) -> State) { _state.value = change(_state.value) }

    /** Fired for every new report or file, so an open vault can move it in
     *  at once rather than at the next unlock. */
    private val _arrivals = MutableSharedFlow<RelayServer.Event>(extraBufferCapacity = 64)
    val arrivals: SharedFlow<RelayServer.Event> = _arrivals
    internal fun arrived(e: RelayServer.Event) { _arrivals.tryEmit(e) }

    /** Phone number -> (label, analyst). Set from the vault while it is
     *  open; the server only uses it to answer /hello by name. */
    val names = MutableStateFlow<Map<Int, Pair<String?, String?>>>(emptyMap())

    fun dir(context: Context): File = File(context.filesDir, "relay")
    fun landing(context: Context) = RelayLanding(dir(context))
    private fun privFile(context: Context) = File(dir(context), "priv.sealed")

    /** Whether this install has relay keys at all. */
    fun isSetUp(context: Context): Boolean =
        landing(context).hasKey() && privFile(context).exists()

    /**
     * Make the relay's key pair. The vault must be open: the private half
     * is sealed under the vault key, so only a team PIN ever opens it.
     */
    fun ensureKeys(context: Context) {
        if (isSetUp(context)) return
        val pair = RelayCrypto.newKeyPair()
        val sealed = Crypto.sealBytes(context, pair.private.encoded)
        dir(context).mkdirs()
        privFile(context).writeBytes(sealed)
        landing(context).setPublicKey(pair.public)
    }

    /** The private key, or null while the vault is shut. */
    fun privateKey(context: Context): PrivateKey? = runCatching {
        RelayCrypto.privateFrom(Crypto.openBytes(context, privFile(context).readBytes()))
    }.getOrNull()

    fun start(context: Context): String? = runCatching {
        if (!isSetUp(context)) return "Open the relay with a team PIN once to set it up."
        ContextCompat.startForegroundService(context,
            Intent(context, RelayService::class.java).setAction(RelayService.ACTION_START))
        null
    }.getOrElse { "Could not start the relay: ${it.message}" }

    fun stop(context: Context) {
        runCatching {
            context.startService(Intent(context, RelayService::class.java)
                .setAction(RelayService.ACTION_STOP))
        }
    }

    /**
     * Where phones can reach this tablet. The hotspot's own address first:
     * that is the network the phones are told to join. Mobile data and VPN
     * interfaces are left out — a phone on the hotspot cannot reach them,
     * and putting the tablet's carrier address in a QR code helps nobody.
     */
    fun addresses(): List<Address> = runCatching {
        NetworkInterface.getNetworkInterfaces().toList()
            .filter { it.isUp && !it.isLoopback }
            .filterNot { n -> listOf("rmnet", "tun", "ppp", "ccmni", "dummy", "ipsec").any { n.name.startsWith(it) } }
            .flatMap { n -> n.inetAddresses.toList().filterIsInstance<Inet4Address>().map { Address(n.name, it.hostAddress ?: "") } }
            .filter { it.ip.isNotBlank() }
            .sortedBy { a ->
                when {
                    a.iface.startsWith("swlan") || a.iface.startsWith("ap") -> 0   // Samsung / AOSP hotspot
                    a.iface == "wlan1" -> 1
                    a.iface.startsWith("wlan") -> 2
                    else -> 3
                }
            }
    }.getOrDefault(emptyList())

    /** The enrollment code a phone scans. The same shape the console's
     *  code has, so the phone needs nothing new to read it. */
    fun enrollmentPayload(address: Address, token: String, label: String, analyst: String): String =
        org.json.JSONObject()
            .put("v", 1).put("url", address.url).put("token", token)
            .put("label", label).put("user", analyst).put("relay", true)
            .toString()

    /** Erase-and-start-again, and the duress PIN: every key, every phone,
     *  everything unopened. What the vault holds goes with the vault. */
    fun wipe(context: Context) {
        stop(context)
        landing(context).wipe()
        RelayLanding.shred(privFile(context))
        names.value = emptyMap()
        _state.value = State()
    }
}
