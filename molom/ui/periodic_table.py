"""Floating periodic table for edit mode — Avogadro's element picker.

Sits over the viewport immediately right of the tool column, and is only up
in **plain edit mode**: with the draw tool armed the element is whatever the
toolbar says and clicks are busy drawing, so the chart would be in the way.
Clicking a cell does exactly what typing the symbol and pressing Enter does
(set the draw element, convert any selected atoms) — one code path, see
`MolViewport.apply_element`.

Cells are painted in the element's own Jmol colour, so the table doubles as
the legend for what you are looking at in the viewport.
"""

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (QGridLayout, QLabel, QToolButton, QVBoxLayout,
                               QWidget)

from ..core import elements, ptable

_CELL = 21          # px per element button
_PANEL_STYLE = """
QWidget#ptableRoot {
    background: rgba(38, 38, 38, 205);
    border: 1px solid rgba(0, 0, 0, 110);
    border-radius: 6px;
}
QLabel#ptableTitle {
    color: rgba(235, 235, 235, 230);
    font-size: 11px;
    padding: 1px 2px;
}
"""


class PeriodicTablePanel(QWidget):
    """Floating element picker. Emits the canonical symbol ("Fe")."""

    element_picked = Signal(str)
    meta_atom_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ptableRoot")
        self.setStyleSheet(_PANEL_STYLE)
        self._buttons = {}          # type: dict
        self._current = ""

        outer = QVBoxLayout(self)
        outer.setContentsMargins(5, 4, 5, 5)
        outer.setSpacing(3)
        # Reads out whatever is hovered, so the full names are discoverable
        # without a tooltip delay.
        self.title = QLabel("Periodic table — click to set the element")
        self.title.setObjectName("ptableTitle")
        outer.addWidget(self.title)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(1)
        for z, row, col in ptable.layout():
            b = QToolButton(self)
            b.setText(elements.symbol(z))
            b.setFixedSize(QSize(_CELL, _CELL))
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip("{}  ({}, Z = {})".format(
                elements.name(z), elements.symbol(z), z))
            b.setStyleSheet(self._cell_style(z, current=False))
            b.clicked.connect(
                lambda _c=False, sym=elements.symbol(z):
                self.element_picked.emit(sym))
            b.installEventFilter(self)
            grid.addWidget(b, row, col)
            self._buttons[elements.symbol(z)] = (b, z)
        # The f-block placeholders, so row 6/7 read as continuous.
        for (row, col), text in ((ptable.LANTHANIDE_GAP, "*"),
                                 (ptable.ACTINIDE_GAP, "**")):
            gap = QLabel(text, self)
            gap.setAlignment(Qt.AlignCenter)
            gap.setFixedSize(QSize(_CELL, _CELL))
            gap.setStyleSheet("color: rgba(200, 200, 200, 150);"
                              "font-size: 10px;")
            grid.addWidget(gap, row, col)
        # Meta atom lives in the chart's empty top-middle, where the f-block
        # legend usually goes: it IS an element choice, just not a real one.
        self.meta_button = QToolButton(self)
        self.meta_button.setText("✳ Meta atom…")
        self.meta_button.setCursor(Qt.PointingHandCursor)
        self.meta_button.setToolTip(
            "Coordination centre that holds its geometry during optimisation "
            "(set the shape, the donor distance, and the element it becomes "
            "on export)")
        self.meta_button.setStyleSheet(
            "QToolButton { background: rgba(120, 80, 160, 220);"
            " color: #f2f2f2; border: 1px solid rgba(0,0,0,120);"
            " border-radius: 3px; font-size: 10px; padding: 2px 6px; }"
            "QToolButton:hover { border: 2px solid #ffffff; }")
        self.meta_button.clicked.connect(self.meta_atom_requested.emit)
        grid.addWidget(self.meta_button, 1, 3, 1, 8)

        grid.setRowMinimumHeight(ptable.MAIN_ROWS + 1, 5)   # f-block gap
        outer.addLayout(grid)
        self.adjustSize()

    @staticmethod
    def _cell_style(z, current):
        r, g, b = elements.color(z)
        fg = "#101010" if ptable.text_is_dark(z) else "#f2f2f2"
        border = ("2px solid #ffcc44" if current
                  else "1px solid rgba(0, 0, 0, 120)")
        return ("QToolButton {{ background: rgb({r},{g},{b}); color: {fg};"
                " border: {border}; border-radius: 3px; font-size: 9px;"
                " font-weight: bold; padding: 0px; }}"
                "QToolButton:hover {{ border: 2px solid #ffffff; }}"
                ).format(r=r, g=g, b=b, fg=fg, border=border)

    def eventFilter(self, obj, ev):
        if ev.type() == ev.Type.Enter:
            for sym, (btn, z) in self._buttons.items():
                if btn is obj:
                    self.title.setText("{}  —  {}  (Z = {})".format(
                        sym, elements.name(z), z))
                    break
        elif ev.type() == ev.Type.Leave:
            self._show_current()
        elif ev.type() == ev.Type.MouseButtonPress:
            self._press(obj, True)
        elif ev.type() == ev.Type.MouseButtonRelease:
            self._press(obj, False)
        return False

    @staticmethod
    def _press(button, down):
        """Nudge a cell down-right by a pixel while held.

        A flat coloured square gives no feedback at all on click — with 118
        of them side by side it is genuinely unclear whether the one under
        the cursor is the one that fired.
        """
        margin = button.contentsMargins()
        if down and margin.left() == 0:
            button.setContentsMargins(2, 2, 0, 0)
        elif not down:
            button.setContentsMargins(0, 0, 0, 0)

    def set_meta_label(self, element, geometry):
        # type: (str, str) -> None
        """Show what the armed meta atom IS: "Meta: Fe - octahedral"."""
        if not geometry:
            self.meta_button.setText("✳ Meta atom…")
            return
        short = geometry.replace("_", " ")
        self.meta_button.setText("✳ Meta: {} - {}".format(
            element or "?", short))

    def set_current(self, symbol):
        # type: (str) -> None
        """Ring the active draw element."""
        symbol = str(symbol or "")
        if symbol == self._current:
            return
        for sym in (self._current, symbol):
            entry = self._buttons.get(sym)
            if entry is not None:
                entry[0].setStyleSheet(self._cell_style(entry[1],
                                                        current=sym == symbol))
        self._current = symbol
        self._show_current()

    def _show_current(self):
        entry = self._buttons.get(self._current)
        if entry is None:
            self.title.setText("Periodic table — click to set the element")
            return
        self.title.setText("Element: {}  —  {}".format(
            self._current, elements.name(entry[1])))
