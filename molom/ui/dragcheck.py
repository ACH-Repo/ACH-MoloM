"""Checkbox rows you can PAINT across by holding the mouse down.

Christian's general design principle (2026-08-03): wherever several tick
boxes sit in a row, holding the left button and sweeping across them should
set them all — the same gesture the outliner's visibility eyes already use.
Clicking six boxes one at a time is six decisions; sweeping is one.

`install(container)` makes every QCheckBox under `container` behave that way.
The first box you press decides the direction (if it was off, the sweep turns
things ON), so the gesture is "make these all like this one".
"""

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QCheckBox


class _SweepFilter(QObject):
    def __init__(self, container):
        super().__init__(container)
        self._container = container
        self._target = None        # the state being painted, or None

    def _boxes(self):
        return self._container.findChildren(QCheckBox)

    def _box_at(self, global_pos):
        for box in self._boxes():
            if not box.isVisible() or not box.isEnabled():
                continue
            local = box.mapFromGlobal(global_pos)
            if box.rect().contains(local):
                return box
        return None

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.MouseButtonPress \
                and ev.button() == Qt.LeftButton:
            box = self._box_at(ev.globalPosition().toPoint())
            if box is not None:
                # The box under the press flips normally; the sweep then
                # carries THAT new state to everything it touches.
                self._target = not box.isChecked()
        elif ev.type() == QEvent.MouseMove and self._target is not None:
            box = self._box_at(ev.globalPosition().toPoint())
            if box is not None and box.isChecked() != self._target:
                box.setChecked(self._target)
        elif ev.type() in (QEvent.MouseButtonRelease, QEvent.Leave):
            self._target = None
        return False


def install(container):
    """Make every checkbox under `container` paintable by dragging."""
    if container is None:
        return None
    existing = container.findChild(_SweepFilter)
    if existing is not None:
        return existing
    sweep = _SweepFilter(container)
    container.setMouseTracking(True)
    container.installEventFilter(sweep)
    for box in container.findChildren(QCheckBox):
        box.installEventFilter(sweep)
    return sweep
