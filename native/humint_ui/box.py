"""The app's link to humint-boxd: the machine's state, and the few things
the app may ask the machine to do (see deploy/x86/files/opt/humint/bin/humint-boxd.py).

QML sees one object, `box`:

  box.state            the latest status (a JS object), refreshed every 2 s
  box.connected        whether the helper is answering
  box.request(op, args) → id    then box.replied(id, ok, data, error)
"""
import itertools
import json
import os
import socket
import threading

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

SOCK = os.environ.get("HUMINT_BOX_SOCK", "/run/humint/box.sock")


def call(op: str, args: dict | None = None, timeout: float = 1900) -> dict:
    """One request to the helper; blocks. Returns its reply as a dict."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(SOCK)
        s.sendall((json.dumps({"op": op, **(args or {})}) + "\n").encode())
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
        return json.loads(buf or b'{"ok": false, "error": "no answer"}')
    except (OSError, ValueError) as e:
        return {"ok": False, "error": f"The machine's helper is not answering ({e})"}
    finally:
        s.close()


class Box(QObject):
    stateChanged = Signal()
    connectedChanged = Signal()
    replied = Signal(int, bool, "QVariant", str)

    def __init__(self, parent=None, interval_ms: int = 2000):
        super().__init__(parent)
        self._state = {}
        self._connected = False
        self._ids = itertools.count(1)
        self._polling = False
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        self._result.connect(self._apply)
        self.refresh()

    _result = Signal("QVariant")

    @Property("QVariant", notify=stateChanged)
    def state(self):
        return self._state

    @Property(bool, notify=connectedChanged)
    def connected(self):
        return self._connected

    @Slot()
    def refresh(self):
        if self._polling:
            return
        self._polling = True

        def work():
            r = call("status", timeout=10)
            self._result.emit(r)
        threading.Thread(target=work, daemon=True).start()

    def _apply(self, r):
        self._polling = False
        ok = bool(r.get("ok"))
        if ok and r.get("data") != self._state:
            self._state = r["data"]
            self.stateChanged.emit()
        if ok != self._connected:
            self._connected = ok
            self.connectedChanged.emit()

    @Slot(str, "QVariant", result=int)
    def request(self, op, args=None):
        rid = next(self._ids)
        args = dict(args or {}) if not hasattr(args, "toVariant") else args.toVariant()

        def work():
            r = call(op, args)
            self.replied.emit(rid, bool(r.get("ok")), r.get("data"), r.get("error") or "")
            self.refresh()
        threading.Thread(target=work, daemon=True).start()
        return rid
