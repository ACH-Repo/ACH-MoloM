"""Round 80 (open item A1): a delete renumbers, so every per-atom map must
be renumbered with it.

`edits.delete_atoms` reindexed the BONDS and the cell reference and nothing
else. Everything else keyed by atom index - a meta centre's geometry, the
crystal columns, the occupancy of a shared site, the refused-bond override,
and a molecule's own colours, labels, hidden atoms and sphere sizes - kept
its old keys and quietly came to describe different atoms.

**The reason it survived so long is that it never looks broken.** An index
map stays perfectly VALID after a renumbering; `meta.prune` was being called
and only ever caught the entries that fell off the END. So the failure is a
meta centre silently attached to some other atom, which is round 42's rule
("a per-atom map must be built after everything that renumbers") stated as a
bug rather than as a convention.
"""

import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from molom.core import edits, meta as meta_mod
from molom.core.scene import MolObject, Scene
from molom.core.structure import Structure

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def _chain(symbols=("C", "N", "O", "F", "S", "P")):
    return Structure.from_atoms(
        [(s, float(i), 0.0, 0.0) for i, s in enumerate(symbols)], name="chain")


def _obj(structure=None):
    scene = Scene()
    return scene.add(structure or _chain(), name="chain")


# ------------------------------------------------------------ the meta table
def test_a_meta_centre_follows_its_atom_through_a_delete():
    """A1. `meta.remap` has existed since round 19 and was never called."""
    obj = _obj()
    meta_mod.set_meta(obj.structure, 4,
                      meta_mod.MetaAtom(geometry="octahedral", distance=2.0,
                                        element="Fe", locked=True))
    assert obj.structure.symbols[4] == "Xx"     # a meta centre draws as Xx
    obj.delete_atoms([1])
    table = meta_mod.all_meta(obj.structure)
    assert list(table) == [3]
    assert obj.structure.symbols[3] == "Xx"     # the same atom, renumbered
    assert table[3].element == "Fe"


def test_pruning_was_never_enough_and_this_is_why():
    """`prune` drops entries pointing PAST THE END, and an index that has
    merely come to mean a different atom is not past the end. Deleting one
    atom below a meta centre leaves its index perfectly in range."""
    s = _chain()
    meta_mod.set_meta(s, 4, meta_mod.MetaAtom(geometry="octahedral",
                                              distance=2.0, element="Fe"))
    edits.delete_atoms(s, [1])          # the real path: remapped
    assert list(meta_mod.all_meta(s)) == [3]
    # ...and the old behaviour, reconstructed, to show what prune alone did
    s2 = _chain()
    s2.metadata[meta_mod._KEY] = {"4": {"geometry": "octahedral",
                                        "distance": 2.0, "element": "Fe"}}
    del s2.symbols[1]
    for k in range(s2.n_frames):
        s2.frames[k] = np.delete(s2.frames[k], [1], axis=0)
    meta_mod.prune(s2)
    assert list(meta_mod.all_meta(s2)) == [4]      # still in range
    assert s2.symbols[4] == "P"                    # and naming the wrong atom
    assert s2.symbols[3] == "S"                    # the one it meant


def test_a_meta_centre_that_was_deleted_is_dropped():
    obj = _obj()
    meta_mod.set_meta(obj.structure, 4,
                      meta_mod.MetaAtom(geometry="octahedral", distance=2.0))
    obj.delete_atoms([4])
    assert not meta_mod.all_meta(obj.structure)


# ------------------------------------------------- the object's display maps
def test_every_display_map_follows_its_atom():
    """Colours, labels, hidden atoms and sphere sizes live on the OBJECT, so
    `edits.delete_atoms` cannot reach them - which is what
    `MolObject.delete_atoms` is for."""
    obj = _obj()
    obj.atom_colors[4] = (1.0, 0.0, 0.0)
    obj.atom_labels.add(4)
    obj.atom_label_text[4] = "here"
    obj.atom_label_colors[4] = (0.0, 1.0, 0.0)
    obj.atom_label_modes[4] = "element"
    obj.atom_hidden.add(5)
    obj.atom_scales[4] = 2.0
    obj.delete_atoms([1])
    assert obj.structure.symbols == ["C", "O", "F", "S", "P"]
    for name in ("atom_colors", "atom_label_text", "atom_label_colors",
                 "atom_label_modes", "atom_scales"):
        assert list(getattr(obj, name)) == [3], name
    assert obj.atom_labels == {3}
    assert obj.atom_hidden == {4}
    assert obj.structure.symbols[3] == "S" and obj.structure.symbols[4] == "P"


def test_a_display_entry_whose_atom_is_gone_is_dropped():
    obj = _obj()
    obj.atom_colors[4] = (1.0, 0.0, 0.0)
    obj.atom_hidden.add(4)
    obj.delete_atoms([4])
    assert not obj.atom_colors and not obj.atom_hidden


def test_ATOM_MAPS_names_every_per_atom_field():
    """The guard that makes this a one-place checklist. A new per-atom map
    added beside the others and left out of `ATOM_MAPS` would be silently
    unmapped, which is the exact bug this round fixes - so it fails here
    instead, at the line that introduced it."""
    obj = _obj()
    fields = {name for name in vars(obj) if name.startswith("atom_")}
    assert fields == set(MolObject.ATOM_MAPS)


# ------------------------------------------------------- the crystal columns
def test_the_crystal_columns_follow_too():
    obj = _obj()
    meta = obj.structure.metadata
    meta["site_of"] = [10, 11, 12, 13, 14, 15]
    meta["content_of"] = [0, 1, 2, 3, 4, 5]
    meta["site_occupancy"] = {"4": {"S": 0.5, "P": 0.5}}
    meta["refused_bonds"] = [(0, 4), (2, 5)]
    obj.delete_atoms([1])
    assert meta["site_of"] == [10, 12, 13, 14, 15]
    assert meta["content_of"] == [0, 2, 3, 4, 5]
    assert meta["site_occupancy"] == {"3": {"S": 0.5, "P": 0.5}}
    assert meta["refused_bonds"] == [(0, 3), (1, 4)]


def test_a_refused_bond_to_a_deleted_atom_goes():
    obj = _obj()
    obj.structure.metadata["refused_bonds"] = [(0, 4), (2, 5)]
    obj.delete_atoms([4])
    assert obj.structure.metadata["refused_bonds"] == [(2, 4)]


# ---------------------------------------------- the OTHER renumbering path
def test_re_dressing_hydrogens_renumbers_too():
    """Adding a hydrogen appends and disturbs nothing; REMOVING one - which
    is what C -> O does, and what raising a bond order does - renumbers every
    atom above it exactly as a delete would."""
    s = Structure.from_atoms(
        [("C", 0.0, 0.0, 0.0), ("H", 1.09, 0.0, 0.0), ("H", -1.09, 0.0, 0.0),
         ("H", 0.0, 1.09, 0.0), ("H", 0.0, -1.09, 0.0)], name="ch4")
    s.bonds = [(0, i, 1) for i in range(1, 5)]
    obj = _obj(s)
    obj.atom_colors[4] = (1.0, 0.0, 0.0)
    added, removed = obj.set_element_adjusted([0], "O")
    assert removed == 2 and added == 0           # CH4 -> OH2
    assert list(obj.atom_colors) == [2]
    assert obj.structure.symbols[2] == "H"
    assert all(k < obj.structure.n_atoms for k in obj.atom_colors)


def test_adding_an_atom_disturbs_nothing():
    """Appending cannot renumber, so nothing is remapped and nothing is
    lost - worth pinning so the fix is not extended to a path that would
    only ever damage it."""
    obj = _obj()
    obj.atom_colors[4] = (1.0, 0.0, 0.0)
    meta_mod.set_meta(obj.structure, 4,
                      meta_mod.MetaAtom(geometry="octahedral", distance=2.0))
    edits.add_atom(obj.structure, "H", (9.0, 0.0, 0.0))
    assert list(obj.atom_colors) == [4]
    assert list(meta_mod.all_meta(obj.structure)) == [4]


# ------------------------------------------------------------ end to end
@pytest.fixture
def win():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.app import MainWindow
    QApplication.instance() or QApplication([])
    w = MainWindow()
    w.show()
    return w


def test_an_occupancy_pie_sphere_stays_on_its_own_atom(win):
    """The visible half, on the file round 42 was written against: a shared
    site's composition is keyed by DRAWN atom index, so deleting an atom
    below it used to slide the pie chart onto whichever atom inherited the
    index."""
    win.open_path(os.path.join(DATA, "cod_1547149_solid_solution.cif"))
    obj = win._active_obj()
    table = obj.structure.metadata.get("site_occupancy") or {}
    assert table, "this file has a shared site"
    marked = sorted(int(k) for k in table)
    assert len(marked) > 1, "more than one image of the shared site"
    # The shared sites here are the FIRST atoms in the cell, so the only way
    # to renumber one is to delete another - which is the realistic gesture
    # anyway: the images of one site are the atoms most likely to be edited
    # together.
    victim, survivor = marked[0], marked[1]
    symbol = obj.structure.symbols[survivor]
    composition = table[str(survivor)]
    obj.delete_atoms([victim])

    now = obj.structure.metadata.get("site_occupancy") or {}
    keys = sorted(int(k) for k in now)
    assert keys == [i - 1 for i in marked[1:]]
    assert obj.structure.symbols[survivor - 1] == symbol
    assert now[str(survivor - 1)] == composition


def test_deleting_through_the_window_keeps_a_meta_centre(win):
    """The path Christian would take: select an atom, press Delete."""
    win.load_default_scene()
    obj = win._active_obj()
    meta_mod.set_meta(obj.structure, 7,
                      meta_mod.MetaAtom(geometry="octahedral", distance=2.4,
                                        element="Fe", locked=True))
    obj.atom_colors[7] = (1.0, 0.0, 0.0)
    win.viewport.set_selection([(obj.id, 0)])
    win.on_delete_selected()
    obj = win.scene.get(obj.id)
    table = meta_mod.all_meta(obj.structure)
    assert len(table) == 1
    index = list(table)[0]
    assert obj.structure.symbols[index] == "Xx"
    assert list(obj.atom_colors) == [index]        # and the colour with it
    assert table[index].distance == pytest.approx(2.4)
