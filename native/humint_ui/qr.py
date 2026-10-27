"""image://qr/<text> — a QR code for any text (Wi-Fi join, console address,
phone upload code), drawn here: nothing leaves the machine to make it."""
import io
import urllib.parse

import segno
from PySide6.QtCore import QSize
from PySide6.QtGui import QImage
from PySide6.QtQuick import QQuickImageProvider


class QrImages(QQuickImageProvider):
    def __init__(self):
        super().__init__(QQuickImageProvider.ImageType.Image)

    def requestImage(self, id_, size, requested: QSize):
        text = urllib.parse.unquote(id_.split("#", 1)[0])
        img = QImage()
        if text:
            q = segno.make(text, error="m", micro=False)
            want = max(requested.width(), requested.height(), 240) if requested.isValid() else 480
            scale = max(1, want // (q.symbol_size(border=2)[0]))
            buf = io.BytesIO()
            q.save(buf, kind="png", scale=scale, border=2, dark="#000000", light="#ffffff")
            img.loadFromData(buf.getvalue(), "PNG")
        if size is not None:
            size.setWidth(img.width()); size.setHeight(img.height())
        return img


def wifi_payload(ssid: str, psk: str, hidden: bool) -> str:
    def esc(v):
        return "".join("\\" + c if c in '\\;,:"' else c for c in v or "")
    return f"WIFI:T:WPA;S:{esc(ssid)};P:{esc(psk)};" + ("H:true;" if hidden else "") + ";"
