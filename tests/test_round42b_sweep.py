"""Round 42b: the faults the 37-file VESTA sweep turned up.

Christian exported every test CIF from VESTA down each cell axis and compared
them against MoloM. Four defects came out of it, and none of them is tested
with a vendored file: his set is largely CCDC data, which may not be
redistributed. The rules are unit-testable in their own right, which is a
better test anyway -- each one states the principle rather than a number.

The sweep also produced its own lesson about METHOD: the first pass framed
each render on the cell box, which cropped exactly the strays that were the
bug. Frame on everything (F / `fit_view`) when hunting for atoms that should
not be there.
"""

import numpy as np
import pytest

from molom.core import cif, edits
from molom.core.structure import Structure

CELL = cif.Cell(10.0, 10.0, 10.0)


# ------------------------------------------------- fragments outside the cell
def test_a_fragment_with_nothing_inside_the_cell_is_dropped():
    """Both reference viewers state this rule outright: Mercury includes a
    molecule when ANY of its atoms is in the cell, VESTA searches outward from
    atoms that are inside. A copy with nothing inside is not in the picture.

    Christian saw these as triazoles floating a cell away from Cu_trz_tet and
    as magnesiums above H2Mg2O8P2's box.
    """
    symbols = ["C", "C", "C", "C"]
    frac = np.array([[0.5, 0.5, 0.5], [0.62, 0.5, 0.5],     # inside: kept
                     [2.5, 0.5, 0.5], [2.62, 0.5, 0.5]])    # a cell away: not
    keep = cif._reaches_into_cell(symbols, frac, CELL.matrix(), n_content=2)
    assert list(keep) == [True, True, False, False]


def test_the_cell_content_is_never_dropped():
    """Only COPIES are eligible. Z, the crystal page's count and anything
    counting formula units have to survive this untouched."""
    symbols = ["C", "C"]
    frac = np.array([[5.0, 5.0, 5.0], [5.12, 5.0, 5.0]])    # absurd, but base
    keep = cif._reaches_into_cell(symbols, frac, CELL.matrix(), n_content=2)
    assert keep.all()


def test_an_atom_bonded_to_the_inside_is_kept_though_it_is_outside():
    """Round 35's bonded shell is exactly this: atoms beyond the wall that
    belong to something within it. They share a fragment, so they stay."""
    symbols = ["C", "C"]
    frac = np.array([[0.98, 0.5, 0.5], [1.12, 0.5, 0.5]])   # 1.4 A apart
    keep = cif._reaches_into_cell(symbols, frac, CELL.matrix(), n_content=1)
    assert keep.all()


# --------------------------------------------------- the cell box on deletion
def _crystal():
    coords = np.array([[1.0, 1.0, 1.0], [2.0, 1.0, 1.0], [1.0, 2.0, 1.0],
                       [1.0, 1.0, 2.0], [3.0, 3.0, 3.0], [4.0, 3.0, 3.0]])
    s = Structure(["C"] * 6, coords)
    s.metadata["cell"] = CELL.to_dict()
    return s


def test_deleting_atoms_does_not_move_the_unit_cell_box():
    """The box has no transform of its own -- it is carried by a Kabsch fit
    from reference atoms held as INDICES (round 19). Deleting an atom
    renumbers the rest, so those indices quietly came to mean different atoms
    and the box flipped. The out-of-range guard never fired: the indices
    stayed valid, they just stopped meaning what they said."""
    pytest.importorskip("PySide6")
    from molom.ui.viewport import set_cell_reference, cell_corners_world

    class Obj(object):
        def __init__(self, structure):
            self.structure = structure

    s = _crystal()
    set_cell_reference(s)
    obj = Obj(s)
    before = np.asarray(cell_corners_world(obj))
    edits.delete_atoms(s, [1])                 # from the MIDDLE
    after = np.asarray(cell_corners_world(obj))
    assert np.allclose(before, after, atol=1e-9)


def test_a_deleted_reference_atom_is_removed_from_the_reference():
    s = _crystal()
    s.metadata["cell_ref_idx"] = [0, 1, 2, 3]
    s.metadata["cell_ref_xyz"] = [list(p) for p in s.coords[:4]]
    edits.delete_atoms(s, [1])
    assert s.metadata["cell_ref_idx"] == [0, 1, 2]      # 2,3 shifted down
    assert len(s.metadata["cell_ref_xyz"]) == 3


def test_the_reference_is_cleared_rather_than_left_under_determined():
    """Under three points a rigid fit is not determined; falling back to the
    stored frame is right, inventing a rotation from two points is not."""
    s = _crystal()
    s.metadata["cell_ref_idx"] = [0, 1, 2]
    s.metadata["cell_ref_xyz"] = [list(p) for p in s.coords[:3]]
    edits.delete_atoms(s, [0, 1])
    assert "cell_ref_idx" not in s.metadata


# ------------------------------------------------------------------- disorder
DISORDERED = """data_x
_cell_length_a 10.0
_cell_length_b 10.0
_cell_length_c 10.0
_symmetry_space_group_name_H-M 'P 1'
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
C1 C 0.500 0.500 0.500 {occ1}
C2 C 0.520 0.500 0.500 {occ2}
O1 O 0.100 0.100 0.100 {occ3}
"""


def test_a_wholly_disordered_structure_is_drawn_whole():
    """No site fully occupied means no ordered skeleton to resolve against:
    nothing is dominant, and picking greedily by occupancy gives a chimera
    obeying neither the chemistry nor the space group. `2240539.cif` -- a
    plastic crystal smeared over 192 operations of Fm-3m -- came out as 184
    atoms of 280 and looked it. The honest picture of a smear is the smear.
    """
    data = cif.parse_cif(DISORDERED.format(occ1=0.43, occ2=0.43, occ3=0.21))
    report = {}
    symbols, _coords = cif.expand(data, boundary=False, report=report)
    assert len(symbols) == 3
    assert report["disorder"]["wholly_disordered"] is True


def test_an_ordered_structure_still_resolves_its_overlaps():
    """The counterpart: with a fully occupied site present there IS a skeleton,
    and two alternatives 0.2 A apart are still not both real."""
    data = cif.parse_cif(DISORDERED.format(occ1=0.6, occ2=0.4, occ3=1.0))
    report = {}
    symbols, _coords = cif.expand(data, boundary=False, report=report)
    assert len(symbols) == 2
    assert report["disorder"]["dropped"] == 1


def test_a_symmetry_orbit_is_never_split():
    """Two overlapping atoms from the SAME site are images of one another
    under the space group. Keeping some and dropping others leaves a structure
    that no longer obeys its own symmetry."""
    symbols = ["C", "C"]
    frac = np.array([[0.5, 0.5, 0.5], [0.52, 0.5, 0.5]])
    keep, _report = cif.resolve_disorder(
        symbols, frac, CELL, [0.5, 0.5], sites=[0, 0])
    assert keep.all(), "images of one site must be kept or dropped together"
    keep2, _r2 = cif.resolve_disorder(
        symbols, frac, CELL, [0.6, 0.4], sites=[0, 1])
    assert not keep2.all(), "different sites are genuine alternatives"
