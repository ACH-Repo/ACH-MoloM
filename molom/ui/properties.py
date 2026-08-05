"""Properties editor — Blender's right-hand panel: a vertical strip of tab
buttons selecting one page at a time.

Pages: **Modifiers** (the non-destructive stack) and **Force field** (the
optimiser, moved in here so the right side is one dock rather than several
competing ones). The strip is what makes room for the pages that will follow
(CIF/unit cell, per-atom display, ...) without adding another dock each time.
"""

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDoubleValidator

from . import dragcheck
from ..core import vibrations
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDockWidget,
                               QLineEdit, QSlider,
                               QDoubleSpinBox, QFormLayout, QFrame,
                               QHBoxLayout, QLabel, QPushButton, QRadioButton,
                               QScrollArea, QSizePolicy, QSpinBox,
                               QStackedWidget, QToolButton, QVBoxLayout,
                               QWidget)

#: Amplitude defaults for a normal mode, in Angstrom. 0.2 A reads as a
#: vibration; the old 0.6 A default with a 2 A ceiling put the whole usable
#: range in the first fifth of the slider (Christian, 2026-08-03).
DEFAULT_AMPLITUDE = 0.2
AMP_MIN_STEPS = 5        # slider counts hundredths of an Angstrom
AMP_MAX_STEPS = 100

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
        self.add_combo.addItem("Boundary bonds", "boundary")
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
        elif getattr(mod, "kind", "") == "boundary":
            note = QLabel(
                "Bond perception measures straight lines, so a bond whose "
                "partner sits in the next cell is not drawn and a framework "
                "comes out severed at every face. This adds the periodic "
                "image at the far end of each such bond. The molecule itself "
                "is untouched — it stays the cell contents.")
            note.setWordWrap(True)
            note.setStyleSheet("color: rgba(200,200,200,150);")
            form.addRow(note)
            whole = QCheckBox("whole molecules")
            whole.setChecked(bool(getattr(mod, "whole_molecules", True)))
            whole.setToolTip(
                "Bring the WHOLE molecule on the far side of a cut bond "
                "(half an imidazolate ring is not a thing that exists). "
                "Off closes each bond with the single atom that completes "
                "it, which draws far fewer atoms.")
            whole.toggled.connect(
                lambda v, m=mod, s=summary:
                self._set(m, "whole_molecules", bool(v), s))
            form.addRow("", whole)
            shells = QSpinBox()
            shells.setRange(1, 4)
            shells.setValue(int(getattr(mod, "shells", 1)))
            shells.setMaximumWidth(60)
            shells.setToolTip(
                "Only used with 'whole molecules' off: how far to follow the "
                "bonds out. 1 closes every bond that crosses a face.")
            shells.valueChanged.connect(
                lambda v, m=mod, s=summary: self._set(m, "shells", int(v), s))
            form.addRow("Shells:", shells)
        elif getattr(mod, "kind", "") == "symmetry":
            # Without these the card is a bare title with an arrow that opens
            # onto nothing, which reads as a modifier that did not work.
            note = QLabel("The molecule stays the asymmetric unit; the "
                          "viewport and any export see the full cell.")
            note.setWordWrap(True)
            note.setStyleSheet("color: rgba(200,200,200,150);")
            form.addRow(note)
            cells = QHBoxLayout()
            cells.setSpacing(2)
            for a, attr in enumerate(("na", "nb", "nc")):
                box = QSpinBox()
                box.setRange(1, 12)
                box.setValue(int(getattr(mod, attr, 1)))
                box.setMaximumWidth(52)
                box.setToolTip("Cells along " + "abc"[a])
                box.valueChanged.connect(
                    lambda v, m=mod, k=attr, s=summary:
                    self._set(m, k, int(v), s))
                cells.addWidget(box)
            cells.addStretch(1)
            holder2 = QWidget()
            holder2.setLayout(cells)
            form.addRow("Cells:", holder2)
            form.addRow(self._symop_editor(mod, summary))
        body.setVisible(False)              # collapsed by default
        outer.addWidget(body)
        return card

    #: Ready-made single operations, so a space group can be built up one
    #: element at a time without remembering the xyz syntax. Christian's use
    #: case: take a fragment and watch it become a cell, a glide at a time.
    SYMOP_PRESETS = [
        ("Inversion centre", "-x,-y,-z"),
        ("2-fold about c", "-x,-y,z"),
        ("2-fold about b", "-x,y,-z"),
        ("2-fold about a", "x,-y,-z"),
        ("3-fold about c", "-y,x-y,z"),
        ("4-fold about c", "-y,x,z"),
        ("6-fold about c", "x-y,x,z"),
        ("2_1 screw along c", "-x,-y,1/2+z"),
        ("2_1 screw along b", "-x,1/2+y,-z"),
        ("2_1 screw along a", "1/2+x,-y,-z"),
        ("Mirror perp. c", "x,y,-z"),
        ("Mirror perp. b", "x,-y,z"),
        ("Mirror perp. a", "-x,y,z"),
        ("a-glide perp. c", "1/2+x,y,-z"),
        ("b-glide perp. c", "x,1/2+y,-z"),
        ("c-glide perp. a", "-x,y,1/2+z"),
        ("n-glide perp. c", "1/2+x,1/2+y,-z"),
        ("A-centring", "x,1/2+y,1/2+z"),
        ("B-centring", "1/2+x,y,1/2+z"),
        ("C-centring", "1/2+x,1/2+y,z"),
        ("I-centring", "1/2+x,1/2+y,1/2+z"),
    ]

    def _symop_editor(self, mod, summary):
        """Add and remove individual symmetry operations on this modifier.

        The point of stacking operations by hand is to SEE what each one
        does, so this is a list you can grow one entry at a time rather than
        a space-group name you either know or do not. Anything the CIF reader
        accepts is accepted here, and the presets cover the elements you would
        normally reach for.
        """
        holder = QWidget()
        col = QVBoxLayout(holder)
        col.setContentsMargins(0, 2, 0, 0)
        col.setSpacing(2)

        row = QHBoxLayout()
        row.setSpacing(3)
        preset = QComboBox()
        preset.addItem("Add operation...", "")
        for label, xyz in self.SYMOP_PRESETS:
            preset.addItem("{}   ({})".format(label, xyz), xyz)
        preset.setToolTip("Append one symmetry operation to this modifier")
        typed = QLineEdit()
        typed.setPlaceholderText("or type: -x, 1/2+y, -z")
        typed.setToolTip("Any operation in the CIF's own xyz notation")
        add = QToolButton()
        add.setText("+")
        add.setToolTip("Add the typed operation")
        row.addWidget(preset, 1)
        col.addLayout(row)
        row2 = QHBoxLayout()
        row2.setSpacing(3)
        row2.addWidget(typed, 1)
        row2.addWidget(add)
        col.addLayout(row2)

        listing = QVBoxLayout()
        listing.setContentsMargins(0, 0, 0, 0)
        listing.setSpacing(1)
        col.addLayout(listing)

        def rebuild_list():
            while listing.count():
                item = listing.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.setParent(None)
                    w.deleteLater()
            for k, text in enumerate(mod.symops):
                line = QHBoxLayout()
                line.setSpacing(3)
                tag = QLabel("{}.  {}".format(k + 1, text))
                tag.setStyleSheet("color: rgba(210,210,210,190);"
                                  " font-family: monospace;")
                drop = QToolButton()
                drop.setText("x")
                drop.setAutoRaise(True)
                drop.setToolTip("Remove this operation")
                drop.clicked.connect(
                    lambda _c=False, i=k: remove(i))
                line.addWidget(tag, 1)
                line.addWidget(drop)
                wrap = QWidget()
                wrap.setLayout(line)
                listing.addWidget(wrap)

        def remove(index):
            if 0 <= index < len(mod.symops):
                mod.symops.pop(index)
                summary.setText(self._summary(mod))
                rebuild_list()
                if not self._loading:
                    self.changed.emit()

        def append(text):
            text = (text or "").strip()
            if not text:
                return
            from ..core import cif as cif_mod
            try:
                cif_mod.SymOp.from_xyz(text)
            except Exception:
                typed.setStyleSheet("border: 1px solid #b05050;")
                typed.setToolTip("Not a symmetry operation: expected three "
                                 "comma-separated terms like '-x, 1/2+y, -z'")
                return
            typed.setStyleSheet("")
            if text not in mod.symops:
                mod.symops.append(text)
                summary.setText(self._summary(mod))
                rebuild_list()
                if not self._loading:
                    self.changed.emit()

        def take_preset(index):
            data = preset.itemData(index)
            if data:
                append(data)
            preset.setCurrentIndex(0)

        preset.currentIndexChanged.connect(take_preset)
        add.clicked.connect(lambda: append(typed.text()))
        typed.returnPressed.connect(lambda: append(typed.text()))
        rebuild_list()
        return holder

    @staticmethod
    def _summary(mod):
        kind = getattr(mod, "kind", "")
        if kind == "array":
            unit = "x size" if mod.relative else "A"
            return "x{}  ({:.2g}, {:.2g}, {:.2g}) {}".format(
                mod.count, *[float(v) for v in mod.offset], unit)
        if kind == "symmetry":
            block = "" if max(mod.na, mod.nb, mod.nc) <= 1 else \
                "  {}x{}x{}".format(mod.na, mod.nb, mod.nc)
            return "{} ops{}".format(len(mod.symops), block)
        if kind == "boundary":
            return ("close bonds across faces, whole molecules"
                    if getattr(mod, "whole_molecules", True)
                    else "close bonds across faces, {} shell(s)".format(
                        int(getattr(mod, "shells", 1))))
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
    exterior_toggled = Signal(bool)

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

        # VESTA's boundary search. Sits under Contents because that is what
        # it changes — what is DRAWN, not the cell itself.
        self.ext_check = QCheckBox("Bonded atoms outside the cell")
        self.ext_check.setToolTip(
            "Draw the atoms just beyond each face that are bonded to atoms "
            "inside the cell, so chains and frameworks run on instead of "
            "being cut off at the boundary (VESTA does this by default). "
            "The cell content is unchanged — these are extra atoms in the "
            "picture only.")
        self.ext_check.toggled.connect(
            lambda v: None if self._loading
            else self.exterior_toggled.emit(bool(v)))
        lay.addWidget(self.ext_check)
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
        # `clicked` carries the button's CHECKED state, and this button is not
        # checkable — so connecting it straight to `_toggle_kinds` passed
        # force=False every time and the arrow could only ever COLLAPSE. That
        # is Christian's "you have to untick and retick to get control over
        # the arrow expansion back": ticking the box was the only thing left
        # that could open the group. Swallow the argument so a click toggles.
        self.sym_arrow.clicked.connect(lambda _checked=False:
                                       self._toggle_kinds())
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
        """Expand/collapse the per-kind filters — and TICK the box on the way.

        Opening the group is a statement of intent: you are about to choose
        which elements to draw, which is meaningless while none of them are
        drawn at all. Christian asked for exactly this ("clicking the arrow
        should also immediately tick the Symmetry Elements checkbox"), and it
        removes the two-click dance of tick-then-expand.
        """
        # `isHidden`, NOT `isVisible`: a widget on a QStackedWidget page that
        # is not the current one reports isVisible() == False no matter what
        # its own flag says. Toggling off that would mean the arrow expands
        # every time and never collapses whenever the ❖ tab is not the one on
        # screen — which is most of the time, since the page is reached from
        # the outliner's "Advanced...". `isHidden` is the widget's OWN flag.
        show = self._kind_holder.isHidden() if force is None else bool(force)
        self._kind_holder.setVisible(show)
        self.sym_arrow.setText("▾" if show else "▸")
        if show and self.sym_check.isEnabled() and not self.sym_check.isChecked():
            self.sym_check.setChecked(True)      # emits toggled -> app redraws

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

    def set_cell(self, cell, spacegroup="", n_asym=0, n_atoms=0, mode="cell",
                 name="", exterior=0, chemistry=""):
        """Refresh from the active molecule.

        `cell=None` greys every CONTROL but leaves the page itself readable —
        the tab stays clickable (see `MainWindow._sync_crystal_page`), so this
        text is what the user gets when they open it on the wrong molecule and
        it has to say which molecule to pick instead.
        """
        has = cell is not None
        for w in (self.asym_radio, self.cell_radio, self.pack_radio,
                  self.box_check, self.poly_check, self.sym_check,
                  self.ghost_check, self._kind_holder, self.ext_check):
            w.setEnabled(has)
        self._sync_pack_enabled()
        # Guarded: writing a widget from sync fires its own valueChanged,
        # which the app would read back as "the user asked for this" — the
        # round-30 TimelinePanel bug in a different costume.
        self._loading = True
        self.ext_check.setChecked(bool(exterior))
        self._loading = False
        if not has:
            self.summary.setText(
                "<b>{}</b> has no unit cell, so there is nothing to show "
                "here.<br><br>Select a molecule imported from a <b>.cif</b> — "
                "in the viewport or in the outliner — and these controls "
                "become live.".format(name or "This molecule"))
            return
        self.summary.setText(
            "a = {:.4f}  b = {:.4f}  c = {:.4f} A\n"
            "alpha = {:.2f}  beta = {:.2f}  gamma = {:.2f}\n"
            "Space group: {}\nAsymmetric unit: {} site(s)\n"
            "Showing: {} atoms{}".format(
                cell.a, cell.b, cell.c, cell.alpha, cell.beta, cell.gamma,
                spacegroup or "not stated", n_asym, n_atoms,
                # What the reader REFUSED to draw. A silently dropped atom or
                # bond is indistinguishable from a bug, and this page is where
                # someone comes to ask why the cell looks like that.
                "\n" + chemistry if chemistry else ""))
        chosen = {"asym": self.asym_radio,
                  "packing": self.pack_radio}.get(mode, self.cell_radio)
        self._loading = True
        for b in (self.asym_radio, self.cell_radio, self.pack_radio):
            b.setChecked(b is chosen)
        self._loading = False


class VibrationPage(QWidget):
    """Normal modes of a FREQ job: one card per mode, over the settings that
    turn a mode into frames.

    Same card idiom as the modifier stack — a header you can scan (the
    frequency plus an animate button). A FREQ run has 3N modes, so a flat
    list of sliders would be unreadable; cards let you skim the spectrum and
    pick the one you care about.

    Amplitude and frames-per-period sit at the TOP, not on each card, because
    they are properties of the imported FREQ object rather than of one mode
    (round 30 — they were always stored per object, the per-card sliders just
    made it look otherwise and reset themselves on every rebuild). Frames per
    period steps in FOURS so both turning points of the oscillation are
    always sampled; see `core.vibrations.period_frames`.
    """

    mode_selected = Signal(int)                 # mode index -> animate it
    settings_changed = Signal(float, int)       # amplitude, frames/period
    load_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(4)
        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        lay.addWidget(self.summary)

        self.load_btn = QPushButton("Load ORCA frequencies...")
        self.load_btn.setToolTip(
            "Read normal modes from an ORCA FREQ output. Opening the .out "
            "file directly picks them up on its own.")
        self.load_btn.clicked.connect(self.load_requested)
        lay.addWidget(self.load_btn)

        # ---- per-OBJECT settings, above the mode list
        self.settings_box = QWidget()
        form = QFormLayout(self.settings_box)
        form.setContentsMargins(0, 2, 0, 2)
        form.setSpacing(3)
        # 0.05 .. 1.00 A on the slider: 2 A swings atoms clean through their
        # neighbours and reads as an explosion rather than a vibration, so
        # the useful range was squeezed into the first fifth of the travel.
        self.amp_slider = QSlider(Qt.Horizontal)
        self.amp_slider.setRange(AMP_MIN_STEPS, AMP_MAX_STEPS)
        self.amp_slider.setValue(int(round(DEFAULT_AMPLITUDE * 100)))
        self.amp_slider.setMaximumWidth(130)
        self.amp_slider.setToolTip(
            "Peak displacement of the busiest atom, in Angstrom")
        # ...and a box to TYPE in, which may go past the slider's top end:
        # the slider is calibrated for reading a mode, not for the occasional
        # deliberately absurd amplitude used to see where a mode is going.
        self.amp_spin = QDoubleSpinBox()
        self.amp_spin.setRange(0.01, 50.0)
        self.amp_spin.setDecimals(2)
        self.amp_spin.setSingleStep(0.05)
        self.amp_spin.setSuffix(" A")
        self.amp_spin.setValue(DEFAULT_AMPLITUDE)
        self.amp_spin.setMaximumWidth(86)
        self.amp_spin.setToolTip(
            "Type an exact amplitude. Values above the slider's {:g} A top "
            "end are allowed and simply peg the slider.".format(
                AMP_MAX_STEPS / 100.0))
        amp_row = QHBoxLayout()
        amp_row.setSpacing(4)
        amp_row.addWidget(self.amp_slider, 1)
        amp_row.addWidget(self.amp_spin)
        amp_holder = QWidget()
        amp_holder.setLayout(amp_row)

        self.frames_spin = QSpinBox()
        self.frames_spin.setRange(4, 120)
        self.frames_spin.setSingleStep(4)         # keeps the extremes sampled
        self.frames_spin.setValue(20)
        self.frames_spin.setMaximumWidth(80)
        self.frames_spin.setToolTip(
            "Frames generated for one period of the mode. Steps in fours so "
            "the sampling lands exactly on both turning points of the "
            "oscillation — otherwise the highest and lowest points of the "
            "coordinate are never reached. The player's Smoothing then "
            "subdivides between these frames.")
        form.addRow("Amplitude:", amp_holder)
        form.addRow("Frames / period:", self.frames_spin)

        # ---- which modes to show, and in what order
        self.sort_combo = QComboBox()
        self.sort_combo.addItem("Frequency", vibrations.SORT_FREQUENCY)
        self.sort_combo.addItem("IR intensity", vibrations.SORT_INTENSITY)
        self.sort_combo.setMaximumWidth(130)
        self.sort_combo.setToolTip(
            "Frequency lists the spectrum in order; IR intensity puts the "
            "bands you would actually see at the top")
        form.addRow("Sort by:", self.sort_combo)

        self.low_edit = QLineEdit()
        self.high_edit = QLineEdit()
        for edit, tip in ((self.low_edit, "Lowest wavenumber to show"),
                          (self.high_edit, "Highest wavenumber to show")):
            edit.setValidator(QDoubleValidator(-100000.0, 100000.0, 2, edit))
            edit.setPlaceholderText("any")
            edit.setMaximumWidth(62)
            edit.setToolTip(tip + " — leave empty for no bound. The list "
                                  "filters as you type.")
        range_row = QHBoxLayout()
        range_row.setSpacing(4)
        range_row.addWidget(self.low_edit)
        range_row.addWidget(QLabel("-"))
        range_row.addWidget(self.high_edit)
        range_row.addWidget(QLabel("cm-1"))
        range_row.addStretch(1)
        range_holder = QWidget()
        range_holder.setLayout(range_row)
        form.addRow("Range:", range_holder)
        lay.addWidget(self.settings_box)

        self.trivial_check = QCheckBox("Show translations / rotations")
        self.trivial_check.setToolTip(
            "The first six modes of a non-linear molecule are rigid motions "
            "at ~0 cm-1, not vibrations")
        lay.addWidget(self.trivial_check)

        self.count_label = QLabel("")
        self.count_label.setStyleSheet("color: rgba(200,200,200,150);")
        lay.addWidget(self.count_label)

        self.body = QWidget()
        self.column = QVBoxLayout(self.body)
        self.column.setContentsMargins(0, 4, 0, 0)
        self.column.setSpacing(3)
        lay.addWidget(self.body)
        lay.addStretch(1)

        self._modes = []
        self._active = None
        self._loading = False
        self.trivial_check.toggled.connect(lambda _v: self._rebuild())
        self.amp_slider.valueChanged.connect(self._on_amp_slider)
        self.amp_spin.valueChanged.connect(self._on_amp_typed)
        self.frames_spin.valueChanged.connect(self._emit_settings)
        self.sort_combo.currentIndexChanged.connect(lambda _i: self._rebuild())
        for edit in (self.low_edit, self.high_edit):
            edit.textChanged.connect(lambda _t: self._rebuild())
        dragcheck.install(self)
        self.set_modes([])

    # ---------------------------------------------------------- amplitude
    def _on_amp_slider(self, value):
        """Slider moved: mirror it into the type-in box and emit once."""
        if self._loading:
            return
        self._loading = True
        self.amp_spin.setValue(value / 100.0)
        self._loading = False
        self._emit_settings()

    def _on_amp_typed(self, value):
        """Box edited: peg the slider (the box may go past its top end)."""
        if self._loading:
            return
        self._loading = True
        self.amp_slider.setValue(
            max(AMP_MIN_STEPS, min(int(round(value * 100)), AMP_MAX_STEPS)))
        self._loading = False
        self._emit_settings()

    def amplitude(self):
        # type: () -> float
        """The typed box is authoritative — it is the one that can exceed
        the slider's range."""
        return float(self.amp_spin.value())

    def _emit_settings(self, _value=0):
        if not self._loading:
            self.settings_changed.emit(self.amplitude(),
                                       self.frames_spin.value())

    # ------------------------------------------------------------- content
    def set_modes(self, modes, active=None, name="",
                  amplitude=DEFAULT_AMPLITUDE,
                  n_frames=vibrations.DEFAULT_PERIOD_FRAMES):
        self._modes = list(modes or [])
        self._active = active
        # The PAGE stays usable with no data — only the parts that need modes
        # are switched off, so the tab can always be opened and read.
        self.settings_box.setEnabled(bool(self._modes))
        self.trivial_check.setEnabled(bool(self._modes))
        self._loading = True
        self.amp_spin.setValue(float(amplitude))
        self.amp_slider.setValue(
            max(AMP_MIN_STEPS,
                min(int(round(float(amplitude) * 100)), AMP_MAX_STEPS)))
        self.frames_spin.setValue(int(n_frames))
        self._loading = False
        if not self._modes:
            self.summary.setText(
                "<b>{}</b> has no vibrational data.<br>Open an ORCA FREQ "
                "output (the modes are picked up automatically), or load one "
                "onto this molecule below.".format(name or "This molecule"))
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

    @staticmethod
    def _number(edit):
        """A half-typed bound is no bound — "-" and "" both mean unbounded,
        which is what keeps the list from blinking empty mid-keystroke."""
        text = edit.text().strip().replace(",", ".")
        try:
            return float(text)
        except ValueError:
            return None

    def visible_modes(self):
        # type: () -> list
        """The modes the list is currently showing, in list order."""
        shown = vibrations.filter_modes(
            self._modes, self._number(self.low_edit),
            self._number(self.high_edit),
            include_trivial=self.trivial_check.isChecked())
        return vibrations.sort_modes(shown, self.sort_combo.currentData())

    def _rebuild(self):
        while self.column.count():
            widget = self.column.takeAt(0).widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        shown = self.visible_modes()
        for mode in shown:
            self.column.addWidget(self._mode_card(mode))
        if self._modes and not shown:
            empty = QLabel("No mode in that range.")
            empty.setStyleSheet("color: rgba(200,200,200,150);")
            self.column.addWidget(empty)
        self.count_label.setText(
            "{} of {} modes shown".format(len(shown), len(self._modes))
            if self._modes else "")

    def _mode_card(self, mode):
        """One row per mode: frequency + the button that animates it.

        No body to expand any more — the two settings that used to live in
        one belong to the whole FREQ object and are now at the top of the
        page, so a card is a single scannable line.
        """
        card = QFrame()
        card.setFrameShape(QFrame.StyledPanel)
        lit = 34 if self._active == mode.index else 10
        card.setStyleSheet(
            "QFrame {{ background: rgba(255,255,255,{}); border: 1px solid"
            " rgba(0,0,0,60); border-radius: 4px; }}".format(lit))
        head = QHBoxLayout(card)
        head.setContentsMargins(6, 2, 4, 2)
        head.setSpacing(4)

        title = QLabel("{:.2f} cm-1".format(mode.wavenumber))
        if mode.is_imaginary:
            title.setStyleSheet("color: #ff9d7a;")
            title.setToolTip("Imaginary — walks toward a transition state")
        elif mode.is_trivial:
            title.setStyleSheet("color: rgba(200,200,200,140);")

        # The intensity is on the card, not just in the sort order: sorting
        # by a number you cannot see is a list you have to trust blindly.
        intensity = QLabel("" if mode.intensity is None
                           else "{:.0f}".format(mode.intensity))
        intensity.setStyleSheet("color: rgba(190,205,225,170);")
        intensity.setToolTip("IR intensity, km/mol")
        intensity.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        intensity.setMinimumWidth(38)

        play = QToolButton()
        play.setText("A")            # a LETTER, per the outliner convention
        play.setAutoRaise(True)
        play.setToolTip("Animate this mode (adds it to the player track)")
        play.clicked.connect(
            lambda _c=False, i=mode.index: self.mode_selected.emit(i))

        head.addWidget(title, 1)
        head.addWidget(intensity)
        head.addWidget(play)
        return card


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
