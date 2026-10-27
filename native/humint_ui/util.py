"""Small helpers QML cannot do on its own."""
import os
import tempfile

from PySide6.QtCore import Property, QObject, Signal, Slot

from .qr import wifi_payload


class Util(QObject):
    changed = Signal()

    def __init__(self, windowed=False, parent=None):
        super().__init__(parent)
        self._windowed = windowed

    @Property(bool, notify=changed)
    def windowed(self):
        return self._windowed

    @Slot(str, str, bool, result=str)
    def wifiPayload(self, ssid, psk, hidden):
        return wifi_payload(ssid, psk, hidden)

    @Slot(str, result=str)
    def tempPath(self, name):
        """A path for a file the app opens to show (a PDF from the case
        file). In RAM (the session's runtime directory, a tmpfs), never on the
        unencrypted disk, and only this account can read it."""
        base = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
        d = os.path.join(base, "humint-view")
        os.makedirs(d, mode=0o700, exist_ok=True)
        safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in name)[-80:] or "file"
        return os.path.join(d, safe)

    @Slot(str)
    def removeFile(self, path):
        try:
            if path.startswith(os.path.join(os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir(), "humint-view")):
                os.unlink(path)
        except OSError:
            pass

    @Slot(str, result=str)
    def readText(self, path):
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                return fh.read(2_000_000)
        except OSError:
            return ""

    @Slot(str, result=str)
    def env(self, name):
        return os.environ.get(name, "")
