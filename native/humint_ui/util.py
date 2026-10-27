"""Small helpers QML cannot do on its own."""
import os

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
    def env(self, name):
        return os.environ.get(name, "")
