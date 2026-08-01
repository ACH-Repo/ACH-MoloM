"""Camera math (trackball / orbit / projections) and ray picking."""

import numpy as np
import pytest

from molom.core import picking, selection2d
from molom.core.camera import (Camera, look_at, orthographic, perspective,
                               quat_from_axis_angle, quat_mul, quat_to_mat3)


def test_perspective_shape():
    p = perspective(40.0, 4 / 3, 0.1, 100.0)
    assert p.shape == (4, 4)
    assert p[3, 2] == -1.0 and p[3, 3] == 0.0


def test_orthographic_maps_halfheight_to_unit():
    m = orthographic(5.0, 2.0, -10.0, 10.0)
    v = m @ np.array([10.0, 5.0, 0.0, 1.0])   # (half_w, half_h)
    assert v[0] == pytest.approx(1.0) and v[1] == pytest.approx(1.0)
    assert v[3] == pytest.approx(1.0)          # ortho keeps w = 1


def test_look_at_origin():
    v = look_at([0, 0, 10], [0, 0, 0], [0, 1, 0])
    p = v @ np.array([0.0, 0, 0, 1])
    assert p[2] == pytest.approx(-10.0)


def test_quat_rotation_90deg():
    q = quat_from_axis_angle([0, 0, 1], np.pi / 2)
    r = quat_to_mat3(q)
    assert np.allclose(r @ np.array([1.0, 0, 0]), [0, 1, 0], atol=1e-12)


def test_quat_mul_composes():
    qa = quat_from_axis_angle([0, 0, 1], np.pi / 2)
    r = quat_to_mat3(quat_mul(qa, qa))
    assert np.allclose(r @ np.array([1.0, 0, 0]), [-1, 0, 0], atol=1e-12)


def test_camera_view_places_center_at_distance():
    cam = Camera()
    cam.center = np.array([1.0, 2.0, 3.0])
    cam.distance = 7.0
    v = cam.view_matrix()
    p = v @ np.array([1.0, 2.0, 3.0, 1.0])
    assert np.allclose(p[:3], [0, 0, -7], atol=1e-5)


def test_camera_fit_contains_molecule():
    cam = Camera()
    cam.fit([0, 0, 0], 5.0)
    half = np.radians(Camera.FOV_Y / 2)
    assert cam.distance * np.tan(half) >= 5.0


# ----------------------------------------------------------------- trackball

def test_trackball_constant_rate_everywhere():
    """The fix for the arcball edge-acceleration: equal pixel drags must give
    equal rotation angles regardless of where on the screen they happen."""
    cam = Camera()
    q1 = cam.trackball_quat(30.0, 0.0)
    q2 = cam.trackball_quat(0.0, 30.0)
    ang1 = 2 * np.arccos(np.clip(q1[0], -1, 1))
    ang2 = 2 * np.arccos(np.clip(q2[0], -1, 1))
    assert ang1 == pytest.approx(ang2)
    # doubling the drag doubles the angle (strict proportionality)
    q3 = cam.trackball_quat(60.0, 0.0)
    ang3 = 2 * np.arccos(np.clip(q3[0], -1, 1))
    assert ang3 == pytest.approx(2 * ang1)


def test_trackball_speed_scales():
    cam = Camera()
    cam.rotate_speed = 2.0
    fast = 2 * np.arccos(np.clip(cam.trackball_quat(30, 0)[0], -1, 1))
    cam.rotate_speed = 1.0
    slow = 2 * np.arccos(np.clip(cam.trackball_quat(30, 0)[0], -1, 1))
    assert fast == pytest.approx(2 * slow)


def test_trackball_full_revolution_distance():
    cam = Camera()
    q = cam.trackball_quat(Camera.PX_PER_REV, 0.0)
    ang = 2 * np.arccos(np.clip(abs(q[0]), -1, 1))
    assert ang == pytest.approx(0.0, abs=1e-6)   # full turn = identity angle


def test_rotate_keeps_unit_quaternion():
    cam = Camera()
    for k in range(50):
        cam.rotate(5 + k, 3 - k)
    assert np.linalg.norm(cam.rotation) == pytest.approx(1.0)


# --------------------------------------------------------------------- orbit

def test_orbit_pivot_screen_position_invariant():
    """Rotating about an atom must keep that atom fixed on screen — the
    Avogadro-feel property the pivot orbit exists for."""
    cam = Camera()
    cam.center = np.array([1.0, -2.0, 0.5])
    cam.distance = 12.0
    cam.rotate(37.0, -18.0)                       # arbitrary starting pose
    pivot = np.array([2.0, 1.0, -1.0])
    w = h = 640
    view0 = cam.view_matrix()
    proj = cam.projection_matrix(w, h)
    xy0, _ = selection2d.project_points(pivot[None, :], view0, proj, w, h)
    dq = cam.trackball_quat(55.0, 23.0)
    cam.orbit(dq, pivot)
    xy1, _ = selection2d.project_points(pivot[None, :], cam.view_matrix(),
                                        cam.projection_matrix(w, h), w, h)
    assert np.allclose(xy0, xy1, atol=1e-3)


def test_orbit_default_pivot_is_center():
    cam = Camera()
    cam.center = np.array([3.0, 0.0, 0.0])
    c0 = cam.center.copy()
    cam.rotate(40, 25)                            # pivot None = center
    assert np.allclose(cam.center, c0)


def test_zoom_clamps():
    cam = Camera()
    cam.zoom(-1000)
    assert cam.distance <= 5000.0
    cam.zoom(1000)
    assert cam.distance >= 0.5


# ------------------------------------------------------------------- picking

def test_pick_direct_hit():
    origin = np.array([0.0, 0.0, 10.0])
    direction = np.array([0.0, 0.0, -1.0])
    centers = np.array([[0.0, 0, 0], [0.0, 0, -5]])
    radii = np.array([0.5, 0.5])
    assert picking.pick_sphere(origin, direction, centers, radii) == 0


def test_pick_nearest_wins():
    origin = np.array([0.0, 0.0, 10.0])
    direction = np.array([0.0, 0.0, -1.0])
    centers = np.array([[0.0, 0, -5], [0.0, 0, 5]])
    radii = np.array([0.5, 0.5])
    assert picking.pick_sphere(origin, direction, centers, radii) == 1


def test_pick_miss_and_behind():
    origin = np.array([0.0, 0.0, 10.0])
    direction = np.array([0.0, 0.0, -1.0])
    assert picking.pick_sphere(origin, direction,
                               np.array([[5.0, 5, 0]]),
                               np.array([0.5])) is None
    assert picking.pick_sphere(np.zeros(3), direction,
                               np.array([[0.0, 0.0, 5.0]]),
                               np.array([0.5])) is None


def test_pick_through_screen_ray():
    cam = Camera()
    cam.center = np.zeros(3)
    cam.distance = 10.0
    w = h = 400
    view = cam.view_matrix()
    proj = cam.projection_matrix(w, h)
    origin, direction = picking.ray_from_screen(w / 2, h / 2, w, h, view, proj)
    centers = np.array([[0.0, 0.0, 0.0]])
    assert picking.pick_sphere(origin, direction, centers,
                               np.array([0.5])) == 0
    origin, direction = picking.ray_from_screen(5, 5, w, h, view, proj)
    assert picking.pick_sphere(origin, direction, centers,
                               np.array([0.5])) is None


def test_pick_segment_bond():
    origin = np.array([0.5, 5.0, 0.0])
    direction = np.array([0.0, -1.0, 0.0])
    starts = np.array([[0.0, 0, 0], [10.0, 0, 0]])
    ends = np.array([[1.0, 0, 0], [11.0, 0, 0]])
    assert picking.pick_segment(origin, direction, starts, ends, 0.3) == 0
    # aim well past the segment end: clamped endpoint is > radius away
    origin2 = np.array([3.0, 5.0, 0.0])
    assert picking.pick_segment(origin2, direction, starts, ends, 0.3) is None
    assert picking.pick_segment(origin, direction, np.zeros((0, 3)),
                                np.zeros((0, 3)), 0.3) is None


def test_pick_segment_nearest_of_two():
    origin = np.array([0.5, 0.0, 10.0])
    direction = np.array([0.0, 0.0, -1.0])
    starts = np.array([[0.0, 0, 0], [0.0, 0, 5.0]])
    ends = np.array([[1.0, 0, 0], [1.0, 0, 5.0]])
    assert picking.pick_segment(origin, direction, starts, ends, 0.3) == 1
