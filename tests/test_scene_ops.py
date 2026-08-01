"""Scene model and operator registry."""

import numpy as np

from molom.core.ops import OperatorRegistry
from molom.core.scene import Scene
from molom.core.structure import Structure

WATER = [("O", 0.0, 0.0, 0.117), ("H", 0.0, 0.757, -0.469),
         ("H", 0.0, -0.757, -0.469)]


def _scene2():
    sc = Scene()
    sc.add(Structure.from_atoms(WATER, name="water"))
    s2 = Structure.from_atoms([(sym, x + 5.0, y, z)
                               for sym, x, y, z in WATER], name="water")
    sc.add(s2)
    return sc


def test_unique_names_blender_style():
    sc = _scene2()
    assert [o.name for o in sc.objects] == ["water", "water.001"]
    sc.add(Structure.from_atoms(WATER, name="water"))
    assert sc.objects[-1].name == "water.002"


def test_rename_dedups_and_keeps():
    sc = _scene2()
    a, b = sc.objects
    assert sc.rename(b.id, "water") == "water.001"    # collision kept unique
    assert sc.rename(b.id, "ice") == "ice"
    assert sc.rename(a.id, "") == "water"             # blank -> unchanged


def test_remove_and_get():
    sc = _scene2()
    a = sc.objects[0]
    assert sc.remove(a.id)
    assert sc.get(a.id) is None
    assert not sc.remove(999)
    assert sc.n_objects == 1


def test_visibility_and_bounds():
    sc = _scene2()
    r_all = sc.bounding_radius()
    sc.objects[1].visible = False
    r_one = sc.bounding_radius()
    assert r_all > r_one            # hiding the far molecule shrinks the fit
    assert len(sc.visible_objects()) == 1


def test_pick_helpers():
    sc = _scene2()
    a, b = sc.objects
    assert sc.pick_label((a.id, 0)) == "water:O0"     # multi-object: prefixed
    sc.remove(b.id)
    assert sc.pick_label((a.id, 0)) == "O0"           # single object: bare
    assert sc.pick_coords((a.id, 1)) is not None
    assert sc.resolve_pick((a.id, 99)) is None
    assert sc.pick_coords((999, 0)) is None


def test_centroid_two_objects():
    sc = _scene2()
    c = sc.centroid()
    assert abs(c[0] - 2.5) < 1e-9   # halfway between x=0 and x=+5 copies


# ------------------------------------------------------------------ registry

class _Ctx:
    def __init__(self, sel=0):
        self.sel = sel


def _registry():
    r = OperatorRegistry()
    r.register("open", "Open file", lambda c: "open", category="File")
    r.register("delete", "Delete selected", lambda c: "del",
               enabled=lambda c: c.sel > 0, category="Edit", shortcut="Del")
    r.register("bond", "Cycle bond", lambda c: "bond",
               enabled=lambda c: c.sel == 2, category="Edit")
    return r


def test_registry_search_filters_and_ranks():
    r = _registry()
    hits = r.search("dele", _Ctx(sel=0))
    assert [op.id for op, _en in hits] == ["delete"]
    assert hits[0][1] is False                       # disabled with no selection
    hits = r.search("dele", _Ctx(sel=3))
    assert hits[0][1] is True


def test_registry_enabled_first():
    r = _registry()
    hits = r.search("", _Ctx(sel=2))                 # everything matches
    ids = [op.id for op, _en in hits]
    # enabled ops (open, delete, bond) before disabled (none here: all enabled)
    assert set(ids) == {"open", "delete", "bond"}
    hits0 = r.search("", _Ctx(sel=0))
    en = [e for _op, e in hits0]
    assert en == sorted(en, reverse=True)            # enabled sorted first


def test_registry_duplicate_id_raises():
    r = _registry()
    try:
        r.register("open", "Again", lambda c: None)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_registry_multiword_and_predicate_error():
    r = _registry()
    r.register("boom", "Broken predicate", lambda c: None,
               enabled=lambda c: 1 / 0)
    hits = r.search("broken predicate", _Ctx())
    assert hits[0][0].id == "boom" and hits[0][1] is False   # error -> disabled
