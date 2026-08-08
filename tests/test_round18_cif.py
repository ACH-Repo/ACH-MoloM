"""Round 18: CIF reading — cell, symmetry operators, asymmetric-unit expansion."""

import math

import numpy as np
import pytest

from molom.core import cif

# Halite (NaCl), Fm-3m, a = 5.64 A. Written with the 4 face-centring ops plus
# the mirror ones needed to fill the cell, which is enough to exercise the
# expansion without pasting all 192 operations of the real group.
NACL_CIF = """
data_halite
_symmetry_space_group_name_H-M   'F m -3 m'
_cell_length_a     5.6402(3)
_cell_length_b     5.6402(3)
_cell_length_c     5.6402(3)
_cell_angle_alpha  90.0
_cell_angle_beta   90.0
_cell_angle_gamma  90.0
loop_
_symmetry_equiv_pos_as_xyz
  'x,y,z'
  'x+1/2,y+1/2,z'
  'x+1/2,y,z+1/2'
  'x,y+1/2,z+1/2'
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
  Na1  Na  0.0  0.0  0.0
  Cl1  Cl  0.5  0.5  0.5
"""

TRICLINIC_CIF = """
data_tri
_cell_length_a 6.0
_cell_length_b 7.0
_cell_length_c 8.0
_cell_angle_alpha 80.0
_cell_angle_beta  85.0
_cell_angle_gamma 95.0
loop_
_atom_site_label
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
  C1  0.1 0.2 0.3
"""


# ------------------------------------------------------------- symmetry ops
@pytest.mark.parametrize("text,want", [
    ("x", (1, 0, 0, 0)),
    ("-x", (-1, 0, 0, 0)),
    ("y", (0, 1, 0, 0)),
    ("-z", (0, 0, -1, 0)),
    ("x+1/2", (1, 0, 0, 0.5)),
    ("1/2-x", (-1, 0, 0, 0.5)),
    ("-x+1/2", (-1, 0, 0, 0.5)),
    ("0.5+y", (0, 1, 0, 0.5)),
    ("x-y", (1, -1, 0, 0)),
    ("x-y+1/3", (1, -1, 0, 1.0 / 3.0)),
    ("2x", (2, 0, 0, 0)),
    ("x/2", (0.5, 0, 0, 0)),
    ("-1/4+z", (0, 0, 1, -0.25)),
])
def test_parse_symop_component(text, want):
    got = cif.parse_symop_component(text)
    assert got == pytest.approx(want, abs=1e-9)


def test_symop_from_xyz_round_trips_and_applies():
    op = cif.SymOp.from_xyz("-x+1/2, y, -z")
    out = op.apply(np.array([0.25, 0.10, 0.40]))
    assert out == pytest.approx([0.25, 0.10, -0.40])
    again = cif.SymOp.from_xyz(op.as_xyz())
    assert again.rotation == pytest.approx(op.rotation)
    assert again.translation == pytest.approx(op.translation)


def test_symop_needs_three_components():
    with pytest.raises(cif.CifError):
        cif.SymOp.from_xyz("x,y")


# -------------------------------------------------------------------- cell
def test_orthorhombic_cell_matrix_is_diagonal():
    c = cif.Cell(3.0, 4.0, 5.0)
    m = c.matrix()
    assert m == pytest.approx(np.diag([3.0, 4.0, 5.0]), abs=1e-9)
    assert c.volume() == pytest.approx(60.0)


def test_cell_matrix_reproduces_its_own_lengths_and_angles():
    c = cif.Cell(6.0, 7.0, 8.0, 80.0, 85.0, 95.0)
    va, vb, vc = c.matrix()
    assert np.linalg.norm(va) == pytest.approx(6.0)
    assert np.linalg.norm(vb) == pytest.approx(7.0)
    assert np.linalg.norm(vc) == pytest.approx(8.0)
    ang = lambda u, v: math.degrees(math.acos(
        float(u @ v) / (np.linalg.norm(u) * np.linalg.norm(v))))
    assert ang(vb, vc) == pytest.approx(80.0)      # alpha
    assert ang(va, vc) == pytest.approx(85.0)      # beta
    assert ang(va, vb) == pytest.approx(95.0)      # gamma


def test_fractional_cartesian_round_trip():
    c = cif.Cell(6.0, 7.0, 8.0, 80.0, 85.0, 95.0)
    frac = np.array([[0.1, 0.2, 0.3], [0.9, 0.5, 0.25]])
    assert c.to_fractional(c.to_cartesian(frac)) == pytest.approx(frac)


def test_impossible_angles_are_rejected():
    with pytest.raises(cif.CifError):
        cif.Cell(5.0, 5.0, 5.0, 20.0, 20.0, 170.0).matrix()


def test_cell_box_has_eight_corners_and_twelve_edges():
    c = cif.Cell(3.0, 4.0, 5.0)
    assert c.corners().shape == (8, 3)
    assert len(c.edges()) == 12
    assert c.corners()[0] == pytest.approx([0.0, 0.0, 0.0])


# ------------------------------------------------------------------ parsing
def test_parse_nacl():
    d = cif.parse_cif(NACL_CIF)
    assert d.name == "halite"
    assert d.spacegroup == "F m -3 m"
    assert d.cell.a == pytest.approx(5.6402)      # the (3) esd is stripped
    assert d.cell.alpha == pytest.approx(90.0)
    assert d.symbols == ["Na", "Cl"]              # the ASYMMETRIC unit only
    assert len(d.symops) == 4


def test_expansion_applies_every_operator():
    """The CONTENT of the cell: 2 sites x 4 centrings, no boundary copies."""
    d = cif.parse_cif(NACL_CIF)
    symbols, coords = cif.expand(d, boundary=False)
    assert len(symbols) == 8                      # 2 sites x 4 centrings
    assert symbols.count("Na") == 4
    assert symbols.count("Cl") == 4
    assert coords.shape == (8, 3)


def test_the_drawn_cell_completes_its_boundary():
    """What a crystallographer expects to SEE (round 32): rock salt is 14 Na
    (8 corners + 6 face centres) around 13 Cl (12 edge midpoints + the body
    centre). Drawing one corner atom and calling it a unit cell is what made
    Christian's NaCl look nothing like Mercury's."""
    d = cif.parse_cif(NACL_CIF)
    symbols, coords = cif.expand(d)
    assert symbols.count("Na") == 14
    assert symbols.count("Cl") == 13
    assert coords.shape == (27, 3)


def test_expansion_drops_duplicates_on_special_positions():
    """An atom sitting ON a symmetry element is mapped to itself; without
    de-duplication the cell fills with atoms stacked on each other."""
    d = cif.parse_cif(NACL_CIF)
    d.symops.append(cif.IDENTITY)                 # a redundant operator
    d.symops.append(cif.SymOp.from_xyz("x,y,z"))
    symbols, coords = cif.expand(d, boundary=False)
    assert len(symbols) == 8                      # still 8, not 16
    # ...and nothing is on top of anything else.
    for i in range(len(coords)):
        for j in range(i + 1, len(coords)):
            assert np.linalg.norm(coords[i] - coords[j]) > 0.1


def test_expansion_wraps_into_the_cell():
    d = cif.parse_cif(NACL_CIF)
    _syms, coords = cif.expand(d)
    frac = d.cell.to_fractional(coords)
    assert np.all(frac > -1e-9) and np.all(frac < 1.0 + 1e-9)


def test_no_symmetry_listed_means_p1():
    d = cif.parse_cif(TRICLINIC_CIF)
    assert len(d.symops) == 1
    symbols, coords = cif.expand(d)
    assert symbols == ["C"]
    assert coords[0] == pytest.approx(
        d.cell.to_cartesian(np.array([0.1, 0.2, 0.3])))


def test_element_is_taken_from_the_label_when_no_type_column():
    d = cif.parse_cif(TRICLINIC_CIF)
    assert d.symbols == ["C"]


def test_labels_with_digits_and_charges_resolve():
    assert cif._element_from_label("C12A") == "C"
    assert cif._element_from_label("Fe1", "Fe3+") == "Fe"
    assert cif._element_from_label("Cl2") == "Cl"
    assert cif._element_from_label("Na1") == "Na"
    assert cif._element_from_label("???") == ""


def test_a_file_without_a_cell_is_rejected():
    with pytest.raises(cif.CifError):
        cif.parse_cif("data_x\nloop_\n_atom_site_label\n C1\n")


def test_a_file_without_sites_is_rejected():
    with pytest.raises(cif.CifError):
        cif.parse_cif("data_x\n_cell_length_a 5\n_cell_length_b 5\n"
                      "_cell_length_c 5\n")


def test_molecules_are_reassembled_across_the_boundary():
    """Wrapping each atom into [0,1) on its own splits a molecule that
    straddles a face — the stray hydrogens Christian saw against the CCDC
    reference. A bonded fragment must come out contiguous."""
    cell = cif.Cell(10.0, 10.0, 10.0)
    # An O-H sitting across the z face: 0.98 and 1.076 -> wraps to 0.076.
    # The separation is a REAL 0.96 A O-H, not the 0.4 A this fixture used
    # before round 38: valence sanity now refuses a contact that short (it is
    # well inside any possible bond), so an impossible fixture would test
    # nothing but the new rule.
    symbols = ["O", "H"]
    frac = np.array([[0.5, 0.5, 0.98], [0.5, 0.5, 0.076]])
    out = cif.unwrap_molecules(symbols, frac, cell)
    cart = out @ cell.matrix()
    assert np.linalg.norm(cart[0] - cart[1]) == pytest.approx(0.96, abs=1e-6)


def test_unwrapping_leaves_a_compact_molecule_alone():
    cell = cif.Cell(10.0, 10.0, 10.0)
    symbols = ["O", "H"]
    frac = np.array([[0.5, 0.5, 0.50], [0.5, 0.5, 0.56]])
    out = cif.unwrap_molecules(symbols, frac, cell)
    assert out == pytest.approx(frac)


def test_periodic_neighbours_see_through_a_cell_face():
    # 0.95 / 0.05 of a 10 A cell = 1.0 A apart across the face: a real O-H.
    cell = cif.Cell(10.0, 10.0, 10.0)
    frac = np.array([[0.5, 0.5, 0.95], [0.5, 0.5, 0.05]])
    adj = cif.periodic_neighbours(["O", "H"], frac, cell)
    assert adj[0] == [1] and adj[1] == [0]


def test_straight_line_distance_would_have_missed_that_bond():
    """Why the minimum image matters: measured directly, those two atoms are
    9 A apart and no bond is found — which is how a framework ends up cut
    open at the cell faces."""
    cell = cif.Cell(10.0, 10.0, 10.0)
    frac = np.array([[0.5, 0.5, 0.95], [0.5, 0.5, 0.05]])
    cart = frac @ cell.matrix()
    assert np.linalg.norm(cart[0] - cart[1]) == pytest.approx(9.0)


def test_build_view_modes():
    d = cif.parse_cif(NACL_CIF)
    symops = d.symops
    asym, _ = cif.build_view(d.cell, d.symbols, d.frac, symops, mode="asym")
    cell_syms, _ = cif.build_view(d.cell, d.symbols, d.frac, symops,
                                  mode="cell")
    pack, coords = cif.build_view(d.cell, d.symbols, d.frac, symops,
                                  mode="packing", na=2, nb=2, nc=1)
    assert len(asym) == 2                 # the asymmetric unit as listed
    assert len(cell_syms) == 39           # one full cell, PACKED
    # NOT 27 x 4. Each cell in the block carries its own boundary copies, and
    # the copy on a shared internal face is the same atom as its neighbour's,
    # so stacking them naively draws it twice at exactly the same point. The
    # deduplicated count is the textbook grid: rock salt boundary-completed
    # over na x nb x nc cells is (2na+1)(2nb+1)(2nc+1), here 5 x 5 x 3.
    assert len(pack) == 107
    assert coords.shape == (107, 3)
    from scipy.spatial import cKDTree
    assert not cKDTree(coords).query_pairs(0.1)   # and no atom drawn twice


def test_rigid_from_reference_recovers_a_translation():
    ref = np.array([[0.0, 0, 0], [1.0, 0, 0], [0, 1.0, 0], [0, 0, 1.0]])
    rot, trans = cif.rigid_from_reference(ref, ref + np.array([3.0, -2.0, 1.0]))
    assert rot == pytest.approx(np.eye(3), abs=1e-9)
    assert trans == pytest.approx([3.0, -2.0, 1.0])


def test_rigid_from_reference_recovers_a_rotation():
    ref = np.array([[0.0, 0, 0], [1.0, 0, 0], [0, 1.0, 0], [0, 0, 1.0]])
    r90 = np.array([[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])
    rot, trans = cif.rigid_from_reference(ref, ref @ r90.T)
    assert rot == pytest.approx(r90, abs=1e-9)
    assert trans == pytest.approx([0, 0, 0], abs=1e-9)


def test_rigid_from_reference_refuses_degenerate_input():
    assert cif.rigid_from_reference(np.zeros((2, 3)), np.zeros((2, 3))) is None


def test_supercell_offsets():
    c = cif.Cell(3.0, 4.0, 5.0)
    offs = cif.supercell_offsets(c, 2, 1, 1)
    assert offs.shape == (2, 3)
    assert offs[0] == pytest.approx([0, 0, 0])
    assert offs[1] == pytest.approx([3.0, 0, 0])


# --------------------------------------------------------------- io pipeline
def test_read_structures_keeps_the_crystallography(tmp_path):
    from molom.core import io
    path = tmp_path / "nacl.cif"
    path.write_text(NACL_CIF, encoding="utf-8")
    records = io.read_structures(str(path))
    assert len(records) == 1
    atoms, meta = records[0]
    assert len(atoms) == 39               # the drawn cell, boundary completed
    assert meta["source"] == "cif"
    assert meta["cell"]["a"] == pytest.approx(5.6402)
    assert meta["spacegroup"] == "F m -3 m"
    assert len(meta["symops"]) == 4
    assert meta["asym_symbols"] == ["Na", "Cl"]


def test_a_periodic_framework_is_not_unwrapped():
    """MOF-5 regression: a framework's bonded network percolates through the
    boundary, so walking it to make it 'contiguous' marches the structure out
    across cells forever. Such a component must be left plainly wrapped."""
    cell = cif.Cell(10.0, 10.0, 10.0)
    # A chain of atoms 2.0 A apart that closes on itself THROUGH the face.
    symbols = ["C"] * 5
    frac = np.array([[k * 0.2, 0.5, 0.5] for k in range(5)])
    out = cif.unwrap_molecules(symbols, frac, cell)
    assert out == pytest.approx(frac), "a percolating chain must stay wrapped"


def test_a_finite_molecule_is_still_unwrapped():
    """The other half of the same decision: a fragment that does NOT close on
    itself is still walked back together."""
    cell = cif.Cell(10.0, 10.0, 10.0)
    symbols = ["O", "H"]
    frac = np.array([[0.5, 0.5, 0.95], [0.5, 0.5, 0.05]])
    out = cif.unwrap_molecules(symbols, frac, cell)
    cart = out @ cell.matrix()
    assert np.linalg.norm(cart[0] - cart[1]) == pytest.approx(1.0)
