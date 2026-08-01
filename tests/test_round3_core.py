"""Round-3 core: turntable/no-roll camera, axis views, rotations/Euler,
R modal, local-frame cycling, precision, undo stack, planar align, mathexpr,
scene snapshots."""

import numpy as np
import pytest

from molom.core import align, mathexpr, rotations, selection2d
from molom.core.camera import (Camera, quat_from_mat3, quat_to_mat3,
                               quat_from_axis_angle)
from molom.core.manipulate import GrabState, RotateState
from molom.core.scene import Scene
from molom.core.structure import Structure
from molom.core.undo import UndoStack


# ------------------------------------------------------------------- camera

def test_quat_mat_roundtrip():
    rng = np.random.default_rng(3)
    for _ in range(20):
        q = quat_from_axis_angle(rng.normal(size=3), rng.uniform(-3, 3))
        m = quat_to_mat3(q)
        q2 = quat_from_mat3(m)
        assert np.allclose(quat_to_mat3(q2), m, atol=1e-9)


def test_turntable_never_rolls():
    """World +Z must always project to a vertical screen line: its view-space
    x component stays 0 through any orbit sequence (Blender turntable)."""
    cam = Camera()
    rng = np.random.default_rng(7)
    for _ in range(40):
        cam.rotate(rng.uniform(-200, 200), rng.uniform(-200, 200))
        z_view = quat_to_mat3(cam.rotation) @ np.array([0.0, 0.0, 1.0])
        assert abs(z_view[0]) < 1e-9


def test_turntable_pivot_screen_invariant():
    cam = Camera()
    cam.center = np.array([1.0, -2.0, 0.5])
    cam.distance = 12.0
    pivot = np.array([2.0, 1.0, -1.0])
    w = h = 640
    xy0, _ = selection2d.project_points(
        pivot[None, :], cam.view_matrix(), cam.projection_matrix(w, h), w, h)
    cam.rotate(55.0, 23.0, pivot=pivot)
    xy1, _ = selection2d.project_points(
        pivot[None, :], cam.view_matrix(), cam.projection_matrix(w, h), w, h)
    assert np.allclose(xy0, xy1, atol=1e-3)


def test_align_view_looks_along_axis():
    cam = Camera()
    cam.align_view(0, 1)      # from +X
    r = quat_to_mat3(cam.rotation)
    # looking along -X: world -X maps to view -Z (into the screen)
    assert np.allclose(r @ np.array([-1.0, 0, 0]), [0, 0, -1], atol=1e-9)
    # world +Z is screen-up
    assert np.allclose(r @ np.array([0.0, 0, 1.0]), [0, 1, 0], atol=1e-9)
    assert cam.orthographic and cam.auto_ortho


def test_align_view_z_uses_y_up():
    cam = Camera()
    cam.align_view(2, 1)      # top view
    r = quat_to_mat3(cam.rotation)
    assert np.allclose(r @ np.array([0.0, 1.0, 0]), [0, 1, 0], atol=1e-9)


def test_auto_ortho_pops_on_orbit_not_on_manual():
    cam = Camera()
    cam.align_view(1, -1)
    assert cam.orthographic
    cam.rotate(10, 0)
    assert not cam.orthographic and not cam.auto_ortho
    cam.orthographic = True   # manual (viewport toggle clears auto_ortho)
    cam.auto_ortho = False
    cam.rotate(10, 0)
    assert cam.orthographic   # manual ortho survives orbiting


# ---------------------------------------------------------------- rotations

def test_axis_angle_mat3_90():
    m = rotations.axis_angle_mat3([0, 0, 1], np.pi / 2)
    assert np.allclose(m @ [1, 0, 0], [0, 1, 0], atol=1e-12)


def test_euler_roundtrip():
    rng = np.random.default_rng(11)
    for _ in range(25):
        e = rng.uniform(-1.4, 1.4, size=3)      # stay off gimbal lock
        m = rotations.euler_xyz_to_mat3(*e)
        e2 = rotations.mat3_to_euler_xyz(m)
        assert np.allclose(rotations.euler_xyz_to_mat3(*e2), m, atol=1e-9)


def test_rotate_points_about_pivot_fixed():
    pts = np.array([[1.0, 0, 0], [2.0, 0, 0]])
    m = rotations.axis_angle_mat3([0, 0, 1], np.pi)
    out = rotations.rotate_points_about(pts, m, [1.0, 0, 0])
    assert np.allclose(out[0], [1, 0, 0], atol=1e-12)   # pivot atom fixed
    assert np.allclose(out[1], [0, 0, 0], atol=1e-12)


# ----------------------------------------------------- G/R modal round 3

def _frame45():
    """Local frame rotated 45 deg about Z (columns = local axes)."""
    return rotations.axis_angle_mat3([0, 0, 1], np.pi / 4)


def test_axis_cycle_global_local_off():
    g = GrabState([0, 0, 0], [0, 0, -1], frame=_frame45())
    g.set_axis(0)
    assert g.axis == 0 and not g.axis_local
    assert np.allclose(g.axis_vector(), [1, 0, 0])
    g.set_axis(0)
    assert g.axis == 0 and g.axis_local
    assert np.allclose(g.axis_vector(),
                       [np.sqrt(0.5), np.sqrt(0.5), 0], atol=1e-12)
    assert "(local)" in g.constraint_label()
    g.set_axis(0)
    assert g.axis is None                     # third press: off
    # identity frame: local step is skipped (world == local)
    g2 = GrabState([0, 0, 0], [0, 0, -1])
    g2.set_axis(1)
    g2.set_axis(1)
    assert g2.axis is None


def test_grab_precision_scales_increments():
    g = GrabState([0, 0, 0], [0, 0, -1])
    g.precision_factor = 0.5
    o, d = np.array([0, 0, 10.0]), np.array([0, 0, -1.0])
    g.update_mouse(o, d)                                  # reference
    g.update_mouse(np.array([2.0, 0, 10.0]), d)           # +2 full speed
    g.set_precision(True)
    g.update_mouse(np.array([4.0, 0, 10.0]), d)           # +2 at half speed
    assert np.allclose(g.delta(), [3.0, 0, 0])
    g.set_precision(False)
    g.update_mouse(np.array([5.0, 0, 10.0]), d)           # +1 full again
    assert np.allclose(g.delta(), [4.0, 0, 0])


def test_rotate_numeric_degrees_about_locked_axis():
    r = RotateState([0, 0, 0], [0, 0, -1])
    r.set_axis(2)
    for ch in "90":
        r.type_char(ch)
    m = r.rotation_matrix()
    assert np.allclose(m @ [1, 0, 0], [0, 1, 0], atol=1e-9)


def test_rotate_mouse_follows_cursor():
    """View from +Z (view_dir -Z), axis +Z (toward viewer). Cursor sweeping
    visually clockwise (atan2 in y-down coords increasing) must rotate the
    selection clockwise as seen on screen = negative right-hand angle."""
    r = RotateState([0, 0, 0], [0, 0, -1.0])
    r.set_axis(2)
    pivot_screen = (100.0, 100.0)
    r.update_mouse((150.0, 100.0), pivot_screen)   # angle 0
    r.update_mouse((100.0, 150.0), pivot_screen)   # +90 deg in y-down atan2
    assert r.angle() == pytest.approx(-np.pi / 2)
    # a point on +X should end up on -Y (clockwise seen from +Z)
    out = r.rotation_matrix() @ np.array([1.0, 0, 0])
    assert np.allclose(out, [0, -1, 0], atol=1e-9)


def test_rotate_local_axis_cycle():
    r = RotateState([0, 0, 0], [0, 0, -1], frame=_frame45())
    r.set_axis(0)
    r.set_axis(0)
    assert r.axis_local
    e = r.effective_axis()
    assert np.allclose(e, [np.sqrt(0.5), np.sqrt(0.5), 0], atol=1e-12)


def test_rotate_precision_scales():
    r = RotateState([0, 0, 0], [0, 0, -1])
    r.precision_factor = 0.5
    p = (0.0, 0.0)
    r.update_mouse((10.0, 0.0), p)
    r.update_mouse((10.0, 10.0), p)          # 45 deg full speed
    a1 = abs(r.angle())
    r.set_precision(True)
    r.update_mouse((0.0, 10.0), p)           # another 45, half speed
    assert abs(r.angle()) == pytest.approx(a1 + a1 / 2, rel=1e-6)


# --------------------------------------------------------------------- undo

def test_undo_redo_cycle():
    u = UndoStack(limit=3)
    assert not u.can_undo and not u.can_redo
    u.push("s0")
    u.push("s1")
    got = u.undo("s2")                       # current s2 -> back to s1
    assert got == "s1" and u.can_redo
    assert u.redo("s1") == "s2"
    u.push("s3")                             # new edit invalidates redo
    assert not u.can_redo


def test_undo_limit_and_discard():
    u = UndoStack(limit=2)
    u.push("a")
    u.push("b")
    u.push("c")                              # "a" trimmed
    assert u.undo("cur") == "c"
    assert u.undo("c") == "b"
    assert u.undo("b") is None
    u.push("x")
    u.discard_last()
    assert not u.can_undo


# -------------------------------------------------------------------- align

def _benzene_ish():
    """6 ring atoms in the x+z plane (tilted), plus 3 stragglers."""
    ang = np.linspace(0, 2 * np.pi, 6, endpoint=False)
    ring = np.stack([1.4 * np.cos(ang), np.zeros(6), 1.4 * np.sin(ang)],
                    axis=1)
    extra = np.array([[0.0, 2.5, 0.3], [1.0, -3.0, 0.7], [-2.0, 1.5, -1.1]])
    return np.vstack([ring, extra])


def test_largest_planar_cluster_finds_ring():
    pts = _benzene_ish()
    mask = align.largest_planar_cluster(pts, tol=0.1)
    assert mask[:6].all()
    assert mask.sum() < 9                    # stragglers excluded


def test_align_planar_to_xy():
    pts = _benzene_ish()
    rot, pivot, mask = align.align_planar_to_plane(pts, [0, 0, 1], tol=0.1)
    out = rotations.rotate_points_about(pts, rot, pivot)
    assert np.abs(out[mask][:, 2] - out[mask][0, 2]).max() < 0.15
    ring_z_spread = out[:6][:, 2].std()
    assert ring_z_spread < 0.1               # ring is now flat in z


def test_rotation_between_antiparallel():
    m = align.rotation_between([0, 0, 1], [0, 0, -1])
    assert np.allclose(m @ [0, 0, 1], [0, 0, -1], atol=1e-9)
    assert np.allclose(np.linalg.det(m), 1.0)


# ----------------------------------------------------------------- mathexpr

def test_mathexpr_basic():
    assert mathexpr.evaluate("3+5*1.3") == pytest.approx(9.5)
    assert mathexpr.evaluate("-2**2") == pytest.approx(-4.0)
    assert mathexpr.evaluate("(1+2)/4") == pytest.approx(0.75)
    assert mathexpr.evaluate("1,5") == pytest.approx(1.5)   # decimal comma


@pytest.mark.parametrize("bad", ["", "x", "1+", "__import__('os')",
                                 "abs(1)", "1/0", "'a'"])
def test_mathexpr_rejects(bad):
    with pytest.raises(ValueError):
        mathexpr.evaluate(bad)


# ---------------------------------------------------------- scene snapshots

def test_scene_snapshot_restore_roundtrip():
    sc = Scene()
    s = Structure.from_atoms([("O", 0, 0, 0), ("H", 0.9, 0, 0)], name="w")
    obj = sc.add(s)
    obj.origin = np.array([1.0, 2.0, 3.0])
    snap = sc.snapshot()
    s.frames[0][0] = [9.0, 9.0, 9.0]         # mutate after snapshot
    obj.origin[0] = -1.0
    sc.add(Structure.from_atoms([("He", 5, 5, 5)], name="he"))
    sc.restore(snap)
    assert sc.n_objects == 1
    o2 = sc.objects[0]
    assert o2.id == obj.id                   # ids survive restore
    assert np.allclose(o2.structure.coords[0], [0, 0, 0])
    assert np.allclose(o2.origin, [1.0, 2.0, 3.0])
    # snapshots are isolated: restoring twice from the same snap is safe
    sc.objects[0].structure.frames[0][0] = [7, 7, 7]
    sc.restore(snap)
    assert np.allclose(sc.objects[0].structure.coords[0], [0, 0, 0])
