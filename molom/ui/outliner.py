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

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import (QAction, QBrush, QColor, QPainter, QPalette,
                           QPen)
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox,
                               QHBoxLayout, QHeaderView, QInputDialog,
                               QLabel, QMenu, QStyledItemDelegate,
                               QFrame, QToolButton, QToolTip,
                               QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from ..core import attachments as attach_mod
from ..core import elements
from ..core import occupancy
from ..core import style as style_mod
from .widgets import FlowLayout

_STYLE_CHOICES = [("", "(app style)")] + [(s.key, s.label)
                                          for s in style_mod.STYLES]
LABEL_MODES = [("element", "Element"), ("index", "Index"),
               ("element_index", "Element + index"),
               ("occupancy", "Occupancy"), ("custom", "Custom")]

#: Label modes that only mean anything on a crystal. Greyed elsewhere rather
#: than hidden, so it is visible that the option exists and why it is off.
CRYSTAL_ONLY_MODES = {"occupancy"}


def _mode_is_available(key, obj):
    # type: (str, object) -> bool
    if key not in CRYSTAL_ONLY_MODES:
        return True
    try:
        return bool((obj.structure.metadata or {}).get("cell"))
    except AttributeError:
        return False

ROLE_KIND = Qt.UserRole          # "object" | "element" | "site" | "atom" | ...
ROLE_OBJ = Qt.UserRole + 1
ROLE_ATOM = Qt.UserRole + 2      # atom index, or the symbol on a group row
ROLE_HIDDEN = Qt.UserRole + 3    # this molecule has hidden atoms
ROLE_UNPHYSICAL = Qt.UserRole + 4  # an attachment no longer matches it
ROLE_SITE = Qt.UserRole + 5      # asymmetric-unit row, None where unsited
ROLE_SITE_ROWS = Qt.UserRole + 6  # the drawn atoms of that site


def _element_brush(sym):
    # type: (str) -> QColor
    """An element's own colour, for a row that stands for it."""
    c = elements.color_f(elements.atomic_number(sym))
    return QColor(int(c[0] * 255), int(c[1] * 255), int(c[2] * 255))

# Short codes for the label-type square
_MODE_CODE = {"element": "El", "index": "#", "element_index": "E#",
              "custom": "✎"}

# The four states a square can be in, as colours rather than as five copies of
# a stylesheet string. Named for what they MEAN: idle is "nothing set here",
# partial is "some of these atoms", on is "all of them", off is "hidden".
_IDLE = QColor(255, 255, 255, 18)
_PARTIAL = QColor(0x3d, 0x55, 0x6e)
_ON = QColor(0x4a, 0x7a, 0xb0)
_OFF = QColor(0x6b, 0x3a, 0x3a)
_EDGE = QColor(0x1a, 0x1a, 0x1a)
_INK = QColor(0xee, 0xee, 0xee)


class _Divider(QFrame):
    """A hairline between the molecules and the cameras.

    A widget rather than a styled row: a QTreeWidgetItem cannot draw a line
    across the full width without a delegate, and this is one line of code
    that reads as what it is.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.HLine)
        self.setFrameShadow(QFrame.Sunken)
        self.setStyleSheet("color: rgba(255,255,255,45);")


class _HiddenMarkDelegate(QStyledItemDelegate):
    """Marks the two states a molecule's row has to be able to declare.

    **HIDDEN ATOMS: diagonal stripes, not colour.** They used to be painted in
    red, and Christian's objection is a good one - red is the strongest signal
    the outliner has and hiding a few hydrogens is a routine display choice,
    not a problem. Spending red on it leaves nothing louder for the state that
    IS a problem. Stripes say "part of this is not being shown" without
    claiming anything is wrong, and they read at a glance in a long list.

    **UNPHYSICAL: red text.** An attachment that no longer describes the
    structure it was computed for (modes kept across an element change) is a
    correctness warning, and now has the loud colour to itself.

    Both are ROLES rather than brushes. Setting the foreground directly works
    until the row is selected, at which point the style paints the text in
    `HighlightedText` and the mark disappears against the blue - so the one row
    you are looking at is the one that stops telling you anything (round 32).
    """

    #: Faint, because it is information rather than a warning.
    STRIPE = QColor(255, 255, 255, 26)
    STRIPE_STEP = 7

    def __init__(self, colour, parent=None):
        super().__init__(parent)
        self._colour = colour

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        if index.data(ROLE_UNPHYSICAL):
            for role in (QPalette.Text, QPalette.HighlightedText,
                         QPalette.WindowText, QPalette.ButtonText):
                option.palette.setColor(role, self._colour)

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        if not index.data(ROLE_HIDDEN):
            return
        painter.save()
        painter.setClipRect(option.rect)
        pen = QPen(self.STRIPE)
        pen.setWidth(2)
        painter.setPen(pen)
        r = option.rect
        # 45-degree hatching over the whole cell. Drawn from -height so the
        # leading edge is covered as well; the step is what keeps it reading
        # as texture rather than as a fill.
        x = r.left() - r.height()
        while x < r.right():
            painter.drawLine(x, r.bottom(), x + r.height(), r.top())
            x += self.STRIPE_STEP
        painter.restore()


class AttachmentControls(QWidget):
    """The tick boxes for a molecule's computed layers, and its lock.

    Christian's sketch: "Additional visualisation states that are Global for an
    entire mol (such as isosurfaces), that can also originate from an add-on
    get put in an additional row above the expandable element rows, if present,
    as check boxes. Allow for wrapping just in case the amount of checkboxes
    becomes huge."

    So it WRAPS (`FlowLayout`), because the count is not ours to bound - once
    add-ons contribute these, a molecule can accumulate a dozen and a plain row
    would push the rest off the edge of a narrow dock with no hint they were
    there (the round-21 lesson, which is why `FlowLayout` existed already).

    The LOCK sits at the front rather than the end: it governs the whole row,
    and a control that governs the others reads wrongly when it trails them.
    """

    #: Red is now free for this - see `_HiddenMarkDelegate`.
    STALE = "color: rgb(255,105,105);"

    toggled = Signal(int, str, bool)      # obj_id, key, visible
    lock_toggled = Signal(int, bool)      # obj_id, locked

    def __init__(self, obj_id, attachments, locked, parent=None):
        super().__init__(parent)
        self.obj_id = int(obj_id)
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = FlowLayout(self, spacing=6)

        self.lock = QCheckBox("Lock")
        self.lock.setChecked(bool(locked))
        self.lock.setToolTip(
            "Overwrite protection. While this is ticked, edits that would "
            "change what this molecule IS - an element, a bond, deleting an "
            "atom - are refused, because the layers below were computed for "
            "the structure as it stands.\n\nUntick to edit anyway.")
        self.lock.toggled.connect(
            lambda on: self.lock_toggled.emit(self.obj_id, bool(on)))
        lay.addWidget(self.lock)

        for key, att in sorted(attachments.items()):
            # A layer that cannot be switched off gets a LABEL, not a dead
            # tick box - see `Attachment.toggleable`.
            box = QCheckBox(att.label) if att.toggleable else QLabel(att.label)
            if att.toggleable:
                box.setChecked(bool(att.visible))
            bits = [att.detail] if att.detail else []
            if att.source:
                bits.append("from the {} add-on".format(att.source))
            if att.stale:
                box.setStyleSheet(self.STALE)
                bits.append("NO LONGER PHYSICAL - computed before this "
                            "molecule was edited")
            box.setToolTip("\n".join(bits) if bits else att.label)
            if att.toggleable:
                box.toggled.connect(
                    lambda on, k=key: self.toggled.emit(self.obj_id, k,
                                                        bool(on)))
            lay.addWidget(box)


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
    """The five squares an element group, a site and an atom row all carry:
    colour, show/hide, sphere size, label on/off, label type.

    Identical at every level on purpose - the action simply applies to every
    atom the row stands for, so "colour all my oxygens", "colour the O3 site"
    and "colour this one oxygen" are the same gesture at different depths.

    **ONE widget that paints five squares, not five QToolButtons**, and the
    reason is measured rather than stylistic. A row cost about 0.9 ms to build
    because it was seven widgets (five buttons, a layout, the container), so
    opening an element group of 300 atoms took **512 ms** and the tree carried
    2100 widgets afterwards. The same 300 rows carrying ONE bare widget each
    cost 14.5 ms. Nothing about the squares needed a QWidget: they are fixed
    rectangles with a letter in them, and hit-testing five rectangles is the
    one line that replaces all of it.

    The trade is that tooltips and the colour square's right-click menu are
    handled here (`event`, `mousePressEvent`) rather than by Qt per button -
    a few lines, and they were per-square behaviour that had to be described
    somewhere anyway.
    """

    changed = Signal()

    SIZE = 17
    GAP = 2
    PAD = 1

    #: Square order, left to right, and which method a click runs. The order
    #: is the one Christian has been reading since round 26 - do not shuffle
    #: it for tidiness; the letters are memorised by position.
    KEYS = ("colour", "show", "size", "label", "mode")

    def __init__(self, panel, obj, indices, parent=None):
        super().__init__(parent)
        self._panel = panel
        self._obj = obj
        self._rows = list(indices)
        #: key -> (text, background, foreground, tooltip), filled by refresh.
        self._faces = {}
        self.setFixedHeight(self.SIZE + 2 * self.PAD)
        self.setMinimumWidth(len(self.KEYS) * self.SIZE
                             + (len(self.KEYS) - 1) * self.GAP
                             + 2 * self.PAD)
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)
        self.refresh()

    # ------------------------------------------------------------ geometry
    def square_rect(self, key):
        # type: (str) -> QRect
        """Where one square sits. Public because the popups anchor on it."""
        k = self.KEYS.index(key)
        return QRect(self.PAD + k * (self.SIZE + self.GAP), self.PAD,
                     self.SIZE, self.SIZE)

    def _key_at(self, pos):
        for key in self.KEYS:
            if self.square_rect(key).contains(pos):
                return key
        return None

    # ------------------------------------------------------------- display
    def refresh(self):
        obj, rows = self._obj, self._rows
        if not rows:
            return
        faces = {}

        cols = {obj.atom_colors.get(i) for i in rows}
        if len(cols) == 1 and next(iter(cols)) is not None:
            c = next(iter(cols))
            text = ""
        else:
            z = elements.atomic_number(obj.structure.symbols[rows[0]])
            c = elements.color_f(z)
            text = "" if len(cols) == 1 else "~"      # ~ = mixed overrides
        qc = QColor(int(c[0] * 255), int(c[1] * 255), int(c[2] * 255))
        faces["colour"] = (text, qc,
                           QColor("#000") if qc.lightness() > 128
                           else QColor("#ddd"),
                           "Colour - click to set, right-click to reset to "
                           "the element colour")

        # H = these are shown (click to Hide), S = these are hidden (click to
        # Show). A letter, not a glyph: an unlabelled square is a guess.
        hidden = sum(1 for i in rows if i in obj.atom_hidden)
        vis = "none" if hidden == len(rows) else ("some" if hidden else "all")
        faces["show"] = ({"all": "H", "some": "h", "none": "S"}[vis],
                         {"all": _IDLE, "some": _PARTIAL,
                          "none": _OFF}[vis],
                         _INK,
                         "Show these atoms again" if vis == "none"
                         else "Hide these atoms in the viewport")

        # R = radius, replaced by the multiplier once it is not 1.
        scales = {round(obj.atom_scale_for(i), 2) for i in rows}
        if len(scales) == 1:
            value = next(iter(scales))
            size_text = "R" if abs(value - 1.0) < 1e-6 else "{:g}".format(value)
            custom = abs(value - 1.0) > 1e-6
        else:
            size_text, custom = "~", True
        faces["size"] = (size_text, _PARTIAL if custom else _IDLE, _INK,
                         "Sphere size for these atoms - click for a slider")

        on = sum(1 for i in rows if i in obj.atom_labels)
        state = "all" if on == len(rows) else ("some" if on else "none")
        faces["label"] = ({"all": "L", "some": "l", "none": "L"}[state],
                          {"all": _ON, "some": _PARTIAL, "none": _IDLE}[state],
                          _INK, "Label on / off")

        modes = {obj.label_mode_for(i) for i in rows}
        code = _MODE_CODE.get(next(iter(modes)), "?") if len(modes) == 1 \
            else "~"
        faces["mode"] = (code, _IDLE, _INK, "Label type")

        if faces != self._faces:
            self._faces = faces
            self.update()

    def paintEvent(self, _ev):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        font = painter.font()
        font.setPixelSize(8)
        painter.setFont(font)
        for key in self.KEYS:
            face = self._faces.get(key)
            if face is None:
                continue
            text, bg, fg, _tip = face
            rect = self.square_rect(key)
            painter.setPen(QPen(_EDGE))
            painter.setBrush(bg)
            painter.drawRoundedRect(rect.adjusted(0, 0, -1, -1), 2, 2)
            if text:
                painter.setPen(QPen(fg))
                painter.drawText(rect, Qt.AlignCenter, text)
        painter.end()

    # ------------------------------------------------------------- input
    def event(self, ev):
        """Per-square tooltips.

        With five child buttons Qt did this itself; with one widget the tip
        has to follow the pointer, and a single tooltip for the whole row
        would be no tooltip at all - the letters are exactly the thing that
        needs explaining.
        """
        if ev.type() == QEvent.ToolTip:
            key = self._key_at(ev.pos())
            face = self._faces.get(key) if key else None
            QToolTip.showText(ev.globalPos(), face[3] if face else "", self)
            return True
        return super().event(ev)

    def mousePressEvent(self, ev):
        key = self._key_at(ev.position().toPoint())
        if key is None:
            super().mousePressEvent(ev)
            return
        if ev.button() == Qt.RightButton:
            # Only the colour square has ever had a second action, and it is
            # the one that needs a way back: an atom painted by hand has no
            # other route to "whatever the element says".
            if key == "colour":
                self._reset_colour()
            ev.accept()
            return
        if ev.button() != Qt.LeftButton:
            super().mousePressEvent(ev)
            return
        {"colour": self._pick_colour, "show": self._toggle_shown,
         "size": self._pick_size, "label": self._toggle_label,
         "mode": self._pick_mode}[key]()
        ev.accept()

    def _popup_at(self, popup, key, align_right):
        """Put a popup under one square, kept on the screen.

        Anchored on the square's RIGHT edge where it is wide: the outliner
        lives against the right side of the window, so a popup growing
        rightwards runs off the screen (round 27).
        """
        rect = self.square_rect(key)
        corner = rect.bottomRight() if align_right else rect.bottomLeft()
        pos = self.mapToGlobal(corner)
        if align_right:
            pos -= QPoint(popup.width(), 0)
        screen = self.screen().availableGeometry() if self.screen() else None
        if screen is not None:
            pos.setX(max(screen.left() + 2,
                         min(pos.x(), screen.right() - popup.width() - 2)))
            pos.setY(max(screen.top() + 2,
                         min(pos.y(), screen.bottom() - popup.height() - 2)))
        popup.move(pos)

    # ------------------------------------------------------------- actions
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
        """A slider in a popup, right under the square that opened it -
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
        self._popup_at(popup, "size", align_right=True)
        popup.show()

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
            act.setEnabled(_mode_is_available(key, self._obj))
            if not act.isEnabled():
                act.setToolTip("This molecule has no unit cell, so it has no "
                               "site occupancies to label.")
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
        menu.exec(self.mapToGlobal(self.square_rect("mode").bottomLeft()))

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
    camera_activated = Signal(int)       # double-clicked: look through it
    camera_renamed = Signal(int, str)
    camera_delete_requested = Signal(int)
    camera_add_requested = Signal()
    atom_display_changed = Signal()          # colours / labels edited
    atom_picked = Signal(int, int)           # obj_id, atom index
    atoms_selected = Signal(list)            # [(obj_id, atom), ...]
    crystal_view_changed = Signal(int, str)  # obj_id, 'asym' | 'cell'
    crystal_box_toggled = Signal(int, bool)
    crystal_poly_toggled = Signal(int, bool)
    crystal_exterior_toggled = Signal(int, bool)
    attachment_toggled = Signal(int, str, bool)   # obj_id, key, visible
    attachment_lock_toggled = Signal(int, bool)   # obj_id, locked
    comment_requested = Signal(int)               # obj_id
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
        self.tree.itemCollapsed.connect(self._on_collapsed)
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
            self._add_attachment_row(item, obj)
            self._add_crystal_row(item, obj)
            self._add_element_groups(item, obj)
            if obj.id == active_id:
                item.setSelected(True)
        add = QTreeWidgetItem(["+  New molecule", "", ""])
        add.setData(0, ROLE_KIND, "add")
        add.setFlags(Qt.ItemIsEnabled)
        add.setForeground(0, QColor(150, 190, 240))
        self.tree.addTopLevelItem(add)
        self._add_camera_section(scene)
        self._restore_expanded(expanded)
        self._loading = False
        self._sync_label_combo(active_id)

    def _add_camera_section(self, scene):
        """Saved viewpoints, under a divider.

        A camera is not a molecule — it has no atoms, no style and no
        elements — so it goes below its own rule rather than in the same list
        pretending to be one. Christian asked for the divider explicitly, and
        it is the same device the F3 palette uses between categories.
        """
        cams = list(getattr(scene, "cameras", []) or [])
        if not cams and not getattr(scene, "cameras", None):
            # Still show the "+ Camera" row: a feature nobody can find is one
            # nobody has. It is one line and it explains itself.
            pass
        rule = QTreeWidgetItem(["", "", ""])
        rule.setData(0, ROLE_KIND, "divider")
        rule.setFlags(Qt.ItemIsEnabled)
        rule.setSizeHint(0, QSize(1, 9))
        self.tree.addTopLevelItem(rule)
        self.tree.setItemWidget(rule, 0, _Divider(self.tree))

        active = getattr(scene, "active_camera_id", None)
        for cam in cams:
            item = QTreeWidgetItem(["\U0001F3A5  " + cam.name, "", ""])
            item.setData(0, ROLE_KIND, "camera")
            item.setData(0, ROLE_OBJ, cam.id)
            item.setFlags(item.flags() | Qt.ItemIsEditable)
            item.setToolTip(
                0, "{:.0f} mm {}, {}x{} at {:g}x\n\nDouble-click to look "
                   "through it (Numpad 0 toggles the last one)".format(
                       cam.focal_mm, cam.projection, cam.width, cam.height,
                       cam.multiplier))
            if cam.id == active:
                item.setForeground(0, QColor(150, 190, 240))
            self.tree.addTopLevelItem(item)
        add_cam = QTreeWidgetItem(["+  Camera (save this view)", "", ""])
        add_cam.setData(0, ROLE_KIND, "add_camera")
        add_cam.setFlags(Qt.ItemIsEnabled)
        add_cam.setForeground(0, QColor(150, 190, 240))
        self.tree.addTopLevelItem(add_cam)

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
        # UNPHYSICAL is a separate mark from HIDDEN and they can both be on:
        # hiding is a display choice (stripes), a stale attachment is a
        # correctness warning (red). Round 32's reason for using a role rather
        # than a brush applies to both - see `_HiddenMarkDelegate`.
        stale = attach_mod.describe_stale(obj)
        item.setData(0, ROLE_UNPHYSICAL, True if stale else None)
        tips = []
        if obj.has_hidden:
            tips.append("{} of {} atoms hidden — tick the eye off and on, or "
                        "Alt+H, to bring them back".format(
                            len(obj.atom_hidden), obj.structure.n_atoms))
        if stale:
            tips.append(stale)
        item.setToolTip(0, "\n".join(tips))

    def _add_attachment_row(self, parent_item, obj):
        """The computed-layer tick boxes, ABOVE the element groups.

        Nothing is added for a molecule that has none, which is most of them -
        Christian: "Only add overwrite protections to outliner objects that
        actually require them." A lock on an object with nothing to lose is
        noise, and noise is what teaches people to click through warnings.
        """
        table = attach_mod.attachments_of(obj)
        if not table:
            return
        row = QTreeWidgetItem(["", "", ""])
        row.setData(0, ROLE_KIND, "attachments")
        row.setData(0, ROLE_OBJ, obj.id)
        row.setFlags(Qt.ItemIsEnabled)
        parent_item.addChild(row)
        controls = AttachmentControls(obj.id, table,
                                      attach_mod.is_locked(obj))
        controls.toggled.connect(self.attachment_toggled)
        controls.lock_toggled.connect(self.attachment_lock_toggled)
        row.setFirstColumnSpanned(True)
        self.tree.setItemWidget(row, 0, controls)

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
        """One collapsed row per element; everything below is filled in on
        expand so a 3000-atom slab does not build 3000 widgets nobody asked
        for - and thrown away again on collapse, so it does not keep them."""
        counts = {}
        for i, sym in enumerate(obj.structure.symbols):
            counts.setdefault(sym, []).append(i)
        meta = obj.structure.metadata or {}
        for sym in sorted(counts, key=lambda s: elements.atomic_number(s)):
            rows = counts[sym]
            grp = QTreeWidgetItem(["{}   ({})".format(sym, len(rows)), "", ""])
            grp.setData(0, ROLE_KIND, "element")
            grp.setData(0, ROLE_OBJ, obj.id)
            grp.setData(0, ROLE_ATOM, sym)
            grp.setForeground(0, QBrush(_element_brush(sym)))
            grp.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            sites = occupancy.site_groups(meta, rows)
            if len(sites) > 1:
                grp.setToolTip(0, "{} {} atoms over {} crystallographic "
                               "sites".format(len(rows), sym, len(sites)))
            self._add_placeholder(grp)
            parent.addChild(grp)
            self._attach_controls(grp, obj, rows)

    # ------------------------------------------------- lazy fill and free
    def _add_placeholder(self, item):
        """What a collapsed group carries instead of its rows.

        A child rather than a flag, because a `QTreeWidget` draws no expander
        arrow on an item with no children - so an emptied group would look
        like a leaf and could never be opened again.
        """
        dummy = QTreeWidgetItem(["..."])
        dummy.setFlags(Qt.NoItemFlags)
        item.addChild(dummy)

    def _is_placeheld(self, item):
        return (item.childCount() == 1
                and self._kind(item.child(0)) is None)

    def _on_expanded(self, item):
        """Build this group's children the first time it is opened."""
        if self._loading or self._kind(item) not in ("element", "site"):
            return
        obj = self._obj(item)
        if obj is None or not self._is_placeheld(item):
            return
        item.takeChildren()
        # Saved and RESTORED, not forced back to False: this also runs from
        # inside `sync`, which holds the guard down for the whole rebuild.
        was, self._loading = self._loading, True
        drawing = self.tree.updatesEnabled()
        # Building a few hundred rows one at a time makes the tree re-lay
        # itself out on each of them; the whole fill is one update instead.
        self.tree.setUpdatesEnabled(False)
        try:
            if self._kind(item) == "site":
                for i in item.data(0, ROLE_SITE_ROWS) or []:
                    self._add_atom_row(item, obj, int(i))
            else:
                self._fill_element(item, obj, item.data(0, ROLE_ATOM))
        finally:
            self.tree.setUpdatesEnabled(drawing)
            self._loading = was

    def _fill_element(self, item, obj, sym):
        """Atoms of this element - or, in a crystal, the SITES they belong to.

        Christian's point, and it is crystallographic rather than a
        convenience: "let's say I want to hide all oxygen atoms of a specific
        type". An element is not a type. A cell draws one asymmetric-unit site
        over and over - ferrocene's `C(11)` is twenty of its hundred carbons -
        and THAT is what the refinement calls a type, what the file labels,
        and what somebody means by "the bridging oxygens" as against "the
        terminal ones".

        The tier appears only where there is more than one site to choose
        between. One site is not a grouping, it is the same list one click
        deeper; a molecule has no sites at all. Both fall through to the plain
        element -> atom tree that was here before.
        """
        rows = [i for i, s in enumerate(obj.structure.symbols) if s == sym]
        meta = obj.structure.metadata or {}
        sites = occupancy.site_groups(meta, rows)
        if len(sites) < 2:
            for i in rows:
                self._add_atom_row(item, obj, i)
            return
        for site, label, indices in sites:
            # The unsited group is real and is named as such: an atom added
            # by an edit is an image of nothing, and filing it under a site
            # it has no relation to would be a quiet lie about the structure.
            text = label if site is not None else "(added since)"
            row = QTreeWidgetItem(["{}   ({})".format(text, len(indices)),
                                   "", ""])
            row.setData(0, ROLE_KIND, "site")
            row.setData(0, ROLE_OBJ, obj.id)
            row.setData(0, ROLE_ATOM, sym)
            row.setData(0, ROLE_SITE, site)
            row.setData(0, ROLE_SITE_ROWS, list(indices))
            row.setForeground(0, QBrush(_element_brush(sym)))
            row.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            row.setToolTip(0, "Crystallographic site {} - {} drawn atoms from "
                           "one row of the asymmetric unit".format(
                               text, len(indices)))
            self._add_placeholder(row)
            item.addChild(row)
            self._attach_controls(row, obj, list(indices))

    def _on_collapsed(self, item):
        """Give the rows back.

        Measured before it was written, because the number decides whether it
        is worth doing: 300 atom rows cost 473 ms to build and left 300 live
        `RowControls` behind - and `refresh_row_controls` walks every one of
        them on every colour, label or visibility change, which was 190 ms of
        work per click on rows nobody could see. Collapsing kept all of it.
        Freeing on collapse bounds the cost to what is actually open.
        """
        if self._loading or self._kind(item) not in ("element", "site"):
            return
        if self._is_placeheld(item):
            return
        was, self._loading = self._loading, True
        try:
            self._drop_controls_under(item)
            item.takeChildren()
            self._add_placeholder(item)
        finally:
            self._loading = was

    def _drop_controls_under(self, item):
        """Unregister the row widgets of everything below `item`.

        `takeChildren` destroys the items and Qt deletes the widgets that were
        set on them - but `self._controls` would keep the dead Python
        wrappers, and `refresh_row_controls` would then be walking a list that
        only ever grows. It catches `RuntimeError` for exactly that reason;
        this is what stops the list needing to be caught.
        """
        doomed = set()

        def walk(node):
            for k in range(node.childCount()):
                child = node.child(k)
                widget = self.tree.itemWidget(child, 2)
                if widget is not None:
                    doomed.add(id(widget))
                walk(child)

        walk(item)
        if doomed:
            self._controls = [c for c in self._controls
                              if id(c) not in doomed]

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
        """The colour / label / label-type squares - identical for an element
        group, a crystallographic site and a single atom, only the index set
        differs. That is what makes "hide every oxygen of this type" the same
        gesture as "hide this oxygen", one row up."""
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
    #: What identifies a row across a `sync`, which throws every item away and
    #: builds new ones. A PATH rather than a pair, because the site tier makes
    #: the tree three deep and `(object, symbol)` can no longer tell an
    #: element group from the sites inside it.
    def _expand_key(self, item):
        return (self._obj_id(item), self._kind(item),
                item.data(0, ROLE_ATOM), item.data(0, ROLE_SITE))

    def _expanded_keys(self):
        keys = set()

        def walk(node, path):
            for k in range(node.childCount()):
                child = node.child(k)
                if self._kind(child) is None:
                    continue                       # the "..." placeholder
                here = path + (self._expand_key(child),)
                if child.isExpanded():
                    keys.add(here)
                    walk(child, here)

        for k in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(k)
            here = (self._expand_key(top),)
            if top.isExpanded():
                keys.add(here)
                walk(top, here)
        return keys

    def _restore_expanded(self, keys):
        """Re-open what was open, depth first.

        Each level has to be FILLED before the level below it can be found,
        so `_on_expanded` is called explicitly rather than left to the signal
        - `sync` runs under `_loading`, which is exactly what makes the signal
        do nothing.
        """
        def walk(node, path):
            for k in range(node.childCount()):
                child = node.child(k)
                if self._kind(child) is None:
                    continue
                here = path + (self._expand_key(child),)
                if here in keys:
                    child.setExpanded(True)
                    self._fill_now(child)
                    walk(child, here)

        for k in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(k)
            here = (self._expand_key(top),)
            if here in keys:
                top.setExpanded(True)
                walk(top, here)

    def _fill_now(self, item):
        """`_on_expanded` with the loading guard lifted for the one call."""
        was, self._loading = self._loading, False
        try:
            self._on_expanded(item)
        finally:
            self._loading = was

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
        elif column == 0 and kind == "camera":
            # The row carries a glyph the user did not type, so it is
            # stripped before the name goes back to the scene.
            self.camera_renamed.emit(self._obj_id(item),
                                     item.text(0).lstrip("🎥 "))

    def _on_item_clicked(self, item, _column):
        kind = self._kind(item)
        if kind == "add":
            self.add_requested.emit()
        elif kind == "add_camera":
            self.camera_add_requested.emit()
        elif kind == "object":
            # Qt changes the selection on PRESS and emits itemClicked on
            # RELEASE, so this ran last and collapsed a Ctrl/Shift selection
            # back to the one row clicked. Respect what is actually selected.
            chosen = self.selected_object_ids()
            if len(chosen) > 1:
                self.objects_selected.emit(list(chosen))
            else:
                self.activated.emit(self._obj_id(item))
        elif kind in ("atom", "site", "element"):
            # Qt changes the selection on PRESS and emits itemClicked on
            # RELEASE, so emitting one atom here ran LAST and collapsed a
            # Ctrl/Shift range back to the row clicked - the same trap the
            # object branch above already had to be fixed for. Respect what
            # is actually selected.
            atoms = self.selected_atoms()
            if atoms:
                self.atoms_selected.emit(atoms)
            if kind == "atom" and len(atoms) == 1:
                self.atom_picked.emit(self._obj_id(item),
                                      int(item.data(0, ROLE_ATOM)))

    def atoms_of_row(self, item):
        # type: (object) -> list
        """Every atom index a row STANDS FOR.

        One rule for all three depths, and it is the same rule the colour and
        visibility squares already use: an atom row is its atom, a site row is
        the whole symmetry orbit, an element row is every atom of that
        element. That is what makes "select this site" a gesture at all.
        """
        kind = self._kind(item)
        if kind == "atom":
            return [int(item.data(0, ROLE_ATOM))]
        if kind == "site":
            return [int(i) for i in (item.data(0, ROLE_SITE_ROWS) or [])]
        if kind == "element":
            obj = self._obj(item)
            sym = item.data(0, ROLE_ATOM)
            if obj is None:
                return []
            return [i for i, s in enumerate(obj.structure.symbols)
                    if s == sym]
        return []

    def selected_atoms(self):
        # type: () -> list
        """`[(obj_id, atom), ...]` for every atom row currently selected."""
        picks, seen = [], set()
        for item in self.tree.selectedItems():
            oid = self._obj_id(item)
            if oid is None:
                continue
            for index in self.atoms_of_row(item):
                key = (int(oid), int(index))
                if key not in seen:
                    seen.add(key)
                    picks.append(key)
        return picks

    def _on_selection_changed(self):
        """Take the tree's selection into the viewport.

        Two kinds of row, and they mean different things. Several MOLECULE
        rows select those molecules, so they can be grabbed and moved as a
        group - picking each one by Shift+double-click in the 3D view was the
        only way before (round 24).

        Several ATOM rows now select those atoms, which is Christian's
        report: "selecting multiple atoms in the outline does not highlight
        them in the viewport, making editing multiple atoms very tiresome."
        The outliner was emitting `atom_picked` for ONE atom on click and
        nothing at all for a Ctrl or Shift range, so the tree could show six
        rows highlighted while the viewport showed one atom - two selections
        disagreeing, with the one you were looking at being the wrong one.

        Atoms WIN when both kinds are selected: a mixed selection comes from
        Ctrl-clicking down a tree, and the atoms are the specific thing;
        replacing them with their whole molecule would quietly widen an edit.
        """
        if self._loading:
            return
        atoms = self.selected_atoms()
        if atoms:
            self.atoms_selected.emit(atoms)
            return
        chosen = self.selected_object_ids()
        if len(chosen) > 1:
            self.objects_selected.emit(list(chosen))

    def _on_item_double_clicked(self, item, column):
        if column == 0 and self._kind(item) == "camera":
            self.camera_activated.emit(int(self._obj_id(item)))
            return
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
        if kind == "camera":
            cam_id = int(self._obj_id(item))
            for text, slot in (
                    ("Look through", lambda: self.camera_activated.emit(cam_id)),
                    ("Rename", lambda: self.tree.editItem(item, 0)),
                    ("Delete",
                     lambda: self.camera_delete_requested.emit(cam_id))):
                act = QAction(text, menu)
                act.triggered.connect(slot)
                menu.addAction(act)
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
                ("Edit comment...",
                 lambda: self.comment_requested.emit(obj_id)),
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
