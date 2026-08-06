"""Round 43d: unit-cell edits that persist, with the symmetry kept honest.

Christian: "I want to be able to change the asymmetric unit and have the
change repeated while the space group is kept constant. If the full cell is
edited, then the space group has to be reevaluated or set to triclinic because
the symmetry has been broken."

Two mechanisms, and which one applies is decided by whether a SYMMETRY
MODIFIER owns the expansion:

  * with one, the base IS the asymmetric unit, every edit is repeated by the
    operators, and the space group is untouched;
  * without one, the base is the full cell, so an edit really does break the
    symmetry and the operators have to be re-derived from the coordinates —
    `spacegroups.from_structure`, which is the first thing in this module that
    reads symmetry off ATOMS rather than off a name.
"""

import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from molom.core import cif, modifiers as mods
from molom.core import spacegroups as sg
from molom.core.scene import Scene
from molom.core.structure import Structure


# A real P2_1/c-shaped test case built by hand: four general positions.
PBCA = """
data_t
_cell_length_a 8.0
_cell_length_b 9.0
_cell_length_c 10.0
_cell_angle_alpha 90.0
_cell_angle_beta 90.0
_cell_angle_gamma 90.0
_symmetry_space_group_name_H-M 'P 21/c'
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
C1 C 0.120 0.230 0.310
O1 O 0.240 0.410 0.180
N1 N 0.330 0.150 0.470
"""


def _data():
    return cif.parse_cif(PBCA)


def _asym_object():
    d = _data()
    s = Structure(list(d.symbols), [np.asarray(d.frac) @ d.cell.matrix()])
    s.metadata["cell"] = d.cell.to_dict()
    s.metadata["spacegroup"] = d.spacegroup
    s.metadata["symops"] = [o.as_xyz() for o in d.symops]
    obj = Scene().add(s)
    obj.modifiers.append(mods.SymmetryModifier(
        cell=d.cell.to_dict(), symops=[o.as_xyz() for o in d.symops]))
    return obj, d


# ------------------------------------------- the file resolves to real ops
def test_the_fixture_really_has_symmetry():
    d = _data()
    assert len(d.symops) == 4, "P2_1/c should resolve to four operators"


# ------------------------------------ editing the asymmetric unit repeats
def test_moving_one_asymmetric_atom_moves_one_image_per_operator():
    obj, d = _asym_object()
    s = obj.structure
    before = obj.evaluated()[1].copy()
    assert len(before) == s.n_atoms * len(d.symops)

    s.frames[0][0] += np.array([0.4, 0.0, 0.0])
    s.set_frame(0)
    after = obj.evaluated()[1]

    assert len(after) == len(before), "the cell must not gain or lose atoms"
    moved = int(np.sum(np.linalg.norm(after - before, axis=1) > 1e-6))
    assert moved == len(d.symops)


def test_the_space_group_is_untouched_by_an_asymmetric_edit():
    """The whole point of editing this way: the symmetry is an INPUT."""
    obj, _d = _asym_object()
    s = obj.structure
    was = s.metadata["spacegroup"]
    ops = list(s.metadata["symops"])
    s.frames[0][1] += np.array([0.0, 0.3, 0.2])
    s.set_frame(0)
    obj.evaluated()
    assert s.metadata["spacegroup"] == was
    assert s.metadata["symops"] == ops


# --------------------------------------- reading symmetry off coordinates
def test_symmetry_is_derived_from_the_atoms():
    d = _data()
    symbols, coords = cif.expand(d, boundary=False)
    frac = np.asarray(coords) @ np.linalg.inv(d.cell.matrix())
    found = sg.from_structure(d.cell, list(symbols), frac)
    assert found is not None
    assert len(found.xyz) == len(d.symops)
    assert found.source == sg.SOURCE_DERIVED


def test_breaking_the_symmetry_is_detected():
    d = _data()
    symbols, coords = cif.expand(d, boundary=False)
    coords = np.asarray(coords, dtype=float).copy()
    coords[2] += np.array([0.37, 0.21, 0.13])      # one atom off its orbit
    frac = coords @ np.linalg.inv(d.cell.matrix())
    found = sg.from_structure(d.cell, list(symbols), frac)
    assert found is None or len(found.xyz) < len(d.symops)


def test_boundary_copies_do_not_defeat_the_search():
    """The hazard that made this return None on every real file: a drawn
    crystal carries boundary copies, which wrap onto atoms already present.
    spglib refuses a cell listing the same site twice."""
    d = _data()
    symbols, coords = cif.expand(d, boundary=True)
    frac = np.asarray(coords) @ np.linalg.inv(d.cell.matrix())
    keep = sg.content_subset(list(symbols), frac)
    plain, _ = cif.expand(d, boundary=False)
    assert len(keep) == len(plain)
    found = sg.from_structure(d.cell, list(symbols), frac)
    assert found is not None and len(found.xyz) == len(d.symops)


def test_content_subset_survives_a_bucket_boundary():
    """A single rounded key splits two copies that straddle a bucket edge —
    measured as 225 sites on 7712836 where there are 222, which is enough for
    spglib to refuse the cell. The neighbour probe is what fixes it."""
    frac = np.array([[0.0, 0.0, 0.0],
                     [1.0, 1.0, 1.0],          # the same site, wrapped
                     [0.99999, 0.0, 0.0],      # and again, from below
                     [0.5, 0.5, 0.5]])
    keep = sg.content_subset(["C"] * 4, frac)
    assert len(keep) == 2


def test_different_elements_on_one_position_are_not_merged():
    """A shared site (round 42) is several species at one position, and
    collapsing them would silently delete a component of a solid solution."""
    frac = np.array([[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]])
    assert len(sg.content_subset(["Nb", "Ti"], frac)) == 2


# ------------------------------------------------- the app-level contract
@pytest.fixture
def win():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.app import MainWindow

    QApplication.instance() or QApplication([])
    w = MainWindow()
    yield w
    w.close()


def _install(win):
    d = _data()
    symbols, coords = cif.expand(d, boundary=False)
    s = Structure(list(symbols), [np.asarray(coords, dtype=float)])
    s.metadata["cell"] = d.cell.to_dict()
    s.metadata["spacegroup"] = d.spacegroup
    s.metadata["symops"] = [o.as_xyz() for o in d.symops]
    obj = win.scene.add(s)
    win.active_id = obj.id
    return obj


def test_an_untouched_cell_is_not_re_derived(win):
    """A control that fires when nothing changed is noise — and it would
    rewrite the file's own setting with the database's spelling."""
    obj = _install(win)
    assert win.reevaluate_symmetry(obj, announce=False) is None


def test_editing_the_full_cell_drops_the_symmetry(win):
    obj = _install(win)
    s = obj.structure
    s.frames[0][2] += np.array([0.41, 0.23, 0.17])
    s.set_frame(0)
    changed = win.reevaluate_symmetry(obj, announce=False)
    assert changed is not None
    assert len(s.metadata["symops"]) < 4
    assert s.metadata["symmetry_source"] == sg.SOURCE_DERIVED
    assert "re-derived" in s.metadata.get("symmetry_note", "")


def test_a_symmetry_modifier_protects_the_space_group(win):
    """With the base as the asymmetric unit the operators still hold, so
    re-deriving would collapse a perfectly good structure to P1."""
    obj = _install(win)
    obj.modifiers.append(mods.SymmetryModifier(
        cell=obj.structure.metadata["cell"],
        symops=list(obj.structure.metadata["symops"])))
    obj.structure.frames[0][0] += np.array([0.4, 0.1, 0.0])
    obj.structure.set_frame(0)
    assert win.reevaluate_symmetry(obj, announce=False) is None
    assert len(obj.structure.metadata["symops"]) == 4


def test_enabling_symmetry_editing_reduces_the_base(win):
    obj = _install(win)
    full = obj.structure.n_atoms
    drawn = len(obj.evaluated()[0])
    note = win.enable_symmetry_editing(obj)
    assert note
    assert obj.structure.n_atoms < full          # base is the asym unit now
    assert len(obj.evaluated()[0]) == drawn      # the picture is unchanged
    assert any(getattr(m, "kind", "") == "symmetry" for m in obj.modifiers)
