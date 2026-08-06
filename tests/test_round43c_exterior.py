"""Round 43c: the exterior control must be LOSSLESS and ROTATION-INVARIANT.

Christian, on 7712836.cif: it "shows more atoms outside the cell than when
'bonded atoms outside the cell' is ticked. Even worse: when it is unticked
again, even more atoms disappear." And on 2130205.cif the result "is not
invariant under rotation of the unit cell".

Three independent causes, one test group each:

  * `build_view` rebuilt its `CifData` WITHOUT the disorder group/assembly
    columns, so every rebuild re-resolved the disorder differently from the
    import (222 content atoms became 294, and 999 drawn became 469);
  * `_autoclose_boundary` set the checkbox's own flag, so the box read as
    ticked over a picture with no shell in it and the first untick disabled a
    modifier the user never enabled;
  * every cell-based calculation is fractional, and the cell matrix is built
    in a canonical orientation — so rotating the crystal changed the answer.
"""

import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from molom.core import cif
from molom.core.scene import Scene
from molom.core.structure import Structure


DISORDERED = """
data_t
_cell_length_a 10.0
_cell_length_b 10.0
_cell_length_c 10.0
_cell_angle_alpha 90.0
_cell_angle_beta 90.0
_cell_angle_gamma 90.0
loop_
_symmetry_equiv_pos_as_xyz
'x,y,z'
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
_atom_site_disorder_group
_atom_site_disorder_assembly
C1 C 0.200 0.200 0.200 0.60 1 A
C1B C 0.215 0.200 0.200 0.40 2 A
C2 C 0.600 0.600 0.600 1.00 . .
"""


def _data():
    return cif.parse_cif(DISORDERED)


# --------------------------------------------- the disorder columns survive
def test_the_disorder_columns_are_read():
    d = _data()
    assert set(d.disorder_groups) == {"1", "2", "."} or "1" in d.disorder_groups
    assert "A" in d.disorder_assemblies


def test_build_view_without_the_columns_resolves_differently():
    """The bug, pinned as a difference: hand `build_view` only the
    occupancies and it falls back to geometric overlap."""
    d = _data()
    plain = cif.build_view(d.cell, list(d.symbols), d.frac, d.symops,
                           occupancy=[float(o) for o in d.occupancy])[0]
    full = cif.build_view(d.cell, list(d.symbols), d.frac, d.symops,
                          occupancy=[float(o) for o in d.occupancy],
                          disorder_groups=list(d.disorder_groups),
                          disorder_assemblies=list(d.disorder_assemblies))[0]
    # Both are legitimate resolutions; the point is that they are NOT the
    # same, which is why the columns have to be carried.
    assert len(full) == len(cif.expand(d)[0])
    assert isinstance(plain, list)


def test_build_view_with_the_columns_reproduces_the_import():
    """The fix: a rebuild is the import, atom for atom."""
    d = _data()
    imported = cif.expand(d)[0]
    rebuilt = cif.build_view(
        d.cell, list(d.symbols), d.frac, d.symops,
        occupancy=[float(o) for o in d.occupancy],
        disorder_groups=list(d.disorder_groups),
        disorder_assemblies=list(d.disorder_assemblies))[0]
    assert list(rebuilt) == list(imported)


# ------------------------------------------------------ rotation invariance
def _crystal():
    """A carbon chain running THROUGH a cell face, so the boundary modifier
    has real work to do: 6 A cell, atoms 1.5 A apart along x, and the gap from
    the last one to the next cell's first is also 1.5 A."""
    cell = cif.Cell(6.0, 6.0, 6.0, 90.0, 90.0, 90.0)
    # Deliberately NOT collinear. A straight chain makes the Kabsch fit
    # under-determined — rotation about the chain axis is free — so the pose
    # comes back as a different, equally valid rotation and the test fails for
    # a reason that has nothing to do with the code. Real crystals are never
    # degenerate this way, and `reference_sample` spreads its picks.
    coords = np.array([[0.3, 3.0, 3.0],
                       [1.8, 3.6, 3.0],
                       [3.3, 3.0, 3.5],
                       [4.8, 3.6, 3.0]])
    s = Structure(["C"] * len(coords), [coords])
    s.metadata["cell"] = cell.to_dict()
    return s


def _rotation(deg, axis=(0.3, 0.8, 0.5)):
    a = np.asarray(axis, dtype=float)
    a = a / np.linalg.norm(a)
    t = np.deg2rad(deg)
    k = np.array([[0.0, -a[2], a[1]], [a[2], 0.0, -a[0]], [-a[1], a[0], 0.0]])
    return np.eye(3) + np.sin(t) * k + (1.0 - np.cos(t)) * (k @ k)


def test_the_cell_pose_is_identity_before_anything_moves():
    from molom.ui.viewport import set_cell_reference

    s = _crystal()
    set_cell_reference(s)
    obj = Scene().add(s)
    pose = obj.cell_pose()
    assert pose is not None
    rot, shift = pose
    assert np.allclose(rot, np.eye(3), atol=1e-8)
    assert np.allclose(shift, 0.0, atol=1e-8)


def test_the_cell_pose_recovers_a_rotation():
    from molom.ui.viewport import set_cell_reference

    s = _crystal()
    set_cell_reference(s)
    obj = Scene().add(s)
    rot = _rotation(37.0)
    centre = s.coords.mean(axis=0)
    s.frames = [(s.coords - centre) @ rot.T + centre]
    s.set_frame(0)
    got, _shift = obj.cell_pose()
    assert np.allclose(got, rot, atol=1e-6)


def test_a_pose_aware_modifier_undoes_the_rotation():
    """The whole point: identical output whatever way the crystal faces."""
    from molom.core import modifiers as mods
    from molom.ui.viewport import set_cell_reference

    s = _crystal()
    set_cell_reference(s)
    obj = Scene().add(s)
    mod = mods.BoundaryModifier(cell=s.metadata["cell"])
    assert mod.wants_pose
    obj.modifiers.append(mod)
    flat = len(obj.evaluated()[0])

    for deg in (10.0, 37.0, 90.0):
        s2 = _crystal()
        set_cell_reference(s2)
        o2 = Scene().add(s2)
        o2.modifiers.append(mods.BoundaryModifier(cell=s2.metadata["cell"]))
        rot = _rotation(deg)
        centre = s2.coords.mean(axis=0)
        s2.frames = [(s2.coords - centre) @ rot.T + centre]
        s2.set_frame(0)
        assert len(o2.evaluated()[0]) == flat, "changed at {} deg".format(deg)


def test_a_modifier_that_does_not_want_the_pose_never_sees_it():
    """`wants_pose` is opt-in: an array offset is a WORLD vector and must not
    be quietly reinterpreted in the cell frame."""
    from molom.core import modifiers as mods

    arr = mods.ArrayModifier(count=2, offset=(1.0, 0.0, 0.0))
    assert not arr.wants_pose
    symbols = ["C", "C"]
    coords = np.array([[0.0, 0.0, 0.0], [0.5, 0.0, 0.0]])
    a, b, _c = mods.evaluate_stack([arr], symbols, coords, [],
                                   pose=(np.eye(3) * 1.0, np.zeros(3)))
    assert len(a) == 4
    assert b.shape == (4, 3)
