"""Blender's at-the-cursor choice popup.

When one key can mean several things Blender does not open a dialog in the
middle of the screen — it drops a small list right where the pointer already
is, so the eye never has to travel and the mouse barely moves. Click an entry,
or walk it with the arrow keys and confirm with Enter; Escape or clicking
away cancels.

Kept generic on purpose: `J` (join) is the first user, but every "this key
could do two things" case wants exactly this widget.
"""

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QCursor, QFont
from PySide6.QtWidgets import (QFrame, QLabel, QListWidget, QListWidgetItem,
                               QVBoxLayout)

_STYLE = """
QFrame#choiceRoot {
    background: rgba(42, 42, 42, 245);
    border: 1px solid rgba(0, 0, 0, 140);
    border-radius: 5px;
}
QLabel#choiceTitle {
    color: rgba(190, 190, 190, 230);
    font-size: 11px;
    padding: 3px 6px 1px 6px;
}
QListWidget {
    background: transparent;
    border: none;
    color: rgba(230, 230, 230, 240);
    font-size: 12px;
    outline: none;
}
QListWidget::item { padding: 3px 8px; border-radius: 3px; }
QListWidget::item:selected { background: rgba(70, 115, 175, 240); color: #fff; }
"""


class ChoicePopup(QFrame):
    """A small at-the-cursor menu. `chosen` carries the picked key."""

    chosen = Signal(str)

    def __init__(self, title, options, parent=None):
        # options: [(key, label, tooltip), ...]
        super().__init__(parent, Qt.Popup)
        self.setObjectName("choiceRoot")
        self.setStyleSheet(_STYLE)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 3)
        lay.setSpacing(1)

        heading = QLabel(title, self)
        heading.setObjectName("choiceTitle")
        lay.addWidget(heading)

        self.list = QListWidget(self)
        self.list.setFrameShape(QFrame.NoFrame)
        widest = 0
        metrics = self.list.fontMetrics()
        for key, label, tip in options:
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, key)
            if tip:
                item.setToolTip(tip)
            self.list.addItem(item)
            widest = max(widest, metrics.horizontalAdvance(label))
        self.list.setCurrentRow(0)
        self.list.itemClicked.connect(self._pick)
        self.list.setFixedHeight(
            self.list.sizeHintForRow(0) * self.list.count() + 6)
        lay.addWidget(self.list)
        self.setFixedWidth(max(widest + 44,
                               metrics.horizontalAdvance(title) + 26))
        self.list.setFocus()

    def _pick(self, item):
        self.close()
        self.chosen.emit(str(item.data(Qt.UserRole)))

    def keyPressEvent(self, ev):
        if ev.key() in (Qt.Key_Return, Qt.Key_Enter):
            item = self.list.currentItem()
            if item is not None:
                self._pick(item)
            return
        if ev.key() == Qt.Key_Escape:
            self.close()
            return
        super().keyPressEvent(ev)

    def popup_at_cursor(self):
        """Show with the FIRST entry under the pointer, Blender-style: the
        default choice is the one you are already hovering, so a confident
        user can click straight through without reading."""
        pos = QCursor.pos() - QPoint(18, 22)
        screen = self.screen().availableGeometry() if self.screen() else None
        if screen is not None:
            pos.setX(max(screen.left(),
                         min(pos.x(), screen.right() - self.width())))
            pos.setY(max(screen.top(),
                         min(pos.y(), screen.bottom() - self.height())))
        self.move(pos)
        self.show()
        self.list.setFocus()
        return self
