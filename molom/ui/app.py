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
    QMainWindow, QMenu, QMessageBox, QSlider, QSpinBox, QToolButton,
    QVBoxLayout, QWidget,
)

from .. import __version__
from ..core import align as align_mod
from ..core import blender_export as blender_mod
from ..core import build as build_mod
from ..core import modifiers as modifiers_mod
from ..core import (bonding, edits, input_map, internal, io, measure, project,
                    rotations)
from ..core import cif as cif_mod
from ..core import coplanar
from ..core import spacegroups
from ..core import templates as tpl_mod
from ..core import vibrations as vib_mod
from ..core import timeline as timeline_mod
from ..core import meta as meta_mod
from ..core.camera import quat_from_mat3, quat_to_mat3
from ..core import resolve as resolve_mod
from ..core.ops import OperatorRegistry
from ..core.scene import Scene
from ..core.structure import Structure
from ..core import style as style_mod
from ..core.undo import UndoStack
from .choice_popup import ChoicePopup
from .dialogs import (BlenderExportDialog, MetaAtomDialog,
                      OperatorSearchDialog, ResolveNameDialog, SettingsDialog)
from .crystal_ribbon import CrystalRibbon
from .optimize_panel import OptimizeDock, OptimizeWorker, TASK_SELECTION
from . import properties as properties_mod
from .properties import (CrystalPage, ModifierPage,
                         PropertiesDock, VibrationPage)
from .timeline_panel import TimelinePanel
from .toolbar import ViewportToolbar
from .outliner import OutlinerPanel
from .periodic_table import PeriodicTablePanel
from .transform_panel import TransformDock
from .viewport import (MODE_EDIT, MODE_OBJECT, MolViewport, cell_of,
                       set_cell_reference)

_MAX_RECENT = 8
# Height reserved at the top of the viewport for the edit-mode header banner
# (MolViewport._paint_edit_header draws it at y = 8). Floating overlays start
# below this so they never cover the molecule's name.
_VIEWPORT_HEADER_H = 36


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
        self._align_preview = None       # pose captured when A armed
        # Objects whose frame moved while they were hidden: their bonds are
        # re-perceived when they come back, not while nobody can see them.
        self._stale_bonds = set()
        self.project_path = None         # type: Optional[str]  (.molom)
        self._local_view = None          # {obj_id: visible} while isolated
        self._pending_suppress = False   # merge the next push into this one
        #: (obj_id, pose) captured when an edit STARTS. An edit is not a rigid
        #: motion, so the Kabsch fit that recovers a crystal's orientation
        #: absorbs part of it as a spurious rotation — which then drifts the
        #: drawn cell box and corrupts the fractional coordinates written back
        #: to the asymmetric unit. The pose before the atoms moved is the
        #: trustworthy one.
        self._pose_before_edit = None
        self._last_push_suppressed = False
        self._repeat_macro = None        # {"delta"} after D + move
        self._macro_serial = -1          # viewport transform_serial it came from
        self._dup_grab_active = False
        self._modes = {}          # obj_id -> [vibrations.Mode]
        self._rest_geometry = {}  # obj_id -> equilibrium coords
        self._active_mode = {}    # obj_id -> mode index playing
        self._mode_amplitude = {} # obj_id -> Angstrom
        self._mode_frames = {}    # obj_id -> frames per period
        # Coalesces a slider drag into one re-bake instead of ~60 a second.
        self._mode_rebake = QTimer(self)
        self._mode_rebake.setSingleShot(True)
        self._mode_rebake.setInterval(70)
        self._mode_rebake.timeout.connect(self._rebake_mode)

        self.viewport = MolViewport(self)
        self.viewport.set_scene(self.scene)
        self.viewport.camera.rotate_speed = float(
            self.settings.value("rotate_speed", 1.0))
        self.viewport.precision_factor = float(
            self.settings.value("precision_factor", 0.5))
        self.viewport.set_input_preset(
            self.settings.value("input_preset", input_map.PRESET_AUTO))
        self.viewport.selection_changed.connect(self._on_selection_changed)
        self.viewport.status_message.connect(
            lambda t: self.statusBar().showMessage(t, 4000))
        self.viewport.edit_committed.connect(self._on_edit_committed)
        self.viewport.origin_active_changed.connect(
            lambda _on: self._sync_transform_panel())
        # Undo hooks: modals + anchored-rotation gestures snapshot through us.
        self.viewport.on_model_edit_begin = self.begin_model_edit
        self.viewport.on_model_edit_cancel = self._on_model_edit_cancel
        self.viewport.on_align_key = self._on_align_key
        self.viewport.on_align_confirm = self._on_align_confirm
        self.viewport.on_align_cancel = self._on_align_cancel
        self.viewport.on_edit_begin = self.push_undo
        self.viewport.on_mode_changed = self._on_mode_changed
        self.viewport.on_new_molecule = self.new_empty_molecule
        self.viewport.on_toggle_mode = \
            lambda: self.viewport.toggle_mode(self.active_id)
        # The right-click menu runs REGISTERED OPERATORS rather than its own
        # copies of hide/delete, so the menu, the hotkey and F3 can never
        # disagree about what an entry does or when it is allowed.
        self.viewport.on_context_op = self.run_op
        self.viewport.set_atom_scale(
            float(self.settings.value("atom_scale", 0.9)))
        self.viewport.label_scale = float(
            self.settings.value("label_scale", 1.0))
        self.viewport.adjust_h = self.settings.value(
            "adjust_hydrogens", "true") in (True, "true")
        #: What to do with partially occupied CIF sites — see
        #: `core.cif.resolve_disorder`. An import-time decision, so changing it
        #: applies to the next file opened (and to a crystal-view rebuild).
        policy = self.settings.value("disorder_policy",
                                     cif_mod.POLICY_DOMINANT)
        self.disorder_policy = (policy if policy in cif_mod.DISORDER_POLICIES
                                else cif_mod.POLICY_DOMINANT)
        #: How a space group is NAMED on the crystal page. Hermann-Mauguin by
        #: default because that is what chemists read and publish; the file's
        #: own spelling is inconsistent between programs and Hall is exact but
        #: unreadable. Purely a display choice — it never changes the
        #: operators, which always come from the file or from its symbol.
        from ..core import spacegroups as _sg
        convention = self.settings.value("sg_convention", _sg.CONVENTION_HM)
        valid = [key for key, _label in _sg.CONVENTIONS]
        self.sg_convention = (convention if convention in valid
                              else _sg.CONVENTION_HM)
        for key, attr in self._FLIGHT_KEYS.items():
            stored = self.settings.value("flight_" + key, None)
            if stored is not None:
                try:
                    setattr(self.viewport, attr, float(stored))
                except (TypeError, ValueError):
                    pass

        # ONE clock for the whole scene: every trajectory runs off this
        # playhead, so several can play together.
        self.timeline = timeline_mod.Timeline()
        self._rigid_interp = self.settings.value(
            "rigid_interpolation", "true") in (True, "true")
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
            lambda: (self.viewport.refresh_geometry(), self.viewport.update(),
                     self.outliner.refresh_row_controls()))
        self.outliner.atom_picked.connect(
            lambda oid, i: self.viewport.set_selection([(oid, i)]))
        self.outliner.isolate_requested.connect(self._on_obj_isolate)
        self.outliner.style_changed.connect(self._on_obj_style)
        self.outliner.renamed.connect(self._on_obj_renamed)
        self.outliner.delete_requested.connect(self._on_obj_delete)
        self.outliner.activated.connect(self._on_obj_activated)
        self.outliner.add_requested.connect(self.on_outliner_add)
        self.outliner.merge_requested.connect(self.on_merge_ids)
        self.outliner.crystal_view_changed.connect(self._on_crystal_row_view)
        self.outliner.crystal_box_toggled.connect(
            lambda _oid, on: self._set_cell_box(on))
        self.outliner.crystal_poly_toggled.connect(self._on_crystal_poly)
        self.outliner.crystal_exterior_toggled.connect(
            self._on_crystal_exterior)
        self.outliner.crystal_advanced.connect(self._on_crystal_advanced)
        self.outliner.objects_selected.connect(
            self.viewport.select_whole_molecules)

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
        self.vibration_page = VibrationPage()
        self.vibration_page.mode_selected.connect(self.on_animate_mode)
        self.vibration_page.settings_changed.connect(self._on_mode_settings)
        self.vibration_page.load_requested.connect(self.on_load_frequencies)
        self.crystal_page = CrystalPage()
        self.crystal_page.view_changed.connect(self.on_crystal_view)
        self.crystal_page.occupancy_toggled.connect(
            self._on_occupancy_display)
        self.crystal_page.exterior_toggled.connect(
            lambda on: self._on_crystal_exterior(self.active_id, on))
        self.crystal_page.box_toggled.connect(self._set_cell_box)
        self.crystal_page.poly_check.toggled.connect(
            lambda on: self._set_obj_flag("polyhedra", on))
        self.crystal_page.refused_toggled.connect(
            lambda on: self._set_obj_flag("show_refused_bonds", on))
        self.crystal_page.sym_check.toggled.connect(
            lambda on: self._set_obj_flag("show_symmetry", on))
        self.crystal_page.ghost_check.toggled.connect(
            lambda on: self._set_obj_flag("show_ghosts", on))
        for _key, _box in self.crystal_page.kind_checks.items():
            _box.toggled.connect(lambda _on: self._sync_symmetry_kinds())
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
             ("crystal", "❖", "Unit cell / crystal (CIF)",
              self.crystal_page),
             ("vibrations", "∿", "Vibrational normal modes (ORCA FREQ)",
              self.vibration_page),
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
        # Below the edit-mode header band, not beside it: at y = 8 the first
        # button sat ON TOP of "EDIT | <name> | draw: X", which read as the
        # header text being clipped.
        self.toolbar.move(8, _VIEWPORT_HEADER_H + 8)
        self.toolbar.tool_clicked.connect(self._on_tool_clicked)
        self.toolbar.set_enabled_tools(False)
        self.toolbar.show()
        self.viewport.on_tool_changed = self._on_draw_tool_changed
        self.viewport.on_measure_changed = self._on_measure_changed

        # VESTA's orientation strip, along the top of the viewport. It pops
        # in only when the object in focus is a crystal (`_sync_crystal_
        # ribbon`), so an ordinary molecule never loses the space to it.
        self.crystal_ribbon = CrystalRibbon(self.viewport)
        self.crystal_ribbon.move(8, 6)
        self.crystal_ribbon.axis_view.connect(self._on_ribbon_axis)
        self.crystal_ribbon.standard_view.connect(self._on_ribbon_standard)
        self.crystal_ribbon.rotate_view.connect(self._on_ribbon_rotate)
        self.crystal_ribbon.pan_view.connect(self._on_ribbon_pan)
        self.crystal_ribbon.zoom_view.connect(self._on_ribbon_zoom)
        self.crystal_ribbon.fit_view.connect(self._on_ribbon_fit)

        # Avogadro's element picker, floating just right of the tool column.
        # Edit mode only, and only with the draw tool OFF — see _sync_ptable.
        self.ptable = PeriodicTablePanel(self.viewport)
        self.ptable.element_picked.connect(self.viewport.apply_element)
        self.ptable.meta_atom_requested.connect(self.on_meta_atom)
        self.ptable.set_current(self.viewport.draw_element)
        self.ptable.hide()
        self.viewport.on_element_changed = self.ptable.set_current

        # Both data-dependent tabs start greyed; nothing is loaded yet.
        self._sync_crystal_page()
        self._sync_vibration_page()

        self.ops = OperatorRegistry()
        self._register_operators()
        self._install_shortcuts()
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
          category="File", shortcut="Ctrl+O", key="Ctrl+O")
        r("save_project", "Save project (savepoint)",
          lambda c: c.on_save_project(), enabled=has_obj, category="File",
          shortcut="Ctrl+S", key="Ctrl+S")
        r("save_project_as", "Save project as...",
          lambda c: c.on_save_project_as(), enabled=has_obj, category="File",
          shortcut="Ctrl+Shift+P", key="Ctrl+Shift+P")
        r("import_name", "Import molecule by name...",
          lambda c: c.on_import_by_name(), category="File",
          shortcut="Ctrl+Shift+N", key="Ctrl+Shift+N")
        r("from_smiles", "Add molecule from SMILES...",
          lambda c: c.on_from_smiles(), category="File",
          shortcut="File menu / F3")
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
          category="File", shortcut="Ctrl+V", key="Ctrl+V")
        r("save_as", "Export geometry (visible molecules)...",
          lambda c: c.on_save_as(), enabled=has_obj, category="File",
          shortcut="Ctrl+E", key="Ctrl+E")
        r("export_image", "Export image (PNG snapshot of the viewport)...",
          lambda c: c.on_export_image(), enabled=has_obj, category="File",
          shortcut="Ctrl+Shift+E", key="Ctrl+Shift+E")
        r("export_blender",
          "Export to Blender (script with materials, camera, HDRI)...",
          lambda c: c.on_export_blender(), enabled=has_obj, category="File",
          shortcut="Ctrl+Shift+B", key="Ctrl+Shift+B",
          aliases=("render", "cycles", "hdri", "publication figure",
                   "ray trace", "bpy"))
        r("clear_scene", "Clear scene (remove all molecules)",
          lambda c: c.on_clear_scene(), enabled=has_obj, category="File")

        r("select_all", "Select all", lambda c: c.on_select_all(),
          enabled=has_obj, category="Select", shortcut="Ctrl+A",
          key="Ctrl+A")
        r("clear_selection", "Clear selection",
          lambda c: c.on_deselect_all(), enabled=sel,
          category="Select", shortcut="Alt+A (or Esc)", key="Alt+A")
        r("cancel", "Clear selection / cancel the active mode",
          lambda c: c.on_escape(), category="Select", shortcut="Esc",
          key="Esc", aliases=("escape", "abort"))
        # E is a normal operator key again (round 20): elements are picked
        # from the periodic table, so edit mode no longer needs to swallow
        # letters and nothing competes for it.
        r("toggle_draw", "Draw tool on / off (edit mode)",
          lambda c: c.viewport.set_draw_tool(not c.viewport.draw_tool_active),
          enabled=lambda c: c.viewport.mode == MODE_EDIT, category="Edit",
          shortcut="E", key="E")
        r("select_linked", "Select whole molecule of selection",
          lambda c: c.on_select_linked(), enabled=sel, category="Select",
          shortcut="Ctrl+L", key="Ctrl+L")
        r("box_select", "Box select (arm tool)",
          lambda c: c.viewport.set_select_tool("box"), enabled=has_obj,
          category="Select", shortcut="Shift+Space, B / plain left-drag",
          key="Shift+Space, B")
        r("lasso_select", "Lasso select (arm tool)",
          lambda c: c.viewport.set_select_tool("lasso"), enabled=has_obj,
          category="Select", shortcut="Shift+Space, L",
          key="Shift+Space, L")

        r("move_grab", "Move selection (grab)",
          lambda c: c.viewport.start_grab(), enabled=sel, category="Edit",
          shortcut="G, then X/Y/Z, number", key="G")
        r("rotate", "Rotate selection",
          lambda c: c.viewport.start_rotate(), enabled=sel, category="Edit",
          shortcut="R, then X/Y/Z, degrees", key="R")
        # T, not an axis lock inside R: the axis is a BOND, which belongs to
        # the molecule rather than to the object frame X/Y/Z cycle through.
        r("twist_bond", "Twist a terminal group about its bond axis "
          "(methyl rotor)",
          lambda c: c.viewport.start_twist(), enabled=sel, category="Edit",
          shortcut="T", key="T",
          aliases=("methyl", "rotor", "torsion", "spin group",
                   "internal rotation", "conformer"))
        r("undo", "Undo", lambda c: c.on_undo(),
          enabled=lambda c: c.undo.can_undo, category="Edit",
          shortcut="Ctrl+Z", key="Ctrl+Z")
        r("redo", "Redo", lambda c: c.on_redo(),
          enabled=lambda c: c.undo.can_redo, category="Edit",
          shortcut="Ctrl+Y", key="Ctrl+Y")
        # Alt+O, not plain O: in edit mode every unmodified letter belongs to
        # the element buffer, and O is oxygen. Ctrl/Alt combos are the only
        # ones that survive that policy (see MolViewport.event).
        r("origin_edit", "Origin: snap to selection and pick up (edit mode)",
          lambda c: c.on_origin_edit(),
          enabled=lambda c: c.viewport.mode == MODE_EDIT, category="Edit",
          shortcut="Alt+O (edit mode), or click the orange dot",
          key="Alt+O")
        r("duplicate", "Duplicate selection into a new molecule",
          lambda c: c.on_duplicate(), enabled=sel, category="Edit",
          shortcut="D", key="D")
        r("repeat_transform", "Repeat last action (duplicate + move)",
          lambda c: c.on_repeat_last(),
          enabled=lambda c: (c._repeat_macro is not None
                             or (c.viewport.last_transform is not None
                                 and bool(c.viewport.selection))),
          category="Edit", shortcut="Shift+R", key="Shift+R")
        r("shuttle", "Shuttle mode: pilot the selected molecule",
          lambda c: c.on_shuttle(), enabled=has_active, category="View")
        r("toggle_hbonds", "Show suspected hydrogen bonds",
          lambda c: c.viewport.toggle_hbonds(), category="View",
          aliases=("h-bond", "hydrogen bonding", "contacts"))
        r("optimize_panel", "Force field: optimize geometry (panel)",
          lambda c: c.on_toggle_optimize(), category="Edit", shortcut="Ctrl+R",
          key="Ctrl+R")
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
          shortcut="Ctrl+N", key="Ctrl+N")
        r("drop_floor", "Drop selection to the floor (z = 0)",
          lambda c: c.on_drop_to_floor(), enabled=sel, category="Transform",
          shortcut="End", key="End")
        r("move_to_origin", "Move selection to the world origin",
          lambda c: c.on_move_to_origin(), enabled=sel, category="Transform",
          shortcut="Home (Pos1)", key="Home")
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
          shortcut="/", key="/")
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
                   "2 (two mols) = dock at 3 A, 3+ = plane key", key="A")
        r("add_atom", "Add atom...", lambda c: c.on_add_atom(),
          category="Edit", shortcut="Shift+A (object mode)", key="Shift+A")
        r("delete_selected", "Delete selected atoms",
          lambda c: c.on_delete_selected(), enabled=sel, category="Edit",
          shortcut="Del", key="Del")
        r("hide_selected", "Hide the selected atoms",
          lambda c: c.on_hide_selected(), enabled=sel, category="Edit",
          shortcut="H", key="H",
          aliases=("hide", "conceal", "invisible", "mask"))
        r("unhide_all", "Show every hidden atom",
          lambda c: c.on_unhide_all(),
          enabled=lambda c: any(o.has_hidden for o in c.scene.objects),
          category="Edit", shortcut="Alt+H", key="Alt+H",
          aliases=("unhide", "reveal", "show hidden", "alt h"))
        r("change_element", "Change element of selection...",
          lambda c: c.on_change_element(), enabled=sel, category="Edit",
          shortcut="F3 (in edit mode just type the symbol)")
        r("load_frequencies",
          "Vibrations: load ORCA frequencies for the active molecule...",
          lambda c: c.on_load_frequencies(), enabled=has_active,
          category="Molecule",
          aliases=("freq", "normal mode", "ir", "raman", "orca",
                   "vibration", "imaginary"))
        r("pick_mode", "Vibrations: choose a normal mode to animate...",
          lambda c: c.on_pick_mode(),
          enabled=lambda c: bool(getattr(c, "_modes", {}).get(c.active_id)),
          category="Molecule", aliases=("freq", "normal mode", "vibration"))
        r("template_mark",
          "Template: Set ligating atom(s) on the selected molecule",
          lambda c: c.on_template_mark(), enabled=sel, category="Edit",
          aliases=("ligand", "donor", "coordinating", "template", "anchor"))
        r("template_coordinate",
          "Template: Coordinate ligand onto the selected placeholders",
          lambda c: c.on_template_coordinate(), enabled=sel, category="Edit",
          aliases=("ligand", "attach", "dock", "template", "coordinate"))
        r("join", "Join — bond 2 atoms (edit) / merge molecules (object)",
          lambda c: c.on_join(), enabled=sel, category="Edit",
          shortcut="J", key="J",
          aliases=("merge", "bond", "combine", "connect", "weld"))
        r("cycle_bond", "Cycle bond between 2 selected (none-1-2-3)",
          lambda c: c.on_cycle_bond(), enabled=two_same, category="Edit",
          shortcut="B (object mode; in edit mode hover a bond + 0-4)",
          key="B")
        r("remove_bond", "Remove bond between 2 selected",
          lambda c: c.on_remove_bond(), enabled=two_same, category="Edit",
          shortcut="Shift+B (object mode)", key="Shift+B")

        # Internal coordinates: the one operation a Cartesian editor cannot
        # fake. Enabled strictly on the selection SIZE, so F3 shows exactly
        # the one that applies — the same rule the right-click menu uses.
        def _n_picks(n):
            return lambda c: (c.viewport.internal_picks() is not None
                              and len(c.viewport.internal_picks()[1]) == n)

        r("set_bond_length", "Geometry: set bond length (2 atoms)",
          lambda c: c.viewport.start_internal(internal.DISTANCE),
          enabled=_n_picks(2), category="Edit",
          shortcut="right-click over the selection",
          aliases=("distance", "bond", "stretch", "length", "internal",
                   "z-matrix", "zmatrix"))
        r("set_angle", "Geometry: set angle (3 atoms, vertex = the middle one)",
          lambda c: c.viewport.start_internal(internal.ANGLE),
          enabled=_n_picks(3), category="Edit",
          shortcut="right-click over the selection",
          aliases=("valence", "bend", "internal", "z-matrix", "zmatrix"))
        r("set_dihedral", "Geometry: set dihedral (4 atoms, in pick order)",
          lambda c: c.viewport.start_internal(internal.DIHEDRAL),
          enabled=_n_picks(4), category="Edit",
          shortcut="right-click over the selection",
          aliases=("torsion", "twist", "rotamer", "conformer", "internal",
                   "z-matrix", "zmatrix"))

        r("fit", "Fit view to scene", lambda c: c.viewport.fit_view(),
          enabled=has_obj, category="View", shortcut="F", key="F")
        r("toggle_projection", "Toggle perspective / orthographic",
          lambda c: c.viewport.toggle_projection(), category="View",
          shortcut="Shift+O (object mode)", key="Shift+O")
        for axis, name in ((0, "X"), (1, "Y"), (2, "Z")):
            r("view_pos_" + name.lower(), "View along +{}".format(name),
              lambda c, a=axis: c.viewport.align_view_axis(a, 1),
              category="View")
            r("view_neg_" + name.lower(), "View along -{}".format(name),
              lambda c, a=axis: c.viewport.align_view_axis(a, -1),
              category="View")
        r("toggle_grid", "Toggle floor grid",
          lambda c: c.viewport.toggle_grid(), category="View")
        r("toggle_cell", "Show unit cell box (CIF imports)",
          lambda c: c.on_toggle_cell(), category="View",
          aliases=("crystal", "lattice", "unit cell", "cif", "box"))
        r("meta_atom", "Meta atom: set coordination geometry on the selection",
          lambda c: c.on_meta_atom(), enabled=sel, category="Edit",
          aliases=("coordination", "metal", "dummy", "constraint",
                   "geometry", "restraint"))

        has_cell = lambda c: c._active_cell() is not None
        r("crystal_asym", "Crystal: show the asymmetric unit only",
          lambda c: c.on_crystal_view("asym"), enabled=has_cell,
          category="Crystal", aliases=("cif", "symmetry", "asymmetric"))
        r("crystal_cell", "Crystal: show the full unit cell",
          lambda c: c.on_crystal_view("cell"), enabled=has_cell,
          category="Crystal", aliases=("cif", "symmetry", "expand", "fill"))
        r("crystal_packing", "Crystal: build a packing / supercell...",
          lambda c: c.on_crystal_packing(), enabled=has_cell,
          category="Crystal", aliases=("cif", "supercell", "lattice",
                                       "repeat"))
        r("make_coplanar",
          "Make the selected substituent coplanar with its ring",
          lambda c: c.on_make_coplanar(), enabled=sel, category="Edit",
          aliases=("flat", "planar", "coplanar", "imidazolate", "ring",
                   "flatten", "substituent", "sp2", "conjugation"))
        r("crystal_edit_asym",
          "Crystal: edit the asymmetric unit (cell follows the symmetry)",
          lambda c: c.on_edit_asymmetric_unit(), enabled=has_cell,
          category="Crystal", aliases=("cif", "symmetry", "asymmetric",
                                       "propagate", "repeat", "space group"))
        r("crystal_resymmetrise",
          "Crystal: re-derive the space group from the coordinates",
          lambda c: c.on_reevaluate_symmetry(), enabled=has_cell,
          category="Crystal", aliases=("cif", "symmetry", "space group",
                                       "spglib", "triclinic", "P1"))
        r("cell_info", "Unit cell: report cell parameters and space group",
          lambda c: c.on_cell_info(),
          enabled=lambda c: c._active_cell() is not None,
          category="Molecule", aliases=("crystal", "cif", "spacegroup",
                                        "lattice parameters"))
        r("toggle_outliner", "Toggle outliner panel",
          lambda c: c.on_toggle_outliner(), category="View", shortcut="M",
          key="M")
        r("toggle_transform", "Toggle transform panel",
          lambda c: c.on_toggle_transform(), category="View", shortcut="N",
          key="N")
        r("labels_element", "Toggle atom element labels",
          lambda c: c._label_actions["element"].trigger(), category="View")
        r("labels_index", "Toggle atom index labels",
          lambda c: c._label_actions["index"].trigger(), category="View")
        r("toggle_background", "Toggle background (Blender grey / white)",
          lambda c: c.viewport.toggle_background(), category="View",
          shortcut="Ctrl+B", key="Ctrl+B")
        for st in style_mod.STYLES:
            r("style_" + st.key, "Display style: " + st.label,
              lambda c, s=st: c._set_style(s), category="View")
        r("reperceive", "Re-perceive bonds from geometry (active molecule)",
          lambda c: c.on_reperceive_bonds(), enabled=has_active,
          category="Molecule", shortcut="Ctrl+P", key="Ctrl+P",
          aliases=("recalculate bonds", "recompute bonds", "redetect bonds",
                   "rebuild connectivity", "reconnect"))
        r("perceive_orders", "Re-assign bond orders (active molecule)",
          lambda c: c.on_perceive_orders(), enabled=has_active,
          category="Edit")

        # No has_obj guard: Tab on an EMPTY scene starts a new molecule to
        # draw into, which is the whole point of drawing from scratch.
        # Routed through on_tab_pressed so Tab still WALKS FIELDS while the
        # transform panel has focus.
        r("toggle_mode", "Toggle edit / object mode",
          lambda c: c.on_tab_pressed(),
          category="Edit", shortcut="Tab", key="Tab")
        r("set_draw_element", "Set draw element...",
          lambda c: c.on_set_draw_element(), category="Edit")
        for order, label in ((1, "single"), (2, "double"), (3, "triple")):
            r("bond_order_{}".format(order),
              "Bond order: {} (2 atoms selected)".format(label),
              lambda c, o=order: c.viewport.set_bond_order_selected(o),
              enabled=two_same, category="Edit", shortcut=str(order))
        r("adjust_h", "Adjust hydrogens on selection",
          lambda c: c.on_adjust_hydrogens(), enabled=sel, category="Edit")

        # The palette is itself an operator, registered ONCE. It used to be
        # added straight to two menus with the same shortcut, which Qt reads
        # as an ambiguous overload and refuses to fire — F3 opened nothing.
        r("operator_search", "Search operations (this palette)",
          lambda c: c.on_operator_search(), category="App", shortcut="F3",
          key="F3", aliases=("command palette", "find command", "menu search",
                             "operator search", "spotlight"))
        r("settings", "Settings...", lambda c: c.on_settings(),
          category="App", aliases=("preferences", "mouse", "trackpad",
                                   "input", "options"))
        r("about", "About MoloM", lambda c: c.on_about(), category="App",
          aliases=("shortcuts", "keys", "navigation", "help"))
        r("quit", "Quit MoloM", lambda c: c.close(), category="App",
          shortcut="Ctrl+Q", key="Ctrl+Q", aliases=("exit",))

    def run_op(self, op_id):
        op = self.ops.get(op_id)
        if op is not None and op.enabled(self):
            op.run(self)

    # -------------------------------------------------------------- shortcuts
    def _install_shortcuts(self):
        """Bind every operator that owns a key — independent of the menus.

        Bindings used to ride along on menu entries, so thinning the menus
        down to essentials silently unbound half the app (O, Home/End,
        Shift+R, B/Shift+B, Ctrl+B, Ctrl+P, the box-select chord). Worse, F3
        ended up on TWO menu actions, and Qt answers an ambiguous shortcut by
        firing NEITHER — the operator palette simply stopped opening.

        So: one QAction per operator, owned by the window, keys straight from
        `core.ops`. Menus reuse these same action objects (see `_add_op`), so
        an entry can never register a second copy of the same key.
        """
        clashes = self.ops.duplicate_keys()
        if clashes:      # a programming error, and an invisible one at runtime
            raise RuntimeError(
                "two operators claim the same key: {}".format(clashes))
        self._op_actions = {}
        for op in self.ops.keyed():
            act = QAction(op.label, self)
            act.setShortcut(QKeySequence(op.key))
            act.setShortcutContext(Qt.WindowShortcut)
            act.triggered.connect(
                lambda _checked=False, op_id=op.id: self.run_op(op_id))
            self.addAction(act)
            self._op_actions[op.id] = act

    # ------------------------------------------------------------------ menus
    def _build_menus(self):
        bar = self.menuBar()

        m_file = bar.addMenu("&File")
        self._add_op(m_file, "open", "&Open...")
        self._add_op(m_file, "save_project", "&Save project")
        self._add_op(m_file, "save_project_as", "Save project &as...")
        m_file.addSeparator()
        self._add_op(m_file, "import_name", "Import by &name...")
        self._add_op(m_file, "from_smiles", "Add from &SMILES...")
        self._add_op(m_file, "paste", "&Paste XYZ / SMILES")
        m_file.addSeparator()
        self._add_op(m_file, "new_molecule", "New &empty molecule")
        self._add_op(m_file, "save_as", "&Export geometry...")
        self._add_op(m_file, "export_image", "Export &image...")
        self._add_op(m_file, "export_blender", "Export to &Blender...")
        self._add_op(m_file, "clear_scene", "&Clear scene")
        m_file.addSeparator()
        self.recent_menu = m_file.addMenu("&Recent files")
        self._rebuild_recent_menu()
        m_file.addSeparator()
        self._add_op(m_file, "quit", "E&xit")

        # ESSENTIALS ONLY. Everything else lives in F3, which searches by
        # name and alias and greys out what does not apply — a menu that
        # lists every operator is slower to use than typing two letters.
        # NOTE: the keys are NOT defined here (see _install_shortcuts); a
        # menu is a shortlist, never the thing that keeps a key alive.
        m_edit = bar.addMenu("&Edit")
        self._add_op(m_edit, "undo", "&Undo")
        self._add_op(m_edit, "redo", "&Redo")
        m_edit.addSeparator()
        self._add_op(m_edit, "toggle_mode", "Toggle edit / object mode")
        m_edit.addSeparator()
        self._add_op(m_edit, "duplicate", "&Duplicate selection")
        self._add_op(m_edit, "delete_selected", "&Delete selected atoms")
        m_edit.addSeparator()
        self._add_op(m_edit, "move_grab", "&Move selection (grab)")
        self._add_op(m_edit, "rotate", "Ro&tate selection")
        self._add_op(m_edit, "align_smart", "Ali&gn (selection-aware)")
        m_edit.addSeparator()
        self._add_op(m_edit, "operator_search", "&Search operations...")

        m_sel = bar.addMenu("&Select")
        self._add_op(m_sel, "select_all", "Select &all")
        self._add_op(m_sel, "clear_selection", "Clear selectio&n")
        self._add_op(m_sel, "cancel", "Clear selection / cancel mode")
        self._add_op(m_sel, "select_linked", "Select &linked (whole mol)")
        m_sel.addSeparator()
        self._add_op(m_sel, "box_select", "&Box select tool")
        self._add_op(m_sel, "lasso_select", "La&sso select tool")

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
        self._add_op(m_view, "fit", "&Fit view")
        self._add_op(m_view, "toggle_projection",
                     "Perspective / &Orthographic")
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
        crystal = m_view.addMenu("Cr&ystal (CIF)")
        self._add_op(crystal, "crystal_asym", "&Asymmetric unit")
        self._add_op(crystal, "crystal_cell", "Full &unit cell")
        self._add_op(crystal, "crystal_packing", "&Packing / supercell...")
        crystal.addSeparator()
        self._add_op(crystal, "toggle_cell", "Show unit cell &box")
        self._add_op(crystal, "cell_info", "Cell &parameters...")
        m_view.addSeparator()
        self._add_op(m_view, "local_view", "&Local view (isolate)")
        self._add_op(m_view, "toggle_outliner", "Properties / out&liner")
        self._add_op(m_view, "toggle_transform", "Tra&nsform panel")
        self._add_op(m_view, "optimize_panel", "Force field panel")

        # "A&pp", not "&App": a menu-bar mnemonic IS a shortcut, so Alt+A was
        # claimed by both this menu and Blender's deselect-all — the same
        # ambiguity that killed F3, and Alt+A simply stopped deselecting.
        # _check_menu_mnemonics() keeps this from creeping back.
        m_app = bar.addMenu("A&pp")
        # The SAME action object as the Edit menu's entry — two actions with
        # one key is the ambiguity that killed F3.
        self._add_op(m_app, "operator_search", "&Search operations...")
        self._add_op(m_app, "settings", "&Settings...")
        self._add_op(m_app, "about", "&About MoloM")

    def _check_menu_mnemonics(self):
        """A menu-bar mnemonic is a real shortcut, so it can go ambiguous
        against an operator key exactly like two QActions can — and Qt's
        answer is the same: fire neither, silently. "&App" versus Blender's
        Alt+A deselect is how that was found. Returns the clashes."""
        keys = {op.key: op.id for op in self.ops.keyed()}
        clashes = {}
        for menu in self.menuBar().findChildren(QMenu):
            title = menu.title()
            i = title.find("&")
            if i < 0 or i + 1 >= len(title):
                continue
            key = "Alt+" + title[i + 1].upper()
            if key in keys:
                clashes[key] = (title, keys[key])
        return clashes

    def _add(self, menu, text, slot, shortcut=None):
        act = QAction(text, self)
        if shortcut is not None:
            act.setShortcut(QKeySequence(shortcut))
        act.triggered.connect(slot)
        menu.addAction(act)
        return act

    def _add_op(self, menu, op_id, text):
        """Add an operator to a menu, REUSING its shortcut action if it has
        one (Qt shows the key in the menu by itself). Menu entries never
        define keys — `_install_shortcuts` owns that."""
        act = self._op_actions.get(op_id)
        if act is None:
            return self._add(menu, text, lambda: self.run_op(op_id))
        act.setText(text)
        menu.addAction(act)
        return act

    # ------------------------------------------------------------- status bar
    def _build_statusbar(self):
        self._measure_label = QLabel("")
        self._counts_label = QLabel("")
        # PERMANENT, both of them. A temporary showMessage() hides ordinary
        # status widgets, and picking an atom emits one every time — so the
        # measurement readout was being covered the instant it had something
        # to say. That is the whole "measurement tool is unresponsive" bug;
        # the measuring itself always worked.
        self.statusBar().addPermanentWidget(self._measure_label, 1)
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
                # Picking a crystal in the VIEWPORT must unlock its unit-cell
                # page too — the pane was only re-synced from outliner clicks.
                self._sync_modifier_page()
                # ...and bring in the orientation ribbon, which is what
                # "selected in the viewport, or any part of a cif" means.
                self._sync_crystal_ribbon()

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
        # An edit to a crystal's FULL CELL breaks the symmetry the file
        # declared, so the operators are re-derived from where the atoms now
        # are (round 43d). Skipped entirely when a symmetry modifier owns the
        # expansion — there the base is the asymmetric unit and the operators
        # still hold, which is the whole point of editing that way.
        self._reevaluate_edited_crystal()
        self._update_counts()
        self._on_selection_changed(self.viewport.selection)
        self._sync_transform_panel()

    def base_is_asymmetric_unit(self, obj):
        # type: (object) -> bool
        """Whether this object's ATOMS are the asymmetric unit, not the cell.

        Two ways to be in that state and they must be treated alike, which is
        what round 43d got wrong: a `SymmetryModifier` on the stack (the F3
        route), or the ❖ page's own "Asymmetric unit only" radio, which
        rebuilds the base and adds no modifier at all. Christian used the
        radio, so the modifier-only test never fired.
        """
        meta = getattr(obj.structure, "metadata", None) or {}
        if any(getattr(m, "kind", "") == "symmetry"
               for m in getattr(obj, "modifiers", None) or ()):
            return True
        return str(meta.get("cell_view", "cell")) == "asym"

    def _reevaluate_edited_crystal(self):
        """After an edit: keep the asymmetric unit, or re-derive the cell."""
        obj_id = getattr(self.viewport, "edit_obj_id", None)
        obj = self.scene.get(obj_id) if obj_id is not None else None
        if obj is None:
            obj = self._active_obj()
        if obj is None or not (obj.structure.metadata or {}).get("symops"):
            return
        try:
            if self.base_is_asymmetric_unit(obj):
                # NEVER re-derive here. The atoms in front of us are one
                # asymmetric unit, which by construction has no symmetry among
                # itself — spglib answers P1, correctly, about the wrong
                # question, and the file's real group is destroyed. Christian:
                # "I wanted the reevaluation of the space group to be
                # restricted to editing the full cell directly."
                #
                # It is also the wrong answer chemically: changing one Zn to Co
                # in the asymmetric unit changes ALL EIGHT of its images
                # together, so the operators still map the structure onto
                # itself and the group is untouched.
                self.sync_asymmetric_unit(obj)
                return
            changed = self.reevaluate_symmetry(obj)
        except Exception:                    # never let this break an edit
            return
        if changed:
            self._sync_crystal_page()

    def sync_asymmetric_unit(self, obj):
        # type: (object) -> bool
        """Write an edit to the asymmetric unit back into the metadata.

        Every crystal rebuild regenerates from `asym_symbols`/`asym_frac`, so
        an edit that does not reach them is discarded the moment anything on
        the ❖ page is touched — Christian's "switching back to full unit cell
        doesn't change anything, except that the Co switches back to Zn".
        This is what makes editing the asymmetric unit PERSISTENT.
        """
        s = obj.structure
        meta = s.metadata
        cell = cell_of(obj)
        if cell is None or s.n_atoms == 0:
            return False
        # Prefer the pose from BEFORE the edit: measuring it now would read
        # the atom the user just moved as a rotation of the whole crystal.
        pose = None
        remembered = self._pose_before_edit
        if remembered is not None and remembered[0] == obj.id:
            pose = remembered[1]
        else:
            pose = obj.cell_pose()
        xyz = np.asarray(s.coords, dtype=float)
        if pose is not None:
            rot, shift = pose
            xyz = (xyz - np.asarray(shift)) @ np.asarray(rot)
        frac = cell.to_fractional(xyz)
        meta["asym_symbols"] = list(s.symbols)
        meta["asym_frac"] = [[float(v) for v in row] for row in frac]
        # Re-pin against the CELL-frame coordinates, so the next fit returns
        # this same pose exactly and the error cannot accumulate over a run of
        # edits. Without this the box creeps a little further with every atom
        # moved, which is what "a small re-scaling of the unit cell boundary"
        # looks like from the outside.
        set_cell_reference(s, xyz)
        # The parallel columns must stay the same length as the sites they
        # describe. When atoms have been added or deleted the old values no
        # longer line up with anything, and a silently mis-indexed occupancy
        # is worse than none, so they are reset rather than guessed at.
        n = s.n_atoms
        for key, fill in (("asym_occupancy", 1.0),
                          ("asym_disorder_groups", ""),
                          ("asym_disorder_assemblies", "")):
            values = meta.get(key)
            if values is None:
                continue
            if len(values) != n:
                meta[key] = [fill] * n
        return True

    def begin_model_edit(self):
        """Undo snapshot, plus the crystal's pose while it can still be read.

        The viewport calls this before it moves any atom. Capturing the pose
        here rather than after the fact is what keeps a crystal's cell box
        still during an edit: `cell_pose` is a Kabsch fit against a sample of
        the atoms, and moving some of those atoms makes the fit report a
        rotation that nobody performed.
        """
        obj = self._edited_crystal()
        self._pose_before_edit = ((obj.id, obj.cell_pose())
                                  if obj is not None else None)
        self.push_undo()

    def _edited_crystal(self):
        """Whichever crystal an edit is about to touch, or None."""
        obj_id = getattr(self.viewport, "edit_obj_id", None)
        obj = self.scene.get(obj_id) if obj_id is not None else None
        if obj is None:
            obj = self._active_obj()
        if obj is None or not (getattr(obj.structure, "metadata", None)
                               or {}).get("cell"):
            return None
        return obj

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
        """Tab toggles the mode — UNLESS a PANEL field has focus, where it
        must walk to the next field like any form.

        Checked against every panel, not just the transform one: the array
        modifier's spin boxes had the same collision (Tab jumped into edit
        mode instead of moving to the next number), and so would any panel
        added later. The viewport itself is excluded, which is where Tab
        genuinely means "switch mode".
        """
        focus = QApplication.focusWidget()
        if focus is not None and not self.viewport.isAncestorOf(focus) \
                and focus is not self.viewport:
            for panel in (self.transform_panel, self.properties,
                          self.optimize_panel.widget()):
                if panel is not None and panel.isAncestorOf(focus):
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
            self._sync_crystal_page()
            self._sync_vibration_page()

    def _on_modifiers_changed(self):
        self.viewport.refresh_geometry()
        self._update_counts()

    def _new_symmetry_modifier(self, obj):
        """Seeded from the molecule's own crystallography where it has any.

        A PLAIN molecule gets a working modifier too, with a box drawn round
        it and the identity operation — Christian's actual use case, 2026-08-
        03: take a fragment, stack single operations (a glide, a screw axis)
        one at a time, and watch an asymmetric unit turn into a cell. That is
        a legitimate way to learn a space group, and refusing because the
        molecule "has no cell" made the whole modifier unreachable for it.
        The cell is a starting point to edit, not a fact being asserted.
        """
        meta = obj.structure.metadata or {}
        if meta.get("cell") and meta.get("symops"):
            return modifiers_mod.SymmetryModifier(
                cell=meta.get("cell"), symops=list(meta.get("symops")))
        cell, origin = self._default_cell_for(obj)
        return modifiers_mod.SymmetryModifier(
            cell=meta.get("cell") or cell,
            symops=list(meta.get("symops") or ["x,y,z"]),
            origin=None if meta.get("cell") else origin)

    @staticmethod
    def _default_cell_for(obj):
        """A cubic box around the molecule, plus where to put its origin.

        The origin is offset so the molecule lands near fractional
        (0.3, 0.3, 0.3) — a GENERAL position. Put it on the cell origin
        instead and every operation through that origin maps the molecule
        onto itself, so adding a 2-fold produces no visible copy and the
        modifier looks broken when it is working perfectly.
        """
        from ..core import cif as cif_mod
        coords = obj.structure.coords
        if len(coords) == 0:
            side, centre = 10.0, np.zeros(3)
        else:
            extent = float(np.max(coords.max(axis=0) - coords.min(axis=0)))
            side = max(round(extent * 2.5 + 4.0, 2), 6.0)
            centre = coords.mean(axis=0)
        cell = cif_mod.Cell(side, side, side, 90.0, 90.0, 90.0)
        origin = centre - np.array([0.3, 0.3, 0.3]) @ cell.matrix()
        return cell.to_dict(), origin

    def _reduce_to_asymmetric_unit(self, obj):
        """Put the object's atoms back to the sites the CIF actually listed.

        Kept from `parse_cif` in `asym_symbols`/`asym_frac`, so this is a
        restore rather than a re-derivation — working out which of the cell's
        atoms were the original sites after the user has edited them is not a
        question with a reliable answer.
        """
        from ..core import cif as cif_mod
        meta = obj.structure.metadata or {}
        symbols = list(meta.get("asym_symbols") or ())
        frac = meta.get("asym_frac")
        if not symbols or frac is None:
            return False
        cell = cif_mod.Cell.from_dict(meta["cell"])
        coords = np.asarray(frac, dtype=float) @ cell.matrix()
        obj.structure.symbols = symbols
        obj.structure.frames = [coords.copy()]
        obj.structure.current_frame = 0
        obj.structure.bonds = []
        bonding.perceive_structure_bonds(obj.structure)
        bonding.perceive_structure_bond_orders(obj.structure)
        meta["cell_view"] = "asym"
        return True

    def on_add_modifier(self, kind):
        obj = self._active_obj()
        if obj is None:
            self.statusBar().showMessage("Select a molecule first", 4000)
            return
        if kind == "symmetry":
            mod = self._new_symmetry_modifier(obj)
            if mod is None:
                return
            self.push_undo()
            self._add_modifier(obj, mod)
            # ...and REDUCE the base to the asymmetric unit. Without this the
            # modifier re-applies the operations to a molecule that is
            # already the full cell, de-duplicates straight back to what was
            # there, and nothing whatsoever changes on screen — "Add doesn't
            # do anything". The whole bargain of the modifier is that the
            # base is the asymmetric unit you edit while the viewport shows
            # the cell, so adding it has to put the base into that state.
            reduced = self._reduce_to_asymmetric_unit(obj)
            self._sync_modifier_page()
            self.viewport.refresh_geometry()
            self._update_counts()
            if reduced:
                self.statusBar().showMessage(
                    "Symmetry modifier added to {}: the molecule is now its "
                    "asymmetric unit ({} atoms) and the viewport shows the "
                    "full cell ({} atoms)".format(
                        obj.name, obj.structure.n_atoms,
                        len(obj.evaluated()[0])), 9000)
            else:
                self.statusBar().showMessage(
                    "Symmetry modifier added to {} with a plain box and the "
                    "identity operation — open the card and add operations "
                    "one at a time to build a cell".format(obj.name), 9000)
            return
        elif kind == "boundary":
            cell = cell_of(obj)
            if cell is None:
                self.statusBar().showMessage(
                    "{} has no unit cell — boundary bonds only mean "
                    "something in a periodic structure".format(obj.name), 6000)
                return
            self.push_undo()
            obj.modifiers.append(self._new_boundary_modifier(obj))
            obj.structure.metadata["cell_exterior"] = 1
            self._sync_modifier_page()
            self.viewport.refresh_geometry()
            self._update_counts()
            self.statusBar().showMessage(
                "Boundary bonds on for {}: {} atoms drawn from a {}-atom "
                "cell, with every bond across a face closed".format(
                    obj.name, len(obj.evaluated()[0]),
                    obj.structure.n_atoms), 8000)
            return
        elif kind == "array":
            self.push_undo()
            # default offset along +X, just past the molecule, so the very
            # first click already shows a sensible row instead of a pile-up
            span = obj.structure.bounding_radius() * 2.0 + 1.0
            self._add_modifier(obj, modifiers_mod.ArrayModifier(
                count=3, offset=(round(span, 2), 0.0, 0.0)))
        else:
            return
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
        try:
            c = self.centralWidget()
        except RuntimeError:
            # Teardown race: a dock's visibilityChanged can still fire after
            # the window's C++ side is gone (PySide keeps the Python wrapper
            # alive a moment longer). Nothing left to position.
            return
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

    def _duplicate_in_place(self, sel):
        """D in EDIT mode: copy the atoms into the SAME molecule.

        Edit mode means "I am working inside this molecule", so spawning a
        new outliner object is the wrong answer — you wanted another copy of
        this fragment here, bonded up and ready to move. Object mode still
        duplicates into a new object.
        """
        obj = self.viewport.edit_object()
        if obj is None:
            return
        rows = sorted({i for o, i in sel if o == obj.id})
        if not rows:
            return
        self.push_undo()
        s = obj.structure
        base = s.n_atoms
        index_map = {}
        for i in rows:
            edits.add_atom(s, s.symbols[i], s.coords[i])
            index_map[i] = s.n_atoms - 1
        # Carry across the bonds INTERNAL to the copied fragment.
        for bond in list(s.bonds):
            a, b = int(bond[0]), int(bond[1])
            if a in index_map and b in index_map:
                order = bond[2] if len(bond) > 2 else 1
                edits.add_bond(s, index_map[a], index_map[b], order=order)
        for i in rows:                       # meta atoms copy their spec too
            spec = meta_mod.get_meta(s, i)
            if spec is not None:
                meta_mod.set_meta(s, index_map[i], spec)
        new_sel = [(obj.id, index_map[i]) for i in rows]
        self.viewport.set_selection(new_sel)
        self._after_edit()
        self.statusBar().showMessage(
            "Duplicated {} atom(s) inside {}".format(len(rows), obj.name),
            4000)
        # Straight into a grab, exactly like object-mode duplicate.
        self._pending_suppress = True
        self.viewport.start_grab()

    def on_duplicate(self):
        """D: copy the selection into new outliner objects and start moving
        them straight away. A partial copy gets fresh bond perception and
        hydrogens, since it was cut out of a bigger molecule."""
        sel = self.viewport.selection
        if not sel:
            self.statusBar().showMessage("Nothing selected to duplicate", 4000)
            return
        if self.viewport.mode == MODE_EDIT:
            self._duplicate_in_place(sel)
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
        # Meta atoms: freeze each locked centre AND its donors, so the
        # coordination sphere cannot collapse under a force field that has no
        # parameters for the metal. The ligands still relax around it.
        frozen_meta = meta_mod.frozen_atoms(s)
        if frozen_meta:
            fixed = sorted(set(fixed) | set(frozen_meta))
        self.optimize_panel.set_running(
            True, "Running {} on {}{}...".format(
                method, obj.name,
                " (holding {} meta centre(s))".format(
                    len(meta_mod.all_meta(s))) if frozen_meta else ""))
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

    # ------------------------------------------------------------ Blender
    #: Export options that are worth remembering between sessions. The camera
    #: and the resolution are NOT among them: those follow the viewport, and
    #: restoring last week's resolution over today's window is never right.
    _BLENDER_KEYS = ("hdri", "hdri_strength", "hdri_rotation", "hdri_visible",
                     "lights", "light_strength", "roughness",
                     "metallic_metals", "sphere_subdivisions", "bond_sides",
                     "shade_smooth", "unit_cell", "engine", "samples",
                     "view_transform", "clear_scene", "collection",
                     "style_key")

    def _blender_options(self):
        # type: () -> blender_mod.ExportOptions
        """Last session's choices, or the defaults."""
        opts = blender_mod.ExportOptions()
        for key in self._BLENDER_KEYS:
            stored = self.settings.value("blender_" + key, None)
            if stored is None:
                continue
            current = getattr(opts, key)
            try:
                if isinstance(current, bool):
                    setattr(opts, key, stored in (True, "true", "True", 1))
                elif isinstance(current, int):
                    setattr(opts, key, int(stored))
                elif isinstance(current, float):
                    setattr(opts, key, float(stored))
                else:
                    setattr(opts, key, stored or None if key == "style_key"
                            else stored)
            except (TypeError, ValueError):
                pass
        return opts

    def on_export_blender(self):
        """Pre-configure, then write a Blender build script.

        A script rather than a .blend because writing .blend needs Blender
        itself; this way there is nothing to find, nothing to shell out to,
        and the result is editable text. See core/blender_export.py.
        """
        vis = [o for o in self.scene.visible_objects() if o.structure.n_atoms]
        if not vis:
            self.statusBar().showMessage("Nothing visible to export", 5000)
            return
        vp = self.viewport
        summary = "{}: {} atoms".format(
            ", ".join(o.name for o in vis[:3])
            + (" +{} more".format(len(vis) - 3) if len(vis) > 3 else ""),
            sum(len(o.evaluated()[0]) for o in vis))
        dlg = BlenderExportDialog(self, self._blender_options(), summary,
                                  (vp.width(), vp.height()))
        if not dlg.exec():
            return
        opts = dlg.options()
        opts.atom_scale = vp.atom_scale
        for key in self._BLENDER_KEYS:
            self.settings.setValue("blender_" + key, getattr(opts, key))
        base = (os.path.splitext(os.path.basename(self.project_path))[0]
                if self.project_path else (vis[0].name or "molom"))
        start = self.settings.value("last_dir", "")
        path, _f = QFileDialog.getSaveFileName(
            self, "Export Blender script",
            blender_mod.default_path(start, base),
            "Blender Python script (*.py);;All files (*)")
        if not path:
            return
        try:
            source = self.blender_script(opts, os.path.basename(path))
        except Exception as e:
            QMessageBox.critical(self, "Export failed", str(e))
            return
        try:
            # UTF-8 explicitly: Blender reads scripts as UTF-8, and Windows
            # would otherwise write cp1252 and hand it a byte it refuses.
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(source)
        except OSError as e:
            QMessageBox.critical(self, "Export failed",
                                 "Could not write {}\n{}".format(path, e))
            return
        self.settings.setValue("last_dir", os.path.dirname(path))
        self.statusBar().showMessage(
            "Wrote {} - open it in Blender's Scripting workspace and press "
            "Run".format(os.path.basename(path)), 10000)

    def blender_script(self, options, basename=""):
        # type: (blender_mod.ExportOptions, str) -> str
        """The script for the CURRENT scene and camera. Split out from the
        dialog plumbing so the whole export is testable without Qt file
        dialogs — and so a future "re-export with the same settings" has
        something to call."""
        vp = self.viewport
        style = vp.style
        if options.style_key:
            style = style_mod.STYLE_BY_KEY.get(options.style_key, style)
        data = blender_mod.collect(
            self.scene, style, options,
            camera=vp.camera if options.match_viewport else None,
            width=options.resolution[0], height=options.resolution[1],
            cell_of=cell_of if options.unit_cell else None)
        title = ", ".join(o.name for o in self.scene.visible_objects()
                          if o.structure.n_atoms) or "scene"
        return blender_mod.build_script(
            data, options, title=title, version=__version__,
            basename=basename, summary=blender_mod.summarise(data))

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

    def on_merge_ids(self, ids, mode=None):
        """Combine molecules into one object — the prerequisite for force-
        field optimising an H-bonded pair as a single system.

        `mode` is "new" (keep the originals, hidden) or "replace" (consume
        them). None asks with a dialog, for the outliner's context menu."""
        ids = [i for i in ids if self.scene.get(i) is not None]
        if len(ids) < 2:
            self.statusBar().showMessage(
                "Select atoms of at least two molecules to merge", 5000)
            return
        if mode is None:
            names = [self.scene.get(i).name for i in ids if self.scene.get(i)]
            box = QMessageBox(self)
            box.setWindowTitle("Merge molecules")
            box.setText("Merge {} into one molecule?".format(", ".join(names)))
            keep_box = QCheckBox("Keep the original molecules")
            keep_box.setChecked(True)
            box.setCheckBox(keep_box)
            box.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
            if box.exec() != QMessageBox.Ok:
                return
            keep = keep_box.isChecked()
        else:
            keep = mode == "new"
        self.push_undo()
        merged = self.scene.merge(ids, keep_originals=keep)
        if merged is None:
            self.undo.discard_last()
            return
        if keep:
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
                "; originals kept but hidden" if keep else ""),
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

    def _moved_rows(self, obj):
        """Which atoms a whole-molecule transform should actually move.

        In OBJECT mode: all of them — you are arranging a molecule. In EDIT
        mode: only the fragment CONNECTED to the selection. One outliner
        object routinely holds several disconnected pieces while you build
        (a metal centre and a ligand not yet bonded), and shifting the atom
        you just drew must not drag the untouched ligand with it.
        """
        if self.viewport.mode != MODE_EDIT:
            return None
        sel = [i for o, i in self.viewport.selection if o == obj.id]
        if not sel:
            return None
        rows = obj.structure.connected_component(sel)
        if len(rows) >= obj.structure.n_atoms:
            return None                    # it IS the whole molecule
        return sorted(rows)

    def _translate_object(self, obj, dv, rows=None):
        dv = np.asarray(dv, dtype=float)
        if rows is None:
            rows = self._moved_rows(obj)
        for k in range(obj.structure.n_frames):
            if rows is None:
                obj.structure.frames[k] = obj.structure.frames[k] + dv
            else:
                obj.structure.frames[k][rows] += dv
        if rows is None:
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
        obj = self.scene.get(unique[0])
        if obj is None:
            return
        # Capture BEFORE arming: every axis key previews from this pose.
        self._align_preview = self._align_capture(obj)
        self.viewport.arm_align_keys("axis" if len(sel) == 2 else "plane")

    # -------------------------------------------------------- align preview
    def _align_capture(self, obj):
        """Everything `_rigid_rotate_object` touches, so a preview can be
        re-applied from the ORIGINAL pose rather than compounding on itself.

        Only the one object is copied — a whole-scene snapshot would rebuild
        every MolObject, and the outliner's row widgets hold direct object
        references that would then be pointing at the dead ones.
        """
        return {"obj_id": obj.id,
                "frames": [f.copy() for f in obj.structure.frames],
                "origin": obj.origin.copy(),
                "orientation": obj.orientation.copy()}

    def _align_rewind(self):
        """Put the previewed object back exactly as it was."""
        cap = self._align_preview
        obj = self.scene.get(cap["obj_id"]) if cap else None
        if obj is None:
            return None
        obj.structure.frames = [f.copy() for f in cap["frames"]]
        obj.origin = cap["origin"].copy()
        obj.orientation = cap["orientation"].copy()
        return obj

    def _on_align_key(self, kind, axis):
        """An axis key arrived: show what it would do, and keep waiting.

        Every press rewinds to the captured pose first, so pressing X then Y
        gives the Y alignment rather than Y-applied-on-top-of-X.
        """
        if self._align_preview is None:
            return
        obj = self._align_rewind()
        if obj is None:
            self.viewport._end_align_wait("The molecule is gone")
            return
        sel = self.viewport.selection
        if kind == "axis":
            done = self._preview_align_axis(obj, sel, axis)
        else:
            done = self._preview_align_plane(obj, sel, axis)
        if not done:
            return
        self.viewport.refresh_geometry()
        self.viewport.update()

    def _preview_align_axis(self, obj, sel, axis):
        c = obj.structure.coords
        if len(sel) != 2:
            return False
        v = c[sel[1][1]] - c[sel[0][1]]
        if np.linalg.norm(v) < 1e-6:
            self.statusBar().showMessage("The two atoms coincide", 4000)
            return False
        target = np.zeros(3)
        target[axis] = 1.0
        pivot = (c[sel[0][1]] + c[sel[1][1]]) / 2.0
        self._rigid_rotate_object(
            obj, align_mod.align_vector_to_axis(v, target), pivot)
        self._align_preview["result"] = {
            "last_axis": {"obj_id": obj.id, "axis": target,
                          "pivot": pivot.copy()},
            "message": "Aligned {}-{} of {} to the {} axis (Flip reverses "
                       "it)".format(self.scene.pick_label(tuple(sel[0])),
                                    self.scene.pick_label(tuple(sel[1])),
                                    obj.name, "XYZ"[axis])}
        return True

    def _preview_align_plane(self, obj, sel, axis):
        if len(sel) < 3:
            return False
        pts = np.array([obj.structure.coords[i] for _o, i in sel])
        centroid, normal = align_mod.best_fit_plane(pts)
        target = np.zeros(3)
        target[axis] = 1.0                  # plane PERPENDICULAR to the key
        self._rigid_rotate_object(
            obj, align_mod.align_vector_to_axis(normal, target), centroid)
        plane = {0: "YZ", 1: "XZ", 2: "XY"}[axis]
        self._align_preview["result"] = {
            "last_axis": None,
            "message": "Aligned the {}-atom selection plane of {} to the {} "
                       "plane".format(len(sel), obj.name, plane)}
        return True

    def _on_align_confirm(self):
        """Left-click: keep the preview, as ONE undo step."""
        cap = self._align_preview
        self._align_preview = None
        if cap is None or "result" not in cap:
            return
        result = cap["result"]
        # The undo entry has to be the pose from BEFORE the preview, so the
        # scene is rewound, snapshotted, and rolled forward again. Pushing
        # now would record the previewed pose and make Ctrl+Z do nothing.
        obj = self.scene.get(cap["obj_id"])
        if obj is not None:
            after = self._align_capture(obj)
            self._align_preview = cap
            self._align_rewind()
            self.push_undo()
            self._align_preview = after
            self._align_rewind()
            self._align_preview = None
        self._last_axis_align = result["last_axis"]
        self.viewport.refresh_geometry()
        self._on_edit_committed()
        self.statusBar().showMessage(result["message"], 6000)

    def _on_align_cancel(self):
        """Right-click or Esc: put it back and leave no undo entry."""
        if self._align_preview is None:
            return
        self._align_rewind()
        self._align_preview = None
        self.viewport.refresh_geometry()
        self.viewport.update()

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
        self._flush_stale_bonds()
        self.outliner.sync(self.scene, self.active_id)
        self.viewport.refresh_geometry()
        if fit:
            self.viewport.fit_view()
        self._sync_traj_bar()
        self._update_counts()
        self._sync_transform_panel()
        # The properties pages describe the ACTIVE molecule, so they are as
        # much a part of "the scene changed" as the outliner is. Without this
        # they were only refreshed by an outliner click or by toggling the
        # dock: importing a .cif left the ❖ page still saying "no unit cell"
        # about the crystal that had just become active, which is precisely
        # the "greyed out even though a cif IS selected" complaint.
        self._sync_modifier_page()
        self._sync_crystal_ribbon()

    @staticmethod
    def _perceive_fresh(s):
        # type: (Structure) -> None
        """Connectivity AND bond orders, ONCE, at import. None of the import
        formats we read carry orders, so a freshly opened molecule would
        otherwise be all-single — which makes editing and any later force
        field run start from the wrong chemistry. After this, orders only
        ever change on explicit user action."""
        report = {}
        bonding.perceive_structure_bonds(s, report=report)
        if report.get("dropped_bonds"):
            # Kept on the structure so the import message, the crystal page
            # and a later "why is that atom not bonded?" all have the same
            # answer. Refusing a bond silently is how a viewer earns a
            # reputation for being wrong.
            s.metadata["dropped_bonds"] = [
                {"i": i, "j": j, "distance": round(d, 3), "reason": why}
                for i, j, d, why in report["dropped_bonds"]]
        # The same refusals as a drawable list, for the ❖ page's override
        # (round 43). Kept even when the tick is off: it costs a few hundred
        # int pairs, and computing it later would mean re-perceiving bonds
        # that the user may have edited since.
        if report.get("refused"):
            s.metadata["refused_bonds"] = [[int(i), int(j)]
                                           for i, j in report["refused"]]
        else:
            s.metadata.pop("refused_bonds", None)
        bonding.perceive_structure_bond_orders(s)
        # Pin a crystal's cell box to the atoms as imported, so it travels
        # with them under any later transform.
        set_cell_reference(s)

    def _install_structure(self, s, path=None, note=None):
        # type: (Structure, Optional[str], Optional[str]) -> None
        """Add a molecule to the scene (imports never replace — outliner)."""
        self.push_undo()
        self._perceive_fresh(s)
        obj = self.scene.add(s)
        self.active_id = obj.id
        # A framework's bonds do not stop at the wall. Close them at import,
        # or the first thing anyone sees of a ZIF is severed linkers.
        closed = self._autoclose_boundary(obj)
        self._sync_all(fit=True)
        if path:
            self._push_recent(path)
            extra = self._attach_frequencies(obj, path)
            note = ", ".join([n for n in (note, extra) if n]) or None
        chem = self.chemistry_note(s)
        if closed:
            chem = ", ".join([n for n in (
                chem, "{} bonds closed across the cell faces (+{} image "
                "atoms, drawn only)".format(
                    s.metadata.get("boundary_bonds", 0),
                    s.metadata.get("boundary_atoms", 0))) if n])
        note = ", ".join([n for n in (note, self.symmetry_note(s), chem)
                          if n]) or None
        self.statusBar().showMessage(
            "Added {}{}".format(obj.name,
                                " ({})".format(note) if note else ""), 6000)

    @staticmethod
    def chemistry_note(structure):
        # type: (Structure) -> Optional[str]
        """What the chemistry filters did to this import, in one phrase.

        Round 38 gave the reader three ways to REFUSE what a file says —
        disorder alternatives, impossible contacts, over-valence bonds — and a
        refusal the user is not told about is indistinguishable from a bug.
        This is what makes them visible without a dialog.
        """
        meta = getattr(structure, "metadata", None) or {}
        bits = []
        dis = meta.get("disorder") or {}
        if dis.get("dropped"):
            bits.append("{} disorder alternative(s) resolved".format(
                dis["dropped"]))
        dropped = meta.get("dropped_bonds") or []
        if dropped:
            short = sum(1 for d in dropped if "short" in d.get("reason", ""))
            bits.append("{} impossible bond(s) dropped".format(len(dropped))
                        if short else
                        "{} over-valence bond(s) dropped".format(len(dropped)))
        return "; ".join(bits) or None

    @staticmethod
    def space_group_naming(structure, cell=None):
        # type: (Structure, object) -> object
        """This crystal's space group under every name it answers to.

        Resolved for EVERY crystal, not only the ones whose operators had to
        be derived: the ❖ page has to be able to print the group in whichever
        convention the user picked, and a file that wrote `p21/n` in lower
        case still deserves a properly typeset `P2_1/n`.
        """
        from ..core import spacegroups
        meta = getattr(structure, "metadata", None) or {}
        if not meta.get("cell"):
            return None
        rhombohedral = bool(cell is not None and cell.looks_rhombohedral())
        return spacegroups.identify(meta.get("spacegroup", ""),
                                    number=int(meta.get("it_number", 0) or 0),
                                    hall=meta.get("hall", ""),
                                    rhombohedral=rhombohedral)

    @staticmethod
    def _calculated_density(info, cell):
        # type: (dict, object) -> Optional[float]
        """Dcalc = formula weight x Z / (V x N_A), the crystallographer's own
        cross-check. Computed rather than read, so it can be compared with the
        file's reported value — and it is the fastest way to notice that a
        structure has been expanded wrongly."""
        try:
            weight = float(str(info.get("formula_weight", "")).split("(")[0])
            z = float(str(info.get("z", "")).split("(")[0])
            volume = float(cell.volume())
        except (TypeError, ValueError, AttributeError):
            return None
        if weight <= 0 or z <= 0 or volume <= 0:
            return None
        return weight * z / (volume * 0.6022140857)

    @staticmethod
    def symmetry_note(structure):
        # type: (Structure) -> Optional[str]
        """What the reader did about a missing symmetry loop (round 40).

        Separate from `chemistry_note` because it is a different kind of
        statement: that one is about atoms and bonds REFUSED, this one is
        about symmetry INVENTED (or admittedly not invented). Both end up in
        the same two places -- the import message and the crystal page --
        because both answer "why does the cell look like that?".
        """
        meta = getattr(structure, "metadata", None) or {}
        return meta.get("symmetry_note") or None

    # ------------------------------------------------------------ vibrations
    _FREQ_SUFFIXES = (".out", ".log", ".txt", ".orca", ".output")

    def _attach_frequencies(self, obj, path):
        # type: (object, str) -> Optional[str]
        """Pick up normal modes from a file that was just OPENED normally.

        Opening an ORCA FREQ output through Ctrl+O read the geometry (via
        OpenBabel) and threw the modes away, so `_modes` stayed empty and the
        ∿ tab stayed grey with no hint why — Christian, 2026-08-03: "which I
        still cannot select and look at btw". Requiring the F3 loader for a
        file whose whole point is the frequencies is a discoverability trap:
        if the modes are in the file we just read, take them.

        Cheap on non-FREQ files: only text-ish extensions are considered and
        the header is looked for before anything is parsed.
        """
        if not path or not path.lower().endswith(self._FREQ_SUFFIXES):
            return None
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            if "VIBRATIONAL FREQUENCIES" not in text:
                return None
            modes = vib_mod.parse_orca_frequencies(
                text, n_atoms=obj.structure.n_atoms)
        except (vib_mod.VibrationError, OSError, ValueError):
            return None                  # a geometry-only job: nothing to add
        self._modes[obj.id] = modes
        self._rest_geometry[obj.id] = obj.structure.coords.copy()
        self._sync_vibration_page()
        real = [m for m in modes if not m.is_trivial]
        return "{} normal modes — see the ∿ page".format(len(real))

    # ----------------------------------------------------------- obj signals
    def _catch_up_bonds(self, obj):
        """Re-perceive the bonds of one object that moved while hidden."""
        if obj.id in self._stale_bonds:
            self._stale_bonds.discard(obj.id)
            bonding.perceive_structure_bonds(obj.structure)

    def _flush_stale_bonds(self):
        """Anything that has become visible again catches up NOW, so its
        connectivity is right even if the clock is paused."""
        for obj in self.scene.objects:
            if obj.visible:
                self._catch_up_bonds(obj)

    def _on_obj_visibility(self, obj_id, visible):
        """The molecule's eye. Ticking it back ON also un-hides every atom.

        H hides a selection and nothing in the viewport says where it went —
        so there has to be one obvious way back, and "show this molecule"
        meaning "show ALL of this molecule" is it (Christian's call: cycling
        the tick restores everything). Otherwise the only route out is
        finding each element group whose square happens to read S.
        """
        obj = self.scene.get(obj_id)
        if obj is None:
            return
        obj.visible = visible
        restored = obj.unhide_all() if visible else 0
        self._flush_stale_bonds()
        self.viewport.refresh_geometry()
        if restored:
            self.outliner.sync(self.scene, self.active_id)
            self.statusBar().showMessage(
                "{}: {} hidden atom(s) shown again".format(obj.name,
                                                           restored), 5000)

    # ------------------------------------------------------------ hide atoms
    def on_hide_selected(self):
        """H — hide the selected atoms (Blender's key, Blender's meaning).

        Hides across every molecule the selection touches, so hiding a
        picked-out shell of a framework is one keystroke rather than one per
        object. The selection is cleared afterwards: leaving invisible atoms
        selected means the next G or Delete acts on things you cannot see.
        """
        picks = list(self.viewport.selection)
        if not picks:
            self.statusBar().showMessage(
                "Nothing selected — H hides the selected atoms", 4000)
            return
        by_obj = {}
        for obj_id, atom in picks:
            by_obj.setdefault(obj_id, []).append(atom)
        self.push_undo()
        total = 0
        for obj_id, atoms in by_obj.items():
            obj = self.scene.get(obj_id)
            if obj is not None:
                total += obj.hide_atoms(atoms)
        if not total:
            self.undo.discard_last()     # already hidden: not an edit
            return
        self.viewport.set_selection([])
        self.viewport.refresh_geometry()
        self.outliner.sync(self.scene, self.active_id)
        self._update_counts()
        self.statusBar().showMessage(
            "Hid {} atom(s) — tick the molecule's eye off and on to bring "
            "them back (Alt+H)".format(total), 8000)

    def on_unhide_all(self):
        """Alt+H — show every hidden atom in the scene, as Blender does."""
        total = sum(o.unhide_all() for o in self.scene.objects)
        if not total:
            self.statusBar().showMessage("Nothing is hidden", 3000)
            return
        self.viewport.refresh_geometry()
        self.outliner.sync(self.scene, self.active_id)
        self._update_counts()
        self.statusBar().showMessage(
            "Showed {} hidden atom(s)".format(total), 5000)

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
        self._flush_stale_bonds()
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
        # Also refreshes the crystal page AND greys its tab for the new
        # active molecule — without this the page kept describing whichever
        # object happened to be active when the dock was last opened.
        self._sync_modifier_page()
        self._sync_crystal_ribbon()

    # -------------------------------------------------------- trajectory bar
    def _build_trajectory_bar(self):
        """The timeline pane: transport bar + expandable per-track rows."""
        self.traj_bar = TimelinePanel(self)
        self.traj_bar.play_pause.connect(self.on_play_pause)
        self.traj_bar.seek_requested.connect(self.on_seek)
        self.traj_bar.smoothing_changed.connect(self._on_smoothing_changed)
        self.traj_bar.fps_changed.connect(self._on_fps_changed)
        self.traj_bar.range_changed.connect(self._on_range_changed)
        self.traj_bar.tracks_changed.connect(self._on_tracks_edited)
        self.traj_bar.setVisible(False)
        # kept as aliases so the older call sites keep reading naturally
        self._play_btn = self.traj_bar.play_btn
        self._frame_label = self.traj_bar.label
        self._fps_spin = self.traj_bar.fps_spin
        self._smooth_spin = self.traj_bar.smooth_spin
        # Both knobs persist: they describe how YOU like to watch an
        # animation, not anything about the file that happens to be open.
        self.timeline.fps = float(self.settings.value(
            "playback_fps", timeline_mod.DEFAULT_FPS))
        self.timeline.smoothing = int(self.settings.value(
            "playback_smoothing", timeline_mod.DEFAULT_SMOOTHING))

    def _on_smoothing_changed(self, images):
        """How many images fill one source-frame interval."""
        self.timeline.smoothing = int(images)
        self.settings.setValue("playback_smoothing", int(images))
        self._apply_timeline()

    def _on_fps_changed(self, fps):
        self.timeline.fps = float(fps)
        self.settings.setValue("playback_fps", int(fps))
        if self._play_timer.isActive():
            self._play_timer.setInterval(int(1000 / max(int(fps), 1)))

    def _on_range_changed(self, first, last):
        """The looping interval, as 0-based IMAGE indices from the spin
        boxes. An end on the last image means 'follow the scene', so a
        trajectory that grows later stays fully covered."""
        start = self.timeline.time_of_image(first)
        end = self.timeline.time_of_image(last)
        self.timeline.set_range(
            start, None if end >= self.timeline.duration - 1e-9 else end)
        self._apply_timeline()

    def _on_tracks_edited(self):
        """A row was dragged, toggled or had its end mode cycled."""
        self._apply_timeline()

    def on_seek(self, time):
        self.timeline.seek(float(time))
        self._apply_timeline()

    def _sync_traj_bar(self):
        """Reconcile the scene clock with the scene, then the pane with it.

        The pane is the SCENE playhead, not the active molecule's frame
        index — every trajectory in the scene runs off it at once.
        """
        self.timeline.sync([(o.id, o.structure.n_frames)
                            for o in self.scene.objects])
        # Re-baking a mode at a different frame count changes the duration
        # under the playhead, so pull it back inside the looping interval.
        self.timeline.seek(self.timeline.time)
        if not self.timeline.has_animation:
            self._play_timer.stop()
            self.timeline.playing = False
            self.traj_bar.setVisible(False)
            for obj in self.scene.objects:
                obj.play_position = None
            return
        self.traj_bar.sync(
            self.timeline,
            {o.id: o.name for o in self.scene.objects},
            self._play_timer.isActive())
        self.traj_bar.setVisible(True)

    def on_play_pause(self):
        if self._play_timer.isActive():
            self._play_timer.stop()
            self.timeline.playing = False
            self._play_btn.setText(">")
        else:
            self.timeline.playing = True
            self._play_timer.start(int(1000 / self._fps_spin.value()))
            self._play_btn.setText("||")

    def _advance_frame(self):
        """One timer tick draws exactly one IMAGE.

        The timer therefore runs at the framerate and the step is one
        subdivision of a source frame — which is what makes the two spin
        boxes independent: `fps` sets how fast images go by, `smoothing` sets
        how many of them there are between two frames of the input file.
        """
        if not self.timeline.has_animation:
            self._play_timer.stop()
            self.timeline.playing = False
            return
        fps = float(self._fps_spin.value())
        self._play_timer.setInterval(int(1000 / fps))
        self.timeline.fps = fps
        self.timeline.advance_images(1)
        self._apply_timeline()

    def _apply_timeline(self):
        """Push the playhead onto every object, then repaint ONCE.

        Bonds are re-perceived only when an object's nearest INTEGER frame
        changes, never per interpolated tick: connectivity is a property of
        the frame, and re-running perception 30 times a second would dominate
        playback cost for no visible gain.
        """
        interpolating = self.timeline.interpolate
        for obj in self.scene.objects:
            position = self.timeline.frame_for(obj.id)
            if position is None or obj.structure.n_frames < 2:
                obj.play_position = None
                continue
            obj.play_rigid = self._rigid_interp
            obj.play_position = position if interpolating else None
            nearest = int(round(position))
            if nearest != obj.structure.current_frame:
                obj.structure.set_frame(nearest)
                # Bond perception is the expensive part of a tick, and it is
                # unobservable on a molecule nobody can see — so an animated
                # molecule you have hidden is deferred rather than computed
                # and thrown away. Measured at 600 atoms / 40 frames: a
                # hidden track cost 105% of a visible one before this.
                if obj.visible:
                    bonding.perceive_structure_bonds(obj.structure)
                else:
                    self._stale_bonds.add(obj.id)
            elif obj.visible and obj.id in self._stale_bonds:
                self._catch_up_bonds(obj)
        self.viewport.refresh_geometry()
        self._sync_traj_bar()
        self._update_counts()
        self._on_selection_changed(self.viewport.selection)

    def _set_frame(self, i):
        """Seek the scene clock to an integer scene frame (kept for callers
        that think in frames, e.g. loading a trajectory)."""
        self.timeline.seek(float(i))
        self._apply_timeline()

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
            structs = io.read_structures(path,
                                         disorder=self.disorder_policy)
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
                # Meta atoms are written as the element they stand in for —
                # the dummy is an editing device, not something a downstream
                # program should ever see. Ones with no element chosen stay
                # as the dummy rather than being guessed at.
                for local, real in enumerate(
                        meta_mod.resolved_symbols(o.structure)):
                    if local < len(sym):
                        sym[local] = real
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
        emptied = []
        for obj_id in sorted({p[0] for p in sel}):
            obj = self.scene.get(obj_id)
            if obj is None:
                continue
            rows = [i for o, i in sel if o == obj_id]
            # take the hanging hydrogens with them
            edits.delete_atoms(obj.structure, rows, with_hydrogens=True)
            meta_mod.prune(obj.structure)
            if obj.structure.n_atoms == 0:
                # Emptying the molecule you are EDITING must not delete it:
                # you are standing inside it with the draw tool, and removing
                # the outliner entry leaves edit mode pointing at nothing, so
                # nothing can be drawn any more. Deleting the object itself
                # is an object-mode action.
                if self.viewport.mode == MODE_EDIT \
                        and obj_id == self.viewport.edit_obj_id:
                    emptied.append(obj.name)
                    continue
                self.scene.remove(obj_id)
                removed_objs.append(obj.name)
        self.viewport.set_selection([])
        self._sync_all()
        if removed_objs:
            self.statusBar().showMessage(
                "Removed empty molecule(s): " + ", ".join(removed_objs), 4000)
        elif emptied:
            self.statusBar().showMessage(
                "{} is empty — draw into it, or Tab out to delete it".format(
                    ", ".join(emptied)), 5000)

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

    def on_load_frequencies(self):
        """Read an ORCA FREQ output and remember its modes for this molecule.

        The modes are NOT applied yet — picking one is a separate step, since
        a FREQ job has 3N of them and you always want a specific one.
        """
        obj = self._active_obj()
        if obj is None:
            # Reachable from the ∿ page's own button now, which is visible on
            # an empty scene — so say why nothing happened.
            self.statusBar().showMessage(
                "Open or build a molecule first, or just open the ORCA .out "
                "file directly — its modes are read on import.", 8000)
            return
        start = self.settings.value("last_dir", "")
        path, _f = QFileDialog.getOpenFileName(
            self, "ORCA frequency output for {}".format(obj.name), start,
            "ORCA output (*.out *.log *.txt);;All files (*)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            modes = vib_mod.parse_orca_frequencies(text)
        except (vib_mod.VibrationError, OSError) as exc:
            QMessageBox.warning(self, "Frequencies", str(exc))
            return
        # The output carries its own geometry, so if the active molecule is
        # not the one the job ran on, build that molecule rather than
        # refusing. Requiring the right structure to be open already, with
        # the atoms in the same ORDER, is a promise no workflow can keep.
        n_file = modes[0].displacements.shape[0]
        if obj.structure.n_atoms != n_file:
            atoms = vib_mod.parse_orca_geometry(text)
            if len(atoms) != n_file:
                QMessageBox.warning(
                    self, "Frequencies",
                    "This job has {} atoms but the active molecule has {}, "
                    "and no matching geometry could be read from the "
                    "file.".format(n_file, obj.structure.n_atoms))
                return
            s = Structure.from_atoms(
                atoms, name=os.path.splitext(os.path.basename(path))[0])
            self._install_structure(s, path=path)
            obj = self._active_obj()
        self._modes.setdefault(obj.id, [])
        self._modes[obj.id] = modes
        self.settings.setValue("last_dir", os.path.dirname(path))
        real = [m for m in modes if not m.is_trivial]
        imaginary = [m for m in modes if m.is_imaginary]
        self.properties.setVisible(True)
        self.properties.show_page("vibrations")
        self._sync_vibration_page()
        self._position_outliner_tab()
        self.statusBar().showMessage(
            "{}: {} modes ({} vibrational{}) — pick one in the ∿ "
            "page".format(obj.name, len(modes), len(real),
                          ", {} IMAGINARY".format(len(imaginary))
                          if imaginary else ""), 12000)

    def _sync_vibration_page(self):
        """Refresh the ∿ page for the active molecule.

        The tab stays CLICKABLE even with no frequency data (unlike ❖): a
        greyed square cannot tell you why it is greyed, and "I still cannot
        select and look at it" was the actual report. The page explains
        itself and carries the loader button instead.
        """
        obj = self._active_obj()
        modes = self._modes.get(obj.id) if obj is not None else None
        tab = self.properties.buttons.get("vibrations")
        if tab is not None:
            tab[0].setEnabled(True)
            tab[0].setToolTip(
                "Vibrational normal modes — {}".format(
                    obj.name if modes else
                    "no frequency data on this molecule yet"))
        obj_id = obj.id if obj is not None else None
        self.vibration_page.set_modes(
            modes or [], active=self._active_mode.get(obj_id),
            name=obj.name if obj is not None else "",
            amplitude=float(self._mode_amplitude.get(
                obj_id, properties_mod.DEFAULT_AMPLITUDE)),
            n_frames=int(self._mode_frames.get(
                obj_id, vib_mod.DEFAULT_PERIOD_FRAMES)))

    def on_animate_mode(self, index, amplitude=None, n_frames=None,
                        push=True, resync=True):
        """Bake one mode into a looping track on the scene clock.

        Nothing vibration-specific reaches the player: the mode becomes
        ordinary frames, so it interpolates, sits in the multi-track pane and
        plays alongside other trajectories like anything else.

        `push`/`resync` are off while a slider is being dragged — see
        `_on_mode_settings` for why.
        """
        obj = self._active_obj()
        modes = self._modes.get(obj.id) if obj is not None else None
        if obj is None or not modes:
            return
        mode = next((m for m in modes if m.index == int(index)), None)
        if mode is None:
            return
        rest = self._rest_geometry.get(obj.id)
        if rest is None:
            rest = obj.structure.coords.copy()
            self._rest_geometry[obj.id] = rest
        amplitude = float(
            self._mode_amplitude.get(obj.id, properties_mod.DEFAULT_AMPLITUDE)
            if amplitude is None else amplitude)
        n_frames = int(self._mode_frames.get(
            obj.id, vib_mod.DEFAULT_PERIOD_FRAMES)
            if n_frames is None else n_frames)
        self._mode_amplitude[obj.id] = amplitude
        self._mode_frames[obj.id] = n_frames
        self._active_mode[obj.id] = mode.index
        if push:
            self.push_undo()
        obj.structure.frames = vib_mod.mode_frames(
            rest, mode, amplitude=amplitude, n_frames=n_frames)
        obj.structure.set_frame(0)
        self._sync_traj_bar()
        track = self.timeline.get(obj.id)
        if track is not None:
            track.end = timeline_mod.LOOP        # a vibration IS a loop
        self._apply_timeline()
        if resync:
            self._sync_vibration_page()
        self.statusBar().showMessage(
            "{}: animating {}".format(obj.name, mode.label().strip()), 9000)

    def _on_mode_settings(self, amplitude, n_frames):
        """Amplitude or frames-per-period moved. Both belong to the FREQ
        OBJECT, so re-bake whichever of its modes is currently animating.

        Dragging the amplitude slider used to stutter badly, and neither
        cause was the maths: every single slider tick took a **full deep
        snapshot of the scene** for undo, and then rebuilt all 3N mode cards
        as widgets through `_sync_vibration_page` — which also fed the
        slider's own value back at it. Sixty of those a second is the stutter.
        So the re-bake is coalesced onto a short timer, the page is NOT
        rebuilt (the widgets already show what you are dragging), and one
        undo step covers the whole gesture instead of one per pixel.
        """
        obj = self._active_obj()
        if obj is None:
            return
        self._mode_amplitude[obj.id] = float(amplitude)
        self._mode_frames[obj.id] = int(n_frames)
        if self._active_mode.get(obj.id) is None:
            return                       # nothing playing: just remember it
        if not self._mode_rebake.isActive():
            self.push_undo()             # once per gesture, at its start
        self._mode_rebake.start()

    def _rebake_mode(self):
        """The coalesced end of an amplitude / frame-count drag."""
        obj = self._active_obj()
        active = self._active_mode.get(obj.id) if obj is not None else None
        if active is not None:
            self.on_animate_mode(active, push=False, resync=False)

    def on_pick_mode(self):
        """Bake the chosen mode into a looping trajectory.

        A normal mode is a displacement vector, not coordinates, so one
        period is generated as frames and handed to the scene clock — the
        track pane, interpolation and the export path then all work on it
        with no vibration-specific code anywhere in the UI.
        """
        obj = self._active_obj()
        modes = self._modes.get(obj.id if obj else None) or []
        if obj is None or not modes:
            self.statusBar().showMessage(
                "Load an ORCA frequency file first (F3 'load ORCA "
                "frequencies')", 6000)
            return
        listed = [m for m in modes if not m.is_trivial] or modes
        labels = [m.label() for m in listed]
        choice, ok = QInputDialog.getItem(
            self, "Normal mode", "Animate which mode?", labels, 0, False)
        if not ok:
            return
        mode = listed[labels.index(choice)]
        rest = self._rest_geometry.get(obj.id)
        if rest is None:
            rest = obj.structure.coords.copy()
            self._rest_geometry[obj.id] = rest
        self.push_undo()
        self._active_mode[obj.id] = mode.index
        obj.structure.frames = vib_mod.mode_frames(
            rest, mode,
            amplitude=float(self._mode_amplitude.get(
                obj.id, properties_mod.DEFAULT_AMPLITUDE)),
            n_frames=int(self._mode_frames.get(
                obj.id, vib_mod.DEFAULT_PERIOD_FRAMES)))
        obj.structure.set_frame(0)
        self._sync_traj_bar()
        track = self.timeline.get(obj.id)
        if track is not None:
            track.end = timeline_mod.LOOP     # a vibration is a loop
        self._apply_timeline()
        self.statusBar().showMessage(
            "{}: animating {}".format(obj.name, mode.label().strip()), 9000)

    def on_template_mark(self):
        """Step 1: remember which atoms of this molecule do the coordinating.

        Nothing moves and no dialog opens — the marks just sit there (small
        violet dots) while you go and build the centre.
        """
        sel = self.viewport.selection
        obj_ids = {p[0] for p in sel}
        if len(obj_ids) != 1:
            self.statusBar().showMessage(
                "Select the ligating atom(s) on ONE molecule", 5000)
            return
        obj = self.scene.get(next(iter(obj_ids)))
        rows = sorted({i for _o, i in sel})
        self.push_undo()
        marked = tpl_mod.set_ligating(obj.structure, rows)
        self.viewport.update()
        self.statusBar().showMessage(
            "{}: {} ligating atom(s) marked — now select the placeholder "
            "atoms on the centre and run 'Template: Coordinate ligand'"
            .format(obj.name, len(marked)), 12000)

    def on_template_coordinate(self):
        """Step 2: dock the marked ligand onto the selected placeholders."""
        sel = self.viewport.selection
        host_ids = {p[0] for p in sel}
        if len(host_ids) != 1:
            self.statusBar().showMessage(
                "Select the placeholder atoms on ONE centre", 5000)
            return
        host = self.scene.get(next(iter(host_ids)))
        slots = sorted({i for _o, i in sel})
        donors = [o for o in self.scene.objects
                  if o is not host and tpl_mod.get_ligating(o.structure)]
        if not donors:
            self.statusBar().showMessage(
                "No ligand marked — run 'Template: Set ligating atom(s)' on "
                "the ligand first", 8000)
            return
        ligand = donors[0]
        if len(donors) > 1:
            names = [o.name for o in donors]
            choice, ok = QInputDialog.getItem(
                self, "Coordinate ligand", "Which marked ligand?", names, 0,
                False)
            if not ok:
                return
            ligand = donors[names.index(choice)]
        marks = tpl_mod.get_ligating(ligand.structure)
        try:
            centre = tpl_mod.check_placeholders(host.structure, slots)
            rot, trans = tpl_mod.coordinate(
                host.structure.coords, slots, centre,
                ligand.structure.coords, marks)
        except tpl_mod.TemplateError as exc:
            self.statusBar().showMessage("Coordinate ligand: {}".format(exc),
                                         10000)
            return

        self.push_undo()
        # Bring a COPY of the ligand in, so the template stays reusable.
        moved = ligand.structure.coords @ rot.T + trans
        s = host.structure
        offset = s.n_atoms
        for k, symbol in enumerate(ligand.structure.symbols):
            edits.add_atom(s, symbol, moved[k])
        for bond in ligand.structure.bonds:
            order = bond[2] if len(bond) > 2 else 1
            edits.add_bond(s, offset + int(bond[0]), offset + int(bond[1]),
                           order=order)
        for donor in marks:
            edits.add_bond(s, centre, offset + donor, order=1)
        # The placeholders have been replaced, so they go — last, because
        # deleting reindexes everything above them.
        edits.delete_atoms(s, slots)
        meta_mod.prune(s)
        self.viewport.set_selection([])
        self._after_edit()
        self._sync_all()
        self.statusBar().showMessage(
            "{} coordinated onto {} — {} bond(s) made, {} placeholder(s) "
            "removed".format(ligand.name, host.name, len(marks), len(slots)),
            9000)

    def on_join(self):
        """J — Blender's Join, meaning whichever join makes sense here.

        EDIT mode with exactly two atoms picked: bond them. Otherwise, if the
        selection spans more than one molecule, merge those molecules — and
        since "merge" has two reasonable answers, ask at the cursor rather
        than guessing (Christian's Blender reference).
        """
        sel = self.viewport.selection
        objs = sorted({p[0] for p in sel})
        if self.viewport.mode == MODE_EDIT and len(objs) <= 1:
            if len(sel) != 2:
                self.statusBar().showMessage(
                    "Join: select exactly 2 atoms to bond them", 5000)
                return
            self.on_cycle_bond_to_single()
            return
        if len(objs) < 2:
            self.statusBar().showMessage(
                "Join: select atoms in two or more molecules to merge them",
                5000)
            return
        popup = ChoicePopup(
            "Join {} molecules".format(len(objs)),
            [("new", "Into a new molecule",
              "Keep the originals (hidden) and add the merged copy"),
             ("replace", "Replace the originals",
              "Consume the originals — the merged molecule takes their place")],
            self)
        popup.chosen.connect(lambda mode: self.on_merge_ids(objs, mode))
        popup.popup_at_cursor()

    def on_cycle_bond_to_single(self):
        """J on two atoms: make a bond if there is none, leave it alone if
        there is (J is 'join', not 'cycle' — repeating it must not delete)."""
        sel = self._two_same_object()
        if sel is None:
            return
        obj = self.scene.get(sel[0][0])
        i, j = sel[0][1], sel[1][1]
        existing = any({int(b[0]), int(b[1])} == {i, j}
                       for b in obj.structure.bonds)
        if existing:
            self.statusBar().showMessage("Those atoms are already bonded",
                                         3000)
            return
        self.push_undo()
        edits.add_bond(obj.structure, i, j, order=1)
        self.statusBar().showMessage("Bonded {} to {}".format(
            self.scene.pick_label((obj.id, i)),
            self.scene.pick_label((obj.id, j))), 4000)
        self._after_edit()

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
            vp.set_measure_tool(False)
            self.toolbar.set_active("select")
        elif tool_id == "draw":
            vp.set_origin_active(False)
            vp.set_measure_tool(False)
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
            # A real tool now: it used to only print a hint, so clicking it
            # did nothing whatsoever.
            on = not vp.measure_active
            if on:
                vp.set_draw_tool(False)
                vp.set_origin_active(False)
            vp.set_measure_tool(on)
        elif tool_id == "optimize":
            self.on_toggle_optimize()

    def _on_measure_changed(self, on):
        self.toolbar.set_active("measure" if on else "select")
        self._sync_ptable()

    def _on_draw_tool_changed(self, on):
        self.toolbar.set_active("draw" if on else "select")
        self._sync_ptable()

    def _sync_ptable(self):
        """The periodic table is up in PLAIN edit mode only.

        With the draw tool armed the element is already on the toolbar and
        every click is a drawing gesture, so the chart would just be a wall
        between the cursor and the molecule. In plain edit mode the opposite
        is true: clicks select, and the obvious next thing to do with a
        selection is change what it is made of.
        """
        show = (self.viewport.mode == MODE_EDIT
                and not self.viewport.draw_tool_active)
        if show:
            self.ptable.set_current(self.viewport.draw_element)
            self._position_ptable()
        self.ptable.setVisible(show)

    def _position_ptable(self):
        """Glued to the right edge of the floating tool column."""
        x = self.toolbar.x() + self.toolbar.width() + 6
        self.ptable.move(x, self.toolbar.y())

    def _on_mode_changed(self, mode):
        """Keep the window title honest about which mode is active."""
        self._update_title()
        self._update_counts()
        edit = mode == MODE_EDIT
        self.toolbar.set_enabled_tools(edit)
        self._sync_ptable()
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

    def _active_cell(self):
        """The unit cell of the active molecule, or None."""
        obj = self._active_obj()
        return None if obj is None else cell_of(obj)

    def _on_crystal_row_view(self, obj_id, mode):
        """A checkbox on the crystal's own outliner row — applies at once."""
        if obj_id != self.active_id:
            self.active_id = obj_id          # act on the row you clicked
            self.outliner.highlight(obj_id)
        self.on_crystal_view(mode)

    def _set_obj_flag(self, key, on):
        """Per-object display flags live in metadata, so they ride undo
        snapshots and savepoints without extra plumbing."""
        obj = self._active_obj()
        if obj is None:
            return
        if on:
            obj.structure.metadata[key] = True
        else:
            obj.structure.metadata.pop(key, None)
        self.viewport.refresh_geometry()
        self.viewport.update()

    def _sync_symmetry_kinds(self):
        obj = self._active_obj()
        if obj is None:
            return
        obj.structure.metadata["symmetry_kinds"] =             self.crystal_page.enabled_kinds()
        self.viewport.update()

    def _on_crystal_poly(self, obj_id, on):
        """Coordination polyhedra are PER OBJECT — one framework shown as
        solids next to a molecule shown as sticks is a normal figure."""
        obj = self.scene.get(obj_id)
        if obj is None:
            return
        if on:
            obj.structure.metadata["polyhedra"] = True
        else:
            obj.structure.metadata.pop("polyhedra", None)
        self.viewport.refresh_geometry()
        self.viewport.update()
        self._sync_crystal_page()

    def _on_crystal_exterior(self, obj_id, on):
        """VESTA's boundary search, per crystal.

        Stored in metadata and then re-run through `on_crystal_view`, because
        the exterior atoms are part of building the view — bolting them on
        afterwards would leave them behind the moment the asym/cell/packing
        switch rebuilt the atom list.
        """
        obj = self.scene.get(obj_id)
        if obj is None:
            return
        if obj_id != self.active_id:
            self.active_id = obj_id
            self.outliner.highlight(obj_id)
        meta = obj.structure.metadata
        meta["cell_exterior"] = 1 if on else 0
        # TWO mechanisms answer to this one control, and round 39 left only
        # the first of them wired — which is why Christian reported that
        # ticking it "does nothing" on three different files:
        #
        #  * the BOUNDARY MODIFIER closes covalent bonds that cross a face.
        #    A framework needs it; a molecular crystal has no such bonds once
        #    its molecules are unwrapped, and an ionic lattice's are not
        #    covalent — so for most files it correctly adds nothing at all.
        #  * the EXTERIOR SEARCH brings in the neighbouring cells' molecules
        #    that reach into this one. That is the part you can see, and it is
        #    what VESTA's default picture is made of.
        #
        # The modifier is non-destructive; the search rebuilds the view, so it
        # goes through the same path the asym/cell/packing switch uses and
        # cannot drift from it.
        # The MODIFIER is deliberately NOT touched here (round 43c). It closes
        # bonds that cross a cell face, which is a correctness fix a framework
        # needs whether or not anyone wants the neighbouring molecules drawn —
        # round 39 added it at import for exactly that reason. Driving it from
        # this checkbox conflated the two: `_autoclose_boundary` sets
        # `cell_exterior = 1` at import while showing NO shell, so the first
        # untick disabled a modifier that was never the user's doing and the
        # picture lost atoms it had been showing since it opened. The modifier
        # remains on the Modifiers page, where it can be switched off on
        # purpose. This control now means one thing: draw the neighbouring
        # cells' molecules that reach into this one.
        self.push_undo()
        self._rebuild_exterior(obj)
        self._sync_modifier_page()
        self.viewport.refresh_geometry()
        self._update_counts()
        self.statusBar().showMessage(
            "{}: atoms outside the cell {} ({} atoms drawn from a "
            "{}-atom cell)".format(obj.name, "shown" if on else "hidden",
                                   len(obj.evaluated()[0]),
                                   obj.structure.n_atoms), 7000)

    def _on_occupancy_display(self, on):
        """VESTA's pie spheres for sites shared by several species."""
        self.viewport.show_occupancy = bool(on)
        self.viewport.refresh_geometry()

    def _rebuild_exterior(self, obj):
        """Re-expand this crystal with the current `cell_exterior` setting.

        Regenerated from the stored asymmetric unit, like every other crystal
        view, so turning the option off restores exactly the previous atoms
        rather than trying to subtract them again.
        """
        meta = obj.structure.metadata
        asym_symbols = meta.get("asym_symbols")
        asym_frac = meta.get("asym_frac")
        cell = cell_of(obj)
        if not asym_symbols or not asym_frac or cell is None:
            return
        if any(getattr(m, "kind", "") == "symmetry" for m in obj.modifiers):
            # A symmetry modifier is generating the cell from the base; it
            # owns the expansion and carries its own exterior setting.
            for m in obj.modifiers:
                if getattr(m, "kind", "") == "symmetry":
                    m.exterior = int(meta.get("cell_exterior", 0))
            return
        symops = [cif_mod.SymOp.from_xyz(t) for t in meta.get("symops") or ()
                  if t]
        report = {}
        symbols, coords = cif_mod.build_view(
            cell, asym_symbols, asym_frac, symops,
            mode=meta.get("cell_view", "cell"),
            na=int(meta.get("cell_na", 1)), nb=int(meta.get("cell_nb", 1)),
            nc=int(meta.get("cell_nc", 1)),
            # The checkbox means VESTA's default picture — the neighbouring
            # molecules that reach into this cell — NOT round 35's bonded
            # shell, which on a lattice buries the cell (see `expand`).
            exterior=0,
            shell_molecules=bool(meta.get("cell_exterior", 0)),
            disorder=meta.get("disorder_policy") or self.disorder_policy,
            report=report, **self._view_disorder_kwargs(meta))
        if not symbols:
            return
        meta.pop("site_occupancy", None)
        if report.get("site_occupancy"):
            meta["site_occupancy"] = dict(report["site_occupancy"])
        s = obj.structure
        # Capture the pose BEFORE the atoms are replaced — it is measured
        # against them.
        pose = self._rebuild_pose(s)
        s.symbols = list(symbols)
        s.frames = [self._apply_rebuild_pose(coords, pose)]
        s.set_frame(0)
        s.bonds = []
        # Per-atom display overrides indexed the OLD atom list.
        obj.atom_colors, obj.atom_labels = {}, set()
        obj.atom_label_text, obj.atom_label_colors = {}, {}
        obj.atom_label_modes = {}
        obj.atom_hidden, obj.atom_scales = set(), {}
        self._perceive_fresh(s)
        # ...and re-pin the box against the CELL frame, not the posed atoms.
        set_cell_reference(s, coords)
        self.viewport.set_selection([])

    def on_make_coplanar(self):
        """Flatten a substituent into the plane of the ring it hangs off.

        Christian, on building substituted imidazolates: a substituent on an
        sp2 ring carbon belongs IN the ring plane, and dragging it there by
        hand is exactly the sort of thing a Cartesian editor is bad at.

        The selection says WHICH GROUP, the same way the rotor does (round
        36): `torsion_split` takes the smallest fragment containing the
        selection that hangs off one bond, so picking the substituent's first
        atom, one of its hydrogens or the whole thing all give the same
        answer. The group then moves RIGIDLY — two rotations about the ring
        atom — so no bond length or internal angle changes.
        """
        found = self.viewport.internal_picks()
        if found is None:
            self.statusBar().showMessage(
                "Select the substituent to flatten (any atom of it will do)",
                5000)
            return
        obj_id, rows = found
        obj = self.scene.get(obj_id)
        if obj is None:
            return
        s = obj.structure
        split = internal.torsion_split(s.n_atoms, s.bonds, rows)
        if split is None:
            self.statusBar().showMessage(
                "No single bond frees that selection — pick a substituent "
                "hanging off the ring, not a ring atom itself", 6000)
            return
        moving, stay, attach = split
        ring = coplanar.ring_through(stay, s.bonds, s.n_atoms)
        if not ring:
            self.statusBar().showMessage(
                "{} is not in a ring, so there is no plane to be coplanar "
                "with".format(self.scene.pick_label((obj_id, stay))), 6000)
            return
        plane = coplanar.plane_of(s.coords, ring)
        if plane is None:
            return
        point, normal = plane
        group = sorted(moving)
        before = coplanar.flatness(s.coords, group, point, normal)
        self.push_undo()
        moved = coplanar.make_coplanar(s.coords, group, stay, attach,
                                       normal=normal, point=point)
        s.frames[s.current_frame] = moved
        s.set_frame(s.current_frame)
        self.viewport.refresh_geometry()
        after = coplanar.flatness(s.coords, group, point, normal)
        self.statusBar().showMessage(
            "Coplanar with the {}-ring: {} atom(s) moved rigidly, out-of-"
            "plane rms {:.3f} -> {:.3f} A{}".format(
                len(ring), len(group), before, after,
                "  (an sp3 group cannot be flat — its attachment is)"
                if after > 0.05 else ""), 9000)

    def on_edit_asymmetric_unit(self):
        """F3: hand editing back to the asymmetric unit."""
        obj = self._active_obj()
        note = self.enable_symmetry_editing(obj)
        if not note:
            self.statusBar().showMessage(
                "That molecule has no space group to propagate edits with",
                5000)
            return
        self.statusBar().showMessage(
            "{}: editing the asymmetric unit — {}. The cell is regenerated "
            "from it, so the space group is kept.".format(obj.name, note),
            8000)

    def on_reevaluate_symmetry(self):
        """F3: re-derive the space group, on demand rather than on edit."""
        obj = self._active_obj()
        if obj is None:
            return
        meta = obj.structure.metadata
        if self.base_is_asymmetric_unit(obj):
            self.statusBar().showMessage(
                "{} is showing its asymmetric unit, whose symmetry is {} by "
                "construction — switch to the full unit cell to re-derive "
                "it".format(obj.name, meta.get("spacegroup") or "the group"),
                7000)
            return
        changed = self.reevaluate_symmetry(obj, announce=False)
        if changed:
            self._sync_crystal_page()
            self.statusBar().showMessage(
                "{}: space group re-derived as {} ({} operator(s))".format(
                    obj.name, changed, len(meta.get("symops") or [])), 8000)
        else:
            self.statusBar().showMessage(
                "{}: the coordinates still have {}".format(
                    obj.name, meta.get("spacegroup") or "no stated symmetry"),
                6000)

    def enable_symmetry_editing(self, obj):
        # type: (object) -> Optional[str]
        """Edit the ASYMMETRIC UNIT and have the cell follow, live.

        Christian: "I want to be able to change the asymmetric unit and have
        the change repeated while the space group is kept constant."

        That is exactly the bargain `SymmetryModifier` was built for (round
        29): the base molecule becomes the asymmetric unit — the thing you
        actually edit — while the viewport, the exporter and the ❖ page all
        see the full cell regenerated from it on every change. What was
        missing is a way to GET there from an ordinary .cif import, whose base
        is the whole cell; adding the modifier on top of that would re-apply
        the operations to atoms that already carry them (the round-32 trap).

        So the base is reduced first: to the file's own asymmetric unit where
        it was stored, and otherwise to one atom per symmetry orbit worked out
        from the coordinates. Returns a short description, or None.
        """
        if obj is None:
            return None
        s = obj.structure
        meta = s.metadata
        cell = cell_of(obj)
        if cell is None or not meta.get("symops"):
            return None
        if any(getattr(m, "kind", "") == "symmetry" for m in obj.modifiers):
            return "already symmetry-linked"
        frac = self._crystal_fractional(obj)
        if frac is None:
            return None
        asym_symbols = meta.get("asym_symbols")
        asym_frac = meta.get("asym_frac")
        if asym_symbols and asym_frac:
            symbols = list(asym_symbols)
            reduced = np.asarray(asym_frac, dtype=float)
        else:
            keep = spacegroups.orbit_representatives(
                cell, list(s.symbols), frac)
            if not keep:
                return None
            symbols = [s.symbols[i] for i in keep]
            reduced = np.asarray(frac, dtype=float)[keep]
        self.push_undo()
        s.symbols = list(symbols)
        s.frames = [reduced @ cell.matrix()]
        s.set_frame(0)
        s.bonds = []
        obj.atom_colors, obj.atom_labels = {}, set()
        obj.atom_label_text, obj.atom_label_colors = {}, {}
        obj.atom_label_modes = {}
        obj.atom_hidden, obj.atom_scales = set(), {}
        self._perceive_fresh(s)
        self._add_modifier(obj, modifiers_mod.SymmetryModifier(
            cell=cell.to_dict(), symops=list(meta.get("symops") or [])))
        meta["cell_view"] = "asym"
        self.viewport.set_selection([])
        self.viewport.refresh_geometry()
        self._sync_all()
        return "{} atoms in the asymmetric unit, {} operator(s)".format(
            len(symbols), len(meta.get("symops") or []))

    def _crystal_fractional(self, obj):
        # type: (object) -> object
        """This crystal's atoms in FRACTIONAL coordinates, pose removed.

        Everything symmetry-related is fractional, and a crystal the user has
        rotated is no longer in its cell's frame (round 43c) — so the pose has
        to come off first or the space group comes back as P1 for no better
        reason than the viewport angle.
        """
        cell = cell_of(obj)
        if cell is None or obj.structure.n_atoms == 0:
            return None
        xyz = np.asarray(obj.structure.coords, dtype=float)
        pose = obj.cell_pose()
        if pose is not None:
            rot, shift = pose
            xyz = (xyz - np.asarray(shift)) @ np.asarray(rot)
        return cell.to_fractional(xyz)

    def reevaluate_symmetry(self, obj, announce=True):
        # type: (object, bool) -> Optional[str]
        """Re-derive the space group from where the atoms NOW are.

        Christian's rule, and it is the honest one: "if the full cell is
        edited, then the space group has to be reevaluated or set to triclinic
        because the symmetry has been broken." Keeping the file's operators
        after an edit is the dangerous alternative — they would expand the
        edited cell into a structure that never existed, confidently.

        Skipped whenever the base IS the asymmetric unit — by a symmetry
        modifier or by the ❖ page's radio. One asymmetric unit has no symmetry
        among itself, so spglib would answer P1 perfectly correctly about the
        wrong question and destroy the group the file actually stated.
        Returns the new symbol when it changed, else None.
        """
        if obj is None:
            return None
        s = obj.structure
        meta = s.metadata
        cell = cell_of(obj)
        if cell is None or not meta.get("symops"):
            return None
        if self.base_is_asymmetric_unit(obj):
            return None
        frac = self._crystal_fractional(obj)
        if frac is None:
            return None
        found = spacegroups.from_structure(cell, list(s.symbols), frac)
        if found is not None and found.xyz:
            ops, symbol, number = found.xyz, found.symbol or "P 1", found.number
        else:
            # Nothing survived, so say so plainly rather than keep operators
            # that no longer hold. P1 is always true of any structure.
            ops, symbol, number = ["x,y,z"], "P 1", 1
        was = str(meta.get("spacegroup", ""))
        if (len(ops) == len(meta.get("symops") or ())
                and spacegroups.canonical_key(symbol)
                == spacegroups.canonical_key(was)):
            return None                      # unbroken; nothing to report
        meta["symops"] = list(ops)
        meta["spacegroup"] = symbol
        meta["it_number"] = int(number or 0)
        meta.pop("hall", None)
        meta["symmetry_source"] = spacegroups.SOURCE_DERIVED
        meta["symmetry_note"] = (
            "symmetry re-derived from the edited coordinates: {} -> {} "
            "({} operator(s))".format(was or "unstated", symbol, len(ops)))
        if announce:
            self.statusBar().showMessage(
                "Symmetry broken by the edit — space group is now {} "
                "({} operator(s), was {})".format(symbol, len(ops),
                                                  was or "unstated"), 8000)
        return symbol

    @staticmethod
    def _rebuild_pose(structure):
        # type: (Structure) -> Optional[tuple]
        """The rigid motion the user has applied since this crystal was built.

        Every crystal rebuild regenerates coordinates as `frac @ cell.matrix()`
        — i.e. in the CELL's own frame, the pose the file had. So a crystal the
        user has rotated snaps back to its import orientation the moment any ❖
        control is touched, and the exterior atoms come back in a different
        place: Christian's "not invariant under rotation of the unit cell".

        Recovered the same way the cell BOX follows its molecule (round 19),
        against the same stored reference sample — so the box and the atoms
        cannot disagree about which way the crystal is facing.
        """
        meta = getattr(structure, "metadata", None) or {}
        ref = meta.get("cell_ref_xyz")
        idx = meta.get("cell_ref_idx")
        if not ref or not idx or structure.n_atoms == 0:
            return None
        try:
            cur = np.asarray([structure.coords[int(i)] for i in idx],
                             dtype=float)
        except (IndexError, ValueError):
            return None
        return cif_mod.rigid_from_reference(np.asarray(ref, dtype=float), cur)

    @staticmethod
    def _apply_rebuild_pose(coords, pose):
        # type: (np.ndarray, Optional[tuple]) -> np.ndarray
        """Put freshly generated cell coordinates back into the user's pose."""
        if pose is None:
            return coords
        rot, shift = pose
        return np.asarray(coords, dtype=float) @ np.asarray(rot).T + shift

    @staticmethod
    def _view_disorder_kwargs(meta):
        # type: (dict) -> dict
        """Everything `build_view` needs to resolve disorder as the IMPORT did.

        One helper because there are two rebuild paths — the asym/cell/packing
        switch and the exterior checkbox — and when they disagree the first
        toggle of either silently re-resolves the structure. They did disagree:
        both passed the occupancies and neither passed the GROUP and ASSEMBLY
        columns, which `resolve_disorder` prefers over geometric overlap. On
        7712836.cif that was 999 drawn atoms becoming 469, and it looked like
        atoms vanishing when a checkbox was unticked.

        Absent keys give None, which is the pre-round-43c behaviour — so a
        savepoint written before this existed still loads.
        """
        return {
            "occupancy": meta.get("asym_occupancy"),
            "disorder_groups": meta.get("asym_disorder_groups"),
            "disorder_assemblies": meta.get("asym_disorder_assemblies"),
        }

    @staticmethod
    def _new_boundary_modifier(obj, shells=1):
        # type: (object, int) -> object
        cell = cell_of(obj)
        return modifiers_mod.BoundaryModifier(
            cell=cell.to_dict() if cell is not None else None, shells=shells)

    @staticmethod
    def _boundary_modifier(obj):
        for m in getattr(obj, "modifiers", None) or ():
            if getattr(m, "kind", "") == "boundary":
                return m
        return None

    @staticmethod
    def _add_modifier(obj, mod):
        """Append, keeping BOUNDARY last.

        The stack runs in order and boundary bonds are about the FINAL
        geometry: if it ran before a symmetry or array modifier, those would
        expand its image atoms as though they were real cell contents, and the
        picture would grow a shell of a shell.
        """
        mods = obj.modifiers
        if getattr(mod, "kind", "") == "boundary":
            mods.append(mod)
            return
        cut = len(mods)
        for k, m in enumerate(mods):
            if getattr(m, "kind", "") == "boundary":
                cut = k
                break
        mods.insert(cut, mod)

    def _autoclose_boundary(self, obj):
        # type: (object) -> bool
        """Add the boundary-bonds modifier if this crystal actually needs one.

        A structure whose bonds all sit inside the box (a molecular crystal —
        benzoic acid, urea) gets nothing: there is nothing to close, and an
        inert modifier on the stack is clutter. A FRAMEWORK gets it turned on
        at import, because without it the picture is not merely sparse, it is
        WRONG — Christian's ZIFs came out as heaps of severed linkers with 48
        atoms missing a bond each.
        """
        cell = cell_of(obj)
        s = obj.structure
        if cell is None or s.n_atoms == 0 or self._boundary_modifier(obj):
            return False
        mod = self._new_boundary_modifier(obj)
        try:
            symbols, _xyz, bonds = mod.evaluate(s.symbols, s.coords, s.bonds)
        except (ValueError, cif_mod.CifError):
            return False
        # ASK THE MODIFIER, do not guess from the bond list. Comparing
        # periodic pairs against `structure.bonds` by INDEX over-triggers on a
        # structure that already carries boundary copies: the partner is
        # present under a different index, so the bond looks undrawn when it
        # is drawn perfectly well, and the object collects an inert modifier.
        added = len(symbols) - s.n_atoms
        if added <= 0:
            return False
        obj.modifiers.append(mod)
        # NOT `cell_exterior = 1`. That is the ❖ checkbox's flag, meaning "draw
        # the neighbouring molecules"; adding this modifier is a different
        # thing and the import shows no shell. Setting it here left the box
        # ticked over a picture that had none, so the first untick removed
        # atoms the user had never asked to add.
        s.metadata["boundary_bonds"] = len(bonds) - len(s.bonds)
        s.metadata["boundary_atoms"] = added
        return True

    def _on_crystal_advanced(self, obj_id):
        """"Advanced..." hands off to the unit-cell page, keeping the crystal
        you came from active so the page is unambiguous about its subject."""
        self.active_id = obj_id
        self.outliner.highlight(obj_id)
        self.properties.setVisible(True)
        self.properties.show_page("crystal")
        self._sync_crystal_page()
        self._position_outliner_tab()

    def on_toggle_cell(self):
        self._set_cell_box(not self.viewport.show_cell)

    def _set_cell_box(self, on):
        self.viewport.show_cell = bool(on)
        if self.crystal_page.box_check.isChecked() != bool(on):
            self.crystal_page.box_check.blockSignals(True)
            self.crystal_page.box_check.setChecked(bool(on))
            self.crystal_page.box_check.blockSignals(False)
        self.viewport.update()
        self.statusBar().showMessage(
            "Unit cell box {}".format("on" if on else "off"), 3000)

    # -------------------------------------------------- crystal ribbon
    def _sync_crystal_ribbon(self):
        """Show the orientation strip when the object in focus is a crystal.

        "In focus" is the ACTIVE object, which viewport picking already sets
        — so clicking any part of a `.cif` in 3D brings the strip in, which
        is what Christian asked for ("when cif is selected, or any part of a
        cif"), and clicking a solvent molecule takes it away again.
        """
        obj = self._active_obj()
        cell = self._active_cell()
        self.crystal_ribbon.set_crystal(cell, "" if obj is None else obj.name)
        if cell is None:
            self._restore_toolbar_position()
            return
        self.crystal_ribbon.adjustSize()
        # Below the edit-mode header band when there is one: at y = 6 the
        # strip would sit ON TOP of "EDIT | <name>", which reads as clipped
        # text rather than as two widgets overlapping (the round-18 lesson).
        top = 6 if self.viewport.mode != MODE_EDIT else _VIEWPORT_HEADER_H + 6
        self.crystal_ribbon.move(8, top)
        # Nudge the tool column down so the two never overlap.
        self.toolbar.move(8, top + self.crystal_ribbon.height() + 6)

    def _restore_toolbar_position(self):
        self.toolbar.move(8, _VIEWPORT_HEADER_H + 8)

    def _ribbon_cell(self):
        """The active cell, or None with a status line saying so."""
        cell = self._active_cell()
        if cell is None:
            self.statusBar().showMessage(
                "Select a crystal (a molecule imported from a .cif)", 4000)
        return cell

    def _on_ribbon_axis(self, key):
        from ..core import orient
        cell = self._ribbon_cell()
        if cell is None:
            return
        cam = self.viewport.camera
        # Clicking the SAME axis again views it from the other side, which is
        # what Mercury spends a second row of x−/x+ buttons on. One button
        # that alternates costs no width and is one less thing to find.
        flip = (key == getattr(self, "_last_axis_view", None)
                and not getattr(self, "_last_axis_flip", False))
        self._last_axis_view, self._last_axis_flip = key, flip
        try:
            basis = orient.look_along(cell, key, flip=flip)
        except (ValueError, np.linalg.LinAlgError):
            self.statusBar().showMessage(
                "That cell has no usable {} axis".format(key), 4000)
            return
        cam.rotation = quat_from_mat3(basis)
        # Axis views go orthographic and pop back on the next orbit, exactly
        # as the compass balls already do — a projected cell axis is only
        # honestly "down the axis" without perspective convergence.
        cam.orthographic = True
        cam.auto_ortho = True
        # The up vector here is a CELL axis, which the world-Z-up turntable
        # cannot represent — so the next orbit levels back to the ordinary
        # viewport alignment rather than starting from a pose it has no way
        # to express (Christian: "if I exit view down b, naturally return to
        # the default alignment").
        cam.auto_level = True
        self.viewport.update()
        self.statusBar().showMessage(
            "View along {}{}{} — click again to view from the other side"
            .format("−" if flip else "", key,
                    " (reciprocal — normal to the planes)"
                    if key.endswith("*") else ""), 5000)

    def _on_ribbon_standard(self):
        from ..core import orient
        cell = self._ribbon_cell()
        if cell is None:
            return
        cam = self.viewport.camera
        try:
            basis = orient.clinographic(cell)
        except (ValueError, np.linalg.LinAlgError):
            self.statusBar().showMessage("That cell is degenerate", 4000)
            return
        cam.rotation = quat_from_mat3(basis)
        cam.orthographic = True          # crystal drawings are orthographic
        cam.auto_ortho = True
        self.viewport.update()
        self.statusBar().showMessage(
            "Standard orientation — clinographic oblique projection", 5000)

    def _on_ribbon_rotate(self, d_deg_x, d_deg_y):
        """Stepped turntable rotation. Converted to the pixel units
        `Camera.rotate` speaks so there is only ONE orbit implementation —
        including the no-roll construction, which a second path would have
        to re-earn."""
        cam = self.viewport.camera
        per_deg = cam.PX_PER_REV / 360.0 / max(cam.rotate_speed, 1e-6)
        cam.rotate(float(d_deg_x) * per_deg, float(d_deg_y) * per_deg)
        self.viewport.update()

    def _on_ribbon_pan(self, dx_px, dy_px):
        vp = self.viewport
        vp.camera.pan(float(dx_px), float(dy_px),
                      max(vp.width(), 1), max(vp.height(), 1))
        vp.update()

    def _on_ribbon_zoom(self, percent):
        from ..core import orient
        self.viewport.camera.zoom(orient.zoom_steps_for_percent(percent))
        self.viewport.update()

    def _on_ribbon_fit(self):
        self.viewport.fit_view()

    def _sync_crystal_page(self):
        obj = self._active_obj()
        cell = self._active_cell()
        # The ❖ TAB is always clickable, like ∿ (round 30's lesson: a greyed
        # tab cannot explain why it is greyed, and this one greys itself on
        # whichever molecule happens to be active — so the page you were just
        # reading vanishes when you click a solvent molecule). The CONTROLS
        # inside grey out instead, and the page says what to select.
        tab = self.properties.buttons.get("crystal")
        if tab is not None:
            tab[0].setEnabled(True)
            tab[0].setToolTip(
                "Unit cell / crystal — {}".format(
                    obj.name if cell is not None
                    else "select a molecule imported from a .cif"))
        if obj is None or cell is None:
            self.crystal_page.set_cell(None, name="" if obj is None
                                       else obj.name)
            return
        meta = obj.structure.metadata
        info = meta.get("cif_info") or {}
        naming = self.space_group_naming(obj.structure, cell)
        shown = (naming.text(self.sg_convention) if naming is not None
                 else meta.get("spacegroup", ""))
        self.crystal_page.set_cell(
            cell, spacegroup=shown,
            n_asym=len(meta.get("asym_symbols") or ()),
            n_atoms=obj.structure.n_atoms,
            mode=meta.get("cell_view", "cell"),
            exterior=int(meta.get("cell_exterior", 0)),
            chemistry=self.chemistry_note(obj.structure) or "",
            symmetry=self.symmetry_note(obj.structure) or "",
            naming=naming,
            bravais=(naming.bravais if naming is not None else ""),
            density=self._calculated_density(info, cell),
            refused=len(meta.get("refused_bonds") or ()),
            refused_on=bool(meta.get("show_refused_bonds")),
            name=obj.name)
        self.crystal_page.set_detail(
            info, naming=naming, site_occupancy=meta.get("site_occupancy"))

    def on_meta_atom(self):
        """Configure the meta atom (the periodic table's ✳ button, and F3).

        Opens whatever is or is not selected: the window IS where a meta atom
        is defined, exactly like the chart is where an element is defined.
        Confirming makes it the current draw element, so the next atom drawn
        is a meta centre — and if atoms happen to be selected, they are
        converted too, matching what picking an element does.
        """
        obj = self.viewport.edit_object() or self._active_obj()
        sel = [i for o, i in self.viewport.selection
               if obj is not None and o == obj.id]
        current = self.viewport.meta_template
        if obj is not None and sel:
            current = meta_mod.get_meta(obj.structure, sel[0]) or current
        dlg = MetaAtomDialog(self, current)
        if not dlg.exec():
            return
        m = dlg.meta_atom()
        # Arm it as the draw element whether or not anything was selected.
        self.viewport.set_meta_template(m)
        self.ptable.set_meta_label(m.element, m.geometry)
        moved = 0
        if obj is not None and sel:
            self.push_undo()
            for i in sel:
                meta_mod.set_meta(obj.structure, i, m)
                if dlg.idealize_now():
                    moved += meta_mod.idealize(obj.structure, i, m)
                    moved += meta_mod.dress_with_hydrogens(obj.structure, i, m)
            self.viewport.set_selection([])
            self.viewport.refresh_geometry()
            self._update_counts()
        self.statusBar().showMessage(
            "Meta atom armed: {} r={:.2f} A{}{}".format(
                m.geometry.replace("_", " "), m.distance,
                " -> {} on export".format(m.element) if m.element
                else " (no export element set)",
                ", {} donor(s) placed".format(moved) if moved
                else " — draw to place one"), 8000)

    def _crystal_view_via_modifier(self, obj, mod, mode, na, nb, nc):
        """The asym/cell/packing switch, expressed through the modifier.

        With a symmetry modifier on the stack the base IS the asymmetric
        unit, so "asymmetric unit" means switching the modifier off and the
        other two mean switching it on with a block size — no rebuilding of
        atoms anywhere, which is the whole point of having it as a modifier.
        """
        self.push_undo()
        mod.enabled = mode != "asym"
        if mode == "packing":
            mod.na, mod.nb, mod.nc = int(na), int(nb), int(nc)
        else:
            mod.na = mod.nb = mod.nc = 1
        meta = obj.structure.metadata or {}
        mod.exterior = 0          # the BoundaryModifier owns this now
        meta["cell_view"] = mode
        self._sync_modifier_page()
        self.viewport.refresh_geometry()
        self._update_counts()
        label = {"asym": "asymmetric unit", "cell": "full unit cell",
                 "packing": "{}x{}x{} packing".format(na, nb, nc)}[mode]
        self.statusBar().showMessage(
            "{}: symmetry modifier now shows the {} ({} atoms drawn from a "
            "{}-atom base)".format(obj.name, label, len(obj.evaluated()[0]),
                                   obj.structure.n_atoms), 7000)

    def on_crystal_view(self, mode, na=1, nb=1, nc=1):
        """Rebuild a CIF import as asymmetric unit / full cell / packing.

        The asymmetric unit and the operators are kept in metadata at import,
        so every mode is regenerated from the SAME source rather than by
        undoing the previous one — switching back and forth cannot drift.
        """
        obj = self._active_obj()
        cell = self._active_cell()
        if obj is None or cell is None:
            self.statusBar().showMessage(
                "The active molecule has no unit cell (import a .cif)", 5000)
            return
        meta = obj.structure.metadata
        asym_symbols = meta.get("asym_symbols")
        asym_frac = meta.get("asym_frac")
        if not asym_symbols or not asym_frac:
            self.statusBar().showMessage(
                "This molecule has a cell but no stored asymmetric unit", 5000)
            return
        # A symmetry MODIFIER is already generating the cell from the base.
        # Rebuilding the base here too would expand an expanded structure —
        # the switch has to drive the modifier instead, or the two fight.
        sym_mods = [m for m in obj.modifiers
                    if getattr(m, "kind", "") == "symmetry"]
        if sym_mods:
            self._crystal_view_via_modifier(obj, sym_mods[0], mode,
                                            na, nb, nc)
            return
        symops = [cif_mod.SymOp.from_xyz(t) for t in meta.get("symops")
                  or ["x,y,z"]]
        report = {}
        symbols, coords = cif_mod.build_view(
            cell, asym_symbols, asym_frac, symops, mode=mode,
            na=na, nb=nb, nc=nc,
            # exterior=0 ALWAYS: closing the bonds across the cell faces
            # is the BoundaryModifier's job now (round 39), and doing it here
            # too would add every exterior atom twice.
            exterior=0,
            # The exterior setting is part of the VIEW, so switching
            # asym/cell/packing must carry it or the checkbox silently
            # un-applies itself on the next mode change.
            shell_molecules=bool(meta.get("cell_exterior", 0)),
            # The occupancies, the disorder columns and the policy all ride
            # with the object, so a rebuild resolves the disorder exactly as
            # the import did.
            disorder=meta.get("disorder_policy") or self.disorder_policy,
            report=report, **self._view_disorder_kwargs(meta))
        if report.get("disorder"):
            meta["disorder"] = dict(report["disorder"])
        # Rebuilt views renumber the atoms, so the shared-site map has to be
        # replaced (or cleared) with them — a stale one would paint the pie
        # slices onto whichever atom happens to hold that index now.
        meta.pop("site_occupancy", None)
        if report.get("site_occupancy"):
            meta["site_occupancy"] = dict(report["site_occupancy"])
        if not symbols:
            self.statusBar().showMessage("That view produced no atoms", 4000)
            return
        self.push_undo()
        s = obj.structure
        # Keep whatever rigid motion the user has applied (see _rebuild_pose):
        # a regenerated view is in the CELL's frame, not the viewport's.
        pose = self._rebuild_pose(s)
        s.symbols = list(symbols)
        s.frames = [self._apply_rebuild_pose(coords, pose)]
        s.set_frame(0)
        s.bonds = []
        # Per-atom display overrides indexed the OLD atom list.
        obj.atom_colors, obj.atom_labels = {}, set()
        obj.atom_label_text, obj.atom_label_colors = {}, {}
        obj.atom_label_modes = {}
        self._perceive_fresh(s)
        set_cell_reference(s, coords)      # cell frame, not the posed atoms
        meta["cell_view"] = mode
        self.viewport.set_selection([])
        self._sync_all()
        label = {"asym": "asymmetric unit", "cell": "full unit cell",
                 "packing": "{}x{}x{} packing".format(na, nb, nc)}[mode]
        self.statusBar().showMessage(
            "{}: {} — {} atoms".format(obj.name, label, s.n_atoms), 6000)

    def on_crystal_packing(self):
        na, ok = QInputDialog.getInt(self, "Packing", "Cells along a:", 2, 1, 12)
        if not ok:
            return
        nb, ok = QInputDialog.getInt(self, "Packing", "Cells along b:", na,
                                     1, 12)
        if not ok:
            return
        nc, ok = QInputDialog.getInt(self, "Packing", "Cells along c:", nb,
                                     1, 12)
        if not ok:
            return
        self.on_crystal_view("packing", na, nb, nc)

    def on_cell_info(self):
        obj = self._active_obj()
        cell = self._active_cell()
        if obj is None or cell is None:
            return
        meta = obj.structure.metadata
        n_asym = len(meta.get("asym_symbols") or ())
        QMessageBox.information(
            self, "Unit cell — {}".format(obj.name),
            "a = {:.4f} A\nb = {:.4f} A\nc = {:.4f} A\n"
            "alpha = {:.3f}\nbeta  = {:.3f}\ngamma = {:.3f}\n\n"
            "Volume = {:.2f} A^3\nSpace group: {}\n"
            "Symmetry operations: {}\n"
            "Asymmetric unit: {} site(s)\nExpanded cell: {} atoms".format(
                cell.a, cell.b, cell.c, cell.alpha, cell.beta, cell.gamma,
                cell.volume(), meta.get("spacegroup") or "not stated",
                len(meta.get("symops") or ()), n_asym,
                obj.structure.n_atoms))

    def on_operator_search(self):
        dlg = OperatorSearchDialog(self, self.ops, self)
        if dlg.exec() and dlg.chosen is not None:
            dlg.chosen.run(self)

    def on_settings(self):
        """Settings is MODELESS — it has live-applying sliders, so being
        locked out of the outliner and the viewport while judging a sphere
        size or a label size was backwards. Nothing here needs the rest of
        the app held still."""
        existing = getattr(self, "_settings_dlg", None)
        if existing is not None:
            existing.raise_()
            existing.activateWindow()
            return
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
            input_preset=self.viewport.input_preset,
            label_scale=self.viewport.label_scale,
            disorder_policy=self.disorder_policy,
            sg_convention=self.sg_convention,
            on_speed_change=lambda v: setattr(self.viewport.camera,
                                              "rotate_speed", v),
            on_atom_scale_change=self.viewport.set_atom_scale,
            on_label_scale_change=self._set_label_scale,
            flight_tuning=self._flight_tuning(),
            on_flight_change=self._set_flight_tuning)
        old_speed = self.viewport.camera.rotate_speed
        old_scale = self.viewport.atom_scale
        old_labels = self.viewport.label_scale
        old_flight = self._flight_tuning()
        self._settings_dlg = dlg
        dlg.setModal(False)
        dlg.finished.connect(
            lambda result: self._settings_closed(dlg, result, old_speed,
                                                 old_scale, old_labels,
                                                 old_flight))
        dlg.show()

    #: Settings key <-> viewport attribute for the flight handling model.
    _FLIGHT_KEYS = {"accel": "fly_accel", "damping": "fly_damping",
                    "brake_factor": "fly_brake_factor",
                    "strafe_factor": "fly_strafe_factor",
                    "roll_rate": "fly_roll_rate", "turn_rate": "fly_turn_rate",
                    "bank_angle": "fly_bank_angle",
                    "aim_expo": "fly_aim_expo", "hold_ms": "fly_hold_ms"}

    def _flight_tuning(self):
        # type: () -> dict
        return {k: float(getattr(self.viewport, attr))
                for k, attr in self._FLIGHT_KEYS.items()}

    def _set_flight_tuning(self, key, value):
        """Live-apply one flight constant, including to a flight IN PROGRESS
        — the whole point of exposing them is judging the feel while flying,
        which you cannot do if the change only lands on the next take-off."""
        attr = self._FLIGHT_KEYS.get(key)
        if attr is None:
            return
        setattr(self.viewport, attr, float(value))
        fly = self.viewport._fly
        if fly is None:
            return
        if key == "aim_expo":
            fly["aim"].expo = max(float(value), 1.0)
        elif key not in ("turn_rate", "hold_ms"):
            # `hold_ms` and `turn_rate` are the viewport's, not the model's —
            # pushing them into FlightModel would invent attributes on it.
            setattr(fly["model"], key, float(value))

    def _settings_closed(self, dlg, result, old_speed, old_scale, old_labels,
                         old_flight=None):
        self._settings_dlg = None
        dlg.deleteLater()
        if result:
            self.viewport.camera.rotate_speed = dlg.rotate_speed()
            self.viewport.set_input_preset(dlg.input_preset())
            self.settings.setValue("input_preset", self.viewport.input_preset)
            self.viewport.precision_factor = dlg.precision_factor()
            self.viewport.adjust_h = dlg.adjust_hydrogens()
            self.disorder_policy = dlg.disorder_policy()
            self.settings.setValue("disorder_policy", self.disorder_policy)
            self.sg_convention = dlg.sg_convention()
            self.settings.setValue("sg_convention", self.sg_convention)
            self.undo.set_limit(dlg.undo_limit())
            self.viewport.set_atom_scale(dlg.atom_scale())
            self._set_label_scale(dlg.label_scale())
            self.settings.setValue("label_scale", dlg.label_scale())
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
            for key, value in dlg.flight_tuning().items():
                self._set_flight_tuning(key, value)
                self.settings.setValue("flight_" + key, float(value))
        else:
            self.viewport.camera.rotate_speed = old_speed
            self.viewport.set_atom_scale(old_scale)
            self._set_label_scale(old_labels)
            for key, value in (old_flight or {}).items():
                self._set_flight_tuning(key, value)

    def _set_label_scale(self, scale):
        """Live-applies while the Settings slider moves."""
        self.viewport.label_scale = max(0.1, float(scale))
        self.viewport.update()

    def on_about(self):
        QMessageBox.about(
            self, "About MoloM",
            "MoloM {}\n\nStandalone molecule viewer/builder.\n"
            "Element data + rendering rules from Avogadro 2 (BSD-3);\n"
            "import cascade and name resolver shared with ORCA Workbench.\n\n"
            "Navigation — mouse: wheel zooms, middle-drag orbits "
            "(Shift pans,\nCtrl zooms), Alt+left-drag orbits too, right-drag "
            "pans.\nTrackpad: two-finger scroll orbits (over the selected "
            "atom it\ntumbles the molecule), Ctrl+scroll zooms, Shift+scroll "
            "pans.\nSet the device under App > Settings.\n\n"
            "Click picks, dbl-click selects the molecule, left-drag "
            "box-selects.\nG moves (X/Y/Z lock, Shift+X/Y/Z plane, number = "
            "A), Shift+O ortho,\nF fit, Tab edit mode — and F3 searches every "
            "operator by name.".format(__version__))
