"""image://pdf/<page>/<path> — one page of a PDF the app has fetched to show,
drawn by poppler's pdftoppm (already on the machine for reading documents),
off the screen's thread. PySide's wheels do not include Qt's own PDF module."""
import os
import subprocess
import urllib.parse

from PySide6.QtCore import QObject, QSize, Slot
from PySide6.QtGui import QImage
from PySide6.QtQuick import QQuickImageProvider


def page_count(path: str) -> int:
    try:
        out = subprocess.run(["pdfinfo", path], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return 0
    for line in out.splitlines():
        if line.startswith("Pages:"):
            try:
                return int(line.split()[1])
            except (IndexError, ValueError):
                return 0
    return 0


class PdfPages(QQuickImageProvider):
    def __init__(self):
        super().__init__(QQuickImageProvider.ImageType.Image,
                         QQuickImageProvider.Flag.ForceAsynchronousImageLoading)

    def requestImage(self, id_, size, requested: QSize):
        img = QImage()
        page, _, path = id_.partition("/")
        path = "/" + urllib.parse.unquote(path).lstrip("/")
        width = requested.width() if requested.isValid() and requested.width() > 0 else 1400
        try:
            png = subprocess.run(["pdftoppm", "-png", "-f", page, "-l", page, "-scale-to-x", str(width),
                                  "-scale-to-y", "-1", path], capture_output=True, timeout=60).stdout
            if png:
                img.loadFromData(png, "PNG")
        except (OSError, subprocess.SubprocessError):
            pass
        if size is not None:
            size.setWidth(img.width()); size.setHeight(img.height())
        return img


class Pdf(QObject):
    @Slot(str, result=int)
    def pages(self, path):
        return page_count(path) if os.path.exists(path) else 0
