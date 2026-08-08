"""Round 48: coordination polyhedra that are always complete, and legible.

Two of Christian's, both about the same picture: a polyhedron must close
whatever the display options are doing, and a translucent solid with no
outline does not read as a shape.
"""
import numpy as np
import pytest

from molom.core import cif, polyhedra


def _octahedron(cell_size=6.0, bond=2.0):
    """A metal at the cell ORIGIN with six oxygens around it.

    On the origin the metal sits on three faces at once, so it is drawn as
    eight boundary copies and its coordination is the case that used to come
    out open.
    """
    cell = cif.Cell(cell_size, cell_size, cell_size)
    f = bond / cell_size
    symbols = ["Mg", "O", "O", "O", "O", "O", "O"]
    frac = np.array([[0.0, 0.0, 0.0],
                     [f, 0.0, 0.0], [-f, 0.0, 0.0],
                     [0.0, f, 0.0], [0.0, -f, 0.0],
                     [0.0, 0.0, f], [0.0, 0.0, -f]])
    return symbols, frac, cell


def test_a_polyhedron_is_complete_even_when_donors_are_not_drawn():
    """The donor POSITIONS come from the periodic graph, so the solid closes
    whether or not an atom happens to be on screen."""
    symbols, frac, cell = _octahedron()
    xyz = frac @ cell.matrix()
    built = polyhedra.build_periodic(symbols, xyz, cell, len(symbols))
    assert len(built) == 1
    assert len(built[0]["vertices"]) == 6         # a whole octahedron
    assert built[0]["faces"]                      # ...with a closed hull


def test_the_drawn_bond_version_can_come_out_open():
    """The contrast that motivates the periodic one: with only some of the
    bonds present, `build` produces a partial solid or none at all."""
    symbols, frac, cell = _octahedron()
    xyz = frac @ cell.matrix()
    partial = [(0, 1, 1), (0, 3, 1), (0, 5, 1)]   # three donors of six
    built = polyhedra.build(symbols, xyz, partial)
    assert len(built) == 1
    assert len(built[0]["vertices"]) == 3         # a triangle, not a solid


def test_metal_neighbours_are_not_donors():
    """A polyhedron is drawn through its LIGANDS; a metal-metal contact is
    not a vertex of the coordination sphere."""
    cell = cif.Cell(6.0, 6.0, 6.0)
    symbols = ["Mg", "Mg", "O", "O", "O"]
    frac = np.array([[0.0, 0.0, 0.0], [0.34, 0.0, 0.0],
                     [0.0, 0.34, 0.0], [0.0, -0.34, 0.0],
                     [0.0, 0.0, 0.34]])
    built = polyhedra.build_periodic(symbols, frac @ cell.matrix(), cell,
                                     len(symbols), min_donors=3)
    for poly in built:
        assert len(poly["vertices"]) <= 3         # never counts the other Mg


def test_hull_edges_are_unique_segments():
    symbols, frac, cell = _octahedron()
    built = polyhedra.build_periodic(symbols, frac @ cell.matrix(), cell,
                                     len(symbols))
    edges = polyhedra.hull_edges(built)
    assert len(edges) % 2 == 0
    # an octahedron has 12 edges; the hull is triangulated but each edge is
    # emitted once per polyhedron
    assert len(edges) // 2 == 12


def test_no_polyhedra_means_no_edges():
    assert polyhedra.hull_edges([]).shape == (0, 3)


def test_fresnel_brightens_the_grazing_faces():
    """A face seen edge-on is lightened toward white; one seen flat-on keeps
    the element colour. Without it the solid has no readable silhouette."""
    symbols, frac, cell = _octahedron()
    built = polyhedra.build_periodic(symbols, frac @ cell.matrix(), cell,
                                     len(symbols))
    eye = np.array([0.0, 0.0, 40.0])
    colours = polyhedra.fresnel_colors(built, eye)
    assert len(colours) == 3 * sum(len(p["faces"]) for p in built)
    assert np.all(colours >= 0.0) and np.all(colours <= 1.0)
    # some faces are grazing and some are not, so the term actually varies
    assert colours.max() > colours.min() + 0.05


def test_fresnel_is_stable_for_a_degenerate_triangle():
    """A zero-area face must not produce a NaN colour and blank the pass."""
    poly = [{"vertices": np.zeros((3, 3)), "faces": [(0, 1, 2)],
             "color": (0.5, 0.5, 0.5), "centre": 0, "symbol": "Mg",
             "donors": []}]
    colours = polyhedra.fresnel_colors(poly, np.array([0.0, 0.0, 10.0]))
    assert np.all(np.isfinite(colours))


def test_a_real_framework_closes_every_metal(tmp_path):
    """ZIF-8's zinc: half of them are boundary copies, and under the drawn
    bonds those came out as flat triangles."""
    from molom.core import io, packing
    import os
    path = r"C:\Users\chris\Desktop\test cifs\ZIF-8.cif"
    if not os.path.exists(path):
        pytest.skip("ZIF-8 fixture not on this machine")
    atoms, meta = io._read_cif(path)[0]
    symbols = [a[0] for a in atoms]
    xyz = np.array([a[1:] for a in atoms])
    cell = cif.Cell.from_dict(meta["cell"])
    built = polyhedra.build_periodic(symbols, xyz, cell,
                                     int(meta["cell_content"]))
    zinc = [p for p in built if p["symbol"] == "Zn"]
    assert len(zinc) == 24
    assert all(len(p["vertices"]) == 4 for p in zinc)


# ------------------------------------------------------- the paint contract
def test_camera_frame_is_a_mapping_not_a_tuple():
    """Pinned because indexing it positionally is exactly what broke the
    viewport: `_camera_frame()[0]` raised KeyError inside `_draw_polyhedra`,
    Qt swallowed it, and everything drawn AFTER polyhedra — the grid and the
    compass — silently stopped. Nothing headless could see it, because the
    offscreen platform never runs paintGL at all."""
    import os
    import pytest as _pytest
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    _pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.viewport import MolViewport
    QApplication.instance() or QApplication([])
    view = MolViewport()
    frame = view._camera_frame()
    assert isinstance(frame, dict)
    assert {"eye", "view", "proj"} <= set(frame)
    assert len(frame["eye"]) == 3
