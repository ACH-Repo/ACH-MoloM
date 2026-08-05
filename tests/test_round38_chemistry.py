"""Round 38: the chemistry a distance rule cannot have.

Christian's diagnosis, which drives all three parts: MOF-5 is infinite through
its bonds, benzoic acid is fine on distance alone, and HpPyBz breaks because
its geometry is not physical — so no combination of "how far apart" and "what
is connected to what" is robust. The three mechanisms are tested separately
because they fix three DIFFERENT files:

* bond KINDS — where a molecule ends (MOF-5, rock salt);
* valence SANITY — which bonds cannot exist (HpPyBz);
* OCCUPANCY — which atoms are not simultaneously there (MIL-53-lp).
"""

import numpy as np
import pytest

from molom.core import bonding, cif
from molom.core.structure import Structure


# =================================================================== kinds
def test_a_metal_to_ligand_bond_is_coordinative():
    assert bonding.bond_kind("Zn", "O") == bonding.COORDINATION
    assert bonding.bond_kind("O", "Zn") == bonding.COORDINATION
    assert bonding.bond_kind("Al", "O") == bonding.COORDINATION
    assert bonding.bond_kind("Na", "Cl") == bonding.COORDINATION


def test_organic_bonds_are_covalent():
    for a, b in (("C", "C"), ("C", "O"), ("C", "H"), ("N", "O"), ("S", "O")):
        assert bonding.bond_kind(a, b) == bonding.COVALENT


def test_metal_to_metal_stays_covalent():
    """A Re-Re quadruple bond is a real bond, and more practically an SBU (a
    Zn4O cluster, a paddlewheel) is ONE framework node — dissecting it into
    loose atoms would be worse than not cutting at all."""
    assert bonding.bond_kind("Re", "Re") == bonding.COVALENT
    assert bonding.bond_kind("Zn", "Zn") == bonding.COVALENT


def test_covalent_bonds_filters_the_linker_off_its_metal():
    symbols = ["Zn", "O", "C", "O", "Zn"]
    bonds = [(0, 1, 1), (1, 2, 1), (2, 3, 1), (3, 4, 1)]
    kept = bonding.covalent_bonds(symbols, bonds)
    assert kept == [(1, 2, 1), (2, 3, 1)]      # the carboxylate, on its own


# ========================================================== valence sanity
def _line(symbols, spacing):
    return Structure.from_atoms(
        [(s, i * spacing, 0.0, 0.0) for i, s in enumerate(symbols)])


def test_an_impossibly_short_contact_is_not_a_bond():
    """HpPyBz_th.cif's 0.75 A C...C. ASE reads the same clash, so the file is
    broken and MoloM cannot invent a structure — but it can refuse to draw a
    bond that no chemistry allows."""
    s = _line(["C", "C"], 0.75)
    assert bonding.perceive_bonds(s.symbols, s.coords) == []
    report = {}
    bonding.perceive_bonds(s.symbols, s.coords, report=report)
    assert report["dropped_bonds"][0][3] == "impossibly short"


def test_a_real_triple_bond_survives():
    """The floor has to sit BELOW every real bond: C#C is 1.20 A, and an
    X-ray riding C-H is 0.93."""
    assert len(bonding.perceive_bonds(*_pair("C", "C", 1.20))) == 1
    assert len(bonding.perceive_bonds(*_pair("C", "N", 1.16))) == 1
    assert len(bonding.perceive_bonds(*_pair("C", "H", 0.93))) == 1
    assert len(bonding.perceive_bonds(*_pair("H", "F", 0.92))) == 1


def _pair(a, b, d):
    s = Structure.from_atoms([(a, 0.0, 0.0, 0.0), (b, d, 0.0, 0.0)])
    return s.symbols, s.coords


def test_a_carbon_cannot_have_six_neighbours():
    """A carbon with nine neighbours is not a carbon with nine neighbours; it
    is a file with a problem. The LONGEST bonds go first, so the four that
    survive are the ones a real structure would have."""
    coords = [("C", 0.0, 0.0, 0.0)]
    for k, d in enumerate((1.4, 1.45, 1.5, 1.55, 1.75, 1.8)):
        angle = k * np.pi / 3.0
        coords.append(("C", d * np.cos(angle), d * np.sin(angle), 0.0))
    s = Structure.from_atoms(coords)
    bonds = bonding.perceive_bonds(s.symbols, s.coords)
    degree = sum(1 for i, j, _o in bonds if 0 in (i, j))
    assert degree == 4
    kept = {j for i, j, _o in bonds if i == 0}
    assert kept == {1, 2, 3, 4}                 # the four SHORTEST


def test_a_metal_keeps_all_of_its_donors():
    """Coordination bonds are exempt: an eight-coordinate metal is ordinary,
    and capping it would dismantle exactly the structures this is for."""
    coords = [("Zn", 0.0, 0.0, 0.0)]
    for dx, dy, dz in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0),
                       (0, 0, 1), (0, 0, -1)):
        coords.append(("O", 2.0 * dx, 2.0 * dy, 2.0 * dz))
    s = Structure.from_atoms(coords)
    bonds = bonding.perceive_bonds(s.symbols, s.coords)
    assert sum(1 for i, j, _o in bonds if 0 in (i, j)) == 6


def test_a_bridging_chloride_keeps_its_metals():
    """The cap is on COVALENT bonds only. Cl bridging three metals is real
    chemistry; Cl with three bonds to carbon is not."""
    s = Structure.from_atoms([("Cl", 0.0, 0.0, 0.0),
                              ("Zn", 2.2, 0.0, 0.0), ("Zn", -2.2, 0.0, 0.0),
                              ("Zn", 0.0, 2.2, 0.0)])
    bonds = bonding.perceive_bonds(s.symbols, s.coords)
    assert sum(1 for i, j, _o in bonds if 0 in (i, j)) == 3


def test_sanity_can_be_switched_off():
    s = _line(["C", "C"], 0.75)
    assert len(bonding.perceive_bonds(s.symbols, s.coords, sanity=False)) == 1


# ================================================================ hierarchy
def _chain_cell():
    """A cell whose contents percolate ONLY through metal-oxygen bonds:
    O-Zn-O-Zn along a, with a carboxylate-ish carbon hanging off each O.
    The full graph is infinite; the covalent one is not."""
    cell = cif.Cell(4.0, 12.0, 12.0)
    symbols = ["Zn", "O", "C", "O", "C"]
    frac = np.array([
        [0.0, 0.5, 0.5],          # Zn
        [0.5, 0.5, 0.5],          # O bridging to the next cell's Zn
        [0.5, 0.62, 0.5],         # C on that O
        [0.0, 0.35, 0.5],         # O on the Zn, pointing the other way
        [0.0, 0.235, 0.5],        # C on that O
    ])
    return cell, symbols, frac


def test_a_framework_is_infinite_until_the_coordination_bonds_are_cut():
    cell, symbols, frac = _chain_cell()
    raw = cif.fragment_info(symbols, frac, cell, split_coordination=False)
    assert len(raw) == 1 and raw[0][1] is True          # one infinite chain
    cut = cif.fragment_info(symbols, frac, cell)
    assert len(cut) > 1
    assert not any(periodic for _g, periodic in cut)    # every piece finite
    assert sorted(len(g) for g, _p in cut) == [1, 2, 2]  # Zn, and two C-O


def test_a_finite_metal_complex_is_never_dissected():
    """Cut where it is INFINITE, nowhere else. Ferrocene is already a
    molecule; splitting it would strand the rings from their iron when the
    boundary completes them."""
    cell = cif.Cell(20.0, 20.0, 20.0)
    symbols = ["Fe", "C", "C"]
    frac = np.array([[0.5, 0.5, 0.5], [0.5, 0.5, 0.585],
                     [0.5, 0.5, 0.415]])
    info = cif.fragment_info(symbols, frac, cell)
    assert len(info) == 1
    assert sorted(info[0][0]) == [0, 1, 2]


def test_a_covalent_polymer_stays_periodic():
    """Cutting coordination bonds cannot save a chain that is covalently
    infinite — graphite, a COF, polyethylene — and it must not pretend to."""
    cell = cif.Cell(2.6, 12.0, 12.0)
    symbols = ["C", "C"]
    frac = np.array([[0.0, 0.5, 0.5], [0.5, 0.5, 0.5]])
    info = cif.fragment_info(symbols, frac, cell)
    assert all(periodic for _g, periodic in info)


def test_a_spurious_contact_no_longer_fuses_two_molecules():
    """The HpPyBz failure mode in miniature: one impossible contact joins two
    separate molecules, the join percolates, and the whole cell then reads as
    a framework that cannot be completed at the boundary."""
    cell = cif.Cell(8.0, 8.0, 8.0)
    symbols = ["C", "C", "C", "C"]
    # Two C-C molecules 1.44 A long, with an impossible 0.6 A gap BETWEEN
    # them: 0.8/2.24 A and 2.84/4.28 A along x.
    frac = np.array([[0.100, 0.5, 0.5], [0.280, 0.5, 0.5],   # molecule 1
                     [0.355, 0.5, 0.5], [0.535, 0.5, 0.5]])  # molecule 2
    info = cif.fragment_info(symbols, frac, cell)
    assert len(info) == 2                       # still two molecules
    assert all(len(g) == 2 for g, _p in info)


# ================================================================ occupancy
DISORDERED = """
data_test
_cell_length_a 10.0
_cell_length_b 10.0
_cell_length_c 10.0
_cell_angle_alpha 90.0
_cell_angle_beta 90.0
_cell_angle_gamma 90.0
loop_
_symmetry_equiv_pos_as_xyz
'x, y, z'
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
_atom_site_disorder_group
C1 C 0.10 0.10 0.10 1.00 .
C2A C 0.50 0.50 0.50 0.70 1
C2B C 0.54 0.50 0.50 0.30 2
O1 O 0.80 0.80 0.80 0.45 .
"""


def test_occupancies_and_disorder_groups_are_read():
    data = cif.parse_cif(DISORDERED)
    assert data.occupancy == [1.0, 0.7, 0.3, 0.45]
    assert data.disorder_groups == ["", "1", "2", ""]
    assert data.is_disordered


def test_the_minor_alternative_is_dropped():
    data = cif.parse_cif(DISORDERED)
    report = {}
    symbols, coords = cif.expand(data, boundary=False, report=report)
    assert len(symbols) == 3                     # C2B went
    assert report["disorder"]["dropped"] == 1
    assert report["disorder"]["by_group"] == 1


def test_a_lone_partial_site_is_kept():
    """It overlaps nothing, so it is a real partially occupied site — a
    half-occupied solvent position is not an "alternative" to anything and
    deleting it would be inventing chemistry."""
    data = cif.parse_cif(DISORDERED)
    symbols, coords = cif.expand(data, boundary=False)
    assert "O" in symbols


def test_the_major_policy_drops_everything_under_half():
    data = cif.parse_cif(DISORDERED)
    report = {}
    symbols, _c = cif.expand(data, boundary=False, disorder=cif.POLICY_MAJOR,
                             report=report)
    # C1 (ordered) and C2A (the 70% major alternative) survive; the 45%
    # oxygen and the 30% minor alternative do not.
    assert symbols == ["C", "C"]
    assert report["disorder"]["by_threshold"] == 1


def test_the_all_policy_restores_the_raw_file():
    data = cif.parse_cif(DISORDERED)
    symbols, _c = cif.expand(data, boundary=False, disorder=cif.POLICY_ALL)
    assert len(symbols) == 4


def test_overlap_resolution_works_without_any_disorder_tags():
    """Most files carry occupancies and no grouping at all, and the
    alternatives are routinely SYMMETRY IMAGES of one another rather than
    separate rows — which is why this runs on the expanded atoms."""
    cell = cif.Cell(10.0, 10.0, 10.0)
    symbols = ["C", "C", "C"]
    frac = np.array([[0.10, 0.10, 0.10],      # alone, full
                     [0.50, 0.50, 0.50],      # two alternatives 0.4 A apart
                     [0.54, 0.50, 0.50]])
    keep, report = cif.resolve_disorder(symbols, frac, cell,
                                        [1.0, 0.6, 0.4])
    assert list(keep) == [True, True, False]
    assert report["by_overlap"] == 1


def test_a_full_atom_is_never_dropped_as_an_alternative():
    cell = cif.Cell(10.0, 10.0, 10.0)
    keep, _r = cif.resolve_disorder(["C", "C"], np.array(
        [[0.5, 0.5, 0.5], [0.54, 0.5, 0.5]]), cell, [1.0, 1.0])
    assert list(keep) == [True, True]


def test_an_ordered_file_is_untouched():
    cell = cif.Cell(10.0, 10.0, 10.0)
    frac = np.random.RandomState(0).rand(20, 3)
    keep, report = cif.resolve_disorder(["C"] * 20, frac, cell, [1.0] * 20)
    assert keep.all() and report["dropped"] == 0


# =============================================================== reporting
def test_a_dropped_bond_says_why():
    s = _line(["C", "C"], 0.75)
    report = {}
    bonding.perceive_bonds(s.symbols, s.coords, report=report)
    i, j, d, why = report["dropped_bonds"][0]
    assert (i, j) == (0, 1)
    assert d == pytest.approx(0.75)
    assert "short" in why


# =================================================================== UI
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def win():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.app import MainWindow
    QApplication.instance() or QApplication([])
    w = MainWindow()
    w.show()
    return w


def test_the_import_says_what_it_refused(win, tmp_path):
    path = tmp_path / "disordered.cif"
    path.write_text(DISORDERED, encoding="utf-8")
    win.open_path(str(path))
    obj = win.scene.objects[-1]
    note = win.chemistry_note(obj.structure)
    assert note and "disorder" in note


def test_the_disorder_policy_round_trips_through_settings(win):
    from molom.core import cif as cif_module
    from molom.ui.dialogs import SettingsDialog
    dlg = SettingsDialog(win, 1.0, True,
                         disorder_policy=cif_module.POLICY_MAJOR)
    assert dlg.disorder_policy() == cif_module.POLICY_MAJOR
    dlg.close()
    assert win.disorder_policy in cif_module.DISORDER_POLICIES


def test_the_policy_reaches_the_reader(win, tmp_path):
    """Settings picks it, the import obeys it — the two ends of the wire."""
    from molom.core import cif as cif_module
    path = tmp_path / "d.cif"
    path.write_text(DISORDERED, encoding="utf-8")
    win.disorder_policy = cif_module.POLICY_ALL
    win.open_path(str(path))
    assert win.scene.objects[-1].structure.n_atoms == 4
    win.disorder_policy = cif_module.POLICY_MAJOR
    win.open_path(str(path))
    assert win.scene.objects[-1].structure.n_atoms == 2
