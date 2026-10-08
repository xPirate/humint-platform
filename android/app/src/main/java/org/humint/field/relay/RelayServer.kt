package org.humint.field.relay

import org.json.JSONObject
import java.io.BufferedInputStream
import java.io.IOException
import java.io.InputStream
import java.io.OutputStream
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket
import java.net.SocketException
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

/**
 * The console's intake, spoken by a tablet.
 *
 * Three endpoints, the same three the console exposes under /api/intake and
 * nothing else — so a phone that scans a relay's code sends to it with the
 * same Uploader, byte for byte, that it uses for the console:
 *
 *     GET  /api/intake/hello
 *     POST /api/intake/submissions
 *     POST /api/intake/submissions/{id}/files
 *
 * WHY NOT A LIBRARY
 *
 * The usual small embedded server for Android (NanoHTTPD) parses a multipart
 * upload by writing it to a temporary file first — a plaintext copy of a
 * photo of somebody, on disk, in a directory nothing shreds. A full framework
 * (Ktor) would avoid that but brings a dependency tree larger than this
 * whole feature. What phones send is narrow: one JSON body, or one multipart
 * form with a file and two short fields, always with a Content-Length
 * (OkHttp sets it for both). That is a small, closed parser, and every byte
 * of it stays in memory until RelayLanding seals it.
 *
 * One request per connection (Connection: close), a small thread pool, and
 * the console's limits and error wording, so a phone cannot tell — and has
 * no need to know — which of the two it is talking to, except that /hello
 * says "relay": true so it can word its confirmation honestly.
 *
 * Plain java.net, so the tests start a real one on the JVM and hit it with
 * the app's own OkHttp.
 */
class RelayServer(
    private val landing: RelayLanding,
    private val config: Config,
    /** Phone number -> (label, analyst), from the vault while it was open.
     *  May be empty after a cold restart; /hello then just names nobody. */
    private val names: () -> Map<Int, Pair<String?, String?>>,
    private val onReceived: (Event) -> Unit = {},
) {
    data class Config(
        val port: Int = DEFAULT_PORT,
        val maxChars: Int = 20_000,
        val maxFileBytes: Long = 150L * 1024 * 1024,
        val maxSubmissionBytes: Long = 300L * 1024 * 1024,
        val maxFiles: Int = 10,
        val templateVersion: Int = 0,
        val criticalities: List<String> = listOf("Routine", "Priority", "Immediate", "Flash"),
        val ratePerMinute: Int = 30,
    )

    sealed interface Event {
        data class Submission(val deviceId: Int, val id: Int) : Event
        data class File(val deviceId: Int, val submissionId: Int, val bytes: Int) : Event
    }

    @Volatile private var socket: ServerSocket? = null
    private var pool: ExecutorService? = null
    private val rate = ConcurrentHashMap<Int, ArrayDeque<Long>>()

    val running: Boolean get() = socket?.isClosed == false
    val port: Int get() = socket?.localPort ?: config.port

    fun start() {
        if (running) return
        val s = ServerSocket()
        s.reuseAddress = true
        s.bind(InetSocketAddress(config.port))
        socket = s
        val p = Executors.newFixedThreadPool(6)
        pool = p
        Thread({
            while (!s.isClosed) {
                val client = try { s.accept() } catch (e: SocketException) { break } catch (e: IOException) { continue }
                p.execute { handle(client) }
            }
        }, "relay-accept").apply { isDaemon = true }.start()
    }

    fun stop() {
        runCatching { socket?.close() }
        socket = null
        pool?.shutdownNow()
        pool = null
    }

    // ---------------------------------------------------------------- HTTP

    private class Request(
        val method: String, val path: String,
        val headers: Map<String, String>, val body: ByteArray,
    )

    private class Reply(val status: Int, val json: JSONObject)

    private fun handle(client: Socket) {
        client.use { c ->
            c.soTimeout = 120_000
            val reply = try {
                val req = read(BufferedInputStream(c.getInputStream()))
                route(req)
            } catch (e: RelayLanding.Refused) {
                Reply(e.status, detail(e.message))
            } catch (e: HttpError) {
                Reply(e.status, detail(e.message))
            } catch (e: Exception) {
                Reply(500, detail("The relay had an error."))
            }
            runCatching { write(c.getOutputStream(), reply) }
        }
    }

    private class HttpError(val status: Int, message: String) : Exception(message)

    private fun read(input: InputStream): Request {
        val head = readHead(input)
        val lines = head.split("\r\n")
        val parts = lines.first().split(' ')
        if (parts.size < 2) throw HttpError(400, "Bad request.")
        val headers = lines.drop(1).mapNotNull { line ->
            val i = line.indexOf(':')
            if (i <= 0) null else line.substring(0, i).trim().lowercase() to line.substring(i + 1).trim()
        }.toMap()
        if (headers["transfer-encoding"]?.contains("chunked", ignoreCase = true) == true) {
            throw HttpError(411, "Send a Content-Length.")
        }
        val length = headers["content-length"]?.toLongOrNull() ?: 0L
        val cap = config.maxFileBytes + 64 * 1024
        if (length > cap) throw HttpError(413, "That file is larger than ${config.maxFileBytes / (1024 * 1024)} MB.")
        val body = ByteArray(length.toInt())
        var off = 0
        while (off < body.size) {
            val n = input.read(body, off, body.size - off)
            if (n < 0) throw HttpError(400, "The upload was cut off.")
            off += n
        }
        return Request(parts[0].uppercase(), parts[1].substringBefore('?'), headers, body)
    }

    private fun readHead(input: InputStream): String {
        val buf = java.io.ByteArrayOutputStream()
        var matched = 0
        val end = byteArrayOf(13, 10, 13, 10)
        while (true) {
            val b = input.read()
            if (b < 0) throw HttpError(400, "Bad request.")
            buf.write(b)
            matched = if (b.toByte() == end[matched]) matched + 1 else if (b == 13) 1 else 0
            if (matched == 4) break
            if (buf.size() > 16 * 1024) throw HttpError(431, "Headers too large.")
        }
        return buf.toString(Charsets.ISO_8859_1.name()).trimEnd()
    }

    private fun write(out: OutputStream, reply: Reply) {
        val body = reply.json.toString().toByteArray()
        val head = "HTTP/1.1 ${reply.status} ${reason(reply.status)}\r\n" +
            "Content-Type: application/json\r\n" +
            "Content-Length: ${body.size}\r\n" +
            "Connection: close\r\n\r\n"
        out.write(head.toByteArray(Charsets.ISO_8859_1))
        out.write(body)
        out.flush()
    }

    private fun reason(code: Int) = when (code) {
        200 -> "OK"; 201 -> "Created"; 400 -> "Bad Request"; 401 -> "Unauthorized"
        404 -> "Not Found"; 405 -> "Method Not Allowed"; 409 -> "Conflict"; 411 -> "Length Required"
        413 -> "Payload Too Large"; 415 -> "Unsupported Media Type"; 429 -> "Too Many Requests"
        503 -> "Service Unavailable"; else -> "Error"
    }

    private fun detail(message: String?) = JSONObject().put("detail", message ?: "Error.")

    // -------------------------------------------------------------- routes

    private val filesPath = Regex("^/api/intake/submissions/(\\d+)/files$")

    private fun route(req: Request): Reply {
        val token = req.headers["authorization"]
            ?.takeIf { it.startsWith("bearer ", ignoreCase = true) }?.substring(7)?.trim()
        when {
            req.path == "/api/intake/hello" && req.method == "GET" -> {
                val device = landing.authenticate(token)
                    ?: throw HttpError(401, "That device token is not valid.")
                return Reply(200, hello(device))
            }
            req.path == "/api/intake/submissions" && req.method == "POST" -> {
                val device = metered(token)
                return Reply(201, submission(device, req))
            }
            filesPath.matches(req.path) && req.method == "POST" -> {
                val device = metered(token)
                val id = filesPath.find(req.path)!!.groupValues[1].toInt()
                return Reply(201, file(device, id, req))
            }
            req.path.startsWith("/api/intake/") -> throw HttpError(405, "Not here.")
            else -> throw HttpError(404, "Not found.")
        }
    }

    private fun metered(token: String?): Int {
        val device = landing.authenticate(token)
            ?: throw HttpError(401, "That device token is not valid.")
        val now = System.currentTimeMillis()
        val hits = rate.getOrPut(device) { ArrayDeque() }
        synchronized(hits) {
            while (hits.isNotEmpty() && now - hits.first() > 60_000) hits.removeFirst()
            if (hits.size >= config.ratePerMinute) throw HttpError(
                429, "Too many submissions from this device — more than " +
                    "${config.ratePerMinute} in a minute. Wait and retry.")
            hits.addLast(now)
        }
        return device
    }

    private fun hello(device: Int): JSONObject {
        val (label, user) = names()[device] ?: (null to null)
        return JSONObject()
            .put("ok", true)
            .put("relay", true)
            .put("device", label ?: JSONObject.NULL)
            .put("user", user ?: JSONObject.NULL)
            .put("scope", "submit")
            .put("server_time", iso(System.currentTimeMillis()))
            .put("max_chars", config.maxChars)
            .put("max_file_bytes", config.maxFileBytes)
            .put("max_submission_bytes", config.maxSubmissionBytes)
            .put("max_files", config.maxFiles)
            .put("templates", JSONObject().put("version", config.templateVersion))
    }

    private fun submission(device: Int, req: Request): JSONObject {
        if (req.body.size > 2 * 1024 * 1024) throw HttpError(413, "That submission is too large.")
        val json = runCatching { JSONObject(String(req.body, Charsets.UTF_8)) }
            .getOrElse { throw HttpError(400, "That is not a report.") }
        val title = json.optString("title").trim()
        if (title.isEmpty() || title.length > 300) throw HttpError(400, "A report needs a title.")
        val crit = json.optString("criticality").takeIf { it.isNotBlank() && it != "null" }
        if (crit != null && crit !in config.criticalities) {
            throw HttpError(400, "Criticality must be one of ${config.criticalities.joinToString(", ")}.")
        }
        if (json.optString("body").length > config.maxChars) {
            throw HttpError(413, "That submission is longer than ${config.maxChars} characters.")
        }
        val accepted = landing.acceptSubmission(device, json, System.currentTimeMillis())
        if (!accepted.duplicate) onReceived(Event.Submission(device, accepted.id))
        return JSONObject().put("id", accepted.id).put("duplicate", accepted.duplicate)
            .put("status", "new")
    }

    private fun file(device: Int, submissionId: Int, req: Request): JSONObject {
        val type = req.headers["content-type"].orEmpty()
        val boundary = Regex("boundary=\"?([^\";]+)\"?").find(type)?.groupValues?.get(1)
            ?: throw HttpError(400, "Send the file as multipart/form-data.")
        val parts = Multipart.parse(req.body, boundary)
        val filePart = parts.firstOrNull { it.name == "file" }
            ?: throw HttpError(400, "No file in that upload.")
        val mime = (filePart.contentType ?: "application/octet-stream").substringBefore(';').trim().lowercase()
        if (!(mime.startsWith("image/") || mime.startsWith("audio/") || mime.startsWith("video/") ||
              mime == "application/octet-stream" || mime == "text/plain")) {
            throw HttpError(415, "A field device sends pictures, audio and video. This was $mime.")
        }
        if (filePart.data.isEmpty()) throw HttpError(400, "That file is empty.")
        if (filePart.data.size > config.maxFileBytes) {
            throw HttpError(413, "That file is larger than ${config.maxFileBytes / (1024 * 1024)} MB.")
        }
        val clientRef = parts.firstOrNull { it.name == "client_ref" }?.text()
        val duration = parts.firstOrNull { it.name == "duration_ms" }?.text()?.toLongOrNull()
            ?.takeIf { it in 1 until 86_400_000 }
        val accepted = landing.acceptFile(
            deviceId = device, submissionId = submissionId, clientRef = clientRef,
            filename = (filePart.filename ?: "photo").substringAfterLast('/').take(200),
            mime = mime, durationMs = duration, bytes = filePart.data,
            receivedAt = System.currentTimeMillis(),
            maxFiles = config.maxFiles, maxSubmissionBytes = config.maxSubmissionBytes,
        )
        if (!accepted.duplicate) onReceived(Event.File(device, submissionId, filePart.data.size))
        return JSONObject().put("id", accepted.id).put("duplicate", accepted.duplicate)
            .put("bytes", filePart.data.size)
    }

    private fun iso(ms: Long): String =
        SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US)
            .apply { timeZone = TimeZone.getTimeZone("UTC") }.format(Date(ms))

    companion object {
        const val DEFAULT_PORT = 8787
    }
}

/** Just enough multipart/form-data for what the Field app sends. */
internal object Multipart {
    class Part(val name: String?, val filename: String?, val contentType: String?, val data: ByteArray) {
        fun text(): String = String(data, Charsets.UTF_8).trim()
    }

    fun parse(body: ByteArray, boundary: String): List<Part> {
        val delim = ("--$boundary").toByteArray(Charsets.ISO_8859_1)
        val out = mutableListOf<Part>()
        var pos = indexOf(body, delim, 0)
        while (pos >= 0) {
            var start = pos + delim.size
            // "--" right after a delimiter ends the body.
            if (start + 1 < body.size && body[start] == '-'.code.toByte() && body[start + 1] == '-'.code.toByte()) break
            if (start + 1 < body.size && body[start] == 13.toByte() && body[start + 1] == 10.toByte()) start += 2
            val next = indexOf(body, delim, start)
            if (next < 0) break
            // The part ends with CRLF before the next delimiter.
            val end = if (next >= 2 && body[next - 2] == 13.toByte() && body[next - 1] == 10.toByte()) next - 2 else next
            val headEnd = indexOf(body, byteArrayOf(13, 10, 13, 10), start)
            if (headEnd in start until end) {
                val head = String(body, start, headEnd - start, Charsets.UTF_8)
                val headers = head.split("\r\n").mapNotNull {
                    val i = it.indexOf(':'); if (i <= 0) null else it.substring(0, i).trim().lowercase() to it.substring(i + 1).trim()
                }.toMap()
                val disp = headers["content-disposition"].orEmpty()
                val name = Regex("\\bname=\"([^\"]*)\"").find(disp)?.groupValues?.get(1)
                val filename = Regex("\\bfilename=\"([^\"]*)\"").find(disp)?.groupValues?.get(1)
                out += Part(name, filename, headers["content-type"], body.copyOfRange(headEnd + 4, end))
            }
            pos = next
        }
        return out
    }

    fun indexOf(hay: ByteArray, needle: ByteArray, from: Int): Int {
        if (needle.isEmpty()) return from
        val first = needle[0]
        var i = from
        val last = hay.size - needle.size
        while (i <= last) {
            if (hay[i] == first) {
                var j = 1
                while (j < needle.size && hay[i + j] == needle[j]) j++
                if (j == needle.size) return i
            }
            i++
        }
        return -1
    }
}
