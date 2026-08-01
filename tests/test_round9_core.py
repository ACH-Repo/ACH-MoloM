"""Round-9 core: force-field optimisation tiers and coordination-aware
hydrogen re-placement."""

import numpy as np
import pytest

from molom.core import bonding, coordination, edits, forcefield
from molom.core.structure import Structure


def _struct(atoms):
    s = Structure.from_atoms(atoms, name="t")
    bonding.perceive_structure_bonds(s)
    bonding.perceive_structure_bond_orders(s)
    return s


# ------------------------------------------------------------- force field

def _squashed_ethane():
    """Ethane with a badly short C-C and crumpled hydrogens."""
    return _struct([("C", 0, 0, 0), ("C", 1.20, 0, 0),
                    ("H", -0.4, 0.9, 0.2), ("H", -0.4, -0.5, 0.8),
                    ("H", -0.4, -0.5, -0.8), ("H", 1.6, -0.9, 0.2),
                    ("H", 1.6, 0.5, 0.8), ("H", 1.6, 0.5, -0.8)])


def test_optimize_relaxes_a_squashed_molecule():
    s = _squashed_ethane()
    d0 = float(np.linalg.norm(s.coords[1] - s.coords[0]))
    out, info = forcefield.optimize(s.symbols, s.coords, s.bonds, steps=800)
    assert out.shape == s.coords.shape
    d1 = float(np.linalg.norm(out[1] - out[0]))
    assert d1 > d0, "C-C did not relax outward ({:.2f} -> {:.2f})".format(d0, d1)
    assert 1.45 < d1 < 1.65, "C-C ended at {:.3f} A".format(d1)
    ch = [float(np.linalg.norm(out[i] - out[0])) for i in (2, 3, 4)]
    assert all(0.95 < d < 1.25 for d in ch), ch
    assert info["method"] == "mmff94" and info["engine"] == "rdkit"


def test_optimize_respects_fixed_atoms():
    s = _squashed_ethane()
    before = s.coords.copy()
    out, _info = forcefield.optimize(s.symbols, s.coords, s.bonds,
                                     steps=400, fixed=[0, 1])
    assert np.allclose(out[:2], before[:2], atol=1e-6), \
        "frozen atoms moved"
    assert not np.allclose(out[2:], before[2:]), "nothing else relaxed"


def test_optimize_falls_back_to_uff_for_metals():
    """MMFF has no parameters for a Zn complex; the UFF tier must catch it."""
    s = _struct([("Zn", 0, 0, 0), ("O", 1.9, 0, 0), ("H", 2.5, 0.8, 0)])
    out, info = forcefield.optimize(s.symbols, s.coords, s.bonds, steps=200)
    assert out.shape == (3, 3)
    assert info["method"] == "uff" or info["engine"] == "openbabel", info
    assert info["notes"], "fallback should record why MMFF was skipped"


def test_optimize_single_atom_is_a_noop():
    s = _struct([("C", 1.0, 2.0, 3.0)])
    out, info = forcefield.optimize(s.symbols, s.coords, s.bonds)
    assert np.allclose(out, s.coords)
    assert info["engine"] == "none"


def test_optimize_reports_backends():
    have = forcefield.backends_available()
    assert set(have) == {"rdkit", "openbabel"}
    assert have["rdkit"], "these tests assume RDKit is installed"


def test_method_list_defaults_to_mmff94():
    assert forcefield.DEFAULT_METHOD == "mmff94"
    assert forcefield.METHODS[0][0] == "mmff94"


# ------------------------------------------ coordination-aware hydrogens

def test_idealize_hydrogens_after_substitution():
    """Draw a C onto methane's carbon: the three leftover H's must swing to
    the free tetrahedral vertices instead of staying where they were."""
    tet = coordination.directions("tetrahedral") * 1.09
    atoms = [("C", 0.0, 0.0, 0.0)]
    atoms += [("H", float(v[0]), float(v[1]), float(v[2])) for v in tet]
    s = _struct(atoms)
    # replace one H with a carbon substituent placed off-template
    edits.delete_atoms(s, [4])
    edits.add_atom(s, "C", np.array([-1.0, -1.0, 1.3]), bond_to=0)
    moved = edits.idealize_terminal_hydrogens(s, [0])
    assert moved == 3, "expected all three H's to be re-placed"
    dirs = s.coords[1:4] - s.coords[0]
    dirs /= np.linalg.norm(dirs, axis=1)[:, None]
    sub = s.coords[4] - s.coords[0]
    sub /= np.linalg.norm(sub)
    # every H is now ~109.5 deg from the substituent and from each other
    for d in dirs:
        ang = np.degrees(np.arccos(np.clip(float(np.dot(d, sub)), -1, 1)))
        assert abs(ang - 109.47) < 3.0, ang
    for a in range(3):
        for b in range(a):
            ang = np.degrees(np.arccos(
                np.clip(float(np.dot(dirs[a], dirs[b])), -1, 1)))
            assert abs(ang - 109.47) < 3.0, ang
    # and they sit at the proper C-H distance
    d = np.linalg.norm(s.coords[1:4] - s.coords[0], axis=1)
    assert np.allclose(d, edits.ideal_bond_length(s, 0, 1), atol=1e-6)


def test_repel_directions_reproduces_tetrahedron():
    """Symmetric case: relaxation seeded from the template must stay on it."""
    tet = coordination.directions("tetrahedral")
    free = coordination.repel_directions(tet[:3], 1)
    assert free.shape == (1, 3)
    assert float(np.dot(free[0], tet[3])) > 0.999


def test_repel_directions_handles_a_squeezed_pair():
    """Two heavy bonds only 40 deg apart — a rigid template would drop a
    hydrogen almost on top of one; relaxation must keep clear of both."""
    a = np.array([1.0, 0.0, 0.0])
    b = np.array([np.cos(np.radians(40)), np.sin(np.radians(40)), 0.0])
    free = coordination.repel_directions(np.vstack([a, b]), 2)
    assert free.shape == (2, 3)
    for d in free:
        for fixed in (a, b):
            ang = np.degrees(np.arccos(
                np.clip(float(np.dot(d, fixed)), -1, 1)))
            assert ang > 80.0, "new direction only {:.1f} deg away".format(ang)
    sep = np.degrees(np.arccos(
        np.clip(float(np.dot(free[0], free[1])), -1, 1)))
    assert sep > 80.0, "the two new directions crowd each other: {:.1f}".format(sep)


def test_repel_directions_all_unit_and_deterministic():
    fixed = np.array([[0.0, 0.0, 1.0]])
    a = coordination.repel_directions(fixed, 3)
    b = coordination.repel_directions(fixed, 3)
    assert np.allclose(np.linalg.norm(a, axis=1), 1.0)
    assert np.allclose(a, b), "relaxation must be deterministic"
    assert coordination.repel_directions(fixed, 0).shape == (0, 3)


def test_idealize_with_awkward_heavy_geometry():
    """The real drag-draw case: a substituent dropped at a silly angle."""
    s = _struct([("C", 0, 0, 0), ("C", 1.54, 0, 0),
                 ("H", 0.0, 1.09, 0.0), ("H", 0.0, -0.55, 0.94)])
    # a second heavy neighbour crowded against the first
    edits.add_atom(s, "C", np.array([1.18, 0.99, 0.0]), bond_to=0)
    edits.idealize_terminal_hydrogens(s, [0])
    nbrs = s.bonded_neighbors(0)
    dirs = s.coords[nbrs] - s.coords[0]
    dirs /= np.linalg.norm(dirs, axis=1)[:, None]
    hyd = [k for k, j in enumerate(nbrs) if s.symbols[j] == "H"]
    for hk in hyd:
        for other in range(len(nbrs)):
            if other == hk:
                continue
            ang = np.degrees(np.arccos(
                np.clip(float(np.dot(dirs[hk], dirs[other])), -1, 1)))
            assert ang > 75.0, \
                "hydrogen crowds a neighbour at {:.1f} deg".format(ang)


def test_square_pyramidal_geometry():
    """The meta-atom case Christian asked about: a 5-donor square pyramid."""
    d = coordination.directions("square_pyramidal")
    assert d.shape == (5, 3)
    assert np.allclose(np.linalg.norm(d, axis=1), 1.0)
    apex, basal = d[0], d[1:]
    # four basal donors, mutually 90 deg apart around the apex axis
    for b in basal:
        ang = np.degrees(np.arccos(np.clip(float(np.dot(apex, b)), -1, 1)))
        assert 95.0 < ang < 110.0, "apex-basal angle {:.1f}".format(ang)
    spec = coordination.CoordinationSpec("square_pyramidal", distance=2.05)
    assert spec.n_donors == 5
    pos = coordination.ideal_donor_positions(np.zeros(3), spec)
    assert np.allclose(np.linalg.norm(pos, axis=1), 2.05)


def test_quadruple_bond_renders_four_cylinders():
    from molom.core import style as style_mod
    cyl = style_mod.bond_cylinders(np.zeros(3), np.array([1.5, 0, 0]), 4)
    assert len(cyl) == 4, "quadruple bond should draw four cylinders"
    assert len(style_mod.bond_cylinders(np.zeros(3),
                                        np.array([1.5, 0, 0]), 3)) == 3


def test_add_bond_allows_order_four():
    s = _struct([("Re", 0, 0, 0), ("Re", 2.24, 0, 0)])
    edits.add_bond(s, 0, 1, order=4)
    assert s.bonds[0][2] == 4
    edits.add_bond(s, 0, 1, order=9)      # still clamped
    assert s.bonds[0][2] == 4


def test_idealize_leaves_heavy_neighbours_alone():
    s = _struct([("C", 0, 0, 0), ("C", 1.54, 0, 0), ("O", -1.43, 0, 0),
                 ("H", 0, 1.09, 0), ("H", 0, -1.09, 0)])
    heavy_before = s.coords[[1, 2]].copy()
    edits.idealize_terminal_hydrogens(s, [0])
    assert np.allclose(s.coords[[1, 2]], heavy_before), \
        "heavy neighbours must not move"


def test_idealize_skips_atoms_without_hydrogens():
    s = _struct([("C", 0, 0, 0), ("C", 1.54, 0, 0)])
    assert edits.idealize_terminal_hydrogens(s, [0]) == 0
