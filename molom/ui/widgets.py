"""Blender-style value field: drag horizontally to scrub, click to type
(with arithmetic — `3+5*1.3` evaluates on commit), Esc restores.

Used by the N transform panel. Thin: evaluation is core.mathexpr."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QLineEdit

from ..core import mathexpr

_DRAG_SLOP_PX = 3


class DragValueEdit(QLineEdit):
    """A numeric field that is a drag-slider until clicked.

    - drag left/right: value += pixels * step (live `value_changed` signals,
      one `drag_started` up front, `value_committed` on release)
    - click without drag: becomes a normal line edit; Enter/focus-out
      evaluates the text as arithmetic and commits; Esc cancels
    """

    drag_started = Signal()
    value_changed = Signal(float)       # live (drag or after commit)
    value_committed = Signal(float)

    def __init__(self, value=0.0, step=0.02, decimals=3, parent=None):
        super().__init__(parent)
        self._value = float(value)
        self._step = float(step)
        self._decimals = int(decimals)
        self._press_x = None
        self._press_val = 0.0
        self._dragging = False
        self._editing = False
        self.setAlignment(Qt.AlignCenter)
        self._show_value()
        self.editingFinished.connect(self._commit_text)

    # ---------------------------------------------------------------- value
    def value(self):
        return self._value

    def set_value(self, v):
        # type: (float) -> None
        self._value = float(v)
        if not self._editing:
            self._show_value()

    def _show_value(self):
        self.setReadOnly(True)
        self.setCursor(QCursor(Qt.SizeHorCursor))
        self.setText("{v:.{d}f}".format(v=self._value, d=self._decimals))

    # ----------------------------------------------------------------- drag
    def mousePressEvent(self, ev):
        if self._editing:
            super().mousePressEvent(ev)
            return
        if ev.button() == Qt.LeftButton:
            self._press_x = ev.position().x()
            self._press_val = self._value
            self._dragging = False

    def mouseMoveEvent(self, ev):
        if self._editing or self._press_x is None:
            super().mouseMoveEvent(ev)
            return
        dx = ev.position().x() - self._press_x
        if not self._dragging and abs(dx) > _DRAG_SLOP_PX:
            self._dragging = True
            self.drag_started.emit()
        if self._dragging:
            scale = 0.1 if ev.modifiers() & Qt.ShiftModifier else 1.0
            self._value = self._press_val + dx * self._step * scale
            self._show_value()
            self.value_changed.emit(self._value)

    def mouseReleaseEvent(self, ev):
        if self._editing:
            super().mouseReleaseEvent(ev)
            return
        if self._press_x is None:
            return
        was_drag = self._dragging
        self._press_x = None
        self._dragging = False
        if was_drag:
            self.value_committed.emit(self._value)
        else:                               # plain click -> edit mode
            self._begin_typing()
            self.setFocus()

    # ----------------------------------------------------------------- typing
    def keyPressEvent(self, ev):
        if self._editing and ev.key() == Qt.Key_Escape:
            self._editing = False
            self._show_value()
            self.clearFocus()
            return
        super().keyPressEvent(ev)

    def _commit_text(self):
        if not self._editing:
            return
        self._editing = False
        try:
            v = mathexpr.evaluate(self.text())
        except ValueError:
            self._show_value()              # bad expression: keep old value
            return
        self._value = float(v)
        self._show_value()
        # committed only (no live signal): lets the app push its undo
        # snapshot before the one-and-only application of a typed value
        self.value_committed.emit(self._value)

    def focusInEvent(self, ev):
        super().focusInEvent(ev)
        # Arriving by Tab means the user intends to TYPE — a drag-slider that
        # ignores the keyboard after tabbing into it is just broken.
        if ev.reason() in (Qt.TabFocusReason, Qt.BacktabFocusReason) \
                and not self._editing:
            self._begin_typing()

    def _begin_typing(self):
        self._editing = True
        self.setReadOnly(False)
        self.setCursor(QCursor(Qt.IBeamCursor))
        self.setText("{v:.{d}f}".format(v=self._value, d=self._decimals))
        self.selectAll()

    def focusOutEvent(self, ev):
        super().focusOutEvent(ev)
        if self._editing:
            self._commit_text()
