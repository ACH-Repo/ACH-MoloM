"""Structure model, measurements, and the editing core."""

import numpy as np
import pytest

from molom.core import bonding, edits, measure
from molom.core.structure import Structure

WATER = [("O", 0.0, 0.0, 0.117), ("H", 0.0, 0.757, -0.469),
         ("H", 0.0, -0.757, -0.469)]


def _water():
    s = Structure.from_atoms(WATER, name="water")
    bonding.perceive_structure_bonds(s)
    return s


# ------------------------------------------------------------------ structure

def test_from_atoms_metadata_charge():
    s = Structure.from_atoms(WATER, metadata={"name": "w", "charge": -1,
                                              "multiplicity": 2})
    assert s.name == "w"
    assert s.charge == -1 and s.multiplicity == 2


def test_frames_and_set_frame():
    f1 = (WATER, None)
    f2 = ([("O", 0, 0, 0.2), ("H", 0, 0.85, -0.5), ("H", 0, -0.85, -0.5)], None)
    s = Structure.from_frames([f1, f2])
    assert s.n_frames == 2
    assert s.set_frame(5) == 1          # clamped
    assert s.coords[0, 2] == 0.2
    assert s.set_frame(-3) == 0
    assert s.coords[0, 2] == 0.117


def test_bounding_radius_positive():
    s = _water()
    assert s.bounding_radius() > 1.0    # includes VdW shell


# ---------------------------------------------------------------- measurements

def test_distance():
    assert measure.distance([0, 0, 0], [3, 4, 0]) == pytest.approx(5.0)


def test_angle_water():
    s = _water()
    a = measure.angle(s.coords[1], s.coords[0], s.coords[2])
    assert a == pytest.approx(104.5, abs=1.0)


def test_dihedral_signed():
    # +/-90 degree probes around a z-axis central bond (standard atan2
    # convention: p4 at +y is +90 for this arrangement).
    p1, p2, p3 = [1.0, 0, 0], [0, 0, 0], [0, 0, 1.0]
    assert measure.dihedral(p1, p2, p3, [0, 1.0, 1.0]) == pytest.approx(90.0)
    assert measure.dihedral(p1, p2, p3, [0, -1.0, 1.0]) == pytest.approx(-90.0)
    assert measure.dihedral(p1, p2, p3, [-1.0, 0, 1.0]) == pytest.approx(180.0)
    assert measure.dihedral(p1, p2, p3, [1.0, 0, 1.0]) == pytest.approx(0.0)


def test_describe_selection_forms():
    s = _water()
    assert "O0" in measure.describe_selection(s, [0])
    assert "d(O0-H1)" in measure.describe_selection(s, [0, 1])
    assert "angle(" in measure.describe_selection(s, [1, 0, 2])
    s2 = Structure.from_atoms([("C", 0, 0, 0), ("C", 1.5, 0, 0),
                               ("C", 2.0, 1.4, 0), ("C", 3.5, 1.4, 0)])
    assert "dihedral(" in measure.describe_selection(s2, [0, 1, 2, 3])


# --------------------------------------------------------------------- edits

def test_add_atom_bonds_and_frames():
    s = _water()
    pos = edits.suggested_position(s, bond_to=0, symbol="H")
    edits.add_atom(s, "H", pos, bond_to=0)
    assert s.n_atoms == 4
    assert s.find_bond(0, 3) is not None
    # distance = covalent sum (O 0.63 + H 0.32)
    assert measure.distance(s.coords[0], s.coords[3]) == pytest.approx(0.95, abs=1e-6)


def test_add_atom_multiframe():
    s = Structure.from_frames([(WATER, None), (WATER, None)])
    edits.add_atom(s, "H", (5, 5, 5))
    assert all(f.shape == (4, 3) for f in s.frames)


def test_delete_reindexes_bonds():
    s = _water()
    edits.delete_atoms(s, [1])
    assert s.n_atoms == 2
    assert s.symbols == ["O", "H"]
    assert s.bonds == [(0, 1, 1)]       # old (0,2) reindexed


def test_delete_multiple_and_out_of_range():
    s = _water()
    edits.delete_atoms(s, [0, 2, 99])
    assert s.symbols == ["H"]
    assert s.bonds == []


def test_set_element_changes_symbols():
    s = _water()
    edits.set_element(s, [1, 2], "F")
    assert s.symbols == ["O", "F", "F"]


def test_set_element_unknown_raises():
    s = _water()
    with pytest.raises(ValueError):
        edits.set_element(s, [0], "Zz")


def test_bond_add_remove_cycle():
    s = Structure.from_atoms([("C", 0, 0, 0), ("C", 1.5, 0, 0)])
    assert edits.cycle_bond_order(s, 0, 1) == 1
    assert edits.cycle_bond_order(s, 0, 1) == 2
    assert edits.cycle_bond_order(s, 0, 1) == 3
    assert edits.cycle_bond_order(s, 0, 1) == 0      # wraps to none
    assert s.bonds == []
    edits.add_bond(s, 1, 0, order=2)                 # stored sorted
    assert s.bonds == [(0, 1, 2)]
    edits.remove_bond(s, 0, 1)
    assert s.bonds == []
    with pytest.raises(ValueError):
        edits.add_bond(s, 0, 0)
    with pytest.raises(ValueError):
        edits.add_bond(s, 0, 5)


def test_suggested_position_away_from_neighbors():
    s = _water()
    pos = edits.suggested_position(s, bond_to=0, symbol="H")
    # New H should sit on the opposite side of O from the two existing H
    # (both have negative z; the suggestion should have positive z).
    assert pos[2] > s.coords[0][2]
