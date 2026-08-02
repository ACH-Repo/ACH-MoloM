"""Properties editor — Blender's right-hand panel: a vertical strip of tab
buttons selecting one page at a time.

Pages: **Modifiers** (the non-destructive stack) and **Force field** (the
optimiser, moved in here so the right side is one dock rather than several
competing ones). The strip is what makes room for the pages that will follow
(CIF/unit cell, per-atom display, ...) without adding another dock each time.
"""

from typing import Optional

from PySide6.QtCore import Qt, Signal

from . import dragcheck
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDockWidget,
                               QSlider,
                               QDoubleSpinBox, QFormLayout, QFrame,
                               QHBoxLayout, QLabel, QPushButton, QRadioButton,
                               QScrollArea, QSizePolicy, QSpinBox,
                               QStackedWidget, QToolButton, QVBoxLayout,
                               QWidget)

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
        self.add_combo.addItem("Symmetry (CIF)", "symmetry")
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


class CrystalPage(QWidget):
    """Unit-cell controls for a CIF import — the page the module docstring
    always promised.

    The asym/cell/packing switch lived only in a menu and in F3, which is
    exactly the kind of thing you never find: it is a property OF the
    molecule, so it belongs beside the molecule's other properties.
    """

    view_changed = Signal(str, int, int, int)   # mode, na, nb, nc
    box_toggled = Signal(bool)
    poly_toggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(6)

        self.summary = QLabel("No unit cell.\nImport a .cif to use this page.")
        self.summary.setWordWrap(True)
        lay.addWidget(self.summary)

        self.box_check = QCheckBox("Show unit cell box")
        self.box_check.setChecked(True)
        self.box_check.toggled.connect(self.box_toggled.emit)
        lay.addWidget(self.box_check)

        lay.addWidget(QLabel("<b>Contents</b>"))
        self.asym_radio = QRadioButton("Asymmetric unit only")
        self.cell_radio = QRadioButton("Full unit cell")
        self.pack_radio = QRadioButton("Packing / supercell")
        self.cell_radio.setChecked(True)
        self.asym_radio.setToolTip(
            "Just the sites the file lists, before symmetry is applied")
        for b in (self.asym_radio, self.cell_radio, self.pack_radio):
            lay.addWidget(b)

        row = QHBoxLayout()
        self.na = QSpinBox()
        self.nb = QSpinBox()
        self.nc = QSpinBox()
        for s in (self.na, self.nb, self.nc):
            s.setRange(1, 12)
            s.setValue(2)
            s.setMaximumWidth(52)
            row.addWidget(s)
        row.addStretch(1)
        lay.addLayout(row)
        self._pack_row = row
        self._loading = False

        lay.addStretch(1)
        # No Apply button: every control here is a switch or a small count,
        # and a change you have to confirm is a change you cannot judge.
        for b in (self.asym_radio, self.cell_radio, self.pack_radio):
            b.toggled.connect(lambda on: self._apply() if on else None)
        for s in (self.na, self.nb, self.nc):
            s.valueChanged.connect(self._apply_if_packing)
        # The supercell counts only mean anything under "Packing".
        self.pack_radio.toggled.connect(self._sync_pack_enabled)
        self._sync_pack_enabled(False)

        # An expansion arrow, like a modifier card: without it there is no
        # sign that the kind filters exist at all (Christian's note).
        sym_row = QHBoxLayout()
        sym_row.setSpacing(3)
        self.sym_arrow = QToolButton()
        self.sym_arrow.setText("▸")
        self.sym_arrow.setFixedWidth(16)
        self.sym_arrow.setAutoRaise(True)
        self.sym_arrow.setToolTip("Show which kinds of element to draw")
        self.sym_check = QCheckBox("Symmetry elements")
        self.sym_check.setToolTip(
            "Draw the space group's axes, mirrors, glides and inversion "
            "centres in the standard crystallographic glyphs")
        # Per-KIND filter: Fm-3m has enough distinct elements that drawing
        # them all is an orange hairball (Christian's MOF-5 screenshot).
        self.kind_checks = {}
        kinds = QVBoxLayout()
        kinds.setContentsMargins(18, 0, 0, 0)
        kinds.setSpacing(1)
        for key, label in (("rotation", "rotation axes"),
                           ("screw", "screw axes"),
                           ("mirror", "mirror planes"),
                           ("glide", "glide planes"),
                           ("inversion", "inversion centres"),
                           ("rotoinversion", "rotoinversion axes")):
            box = QCheckBox(label)
            box.setChecked(True)
            self.kind_checks[key] = box
            kinds.addWidget(box)
        self._kind_holder = QWidget()
        self._kind_holder.setLayout(kinds)

        self.ghost_check = QCheckBox("Ghost images of the asymmetric unit")
        self.ghost_check.setToolTip(
            "Outline where every symmetry copy of the asymmetric unit lands "
            "— usually the quickest answer to 'how does this fill the cell'")
        sym_row.addWidget(self.sym_arrow)
        sym_row.addWidget(self.sym_check, 1)
        sym_holder = QWidget()
        sym_holder.setLayout(sym_row)
        lay.insertWidget(3, sym_holder)
        lay.insertWidget(4, self._kind_holder)
        lay.insertWidget(5, self.ghost_check)
        self.sym_arrow.clicked.connect(self._toggle_kinds)
        self.sym_check.toggled.connect(
            lambda on: self._toggle_kinds(on) if on else None)
        self._kind_holder.setVisible(False)
        dragcheck.install(self)

        self.poly_check = QCheckBox("Coordination polyhedra")
        self.poly_check.setToolTip(
            "Draw a translucent solid through the donor atoms around each "
            "metal centre — how MOFs and framework structures are usually "
            "shown")
        lay.insertWidget(2, self.poly_check)
        self.set_cell(None)

    def _toggle_kinds(self, force=None):
        show = (not self._kind_holder.isVisible()) if force is None             else bool(force)
        self._kind_holder.setVisible(show)
        self.sym_arrow.setText("▾" if show else "▸")

    def enabled_kinds(self):
        """Which symmetry element kinds the user wants drawn."""
        return [k for k, b in self.kind_checks.items() if b.isChecked()]

    def _sync_pack_enabled(self, _on=False):
        packing = self.pack_radio.isChecked() and self.pack_radio.isEnabled()
        for s in (self.na, self.nb, self.nc):
            s.setEnabled(packing)

    def _apply_if_packing(self, _value=0):
        if self.pack_radio.isChecked():
            self._apply()

    def _apply(self):
        if self._loading:
            return
        mode = ("asym" if self.asym_radio.isChecked()
                else "packing" if self.pack_radio.isChecked() else "cell")
        self.view_changed.emit(mode, self.na.value(), self.nb.value(),
                               self.nc.value())

    def set_cell(self, cell, spacegroup="", n_asym=0, n_atoms=0, mode="cell"):
        """Refresh from the active molecule; None disables the whole page."""
        has = cell is not None
        for w in (self.asym_radio, self.cell_radio, self.pack_radio,
                  self.box_check, self.poly_check, self.sym_check,
                  self.ghost_check, self._kind_holder):
            w.setEnabled(has)
        self._sync_pack_enabled()
        if not has:
            self.summary.setText(
                "No unit cell.\nImport a .cif to use this page.")
            return
        self.summary.setText(
            "a = {:.4f}  b = {:.4f}  c = {:.4f} A\n"
            "alpha = {:.2f}  beta = {:.2f}  gamma = {:.2f}\n"
            "Space group: {}\nAsymmetric unit: {} site(s)\n"
            "Showing: {} atoms".format(
                cell.a, cell.b, cell.c, cell.alpha, cell.beta, cell.gamma,
                spacegroup or "not stated", n_asym, n_atoms))
        chosen = {"asym": self.asym_radio,
                  "packing": self.pack_radio}.get(mode, self.cell_radio)
        self._loading = True
        for b in (self.asym_radio, self.cell_radio, self.pack_radio):
            b.setChecked(b is chosen)
        self._loading = False


class VibrationPage(QWidget):
    """Normal modes of a FREQ job: one expandable card per mode.

    Same card idiom as the modifier stack — a header you can scan (the
    frequency plus a play button) and a body, collapsed, holding the
    sliders. A FREQ run has 3N modes, so a flat list of sliders would be
    unreadable; collapsed cards let you skim the spectrum and open only the
    one you care about.
    """

    mode_selected = Signal(int)                 # mode index -> animate it
    mode_settings = Signal(int, float, int)     # index, amplitude, n_frames

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(4)
        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        lay.addWidget(self.summary)

        self.trivial_check = QCheckBox("Show translations / rotations")
        self.trivial_check.setToolTip(
            "The first six modes of a non-linear molecule are rigid motions "
            "at ~0 cm-1, not vibrations")
        lay.addWidget(self.trivial_check)

        self.body = QWidget()
        self.column = QVBoxLayout(self.body)
        self.column.setContentsMargins(0, 4, 0, 0)
        self.column.setSpacing(3)
        lay.addWidget(self.body)
        lay.addStretch(1)

        self._modes = []
        self._active = None
        self.trivial_check.toggled.connect(lambda _v: self._rebuild())
        dragcheck.install(self)
        self.set_modes([])

    # ------------------------------------------------------------- content
    def set_modes(self, modes, active=None, name=""):
        self._modes = list(modes or [])
        self._active = active
        self.setEnabled(bool(self._modes))
        if not self._modes:
            self.summary.setText(
                "No vibrational data.\n"
                "F3 → \"load ORCA frequencies\" for this molecule.")
        else:
            real = [m for m in self._modes if not m.is_trivial]
            imaginary = [m for m in self._modes if m.is_imaginary]
            note = ""
            if imaginary:
                note = ("\n{} IMAGINARY — a saddle point, not a "
                        "minimum".format(len(imaginary)))
            self.summary.setText("{}\n{} modes, {} vibrational{}".format(
                name or "", len(self._modes), len(real), note))
        self._rebuild()

    def _rebuild(self):
        while self.column.count():
            widget = self.column.takeAt(0).widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        show_trivial = self.trivial_check.isChecked()
        for mode in self._modes:
            if mode.is_trivial and not show_trivial:
                continue
            self.column.addWidget(self._mode_card(mode))

    def _mode_card(self, mode):
        card = QFrame()
        card.setFrameShape(QFrame.StyledPanel)
        lit = 34 if self._active == mode.index else 10
        card.setStyleSheet(
            "QFrame {{ background: rgba(255,255,255,{}); border: 1px solid"
            " rgba(0,0,0,60); border-radius: 4px; }}".format(lit))
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
        arrow.setToolTip("Amplitude and smoothness for this mode")
        arrow.clicked.connect(
            lambda _c=False, b=body, a=arrow: self._toggle(b, a))

        title = QLabel("{:.2f} cm-1".format(mode.wavenumber))
        if mode.is_imaginary:
            title.setStyleSheet("color: #ff9d7a;")
            title.setToolTip("Imaginary — walks toward a transition state")
        elif mode.is_trivial:
            title.setStyleSheet("color: rgba(200,200,200,140);")

        play = QToolButton()
        play.setText("A")            # a LETTER, per the outliner convention
        play.setAutoRaise(True)
        play.setToolTip("Animate this mode (adds it to the player track)")
        play.clicked.connect(
            lambda _c=False, i=mode.index: self.mode_selected.emit(i))

        head.addWidget(arrow)
        head.addWidget(title, 1)
        head.addWidget(play)
        holder = QWidget()
        holder.setLayout(head)
        outer.addWidget(holder)

        form = QFormLayout(body)
        form.setContentsMargins(20, 2, 2, 2)
        form.setSpacing(3)
        amp = QSlider(Qt.Horizontal)
        amp.setRange(5, 200)                 # 0.05 .. 2.00 Angstrom
        amp.setValue(60)
        amp.setToolTip("Peak displacement of the busiest atom, in Angstrom")
        steps = QSlider(Qt.Horizontal)
        steps.setRange(6, 60)                # frames per period
        steps.setValue(20)
        steps.setToolTip(
            "Frames per period. More is smoother, though the player "
            "interpolates between them anyway")
        for widget in (amp, steps):
            widget.setMaximumWidth(150)
        amp.valueChanged.connect(
            lambda v, i=mode.index, s=steps:
            self.mode_settings.emit(i, v / 100.0, s.value()))
        steps.valueChanged.connect(
            lambda v, i=mode.index, a=amp:
            self.mode_settings.emit(i, a.value() / 100.0, v))
        form.addRow("Amplitude:", amp)
        form.addRow("Frames:", steps)
        body.setVisible(False)
        outer.addWidget(body)
        return card

    @staticmethod
    def _toggle(body, arrow):
        body.setVisible(not body.isVisible())
        arrow.setText("▾" if body.isVisible() else "▸")


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
