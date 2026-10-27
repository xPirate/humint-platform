"""Drive the native app off-screen: wait for things, tap buttons by their
text, type, and save screenshots. Used by tools/shoot.py and the tests."""
import os
import sys
import time

NATIVE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class AppDriver:
    def __init__(self, box_sock, console_url="", size=(1280, 800), keyboard=False):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        os.environ["HUMINT_BOX_SOCK"] = box_sock
        os.environ.setdefault("HUMINT_FONTS", os.path.join(os.path.dirname(NATIVE), "frontend/vendor/fonts"))
        if console_url:
            os.environ["HUMINT_CONSOLE_URL"] = console_url
        if not keyboard:
            os.environ["QT_IM_MODULE"] = ""
        sys.path.insert(0, NATIVE)
        from humint_ui.__main__ import build
        argv = ["humint-ui", "--window"] + ([] if keyboard else ["--no-keyboard"])
        self.app, self.engine, self.objs = build(argv)
        errors = [w.toString() for w in getattr(self.engine, "_warnings", [])]
        roots = self.engine.rootObjects()
        if not roots:
            raise RuntimeError("the app did not load: " + "; ".join(errors))
        self.win = roots[0]
        self.win.setWidth(size[0]); self.win.setHeight(size[1])
        self.pump(0.5)

    def pump(self, secs=0.1):
        end = time.time() + secs
        while time.time() < end:
            self.app.processEvents()
            time.sleep(0.01)
        self.app.processEvents()

    def until(self, fn, timeout=10, what="condition"):
        end = time.time() + timeout
        while time.time() < end:
            self.app.processEvents()
            try:
                if fn():
                    return True
            except Exception:
                pass
            time.sleep(0.02)
        raise TimeoutError(f"timed out waiting for {what}")

    def items(self):
        out = []

        def walk(item):
            out.append(item)
            for c in item.childItems():
                walk(c)
        walk(self.win.contentItem())
        return out

    def visible(self, item):
        while item is not None:
            if not item.isVisible() or item.opacity() == 0:
                return False
            item = item.parentItem()
        return True

    def texts(self):
        return [i.property("text") for i in self.items()
                if isinstance(i.property("text"), str) and i.property("text") and self.visible(i)]

    def has_text(self, needle):
        return any(needle in t for t in self.texts())

    def button(self, label):
        for i in self.items():
            if i.metaObject().indexOfSignal("clicked()") >= 0 and i.property("text") == label and self.visible(i) \
                    and i.property("enabled"):
                return i
        return None

    def tap(self, label, timeout=5):
        self.until(lambda: self.button(label) is not None, timeout, f"button {label!r}")
        b = self.button(label)
        b.metaObject().invokeMethod(b, "clicked")
        self.pump(0.2)

    def type_into(self, placeholder, text):
        for i in self.items():
            if i.property("placeholderText") == placeholder and self.visible(i):
                i.setProperty("text", text)
                self.pump(0.05)
                return i
        raise LookupError(f"no field {placeholder!r}")

    def field(self, placeholder):
        for i in self.items():
            if i.property("placeholderText") == placeholder and self.visible(i):
                return i
        raise LookupError(f"no field {placeholder!r}")

    def type(self, placeholder, text):
        """Type at the end of a field, as a person would (handlers that watch
        the cursor see it)."""
        f = self.field(placeholder)
        f.forceActiveFocus()
        self.pump(0.05)
        from PySide6.QtCore import Q_ARG, QMetaObject
        for ch in text:
            end = len(f.property("text") or "")
            f.setProperty("cursorPosition", end)
            QMetaObject.invokeMethod(f, "insert", Q_ARG(int, end), Q_ARG(str, ch))
            self.pump(0.01)
        self.pump(0.3)
        return f

    def _under_label(self, label):
        for i in self.items():
            if i.property("label") == label and i.property("hint") is not None and self.visible(i):
                return i
        raise LookupError(f"no field labelled {label!r}")

    def _descendants(self, item):
        out = []

        def walk(x):
            for c in x.childItems():
                out.append(c)
                walk(c)
        walk(item)
        return out

    def set_field(self, label, text):
        """Fill the text field under a form label."""
        box = self._under_label(label)
        for c in self._descendants(box):
            if c.metaObject().indexOfProperty("cursorPosition") >= 0 and c.metaObject().indexOfProperty("placeholderText") >= 0:
                c.forceActiveFocus()
                c.setProperty("text", text)
                # what typing would announce
                if c.metaObject().indexOfSignal("textEdited()") >= 0:
                    c.metaObject().invokeMethod(c, "textEdited")
                self.pump(0.05)
                return c
        raise LookupError(f"no text field under {label!r}")

    def choose(self, label, option):
        """Pick an option from the drop-down under a form label."""
        from PySide6.QtCore import Q_ARG, QMetaObject
        box = self._under_label(label)
        for c in self._descendants(box):
            opts = c.property("options")
            if hasattr(opts, "toVariant"):
                opts = opts.toVariant()
            if opts is not None and c.metaObject().indexOfSignal("activated(int)") >= 0:
                labels = [o[1] for o in opts]
                i = labels.index(option)
                QMetaObject.invokeMethod(c, "activated", Q_ARG(int, i))
                self.pump(0.05)
                return c
        raise LookupError(f"no drop-down under {label!r}")

    def choose_select(self, current, option):
        """Pick an option from a visible drop-down showing `current`."""
        from PySide6.QtCore import Q_ARG, QMetaObject
        for c in self.items():
            opts = c.property("options")
            if hasattr(opts, "toVariant"):
                opts = opts.toVariant()
            if opts and c.metaObject().indexOfSignal("activated(int)") >= 0 and self.visible(c) \
                    and c.property("displayText") == current:
                i = [o[1] for o in opts].index(option)
                QMetaObject.invokeMethod(c, "activated", Q_ARG(int, i))
                self.pump(0.05)
                return c
        raise LookupError(f"no drop-down showing {current!r}")

    def login(self, username, password):
        self.until(lambda: self.has_text("Sign in to the case file"), 20, "sign-in screen")
        self.type_into("Username", username)
        self.type_into("Password", password)
        self.tap("Sign in")
        self.until(lambda: self.has_text("Dashboard"), 15, "signed in")

    def accept(self, placeholder):
        for i in self.items():
            if i.property("placeholderText") == placeholder and self.visible(i):
                i.metaObject().invokeMethod(i, "accepted")
                self.pump(0.2)
                return
        raise LookupError(placeholder)

    def shot(self, path):
        self.pump(0.3)
        img = self.win.grabWindow()
        img.save(path)
        return path
