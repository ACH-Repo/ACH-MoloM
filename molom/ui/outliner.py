"""Scene outliner — a VESTA-style tree that expands from molecules down to
individual atoms, living as a PAGE in the properties dock (not its own).

    water                [eye] [style]
      └ C  (2)                            <- element group, collapsed
          └ C0            [colour] [lbl]  <- individual atom
      └ H  (6)
    + New molecule

Everything below the molecule row is collapsed by default: the point is to
be able to reach one atom's colour or label without a wall of rows in the
way. Per-atom overrides are sparse (see MolObject.atom_colors), so expanding
and looking costs nothing.
"""

from typing import Optional

from PySide6.QtCore import QEvent, QPoint, Qt, Signal
from PySide6.QtGui import QAction, QBrush, QColor, QPalette
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox,
                               QHBoxLayout, QHeaderView, QInputDialog,
                               QLabel, QMenu, QStyledItemDelegate,
                               QToolButton, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from ..core import elements
from ..core import style as style_mod

_STYLE_CHOICES = [("", "(app style)")] + [(s.key, s.label)
                                          for s in style_mod.STYLES]
LABEL_MODES = [("element", "Element"), ("index", "Index"),
               ("element_index", "Element + index"), ("custom", "Custom")]

ROLE_KIND = Qt.UserRole          # "object" | "element" | "atom" | "add"
ROLE_OBJ = Qt.UserRole + 1
ROLE_ATOM = Qt.UserRole + 2
ROLE_HIDDEN = Qt.UserRole + 3    # this molecule has hidden atoms

# Short codes for the label-type square
_MODE_CODE = {"element": "El", "index": "#", "element_index": "E#",
              "custom": "✎"}


class _HiddenMarkDelegate(QStyledItemDelegate):
    """Paints a hidden-atoms row in the mark colour, selected or not.

    A plain `setForeground` loses to the selection highlight: Qt's style
    draws selected text with `QPalette.HighlightedText`, so the row turns
    white on blue and the warning vanishes exactly when you click it. Both
    palette roles are overridden here, which is the only way that holds for
    every style.
    """

    def __init__(self, colour, parent=None):
        super().__init__(parent)
        self._colour = colour

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        if index.data(ROLE_HIDDEN):
            for role in (QPalette.Text, QPalette.HighlightedText,
                         QPalette.WindowText, QPalette.ButtonText):
                option.palette.setColor(role, self._colour)


class CrystalControls(QWidget):
    """The per-`.cif` switches that hang off a crystal's outliner row.

    Only crystals get these — an ordinary molecule has no unit cell to show
    and no asymmetric unit to fall back to, so the row would be lying. The
    same pattern is the obvious home for future per-object kinds (a protein's
    chains, say): the controls that are UNIQUE to a kind of object belong on
    that object's row, and "Advanced" hands off to the full page while
    remembering which object it came from.

    Changes apply IMMEDIATELY. An Apply button on a two-state switch just
    adds a step between deciding and seeing.
    """

    view_changed = Signal(int, str)      # obj_id, mode
    box_toggled = Signal(int, bool)
    poly_toggled = Signal(int, bool)
    exterior_toggled = Signal(int, bool)
    advanced = Signal(int)

    def __init__(self, obj_id, mode="cell", show_box=True, show_poly=False,
                 exterior=0, parent=None):
        super().__init__(parent)
        self.obj_id = int(obj_id)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 0, 2, 0)
        lay.setSpacing(2)          # this row shares width with a narrow dock
        self._loading = True

        # SHORT labels: this row shares its width with the tree. The full
        # explanation lives in the tooltip, where it costs no space.
        self.box_check = QCheckBox("Cell", self)
        self.box_check.setChecked(bool(show_box))
        self.box_check.setToolTip("Show the unit cell box for this crystal")
        self.box_check.toggled.connect(
            lambda v: None if self._loading
            else self.box_toggled.emit(self.obj_id, bool(v)))

        self.poly_check = QCheckBox("Poly", self)
        self.poly_check.setChecked(bool(show_poly))
        self.poly_check.setToolTip(
            "Coordination polyhedra — draw a translucent solid through the "
            "donor atoms around each metal centre, the usual way MOFs and "
            "framework structures are shown")
        self.poly_check.toggled.connect(
            lambda v: None if self._loading
            else self.poly_toggled.emit(self.obj_id, bool(v)))

        self.asym_check = QCheckBox("Asym", self)
        self.asym_check.setToolTip(
            "Asymmetric unit — only the sites the file lists, before any "
            "symmetry operation is applied")
        self.full_check = QCheckBox("Full", self)
        self.full_check.setToolTip(
            "Full unit cell — every symmetry operation applied to fill it")
        self.asym_check.setChecked(mode == "asym")
        self.full_check.setChecked(mode != "asym")
        self.asym_check.toggled.connect(
            lambda v: self._pick("asym" if v else "cell"))
        self.full_check.toggled.connect(
            lambda v: self._pick("cell" if v else "asym"))

        self.adv_button = QToolButton(self)
        self.adv_button.setText("⋯")
        self.adv_button.setAutoRaise(True)
        self.adv_button.setToolTip(
            "Open the unit-cell page for this crystal (packing, supercell, "
            "cell parameters)")
        self.adv_button.clicked.connect(
            lambda: self.advanced.emit(self.obj_id))

        self.ext_check = QCheckBox("Ext", self)
        self.ext_check.setChecked(bool(exterior))
        self.ext_check.setToolTip(
            "Bonded atoms outside the cell — VESTA's boundary search. Draws "
            "the atoms just beyond each face that are bonded to atoms "
            "inside, so chains and frameworks run on instead of being cut "
            "off at the wall. Adds atoms to the PICTURE only; the cell "
            "content and Z are unchanged.")
        self.ext_check.toggled.connect(
            lambda v: None if self._loading
            else self.exterior_toggled.emit(self.obj_id, bool(v)))

        for w in (self.box_check, self.poly_check, self.asym_check,
                  self.full_check, self.ext_check, self.adv_button):
            w.setStyleSheet("QCheckBox { spacing: 3px; }")
            lay.addWidget(w)
        lay.addStretch(1)
        self._loading = False

    def _pick(self, mode):
        """The two content checkboxes are exclusive but read better than
        radio buttons in a row this narrow."""
        if self._loading:
            return
        self._loading = True
        self.asym_check.setChecked(mode == "asym")
        self.full_check.setChecked(mode == "cell")
        self._loading = False
        self.view_changed.emit(self.obj_id, mode)


class RowControls(QWidget):
    """The three squares an element group and an atom row both carry:
    colour, label on/off, label type.

    Identical at both levels on purpose — at the element level the action
    simply applies to every atom of that element, so "colour all my oxygens"
    and "colour this one oxygen" are the same gesture at different depths.
    """

    changed = Signal()

    SIZE = 17

    def __init__(self, panel, obj, indices, parent=None):
        super().__init__(parent)
        self._panel = panel
        self._obj = obj
        self._rows = list(indices)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(1, 0, 1, 0)
        lay.setSpacing(2)
        self.colour_btn = self._square("Colour — click to set, right-click "
                                       "to reset to the element colour")
        self.colour_btn.clicked.connect(self._pick_colour)
        self.colour_btn.customContextMenuRequested.connect(
            lambda _p: self._reset_colour())
        self.label_btn = self._square("Label on / off")
        self.label_btn.clicked.connect(self._toggle_label)
        self.mode_btn = self._square("Label type")
        self.mode_btn.clicked.connect(self._pick_mode)
        # Show/hide and per-element sphere size: without these a MOF cannot
        # be drawn properly — the hydrogens bury the framework and the metal
        # spheres burst out of their own coordination polyhedra.
        self.show_btn = self._square(
            "Show / hide these atoms in the viewport")
        self.show_btn.clicked.connect(self._toggle_shown)
        self.size_btn = self._square(
            "Sphere size for these atoms — click for a slider")
        self.size_btn.clicked.connect(self._pick_size)
        for b in (self.colour_btn, self.show_btn, self.size_btn,
                  self.label_btn, self.mode_btn):
            lay.addWidget(b)
        lay.addStretch(1)
        self.refresh()

    def _toggle_shown(self):
        obj, rows = self._obj, self._rows
        hidden = sum(1 for i in rows if i in obj.atom_hidden)
        show = hidden > len(rows) // 2      # mixed -> show them all
        for i in rows:
            if show:
                obj.atom_hidden.discard(i)
            else:
                obj.atom_hidden.add(i)
        self.refresh()
        self.changed.emit()

    def _pick_size(self):
        """A slider in a popup, right under the square that opened it —
        judging a sphere size means watching the viewport while you drag."""
        from PySide6.QtWidgets import QSlider, QHBoxLayout, QFrame
        popup = QFrame(self, Qt.Popup)
        popup.setStyleSheet(
            "QFrame { background: rgba(44,44,44,246); border: 1px solid"
            " rgba(0,0,0,140); border-radius: 5px; }"
            "QLabel { color: #dcdcdc; font-size: 11px; }")
        row = QHBoxLayout(popup)
        row.setContentsMargins(7, 4, 7, 4)
        obj, rows = self._obj, self._rows
        current = obj.atom_scale_for(rows[0])
        slider = QSlider(Qt.Horizontal, popup)
        slider.setRange(5, 300)                 # 0.05x .. 3.00x
        slider.setValue(int(round(current * 100)))
        slider.setFixedWidth(150)
        readout = QLabel("{:.2f}x".format(current), popup)
        readout.setMinimumWidth(40)

        def apply(value):
            scale = value / 100.0
            readout.setText("{:.2f}x".format(scale))
            for i in rows:
                if abs(scale - 1.0) < 1e-6:
                    obj.atom_scales.pop(i, None)
                else:
                    obj.atom_scales[i] = scale
            self.refresh()
            self.changed.emit()

        slider.valueChanged.connect(apply)
        row.addWidget(QLabel("Size", popup))
        row.addWidget(slider)
        row.addWidget(readout)
        popup.adjustSize()
        # Anchored on its RIGHT edge: the outliner lives against the right
        # side of the window, so a popup growing rightwards runs off screen.
        anchor = self.size_btn.mapToGlobal(self.size_btn.rect().bottomRight())
        pos = anchor - QPoint(popup.width(), 0)
        screen = self.screen().availableGeometry() if self.screen() else None
        if screen is not None:
            pos.setX(max(screen.left() + 2,
                         min(pos.x(), screen.right() - popup.width() - 2)))
            pos.setY(max(screen.top() + 2,
                         min(pos.y(), screen.bottom() - popup.height() - 2)))
        popup.move(pos)
        popup.show()

    def _square(self, tip):
        b = QToolButton(self)
        b.setFixedSize(self.SIZE, self.SIZE)
        b.setToolTip(tip)
        b.setCursor(Qt.PointingHandCursor)
        b.setContextMenuPolicy(Qt.CustomContextMenu)
        return b

    # ------------------------------------------------------------- display
    def refresh(self):
        obj, rows = self._obj, self._rows
        cols = {obj.atom_colors.get(i) for i in rows}
        if len(cols) == 1 and next(iter(cols)) is not None:
            c = next(iter(cols))
            text = ""
        else:
            z = elements.atomic_number(obj.structure.symbols[rows[0]])
            c = elements.color_f(z)
            text = "" if len(cols) == 1 else "~"      # ~ = mixed overrides
        qc = QColor(int(c[0] * 255), int(c[1] * 255), int(c[2] * 255))
        self.colour_btn.setText(text)
        self.colour_btn.setStyleSheet(
            "QToolButton {{ background: {}; border: 1px solid #1a1a1a;"
            " border-radius: 2px; font-size: 8px; color: {}; }}".format(
                qc.name(), "#000" if qc.lightness() > 128 else "#ddd"))

        on = sum(1 for i in rows if i in obj.atom_labels)
        state = "all" if on == len(rows) else ("some" if on else "none")
        fill = {"all": "#4a7ab0", "some": "#3d556e", "none": "rgba(255,255,255,18)"}
        self.label_btn.setText({"all": "L", "some": "l", "none": "L"}[state])
        self.label_btn.setStyleSheet(
            "QToolButton {{ background: {}; border: 1px solid #1a1a1a;"
            " border-radius: 2px; color: #eee; font-size: 8px; }}".format(
                fill[state]))

        # H = these are shown (click to Hide), S = these are hidden (click to
        # Show). A letter, not a glyph: an unlabelled square is a guess.
        hidden = sum(1 for i in rows if i in obj.atom_hidden)
        vis = "none" if hidden == len(rows) else ("some" if hidden else "all")
        self.show_btn.setText({"all": "H", "some": "h", "none": "S"}[vis])
        self.show_btn.setToolTip(
            "Show these atoms again" if vis == "none"
            else "Hide these atoms in the viewport")
        self.show_btn.setStyleSheet(
            "QToolButton {{ background: {}; border: 1px solid #1a1a1a;"
            " border-radius: 2px; color: #eee; font-size: 8px; }}".format(
                {"all": "rgba(255,255,255,18)", "some": "#3d556e",
                 "none": "#6b3a3a"}[vis]))

        # R = radius, replaced by the multiplier once it is not 1.
        scales = {round(obj.atom_scale_for(i), 2) for i in rows}
        if len(scales) == 1:
            value = next(iter(scales))
            size_text = "R" if abs(value - 1.0) < 1e-6 else "{:g}".format(value)
            custom = abs(value - 1.0) > 1e-6
        else:
            size_text, custom = "~", True
        self.size_btn.setText(size_text)
        self.size_btn.setStyleSheet(
            "QToolButton {{ background: {}; border: 1px solid #1a1a1a;"
            " border-radius: 2px; color: #ddd; font-size: 8px; }}".format(
                "#3d556e" if custom else "rgba(255,255,255,18)"))

        modes = {obj.label_mode_for(i) for i in rows}
        code = _MODE_CODE.get(next(iter(modes)), "?") if len(modes) == 1 \
            else "~"
        self.mode_btn.setText(code)
        self.mode_btn.setStyleSheet(
            "QToolButton { background: rgba(255,255,255,18); border: 1px"
            " solid #1a1a1a; border-radius: 2px; color: #ddd;"
            " font-size: 8px; }")

    # ------------------------------------------------------------- actions
    def _pick_colour(self):
        obj, rows = self._obj, self._rows
        cur = obj.atom_colors.get(rows[0])
        if cur is None:
            cur = elements.color_f(
                elements.atomic_number(obj.structure.symbols[rows[0]]))
        picked = QColorDialog.getColor(
            QColor(int(cur[0] * 255), int(cur[1] * 255), int(cur[2] * 255)),
            self, "Colour for {} atom(s)".format(len(rows)))
        if not picked.isValid():
            return
        rgb = (picked.redF(), picked.greenF(), picked.blueF())
        for i in rows:
            obj.atom_colors[i] = rgb
        self.refresh()
        self.changed.emit()

    def _reset_colour(self):
        for i in self._rows:
            self._obj.atom_colors.pop(i, None)
        self.refresh()
        self.changed.emit()

    def _toggle_label(self):
        obj, rows = self._obj, self._rows
        turn_on = not all(i in obj.atom_labels for i in rows)
        for i in rows:
            if turn_on:
                obj.atom_labels.add(i)
            else:
                obj.atom_labels.discard(i)
        self.refresh()
        self._panel.refresh_row_controls()
        self.changed.emit()

    def _pick_mode(self):
        menu = QMenu(self)
        for key, text in LABEL_MODES:
            act = QAction(text, menu)
            act.triggered.connect(lambda _c=False, k=key: self._set_mode(k))
            menu.addAction(act)
        menu.addSeparator()
        if len(self._rows) == 1:
            act = QAction("Custom text...", menu)
            act.triggered.connect(
                lambda: self._panel._set_custom_text(self._obj, self._rows[0]))
            menu.addAction(act)
        act_col = QAction("Label colour...", menu)
        act_col.triggered.connect(self._pick_label_colour)
        menu.addAction(act_col)
        menu.exec(self.mode_btn.mapToGlobal(self.mode_btn.rect().bottomLeft()))

    def _set_mode(self, key):
        for i in self._rows:
            self._obj.atom_label_modes[i] = key
        self.refresh()
        self.changed.emit()

    def _pick_label_colour(self):
        obj, rows = self._obj, self._rows
        cur = obj.atom_label_colors.get(rows[0], (1.0, 1.0, 1.0))
        picked = QColorDialog.getColor(
            QColor(int(cur[0] * 255), int(cur[1] * 255), int(cur[2] * 255)),
            self, "Label colour")
        if not picked.isValid():
            return
        for i in rows:
            obj.atom_label_colors[i] = (picked.redF(), picked.greenF(),
                                        picked.blueF())
            obj.atom_labels.add(i)
        self.refresh()
        self.changed.emit()


class OutlinerPanel(QWidget):

    visibility_changed = Signal(int, bool)
    isolate_requested = Signal(int)
    style_changed = Signal(int, str)
    renamed = Signal(int, str)
    delete_requested = Signal(int)
    activated = Signal(int)
    add_requested = Signal()
    merge_requested = Signal(list)
    atom_display_changed = Signal()          # colours / labels edited
    atom_picked = Signal(int, int)           # obj_id, atom index
    crystal_view_changed = Signal(int, str)  # obj_id, 'asym' | 'cell'
    crystal_box_toggled = Signal(int, bool)
    crystal_poly_toggled = Signal(int, bool)
    crystal_exterior_toggled = Signal(int, bool)
    crystal_advanced = Signal(int)           # open the unit-cell page
    objects_selected = Signal(list)          # every molecule row selected

    EYE_COLUMN = 1

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(3)
        head = QHBoxLayout()
        head.addWidget(QLabel("Labels:"))
        self.label_combo = QComboBox()
        for key, text in LABEL_MODES:
            self.label_combo.addItem(text, key)
        self.label_combo.setToolTip(
            "What a switched-on atom label shows (per molecule)")
        self.label_combo.currentIndexChanged.connect(self._label_mode_changed)
        head.addWidget(self.label_combo, 1)
        lay.addLayout(head)

        self.tree = QTreeWidget(self)
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Molecule / atom", "", "Style"])
        self.tree.setSelectionMode(QTreeWidget.ExtendedSelection)
        # The NAME column stretches; the eye and style columns are fixed.
        # All three used to be fixed pixel widths totalling 290 px, so any
        # dock narrower than that pushed the Style column out of reach behind
        # a horizontal scrollbar — the per-molecule display settings simply
        # could not be clicked. A stretching first column always fits.
        head = self.tree.header()
        head.setStretchLastSection(False)
        head.setSectionResizeMode(0, QHeaderView.Stretch)
        head.setSectionResizeMode(1, QHeaderView.Fixed)
        head.setSectionResizeMode(2, QHeaderView.Fixed)
        head.resizeSection(1, 26)
        head.resizeSection(2, 96)
        head.setMinimumSectionSize(22)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._hidden_delegate = _HiddenMarkDelegate(self.HIDDEN_MARK, self)
        self.tree.setItemDelegateForColumn(0, self._hidden_delegate)
        lay.addWidget(self.tree, 1)

        self._loading = False
        self.show_cell_box = True
        self._paint_state = None
        self._scene = None
        self._controls = []          # live RowControls, refreshed together
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.itemClicked.connect(self._on_item_clicked)
        self.tree.itemSelectionChanged.connect(self._on_selection_changed)
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.tree.itemExpanded.connect(self._on_expanded)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        self.tree.viewport().installEventFilter(self)

    # ------------------------------------------------------------ helpers
    def _kind(self, item):
        return item.data(0, ROLE_KIND) if item is not None else None

    def _obj_id(self, item):
        return item.data(0, ROLE_OBJ) if item is not None else None

    def _obj(self, item):
        oid = self._obj_id(item)
        return self._scene.get(oid) if (self._scene and oid is not None) \
            else None

    # --------------------------------------------------------------- sync
    def sync(self, scene, active_id=None):
        # type: (object, Optional[int]) -> None
        self._scene = scene
        expanded = self._expanded_keys()
        self._loading = True
        self._controls = []
        self.tree.clear()
        for obj in scene.objects:
            item = QTreeWidgetItem([obj.name, "", ""])
            item.setData(0, ROLE_KIND, "object")
            item.setData(0, ROLE_OBJ, obj.id)
            item.setFlags(item.flags() | Qt.ItemIsEditable
                          | Qt.ItemIsUserCheckable)
            item.setCheckState(self.EYE_COLUMN,
                               Qt.Checked if obj.visible else Qt.Unchecked)
            item.setToolTip(self.EYE_COLUMN,
                            "Show / hide in viewport. Ticking it back on "
                            "also un-hides every atom of this molecule.")
            self.tree.addTopLevelItem(item)
            self._mark_hidden(item, obj)
            combo = QComboBox()
            for key, label in _STYLE_CHOICES:
                combo.addItem(label, key)
            idx = [k for k, (key, _l) in enumerate(_STYLE_CHOICES)
                   if key == (obj.style_key or "")]
            combo.setCurrentIndex(idx[0] if idx else 0)
            combo.currentIndexChanged.connect(
                lambda _i, oid=obj.id, c=combo:
                self.style_changed.emit(oid, c.currentData()))
            self.tree.setItemWidget(item, 2, combo)
            self._add_crystal_row(item, obj)
            self._add_element_groups(item, obj)
            if obj.id == active_id:
                item.setSelected(True)
        add = QTreeWidgetItem(["+  New molecule", "", ""])
        add.setData(0, ROLE_KIND, "add")
        add.setFlags(Qt.ItemIsEnabled)
        add.setForeground(0, QColor(150, 190, 240))
        self.tree.addTopLevelItem(add)
        self._restore_expanded(expanded)
        self._loading = False
        self._sync_label_combo(active_id)

    #: A molecule with hidden atoms — bright enough to catch the eye in a
    #: long list, since the whole problem is that hidden atoms are invisible.
    HIDDEN_MARK = QColor(255, 105, 105)

    def _mark_hidden(self, item, obj):
        """Flag the molecule's row while any of its atoms are hidden.

        Without this the state is unfalsifiable: a molecule missing its
        hydrogens looks exactly like a molecule that never had them, so you
        cannot tell a display choice from a broken import. The row is the
        only place that can say so, because it is the one thing still visible.

        The flag is a ROLE, not a brush. Setting the foreground directly
        works until the row is selected, at which point the style paints the
        text in `HighlightedText` and the mark disappears against the blue —
        so the one row you are looking at is the one that stops telling you
        anything (Christian's screenshot). `_HiddenMarkDelegate` reads the
        role and overrides both palette entries instead.
        """
        item.setData(0, ROLE_HIDDEN, True if obj.has_hidden else None)
        item.setToolTip(0, "{} of {} atoms hidden — tick the eye off and "
                           "on, or Alt+H, to bring them back".format(
                               len(obj.atom_hidden), obj.structure.n_atoms)
                        if obj.has_hidden else "")

    def _add_crystal_row(self, parent_item, obj):
        """A crystal gets one extra child row carrying its own switches.

        Nothing is added for an ordinary molecule, so the outliner never
        grows controls that cannot do anything.
        """
        if not (obj.structure.metadata or {}).get("cell"):
            return
        row = QTreeWidgetItem(["", "", ""])
        row.setData(0, ROLE_KIND, "crystal")
        row.setData(0, ROLE_OBJ, obj.id)
        row.setFlags(Qt.ItemIsEnabled)
        parent_item.addChild(row)
        controls = CrystalControls(
            obj.id,
            mode=(obj.structure.metadata or {}).get("cell_view", "cell"),
            show_box=self.show_cell_box,
            show_poly=bool((obj.structure.metadata or {}).get("polyhedra")),
            exterior=int((obj.structure.metadata or {}).get(
                "cell_exterior", 0)))
        controls.view_changed.connect(self.crystal_view_changed)
        controls.box_toggled.connect(self.crystal_box_toggled)
        controls.poly_toggled.connect(self.crystal_poly_toggled)
        controls.exterior_toggled.connect(self.crystal_exterior_toggled)
        controls.advanced.connect(self.crystal_advanced)
        # Spanned: these are wider than the name column.
        row.setFirstColumnSpanned(True)
        self.tree.setItemWidget(row, 0, controls)

    def _add_element_groups(self, parent, obj):
        """One collapsed row per element; atoms are filled in on expand so a
        3000-atom slab does not build 3000 widgets nobody asked for."""
        counts = {}
        for i, sym in enumerate(obj.structure.symbols):
            counts.setdefault(sym, []).append(i)
        for sym in sorted(counts, key=lambda s: elements.atomic_number(s)):
            rows = counts[sym]
            grp = QTreeWidgetItem(["{}   ({})".format(sym, len(rows)), "", ""])
            grp.setData(0, ROLE_KIND, "element")
            grp.setData(0, ROLE_OBJ, obj.id)
            grp.setData(0, ROLE_ATOM, sym)
            z = elements.atomic_number(sym)
            c = elements.color_f(z)
            grp.setForeground(0, QBrush(QColor(int(c[0] * 255),
                                               int(c[1] * 255),
                                               int(c[2] * 255))))
            grp.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            grp.addChild(QTreeWidgetItem(["..."]))    # expand placeholder
            parent.addChild(grp)
            self._attach_controls(grp, obj, rows)

    def _on_expanded(self, item):
        if self._kind(item) != "element" or self._loading:
            return
        obj = self._obj(item)
        if obj is None:
            return
        sym = item.data(0, ROLE_ATOM)
        if item.childCount() == 1 and \
                self._kind(item.child(0)) is None:
            item.takeChildren()
            self._loading = True
            for i, s in enumerate(obj.structure.symbols):
                if s != sym:
                    continue
                self._add_atom_row(item, obj, i)
            self._loading = False

    def _add_atom_row(self, parent, obj, index):
        row = QTreeWidgetItem(["{}{}".format(obj.structure.symbols[index],
                                             index), "", ""])
        row.setData(0, ROLE_KIND, "atom")
        row.setData(0, ROLE_OBJ, obj.id)
        row.setData(0, ROLE_ATOM, index)
        row.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        parent.addChild(row)
        self._attach_controls(row, obj, [index])

    def _attach_controls(self, item, obj, indices):
        """The colour / label / label-type squares — identical for an element
        group and for a single atom, only the index set differs."""
        ctrl = RowControls(self, obj, indices)
        ctrl.changed.connect(self.atom_display_changed)
        self.tree.setItemWidget(item, 2, ctrl)
        self._controls.append(ctrl)

    def refresh_row_controls(self):
        """Re-read every visible control (a group toggle changes its atoms'
        squares and vice versa) and re-mark the molecules that have hidden
        atoms — hiding from a group square never goes through `sync`."""
        for c in list(self._controls):
            try:
                c.refresh()
            except RuntimeError:        # widget already deleted by a re-sync
                self._controls.remove(c)
        for k in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(k)
            obj = self._obj(item)
            if obj is not None:
                self._mark_hidden(item, obj)

    # --------------------------------------------------------- expand state
    def _expanded_keys(self):
        keys = set()
        for k in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(k)
            if top.isExpanded():
                keys.add((self._obj_id(top), None))
            for c in range(top.childCount()):
                grp = top.child(c)
                if grp.isExpanded():
                    keys.add((self._obj_id(grp), grp.data(0, ROLE_ATOM)))
        return keys

    def _restore_expanded(self, keys):
        for k in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(k)
            if (self._obj_id(top), None) in keys:
                top.setExpanded(True)
            for c in range(top.childCount()):
                grp = top.child(c)
                if (self._obj_id(grp), grp.data(0, ROLE_ATOM)) in keys:
                    grp.setExpanded(True)
                    self._on_expanded(grp)

    # ------------------------------------------------------------- signals
    def _sync_label_combo(self, active_id):
        obj = self._scene.get(active_id) if (self._scene and active_id) \
            else None
        mode = obj.label_mode if obj is not None else "element"
        self._loading = True
        for k, (key, _t) in enumerate(LABEL_MODES):
            if key == mode:
                self.label_combo.setCurrentIndex(k)
                break
        self._loading = False

    def _label_mode_changed(self, _index):
        if self._loading:
            return
        for oid in self.selected_object_ids() or []:
            obj = self._scene.get(oid) if self._scene else None
            if obj is not None:
                obj.label_mode = self.label_combo.currentData()
        self.atom_display_changed.emit()

    def _on_item_changed(self, item, column):
        if self._loading:
            return
        kind = self._kind(item)
        if column == self.EYE_COLUMN and kind == "object":
            self.visibility_changed.emit(
                self._obj_id(item),
                item.checkState(self.EYE_COLUMN) == Qt.Checked)
        elif column == 0 and kind == "object":
            self.renamed.emit(self._obj_id(item), item.text(0))

    def _on_item_clicked(self, item, _column):
        kind = self._kind(item)
        if kind == "add":
            self.add_requested.emit()
        elif kind == "object":
            # Qt changes the selection on PRESS and emits itemClicked on
            # RELEASE, so this ran last and collapsed a Ctrl/Shift selection
            # back to the one row clicked. Respect what is actually selected.
            chosen = self.selected_object_ids()
            if len(chosen) > 1:
                self.objects_selected.emit(list(chosen))
            else:
                self.activated.emit(self._obj_id(item))
        elif kind == "atom":
            self.atom_picked.emit(self._obj_id(item),
                                  int(item.data(0, ROLE_ATOM)))

    def _on_selection_changed(self):
        """Ctrl/Shift-selecting several molecule rows selects them ALL in the
        viewport, so they can be grabbed and moved as a group — picking each
        one by Shift+double-click in the 3D view was the only way before."""
        if self._loading:
            return
        chosen = self.selected_object_ids()
        if len(chosen) > 1:
            self.objects_selected.emit(list(chosen))

    def _on_item_double_clicked(self, item, column):
        if column == 0 and self._kind(item) == "object":
            self.tree.editItem(item, 0)

    def _context_menu(self, pos):
        item = self.tree.itemAt(pos)
        kind = self._kind(item)
        menu = QMenu(self)
        if kind == "atom":
            obj = self._obj(item)
            idx = int(item.data(0, ROLE_ATOM))
            act_txt = QAction("Set custom label text...", menu)
            act_txt.triggered.connect(lambda: self._set_custom_text(obj, idx))
            act_col = QAction("Label colour...", menu)
            act_col.triggered.connect(lambda: self._set_label_color(obj, idx))
            menu.addAction(act_txt)
            menu.addAction(act_col)
            menu.exec(self.tree.viewport().mapToGlobal(pos))
            return
        if kind != "object":
            return
        obj_id = self._obj_id(item)
        for text, slot in (
                ("Select molecule", lambda: self.activated.emit(obj_id)),
                ("Rename", lambda: self.tree.editItem(item, 0)),
                ("Hide" if item.checkState(1) == Qt.Checked else "Show",
                 lambda: item.setCheckState(
                     1, Qt.Unchecked if item.checkState(1) == Qt.Checked
                     else Qt.Checked)),
                ("Delete", lambda: self.delete_requested.emit(obj_id))):
            act = QAction(text, menu)
            act.triggered.connect(slot)
            menu.addAction(act)
        chosen = self.selected_object_ids()
        if len(chosen) > 1:
            menu.addSeparator()
            act = QAction("Merge {} molecules into one".format(len(chosen)),
                          menu)
            act.triggered.connect(lambda: self.merge_requested.emit(chosen))
            menu.addAction(act)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _set_custom_text(self, obj, index):
        if obj is None:
            return
        text, ok = QInputDialog.getText(
            self, "Custom label",
            "Label for {}{}:".format(obj.structure.symbols[index], index),
            text=obj.atom_label_text.get(index, ""))
        if not ok:
            return
        obj.atom_label_text[index] = text
        obj.atom_labels.add(index)
        obj.atom_label_modes[index] = "custom"
        self.refresh_row_controls()
        self.atom_display_changed.emit()

    def _set_label_color(self, obj, index):
        if obj is None:
            return
        cur = obj.atom_label_colors.get(index, (1.0, 1.0, 1.0))
        picked = QColorDialog.getColor(
            QColor(int(cur[0] * 255), int(cur[1] * 255), int(cur[2] * 255)),
            self, "Label colour")
        if not picked.isValid():
            return
        obj.atom_label_colors[index] = (picked.redF(), picked.greenF(),
                                        picked.blueF())
        obj.atom_labels.add(index)
        self.atom_display_changed.emit()

    # ---------------------------------------------- eye column drag-paint
    def eventFilter(self, obj, ev):
        if obj is not self.tree.viewport():
            return super().eventFilter(obj, ev)
        if ev.type() == QEvent.MouseButtonPress \
                and ev.button() == Qt.LeftButton:
            item = self.tree.itemAt(ev.position().toPoint())
            col = self.tree.columnAt(int(ev.position().x()))
            if item is not None and col == self.EYE_COLUMN \
                    and self._kind(item) == "object":
                if ev.modifiers() & Qt.ShiftModifier:
                    self.isolate_requested.emit(self._obj_id(item))
                    return True
                self._paint_state = item.checkState(self.EYE_COLUMN) \
                    != Qt.Checked
                self._apply_paint(item)
                return True
        elif ev.type() == QEvent.MouseMove and self._paint_state is not None:
            item = self.tree.itemAt(ev.position().toPoint())
            col = self.tree.columnAt(int(ev.position().x()))
            if item is not None and col == self.EYE_COLUMN \
                    and self._kind(item) == "object":
                self._apply_paint(item)
            return True
        elif ev.type() == QEvent.MouseButtonRelease:
            self._paint_state = None
        return super().eventFilter(obj, ev)

    def _apply_paint(self, item):
        want = Qt.Checked if self._paint_state else Qt.Unchecked
        if item.checkState(self.EYE_COLUMN) != want:
            item.setCheckState(self.EYE_COLUMN, want)

    # ------------------------------------------------------------- helpers
    def selected_object_ids(self):
        out = []
        for item in self.tree.selectedItems():
            oid = self._obj_id(item)
            if oid is not None and self._kind(item) == "object" \
                    and oid not in out:
                out.append(oid)
        return out

    def highlight(self, obj_id):
        """Make this the CURRENT row without destroying a multi-selection.

        Plain `setCurrentItem` clears the selection and selects one row, so
        Ctrl/Shift-picking several molecules was undone the moment the app
        synced the active object back. If the row is already part of the
        selection, only the current index moves.
        """
        from PySide6.QtCore import QItemSelectionModel
        for k in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(k)
            if self._obj_id(item) == obj_id and self._kind(item) == "object":
                self._loading = True
                if item.isSelected():
                    self.tree.setCurrentItem(item, 0,
                                             QItemSelectionModel.NoUpdate)
                else:
                    self.tree.setCurrentItem(item)
                self._loading = False
                self._sync_label_combo(obj_id)
                return

    def start_rename(self, obj_id):
        for k in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(k)
            if self._obj_id(item) == obj_id:
                self.tree.setCurrentItem(item)
                self.tree.editItem(item, 0)
                return

    def current_object_id(self):
        ids = self.selected_object_ids()
        return ids[0] if ids else None
