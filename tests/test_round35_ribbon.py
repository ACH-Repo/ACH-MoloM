"""Round 35: the VESTA orientation ribbon and the maths under it.

The interesting assertions are all about the DIRECT vs RECIPROCAL distinction:
in a monoclinic cell "down the a axis" and "perpendicular to the (100) planes"
are different pictures, and conflating them is the same class of error as the
round-26 mirror-plane bug.
"""

import os

import numpy as np
import pytest

from molom.core import orient
from molom.core.cif import Cell

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

CUBIC = Cell(5.0, 5.0, 5.0, 90.0, 90.0, 90.0)
MONOCLINIC = Cell(7.0, 9.0, 11.0, 90.0, 115.0, 90.0)
TRICLINIC = Cell(6.0, 7.5, 9.1, 78.0, 85.0, 102.0)


# ----------------------------------------------------------- axis vectors
def test_every_axis_is_a_unit_vector():
    for cell in (CUBIC, MONOCLINIC, TRICLINIC):
        for key in orient.AXIS_KEYS:
            v = orient.axis_vector(cell, key)
            assert np.linalg.norm(v) == pytest.approx(1.0)


def test_in_a_cubic_cell_direct_and_reciprocal_axes_coincide():
    for letter in "abc":
        assert np.allclose(orient.axis_vector(CUBIC, letter),
                           orient.axis_vector(CUBIC, letter + "*"),
                           atol=1e-12)


def test_in_a_monoclinic_cell_a_and_a_star_genuinely_differ():
    """beta = 115 deg, so a and a* are 25 deg apart. If these came out equal
    the reciprocal buttons would be silently duplicating the direct ones."""
    a = orient.axis_vector(MONOCLINIC, "a")
    a_star = orient.axis_vector(MONOCLINIC, "a*")
    angle = np.degrees(np.arccos(np.clip(np.dot(a, a_star), -1.0, 1.0)))
    assert angle == pytest.approx(25.0, abs=1e-6)
    # b is the unique axis of a monoclinic cell, so b and b* must agree.
    assert np.allclose(orient.axis_vector(MONOCLINIC, "b"),
                       orient.axis_vector(MONOCLINIC, "b*"), atol=1e-12)


def test_a_star_is_perpendicular_to_b_and_c():
    """That IS the definition of a reciprocal axis — the normal to the plane
    the other two span."""
    for cell in (MONOCLINIC, TRICLINIC):
        a_star = orient.axis_vector(cell, "a*")
        for other in ("b", "c"):
            assert float(np.dot(a_star, orient.axis_vector(cell, other))) == \
                pytest.approx(0.0, abs=1e-12)


def test_an_unknown_axis_is_refused():
    with pytest.raises(ValueError):
        orient.axis_vector(CUBIC, "d")


# ------------------------------------------------------------ view bases
def _is_view_basis(m):
    m = np.asarray(m, dtype=float)
    return (np.allclose(m @ m.T, np.eye(3), atol=1e-9)
            and np.linalg.det(m) == pytest.approx(1.0))


def test_look_along_gives_a_proper_right_handed_view_basis():
    for cell in (CUBIC, MONOCLINIC, TRICLINIC):
        for key in orient.AXIS_KEYS:
            assert _is_view_basis(orient.look_along(cell, key))


def test_the_chosen_axis_points_into_the_screen():
    """Mercury's convention: the axis you picked goes AWAY from you, with the
    cell origin at the top left."""
    for cell in (CUBIC, MONOCLINIC, TRICLINIC):
        for key in orient.AXIS_KEYS:
            forward = -orient.look_along(cell, key)[2]
            axis = orient.axis_vector(cell, key)
            assert float(np.dot(forward, axis)) == pytest.approx(1.0)
            # ...and the flip shows the other side.
            flipped = -orient.look_along(cell, key, flip=True)[2]
            assert float(np.dot(flipped, axis)) == pytest.approx(-1.0)


def test_the_next_axis_goes_right_and_the_one_after_goes_DOWN():
    """Christian's b-view comparison: MoloM was "exactly mirrored around the
    red a axis" against Mercury. A mirror is not a rotation, so it can only
    be the sign of the up vector — a runs DOWN the screen, not up."""
    for key, right, down in (("a", "b", "c"), ("b", "c", "a"),
                             ("c", "a", "b")):
        basis = orient.look_along(CUBIC, key)
        assert np.allclose(basis[0], orient.axis_vector(CUBIC, right),
                           atol=1e-9)
        assert np.allclose(basis[1], -orient.axis_vector(CUBIC, down),
                           atol=1e-9)


def test_the_b_view_is_wide_when_c_is_the_long_axis():
    """The aspect-ratio check against Christian's Mercury screenshot: a cell
    with c = 16 A must come out WIDE in the b view, not tall."""
    cell = Cell(7.137, 14.438, 16.11, 90.0, 90.0, 90.0)
    basis = orient.look_along(cell, "b")
    corners = cell.corners()
    # np.ptp(), not arr.ptp(): the method was removed in NumPy 2.0, and the
    # desktop runs 2.x while the laptop did not — the test failed only here.
    assert np.ptp(corners @ basis[0]) > np.ptp(corners @ basis[1])


def test_looking_down_c_does_not_blow_up_on_the_parallel_up_vector():
    """c as both forward and up is degenerate; a basis still has to exist,
    because every button must do something."""
    assert _is_view_basis(orient.view_basis(np.array([0.0, 0.0, 1.0]),
                                            np.array([0.0, 0.0, 1.0])))


# ------------------------------------------------ standard (clinographic)
def test_the_standard_orientation_shows_all_three_axes():
    """No axis may be seen exactly end-on, or the cell reads as a flat quad.

    Note what is NOT asserted: that no two axes share a screen direction.
    The classical clinographic view deliberately looks nearly down **a** and
    foreshortens it to sin(18.4 deg) of its length, so a and b do project onto
    nearly the same screen line. That is the projection working, not failing.
    """
    for cell in (CUBIC, MONOCLINIC, TRICLINIC):
        basis = orient.clinographic(cell)
        assert _is_view_basis(basis)
        for letter in "abc":
            v = orient.axis_vector(cell, letter)
            xy = np.array([float(np.dot(v, basis[0])),
                           float(np.dot(v, basis[1]))])
            assert np.linalg.norm(xy) > 0.15      # not seen end-on
        # The cell must project to a real 2-D outline, not a line.
        corners = cell.corners()
        xs, ys = corners @ basis[0], corners @ basis[1]
        assert np.ptp(xs) > 0.1 * cell.a and np.ptp(ys) > 0.1 * cell.c


def test_the_standard_orientation_looks_DOWN_on_the_crystal():
    """Christian's report: the oblique view arrived from underneath the floor
    grid. The elevation is applied to the forward vector, and the sign is the
    whole difference between a crystal drawing and looking up through it."""
    for cell in (CUBIC, MONOCLINIC, TRICLINIC):
        forward = -orient.clinographic(cell)[2]
        c = orient.axis_vector(cell, "c")
        assert float(np.dot(forward, c)) < 0.0


def test_the_standard_orientation_puts_c_upward_on_screen():
    for cell in (CUBIC, MONOCLINIC, TRICLINIC):
        basis = orient.clinographic(cell)
        c = orient.axis_vector(cell, "c")
        assert float(np.dot(c, basis[1])) > 0.9   # strongly up


# ------------------------------------------------------------------- zoom
def test_zoom_percent_maps_onto_the_cameras_own_exponential_steps():
    from molom.core.camera import Camera
    cam = Camera()
    cam.distance = 10.0
    cam.zoom(orient.zoom_steps_for_percent(10.0))
    assert cam.distance == pytest.approx(9.0)
    cam.distance = 10.0
    cam.zoom(orient.zoom_steps_for_percent(-25.0))
    assert cam.distance == pytest.approx(12.5)


def test_zoom_percent_is_clamped_rather_than_going_singular():
    assert np.isfinite(orient.zoom_steps_for_percent(100.0))
    assert np.isfinite(orient.zoom_steps_for_percent(1e6))


# --------------------------------------------------------------- the widget
@pytest.fixture
def ribbon():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.crystal_ribbon import CrystalRibbon
    QApplication.instance() or QApplication([])
    return CrystalRibbon()


def test_the_ribbon_is_hidden_until_a_crystal_is_in_focus(ribbon):
    assert not ribbon.isVisible()
    ribbon.set_crystal(CUBIC, "halite")
    assert not ribbon.isHidden()
    ribbon.set_crystal(None)
    assert ribbon.isHidden()


def test_every_ribbon_button_is_non_checkable(ribbon):
    """`QToolButton.clicked` carries the checked state, and a non-checkable
    button passes False forever — the round-34 symmetry-arrow bug. Nothing
    here may be checkable, and no slot may read the argument."""
    from PySide6.QtWidgets import QToolButton
    buttons = ribbon.findChildren(QToolButton)
    assert buttons
    assert not any(b.isCheckable() for b in buttons)


def test_the_axis_buttons_emit_their_own_key(ribbon):
    seen = []
    ribbon.axis_view.connect(seen.append)
    for key in orient.AXIS_KEYS:
        ribbon._axis_buttons[key].click()
    assert seen == list(orient.AXIS_KEYS)


def test_the_step_boxes_scale_what_the_buttons_emit(ribbon):
    from PySide6.QtWidgets import QToolButton
    rots, pans, zooms = [], [], []
    ribbon.rotate_view.connect(lambda x, y: rots.append((x, y)))
    ribbon.pan_view.connect(lambda x, y: pans.append((x, y)))
    ribbon.zoom_view.connect(zooms.append)
    ribbon.rot_step.setValue(12.0)
    ribbon.pan_step.setValue(30)
    ribbon.zoom_step.setValue(25)
    by_text = {b.text(): b for b in ribbon.findChildren(QToolButton)}
    by_text["↻"].click()          # rotate right
    by_text["⬅"].click()          # pan left
    by_text["+"].click()
    by_text["−"].click()
    assert rots == [(12.0, 0.0)]
    assert pans == [(-30.0, 0.0)]
    assert zooms == [25.0, -25.0]


# --------------------------------------------------- leaving an axis view
def test_orbiting_out_of_an_axis_view_re_levels_the_horizon():
    """Christian: "setting view down cell axis b forces the camera into a
    view where the y-axis always points up... can you make it so if I exit
    view down b, I naturally return to the default alignment."

    An axis view's up is a CELL axis, which the world-Z-up turntable has no
    way to express, so the first orbit levels back first — the same contract
    `auto_ortho` has with perspective.
    """
    from molom.core.camera import Camera, quat_from_mat3, quat_to_mat3
    cam = Camera()
    cam.rotation = quat_from_mat3(orient.look_along(MONOCLINIC, "b"))
    cam.auto_level = True
    tilted = float((quat_to_mat3(cam.rotation)
                    @ np.array([0.0, 0.0, 1.0]))[0])
    assert abs(tilted) > 1e-6                 # the pose really is rolled
    cam.rotate(12.0, 0.0)
    level = float((quat_to_mat3(cam.rotation) @ np.array([0.0, 0.0, 1.0]))[0])
    assert abs(level) < 1e-9                  # turntable invariant restored
    assert not cam.auto_level                 # and it only happens once


def test_level_horizon_keeps_the_view_direction():
    """Levelling must only untwist, never turn you to face somewhere else."""
    from molom.core.camera import Camera, quat_from_mat3
    cam = Camera()
    cam.rotation = quat_from_mat3(orient.look_along(TRICLINIC, "a"))
    before = cam.forward().copy()
    cam.level_horizon()
    assert np.allclose(cam.forward(), before, atol=1e-9)


def test_level_horizon_leaves_a_top_view_alone():
    """Z-up is undefined looking straight down, and a top view is a perfectly
    good turntable pose — levelling it would spin the picture for nothing."""
    from molom.core.camera import Camera
    cam = Camera()
    cam.align_view(2, 1)
    before = cam.rotation.copy()
    cam.level_horizon()
    assert np.allclose(cam.rotation, before)
