"""Round 67: the chase camera made consistent, and F3 repeating itself.

Christian, 2026-08-12:
* "oftentimes the piloted mol is on the left hand side once a roll has been
  introduced to the mol? the distance of the camera away from the mol is also
  too large."
* "Select single atom (cockpit). Camera is placed lightly above and behind from
  cockpit. Align up direction always to global z direction."
* "Also add the steering in full from flying mode (the same circle and
  navigation gizmo that indicates direction etc.)."
* "in blender once you have used F3, the last used search result is the one
  prehighlighted at the top so a single enter click is enough."
"""

import inspect

import numpy as np
import pytest

from molom.core import flight
from molom.core.camera import quat_to_mat3


@pytest.fixture
def win():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.app import MainWindow
    QApplication.instance() or QApplication([])
    win = MainWindow()
    win.load_default_scene()
    return win


def _up(camera):
    return quat_to_mat3(camera.rotation).T @ np.array([0.0, 1.0, 0.0])


# --------------------------------------------------------- the roll problem
def test_the_chase_pivot_uses_WORLD_z_not_the_camera_up():
    """The bug: the pivot was offset along the CAMERA's up, so rolling swung it
    sideways and carried the molecule out of frame with it."""
    origin = np.zeros(3)
    default = flight.chase_pivot(origin, radius=2.0, height=0.5)
    assert np.allclose(default, [0.0, 0.0, 1.0])
    assert np.allclose(flight.WORLD_UP, [0.0, 0.0, 1.0])


def test_the_camera_stays_LEVEL_while_the_ship_rolls(win):
    obj = win._active_obj()
    vp = win.viewport
    win.on_shuttle(third_person=True)
    vp._fly["model"].roll = 1.2
    for _ in range(30):
        vp._fly_turn(0.0, 0.0)
        vp._fly_tick(dt=1.0 / 60.0)
    up = _up(vp.camera)
    # No ROLL component: the up vector may tilt with pitch but must stay in the
    # plane containing world Z, i.e. z dominates.
    assert abs(float(up[2])) > 0.85, "the chase camera rolled with the ship"


def test_the_ship_still_rolls_even_though_the_camera_does_not(win):
    """Q/E has to keep doing something - the roll moved to the ship, it was
    not removed."""
    obj = win._active_obj()
    vp = win.viewport
    win.on_shuttle(third_person=True)
    before = np.array(obj.orientation, dtype=float)
    vp._fly["model"].roll = 0.9
    vp._fly_turn(0.0, 0.0)
    assert not np.allclose(obj.orientation, before), "the ship did not roll"


def test_the_roll_is_applied_as_a_DELTA_not_replayed(win):
    """`model.roll` is an ABSOLUTE angle. Re-applying it every tick would spin
    the molecule up without limit."""
    obj = win._active_obj()
    vp = win.viewport
    win.on_shuttle(third_person=True)
    vp._fly["model"].roll = 0.5
    vp._fly_turn(0.0, 0.0)
    after_first = np.array(obj.orientation, dtype=float)
    for _ in range(20):                      # same roll, many ticks
        vp._fly_turn(0.0, 0.0)
    assert np.allclose(obj.orientation, after_first, atol=1e-9), \
        "a held roll kept spinning the ship"


def test_the_cockpit_view_still_rolls_the_camera_with_the_ship(win):
    """First person is unchanged: inside the ship the two ARE one rotation."""
    src = inspect.getsource(win.viewport._fly_turn)
    assert "0.0 if chase else roll" in src


# ------------------------------------------------------- the cockpit atom
def test_a_single_selected_atom_becomes_the_cockpit(win):
    obj = win._active_obj()
    vp = win.viewport
    vp.set_selection([(obj.id, 3)])
    win.on_shuttle(third_person=True)
    assert vp._shuttle["cockpit"] == 3


def test_no_selection_falls_back_to_the_origin(win):
    obj = win._active_obj()
    vp = win.viewport
    vp.set_selection([])
    win.on_shuttle(third_person=True)
    assert vp._shuttle["cockpit"] is None
    assert np.allclose(vp._cockpit_pos(obj), obj.origin)


def test_several_selected_atoms_are_ambiguous_and_fall_back(win):
    obj = win._active_obj()
    vp = win.viewport
    vp.set_selection([(obj.id, 0), (obj.id, 1)])
    win.on_shuttle(third_person=True)
    assert vp._shuttle["cockpit"] is None


def test_the_camera_follows_the_COCKPIT_ATOM_not_the_centroid(win):
    obj = win._active_obj()
    vp = win.viewport
    vp.set_selection([(obj.id, 2)])
    win.on_shuttle(third_person=True)
    target = flight.chase_pivot(obj.structure.coords[2],
                                radius=vp._shuttle["radius"])
    assert np.allclose(vp.camera.center, target)


# ------------------------------------------------------------ the distance
def test_the_camera_sits_closer_than_it_used_to():
    """"the distance of the camera away from the mol is also too large"."""
    assert flight.CHASE_DISTANCE < 4.0
    assert flight.chase_distance(3.7) < 12.0


def test_the_distance_still_scales_with_the_molecule():
    assert flight.chase_distance(20.0) > flight.chase_distance(3.0)


# --------------------------------------------------------------- the HUD
def test_the_steering_instrument_is_shared_by_both_modes(win):
    """The shuttle drew a bare circle: the one mode where you steer a whole
    molecule had the least information on screen."""
    vp = win.viewport
    assert hasattr(vp, "_paint_aim")
    for painter in (vp._paint_fly, vp._paint_shuttle):
        assert "_paint_aim" in inspect.getsource(painter)


def test_the_aim_instrument_draws_the_travel_ring_and_the_reticle(win):
    src = inspect.getsource(win.viewport._paint_aim)
    assert "limit" in src and "offset" in src      # the stick and its extent
    assert "roll" in src                            # and which way is up


def test_the_shuttle_banner_reports_speed(win):
    assert "A/s" in inspect.getsource(win.viewport._paint_shuttle)


# ------------------------------------------------- F3 repeats the last one
def test_the_palette_preselects_the_last_operator(win):
    from PySide6.QtCore import Qt
    from molom.ui.dialogs import OperatorSearchDialog
    dlg = OperatorSearchDialog(win, win.ops, win, last="fit")
    assert dlg.list.currentItem().data(Qt.UserRole) == "fit"


def test_a_real_search_beats_the_memory(win):
    """Once you have typed, the best MATCH should be selected, not a memory of
    something unrelated."""
    from PySide6.QtCore import Qt
    from molom.ui.dialogs import OperatorSearchDialog
    dlg = OperatorSearchDialog(win, win.ops, win, last="fit")
    dlg.edit.setText("hydrogen bond")
    item = dlg.list.currentItem()
    assert item is not None
    assert item.data(Qt.UserRole) != "fit"


def test_a_fresh_palette_selects_the_first_enabled_entry(win):
    from PySide6.QtCore import Qt
    from molom.ui.dialogs import OperatorSearchDialog
    dlg = OperatorSearchDialog(win, win.ops, win, last=None)
    item = dlg.list.currentItem()
    assert item is not None and item.data(Qt.UserRole) is not None


def test_running_an_operator_records_it(win):
    """`on_operator_search` stores the choice so the next F3 opens on it."""
    assert win._last_operator is None
    src = inspect.getsource(win.on_operator_search)
    assert "_last_operator = dlg.chosen.id" in src
    assert "last=self._last_operator" in src


def test_an_unknown_last_id_is_harmless(win):
    """A remembered operator can disappear (an add-on unloaded), and the
    palette must still open."""
    from molom.ui.dialogs import OperatorSearchDialog
    dlg = OperatorSearchDialog(win, win.ops, win, last="no_such_operator")
    assert dlg.list.currentItem() is not None
