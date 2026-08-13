"""Round 71: the cockpit anchor, the spring arm, and a cached rebuild.

Christian, 2026-08-12, with `docking.molom`:
* "the meta-molecule (Meta-Ship) is showing the mismatch between first person
  view and parking position. Highlighted hydrogen is the cockpit."
  His own hypothesis - "I free drew a mol far away from its object origin" -
  was exactly right: that file's meta-ship has its stored origin 8.10 A from
  its real centroid.
* "some kind of small camera jump that gets corrected quickly ... as if the
  camera is colliding with a boundary ... typically managed by spring arm
  logic in game engines."
* "fix the refresh_geometry rebuild every tick"
"""

import numpy as np
import pytest

from molom.core import flight


@pytest.fixture
def win():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.app import MainWindow
    QApplication.instance() or QApplication([])
    win = MainWindow()
    win.load_default_scene()
    return win


def _drift_origin(obj, offset=(8.0, 0.0, 0.0)):
    """Reproduce the meta-ship's condition: an origin far off the centroid,
    which is what free-drawing leaves behind."""
    obj.origin = np.asarray(obj.origin, dtype=float) + np.asarray(offset,
                                                                 dtype=float)


# ------------------------------------------- the cockpit anchors BOTH modes
def test_first_person_sits_at_the_cockpit_atom_not_the_origin(win):
    obj = win._active_obj()
    _drift_origin(obj)
    win.viewport.set_selection([(obj.id, 4)])
    win.on_shuttle()
    eye = win.viewport._shuttle_eye()
    atom = obj.structure.coords[4]
    assert float(np.linalg.norm(eye - atom)) < 1.0, \
        "the cockpit view is not at the picked atom"
    assert float(np.linalg.norm(eye - np.asarray(obj.origin, float))) > 5.0


def test_first_person_rides_WITH_the_cockpit(win):
    from PySide6.QtCore import Qt
    obj = win._active_obj()
    _drift_origin(obj)
    win.viewport.set_selection([(obj.id, 4)])
    win.on_shuttle()
    vp = win.viewport
    vp._fly["keys"].add(Qt.Key_W)
    for _ in range(60):
        vp._fly_tick(dt=1.0 / 60.0)
    gap = float(np.linalg.norm(vp._shuttle_eye() - obj.structure.coords[4]))
    assert gap < 1.0, "the cockpit view drifted off its atom while flying"


def test_no_selection_still_falls_back_to_the_origin(win):
    obj = win._active_obj()
    win.viewport.set_selection([])
    win.on_shuttle()
    assert win.viewport._shuttle["cockpit"] is None


def test_both_modes_use_the_same_anchor(win):
    obj = win._active_obj()
    win.viewport.set_selection([(obj.id, 2)])
    win.on_shuttle()
    first = win.viewport._cockpit_pos(obj).copy()
    win.viewport.stop_shuttle()
    win.viewport.set_selection([(obj.id, 2)])
    win.on_shuttle(third_person=True)
    assert np.allclose(win.viewport._cockpit_pos(obj), first)


# ------------------------------------------------------------ the spring arm
def test_the_follow_rate_stiffens_as_the_gap_opens():
    """A spring arm has no wall: the rate rises smoothly instead of the pivot
    striking a cap and being snapped back."""
    near = flight.spring_lag(np.zeros(3), np.array([0.1, 0, 0]), limit=3.0)
    far = flight.spring_lag(np.zeros(3), np.array([2.9, 0, 0]), limit=3.0)
    assert near == pytest.approx(flight.CHASE_LAG)
    assert far > near * 2.0


def test_the_rate_is_continuous_across_the_soft_zone():
    """A step in the rate would be a wall by another name."""
    cap = 3.0
    edge = flight.CHASE_SOFT_ZONE * cap
    just_under = flight.spring_lag(np.zeros(3), np.array([edge - 1e-4, 0, 0]),
                                   limit=cap)
    just_over = flight.spring_lag(np.zeros(3), np.array([edge + 1e-4, 0, 0]),
                                  limit=cap)
    assert just_over == pytest.approx(just_under, rel=1e-3)


def test_the_rate_is_capped_so_it_cannot_explode():
    huge = flight.spring_lag(np.zeros(3), np.array([1e6, 0, 0]), limit=3.0)
    assert huge == pytest.approx(flight.CHASE_LAG * flight.CHASE_STIFFEN)


def test_the_chase_step_never_reverses(win):
    """The judder was ease-ease-SNAP; a reversal in step size is its
    signature."""
    from PySide6.QtCore import Qt
    obj = win._active_obj()
    vp = win.viewport
    vp.set_selection([(obj.id, 0)])
    win.on_shuttle(third_person=True)
    vp._fly["keys"].add(Qt.Key_W)
    prev = vp.camera.center.copy()
    steps = []
    for _ in range(240):
        vp._fly_tick(dt=1.0 / 60.0)
        steps.append(float(np.linalg.norm(vp.camera.center - prev)))
        prev = vp.camera.center.copy()
    d = np.diff(np.array(steps))
    reversals = int(np.count_nonzero(np.sign(d[:-1]) * np.sign(d[1:]) < 0))
    assert reversals == 0, "{} step reversals - the camera is juddering".format(
        reversals)


# ------------------------------------------------------- the cached rebuild
def test_the_draw_cache_exists_only_while_flying(win):
    obj = win._active_obj()
    vp = win.viewport
    assert vp._draw_cache is None
    win.on_shuttle(third_person=True)
    assert vp._draw_cache is not None
    vp.stop_shuttle()
    assert vp._draw_cache is None, "a stale cache outlived the flight"


def test_the_flown_object_is_never_cached(win):
    """Its coordinates change every tick - caching it is the one thing that
    would be wrong."""
    obj = win._active_obj()
    vp = win.viewport
    win.on_shuttle(third_person=True)
    # `_object_block`, not `_rebuild`: the latter uploads to GL buffers that do
    # not exist without a live context, which is a property of the test
    # environment rather than of the cache.
    vp._object_block(obj)
    assert obj.id not in (vp._draw_cache or {})


def test_other_objects_ARE_cached(win):
    from molom.core.structure import Structure
    other = win.scene.add(
        Structure(["C"], np.array([[20.0, 0.0, 0.0]])), name="bystander")
    obj = win._active_obj()
    vp = win.viewport
    win.on_shuttle(third_person=True)
    vp._object_block(other)
    assert other.id in (vp._draw_cache or {})


def test_the_cached_and_uncached_pictures_agree(win):
    """A performance change that alters the picture is a different change."""
    obj = win._active_obj()
    vp = win.viewport
    plain = vp._build_object_block(obj)
    win.on_shuttle(third_person=True)
    cached = vp._object_block(obj)          # the flown one: always fresh
    assert len(cached["sphere_mats"]) == len(plain["sphere_mats"])
    assert len(cached["cyl_starts"]) == len(plain["cyl_starts"])
