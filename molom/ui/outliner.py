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

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QAction, QBrush, QColor
from PySide6.QtWidgets import (QColorDialog, QComboBox, QHBoxLayout,
                               QInputDialog, QLabel, QMenu, QToolButton,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

from ..core import elements
from ..core import style as style_mod

_STYLE_CHOICES = [("", "(app style)")] + [(s.key, s.label)
                                          for s in style_mod.STYLES]
LABEL_MODES = [("element", "Element"), ("index", "Index"),
               ("element_index", "Element + index"), ("custom", "Custom")]

ROLE_KIND = Qt.UserRole          # "object" | "element" | "atom" | "add"
ROLE_OBJ = Qt.UserRole + 1
ROLE_ATOM = Qt.UserRole + 2

# Short codes for the label-type square
_MODE_CODE = {"element": "El", "index": "#", "element_index": "E#",
              "custom": "✎"}


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
        for b in (self.colour_btn, self.label_btn, self.mode_btn):
            lay.addWidget(b)
        lay.addStretch(1)
        self.refresh()

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
        self.label_btn.setText({"all": "A", "some": "–", "none": ""}[state])
        self.label_btn.setStyleSheet(
            "QToolButton {{ background: {}; border: 1px solid #1a1a1a;"
            " border-radius: 2px; color: #eee; font-size: 8px; }}".format(
                fill[state]))

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
        self.tree.header().setStretchLastSection(False)
        self.tree.header().resizeSection(0, 168)
        self.tree.header().resizeSection(1, 26)
        self.tree.header().resizeSection(2, 96)
        lay.addWidget(self.tree, 1)

        self._loading = False
        self._paint_state = None
        self._scene = None
        self._controls = []          # live RowControls, refreshed together
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.itemClicked.connect(self._on_item_clicked)
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
            item.setToolTip(self.EYE_COLUMN, "Show / hide in viewport")
            self.tree.addTopLevelItem(item)
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
        squares and vice versa)."""
        for c in list(self._controls):
            try:
                c.refresh()
            except RuntimeError:        # widget already deleted by a re-sync
                self._controls.remove(c)

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
            self.activated.emit(self._obj_id(item))
        elif kind == "atom":
            self.atom_picked.emit(self._obj_id(item),
                                  int(item.data(0, ROLE_ATOM)))

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
        for k in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(k)
            if self._obj_id(item) == obj_id and self._kind(item) == "object":
                self._loading = True
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
