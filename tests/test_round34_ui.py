"""Round 34, UI half: the CIF page's arrow, the right-click geometry menu,
the internal-coordinate modal, and right-mouse flight.

The core maths lives in `test_round34_internal.py`; this file pins the things
that can only go wrong once Qt is involved — signal arguments, modal
bookkeeping, and which state owns the keyboard.
"""

import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from molom.core import flight, internal, measure
from molom.core.structure import Structure


def _propane():
    """C-C-C with a hydrogen on the far carbon: three real internal
    coordinates and a fragment that has to follow each of them."""
    s = Structure.from_atoms([
        ("C", 0.0, 0.0, 0.0),
        ("C", 1.5, 0.0, 0.0),
        ("C", 2.3, 1.2, 0.0),
        ("H", 3.4, 1.1, 0.4),
    ], name="propane-ish")
    s.bonds = [(0, 1, 1), (1, 2, 1), (2, 3, 1)]
    return s


@pytest.fixture
def win():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.app import MainWindow
    QApplication.instance() or QApplication([])
    w = MainWindow()
    w.show()
    w.load_default_scene()
    return w


@pytest.fixture
def chain(win):
    """A window whose active molecule is the propane-ish chain."""
    obj = win._install_structure(_propane())
    if obj is None:                       # _install_structure may return None
        obj = win.scene.objects[-1]
    win.active_id = obj.id
    return win, obj


# ------------------------------------------------------ CIF page: the arrow
@pytest.fixture
def crystal_win(tmp_path):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.app import MainWindow
    from tests.test_round18_cif import NACL_CIF
    QApplication.instance() or QApplication([])
    w = MainWindow()
    w.show()
    path = tmp_path / "nacl.cif"
    path.write_text(NACL_CIF, encoding="utf-8")
    w.open_path(str(path))
    return w


def test_the_symmetry_arrow_expands_every_time(crystal_win):
    """The reported bug: expand once, and the arrow never worked again until
    the checkbox was unticked and reticked.

    `QToolButton.clicked` carries the button's checked state, and this button
    is not checkable — so it always passed False, i.e. "collapse".
    """
    page = crystal_win.crystal_page
    holder = page._kind_holder
    assert holder.isHidden()

    page.sym_arrow.click()
    assert not holder.isHidden()
    page.sym_arrow.click()
    assert holder.isHidden()
    page.sym_arrow.click()                # this is the one that used to fail
    assert not holder.isHidden()


def test_expanding_the_arrow_ticks_the_symmetry_box(crystal_win):
    page = crystal_win.crystal_page
    page.sym_check.setChecked(False)
    page.sym_arrow.click()
    assert page.sym_check.isChecked()


def test_collapsing_the_arrow_leaves_the_box_alone(crystal_win):
    """Only EXPANDING implies intent; collapsing the filters must not switch
    the elements off underneath you."""
    page = crystal_win.crystal_page
    page.sym_arrow.click()
    assert page.sym_check.isChecked()
    page.sym_arrow.click()
    assert page.sym_check.isChecked()


def test_the_arrow_does_not_tick_a_disabled_box(win):
    """On a molecule with no cell everything is greyed — the arrow must not
    reach around that and switch symmetry on for something without any."""
    page = win.crystal_page
    page.set_cell(None)
    page._toggle_kinds(True)
    assert not page.sym_check.isChecked()


# ------------------------------------------------ internal_picks bookkeeping
def test_internal_picks_keeps_click_order(chain):
    win, obj = chain
    win.viewport.set_selection([(obj.id, 2), (obj.id, 1), (obj.id, 0)])
    assert win.viewport.internal_picks() == (obj.id, [2, 1, 0])


def test_internal_picks_refuses_two_molecules(chain):
    win, obj = chain
    other = win.scene.objects[0]
    win.viewport.set_selection([(obj.id, 0), (other.id, 0)])
    assert win.viewport.internal_picks() is None


def test_internal_picks_refuses_a_repeated_atom(chain):
    win, obj = chain
    win.viewport.set_selection([(obj.id, 0), (obj.id, 0)])
    assert win.viewport.internal_picks() is None


# ------------------------------------------------------- the modal, end to end
def test_setting_a_bond_length_drags_the_rest_of_the_chain(chain):
    win, obj = chain
    vp = win.viewport
    vp.set_selection([(obj.id, 0), (obj.id, 1)])
    before = obj.structure.coords.copy()
    vp.start_internal(internal.DISTANCE)
    assert vp.modal_active()
    vp._internal["state"].type_char("2")
    vp._internal["state"].type_char(".")
    vp._internal["state"].type_char("0")
    vp._apply_internal()
    vp._finish_internal(commit=True)

    c = obj.structure.coords
    assert measure.distance(c[0], c[1]) == pytest.approx(2.0)
    assert np.allclose(c[0], before[0])                  # anchor stayed
    # ...and everything past the bond kept its own geometry exactly
    assert measure.distance(c[1], c[2]) == \
        pytest.approx(measure.distance(before[1], before[2]))
    assert measure.distance(c[2], c[3]) == \
        pytest.approx(measure.distance(before[2], before[3]))
    assert measure.angle(c[1], c[2], c[3]) == \
        pytest.approx(measure.angle(before[1], before[2], before[3]))


def test_setting_an_angle_swings_the_far_fragment(chain):
    win, obj = chain
    vp = win.viewport
    vp.set_selection([(obj.id, 0), (obj.id, 1), (obj.id, 2)])
    before = obj.structure.coords.copy()
    vp.start_internal(internal.ANGLE)
    for ch in "100":
        vp._internal["state"].type_char(ch)
    vp._apply_internal()
    vp._finish_internal(commit=True)
    c = obj.structure.coords
    assert measure.angle(c[0], c[1], c[2]) == pytest.approx(100.0)
    assert measure.distance(c[2], c[3]) == \
        pytest.approx(measure.distance(before[2], before[3]))


def test_setting_a_dihedral_spins_the_tail(chain):
    win, obj = chain
    vp = win.viewport
    vp.set_selection([(obj.id, i) for i in (0, 1, 2, 3)])
    vp.start_internal(internal.DIHEDRAL)
    for ch in "90":
        vp._internal["state"].type_char(ch)
    vp._apply_internal()
    vp._finish_internal(commit=True)
    c = obj.structure.coords
    assert measure.dihedral(c[0], c[1], c[2], c[3]) == pytest.approx(90.0)


def test_cancelling_puts_the_geometry_back_exactly(chain):
    win, obj = chain
    vp = win.viewport
    vp.set_selection([(obj.id, 0), (obj.id, 1)])
    before = obj.structure.coords.copy()
    vp.start_internal(internal.DISTANCE)
    vp._internal["state"].add_delta(0.8)
    vp._apply_internal()
    assert not np.allclose(obj.structure.coords, before)
    vp._finish_internal(commit=False)
    assert np.allclose(obj.structure.coords, before)
    assert not vp.modal_active()


def test_dragging_never_compounds(chain):
    """Each update re-derives from the snapshot, so moving out and back
    returns to exactly where it started."""
    win, obj = chain
    vp = win.viewport
    vp.set_selection([(obj.id, 0), (obj.id, 1)])
    before = obj.structure.coords.copy()
    vp.start_internal(internal.DISTANCE)
    for amount in (0.4, 0.4, -0.8):
        vp._internal["state"].add_delta(amount)
        vp._apply_internal()
    assert np.allclose(obj.structure.coords, before, atol=1e-9)
    vp._finish_internal(commit=False)


def test_a_ring_bond_moves_only_the_one_atom(win):
    s = Structure.from_atoms([("C", 0.0, 0, 0), ("C", 1.5, 0, 0),
                              ("C", 0.75, 1.3, 0)], name="ring")
    s.bonds = [(0, 1, 1), (1, 2, 1), (2, 0, 1)]
    obj = win._install_structure(s) or win.scene.objects[-1]
    vp = win.viewport
    vp.set_selection([(obj.id, 0), (obj.id, 1)])
    vp.start_internal(internal.DISTANCE)
    assert vp._internal["blocked"] is True
    assert vp._internal["rows"] == [1]
    vp._finish_internal(commit=False)


def test_the_modal_refuses_a_selection_of_the_wrong_size(chain):
    win, obj = chain
    vp = win.viewport
    vp.set_selection([(obj.id, 0)])
    vp.start_internal(internal.DISTANCE)
    assert vp._internal is None            # one atom is not a bond length


def test_escape_cancels_the_modal(chain):
    win, obj = chain
    vp = win.viewport
    vp.set_selection([(obj.id, 0), (obj.id, 1)])
    before = obj.structure.coords.copy()
    vp.start_internal(internal.DISTANCE)
    vp._internal["state"].add_delta(0.5)
    vp._apply_internal()
    assert vp.cancel_modes() is True
    assert vp._internal is None
    assert np.allclose(obj.structure.coords, before)


def test_the_modal_owns_the_keyboard_so_digits_do_not_fire_hotkeys(chain):
    win, obj = chain
    vp = win.viewport
    vp.set_selection([(obj.id, 0), (obj.id, 1)])
    vp.start_internal(internal.DISTANCE)
    assert vp._keyboard_captured()
    vp._finish_internal(commit=False)


def test_painting_the_guides_with_a_scalar_state_does_not_raise(chain):
    """Caught by a scripted GUI run, invisible to every logic test.

    `_paint_overlays` hands the ACTIVE MODAL STATE to `_paint_modal_guides`,
    which assumed a G/R state and read `state.axis`. A ScalarState has no
    axis — it has one degree of freedom — so every repaint during the modal
    raised inside paintGL, where Qt prints the traceback and carries on. The
    app looked fine and the overlays silently stopped.
    """
    from PySide6.QtGui import QImage, QPainter
    win, obj = chain
    vp = win.viewport
    vp.set_selection([(obj.id, 0), (obj.id, 1)])
    vp.start_internal(internal.DISTANCE)
    image = QImage(64, 64, QImage.Format_ARGB32)
    painter = QPainter(image)
    try:
        vp._paint_modal_guides(painter, vp._internal["state"])
    finally:
        painter.end()
        vp._finish_internal(commit=False)


def test_the_edit_is_one_undo_step(chain):
    win, obj = chain
    vp = win.viewport
    vp.set_selection([(obj.id, 0), (obj.id, 1)])
    before = obj.structure.coords.copy()
    vp.start_internal(internal.DISTANCE)
    for ch in "2.5":
        vp._internal["state"].type_char(ch)
    vp._apply_internal()
    vp._finish_internal(commit=True)
    assert measure.distance(*obj.structure.coords[[0, 1]]) == \
        pytest.approx(2.5)
    win.on_undo()
    obj = win.scene.get(obj.id)
    assert np.allclose(obj.structure.coords, before, atol=1e-9)


# ------------------------------------------------------- right-click menu
def test_the_menu_offers_the_edit_that_fits_the_selection(chain):
    win, obj = chain
    vp = win.viewport
    for n, kind in ((2, internal.DISTANCE), (3, internal.ANGLE),
                    (4, internal.DIHEDRAL)):
        vp.set_selection([(obj.id, i) for i in range(n)])
        keys = [k for k, _label, _tip in vp.context_entries()]
        assert "internal:" + kind in keys
        assert sum(k.startswith("internal:") for k in keys) == 1


def test_the_menu_shows_the_current_value(chain):
    win, obj = chain
    vp = win.viewport
    vp.set_selection([(obj.id, 0), (obj.id, 1)])
    label = [lab for k, lab, _t in vp.context_entries()
             if k.startswith("internal:")][0]
    assert "1.500" in label            # the C-C bond it is about to change


def test_the_menu_drops_the_geometry_entry_when_nothing_fits(chain):
    win, obj = chain
    vp = win.viewport
    vp.set_selection([(obj.id, 0)])
    keys = [k for k, _label, _tip in vp.context_entries()]
    assert not any(k.startswith("internal:") for k in keys)
    assert "op:hide_selected" in keys   # but the plain edits are still there


def test_an_empty_selection_has_no_menu(win):
    win.viewport.set_selection([])
    assert win.viewport.context_entries() == []


def test_menu_operator_entries_exist_in_the_registry(chain):
    win, obj = chain
    win.viewport.set_selection([(obj.id, 0), (obj.id, 1)])
    for key, _label, _tip in win.viewport.context_entries():
        if key.startswith("op:"):
            assert win.ops.get(key.split(":", 1)[1]) is not None


def test_choosing_a_menu_entry_runs_it(chain):
    win, obj = chain
    vp = win.viewport
    vp.set_selection([(obj.id, 0), (obj.id, 1)])
    vp._run_context_action("internal:" + internal.DISTANCE)
    assert vp._internal is not None
    vp._finish_internal(commit=False)

    vp.set_selection([(obj.id, 0)])
    vp._run_context_action("op:hide_selected")
    assert obj.atom_hidden == {0}


# ----------------------------------------------------- F3 operator predicates
def test_the_geometry_operators_light_up_by_selection_size(chain):
    win, obj = chain
    ops = {o.id: o for o in win.ops.all()}

    def live():
        return {k for k in ("set_bond_length", "set_angle", "set_dihedral")
                if ops[k].enabled(win)}

    win.viewport.set_selection([(obj.id, 0), (obj.id, 1)])
    assert live() == {"set_bond_length"}
    win.viewport.set_selection([(obj.id, i) for i in (0, 1, 2)])
    assert live() == {"set_angle"}
    win.viewport.set_selection([(obj.id, i) for i in (0, 1, 2, 3)])
    assert live() == {"set_dihedral"}
    win.viewport.set_selection([])
    assert live() == set()


def test_the_geometry_operators_are_findable_in_the_palette(win):
    ids = [op.id for op, _en in win.ops.search("dihedral", win)]
    assert "set_dihedral" in ids
    ids = [op.id for op, _en in win.ops.search("torsion", win)]
    assert "set_dihedral" in ids
    ids = [op.id for op, _en in win.ops.search("bond length", win)]
    assert "set_bond_length" in ids


def test_no_operator_key_clashes_after_the_new_ops(win):
    assert win.ops.duplicate_keys() == {}


# ------------------------------------------------------------------- flying
def test_right_button_starts_and_stops_flight(win):
    vp = win.viewport
    assert not vp.flying()
    vp.start_fly()
    assert vp.flying()
    assert vp._keyboard_captured()          # WASD must not fire QActions
    vp.stop_fly(coast=False)
    assert not vp.flying()


def test_holding_w_moves_the_camera_and_letting_go_coasts(win):
    vp = win.viewport
    before = vp.camera.center.copy()
    vp.start_fly()
    from PySide6.QtCore import Qt
    vp._fly["keys"].add(Qt.Key_W)
    for _ in range(20):
        vp._fly_tick(1 / 60.0)
    travelled = np.linalg.norm(vp.camera.center - before)
    assert travelled > 0.0

    vp.stop_fly()                           # button up: keeps coasting
    assert vp.flying()
    mid = vp.camera.center.copy()
    for _ in range(400):
        if not vp.flying():
            break
        vp._fly_tick(1 / 60.0)
    assert np.linalg.norm(vp.camera.center - mid) > 0.0   # it glided on
    assert not vp.flying()                                # and then stopped


def test_flying_never_rolls_the_horizon(win):
    from molom.core.camera import quat_to_mat3
    vp = win.viewport
    vp.start_fly()
    rng = np.random.RandomState(3)
    for _ in range(120):
        vp._fly_look(float(rng.uniform(-60, 60)), float(rng.uniform(-60, 60)))
        # World Z must stay in the screen's vertical plane: its VIEW-space x
        # component is exactly the roll, and it has to be zero every time.
        world_z_in_view = quat_to_mat3(vp.camera.rotation) @ np.array(
            [0.0, 0.0, 1.0])
        assert abs(float(world_z_in_view[0])) < 1e-9
    vp.stop_fly(coast=False)


def test_the_camera_cannot_be_flown_over_the_pole(win):
    vp = win.viewport
    vp.start_fly()
    for _ in range(80):
        vp._fly_look(0.0, -400.0)           # keep pushing "up"
    assert vp.camera.forward()[2] < 0.9999
    vp.stop_fly(coast=False)


def test_flight_speed_scales_with_the_scene(win):
    vp = win.viewport
    vp.start_fly()
    assert vp._fly["model"].scale > 0.0
    vp.stop_fly(coast=False)


def test_right_drag_no_longer_pans(win):
    """RMB is the fly button now; pan lives on Shift+MMB and Shift+scroll."""
    from PySide6.QtCore import Qt
    vp = win.viewport
    assert vp._nav_drag_kind(Qt.RightButton, Qt.NoModifier) is None
    assert vp._nav_drag_kind(Qt.MiddleButton, Qt.ShiftModifier) == "pan"
    assert vp._nav_drag_kind(Qt.MiddleButton, Qt.NoModifier) == "orbit"


def test_shuttle_uses_the_same_flight_model(win):
    obj = win.scene.objects[0]
    vp = win.viewport
    vp.start_shuttle(obj.id)
    assert vp.flying()
    assert isinstance(vp._fly["model"], flight.FlightModel)
    assert vp._fly["obj_id"] == obj.id
    before = obj.structure.coords.copy()
    from PySide6.QtCore import Qt
    vp._shuttle_key(Qt.Key_W, down=True)
    for _ in range(30):
        vp._fly_tick(1 / 60.0)
    assert not np.allclose(obj.structure.coords, before)
    vp.stop_shuttle()
    assert not vp.flying()


def test_a_key_release_stops_thrust(win):
    from PySide6.QtCore import Qt
    vp = win.viewport
    vp.start_fly()
    vp._fly["keys"].add(Qt.Key_W)
    for _ in range(10):
        vp._fly_tick(1 / 60.0)
    vp._fly["keys"].discard(Qt.Key_W)
    for _ in range(400):
        if not vp._fly["model"].moving:
            break
        vp._fly_tick(1 / 60.0)
    assert not vp._fly["model"].moving
    vp.stop_fly(coast=False)


# ------------------------------------------------------ selection highlight
def test_the_outline_hull_covers_atoms_and_their_shared_bonds(chain):
    win, obj = chain
    vp = win.viewport
    vp.set_selection([(obj.id, 0), (obj.id, 1)])
    spheres, cylinders = vp._selection_hull()
    assert len(spheres) == 2
    assert len(cylinders) == 1              # the 0-1 bond is fully selected


def test_a_lone_atom_gets_no_outline_cylinder(chain):
    win, obj = chain
    vp = win.viewport
    vp.set_selection([(obj.id, 0)])
    spheres, cylinders = vp._selection_hull()
    assert len(spheres) == 1 and cylinders == []


def test_the_hull_is_bigger_than_the_atom_it_outlines(chain):
    win, obj = chain
    vp = win.viewport
    vp.set_selection([(obj.id, 0)])
    spheres, _c = vp._selection_hull()
    assert spheres[0][0, 0] > vp.outline_width()


def test_the_outline_width_tracks_the_zoom_but_stays_bounded(chain):
    win, _obj = chain
    vp = win.viewport
    vp.camera.distance = 5.0
    near = vp.outline_width()
    vp.camera.distance = 40.0
    far = vp.outline_width()
    assert far > near
    vp.camera.distance = 100000.0
    assert vp.outline_width() <= 0.22 + 1e-9


def test_hidden_atoms_get_no_outline(chain):
    win, obj = chain
    vp = win.viewport
    obj.hide_atoms([0])
    vp.set_selection([(obj.id, 0), (obj.id, 1)])
    spheres, cylinders = vp._selection_hull()
    assert len(spheres) == 1                # only the visible one
    assert cylinders == []                  # and its bond went with it
