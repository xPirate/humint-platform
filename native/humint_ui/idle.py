"""The screen sleeping: after a set time with nobody touching it, the panel
switches off (its backlight, through humint-boxd) and the app draws black;
the next touch, key or mouse movement wakes it — and only wakes it, so a tap
on a dark screen never presses whatever was under the finger.

QML sees one object, `Idle`:

  Idle.minutes      minutes of no input before sleeping (0 = never)
  Idle.asleep       whether the screen is asleep now
  Idle.sleepNow()   sleep at once (the quick settings' "Sleep now")
  Idle.poke()       count as activity (something on screen the person is
                    watching, e.g. an update's progress)
"""
import threading
import time

from PySide6.QtCore import Property, QEvent, QObject, QTimer, Signal, Slot

from .box import call

INPUT = {
    QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease, QEvent.Type.MouseButtonDblClick,
    QEvent.Type.MouseMove, QEvent.Type.Wheel,
    QEvent.Type.TouchBegin, QEvent.Type.TouchUpdate, QEvent.Type.TouchEnd,
    QEvent.Type.KeyPress, QEvent.Type.KeyRelease,
}
# What wakes it (a release or touch-end on its own does not: they follow).
WAKE = {QEvent.Type.MouseButtonPress, QEvent.Type.MouseMove, QEvent.Type.Wheel,
        QEvent.Type.TouchBegin, QEvent.Type.KeyPress}


class Idle(QObject):
    changed = Signal()

    def __init__(self, parent=None, power=None):
        super().__init__(parent)
        self._minutes = 0
        self._asleep = False
        self._last = time.monotonic()
        # Swallow the rest of the gesture that woke it (the release, the touch end).
        self._swallow_until = 0.0
        self._power = power or (lambda on: threading.Thread(
            target=call, args=("screen_power", {"on": on}), kwargs={"timeout": 10}, daemon=True).start())
        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self._check)
        self._timer.start()

    def watch(self, window):
        window.installEventFilter(self)

    # ---- QML ------------------------------------------------------------------

    @Property(int, notify=changed)
    def minutes(self):
        return self._minutes

    @minutes.setter
    def minutes(self, m):
        m = max(0, int(m or 0))
        if m != self._minutes:
            self._minutes = m
            self._last = time.monotonic()
            self.changed.emit()

    @Property(bool, notify=changed)
    def asleep(self):
        return self._asleep

    @Slot()
    def sleepNow(self):
        self._sleep()

    @Slot()
    def poke(self):
        self._last = time.monotonic()

    @Slot()
    def wake(self):
        if self._asleep:
            self._asleep = False
            self._last = time.monotonic()
            self._power(True)
            self.changed.emit()

    # ---- the clock and the input ------------------------------------------------

    def _sleep(self):
        if not self._asleep:
            self._asleep = True
            # A moment's grace: the tap on "Sleep now" itself is still finishing.
            self._swallow_until = time.monotonic() + 0.6
            self._power(False)
            self.changed.emit()

    def _check(self):
        if not self._asleep and self._minutes > 0 and time.monotonic() - self._last >= self._minutes * 60:
            self._sleep()

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t not in INPUT:
            return False
        now = time.monotonic()
        if self._asleep:
            if now < self._swallow_until:
                return True
            if t in WAKE:
                self.wake()
                self._swallow_until = now + 0.8
            return True             # the waking gesture goes no further
        if now < self._swallow_until and t not in (QEvent.Type.MouseMove,):
            return True
        self._last = now
        return False
