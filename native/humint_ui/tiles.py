"""image://tile/<url> — an online map tile, for the map pages when they show
a tile server live (not an offline area).

Not QML's own loader, for two reasons. Tile servers' usage policies
(OpenStreetMap's among them) refuse requests that do not name the
application, and Qt's loader sends a bare "Mozilla/5.0" with no way to change
it short of overriding its network calls from Python on Qt's own threads,
which crashes PySide. And a disk cache: tiles panned past are not fetched
again (and the map still shows them a while after the internet goes).

The cache is in memory (the session's runtime folder, gone at power-off),
never on the system disk: that is not encrypted, and the tiles would record
which places were looked at. Offline areas are what keeps maps for good —
inside the encrypted case file.
"""
import hashlib
import os
import threading
import time
import urllib.parse

import requests
from PySide6.QtCore import QSize, QStandardPaths
from PySide6.QtGui import QImage
from PySide6.QtQuick import QQuickImageProvider

USER_AGENT = os.environ.get("HUMINT_TILE_USER_AGENT",
                            "HUMINT-field-server-map/1 (+https://github.com/xPirate/humint-platform)")
CACHE_DAYS = 30
CACHE_MAX_BYTES = 64 * 1024 * 1024


def cache_dir() -> str:
    base = os.environ.get("HUMINT_TILE_CACHE")
    if not base:
        run = os.environ.get("XDG_RUNTIME_DIR") or \
            QStandardPaths.writableLocation(QStandardPaths.StandardLocation.RuntimeLocation)
        if not run:
            return None          # nowhere in memory: no cache, rather than the disk
        base = os.path.join(run, "humint-tiles")
    os.makedirs(base, mode=0o700, exist_ok=True)
    return base


class WebTiles(QQuickImageProvider):
    def __init__(self):
        super().__init__(QQuickImageProvider.ImageType.Image,
                         QQuickImageProvider.Flag.ForceAsynchronousImageLoading)
        self._session = requests.Session()
        self._session.headers["User-Agent"] = USER_AGENT
        self._dir = None
        self._lock = threading.Lock()
        self._writes = 0

    def _path(self, url):
        if self._dir is None:
            try:
                self._dir = cache_dir() or ""
            except OSError:
                self._dir = ""
        if not self._dir:
            return None
        return os.path.join(self._dir, hashlib.sha1(url.encode()).hexdigest())

    def _prune(self):
        """Oldest first, down to the size limit (now and then, not per tile)."""
        try:
            files = [(e.stat().st_mtime, e.stat().st_size, e.path) for e in os.scandir(self._dir) if e.is_file()]
        except OSError:
            return
        total = sum(f[1] for f in files)
        now = time.time()
        for mtime, size, path in sorted(files):
            if total <= CACHE_MAX_BYTES and now - mtime < CACHE_DAYS * 86400:
                break
            try:
                os.unlink(path)
                total -= size
            except OSError:
                pass

    def fetch(self, url: str) -> bytes | None:
        if not url.startswith(("https://", "http://")):
            return None
        path = self._path(url)
        try:
            if path and time.time() - os.path.getmtime(path) < CACHE_DAYS * 86400:
                with open(path, "rb") as f:
                    return f.read()
        except OSError:
            pass
        try:
            r = self._session.get(url, timeout=20)
        except requests.RequestException:
            r = None
        if r is None or r.status_code != 200 or not r.headers.get("Content-Type", "").startswith("image/"):
            # Offline, or refused: an old copy beats a blank square.
            try:
                with open(path, "rb") as f:
                    return f.read()
            except (OSError, TypeError):
                return None
        if not path:
            return r.content
        try:
            tmp = f"{path}.{threading.get_ident()}"
            with open(tmp, "wb") as f:
                f.write(r.content)
            os.replace(tmp, path)
            with self._lock:
                self._writes += 1
                prune = self._writes % 500 == 0
            if prune:
                self._prune()
        except OSError:
            pass
        return r.content

    def requestImage(self, id_, size, requested: QSize):
        url = id_ if id_.startswith(("http://", "https://")) else urllib.parse.unquote(id_)
        img = QImage()
        data = self.fetch(url)
        if data:
            img.loadFromData(data)
        if img.isNull():
            # No internet, or refused: an empty square (as an unreachable
            # server always looked), not an error for every tile.
            img = QImage(256, 256, QImage.Format.Format_ARGB32)
            img.fill(0)
        if size is not None:
            size.setWidth(img.width()); size.setHeight(img.height())
        return img
