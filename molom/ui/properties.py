"""Properties editor — Blender's right-hand panel: a vertical strip of tab
buttons selecting one page at a time.

Pages: **Modifiers** (the non-destructive stack) and **Force field** (the
optimiser, moved in here so the right side is one dock rather than several
competing ones). The strip is what makes room for the pages that will follow
(CIF/unit cell, per-atom display, ...) without adding another dock each time.
"""

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDockWidget,
                               QDoubleSpinBox, QFormLayout, QFrame,
                               QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QSizePolicy, QSpinBox, QStackedWidget,
                               QToolButton, QVBoxLayout, QWidget)

_TAB_STYLE = """
QToolButton {
    background: rgba(48,48,48,220); color: rgba(225,225,225,210);
    border: 1px solid rgba(0,0,0,80); border-radius: 4px; font-size: 15px;
}
QToolButton:hover   { background: rgba(78,78,78,235); color: #fff; }
QToolButton:checked { background: rgba(70,115,175,240); color: #fff; }
"""


class ModifierPage(QWidget):
    """The stack for one object: add / edit / remove / apply."""

    changed = Signal()
    apply_requested = Signal()
    add_requested = Signal(str)
    remove_requested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        row = QHBoxLayout()
        row.setSpacing(4)
        self.add_combo = QComboBox()
        self.add_combo.addItem("Array", "array")
        self.add_combo.setMaximumWidth(120)
        add_btn = QPushButton("+ Add")
        add_btn.setMaximumWidth(70)
        add_btn.setToolTip("Add the chosen modifier to the active molecule")
        add_btn.clicked.connect(
            lambda: self.add_requested.emit(self.add_combo.currentData()))
        row.addWidget(self.add_combo, 1)
        row.addWidget(add_btn)
        lay.addLayout(row)

        self.body = QWidget()
        self.form = QVBoxLayout(self.body)     # a COLUMN of modifier cards
        self.form.setContentsMargins(0, 6, 0, 0)
        self.form.setSpacing(4)
        lay.addWidget(self.body)

        self.empty_label = QLabel("No modifiers on this molecule.\n"
                                  "An Array is the quick way to build a "
                                  "surface or a stack from one unit.")
        self.empty_label.setWordWrap(True)
        lay.addWidget(self.empty_label)
        lay.addStretch(1)

        self.apply_btn = QPushButton("Apply stack (bake into atoms)")
        self.apply_btn.clicked.connect(self.apply_requested)
        lay.addWidget(self.apply_btn)
        self._widgets = {}
        self._loading = False

    def sync(self, obj):
        # type: (Optional[object]) -> None
        while self.form.count():
            w = self.form.takeAt(0).widget()
            if w is not None:
                # detach NOW as well as scheduling deletion: deleteLater is
                # asynchronous, so a rebuild in the same tick would otherwise
                # still see the old cards as children.
                w.setParent(None)
                w.deleteLater()
        mods = list(getattr(obj, "modifiers", []) or []) if obj else []
        self.empty_label.setVisible(not mods)
        self.apply_btn.setEnabled(bool(mods))
        self.setEnabled(obj is not None)
        self._loading = True
        for k, mod in enumerate(mods):
            self.form.addWidget(self._modifier_card(mod, k))
        self._loading = False

    def _modifier_card(self, mod, index):
        """One modifier = one boxed row: a header that is always visible and
        a body that is COLLAPSED by default, so a stack of five reads as five
        lines instead of five screens."""
        card = QFrame()
        card.setFrameShape(QFrame.StyledPanel)
        card.setStyleSheet(
            "QFrame { background: rgba(255,255,255,10); border: 1px solid"
            " rgba(0,0,0,60); border-radius: 4px; }")
        outer = QVBoxLayout(card)
        outer.setContentsMargins(4, 3, 4, 3)
        outer.setSpacing(2)

        body = QWidget()
        head = QHBoxLayout()
        head.setSpacing(4)
        arrow = QToolButton()
        arrow.setText("▸")
        arrow.setFixedWidth(16)
        arrow.setAutoRaise(True)
        arrow.setToolTip("Expand / collapse this modifier")
        arrow.clicked.connect(
            lambda _c=False, b=body, a=arrow: self._toggle(b, a))
        on = QCheckBox(mod.name)
        on.setChecked(mod.enabled)
        on.setToolTip("Enable this modifier")
        on.toggled.connect(lambda v, m=mod: self._set(m, "enabled", v))
        summary = QLabel(self._summary(mod))
        summary.setStyleSheet("color: rgba(200,200,200,150);")
        # must be allowed to shrink, or the header pushes the card wider than
        # the dock and the delete button falls off the edge
        summary.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        summary.setMinimumWidth(0)
        gone = QToolButton()
        gone.setText("✕")
        gone.setAutoRaise(True)
        gone.setToolTip("Remove this modifier")
        gone.clicked.connect(lambda _c=False, i=index:
                             self.remove_requested.emit(i))
        head.addWidget(arrow)
        head.addWidget(on)
        head.addWidget(summary, 1)
        head.addWidget(gone)
        holder = QWidget()
        holder.setLayout(head)
        outer.addWidget(holder)

        form = QFormLayout(body)
        form.setContentsMargins(20, 2, 2, 2)
        form.setSpacing(3)
        form.setLabelAlignment(Qt.AlignRight)
        if getattr(mod, "kind", "") == "array":
            count = QSpinBox()
            count.setRange(1, 2000)
            count.setValue(mod.count)
            count.setMaximumWidth(80)
            count.valueChanged.connect(
                lambda v, m=mod, s=summary: self._set(m, "count", int(v), s))
            form.addRow("Count:", count)
            axes = QHBoxLayout()
            axes.setSpacing(2)
            for a in range(3):
                box = QDoubleSpinBox()
                box.setRange(-1000.0, 1000.0)
                box.setDecimals(2)
                box.setSingleStep(0.5)
                box.setValue(float(mod.offset[a]))
                box.setMaximumWidth(66)      # three of these must FIT
                box.setToolTip("XYZ"[a] + " offset")
                box.valueChanged.connect(
                    lambda v, m=mod, i=a, s=summary:
                    self._set_offset(m, i, v, s))
                axes.addWidget(box)
            cell = QWidget()
            cell.setLayout(axes)
            form.addRow("Offset:", cell)
            rel = QCheckBox("relative to size")
            rel.setChecked(mod.relative)
            rel.setToolTip("Offsets count in multiples of the molecule's "
                           "bounding box instead of Angstrom")
            rel.toggled.connect(
                lambda v, m=mod, s=summary:
                self._set(m, "relative", bool(v), s))
            form.addRow("", rel)
        body.setVisible(False)              # collapsed by default
        outer.addWidget(body)
        return card

    @staticmethod
    def _summary(mod):
        if getattr(mod, "kind", "") == "array":
            unit = "x size" if mod.relative else "A"
            return "x{}  ({:.2g}, {:.2g}, {:.2g}) {}".format(
                mod.count, *[float(v) for v in mod.offset], unit)
        return ""

    def _toggle(self, body, arrow):
        body.setVisible(not body.isVisible())
        arrow.setText("▾" if body.isVisible() else "▸")

    def _set(self, mod, attr, value, summary=None):
        setattr(mod, attr, value)
        if summary is not None:
            summary.setText(self._summary(mod))
        if not self._loading:
            self.changed.emit()

    def _set_offset(self, mod, axis, value, summary=None):
        mod.offset[axis] = float(value)
        if summary is not None:
            summary.setText(self._summary(mod))
        if not self._loading:
            self.changed.emit()


class PropertiesDock(QDockWidget):
    """Right-hand dock: vertical tab strip + stacked pages."""

    def __init__(self, pages, parent=None):
        # pages: [(key, glyph, tooltip, widget), ...]
        super().__init__("Properties", parent)
        self.setObjectName("properties")
        root = QWidget(self)
        lay = QHBoxLayout(root)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(4)

        strip = QVBoxLayout()
        strip.setSpacing(3)
        strip.setContentsMargins(0, 2, 0, 2)
        self.stack = QStackedWidget()
        self.buttons = {}
        for index, (key, glyph, tip, widget) in enumerate(pages):
            b = QToolButton()
            b.setText(glyph)
            b.setToolTip(tip)
            b.setCheckable(True)
            b.setFixedSize(28, 28)
            b.setStyleSheet(_TAB_STYLE)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _c=False, i=index, k=key:
                              self.show_page(k))
            strip.addWidget(b)
            self.buttons[key] = (b, index)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(widget)
            scroll.setFrameShape(QFrame.NoFrame)
            # Never scroll sideways — the panel is narrow, so content must
            # fit its width and grow downward instead of getting cut off.
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.stack.addWidget(scroll)
        strip.addStretch(1)
        lay.addLayout(strip)
        lay.addWidget(self.stack, 1)
        self.setWidget(root)
        if pages:
            self.show_page(pages[0][0])

    def show_page(self, key):
        entry = self.buttons.get(key)
        if entry is None:
            return
        self.stack.setCurrentIndex(entry[1])
        for k, (btn, _i) in self.buttons.items():
            btn.setChecked(k == key)
