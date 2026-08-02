"""Blender-style tool strip: a translucent column of buttons floating over
the TOP-LEFT of the viewport (Blender's T panel), not a window-edge toolbar.

Buttons are checkable and mirror the viewport's current tool, so pressing
the hotkey lights the button and vice versa. Glyphs stand in for icons —
there are no icon assets in the repo, and unicode keeps it dependency-free.
"""

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QToolButton, QVBoxLayout, QWidget

_STYLE = """
QToolButton {
    background: rgba(40, 40, 40, 165);
    color: rgba(230, 230, 230, 220);
    border: 1px solid rgba(0, 0, 0, 90);
    border-radius: 5px;
    font-size: 15px;
}
QToolButton:hover   { background: rgba(75, 75, 75, 210); color: #ffffff; }
QToolButton:checked { background: rgba(70, 115, 175, 235); color: #ffffff;
                      border: 1px solid rgba(120, 170, 230, 220); }
QToolButton:disabled { color: rgba(150, 150, 150, 110); }
"""


class ViewportToolbar(QWidget):
    """Floating tool column. Emits the tool id when a button is pressed."""

    tool_clicked = Signal(str)

    # (id, glyph, tooltip, checkable)
    TOOLS = [
        ("select", "⬚", "Select — box select by dragging (default)", True),
        ("draw", "✎", "Draw atoms — click to change an element, drag from an "
                      "atom to add one, drag onto another to close a ring "
                      "(E, edit mode)", True),
        ("move", "✥", "Move the selection (G)", False),
        ("rotate", "⟳", "Rotate the selection (R)", False),
        ("origin", "◉", "Object origin — pick the orange dot up (Alt+O, edit "
                        "mode)", True),
        ("measure", "📏", "Measure — click 2 atoms for a distance, 3 for an "
                          "angle, 4 for a dihedral (Esc finishes)", True),
        ("optimize", "⚛", "Force-field clean-up panel (Ctrl+R)", False),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setStyleSheet(_STYLE)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(3)
        self.buttons = {}
        for tool_id, glyph, tip, checkable in self.TOOLS:
            b = QToolButton(self)
            b.setText(glyph)
            b.setToolTip(tip)
            b.setCheckable(checkable)
            b.setFixedSize(QSize(30, 30))
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _c=False, t=tool_id:
                              self.tool_clicked.emit(t))
            lay.addWidget(b)
            self.buttons[tool_id] = b
            if tool_id in ("select", "origin", "measure"):
                lay.addSpacing(4)      # Blender-ish grouping gaps
        self.buttons["select"].setChecked(True)
        self.adjustSize()

    def set_active(self, tool_id):
        """Light exactly one of the checkable tools."""
        for key, b in self.buttons.items():
            if b.isCheckable():
                b.setChecked(key == tool_id)

    def set_enabled_tools(self, edit_mode):
        for key in ("draw", "origin"):
            self.buttons[key].setEnabled(edit_mode)
        if not edit_mode:
            self.buttons["draw"].setChecked(False)
            self.buttons["origin"].setChecked(False)
