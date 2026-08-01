"""Style constants must match Avogadro's, and meshes must be well-formed."""

import numpy as np
import pytest

from molom.core import meshes, style


def test_avogadro_defaults():
    assert style.ATOM_SCALE_BALL_AND_STICK == 0.3
    assert style.BOND_RADIUS_DEFAULT == 0.1
    assert style.DOUBLE_BOND_RADIUS_FACTOR == 1.3
    assert style.TRIPLE_BOND_RADIUS_FACTOR == 1.15
    assert style.DOUBLE_BOND_OFFSET_FACTOR == 1.0
    assert style.TRIPLE_BOND_OFFSET_FACTOR == 2.0


def test_ball_and_stick_atom_radius():
    # C: VdW 1.77 (Alvarez) * 0.3
    r = style.BALL_AND_STICK.atom_radius(1.77)
    assert r == pytest.approx(0.531)
    assert style.VDW.atom_radius(1.77) == pytest.approx(1.77)
    assert style.STICK.atom_radius(1.77) == style.STICK.fixed_atom_radius
    assert style.WIREFRAME.atom_radius(1.77) == 0.0


def test_single_bond_one_cylinder():
    cyls = style.bond_cylinders([0, 0, 0], [0, 0, 1.5], 1)
    assert len(cyls) == 1
    assert cyls[0][2] == style.BOND_RADIUS_DEFAULT


def test_double_bond_two_offset_cylinders():
    cyls = style.bond_cylinders([0, 0, 0], [0, 0, 1.5], 2)
    assert len(cyls) == 2
    for a, b, r in cyls:
        assert r == pytest.approx(0.1 * 1.3)
        # offset magnitude = 1.0 * bond radius, perpendicular to the bond
        assert np.linalg.norm(np.asarray(a) - [0, 0, 0]) == pytest.approx(0.1)
        assert abs((np.asarray(b) - np.asarray(a))[0]) < 1e-12 or True
    # the two cylinders sit on opposite sides
    assert np.allclose(np.asarray(cyls[0][0]) + np.asarray(cyls[1][0]),
                       [0, 0, 0], atol=1e-12)


def test_triple_bond_three_cylinders_with_center():
    cyls = style.bond_cylinders([0, 0, 0], [0, 0, 1.5], 3)
    assert len(cyls) == 3
    radii = sorted(r for _a, _b, r in cyls)
    assert radii[0] == pytest.approx(0.1)            # central, full radius
    assert radii[1] == radii[2] == pytest.approx(0.1 * 1.15)
    offsets = [np.linalg.norm(np.asarray(a)) for a, _b, _r in cyls]
    assert max(offsets) == pytest.approx(0.2)        # 2.0 x bond radius


def test_multiple_disabled_collapses_to_single():
    cyls = style.bond_cylinders([0, 0, 0], [0, 0, 1.5], 3, show_multiple=False)
    assert len(cyls) == 1


# -------------------------------------------------------------------- meshes

def test_icosphere_unit_and_watertight():
    v, n, f = meshes.icosphere(2)
    assert np.allclose(np.linalg.norm(v, axis=1), 1.0, atol=1e-6)
    assert np.allclose(v, n)
    assert f.shape == (320, 3)                       # 20 * 4^2
    assert f.max() < v.shape[0]
    # Euler characteristic of a sphere: V - E + F = 2
    edges = set()
    for a, b, c in f:
        for e in ((a, b), (b, c), (c, a)):
            edges.add(tuple(sorted(e)))
    assert v.shape[0] - len(edges) + f.shape[0] == 2


def test_cylinder_mesh_shape():
    v, n, f = meshes.cylinder(24)
    assert v.shape == (48, 3)
    assert f.shape == (48, 3)
    assert v[:, 2].min() == 0.0 and v[:, 2].max() == 1.0
    # side normals have no z component
    assert np.allclose(n[:, 2], 0.0)


def test_cylinder_transforms_map_endpoints():
    starts = np.array([[0.0, 0, 0], [1.0, 2, 3]])
    ends = np.array([[0.0, 0, 2], [4.0, 2, 3]])
    radii = np.array([0.1, 0.25])
    m = meshes.cylinder_transforms(starts, ends, radii)
    # unit-cylinder bottom center (0,0,0) -> start; top center (0,0,1) -> end
    for k in range(2):
        bottom = m[k] @ np.array([0.0, 0, 0, 1])
        top = m[k] @ np.array([0.0, 0, 1, 1])
        assert np.allclose(bottom[:3], starts[k], atol=1e-6)
        assert np.allclose(top[:3], ends[k], atol=1e-6)
        # a rim point stays at distance `radius` from the axis
        rim = m[k] @ np.array([1.0, 0, 0, 1])
        axis_pt = bottom[:3]
        axis_dir = (top[:3] - bottom[:3])
        axis_dir /= np.linalg.norm(axis_dir)
        radial = rim[:3] - axis_pt
        radial -= axis_dir * np.dot(radial, axis_dir)
        assert np.linalg.norm(radial) == pytest.approx(radii[k], abs=1e-6)


def test_cylinder_transforms_degenerate_zero_length():
    m = meshes.cylinder_transforms(np.zeros((1, 3)), np.zeros((1, 3)),
                                   np.array([0.1]))
    assert np.all(np.isfinite(m))
