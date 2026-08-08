"""Small dialogs: Settings, F3 operator search, Import-by-name (resolver).

All thin: values in, values out; persistence and side effects stay in app.py.
"""

import re
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QPushButton,
                               QScrollArea, QSlider, QSpinBox, QVBoxLayout,
                               QWidget)

from ..core import blender_export as bx
from ..core import cif as cif_mod
from ..core import flight, input_map
from ..core import resolve as resolve_mod
from ..core import style as style_mod


class SettingsDialog(QDialog):
    """App settings; live-applies rotation speed via `on_speed_change`."""

    def __init__(self, parent, rotate_speed, start_maximized,
                 precision_factor=0.5, undo_limit=30, adjust_h=True,
                 atom_scale=1.0, render_scale=2, render_subdiv=2,
                 input_preset=input_map.PRESET_AUTO, label_scale=1.0,
                 disorder_policy=None, sg_convention=None,
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
                 "strictly 1:1 with the mouse; this only scales it.")):
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
        form.addRow("", QLabel("Renders exclude the grid, compass, labels\n"
                               "and gizmos, on a transparent background."))

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

    def __init__(self, parent, options=None, summary="", viewport_size=None):
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
            "Standard keeps the viewport's colours literally; AgX and Filmic "
            "roll the highlights off, which stops white hydrogens clipping in "
            "a bright scene.")
        form.addRow("View transform:", self.view_transform)

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
            unit_cell=self.unit_cell.isChecked(),
            polyhedra=self.polyhedra.isChecked(),
            polyhedra_alpha=self.polyhedra_alpha.value(),
            output=self.output_combo.currentData(),
            blender_exe=self.blender_exe.text().strip(),
            engine=self.engine_combo.currentData(),
            samples=self.samples.value(),
            view_transform=self.view_transform.currentText(),
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
