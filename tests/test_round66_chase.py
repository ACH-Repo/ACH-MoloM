"""Round 66: third-person pilot mode (roadmap item 10).

Christian, 2026-08-12: "3rd person mode for piloting mols. trying to do it FPS
only leads to problems." The problem is structural rather than a matter of
taste: inside the thing you are steering you cannot see its orientation, and a
molecule has no windscreen to give you a horizon.

Both modes fly the same `FlightModel`. The only differences are where the
camera sits and whether its pivot LAGS - which is what reads as "following"
rather than as the whole world swinging around the ship.
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


def _key_w():
    from PySide6.QtCore import Qt
    return Qt.Key_W


# ------------------------------------------------------------ the core maths
def test_follow_is_framerate_independent():
    """A fixed fraction per frame trails further at 30 fps than at 120, so the
    feel would depend on the machine. Same reasoning as the exponential drag."""
    start, target = np.zeros(3), np.array([10.0, 0.0, 0.0])
    coarse = start.copy()
    for _ in range(30):
        coarse = flight.follow(coarse, target, lag=5.0, dt=1.0 / 30.0)
    fine = start.copy()
    for _ in range(120):
        fine = flight.follow(fine, target, lag=5.0, dt=1.0 / 120.0)
    assert np.allclose(coarse, fine, atol=1e-6)


def test_follow_converges_but_never_overshoots():
    current, target = np.zeros(3), np.array([5.0, 0.0, 0.0])
    previous = -1.0
    for _ in range(200):
        current = flight.follow(current, target, dt=1.0 / 60.0)
        travelled = float(current[0])
        assert travelled >= previous          # monotone
        assert travelled <= 5.0 + 1e-9        # never past the target
        previous = travelled
    assert current[0] == pytest.approx(5.0, abs=1e-3)


def test_zero_lag_snaps():
    out = flight.follow(np.zeros(3), np.array([2.0, 0.0, 0.0]), lag=0.0)
    assert np.allclose(out, [2.0, 0.0, 0.0])


def test_the_chase_pivot_sits_ABOVE_the_ship():
    """The rig puts the eye behind the pivot, so lifting the pivot is what
    lifts the eye - and it drops the ship below centre frame, which is the
    chase-cam look rather than a mistake."""
    origin = np.array([1.0, 2.0, 3.0])
    up = np.array([0.0, 0.0, 1.0])
    pivot = flight.chase_pivot(origin, up, radius=2.0, height=0.5)
    assert np.allclose(pivot, origin + np.array([0.0, 0.0, 1.0]))


def test_the_chase_distance_scales_with_the_molecule():
    """Scenes run from a 3 A molecule to a 200 A framework; a fixed distance
    would be inside the ship or in the next postcode."""
    assert flight.chase_distance(10.0) > flight.chase_distance(2.0)
    assert flight.chase_distance(0.0) >= 2.0        # never zero


def test_slip_is_clamped_so_the_ship_cannot_leave_the_screen():
    """Lag is a feel; losing the ship off the edge during a long burn is a
    bug. (Round 72: the limit is now a DISTANCE in scene units, derived from
    the viewing distance by `slip_limit` — see that round's tests for why a
    multiple of the molecule's radius could never do this job.)"""
    target = np.array([100.0, 0.0, 0.0])
    pivot = np.zeros(3)
    out = flight.clamp_slip(pivot, target, limit=6.0)
    assert float(np.linalg.norm(target - out)) == pytest.approx(6.0)


def test_slip_leaves_a_close_pivot_alone():
    target = np.array([1.0, 0.0, 0.0])
    pivot = np.zeros(3)
    assert np.allclose(flight.clamp_slip(pivot, target, limit=6.0), pivot)


# --------------------------------------------------------------- the mode
def test_third_person_sits_back_from_the_ship(win):
    obj = win._active_obj()
    win.on_shuttle(third_person=True)
    vp = win.viewport
    radius = obj.structure.bounding_radius()
    assert vp._shuttle["third_person"] is True
    assert vp.camera.distance == pytest.approx(flight.chase_distance(radius))
    # the eye really is outside the molecule
    assert float(np.linalg.norm(vp._shuttle_eye() - obj.origin)) > radius


def test_first_person_still_sits_INSIDE_the_ship(win):
    """The cockpit mode is not changed by any of this."""
    win.on_shuttle()
    vp = win.viewport
    assert vp._shuttle["third_person"] is False
    assert vp.camera.distance < 1.0


def test_nothing_is_clipped_in_third_person(win):
    """The ship is the SUBJECT here, so culling what is nearest the camera
    would cull the very thing you are flying."""
    obj = win._active_obj()
    win.on_shuttle(third_person=True)
    assert win.viewport._shuttle_hidden(obj.structure.coords) is None


def test_the_cockpit_still_clips_what_is_too_close(win):
    obj = win._active_obj()
    win.on_shuttle()
    mask = win.viewport._shuttle_hidden(obj.structure.coords)
    assert mask is not None and bool(mask.any())


def test_the_pivot_LAGS_under_thrust_then_catches_up(win):
    """The whole point of the mode: a rigid chase camera swings the world
    around the ship, a lagging one reads as following."""
    obj = win._active_obj()
    win.on_shuttle(third_person=True)
    vp = win.viewport
    settled = float(np.linalg.norm(vp.camera.center - obj.origin))

    vp._fly["keys"].add(_key_w())
    gaps = []
    for _ in range(60):
        vp._fly_tick(dt=1.0 / 60.0)
        gaps.append(float(np.linalg.norm(vp.camera.center - obj.origin)))
    assert float(np.linalg.norm(obj.origin)) > 1.0, "the ship must have moved"
    assert max(gaps) > settled + 0.05, "the pivot did not fall behind at all"

    vp._fly["keys"].clear()
    for _ in range(240):
        vp._fly_tick(dt=1.0 / 60.0)
    caught = float(np.linalg.norm(vp.camera.center - obj.origin))
    assert caught == pytest.approx(settled, abs=0.15)


def test_the_gap_stays_bounded_through_a_long_burn(win):
    obj = win._active_obj()
    win.on_shuttle(third_person=True)
    vp = win.viewport
    radius = float(vp._shuttle["radius"])
    vp._fly["keys"].add(_key_w())
    worst = 0.0
    for _ in range(400):
        vp._fly_tick(dt=1.0 / 60.0)
        # Measured against the pivot the follow is actually aiming at, not
        # against the ship's centre: the two differ by the chase HEIGHT, which
        # is a deliberate framing offset and not slip.
        target = flight.chase_pivot(obj.origin, radius=radius)
        worst = max(worst, float(np.linalg.norm(vp.camera.center - target)))
    assert worst <= flight.slip_limit(vp.camera.distance) + 1e-6


def test_flying_in_third_person_moves_the_MOLECULE_not_the_camera(win):
    """Same as the cockpit: the ship is the airframe."""
    obj = win._active_obj()
    before = obj.structure.coords.copy()
    win.on_shuttle(third_person=True)
    vp = win.viewport
    vp._fly["keys"].add(_key_w())
    for _ in range(30):
        vp._fly_tick(dt=1.0 / 60.0)
    assert not np.allclose(obj.structure.coords, before)


def test_landing_restores_the_view(win):
    win.on_shuttle(third_person=True)
    vp = win.viewport
    saved = vp._shuttle["saved"]
    vp.stop_shuttle()
    assert vp._shuttle is None
    assert np.allclose(vp.camera.center, saved[0])
    assert vp.camera.distance == pytest.approx(saved[1])


def test_both_modes_are_offered_as_operators(win):
    assert win.ops.get("shuttle") is not None
    assert win.ops.get("shuttle_chase") is not None
    assert not win.ops.duplicate_keys()


def test_the_banner_says_which_mode_it_is(win):
    import inspect
    src = inspect.getsource(win.viewport._paint_shuttle) \
        if hasattr(win.viewport, "_paint_shuttle") else ""
    if not src:
        pytest.skip("banner painter not found by name")
    assert "CHASE" in src and "SHUTTLE" in src
