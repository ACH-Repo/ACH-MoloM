"""Grab-mode constraint math and screen-space selection regions."""

import numpy as np
import pytest

from molom.core import manipulate, selection2d
from molom.core.camera import Camera
from molom.core.manipulate import GrabState, ray_line_t, ray_plane


def test_ray_plane_hit():
    p = ray_plane([0, 0, 10], [0, 0, -1], [0, 0, 0], [0, 0, 1])
    assert np.allclose(p, [0, 0, 0])
    assert ray_plane([0, 0, 10], [1, 0, 0], [0, 0, 0], [0, 0, 1]) is None


def test_ray_line_t_closest():
    # Ray along -z at x=3 passes closest to the X axis at t=3.
    t = ray_line_t([3, 0, 10], [0, 0, -1], [0, 0, 0], [1, 0, 0])
    assert t == pytest.approx(3.0)


def _grab():
    return GrabState(pivot=[0.0, 0.0, 0.0], view_dir=[0.0, 0.0, -1.0])


def test_grab_free_move_in_view_plane():
    g = _grab()
    g.update_mouse(np.array([0, 0, 10.0]), np.array([0, 0, -1.0]))   # zero ref
    g.update_mouse(np.array([2, 1, 10.0]), np.array([0, 0, -1.0]))
    assert np.allclose(g.delta(), [2, 1, 0])


def test_grab_axis_lock_and_relock():
    g = _grab()
    g.set_axis(0)
    g.update_mouse(np.array([0, 0, 10.0]), np.array([0, 0, -1.0]))
    g.update_mouse(np.array([2.5, 7, 10.0]), np.array([0, 0, -1.0]))
    d = g.delta()
    assert d[0] == pytest.approx(2.5) and d[1] == 0.0 and d[2] == 0.0
    assert "along X" in g.constraint_label()
    g.set_axis(0)                                   # same axis again unlocks
    assert g.axis is None
    g.set_plane(2)                                  # Shift+Z -> XY plane
    assert "XY plane" in g.constraint_label()
    g.update_mouse(np.array([0, 0, 10.0]), np.array([0, 0, -1.0]))
    g.update_mouse(np.array([1, 2, 10.0]), np.array([0, 0, -1.0]))
    assert np.allclose(g.delta(), [1, 2, 0])


def test_grab_numeric_overrides_mouse():
    g = _grab()
    g.set_axis(2)
    g.update_mouse(np.array([0, 0, 10.0]), np.array([0, 0, -1.0]))
    g.update_mouse(np.array([5, 5, 10.0]), np.array([0, 0, -1.0]))
    for ch in "2.5":
        assert g.type_char(ch)
    assert np.allclose(g.delta(), [0, 0, 2.5])      # typed beats mouse
    g.type_char("-")
    assert np.allclose(g.delta(), [0, 0, -2.5])     # sign toggle
    g.backspace()                                   # "-2." -> invalid -> mouse
    g.backspace()
    g.backspace()
    g.backspace()
    assert g.numeric_value() is None
    assert not g.type_char("x")


def test_grab_status_text():
    g = _grab()
    g.set_axis(1)
    for ch in "3":
        g.type_char(ch)
    assert "along Y" in g.status_text() and "typed: 3" in g.status_text()


# ------------------------------------------------------------- selection 2d

def _screen_setup():
    cam = Camera()
    cam.center = np.zeros(3)
    cam.distance = 10.0
    w = h = 400
    return cam.view_matrix(), cam.projection_matrix(w, h), w, h


def test_project_points_center():
    view, proj, w, h = _screen_setup()
    xy, front = selection2d.project_points(np.zeros((1, 3)), view, proj, w, h)
    assert front[0]
    assert xy[0, 0] == pytest.approx(200.0) and xy[0, 1] == pytest.approx(200.0)


def test_project_points_behind_camera():
    view, proj, w, h = _screen_setup()
    xy, front = selection2d.project_points(np.array([[0.0, 0, 100.0]]),
                                           view, proj, w, h)
    assert not front[0]


def test_points_in_rect_any_corner_order():
    pts = np.array([[10, 10], [50, 50], [90, 90]])
    assert selection2d.points_in_rect(pts, 60, 60, 0, 0).tolist() == \
        [True, True, False]


def test_points_in_polygon_triangle():
    poly = np.array([[0, 0], [100, 0], [0, 100]])
    pts = np.array([[10, 10], [90, 90], [-5, 5]])
    assert selection2d.points_in_polygon(pts, poly).tolist() == \
        [True, False, False]


def test_points_in_polygon_degenerate():
    assert not selection2d.points_in_polygon(
        np.array([[1.0, 1.0]]), np.array([[0, 0], [1, 1]])).any()
