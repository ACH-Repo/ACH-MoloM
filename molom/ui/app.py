"""Main window: scene + outliner, menus, F3 operator palette, trajectory bar.

A thin shell over molom.core — every action is an operator registered in
core.ops (which also powers F3 search); menus/shortcuts just trigger them.
The scene (multiple molecules) lives here; the viewport renders it.
"""

import os
from typing import List, Optional

import numpy as np

from PySide6.QtCore import QEvent, QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QHBoxLayout, QInputDialog, QLabel,
    QMainWindow, QMessageBox, QSlider, QSpinBox, QToolButton, QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..core import align as align_mod
from ..core import build as build_mod
from ..core import modifiers as modifiers_mod
from ..core import bonding, edits, io, measure, project, rotations
from ..core.camera import quat_from_mat3, quat_to_mat3
from ..core import resolve as resolve_mod
from ..core.ops import OperatorRegistry
from ..core.scene import Scene
from ..core.structure import Structure
from ..core import style as style_mod
from ..core.undo import UndoStack
from .dialogs import OperatorSearchDialog, ResolveNameDialog, SettingsDialog
from .optimize_panel import OptimizeDock, OptimizeWorker, TASK_SELECTION
from .properties import ModifierPage, PropertiesDock
from .toolbar import ViewportToolbar
from .outliner import OutlinerPanel
from .transform_panel import TransformDock
from .viewport import MODE_EDIT, MODE_OBJECT, MolViewport

_MAX_RECENT = 8


def apply_dark_theme(app):
    """Blender-ish dark greys for the whole UI (menus, docks, dialogs) —
    Fusion style + palette, so it works identically on every platform."""
    from PySide6.QtGui import QColor, QPalette
    app.setStyle("Fusion")
    p = QPalette()
    grey = QColor(53, 53, 53)
    base = QColor(42, 42, 42)
    text = QColor(220, 220, 220)
    disabled = QColor(128, 128, 128)
    p.setColor(QPalette.Window, grey)
    p.setColor(QPalette.WindowText, text)
    p.setColor(QPalette.Base, base)
    p.setColor(QPalette.AlternateBase, QColor(58, 58, 58))
    p.setColor(QPalette.ToolTipBase, QColor(42, 42, 42))
    p.setColor(QPalette.ToolTipText, text)
    p.setColor(QPalette.Text, text)
    p.setColor(QPalette.Button, grey)
    p.setColor(QPalette.ButtonText, text)
    p.setColor(QPalette.BrightText, QColor(255, 120, 120))
    p.setColor(QPalette.Link, QColor(110, 160, 220))
    p.setColor(QPalette.Highlight, QColor(70, 105, 150))
    p.setColor(QPalette.HighlightedText, QColor(240, 240, 240))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, disabled)
    p.setColor(QPalette.Disabled, QPalette.Highlight, QColor(80, 80, 80))
    app.setPalette(p)


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("MoloM")
        self.settings = QSettings("ACH", "MoloM")
        self.scene = Scene()
        self.active_id = None            # type: Optional[int]
        self.undo = UndoStack(limit=int(self.settings.value("undo_limit", 30)))
        self._last_axis_align = None     # {"obj_id", "axis", "pivot"}
        self.project_path = None         # type: Optional[str]  (.molom)
        self._local_view = None          # {obj_id: visible} while isolated
        self._pending_suppress = False   # merge the next push into this one
        self._last_push_suppressed = False
        self._repeat_macro = None        # {"delta"} after D + move
        self._macro_serial = -1          # viewport transform_serial it came from
        self._dup_grab_active = False

        self.viewport = MolViewport(self)
        self.viewport.set_scene(self.scene)
        self.viewport.camera.rotate_speed = float(
            self.settings.value("rotate_speed", 1.0))
        self.viewport.precision_factor = float(
            self.settings.value("precision_factor", 0.5))
        self.viewport.selection_changed.connect(self._on_selection_changed)
        self.viewport.status_message.connect(
            lambda t: self.statusBar().showMessage(t, 4000))
        self.viewport.edit_committed.connect(self._on_edit_committed)
        self.viewport.origin_active_changed.connect(
            lambda _on: self._sync_transform_panel())
        # Undo hooks: modals + anchored-rotation gestures snapshot through us.
        self.viewport.on_model_edit_begin = self.push_undo
        self.viewport.on_model_edit_cancel = self._on_model_edit_cancel
        self.viewport.on_align_key = self._on_align_key
        self.viewport.on_edit_begin = self.push_undo
        self.viewport.on_mode_changed = self._on_mode_changed
        self.viewport.on_new_molecule = self.new_empty_molecule
        self.viewport.on_toggle_mode = \
            lambda: self.viewport.toggle_mode(self.active_id)
        self.viewport.set_atom_scale(
            float(self.settings.value("atom_scale", 0.9)))
        self.viewport.adjust_h = self.settings.value(
            "adjust_hydrogens", "true") in (True, "true")

        self._play_timer = QTimer(self)
        self._play_timer.timeout.connect(self._advance_frame)

        self._build_trajectory_bar()
        central = QWidget(self)
        col = QVBoxLayout(central)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        col.addWidget(self.viewport, 1)
        col.addWidget(self.traj_bar, 0)
        self.setCentralWidget(central)

        self.outliner = OutlinerPanel(self)
        self.outliner.visibility_changed.connect(self._on_obj_visibility)
        self.outliner.atom_display_changed.connect(
            lambda: (self.viewport.refresh_geometry(), self.viewport.update()))
        self.outliner.atom_picked.connect(
            lambda oid, i: self.viewport.set_selection([(oid, i)]))
        self.outliner.isolate_requested.connect(self._on_obj_isolate)
        self.outliner.style_changed.connect(self._on_obj_style)
        self.outliner.renamed.connect(self._on_obj_renamed)
        self.outliner.delete_requested.connect(self._on_obj_delete)
        self.outliner.activated.connect(self._on_obj_activated)
        self.outliner.add_requested.connect(self.on_outliner_add)
        self.outliner.merge_requested.connect(self.on_merge_ids)

        # The N panel lives along the BOTTOM edge: it pops in and out like
        # the outliner without competing with it for width.
        self.transform_panel = TransformDock(self)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.transform_panel)
        self.transform_panel.setVisible(False)

        self.optimize_panel = OptimizeDock(self)
        self.optimize_panel.start_requested.connect(self.on_optimize)
        self._opt_worker = None

        # Blender's properties editor: one dock, a vertical tab strip, and a
        # page per topic. The force-field panel lives in it as a page rather
        # than competing for the same edge.
        self.modifier_page = ModifierPage()
        self.modifier_page.changed.connect(self._on_modifiers_changed)
        self.modifier_page.add_requested.connect(self.on_add_modifier)
        self.modifier_page.remove_requested.connect(self.on_remove_modifier)
        self.modifier_page.apply_requested.connect(self.on_apply_modifiers)
        # ONE right-hand dock for everything: scene tree, modifiers, force
        # field. Separate docks were fighting each other for the same edge
        # and each one cost vertical space it did not need.
        self.properties = PropertiesDock(
            [("outliner", "🗂", "Scene outliner", self.outliner),
             ("modifiers", "🔧", "Modifiers", self.modifier_page),
             ("forcefield", "⚛", "Force field",
              self.optimize_panel.widget())], self)
        self.addDockWidget(Qt.RightDockWidgetArea, self.properties)
        self._panel_drag_active = False
        self.transform_panel.drag_started.connect(self._on_panel_drag_started)
        self.transform_panel.location_changed.connect(self._on_panel_location)
        self.transform_panel.rotation_changed.connect(self._on_panel_rotation)

        # Edge tabs: small, semi-transparent, arrow-only, and each one sits
        # on the edge ITS dock is attached to (outliner right, transform
        # bottom) so the arrow points the way the panel will come out.
        self._outliner_tab = self._make_edge_tab(
            central, "Show / hide outliner (M)", self.on_toggle_outliner)
        self._transform_tab = self._make_edge_tab(
            central, "Show / hide transform panel (N)",
            self.on_toggle_transform)
        self._optimize_tab = self._make_edge_tab(
            central, "Show / hide the properties panel (modifiers, force "
            "field)", lambda: self.on_toggle_properties())
        for dock in (self.transform_panel, self.properties):
            dock.visibilityChanged.connect(
                lambda _v: self._position_outliner_tab())
        # Docks resize the central widget AFTER visibilityChanged fires, so
        # tab placement keys off the central widget's OWN resize events —
        # this is what keeps the edge tabs glued to the panel boundary.
        central.installEventFilter(self)

        # Blender's T-panel: a floating tool column over the viewport itself.
        self.toolbar = ViewportToolbar(self.viewport)
        self.toolbar.move(8, 8)
        self.toolbar.tool_clicked.connect(self._on_tool_clicked)
        self.toolbar.set_enabled_tools(False)
        self.toolbar.show()
        self.viewport.on_tool_changed = lambda on: self.toolbar.set_active(
            "draw" if on else "select")

        self.ops = OperatorRegistry()
        self._register_operators()
        self._build_menus()
        self._build_statusbar()
        self.setAcceptDrops(True)
        self.resize(1100, 740)

    def load_default_scene(self):
        """Blender opens on a cube; MoloM opens on cubane — centred on the
        origin and axis-aligned. Beats an empty viewport with a wall of
        import instructions, and gives something to orbit immediately."""
        if self.scene.n_objects:
            return
        s = build_mod.cubane()
        obj = self.scene.add(s)
        self.active_id = obj.id
        self._sync_all(fit=True)
        self.undo.clear()          # the starter scene is not an edit to undo
        self.statusBar().showMessage(
            "cubane — Tab to edit, Ctrl+O to open a file, "
            "Ctrl+Shift+N to import by name", 9000)

    # ------------------------------------------------------------- startup
    def show_startup(self):
        """Maximized by default; windowed (setting) anchors upper-right."""
        if self.settings.value("start_maximized", "true") in (True, "true"):
            self.showMaximized()
            return
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            w, h = min(1100, avail.width()), min(740, avail.height())
            self.setGeometry(avail.right() - w, avail.top(), w, h)
        self.show()

    # ------------------------------------------------------------ operators
    def _register_operators(self):
        r = self.ops.register
        sel = lambda ctx: bool(ctx.viewport.selection)
        two_same = lambda ctx: (len(ctx.viewport.selection) == 2 and
                                ctx.viewport.selection[0][0]
                                == ctx.viewport.selection[1][0])
        has_obj = lambda ctx: ctx.scene.n_objects > 0
        has_active = lambda ctx: ctx._active_obj() is not None

        r("open", "Open structure file or project...", lambda c: c.on_open(),
          category="File", shortcut="Ctrl+O")
        r("save_project", "Save project (savepoint)",
          lambda c: c.on_save_project(), enabled=has_obj, category="File",
          shortcut="Ctrl+S")
        r("save_project_as", "Save project as...",
          lambda c: c.on_save_project_as(), enabled=has_obj, category="File",
          shortcut="Ctrl+Shift+P")
        r("import_name", "Import molecule by name...",
          lambda c: c.on_import_by_name(), category="File",
          shortcut="Ctrl+Shift+N")
        r("from_smiles", "Add molecule from SMILES...",
          lambda c: c.on_from_smiles(), category="File", shortcut="F3 only")
        r("copy_smiles", "Copy SMILES of the selected molecule to clipboard",
          lambda c: c.on_copy_smiles(), enabled=sel, category="Molecule")
        r("name_from_structure", "Name molecule from its structure (PubChem)",
          lambda c: c.on_name_from_structure(), enabled=has_active,
          category="Molecule")
        r("merge", "Merge selected molecules into one",
          lambda c: c.on_merge(),
          enabled=lambda c: (len({p[0] for p in c.viewport.selection}) > 1
                             or len(c.outliner.selected_object_ids()) > 1),
          category="Molecule",
          aliases=("join", "combine", "unite"))
        r("paste", "Paste XYZ / SMILES", lambda c: c.on_paste(),
          category="File", shortcut="Ctrl+V")
        r("save_as", "Export geometry (visible molecules)...",
          lambda c: c.on_save_as(), enabled=has_obj, category="File",
          shortcut="Ctrl+E")
        r("export_image", "Export image (PNG snapshot of the viewport)...",
          lambda c: c.on_export_image(), enabled=has_obj, category="File",
          shortcut="Ctrl+Shift+E")
        r("clear_scene", "Clear scene (remove all molecules)",
          lambda c: c.on_clear_scene(), enabled=has_obj, category="File")

        r("select_all", "Select all", lambda c: c.on_select_all(),
          enabled=has_obj, category="Select", shortcut="Ctrl+A")
        r("clear_selection", "Clear selection",
          lambda c: c.viewport.set_selection([]), enabled=sel,
          category="Select", shortcut="Alt+A (or Esc)")
        r("toggle_draw", "Draw tool on / off (edit mode)",
          lambda c: c.viewport.set_draw_tool(not c.viewport.draw_tool_active),
          enabled=lambda c: c.viewport.mode == MODE_EDIT, category="Edit",
          shortcut="E")
        r("select_linked", "Select whole molecule of selection",
          lambda c: c.on_select_linked(), enabled=sel, category="Select",
          shortcut="Ctrl+L")
        r("box_select", "Box select (arm tool)",
          lambda c: c.viewport.set_select_tool("box"), enabled=has_obj,
          category="Select", shortcut="Shift+Space, B / dbl-click-drag")
        r("lasso_select", "Lasso select (arm tool)",
          lambda c: c.viewport.set_select_tool("lasso"), enabled=has_obj,
          category="Select", shortcut="Shift+Space, L")

        r("move_grab", "Move selection (grab)",
          lambda c: c.viewport.start_grab(), enabled=sel, category="Edit",
          shortcut="G, then X/Y/Z, number")
        r("rotate", "Rotate selection",
          lambda c: c.viewport.start_rotate(), enabled=sel, category="Edit",
          shortcut="R, then X/Y/Z, degrees")
        r("undo", "Undo", lambda c: c.on_undo(),
          enabled=lambda c: c.undo.can_undo, category="Edit",
          shortcut="Ctrl+Z")
        r("redo", "Redo", lambda c: c.on_redo(),
          enabled=lambda c: c.undo.can_redo, category="Edit",
          shortcut="Ctrl+Y")
        r("origin_edit", "Origin: snap to selection and pick up (edit mode)",
          lambda c: c.on_origin_edit(),
          enabled=lambda c: c.viewport.mode == MODE_EDIT, category="Edit",
          shortcut="O (edit mode), or click the orange dot")
        r("duplicate", "Duplicate selection into a new molecule",
          lambda c: c.on_duplicate(), enabled=sel, category="Edit",
          shortcut="D")
        r("repeat_transform", "Repeat last action (duplicate + move)",
          lambda c: c.on_repeat_last(),
          enabled=lambda c: (c._repeat_macro is not None
                             or (c.viewport.last_transform is not None
                                 and bool(c.viewport.selection))),
          category="Edit", shortcut="Shift+R")
        r("shuttle", "Shuttle mode: pilot the selected molecule",
          lambda c: c.on_shuttle(), enabled=has_active, category="View")
        r("toggle_hbonds", "Show suspected hydrogen bonds",
          lambda c: c.viewport.toggle_hbonds(), category="View",
          aliases=("h-bond", "hydrogen bonding", "contacts"))
        r("optimize_panel", "Force field: optimize geometry (panel)",
          lambda c: c.on_toggle_optimize(), category="Edit", shortcut="Ctrl+R")
        r("modifier_panel", "Modifiers panel (array, ...)",
          lambda c: c.on_toggle_properties("modifiers"), category="Modifier",
          aliases=("array", "properties", "stack"))
        r("add_array", "Add an array modifier to the active molecule",
          lambda c: c.on_add_modifier("array"), enabled=has_active,
          category="Modifier", aliases=("duplicate pattern", "surface",
                                        "repeat"))
        r("apply_modifiers", "Apply the modifier stack (bake into atoms)",
          lambda c: c.on_apply_modifiers(),
          enabled=lambda c: bool(getattr(c._active_obj(), "modifiers", None)),
          category="Modifier")
        r("optimize_now", "Force field: optimize active molecule now",
          lambda c: c.on_optimize("all", "mmff94", 500), enabled=has_active,
          category="Edit")
        r("origin_snap", "Origin: snap to selection centroid",
          lambda c: c.on_origin_snap(), enabled=has_active, category="Edit")
        r("origin_align_world", "Origin: align compass rotation with world",
          lambda c: c.on_origin_align_world(), enabled=has_active,
          category="Edit")
        r("new_molecule", "New empty molecule (draw from scratch)",
          lambda c: c.on_new_molecule_op(), category="File",
          shortcut="Ctrl+N")
        r("drop_floor", "Drop selection to the floor (z = 0)",
          lambda c: c.on_drop_to_floor(), enabled=sel, category="Transform",
          shortcut="End")
        r("move_to_origin", "Move selection to the world origin",
          lambda c: c.on_move_to_origin(), enabled=sel, category="Transform",
          shortcut="Home (Pos1)")
        r("apply_location", "Apply location (origin becomes 0,0,0)",
          lambda c: c.on_apply_transform(loc=True), enabled=has_active,
          category="Transform")
        r("apply_rotation", "Apply rotation (local frame becomes the world's)",
          lambda c: c.on_apply_transform(rot=True), enabled=has_active,
          category="Transform")
        r("apply_all", "Apply all transforms (location + rotation)",
          lambda c: c.on_apply_transform(loc=True, rot=True),
          enabled=has_active, category="Transform")
        r("local_view", "Local view: isolate selection",
          lambda c: c.on_local_view(), enabled=has_obj, category="View",
          shortcut="/")
        for plane in ("xy", "xz", "yz"):
            r("align_planar_" + plane,
              "Align largest planar part to {} plane".format(plane.upper()),
              lambda c, pl=plane: c.on_align_planar(pl), enabled=has_active,
              category="Edit")
        for axis, name in ((0, "X"), (1, "Y"), (2, "Z")):
            r("align_axis_" + name.lower(),
              "Align 2 selected atoms to the {} axis".format(name),
              lambda c, a=axis: c.on_align_axis(a), enabled=two_same,
              category="Edit")
        r("flip_alignment", "Flip last axis alignment (reverse direction)",
          lambda c: c.on_flip_alignment(),
          enabled=lambda c: c._last_axis_align is not None, category="Edit")
        r("align_smart", "Align (selection-aware)",
          lambda c: c.on_align_smart(), enabled=sel, category="Edit",
          shortcut="A: 1 atom = to origin, 2 (one mol) = axis key, "
                   "2 (two mols) = dock at 3 A, 3+ = plane key")
        r("add_atom", "Add atom...", lambda c: c.on_add_atom(),
          category="Edit", shortcut="Shift+A")
        r("delete_selected", "Delete selected atoms",
          lambda c: c.on_delete_selected(), enabled=sel, category="Edit",
          shortcut="Del")
        r("change_element", "Change element of selection...",
          lambda c: c.on_change_element(), enabled=sel, category="Edit",
          shortcut="F3 / menu (E is the draw tool)")
        r("cycle_bond", "Cycle bond between 2 selected (none-1-2-3)",
          lambda c: c.on_cycle_bond(), enabled=two_same, category="Edit",
          shortcut="B")
        r("remove_bond", "Remove bond between 2 selected",
          lambda c: c.on_remove_bond(), enabled=two_same, category="Edit",
          shortcut="Shift+B")

        r("fit", "Fit view to scene", lambda c: c.viewport.fit_view(),
          enabled=has_obj, category="View", shortcut="F")
        r("toggle_projection", "Toggle perspective / orthographic",
          lambda c: c.viewport.toggle_projection(), category="View",
          shortcut="Shift+O")
        for axis, name in ((0, "X"), (1, "Y"), (2, "Z")):
            r("view_pos_" + name.lower(), "View along +{}".format(name),
              lambda c, a=axis: c.viewport.align_view_axis(a, 1),
              category="View")
            r("view_neg_" + name.lower(), "View along -{}".format(name),
              lambda c, a=axis: c.viewport.align_view_axis(a, -1),
              category="View")
        r("toggle_grid", "Toggle floor grid",
          lambda c: c.viewport.toggle_grid(), category="View")
        r("toggle_outliner", "Toggle outliner panel",
          lambda c: c.on_toggle_outliner(), category="View", shortcut="M")
        r("toggle_transform", "Toggle transform panel",
          lambda c: c.on_toggle_transform(), category="View", shortcut="N")
        r("labels_element", "Toggle atom element labels",
          lambda c: c._label_actions["element"].trigger(), category="View")
        r("labels_index", "Toggle atom index labels",
          lambda c: c._label_actions["index"].trigger(), category="View")
        r("toggle_background", "Toggle background (Blender grey / white)",
          lambda c: c.viewport.toggle_background(), category="View",
          shortcut="Ctrl+B")
        for st in style_mod.STYLES:
            r("style_" + st.key, "Display style: " + st.label,
              lambda c, s=st: c._set_style(s), category="View")
        r("reperceive", "Re-perceive bonds from geometry (active molecule)",
          lambda c: c.on_reperceive_bonds(), enabled=has_active,
          category="Molecule", shortcut="Ctrl+P",
          aliases=("recalculate bonds", "recompute bonds", "redetect bonds",
                   "rebuild connectivity", "reconnect"))
        r("perceive_orders", "Re-assign bond orders (active molecule)",
          lambda c: c.on_perceive_orders(), enabled=has_active,
          category="Edit")

        # No has_obj guard: Tab on an EMPTY scene starts a new molecule to
        # draw into, which is the whole point of drawing from scratch.
        r("toggle_mode", "Toggle edit / object mode",
          lambda c: c.viewport.toggle_mode(c.active_id),
          category="Edit", shortcut="Tab")
        r("set_draw_element", "Set draw element...",
          lambda c: c.on_set_draw_element(), category="Edit")
        for order, label in ((1, "single"), (2, "double"), (3, "triple")):
            r("bond_order_{}".format(order),
              "Bond order: {} (2 atoms selected)".format(label),
              lambda c, o=order: c.viewport.set_bond_order_selected(o),
              enabled=two_same, category="Edit", shortcut=str(order))
        r("adjust_h", "Adjust hydrogens on selection",
          lambda c: c.on_adjust_hydrogens(), enabled=sel, category="Edit")

        r("settings", "Settings...", lambda c: c.on_settings(),
          category="App")
        r("about", "About MoloM", lambda c: c.on_about(), category="App")

    def run_op(self, op_id):
        op = self.ops.get(op_id)
        if op is not None and op.enabled(self):
            op.run(self)

    # ------------------------------------------------------------------ menus
    def _build_menus(self):
        bar = self.menuBar()

        m_file = bar.addMenu("&File")
        self._add_op(m_file, "open", "&Open...", QKeySequence.Open)
        self._add_op(m_file, "save_project", "&Save project", "Ctrl+S")
        self._add_op(m_file, "save_project_as", "Save project &as...",
                     "Ctrl+Shift+P")
        m_file.addSeparator()
        self._add_op(m_file, "import_name", "Import by &name...",
                     "Ctrl+Shift+N")
        self._add_op(m_file, "from_smiles", "Add from &SMILES...")
        self._add_op(m_file, "paste", "&Paste XYZ / SMILES",
                     QKeySequence.Paste)
        m_file.addSeparator()
        self._add_op(m_file, "new_molecule", "New &empty molecule", "Ctrl+N")
        self._add_op(m_file, "save_as", "&Export geometry...", "Ctrl+E")
        self._add_op(m_file, "export_image", "Export &image...",
                     "Ctrl+Shift+E")
        self._add_op(m_file, "clear_scene", "&Clear scene")
        m_file.addSeparator()
        self.recent_menu = m_file.addMenu("&Recent files")
        self._rebuild_recent_menu()
        m_file.addSeparator()
        self._add(m_file, "E&xit", self.close, "Ctrl+Q")

        # ESSENTIALS ONLY. Everything else lives in F3, which searches by
        # name and alias and greys out what does not apply — a menu that
        # lists every operator is slower to use than typing two letters.
        m_edit = bar.addMenu("&Edit")
        self._add_op(m_edit, "undo", "&Undo", QKeySequence.Undo)
        self._add_op(m_edit, "redo", "&Redo", "Ctrl+Y")
        m_edit.addSeparator()
        self._add(m_edit, "Toggle edit / object mode", self.on_tab_pressed,
                  "Tab")
        m_edit.addSeparator()
        self._add_op(m_edit, "duplicate", "&Duplicate selection", "D")
        self._add_op(m_edit, "delete_selected", "&Delete selected atoms",
                     QKeySequence.Delete)
        m_edit.addSeparator()
        self._add_op(m_edit, "move_grab", "&Move selection (grab)", "G")
        self._add_op(m_edit, "rotate", "Ro&tate selection", "R")
        self._add_op(m_edit, "align_smart", "Ali&gn (selection-aware)", "A")
        m_edit.addSeparator()
        self._add(m_edit, "More operations...  (search)",
                  self.on_operator_search, "F3")

        m_sel = bar.addMenu("&Select")
        self._add_op(m_sel, "select_all", "Select &all",
                     QKeySequence.SelectAll)
        self._add(m_sel, "Clear selectio&n", self.on_deselect_all, "Alt+A")
        self._add(m_sel, "Clear selection / cancel mode", self.on_escape,
                  "Escape")
        self._add_op(m_sel, "select_linked", "Select &linked (whole mol)",
                     "Ctrl+L")
        m_sel.addSeparator()
        self._add_op(m_sel, "lasso_select", "La&sso select tool",
                     "Shift+Space,L")

        m_view = bar.addMenu("&View")
        group = QActionGroup(self)
        group.setExclusive(True)
        self._style_actions = {}
        for st in style_mod.STYLES:
            act = QAction(st.label, self, checkable=True)
            act.triggered.connect(lambda _c=False, s=st: self._set_style(s))
            group.addAction(act)
            m_view.addAction(act)
            self._style_actions[st.key] = act
        self._style_actions[style_mod.BALL_AND_STICK.key].setChecked(True)
        m_view.addSeparator()
        self._add_op(m_view, "fit", "&Fit view", "F")
        self._add_op(m_view, "toggle_projection",
                     "Perspective / &Orthographic", "Shift+O")
        along = m_view.addMenu("View a&long")
        for axis, name in ((0, "X"), (1, "Y"), (2, "Z")):
            self._add_op(along, "view_pos_" + name.lower(), "+" + name)
            self._add_op(along, "view_neg_" + name.lower(), "-" + name)
        m_view.addSeparator()
        self._label_actions = {}
        for key, text in (("element", "Atom labels: &element"),
                          ("index", "Atom labels: &index")):
            act = QAction(text, self, checkable=True)
            act.toggled.connect(
                lambda on, k=key: self.viewport.set_labels(**{k: on}))
            m_view.addAction(act)
            self._label_actions[key] = act
        m_view.addSeparator()
        self._add_op(m_view, "local_view", "&Local view (isolate)", "/")
        self._add_op(m_view, "toggle_outliner", "Properties / out&liner", "M")
        self._add_op(m_view, "toggle_transform", "Tra&nsform panel", "N")
        self._add_op(m_view, "optimize_panel", "Force field panel", "Ctrl+R")

        m_app = bar.addMenu("&App")
        self._add(m_app, "Search operation...", self.on_operator_search, "F3")
        self._add_op(m_app, "settings", "&Settings...")
        self._add_op(m_app, "about", "&About MoloM")

    def _add(self, menu, text, slot, shortcut=None):
        act = QAction(text, self)
        if shortcut is not None:
            act.setShortcut(QKeySequence(shortcut))
        act.triggered.connect(slot)
        menu.addAction(act)
        return act

    def _add_op(self, menu, op_id, text, shortcut=None):
        return self._add(menu, text, lambda: self.run_op(op_id), shortcut)

    # ------------------------------------------------------------- status bar
    def _build_statusbar(self):
        self._measure_label = QLabel("")
        self._counts_label = QLabel("")
        self.statusBar().addWidget(self._measure_label, 1)
        self.statusBar().addPermanentWidget(self._counts_label)

    def _update_counts(self):
        n_atoms = sum(o.structure.n_atoms for o in self.scene.objects)
        n_bonds = sum(len(o.structure.bonds) for o in self.scene.objects)
        txt = "{} | {} mol{}, {} atoms, {} bonds".format(
            "EDIT" if self.viewport.mode == MODE_EDIT else "OBJECT",
            self.scene.n_objects, "s" if self.scene.n_objects != 1 else "",
            n_atoms, n_bonds)
        obj = self._active_obj()
        if obj is not None and obj.structure.n_frames > 1:
            txt += " | {}: frame {}/{}".format(
                obj.name, obj.structure.current_frame + 1,
                obj.structure.n_frames)
        self._counts_label.setText(txt)

    def _on_selection_changed(self, selection):
        picks = []
        for p in selection:
            c = self.scene.pick_coords(tuple(p))
            if c is not None:
                picks.append((self.scene.pick_label(tuple(p)), c))
        self._measure_label.setText(measure.describe_picks(picks))
        # Picking in the viewport makes that molecule ACTIVE — otherwise Tab
        # would edit whatever the outliner happened to be pointing at.
        if selection:
            obj_id = selection[-1][0]
            if obj_id != self.active_id:
                self.active_id = obj_id
                self.outliner.highlight(obj_id)
                self._sync_traj_bar()
                self._sync_transform_panel()

    def _on_edit_committed(self):
        # A grab that a duplicate started makes "duplicate + this offset" the
        # thing Shift+R repeats — repeating only the move would slide the
        # same copy along instead of laying down new ones.
        serial = self.viewport.transform_serial
        if self._dup_grab_active:
            self._dup_grab_active = False
            lt = self.viewport.last_transform
            if lt is not None and lt.get("kind") == "move":
                self._repeat_macro = {"delta": np.array(lt["delta"])}
                self._macro_serial = serial
        elif serial != self._macro_serial:
            self._repeat_macro = None      # a plain transform superseded it
        self._update_counts()
        self._on_selection_changed(self.viewport.selection)
        self._sync_transform_panel()

    # ------------------------------------------------------------- undo/redo
    def push_undo(self):
        """Record the CURRENT state; call before any scene mutation.

        An operator that already snapshotted and then hands off to a modal
        (D duplicate -> grab) sets `_pending_suppress` so the pair stays ONE
        undo step, the way Blender treats "Duplicate Objects"."""
        if self._pending_suppress:
            self._pending_suppress = False
            self._last_push_suppressed = True
            return
        self._last_push_suppressed = False
        self.undo.push(self.scene.snapshot())

    def _on_model_edit_cancel(self):
        """A cancelled modal drops its own snapshot — but never the one the
        operator that started it took (Esc after D cancels the move, not the
        duplication)."""
        if self._last_push_suppressed:
            self._last_push_suppressed = False
            return
        self.undo.discard_last()

    def _restore_snapshot(self, snap):
        self.scene.restore(snap)
        # prune selection picks that no longer resolve
        keep = [p for p in self.viewport.selection
                if self.scene.resolve_pick(tuple(p)) is not None]
        self.viewport.set_selection(keep)
        self._sync_all()

    def on_undo(self):
        snap = self.undo.undo(self.scene.snapshot())
        if snap is None:
            self.statusBar().showMessage("Nothing to undo", 3000)
            return
        self._restore_snapshot(snap)
        self.statusBar().showMessage("Undo", 2000)

    def on_redo(self):
        snap = self.undo.redo(self.scene.snapshot())
        if snap is None:
            self.statusBar().showMessage("Nothing to redo", 3000)
            return
        self._restore_snapshot(snap)
        self.statusBar().showMessage("Redo", 2000)

    # ------------------------------------------------------ panels (M and N)
    def on_toggle_outliner(self):
        """M: the outliner is a PAGE of the properties dock now, so this
        opens the dock on that page (or closes it if already there)."""
        self.on_toggle_properties("outliner")

    def on_toggle_transform(self):
        vis = not self.transform_panel.isVisible()
        self.transform_panel.setVisible(vis)
        if vis:
            self._sync_transform_panel()
        self._position_outliner_tab()

    def on_tab_pressed(self):
        """Tab toggles the mode — UNLESS a panel field has focus, where it
        should walk to the next field like any form."""
        focus = QApplication.focusWidget()
        panel = self.transform_panel.widget()
        if focus is not None and panel is not None \
                and panel.isAncestorOf(focus):
            focus.focusNextChild()
            return
        self.viewport.toggle_mode(self.active_id)

    def on_toggle_optimize(self):
        """Ctrl+R: open the properties dock on the force-field page."""
        if self.properties.isVisible() and \
                self.properties.stack.currentIndex() == 1:
            self.properties.setVisible(False)
        else:
            self.properties.setVisible(True)
            self.properties.show_page("forcefield")
        self._position_outliner_tab()

    def on_toggle_properties(self, page="modifiers"):
        if self.properties.isVisible() and \
                self.properties.buttons[page][1] == \
                self.properties.stack.currentIndex():
            self.properties.setVisible(False)
        else:
            self.properties.setVisible(True)
            self.properties.show_page(page)
            self._sync_modifier_page()
        self._position_outliner_tab()

    # ------------------------------------------------------------ modifiers
    def _sync_modifier_page(self):
        if self.properties.isVisible():
            self.modifier_page.sync(self._active_obj())

    def _on_modifiers_changed(self):
        self.viewport.refresh_geometry()
        self._update_counts()

    def on_add_modifier(self, kind):
        obj = self._active_obj()
        if obj is None:
            self.statusBar().showMessage("Select a molecule first", 4000)
            return
        if kind != "array":
            return
        self.push_undo()
        # default offset along +X, just past the molecule, so the very first
        # click already shows a sensible row instead of a pile-up
        span = obj.structure.bounding_radius() * 2.0 + 1.0
        obj.modifiers.append(modifiers_mod.ArrayModifier(
            count=3, offset=(round(span, 2), 0.0, 0.0)))
        self._sync_modifier_page()
        self.viewport.refresh_geometry()
        self._update_counts()
        self.statusBar().showMessage(
            "Array modifier added to {} — non-destructive; Apply bakes it"
            .format(obj.name), 7000)

    def on_remove_modifier(self, index):
        obj = self._active_obj()
        if obj is None or not (0 <= index < len(obj.modifiers)):
            return
        self.push_undo()
        obj.modifiers.pop(index)
        self._sync_modifier_page()
        self.viewport.refresh_geometry()
        self._update_counts()

    def on_apply_modifiers(self):
        obj = self._active_obj()
        if obj is None or not obj.modifiers:
            return
        self.push_undo()
        before = obj.structure.n_atoms
        after = obj.apply_modifiers()
        self._sync_modifier_page()
        self.viewport.refresh_geometry()
        self._on_edit_committed()
        self.statusBar().showMessage(
            "Applied modifiers to {}: {} -> {} real atoms".format(
                obj.name, before, after), 8000)

    def _make_edge_tab(self, parent, tip, slot):
        btn = QToolButton(parent)
        btn.setToolTip(tip)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(
            "QToolButton { background: rgba(30,30,30,110); color:"
            " rgba(225,225,225,190); border: none; border-radius: 3px;"
            " font-size: 9px; }"
            "QToolButton:hover { background: rgba(60,60,60,190); color: #fff; }")
        btn.clicked.connect(slot)
        btn.raise_()
        return btn

    def _position_outliner_tab(self):
        """Each tab hugs the edge its dock docks to: the outliner's on the
        right (vertical strip), the transform and optimize ones on the
        bottom. The docks resize the central widget, so the compass — drawn
        inside the viewport — shifts with them automatically."""
        c = self.centralWidget()
        if c is None:
            return
        w, h = c.width(), c.height()
        # RIGHT edge: the docks that live there (outliner, optimize),
        # stacked. BOTTOM edge: the transform panel. Each tab belongs to the
        # edge its own dock docks to.
        self._outliner_tab.setFixedSize(12, 60)
        self._outliner_tab.setText(
            "▶" if self.properties.isVisible() else "◀")
        self._outliner_tab.move(w - 12, (h - 60) // 2)
        self._optimize_tab.setVisible(False)   # one dock, one tab now
        self._transform_tab.setFixedSize(44, 12)
        self._transform_tab.setText(
            "▼" if self.transform_panel.isVisible() else "▲")
        self._transform_tab.move((w - 44) // 2, h - 12)
        for btn in (self._outliner_tab, self._transform_tab,
                    self._optimize_tab):
            btn.raise_()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._position_outliner_tab()

    def eventFilter(self, obj, ev):
        if obj is self.centralWidget() and ev.type() == QEvent.Resize:
            self._position_outliner_tab()
        return super().eventFilter(obj, ev)

    def _sync_transform_panel(self):
        if not self.transform_panel.isVisible():
            return
        origin_mode = (self.viewport.mode == MODE_EDIT
                       and self.viewport._origin_active)
        obj = (self.viewport.edit_object() if origin_mode
               else self._active_obj())
        if obj is None:
            self.transform_panel.sync(None, None)
            return
        eul = rotations.mat3_to_euler_xyz(quat_to_mat3(obj.orientation))
        self.transform_panel.sync(obj, tuple(np.degrees(eul)),
                                  origin_mode=origin_mode)

    def _panel_undo_gate(self, final):
        """Scrubs push undo via drag_started; typed commits arrive with only
        a `final` event, so push just-in-time for those."""
        if final and not self._panel_drag_active:
            self.push_undo()
        if final:
            self._panel_drag_active = False

    def _on_panel_drag_started(self):
        self._panel_drag_active = True
        self.push_undo()

    def _on_panel_location(self, axis, value, final):
        obj = self._active_obj()
        if obj is None or self.transform_panel.obj_id != obj.id:
            return
        self._panel_undo_gate(final)
        d = float(value) - float(obj.origin[axis])
        if d == 0.0:
            return
        dv = np.zeros(3)
        dv[axis] = d
        if self.transform_panel.origin_mode:
            obj.origin = obj.origin + dv       # move the ORIGIN only
            self.viewport.update()
        else:
            for k in range(obj.structure.n_frames):
                obj.structure.frames[k] = obj.structure.frames[k] + dv
            obj.origin = obj.origin + dv
            self.viewport.refresh_geometry()
        if final:
            self._on_edit_committed()

    def _on_panel_rotation(self, axis, value_deg, final):
        obj = self._active_obj()
        if obj is None or self.transform_panel.obj_id != obj.id:
            return
        self._panel_undo_gate(final)
        r_old = quat_to_mat3(obj.orientation)
        eul = list(rotations.mat3_to_euler_xyz(r_old))
        eul[axis] = np.radians(float(value_deg))
        r_new = rotations.euler_xyz_to_mat3(*eul)
        r_delta = r_new @ r_old.T
        if self.transform_panel.origin_mode:
            obj.orientation = quat_from_mat3(r_new)   # turn the FRAME only
            self.viewport.update()
        else:
            for k in range(obj.structure.n_frames):
                obj.structure.frames[k] = rotations.rotate_points_about(
                    obj.structure.frames[k], r_delta, obj.origin)
            obj.orientation = quat_from_mat3(r_new)
            self.viewport.refresh_geometry()
        if final:
            self._on_edit_committed()

    # --------------------------------------------------- origin & alignment
    def on_origin_edit(self):
        """O in edit mode: snap the origin to the selection and pick the
        handle up (the orange dot can also just be clicked)."""
        if self.viewport.mode != MODE_EDIT:
            self.statusBar().showMessage(
                "Origins are edited in edit mode — press Tab first", 5000)
            return
        self.viewport.snap_origin_to_selection()

    def on_duplicate(self):
        """D: copy the selection into new outliner objects and start moving
        them straight away. A partial copy gets fresh bond perception and
        hydrogens, since it was cut out of a bigger molecule."""
        sel = self.viewport.selection
        if not sel:
            self.statusBar().showMessage("Nothing selected to duplicate", 4000)
            return
        self.push_undo()
        new_sel = []
        partial = 0
        for obj_id in sorted({p[0] for p in sel}):
            src = self.scene.get(obj_id)
            if src is None:
                continue
            rows = sorted({i for o, i in sel if o == obj_id})
            whole = len(rows) == src.structure.n_atoms
            dup = self.scene.duplicate(obj_id, None if whole else rows)
            if dup is None:
                continue
            if not whole:
                partial += 1
                bonding.perceive_structure_bonds(dup.structure)
                bonding.perceive_structure_bond_orders(dup.structure)
                if self.viewport.adjust_h:
                    edits.adjust_hydrogens(
                        dup.structure, list(range(dup.structure.n_atoms)))
            self.active_id = dup.id
            new_sel += [(dup.id, i) for i in range(dup.structure.n_atoms)]
        if not new_sel:
            self.undo.discard_last()
            return
        self.outliner.sync(self.scene, self.active_id)
        self.viewport.set_selection(new_sel)
        self._update_counts()
        self.statusBar().showMessage(
            "Duplicated — move it into place (X/Y/Z lock, type a distance, "
            "click to confirm){}".format(
                "; partial copy re-perceived + H-filled" if partial else ""),
            8000)
        # the grab that follows shares this operator's undo step, and its
        # committed delta turns the pair into a repeatable macro (Shift+R)
        self._pending_suppress = True
        self._dup_grab_active = True
        self.viewport.start_grab()

    def on_repeat_last(self):
        """Shift+R. Repeats the last ACTION, not just its transform: after
        D + move that means duplicate again and offset by the same vector
        (Blender's Repeat Last on Duplicate Objects)."""
        macro = self._repeat_macro
        if macro is None:
            self.viewport.repeat_last_transform()
            return
        sel = self.viewport.selection
        if not sel:
            self.statusBar().showMessage("Nothing selected to repeat on", 4000)
            return
        self.push_undo()
        d = macro["delta"]
        new_sel = []
        for obj_id in sorted({p[0] for p in sel}):
            src = self.scene.get(obj_id)
            if src is None:
                continue
            rows = sorted({i for o, i in sel if o == obj_id})
            whole = len(rows) == src.structure.n_atoms
            dup = self.scene.duplicate(obj_id, None if whole else rows)
            if dup is None:
                continue
            if not whole:
                bonding.perceive_structure_bonds(dup.structure)
                bonding.perceive_structure_bond_orders(dup.structure)
                if self.viewport.adjust_h:
                    edits.adjust_hydrogens(
                        dup.structure, list(range(dup.structure.n_atoms)))
            self._translate_object(dup, d)
            self.active_id = dup.id
            new_sel += [(dup.id, i) for i in range(dup.structure.n_atoms)]
        if not new_sel:
            self.undo.discard_last()
            return
        self.outliner.sync(self.scene, self.active_id)
        self.viewport.set_selection(new_sel)
        self._on_edit_committed()
        self.statusBar().showMessage(
            "Repeated: duplicated and offset by ({:+.3f}, {:+.3f}, {:+.3f}) A"
            .format(*d), 6000)

    def on_optimize(self, task, method, steps):
        """Run the force field on the active molecule. With the 'selection'
        task the UNSELECTED atoms are frozen, which is how you relax a newly
        drawn fragment without disturbing the rest of the structure."""
        obj = self._active_obj()
        if obj is None or obj.structure.n_atoms < 2:
            self.optimize_panel.set_running(
                False, "Nothing to optimize — pick a molecule first.")
            return
        if self._opt_worker is not None:
            return
        s = obj.structure
        fixed = []
        if task == TASK_SELECTION:
            chosen = {i for o, i in self.viewport.selection if o == obj.id}
            if not chosen:
                self.optimize_panel.set_running(
                    False, "Select the atoms to relax first.")
                return
            fixed = [i for i in range(s.n_atoms) if i not in chosen]
        self.optimize_panel.set_running(
            True, "Running {} on {}...".format(method, obj.name))
        self._opt_target = obj.id
        self._opt_worker = OptimizeWorker(list(s.symbols), s.coords.copy(),
                                          list(s.bonds), method, steps,
                                          fixed, self)
        self._opt_worker.done.connect(self._optimize_done)
        self._opt_worker.finished.connect(self._opt_worker.deleteLater)
        self._opt_worker.start()

    def _optimize_done(self, coords, info):
        self._opt_worker = None
        obj = self.scene.get(self._opt_target)
        if coords is None:
            self.optimize_panel.set_running(False, "Failed: {}".format(info))
            self.statusBar().showMessage("Optimization failed", 6000)
            return
        if obj is None:
            self.optimize_panel.set_running(False, "Molecule went away.")
            return
        self.push_undo()
        obj.structure.coords = np.asarray(coords, dtype=float)
        self.viewport.refresh_geometry()
        self._on_edit_committed()
        note = "{} ({}) E = {:.2f}".format(
            info.get("method", "?"), info.get("engine", "?"),
            info.get("energy", float("nan")))
        if not info.get("converged", True):
            note += " — step limit reached, run again to continue"
        for extra in info.get("notes", []):
            note += "\n" + extra
        self.optimize_panel.set_running(False, note)
        self.statusBar().showMessage(
            "Optimized {}: {}".format(obj.name, note.splitlines()[0]), 8000)

    def on_shuttle(self):
        obj = self._active_obj()
        if obj is None:
            return
        self.viewport.start_shuttle(obj.id)

    def on_origin_snap(self):
        obj = self._active_obj()
        if obj is None:
            return
        pts = [self.scene.pick_coords(p) for p in self.viewport.selection
               if p[0] == obj.id]
        pts = [p for p in pts if p is not None]
        if not pts:
            self.statusBar().showMessage(
                "Select atoms of {} first".format(obj.name), 4000)
            return
        self.push_undo()
        obj.origin = np.mean(pts, axis=0)
        self.viewport.update()
        self._on_edit_committed()
        self.statusBar().showMessage(
            "Origin of {} snapped to the selection centroid".format(obj.name),
            5000)

    def on_origin_align_world(self):
        """Reset the object's local frame so its compass matches the world
        axes (the double-press local locks then behave like global ones)."""
        obj = self._active_obj()
        if obj is None:
            return
        self.push_undo()
        obj.orientation = np.array([1.0, 0.0, 0.0, 0.0])
        self.viewport.update()
        self._on_edit_committed()
        self.statusBar().showMessage(
            "Origin compass of {} aligned with the world axes".format(
                obj.name), 5000)

    def new_empty_molecule(self):
        # type: () -> Optional[int]
        """Create an empty molecule and make it active (Tab on an empty
        scene lands here, so a structure can be drawn from nothing)."""
        self.push_undo()
        obj = self.scene.add(Structure(name="molecule"))
        self.active_id = obj.id
        self.outliner.sync(self.scene, self.active_id)
        self.viewport.set_selection([])
        self._update_counts()
        self.statusBar().showMessage(
            "New empty molecule — click in the viewport to draw atoms", 6000)
        return obj.id

    def on_outliner_add(self):
        """The outliner's '+ New molecule' row: create it, then drop the name
        straight into edit so it is obvious a new object just appeared and
        can be named. Tab then draws into it."""
        obj_id = self.new_empty_molecule()
        if obj_id is None:
            return
        self.outliner.start_rename(obj_id)
        self.statusBar().showMessage(
            "New molecule — name it, then press Tab to draw into it", 8000)

    def on_new_molecule_op(self):
        obj_id = self.new_empty_molecule()
        if obj_id is not None:
            self.viewport.set_mode(MODE_EDIT, obj_id)

    def on_export_image(self):
        start = self.settings.value("last_dir", "")
        base = (os.path.splitext(os.path.basename(self.project_path))[0]
                if self.project_path else "molom")
        path, _f = QFileDialog.getSaveFileName(
            self, "Export image", os.path.join(start, base + ".png"),
            "PNG image (*.png);;JPEG image (*.jpg);;All files (*)")
        if not path:
            return
        try:
            img = self.viewport.render_image()
        except Exception as e:      # driver without FBO support, etc.
            self.statusBar().showMessage(
                "High-quality render failed ({}), grabbing the viewport "
                "instead".format(e), 8000)
            img = self.viewport.grabFramebuffer()
        if not img.save(path):
            QMessageBox.critical(self, "Export failed",
                                 "Could not write {}".format(path))
            return
        self.settings.setValue("last_dir", os.path.dirname(path))
        self.statusBar().showMessage(
            "Wrote {} ({}x{})".format(os.path.basename(path),
                                      img.width(), img.height()), 6000)

    def _selected_object(self):
        ids = {p[0] for p in self.viewport.selection}
        if len(ids) == 1:
            return self.scene.get(next(iter(ids)))
        return self._active_obj()

    def on_copy_smiles(self):
        obj = self._selected_object()
        if obj is None or obj.structure.n_atoms == 0:
            return
        smiles, err = io.structure_to_smiles(obj.structure.symbols,
                                             obj.structure.bonds)
        if smiles is None:
            QMessageBox.warning(self, "SMILES", "Could not derive a SMILES "
                                "from {}:\n{}".format(obj.name, err))
            return
        QApplication.clipboard().setText(smiles)
        self.statusBar().showMessage(
            "Copied SMILES of {}: {}".format(obj.name, smiles), 9000)

    def on_name_from_structure(self):
        """Derive the SMILES from the graph, then ask PubChem what it is
        called and rename the object."""
        obj = self._selected_object()
        if obj is None or obj.structure.n_atoms == 0:
            return
        smiles, err = io.structure_to_smiles(obj.structure.symbols,
                                             obj.structure.bonds)
        if smiles is None:
            QMessageBox.warning(self, "Name lookup", err or "no SMILES")
            return
        self.statusBar().showMessage(
            "Looking {} up on PubChem...".format(smiles), 4000)
        QApplication.processEvents()
        name = resolve_mod.name_for_smiles(smiles)
        if not name:
            self.statusBar().showMessage(
                "PubChem has no name for {}".format(smiles), 7000)
            return
        self.push_undo()
        final = self.scene.rename(obj.id, name)
        self.outliner.sync(self.scene, self.active_id)
        self._on_selection_changed(self.viewport.selection)
        self.statusBar().showMessage(
            "Renamed to {} (from {})".format(final, smiles), 8000)

    def on_merge(self):
        ids = sorted({p[0] for p in self.viewport.selection})
        if len(ids) < 2:
            ids = self.outliner.selected_object_ids()
        self.on_merge_ids(ids)

    def on_merge_ids(self, ids):
        """Combine molecules into one object — the prerequisite for force-
        field optimising an H-bonded pair as a single system."""
        ids = [i for i in ids if self.scene.get(i) is not None]
        if len(ids) < 2:
            self.statusBar().showMessage(
                "Select atoms of at least two molecules to merge", 5000)
            return
        names = [self.scene.get(i).name for i in ids if self.scene.get(i)]
        box = QMessageBox(self)
        box.setWindowTitle("Merge molecules")
        box.setText("Merge {} into one molecule?".format(", ".join(names)))
        keep = QCheckBox("Keep the original molecules")
        keep.setChecked(True)
        box.setCheckBox(keep)
        box.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        if box.exec() != QMessageBox.Ok:
            return
        self.push_undo()
        merged = self.scene.merge(ids, keep_originals=keep.isChecked())
        if merged is None:
            self.undo.discard_last()
            return
        if keep.isChecked():
            for i in ids:                  # hide the parts, show the whole
                o = self.scene.get(i)
                if o is not None:
                    o.visible = False
        self.active_id = merged.id
        self.viewport.select_whole_molecules([merged.id])
        self._sync_all()
        self.statusBar().showMessage(
            "Merged into {} ({} atoms){}".format(
                merged.name, merged.structure.n_atoms,
                "; originals kept but hidden" if keep.isChecked() else ""),
            9000)

    def on_move_to_origin(self):
        """Home/Pos1: slide the selected molecules so the selection centroid
        lands on (0, 0, 0). Whole molecules move — never single atoms."""
        sel = self.viewport.selection
        pts = [self.scene.pick_coords(p) for p in sel]
        pts = [p for p in pts if p is not None]
        if not pts:
            self.statusBar().showMessage("Nothing selected to centre", 4000)
            return
        d = -np.mean(pts, axis=0)
        if float(np.linalg.norm(d)) < 1e-12:
            self.statusBar().showMessage("Already at the origin", 3000)
            return
        self.push_undo()
        for obj_id in sorted({p[0] for p in sel}):
            obj = self.scene.get(obj_id)
            if obj is not None:
                self._translate_object(obj, d)
        self.viewport.refresh_geometry()
        self._on_edit_committed()
        self.statusBar().showMessage(
            "Moved to the origin ({:+.3f}, {:+.3f}, {:+.3f}) A".format(*d),
            5000)

    def on_apply_transform(self, loc=False, rot=False):
        """Blender's Apply Transform. Atoms are stored in world coordinates,
        so applying does not move anything — it zeroes the object's reported
        transform, making the current pose the new rest state. The origin
        gizmo simply snaps to the world origin / world axes."""
        obj = self._active_obj()
        if obj is None:
            return
        self.push_undo()
        what = []
        if loc:
            obj.origin = np.zeros(3)
            what.append("location")
        if rot:
            obj.orientation = np.array([1.0, 0.0, 0.0, 0.0])
            what.append("rotation")
        self.viewport.update()
        self._on_edit_committed()
        self.statusBar().showMessage(
            "Applied {} of {} — atoms unchanged, transform is now the rest "
            "state".format(" + ".join(what), obj.name), 7000)

    def on_drop_to_floor(self):
        """End: drop the selected molecules so the selection centroid sits on
        z = 0 (the floor grid)."""
        sel = self.viewport.selection
        pts = [self.scene.pick_coords(p) for p in sel]
        pts = [p for p in pts if p is not None]
        if not pts:
            self.statusBar().showMessage("Nothing selected to drop", 4000)
            return
        dz = -float(np.mean(pts, axis=0)[2])
        if abs(dz) < 1e-12:
            self.statusBar().showMessage("Already on the floor", 3000)
            return
        self.push_undo()
        for obj_id in sorted({p[0] for p in sel}):
            obj = self.scene.get(obj_id)
            if obj is not None:
                self._translate_object(obj, [0.0, 0.0, dz])
        self.viewport.refresh_geometry()
        self._on_edit_committed()
        self.statusBar().showMessage(
            "Dropped to z = 0 ({:+.3f} A)".format(dz), 5000)

    def on_local_view(self):
        """Isolate the selected molecules (Blender's local view) and frame
        them; pressing again restores what was visible before."""
        if self._local_view is not None:
            for obj_id, vis in self._local_view.items():
                obj = self.scene.get(obj_id)
                if obj is not None:
                    obj.visible = vis
            self._local_view = None
            self._sync_all()
            self.viewport.fit_view()
            self.statusBar().showMessage("Local view off", 4000)
            return
        ids = {p[0] for p in self.viewport.selection}
        if not ids and self.active_id is not None:
            ids = {self.active_id}
        if not ids:
            self.statusBar().showMessage(
                "Select a molecule to isolate", 4000)
            return
        self._local_view = {o.id: o.visible for o in self.scene.objects}
        for o in self.scene.objects:
            o.visible = o.id in ids
        self._sync_all()
        self.viewport.fit_view()
        self.statusBar().showMessage(
            "Local view: {} isolated (press again to exit)".format(
                ", ".join(o.name for o in self.scene.objects if o.visible)),
            6000)

    def _rigid_rotate_object(self, obj, rot, pivot):
        for k in range(obj.structure.n_frames):
            obj.structure.frames[k] = rotations.rotate_points_about(
                obj.structure.frames[k], rot, pivot)
        obj.origin = rotations.rotate_points_about(
            obj.origin[None, :], rot, pivot)[0]
        obj.orientation = quat_from_mat3(rot @ quat_to_mat3(obj.orientation))

    def on_align_axis(self, axis):
        sel = self._two_same_object()
        if sel is None:
            return
        obj = self.scene.get(sel[0][0])
        c = obj.structure.coords
        v = c[sel[1][1]] - c[sel[0][1]]
        if np.linalg.norm(v) < 1e-6:
            self.statusBar().showMessage("The two atoms coincide", 4000)
            return
        self.push_undo()
        target = np.zeros(3)
        target[axis] = 1.0
        rot = align_mod.align_vector_to_axis(v, target)
        pivot = (c[sel[0][1]] + c[sel[1][1]]) / 2.0
        self._rigid_rotate_object(obj, rot, pivot)
        self._last_axis_align = {"obj_id": obj.id, "axis": target,
                                 "pivot": pivot.copy()}
        self.viewport.refresh_geometry()
        self._on_edit_committed()
        self.statusBar().showMessage(
            "Aligned {}-{} of {} to the {} axis (Flip reverses it)".format(
                self.scene.pick_label(tuple(sel[0])),
                self.scene.pick_label(tuple(sel[1])),
                obj.name, "XYZ"[axis]), 6000)

    def on_flip_alignment(self):
        la = self._last_axis_align
        if la is None:
            return
        obj = self.scene.get(la["obj_id"])
        if obj is None:
            self._last_axis_align = None
            return
        self.push_undo()
        rot = align_mod.flip_about_axis(la["axis"])
        self._rigid_rotate_object(obj, rot, la["pivot"])
        self.viewport.refresh_geometry()
        self._on_edit_committed()
        self.statusBar().showMessage(
            "Flipped {} about its aligned axis".format(obj.name), 4000)

    def _translate_object(self, obj, dv):
        dv = np.asarray(dv, dtype=float)
        for k in range(obj.structure.n_frames):
            obj.structure.frames[k] = obj.structure.frames[k] + dv
        obj.origin = obj.origin + dv

    def on_align_smart(self):
        """A — selection-aware align (whole molecules only, never lone
        atoms): 1 atom -> molecule jumps so that atom sits at the world
        origin; 2 atoms on TWO molecules -> dock the first-picked molecule
        toward the second atom, stopping 3 A short; 2 atoms on one molecule
        -> wait for an axis key; 3+ atoms on one molecule -> wait for a
        plane key."""
        sel = self.viewport.selection
        if not sel:
            self.statusBar().showMessage("Nothing selected to align (A)",
                                         4000)
            return
        obj_ids = [p[0] for p in sel]
        unique = sorted(set(obj_ids))
        if len(sel) == 1:
            obj = self.scene.get(sel[0][0])
            if obj is None:
                return
            self.push_undo()
            self._translate_object(obj, -obj.structure.coords[sel[0][1]])
            self.viewport.refresh_geometry()
            self._on_edit_committed()
            self.statusBar().showMessage(
                "Moved {} so {} sits at the world origin".format(
                    obj.name, self.scene.pick_label(tuple(sel[0]))), 5000)
            return
        if len(sel) == 2 and len(unique) == 2:
            (o1, a1), (o2, a2) = sel        # click order: first mol moves
            obj1, obj2 = self.scene.get(o1), self.scene.get(o2)
            if obj1 is None or obj2 is None:
                return
            p1 = obj1.structure.coords[a1]
            p2 = obj2.structure.coords[a2]
            d = p2 - p1
            dist = float(np.linalg.norm(d))
            if dist < 1e-6:
                self.statusBar().showMessage("Atoms already coincide", 4000)
                return
            self.push_undo()
            self._translate_object(obj1, d - d / dist * 3.0)
            self.viewport.refresh_geometry()
            self._on_edit_committed()
            self.statusBar().showMessage(
                "Docked {} toward {} — the picked atoms now sit 3.0 A "
                "apart".format(obj1.name, obj2.name), 6000)
            return
        if len(unique) > 1:
            self.statusBar().showMessage(
                "Align needs atoms of ONE molecule (or exactly 2 atoms on "
                "2 molecules)", 5000)
            return
        self.viewport.arm_align_keys("axis" if len(sel) == 2 else "plane")

    def _on_align_key(self, kind, axis):
        """Axis key arrived from the viewport's align-wait state."""
        if kind == "axis":
            self.on_align_axis(axis)
            return
        sel = self.viewport.selection
        obj = self.scene.get(sel[0][0]) if sel else None
        if obj is None or len(sel) < 3:
            return
        pts = np.array([obj.structure.coords[i] for _o, i in sel])
        centroid, normal = align_mod.best_fit_plane(pts)
        target = np.zeros(3)
        target[axis] = 1.0                  # plane PERPENDICULAR to the key
        self.push_undo()
        rot = align_mod.align_vector_to_axis(normal, target)
        self._rigid_rotate_object(obj, rot, centroid)
        self.viewport.refresh_geometry()
        self._on_edit_committed()
        plane = {0: "YZ", 1: "XZ", 2: "XY"}[axis]
        self.statusBar().showMessage(
            "Aligned the {}-atom selection plane of {} to the {} plane"
            .format(len(sel), obj.name, plane), 6000)

    def on_align_planar(self, plane_key):
        obj = self._active_obj()
        if obj is None or obj.structure.n_atoms < 3:
            self.statusBar().showMessage("Need a molecule with >= 3 atoms",
                                         4000)
            return
        self.push_undo()
        target = align_mod.PLANE_NORMALS[plane_key]
        rot, pivot, mask = align_mod.align_planar_to_plane(
            obj.structure.coords, target)
        self._rigid_rotate_object(obj, rot, pivot)
        self.viewport.refresh_geometry()
        self._on_edit_committed()
        self.statusBar().showMessage(
            "Aligned {}-atom planar part of {} to the {} plane".format(
                int(mask.sum()), obj.name, plane_key.upper()), 6000)

    # ------------------------------------------------------------- scene sync
    def _active_obj(self):
        if self.active_id is not None:
            obj = self.scene.get(self.active_id)
            if obj is not None:
                return obj
        return self.scene.objects[-1] if self.scene.objects else None

    def _sync_all(self, fit=False):
        self.outliner.sync(self.scene, self.active_id)
        self.viewport.refresh_geometry()
        if fit:
            self.viewport.fit_view()
        self._sync_traj_bar()
        self._update_counts()
        self._sync_transform_panel()

    @staticmethod
    def _perceive_fresh(s):
        # type: (Structure) -> None
        """Connectivity AND bond orders, ONCE, at import. None of the import
        formats we read carry orders, so a freshly opened molecule would
        otherwise be all-single — which makes editing and any later force
        field run start from the wrong chemistry. After this, orders only
        ever change on explicit user action."""
        bonding.perceive_structure_bonds(s)
        bonding.perceive_structure_bond_orders(s)

    def _install_structure(self, s, path=None, note=None):
        # type: (Structure, Optional[str], Optional[str]) -> None
        """Add a molecule to the scene (imports never replace — outliner)."""
        self.push_undo()
        self._perceive_fresh(s)
        obj = self.scene.add(s)
        self.active_id = obj.id
        self._sync_all(fit=True)
        if path:
            self._push_recent(path)
        self.statusBar().showMessage(
            "Added {}{}".format(obj.name,
                                " ({})".format(note) if note else ""), 6000)

    # ----------------------------------------------------------- obj signals
    def _on_obj_visibility(self, obj_id, visible):
        obj = self.scene.get(obj_id)
        if obj is not None:
            obj.visible = visible
            self.viewport.refresh_geometry()

    def _on_obj_isolate(self, obj_id):
        """Shift+click the eye: toggle between 'show only this one' and
        'show everything except this one'."""
        others = [o for o in self.scene.objects if o.id != obj_id]
        target = self.scene.get(obj_id)
        if target is None:
            return
        only_this = target.visible and not any(o.visible for o in others)
        if only_this:
            target.visible = False
            for o in others:
                o.visible = True
            msg = "Showing everything except {}".format(target.name)
        else:
            target.visible = True
            for o in others:
                o.visible = False
            msg = "Showing only {}".format(target.name)
        self.outliner.sync(self.scene, self.active_id)
        self.viewport.refresh_geometry()
        self._update_counts()
        self.statusBar().showMessage(msg, 5000)

    def _on_obj_style(self, obj_id, style_key):
        obj = self.scene.get(obj_id)
        if obj is not None:
            obj.style_key = style_key or None
            self.viewport.refresh_geometry()

    def _on_obj_renamed(self, obj_id, name):
        final = self.scene.rename(obj_id, name)
        self.outliner.sync(self.scene, self.active_id)
        self._on_selection_changed(self.viewport.selection)  # labels changed
        self.statusBar().showMessage("Renamed to {}".format(final), 3000)

    def _on_obj_delete(self, obj_id):
        obj = self.scene.get(obj_id)
        if obj is None:
            return
        self.push_undo()
        self.scene.remove(obj_id)
        self.viewport.set_selection(
            [p for p in self.viewport.selection if p[0] != obj_id])
        if self.active_id == obj_id:
            self.active_id = None
        self._sync_all()
        self.statusBar().showMessage("Removed {}".format(obj.name), 4000)

    def _on_obj_activated(self, obj_id):
        """Outliner row click: make active AND select the molecule's atoms
        (Blender: clicking an object in the outliner selects it)."""
        self.active_id = obj_id
        self.viewport.select_whole_molecules([obj_id])
        self._sync_traj_bar()
        self._update_counts()
        self._sync_transform_panel()

    # -------------------------------------------------------- trajectory bar
    def _build_trajectory_bar(self):
        self.traj_bar = QWidget(self)
        lay = QHBoxLayout(self.traj_bar)
        lay.setContentsMargins(6, 2, 6, 2)
        self._play_btn = QToolButton(self.traj_bar)
        self._play_btn.setText(">")
        self._play_btn.setToolTip("Play / pause trajectory (Space)")
        self._play_btn.clicked.connect(self.on_play_pause)
        self._frame_slider = QSlider(Qt.Horizontal, self.traj_bar)
        self._frame_slider.setMinimum(0)
        self._frame_slider.valueChanged.connect(self.on_frame_slider)
        self._frame_label = QLabel("0/0", self.traj_bar)
        self._fps_spin = QSpinBox(self.traj_bar)
        self._fps_spin.setRange(1, 60)
        self._fps_spin.setValue(10)
        self._fps_spin.setSuffix(" fps")
        lay.addWidget(self._play_btn)
        lay.addWidget(self._frame_slider, 1)
        lay.addWidget(self._frame_label)
        lay.addWidget(self._fps_spin)
        self.traj_bar.setVisible(False)

    def _sync_traj_bar(self):
        obj = self._active_obj()
        s = obj.structure if obj is not None else None
        multi = s is not None and s.n_frames > 1
        if multi:
            self._frame_slider.blockSignals(True)
            self._frame_slider.setMaximum(s.n_frames - 1)
            self._frame_slider.setValue(s.current_frame)
            self._frame_slider.blockSignals(False)
            self._frame_label.setText("{}/{}".format(s.current_frame + 1,
                                                     s.n_frames))
            self.traj_bar.setVisible(True)
        else:
            self._play_timer.stop()
            self._play_btn.setText(">")
            self.traj_bar.setVisible(False)

    def on_play_pause(self):
        if self._play_timer.isActive():
            self._play_timer.stop()
            self._play_btn.setText(">")
        else:
            self._play_timer.start(int(1000 / self._fps_spin.value()))
            self._play_btn.setText("||")

    def _advance_frame(self):
        obj = self._active_obj()
        if obj is None or obj.structure.n_frames < 2:
            self._play_timer.stop()
            return
        self._play_timer.setInterval(int(1000 / self._fps_spin.value()))
        self._set_frame((obj.structure.current_frame + 1)
                        % obj.structure.n_frames)

    def on_frame_slider(self, value):
        self._set_frame(int(value))

    def _set_frame(self, i):
        obj = self._active_obj()
        if obj is None:
            return
        obj.structure.set_frame(i)
        bonding.perceive_structure_bonds(obj.structure)
        self.viewport.refresh_geometry()
        self._sync_traj_bar()
        self._update_counts()
        self._on_selection_changed(self.viewport.selection)

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Space and self.traj_bar.isVisible():
            self.on_play_pause()
        else:
            super().keyPressEvent(ev)

    # ------------------------------------------------------- SMILES batches
    def _install_smiles_batch(self, pairs, src):
        # type: (List, str) -> None
        """Build every (smiles, name) pair into its own scene object.

        SMILES geometry is GENERATED, so it may be normalised freely (unlike
        measured file imports, which are never silently transformed): each
        molecule is aligned largest-planar-part-to-XY and centred, then the
        batch is spread along +Z with 2 A of bounding-sphere clearance —
        dot-separated ChemDraw multi-copies land side by side, not on top of
        each other. One undo entry for the whole batch."""
        built, failed = [], []
        for smiles, name in pairs:
            try:
                atoms, method = io.smiles_to_xyz(smiles)
            except io.CoordGenError as e:
                failed.append((smiles, str(e)))
                continue
            meta = {"smiles": smiles, "source": method}
            charge, mult = io.smiles_charge_and_mult(smiles)
            if charge is not None:
                meta["charge"] = charge
                meta["multiplicity"] = mult
            s = Structure.from_atoms(atoms, name=name or smiles,
                                     metadata=meta)
            if s.n_atoms >= 3:
                rot, pivot, _mask = align_mod.align_planar_to_plane(
                    s.coords, [0.0, 0.0, 1.0])
                s.coords = rotations.rotate_points_about(s.coords, rot, pivot)
            s.coords = s.coords - s.centroid()
            built.append(s)
        if not built:
            QMessageBox.critical(
                self, "SMILES failed",
                "\n\n".join("{}:\n  {}".format(sm, err)
                            for sm, err in failed[:4]) or "nothing to build")
            return
        self.push_undo()
        zs = align_mod.zstack_offsets([s.bounding_radius() for s in built])
        for s, z in zip(built, zs):
            s.coords = s.coords + np.array([0.0, 0.0, z])
            self._perceive_fresh(s)
            obj = self.scene.add(s)
            self.active_id = obj.id
        self._sync_all(fit=True)
        msg = "Added {} molecule{} ({})".format(
            len(built), "s" if len(built) != 1 else "", src)
        if len(built) > 1:
            msg += ", stacked along Z"
        if failed:
            msg += "; {} failed: {}".format(
                len(failed), ", ".join(sm for sm, _e in failed[:3]))
        self.statusBar().showMessage(msg, 8000)

    # ------------------------------------------------------------ savepoints
    def _update_title(self):
        bits = ["MoloM"]
        if self.project_path:
            bits.append(os.path.basename(self.project_path))
        if self.viewport.mode == MODE_EDIT:
            obj = self.viewport.edit_object()
            bits.append("EDIT: {}".format(obj.name if obj else "?"))
        self.setWindowTitle("  —  ".join(bits))

    def _view_state(self):
        cam = self.viewport.camera
        return {"center": [float(v) for v in cam.center],
                "distance": float(cam.distance),
                "rotation": [float(v) for v in cam.rotation],
                "orthographic": bool(cam.orthographic)}

    def _ui_state(self):
        return {"style": self.viewport.style.key,
                "labels_element": self.viewport.show_labels_element,
                "labels_index": self.viewport.show_labels_index,
                "grid": self.viewport.show_grid,
                "draw_element": self.viewport.draw_element,
                "active_id": self.active_id}

    def on_save_project(self):
        if not self.project_path:
            return self.on_save_project_as()
        try:
            project.save_project(self.project_path, self.scene,
                                 view=self._view_state(), ui=self._ui_state())
        except project.ProjectError as e:
            QMessageBox.critical(self, "Save failed", str(e))
            return
        self.statusBar().showMessage(
            "Saved {}".format(os.path.basename(self.project_path)), 5000)

    def on_save_project_as(self):
        start = self.settings.value("last_dir", "")
        suggested = os.path.join(
            start, os.path.basename(self.project_path) if self.project_path
            else "scene" + project.EXTENSION)
        path, _f = QFileDialog.getSaveFileName(
            self, "Save MoloM project", suggested,
            project.FILE_FILTER + ";;All files (*)")
        if not path:
            return
        try:
            path = project.save_project(path, self.scene,
                                        view=self._view_state(),
                                        ui=self._ui_state())
        except project.ProjectError as e:
            QMessageBox.critical(self, "Save failed", str(e))
            return
        self.project_path = path
        self.settings.setValue("last_dir", os.path.dirname(path))
        self._push_recent(path)
        self._update_title()
        self.statusBar().showMessage(
            "Saved {}".format(os.path.basename(path)), 5000)

    def open_project(self, path):
        # type: (str) -> None
        try:
            payload = project.load_project(path)
        except project.ProjectError as e:
            QMessageBox.critical(self, "Could not open project", str(e))
            return
        self.push_undo()
        self.viewport.set_mode(MODE_OBJECT)
        self.viewport.set_selection([])
        self.scene.from_dict(payload["scene"])
        ui = payload.get("ui") or {}
        st = style_mod.STYLE_BY_KEY.get(ui.get("style", ""))
        if st is not None:
            self._set_style(st)
        self.viewport.set_labels(element=bool(ui.get("labels_element")),
                                 index=bool(ui.get("labels_index")))
        self.viewport.show_grid = bool(ui.get("grid", True))
        if ui.get("draw_element"):
            self.viewport.draw_element = ui["draw_element"]
        for key, act in self._label_actions.items():
            act.blockSignals(True)
            act.setChecked(bool(ui.get("labels_" + key)))
            act.blockSignals(False)
        self.active_id = ui.get("active_id")
        view = payload.get("view") or {}
        cam = self.viewport.camera
        if "center" in view:
            cam.center = np.asarray(view["center"], dtype=float)
            cam.distance = float(view.get("distance", cam.distance))
            cam.rotation = np.asarray(view["rotation"], dtype=float)
            cam.orthographic = bool(view.get("orthographic", False))
            cam.auto_ortho = False
        self.project_path = path
        self._push_recent(path)
        self._sync_all(fit="center" not in view)
        self._update_title()
        self.statusBar().showMessage(
            "Opened project {} ({} molecules, saved {})".format(
                os.path.basename(path), self.scene.n_objects,
                payload.get("saved", "?")), 8000)

    # ---------------------------------------------------------------- opening
    def open_path(self, path):
        # type: (str) -> None
        if project.is_project_file(path):
            self.open_project(path)
            return
        try:
            if io.is_smiles_list_file(path):
                pairs = io.read_smiles_file(path)
                self._install_smiles_batch(pairs, "SMILES file")
                self._push_recent(path)
                return
            structs = io.read_structures(path)
            base = os.path.splitext(os.path.basename(path))[0]
            if len(structs) > 1 and io.frames_are_trajectory(structs):
                s = Structure.from_frames(structs, name=base)
                note = "{} frames".format(len(structs))
                self._install_structure(s, path=path, note=note)
            elif len(structs) > 1:
                # different species per record -> each becomes its own object
                for k, (atoms, meta) in enumerate(structs):
                    nm = (meta or {}).get("name") or "{}_{}".format(base, k)
                    self._install_structure(
                        Structure.from_atoms(atoms, name=nm,
                                             metadata=meta or {}))
                self._push_recent(path)
            else:
                atoms, meta = structs[0]
                s = Structure.from_atoms(atoms, name=base, metadata=meta or {})
                note = None
                if meta and meta.get("source") == "heuristic":
                    note = meta.get("comment", "heuristic import - VERIFY")
                self._install_structure(s, path=path, note=note)
        except (io.CoordGenError, ValueError, OSError) as e:
            QMessageBox.critical(self, "Could not open", str(e))

    def on_open(self):
        start = self.settings.value("last_dir", "")
        filters = [project.FILE_FILTER] + list(io.import_name_filters())
        path, _f = QFileDialog.getOpenFileName(
            self, "Open structure or project", start, ";;".join(filters))
        if path:
            self.settings.setValue("last_dir", os.path.dirname(path))
            self.open_path(path)

    def on_import_by_name(self):
        dlg = ResolveNameDialog(self)
        if not dlg.exec() or dlg.resolution is None:
            return
        res = dlg.resolution
        self._install_smiles_batch([(res.smiles, res.query)],
                                   res.source or "resolved by name")

    def on_from_smiles(self):
        smiles, ok = QInputDialog.getText(self, "New from SMILES",
                                          "SMILES string (dots separate "
                                          "multiple molecules):")
        if not ok or not smiles.strip():
            return
        pairs = io.parse_smiles_list(smiles.strip())
        if pairs:
            self._install_smiles_batch(pairs, "SMILES input")

    def on_paste(self):
        text = QApplication.clipboard().text()
        if not text or not text.strip():
            return
        frames = io.parse_xyz_frames_text(text)
        if frames and frames[0][0]:
            if len(frames) > 1 and io.frames_are_trajectory(frames):
                s = Structure.from_frames(frames, name="pasted")
            else:
                s = Structure.from_atoms(frames[0][0], name="pasted",
                                         metadata=frames[0][1] or {})
            self._install_structure(s, note="pasted XYZ")
            return
        # SMILES paste: parse_smiles_list splits ChemDraw's dot-separated
        # multi-structure copies into one entry per molecule.
        pairs = io.parse_smiles_list(text)
        if pairs:
            self._install_smiles_batch(pairs, "pasted SMILES")
            return
        QMessageBox.information(self, "Paste", "Clipboard text is neither an "
                                "XYZ block nor a SMILES.")

    def on_save_as(self):
        """Export geometry. The exported set is every VISIBLE molecule in the
        outliner (an arrangement is usually the thing you want in the file),
        merged into one record — not just the active one."""
        vis = [o for o in self.scene.visible_objects()
               if o.structure.n_atoms]
        if not vis:
            self.statusBar().showMessage(
                "Nothing visible to export — tick a molecule in the outliner",
                5000)
            return
        default = (vis[0].name if len(vis) == 1
                   else (os.path.splitext(os.path.basename(
                       self.project_path))[0] if self.project_path
                       else "scene"))
        start = self.settings.value("last_dir", "")
        path, _f = QFileDialog.getSaveFileName(
            self, "Export {} visible molecule(s)".format(len(vis)),
            os.path.join(start, default + ".xyz"),
            "XYZ (*.xyz);;MDL SDF (*.sdf);;MDL MOL (*.mol);;PDB (*.pdb);;"
            "Sybyl MOL2 (*.mol2);;All files (*)")
        if not path:
            return
        try:
            backend, n_obj, n_atoms = self.export_visible(path)
            self.settings.setValue("last_dir", os.path.dirname(path))
            self._push_recent(path)
            self.statusBar().showMessage(
                "Exported {} molecule(s), {} atoms to {} ({})".format(
                    n_obj, n_atoms, os.path.basename(path), backend), 7000)
        except (ValueError, OSError) as e:
            QMessageBox.critical(self, "Save failed", str(e))

    def export_visible(self, path):
        # type: (str) -> tuple
        """Write every visible molecule to `path`. Returns
        (backend, n_objects, n_atoms). Split out from the dialog so the
        export rule is testable."""
        vis = [o for o in self.scene.visible_objects() if o.structure.n_atoms]
        if not vis:
            raise ValueError("no visible molecules to export")
        name = " + ".join(o.name for o in vis)
        single = vis[0].structure
        if len(vis) == 1 and single.n_frames > 1 \
                and path.lower().endswith(".xyz"):
            frames = []
            keep = single.current_frame
            for k in range(single.n_frames):
                single.set_frame(k)
                frames.append((single.atoms(), vis[0].name))
            single.set_frame(keep)
            backend = io.write_structures_file(path, frames)
        else:
            # EVALUATED geometry: an array modifier's copies are part of the
            # structure you meant to export, the same way Blender exports
            # modifier output.
            atoms, total = [], 0
            for o in vis:
                sym, xyz, _b = o.evaluated()
                atoms += [(sym[i], float(xyz[i][0]), float(xyz[i][1]),
                           float(xyz[i][2])) for i in range(len(sym))]
                total += len(sym)
            backend = io.write_structure_file(path, atoms, name=name)
            return backend, len(vis), total
        return backend, len(vis), sum(o.structure.n_atoms for o in vis)

    def on_clear_scene(self):
        if self.scene.n_objects == 0:
            return
        if QMessageBox.question(
                self, "Clear scene",
                "Remove all {} molecule(s) from the scene?".format(
                    self.scene.n_objects)) != QMessageBox.Yes:
            return
        self.push_undo()
        self.scene.clear()
        self.active_id = None
        self.viewport.set_selection([])
        self._sync_all()

    # ---------------------------------------------------------- recent files
    def _recent(self):
        # type: () -> List[str]
        return [p for p in self.settings.value("recent_files", []) or []
                if isinstance(p, str)]

    def _push_recent(self, path):
        rec = [path] + [p for p in self._recent() if p != path]
        self.settings.setValue("recent_files", rec[:_MAX_RECENT])
        self._rebuild_recent_menu()

    def _rebuild_recent_menu(self):
        self.recent_menu.clear()
        rec = self._recent()
        if not rec:
            act = QAction("(empty)", self)
            act.setEnabled(False)
            self.recent_menu.addAction(act)
            return
        for p in rec:
            act = QAction(p, self)
            act.triggered.connect(lambda _c=False, q=p: self.open_path(q))
            self.recent_menu.addAction(act)

    # ---------------------------------------------------------- drag and drop
    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        for url in ev.mimeData().urls():
            p = url.toLocalFile()
            if p:
                self.open_path(p)   # every dropped file becomes an object

    # ------------------------------------------------------------- selection
    def on_select_all(self):
        """Ctrl+A. In edit mode this is scoped to the molecule being edited —
        selecting other molecules there would be meaningless."""
        if self.viewport.mode == MODE_EDIT \
                and self.viewport.edit_obj_id is not None:
            self.viewport.select_whole_molecules([self.viewport.edit_obj_id])
            return
        self.viewport.select_whole_molecules(
            [o.id for o in self.scene.visible_objects()])

    def on_select_linked(self):
        obj_ids = sorted({p[0] for p in self.viewport.selection})
        if obj_ids:
            self.viewport.select_whole_molecules(obj_ids)

    def on_deselect_all(self):
        """Alt+A — Blender's deselect-all. Unlike Esc it never cancels a
        modal, so it is safe to hit while something is armed."""
        self.viewport.set_selection([])
        self.statusBar().showMessage("Selection cleared", 2500)

    def on_escape(self):
        if not self.viewport.cancel_modes():
            self.viewport.set_selection([])

    # -------------------------------------------------------------- edit ops
    def _after_edit(self):
        self.viewport.refresh_geometry()
        self._update_counts()
        self._on_selection_changed(self.viewport.selection)

    def on_add_atom(self):
        symbol, ok = QInputDialog.getText(self, "Add atom",
                                          "Element symbol:", text="C")
        if not ok or not symbol.strip():
            return
        symbol = symbol.strip()
        sel = self.viewport.selection
        if len(sel) == 1:
            obj = self.scene.get(sel[0][0])
            bond_to = sel[0][1]
        else:
            obj = self._active_obj()
            bond_to = None
        self.push_undo()
        if obj is None:
            obj = self.scene.add(Structure(name="molecule"))
            self.active_id = obj.id
        s = obj.structure
        try:
            pos = edits.suggested_position(s, bond_to=bond_to, symbol=symbol)
            edits.add_atom(s, symbol, pos, bond_to=bond_to)
        except ValueError as e:
            self.undo.discard_last()
            QMessageBox.warning(self, "Add atom", str(e))
            return
        if s.n_atoms == 1:
            self.viewport.fit_view()
        self.viewport.set_selection([(obj.id, s.n_atoms - 1)])
        self.outliner.sync(self.scene, self.active_id)
        self._after_edit()

    def on_delete_selected(self):
        sel = self.viewport.selection
        if not sel:
            return
        self.push_undo()
        removed_objs = []
        for obj_id in sorted({p[0] for p in sel}):
            obj = self.scene.get(obj_id)
            if obj is None:
                continue
            rows = [i for o, i in sel if o == obj_id]
            # take the hanging hydrogens with them
            edits.delete_atoms(obj.structure, rows, with_hydrogens=True)
            if obj.structure.n_atoms == 0:
                self.scene.remove(obj_id)
                removed_objs.append(obj.name)
        self.viewport.set_selection([])
        self._sync_all()
        if removed_objs:
            self.statusBar().showMessage(
                "Removed empty molecule(s): " + ", ".join(removed_objs), 4000)

    def on_change_element(self):
        sel = self.viewport.selection
        if not sel:
            self.statusBar().showMessage("Select atoms first", 4000)
            return
        symbol, ok = QInputDialog.getText(self, "Change element",
                                          "New element symbol:", text="C")
        if not ok or not symbol.strip():
            return
        self.push_undo()
        try:
            for obj_id in {p[0] for p in sel}:
                obj = self.scene.get(obj_id)
                if obj is not None:
                    edits.set_element(obj.structure,
                                      [i for o, i in sel if o == obj_id],
                                      symbol.strip())
        except ValueError as e:
            self.undo.discard_last()
            QMessageBox.warning(self, "Change element", str(e))
            return
        self._after_edit()

    def _two_same_object(self):
        sel = self.viewport.selection
        if len(sel) == 2 and sel[0][0] == sel[1][0]:
            return sel
        self.statusBar().showMessage(
            "Select exactly 2 atoms of the SAME molecule first", 4000)
        return None

    def on_cycle_bond(self):
        sel = self._two_same_object()
        if sel is None:
            return
        obj = self.scene.get(sel[0][0])
        self.push_undo()
        order = edits.cycle_bond_order(obj.structure, sel[0][1], sel[1][1])
        self.statusBar().showMessage(
            "Bond order: {}".format(order if order else "removed"), 4000)
        self._after_edit()

    def on_remove_bond(self):
        sel = self._two_same_object()
        if sel is None:
            return
        obj = self.scene.get(sel[0][0])
        self.push_undo()
        edits.remove_bond(obj.structure, sel[0][1], sel[1][1])
        self._after_edit()

    # ------------------------------------------------------------------- misc
    def _set_style(self, st):
        self.viewport.set_style(st)
        act = self._style_actions.get(st.key)
        if act is not None:
            act.setChecked(True)

    def on_reperceive_bonds(self):
        obj = self._active_obj()
        if obj is None:
            return
        self.push_undo()
        bonding.perceive_structure_bonds(obj.structure, keep_orders=False)
        n_multi = bonding.perceive_structure_bond_orders(obj.structure)
        self._after_edit()
        self.statusBar().showMessage(
            "{}: {} bonds re-perceived ({} multiple)".format(
                obj.name, len(obj.structure.bonds), n_multi), 5000)

    def on_perceive_orders(self):
        """Bond orders only — connectivity (which the user may have edited by
        hand) is left exactly as it is."""
        obj = self._active_obj()
        if obj is None:
            return
        self.push_undo()
        n_multi = bonding.perceive_structure_bond_orders(obj.structure)
        self._after_edit()
        self.statusBar().showMessage(
            "{}: bond orders re-assigned ({} multiple)".format(
                obj.name, n_multi), 5000)

    def on_adjust_hydrogens(self):
        sel = self.viewport.selection
        if not sel:
            return
        self.push_undo()
        added = removed = 0
        for obj_id in sorted({p[0] for p in sel}):
            obj = self.scene.get(obj_id)
            if obj is None:
                continue
            a, r = edits.adjust_hydrogens(
                obj.structure, [i for o, i in sel if o == obj_id])
            added += a
            removed += r
        if not (added or removed):
            self.undo.discard_last()
            self.statusBar().showMessage("Hydrogens already correct", 4000)
            return
        self.viewport.set_selection([])
        self._sync_all()
        self.statusBar().showMessage(
            "Hydrogens: +{} / -{}".format(added, removed), 5000)

    def on_set_draw_element(self):
        symbol, ok = QInputDialog.getText(
            self, "Draw element", "Element symbol for the edit-mode draw "
            "tool:", text=self.viewport.draw_element)
        if ok and symbol.strip():
            self.viewport.set_draw_element(symbol.strip())

    def _on_tool_clicked(self, tool_id):
        vp = self.viewport
        if tool_id == "select":
            vp.set_draw_tool(False)
            vp.set_origin_active(False)
            vp.set_select_tool(None)
            self.toolbar.set_active("select")
        elif tool_id == "draw":
            vp.set_origin_active(False)
            vp.set_draw_tool(not vp.draw_tool_active)
            self.toolbar.set_active(
                "draw" if vp.draw_tool_active else "select")
        elif tool_id == "move":
            vp.start_grab()
        elif tool_id == "rotate":
            vp.start_rotate()
        elif tool_id == "origin":
            vp.set_draw_tool(False)
            vp.snap_origin_to_selection()
            self.toolbar.set_active(
                "origin" if vp._origin_active else "select")
        elif tool_id == "measure":
            self.statusBar().showMessage(
                "Click 2-4 atoms — distance, angle and dihedral appear here",
                6000)
        elif tool_id == "optimize":
            self.on_toggle_optimize()

    def _on_mode_changed(self, mode):
        """Keep the window title honest about which mode is active."""
        self._update_title()
        self._update_counts()
        edit = mode == MODE_EDIT
        self.toolbar.set_enabled_tools(edit)
        if not edit:
            self.toolbar.set_active("select")
            # Force-field clean-up is an edit-mode job; the panel only
            # clutters object mode.
            # force-field work is an edit-mode job, but modifiers are an
            # object-level thing — keep the dock, just switch the page
            if self.properties.isVisible() and \
                    self.properties.stack.currentIndex() == 1:
                self.properties.show_page("modifiers")
        self._sync_modifier_page()
        self._position_outliner_tab()

    def on_operator_search(self):
        dlg = OperatorSearchDialog(self, self.ops, self)
        if dlg.exec() and dlg.chosen is not None:
            dlg.chosen.run(self)

    def on_settings(self):
        dlg = SettingsDialog(
            self, rotate_speed=self.viewport.camera.rotate_speed,
            start_maximized=self.settings.value("start_maximized", "true")
            in (True, "true"),
            precision_factor=self.viewport.precision_factor,
            undo_limit=self.undo.limit,
            adjust_h=self.viewport.adjust_h,
            atom_scale=self.viewport.atom_scale,
            render_scale=self.viewport.render_scale,
            render_subdiv=self.viewport.render_subdiv_bonus,
            on_speed_change=lambda v: setattr(self.viewport.camera,
                                              "rotate_speed", v),
            on_atom_scale_change=self.viewport.set_atom_scale)
        old_speed = self.viewport.camera.rotate_speed
        old_scale = self.viewport.atom_scale
        if dlg.exec():
            self.viewport.camera.rotate_speed = dlg.rotate_speed()
            self.viewport.precision_factor = dlg.precision_factor()
            self.viewport.adjust_h = dlg.adjust_hydrogens()
            self.undo.set_limit(dlg.undo_limit())
            self.viewport.set_atom_scale(dlg.atom_scale())
            self.settings.setValue("rotate_speed", dlg.rotate_speed())
            self.settings.setValue("precision_factor", dlg.precision_factor())
            self.settings.setValue("undo_limit", dlg.undo_limit())
            self.settings.setValue("atom_scale", dlg.atom_scale())
            self.viewport.render_scale = dlg.render_scale()
            self.viewport.render_subdiv_bonus = dlg.render_subdiv()
            self.settings.setValue("render_scale", dlg.render_scale())
            self.settings.setValue("render_subdiv", dlg.render_subdiv())
            self.settings.setValue(
                "adjust_hydrogens",
                "true" if dlg.adjust_hydrogens() else "false")
            self.settings.setValue(
                "start_maximized",
                "true" if dlg.start_maximized() else "false")
        else:
            self.viewport.camera.rotate_speed = old_speed
            self.viewport.set_atom_scale(old_scale)

    def on_about(self):
        QMessageBox.about(
            self, "About MoloM",
            "MoloM {}\n\nStandalone molecule viewer/builder.\n"
            "Element data + rendering rules from Avogadro 2 (BSD-3);\n"
            "import cascade and name resolver shared with ORCA Workbench.\n\n"
            "Navigation: two-finger scroll orbits (over an atom/bond: about "
            "it),\nCtrl+scroll zoom, Shift+scroll pan; MMB orbit / RMB pan.\n"
            "Click picks, dbl-click selects the molecule, dbl-click-drag "
            "box-selects.\nG moves (X/Y/Z lock, Shift+X/Y/Z plane, number = "
            "A), O ortho, F fit, F3 search.".format(__version__))
