"""Crash and power-cut recovery for the worker's claimed jobs.

Every job the worker takes — a document to read, an address to look up, a map
pack to download — is first *claimed*: its status moves to an in-progress
value so a second worker would skip it. If the process then dies (a crash, the
field server's battery running flat, someone pulling the plug), that claim used
to stay in place for ever: a document sat on "processing", a pack on
"downloading", and only a hand-typed UPDATE got them moving again.

Now each claim names the worker that holds it (WORKER_ID), each worker keeps a
heartbeat row fresh from a thread of its own — so a 40-minute OCR job does not
make it look dead — and recover_orphans() hands back any claim whose holder has
gone quiet. It runs when the worker starts and every minute after.

A document is put back at most MAX_DOCUMENT_ATTEMPTS - 1 times. A file that
reliably kills the worker (a pathological PDF, say) would otherwise be retried
for ever, taking the worker down each time; on the last interruption it is
marked failed with a reason a person can read, and "Read again" starts it over.
"""

import os
import socket
import threading
import time
import uuid

from db import db_cursor

HEARTBEAT_SECONDS = int(os.environ.get("WORKER_HEARTBEAT_SECONDS", "15"))
# A worker is presumed gone once its heartbeat is this old. Several beats, so a
# busy database or a stalled SD card does not get a live worker's work stolen.
STALE_AFTER_SECONDS = int(os.environ.get("WORKER_STALE_AFTER_SECONDS", "120"))
MAX_DOCUMENT_ATTEMPTS = int(os.environ.get("WORKER_MAX_DOCUMENT_ATTEMPTS", "3"))

WORKER_ID = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"

INTERRUPTED_MESSAGE = (
    "Stopped part-way through {n} times (the worker was interrupted — a crash or "
    "power cut). Use Read again to retry; if it keeps happening the file may be "
    "too large or damaged to read here."
)

# Claims whose holder is not a live worker. NULL covers claims made before
# this version, which recorded no holder at all.
_ORPHANED = """
    ({col} IS NULL OR {col} NOT IN (
        SELECT worker_id FROM worker_heartbeats
        WHERE last_seen > now() - make_interval(secs => %(stale)s)))
    AND {col} IS DISTINCT FROM %(me)s
"""


def beat() -> None:
    with db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO worker_heartbeats (worker_id) VALUES (%s) "
            "ON CONFLICT (worker_id) DO UPDATE SET last_seen = now()",
            (WORKER_ID,))


def _heartbeat_loop(stop: threading.Event) -> None:
    while not stop.wait(HEARTBEAT_SECONDS):
        try:
            beat()
        except Exception as exc:                  # noqa: BLE001 - keep beating
            print(f"[worker] heartbeat failed: {exc}", flush=True)


def start_heartbeat() -> threading.Event:
    """Beat once now (before anything is claimed), then keep beating."""
    beat()
    stop = threading.Event()
    threading.Thread(target=_heartbeat_loop, args=(stop,), name="heartbeat",
                     daemon=True).start()
    return stop


def recover_orphans() -> dict:
    """Put interrupted work back in the queue. Returns counts per kind."""
    params = {"stale": STALE_AFTER_SECONDS, "me": WORKER_ID,
              "max": MAX_DOCUMENT_ATTEMPTS}
    counts = {"documents_requeued": 0, "documents_failed": 0,
              "geocodes": 0, "map_packs": 0}
    with db_cursor(commit=True) as cur:
        cur.execute(
            """
            UPDATE attachments SET
                extraction_status = CASE WHEN extraction_attempts >= %(max)s
                                         THEN 'failed' ELSE 'pending' END,
                extraction_error = CASE WHEN extraction_attempts >= %(max)s
                                        THEN replace(%(msg)s, '{n}', extraction_attempts::text)
                                        ELSE extraction_error END,
                extraction_claimed_by = NULL
            WHERE extraction_status = 'processing' AND """
            + _ORPHANED.format(col="extraction_claimed_by")
            + " RETURNING extraction_status",
            {**params, "msg": INTERRUPTED_MESSAGE})
        for (status,) in cur.fetchall():
            counts["documents_failed" if status == "failed" else "documents_requeued"] += 1

        cur.execute(
            "UPDATE location_details SET geocode_status = 'pending', geocode_claimed_by = NULL "
            "WHERE geocode_status = 'processing' AND "
            + _ORPHANED.format(col="geocode_claimed_by"), params)
        counts["geocodes"] = cur.rowcount

        # A pack picks up where it stopped: its tiles are already in the file
        # and the downloader skips any it has.
        cur.execute(
            "UPDATE map_packs SET status = 'pending', claimed_by = NULL "
            "WHERE status = 'downloading' AND "
            + _ORPHANED.format(col="claimed_by"), params)
        counts["map_packs"] = cur.rowcount

        # Rows for workers long gone; keeps the table to the live ones.
        cur.execute("DELETE FROM worker_heartbeats WHERE last_seen < now() - interval '1 day'")

    if any(counts.values()):
        print(f"[worker] recovered interrupted work: {counts}", flush=True)
    return counts


class Every:
    """Call fn at most once per `seconds` (from the main poll loop)."""

    def __init__(self, seconds: int, fn):
        self.seconds, self.fn, self.last = seconds, fn, 0.0

    def __call__(self):
        now = time.monotonic()
        if now - self.last < self.seconds:
            return None
        self.last = now
        return self.fn()
