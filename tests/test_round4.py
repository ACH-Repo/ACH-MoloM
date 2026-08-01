"""Round-4 core additions: scroll-driven R rotation, axis alignment + flip."""

import numpy as np
import pytest

from molom.core import align
from molom.core.manipulate import RotateState
from molom.core.rotations import rotate_points_about


def test_add_angle_view_independent():
    """Scroll rotation must move the FINAL angle by the given delta with the
    same sign regardless of which way the locked axis points."""
    for view_dir in ([0, 0, -1.0], [0, 0, 1.0]):
        r = RotateState([0, 0, 0], view_dir)
        r.set_axis(2)
        r.add_angle(0.5)
        assert r.angle() == pytest.approx(0.5), view_dir


def test_add_angle_precision():
    r = RotateState([0, 0, 0], [0, 0, -1.0])
    r.set_axis(0)
    r.add_angle(0.4)
    r.set_precision(True)
    r.precision_factor = 0.5
    r.add_angle(0.4)
    assert r.angle() == pytest.approx(0.6)


def test_add_angle_numeric_still_wins():
    r = RotateState([0, 0, 0], [0, 0, -1.0])
    r.set_axis(1)
    r.add_angle(1.0)
    for ch in "45":
        r.type_char(ch)
    assert np.degrees(r.angle()) == pytest.approx(45.0)


def test_align_vector_to_axis_smallest_turn():
    # v roughly along -x: aligning to the X axis should pick -x (small turn)
    v = np.array([-1.0, 0.2, 0.0])
    rot = align.align_vector_to_axis(v, [1.0, 0, 0])
    out = rot @ (v / np.linalg.norm(v))
    assert abs(out[0]) == pytest.approx(1.0, abs=1e-9)
    assert out[0] < 0                      # stayed on the -x side
    ang = np.arccos(np.clip((np.trace(rot) - 1) / 2, -1, 1))
    assert ang < np.pi / 2


def test_align_two_atoms_then_flip():
    pts = np.array([[0.0, 0, 0], [1.0, 1.0, 0.0], [2.0, 0.5, 0.3]])
    v = pts[1] - pts[0]
    rot = align.align_vector_to_axis(v, [0, 0, 1.0])
    pivot = (pts[0] + pts[1]) / 2.0
    out = rotate_points_about(pts, rot, pivot)
    d = out[1] - out[0]
    assert abs(d[0]) < 1e-9 and abs(d[1]) < 1e-9      # now along z
    z_sign = np.sign(d[2])
    # flip reverses the direction but keeps the line and the rigidity
    out2 = rotate_points_about(out, align.flip_about_axis([0, 0, 1.0]), pivot)
    d2 = out2[1] - out2[0]
    assert np.sign(d2[2]) == -z_sign
    assert np.linalg.norm(d2) == pytest.approx(np.linalg.norm(v))
    for i in range(3):
        for j in range(i):
            assert (np.linalg.norm(out2[i] - out2[j])
                    == pytest.approx(np.linalg.norm(pts[i] - pts[j])))


def test_flip_about_axis_is_rotation():
    m = align.flip_about_axis([1.0, 0, 0])
    assert np.allclose(m @ m, np.eye(3), atol=1e-12)   # involution
    assert np.linalg.det(m) == pytest.approx(1.0)      # proper rotation
    assert np.allclose(m @ [1.0, 0, 0], [-1.0, 0, 0], atol=1e-12)


# ------------------------------------------------- round 5: batch stacking

def test_zstack_offsets_clearance():
    radii = [2.0, 3.0, 1.0]
    zs = align.zstack_offsets(radii, gap=2.0)
    assert zs[0] == 0.0
    for k in range(1, len(zs)):
        centre_gap = zs[k] - zs[k - 1]
        assert centre_gap == pytest.approx(radii[k - 1] + 2.0 + radii[k])
    assert align.zstack_offsets([5.0]) == [0.0]
    assert align.zstack_offsets([]) == []


def test_dot_smiles_split():
    from molom.core import io
    pairs = io.parse_smiles_list("CCO.c1ccccc1.[Na+]")
    assert [s for s, _n in pairs] == ["CCO", "c1ccccc1", "[Na+]"]
    pairs = io.parse_smiles_list("CCO")
    assert [s for s, _n in pairs] == ["CCO"]
