"""Round 24: coordination polyhedra geometry."""

import numpy as np
import pytest

from molom.core import polyhedra


def _octahedron(centre_symbol="Fe", r=2.0):
    coords = [[0.0, 0.0, 0.0]]
    for axis in range(3):
        for sign in (1.0, -1.0):
            p = [0.0, 0.0, 0.0]
            p[axis] = sign * r
            coords.append(p)
    symbols = [centre_symbol] + ["O"] * 6
    bonds = [(0, j, 1) for j in range(1, 7)]
    return symbols, np.array(coords), bonds


def test_metals_are_recognised_and_non_metals_are_not():
    for sym in ("Fe", "Zn", "Cu", "Zr", "Al", "In", "La", "U"):
        assert polyhedra.is_metal(sym), sym
    for sym in ("H", "C", "N", "O", "F", "S", "Cl", "Br", "Si", "P", "Xe"):
        assert not polyhedra.is_metal(sym), sym


def test_centres_are_found_with_their_donors():
    symbols, coords, bonds = _octahedron()
    found = polyhedra.find_centres(symbols, bonds)
    assert list(found) == [0]
    assert found[0] == [1, 2, 3, 4, 5, 6]


def test_a_two_coordinate_metal_is_skipped():
    """Two donors have no interior — the 'polyhedron' would be a line."""
    symbols = ["Fe", "O", "O"]
    bonds = [(0, 1, 1), (0, 2, 1)]
    assert polyhedra.find_centres(symbols, bonds) == {}


def test_an_octahedron_has_eight_faces():
    symbols, coords, bonds = _octahedron()
    polys = polyhedra.build(symbols, coords, bonds)
    assert len(polys) == 1
    assert len(polys[0]["faces"]) == 8
    assert polys[0]["symbol"] == "Fe"


def test_a_tetrahedron_has_four_faces():
    symbols = ["Zn"] + ["N"] * 4
    coords = np.array([[0.0, 0, 0], [1.0, 1, 1], [1.0, -1, -1],
                       [-1.0, 1, -1], [-1.0, -1, 1]], dtype=float)
    bonds = [(0, j, 1) for j in range(1, 5)]
    polys = polyhedra.build(symbols, coords, bonds)
    assert len(polys[0]["faces"]) == 4


def test_face_normals_point_outward():
    """Backface culling needs consistent winding, or the solid looks
    hollowed out from some angles."""
    symbols, coords, bonds = _octahedron()
    poly = polyhedra.build(symbols, coords, bonds)[0]
    verts = poly["vertices"]
    centre = verts.mean(axis=0)
    for a, b, c in poly["faces"]:
        normal = np.cross(verts[b] - verts[a], verts[c] - verts[a])
        assert float(normal @ (verts[a] - centre)) > 0.0


def test_a_square_planar_centre_still_produces_triangles():
    """Degenerate (coplanar) donors must not crash or vanish."""
    symbols = ["Pd"] + ["Cl"] * 4
    coords = np.array([[0.0, 0, 0], [2.0, 0, 0], [-2.0, 0, 0],
                       [0.0, 2, 0], [0.0, -2, 0]], dtype=float)
    bonds = [(0, j, 1) for j in range(1, 5)]
    polys = polyhedra.build(symbols, coords, bonds)
    assert polys and len(polys[0]["faces"]) >= 2


def test_polyhedra_take_the_metal_colour():
    symbols, coords, bonds = _octahedron("Cu")
    from molom.core import elements
    poly = polyhedra.build(symbols, coords, bonds)[0]
    assert poly["color"] == pytest.approx(
        elements.color_f(elements.atomic_number("Cu")))


def test_an_organic_only_structure_produces_nothing():
    symbols = ["C", "O", "O", "H"]
    bonds = [(0, 1, 2), (0, 2, 1), (2, 3, 1)]
    coords = np.zeros((4, 3))
    assert polyhedra.build(symbols, coords, bonds) == []


def test_triangle_soup_is_three_vertices_per_face():
    symbols, coords, bonds = _octahedron()
    polys = polyhedra.build(symbols, coords, bonds)
    verts, cols = polyhedra.triangle_soup(polys)
    assert verts.shape == (8 * 3, 3)
    assert cols.shape == verts.shape


def test_an_empty_scene_gives_empty_arrays():
    verts, cols = polyhedra.triangle_soup([])
    assert verts.shape == (0, 3) and cols.shape == (0, 3)


def test_an_absurd_coordination_number_is_skipped():
    """A 'metal' bonded to 30 things is a graph artefact, not a node."""
    symbols = ["Fe"] + ["O"] * 30
    coords = np.random.RandomState(0).rand(31, 3) * 3.0
    bonds = [(0, j, 1) for j in range(1, 31)]
    assert polyhedra.build(symbols, coords, bonds, max_donors=12) == []
