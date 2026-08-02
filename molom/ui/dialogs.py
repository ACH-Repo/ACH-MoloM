"""Small dialogs: Settings, F3 operator search, Import-by-name (resolver).

All thin: values in, values out; persistence and side effects stay in app.py.
"""

from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPushButton, QSlider,
                               QSpinBox, QVBoxLayout)

from ..core import input_map
from ..core import resolve as resolve_mod


class SettingsDialog(QDialog):
    """App settings; live-applies rotation speed via `on_speed_change`."""

    def __init__(self, parent, rotate_speed, start_maximized,
                 precision_factor=0.5, undo_limit=30, adjust_h=True,
                 atom_scale=1.0, render_scale=2, render_subdiv=2,
                 input_preset=input_map.PRESET_AUTO, label_scale=1.0,
                 on_speed_change=None, on_atom_scale_change=None,
                 on_label_scale_change=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        form = QFormLayout(self)
        self._on_speed_change = on_speed_change

        self.input_combo = QComboBox()
        for preset in input_map.PRESETS:
            self.input_combo.addItem(input_map.PRESET_LABELS[preset], preset)
        current = input_map.normalize_preset(input_preset)
        self.input_combo.setCurrentIndex(input_map.PRESETS.index(current))
        form.addRow("Pointing device:", self.input_combo)
        form.addRow("", QLabel(
            "Trackpad: two-finger scroll orbits, Ctrl+scroll zooms.\n"
            "Mouse: the wheel zooms; middle-drag (or Alt+drag) orbits,\n"
            "Shift+middle pans. Auto picks per scroll event."))

        row = QHBoxLayout()
        self.speed_slider = QSlider(Qt.Horizontal)
        self.speed_slider.setRange(2, 30)               # 0.2 .. 3.0
        self.speed_slider.setValue(int(round(rotate_speed * 10)))
        self.speed_label = QLabel("{:.1f}x".format(rotate_speed))
        self.speed_slider.valueChanged.connect(self._speed_changed)
        row.addWidget(self.speed_slider, 1)
        row.addWidget(self.speed_label)
        form.addRow("Rotation sensitivity:", row)

        prow = QHBoxLayout()
        self.precision_slider = QSlider(Qt.Horizontal)
        self.precision_slider.setRange(5, 100)          # 0.05 .. 1.00
        self.precision_slider.setValue(int(round(precision_factor * 100)))
        self.precision_label = QLabel("{:.2f}x".format(precision_factor))
        self.precision_slider.valueChanged.connect(
            lambda v: self.precision_label.setText("{:.2f}x".format(v / 100.0)))
        prow.addWidget(self.precision_slider, 1)
        prow.addWidget(self.precision_label)
        form.addRow("Shift-drag precision:", prow)
        form.addRow("", QLabel("Speed multiplier while holding Shift in\n"
                               "G/R modals (0.50 = half speed)."))

        srow = QHBoxLayout()
        self.scale_slider = QSlider(Qt.Horizontal)
        self.scale_slider.setRange(20, 300)              # 0.2x .. 3.0x
        self.scale_slider.setValue(int(round(atom_scale * 100)))
        self.scale_label = QLabel("{:.2f}x".format(atom_scale))
        self._on_atom_scale_change = on_atom_scale_change
        self.scale_slider.valueChanged.connect(self._scale_changed)
        srow.addWidget(self.scale_slider, 1)
        srow.addWidget(self.scale_label)
        form.addRow("Sphere size:", srow)
        form.addRow("", QLabel("Scales every atom radius; the viewport\n"
                               "updates live."))

        lrow = QHBoxLayout()
        self.label_slider = QSlider(Qt.Horizontal)
        self.label_slider.setRange(40, 250)              # 0.4x .. 2.5x
        self.label_slider.setValue(int(round(label_scale * 100)))
        self.label_label = QLabel("{:.2f}x".format(label_scale))
        self._on_label_scale_change = on_label_scale_change
        self.label_slider.valueChanged.connect(self._label_scale_changed)
        lrow.addWidget(self.label_slider, 1)
        lrow.addWidget(self.label_label)
        form.addRow("Atom label size:", lrow)
        form.addRow("", QLabel("Element / index labels scale with the atom;\n"
                               "this multiplies that size."))

        self.undo_spin = QSpinBox()
        self.undo_spin.setRange(1, 500)
        self.undo_spin.setValue(int(undo_limit))
        self.undo_spin.setSuffix(" steps")
        self.undo_spin.setToolTip("How many undo/redo steps to keep "
                                  "(each step is a full scene snapshot)")
        form.addRow("Undo history:", self.undo_spin)

        self.adjust_h_check = QCheckBox(
            "Adjust hydrogens when editing elements")
        self.adjust_h_check.setChecked(bool(adjust_h))
        self.adjust_h_check.setToolTip(
            "Edit mode: adding or converting an atom re-dresses its "
            "hydrogens to the typical valence")
        form.addRow("", self.adjust_h_check)

        self.maximized_check = QCheckBox("Start maximized (fit to screen)")
        self.maximized_check.setChecked(start_maximized)
        form.addRow("", self.maximized_check)
        form.addRow("", QLabel("Windowed start anchors to the upper-right\n"
                               "corner of the screen."))

        form.addRow(QLabel("<b>Image export</b>"))
        self.render_scale_spin = QSpinBox()
        self.render_scale_spin.setRange(1, 8)
        self.render_scale_spin.setValue(int(render_scale))
        self.render_scale_spin.setSuffix("x viewport")
        self.render_scale_spin.setToolTip(
            "Resolution multiplier for Ctrl+Shift+E")
        form.addRow("Render resolution:", self.render_scale_spin)
        self.render_subdiv_spin = QSpinBox()
        self.render_subdiv_spin.setRange(0, 4)
        self.render_subdiv_spin.setValue(int(render_subdiv))
        self.render_subdiv_spin.setSuffix(" extra")
        self.render_subdiv_spin.setToolTip(
            "Extra mesh subdivisions for the render pass. Applies to the "
            "sphere/cylinder styles (ball and stick, licorice, VdW).")
        form.addRow("Render smoothness:", self.render_subdiv_spin)
        form.addRow("", QLabel("Renders exclude the grid, compass, labels\n"
                               "and gizmos, on a transparent background."))

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _speed_changed(self, value):
        speed = value / 10.0
        self.speed_label.setText("{:.1f}x".format(speed))
        if self._on_speed_change:
            self._on_speed_change(speed)

    def _scale_changed(self, value):
        scale = value / 100.0
        self.scale_label.setText("{:.2f}x".format(scale))
        if self._on_atom_scale_change:
            self._on_atom_scale_change(scale)

    def _label_scale_changed(self, value):
        scale = value / 100.0
        self.label_label.setText("{:.2f}x".format(scale))
        if self._on_label_scale_change:
            self._on_label_scale_change(scale)

    def label_scale(self):
        return self.label_slider.value() / 100.0

    def atom_scale(self):
        return self.scale_slider.value() / 100.0

    def render_scale(self):
        return int(self.render_scale_spin.value())

    def render_subdiv(self):
        return int(self.render_subdiv_spin.value())

    def rotate_speed(self):
        return self.speed_slider.value() / 10.0

    def input_preset(self):
        return self.input_combo.currentData()

    def precision_factor(self):
        return self.precision_slider.value() / 100.0

    def undo_limit(self):
        return int(self.undo_spin.value())

    def adjust_hydrogens(self):
        return self.adjust_h_check.isChecked()

    def start_maximized(self):
        return self.maximized_check.isChecked()


class MetaAtomDialog(QDialog):
    """The meta-atom window: geometry, donor distance, and what it becomes.

    Deliberately small — it is opened from a periodic-table cell, so it is in
    the same flow as picking an element and should not feel like a detour.
    """

    def __init__(self, parent, current=None, label=""):
        super().__init__(parent)
        from ..core import coordination, meta as meta_mod
        self.setWindowTitle("Meta atom" + (" — " + label if label else ""))
        form = QFormLayout(self)
        self._meta_mod = meta_mod

        form.addRow(QLabel(
            "A coordination centre that HOLDS ITS SHAPE while the\n"
            "force field relaxes the ligands around it — for metals\n"
            "MMFF/UFF have no parameters for."))

        self.geometry_combo = QComboBox()
        for name in sorted(coordination.GEOMETRY_DIRECTIONS):
            n = len(coordination.GEOMETRY_DIRECTIONS[name])
            self.geometry_combo.addItem(
                "{}  ({} donors)".format(name.replace("_", " "), n), name)
        form.addRow("Coordination geometry:", self.geometry_combo)

        self.distance_spin = QDoubleSpinBox()
        self.distance_spin.setRange(0.5, 6.0)
        self.distance_spin.setSingleStep(0.05)
        self.distance_spin.setDecimals(2)
        self.distance_spin.setSuffix(" A")
        self.distance_spin.setValue(2.0)
        form.addRow("Centre-donor distance r:", self.distance_spin)

        self.element_edit = QLineEdit()
        self.element_edit.setPlaceholderText("e.g. Fe, or iron")
        form.addRow("Becomes on export:", self.element_edit)
        form.addRow("", QLabel(
            "Left empty the atom is written as the dummy '{}'\n"
            "rather than silently guessing an element.".format(
                meta_mod.META_SYMBOL)))

        self.locked_check = QCheckBox(
            "Hold this geometry rigid during optimisation")
        self.locked_check.setChecked(True)
        form.addRow("", self.locked_check)

        self.idealize_check = QCheckBox(
            "Move the bonded donors onto the ideal positions now")
        self.idealize_check.setChecked(True)
        form.addRow("", self.idealize_check)

        if current is not None:
            i = self.geometry_combo.findData(current.geometry)
            if i >= 0:
                self.geometry_combo.setCurrentIndex(i)
            self.distance_spin.setValue(current.distance)
            self.element_edit.setText(current.element)
            self.locked_check.setChecked(current.locked)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                   | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _accept_if_valid(self):
        from ..core import elements
        text = self.element_edit.text().strip()
        if text and not elements.symbol_from_text(text):
            self.element_edit.selectAll()
            self.element_edit.setFocus()
            return                      # unknown element: don't close on it
        self.accept()

    def meta_atom(self):
        return self._meta_mod.MetaAtom(
            self.geometry_combo.currentData(),
            self.distance_spin.value(),
            self.element_edit.text().strip(),
            self.locked_check.isChecked())

    def idealize_now(self):
        return self.idealize_check.isChecked()


class OperatorSearchDialog(QDialog):
    """F3: type-to-filter operator list; Enter / double-click runs.

    Disabled operators (predicate false for the current selection state) are
    listed greyed at the bottom — visible so the palette teaches what exists,
    but not runnable."""

    def __init__(self, parent, registry, ctx):
        super().__init__(parent)
        self.setWindowTitle("Search operation")
        self.registry = registry
        self.ctx = ctx
        self.chosen = None      # type: Optional[object]
        lay = QVBoxLayout(self)
        self.edit = QLineEdit(self)
        self.edit.setPlaceholderText("Type to search operations...")
        self.list = QListWidget(self)
        lay.addWidget(self.edit)
        lay.addWidget(self.list, 1)
        self.edit.textChanged.connect(self._refill)
        self.edit.returnPressed.connect(self._run_current)
        self.list.itemActivated.connect(lambda _i: self._run_current())
        self.resize(420, 380)
        self._refill("")
        self.edit.setFocus()

    def _refill(self, text):
        """Grouped under category headers so a long list stays navigable —
        enabled operators first within each group, disabled ones greyed."""
        self.list.clear()
        hits = self.registry.search(text, self.ctx)
        groups = {}
        order = []
        for op, enabled in hits:
            cat = op.category or "Misc"
            if cat not in groups:
                groups[cat] = []
                order.append(cat)
            groups[cat].append((op, enabled))
        first_enabled = None
        for cat in order:
            header = QListWidgetItem("──  {}  ──".format(cat.upper()))
            header.setFlags(Qt.NoItemFlags)          # a divider, not a choice
            header.setForeground(QColor(130, 165, 205))
            f = header.font()
            f.setBold(True)
            header.setFont(f)
            self.list.addItem(header)
            for op, enabled in groups[cat]:
                label = op.label
                if op.shortcut:
                    label = "{}   ({})".format(label, op.shortcut)
                item = QListWidgetItem("    " + label)
                item.setData(Qt.UserRole, op.id)
                if not enabled:
                    item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
                self.list.addItem(item)
                if enabled and first_enabled is None:
                    first_enabled = self.list.count() - 1
        if first_enabled is not None:
            self.list.setCurrentRow(first_enabled)

    def _run_current(self):
        item = self.list.currentItem()
        if item is None or not (item.flags() & Qt.ItemIsEnabled):
            return
        self.chosen = self.registry.get(item.data(Qt.UserRole))
        self.accept()

    def keyPressEvent(self, ev):
        # Arrow keys steer the list while typing stays in the edit box;
        # category headers are skipped over rather than landed on.
        if ev.key() in (Qt.Key_Down, Qt.Key_Up):
            step = 1 if ev.key() == Qt.Key_Down else -1
            row = self.list.currentRow() + step
            while 0 <= row < self.list.count():
                if self.list.item(row).data(Qt.UserRole) is not None:
                    self.list.setCurrentRow(row)
                    return
                row += step
            return
        super().keyPressEvent(ev)


class _ResolveWorker(QThread):
    done = Signal(object)

    def __init__(self, query, parent=None):
        super().__init__(parent)
        self.query = query

    def run(self):
        self.done.emit(resolve_mod.resolve(self.query))


class ResolveNameDialog(QDialog):
    """Import by name (Ctrl+Shift+N): OPSIN -> PubChem -> did-you-mean.

    Resolution runs in a worker thread (12 s web timeout must not freeze the
    GUI). On success `self.resolution` holds the core Resolution object."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Import molecule by name")
        self.resolution = None
        self._worker = None
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Name / SMILES / InChI / CAS:"))
        self.edit = QLineEdit(self)
        lay.addWidget(self.edit)
        self.info = QLabel("")
        self.info.setWordWrap(True)
        lay.addWidget(self.info, 1)
        # "did you mean X?" as a CLICKABLE list, not prose. OWB does this and
        # it is obviously right: the whole point of a suggestion is that you
        # take it, and retyping a name you just misspelled is the one thing
        # you have already proved you cannot do.
        self.suggestions = QListWidget(self)
        self.suggestions.setVisible(False)
        self.suggestions.setMaximumHeight(110)
        self.suggestions.setToolTip("Click a suggestion to resolve it")
        self.suggestions.itemClicked.connect(self._take_suggestion)
        lay.addWidget(self.suggestions)
        row = QHBoxLayout()
        self.resolve_btn = QPushButton("Resolve")
        self.ok_btn = QPushButton("Import")
        self.ok_btn.setEnabled(False)
        cancel = QPushButton("Cancel")
        row.addWidget(self.resolve_btn)
        row.addStretch(1)
        row.addWidget(self.ok_btn)
        row.addWidget(cancel)
        lay.addLayout(row)
        self.resolve_btn.clicked.connect(self._start_resolve)
        self.edit.returnPressed.connect(self._start_resolve)
        self.ok_btn.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        self.resize(430, 300)

    def _start_resolve(self):
        q = self.edit.text().strip()
        if not q or self._worker is not None:
            return
        self.resolve_btn.setEnabled(False)
        self.info.setText("Resolving {!r}...".format(q))
        self._worker = _ResolveWorker(q, self)
        self._worker.done.connect(self._resolved)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.start()

    def _resolved(self, res):
        self._worker = None
        self.resolve_btn.setEnabled(True)
        if res.ok:
            self.resolution = res
            bits = ["SMILES: {}".format(res.smiles)]
            if res.formula:
                bits.append("Formula: {}".format(res.formula))
            if res.source:
                bits.append("Source: {}".format(res.source))
            if res.note:
                bits.append(res.note)
            self.info.setText("\n".join(bits))
            self.ok_btn.setEnabled(True)
        else:
            self.resolution = None
            self.ok_btn.setEnabled(False)
            self.info.setText(res.error or "no result")
        self._show_suggestions(getattr(res, "candidates", None) or [])

    def _show_suggestions(self, names):
        self.suggestions.clear()
        for name in names[:12]:
            self.suggestions.addItem(QListWidgetItem(str(name)))
        self.suggestions.setVisible(bool(names))

    def _take_suggestion(self, item):
        self.edit.setText(item.text())
        self.suggestions.setVisible(False)
        self._start_resolve()
