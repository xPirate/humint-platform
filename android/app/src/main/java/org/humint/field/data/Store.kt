package org.humint.field.data

import android.content.Context
import androidx.room.ColumnInfo
import androidx.room.Dao
import androidx.room.Database
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.PrimaryKey
import androidx.room.Query
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.Update
import kotlinx.coroutines.flow.Flow
import net.zetetic.database.sqlcipher.SupportOpenHelperFactory
import java.io.File
import java.util.UUID

/**
 * The queue, on disk, encrypted.
 *
 * A report exists here from the moment the analyst starts typing. Nothing is
 * held only in memory and lost when the phone is put in a pocket and the
 * process is killed — which, on a modern Android, is most times.
 *
 * [clientRef] is generated once, when the draft is created, and never
 * changes. It is what makes a retry idempotent on the console: an upload
 * interrupted after the server committed but before the app heard back
 * resends the same ref and lands as the same report. This is the single most
 * important field in the schema and the reason it is a UUID assigned at
 * draft time rather than at upload time.
 */
@Entity(tableName = "reports")
data class ReportRow(
    @PrimaryKey val id: String = UUID.randomUUID().toString(),
    @ColumnInfo(name = "client_ref") val clientRef: String = UUID.randomUUID().toString(),
    val template: String,
    val title: String,
    /** The template's fields, as a JSON object. Parsed with org.json. */
    val fields: String,
    val criticality: String?,
    val body: String?,
    @ColumnInfo(name = "observed_at") val observedAt: Long?,
    val lat: Double?,
    val lng: Double?,
    @ColumnInfo(name = "location_accuracy_m") val accuracyM: Float?,
    @ColumnInfo(name = "location_note") val locationNote: String?,
    /** draft | ready | sent */
    val status: String = "draft",
    @ColumnInfo(name = "created_at") val createdAt: Long = System.currentTimeMillis(),
    @ColumnInfo(name = "updated_at") val updatedAt: Long = System.currentTimeMillis(),
    /** What the console said when it last refused or failed. Shown, not hidden. */
    @ColumnInfo(name = "last_error") val lastError: String? = null,
    /**
     * A route walked with the recorder or the corners of an area, as GeoJSON
     * ([lon, lat]). Null for every other kind of report. See track/Track.kt.
     */
    val geometry: String? = null,
)

/**
 * A photo, clip or memo. Usually it belongs to a report; a row whose
 * [reportId] is [AttachmentRow.UNFILED] is a **quick capture** — taken from
 * the camera button before any report existed, waiting to be filed to one.
 * The empty string rather than null keeps the schema as it was (no
 * migration), and no report can ever have an empty id, so nothing can
 * collide with it. The uploader reads attachments per report, so an
 * unfiled capture can never leave the phone.
 */
@Entity(tableName = "attachments")
data class AttachmentRow(
    @PrimaryKey val id: String = UUID.randomUUID().toString(),
    @ColumnInfo(name = "report_id") val reportId: String,
    @ColumnInfo(name = "client_ref") val clientRef: String = UUID.randomUUID().toString(),
    /** image | audio | video */
    val kind: String,
    val filename: String,
    @ColumnInfo(name = "mime_type") val mimeType: String,
    /** Absolute path in the app's sandbox. The file itself is encrypted. */
    val path: String,
    @ColumnInfo(name = "size_bytes") val sizeBytes: Long,
    @ColumnInfo(name = "duration_ms") val durationMs: Long? = null,
    /** Set once the console has this file, so a resumed upload skips it. */
    val sent: Boolean = false,
) {
    companion object { const val UNFILED = "" }
}

/** How many attachments each report has, for the queue cards. */
data class AttachmentCount(
    @ColumnInfo(name = "report_id") val reportId: String,
    val n: Int,
)

// ------------------------------------------------------------- relay (1.7)
//
// What a relay has opened. Reports arrive sealed to the relay's public key
// (relay/RelayLanding.kt) because the vault is shut while it serves; when
// the team unlocks it, each is opened and moved here, under the PIN like
// everything else. The relay's own numbering is kept as the key, because a
// phone retrying a file upload names the report by that number.

@Entity(tableName = "relay_submissions")
data class RelaySubmissionRow(
    @PrimaryKey val id: Int,
    @ColumnInfo(name = "device_id") val deviceId: Int,
    @ColumnInfo(name = "received_at") val receivedAt: Long,
    val title: String,
    val body: String?,
    val criticality: String?,
    /** As the phone sent it: ISO 8601 UTC. */
    @ColumnInfo(name = "observed_at") val observedAt: String?,
    val lat: Double?,
    val lng: Double?,
    @ColumnInfo(name = "location_accuracy_m") val accuracyM: Double?,
    @ColumnInfo(name = "location_note") val locationNote: String?,
    @ColumnInfo(name = "client_ref") val clientRef: String?,
    val template: String?,
    @ColumnInfo(name = "template_version") val templateVersion: Int?,
    /** The template's fields, as the JSON object the phone sent. */
    val fields: String,
    val geometry: String?,
    /** The lead's priority tags, a JSON array of priority ids (1.7 phase 4). */
    val priorities: String? = null,
    @ColumnInfo(name = "lead_note") val leadNote: String? = null,
    /** Set once the console has confirmed this report on a Sync. */
    @ColumnInfo(name = "forwarded_at") val forwardedAt: Long? = null,
)

@Entity(tableName = "relay_files")
data class RelayFileRow(
    @PrimaryKey val id: Int,
    @ColumnInfo(name = "submission_id") val submissionId: Int,
    @ColumnInfo(name = "client_ref") val clientRef: String?,
    val filename: String,
    @ColumnInfo(name = "mime_type") val mimeType: String,
    /** Re-sealed under the vault key, in the app's media directory. */
    val path: String,
    @ColumnInfo(name = "size_bytes") val sizeBytes: Long,
    @ColumnInfo(name = "duration_ms") val durationMs: Long?,
    val forwarded: Boolean = false,
)

/** A phone this relay takes reports from. The token's hash lives outside
 *  the vault (RelayLanding's devices.idx) so the server can check it while
 *  locked; the names live here, behind the PIN. */
@Entity(tableName = "relay_devices")
data class RelayDeviceRow(
    @PrimaryKey val id: Int,
    val label: String,
    val analyst: String,
    @ColumnInfo(name = "created_at") val createdAt: Long,
    val revoked: Boolean = false,
    /** The analyst's console account, when the relay was provisioned with
     *  the team's roster (phase 2). */
    @ColumnInfo(name = "console_user_id") val consoleUserId: Int? = null,
)

@Dao
interface RelayDao {
    @Query("SELECT * FROM relay_submissions ORDER BY received_at DESC")
    fun submissions(): Flow<List<RelaySubmissionRow>>

    @Query("SELECT * FROM relay_submissions WHERE id = :id")
    fun submissionFlow(id: Int): Flow<RelaySubmissionRow?>

    @Query("SELECT * FROM relay_submissions WHERE id = :id")
    suspend fun submission(id: Int): RelaySubmissionRow?

    @Query("SELECT * FROM relay_submissions WHERE forwarded_at IS NULL ORDER BY received_at ASC")
    suspend fun unforwarded(): List<RelaySubmissionRow>

    @androidx.room.Insert(onConflict = androidx.room.OnConflictStrategy.IGNORE)
    suspend fun insert(row: RelaySubmissionRow)

    @Update suspend fun update(row: RelaySubmissionRow)

    @Query("SELECT * FROM relay_files WHERE submission_id = :id ORDER BY id")
    fun filesFlow(id: Int): Flow<List<RelayFileRow>>

    @Query("SELECT * FROM relay_files WHERE submission_id = :id ORDER BY id")
    suspend fun files(id: Int): List<RelayFileRow>

    @Query("SELECT submission_id AS report_id, count(*) AS n FROM relay_files GROUP BY submission_id")
    fun fileCounts(): Flow<List<AttachmentCount>>

    @androidx.room.Insert(onConflict = androidx.room.OnConflictStrategy.IGNORE)
    suspend fun insert(row: RelayFileRow)

    @Update suspend fun update(row: RelayFileRow)

    @Query("SELECT * FROM relay_devices ORDER BY revoked, id")
    fun devices(): Flow<List<RelayDeviceRow>>

    @Query("SELECT * FROM relay_devices")
    suspend fun allDevices(): List<RelayDeviceRow>

    @androidx.room.Insert(onConflict = androidx.room.OnConflictStrategy.REPLACE)
    suspend fun insert(row: RelayDeviceRow)

    @Query("UPDATE relay_devices SET revoked = 1 WHERE id = :id")
    suspend fun revokeDevice(id: Int)

    @Query("SELECT * FROM relay_files")
    suspend fun allFiles(): List<RelayFileRow>

    @Query("DELETE FROM relay_files")
    suspend fun clearFiles()

    @Query("DELETE FROM relay_files WHERE submission_id = :id")
    suspend fun deleteFiles(id: Int)

    @Query("DELETE FROM relay_submissions WHERE id = :id")
    suspend fun deleteSubmission(id: Int)

    @Query("DELETE FROM relay_submissions")
    suspend fun clearSubmissions()

    @Query("DELETE FROM relay_devices")
    suspend fun clearDevices()
}

@Dao
interface FieldDao {
    @Query("SELECT * FROM reports WHERE status != 'sent' ORDER BY created_at DESC")
    fun queue(): Flow<List<ReportRow>>

    @Query("SELECT * FROM reports WHERE status = 'ready' ORDER BY created_at ASC")
    suspend fun readyToSend(): List<ReportRow>

    @Query("SELECT count(*) FROM reports WHERE status = 'ready'")
    fun readyCount(): Flow<Int>

    @Query("SELECT * FROM reports WHERE id = :id")
    suspend fun report(id: String): ReportRow?

    @Query("SELECT * FROM reports WHERE id = :id")
    fun reportFlow(id: String): Flow<ReportRow?>

    @Insert suspend fun insert(row: ReportRow)
    @Update suspend fun update(row: ReportRow)

    @Query("SELECT * FROM reports WHERE status = 'sent'")
    suspend fun sentReports(): List<ReportRow>

    @Query("DELETE FROM reports WHERE id = :id")
    suspend fun deleteReport(id: String)

    // Attachment rows are removed explicitly rather than by a foreign key
    // with ON DELETE CASCADE, because the file on disk has to be shredded
    // first and the database cannot do that. A cascade here would leave
    // encrypted media orphaned in the sandbox with nothing pointing at it.
    @Query("DELETE FROM attachments WHERE report_id = :reportId")
    suspend fun deleteAttachmentsFor(reportId: String)

    @Query("SELECT * FROM attachments WHERE report_id = :reportId ORDER BY rowid")
    fun attachmentsFlow(reportId: String): Flow<List<AttachmentRow>>

    @Query("SELECT * FROM attachments WHERE report_id = :reportId ORDER BY rowid")
    suspend fun attachments(reportId: String): List<AttachmentRow>

    @Insert suspend fun insert(row: AttachmentRow)
    @Update suspend fun update(row: AttachmentRow)

    @Query("DELETE FROM attachments WHERE id = :id")
    suspend fun deleteAttachment(id: String)

    // ------------------------------------------------------ quick captures

    @Query("SELECT * FROM attachments WHERE report_id = '' ORDER BY rowid DESC")
    fun unfiledFlow(): Flow<List<AttachmentRow>>

    @Query("SELECT * FROM attachments WHERE report_id = '' AND id = :id")
    suspend fun unfiled(id: String): AttachmentRow?

    /** Files a quick capture to a report. From then on it is an ordinary
     *  attachment and is sent, shown and shredded with that report. */
    @Query("UPDATE attachments SET report_id = :reportId WHERE id = :id")
    suspend fun fileAttachment(id: String, reportId: String)

    @Query("SELECT report_id, count(*) AS n FROM attachments GROUP BY report_id")
    fun attachmentCounts(): Flow<List<AttachmentCount>>

    @Query("UPDATE reports SET last_error = :message, updated_at = :now WHERE id = :id")
    suspend fun noteError(id: String, message: String?, now: Long = System.currentTimeMillis())
}

@Database(
    entities = [ReportRow::class, AttachmentRow::class,
                RelaySubmissionRow::class, RelayFileRow::class, RelayDeviceRow::class],
    version = 3, exportSchema = false)
abstract class FieldDatabase : RoomDatabase() {
    abstract fun dao(): FieldDao
    abstract fun relay(): RelayDao

    companion object {
        @Volatile private var instance: FieldDatabase? = null

        /**
         * Opened with the key the Vault is holding, and closed when it locks.
         *
         * Throws rather than opening an unencrypted database if the vault is
         * shut. Every caller is downstream of the lock screen, so this should
         * be unreachable — and if it ever is reached, failing loudly beats
         * quietly creating a second, readable copy of the queue.
         */
        fun get(context: Context): FieldDatabase = instance ?: synchronized(this) {
            instance ?: build(context.applicationContext).also { instance = it }
        }

        /** Called when the vault locks. The next unlock reopens with the key
         *  it gets then, so a stale handle cannot outlive a lock. */
        fun closeAndForget() {
            synchronized(this) {
                runCatching { instance?.close() }
                instance = null
            }
        }

        private fun build(context: Context): FieldDatabase {
            System.loadLibrary("sqlcipher")
            val key = Vault.key() ?: throw Crypto.Locked()
            // SQLCipher's factory zeroes the array it is given, so it gets a
            // copy — the Vault's own key has to survive for the media files.
            val factory = SupportOpenHelperFactory(key.copyOf())
            return Room.databaseBuilder(context, FieldDatabase::class.java, "field.db")
                .openHelperFactory(factory)
                .addMigrations(MIGRATION_1_2, MIGRATION_2_3)
                // No fallbackToDestructiveMigration. A migration this app
                // cannot perform must not silently throw away a queue of
                // reports nobody has uploaded yet; crashing is louder and
                // recoverable, wiping is neither.
                .build()
        }
    }
}

/** 1.5 -> 1.6: routes and areas. One nullable column; every queued report
 *  keeps everything it had. */
val MIGRATION_1_2 = object : androidx.room.migration.Migration(1, 2) {
    override fun migrate(db: androidx.sqlite.db.SupportSQLiteDatabase) {
        db.execSQL("ALTER TABLE reports ADD COLUMN geometry TEXT")
    }
}

/** 1.6 -> 1.7: the relay's three tables. New tables only; a phone that
 *  never becomes a relay carries them empty. */
val MIGRATION_2_3 = object : androidx.room.migration.Migration(2, 3) {
    override fun migrate(db: androidx.sqlite.db.SupportSQLiteDatabase) {
        db.execSQL("CREATE TABLE IF NOT EXISTS `relay_submissions` (`id` INTEGER NOT NULL, " +
            "`device_id` INTEGER NOT NULL, `received_at` INTEGER NOT NULL, `title` TEXT NOT NULL, " +
            "`body` TEXT, `criticality` TEXT, `observed_at` TEXT, `lat` REAL, `lng` REAL, " +
            "`location_accuracy_m` REAL, `location_note` TEXT, `client_ref` TEXT, `template` TEXT, " +
            "`template_version` INTEGER, `fields` TEXT NOT NULL, `geometry` TEXT, `priorities` TEXT, " +
            "`lead_note` TEXT, `forwarded_at` INTEGER, PRIMARY KEY(`id`))")
        db.execSQL("CREATE TABLE IF NOT EXISTS `relay_files` (`id` INTEGER NOT NULL, " +
            "`submission_id` INTEGER NOT NULL, `client_ref` TEXT, `filename` TEXT NOT NULL, " +
            "`mime_type` TEXT NOT NULL, `path` TEXT NOT NULL, `size_bytes` INTEGER NOT NULL, " +
            "`duration_ms` INTEGER, `forwarded` INTEGER NOT NULL, PRIMARY KEY(`id`))")
        db.execSQL("CREATE TABLE IF NOT EXISTS `relay_devices` (`id` INTEGER NOT NULL, " +
            "`label` TEXT NOT NULL, `analyst` TEXT NOT NULL, `created_at` INTEGER NOT NULL, " +
            "`revoked` INTEGER NOT NULL, `console_user_id` INTEGER, PRIMARY KEY(`id`))")
    }
}

/** Where captured media goes. Inside filesDir, so it is in the app sandbox
 *  and is removed with the app — never in shared storage, where the gallery
 *  and every other app would see it. */
fun mediaDir(context: Context): File =
    File(context.filesDir, "media").apply { mkdirs() }
