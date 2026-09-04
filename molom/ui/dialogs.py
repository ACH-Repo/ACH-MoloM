"""Small dialogs: Settings, F3 operator search, Import-by-name (resolver).

All thin: values in, values out; persistence and side effects stay in app.py.
"""

import os
import re
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QImage, QPalette, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox,
                               QDialog,
                               QDialogButtonBox, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QGroupBox,
                               QFrame, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit,
                               QListWidget, QListWidgetItem, QPushButton,
                               QScrollArea, QSlider, QSpinBox,
                               QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from ..core import blender_export as bx
from ..core import cellbox as cellbox_mod
from ..core import cif as cif_mod
from ..core import cifsearch
from ..core import depict as depict_mod
from ..core import molprops
from ..core import flight, input_map
from ..core import style as style_mod
from .search_table import ResultTable
from .widgets import make_text_selectable


class SettingsDialog(QDialog):
    """App settings; live-applies rotation speed via `on_speed_change`."""

    def __init__(self, parent, rotate_speed, start_maximized,
                 precision_factor=0.5, undo_limit=30, adjust_h=True,
                 atom_scale=1.0, render_scale=2, render_subdiv=2,
                 render_crop=False,
                 input_preset=input_map.PRESET_AUTO, label_scale=1.0,
                 disorder_policy=None, sg_convention=None,
                 cif_search_root="",
                 on_speed_change=None, on_atom_scale_change=None,
                 on_label_scale_change=None, flight_tuning=None,
                 on_flight_change=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        # The page outgrew the screen once Flight arrived, so it scrolls — and
        # a scrolling page needs a way to get somewhere without scrolling, so
        # there is a filter box in the top right. `form` still holds every
        # row, exactly as before; only its container changed.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        head = QHBoxLayout()
        head.setContentsMargins(8, 8, 8, 0)
        head.addStretch(1)
        self.filter_edit = QLineEdit(self)
        self.filter_edit.setPlaceholderText("Filter settings…")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.setFixedWidth(190)
        self.filter_edit.setToolTip(
            "Show only the settings whose name or description matches")
        self.filter_edit.textChanged.connect(self._apply_filter)
        head.addWidget(self.filter_edit)
        outer.addLayout(head)

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget(self._scroll)
        self._scroll.setWidget(body)
        outer.addWidget(self._scroll, 1)
        form = QFormLayout(body)
        self._form = form
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

        # ---------------------------------------------------- crystallography
        self.disorder_combo = QComboBox()
        self.disorder_combo.addItem("Resolve superimposed alternatives",
                                    cif_mod.POLICY_DOMINANT)
        self.disorder_combo.addItem("Only the major component (drop < 50%)",
                                    cif_mod.POLICY_MAJOR)
        self.disorder_combo.addItem("Draw every alternative (raw file)",
                                    cif_mod.POLICY_ALL)
        idx = self.disorder_combo.findData(disorder_policy)
        self.disorder_combo.setCurrentIndex(max(idx, 0))
        self.disorder_combo.setToolTip(
            "A disordered CIF lists every alternative position for a site. "
            "Drawing them all superimposes atoms that are never present "
            "together, which then perceives bonds that cannot exist. "
            "'Resolve' keeps the most occupied of each overlapping set; "
            "'major component' also drops everything under half occupancy, "
            "which usually means a framework without its disordered guest. "
            "Applies to the NEXT file opened.")
        form.addRow("CIF disorder:", self.disorder_combo)

        # Where the crystal search also looks. Blank by default and stays
        # blank: there is no sensible guess at where somebody keeps their CIF
        # collection, and a wrong default would silently search the wrong
        # tree. The remote tiers work with nothing set.
        self.cif_root_edit = QLineEdit(cif_search_root or "")
        self.cif_root_edit.setPlaceholderText("(none - remote sources only)")
        self.cif_root_edit.setToolTip(
            "A folder of .cif files that Ctrl+Shift+Alt+N searches alongside "
            "COD and OPTIMADE. Sub-folders are included. A structure you "
            "already have needs no network and is listed first, so this is "
            "worth setting even for a small collection.")
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._pick_cif_root)
        clear = QPushButton("Clear")
        clear.clicked.connect(lambda _c=False: self.cif_root_edit.setText(""))
        root_row = QHBoxLayout()
        root_row.setContentsMargins(0, 0, 0, 0)
        root_row.addWidget(self.cif_root_edit, 1)
        root_row.addWidget(browse, 0)
        root_row.addWidget(clear, 0)
        root_holder = QWidget()
        root_holder.setLayout(root_row)
        form.addRow("Local CIF folder:", root_holder)

        from ..core import spacegroups as _sg
        self.sg_convention_combo = QComboBox()
        for key, label in _sg.CONVENTIONS:
            self.sg_convention_combo.addItem(label, key)
        idx = self.sg_convention_combo.findData(sg_convention
                                                or _sg.CONVENTION_HM)
        self.sg_convention_combo.setCurrentIndex(max(idx, 0))
        self.sg_convention_combo.setToolTip(
            "How the space group is NAMED on the crystal page. This is a "
            "display choice only — the symmetry operations always come from "
            "the file, or from the group it names.\n\n"
            "Short Hermann-Mauguin keeps the SETTING (P2_1/n stays P2_1/n); "
            "the standard-setting form reports every setting of a group under "
            "its standard symbol, so a P2_1/n file reads as P2_1/c there.")
        form.addRow("Space group names:", self.sg_convention_combo)

        self.maximized_check = QCheckBox("Start maximized (fit to screen)")
        self.maximized_check.setChecked(start_maximized)
        form.addRow("", self.maximized_check)
        form.addRow("", QLabel("Windowed start anchors to the upper-right\n"
                               "corner of the screen."))

        # ------------------------------------------------------- flight
        # The 6DoF handling model is a matter of taste and of what you are
        # flying THROUGH — a tight cell wants a different feel from a big
        # framework — so the constants are exposed rather than baked in.
        form.addRow(QLabel("<b>Flight (right-drag / double-right-click)</b>"))
        self._on_flight_change = on_flight_change
        tuning = dict(flight_tuning or {})
        self._flight_sliders = {}
        for key, label, lo, hi, default, tip in (
                ("accel", "Acceleration", 10, 300, flight.DEFAULT_ACCEL,
                 "Thrust, in A/s^2. Higher gets you moving sooner."),
                ("damping", "Drag", 10, 200, flight.DEFAULT_DAMPING,
                 "How quickly speed bleeds off while thrusting. Higher is "
                 "less floaty and lowers your top speed."),
                ("brake_factor", "Auto-brake", 100, 400,
                 flight.DEFAULT_BRAKE_FACTOR,
                 "Extra drag applied the moment every thrust key is "
                 "released, as a multiple of Drag. 1.0 disables auto-braking "
                 "and you coast; 1.5-2.0 is the arcade band."),
                ("strafe_factor", "Strafe response", 50, 300,
                 flight.DEFAULT_STRAFE_FACTOR,
                 "Sideways and vertical acceleration relative to forward. "
                 "1.0 makes strafing exactly as responsive as flying "
                 "forward."),
                ("roll_rate", "Roll rate", 50, 600, flight.DEFAULT_ROLL_RATE,
                 "Q/E manual roll speed, in radians per second."),
                ("bank_angle", "Auto-bank", 0, 150,
                 flight.DEFAULT_BANK_ANGLE,
                 "How far the ship rolls into a turn, in radians at full "
                 "stick. The bank holds while the reticle is off centre and "
                 "eases back to level when you bring it home. 0 disables "
                 "automatic banking."),
                ("aim_expo", "Aim expo", 100, 400,
                 flight.DEFAULT_AIM_EXPO,
                 "Steering response curve. 1.00 is linear; higher makes the "
                 "reticle less sensitive near the middle so small "
                 "corrections are gentle, while full deflection still gives "
                 "the full turn rate."),
                ("turn_rate", "Turn rate", 20, 400, 1.0,
                 "Mouse-look sensitivity while flying. The response is "
                 "strictly 1:1 with the mouse; this only scales it."),
                ("shuttle_factor", "Shuttle speed", 5, 100,
                 flight.DEFAULT_SHUTTLE_FACTOR,
                 "How fast SHUTTLE mode is relative to camera flight, scaling "
                 "both the acceleration and the top speed. Flying the camera "
                 "is a navigation gesture; flying a molecule is a placement "
                 "one, where the thing you are moving has to stay in frame - "
                 "at camera speeds it leaves the viewport before the key comes "
                 "up. 1.00 makes them identical.")):
            # Acceleration is in whole A/s^2 (default 60); everything else is
            # a small multiplier held to 2 dp. Getting this wrong silently
            # CLAMPS the slider — the readout showed 60.00 while the slider
            # sat pinned at its maximum of 30.
            scale = 1.0 if key == "accel" else \
                10.0 if key == "damping" else 100.0
            value = float(tuning.get(key, default))
            slider = QSlider(Qt.Horizontal)
            slider.setRange(int(lo), int(hi))
            slider.setValue(int(round(value * scale)))
            readout = QLabel("{:.2f}".format(value))
            slider.valueChanged.connect(
                lambda v, k=key, s=scale, r=readout:
                self._flight_changed(k, v / s, r))
            slider.setToolTip(tip)
            readout.setToolTip(tip)
            frow = QHBoxLayout()
            frow.addWidget(slider, 1)
            frow.addWidget(readout)
            form.addRow(label + ":", frow)
            self._flight_sliders[key] = (slider, scale)
        # Not a feel constant like the rest: this is the ARBITRATION between
        # the right button's two meanings, and it is here because the only way
        # to judge it is to try both gestures.
        self.fly_hold_spin = QSpinBox()
        self.fly_hold_spin.setRange(0, 1200)
        self.fly_hold_spin.setSingleStep(50)
        self.fly_hold_spin.setSuffix(" ms")
        self.fly_hold_spin.setValue(
            int(tuning.get("hold_ms", flight.DEFAULT_HOLD_MS)))
        self.fly_hold_spin.setToolTip(
            "How long the right button must be held before flight starts. A "
            "shorter press is an ordinary right-click, which is what opens "
            "the geometry menu (bond length / angle / dihedral / twist) on a "
            "selected atom. Dragging takes off at once whatever this says. "
            "Set 0 to switch hold-to-fly off entirely, leaving right "
            "DOUBLE-click as the only way into flight.")
        self.fly_hold_spin.valueChanged.connect(
            lambda v: self._on_flight_change
            and self._on_flight_change("hold_ms", float(v)))
        form.addRow("Hold to fly:", self.fly_hold_spin)
        self._flight_sliders["hold_ms"] = (self.fly_hold_spin, 1.0)
        form.addRow("", QLabel(
            "W/A/S/D thrust and strafe, Space/Ctrl up-down, Q/E roll.\n"
            "Shift boosts, Alt creeps. Roll applies only while flying and\n"
            "levels out when you land."))

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
        self.render_crop_check = QCheckBox("Crop to content")
        self.render_crop_check.setChecked(bool(render_crop))
        self.render_crop_check.setToolTip(
            "Trim the exported image to what was actually drawn, plus a small "
            "margin, instead of keeping the whole viewport rectangle. The "
            "window is whatever shape it happens to be and the molecule sits "
            "wherever the camera left it, so an export otherwise carries a lot "
            "of empty background. A camera object's film back still wins — "
            "this only tightens what is inside it.")
        form.addRow("", self.render_crop_check)
        form.addRow("", QLabel("Renders exclude the grid, compass and gizmos,\n"
                               "on a transparent background. The unit cell,\n"
                               "polyhedra and occupancy spheres are kept."))

        # OK/Cancel stay OUTSIDE the scroll area — buttons you have to scroll
        # to find are buttons people think are missing.
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        brow = QHBoxLayout()
        brow.setContentsMargins(8, 0, 8, 8)
        brow.addWidget(buttons)
        outer.addLayout(brow)

        self._index_rows()
        self.resize(560, min(760, self.sizeHint().height()))

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

    # ------------------------------------------------------ filter/search
    def _row_text(self, row):
        """Everything about a form row that is worth matching against.

        Deliberately includes TOOLTIPS: the tooltip is where the real
        explanation lives for most of these controls, so "brake" should find
        Auto-brake even though the word only appears in its tooltip.
        """
        bits = []
        for role in (QFormLayout.LabelRole, QFormLayout.FieldRole,
                     QFormLayout.SpanningRole):
            item = self._form.itemAt(row, role)
            if item is None:
                continue
            widgets = []
            if item.widget() is not None:
                widgets.append(item.widget())
            elif item.layout() is not None:
                lay = item.layout()
                widgets = [lay.itemAt(i).widget()
                           for i in range(lay.count())
                           if lay.itemAt(i).widget() is not None]
            for w in widgets:
                if hasattr(w, "text"):
                    try:
                        bits.append(w.text())
                    except TypeError:       # e.g. QComboBox has no text()
                        pass
                if isinstance(w, QComboBox):
                    bits.extend(w.itemText(i) for i in range(w.count()))
                bits.append(w.toolTip())
        return " ".join(b for b in bits if b).lower()

    def _index_rows(self):
        """Group each row with the explanatory rows that follow it.

        A control and the small grey paragraph under it are two separate form
        rows, so filtering row-by-row would strip every explanation from the
        controls that survived. A row with an empty label belongs to the last
        NAMED row; a `<b>header</b>` row starts a section and is shown only
        when something inside it matches.
        """
        self._groups = []       # [(is_header, [row indices], searchable text)]
        for row in range(self._form.rowCount()):
            spanning = self._form.itemAt(row, QFormLayout.SpanningRole)
            label = self._form.itemAt(row, QFormLayout.LabelRole)
            text = self._row_text(row)
            header = spanning is not None and "<b>" in text
            named = label is not None and label.widget() is not None \
                and bool(getattr(label.widget(), "text", lambda: "")())
            if header or named or not self._groups:
                self._groups.append([header, [row], text])
            else:
                self._groups[-1][1].append(row)
                self._groups[-1][2] += " " + text

    def _apply_filter(self, text):
        # Match at WORD BOUNDARIES, not anywhere in the string: a plain
        # substring search has "roll" pulling up the pointing-device row
        # because its description mentions scrolling. Prefixes still work, so
        # typing "acce" finds Acceleration.
        terms = [re.compile(r"\b" + re.escape(t))
                 for t in str(text).strip().lower().split() if t]
        shown_since_header = False
        header_index = None
        header_matched = False
        for index, (header, rows, haystack) in enumerate(self._groups):
            if header:
                # Decided once its contents have been judged; park it.
                if header_index is not None:
                    self._set_group_visible(header_index, shown_since_header)
                header_index = index
                # Matching the SECTION NAME reveals everything under it —
                # typing "flight" should give you the flight settings, not an
                # empty page with a heading you cannot act on.
                header_matched = bool(terms) and all(
                    t.search(haystack) for t in terms)
                shown_since_header = header_matched
                continue
            match = header_matched or all(t.search(haystack) for t in terms)
            shown_since_header = shown_since_header or match
            self._set_group_visible(index, match)
        if header_index is not None:
            self._set_group_visible(header_index, shown_since_header)

    def _set_group_visible(self, index, visible):
        for row in self._groups[index][1]:
            self._form.setRowVisible(row, bool(visible))

    def _flight_changed(self, key, value, readout):
        readout.setText("{:.2f}".format(value))
        if self._on_flight_change:
            self._on_flight_change(key, value)

    def flight_tuning(self):
        # type: () -> dict
        return {k: s.value() / scale
                for k, (s, scale) in self._flight_sliders.items()}

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

    def render_crop(self):
        return bool(self.render_crop_check.isChecked())

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

    def disorder_policy(self):
        return self.disorder_combo.currentData()

    def sg_convention(self):
        return self.sg_convention_combo.currentData()

    def start_maximized(self):
        return self.maximized_check.isChecked()


    def _pick_cif_root(self, _checked=False):
        path = QFileDialog.getExistingDirectory(
            self, "Folder of CIF files to search",
            self.cif_root_edit.text().strip())
        if path:
            self.cif_root_edit.setText(path)

    def cif_search_root(self):
        # type: () -> str
        return self.cif_root_edit.text().strip()

class BlenderExportDialog(QDialog):
    """Pre-configure the Blender scene before writing the script.

    A render is a dozen decisions — HDRI, lamps, engine, samples, how smooth
    the spheres are — and every one of them is quicker to make here than to
    hunt for in Blender afterwards. The defaults are chosen to give something
    worth looking at on the first run (Blender's own `forest` HDRI, a
    three-point rig at half power under it, Cycles at 128 samples, the camera
    exactly where the viewport is), so "just press OK" is a real option.

    Values in, values out: it owns no scene and writes no file. `options()`
    hands back a `core.blender_export.ExportOptions`.
    """

    _HDRI_NONE = "None (solid colour)"
    _HDRI_CUSTOM = "Custom file..."
    _LIGHT_LABELS = (("three_point", "Three-point studio (key + fill + rim)"),
                     ("key", "Key light only"),
                     ("none", "None - the world lights it"),
                     ("sun", "Sun (hard shadows)"))
    _STYLE_FOLLOW = "Follow the viewport"

    def __init__(self, parent, options=None, summary="",
                 viewport_size=None, scene=None):
        super().__init__(parent)
        self.setWindowTitle("Export to Blender")
        opts = options or bx.ExportOptions()
        self._custom_hdri = ""
        self._background = QColor.fromRgbF(*opts.background)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        area = QScrollArea(self)
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        form = QFormLayout(body)
        form.setContentsMargins(12, 12, 12, 8)
        area.setWidget(body)
        outer.addWidget(area, 1)

        self.head = QLabel()
        self.head.setWordWrap(True)
        form.addRow(self.head)
        if summary:
            note = QLabel(summary)
            note.setWordWrap(True)
            form.addRow("", note)

        # ----------------------------------------------------------- output
        # A .blend is built by running the script in Blender headlessly, so
        # the scene is already there when the file opens: no auto-run, no
        # "Allow Execution" prompt, F12 renders. The script stays on offer
        # because it is diffable, editable and needs no Blender to produce.
        self.output_combo = QComboBox()
        self.output_combo.addItem("Blender file (.blend) - open and press F12",
                                  "blend")
        self.output_combo.addItem("Python script (.py) - run it in Blender",
                                  "script")
        self._select_data(self.output_combo, opts.output)
        self.output_combo.currentIndexChanged.connect(self._output_changed)
        form.addRow("Write:", self.output_combo)

        exe_row = QHBoxLayout()
        self.blender_exe = QLineEdit(bx.find_blender(opts.blender_exe))
        self.blender_exe.setToolTip(
            "Only needed for a .blend, which Blender itself has to build. "
            "Found automatically where it can be; a launcher is resolved to "
            "the real executable beside it.")
        browse = QPushButton("Browse...")
        browse.clicked.connect(lambda _c=False: self._pick_blender())
        exe_row.addWidget(self.blender_exe, 1)
        exe_row.addWidget(browse)
        self.exe_row_widgets = (self.blender_exe, browse)
        form.addRow("Blender:", exe_row)

        # ------------------------------------------------------------ world
        form.addRow(QLabel("<b>World</b>"))
        self.hdri_combo = QComboBox()
        for name in bx.STUDIO_HDRIS:
            self.hdri_combo.addItem(name)
        self.hdri_combo.addItem(self._HDRI_NONE)
        self.hdri_combo.addItem(self._HDRI_CUSTOM)
        self.hdri_combo.setToolTip(
            "Blender's own material-preview HDRIs, found on YOUR machine when "
            "the script runs - nothing is copied and no path is baked in. An "
            "environment is worth more to a molecule than any lamp: shiny "
            "spheres are mostly reflection.")
        self._select_hdri(opts.hdri)
        self.hdri_combo.currentIndexChanged.connect(self._hdri_changed)
        form.addRow("Environment (HDRI):", self.hdri_combo)

        self.hdri_strength = QDoubleSpinBox()
        self.hdri_strength.setRange(0.0, 20.0)
        self.hdri_strength.setSingleStep(0.1)
        self.hdri_strength.setValue(float(opts.hdri_strength))
        self.hdri_strength.setToolTip("World lighting multiplier.")
        form.addRow("HDRI strength:", self.hdri_strength)

        self.hdri_rotation = QDoubleSpinBox()
        self.hdri_rotation.setRange(-360.0, 360.0)
        self.hdri_rotation.setSuffix(" deg")
        self.hdri_rotation.setValue(float(opts.hdri_rotation))
        self.hdri_rotation.setToolTip(
            "Spin the environment about Z - the cheapest way to move a "
            "highlight off an atom you want to read.")
        form.addRow("HDRI rotation:", self.hdri_rotation)

        self.hdri_visible = QCheckBox("Show the environment behind the "
                                      "molecule")
        self.hdri_visible.setChecked(bool(opts.hdri_visible))
        self.hdri_visible.setToolTip(
            "Off renders on a TRANSPARENT background (alpha PNG) while still "
            "lighting with the HDRI - what a figure usually wants.")
        form.addRow("", self.hdri_visible)

        self.bg_button = QPushButton()
        self.bg_button.setToolTip("Background colour when no HDRI is used.")
        self.bg_button.clicked.connect(lambda _c=False: self._pick_colour())
        self._paint_bg_button()
        form.addRow("Background colour:", self.bg_button)

        # ----------------------------------------------------- camera/render
        form.addRow(QLabel("<b>Camera and render</b>"))
        self.match_camera = QCheckBox("Place the camera exactly where the "
                                      "MoloM viewport is")
        self.match_camera.setChecked(bool(opts.match_viewport))
        self.match_camera.setToolTip(
            "Same position, same aim, same field of view - and orthographic "
            "if the viewport is. Turn it off to keep Blender's own camera.")
        form.addRow("", self.match_camera)

        # WHICH saved camera renders. It worked only implicitly before -
        # whichever one you happened to be looking through became Blender's
        # `scene.camera` - so exporting the shot you wanted meant entering it
        # first and there was no way to say so outright. Every saved camera is
        # still exported as an object either way; this only chooses the active
        # one. Hidden when the scene has none, so it never offers a choice
        # that has nothing to choose between.
        self.render_camera = QComboBox()
        self.render_camera.addItem("Active / viewport view", None)
        for cam in list(getattr(scene, "cameras", []) or []):
            self.render_camera.addItem(cam.name, cam.id)
        current = getattr(scene, "active_camera_id", None)
        index = self.render_camera.findData(current)
        self.render_camera.setCurrentIndex(max(index, 0))
        self.render_camera.setToolTip(
            "Which camera Blender opens on. The others are still exported as "
            "camera objects you can switch to.")
        if self.render_camera.count() > 1:
            form.addRow("Render through:", self.render_camera)

        res = QHBoxLayout()
        self.res_x = QSpinBox()
        self.res_x.setRange(64, 16384)
        self.res_y = QSpinBox()
        self.res_y.setRange(64, 16384)
        w, h = (viewport_size or opts.resolution)
        self.res_x.setValue(int(w))
        self.res_y.setValue(int(h))
        for box in (self.res_x, self.res_y):
            box.setToolTip(
                "Defaults to the viewport's own size, so the framing you see "
                "is the framing you render. A different ASPECT re-frames the "
                "shot vertically, since the field of view is vertical.")
        res.addWidget(self.res_x)
        res.addWidget(QLabel("x"))
        res.addWidget(self.res_y)
        form.addRow("Resolution:", res)

        self.engine_combo = QComboBox()
        self.engine_combo.addItem("Cycles (path tracing)", "CYCLES")
        self.engine_combo.addItem("EEVEE (fast raster)", "BLENDER_EEVEE_NEXT")
        self.engine_combo.setCurrentIndex(
            1 if opts.engine != "CYCLES" else 0)
        self.engine_combo.setToolTip(
            "The script falls back gracefully if the build does not have the "
            "one you pick (EEVEE was renamed twice, Cycles is an add-on).")
        form.addRow("Render engine:", self.engine_combo)

        self.samples = QSpinBox()
        self.samples.setRange(1, 8192)
        self.samples.setValue(int(opts.samples))
        form.addRow("Samples:", self.samples)

        self.view_transform = QComboBox()
        for name in bx.VIEW_TRANSFORMS:
            self.view_transform.addItem(name)
        idx = self.view_transform.findText(opts.view_transform)
        self.view_transform.setCurrentIndex(max(idx, 0))
        self.view_transform.setToolTip(
            "AgX and Filmic roll the highlights off, so white hydrogens stop "
            "clipping; Standard keeps the colours literally and blew 4.9% of "
            "a measured MOF-5 render to pure white.\n\n"
            "AgX rather than Filmic: Filmic was the default through Blender "
            "2.8x-3.x (which is why the tutorials say so) and desaturates "
            "midtones toward grey. AgX replaced it in 4.0 and keeps the "
            "colour.")
        form.addRow("View transform:", self.view_transform)

        self.look = QComboBox()
        for name in bx.LOOKS:
            self.look.addItem(name)
        idx = self.look.findText(opts.look)
        self.look.setCurrentIndex(max(idx, 0))
        self.look.setToolTip(
            "Puts back the contrast the roll-off takes away - without one, "
            "not clipping costs you the picture. Measured: bare AgX drops "
            "contrast from 0.165 to 0.120, High Contrast restores it to 0.160 "
            "at the same brightness with nothing clipped.")
        form.addRow("Contrast look:", self.look)

        # ----------------------------------------------------------- lights
        form.addRow(QLabel("<b>Lights</b>"))
        self.light_combo = QComboBox()
        for key, label in self._LIGHT_LABELS:
            self.light_combo.addItem(label, key)
        self._select_data(self.light_combo, opts.lights)
        self.light_combo.setToolTip(
            "Lamps are placed in the CAMERA's frame, so the rig follows the "
            "shot, and their power scales with the scene size. With an HDRI "
            "they run at half strength - both at once blows the highlights.")
        form.addRow("Lamp rig:", self.light_combo)

        self.light_strength = QDoubleSpinBox()
        self.light_strength.setRange(0.0, 10.0)
        self.light_strength.setSingleStep(0.1)
        self.light_strength.setValue(float(opts.light_strength))
        form.addRow("Lamp strength:", self.light_strength)

        # ------------------------------------------------- materials/geometry
        form.addRow(QLabel("<b>Materials and geometry</b>"))
        self.style_combo = QComboBox()
        self.style_combo.addItem(self._STYLE_FOLLOW, None)
        for st in style_mod.STYLES:
            self.style_combo.addItem(st.label, st.key)
        self._select_data(self.style_combo, opts.style_key)
        form.addRow("Style:", self.style_combo)

        self.roughness = QDoubleSpinBox()
        self.roughness.setRange(0.0, 1.0)
        self.roughness.setSingleStep(0.05)
        self.roughness.setValue(float(opts.roughness))
        self.roughness.setToolTip(
            "0 is a mirror, 1 is chalk. Around 0.35 reads as the glossy "
            "plastic every textbook figure uses.")
        form.addRow("Roughness:", self.roughness)

        self.metallic = QCheckBox("Metals get a metallic shader")
        self.metallic.setChecked(bool(opts.metallic_metals))
        form.addRow("", self.metallic)

        self.subdiv = QSpinBox()
        self.subdiv.setRange(1, 5)
        self.subdiv.setValue(int(opts.sphere_subdivisions))
        self.subdiv.setToolTip(
            "Icosphere subdivisions. 3 (1280 faces) is smooth at any "
            "sensible size; 5 is 20k faces PER ATOM and will hurt.")
        form.addRow("Sphere subdivisions:", self.subdiv)

        self.bond_sides = QSpinBox()
        self.bond_sides.setRange(6, 128)
        self.bond_sides.setValue(int(opts.bond_sides))
        form.addRow("Bond sides:", self.bond_sides)

        self.shade_smooth = QCheckBox("Shade smooth")
        self.shade_smooth.setChecked(bool(opts.shade_smooth))
        form.addRow("", self.shade_smooth)

        self.subsurf = QCheckBox("Subdivision Surface modifier on atoms")
        self.subsurf.setChecked(bool(opts.subsurf))
        self.subsurf.setToolTip(
            "Smooth shading fixes the inside of a sphere but not its "
            "silhouette, so a baked icosphere still looks faceted against the "
            "background. This adds a real modifier you can raise in Blender "
            "afterwards, instead of baking the detail in here.")
        form.addRow("", self.subsurf)

        self.meta_glow = QCheckBox("Meta atoms glow (emissive)")
        self.meta_glow.setChecked(bool(opts.meta_glow))
        self.meta_glow.setToolTip(
            "Carries the viewport's meta-atom halo into Blender as an emissive "
            "material. Off by default: a glowing atom is a deliberate look "
            "rather than a fact about the structure, and an emitter lights "
            "everything near it.")
        form.addRow("", self.meta_glow)

        self.unit_cell = QCheckBox("Unit cell box (as cylinders, a/b/c "
                                   "coloured)")
        self.unit_cell.setChecked(bool(opts.unit_cell))
        form.addRow("", self.unit_cell)

        self.polyhedra = QCheckBox("Coordination polyhedra (whichever "
                                   "molecules have them switched on)")
        self.polyhedra.setChecked(bool(opts.polyhedra))
        self.polyhedra.setToolTip(
            "The solids through each metal's donors - what makes a framework "
            "figure readable. One closed mesh per centre, flat shaded, on a "
            "translucent material you can adjust as a group.")
        form.addRow("", self.polyhedra)

        self.polyhedra_alpha = QDoubleSpinBox()
        self.polyhedra_alpha.setRange(0.05, 1.0)
        self.polyhedra_alpha.setSingleStep(0.05)
        self.polyhedra_alpha.setValue(float(opts.polyhedra_alpha))
        self.polyhedra_alpha.setToolTip(
            "1.0 hides everything inside the solid; the viewport uses 0.55.")
        form.addRow("Polyhedron opacity:", self.polyhedra_alpha)
        self.polyhedra.toggled.connect(self.polyhedra_alpha.setEnabled)
        self.polyhedra_alpha.setEnabled(self.polyhedra.isChecked())

        self.clear_scene = QCheckBox("Clear the Blender scene first (removes "
                                     "the default cube)")
        self.clear_scene.setChecked(bool(opts.clear_scene))
        form.addRow("", self.clear_scene)

        self.collection = QLineEdit(opts.collection)
        self.collection.setToolTip(
            "Everything lands in this collection, with atoms, bonds and the "
            "camera/lights in sub-collections - so re-running the script "
            "cannot lose your own objects.")
        form.addRow("Collection:", self.collection)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                   | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Choose file...")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        brow = QHBoxLayout()
        brow.setContentsMargins(8, 0, 8, 8)
        brow.addWidget(buttons)
        outer.addLayout(brow)
        self._hdri_changed()
        self._output_changed()
        self.resize(560, min(720, self.sizeHint().height() + 40))

    def _output_changed(self, _index=0):
        blend = self.output_combo.currentData() == "blend"
        for w in self.exe_row_widgets:
            w.setEnabled(blend)
        if not blend:
            self.head.setText(
                "Writes a Blender <b>Python script</b>. Open it in Blender's "
                "Scripting workspace and press Run, or "
                "<tt>blender --python &lt;file&gt;</tt>.")
        elif self.blender_exe.text().strip():
            self.head.setText(
                "Runs Blender headlessly to build the scene, then saves it as "
                "a <b>.blend</b> - open it and press F12. The build script "
                "rides along as a text datablock.")
        else:
            self.head.setText(
                "<b>No Blender found.</b> Point at the executable, or write "
                "the Python script instead.")

    def _pick_blender(self):
        from PySide6.QtWidgets import QFileDialog
        path, _f = QFileDialog.getOpenFileName(
            self, "Blender executable", self.blender_exe.text(),
            "Blender (blender.exe blender);;All files (*)")
        if path:
            # A launcher is a GUI shim; headless wants the binary beside it.
            self.blender_exe.setText(bx.find_blender(path))
            self._output_changed()

    # ------------------------------------------------------------- helpers
    @staticmethod
    def _select_data(combo, value):
        idx = combo.findData(value)
        combo.setCurrentIndex(idx if idx >= 0 else 0)

    def _select_hdri(self, value):
        if not value:
            self.hdri_combo.setCurrentText(self._HDRI_NONE)
            return
        idx = self.hdri_combo.findText(value)
        if idx >= 0:
            self.hdri_combo.setCurrentIndex(idx)
            return
        self._custom_hdri = value
        self.hdri_combo.insertItem(0, value)
        self.hdri_combo.setCurrentIndex(0)

    def _hdri_changed(self, _index=0):
        text = self.hdri_combo.currentText()
        if text == self._HDRI_CUSTOM:
            from PySide6.QtWidgets import QFileDialog
            path, _f = QFileDialog.getOpenFileName(
                self, "Environment image", "",
                "HDR images (*.exr *.hdr);;All files (*)")
            if path:
                self._custom_hdri = path
                self.hdri_combo.insertItem(0, path)
                self.hdri_combo.setCurrentIndex(0)
            else:
                self._select_hdri(bx.STUDIO_HDRIS[0])
            text = self.hdri_combo.currentText()
        none = text == self._HDRI_NONE
        self.hdri_strength.setEnabled(not none)
        self.hdri_rotation.setEnabled(not none)
        self.hdri_visible.setEnabled(not none)
        self.bg_button.setEnabled(none or self.hdri_visible.isChecked())

    def _pick_colour(self):
        from PySide6.QtWidgets import QColorDialog
        c = QColorDialog.getColor(self._background, self, "Background colour")
        if c.isValid():
            self._background = c
            self._paint_bg_button()

    def _paint_bg_button(self):
        c = self._background
        self.bg_button.setText(c.name())
        self.bg_button.setStyleSheet(
            "background: {}; color: {};".format(
                c.name(), "#000" if c.lightnessF() > 0.5 else "#fff"))

    # -------------------------------------------------------------- output
    def render_camera_id(self):
        """Which saved camera Blender should open on, or None for the
        viewport pose. Separate from `options` because it is a property of the
        SCENE, not of the render settings that get remembered."""
        return self.render_camera.currentData()

    def options(self):
        # type: () -> bx.ExportOptions
        text = self.hdri_combo.currentText()
        hdri = "" if text in (self._HDRI_NONE, self._HDRI_CUSTOM) else text
        return bx.ExportOptions(
            hdri=hdri,
            hdri_strength=self.hdri_strength.value(),
            hdri_rotation=self.hdri_rotation.value(),
            hdri_visible=self.hdri_visible.isChecked(),
            background=(self._background.redF(), self._background.greenF(),
                        self._background.blueF()),
            transparent=not self.hdri_visible.isChecked(),
            match_viewport=self.match_camera.isChecked(),
            resolution=(self.res_x.value(), self.res_y.value()),
            lights=self.light_combo.currentData(),
            light_strength=self.light_strength.value(),
            roughness=self.roughness.value(),
            metallic_metals=self.metallic.isChecked(),
            style_key=self.style_combo.currentData(),
            sphere_subdivisions=self.subdiv.value(),
            bond_sides=self.bond_sides.value(),
            shade_smooth=self.shade_smooth.isChecked(),
            subsurf=self.subsurf.isChecked(),
            meta_glow=self.meta_glow.isChecked(),
            unit_cell=self.unit_cell.isChecked(),
            polyhedra=self.polyhedra.isChecked(),
            polyhedra_alpha=self.polyhedra_alpha.value(),
            output=self.output_combo.currentData(),
            blender_exe=self.blender_exe.text().strip(),
            engine=self.engine_combo.currentData(),
            samples=self.samples.value(),
            view_transform=self.view_transform.currentText(),
            look=self.look.currentText(),
            clear_scene=self.clear_scene.isChecked(),
            collection=self.collection.text().strip() or "MoloM",
        )


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

    def __init__(self, parent, registry, ctx, last=None):
        super().__init__(parent)
        self.setWindowTitle("Search operation")
        self.registry = registry
        self.ctx = ctx
        self.chosen = None      # type: Optional[object]
        #: The operator run last time, pre-selected on an EMPTY search so a
        #: single Enter repeats it - Blender's behaviour, and the reason F3 is
        #: usable for a thing you are doing over and over. It only applies to
        #: the unfiltered list: once you have typed, the best MATCH is what
        #: should be selected, not a memory of something else.
        self.last_id = last
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
                # Remember where the LAST-RUN operator landed, so an empty
                # search can open straight on it.
                if enabled and op.id == self.last_id and not text.strip():
                    last_row = self.list.count() - 1
                    first_enabled = last_row
        if first_enabled is not None:
            self.list.setCurrentRow(first_enabled)
            self.list.scrollToItem(self.list.currentItem())

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


#: Worker threads still running, held here and nowhere else.
#:
#: **A QThread parented to the dialog is destroyed with the dialog**, and
#: destroying a running QThread is undefined behaviour - in practice an
#: access violation that takes the whole process down with no Python
#: traceback. It is reachable from the GUI: start a lookup that has to wait
#: out the 12 s web timeout, press Cancel, and the dialog goes while the
#: thread is still in `run()`.
#:
#: Un-parenting alone is not enough, and this is round 76's trap exactly: the
#: only remaining reference would be `self._worker` on the dialog, which dies
#: with it, and Python is then free to collect a QThread mid-run. So the set
#: outlives both, and a worker leaves it when it finishes.
#:
#: Nothing here needs cancelling. The resolver and the crystal search both
#: carry their own timeouts, and a result arriving after the dialog has gone
#: is delivered to nobody - Qt drops a connection when its receiver is
#: destroyed.
_LIVE_WORKERS = set()


def _own_worker(worker):
    """Keep `worker` alive until its thread really finishes."""
    _LIVE_WORKERS.add(worker)
    worker.finished.connect(lambda: _LIVE_WORKERS.discard(worker))
    worker.finished.connect(worker.deleteLater)
    return worker


def wait_for_workers(msecs=15000):
    """Block until every in-flight lookup thread has finished.

    The other half of not parenting them. A worker that outlives its dialog is
    correct; a worker that outlives the PROCESS is not - Python tearing down
    the interpreter under a running QThread is the same access violation from
    the other end, and it happens after everything has apparently succeeded,
    which makes it look like a shutdown problem rather than a threading one.

    Call it before quitting, and from a test teardown. Bounded, because both
    workers carry their own network timeouts and hanging on exit would be a
    worse bug than the one being fixed.
    """
    for worker in list(_LIVE_WORKERS):
        try:
            if worker.isRunning():
                worker.wait(int(msecs))
            # Discarded HERE rather than left to the `finished` signal, which
            # is queued: `wait()` returns as soon as the thread has ended, and
            # the connection that would drop it from the set has not run yet.
            # Relying on the signal made this report "still running" for a
            # thread that had plainly finished.
            if not worker.isRunning():
                _LIVE_WORKERS.discard(worker)
        except RuntimeError:              # already deleted; nothing to wait on
            _LIVE_WORKERS.discard(worker)
    return not _LIVE_WORKERS


class _ResolveWorker(QThread):
    done = Signal(object)

    def __init__(self, query, parent=None):
        super().__init__(parent)
        self.query = query

    def run(self):
        # Deferred with the same reasoning as app.py's: the network stack
        # is only needed once someone actually resolves a name.
        from ..core import resolve as resolve_mod
        self.done.emit(resolve_mod.resolve(self.query))


class ResolveNameDialog(QDialog):
    """Import by name: OPSIN -> PubChem -> did-you-mean.

    **SUPERSEDED by `MoleculeSearchDialog` in round 90** and no longer wired
    to anything - Ctrl+Shift+N now opens a list. Kept because the resolver
    cascade it drives is still the right shape for "turn this one name into
    one structure", and because its did-you-mean behaviour is pinned by tests
    that describe a real contract. If nothing has adopted it by the next
    sweep, delete it and them together.

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
        # The resolved SMILES is the whole reason someone opens this, and it is
        # the kind of thing you paste into the next program — so it has to be
        # markable.
        make_text_selectable(self)
        self.resize(430, 300)

    def _start_resolve(self):
        q = self.edit.text().strip()
        if not q or self._worker is not None:
            return
        self.resolve_btn.setEnabled(False)
        self.info.setText("Resolving {!r}...".format(q))
        # NO parent: see `_LIVE_WORKERS`.
        self._worker = _own_worker(_ResolveWorker(q))
        self._worker.done.connect(self._resolved)
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


class SiteOccupancyDialog(QDialog):
    """Say what a crystallographic SITE is made of.

    The one thing no derivation can recover. A shared position — several
    species on one Gitterplatz — is destroyed at import before occupancy is
    ever consulted: `expand`'s minimum-image merge removes the co-located
    species, so on the solid solution the nitrogen sharing a position with a
    carbon comes back with multiplicity zero (round 45e). The composition is
    then only in a table, and a rebuild loses it. Since nothing in the
    coordinates implies it, the honest answer is to let the user state it —
    Christian's suggestion.

    Edits apply to the whole symmetry ORBIT, not to the one atom picked: a
    cubic cell draws a site twenty-four times and nobody would do that
    twenty-four times over.
    """

    def __init__(self, parent, parts, label="", n_atoms=1):
        super().__init__(parent)
        from ..core import occupancy as occ_mod
        self._occ = occ_mod
        self.setWindowTitle("Site occupancy"
                            + (" — {}".format(label) if label else ""))
        outer = QVBoxLayout(self)
        head = QLabel(
            "Several species on ONE position — a substitutional solid "
            "solution. Applies to all <b>{}</b> atom(s) of this site."
            .format(int(n_atoms)))
        head.setWordWrap(True)
        head.setTextFormat(Qt.RichText)
        outer.addWidget(head)

        self._rows = []
        self.body = QVBoxLayout()
        self.body.setSpacing(3)
        outer.addLayout(self.body)

        add = QPushButton("+ Add a species")
        add.setToolTip("Another element sharing this position")
        add.clicked.connect(lambda _c=False: self._add_row("", 0.0))
        outer.addWidget(add)

        self.total = QLabel("")
        self.total.setWordWrap(True)
        outer.addWidget(self.total)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                   | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        self._ok = buttons.button(QDialogButtonBox.Ok)

        for sym, occ in (parts or [("", 1.0)]):
            self._add_row(sym, occ)
        self._retotal()
        self.resize(340, self.sizeHint().height())

    def _add_row(self, symbol, value):
        row = QHBoxLayout()
        edit = QLineEdit(str(symbol or ""))
        edit.setPlaceholderText("element")
        edit.setMaximumWidth(80)
        edit.textChanged.connect(lambda _t: self._retotal())
        spin = QDoubleSpinBox()
        spin.setRange(0.0, 1.0)
        spin.setDecimals(3)
        spin.setSingleStep(0.05)
        spin.setValue(float(value))
        spin.valueChanged.connect(lambda _v: self._retotal())
        gone = QPushButton("✕")
        gone.setMaximumWidth(28)
        gone.setToolTip("Remove this species")
        holder = QWidget()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(edit)
        row.addWidget(spin, 1)
        row.addWidget(gone)
        holder.setLayout(row)
        entry = (edit, spin, holder)
        self._rows.append(entry)
        gone.clicked.connect(lambda _c=False, e=entry: self._drop(e))
        self.body.addWidget(holder)

    def _drop(self, entry):
        if entry not in self._rows:
            return
        self._rows.remove(entry)
        entry[2].setParent(None)
        entry[2].deleteLater()
        self._retotal()

    def parts(self):
        """`[(element, occupancy), ...]`, cleaned. Unreadable symbols are
        dropped by `normalise`, which is also what validates them."""
        return self._occ.normalise(
            [(e.text(), s.value()) for e, s, _h in self._rows])

    def _retotal(self):
        parts = self.parts()
        note = self._occ.total_note(parts)
        over = self._occ.total(parts) > 1.0 + 1e-6
        self.total.setText(note or "Nothing entered — the site becomes an "
                                   "ordinary full atom.")
        self.total.setStyleSheet("color: #e08a6a;" if over else "")
        if self._ok is not None:
            self._ok.setEnabled(not over)


class ImageExportDialog(QDialog):
    """Every setting a PNG export has, in ONE window.

    Christian: "I am also getting confused by the re-rendering/settings
    dialogue. I don't think it shows the entire image export settings
    dialogue where everything can be set. Like in GIMP I mean... We need a
    straight-forward way of setting all these rendering options for simple PNG
    exports that do not conflict with each other."

    He is describing a real mess rather than a missing convenience. Exporting
    a still had **no dialog at all** - it was a bare file picker - while the
    options that decide what comes out (resolution multiplier, mesh
    subdivision, crop-to-content) lived in **App > Settings**, several tabs
    away from the thing they affect, and the unit-cell z-order was reachable
    only from F3. So the export asked one question and silently obeyed four
    answers given somewhere else, one of which (the z-order) deliberately
    differs from what the viewport is showing. That is exactly how you end up
    unsure whether the camera or the F12 made the difference.

    Everything is here now, the pixel size is computed live so the multiplier
    is never abstract, and the same options are what F12 repeats.
    """

    #: What the file dialog offers, and what Qt will actually write.
    FORMATS = (("png", "PNG image (*.png)"),
               ("jpg", "JPEG image (*.jpg *.jpeg)"),
               ("tif", "TIFF image (*.tif *.tiff)"))

    def __init__(self, parent, viewport, path="", remembered=None):
        super().__init__(parent)
        self.setWindowTitle("Export image")
        self._vp = viewport
        opts = dict(remembered or {})
        lay = QVBoxLayout(self)

        # ------------------------------------------------------------ file
        box = QGroupBox("File", self)
        form = QFormLayout(box)
        row = QHBoxLayout()
        self.path_edit = QLineEdit(path or opts.get("path", ""), self)
        browse = QPushButton("Browse...", self)
        browse.clicked.connect(self._browse)
        row.addWidget(self.path_edit, 1)
        row.addWidget(browse)
        form.addRow("Save to:", row)
        self.increment = QCheckBox(
            "Number each further export (shot.png, shot_001.png, ...)", self)
        self.increment.setChecked(bool(opts.get("increment", True)))
        self.increment.setToolTip(
            "F12 renders again without asking, so without this the second "
            "press would silently replace the first render.")
        form.addRow("", self.increment)
        lay.addWidget(box)

        # -------------------------------------------------------- geometry
        box = QGroupBox("Size", self)
        form = QFormLayout(box)
        self.scale = QSpinBox(self)
        self.scale.setRange(1, 8)
        self.scale.setValue(int(opts.get("scale", viewport.render_scale)))
        self.scale.setSuffix("x the viewport")
        form.addRow("Resolution:", self.scale)
        self.size_label = QLabel("", self)
        form.addRow("", self.size_label)
        self.crop = QCheckBox("Crop to the structure", self)
        self.crop.setChecked(bool(opts.get("crop", viewport.render_crop)))
        self.crop.setToolTip(
            "Trim the dead background. The viewport is whatever shape the "
            "window happens to be, so an export routinely carries a third of "
            "its pixels as nothing.")
        form.addRow("", self.crop)
        self.margin = QSpinBox(self)
        self.margin.setRange(0, 400)
        self.margin.setValue(int(opts.get("margin", 16)))
        self.margin.setSuffix(" px of air")
        form.addRow("Crop margin:", self.margin)
        lay.addWidget(box)

        # ----------------------------------------------------------- looks
        box = QGroupBox("Contents", self)
        form = QFormLayout(box)
        self.transparent = QCheckBox("Transparent background", self)
        self.transparent.setChecked(bool(opts.get("transparent", True)))
        self.transparent.setToolTip(
            "PNG and TIFF carry an alpha channel; JPEG does not, and a "
            "transparent JPEG comes out black.")
        form.addRow("", self.transparent)
        self.labels = QCheckBox("Atom labels", self)
        self.labels.setChecked(bool(opts.get("labels", False)))
        self.labels.setToolTip(
            "Off by default: a label is a reading aid rather than a fact "
            "about the structure. The cell box, polyhedra, symmetry elements "
            "and occupancy spheres are always drawn when their own toggle "
            "is on.")
        form.addRow("", self.labels)
        self.cell_depth = QCheckBox(
            "Unit cell box respects depth (drawn behind what is in front)",
            self)
        self.cell_depth.setChecked(
            bool(opts.get("cell_depth",
                          viewport.cell_zorder_export == cellbox_mod.DEPTH)))
        self.cell_depth.setToolTip(
            "Off draws the box over everything, which is what the viewport "
            "does while you navigate - handy on screen, and a false claim in "
            "a published still.")
        form.addRow("", self.cell_depth)
        self.subdiv = QSpinBox(self)
        self.subdiv.setRange(0, 4)
        self.subdiv.setValue(int(opts.get("subdiv",
                                          viewport.render_subdiv_bonus)))
        self.subdiv.setSuffix(" extra subdivisions")
        self.subdiv.setToolTip(
            "Finer spheres and cylinders than the interactive meshes, which "
            "are deliberately cheap.")
        form.addRow("Mesh detail:", self.subdiv)
        lay.addWidget(box)

        self.note = QLabel("", self)
        self.note.setWordWrap(True)
        lay.addWidget(self.note)

        row = QHBoxLayout()
        self.ok_btn = QPushButton("Export", self)
        cancel = QPushButton("Cancel", self)
        row.addStretch(1)
        row.addWidget(self.ok_btn)
        row.addWidget(cancel)
        lay.addLayout(row)
        self.ok_btn.clicked.connect(self._accept)
        cancel.clicked.connect(self.reject)

        for widget in (self.scale, self.margin):
            widget.valueChanged.connect(self._refresh)
        for widget in (self.crop, self.transparent):
            widget.toggled.connect(self._refresh)
        self.path_edit.textChanged.connect(self._refresh)
        make_text_selectable(self)
        self._refresh()
        self.resize(560, 470)

    # ------------------------------------------------------------- helpers
    def _browse(self):
        start = self.path_edit.text() or "molom.png"
        path, _f = QFileDialog.getSaveFileName(
            self, "Export image", start,
            ";;".join(label for _e, label in self.FORMATS) + ";;All files (*)")
        if path:
            self.path_edit.setText(path)

    def _refresh(self):
        """Say what will actually be written.

        A multiplier is abstract; a pixel count is not, and it is the one
        thing someone checks before pressing Export.
        """
        width, height = self.pixel_size()
        bits = ["{} x {} pixels".format(width, height)]
        if self.crop.isChecked():
            bits.append("before cropping")
        self.size_label.setText("  ".join(bits))
        self.margin.setEnabled(self.crop.isChecked())
        notes = []
        ext = os.path.splitext(self.path_edit.text())[1].lower().lstrip(".")
        if self.transparent.isChecked() and ext in ("jpg", "jpeg"):
            notes.append("JPEG has no alpha channel - a transparent export "
                         "will come out with a black background. Use PNG.")
        if self._camera_note():
            notes.append(self._camera_note())
        self.note.setText("\n".join(notes))

    def _camera_note(self):
        cam = self._vp.active_camera_object()
        if cam is None:
            return ""
        return ("Looking through {}: the export is that camera's frame at "
                "its own resolution x multiplier.".format(cam.name or "a camera"))

    def pixel_size(self):
        # type: () -> tuple
        """What the file will be, before any crop."""
        scale = int(self.scale.value())
        cam = self._vp.active_camera_object()
        if cam is not None:
            # `render_size()`, not a `resolution` attribute - a CameraObject
            # stores `width`/`height` and applies its own `multiplier`, and
            # guessing the name is exactly how this shipped raising
            # AttributeError the moment a camera was active.
            width, height = cam.render_size()
            return max(int(width) * scale, 1), max(int(height) * scale, 1)
        return (max(int(self._vp.width()) * scale, 1),
                max(int(self._vp.height()) * scale, 1))

    def _accept(self):
        if not self.path_edit.text().strip():
            self._browse()
            if not self.path_edit.text().strip():
                return
        self.accept()

    def options(self):
        # type: () -> dict
        """Everything the export needs, and everything F12 repeats."""
        return {"path": self.path_edit.text().strip(),
                "increment": self.increment.isChecked(),
                "scale": int(self.scale.value()),
                "subdiv": int(self.subdiv.value()),
                "crop": self.crop.isChecked(),
                "margin": int(self.margin.value()),
                "transparent": self.transparent.isChecked(),
                "labels": self.labels.isChecked(),
                "cell_depth": self.cell_depth.isChecked()}


class AnimationExportDialog(QDialog):
    """Pre-configure an animation export: format, size, speed, how many loops.

    A PNG SEQUENCE is the default and takes no dependency — it works
    everywhere, it is what feeds Blender or a journal, and a failed export
    leaves the frames that did render rather than a corrupt container. Video
    is offered only when there is an ffmpeg to do it, and says so when there
    is not, rather than failing at the end of a long render.
    """

    def __init__(self, parent, n_frames=0, fps=30.0, size=(1280, 720),
                 have_video=True, remembered=None, ffmpeg_hint=""):
        super().__init__(parent)
        from ..core import animation as anim
        self._anim = anim
        self._ffmpeg_hint = ffmpeg_hint or ""
        self._ffmpeg_source = anim.ffmpeg_source(self._ffmpeg_hint)[1]
        self.setWindowTitle("Export animation")
        # Reopening the dialog shows what you LAST chose, not the defaults —
        # someone who goes looking for the settings is nearly always there to
        # change one of them, and re-picking the other six is pure friction.
        remembered = remembered or {}
        if remembered.get("size"):
            size = remembered["size"]
        if remembered.get("fps"):
            fps = remembered["fps"]
        form = QFormLayout(self)

        self.head = QLabel("")
        self.head.setWordWrap(True)
        form.addRow(self.head)

        self.format_combo = QComboBox()
        self.format_combo.addItem("PNG image sequence (a folder of frames)",
                                  anim.FORMAT_PNG)
        self.format_combo.addItem("MP4 video (H.264)", anim.FORMAT_MP4)
        self.format_combo.addItem("Animated GIF", anim.FORMAT_GIF)
        if not have_video:
            for row in (1, 2):
                self.format_combo.model().item(row).setEnabled(False)
        self.format_combo.setToolTip(
            "A sequence is the safe choice and needs nothing installed. "
            "Video goes through ffmpeg - the `imageio-ffmpeg` wheel brings a "
            "self-contained one, so there is nothing to install system-wide.")
        self.format_combo.currentIndexChanged.connect(self._refresh)
        form.addRow("Format:", self.format_combo)

        res = QHBoxLayout()
        self.res_x = QSpinBox()
        self.res_x.setRange(64, 8192)
        self.res_x.setValue(int(size[0]))
        self.res_y = QSpinBox()
        self.res_y.setRange(64, 8192)
        self.res_y.setValue(int(size[1]))
        for box in (self.res_x, self.res_y):
            box.valueChanged.connect(self._refresh)
        res.addWidget(self.res_x)
        res.addWidget(QLabel("x"))
        res.addWidget(self.res_y)
        form.addRow("Resolution:", res)
        self.res_note = QLabel("")
        self.res_note.setWordWrap(True)
        form.addRow("", self.res_note)

        self.fps = QDoubleSpinBox()
        self.fps.setRange(1.0, 240.0)
        self.fps.setValue(float(fps))
        self.fps.setSuffix(" fps")
        self.fps.setToolTip(
            "Playback rate of the FILE. The scene's frame range decides "
            "how many frames there are; this decides how fast they go "
            "past.")
        self.fps.valueChanged.connect(self._refresh)
        form.addRow("Frame rate:", self.fps)

        self.loops = QDoubleSpinBox()
        self.loops.setRange(0.25, 100.0)
        self.loops.setValue(1.0)
        self.loops.setSingleStep(0.5)
        self.loops.setToolTip(
            "How many times round the loop. Frame End is the last frame "
            "PLAYED and the frame after it is Frame Start again, so a "
            "cycle never repeats its own first picture.")
        self.loops.valueChanged.connect(self._refresh)
        form.addRow("Loops:", self.loops)

        self.furniture = QCheckBox("Include the unit cell box and labels")
        self.furniture.setToolTip(
            "Off renders the molecule alone on a transparent background, "
            "which is what a figure usually wants. On keeps what the viewport "
            "draws around it.")
        form.addRow("", self.furniture)

        self.increment = QCheckBox("Increment filenames (overwrite "
                                   "protection)")
        self.increment.setChecked(True)
        self.increment.setToolTip(
            "A second render writes name_001, name_002, ... instead of "
            "replacing the first. This is what makes F12 safe to lean on: a "
            "render key that silently overwrites is a key you cannot press "
            "twice.")
        form.addRow("", self.increment)

        self.transparent = QCheckBox("Transparent background")
        self.transparent.setChecked(True)
        self.transparent.toggled.connect(self._refresh)
        form.addRow("", self.transparent)

        # A way OUT of "no ffmpeg" that does not involve closing the dialog and
        # going to read documentation. Only offered when there is none to find:
        # a browse button for something already working is just clutter.
        self.ffmpeg_button = QPushButton("Locate ffmpeg...")
        self.ffmpeg_button.setToolTip(
            "Point MoloM at an ffmpeg executable. Remembered in Settings, and "
            "only needed when there is no ffmpeg on PATH and imageio-ffmpeg "
            "is not installed.")
        self.ffmpeg_button.clicked.connect(self._locate_ffmpeg)
        self.ffmpeg_button.setVisible(not have_video)
        form.addRow("", self.ffmpeg_button)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                   | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Choose file...")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self._n_frames = int(n_frames)
        self._have_video = bool(have_video)
        # Restore the rest of the remembered choices. Done after every widget
        # exists so nothing has to be constructed in a particular order.
        for key, widget in (("furniture", self.furniture),
                            ("increment", self.increment),
                            ("transparent", self.transparent)):
            if key in remembered:
                widget.setChecked(bool(remembered[key]))
        if remembered.get("loops"):
            self.loops.setValue(float(remembered["loops"]))
        if remembered.get("format"):
            index = self.format_combo.findData(remembered["format"])
            if index >= 0 and self.format_combo.model().item(index).isEnabled():
                self.format_combo.setCurrentIndex(index)
        self._refresh()

    def _locate_ffmpeg(self):
        """Browse for an ffmpeg, then re-enable the video formats in place."""
        path, _f = QFileDialog.getOpenFileName(
            self, "Locate ffmpeg", "",
            "ffmpeg (ffmpeg.exe ffmpeg);;All files (*)")
        if not path:
            return
        self._ffmpeg_hint = path
        found, source = self._anim.ffmpeg_source(path)
        self._ffmpeg_source = source
        self._have_video = bool(found)
        for row in range(self.format_combo.count()):
            if self.format_combo.itemData(row) in self._anim.VIDEO_FORMATS:
                self.format_combo.model().item(row).setEnabled(self._have_video)
        self.ffmpeg_button.setVisible(not self._have_video)
        self._refresh()

    def ffmpeg_hint(self):
        """The path the user browsed to, so the window can remember it."""
        return self._ffmpeg_hint

    def _refresh(self, *_a):
        fmt = self.format_combo.currentData()
        total = max(int(round(self._n_frames * self.loops.value())), 1)
        bits = [self._anim.summarise(total, self.fps.value(), fmt)]
        if not self._have_video:
            bits.append(self._anim.NO_FFMPEG_HELP)
        elif self._ffmpeg_source:
            # Say WHICH ffmpeg before the render, not after. "No ffmpeg" and
            # "using the one you pointed me at" are very different things to
            # someone looking at a disabled combo box.
            bits.append("Video via {}.".format(self._ffmpeg_source))
        self.head.setText("  ".join(bits))
        # H.264 refuses odd dimensions, with a message nobody reads to the end
        odd = fmt in self._anim.EVEN_DIMENSIONS and (
            self.res_x.value() % 2 or self.res_y.value() % 2)
        notes = []
        if odd:
            notes.append("H.264 needs even dimensions — {} x {} will be used."
                         .format(self._anim.even(self.res_x.value()),
                                 self._anim.even(self.res_y.value())))
        # A GIF cannot hold an arbitrary frame rate, and finding that out by
        # watching the finished file stutter is the worst way to learn it.
        if fmt == self._anim.FORMAT_GIF:
            notes.append(self._anim.gif_note(self.fps.value()))
        self.res_note.setText("  ".join(n for n in notes if n))
        # a transparent background cannot survive an MP4
        self.transparent.setEnabled(fmt != self._anim.FORMAT_MP4)

    def options(self):
        fmt = self.format_combo.currentData()
        w, h = self.res_x.value(), self.res_y.value()
        if fmt in self._anim.EVEN_DIMENSIONS:
            w, h = self._anim.even(w), self._anim.even(h)
        return {"format": fmt, "size": (w, h), "fps": self.fps.value(),
                "loops": self.loops.value(),
                "furniture": self.furniture.isChecked(),
                "transparent": (self.transparent.isChecked()
                                and fmt != self._anim.FORMAT_MP4),
                "increment": self.increment.isChecked()}


def _age_phrase(when):
    # type: (float) -> str
    """How long ago, in words, or "" when it was a moment ago.

    Coarse on purpose: the number is there to say whether the list can still
    be trusted, and "3 minutes ago" answers that as well as a timestamp while
    reading as a remark rather than as data.
    """
    import time
    if not when:
        return ""
    seconds = max(0.0, time.time() - float(when))
    if seconds < 90:
        return ""
    minutes = seconds / 60.0
    if minutes < 60:
        return ", {:.0f} minutes ago".format(minutes)
    hours = minutes / 60.0
    if hours < 24:
        return ", {:.0f} hour{} ago".format(hours, "" if hours < 1.5 else "s")
    days = hours / 24.0
    return ", {:.0f} day{} ago".format(days, "" if days < 1.5 else "s")


def _result_line(hits, query, noun="structure"):
    # type: (list, str, str) -> str
    return "{} {}{} for {!r}".format(
        len(hits), noun, "" if len(hits) == 1 else "s", query or "")


class _CifSearchWorker(QThread):
    """One search, off the GUI thread.

    Three providers with an 8 s budget each cannot run on the main thread -
    and the whole point of `cifsearch.search` is that it returns even when a
    provider does not, so the worker only has to carry the result across.
    """

    done = Signal(object)

    def __init__(self, query, roots=(), parent=None):
        super().__init__(parent)
        self._query = query
        self._roots = list(roots or [])

    def run(self):
        try:
            result = cifsearch.search(self._query, roots=self._roots)
        except Exception as exc:                    # noqa: BLE001
            result = cifsearch.Results(
                self._query, trouble=["search failed: {}".format(exc)])
        self.done.emit(result)


class _CifResultTable(ResultTable):
    """The crystal search's columns: what a person actually chooses by - what
    it is, which polymorph, what symmetry, measured or computed, how recent."""

    COLUMNS = ("★", "Formula", "Name / mineral", "Space group", "T / K",
               "Year", "Source")
    STAR = 0
    NUMERIC_COLUMNS = {4: "temperature", 5: "year"}
    STRETCH_COLUMN = 2
    DIVIDER_TEXT = "FAVOURITES"

    def cells_for(self, hit):
        source = ("on disk" if hit.source == cifsearch.SOURCE_LOCAL
                  else (hit.note.split()[0] if hit.note else hit.source))
        return ("",                     # the star column carries no text
                hit.formula,
                hit.mineral or hit.name,
                hit.spacegroup,
                "" if hit.temperature is None
                else "{:g}".format(float(hit.temperature)),
                "" if not hit.year else str(hit.year),
                source + (" (calc)" if hit.computed else ""))

    def key_for(self, hit):
        return hit.key()

    def decorate(self, hit, widget_item, column):
        if hit.computed:
            # A DFT-relaxed cell is not a measurement, and which kind you are
            # looking at must be visible at a glance.
            widget_item.setForeground(QColor(150, 170, 210))
        widget_item.setToolTip(hit.note or str(hit.ref))

    def star_tooltip(self):
        return ("Keep this structure in the list - the reference is "
                "remembered, not the file")


class CifSearchDialog(QDialog):
    """Find a crystal structure and import it (Ctrl+Shift+Alt+N).

    Deliberately NOT modelled on `ResolveNameDialog` as that dialog was: a
    crystal name gives many answers - polymorphs, temperatures,
    redeterminations, a dozen determinations of quartz - so this is a LIST you
    choose from, and it is multi-select because comparing two polymorphs side
    by side is the commonest reason to go looking in the first place.

    Round 90 moved the table itself into `ui/search_table.py`, because the
    molecule search needs every bit of its sorting, starring and dividing
    behaviour and two copies of that is how they drift apart.
    """

    #: Kept on the dialog because callers and tests ask by MEANING rather than
    #: by position - round 87's lesson, when inserting the star column shifted
    #: every other index by one and broke six tests that had numbers in them.
    COLUMNS = _CifResultTable.COLUMNS
    STAR = _CifResultTable.STAR
    COL_FORMULA = 1
    COL_NAME = 2
    COL_SPACEGROUP = 3
    COL_TEMPERATURE = 4
    COL_YEAR = 5
    COL_SOURCE = 6

    def __init__(self, parent, roots=(), remembered=None, favourites=None):
        super().__init__(parent)
        self.setWindowTitle("Find a crystal structure")
        self.chosen = []          # type: list
        self._roots = list(roots or [])
        self._worker = None
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Formula, mineral or chemical name:"))
        self.edit = QLineEdit(self)
        self.edit.setPlaceholderText("SiO2    quartz    TiO2    ferrocene")
        lay.addWidget(self.edit)

        self.table = _CifResultTable(self, favourites=favourites)
        self.table.chosen_changed.connect(self._selection_changed)
        self.table.item_activated.connect(self._take_one)
        lay.addWidget(self.table, 1)

        self.info = QLabel("")
        self.info.setWordWrap(True)
        lay.addWidget(self.info)

        row = QHBoxLayout()
        self.search_btn = QPushButton("Search")
        self.ok_btn = QPushButton("Import selected")
        self.ok_btn.setEnabled(False)
        cancel = QPushButton("Cancel")
        row.addWidget(self.search_btn)
        row.addStretch(1)
        row.addWidget(self.ok_btn)
        row.addWidget(cancel)
        lay.addLayout(row)
        self.search_btn.clicked.connect(self._start)
        self.edit.returnPressed.connect(self._start)
        self.ok_btn.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        make_text_selectable(self)
        self.resize(820, 470)
        self.restore(remembered)
        if not self.hits and self.favourites:
            # Christian: "show them by default when opening the search
            # window". With nothing remembered they ARE the window's content,
            # so there is nothing to separate them from and no rule is drawn.
            self.table.refill()
            self.info.setText(
                "{} favourite{} - search to add more".format(
                    len(self.favourites),
                    "" if len(self.favourites) == 1 else "s"))

    # ---------------------------------------------------- table pass-through
    @property
    def hits(self):
        """The ranked results. Lives on the table, which owns the view."""
        return self.table.results

    @hits.setter
    def hits(self, value):
        self.table.set_results(value)

    @property
    def favourites(self):
        return self.table.favourites

    # ------------------------------------------------------------ searching
    def restore(self, remembered):
        """Put the last search back, without re-running it.

        Re-running would be worse than useless - it costs three network round
        trips to redisplay something that was on the screen a moment ago, and
        it would silently change under you if a provider answered differently.

        The age is SAID rather than hidden. A stale list that looks live is
        worse than an empty one.
        """
        if not remembered:
            return
        query, hits, when = remembered
        self.edit.setText(query or "")
        self.edit.selectAll()
        self.table.set_results(hits or [])
        self.info.setText(
            "{} - from your last search{}. Press Enter to run it again."
            .format(_result_line(self.hits, query), _age_phrase(when)))

    def remembered(self):
        # type: () -> tuple
        """`(query, hits, when)` for the next time the dialog opens."""
        import time
        return (self.edit.text().strip(), list(self.hits), time.time())

    def _start(self):
        query = self.edit.text().strip()
        if not query or self._worker is not None:
            return
        self.search_btn.setEnabled(False)
        self.info.setText("Searching {!r}...".format(query))
        self.table.set_results([])
        # NO parent: see `_LIVE_WORKERS`. A crystal search is three providers
        # with an 8 s budget each, so closing the dialog while one is in
        # flight is an ordinary thing to do rather than a corner case.
        self._worker = _own_worker(_CifSearchWorker(query, self._roots))
        self._worker.done.connect(self._finished)
        self._worker.start()

    def _finished(self, result):
        self._worker = None
        self.search_btn.setEnabled(True)
        self.table.set_results(result.hits)
        text = result.summary()
        if result.trouble:
            # NAMED, not counted. "Materials Project did not answer" is
            # something a user can act on; "1 source failed" is not.
            text += "\n" + "; ".join(result.trouble[:3])
        self.info.setText(text)

    # ------------------------------------------------------------- choosing
    def _selection_changed(self):
        self.chosen = self.table.chosen()
        self.ok_btn.setEnabled(bool(self.chosen))

    def _take_one(self, hit):
        self.chosen = [hit]
        self.accept()


# ---------------------------------------------------------- molecule search
class _MolSearchWorker(QThread):
    """One molecule search, off the GUI thread, reporting AS IT LANDS.

    `landed` fires once per provider with that provider's enriched, ranked
    batch, which is what lets the dialog fill incrementally instead of
    staring at nothing for four seconds. It is emitted from the provider's
    own thread inside `molsearch.search`; the receiving dialog lives in the
    GUI thread, so Qt queues it, and a dialog that has since been destroyed
    is disconnected rather than called.
    """

    landed = Signal(str, object)
    done = Signal(object)

    def __init__(self, query, parent=None):
        super().__init__(parent)
        self._query = query

    def run(self):
        # Imported in the WORKER: `molsearch` reaches the resolver and so the
        # network stack, which must not be on the path that merely opens a
        # window (round 65).
        from ..core import molsearch

        def progress(source, batch):
            self.landed.emit(str(source), list(batch))
        try:
            result = molsearch.search(self._query, progress=progress)
        except Exception as exc:                    # noqa: BLE001
            result = molsearch.Results(
                self._query, trouble=["search failed: {}".format(exc)])
        self.done.emit(result)


class _MolResultTable(ResultTable):
    """The molecule search's columns.

    Formula and weight are here because they are FREE - RDKit computes both
    from the SMILES offline, so every row has them whichever provider found
    it. They are also, for the case this dialog exists to fix, completely
    useless as discriminators: o-, m- and p-xylene share both. That is what
    the picture beside the table is for.
    """

    COLUMNS = ("★", "Name", "Formula", "M / g mol-1", "CAS", "Source")
    STAR = 0
    NUMERIC_COLUMNS = {3: "weight"}
    STRETCH_COLUMN = 1
    DIVIDER_TEXT = "FAVOURITES"
    #: SINGLE select: the panel beside the table shows ONE structure, and a
    #: multi-selection would leave it showing an arbitrary member of the set.
    MULTI_SELECT = False

    def cells_for(self, cand):
        return ("",
                cand.label(),
                cand.formula,
                "" if cand.weight is None else "{:.2f}".format(cand.weight),
                cand.cas,
                cand.source)

    def key_for(self, cand):
        return cand.key()

    def decorate(self, cand, widget_item, column):
        if cand.note:
            # The interpretation note - "read 'xylene' as O-Xylene" - is the
            # one thing on the row that nobody would otherwise be told.
            widget_item.setForeground(QColor(230, 180, 120))
        widget_item.setToolTip(cand.note or cand.iupac_name or cand.smiles)

    def star_tooltip(self):
        return ("Keep this compound in the list - the structure is small "
                "enough to remember, so a favourite works offline")


class MoleculeSearchDialog(QDialog):
    """Find a molecule by name and import it (Ctrl+Shift+N).

    Replaces the single-answer resolver dialog, and the reason is measured
    rather than aesthetic: PubChem's exact-name endpoint 404s on "xylene" and
    on "cresol", and OPSIN answers both with the ORTHO isomer without saying
    so. A dialog that shows one structure has no way to tell you either of
    those things happened.

    The panel on the right is the point. Formula and weight cannot separate
    o-, m- and p-xylene - they are identical - so the skeletal formula is the
    only thing in the window that settles which one you are about to import.
    """

    def __init__(self, parent, remembered=None, favourites=None):
        super().__init__(parent)
        self.setWindowTitle("Find a molecule by name")
        self.chosen = []          # type: list
        self._worker = None
        self._last = None

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Name, SMILES, InChI or CAS number:"))
        self.edit = QLineEdit(self)
        self.edit.setPlaceholderText(
            "xylene    benzoic acid    ferrocene    aspirin")
        lay.addWidget(self.edit)

        middle = QHBoxLayout()
        self.table = _MolResultTable(self, favourites=favourites)
        self.table.chosen_changed.connect(self._selection_changed)
        self.table.item_activated.connect(self._take_one)
        middle.addWidget(self.table, 1)
        middle.addWidget(self._build_preview(), 0)
        lay.addLayout(middle, 1)

        self.info = QLabel("")
        self.info.setWordWrap(True)
        lay.addWidget(self.info)

        row = QHBoxLayout()
        self.search_btn = QPushButton("Search")
        self.ok_btn = QPushButton("Import")
        self.ok_btn.setEnabled(False)
        cancel = QPushButton("Cancel")
        row.addWidget(self.search_btn)
        row.addStretch(1)
        row.addWidget(self.ok_btn)
        row.addWidget(cancel)
        lay.addLayout(row)
        self.search_btn.clicked.connect(self._start)
        self.edit.returnPressed.connect(self._start)
        self.ok_btn.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        make_text_selectable(self)
        self.resize(940, 500)
        self.restore(remembered)
        if not self.candidates and self.favourites:
            self.table.refill()
            self.info.setText(
                "{} favourite{} - search to add more".format(
                    len(self.favourites),
                    "" if len(self.favourites) == 1 else "s"))

    def _build_preview(self):
        panel = QWidget(self)
        panel.setFixedWidth(320)
        box = QVBoxLayout(panel)
        box.setContentsMargins(8, 0, 0, 0)
        self.picture = QLabel(panel)
        self.picture.setAlignment(Qt.AlignCenter)
        self.picture.setMinimumHeight(depict_mod.DEFAULT_SIZE[1])
        self.picture.setToolTip("The selected compound, drawn from its SMILES")
        box.addWidget(self.picture)
        self.detail = QLabel(panel)
        self.detail.setWordWrap(True)
        self.detail.setAlignment(Qt.AlignTop)
        self.detail.setTextInteractionFlags(Qt.TextBrowserInteraction)
        box.addWidget(self.detail, 1)
        self._clear_preview("Select a result to see its structure")
        return panel

    # ---------------------------------------------------- table pass-through
    @property
    def candidates(self):
        return self.table.results

    @property
    def favourites(self):
        return self.table.favourites

    # ------------------------------------------------------------ searching
    def restore(self, remembered):
        """Put the last search back without re-running it - same reasoning as
        the crystal dialog, and the same cost of getting it wrong."""
        if not remembered:
            return
        query, cands, when = remembered
        self.edit.setText(query or "")
        self.edit.selectAll()
        self.table.set_results(cands or [])
        self.info.setText(
            "{} - from your last search{}. Press Enter to run it again."
            .format(_result_line(self.candidates, query, noun="compound"),
                    _age_phrase(when)))

    def remembered(self):
        # type: () -> tuple
        import time
        return (self.edit.text().strip(), list(self.candidates), time.time())

    def _start(self):
        query = self.edit.text().strip()
        if not query or self._worker is not None:
            return
        self.search_btn.setEnabled(False)
        self.info.setText("Searching {!r}...".format(query))
        self.table.set_results([])
        self._clear_preview("Searching...")
        # NO parent: see `_LIVE_WORKERS`.
        self._worker = _own_worker(_MolSearchWorker(query))
        self._worker.landed.connect(self._landed)
        self._worker.done.connect(self._finished)
        self._worker.start()

    def _landed(self, source, batch):
        """One provider's results, folded into what is already on screen.

        `merge_batch` is what makes this safe: a row already drawn is never
        moved or removed, only filled in. So PubChem arriving after OPSIN
        gives the row that is already there its real name and its CID rather
        than adding a second row for the same molecule - and nothing the user
        is reading jumps under their hand, which is round 78's rule.
        """
        from ..core import molsearch
        added, updated = molsearch.merge_batch(self.table.results, batch)
        if added or updated:
            self.table.refill()
        self.info.setText("{} so far - still searching...".format(
            _result_line(self.candidates, self.edit.text().strip(),
                         noun="compound")))
        self._refresh_preview()

    def _finished(self, result):
        self._worker = None
        self.search_btn.setEnabled(True)
        if not self.candidates and result.candidates:
            # Nothing arrived incrementally (an injected search, or a
            # provider that answered only at the end).
            self.table.set_results(result.candidates)
        elif result.candidates:
            # RECONCILE with the finished list. The incremental path merges
            # each provider's batch as it lands, and a row whose key did not
            # match anything (an empty InChIKey, a provider that answered
            # before its enrichment) would otherwise stay half-filled for the
            # rest of the session - visible as a row with no name that comes
            # good only when the dialog is closed and reopened, which is what
            # Christian saw. `merge_batch` is safe here for the same reason
            # it is safe incrementally: a drawn row is FILLED IN, never moved
            # or removed (round 78).
            from ..core import molsearch
            added, updated = molsearch.merge_batch(self.table.results,
                                                   result.candidates)
            if added or updated:
                self.table.refill()
        self._absorb_favourite_updates()
        text = result.summary() if not self.candidates else (
            _result_line(self.candidates, result.query, noun="compound")
            + (" - " + result.ambiguous if result.ambiguous else ""))
        if result.trouble:
            text += "\n" + "; ".join(result.trouble[:3])
        self.info.setText(text)
        self._refresh_preview()

    def _absorb_favourite_updates(self):
        """Give a stored favourite anything the live search just learned.

        A favourite is a SNAPSHOT of the row that was starred, so one saved
        before a column existed does not have it - Christian starred these
        before the CAS number was a column, and they came back blank in it.
        Re-fetching every favourite would be a request per star; folding in
        what this search already knows costs nothing and is self-healing,
        which is the same argument `merge_batch` makes one level up.
        """
        favourites = self.table.favourites
        if not favourites:
            return
        changed = False
        for cand in self.table.results:
            stored = favourites.get(cand.key())
            if stored is None:
                continue
            for field in ("cas", "formula", "inchikey", "iupac_name"):
                if not getattr(stored, field, "") and getattr(cand, field, ""):
                    setattr(stored, field, getattr(cand, field))
                    changed = True
            if stored.weight is None and cand.weight is not None:
                stored.weight = cand.weight
                changed = True
        if changed:
            # The dict is the one the window saves when the dialog closes,
            # whatever the outcome - starring something and then pressing
            # Cancel is an ordinary way to use a bookmark list - so mutating
            # it in place is all the persistence this needs.
            self.table.refill()

    # -------------------------------------------------------------- preview
    def _is_dark(self):
        return self.palette().color(QPalette.Window).lightness() < 128

    def _clear_preview(self, message):
        self.picture.clear()
        self.picture.setText("")
        self.detail.setText(message)
        self._last = None

    def _refresh_preview(self):
        cand = self.table.current_item()
        if cand is None:
            self._clear_preview("Select a result to see its structure")
            return
        if self._last is not None and self._last is cand:
            return
        self._last = cand
        png = depict_mod.depict(cand.smiles, dark=self._is_dark())
        if png:
            image = QImage()
            image.loadFromData(png, "PNG")
            self.picture.setPixmap(QPixmap.fromImage(image))
        else:
            self.picture.clear()
            self.picture.setText("(no structure to draw yet)")
        rows = []
        if cand.name:
            rows.append("<b>{}</b>".format(cand.name))
        if cand.iupac_name and cand.iupac_name != cand.name:
            rows.append(cand.iupac_name)
        if cand.formula:
            weight = ("" if cand.weight is None
                      else "  -  {:.2f} g mol-1".format(cand.weight))
            rows.append(cand.formula + weight)
        if cand.note:
            # Bright, because it is a warning that a name was interpreted.
            rows.append("<span style='color:#e6b478'>{}</span>"
                        .format(cand.note))
        if cand.inchikey:
            rows.append("<small>{}</small>".format(cand.inchikey))
        if cand.cid() is not None:
            rows.append("<small>PubChem CID {}</small>".format(cand.cid()))
        if cand.smiles:
            rows.append("<small>{}</small>".format(cand.smiles))
        self.detail.setText("<br>".join(rows))

    # ------------------------------------------------------------- choosing
    def _selection_changed(self):
        self.chosen = self.table.chosen()
        self.ok_btn.setEnabled(bool(self.chosen))
        self._refresh_preview()

    def _take_one(self, cand):
        self.chosen = [cand]
        self.accept()
