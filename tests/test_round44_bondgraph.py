"""Round 44: the labelled periodic bond graph (stage 4 of the crystal pipeline).

Every fixture here is CONSTRUCTED rather than read from a file — Christian's
test set is largely CCDC data that may not be redistributed, and these are
rules rather than files anyway. The rules are the ones the audit measured
against the real set.
"""
import itertools

import numpy as np
import pytest

from molom.core import bonding, bondgraph, cif


# --------------------------------------------------------------- fixtures
def _bcc_iron():
    """a = 2.87 A, Fe at the corner and the body centre. Coordination 8."""
    cell = cif.Cell(2.87, 2.87, 2.87)
    frac = np.array([[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]])
    return ["Fe", "Fe"], frac, cell


def _simple_cubic():
    """One atom per cell: every neighbour is one of its OWN images."""
    cell = cif.Cell(3.0, 3.0, 3.0)
    return ["Po"], np.array([[0.0, 0.0, 0.0]]), cell


def _rock_salt():
    """The CONVENTIONAL cubic cell, 4 Na + 4 Cl.

    Not a two-atom cell: Na(0,0,0) + Cl(1/2,0,0) alone is a chain, not rock
    salt, and gives coordination 2 where the mineral has 6.
    """
    cell = cif.Cell(5.64, 5.64, 5.64)
    frac = np.array([[0.0, 0.0, 0.0], [0.5, 0.5, 0.0],
                     [0.5, 0.0, 0.5], [0.0, 0.5, 0.5],
                     [0.5, 0.0, 0.0], [0.0, 0.5, 0.0],
                     [0.0, 0.0, 0.5], [0.5, 0.5, 0.5]])
    return ["Na"] * 4 + ["Cl"] * 4, frac, cell


def _brute_force(symbols, frac, cell, slack=0.45):
    """Reference edge count over an explicit 5x5x5 of translations."""
    m = cell.matrix()
    radii = bonding.covalent_radii(symbols)
    n = len(symbols)
    total = 0
    for t in itertools.product(range(-2, 3), repeat=3):
        for i in range(n):
            d = frac + np.array(t, float) - frac[i]
            dist = np.linalg.norm(d @ m, axis=1)
            limit = radii + radii[i] + slack
            hit = (dist > bonding.MIN_DISTANCE) & (dist < limit)
            total += int(hit.sum())
    return total // 2          # each bond seen from both ends


# ----------------------------------------------------- the shell, not the image
def test_an_atom_bonds_to_its_own_periodic_images():
    """The minimum image can never return this bond, and simple cubic is
    nothing BUT this bond: one atom, six neighbours, all of them itself."""
    symbols, frac, cell = _simple_cubic()
    graph = bondgraph.build(symbols, frac, cell)
    assert graph.degree(0) == 6
    assert all(e.i == e.j for e in graph.edges)
    assert len(graph.edges) == 3          # +x, +y, +z; their inverses are -x...


def test_bcc_iron_is_eight_coordinate():
    """Under the minimum image this came back as ONE bond, because that
    convention keeps at most one image per pair of indices."""
    symbols, frac, cell = _bcc_iron()
    graph = bondgraph.build(symbols, frac, cell)
    assert list(graph.coordination()) == [8, 8]
    assert len(graph.edges) == _brute_force(symbols, frac, cell)


def test_the_translation_shell_uses_perpendicular_widths():
    """Spec test 8: a cell whose PERPENDICULAR width is under twice the
    cutoff while its shortest EDGE is not. Deriving the shell from the edges
    silently drops the bonds that cross the thin direction."""
    cell = cif.Cell(7.0, 7.0, 7.0, alpha=90.0, beta=90.0, gamma=20.0)
    widths = bondgraph.perpendicular_widths(cell)
    assert min(widths) / 2.0 < 1.5 < min(cell.a, cell.b, cell.c) / 2.0
    symbols = ["C", "C"]
    frac = np.array([[0.1, 0.1, 0.1], [0.4, 0.4, 0.4]])
    graph = bondgraph.build(symbols, frac, cell)
    assert len(graph.edges) == _brute_force(symbols, frac, cell)
    assert not bondgraph.minimum_image_is_safe(cell, 1.5)


def test_minimum_image_is_safe_in_a_roomy_cell():
    cell = cif.Cell(17.0, 17.0, 17.0)
    assert bondgraph.minimum_image_is_safe(cell, 2.8)


# ------------------------------------------------------------------ labels
def test_edges_carry_the_npqr_code():
    symbols, frac, cell = _simple_cubic()
    graph = bondgraph.build(symbols, frac, cell)
    codes = sorted(bondgraph.npqr(e) for e in graph.edges)
    assert codes == ["1_556", "1_565", "1_655"]
    assert len(graph.crossing_edges()) == 3


def test_a_framework_reports_non_identity_edges():
    """Zero crossing edges means the framework was read as loose molecules —
    the single most useful smoke test in the whole pipeline."""
    symbols, frac, cell = _bcc_iron()
    graph = bondgraph.build(symbols, frac, cell)
    assert graph.crossing_edges()
    assert [rank for _group, rank in graph.components()] == [3]


def test_a_molecule_in_a_big_box_is_rank_zero():
    cell = cif.Cell(20.0, 20.0, 20.0)
    symbols = ["O", "H", "H"]
    frac = np.array([[0.5, 0.5, 0.5],
                     [0.5 + 0.0479, 0.5, 0.5],
                     [0.5 - 0.012, 0.5 + 0.0464, 0.5]])
    graph = bondgraph.build(symbols, frac, cell)
    assert [rank for _group, rank in graph.components()] == [0]
    assert not graph.crossing_edges()


# ----------------------------------------------------- stage 5: instantiation
def test_label_instances_recovers_the_lattice_shift():
    symbols, frac, cell = _rock_salt()
    extra = np.vstack([frac, frac[0] + np.array([1.0, 0.0, 0.0]),
                       frac[1] + np.array([0.0, -1.0, 2.0])])
    n = len(symbols)
    labels = bondgraph.label_instances(extra, cell, n)
    assert labels[:2] == [(0, (0, 0, 0)), (1, (0, 0, 0))]
    assert labels[n] == (0, (1, 0, 0))
    assert labels[n + 1] == (1, (0, -1, 2))


def test_an_atom_that_is_not_a_translate_is_unlabelled():
    symbols, frac, cell = _rock_salt()
    extra = np.vstack([frac, [[0.123, 0.456, 0.789]]])
    labels = bondgraph.label_instances(extra, cell, len(symbols))
    assert labels[-1] is None


def test_a_face_atom_keeps_its_whole_coordination_sphere():
    """The defect this module was written for.

    An atom sitting exactly ON a cell face is drawn twice, once per face.
    Perceiving bonds from Cartesian coordinates then splits ONE coordination
    sphere between the two copies — which is how every Zn in ZIF-8 came out
    3-coordinate. Instantiated from the graph, each copy carries its own
    shift and so looks up its own neighbours.
    """
    symbols, frac, cell = _rock_salt()
    graph = bondgraph.build(symbols, frac, cell)
    assert list(graph.coordination()) == [6] * 8
    # Atom 0 is the Na at the ORIGIN — on three faces at once, so it is drawn
    # at all eight corners. Give the picture those eight copies plus every
    # chloride in the surrounding cells, and each corner copy must come out
    # with its own full six, not a share of one sphere between them.
    corners = list(itertools.product((0, 1), repeat=3))
    instances = [(0, c) for c in corners]
    for shift in itertools.product((-1, 0, 1), repeat=3):
        for site in range(4, 8):                  # the chlorides
            instances.append((site, shift))
    instances = list(dict.fromkeys(instances))
    bonds = graph.instantiate(instances)
    count = {}
    for i, j, _o in bonds:
        count[i] = count.get(i, 0) + 1
        count[j] = count.get(j, 0) + 1
    assert [count.get(k, 0) for k in range(len(corners))] == [6] * 8


def test_instantiation_is_a_pure_function_of_its_inputs():
    """Spec: running it twice with the same inputs yields identical output."""
    symbols, frac, cell = _bcc_iron()
    graph = bondgraph.build(symbols, frac, cell)
    instances = [(i, s) for i in (0, 1)
                 for s in itertools.product((0, 1), repeat=3)]
    assert graph.instantiate(instances) == graph.instantiate(instances)


# ------------------------------------------------ the display-window question
def _coordination(symbols, frac, cell, na, nb, nc):
    """Per-atom CN of the first cell's atoms in an na x nb x nc block."""
    graph = bondgraph.build(symbols, frac, cell)
    instances = [(i, s) for s in itertools.product(range(na), range(nb),
                                                   range(nc))
                 for i in range(len(symbols))]
    bonds = graph.instantiate(instances)
    count = {}
    for i, j, _o in bonds:
        count[i] = count.get(i, 0) + 1
        count[j] = count.get(j, 0) + 1
    # the middle cell of the block, whose environment is complete
    mid = (na // 2, nb // 2, nc // 2)
    start = instances.index((0, mid))
    return [count.get(start + k, 0) for k in range(len(symbols))]


def test_coordination_is_independent_of_the_display_range():
    """Spec test 9. The bond graph is keyed on the cell, not on the window,
    so an interior atom has the same neighbours however many cells are drawn.
    """
    symbols, frac, cell = _rock_salt()
    assert _coordination(symbols, frac, cell, 3, 3, 3) == [6] * 8
    assert _coordination(symbols, frac, cell, 4, 4, 4) == [6] * 8
    assert _coordination(symbols, frac, cell, 5, 3, 4) == [6] * 8


def test_the_graph_does_not_depend_on_wrapping():
    """`unwrap_molecules` moves atoms by whole lattice vectors, so it must not
    be able to change the answer."""
    symbols, frac, cell = _bcc_iron()
    a = bondgraph.build(symbols, frac, cell)
    moved = frac + np.array([[0.0, 0.0, 0.0], [-1.0, 2.0, 0.0]])
    b = bondgraph.build(symbols, moved, cell)
    assert sorted(e.dist for e in a.edges) == pytest.approx(
        sorted(e.dist for e in b.edges))
    assert list(a.coordination()) == list(b.coordination())


# ------------------------------------------------------- the growth rules
def test_a_lattice_does_not_sprout_a_shell():
    """Rock salt's chloride is a lone ion, so completing the coordination of
    every drawn atom would bury the cell in a slab — round 42b's lesson, and
    the reason a coordination bond is only followed to a partner that belongs
    to a real molecule."""
    symbols, frac, cell = _rock_salt()
    drawn_symbols, drawn = cif.expand(
        cif.CifData(cell, [cif.SymOp.from_xyz("x,y,z")], symbols, frac))
    add_symbols, _add = cif.missing_partners(
        drawn_symbols, drawn, cell, len(symbols))
    assert not add_symbols


def test_a_bonded_partner_outside_the_box_is_materialised():
    """The other half of the same rule: a partner that carries a molecule IS
    brought in, which is what closes a linker across a cell face."""
    cell = cif.Cell(6.0, 6.0, 6.0)
    # A C-C dimer straddling the x face: 1.5 A apart through the boundary,
    # so the partner of the atom at x = 0.05 is the image at x = -0.20.
    symbols = ["C", "C"]
    frac = np.array([[0.05, 0.5, 0.5], [0.80, 0.5, 0.5]])
    graph = bondgraph.build(symbols, frac, cell)
    assert graph.crossing_edges()
    add_symbols, add_frac = cif.missing_partners(
        symbols, frac @ cell.matrix(), cell, len(symbols))
    # One at EACH end: the atom at x = 0.05 wants the image at x = -0.20, and
    # the one at x = 0.80 wants the image at x = 1.05.
    assert add_symbols == ["C", "C"]
    assert sorted(round(float(f[0]), 2) for f in add_frac) == [-0.20, 1.05]


def test_display_bonds_falls_back_for_atoms_it_cannot_label():
    """A hand-drawn atom is not a lattice translate of anything, so it must
    keep ordinary perception rather than come out unbonded."""
    cell = cif.Cell(12.0, 12.0, 12.0)
    symbols = ["C", "C", "H"]
    xyz = np.array([[1.0, 1.0, 1.0], [2.5, 1.0, 1.0], [3.6, 1.0, 1.0]])
    bonds = cif.display_bonds(symbols, xyz, cell, n_content=2)
    assert (1, 2, 1) in [(i, j, o) for i, j, o in bonds]
