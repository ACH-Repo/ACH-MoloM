"""Round 43e: asymmetric-unit edits that really persist, plus coplanarity.

Christian, after trying round 43d: "Editing asymmetric units does not work at
all... When I change one of the Zn in the asymmetric unit to Co I am told that
the re-derived space group is P1, which is obviously incorrect."

He was right twice over.

  * The re-derivation fired while the base WAS the asymmetric unit. Round 43d
    only checked for a `SymmetryModifier`, and the ❖ page's "Asymmetric unit
    only" radio — the route he took — rebuilds the base and adds no modifier.
    spglib then answered P1 perfectly correctly about 22 atoms alone in a box,
    and destroyed the file's real group.
  * Nothing wrote the edit back into `asym_symbols`, so the next rebuild
    regenerated from the file's values: "the Co switches back to Zn".

And the chemistry says the same: changing one Zn to Co in the asymmetric unit
changes ALL of its images together, so the operators still map the structure
onto itself and Pbca is untouched. Symmetry may only be re-derived after an
edit to the FULL CELL.
"""

import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from molom.core import cif, coplanar, edits
from molom.core import modifiers as mods
from molom.core.structure import Structure

PBCA = """
data_t
_cell_length_a 12.0
_cell_length_b 13.0
_cell_length_c 14.0
_cell_angle_alpha 90.0
_cell_angle_beta 90.0
_cell_angle_gamma 90.0
_symmetry_space_group_name_H-M 'P b c a'
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
Zn1 Zn 0.113 0.227 0.319
N1  N  0.241 0.408 0.176
C1  C  0.332 0.151 0.472
"""


@pytest.fixture
def win():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.app import MainWindow

    QApplication.instance() or QApplication([])
    w = MainWindow()
    yield w
    w.close()


def _install(win, path=None, tmp_path=None):
    """A Pbca crystal in the app, exactly as an import leaves it."""
    data = cif.parse_cif(PBCA)
    symbols, coords = cif.expand(data, boundary=False)
    s = Structure(list(symbols), [np.asarray(coords, dtype=float)])
    s.metadata.update({
        "cell": data.cell.to_dict(),
        "spacegroup": data.spacegroup,
        "symops": [o.as_xyz() for o in data.symops],
        "asym_symbols": list(data.symbols),
        "asym_frac": [[float(v) for v in row] for row in data.frac],
        "asym_occupancy": [1.0] * data.n_sites,
        "cell_view": "cell",
    })
    obj = win.scene.add(s)
    win.active_id = obj.id
    from molom.ui.viewport import set_cell_reference
    set_cell_reference(s)
    return obj


def test_the_fixture_is_really_pbca():
    data = cif.parse_cif(PBCA)
    assert len(data.symops) == 8


# ------------------------------------------- the asymmetric unit is detected
def test_the_radio_route_counts_as_the_asymmetric_unit(win):
    """Round 43d only recognised the modifier, which is why this broke."""
    obj = _install(win)
    assert not win.base_is_asymmetric_unit(obj)
    obj.structure.metadata["cell_view"] = "asym"
    assert win.base_is_asymmetric_unit(obj)


def test_the_modifier_route_still_counts(win):
    obj = _install(win)
    obj.modifiers.append(mods.SymmetryModifier(
        cell=obj.structure.metadata["cell"],
        symops=list(obj.structure.metadata["symops"])))
    assert win.base_is_asymmetric_unit(obj)


# ----------------------------------- editing the asymmetric unit keeps Pbca
def test_an_element_change_in_the_asymmetric_unit_keeps_the_space_group(win):
    obj = _install(win)
    win.on_crystal_view("asym")
    s = obj.structure
    zn = [i for i, x in enumerate(s.symbols) if x == "Zn"]
    assert zn, "the asymmetric unit should carry the Zn"
    edits.set_element(s, [zn[0]], "Co")
    win._on_edit_committed()
    assert s.metadata["spacegroup"] == "P b c a"
    assert len(s.metadata["symops"]) == 8


def test_the_change_survives_a_switch_to_the_full_cell(win):
    """"...except that the Co switches back to Zn." It must not."""
    obj = _install(win)
    win.on_crystal_view("asym")
    s = obj.structure
    zn = [i for i, x in enumerate(s.symbols) if x == "Zn"]
    edits.set_element(s, [zn[0]], "Co")
    win._on_edit_committed()

    win.on_crystal_view("cell")
    assert "Co" in s.symbols, "the edit was discarded by the rebuild"
    # One Co per operator: the change was REPEATED, which is the whole point.
    assert s.symbols.count("Co") == 8
    assert s.symbols.count("Zn") == 0


def test_going_back_to_the_asymmetric_unit_still_works(win):
    obj = _install(win)
    win.on_crystal_view("asym")
    s = obj.structure
    n_asym = s.n_atoms
    edits.set_element(s, [0], "Co")
    win._on_edit_committed()
    win.on_crystal_view("cell")
    win.on_crystal_view("asym")
    assert s.n_atoms == n_asym
    assert "Co" in s.symbols


def test_a_moved_atom_is_written_back_too(win):
    """Not just elements — coordinates are the other half of an edit."""
    obj = _install(win)
    win.on_crystal_view("asym")
    s = obj.structure
    win.begin_model_edit()          # what the viewport does before it moves
    s.frames[0][0] += np.array([0.4, 0.2, 0.1])
    s.set_frame(0)
    win._on_edit_committed()
    stored = np.asarray(s.metadata["asym_frac"], dtype=float)
    cell = cif.Cell.from_dict(s.metadata["cell"])
    assert np.allclose(stored @ cell.matrix(), s.coords, atol=1e-6)


# -------------------------------- editing the FULL cell still re-derives it
def test_editing_the_full_cell_still_breaks_the_symmetry(win):
    obj = _install(win)
    s = obj.structure
    assert s.metadata["cell_view"] == "cell"
    s.frames[0][1] += np.array([0.44, 0.28, 0.19])
    s.set_frame(0)
    win._on_edit_committed()
    assert len(s.metadata["symops"]) < 8


# --------------------------------------------------- the unit cell is fixed
def test_the_cell_parameters_never_change(win):
    """"The unit cell parameters should not change whether the asymmetric
    unit is edited or the full unit cell.\""""
    obj = _install(win)
    was = dict(obj.structure.metadata["cell"])
    win.on_crystal_view("asym")
    edits.set_element(obj.structure, [0], "Co")
    win._on_edit_committed()
    win.on_crystal_view("cell")
    assert obj.structure.metadata["cell"] == was


def test_the_drawn_cell_box_does_not_creep_as_atoms_are_edited(win):
    """An edit is not a rigid motion, but `cell_pose` is a Kabsch fit against
    a sample of the atoms — so moving one reports a rotation nobody made, and
    the box that follows it drifts a little further with every edit. That is
    what "a small re-scaling of the unit cell boundary" looks like."""
    from molom.ui.viewport import cell_corners_world

    obj = _install(win)
    win.on_crystal_view("asym")
    s = obj.structure
    start = np.asarray(cell_corners_world(obj), dtype=float)

    for k in range(6):
        win.begin_model_edit()
        s.frames[0][k % s.n_atoms] += np.array([0.15, -0.1, 0.08])
        s.set_frame(0)
        win._on_edit_committed()

    now = np.asarray(cell_corners_world(obj), dtype=float)
    assert np.allclose(now, start, atol=1e-6), (
        "the cell box moved by {:.4f} A".format(
            float(np.abs(now - start).max())))


# ----------------------------------------------------------- coplanarity
def _imidazolate_with_substituent(tilt_deg=48.0):
    """A five-ring in the xy plane carrying a PLANAR substituent that has
    been rotated bodily out of it — the state a freshly drawn group is in."""
    import math
    from molom.core.rotations import axis_angle_mat3, rotate_points_about

    r = 1.35
    ring = np.array([[r * math.cos(2 * math.pi * k / 5),
                      r * math.sin(2 * math.pi * k / 5), 0.0]
                     for k in range(5)])
    anchor = ring[1]
    out = anchor / np.linalg.norm(anchor)
    perp = np.array([-out[1], out[0], 0.0])
    n_at = anchor + out * 1.45
    group = np.array([n_at,
                      n_at + out * 0.6 + perp * 1.05,
                      n_at + out * 0.6 - perp * 1.05])
    rot = axis_angle_mat3(np.array([0.4, -0.7, 0.6]), math.radians(tilt_deg))
    group = rotate_points_about(group, rot, anchor)
    coords = np.vstack([ring, group])
    bonds = [(0, 1, 1), (1, 2, 1), (2, 3, 1), (3, 4, 1), (4, 0, 1),
             (1, 5, 1), (5, 6, 2), (5, 7, 2)]
    return coords, bonds


def test_the_five_ring_is_found():
    _coords, bonds = _imidazolate_with_substituent()
    ring = coplanar.ring_through(1, bonds, 8)
    assert ring is not None and len(ring) == 5


def test_an_atom_outside_a_ring_has_no_ring():
    _coords, bonds = _imidazolate_with_substituent()
    assert coplanar.ring_through(6, bonds, 8) is None


def test_a_planar_substituent_becomes_exactly_coplanar():
    coords, bonds = _imidazolate_with_substituent()
    ring = coplanar.ring_through(1, bonds, 8)
    point, normal = coplanar.plane_of(coords, ring)
    before = coplanar.flatness(coords, [5, 6, 7], point, normal)
    assert before > 0.3, "the fixture should start well out of plane"
    moved = coplanar.make_coplanar(coords, [5, 6, 7], 1, 5, ring=ring)
    assert coplanar.flatness(moved, [5, 6, 7], point, normal) < 1e-8


def test_flattening_is_rigid():
    """A projection would flatten it too — and shorten every bond doing it."""
    coords, bonds = _imidazolate_with_substituent()
    ring = coplanar.ring_through(1, bonds, 8)
    moved = coplanar.make_coplanar(coords, [5, 6, 7], 1, 5, ring=ring)
    for i, j in ((1, 5), (5, 6), (5, 7), (6, 7)):
        assert np.linalg.norm(moved[i] - moved[j]) == pytest.approx(
            float(np.linalg.norm(coords[i] - coords[j])), abs=1e-9)


def test_the_ring_itself_never_moves():
    coords, bonds = _imidazolate_with_substituent()
    ring = coplanar.ring_through(1, bonds, 8)
    moved = coplanar.make_coplanar(coords, [5, 6, 7], 1, 5, ring=ring)
    assert np.allclose(moved[:5], coords[:5])


def test_an_sp3_group_puts_its_ATTACHMENT_in_the_plane():
    """A methyl's hydrogens are tetrahedral, so the group can never be flat.
    What must land in the plane is the atom bonded to the ring."""
    import math

    r = 1.35
    ring = np.array([[r * math.cos(2 * math.pi * k / 5),
                      r * math.sin(2 * math.pi * k / 5), 0.0]
                     for k in range(5)])
    out = ring[1] / np.linalg.norm(ring[1])
    c = ring[1] + out * 1.5 + np.array([0.0, 0.0, 1.1])
    coords = np.vstack([ring, [c], [c + [0.6, 0.6, 0.7]],
                        [c + [-0.9, 0.3, 0.5]], [c + [0.2, -0.9, 0.6]]])
    bonds = [(0, 1, 1), (1, 2, 1), (2, 3, 1), (3, 4, 1), (4, 0, 1),
             (1, 5, 1), (5, 6, 1), (5, 7, 1), (5, 8, 1)]
    ring_idx = coplanar.ring_through(1, bonds, 9)
    point, normal = coplanar.plane_of(coords, ring_idx)
    moved = coplanar.make_coplanar(coords, [5, 6, 7, 8], 1, 5, ring=ring_idx)
    assert abs(float((moved[5] - point) @ normal)) < 1e-9
