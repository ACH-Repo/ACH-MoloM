"""Blender-style value field: drag horizontally to scrub, click to type
(with arithmetic — `3+5*1.3` evaluates on commit), Esc restores.

Used by the N transform panel. Thin: evaluation is core.mathexpr."""

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (QLabel, QLayout, QLineEdit,
                               QSizePolicy, QWidgetItem)

from ..core import mathexpr

_DRAG_SLOP_PX = 3


def make_text_selectable(root):
    """Let the user MARK AND COPY the text of every QLabel under `root`.

    Qt labels are not selectable by default, so everything MoloM computes and
    then displays — a resolved SMILES, the cell parameters, the space group, a
    density, the GL renderer string — was readable and impossible to copy.
    Christian: "I just tried to mark the resolved SMILES from name so I could
    copy it, but the highlighting is not possible."

    Applied to a CONTAINER rather than to each label by hand, because the
    failure mode of the hand-written version is a label added later that
    quietly is not selectable. Only labels that actually carry text are
    touched, and `TextSelectableByMouse` leaves the widget's appearance and
    layout alone — it does not make the label focusable or steal Tab.
    """
    flags = Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
    for label in root.findChildren(QLabel):
        # A label acting as a BUDDY carries a mnemonic ("&Name:") and must keep
        # its click-to-focus behaviour, so it is left alone.
        if label.buddy() is not None:
            continue
        label.setTextInteractionFlags(flags)
    return root


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

# Moved here from `debug_page.py` (round 45) when the outliner
# needed it too: an attachment row can carry an unbounded number of
# tick boxes once add-ons start contributing them, and a plain
# QHBoxLayout in a narrow dock hides the overflow with no hint it
# is there - the round-21 lesson.
class FlowLayout(QLayout):
    """A horizontal row that WRAPS instead of being cut off.

    The dock is narrow and its scroll area refuses horizontal scrolling (the
    round-21 lesson: fixed widths make part of a panel unreachable). A plain
    QHBoxLayout of nine buttons would push the last ones off the edge with no
    hint they were there, so the row wraps onto a second line instead.
    """

    def __init__(self, parent=None, spacing=4):
        super().__init__(parent)
        self._items = []
        self.setSpacing(spacing)
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._layout(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._layout(rect, apply=True)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _layout(self, rect, apply):
        x, y, line_height = rect.x(), rect.y(), 0
        space = self.spacing()
        for item in self._items:
            hint = item.sizeHint()
            nxt = x + hint.width()
            if nxt > rect.right() and line_height > 0:
                x = rect.x()
                y = y + line_height + space
                nxt = x + hint.width()
                line_height = 0
            if apply:
                item.setGeometry(QRect(x, y, hint.width(), hint.height()))
            x = nxt + space
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y()
