"""The app's link to the console (the same API the web console and the phone
app use), on this machine.

QML sees one object, `api`:

  api.call(method, path, body) → id   then api.finished(id, status, data, error)
  api.upload(path, filePath, fields) → id   (multipart, same signal)
  api.download(path, filePath) → id         (saves the response, same signal)
  api.signOut()

and images from the console as  image://api/<path>  (signed in as the app).

The session is the console's own cookie, kept in memory only: a restart of
the app means signing in again, as closing a browser would.
"""
import concurrent.futures
import itertools
import json
import mimetypes
import os
import threading

import requests
import urllib3
from PySide6.QtCore import Property, QObject, QSize, Signal, Slot
from PySide6.QtGui import QImage
from PySide6.QtQuick import QQuickImageProvider

# 127.0.0.1 is this machine. Its certificate names its network addresses,
# not the loopback, and nothing but root on this machine could stand in the
# middle of a loopback connection — so the name is not checked for it.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class Api(QObject):
    finished = Signal(int, int, "QVariant", str)
    baseChanged = Signal()

    def __init__(self, base: str = "", parent=None):
        super().__init__(parent)
        self._base = base
        self._session = requests.Session()
        self._session.headers["User-Agent"] = "HUMINT-native/1"
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self._pool = concurrent.futures.ThreadPoolExecutor(max_workers=6, thread_name_prefix="api")

    # ---- where the console is ------------------------------------------------

    @Property(str, notify=baseChanged)
    def base(self):
        return self._base

    @Slot(str)
    def setBase(self, base):
        if base != self._base:
            self._base = base.rstrip("/")
            self.baseChanged.emit()

    def _url(self, path: str) -> str:
        return self._base + (path if path.startswith("/") else "/" + path)

    # ---- requests ---------------------------------------------------------------

    def _finish(self, rid, resp: requests.Response | None, error: str = "", body: bool = True):
        if resp is None:
            self.finished.emit(rid, 0, None, error or "The console is not answering")
            return
        data = None
        ctype = resp.headers.get("content-type", "")
        if body or resp.status_code >= 400:
            try:
                if "json" in ctype:
                    data = resp.json()
                elif "text/" in ctype:
                    data = resp.text
            except (ValueError, RuntimeError):
                data = None
        err = ""
        if resp.status_code >= 400:
            detail = data.get("detail") if isinstance(data, dict) else None
            if isinstance(detail, list):        # FastAPI validation errors
                detail = "; ".join(str(d.get("msg", d)) for d in detail if isinstance(d, dict)) or None
            err = detail if isinstance(detail, str) else f"The console said {resp.status_code}"
        self.finished.emit(rid, resp.status_code, data, err)

    def _submit(self, fn, body=True):
        rid = next(self._ids)

        def work():
            # Whatever happens, the screen that asked hears back.
            try:
                resp = fn()
            except requests.RequestException as e:
                self._finish(rid, None, f"The console is not answering ({e.__class__.__name__})")
                return
            except OSError as e:
                self._finish(rid, None, f"Could not read or write the file ({e.strerror or e})")
                return
            except Exception as e:  # noqa: BLE001 — never leave a screen waiting forever
                self._finish(rid, None, f"Something went wrong ({e.__class__.__name__})")
                return
            try:
                self._finish(rid, resp, body=body)
            except Exception as e:  # noqa: BLE001
                self.finished.emit(rid, 0, None, f"Something went wrong ({e.__class__.__name__})")
        self._pool.submit(work)
        return rid

    @Slot(str, str, "QVariant", result=int)
    def call(self, method, path, body=None):
        method = method.upper()
        kw = {"timeout": 120, "verify": False}
        if body is not None and method != "GET":
            kw["data"] = json.dumps(body)
            kw["headers"] = {"Content-Type": "application/json"}
        elif body is not None:
            kw["params"] = body
        return self._submit(lambda: self._session.request(method, self._url(path), **kw))

    @Slot(str, str, "QVariant", result=int)
    def upload(self, path, file_path, fields=None):
        file_path = file_path.replace("file://", "", 1) if file_path.startswith("file://") else file_path

        def go():
            mime = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
            with open(file_path, "rb") as fh:
                return self._session.post(self._url(path), data=dict(fields or {}), timeout=600, verify=False,
                                          files={"file": (os.path.basename(file_path), fh, mime)})
        return self._submit(go)

    @Slot(str, str, result=int)
    def download(self, path, file_path):
        file_path = file_path.replace("file://", "", 1) if file_path.startswith("file://") else file_path

        def go():
            r = self._session.get(self._url(path), timeout=600, verify=False, stream=True)
            if r.status_code < 400:
                with open(file_path, "wb") as fh:
                    for chunk in r.iter_content(65536):
                        fh.write(chunk)
            return r
        return self._submit(go, body=False)

    @Slot(str, "QVariant", str, result=int)
    def downloadPost(self, path, body, file_path):
        """A file the console makes on request (a field package): POST, save."""
        file_path = file_path.replace("file://", "", 1) if file_path.startswith("file://") else file_path

        def go():
            r = self._session.post(self._url(path), data=json.dumps(body or {}), timeout=900, verify=False, stream=True,
                                   headers={"Content-Type": "application/json"})
            if r.status_code < 400:
                with open(file_path, "wb") as fh:
                    for chunk in r.iter_content(65536):
                        fh.write(chunk)
            return r
        return self._submit(go, body=False)

    @Slot()
    def signOut(self):
        self._session.cookies.clear()

    # Used by the image provider, from its own threads.
    def get_bytes(self, path: str) -> bytes | None:
        try:
            r = self._session.get(self._url(path), timeout=60, verify=False)
        except requests.RequestException:
            return None
        return r.content if r.status_code == 200 else None


class ApiImages(QQuickImageProvider):
    """image://api/<path> — an image from the console, fetched with the
    app's session (QML's own loader would not carry the cookie)."""

    def __init__(self, api: Api):
        super().__init__(QQuickImageProvider.ImageType.Image,
                         QQuickImageProvider.Flag.ForceAsynchronousImageLoading)
        self.api = api

    def requestImage(self, id_, size, requested: QSize):
        img = QImage()
        data = self.api.get_bytes("/" + id_.lstrip("/"))
        if data:
            img.loadFromData(data)
        if not img.isNull() and requested.isValid() and requested.width() > 0 and requested.height() > 0:
            from PySide6.QtCore import Qt
            img = img.scaled(requested, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        if size is not None:
            size.setWidth(img.width()); size.setHeight(img.height())
        return img
