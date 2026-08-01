"""Round-14 core: the non-destructive modifier stack, and delete-with-H."""

import numpy as np
import pytest

from molom.core import bonding, build, edits, modifiers, project
from molom.core.scene import Scene
from molom.core.structure import Structure


def _cubane_scene():
    sc = Scene()
    return sc, sc.add(build.cubane())


# ---------------------------------------------------------------- modifiers

def test_array_is_non_destructive():
    sc, obj = _cubane_scene()
    base_n = obj.structure.n_atoms
    base_xyz = obj.structure.coords.copy()
    obj.modifiers.append(modifiers.ArrayModifier(count=4, offset=(4, 0, 0)))
    sym, xyz, bonds = obj.evaluated()
    assert len(sym) == base_n * 4
    assert len(bonds) == len(obj.structure.bonds) * 4
    # the base molecule is untouched — this is what keeps editing sane
    assert obj.structure.n_atoms == base_n
    assert np.allclose(obj.structure.coords, base_xyz)
    # copies are displaced by exactly the offset
    assert np.allclose(xyz[base_n:2 * base_n] - xyz[:base_n], [4, 0, 0])
    # ...and bonds are reindexed into each copy, never across copies
    for i, j, _o in bonds:
        assert i // base_n == j // base_n


def test_array_count_one_is_identity():
    sc, obj = _cubane_scene()
    obj.modifiers.append(modifiers.ArrayModifier(count=1))
    sym, xyz, bonds = obj.evaluated()
    assert len(sym) == obj.structure.n_atoms
    assert np.allclose(xyz, obj.structure.coords)


def test_disabled_modifier_is_skipped():
    sc, obj = _cubane_scene()
    mod = modifiers.ArrayModifier(count=5, offset=(4, 0, 0))
    mod.enabled = False
    obj.modifiers.append(mod)
    assert not modifiers.stack_is_active(obj.modifiers)
    sym, _xyz, _b = obj.evaluated()
    assert len(sym) == obj.structure.n_atoms


def test_relative_offset_scales_with_the_molecule():
    sc, obj = _cubane_scene()
    span = (obj.structure.coords[:, 0].max()
            - obj.structure.coords[:, 0].min())
    obj.modifiers.append(modifiers.ArrayModifier(count=2, offset=(1.0, 0, 0),
                                                 relative=True))
    _s, xyz, _b = obj.evaluated()
    n = obj.structure.n_atoms
    assert np.allclose(xyz[n] - xyz[0], [span, 0, 0])


def test_stacked_modifiers_compose():
    sc, obj = _cubane_scene()
    n = obj.structure.n_atoms
    obj.modifiers.append(modifiers.ArrayModifier(count=2, offset=(4, 0, 0)))
    obj.modifiers.append(modifiers.ArrayModifier(count=3, offset=(0, 5, 0)))
    sym, _xyz, _b = obj.evaluated()
    assert len(sym) == n * 6              # a 2x3 grid


def test_apply_bakes_and_clears():
    sc, obj = _cubane_scene()
    obj.modifiers.append(modifiers.ArrayModifier(count=3, offset=(4, 0, 0)))
    n = obj.apply_modifiers()
    assert n == 48 and obj.structure.n_atoms == 48
    assert obj.modifiers == []
    assert len(obj.structure.bonds) == 60
    # applying again is a no-op
    assert obj.apply_modifiers() == 48


def test_modifiers_survive_a_savepoint(tmp_path):
    sc, obj = _cubane_scene()
    obj.modifiers.append(modifiers.ArrayModifier(count=7, offset=(1, 2, 3),
                                                 relative=True))
    p = project.save_project(str(tmp_path / "m.molom"), sc)
    sc2 = Scene()
    sc2.from_dict(project.load_project(p)["scene"])
    mod = sc2.objects[0].modifiers[0]
    assert isinstance(mod, modifiers.ArrayModifier)
    assert mod.count == 7 and mod.relative
    assert np.allclose(mod.offset, [1, 2, 3])


def test_modifiers_survive_undo_snapshot():
    sc, obj = _cubane_scene()
    obj.modifiers.append(modifiers.ArrayModifier(count=5))
    snap = sc.snapshot()
    obj.modifiers = []
    sc.restore(snap)
    assert len(sc.objects[0].modifiers) == 1
    assert sc.objects[0].modifiers[0].count == 5


# ------------------------------------------------------------ delete with H

def test_delete_takes_the_hydrogens_with_it():
    s = Structure.from_atoms([("C", 0, 0, 0), ("C", 1.54, 0, 0)])
    bonding.perceive_structure_bonds(s)
    edits.adjust_hydrogens(s, [0, 1])
    assert s.n_atoms == 8                          # ethane
    edits.delete_atoms(s, [0], with_hydrogens=True)
    assert s.symbols.count("H") == 3, s.symbols     # only the CH3 remains
    assert s.n_atoms == 4


def test_delete_without_the_flag_is_unchanged():
    s = Structure.from_atoms([("C", 0, 0, 0), ("C", 1.54, 0, 0)])
    bonding.perceive_structure_bonds(s)
    edits.adjust_hydrogens(s, [0, 1])
    edits.delete_atoms(s, [0])
    assert s.n_atoms == 7                          # orphan H's left behind


def test_delete_keeps_shared_hydrogens_of_survivors():
    """A hydrogen bonded to something that is NOT being deleted stays."""
    s = Structure.from_atoms([("O", 0, 0, 0), ("H", 0.96, 0, 0),
                              ("H", -0.24, 0.93, 0), ("C", 3.0, 0, 0)])
    bonding.perceive_structure_bonds(s)
    edits.delete_atoms(s, [3], with_hydrogens=True)
    assert s.symbols == ["O", "H", "H"]
