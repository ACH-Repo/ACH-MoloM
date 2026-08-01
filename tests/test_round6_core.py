"""Round-6 core: bond-order perception, hydrogen adjustment, coordination
templates, savepoint files, undo depth, axis-locked tumble math."""

import numpy as np
import pytest

from molom.core import (bonding, coordination, edits, manipulate, project)
from molom.core.scene import Scene
from molom.core.structure import Structure
from molom.core.undo import UndoStack


def _struct(atoms):
    s = Structure.from_atoms(atoms, name="t")
    bonding.perceive_structure_bonds(s)
    return s


def _orders(s):
    return sorted(o for _i, _j, o in s.bonds)


# --------------------------------------------------------------- bond orders

def test_ethene_double():
    s = _struct([("C", 0, 0, 0), ("C", 1.33, 0, 0),
                 ("H", -0.57, 0.93, 0), ("H", -0.57, -0.93, 0),
                 ("H", 1.90, 0.93, 0), ("H", 1.90, -0.93, 0)])
    bonding.perceive_structure_bond_orders(s)
    assert _orders(s) == [1, 1, 1, 1, 2]


def test_ethyne_triple():
    s = _struct([("C", 0, 0, 0), ("C", 1.20, 0, 0),
                 ("H", -1.06, 0, 0), ("H", 2.26, 0, 0)])
    bonding.perceive_structure_bond_orders(s)
    assert _orders(s) == [1, 1, 3]


def test_ethane_stays_single():
    s = _struct([("C", 0, 0, 0), ("C", 1.54, 0, 0),
                 ("H", -0.36, 1.02, 0), ("H", -0.36, -0.51, 0.89),
                 ("H", -0.36, -0.51, -0.89), ("H", 1.90, -1.02, 0),
                 ("H", 1.90, 0.51, 0.89), ("H", 1.90, 0.51, -0.89)])
    bonding.perceive_structure_bond_orders(s)
    assert _orders(s) == [1] * 7


def test_benzene_kekule_alternates():
    """Six equal 1.39 A ring bonds all *look* double; the valence cap is what
    forces the alternating Kekule pattern instead of six doubles."""
    ang = np.linspace(0, 2 * np.pi, 6, endpoint=False)
    atoms = [("C", 1.39 * np.cos(a), 1.39 * np.sin(a), 0.0) for a in ang]
    atoms += [("H", 2.48 * np.cos(a), 2.48 * np.sin(a), 0.0) for a in ang]
    s = _struct(atoms)
    bonding.perceive_structure_bond_orders(s)
    ring = [(i, j, o) for i, j, o in s.bonds if i < 6 and j < 6]
    assert len(ring) == 6
    assert sum(1 for _i, _j, o in ring if o == 2) == 3
    for c in range(6):
        n_double = sum(1 for i, j, o in ring if o == 2 and c in (i, j))
        assert n_double == 1, "carbon {} has {} doubles".format(c, n_double)


def test_co2_two_doubles():
    s = _struct([("C", 0, 0, 0), ("O", 1.16, 0, 0), ("O", -1.16, 0, 0)])
    bonding.perceive_structure_bond_orders(s)
    assert _orders(s) == [2, 2]


def test_water_and_metal_stay_single():
    s = _struct([("O", 0, 0, 0), ("H", 0.96, 0, 0), ("H", -0.24, 0.93, 0)])
    bonding.perceive_structure_bond_orders(s)
    assert _orders(s) == [1, 1]
    # a metal centre is never given multiple bonds (no typical valence)
    m = _struct([("Fe", 0, 0, 0), ("O", 1.7, 0, 0), ("O", -1.7, 0, 0)])
    bonding.perceive_structure_bond_orders(m)
    assert _orders(m) == [1, 1]


def test_bond_orders_do_not_mutate_input():
    s = _struct([("C", 0, 0, 0), ("C", 1.33, 0, 0)])
    original = list(s.bonds)
    out = bonding.perceive_bond_orders(s.symbols, s.coords, s.bonds)
    assert s.bonds == original
    assert out != original or original == []


# -------------------------------------------------------------- coordination

def test_tetrahedral_free_direction():
    """A CH3 fragment's missing vertex, not just 'away from the rest'."""
    tet = coordination.directions("tetrahedral")
    free = coordination.free_directions(tet[:3], n_needed=1)
    assert free.shape == (1, 3)
    assert abs(float(np.dot(free[0], tet[3]))) > 0.99


def test_free_direction_from_two_bonds():
    tet = coordination.directions("tetrahedral")
    free = coordination.free_directions(tet[:2], geometry="tetrahedral",
                                        n_needed=2)
    assert free.shape == (2, 3)
    for want in (tet[2], tet[3]):
        assert max(abs(float(np.dot(f, want))) for f in free) > 0.95


def test_geometry_tables_are_unit_and_sized():
    for name, dirs in coordination.GEOMETRY_DIRECTIONS.items():
        d = coordination.directions(name)
        assert np.allclose(np.linalg.norm(d, axis=1), 1.0), name
    assert coordination.geometry_for_count(4) == "tetrahedral"
    assert coordination.geometry_for_count(6) == "octahedral"
    with pytest.raises(ValueError):
        coordination.directions("nonsense")


def test_coordination_spec_and_targets():
    spec = coordination.CoordinationSpec("octahedral", distance=2.1)
    assert spec.n_donors == 6
    pos = coordination.ideal_donor_positions(np.array([1.0, 0, 0]), spec)
    assert pos.shape == (6, 3)
    d = np.linalg.norm(pos - np.array([1.0, 0, 0]), axis=1)
    assert np.allclose(d, 2.1)
    assert coordination.CoordinationSpec.from_dict(
        spec.to_dict()).geometry == "octahedral"


# ---------------------------------------------------------------- hydrogens

def _methyl():
    tet = coordination.directions("tetrahedral") * 1.09
    atoms = [("C", 0.0, 0.0, 0.0)]
    atoms += [("H", float(v[0]), float(v[1]), float(v[2])) for v in tet[:3]]
    return _struct(atoms)


def test_adjust_hydrogens_completes_methane():
    s = _methyl()
    assert edits.free_valence(s, 0) == 1
    added, removed = edits.adjust_hydrogens(s, [0])
    assert (added, removed) == (1, 0)
    assert s.n_atoms == 5
    assert edits.free_valence(s, 0) == 0
    d = np.linalg.norm(s.coords[1:] - s.coords[0], axis=1)
    assert np.allclose(d, d[0], atol=0.05)      # all four C-H equal
    # The new H sits on the free tetrahedral vertex: for a tetrahedron the
    # four unit vectors sum to zero, so the fourth is exactly the negated
    # sum of the other three (their mean can only ever dot to -1/3).
    dirs = (s.coords[1:] - s.coords[0])
    dirs /= np.linalg.norm(dirs, axis=1)[:, None]
    assert np.allclose(dirs.sum(axis=0), 0.0, atol=1e-6)
    opposite = -dirs[:3].sum(axis=0)
    opposite /= np.linalg.norm(opposite)
    assert float(np.dot(dirs[3], opposite)) > 0.999


def test_element_change_drops_hydrogen():
    s = _methyl()
    edits.adjust_hydrogens(s, [0])              # CH4
    added, removed = edits.set_element_adjusted(s, [0], "N")
    assert (added, removed) == (0, 1)
    assert s.symbols[0] == "N" and s.n_atoms == 4      # NH3
    assert edits.free_valence(s, 0) == 0


def test_bond_length_grows_when_h_becomes_metal():
    """H -> Zn must push the atom out to the C-Zn covalent distance."""
    s = _struct([("C", 0, 0, 0), ("H", 1.09, 0, 0)])
    assert len(s.bonds) == 1
    edits.set_element_adjusted(s, [1], "Zn", adjust_h=False)
    d = float(np.linalg.norm(s.coords[1] - s.coords[0]))
    want = edits.ideal_bond_length(s, 0, 1)
    assert d == pytest.approx(want, abs=1e-6)
    assert d > 1.5, "Zn should sit much further out than H did"
    # direction preserved (moved along the bond, not somewhere random)
    assert np.allclose(s.coords[1][1:], 0.0, atol=1e-9)


def test_bond_length_shrinks_and_moves_terminal_neighbours():
    s = _struct([("Br", 0, 0, 0), ("H", 1.5, 0, 0)])
    edits.set_element_adjusted(s, [0], "C", adjust_h=False)
    d = float(np.linalg.norm(s.coords[1] - s.coords[0]))
    assert d == pytest.approx(edits.ideal_bond_length(s, 0, 1), abs=1e-6)


def test_bond_length_leaves_interior_atoms_put():
    """An atom with two neighbours is not shoved along one of them."""
    s = _struct([("C", 0, 0, 0), ("C", 1.54, 0, 0), ("C", 3.08, 0, 0)])
    before = s.coords.copy()
    edits.adjust_bond_lengths(s, [1])
    assert np.allclose(s.coords[1], before[1])


def test_hydrogen_adjust_skips_metals_and_h():
    s = _struct([("Fe", 0, 0, 0), ("H", 1.6, 0, 0)])
    assert edits.free_valence(s, 0) is None
    assert edits.adjust_hydrogens(s, [0, 1]) == (0, 0)
    assert s.n_atoms == 2


def test_double_bond_consumes_valence():
    s = _struct([("C", 0, 0, 0), ("C", 1.33, 0, 0)])
    bonding.perceive_structure_bond_orders(s)
    assert edits.bond_order_sum(s, 0) == 2
    added, _r = edits.adjust_hydrogens(s, [0])
    assert added == 2                           # =CH2, not -CH3


# ------------------------------------------------------------------ project

def test_project_roundtrip(tmp_path):
    sc = Scene()
    s = Structure.from_atoms([("O", 0, 0, 0), ("H", 0.96, 0, 0),
                              ("H", -0.24, 0.93, 0)], name="water")
    bonding.perceive_structure_bonds(s)
    obj = sc.add(s)
    obj.origin = np.array([1.0, 2.0, 3.0])
    obj.style_key = "stick"
    obj.visible = False
    sc.add(Structure.from_atoms([("C", 5, 5, 5)], name="lone"))

    p = project.save_project(str(tmp_path / "proj"), sc,
                             view={"distance": 12.5},
                             ui={"style": "vdw"})
    assert p.endswith(".molom")

    payload = project.load_project(p)
    assert payload["version"] == project.VERSION
    assert payload["view"]["distance"] == 12.5
    assert payload["ui"]["style"] == "vdw"

    sc2 = Scene()
    sc2.from_dict(payload["scene"])
    assert [o.name for o in sc2.objects] == ["water", "lone"]
    a = sc2.objects[0]
    assert np.allclose(a.structure.coords, s.coords)
    assert np.allclose(a.origin, [1.0, 2.0, 3.0])
    assert a.style_key == "stick" and a.visible is False
    assert a.structure.bonds == s.bonds
    # ids preserved -> a new object added after load gets a fresh id
    assert sc2.add(Structure.from_atoms([("He", 0, 0, 0)])).id \
        not in (o.id for o in sc.objects)


def test_scene_duplicate_whole_and_subset():
    sc = Scene()
    s = Structure.from_atoms([("C", 0, 0, 0), ("C", 1.54, 0, 0),
                              ("H", -1.0, 0, 0), ("H", 2.54, 0, 0)],
                             name="thing")
    bonding.perceive_structure_bonds(s)
    src = sc.add(s)
    src.style_key = "stick"
    src.origin = np.array([9.0, 0.0, 0.0])

    whole = sc.duplicate(src.id)
    assert whole.name == "thing.001"           # Blender-style dedup
    assert whole.style_key == "stick"
    assert np.allclose(whole.origin, src.origin)   # inherits the parent frame
    assert whole.structure.bonds == s.bonds
    assert whole.structure is not s
    whole.structure.frames[0][0] = [5, 5, 5]
    assert not np.allclose(s.coords[0], [5, 5, 5])  # deep copy

    part = sc.duplicate(src.id, rows=[0, 2])
    assert part.structure.n_atoms == 2
    assert part.structure.symbols == ["C", "H"]
    assert part.structure.bonds == [(0, 1, 1)]     # bond reindexed
    assert np.allclose(part.origin, part.structure.centroid())
    assert sc.duplicate(999) is None
    assert sc.duplicate(src.id, rows=[]) is None


def test_project_rejects_foreign_files(tmp_path):
    bad = tmp_path / "nope.molom"
    bad.write_text('{"format": "something-else"}', encoding="utf-8")
    with pytest.raises(project.ProjectError):
        project.load_project(str(bad))
    notjson = tmp_path / "bad.molom"
    notjson.write_text("<xml/>", encoding="utf-8")
    with pytest.raises(project.ProjectError):
        project.load_project(str(notjson))
    with pytest.raises(project.ProjectError):
        project.load_project(str(tmp_path / "missing.molom"))


def test_project_rejects_newer_version(tmp_path):
    p = tmp_path / "future.molom"
    p.write_text('{"format": "molom-project", "version": 99, "scene": {}}',
                 encoding="utf-8")
    with pytest.raises(project.ProjectError):
        project.load_project(str(p))


def test_project_overwrite_keeps_no_tmp(tmp_path):
    sc = Scene()
    sc.add(Structure.from_atoms([("C", 0, 0, 0)], name="c"))
    p = project.save_project(str(tmp_path / "x.molom"), sc)
    project.save_project(p, sc)
    assert not (tmp_path / "x.molom.tmp").exists()
    assert project.is_project_file(p)


# --------------------------------------------------------------- undo depth

def test_undo_set_limit_trims_now():
    u = UndoStack(limit=30)
    for k in range(10):
        u.push(k)
    u.set_limit(3)
    assert u.undo("cur") == 9
    assert u.undo(9) == 8
    assert u.undo(8) == 7
    assert u.undo(7) is None            # only 3 kept
    assert UndoStack().limit == 30      # default per Christian's spec
    u.set_limit(0)
    assert u.limit == 1


# ------------------------------------------------------- axis-locked tumble

def test_axis_screen_drag_perpendicular():
    r = np.eye(3)                       # camera looking down -Z, x right, y up
    # axis along screen X: dragging UP (dy negative) spins it positively
    assert manipulate.axis_screen_drag([1, 0, 0], r, 0, -10) == pytest.approx(10)
    # dragging along the axis itself does nothing
    assert manipulate.axis_screen_drag([1, 0, 0], r, 10, 0) == pytest.approx(0)


def test_axis_screen_drag_axis_toward_viewer():
    r = np.eye(3)
    # axis pointing at the viewer: horizontal drag spins it (no perpendicular)
    v = manipulate.axis_screen_drag([0, 0, 1], r, 10, 0)
    assert v == pytest.approx(-10)
    assert manipulate.axis_screen_drag([0, 0, -1], r, 10, 0) == pytest.approx(10)
