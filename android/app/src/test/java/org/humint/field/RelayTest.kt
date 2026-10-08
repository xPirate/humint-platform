package org.humint.field

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.humint.field.relay.RelayCrypto
import org.humint.field.relay.RelayLanding
import org.humint.field.relay.RelayServer
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test
import java.io.File
import java.net.ServerSocket
import java.nio.file.Files

/**
 * The relay, end to end on the JVM: a real server on a real socket, and the
 * same requests the phone's Uploader makes, through the same OkHttp.
 */
class RelayTest {

    private lateinit var dir: File
    private lateinit var landing: RelayLanding
    private lateinit var server: RelayServer
    private val keys = RelayCrypto.newKeyPair()
    private val client = OkHttpClient()
    private var base = ""
    private var token = ""
    private var deviceId = 0

    @Before fun up() {
        dir = Files.createTempDirectory("relay").toFile()
        landing = RelayLanding(dir)
        landing.setPublicKey(keys.public)
        token = RelayLanding.newToken()
        deviceId = landing.addDevice(token)
        val port = ServerSocket(0).use { it.localPort }
        server = RelayServer(landing, RelayServer.Config(port = port, templateVersion = 2),
                             names = { mapOf(deviceId to ("Phone 3" to "jordan")) })
        server.start()
        base = "http://127.0.0.1:$port"
    }

    @After fun down() { server.stop(); dir.deleteRecursively() }

    // ---------------------------------------------------------------- crypto

    @Test fun sealedBlobsOpenOnlyWithTheRightKey() {
        val plain = "a photo of a van".toByteArray()
        val sealed = RelayCrypto.seal(keys.public, plain)
        assertArrayEquals(plain, RelayCrypto.open(keys.private, sealed))
        // Two seals of the same bytes differ: fresh ephemeral key each time.
        assertFalse(sealed.contentEquals(RelayCrypto.seal(keys.public, plain)))
        try {
            RelayCrypto.open(RelayCrypto.newKeyPair().private, sealed)
            fail("opened with the wrong key")
        } catch (_: Exception) { }
    }

    @Test fun nothingLandsInTheClear() {
        post("/api/intake/submissions", JSONObject().put("title", "Blue Transit van, plate KX7")
            .put("client_ref", "r1"))
        val onDisk = dir.walkTopDown().filter { it.isFile }.joinToString("") { it.readBytes().toString(Charsets.ISO_8859_1) }
        assertFalse(onDisk.contains("Transit"))
        assertFalse(onDisk.contains("KX7"))
    }

    // ------------------------------------------------------------ protocol

    @Test fun helloSaysItIsARelayAndWhoIsAsking() {
        val r = get("/api/intake/hello")
        assertEquals(200, r.first)
        assertTrue(r.second.getBoolean("relay"))
        assertEquals("Phone 3", r.second.getString("device"))
        assertEquals(2, r.second.getJSONObject("templates").getInt("version"))
    }

    @Test fun aWrongOrRevokedTokenGetsTheSame401() {
        assertEquals(401, get("/api/intake/hello", "nope").first)
        landing.revokeDevice(deviceId)
        assertEquals(401, get("/api/intake/hello").first)
    }

    @Test fun aRetryWithTheSameRefIsTheSameReport() {
        val body = JSONObject().put("title", "North gate").put("client_ref", "abc")
        val first = post("/api/intake/submissions", body)
        val again = post("/api/intake/submissions", body)
        assertEquals(201, first.first)
        assertEquals(first.second.getInt("id"), again.second.getInt("id"))
        assertTrue(again.second.getBoolean("duplicate"))
    }

    @Test fun aReportNeedsATitleAndAKnownCriticality() {
        assertEquals(400, post("/api/intake/submissions", JSONObject().put("title", "")).first)
        assertEquals(400, post("/api/intake/submissions",
            JSONObject().put("title", "x").put("criticality", "Whenever")).first)
    }

    @Test fun aPhotoTravelsWithItsReportAndComesOutWhole() {
        val sub = post("/api/intake/submissions", JSONObject().put("title", "Depot").put("client_ref", "s1"))
        val id = sub.second.getInt("id")
        val photo = ByteArray(300_000) { (it % 251).toByte() }
        val up = upload(id, photo, "IMG_1.jpg", "image/jpeg", "f1")
        assertEquals(201, up.first)
        // Same file again: acknowledged, not stored twice.
        assertTrue(upload(id, photo, "IMG_1.jpg", "image/jpeg", "f1").second.getBoolean("duplicate"))

        val seen = mutableListOf<RelayLanding.Landed>()
        val result = landing.drain(keys.private) { seen += it; true }
        assertEquals(2, result.moved)
        assertEquals("submission", seen[0].kind)
        assertEquals("Depot", seen[0].header.getJSONObject("submission").getString("title"))
        assertEquals("file", seen[1].kind)
        assertEquals("IMG_1.jpg", seen[1].header.getString("filename"))
        assertArrayEquals(photo, seen[1].content)
        assertEquals(0, landing.pendingCount())
    }

    @Test fun aPhoneCannotAttachToAnotherPhonesReport() {
        val sub = post("/api/intake/submissions", JSONObject().put("title", "Mine"))
        val other = RelayLanding.newToken()
        landing.addDevice(other)
        val r = upload(sub.second.getInt("id"), byteArrayOf(1, 2, 3), "x.jpg", "image/jpeg", "z", other)
        assertEquals(404, r.first)
    }

    @Test fun onlyMediaIsAccepted() {
        val sub = post("/api/intake/submissions", JSONObject().put("title", "x"))
        assertEquals(415, upload(sub.second.getInt("id"), byteArrayOf(1), "a.exe",
                                 "application/x-msdownload", "q").first)
    }

    @Test fun aFailedMoveLeavesTheItemForNextTime() {
        post("/api/intake/submissions", JSONObject().put("title", "Keep me"))
        landing.drain(keys.private) { false }
        assertEquals(1, landing.pendingCount())
    }

    @Test fun unknownPathsAreNotServed() {
        val r = client.newCall(Request.Builder().url("$base/api/entities").get().build()).execute()
        assertEquals(404, r.code)
        r.close()
    }

    @Test fun anUnsetRelayRefusesRatherThanStoringInTheClear() {
        val bare = RelayLanding(Files.createTempDirectory("bare").toFile())
        val t = RelayLanding.newToken()
        val id = bare.addDevice(t)
        try {
            bare.acceptSubmission(id, JSONObject().put("title", "x"), 0L)
            fail("accepted with no key")
        } catch (e: RelayLanding.Refused) { assertEquals(503, e.status) }
        assertNull(bare.publicKey())
    }

    // ---------------------------------------------------------------- backup

    private fun sampleBackup(pin: CharArray, console: java.security.KeyPair): ByteArray {
        val photo = ByteArray(5000) { (it * 7).toByte() }
        val manifest = JSONObject().put("reports", org.json.JSONArray().put(
            JSONObject().put("title", "Depot gate").put("relay_submission_id", 4).put("relay_device_id", 2)
                .put("phone_label", "Sonim 2").put("analyst_name", "R. Ortiz").put("client_ref", "c-4")
                .put("fields", JSONObject().put("place_name", "Depot"))
                .put("files", org.json.JSONArray().put(JSONObject().put("filename", "gate.jpg")
                    .put("mime", "image/jpeg").put("client_ref", "f-9").put("length", photo.size)))))
        val out = java.io.ByteArrayOutputStream()
        org.humint.field.relay.BackupFormat.write(
            out, JSONObject().put("relay_id", 1).put("label", "Team Alpha tablet").put("reports", 1),
            manifest, listOf { photo.copyOf() }, pin, console.public, "AAAA BBBB")
        return out.toByteArray()
    }

    @Test fun aBackupOpensWithThePinAndWithTheConsoleKey() {
        val console = RelayCrypto.newKeyPair()
        val bytes = sampleBackup("483920".toCharArray(), console)
        val a = org.humint.field.relay.BackupFormat.openWithPin(bytes, "483920".toCharArray())
        assertEquals("Depot gate", a.manifest.getJSONArray("reports").getJSONObject(0).getString("title"))
        assertArrayEquals(ByteArray(5000) { (it * 7).toByte() }, a.files.readBytes())
        val b = org.humint.field.relay.BackupFormat.openWithConsoleKey(bytes, console.private)
        assertEquals("Team Alpha tablet", b.header.getString("label"))
        assertFalse(String(bytes, Charsets.ISO_8859_1).contains("Depot gate"))

        // Kept for the console's reader to open too (see the Python cross-check).
        val dir = File("build/relay-backup-sample").apply { mkdirs() }
        File(dir, "sample.hrb").writeBytes(bytes)
        File(dir, "console-key.pk8").writeBytes(console.private.encoded)
    }

    @Test fun theWrongPinDoesNotOpenABackup() {
        val bytes = sampleBackup("483920".toCharArray(), RelayCrypto.newKeyPair())
        try {
            org.humint.field.relay.BackupFormat.openWithPin(bytes, "000000".toCharArray())
            fail("opened with the wrong PIN")
        } catch (e: org.humint.field.relay.BackupFormat.Wrongkey) { }
    }

    @Test fun anEditedHeaderBreaksTheWholeBackup() {
        val bytes = sampleBackup("483920".toCharArray(), RelayCrypto.newKeyPair())
        val text = String(bytes, Charsets.ISO_8859_1).replace("Team Alpha tablet", "Team Omega tablet")
        try {
            org.humint.field.relay.BackupFormat.openWithPin(text.toByteArray(Charsets.ISO_8859_1), "483920".toCharArray())
            fail("opened after the header was edited")
        } catch (e: IllegalArgumentException) { }
    }

    // --------------------------------------------------------------- helpers

    private fun get(path: String, t: String = token): Pair<Int, JSONObject> =
        client.newCall(Request.Builder().url(base + path).header("Authorization", "Bearer $t").get().build())
            .execute().use { it.code to JSONObject(it.body!!.string()) }

    private fun post(path: String, body: JSONObject, t: String = token): Pair<Int, JSONObject> =
        client.newCall(Request.Builder().url(base + path).header("Authorization", "Bearer $t")
            .post(body.toString().toRequestBody("application/json; charset=utf-8".toMediaType())).build())
            .execute().use { it.code to JSONObject(it.body!!.string()) }

    private fun upload(id: Int, bytes: ByteArray, name: String, mime: String, ref: String,
                       t: String = token): Pair<Int, JSONObject> {
        val body = MultipartBody.Builder().setType(MultipartBody.FORM)
            .addFormDataPart("client_ref", ref)
            .addFormDataPart("file", name, bytes.toRequestBody(mime.toMediaType()))
            .build()
        return client.newCall(Request.Builder().url("$base/api/intake/submissions/$id/files")
            .header("Authorization", "Bearer $t").post(body).build())
            .execute().use { it.code to JSONObject(it.body!!.string()) }
    }
}
