"""Main window: scene + outliner, menus, F3 operator palette, trajectory bar.

A thin shell over molom.core — every action is an operator registered in
core.ops (which also powers F3 search); menus/shortcuts just trigger them.
The scene (multiple molecules) lives here; the viewport renders it.
"""

import os
import time
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
from ..core import attachments as attach_mod
from ..core import blender_export as blender_mod
from ..core import build as build_mod
from ..core import cellbox
from ..core import modifiers as modifiers_mod
from ..core import (bonding, edits, input_map, internal, io, measure, project,
                    rotations)
from ..core import celledit
from ..core import flight as flight_mod
from ..core import cif as cif_mod
from ..core import animation as anim_mod
from ..core import cameras as cameras_mod
from ..core import cif_write
from ..core import packing as packing_mod
from ..core import coplanar
from ..core import spacegroups
from ..core import templates as tpl_mod
from ..core import vibrations as vib_mod
from ..core import timeline as timeline_mod
from ..core import cifsearch
from ..core import molprops
from ..core import meta as meta_mod
from ..core.camera import quat_from_mat3, quat_to_mat3
from ..core import ops as ops_mod
from ..core.ops import OperatorRegistry
from ..core.scene import Scene
from ..core.structure import Structure
from ..core import style as style_mod
from .. import resources
from ..core.undo import UndoStack
from .choice_popup import ChoicePopup
from .dialogs import (AnimationExportDialog, BlenderExportDialog,
                      ImageExportDialog,
                      MetaAtomDialog,
                      SiteOccupancyDialog,
                      CifSearchDialog, MoleculeSearchDialog,
                      OperatorSearchDialog, SettingsDialog)
from .crystal_ribbon import CrystalRibbon
from .optimize_panel import OptimizeDock, OptimizeWorker, TASK_SELECTION
from . import properties as properties_mod
from .properties import (CameraPage, CrystalPage, ModifierPage,
                         PropertiesDock, StripPage, VibrationPage)
from .timeline_panel import TimelinePanel
from .toolbar import ViewportToolbar
from .outliner import OutlinerPanel
from .periodic_table import PeriodicTablePanel
from .transform_panel import TransformDock
from .viewport import (MODE_EDIT, MODE_OBJECT, MolViewport, cell_of,
                       set_cell_pose, set_cell_reference, stored_cell_pose)

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


def _snap_fractional(frac, places=9):
    """Round a fractional coordinate back onto its exact value.

    A write-back converts Cartesian coordinates into the cell frame, and the
    round trip through a pose matrix leaves an atom that sits at exactly 0 at
    something like **-9.45e-17**. The sign is what does the damage: a tiny
    NEGATIVE fraction is on the far face of the cell, so the next expansion
    gives that site an extra boundary copy and the solid solution comes back
    as 22 atoms instead of 21 - a structure changed by floating-point noise.
    Round 45b hit the same `-0.0` in the symmetry operators.

    Nine decimals is far finer than any CIF writes (five is typical) and far
    coarser than the noise, so a real edit is untouched: dragging an atom
    0.3 A in a 10 A cell moves it 0.03 fractional, seven orders of magnitude
    above the snap. `+ 0.0` is not decoration - it turns -0.0 back into 0.0,
    which is the whole point.
    """
    return [[float(round(float(v), places)) + 0.0 for v in row]
            for row in np.asarray(frac, dtype=float).reshape(-1, 3)]


#: What each per-crystal display flag is CALLED in a status message. Without
#: it a multi-object report reads "4 crystals: show_refused_bonds on".
_FLAG_LABELS = {
    "polyhedra": "coordination polyhedra",
    "show_refused_bonds": "refused bonds",
    "show_symmetry": "symmetry elements",
    "show_ghosts": "symmetry ghosts",
}


class MainWindow(QMainWindow):

    #: What the last CIF export decided, for the status bar. On the CLASS so
    #: it exists before any export has happened — the round-34 rule.
    _cif_export_note = ""
    _cif_export_reports = ()

    #: Where the free view was before we stepped into a camera.
    _view_before_camera = None

    #: What F12 / Ctrl+F12 render when pressed again: {animation: {...}}.
    #: On the CLASS so the keys exist before any export has happened, and
    #: deliberately NOT persisted — a render key that fires at a path from
    #: last week is worse than one that asks.

    def __init__(self):
        super().__init__()
        #: Objects already warned about editing a packed crystal — the hazard
        #: is real every time, but a message on every drag drowns out
        #: everything else the status bar has to say.
        self._packed_edit_warned = set()
        self._render_target = {}
        self.setWindowTitle("MoloM")
        # Also on the window, not only on the QApplication in `__main__`: a
        # window built any other way (a test, the smoke tool, an embedder)
        # would otherwise still show the generic Python icon.
        _icon = resources.app_icon()
        if _icon is not None:
            self.setWindowIcon(_icon)
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
        #: The STRUCTURE file this session was opened from, where there is
        #: one. Distinct from `project_path`, and it is what makes the ORCA
        #: Workbench round-trip work: OWB launches `[molom, file.xyz]`, tells
        #: the user to edit and Save, and then re-reads that same file.
        self.source_path = None          # type: Optional[str]
        self._local_view = None          # {obj_id: visible} while isolated
        self._pending_suppress = False   # merge the next push into this one
        #: (obj_id, pose) captured when an edit STARTS. An edit is not a rigid
        #: motion, so the Kabsch fit that recovers a crystal's orientation
        #: absorbs part of it as a spurious rotation — which then drifts the
        #: drawn cell box and corrupts the fractional coordinates written back
        #: to the asymmetric unit. The pose before the atoms moved is the
        #: trustworthy one.
        self._pose_before_edit = None
        #: `(obj id, coords)` captured before an edit, for the rigidity test.
        self._coords_before_edit = None
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
        # The CHEMISTRY edits (element change, draw, bond order, delete) go
        # through this one, and it used to be `push_undo` alone — so round
        # 43e's "capture the pose while it can still be read" never fired for
        # any of them, only for the geometry modals above. `cell_pose` then
        # got measured AFTER the atom had moved, read the move as a rotation
        # of the whole crystal, and baked it into the cell reference: on
        # MOF-5 one H -> F tilted the box by 1.2 degrees and grew the drawn
        # cell by 144 carbons. `begin_model_edit` snapshots undo itself.
        self.viewport.on_camera_changed = self.camera_changed
        # A view rotation drops out of a camera view KEEPING the pose it
        # rotated to (round 57) — restoring the pre-camera view here would
        # undo the very gesture that caused the exit.
        self.viewport.on_camera_exit = \
            lambda restore=False: self.leave_camera(restore=restore,
                                                    message="")
        self.viewport.on_camera_look = self.on_activate_camera
        self.viewport.on_edit_begin = self.begin_chemistry_edit
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
        self.viewport.render_scale = int(
            self.settings.value("render_scale", 2))
        self.viewport.render_subdiv_bonus = int(
            self.settings.value("render_subdiv", 2))
        self.viewport.render_crop = self.settings.value(
            "render_crop", "false") in (True, "true")
        for attr in ("cell_zorder", "cell_zorder_export"):
            stored = self.settings.value(attr, "")
            if stored in cellbox.ZORDERS:
                setattr(self.viewport, attr, stored)
        #: An explicit ffmpeg path, for when there is no system one and the
        #: optional `imageio-ffmpeg` is not installed. Same shape as the
        #: Blender path hint (round 50): a stored hint, then PATH, then the
        #: usual install locations — never a hard dependency.
        self.ffmpeg_hint = self.settings.value("ffmpeg_path", "") or ""
        #: The last operator run from F3, pre-selected next time it opens.
        self._last_operator = None
        #: `(query, hits, when)` from the last crystal search, restored the
        #: next time the dialog opens. Christian, after using round 85: "it
        #: really needs to remember the results of the last search".
        #: Callables an ADD-ON page registers to be told the active molecule
        #: changed. Round 51's bug was a properties page that described the
        #: PREVIOUS molecule because nothing refreshed it on the transition;
        #: a built-in page is named in `_sync_all` by hand, and an add-on
        #: page had no way in at all.
        self.page_sync_hooks = []
        self._last_cif_search = None
        #: The last MOLECULE search, same reasoning as the crystal one: on
        #: the window rather than in a module global, so a second window (or
        #: the next test) cannot inherit somebody else's results.
        self._last_mol_search = None
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
        self.outliner.atoms_selected.connect(self._on_outliner_atoms)
        self.outliner.isolate_requested.connect(self._on_obj_isolate)
        self.outliner.style_changed.connect(self._on_obj_style)
        self.outliner.renamed.connect(self._on_obj_renamed)
        self.outliner.delete_requested.connect(self._on_obj_delete)
        self.outliner.activated.connect(self._on_obj_activated)
        self.outliner.add_requested.connect(self.on_outliner_add)
        self.outliner.camera_activated.connect(
            lambda cid: self.on_activate_camera(cid))
        self.outliner.camera_add_requested.connect(
            self.on_place_camera)
        self.outliner.camera_delete_requested.connect(
            lambda cid: self.on_delete_camera(cid))
        self.outliner.camera_renamed.connect(
            lambda cid, name: (self.scene.rename_camera(cid, name),
                               self._sync_all()))
        self.outliner.merge_requested.connect(self.on_merge_ids)
        self.outliner.crystal_view_changed.connect(self._on_crystal_row_view)
        self.outliner.crystal_box_toggled.connect(
            lambda _oid, on: self._set_cell_box(on))
        self.outliner.crystal_poly_toggled.connect(self._on_crystal_poly)
        self.outliner.comment_requested.connect(self.on_edit_comment)
        self.outliner.attachment_toggled.connect(
            self.on_attachment_toggled)
        self.outliner.attachment_lock_toggled.connect(
            self.on_attachment_lock_toggled)
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
        self.optimize_panel.species_changed.connect(
            self.on_species_changed)
        # Round 15 moved this dock's WIDGET into the properties dock as a page
        # and left the dock itself behind, parented to the window but never
        # added to a dock area. `QWidget.show()` shows every child that has not
        # been explicitly hidden, so the empty shell — title bar, close button,
        # nothing in it — floated at (0, 0) ON TOP OF THE MENU BAR, which is
        # why "File" and "Edit" read as overlapping garbage in a screenshot of
        # a fresh window. Only the page is wanted; hide the husk.
        self.optimize_panel.setVisible(False)
        self._opt_worker = None

        # Blender's properties editor: one dock, a vertical tab strip, and a
        # page per topic. The force-field panel lives in it as a page rather
        # than competing for the same edge.
        self.vibration_page = VibrationPage()
        self.vibration_page.mode_selected.connect(self.on_animate_mode)
        self.vibration_page.settings_changed.connect(self._on_mode_settings)
        self.vibration_page.load_requested.connect(self.on_load_frequencies)
        self.vibration_page.calculate_requested.connect(
            self.on_calculate_frequencies)
        self.crystal_page = CrystalPage()
        self.crystal_page.view_changed.connect(self.on_crystal_view)
        self.crystal_page.occupancy_toggled.connect(
            self._on_occupancy_display)
        self.crystal_page.outside_toggled.connect(
            lambda on: self._on_packing_option(self.active_id, "outside", on))
        self.crystal_page.copies_toggled.connect(
            lambda on: self._on_packing_option(self.active_id, "copies", on))
        self.crystal_page.box_toggled.connect(self._set_cell_box)
        self.crystal_page.cell_apply_requested.connect(self.on_apply_cell)
        self.crystal_page.cell_suggest_requested.connect(self.on_suggest_cell)
        self.crystal_page.cell_remove_requested.connect(self.on_remove_cell)
        self.crystal_page.frac_apply_requested.connect(self.on_apply_fractional)
        # Through the page's GUARDED signals, never the raw `toggled`: these
        # ticks are now written from the active object by `set_cell`, and an
        # unguarded connection reads that refresh back as the user asking for
        # it — which would carry one molecule's display state onto the next.
        self.crystal_page.poly_toggled.connect(
            lambda on: self._set_obj_flag("polyhedra", on))
        self.crystal_page.refused_toggled.connect(
            lambda on: self._set_obj_flag("show_refused_bonds", on))
        self.crystal_page.symmetry_toggled.connect(
            lambda on: self._set_obj_flag("show_symmetry", on))
        self.crystal_page.ghosts_toggled.connect(
            lambda on: self._set_obj_flag("show_ghosts", on))
        for _key, _box in self.crystal_page.kind_checks.items():
            _box.toggled.connect(lambda _on: self._sync_symmetry_kinds())
        self.strip_page = StripPage()
        self.strip_page.start_changed.connect(self.on_strip_start)
        self.strip_page.duration_changed.connect(self.on_strip_duration)
        self.strip_page.interpolate_changed.connect(
            self.on_strip_interpolate)
        self.strip_page.end_mode_changed.connect(
            self.on_strip_end_mode)
        self.strip_page.remove_requested.connect(
            self.on_strip_removed)
        self.camera_page = CameraPage()
        self.camera_page.changed.connect(lambda: self.camera_changed())
        self.camera_page.activate_requested.connect(
            lambda: self.on_activate_camera(self.scene.active_camera_id))
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
             ("camera", "🎥", "Camera — lens, frame and roll",
              self.camera_page),
             ("strip", "▤", "Animation strip — start, speed, end mode",
              self.strip_page),
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
        # BUILT ON FIRST USE. 118 painted cells cost ~640 ms to construct,
        # which was about a fifth of the whole launch - and the panel is hidden
        # at startup, because it only appears in plain edit mode. Paying for a
        # widget nobody has asked to see is the easiest kind of slow startup to
        # fix, and the laziness is invisible: `_ptable` builds it the first
        # time anything reaches for it.
        self._ptable = None
        self.viewport.on_element_changed = \
            lambda symbol: (self._ptable.set_current(symbol)
                            if self._ptable is not None else None)

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
        # LAST: an add-on's register() is handed this window and reaches
        # straight into it, so everything it might touch has to exist first.
        self._init_addons()

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
        r("save_document", "Save",
          lambda c: c.on_save(), enabled=has_obj, category="File",
          shortcut="Ctrl+S", key="Ctrl+S",
          aliases=("save project", "savepoint", "write geometry back"))
        r("save_geometry_back", "Save geometry back to the opened file",
          lambda c: c.on_save_geometry_back(),
          enabled=lambda ctx: bool(getattr(ctx, "source_path", None)),
          category="File", shortcut="Ctrl+Alt+S", key="Ctrl+Alt+S",
          aliases=("round trip", "overwrite xyz", "orca workbench"))
        r("save_project", "Save project (savepoint)",
          lambda c: c.on_save_project(), enabled=has_obj, category="File")
        r("save_project_as", "Save project as...",
          lambda c: c.on_save_project_as(), enabled=has_obj, category="File",
          shortcut="Ctrl+Shift+P", key="Ctrl+Shift+P")
        r("import_name", "Find a molecule by name (PubChem / OPSIN)...",
          lambda c: c.on_import_by_name(), category="File",
          shortcut="Ctrl+Shift+N", key="Ctrl+Shift+N")
        r("search_cif", "Find a crystal structure (COD / OPTIMADE)...",
          lambda c: c.on_search_cif(), category="File",
          shortcut="Ctrl+Shift+Alt+N", key="Ctrl+Shift+Alt+N",
          aliases=("cif", "crystal", "cod", "optimade", "search", "download"))
        r("set_cif_folder", "Crystal search: set the local CIF folder...",
          lambda c: c.on_set_cif_folder(), category="File",
          aliases=("cif", "folder", "directory", "local"))
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
        r("export_image", "Export image... (resolution, crop, transparency, "
          "labels, cell box)",
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
        r("shuttle", "Shuttle mode: pilot the selected molecule (cockpit)",
          lambda c: c.on_shuttle(), enabled=has_active, category="View",
          aliases=("fly", "pilot", "first person", "cockpit", "fps"))
        r("shuttle_chase",
          "Shuttle mode: pilot from behind (third person)",
          lambda c: c.on_shuttle(third_person=True), enabled=has_active,
          category="View",
          aliases=("fly", "pilot", "third person", "chase", "chase camera",
                   "follow", "behind"))
        r("toggle_hbonds", "Show suspected hydrogen bonds",
          lambda c: c.viewport.toggle_hbonds(), category="View",
          aliases=("h-bond", "hydrogen bonding", "contacts"))
        # Measurements persist in the viewport, so they need the three controls
        # any persistent annotation needs: hide them without losing them, get
        # them back, and bin the lot.
        r("measure_show", "Measurements: show or hide them all",
          lambda c: c.viewport.set_show_measurements(
              not c.viewport.show_measurements),
          enabled=lambda c: bool(c.viewport.measurements),
          category="View",
          aliases=("hide measurements", "show measurements", "distances",
                   "angles", "dihedral"))
        r("measure_clear", "Measurements: delete every one",
          lambda c: c.viewport.clear_measurements(),
          enabled=lambda c: bool(c.viewport.measurements
                                 or c.viewport._measure_picks),
          category="View",
          aliases=("clear measurements", "remove measurements"))
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
        r("delete_selected", "Delete selected atoms (or a measurement)",
          lambda c: c.on_delete_selected(),
          enabled=lambda c: bool(c.viewport.selection
                                 or c.viewport.has_measurement_target()),
          category="Edit",
          shortcut="Del or X", key="Del", extra_keys=("X",))
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
        # Two operators rather than one, because the choice is genuinely made
        # twice: a box that reads through the structure is a navigation aid on
        # screen and a false claim in a published still. The labels name the
        # SURFACE first, so the two sit together in the palette and neither
        # can be mistaken for the other.
        r("cell_zorder_view", "Unit cell box (Viewport): draw on top / "
          "respect depth",
          lambda c: c.on_toggle_cell_zorder(export=False), category="View",
          aliases=("z-order", "zorder", "depth", "occlude", "in front",
                   "behind", "overlay", "cell", "axes"))
        r("cell_zorder_export", "Unit cell box (Image export): draw on top / "
          "respect depth",
          lambda c: c.on_toggle_cell_zorder(export=True), category="View",
          aliases=("z-order", "zorder", "depth", "occlude", "png", "render",
                   "overlay", "cell", "axes"))
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
        r("crystal_site_occupancy",
          "Crystal: set the occupancies of a shared site",
          lambda c: c.on_site_occupancy(), enabled=has_cell,
          category="Crystal", aliases=("occupancy", "solid solution",
                                       "shared site", "mixed", "doping",
                                       "substitution", "pie", "partial"))
        r("export_animation", "Export the animation (PNG sequence or video)",
          lambda c: c.on_export_animation(),
          enabled=lambda c: c.timeline.duration > 0.0,
          category="File", shortcut="Ctrl+Shift+A", key="Ctrl+Shift+A",
          aliases=("movie", "video", "mp4", "gif", "render", "frames",
                   "trajectory", "playback", "sequence"))
        r("camera_place", "Camera: place one here (save this view)",
          lambda c: c.on_place_camera(), category="Camera",
          aliases=("view", "viewpoint", "angle", "save view", "bookmark",
                   "shot", "add camera"))
        r("camera_activate", "Camera: look through the active one",
          lambda c: c.on_activate_camera(), category="Camera",
          enabled=lambda c: bool(c.scene.cameras),
          shortcut="Numpad 0", key="Num+0",
          # With NUM LOCK OFF the numpad's 0 sends Key_Insert, not Key_0 —
          # so `Num+0` alone binds a key that half the keyboards in the world
          # never send, and the shortcut simply does nothing (Christian:
          # "Numpad 0 is also not bound"). Both spellings, the same way round
          # 55 registers both spellings of a Shift chord.
          extra_keys=("Num+Ins",),
          aliases=("view", "through", "numpad", "restore view", "exit camera",
                   "leave camera"))
        r("camera_update", "Camera: update the active one to this view",
          lambda c: c.on_update_camera(), category="Camera",
          enabled=lambda c: c.scene.active_camera() is not None,
          aliases=("re-place", "move camera", "re-aim"))
        r("camera_delete", "Camera: delete the active one",
          lambda c: c.on_delete_camera(), category="Camera",
          enabled=lambda c: c.scene.active_camera() is not None,
          aliases=("remove camera",))
        r("render_still", "Render: still image (F12)",
          lambda c: c.on_render_key(False), enabled=has_obj, category="File",
          shortcut="F12", key="F12",
          aliases=("render", "image", "png", "screenshot", "f12", "execute"))
        r("render_animation", "Render: animation (Ctrl+F12)",
          lambda c: c.on_render_key(True), enabled=has_obj, category="File",
          shortcut="Ctrl+F12", key="Ctrl+F12",
          aliases=("render", "movie", "animation", "f12", "execute"))
        # Once F12 has a remembered target it renders straight away, which is
        # the point of it — but that made the settings a ONE-WAY DOOR:
        # "there is currently no way to bring back the animation rendering
        # properties tab once it has been set." These two put the question
        # back, and the dialog now reopens showing what you last chose rather
        # than the defaults.
        r("render_settings_animation",
          "Render settings: animation (ask again / change them)",
          lambda c: c.on_render_settings(True),
          enabled=lambda c: c.timeline.duration > 0.0, category="File",
          aliases=("animation settings", "movie settings", "render properties",
                   "change settings", "reconfigure", "ask again", "gif", "mp4",
                   "fps", "framerate", "resolution", "export options"))
        r("render_settings_still",
          "Render settings: still image (ask again / change them)",
          lambda c: c.on_render_settings(False), enabled=has_obj,
          category="File",
          aliases=("image settings", "render properties", "change settings",
                   "ask again", "png", "export options"))
        r("graphics_info", "Report the graphics device (which GPU is drawing)",
          lambda c: c.on_graphics_info(), category="App",
          aliases=("gpu", "opengl", "renderer", "driver", "video card",
                   "performance", "hardware"))
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
        r("addons", "Add-ons...", lambda c: c.on_addons(), category="App",
          aliases=("plugins", "extensions", "preferences", "install",
                   "debug pipeline", "sandbox"))
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
            # A chord gets both spellings — see `ops.chord_variants`: holding
            # Shift through `Shift+Space, L` makes Qt look for `Shift+L` as
            # the second key, and nothing fires.
            variants = list(ops_mod.chord_variants(op.key))
            for extra in op.extra_keys:
                variants += ops_mod.chord_variants(extra)
            if len(variants) > 1:
                act.setShortcuts([QKeySequence(v) for v in variants])
            else:
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
        # The animation export is the most option-heavy thing in the program,
        # and it was reachable only by Ctrl+Shift+A or F3 — so anyone who does
        # not use shortcuts could not find it at all.
        self._add_op(m_file, "export_animation", "Export a&nimation...")
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
        self._add_op(m_app, "addons", "&Add-ons...")
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
        # The ∿ page can rank modes by how much they move the SELECTED atoms,
        # so it has to hear about every selection change.
        self._push_mode_selection()
        # ...and the ❖ page's fractional block edits the ONE picked atom, so it
        # has to know which (and to grey itself out when that is ambiguous).
        self._sync_fractional()
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
                # ...and every ADD-ON page, or the properties tab keeps
                # describing the molecule you clicked away from.
                self._sync_addon_pages()

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

    @staticmethod
    def packed_crystal_edit(obj):
        # type: (object) -> bool
        """Is this an edit to a PACKED crystal, where the copies won't follow?

        A packed import's boundary copies are ordinary independent atoms in
        the list — measured on ZIF-8, atom 0 has a copy at index 348 and
        moving one does not move the other — so an edit desynchronises them
        silently. The existing guards do not cover it: `begin_model_edit`
        handles the cell-box drift (round 43e) and `sync_asymmetric_unit`
        only fires when the base IS the asymmetric unit, which a packed
        import's base is not.

        Editing that way is unsupported until edits operate on the CONTENT and
        re-pack. Until then the honest thing is to SAY so — a structure that
        quietly disagrees with itself is the worst of the options.
        """
        meta = getattr(obj.structure, "metadata", None) or {}
        if not meta.get("packed"):
            return False
        content = int(meta.get("cell_content") or 0)
        return 0 < content < obj.structure.n_atoms

    def _warn_packed_edit(self, obj):
        if not self.packed_crystal_edit(obj):
            return
        if obj.id in self._packed_edit_warned:
            return
        self._packed_edit_warned.add(obj.id)
        self.statusBar().showMessage(
            "Edited a PACKED crystal: the boundary copies are separate atoms "
            "and do not follow. Switch the crystal page to \"Asymmetric unit "
            "only\" to edit the structure itself.", 15000)

    def _reevaluate_edited_crystal(self):
        """After an edit: keep the asymmetric unit, or re-derive the cell."""
        obj_id = getattr(self.viewport, "edit_obj_id", None)
        obj = self.scene.get(obj_id) if obj_id is not None else None
        if obj is None:
            obj = self._active_obj()
        if obj is None or not (obj.structure.metadata or {}).get("symops"):
            return
        self._warn_packed_edit(obj)
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
            if self._edit_was_rigid(obj):
                # A RIGID PLACEMENT IS NOT AN EDIT TO THE STRUCTURE.
                #
                # Christian's report: he selected several isostructural
                # fluorides, went to change one tick box, and CsF came back
                # as P1 with its cell frozen and the tick dead. Reproduced
                # from his savefile: a plain 0.5 A translation of a whole
                # crystal demoted `F m -3 m` to `P 1`.
                #
                # A space group describes the STRUCTURE, not where it sits in
                # world space, so moving or turning a crystal preserves it
                # exactly - and `demote_to_p1` freezes the cell as a side
                # effect (round 52), which is what made the control
                # unresponsive afterwards. Round 43e already knew that "an
                # EDIT is not a rigid motion" and captured the pose before one
                # for the cell box; this is the same distinction, applied to
                # the symmetry.
                #
                # Dragging SOME of a crystal's atoms still demotes, because
                # the fit is over all of them and a partial move is not rigid.
                return
            changed = self.demote_to_p1(obj)
        except Exception:                    # never let this break an edit
            return
        if changed:
            self._sync_crystal_page()

    def _edit_was_rigid(self, obj):
        # type: (object) -> bool
        """Were the atoms merely MOVED, or was the structure changed?

        Two questions, and the composition one comes first because an element
        change moves nothing. Then Kabsch: fit the pre-edit coordinates onto
        the post-edit ones and look at what is left. A rigid motion leaves nothing (float noise only), so
        the symmetry the file declared still holds and there is nothing to
        re-derive. Anything else - an atom dragged out of its site, an element
        changed, an atom added or deleted - leaves a residual or changes the
        count, and the demotion goes ahead.

        False whenever there is nothing to compare, so the conservative path
        (demote) is what happens when this cannot tell.
        """
        stash = self._coords_before_edit
        self._coords_before_edit = None
        if not stash or stash[0] != obj.id:
            return False
        # COMPOSITION FIRST. An element change moves no atoms at all, so a
        # coordinate-only test would call it a rigid placement and keep a
        # space group that no longer holds - caught by the test that drives
        # `set_element` rather than by reading the code.
        if (stash[2] != tuple(obj.structure.symbols)
                or stash[3] != tuple(map(tuple, obj.structure.bonds))):
            return False
        before = np.asarray(stash[1], dtype=float)
        after = np.asarray(obj.structure.coords, dtype=float)
        if before.shape != after.shape or len(before) < 3:
            return False
        bc = before - before.mean(axis=0)
        ac = after - after.mean(axis=0)
        try:
            u, _s, vt = np.linalg.svd(bc.T @ ac)
        except np.linalg.LinAlgError:
            return False
        d = np.sign(np.linalg.det(vt.T @ u.T))
        rot = vt.T @ np.diag([1.0, 1.0, d]) @ u.T
        residual = bc @ rot.T - ac
        rmsd = float(np.sqrt((residual ** 2).sum() / len(before)))
        # A real edit moves an atom by a thousandth of an Angstrom at the very
        # least; a rigid move leaves only float noise.
        return rmsd < 1e-6

    def demote_to_p1(self, obj):
        # type: (object) -> Optional[str]
        """An edit to a FULL CELL makes it P1, with the content as its unit.

        Christian's call, and the measurements back it: automatically
        re-deriving a group from edited coordinates and then REBUILDING from
        it is fragile, because the operators spglib reports and the orbits it
        reports have to reconstruct the cell exactly and nothing guarantees
        they do. Adding two carbons to MOF-5 got `R3m` with 6 operators and 7
        orbits — 42 atoms where the cell holds 424 — so the next view switch
        drew 13 atoms and called it a crystal.

        **P1, not P-1.** P-1 asserts an inversion centre through the origin,
        and an arbitrary edit preserves no such thing; writing it would make
        every downstream expansion invent a second half of the structure that
        is not there. P1 is the one group true of every arrangement of atoms,
        so it can never be wrong — and it makes the rebuild an identity,
        which is what stops the picture changing under the user.

        Deriving the real group is still available, deliberately, as
        `F3 > Crystal: re-derive the space group` — and that route now checks
        the reconstruction before it accepts an answer.
        """
        s = obj.structure
        meta = s.metadata
        cell = cell_of(obj)
        if cell is None or not meta.get("symops"):
            return None
        frac = self._crystal_fractional(obj)
        if frac is None:
            return None
        was = str(meta.get("spacegroup", ""))
        n_before = int(meta.get("cell_content") or 0)
        # Atoms ADDED land after the boundary copies, so the "first N are the
        # content" split stops meaning anything the moment the count changes —
        # the added carbons were outside the content entirely, which is why
        # they never reached the asymmetric unit. Once that happens the object
        # is a box of atoms, not a packed cell, and saying so beats keeping a
        # split that is quietly wrong.
        # NOT `cell_content != n_atoms`: those differ by design on a packed
        # crystal (424 content, 616 drawn). `packed_n` is what the packing
        # actually drew, so only that can say an atom has been added or
        # deleted since.
        drawn = int(meta.get("packed_n") or 0)
        grew = bool(drawn) and drawn != s.n_atoms
        if grew or not n_before:
            meta["cell_content"] = s.n_atoms
            meta["packed"] = False
            meta["packed_n"] = s.n_atoms
        meta["symops"] = ["x,y,z"]
        meta["spacegroup"] = "P 1"
        meta["it_number"] = 1
        meta.pop("hall", None)
        meta["symmetry_source"] = spacegroups.SOURCE_DERIVED
        # From here the ❖ contents radio stops REGENERATING this object: in
        # P1 the asymmetric unit is the cell content, so there is nothing left
        # to expand, and re-packing atoms the packing has already relocated
        # does not give the same picture back.
        meta["cell_frozen"] = True
        meta["symmetry_note"] = (
            "edited in the full cell, so the symmetry no longer holds: "
            "written as P1 with {} site(s){}".format(
                meta["cell_content"],
                " (the boundary copies are now ordinary atoms)"
                if grew else ""))
        self.resync_derived_asymmetric_unit(obj, cell, frac, identity=True)
        if was and spacegroups.canonical_key(was) != spacegroups.canonical_key(
                "P 1"):
            self.statusBar().showMessage(
                "Edited the full cell, so the symmetry no longer holds — "
                "{} is now P1 with {} site(s). F3 \"re-derive the space "
                "group\" looks for a real one.".format(was,
                                                       meta["cell_content"]),
                10000)
        return "P 1"

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
        frac = _snap_fractional(cell.to_fractional(xyz))
        if not self._write_back_shared(meta, s, frac):
            meta["asym_symbols"] = list(s.symbols)
            meta["asym_frac"] = [list(row) for row in frac]
            # One row per atom again, so the merge map describes nothing.
            # Leaving it is round 80's silent failure: it stays perfectly
            # well-formed and quietly refers to rows that are no longer there
            # - which is what deleting the last shared site does.
            meta.pop("asym_rows", None)
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
        #
        # Measured against `asym_symbols`, NOT against the drawn atom count.
        # They describe the `_atom_site_` ROWS, and once a shared site is
        # merged for display those are no longer the same number: the solid
        # solution is five rows behind two drawn atoms, so comparing with
        # `s.n_atoms` found 5 != 2 and reset `asym_occupancy` to [1.0, 1.0] -
        # flattening the composition immediately after `_write_back_shared`
        # had just rebuilt it correctly. Identical in the ordinary case,
        # where one atom is one row.
        n = len(meta.get("asym_symbols") or [])
        for key, fill in (("asym_occupancy", 1.0),
                          ("asym_disorder_groups", ""),
                          ("asym_disorder_assemblies", "")):
            values = meta.get(key)
            if values is None:
                continue
            if len(values) != n:
                meta[key] = [fill] * n
        return True

    def _write_back_shared(self, meta, s, frac):
        # type: (dict, object, object) -> bool
        """Expand the merged asymmetric unit back into one row per species.

        A CIF writes a solid solution as one `_atom_site_` row per species at
        the same coordinates, and round 87 MERGES those into a single drawn
        atom so the asymmetric unit shows the same pie sphere the full cell
        has shown since round 42. That merge is what makes this function
        necessary: the plain write-back sets `asym_symbols` from the DRAWN
        atoms, so `1547149.cif` would go from five rows to two, the parallel
        columns would no longer match, and `asym_occupancy` would be reset to
        `[1.0, 1.0]` - permanently reducing a Nb/Ti/Ni/Co solid solution to
        the pure NbO2 that round 42 exists to stop MoloM drawing. Christian's
        decision was to merge AND fix this, rather than lock the view or leave
        it showing four atoms stacked inside one another.

        Every row of a merged site takes the drawn atom's new position, and
        keeps its own element and occupancy. A DELETE is handled by the same
        walk: `asym_rows` is remapped with the atoms (see `edits.
        _PER_ATOM_LISTS`), so a deleted drawn atom simply takes its whole
        group of rows out of the rebuilt columns, and the indices are compacted
        as they are rewritten.

        Returns False when the map cannot be trusted - no shared sites, or a
        length that no longer lines up - and the caller then does the ordinary
        one-row-per-atom write.
        """
        rows = meta.get("asym_rows")
        if not rows or len(rows) != s.n_atoms:
            return False
        old_symbols = list(meta.get("asym_symbols") or [])
        if not old_symbols:
            return False
        flat = [int(r) for group in rows for r in group]
        if len(flat) == len(rows):
            return False              # nothing merged; the plain path is fine
        if any(r < 0 or r >= len(old_symbols) for r in flat):
            return False              # stale map; better none than misindexed
        columns = {}
        for key in ("asym_occupancy", "asym_disorder_groups",
                    "asym_disorder_assemblies", "asym_labels"):
            values = meta.get(key)
            if values is not None and len(values) == len(old_symbols):
                columns[key] = list(values)
        symbols, out_frac, compacted, cursor = [], [], [], 0
        for drawn, group in enumerate(rows):
            here = []
            drawn_symbol = str(s.symbols[drawn])
            for position, r in enumerate(group):
                # THE DRAWN SYMBOL WINS ON THE ROW IT REPRESENTS. A single-row
                # atom is an ordinary site, so changing its element must reach
                # the metadata exactly as it did before this round - the first
                # cut restored the stored symbol unconditionally and silently
                # discarded every element edit in the asymmetric unit, which
                # is round 43e's bug reintroduced from a new direction.
                #
                # On a MERGED site the drawn atom carries the majority
                # species (`asym_view` puts that row first), so an element
                # change there re-labels that species and leaves the others
                # and every occupancy untouched. Nothing is lost, which is the
                # test a shared-site edit has to pass.
                symbols.append(drawn_symbol if position == 0
                               else old_symbols[int(r)])
                out_frac.append(list(frac[drawn]))
                here.append(cursor)
                cursor += 1
            compacted.append(here)
        for key, values in columns.items():
            meta[key] = [values[int(r)] for r in flat]
        meta["asym_symbols"] = symbols
        meta["asym_frac"] = out_frac
        meta["asym_rows"] = compacted
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
        # ...and the COORDINATES, so the commit can tell a rigid placement
        # from a change to the structure. See `_reevaluate_edited_crystal`.
        self._coords_before_edit = (
            (obj.id, np.array(obj.structure.coords, copy=True),
             tuple(obj.structure.symbols), tuple(map(tuple, obj.structure.bonds)))
            if obj is not None else None)
        self.push_undo()

    def _edit_target(self):
        """Whichever molecule an edit is about to touch, or None."""
        obj_id = getattr(self.viewport, "edit_obj_id", None)
        obj = self.scene.get(obj_id) if obj_id is not None else None
        return obj if obj is not None else self._active_obj()

    def begin_chemistry_edit(self):
        """Permission for an edit that changes what a molecule IS.

        Returns False to REFUSE, which is the whole of the overwrite
        protection: a molecule carrying computed layers is locked, and an edit
        to its composition or connectivity has to be agreed to first. Modelled
        on ORCA Workbench, where a tick box has to be cleared before the
        information behind it can be altered.

        The dialog is not a nag. It appears only while the molecule is locked,
        it says what will be lost and what will merely stop being physical -
        which are different fates, decided per attachment (see
        `core/attachments.py`) - and agreeing to it clears the lock, so the
        rest of an editing session is uninterrupted.

        Geometry edits deliberately do not come through here: `on_model_edit_
        begin` is still wired straight to `begin_model_edit`. Moving a whole
        molecule is a rigid placement that leaves its modes exactly as valid,
        and a dialog on every grab is a dialog nobody reads.
        """
        obj = self._edit_target()
        if obj is not None and attach_mod.is_locked(obj):
            if not self._confirm_unlock(obj):
                return False
            attach_mod.set_locked(obj, False)
        self.begin_model_edit()
        if obj is not None:
            # Marked HERE, after the undo snapshot `begin_model_edit` just
            # pushed, so Ctrl+Z restores a molecule whose layers are intact
            # rather than one that is still flagged unphysical.
            dropped, flagged = attach_mod.note_edit(
                obj, attach_mod.KIND_CHEMISTRY)
            if dropped or flagged:
                self._announce_attachment_change(obj, dropped, flagged)
        return True

    def _confirm_unlock(self, obj):
        # type: (object) -> bool
        """The "you are about to make this unphysical" dialog."""
        from PySide6.QtWidgets import QMessageBox
        table = attach_mod.attachments_of(obj)
        lost = sorted(a.label for a in table.values()
                      if a.policy == attach_mod.POLICY_VOLATILE)
        kept = sorted(a.label for a in table.values()
                      if a.policy != attach_mod.POLICY_VOLATILE and not a.stale)
        bits = []
        if lost:
            bits.append("{} will be DISCARDED - it cannot survive a change to "
                        "the structure and is meant to be recomputed.".format(
                            ", ".join(lost)))
        if kept:
            bits.append("{} will be KEPT but marked as no longer physical: it "
                        "was computed for this molecule as it stands, and will "
                        "say so wherever it is shown or exported.".format(
                            ", ".join(kept)))
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Edit a protected molecule?")
        box.setText("{} is protected because it carries computed data.".format(
            obj.name))
        box.setInformativeText("\n\n".join(bits) if bits else
                               "Its computed layers will be affected.")
        unlock = box.addButton("Unlock and edit", QMessageBox.AcceptRole)
        box.addButton("Cancel", QMessageBox.RejectRole)
        box.setDefaultButton(unlock)
        box.exec()
        return box.clickedButton() is unlock

    def _announce_attachment_change(self, obj, dropped, flagged):
        table = attach_mod.attachments_of(obj)
        bits = []
        if dropped:
            bits.append("{} discarded".format(len(dropped)))
        if flagged:
            bits.append("{} no longer physical".format(
                ", ".join(sorted(table[k].label for k in flagged
                                 if k in table))))
        self.statusBar().showMessage(
            "{}: {}".format(obj.name, "; ".join(bits)), 8000)
        self._sync_outliner()

    # ------------------------------------------------- attachment tick boxes
    def on_edit_comment(self, obj_id):
        """A plain-text note on a molecule, which follows it into exports.

        Kept in `Structure.metadata["comment"]`, so it rides undo and
        savepoints with no new bookkeeping (round 43's pattern) - and lands in
        the .xyz COMMENT LINE, which is the one place every downstream tool
        already looks and nobody has to be taught about.
        """
        from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel,
                                       QPlainTextEdit, QVBoxLayout)
        obj = self.scene.get(obj_id)
        if obj is None:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Comment - {}".format(obj.name))
        dlg.resize(520, 300)
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel(
            "Notes on <b>{}</b>. Written to the comment line of an exported "
            ".xyz.".format(obj.name)))
        edit = QPlainTextEdit(
            str((obj.structure.metadata or {}).get("comment", "")))
        edit.setPlaceholderText(
            "e.g. PM7 optimised, charge -2; ligand geometry taken from "
            "1ABC.cif")
        lay.addWidget(edit, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                   | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        lay.addWidget(buttons)
        if dlg.exec() != QDialog.Accepted:
            return
        self.push_undo()
        text = edit.toPlainText().strip()
        if text:
            obj.structure.metadata["comment"] = text
        else:
            obj.structure.metadata.pop("comment", None)
        self._sync_all()
        self.statusBar().showMessage(
            "Comment {} on {}".format("saved" if text else "cleared",
                                      obj.name), 5000)

    def on_attachment_toggled(self, obj_id, key, visible):
        obj = self.scene.get(obj_id)
        att = attach_mod.attachments_of(obj).get(key) if obj else None
        if att is None:
            return
        att.visible = bool(visible)
        self.viewport.refresh_geometry()

    def on_attachment_lock_toggled(self, obj_id, locked):
        obj = self.scene.get(obj_id)
        if obj is not None:
            attach_mod.set_locked(obj, bool(locked))

    def set_modes(self, obj, modes, detail=""):
        """Store normal modes AND register them as an attachment.

        One place, so the three routes that can produce modes - opening a FREQ
        file, the F3 loader, and the MOPAC add-on - cannot disagree about
        whether the molecule is protected or how it is labelled.

        `toggleable=False`: modes are a data source for the animation, not a
        layer painted over the molecule, so a visibility tick would have
        nothing to do. They still belong in the row, because the lock and the
        unphysical marking are exactly what they need.
        """
        self._modes[obj.id] = modes
        real = [m for m in modes if not m.is_trivial]
        attach_mod.attach(obj, attach_mod.Attachment(
            "modes", "Modes", policy=attach_mod.POLICY_FRAGILE,
            toggleable=False,
            detail=detail or "{} vibrational modes".format(len(real))))
        self._sync_outliner()

    def _sync_outliner(self):
        try:
            self.outliner.sync(self.scene, self.active_id)
        except Exception:
            pass

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
        # THE INVENTED CELL IS WRITTEN TO METADATA, not kept privately on the
        # modifier. Christian: "I have no idea what the cell/box limits are and
        # where the center of inversion actually lies" - and he could not,
        # because a cell known only to the modifier is a cell the viewport
        # cannot draw a box for, the ❖ page cannot report, and
        # `on_add_modifier`'s boundary branch reads as absent (which is why
        # "the boundary bonds modifier doesn't add at all"). Making it a real
        # cell makes all three work with no special cases.
        if not meta.get("cell"):
            obj.structure.metadata["cell"] = cell
            obj.structure.metadata.setdefault("symops", ["x,y,z"])
            obj.structure.metadata.setdefault("spacegroup", "P 1")
            self.viewport.show_cell = True
        return modifiers_mod.SymmetryModifier(
            cell=obj.structure.metadata.get("cell") or cell,
            symops=list(obj.structure.metadata.get("symops") or ["x,y,z"]),
            origin=origin)

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
                    dup.adjust_hydrogens(
                        list(range(dup.structure.n_atoms)))
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
                    dup.adjust_hydrogens(
                        list(range(dup.structure.n_atoms)))
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

    # ------------------------------------------------- animation strips
    def _selected_strip(self):
        obj_id = getattr(self.traj_bar.rows, "selected", None)
        if obj_id is None:
            return None, None
        return obj_id, self.timeline.get(obj_id)

    def on_strip_selected(self, obj_id):
        """Show the selected strip on its page. -1 means nothing selected."""
        if obj_id is None or int(obj_id) < 0:
            self.strip_page.set_strip(None, None, "")
            return
        obj = self.scene.get(int(obj_id))
        self.strip_page.set_strip(int(obj_id),
                                  self.timeline.get(int(obj_id)),
                                  obj.name if obj is not None else "",
                                  fps=self.timeline.fps)

    def _sync_strip_page(self):
        obj_id, track = self._selected_strip()
        obj = self.scene.get(obj_id) if obj_id is not None else None
        self.strip_page.set_strip(obj_id, track,
                                  obj.name if obj is not None else "",
                                  fps=self.timeline.fps)

    def on_strip_start(self, obj_id, start):
        track = self.timeline.get(int(obj_id))
        if track is not None:
            track.start = float(start)
            self._apply_timeline()
            self._sync_traj_bar()
            self._sync_strip_page()

    def on_strip_duration(self, obj_id, seconds):
        """The strip's length in SECONDS - its only playback knob.

        Seconds because that is what a person means (round 78); the clock
        still counts frames, and `set_duration` is the one place the two meet.
        It goes through `set_frames`, which marks the length as CHOSEN: a
        later re-sync - re-baking the mode at a different sample count, say -
        must not quietly replace a number the user picked with the default
        for the new data.
        """
        if self.timeline.set_duration(int(obj_id), float(seconds)) is not None:
            self._apply_timeline()
            self._sync_traj_bar()
            self._sync_strip_page()

    def on_strip_interpolate(self, obj_id, on):
        """Blend between the source frames, or step from one to the next."""
        track = self.timeline.get(int(obj_id))
        if track is not None:
            track.interpolated = bool(on)
            self._apply_timeline()
            self._sync_strip_page()

    def on_strip_end_mode(self, obj_id, mode):
        track = self.timeline.get(int(obj_id))
        if track is not None:
            track.end = str(mode)
            self._apply_timeline()
            self._sync_traj_bar()

    def on_strip_removed(self, obj_id):
        """Take a strip off the player. THE FRAMES STAY: this is the
        animation's track, not the molecule's data."""
        self.timeline.exclude(int(obj_id))
        self.traj_bar.rows.selected = None
        self.strip_page.set_strip(None, None, "")
        self._sync_traj_bar()
        obj = self.scene.get(int(obj_id))
        self.statusBar().showMessage(
            "{} removed from the player - its frames are untouched".format(
                obj.name if obj is not None else obj_id), 6000)

    def on_species_changed(self, charge, multiplicity):
        """Write the panel's charge/spin onto the ACTIVE molecule.

        They live in `Structure.metadata`, so they ride undo and savepoints for
        free (round 43's pattern) and `Structure.charge` picks them up with no
        second source of truth.
        """
        obj = self._active_obj()
        if obj is None:
            return
        meta = obj.structure.metadata
        meta["charge"] = int(charge)
        meta["multiplicity"] = max(1, int(multiplicity))
        obj.structure.charge = int(charge)
        obj.structure.multiplicity = max(1, int(multiplicity))

    def sync_species_panel(self):
        """Show whichever molecule is active - called from `_sync_all`."""
        obj = self._active_obj()
        if obj is None:
            return
        self.optimize_panel.show_species(
            getattr(obj.structure, "charge", 0),
            getattr(obj.structure, "multiplicity", 1))

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
        # RESTORE the spec geometry before freezing it. Christian: "the bonds
        # do not keep the length they are set with. They become incredibly
        # short." A previous run could leave the sphere collapsed (see below),
        # and freezing a collapsed sphere just preserves the damage — the whole
        # promise of a locked meta atom is that the distance you set is the
        # distance you get, so it is re-asserted here rather than assumed.
        symbols = list(s.symbols)
        if frozen_meta:
            for index in meta_mod.all_meta(s):
                spec = meta_mod.get_meta(s, index)
                if spec is not None and spec.locked:
                    meta_mod.idealize(s, index, spec)
            # And the force field is handed the element the centre STANDS FOR,
            # never the `Xx` dummy. Both RDKit tiers refuse an unknown element
            # outright ("mmff94: unknown element 'Xx'", "uff: unknown element
            # 'Xx'"), so every meta complex fell through to OpenBabel UFF —
            # which, until now, ignored `fixed` entirely. That combination is
            # what collapsed the coordination sphere to 0.655 A on Christian's
            # meta-test file: nothing was frozen and the dummy had no radius.
            symbols = meta_mod.resolved_symbols(s)
        self.optimize_panel.set_running(
            True, "Running {} on {}{}...".format(
                method, obj.name,
                " (holding {} meta centre(s))".format(
                    len(meta_mod.all_meta(s))) if frozen_meta else ""))
        self._opt_target = obj.id
        self._opt_worker = OptimizeWorker(symbols, s.coords.copy(),
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

    def on_shuttle(self, third_person=False):
        obj = self._active_obj()
        if obj is None:
            return
        self.viewport.start_shuttle(obj.id, third_person=third_person)

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
        """Export a still, through the one dialog that owns every option.

        There used to be no dialog here at all - a bare file picker - while
        the settings that decide what comes out lived in App > Settings and
        the cell-box z-order only in F3. So the export asked one question and
        silently obeyed four answers given somewhere else. Christian: "we need
        a straight-forward way of setting all these rendering options for
        simple PNG exports that do not conflict with each other."
        """
        start = self.settings.value("last_dir", "")
        base = (os.path.splitext(os.path.basename(self.project_path))[0]
                if self.project_path else "molom")
        remembered = (self._render_target.get(False) or {}).get("opts")
        dlg = ImageExportDialog(
            self, self.viewport,
            path=os.path.join(start, base + ".png"),
            remembered=remembered)
        if not dlg.exec():
            return
        opts = dlg.options()
        if not self._write_still(opts, opts["path"]):
            return
        self.settings.setValue("last_dir", os.path.dirname(opts["path"]))
        # F12 from here on renders straight to the next free name, with THESE
        # options - not with whatever App > Settings happens to hold.
        self._render_target[False] = {"path": opts["path"],
                                      "increment": opts["increment"],
                                      "opts": opts}

    def _write_still(self, opts, path):
        # type: (dict, str) -> bool
        """Render and save one image. The ONE place a still is produced.

        Both routes come here - the dialog and F12 - so a repeat cannot
        quietly differ from the export that set it up, which is half of what
        made the old behaviour confusing.
        """
        vp = self.viewport
        keep = vp.cell_zorder_export
        vp.cell_zorder_export = (cellbox.DEPTH if opts.get("cell_depth", True)
                                 else cellbox.OVERLAY)
        try:
            image = vp.render_image(
                scale=int(opts.get("scale", vp.render_scale)),
                subdiv_bonus=int(opts.get("subdiv", vp.render_subdiv_bonus)),
                transparent=bool(opts.get("transparent", True)),
                furniture=bool(opts.get("labels", False)),
                crop_to_content=bool(opts.get("crop", False)),
                crop_margin=int(opts.get("margin", 16)))
        except Exception as exc:            # driver without FBO support, etc.
            # The fallback is a VIEWPORT grab, which obeys `cell_zorder` and
            # not `cell_zorder_export` - so it can differ from every other
            # export. Said out loud rather than left to be discovered.
            self.statusBar().showMessage(
                "High-quality render failed ({}) - grabbed the viewport "
                "instead, so it looks exactly like the screen".format(exc),
                9000)
            image = vp.grabFramebuffer()
        finally:
            vp.cell_zorder_export = keep
        if not image.save(path):
            QMessageBox.critical(self, "Export failed",
                                 "Could not write {}".format(path))
            return False
        self.statusBar().showMessage(
            "Wrote {} ({}x{}) — F12 renders the next one".format(
                os.path.basename(path), image.width(), image.height()), 8000)
        return True

    # ------------------------------------------------------------ Blender
    #: Export options that are worth remembering between sessions. The camera
    #: and the resolution are NOT among them: those follow the viewport, and
    #: restoring last week's resolution over today's window is never right.
    _BLENDER_KEYS = ("hdri", "hdri_strength", "hdri_rotation", "hdri_visible",
                     "lights", "light_strength", "roughness",
                     "metallic_metals", "sphere_subdivisions", "bond_sides",
                     "shade_smooth", "unit_cell", "polyhedra",
                     "polyhedra_alpha", "output", "blender_exe", "engine",
                     "samples", "view_transform", "look", "clear_scene", "collection",
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
        """Pre-configure, then write a .blend — or the build script.

        Round 37 wrote a script because a .blend needs Blender itself. It
        does, so the export INVOKES it: the script is built as before and run
        headlessly with `--save`, which means the saved scene is already
        complete and F12 renders it (Christian: "I don't like having to load
        it in every time"). No auto-run, no trust prompt. The script remains
        an option — it is diffable, editable, and needs no Blender at all.
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
                                  (vp.width(), vp.height()), scene=self.scene)
        if not dlg.exec():
            return
        opts = dlg.options()
        self._render_camera_id = dlg.render_camera_id()
        opts.atom_scale = vp.atom_scale
        for key in self._BLENDER_KEYS:
            self.settings.setValue("blender_" + key, getattr(opts, key))
        base = (os.path.splitext(os.path.basename(self.project_path))[0]
                if self.project_path else (vis[0].name or "molom"))
        start = self.settings.value("last_dir", "")
        blend = opts.output == "blend" and bool(opts.blender_exe)
        suffix = ".blend" if blend else ".py"
        path, _f = QFileDialog.getSaveFileName(
            self, "Export to Blender",
            blender_mod.default_path(start, base, suffix),
            "Blender file (*.blend)" if blend
            else "Blender Python script (*.py);;All files (*)")
        if not path:
            return
        try:
            script_path = (os.path.splitext(path)[0] + "_build.py" if blend
                           else path)
            source = self.blender_script(opts, os.path.basename(script_path))
        except Exception as e:
            QMessageBox.critical(self, "Export failed", str(e))
            return
        try:
            # UTF-8 explicitly: Blender reads scripts as UTF-8, and Windows
            # would otherwise write cp1252 and hand it a byte it refuses.
            with open(script_path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(source)
        except OSError as e:
            QMessageBox.critical(self, "Export failed",
                                 "Could not write {}\n{}".format(script_path,
                                                                 e))
            return
        self.settings.setValue("last_dir", os.path.dirname(path))
        if not blend:
            self.statusBar().showMessage(
                "Wrote {} - open it in Blender's Scripting workspace and press "
                "Run".format(os.path.basename(path)), 10000)
            return
        self.statusBar().showMessage("Building {} in Blender...".format(
            os.path.basename(path)))
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            ok, out = blender_mod.write_blend(opts.blender_exe, script_path,
                                              path)
        finally:
            QApplication.restoreOverrideCursor()
        if not ok:
            # The script is still on disk and still valid, so say so — the
            # user can run it by hand rather than having to export again.
            QMessageBox.warning(
                self, "Blender could not build the file",
                "The build script was written to\n{}\n\nBut Blender did not "
                "produce the .blend:\n\n{}".format(
                    script_path, out[-2000:] if out else "no output"))
            return
        self.statusBar().showMessage(
            "Wrote {} - open it and press F12. The build script is beside it "
            "as {}".format(os.path.basename(path),
                           os.path.basename(script_path)), 12000)

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
            camera_id=getattr(self, "_render_camera_id", blender_mod._ACTIVE),
            width=options.resolution[0], height=options.resolution[1],
            # ALWAYS the cell lookup, whatever the box option says: the
            # polyhedra need it to build from the periodic graph, and gating
            # it on the box tick would silently make them fall back to the
            # drawn bonds and come out open.
            cell_of=cell_of)
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

    @staticmethod
    def _smiles_symbols(obj):
        """The element list to hand a CHEMISTRY tool, with meta dummies
        resolved to what they stand for.

        `Xx` has atomic number 0, so RDKit refuses it outright and the whole
        SMILES fails with "unknown element 'Xx'" - Christian: "Copy SMILES does
        not work on structures with meta atoms". A meta centre already declares
        the element it becomes on export, and that is the only sensible answer
        here too: a SMILES is a statement about chemistry, and a placeholder is
        not an element. Same fix as the force field's (round 62), and the same
        one function answers both.
        """
        return meta_mod.resolved_symbols(obj.structure)

    def on_copy_smiles(self):
        obj = self._selected_object()
        if obj is None or obj.structure.n_atoms == 0:
            return
        smiles, err = io.structure_to_smiles(self._smiles_symbols(obj),
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
        smiles, err = io.structure_to_smiles(self._smiles_symbols(obj),
                                             obj.structure.bonds)
        if smiles is None:
            QMessageBox.warning(self, "Name lookup", err or "no SMILES")
            return
        self.statusBar().showMessage(
            "Looking {} up on PubChem...".format(smiles), 4000)
        QApplication.processEvents()
        # Imported HERE, not at module scope: it pulls in urllib/http/email,
        # about 130 ms, for a lookup most launches never make.
        from ..core import resolve as resolve_mod
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
        self.sync_species_panel()
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
        # ...and the ❖ page itself, which round 34's comment above NAMES and
        # then did not call — only the ribbon and the modifier page were.
        # So an import left the whole page describing the PREVIOUS molecule,
        # every per-crystal tick with it. That is Christian's "the
        # coordination polyhedra tickbox needs to be cycled to show polyhedra
        # even though it is on": the box carried the last structure's state,
        # so his first click was the one that finally set the flag on this
        # one. Same for the symmetry tick.
        self._sync_crystal_page()
        self.camera_page.set_camera(self.scene.active_camera())
        self._sync_crystal_ribbon()
        self._sync_addon_pages()

    def _sync_addon_pages(self):
        """Tell every add-on page which molecule is active now.

        **Called from every path that changes the active object**, not only
        from `_sync_all`. Round 90 wired it into `_sync_all` alone, which
        covers imports and scene changes and NOT selection - so clicking a
        different molecule left the properties page describing the previous
        one, and its Fetch button acting on the previous one. That is round
        51's bug exactly ("a page not refreshed on the very same transition"),
        reintroduced in the hook built to prevent it.
        """
        active = self._active_obj()
        for hook in list(self.page_sync_hooks):
            try:
                hook(active)
            except Exception as exc:            # noqa: BLE001
                # One add-on page must not take the whole scene sync with it.
                # Reported rather than swallowed: a page that silently stops
                # updating is round 51's bug from the other side.
                self.statusBar().showMessage(
                    "An add-on page failed to refresh: {}".format(exc), 8000)

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
        # A CRYSTAL's bonds come from the labelled periodic graph instead:
        # perception measures straight lines, so every bond crossing a cell
        # face is missing, and an atom drawn twice at opposite faces ends up
        # sharing one coordination sphere between its two copies (ZIF-8's Zn
        # came out 3-coordinate on all twelve). The perception above still
        # runs, because it is what reports the refusals below — the graph
        # replaces the connectivity, not the chemistry.
        cell_dict = s.metadata.get("cell")
        content = int(s.metadata.get("cell_content") or 0)
        cell = None
        if cell_dict and content:
            try:
                cell = cif_mod.Cell.from_dict(cell_dict)
            except (KeyError, TypeError, ValueError, cif_mod.CifError):
                cell = None
        packed = s.metadata.pop("packed_bonds", None)
        if packed is not None:
            # The packing already instantiated the bonds from the periodic
            # graph over exactly these atoms — including the ones it
            # materialised outside the wall, which no straight-line pass over
            # this coordinate array could get right.
            s.bonds = sorted({(min(int(i), int(j)), max(int(i), int(j)),
                               int(o)) for i, j, o in packed})
        elif cell is not None:
            s.bonds = cif_mod.display_bonds(s.symbols, s.coords, cell, content,
                                            existing=s.bonds)
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
            # Which PROGRAM wrote it is decided by the header, not by the
            # extension: both ORCA and MOPAC write `.out`, so the suffix says
            # nothing. Each parser's own header is the discriminator.
            if "VIBRATIONAL FREQUENCIES" in text:
                modes = vib_mod.parse_orca_frequencies(
                    text, n_atoms=obj.structure.n_atoms)
            elif vib_mod.MOPAC_FREQ_HEADER in text:
                modes = vib_mod.parse_mopac_frequencies(
                    text, n_atoms=obj.structure.n_atoms)
            else:
                return None
        except (vib_mod.VibrationError, OSError, ValueError):
            return None                  # a geometry-only job: nothing to add
        self.set_modes(obj, modes)
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

    def _on_outliner_atoms(self, picks):
        """Outliner row selection -> viewport selection.

        The list arrives as `(obj_id, atom)` pairs, which is exactly what the
        viewport's selection already is, so there is nothing to translate.
        The ACTIVE object follows the first pick for the same reason a
        viewport click sets it (round 7): Tab should edit what you just
        selected, not whatever happened to be active before.
        """
        picks = [(int(o), int(i)) for o, i in picks or []]
        self.viewport.set_selection(picks)
        if picks and picks[0][0] != self.active_id:
            self.active_id = picks[0][0]
            self._sync_traj_bar()
            self._sync_transform_panel()
            self._sync_modifier_page()
            self._sync_crystal_ribbon()
            self._sync_addon_pages()
        self._update_counts()
        self.viewport.update()

    def _on_obj_activated(self, obj_id):
        """Outliner row click: make active AND select the molecule's atoms
        (Blender: clicking an object in the outliner selects it)."""
        self.active_id = obj_id
        self.viewport.select_whole_molecules([obj_id])
        self._sync_traj_bar()
        self._update_counts()
        self._sync_transform_panel()
        self._sync_addon_pages()
        # Also refreshes the crystal page AND greys its tab for the new
        # active molecule — without this the page kept describing whichever
        # object happened to be active when the dock was last opened.
        self._sync_modifier_page()
        self._sync_crystal_ribbon()

    # -------------------------------------------------------- trajectory bar
    def _build_trajectory_bar(self):
        """The timeline pane: transport bar + expandable per-track rows."""
        self.traj_bar = TimelinePanel(self)
        self.traj_bar.strip_selected.connect(self.on_strip_selected)
        self.traj_bar.strip_removed.connect(self.on_strip_removed)
        self.traj_bar.play_pause.connect(self.on_play_pause)
        self.traj_bar.seek_requested.connect(self.on_seek)
        self.traj_bar.fps_changed.connect(self._on_fps_changed)
        self.traj_bar.range_changed.connect(self._on_range_changed)
        self.traj_bar.fit_range_requested.connect(self._on_fit_range)
        self.traj_bar.tracks_changed.connect(self._on_tracks_edited)
        self.traj_bar.setVisible(False)
        # kept as aliases so the older call sites keep reading naturally
        self._play_btn = self.traj_bar.play_btn
        self._frame_label = self.traj_bar.label
        self._fps_spin = self.traj_bar.fps_spin
        # The framerate persists: it describes how YOU like to watch an
        # animation, not anything about the file that happens to be open.
        # What used to sit beside it - the global smoothing - is now each
        # STRIP's own frame count, so it belongs to the scene and rides
        # the savefile rather than a preference.
        self.timeline.fps = float(self.settings.value(
            "playback_fps", timeline_mod.DEFAULT_FPS))

    def _on_fps_changed(self, fps):
        self.timeline.fps = float(fps)
        self.settings.setValue("playback_fps", int(fps))
        if self._play_timer.isActive():
            self._play_timer.setInterval(int(1000 / max(int(fps), 1)))

    def _on_range_changed(self, first, last):
        """Frame Start / Frame End, in scene frames exactly as typed.

        An end ON the last frame of the content means "follow the scene",
        so a trajectory that grows later stays fully covered rather than
        being cut off at whatever the range happened to say when it was
        shorter.
        """
        end = float(last)
        self.timeline.set_range(
            float(first),
            None if end >= self.timeline.duration - 1e-9 else end)
        self._apply_timeline()

    def _on_fit_range(self):
        """Bring every strip into the play range.

        The range is fitted once and then left alone, so that arranging
        strips cannot move it (round 78) - which leaves exactly one gap:
        a trajectory imported later sits outside it. This is that gap,
        closed as a deliberate action rather than as a side effect.
        """
        self.timeline.fit_range()
        self._apply_timeline()
        self.statusBar().showMessage(
            "Frame range fitted to the strips: {:g} - {:g}".format(
                self.timeline.play_start, self.timeline.play_end), 5000)

    def _on_tracks_edited(self):
        """A strip was dragged, toggled or had its end mode cycled.

        The strip PAGE has to follow: dragging a bar changes the same Start
        the page shows, and a page still displaying where the strip used to be
        is worse than one showing nothing - Christian: "Moving the strip
        manually does not seem to update the start number in the strip pane".
        """
        self._apply_timeline()
        self._sync_strip_page()

    def on_seek(self, time):
        self.timeline.seek(float(time))
        self._apply_timeline()

    def _sync_traj_bar(self):
        """Reconcile the scene clock with the scene, then the pane with it.

        The pane is the SCENE playhead, not the active molecule's frame
        index — every trajectory in the scene runs off it at once.
        """
        self.timeline.sync([(o.id, o.structure.n_frames,
                             timeline_mod.frames_are_cyclic(o.structure))
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

    #: How often the playback timer wakes up, in ms. It is NOT the frame
    #: interval: the clock is advanced by elapsed WALL TIME, so the timer only
    #: has to wake often enough to land near each frame boundary. Oversampling
    #: is what makes 60 fps possible on Windows at all - see `_advance_frame`.
    _PLAY_TICK_MS = 4

    def on_play_pause(self):
        if self._play_timer.isActive():
            self._play_timer.stop()
            self.timeline.playing = False
            self._play_btn.setText(">")
        else:
            self.timeline.playing = True
            self._play_clock = time.perf_counter()
            self._play_timer.setTimerType(Qt.PreciseTimer)
            self._play_timer.start(self._PLAY_TICK_MS)
            self._play_btn.setText("||")

    def _advance_frame(self):
        """Advance the clock by however much WALL TIME has actually passed.

        **The framerate used to be a lie, and this is why** (round 78).
        Playback ran one frame per timer tick at `int(1000 / fps)` ms, which
        for 60 fps is 16 ms - and Windows' default timer granularity is
        ~15.6 ms, so a 16 ms timer does not fire at 16 ms, it fires at 31.2.
        Sixty frames took **1.87 s instead of 1.00**, which is exactly the
        "~2 seconds" Christian counted. Any per-tick scheme has the same
        problem the moment a repaint costs more than a frame: the animation
        does not drop frames, it slows down, and the number in the box stops
        meaning anything.

        So the timer is only a wake-up (`_PLAY_TICK_MS`, well under a frame)
        and the STEP comes from `perf_counter`. The remainder is carried
        rather than discarded, so the error cannot accumulate. If a frame
        cannot be drawn in time the playhead skips one, which is what every
        player does and what keeps a rendered animation and a previewed one
        the same length.
        """
        if not self.timeline.has_animation:
            self._play_timer.stop()
            self.timeline.playing = False
            return
        fps = float(self._fps_spin.value())
        self.timeline.fps = fps
        now = time.perf_counter()
        elapsed = now - getattr(self, "_play_clock", now)
        steps = int(elapsed * fps)
        if steps <= 0:
            return                      # not a frame's worth yet; draw nothing
        self._play_clock += steps / fps
        self.timeline.advance_frames(steps)
        self._apply_timeline()

    def _apply_timeline(self):
        """Push the playhead onto every object, then repaint ONCE.

        Bonds are re-perceived only when an object's nearest INTEGER frame
        changes, never per interpolated tick: connectivity is a property of
        the frame, and re-running perception 30 times a second would dominate
        playback cost for no visible gain.
        """
        for obj in self.scene.objects:
            position = self.timeline.frame_for(obj.id)
            if position is None or obj.structure.n_frames < 2:
                obj.play_position = None
                continue
            obj.play_rigid = self._rigid_interp
            # Interpolation is no longer a global switch: a strip either
            # is longer than its data, in which case there is something
            # between the frames to draw, or it is not, in which case the
            # position lands on whole frames anyway and the blend is a
            # no-op. So the position is simply always handed over.
            track = self.timeline.get(obj.id)
            obj.play_cyclic = bool(track is not None and track.cyclic)
            # How MANY pictures there are follows from the strip's duration
            # and the framerate; all that is left to say is what happens
            # between two source frames - blend, or hold the nearer one.
            obj.play_position = (position if track is None
                                 or track.interpolated else None)
            # A cyclic strip runs up to (but never reaches) n, so the
            # nearest stored frame of a position just short of the end is
            # frame 0 again - not a frame past the end of the list.
            nearest = int(round(position))
            if obj.play_cyclic:
                nearest %= obj.structure.n_frames
            if nearest != obj.structure.current_frame:
                obj.structure.set_frame(nearest)
                if bonding.bonds_are_fixed(obj.structure):
                    continue     # a vibration is one molecule at every phase
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
    def _install_smiles_batch(self, pairs, src, extras=None):
        # type: (List, str, Optional[List[dict]]) -> None
        """Build every (smiles, name) pair into its own scene object.

        SMILES geometry is GENERATED, so it may be normalised freely (unlike
        measured file imports, which are never silently transformed): each
        molecule is aligned largest-planar-part-to-XY and centred, then the
        batch is spread along +Z with 2 A of bounding-sphere clearance —
        dot-separated ChemDraw multi-copies land side by side, not on top of
        each other. One undo entry for the whole batch."""
        built, failed = [], []
        extras = list(extras or [])
        for index, (smiles, name) in enumerate(pairs):
            try:
                atoms, method = io.smiles_to_xyz(smiles)
            except io.CoordGenError as e:
                failed.append((smiles, str(e)))
                continue
            meta = {"smiles": smiles, "source": method}
            # Whatever the caller knows about this compound and the
            # coordinates do not: the provenance line and, where a search
            # found it, its identity record. Merged rather than assigned so
            # `smiles` and `source` above stay authoritative about how the
            # GEOMETRY was made.
            if index < len(extras):
                meta.update(extras[index] or {})
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
                "orthographic": bool(cam.orthographic),
                # WHICH camera you were looking through, so reopening a file
                # puts you back in the shot rather than in a free view that
                # merely happens to sit where the shot was. The pose above is
                # not enough: a camera view also constrains the frame, the
                # lens and what a render will produce.
                "looking_through": self.viewport.looking_through,
                "selected_camera": self.viewport.selected_camera_id}

    def _modes_state(self):
        """Normal modes, per object, for the savefile.

        They lived only on the window, so a `.molom` carrying a molecule with
        a whole FREQ job attached reopened with the ∿ page empty and no way to
        tell that anything had been lost. Written as plain lists because the
        savefile is JSON (round 6); a mode is a frequency plus 3N floats, so
        even a large job costs a few hundred kB - far less than the frames the
        file already carries.
        """
        out = {}
        for obj_id, modes in (self._modes or {}).items():
            if not modes:
                continue
            out[str(obj_id)] = [
                {"index": m.index, "wavenumber": m.wavenumber,
                 "intensity": m.intensity,
                 "intensity_unit": getattr(m, "intensity_unit", "km/mol"),
                 "symmetry": getattr(m, "symmetry", None),
                 "displacements": [[float(c) for c in row]
                                   for row in m.displacements]}
                for m in modes]
        return out

    def _restore_modes(self, data):
        for key, entries in (data or {}).items():
            try:
                obj_id = int(key)
            except (TypeError, ValueError):
                continue
            obj = self.scene.get(obj_id)
            if obj is None:
                continue
            modes = [vib_mod.Mode(
                e.get("index", i), e.get("wavenumber", 0.0),
                e.get("displacements") or [],
                intensity=e.get("intensity"),
                intensity_unit=e.get("intensity_unit", "km/mol"),
                symmetry=e.get("symmetry"))
                for i, e in enumerate(entries)]
            if modes:
                self.set_modes(obj, modes)

    def _ui_state(self):
        return {"style": self.viewport.style.key,
                "labels_element": self.viewport.show_labels_element,
                "labels_index": self.viewport.show_labels_index,
                "grid": self.viewport.show_grid,
                "draw_element": self.viewport.draw_element,
                "active_id": self.active_id,
                # The player. It was never written before, which cost
                # nothing while a strip only carried a start and a speed
                # nobody set - but round 77 made a strip's LENGTH the
                # number you tune by hand until the motion looks right,
                # and losing that on save is losing the work.
                "timeline": self.timeline.to_dict(),
                "modes": self._modes_state()}

    def _restore_timeline(self, data):
        """Put the player back as it was saved.

        Object ids are stable across a savefile (`Scene.from_dict`
        restores them along with `next_id`), so a strip finds its
        molecule again. A file written before round 77 is migrated by
        `Timeline.from_dict`; one written before the player was saved at
        all simply has no key, and the defaults stand.
        """
        if not data:
            return
        self.timeline = timeline_mod.Timeline.from_dict(data)

    def on_save(self):
        """Ctrl+S: save the DOCUMENT, whatever this session's document is.

        A project when there is one; otherwise the structure file MoloM was
        launched with. That second case is the ORCA Workbench round-trip:
        OWB opens `[molom, mol.xyz]`, tells the user to "adjust the geometry,
        then Save so it overwrites the .xyz", and re-reads that file. If
        Ctrl+S put up a `.molom` project dialog instead, the round-trip would
        fail SILENTLY - OWB would reload an unchanged file and report success.
        """
        if self.project_path:
            return self.on_save_project()
        if self.source_path:
            return self.on_save_geometry_back()
        return self.on_save_project_as()

    def _smiles_note(self):
        # type: () -> str
        """The visible molecules' SMILES, for the file MoloM writes back.

        Christian: "since MoloM can derive SMILES from struct, it should also
        forward the updated SMILES (if possible) to OWB so the skeletal
        structure updates." The graph is what `io.structure_to_smiles` reads,
        so after an edit this is the EDITED constitution rather than the one
        the molecule arrived with.

        It goes on the xyz COMMENT line, which is the one place every other
        program already looks (round 76) and the only channel an .xyz has.
        Reading it back is OWB's side of the job and is recorded in its TODO.

        Silent on anything it cannot honestly answer - a crystal (a SMILES of
        a packed cell means nothing), a structure with no bonds, or a graph
        RDKit refuses. A wrong SMILES forwarded into another program is much
        worse than none.
        """
        vis = [o for o in self.scene.visible_objects()
               if o.structure.n_atoms and o.structure.bonds]
        if not vis or any(cell_of(o) is not None for o in vis):
            return ""
        parts = []
        for o in vis:
            try:
                smiles, _err = io.structure_to_smiles(
                    meta_mod.resolved_symbols(o.structure) or o.structure.symbols,
                    o.structure.bonds,
                    charge=getattr(o.structure, "charge", 0) or 0)
            except Exception:                           # noqa: BLE001
                smiles = None
            if smiles:
                parts.append("{}={}".format(o.name, smiles) if len(vis) > 1
                             else smiles)
        return "SMILES: {}".format(" ".join(parts)) if parts else ""

    def _sync_roundtrip_note(self):
        """Keep the viewport banner describing where Ctrl+S will write.

        Only for the ROUND-TRIP case - a `.molom` project is MoloM's own
        document and needs no warning that saving it saves it. The banner
        exists because a session launched from ORCA Workbench overwrites
        somebody else's file, and nothing on screen used to say so.
        """
        if self.project_path or not self.source_path:
            self.viewport.set_roundtrip("")
            return
        self.viewport.set_roundtrip("Round trip - Ctrl+S writes back to {}"
                                    .format(os.path.basename(
                                        self.source_path)))

    def on_save_geometry_back(self):
        """Write the visible geometry back over the file this session opened.

        The same writer Ctrl+E uses, so a round-tripped file is exactly what
        an ordinary export would have produced - one path, not two.
        """
        if not self.source_path:
            self.statusBar().showMessage(
                "This session was not opened from a structure file - use "
                "File > Export geometry", 8000)
            return
        try:
            backend, n_obj, n_atoms = self.export_visible(
                self.source_path, extra_comment=self._smiles_note())
        except Exception as exc:                        # noqa: BLE001
            QMessageBox.critical(self, "Save failed",
                                 "Could not write {}:\n{}".format(
                                     self.source_path, exc))
            return
        self.statusBar().showMessage(
            "Saved {} atom{} to {} ({}){}".format(
                n_atoms, "" if n_atoms == 1 else "s",
                os.path.basename(self.source_path), backend,
                "" if n_obj == 1 else
                " - {} molecules written".format(n_obj)), 9000)
        self.viewport.flash("Saved to {}".format(
            os.path.basename(self.source_path)))

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
        self.viewport.flash("Saved {}".format(
            os.path.basename(self.project_path)))

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
        self.source_path = None   # the project is the document now
        self._sync_roundtrip_note()
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
        self._restore_modes(ui.get("modes"))
        self._restore_timeline(ui.get("timeline"))
        view = payload.get("view") or {}
        cam = self.viewport.camera
        if "center" in view:
            cam.center = np.asarray(view["center"], dtype=float)
            cam.distance = float(view.get("distance", cam.distance))
            cam.rotation = np.asarray(view["rotation"], dtype=float)
            cam.orthographic = bool(view.get("orthographic", False))
            cam.auto_ortho = False
        self.viewport.selected_camera_id = view.get("selected_camera")
        through = view.get("looking_through")
        if through is not None and self.scene.camera(through) is not None:
            self.on_activate_camera(through)
        self.project_path = path
        self.source_path = None   # the project is the document now
        self._sync_roundtrip_note()
        self._push_recent(path)
        self._sync_all(fit="center" not in view)
        self._update_title()
        self.statusBar().showMessage(
            "Opened project {} ({} molecules, saved {})".format(
                os.path.basename(path), self.scene.n_objects,
                payload.get("saved", "?")), 8000)

    # ---------------------------------------------------------------- opening
    def select_atom_indices(self, indices, obj_id=None):
        # type: (list, Optional[int]) -> tuple
        """Select atoms by index on one molecule. Returns `(picked, missing)`.

        **0-BASED, because ORCA is.** `orca_workbench/core/geomspec.py` says
        so outright - "ORCA atom indices are 0-based" - and the whole point of
        `--select` is to paste the numbers out of a `%geom` constraint and see
        which atoms they are. Renumbering them here would make the feature
        worse than useless.

        Out-of-range indices are REPORTED rather than dropped: a constraint
        that names an atom this file does not have is exactly the mistake
        somebody would want to be told about.
        """
        obj = self.scene.get(obj_id) if obj_id is not None else None
        if obj is None:
            obj = self._active_obj()
        if obj is None:
            return [], list(indices)
        n = obj.structure.n_atoms
        picked, missing = [], []
        for raw in indices:
            try:
                i = int(raw)
            except (TypeError, ValueError):
                missing.append(raw)
                continue
            (picked if 0 <= i < n else missing).append(i)
        self.viewport.set_selection([(obj.id, i) for i in picked])
        return picked, missing

    def open_path(self, path):
        # type: (str) -> None
        if project.is_project_file(path):
            self.open_project(path)
            return
        # Remembered BEFORE the read, so it is set even for a format whose
        # import reports something unusual. Only the first structure file of
        # a session claims it: importing a second molecule ADDS to the scene
        # (round 2), and silently re-pointing "Save" at whatever was opened
        # most recently is how a round-trip writes the wrong file.
        if self.source_path is None and self.project_path is None:
            self.source_path = os.path.abspath(path)
            self._sync_roundtrip_note()
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

    def on_import_by_name(self, query=""):
        """Find a molecule by name and import it (Ctrl+Shift+N).

        A LIST rather than a single answer since round 90, and the reason is
        measured: PubChem's exact-name endpoint 404s on "xylene" and on
        "cresol", while OPSIN answers both with the ortho isomer and says
        nothing. A dialog showing one structure cannot tell you either.
        """
        dlg = MoleculeSearchDialog(self, remembered=self._last_mol_search,
                                   favourites=self.mol_favourites())
        if query:
            # Pasted, rather than typed: fill it in and run it, so a CAS
            # number on the clipboard behaves like one the user searched for.
            dlg.edit.setText(str(query))
            dlg._start()
        accepted = dlg.exec()
        # Saved whatever the outcome: starring something and then pressing
        # Cancel is an ordinary way to use a bookmark list.
        self.set_mol_favourites(dlg.favourites)
        self._last_mol_search = dlg.remembered()
        if not accepted or not dlg.chosen:
            return
        import datetime
        today = datetime.date.today().isoformat()
        pairs, extras = [], []
        for cand in dlg.chosen:
            if not cand.smiles:
                continue
            pairs.append((cand.smiles, cand.name or cand.query or cand.label()))
            # The IDENTITY record is stored on import whether or not the
            # properties add-on is enabled: it is small, it is the answer to
            # "what is this and where did it come from", and it is what lets
            # the add-on work on a molecule imported before it was switched
            # on. It carries no measured properties, so it creates no
            # attachment and therefore no overwrite lock - there is nothing
            # to lose yet.
            record = molprops.Record(
                name=cand.name, formula=cand.formula,
                inchikey=cand.inchikey, cid=cand.cid(), smiles=cand.smiles,
                iupac_name=cand.iupac_name, retrieved=today,
                source=cand.source, note=cand.note)
            extras.append({molprops.METADATA_KEY: record.to_dict(),
                           "comment": record.provenance()})
        if not pairs:
            self.statusBar().showMessage(
                "That result carries no structure to import", 8000)
            return
        self._install_smiles_batch(pairs, "found by name", extras=extras)

    def mol_favourites(self):
        # type: () -> dict
        """Bookmarked compounds, `{candidate.key(): Candidate}`.

        Unlike a CIF favourite this DOES store the structure, because a
        molecule's structure is a short string - which costs nothing and
        makes a starred compound importable with no network at all.
        """
        # Imported HERE and not at module scope: `molsearch` pulls in the
        # resolver, which pulls urllib/http/email for about 130 ms - and most
        # launches never look a compound up. Round 65's guard pins it.
        import json

        from ..core import molsearch
        raw = self.settings.value("mol_favourites", "") or ""
        try:
            entries = json.loads(raw) if raw else []
        except ValueError:
            return {}
        out = {}
        for entry in entries if isinstance(entries, list) else []:
            cand = molsearch.candidate_from_dict(entry)
            if cand is not None:
                out[cand.key()] = cand
        return out

    def set_mol_favourites(self, favourites):
        # type: (dict) -> None
        import json
        entries = [c.to_dict() for c in (favourites or {}).values()]
        self.settings.setValue("mol_favourites", json.dumps(entries))

    def on_search_cif(self):
        """Find a crystal structure by formula, mineral or name, and import
        the ones chosen. Several at once: comparing two polymorphs is the
        commonest reason to go looking."""
        # The last search is remembered ON THE WINDOW, not in a module
        # global: a second window - or the next test - must not inherit
        # somebody else's result list, which is the shape of bug this project
        # keeps finding in shared state (the round-37 circuit breaker, the
        # round-46 module cache, the round-77 QSettings sandbox).
        dlg = CifSearchDialog(self, roots=self.cif_search_roots(),
                              remembered=self._last_cif_search,
                              favourites=self.cif_favourites())
        accepted = dlg.exec()
        # Saved whatever the outcome: starring something and then pressing
        # Cancel is an ordinary way to use a bookmark list.
        self.set_cif_favourites(dlg.favourites)
        # Kept whether or not anything was imported: closing the dialog to
        # look at the structure you just took is the commonest way to end up
        # reopening it, and that is exactly when retyping the query stings.
        self._last_cif_search = dlg.remembered()
        if not accepted or not dlg.chosen:
            return
        installed, failed = 0, []
        for hit in dlg.chosen:
            try:
                text = cifsearch.fetch_cif(hit)
            except Exception as exc:              # noqa: BLE001
                failed.append("{}: {}".format(hit.label(), exc))
                continue
            # Written to a temp file rather than parsed in memory, so the
            # download takes the SAME path a file on disk does - the packed
            # import, the disorder policy, the symmetry derivation and every
            # report that goes with them. A second, subtly different import
            # path for downloaded structures is exactly the drift this
            # project keeps finding.
            import shutil
            import tempfile
            # A temp DIRECTORY with a properly named file inside, rather than
            # a temp file: the import names the object after the file, so
            # `mkstemp` would put `molom_d2dtna96` in the outliner - which
            # says nothing and is indistinguishable from the next one.
            folder = tempfile.mkdtemp(prefix="molom_cif_")
            path = os.path.join(folder, hit.filename() + ".cif")
            try:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(text)
                before = self.scene.n_objects
                self.open_path(path)
                installed += self.scene.n_objects - before
            finally:
                shutil.rmtree(folder, ignore_errors=True)
        note = "Imported {} structure{}".format(
            installed, "" if installed == 1 else "s")
        if failed:
            note += " - {} could not be fetched: {}".format(len(failed),
                                                            failed[0])
        self.statusBar().showMessage(note, 9000)

    def cif_favourites(self):
        # type: () -> dict
        """Bookmarked structures, `{hit.key(): Hit}`.

        REFERENCES, not files. A favourite is "fetch this again", so it stays
        correct when COD supersedes an entry, and starring a hundred
        structures costs a few kilobytes of settings rather than a hundred
        CIFs on disk. Stored as JSON because QSettings round-trips a list of
        dicts through the registry unreliably on Windows.
        """
        import json
        raw = self.settings.value("cif_favourites", "") or ""
        try:
            entries = json.loads(raw) if raw else []
        except ValueError:
            return {}
        out = {}
        for entry in entries if isinstance(entries, list) else []:
            hit = cifsearch.hit_from_dict(entry)
            if hit is not None:
                out[hit.key()] = hit
        return out

    def set_cif_favourites(self, favourites):
        # type: (dict) -> None
        import json
        entries = [h.to_dict() for h in (favourites or {}).values()]
        self.settings.setValue("cif_favourites", json.dumps(entries))

    def cif_search_roots(self):
        # type: () -> list
        """Folders the local tier searches. Empty until the user names one -
        there is no sensible default for somebody else's file collection."""
        value = self.settings.value("cif_search_root", "")
        return [str(value)] if value else []

    def on_set_cif_folder(self):
        """Point the local search tier at a folder of CIFs."""
        current = self.settings.value("cif_search_root", "") or ""
        path = QFileDialog.getExistingDirectory(
            self, "Folder of CIF files to search", str(current))
        if not path:
            return
        self.settings.setValue("cif_search_root", path)
        self.statusBar().showMessage(
            "Crystal search will also look in {}".format(path), 6000)

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
        # NOT EVERYTHING THAT IS NOT XYZ IS A SMILES. Pasting a CAS number
        # handed `2591-17-5` to both chemistry backends and showed their
        # complaints in a dialog - "RDKit could not parse SMILES", "OpenBabel
        # raised OSError" - which says nothing about the real problem, that
        # a CAS number is a NAME and wants looking up. `resolve.classify`
        # already tells the two apart; the paste path simply never asked.
        from ..core import resolve as resolve_mod
        kind = resolve_mod.classify(text.strip())
        if kind in ("name", "cas", "inchikey"):
            self.on_import_by_name(query=text.strip())
            return
        # SMILES paste: parse_smiles_list splits ChemDraw's dot-separated
        # multi-structure copies into one entry per molecule.
        pairs = io.parse_smiles_list(text)
        if pairs:
            self._install_smiles_batch(pairs, "pasted SMILES")
            return
        QMessageBox.information(
            self, "Paste",
            "Clipboard text is not an XYZ block, a SMILES, an InChI, a CAS "
            "number or a compound name.")

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
            "XYZ (*.xyz);;Crystallographic CIF (*.cif);;MDL SDF (*.sdf);;"
            "MDL MOL (*.mol);;PDB (*.pdb);;Sybyl MOL2 (*.mol2);;"
            "All files (*)")
        if not path:
            return
        try:
            self._cif_export_note = ""
            backend, n_obj, n_atoms = self.export_visible(path)
            self.settings.setValue("last_dir", os.path.dirname(path))
            self._push_recent(path)
            self.statusBar().showMessage(
                "Exported {} molecule(s), {} atoms to {} ({}){}".format(
                    n_obj, n_atoms, os.path.basename(path), backend,
                    " — " + self._cif_export_note
                    if self._cif_export_note else ""), 12000)
        except (ValueError, OSError) as e:
            QMessageBox.critical(self, "Save failed", str(e))

    def export_visible(self, path, extra_comment=""):
        # type: (str, str) -> tuple
        """Write every visible molecule to `path`. Returns
        (backend, n_objects, n_atoms). Split out from the dialog so the
        export rule is testable."""
        vis = [o for o in self.scene.visible_objects() if o.structure.n_atoms]
        if not vis:
            raise ValueError("no visible molecules to export")
        name = " + ".join(o.name for o in vis)
        if path.lower().endswith((".cif", ".mmcif")):
            return self.export_cif(path, vis)
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
            # The molecules' own comments, joined when several are being
            # written into one file - a comment that silently applied to only
            # the first of five would be worse than none.
            notes = []
            for o in vis:
                text = str((o.structure.metadata or {}).get("comment", ""))
                if text.strip():
                    notes.append("{}: {}".format(o.name, text.strip())
                                 if len(vis) > 1 else text.strip())
            if extra_comment:
                notes.append(extra_comment)
            backend = io.write_structure_file(path, atoms, name=name,
                                              comment=" | ".join(notes))
            return backend, len(vis), total
        return backend, len(vis), sum(o.structure.n_atoms for o in vis)

    def export_cif(self, path, objects=None):
        # type: (str, list) -> tuple
        """Write a real CIF — cell, operators, asymmetric unit, occupancies.

        Its own path rather than a branch of `write_structure_file`, because
        that function is handed plain atoms and the whole content of a CIF is
        the crystallography hanging off the OBJECT. Before this, a `.cif`
        export went to OpenBabel as an xyz block: the file had coordinates and
        nothing else, and MoloM's own reader rejected it.

        The report is put in front of the user, not swallowed: a file that
        quietly lost its symmetry or gained an invented cell is exactly the
        kind of wrongness that looks right.
        """

        objects = objects or [o for o in self.scene.visible_objects()
                              if o.structure.n_atoms]
        if not objects:
            raise ValueError("no visible molecules to export")
        reports = []
        text = cif_write.scene_text(objects, version=__version__,
                                    reports=reports)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        self._cif_export_reports = reports
        self._cif_export_note = self.cif_export_note(reports)
        return "cif", len(objects), sum(len(o.evaluated()[0])
                                        for o in objects)

    @staticmethod
    def cif_export_note(reports):
        # type: (list) -> str
        """What the writer decided, in one phrase for the status bar.

        Same discipline as `chemistry_note` (round 38): the reader has three
        ways to refuse what a file says and the writer has two ways to change
        what it writes, and either one going unmentioned is indistinguishable
        from a bug.
        """

        bits = []
        for report in reports:
            who = report.get("name") or "?"
            if report.get("invented_cell"):
                bits.append("{}: no unit cell, written in an invented P1 box"
                            .format(who))
            elif report.get("policy") == cif_write.POLICY_ASYMMETRIC:
                bits.append("{}: {}, {} operations, {} sites".format(
                    who, report.get("spacegroup"), report.get("symops"),
                    report.get("n_sites")))
            elif report.get("policy") == cif_write.POLICY_CELL:
                bits.append("{}: symmetry re-derived as {} ({} operations)"
                            .format(who, report.get("spacegroup"),
                                    report.get("symops")))
            else:
                bits.append("{}: written as P1, {} sites".format(
                    who, report.get("n_sites")))
            if report.get("occupancy_lost"):
                bits[-1] += " — partial occupancies NOT carried over"
        return "; ".join(bits)

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
        # A hovered or selected MEASUREMENT is what Delete takes first: it is
        # the thing under the cursor, it is drawn highlighted to say so, and it
        # is not part of the structure — so this needs no undo entry and must
        # not fall through to deleting atoms. Christian asked for both routes,
        # "selecting + Delete or hovering over them + Delete".
        if self.viewport.delete_measurement():
            return
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
            # A boundary copy is the same crystallographic atom, so deleting
            # one deletes them all — leaving the copies behind is exactly the
            # desynchronisation that made an edited packed cell disagree with
            # itself across its own faces.
            rows = packing_mod.images_of(obj.structure.metadata or {}, rows,
                                         obj.structure.n_atoms)
            # take the hanging hydrogens with them. Through the OBJECT, so
            # its own per-atom maps - colours, labels, hidden atoms, sphere
            # sizes - are renumbered with the atoms rather than left naming
            # whichever atoms inherited those indices (round 80).
            obj.delete_atoms(rows, with_hydrogens=True)
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
        self.set_modes(obj, modes)
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

    #: Engines that can COMPUTE normal modes, contributed by add-ons as
    #: `(label, callable)` where the callable takes the MainWindow. Core knows
    #: the contract and never the implementation - the same extension point
    #: `forcefield.register_method` is, for the same reason: MoloM must not
    #: learn what MOPAC is in order to offer a button that runs it.
    frequency_providers = None

    def register_frequency_provider(self, label, run):
        if self.frequency_providers is None:
            self.frequency_providers = []
        self.frequency_providers = [
            e for e in self.frequency_providers if e[0] != label]
        self.frequency_providers.append((str(label), run))
        self._sync_vibration_page()

    def unregister_frequency_provider(self, label):
        self.frequency_providers = [
            e for e in (self.frequency_providers or []) if e[0] != label]
        self._sync_vibration_page()

    def on_calculate_frequencies(self):
        providers = self.frequency_providers or []
        if not providers:
            return
        providers[0][1](self)          # the add-on owns everything past here

    # ---- which molecules have a job in flight, so the page can say so
    def freq_job_started(self, obj_id, label=""):
        jobs = getattr(self, "_freq_jobs", None)
        if jobs is None:
            jobs = {}
            self._freq_jobs = jobs
        jobs[int(obj_id)] = str(label)
        self._sync_vibration_page()

    def freq_job_finished(self, obj_id):
        (getattr(self, "_freq_jobs", None) or {}).pop(int(obj_id), None)
        self._sync_vibration_page()

    def freq_job_running(self, obj_id):
        return int(obj_id) in (getattr(self, "_freq_jobs", None) or {})

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
        # The button and the busy bar, AFTER `set_modes` - which rewrites the
        # summary label the busy state also writes to, so doing it first would
        # have the running message immediately overwritten by "has no
        # vibrational data".
        self.vibration_page.set_providers(
            [label for label, _run in (self.frequency_providers or [])])
        running = obj is not None and self.freq_job_running(obj.id)
        self.vibration_page.set_busy(
            running,
            "Calculating frequencies for {}...\nThis runs in the background "
            "- the molecule stays usable.".format(obj.name)
            if running else "")
        self._push_mode_selection()
        self._sync_fractional()

    def _push_mode_selection(self):
        """Hand the ∿ page the atoms picked ON ITS OWN molecule.

        Scoped to the active object on purpose: a mode belongs to one FREQ job,
        so atoms selected in some other molecule are not part of the question,
        and their indices would mean different atoms here anyway.
        """
        obj = self._active_obj()
        if obj is None:
            self.vibration_page.set_selection([], [])
            return
        rows = [i for o, i in self.viewport.selection if o == obj.id]
        self.vibration_page.set_selection(rows, obj.structure.symbols)

    def _rest_for(self, obj):
        # type: (object) -> object
        """This molecule's EQUILIBRIUM geometry, where it is now.

        A mode is baked as `rest + eigenvector * sin(phase)`, so the stored
        rest was captured once when the frequencies were read and then used
        for every re-bake — which meant selecting another mode, or nudging the
        amplitude, teleported the molecule back to where it was imported.
        Christian: "selecting a different normal mode should not reset the
        transform location of the molecule."

        Frame 0 of a baked mode IS the undisplaced geometry (sin 0 = 0), and a
        grab moves EVERY frame, so after any transform frame 0 is the rest
        geometry in its new place. Re-reading it is the whole fix, and it
        needs no extra bookkeeping to go stale.

        Round 57: it was re-read only while a mode was ALREADY animating, so
        the FIRST animate still used the capture taken when the frequencies
        were read and teleported the molecule back to where it was imported —
        Christian: "curiously, only the first animate click resets the
        location". There is nothing special about the first one. Frame 0 is
        the rest geometry whether a mode is baked (undisplaced phase) or not
        (the molecule itself), so it is read unconditionally; the capture
        survives only as the fallback for a mode whose atom count does not
        match the molecule, which cannot be animated anyway.
        """
        s = obj.structure
        stored = self._rest_geometry.get(obj.id)
        current = np.asarray(s.frames[0] if s.n_frames else s.coords,
                             dtype=float)
        if current.shape == (s.n_atoms, 3):
            stored = current.copy()
        if stored is None or np.shape(stored)[0] != s.n_atoms:
            stored = s.coords.copy()
        self._rest_geometry[obj.id] = stored
        return stored

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
        rest = self._rest_for(obj)
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
        self._freeze_mode_bonds(obj)
        self._sync_traj_bar()
        track = self.timeline.get(obj.id)
        if track is not None:
            track.end = timeline_mod.LOOP        # a vibration IS a loop
        self._apply_timeline()
        if resync:
            self._sync_vibration_page()
        self.statusBar().showMessage(
            "{}: animating {}".format(obj.name, mode.label().strip()), 9000)

    def _freeze_mode_bonds(self, obj):
        """Pin this molecule's connectivity to its EQUILIBRIUM geometry.

        Called the moment a mode is baked, with the playhead put back on frame
        0 — which is the undisplaced geometry — so the bonds drawn for the
        whole animation are the bonds of the molecule at rest. See
        `bonding.bonds_are_fixed` for why a vibrating frame must not be asked
        the question at all.

        Re-perceiving here rather than merely setting the flag is what makes
        it self-healing: a mode animated earlier at a large amplitude may
        already have eaten a bond, and this is the point at which the
        molecule is definitely standing still.
        """
        obj.structure.metadata[bonding.FIXED_BONDS] = True
        # These frames are one CLOSED PERIOD: `mode_frames` samples
        # sin(2*pi*k/n) for k = 0..n-1 and deliberately omits the k = n
        # duplicate, so the player must divide the strip into n arcs and
        # blend the last sample back into the first. Metadata rather than
        # a flag on the track, so it rides undo and the savefile and a
        # strip removed and re-added still describes a period.
        obj.structure.metadata[timeline_mod.CYCLIC_FRAMES] = True
        self._stale_bonds.discard(obj.id)
        bonding.perceive_structure_bonds(obj.structure)

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
        rest = self._rest_for(obj)
        self.push_undo()
        self._active_mode[obj.id] = mode.index
        obj.structure.frames = vib_mod.mode_frames(
            rest, mode,
            amplitude=float(self._mode_amplitude.get(
                obj.id, properties_mod.DEFAULT_AMPLITUDE)),
            n_frames=int(self._mode_frames.get(
                obj.id, vib_mod.DEFAULT_PERIOD_FRAMES)))
        obj.structure.set_frame(0)
        self._freeze_mode_bonds(obj)
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
        # A MONODENTATE ligand is the one case where several placeholders do
        # not have to be geminal: each one simply gets its own copy. Christian:
        # "monodentate ligands are a nice exception in that we can allow to
        # coordinate multiple times at once". With more donors the geminal rule
        # still holds — a chelate has to span slots on ONE centre, and two
        # centres would be a bridging ligand, which is a different operation.
        if len(marks) == 1 and len(slots) > 1:
            groups = [[i] for i in slots]
        else:
            groups = [list(slots)]
        try:
            # Every transform is computed against the ORIGINAL coordinates,
            # before anything is appended — the placeholders do not move, and
            # doing it up front means a failure on the third of five leaves the
            # molecule untouched rather than half-built.
            plan = []
            for group in groups:
                centre = tpl_mod.check_placeholders(host.structure, group)
                rot, trans = tpl_mod.coordinate(
                    host.structure.coords, group, centre,
                    ligand.structure.coords, marks)
                plan.append((group, centre, rot, trans))
        except tpl_mod.TemplateError as exc:
            self.statusBar().showMessage("Coordinate ligand: {}".format(exc),
                                         10000)
            return

        self.push_undo()
        s = host.structure
        for group, centre, rot, trans in plan:
            # Bring a COPY of the ligand in, so the template stays reusable.
            moved = ligand.structure.coords @ rot.T + trans
            offset = s.n_atoms
            for k, symbol in enumerate(ligand.structure.symbols):
                edits.add_atom(s, symbol, moved[k])
            for bond in ligand.structure.bonds:
                order = bond[2] if len(bond) > 2 else 1
                edits.add_bond(s, offset + int(bond[0]), offset + int(bond[1]),
                               order=order)
            for donor in marks:
                edits.add_bond(s, centre, offset + donor, order=1)
        # The placeholders have been replaced, so they go — last, and all at
        # once, because deleting reindexes everything above them.
        host.delete_atoms(sorted(slots))
        self.viewport.set_selection([])
        self._after_edit()
        self._sync_all()
        self.statusBar().showMessage(
            "{} coordinated onto {} — {} cop{} placed, {} bond(s) made, {} "
            "placeholder(s) removed".format(
                ligand.name, host.name, len(plan),
                "y" if len(plan) == 1 else "ies",
                len(marks) * len(plan), len(slots)),
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
            a, r = obj.adjust_hydrogens(
                [i for o, i in sel if o == obj_id])
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
        elif tool_id == "lasso":
            # It was reachable only by `Shift+Space, L` or F3, which is why it
            # felt like it had been removed — a plain left-drag is box select,
            # so nothing on screen said the lasso still existed.
            on = vp._select_tool != "lasso"
            if on:
                vp.set_draw_tool(False)
                vp.set_origin_active(False)
                vp.set_measure_tool(False)
            vp.set_select_tool("lasso" if on else None)
            self.toolbar.set_active("lasso" if on else "select")
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
        if not show and self._ptable is None:
            return                  # never built, nothing to hide
        table = self.ptable
        if show:
            table.set_current(self.viewport.draw_element)
            self._position_ptable()
        table.setVisible(show)

    @property
    def ptable(self):
        """The periodic table, built the first time it is needed.

        A property rather than a `_build_ptable()` everyone must remember to
        call: every existing use site keeps working unchanged, and a new one
        cannot forget.
        """
        if self._ptable is None:
            self._ptable = PeriodicTablePanel(self.viewport)
            self._ptable.element_picked.connect(self.viewport.apply_element)
            self._ptable.meta_atom_requested.connect(self.on_meta_atom)
            self._ptable.set_current(self.viewport.draw_element)
            self._ptable.hide()
        return self._ptable

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

    def _crystal_targets(self):
        # type: () -> List
        """Which crystals a ❖ control acts on: every SELECTED one.

        Christian, with five isostructural alkali fluorides open: "I wanted to
        change a tick box in the cif props pane for all of them simultaneously
        => Select all, untick draw atoms outside boundary." Before round 91b
        every control on this page took one `obj_id` and that was the ACTIVE
        object, so exactly one crystal changed and the other four silently did
        not.

        **Crystals only**, meaning objects that have a cell. The page is the
        crystal page and its ticks are about crystallographic display, so a
        molecule caught in a select-all is passed over rather than being
        given `show_symmetry` it can do nothing with.

        The ACTIVE object is always included even when the selection does not
        reach it, because the tick the user just clicked shows ITS state - it
        would be strange for the one the page is describing to be the one left
        behind. With nothing selected that is the whole list, which is exactly
        the old behaviour.
        """
        ids = {int(oid) for oid, _atom in (self.viewport.selection or [])}
        active = self._active_obj()
        if active is not None:
            ids.add(active.id)
        order = {o.id: i for i, o in enumerate(self.scene.objects)}
        targets = [o for o in (self.scene.get(i) for i in ids)
                   if o is not None and cell_of(o) is not None]
        targets.sort(key=lambda o: order.get(o.id, 0))
        return targets

    def _report_crystal_change(self, targets, what):
        # type: (List, str) -> None
        """Say how many crystals a click reached.

        A control that quietly acts on four objects needs to say so as much as
        one that acts on a single object the user was not looking at.
        """
        if not targets:
            return
        if len(targets) == 1:
            self.statusBar().showMessage(
                "{}: {}".format(targets[0].name, what), 6000)
        else:
            self.statusBar().showMessage(
                "{} crystals: {}".format(len(targets), what), 6000)

    def _set_obj_flag(self, key, on):
        """Per-object display flags live in metadata, so they ride undo
        snapshots and savepoints without extra plumbing.

        Applied to every SELECTED crystal - see `_crystal_targets`.
        """
        targets = self._crystal_targets()
        if not targets:
            return
        for obj in targets:
            if on:
                obj.structure.metadata[key] = True
            else:
                obj.structure.metadata.pop(key, None)
        self.viewport.refresh_geometry()
        self.viewport.update()
        self._report_crystal_change(
            targets, "{} {}".format(_FLAG_LABELS.get(key, key),
                                    "on" if on else "off"))

    def _sync_symmetry_kinds(self):
        """The symmetry-element kind filters, on every selected crystal."""
        kinds = self.crystal_page.enabled_kinds()
        for obj in self._crystal_targets():
            obj.structure.metadata["symmetry_kinds"] = kinds
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

    def _on_packing_option(self, obj_id, which, on):
        # type: (int, str, bool) -> None
        """A packing choice on the ❖ page: rebuild the view through it.

        These replace the old "Bonded atoms outside the cell" tick, which
        drove `BoundaryModifier`/`shell_molecules` — mechanisms the packed
        pipeline no longer uses, so the control had quietly stopped doing
        anything.
        """
        # WHICH crystals: the page's own ticks pass the ACTIVE id, and that
        # is what "act on the selection" looks like from here. An outliner
        # row's control names a specific object instead and must act on that
        # one alone - membership in the selection is the wrong test, because
        # a row control for a crystal that happens to be selected would then
        # broadcast to all of them.
        if obj_id is None or obj_id == self.active_id:
            targets = self._crystal_targets()
        else:
            obj = self.scene.get(obj_id)
            targets = ([obj] if obj is not None and cell_of(obj) is not None
                       else [])
        if not targets:
            return
        key = "pack_outside" if which == "outside" else "pack_copies"
        active = self.active_id
        for obj in targets:
            obj.structure.metadata[key] = bool(on)
            # `on_crystal_view` rebuilds THE ACTIVE crystal, so each target
            # takes its turn at being active. Restored afterwards, or a click
            # on a tick would quietly move the selection.
            self.active_id = obj.id
            self.on_crystal_view(obj.structure.metadata.get("cell_view",
                                                            "cell"))
        self.active_id = active
        if len(targets) > 1:
            # Rebuilding a crystal's view regenerates its atom list, so the
            # selection - which names atoms by index - is dropped. Without
            # putting it back, the FIRST tick would reach all five crystals
            # and the SECOND would quietly reach one, which is the very
            # surprise this change exists to remove. Whole molecules, because
            # that is what "these are the ones I am working on" means and the
            # old indices no longer refer to anything.
            self.viewport.select_whole_molecules([o.id for o in targets])
        self._sync_crystal_page()
        self._report_crystal_change(
            targets, "atoms outside the cell {}".format(
                "shown" if on else "hidden") if which == "outside"
            else "boundary copies {}".format("completed" if on else "left"))

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
            outside=bool(meta.get("pack_outside", True)),
            grow_from_copies=bool(meta.get("pack_copies", False)),
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
        # Recorded explicitly as well, because an asymmetric unit of one or
        # two atoms cannot carry a reference sample and would otherwise lose
        # its placement on the next rebuild.
        set_cell_pose(s, pose)
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

    def on_export_animation(self):
        """Seek, render, write — the scene clock as a file.

        Everything needed was already here: the clock steps deterministically
        and `render_image` renders one frame offscreen at a resolution
        multiplier. What this adds is the frame PLAN (`core/animation.py`),
        which is where the mistakes live — an off-by-one at a loop boundary
        makes a video that hitches once per cycle and is invisible in any
        single frame.
        """
        clock = self.timeline
        if clock.duration <= 0.0:
            self.statusBar().showMessage(
                "Nothing to animate — open a trajectory, or bake a "
                "vibrational mode from the modes page", 7000)
            return
        vp = self.viewport
        times = anim_mod.frame_times(clock)
        have_video = anim_mod.video_available(self.ffmpeg_hint)
        # Inside a camera, the shot's own resolution is the default — the
        # frames come out of `render_image` cropped to the film back, so a
        # default taken from the WINDOW would have a different aspect and the
        # export's final scale (IgnoreAspectRatio) would stretch every frame.
        active_cam = self.scene.active_camera() \
            if vp.looking_through is not None else None
        default_size = (active_cam.render_size() if active_cam is not None
                        else (vp.width(), vp.height()))
        dlg = AnimationExportDialog(
            self, len(times), clock.fps, default_size, have_video,
            remembered=(self._render_target.get(True) or {}).get("opts"),
            ffmpeg_hint=self.ffmpeg_hint)
        if not dlg.exec():
            return
        # An ffmpeg located from inside the dialog is remembered, or the next
        # export would ask again for something already answered.
        if dlg.ffmpeg_hint() and dlg.ffmpeg_hint() != self.ffmpeg_hint:
            self.ffmpeg_hint = dlg.ffmpeg_hint()
            self.settings.setValue("ffmpeg_path", self.ffmpeg_hint)
        opts = dlg.options()
        times = anim_mod.frame_times(clock, loops=opts["loops"])
        if not times:
            return
        start = self.settings.value("last_dir", "")
        base = (os.path.splitext(os.path.basename(self.project_path))[0]
                if self.project_path else "molom")
        suffix = ".png" if opts["format"] == anim_mod.FORMAT_PNG \
            else "." + opts["format"]
        path, _f = QFileDialog.getSaveFileName(
            self, "Export animation", os.path.join(start, base + suffix),
            "Animation (*{})".format(suffix))
        if not path:
            return
        self.settings.setValue("last_dir", os.path.dirname(path))
        try:
            written, message = self.write_animation(path, times, opts)
        except Exception as e:                # a long render must not vanish
            QMessageBox.critical(self, "Animation export failed", str(e))
            return
        if written:
            self._render_target[True] = {"path": path, "opts": opts,
                                         "increment": opts.get("increment",
                                                               True)}
            self.statusBar().showMessage(
                message + " — Ctrl+F12 renders the next one", 15000)
        else:
            QMessageBox.warning(self, "Animation export", message)

    def write_animation(self, path, times, opts, progress=True):
        # type: (str, list, dict, bool) -> tuple
        """Render `times` and write them out. Split from the dialog plumbing
        so the whole export is testable without a file dialog."""
        vp = self.viewport
        where = anim_mod.plan(path, opts["format"], len(times))
        directory = where["directory"] or "."
        if where["format"] == anim_mod.FORMAT_PNG:
            os.makedirs(where["path"], exist_ok=True)
            directory = where["path"]
        elif directory and not os.path.isdir(directory):
            os.makedirs(directory)
        # A video is assembled from a sequence, so the frames go to a scratch
        # folder beside the output and are cleared afterwards. Writing PNGs
        # and encoding from them (rather than piping raw frames) means a
        # failed encode still leaves every rendered frame on disk.
        temp = None
        if where["format"] != anim_mod.FORMAT_PNG:
            temp = os.path.join(directory or ".",
                                "." + where["base"] + "_frames")
            os.makedirs(temp, exist_ok=True)
            directory = temp
        keep = clock_time = self.timeline.time
        n = 0
        width, height = opts["size"]
        scale = max(width / max(vp.width(), 1), height / max(vp.height(), 1))
        try:
            if progress:
                QApplication.setOverrideCursor(Qt.WaitCursor)
            for index, when in enumerate(times):
                self.timeline.seek(when)
                self._apply_timeline()
                image = vp.render_image(scale=max(scale, 1.0),
                                        transparent=opts["transparent"],
                                        furniture=opts["furniture"])
                image = image.scaled(int(width), int(height),
                                     Qt.IgnoreAspectRatio,
                                     Qt.SmoothTransformation)
                out = anim_mod.sequence_path(directory, where["base"], index,
                                             where["digits"])
                if not image.save(out):
                    raise IOError("could not write " + out)
                n += 1
                if progress and index % 5 == 0:
                    self.statusBar().showMessage(
                        "Rendering {} / {}...".format(index + 1, len(times)))
                    QApplication.processEvents()
        finally:
            if progress:
                QApplication.restoreOverrideCursor()
            self.timeline.seek(keep)
            self._apply_timeline()
        if where["format"] == anim_mod.FORMAT_PNG:
            return True, "Wrote {} frame(s) to {}".format(
                n, os.path.basename(where["path"]))
        pattern = anim_mod.sequence_path(directory, where["base"], 0,
                                         where["digits"]).replace(
                                             "_{:0{}d}".format(
                                                 0, where["digits"]),
                                             "_%0{}d".format(where["digits"]))
        ok, note = anim_mod.encode(pattern, where["path"], opts["fps"],
                                   where["format"],
                                   hint=self.ffmpeg_hint)
        if ok:
            import shutil as _sh
            if temp:
                _sh.rmtree(temp, ignore_errors=True)
            return True, "Wrote {} ({} frames at {:g} fps)".format(
                os.path.basename(where["path"]), n, opts["fps"])
        return False, ("The {} frames rendered to\n{}\n\nbut the encode "
                       "failed:\n\n{}".format(n, directory, note))

    def on_render_key(self, animation=False):
        """F12 / Ctrl+F12 — Blender's render keys, with Blender's habit.

        The FIRST press behaves like the ordinary export: the dialog opens and
        a file is chosen. From then on the same key RENDERS IMMEDIATELY with
        those settings, which is what F12 means to anyone who uses Blender —
        the deliberate route (Ctrl+Shift+E / Ctrl+Shift+A) still opens the
        dialog every time, so nothing is taken away.

        Press-and-forget is only safe because the filename increments
        (`animation.next_free`): a render key that silently replaces the last
        render is a key you cannot press twice.
        """
        remembered = self._render_target.get(bool(animation))
        if remembered is None:
            if animation:
                self.on_export_animation()
            else:
                self.on_export_image()
            return
        if remembered is not None and not remembered.get("path"):
            self._render_target.pop(bool(animation), None)
            return self.on_render_key(animation)
        if animation:
            self._render_animation_again(remembered)
        else:
            self._render_still_again(remembered)

    def on_render_settings(self, animation):
        """Reopen the export dialog. F12's way back.

        F12's press-and-forget behaviour is right, but it left the settings
        with no way back - the dialog only ever appeared on the first render.
        This reopens it immediately rather than just clearing the memory,
        because "ask me next time" is never what someone wants when they have
        gone looking for the settings.

        **The memory is NOT cleared first**, which it used to be. Both export
        dialogs read the remembered options to open on your last choices
        (round 61), so popping them first meant the one route whose whole
        purpose is "let me change a setting" was also the one route that threw
        the settings away and opened on the defaults. Nothing needs clearing:
        `on_export_image` and `on_export_animation` always ask.
        """
        if animation:
            self.on_export_animation()
        else:
            self.on_export_image()

    def _render_still_again(self, remembered):
        """F12 after the first export: the SAME options, the next filename.

        The remembered path stays the BASE one. Storing the incremented name
        instead compounds the suffix - three presses gave shot.png,
        shot_001.png, shot_001_001.png.
        """
        path = anim_mod.next_free(remembered["path"],
                                  remembered.get("increment", True))
        self._write_still(remembered.get("opts") or {}, path)

    def _render_animation_again(self, remembered):
        times = anim_mod.frame_times(self.timeline,
                                     loops=remembered["opts"]["loops"])
        if not times:
            self.statusBar().showMessage("Nothing to animate", 5000)
            return
        path = anim_mod.next_free(remembered["path"],
                                  remembered.get("increment", True))
        try:
            ok, message = self.write_animation(path, times,
                                               remembered["opts"])
        except Exception as e:
            QMessageBox.critical(self, "Render failed", str(e))
            return
        if ok:
            self.statusBar().showMessage(
                message + " — Ctrl+F12 again for the next", 12000)
        else:
            QMessageBox.warning(self, "Render", message)

    # --------------------------------------------------------------- cameras
    def on_place_camera(self):
        """F3 / the outliner: save the current view as a camera object."""
        vp = self.viewport
        self.push_undo()
        cam = self.scene.add_camera(camera=vp.camera, width=vp.width(),
                                    height=vp.height())
        # Size the DRAWN frame once, here. The frame is angular, so its size
        # is a stored property rather than something recomputed per draw —
        # which is exactly what stops a handle drag rescaling the scene.
        cam.fit_frame(vp.width(), vp.height())
        self._view_before_camera = self._current_view()
        self.viewport.looking_through = cam.id
        vp.sync_camera_lens()
        self._sync_all()
        self.statusBar().showMessage(
            "{} placed here — {:.0f} mm, {}x{}. Numpad 0 looks through it "
            "again.".format(cam.name, cam.focal_mm, cam.width, cam.height),
            9000)

    def on_activate_camera(self, cam_id=None):
        """Numpad 0: look through a camera — and press it again to leave.

        Toggling rather than only entering is Blender's behaviour and the
        thing that makes the key usable: you glance through the shot, then go
        back to the view you were composing from.
        """
        vp = self.viewport
        if cam_id is None:
            if vp.looking_through is not None:
                self.leave_camera()
                return
            cam_id = self.scene.active_camera_id
        cam = self.scene.camera(cam_id) if cam_id is not None else None
        if cam is None:
            self.statusBar().showMessage(
                "No camera yet — F3 \"Camera: place one here\" saves this "
                "view as one", 6000)
            return
        # Remember where we were, so leaving the camera puts the user back
        # rather than stranding them inside a shot.
        if vp.looking_through is None:
            self._view_before_camera = self._current_view()
        self.scene.active_camera_id = cam.id
        cam.apply_to(vp.camera)
        vp.looking_through = cam.id
        vp.camera_roll = float(cam.roll)
        vp.sync_camera_lens()
        self._sync_all()
        self.statusBar().showMessage(
            "Looking through {} ({:.0f} mm, {}x{} at {:g}x) — orbit or "
            "Numpad 0 to leave".format(cam.name, cam.focal_mm, cam.width,
                                       cam.height, cam.multiplier), 9000)

    def _current_view(self):
        """The interactive camera's pose as a plain dict."""
        cam = self.viewport.camera
        return {"center": np.array(cam.center, dtype=float),
                "distance": float(cam.distance),
                "rotation": np.array(cam.rotation, dtype=float),
                "orthographic": bool(cam.orthographic)}

    def leave_camera(self, restore=True, message="Free view"):
        """Back to the free view.

        `restore=True` is the Numpad 0 toggle: it puts the view back where it
        was before you looked through the camera, which is what makes the key
        a glance rather than a one-way trip.

        `restore=False` is the ORBIT exit (round 57). You left by moving, so
        the pose you are holding is the one you want — restoring would undo
        the gesture that caused the exit, which is precisely backwards. The
        remembered view is dropped with it, since a subsequent Numpad 0 will
        capture the pose you have now on the way back in.
        """
        vp = self.viewport
        vp.looking_through = None
        vp.camera_roll = 0.0
        saved = self._view_before_camera
        if restore and saved:
            vp.camera.center = saved["center"].copy()
            vp.camera.distance = saved["distance"]
            vp.camera.rotation = saved["rotation"].copy()
            vp.camera.orthographic = saved["orthographic"]
        self._view_before_camera = None
        vp.sync_camera_lens()
        self._sync_all()
        if message:
            self.statusBar().showMessage(message, 4000)

    def on_update_camera(self):
        """Re-aim the active camera at the view you are looking from."""
        cam = self.scene.active_camera()
        if cam is None:
            return
        vp = self.viewport
        self.push_undo()
        keep = (cam.width, cam.height, cam.multiplier, cam.frame_zoom)
        # The roll is handed in so `capture` can take it back OFF the pose it
        # stores — the view rotation already carries it, and storing it in
        # both places would tilt the camera twice on the next activation.
        cam.capture(vp.camera, roll=float(getattr(vp, "camera_roll", 0.0)))
        cam.width, cam.height, cam.multiplier, cam.frame_zoom = keep
        vp.sync_camera_lens()
        self._sync_all()
        self.statusBar().showMessage(
            "{} now looks from here".format(cam.name), 7000)

    def on_delete_camera(self, cam_id=None):
        cam = (self.scene.camera(cam_id) if cam_id is not None
               else self.scene.active_camera())
        if cam is None:
            return
        self.push_undo()
        if self.viewport.looking_through == cam.id:
            self.leave_camera()
        if self.viewport.selected_camera_id == cam.id:
            self.viewport.selected_camera_id = None
        name = cam.name
        self.scene.remove_camera(cam.id)
        self._sync_all()
        self.statusBar().showMessage("Deleted {}".format(name), 6000)

    def camera_changed(self, cam_id=None):
        """A camera's settings were edited — re-apply if we are inside it.

        The LENS only, never the pose. Round 57, Christian: "clicking on one
        of the scaling knobs of the camera view also resets a previous dolly."
        It did — every edit ran `apply_to`, which assigns centre, distance and
        rotation, so touching the resolution threw away any navigating done
        since Numpad 0. Changing the film size is not a statement about where
        the camera stands.

        A rolled pose is the one exception, because roll lives in the
        rotation: it is re-applied against the pose you are actually holding
        rather than against the camera's stored one, so a dolly survives that
        too.
        """
        cam = (self.scene.camera(cam_id) if cam_id is not None
               else self.scene.active_camera())
        vp = self.viewport
        if cam is not None and vp.looking_through == cam.id:
            if float(cam.roll) != float(vp.camera_roll):
                vp.camera.rotation = cameras_mod.twist_rotation(
                    vp.camera.rotation, float(cam.roll) - float(vp.camera_roll))
                vp.camera_roll = float(cam.roll)
            vp.sync_camera_lens()
        vp.refresh_geometry()
        vp.update()

    def on_graphics_info(self):
        """Which GPU is drawing the viewport, and at what GL version.

        Not idle curiosity: a QOpenGLWidget draws on the GPU, but on a machine
        with an integrated adapter AND a discrete one, which of the two a
        given process gets is the driver's decision, not the program's — and
        a Python process usually lands on the integrated one unless told
        otherwise. `GL_RENDERER` is the only way to know, and if it names the
        integrated chip the fix is a per-application setting in the graphics
        control panel rather than anything in MoloM.
        """
        info = self.viewport.graphics_info()
        if not info:
            self.statusBar().showMessage(
                "The OpenGL context is not up yet", 5000)
            return
        body = "<br>".join(
            "<b>{}</b>: {}".format(k.upper() if k == "glsl" else k.title(),
                                   info[k])
            for k in ("renderer", "vendor", "version", "glsl", "profile",
                      "samples") if k in info)
        body += ("<br><i>Samples is the LIVE multisampling of the framebuffer "
                 "being drawn into, not what the surface format claims.</i>")
        box = QMessageBox(self)
        box.setWindowTitle("Graphics device")
        box.setIcon(QMessageBox.Information)
        box.setTextFormat(Qt.RichText)
        box.setText(
            "MoloM draws through OpenGL, so the viewport runs on the GPU "
            "named below.<br><br>{}<br><br>"
            "If that is an integrated chip and the machine also has a "
            "discrete card, the choice is made by the driver, not by MoloM — "
            "set a per-application preference for <tt>python.exe</tt> in the "
            "graphics control panel to change it.".format(body))
        # A driver string is the first thing anyone is asked to paste into a
        # bug report, and a QMessageBox is not selectable by default.
        box.setTextInteractionFlags(Qt.TextSelectableByMouse
                                    | Qt.TextSelectableByKeyboard)
        box.exec()
        self.statusBar().showMessage(
            "Drawing on: {}".format(info.get("renderer", "unknown")), 10000)

    def on_site_occupancy(self):
        """F3: say what a shared crystallographic site is made of.

        The one thing no derivation can recover — the co-located species are
        merged away at import before occupancy is consulted (round 45e), so
        the composition lives in a table and nothing in the coordinates
        implies it. Letting the user state it is the only honest answer, and
        it closes the gap the CIF writer had to report as a limit.
        """
        from ..core import occupancy as occ_mod
        obj = self._active_obj()
        if obj is None or cell_of(obj) is None:
            self.statusBar().showMessage(
                "Select a crystal — a shared site is a crystallographic "
                "position, so this needs a unit cell", 6000)
            return
        rows = sorted({i for o, i in self.viewport.selection if o == obj.id})
        if not rows:
            self.statusBar().showMessage(
                "Select one atom of the site whose composition you want to "
                "set", 6000)
            return
        s = obj.structure
        meta = s.metadata
        index = rows[0]
        orbit = occ_mod.orbit_of(meta, index, s.n_atoms)
        # The picked atoms always count, even where there is no `site_of` to
        # give the orbit — otherwise selecting three atoms and getting one
        # edited would be a silent surprise.
        orbit = sorted(set(orbit) | set(rows))
        parts = occ_mod.composition_of(meta, index)
        if not parts:
            parts = [(s.symbols[index], float(s.occupancy_of(index) or 1.0)
                      if hasattr(s, "occupancy_of") else 1.0)]
        dlg = SiteOccupancyDialog(self, parts,
                                  label=self.scene.pick_label((obj.id, index)),
                                  n_atoms=len(orbit))
        if not dlg.exec():
            return
        self.push_undo()
        chosen = dlg.parts()
        occ_mod.set_composition(meta, orbit, chosen)
        # Marks the stored asymmetric unit as no longer the whole truth: it is
        # the FILE's unit, from before the user said otherwise, so the writer
        # has to build from the drawn atoms instead of round-tripping it.
        meta["site_occupancy_edited"] = True
        self.viewport.refresh_geometry()
        self._sync_crystal_page()
        self.statusBar().showMessage(
            "{}: {} atom(s) set to {}".format(
                obj.name, len(orbit),
                occ_mod.describe(chosen) or "a plain full atom"), 8000)

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

    @staticmethod
    def _reconstructs(obj, meta, frac, n_content):
        # type: (object, dict, object, int) -> bool
        """Do the stored unit and operators actually rebuild this cell?

        The invariant every crystal rebuild depends on, and the one thing
        nobody was checking. `cif_write` asks the same question of a file it
        is about to write, so the two share the machinery.
        """
        unit = list(meta.get("asym_symbols") or [])
        if not unit:
            return False
        expanded_s, expanded_f = cif_write._expand(
            unit, np.asarray(meta.get("asym_frac") or [], dtype=float),
            [str(t) for t in (meta.get("symops") or ["x,y,z"])])
        return cif_write._covered(
            list(obj.structure.symbols)[:n_content],
            np.asarray(frac, dtype=float).reshape(-1, 3)[:n_content],
            expanded_s, expanded_f)

    def resync_derived_asymmetric_unit(self, obj, cell, frac, identity=False):
        # type: (object, object, object, bool) -> int
        """Re-derive the stored asymmetric unit to match re-derived operators.

        A rebuild is `asym_symbols` + `asym_frac` expanded by `symops`, so
        those three have to describe ONE structure. Round 43d re-derived the
        operators after an edit and left the unit alone, which silently made
        them describe two — and the rebuild believes the metadata, not the
        atoms in front of it.

        Taken from the cell CONTENT, never from the drawn atoms: everything
        past `cell_content` is a boundary copy, and expanding a unit that
        already contains copies puts them in twice.
        """
        s = obj.structure
        meta = s.metadata
        n = min(int(meta.get("cell_content") or 0) or s.n_atoms, s.n_atoms)
        symbols = list(s.symbols)[:n]
        content = np.asarray(frac, dtype=float).reshape(-1, 3)[:n]
        reps = None
        if not identity:
            try:
                reps = spacegroups.orbit_representatives(cell, symbols,
                                                         content)
            except Exception:
                reps = None
        # Under P1 every atom IS its own orbit, so the cell content is the
        # asymmetric unit — which is also the honest answer when no dataset
        # came back, rather than a reason to leave a stale unit in place.
        # `identity=True` says so up front and skips the search: asking spglib
        # and then ignoring the answer is how the two ended up disagreeing.
        if not reps:
            reps = list(range(n))
        meta["asym_symbols"] = [symbols[i] for i in reps]
        # WRAPPED into [0,1). The drawn content is not: `packing.pack` unwraps
        # molecules to keep them whole, so 34 of ferrocene's 42 content atoms
        # sit between -0.43 and 1.43. Storing those as the unit means the next
        # rebuild wraps them itself, tearing the molecules apart before the
        # completion runs — 210 drawn atoms came back as 168. Wrapping here
        # makes the stored unit the canonical cell content, which is what
        # `expand` would have produced, so the rebuild reproduces the picture.
        meta["asym_frac"] = [[float(v) for v in (content[i] % 1.0)]
                             for i in reps]
        # The parallel columns describe the OLD sites, so they cannot be
        # sliced — but they need not be thrown away either: `packing.pack`
        # records which asymmetric-unit site each DRAWN atom came from, so
        # each new representative can be looked up in the old columns. That
        # is what stops a re-exported solid solution silently claiming full
        # occupancy for every species on a shared site. Where the mapping is
        # absent the column goes, because a mis-indexed occupancy is worse
        # than none (round 43e).
        columns, _missing = cif_write._site_columns(meta, reps, s.n_atoms)
        for key, source in (("occupancy", "asym_occupancy"),
                            ("labels", "asym_labels"),
                            ("disorder_groups", "asym_disorder_groups"),
                            ("disorder_assemblies",
                             "asym_disorder_assemblies")):
            if key in columns:
                meta[source] = list(columns[key])
            else:
                meta.pop(source, None)
        # `site_of` described the unit that has just been replaced, so it is
        # dropped rather than left to be believed by the next caller — the
        # round-42 rule about a per-atom map surviving a renumbering.
        meta.pop("site_of", None)
        # Re-pin the cell frame against the CELL-frame coordinates, or the
        # Kabsch fit keeps measuring the edit as a rotation of the whole
        # crystal and the box creeps further with every atom moved (round
        # 43e). The full-cell branch never did this; only the asymmetric one.
        set_cell_reference(s, cell.to_cartesian(
            np.asarray(frac, dtype=float).reshape(-1, 3)))
        return len(reps)

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
        # The stored asymmetric unit belonged to the OLD operators, and every
        # crystal rebuild regenerates from `asym_symbols` + `symops` together.
        # Leaving the two inconsistent is what made a single H -> F on MOF-5
        # destroy the structure the moment anything on the ❖ page was touched:
        # 616 drawn atoms came back as 7, the file's asymmetric unit expanded
        # by a 2-operator group.
        keep = dict(meta)
        meta["symops"] = list(ops)
        meta["spacegroup"] = symbol
        meta["it_number"] = int(number or 0)
        meta.pop("hall", None)
        n_reps = self.resync_derived_asymmetric_unit(obj, cell, frac)
        # ...and then CHECK IT. "spglib found a group" is not the same claim as
        # "this unit and these operators rebuild this cell", and the two came
        # apart on MOF-5: R3m with 6 operators over 7 orbits, i.e. 42 atoms
        # where the cell holds 424. A group that cannot reconstruct the
        # structure is not an answer, so it is refused rather than stored.
        n_content = min(int(meta.get("cell_content") or 0)
                        or obj.structure.n_atoms, obj.structure.n_atoms)
        if not self._reconstructs(obj, meta, frac, n_content):
            for key in ("symops", "spacegroup", "it_number", "hall",
                        "asym_symbols", "asym_frac", "asym_occupancy",
                        "asym_labels", "asym_disorder_groups",
                        "asym_disorder_assemblies", "site_of"):
                meta.pop(key, None)
                if key in keep:
                    meta[key] = keep[key]
            if announce:
                self.statusBar().showMessage(
                    "{}: spglib offered {} ({} operator(s), {} site(s)), but "
                    "that does not rebuild this cell's {} atoms — keeping {}"
                    .format(obj.name, symbol, len(ops), n_reps, n_content,
                            was or "the stored symmetry"), 9000)
            return None
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
            # No sample to fit against - an asymmetric unit of one or two
            # atoms has none. The pose the last rebuild recorded is what
            # keeps the crystal where the user put it.
            return stored_cell_pose(structure)
        try:
            cur = np.asarray([structure.coords[int(i)] for i in idx],
                             dtype=float)
        except (IndexError, ValueError):
            return stored_cell_pose(structure)
        fit = cif_mod.rigid_from_reference(np.asarray(ref, dtype=float), cur)
        return fit if fit is not None else stored_cell_pose(structure)

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
        # The content count travels with the modifier so it can build the
        # periodic bond graph on the cell's own atoms rather than on the
        # picture, which already carries copies.
        try:
            content = int(obj.structure.metadata.get("cell_content") or 0)
        except AttributeError:
            content = 0
        return modifiers_mod.BoundaryModifier(
            cell=cell.to_dict() if cell is not None else None, shells=shells,
            content=content)

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
        if s.metadata.get("packed"):
            # `core.packing` already completed every fragment reaching into
            # the cell and instantiated its bonds. Running the modifier on top
            # would grow a shell of a shell.
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

    def on_toggle_cell_zorder(self, export=False):
        """Flip the cell box between painted-on-top and real geometry.

        Two settings, not one. On screen the box is partly a navigation aid
        and an edge disappearing behind the framework is a real loss; in an
        export the picture has to be true, and an overlay says every edge it
        crosses is in front of the structure - which on a dense cell is
        visibly wrong, and is what Christian reported.
        """
        attr = "cell_zorder_export" if export else "cell_zorder"
        now = getattr(self.viewport, attr)
        new = (cellbox.DEPTH if now == cellbox.OVERLAY else cellbox.OVERLAY)
        setattr(self.viewport, attr, new)
        self.settings.setValue(attr, new)
        self.viewport.update()
        self.statusBar().showMessage(
            "Unit cell box ({}): {}".format(
                "image export" if export else "viewport",
                "drawn on top of everything" if new == cellbox.OVERLAY
                else "occluded by what is in front of it"), 5000)

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
            # The EDITOR stays live with no cell - that is the case it exists
            # for. Everything else on the page greys out, but "give this
            # molecule a box" has to remain reachable.
            self.crystal_page.cell_editor.setEnabled(obj is not None)
            return
        meta = obj.structure.metadata
        # Keep the editor showing the cell it would change, so opening it never
        # presents numbers belonging to a different molecule.
        self.crystal_page.cell_editor.setEnabled(True)
        self.crystal_page.set_cell_fields(cell, meta.get("spacegroup", ""))
        self._sync_fractional()
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
            outside=bool(meta.get("pack_outside", True)),
            copies=bool(meta.get("pack_copies", False)),
            # Every per-crystal display flag, read back from the OBJECT. They
            # are stored per molecule, so leaving the ticks where the last one
            # left them makes the page describe a structure that is not on
            # screen: "Coordination polyhedra" reads ticked over a crystal
            # that has none, and the only way to get a picture is to untick
            # and retick it (Christian). The box tick is a viewport-wide
            # setting, so it is deliberately not in this list.
            polyhedra=bool(meta.get("polyhedra")),
            symmetry_on=bool(meta.get("show_symmetry")),
            ghosts=bool(meta.get("show_ghosts")),
            occupancy=bool(self.viewport.show_occupancy),
            frozen=bool(meta.get("cell_frozen")),
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
        # A cell the user has EDITED is not regenerated. In P1 the asymmetric
        # unit IS the cell content, so there is no symmetry left to apply —
        # and re-running the packing on atoms it has already relocated does
        # not reproduce the picture: round 45d's trap, measured here as
        # ferrocene coming back with 4 complete molecules where it had 5, and
        # 210 drawn atoms as 168. The atoms in front of us ARE the cell.
        if meta.get("cell_frozen"):
            if mode == "packing":
                # A supercell has to REGENERATE, which is the one thing an
                # edited cell cannot survive — and there would then be no way
                # back to the single cell, since the frozen atoms are the only
                # copy of it. Refused rather than offered and then lost.
                self.statusBar().showMessage(
                    "{} was edited in the full cell, so it cannot be packed "
                    "into a supercell — the edit is the structure now. Use an "
                    "Array modifier to repeat it.".format(obj.name), 9000)
                self._sync_crystal_page()
                return
            meta["cell_view"] = mode
            self.statusBar().showMessage(
                "{} was edited in the full cell, so it is P1 — the "
                "asymmetric unit and the cell are the same atoms".format(
                    obj.name), 7000)
            self._sync_all()
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
            outside=bool(meta.get("pack_outside", True)),
            grow_from_copies=bool(meta.get("pack_copies", False)),
            report=report, **self._view_disorder_kwargs(meta))
        if report.get("disorder"):
            meta["disorder"] = dict(report["disorder"])
        # A rebuilt view renumbers everything, so the content boundary the
        # periodic bond graph is built on has to be replaced with it. In a
        # PACKING the content is still the first cell's — every other cell is
        # a lattice translate of it, which is exactly what the graph labels.
        if report.get("packed_bonds") is not None:
            # Carried the same way an import does, so `_perceive_fresh` uses
            # the graph's answer rather than re-perceiving straight lines.
            meta["packed_bonds"] = report["packed_bonds"]
            meta["packed"] = True
        if report.get("n_content"):
            meta["cell_content"] = int(report["n_content"])
            # A boundary modifier already on the stack holds the OLD count,
            # and a stale one would label the new picture against the wrong
            # atoms — silently, since every index still exists.
            existing = self._boundary_modifier(obj)
            if existing is not None:
                existing.content = int(report["n_content"])
        # A rebuilt view renumbers the atoms, so EVERY per-atom map has to be
        # replaced with them or dropped — a stale one stays perfectly valid
        # and quietly describes different atoms, which is round 80's lesson in
        # the one place that regenerates the atom list wholesale rather than
        # editing it.
        #
        # `site_occupancy` was already handled here; `site_of` and
        # `content_of` were not, and `content_of` is the dangerous one: it is
        # what `images_of` reads to decide which atoms are copies of the same
        # site, and `on_delete_selected` deletes every image of what you
        # picked. A stale one therefore deletes the wrong atoms. The
        # asymmetric-unit mode produces neither, so there they are simply
        # dropped rather than left describing the full cell.
        # `asym_rows` rides with them: it describes the view just built, so a
        # stale one from the previous mode would tell the write-back that two
        # drawn atoms stand for five rows of a structure that is no longer on
        # screen. Round 80's rule, in the one place that regenerates the atom
        # list wholesale.
        for key in ("site_occupancy", "site_of", "content_of", "asym_rows"):
            meta.pop(key, None)
            if report.get(key) is not None:
                meta[key] = (dict(report[key])
                             if isinstance(report[key], dict)
                             else list(report[key]))
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
        # ...and RECORD the pose, because an asymmetric unit of one or two
        # atoms cannot carry a reference sample: switching an `F m -3 m`
        # fluoride (unit: 2 atoms) to "asymmetric unit only" left it with no
        # way to recover its placement, so the crystal and its box snapped to
        # the origin on the way back to the full cell.
        set_cell_pose(s, pose)
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

    # ------------------------------------------------- defining a unit cell
    def on_suggest_cell(self):
        """Fill the editor with the molecule's own bounding box.

        So "define a cell" does not open on 1x1x1 and demand six numbers before
        anything can be seen.
        """
        obj = self._active_obj()
        if obj is None:
            return
        cell = celledit.suggest_cell(obj.structure)
        self.crystal_page.set_cell_fields(cell)
        self.crystal_page.set_cell_note(
            "Filled from the molecule's bounding box plus a 2 A margin. "
            "Adjust and press Apply.")

    def on_apply_cell(self):
        """Put the typed cell onto the active molecule."""
        obj = self._active_obj()
        if obj is None:
            return
        values, group, keep_frac = self.crystal_page.cell_fields()
        had = celledit.cell_of(obj.structure) is not None
        try:
            cell = celledit.make_cell(**values)
        except celledit.CellError as exc:
            # Refused, and SAID so on the page rather than in a status bar
            # message that four seconds later is gone.
            self.crystal_page.set_cell_note(str(exc), error=True)
            return
        symops = None
        note_bits = []
        if group:
            # A symbol is resolved through the same Hall database a file's own
            # symbol goes through (round 40), so a cell defined here expands
            # exactly as an imported one would.
            resolved = spacegroups.operators_for(group)
            if resolved is None:
                self.crystal_page.set_cell_note(
                    "Space group {!r} was not recognised - the cell was not "
                    "changed. Leave it empty for P1.".format(group), error=True)
                return
            symops = list(resolved.xyz)
            note_bits.append("{} with {} operator(s)".format(
                resolved.symbol or group, len(symops)))
        self.push_undo()
        report = celledit.apply_cell(obj.structure, cell,
                                     keep_fractional=keep_frac,
                                     symops=symops, spacegroup=group or None)
        note_bits.insert(0, "Cell {}".format("updated" if had else "added"))
        if report["kept"] == "fractional" and report["moved"]:
            note_bits.append("{} atom(s) moved with the frame".format(
                report["moved"]))
        elif not had:
            note_bits.append("atoms left where they are")
        self.viewport.show_cell = True
        self.viewport.refresh_geometry()
        self._after_edit()
        self._sync_all()
        self.crystal_page.set_cell_note(" - ".join(note_bits))
        self.statusBar().showMessage(" - ".join(note_bits), 8000)

    def on_remove_cell(self):
        obj = self._active_obj()
        if obj is None:
            return
        self.push_undo()
        if not celledit.clear_cell(obj.structure):
            self.crystal_page.set_cell_note("This molecule has no cell.")
            return
        self.viewport.refresh_geometry()
        self._after_edit()
        self._sync_all()
        self.crystal_page.set_cell_note(
            "Cell removed - the atoms are untouched.")

    def _frac_target(self):
        """`(obj, atom_index)` when exactly one atom is picked on a molecule
        that has a cell, else `(None, None)`."""
        obj = self._active_obj()
        if obj is None or celledit.cell_of(obj.structure) is None:
            return None, None
        rows = [i for o, i in self.viewport.selection if o == obj.id]
        if len(rows) != 1 or rows[0] >= obj.structure.n_atoms:
            return None, None
        return obj, int(rows[0])

    def _sync_fractional(self):
        """Show the picked atom's fractional position on the ❖ page."""
        obj, index = self._frac_target()
        if obj is None:
            self.crystal_page.set_frac_fields(None)
            return
        frac = celledit.fractional_of(obj.structure, index)
        self.crystal_page.set_frac_fields(
            frac, "{}{} of {}".format(obj.structure.symbols[index], index,
                                      obj.name))

    def on_apply_fractional(self):
        """Move the picked atom to the typed fractional position."""
        obj, index = self._frac_target()
        if obj is None:
            self.crystal_page.set_frac_fields(None)
            return
        values, wrap = self.crystal_page.frac_fields()
        self.push_undo()
        try:
            celledit.set_fractional(obj.structure, index, values, wrap=wrap)
        except celledit.CellError as exc:
            self.crystal_page.frac_note.setText(str(exc))
            return
        self.viewport.refresh_geometry()
        self._after_edit()
        self._sync_fractional()
        self.statusBar().showMessage(
            "{}{} moved to ({:.4f}, {:.4f}, {:.4f})".format(
                obj.structure.symbols[index], index, *values), 7000)

    def on_operator_search(self):
        # The last operator run is pre-selected on an empty search, so pressing
        # F3-Enter repeats it. That is Blender's behaviour and it is what makes
        # the palette usable for something you are doing over and over.
        dlg = OperatorSearchDialog(self, self.ops, self,
                                   last=self._last_operator)
        if dlg.exec() and dlg.chosen is not None:
            self._last_operator = dlg.chosen.id
            dlg.chosen.run(self)

    # ------------------------------------------------------------- add-ons
    def _init_addons(self):
        """Discover add-ons and enable the ones that were on last time.

        Runs LAST in `__init__`, after every dock and page exists, because an
        add-on's `register()` is handed this window and will reach straight
        into it. A failure disables the add-on and is reported — it must
        never stop MoloM starting.
        """
        from ..core import addons as addons_mod
        self.addons = addons_mod.AddOnManager()
        wanted = [a for a in (self.settings.value("addons/enabled", [])
                              or []) if a]
        if isinstance(wanted, str):          # QSettings collapses a 1-element
            wanted = [wanted]                # list to a bare string
        failed = self.addons.enable_all(wanted, self)
        if failed:
            self.statusBar().showMessage(
                "{} add-on(s) failed to load — see App > Add-ons".format(
                    len(failed)), 10000)

    def save_enabled_addons(self):
        self.settings.setValue("addons/enabled",
                               sorted(self.addons.enabled))

    def on_addons(self):
        from .addons_dialog import AddOnsDialog
        dialog = getattr(self, "_addons_dialog", None)
        if dialog is None:
            dialog = AddOnsDialog(self, self)
            self._addons_dialog = dialog
        dialog.rebuild()
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

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
            render_crop=self.viewport.render_crop,
            input_preset=self.viewport.input_preset,
            label_scale=self.viewport.label_scale,
            disorder_policy=self.disorder_policy,
            sg_convention=self.sg_convention,
            cif_search_root=(self.settings.value("cif_search_root", "")
                             or ""),
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
                    "aim_expo": "fly_aim_expo", "hold_ms": "fly_hold_ms",
                    "shuttle_factor": "shuttle_factor"}

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
        elif key == "shuttle_factor":
            # Live-applied to a SHUTTLE in progress only: it is the difference
            # between the two modes, so pushing it into a camera flight would
            # slow down the thing it does not describe. Rebuilt from the
            # unscaled settings so repeated edits cannot compound.
            if fly["obj_id"] is not None:
                fly["model"].accel, fly["model"].max_speed = \
                    flight_mod.shuttle_scaled(
                        float(self.viewport.fly_accel),
                        flight_mod.DEFAULT_MAX_SPEED, float(value))
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
            self.settings.setValue("cif_search_root", dlg.cif_search_root())
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
            self.viewport.render_crop = dlg.render_crop()
            self.settings.setValue("render_scale", dlg.render_scale())
            self.settings.setValue("render_subdiv", dlg.render_subdiv())
            self.settings.setValue("render_crop",
                                   "true" if dlg.render_crop() else "false")
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
