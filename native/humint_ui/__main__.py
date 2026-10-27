"""HUMINT native app — the field server's own screen on x86 machines.

    python -m humint_ui            full screen, as on the machine (under cage)
    python -m humint_ui --window   in a window (development)

Settings from the environment:
  HUMINT_BOX_SOCK     the machine helper's socket (default /run/humint/box.sock)
  HUMINT_CONSOLE_URL  the console, when not the one the helper reports
  HUMINT_UI_SCALE     multiply every size (default: from the screen)
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
QML = os.path.join(os.path.dirname(HERE), "qml")
# Complete desktop fonts (fonts/README.md) — not the console's split web fonts.
FONTS = os.environ.get("HUMINT_FONTS", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fonts"))


def keyboard_attached(path="/proc/bus/input/devices") -> bool:
    """Is a real keyboard plugged in or built in? (Power and lid buttons
    report as keyboards too; a keyboard has letter keys.)"""
    try:
        blocks = open(path).read().split("\n\n")
    except OSError:
        return True
    for b in blocks:
        name = next((ln.split("=", 1)[1].strip('"') for ln in b.splitlines() if ln.startswith("N: Name=")), "")
        handlers = next((ln for ln in b.splitlines() if ln.startswith("H: Handlers=")), "")
        keys = next((ln.split("=", 1)[1] for ln in b.splitlines() if ln.startswith("B: KEY=")), "")
        if "kbd" not in handlers or any(w in name.lower() for w in ("button", "video bus", "hotkey", "wmi")):
            continue
        # A full keyboard sets many key bits; buttons set a handful.
        if sum(bin(int(w, 16)).count("1") for w in keys.split() if w) >= 60:
            return True
    return False


def build(argv=None):
    """The app, ready to run: (QGuiApplication, QQmlApplicationEngine,
    {"box", "api", "util"}). main() runs it; the tests drive it."""
    argv = list(sys.argv if argv is None else argv)
    windowed = "--window" in argv
    # A plain, fully self-drawn look (no platform theme to differ between
    # machines) and the on-screen keyboard for touch-only machines.
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
    want = os.environ.get("HUMINT_KEYBOARD", "auto")
    if "--no-keyboard" not in argv and (want == "on" or (want == "auto" and not keyboard_attached())):
        os.environ.setdefault("QT_IM_MODULE", "qtvirtualkeyboard")

    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterSingletonInstance

    from .api import Api, ApiImages
    from .box import Box
    from .pdf import Pdf, PdfPages
    from .qr import QrImages
    from .util import Util

    app = QGuiApplication(argv)
    app.setApplicationName("HUMINT")
    app.setOrganizationName("HUMINT")

    if os.path.isdir(FONTS):
        for name in sorted(os.listdir(FONTS)):
            if name.endswith((".ttf", ".otf", ".woff", ".woff2")):
                QFontDatabase.addApplicationFont(os.path.join(FONTS, name))
    # Drawn in software (a machine whose graphics chip crashes the screen —
    # see humint-ui-launch), full hinting snaps each letter's width to whole
    # pixels and spaces words unevenly ("c ase"). Vertical-only hinting keeps
    # it crisp and evenly spaced; drawing on the graphics chip ignores it.
    base = app.font()
    base.setHintingPreference(QFont.PreferVerticalHinting)
    app.setFont(base)

    box = Box()
    api = Api(os.environ.get("HUMINT_CONSOLE_URL", ""))
    util = Util(windowed=windowed)

    def follow_console():
        if not os.environ.get("HUMINT_CONSOLE_URL"):
            api.setBase((box.state or {}).get("api_base") or "")
    box.stateChanged.connect(follow_console)

    qmlRegisterSingletonInstance(Box, "Humint", 1, 0, "Box", box)
    qmlRegisterSingletonInstance(Api, "Humint", 1, 0, "Api", api)
    qmlRegisterSingletonInstance(Util, "Humint", 1, 0, "Util", util)
    pdf = Pdf()
    qmlRegisterSingletonInstance(Pdf, "Humint", 1, 0, "Pdf", pdf)

    engine = QQmlApplicationEngine()
    engine.addImportPath(QML)
    engine.addImageProvider("qr", QrImages())
    engine.addImageProvider("api", ApiImages(api))
    engine.addImageProvider("pdf", PdfPages())
    engine.load(QUrl.fromLocalFile(os.path.join(QML, "Main.qml")))
    return app, engine, {"box": box, "api": api, "util": util, "pdf": pdf}


def main(argv=None) -> int:
    app, engine, _ = build(argv)
    if not engine.rootObjects():
        return 1
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
