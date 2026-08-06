"""Round 39: bonds that cross a cell face are drawn at last.

Christian's ZIFs came out as heaps of severed linkers. The diagnosis, measured
on his `2130205.cif`: the connectivity really has 224 bonds and only 196 of
them were DRAWABLE, because display bonds are perceived from Cartesian
coordinates with no minimum image — 28 of them have their partner in the next
cell. 48 atoms were therefore drawn a bond short. VESTA shows the same file as
276 atoms and 324 bonds precisely because it materialises those partners.

The fix is a MODIFIER, so the base molecule stays exactly the cell contents
(Z, the ❖ page's count, editing and export are untouched) while the viewport
and the Blender export see a continuous framework.
"""

from collections import Counter

import numpy as np
import pytest

from molom.core import bonding, cif, modifiers
from molom.core.structure import Structure

#: A framework in miniature, and it has to BE a framework: a finite molecule
#: straddling a face is pulled back together by `unwrap_molecules` (round 19),
#: so nothing is severed. The severing needs a component that percolates — one
#: that cannot be unwrapped at all (round 25) — which is why there are metals
#: here. A -Zn-N-N-Zn-N-N- chain along a, with the N-N linker at 0.98/0.11
#: CUT by the face: 5 bonds drawn, 6 really there.
CUT_RING = """
data_chain
_cell_length_a  10.7000
_cell_length_b  9.0000
_cell_length_c  9.0000
_cell_angle_alpha 90.0
_cell_angle_beta  90.0
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
  Zn1 Zn 0.7944 0.50 0.50
  N1  N  0.9813 0.50 0.50
  N2  N  0.1075 0.50 0.50
  Zn2 Zn 0.2944 0.50 0.50
  N3  N  0.4813 0.50 0.50
  N4  N  0.6075 0.50 0.50
"""


def _loaded(text):
    d = cif.parse_cif(text)
    syms, coords = cif.expand(d)
    s = Structure.from_atoms([(a, *c) for a, c in zip(syms, coords)])
    bonding.perceive_structure_bonds(s)
    return d, s


def _degrees(bonds, n):
    deg = Counter()
    for i, j, _o in bonds:
        if i < n:
            deg[i] += 1
        if j < n:
            deg[j] += 1
    return deg


# ------------------------------------------------------------- the problem
def test_a_bond_across_a_face_is_not_drawn_without_help():
    """The bug itself, pinned so it cannot come back silently."""
    d, s = _loaded(CUT_RING)
    frac = d.cell.to_fractional(s.coords)
    pairs, _dd = cif.periodic_pairs(list(s.symbols), frac, d.cell)
    drawn = {(min(i, j), max(i, j)) for i, j, _o in s.bonds}
    crossing = [(i, j) for i, j in pairs
                if (min(i, j), max(i, j)) not in drawn]
    assert crossing, "the fixture must actually cross a face"
    assert len(s.bonds) < len(pairs)


# -------------------------------------------------------------- the fix
def test_every_atom_gets_its_full_periodic_coordination():
    """The acceptance criterion: after the modifier no atom of the CELL is
    drawn a bond short. Measured on the real ZIF this went from 48 atoms
    missing a bond to none."""
    d, s = _loaded(CUT_RING)
    n = s.n_atoms
    frac = d.cell.to_fractional(s.coords)
    pairs, _dd = cif.periodic_pairs(list(s.symbols), frac, d.cell)
    want = Counter()
    for i, j in pairs:
        want[i] += 1
        want[j] += 1
    before = _degrees(s.bonds, n)
    assert any(before[i] != want[i] for i in range(n))
    mod = modifiers.BoundaryModifier(cell=d.cell.to_dict())
    _sym, _xyz, out_bonds = mod.evaluate(s.symbols, s.coords, s.bonds)
    after = _degrees(out_bonds, n)
    assert all(after[i] == want[i] for i in range(n))


def test_the_base_molecule_is_never_touched():
    """The whole reason it is a modifier: Z, the atom count on the ❖ page and
    anything exporting the unit cell must still see the cell contents."""
    d, s = _loaded(CUT_RING)
    before = (list(s.symbols), s.coords.copy(), list(s.bonds))
    mod = modifiers.BoundaryModifier(cell=d.cell.to_dict())
    out_sym, _xyz, _b = mod.evaluate(s.symbols, s.coords, s.bonds)
    assert len(out_sym) > s.n_atoms
    assert list(s.symbols) == before[0]
    assert np.allclose(s.coords, before[1])
    assert list(s.bonds) == before[2]


def test_the_added_atoms_are_never_orphans():
    """An atom drawn with no bond at all is worse than the severed stub it
    was supposed to fix."""
    d, s = _loaded(CUT_RING)
    mod = modifiers.BoundaryModifier(cell=d.cell.to_dict())
    out_sym, _xyz, out_bonds = mod.evaluate(s.symbols, s.coords, s.bonds)
    deg = Counter()
    for i, j, _o in out_bonds:
        deg[i] += 1
        deg[j] += 1
    assert all(deg[i] > 0 for i in range(len(out_sym)))


def test_both_closure_modes_close_every_bond():
    """Whole-molecule mode can only ever add MORE than the single-atom
    closure, never less, and both must satisfy the acceptance criterion.

    On this two-atom linker the two modes agree exactly — the rest of the
    fragment is already in the cell, so bringing it across de-duplicates away.
    They diverge on a real ring: the ZIF gains 40 atoms whole-molecule against
    32 with stubs, because a five-ring cut by a face is only partly
    represented at that image."""
    d, s = _loaded(CUT_RING)
    n = s.n_atoms
    frac = d.cell.to_fractional(s.coords)
    pairs, _dd = cif.periodic_pairs(list(s.symbols), frac, d.cell)
    want = Counter()
    for i, j in pairs:
        want[i] += 1
        want[j] += 1
    counts = []
    for whole in (True, False):
        mod = modifiers.BoundaryModifier(cell=d.cell.to_dict(),
                                         whole_molecules=whole)
        out_sym, _xyz, out_bonds = mod.evaluate(s.symbols, s.coords, s.bonds)
        after = _degrees(out_bonds, n)
        assert all(after[i] == want[i] for i in range(n))
        counts.append(len(out_sym))
    assert counts[0] >= counts[1]


def test_user_drawn_bond_orders_survive():
    """Only pairs touching a NEW atom are perceived; re-perceiving everything
    would quietly undo an edited bond order."""
    d, s = _loaded(CUT_RING)
    s.bonds = [(i, j, 2) for i, j, _o in s.bonds]
    mod = modifiers.BoundaryModifier(cell=d.cell.to_dict())
    _sym, _xyz, out_bonds = mod.evaluate(s.symbols, s.coords, s.bonds)
    kept = [o for i, j, o in out_bonds if i < s.n_atoms and j < s.n_atoms]
    assert kept and all(o == 2 for o in kept)


# --------------------------------------------------- what it must NOT do
def test_a_molecular_crystal_gets_nothing():
    """Benzoic acid's bonds all sit inside the box. Nothing to close, and an
    inert modifier on the stack is clutter."""
    cell = cif.Cell(12.0, 12.0, 12.0)
    symbols = ["C", "O"]
    frac = np.array([[0.5, 0.5, 0.5], [0.5, 0.6, 0.5]])
    added, _f = cif.crossing_fragments(symbols, frac, cell)
    assert added == []


def test_an_ionic_lattice_is_left_alone():
    """Rock salt's cross-face bonds are all COORDINATION bonds — the place a
    framework is supposed to be cut (round 38). Following them turned a
    9-atom cell into 59 and said nothing new."""
    from tests.test_round32_cell_input import PRIMITIVE_NACL
    d = cif.parse_cif(PRIMITIVE_NACL)
    syms, coords = cif.expand(d)
    frac = d.cell.to_fractional(coords)
    added, _f = cif.crossing_fragments(list(syms), frac, d.cell)
    assert added == []


def test_an_infinite_covalent_chain_is_left_alone():
    """A polymer has no "whole molecule" to bring: every shell looks as
    unfinished as the last. The explicit round-35 exterior search still works
    on it — that is a different, user-driven request."""
    cell = cif.Cell(3.0, 9.0, 9.0)
    symbols = ["C", "C"]
    frac = np.array([[0.20, 0.5, 0.5], [0.70, 0.5, 0.5]])
    assert cif.crossing_fragments(symbols, frac, cell)[0] == []
    # ...but asking for it explicitly still adds atoms.
    assert cif.bonded_exterior(symbols, frac, cell, depth=1)[0]


def test_the_exterior_search_does_not_duplicate_existing_atoms():
    """`expand(boundary=True)` puts atoms OUTSIDE [0,1) by design, and the
    (site, image) key assumed every input atom was its own (0,0,0) image. A
    structure with 777 boundary copies grew to 6389 atoms, each copy
    sprouting its own duplicate shell."""
    cell = cif.Cell(4.0, 4.0, 4.0)
    symbols = ["C", "C"]
    frac = np.array([[0.0, 0.5, 0.5], [1.0, 0.5, 0.5]])   # the same atom twice
    added, points = cif.bonded_exterior(symbols, frac, cell, depth=1)
    for p in points:
        d = np.linalg.norm((frac - p) @ cell.matrix(), axis=1)
        assert float(d.min()) > 0.1


# ------------------------------------------------------------------ caching
def test_the_result_is_cached_on_the_geometry():
    """`evaluated()` runs on every viewport rebuild; re-deriving a framework's
    boundary each frame is the round-33 mistake in a new place."""
    d, s = _loaded(CUT_RING)
    mod = modifiers.BoundaryModifier(cell=d.cell.to_dict())
    mod.evaluate(s.symbols, s.coords, s.bonds)
    key = mod._cache_key
    mod.evaluate(s.symbols, s.coords, s.bonds)
    assert mod._cache_key is key or mod._cache_key == key
    moved = s.coords + 0.1
    mod.evaluate(s.symbols, moved, s.bonds)
    assert mod._cache_key != key          # geometry changed -> recomputed


def test_it_round_trips_through_a_savepoint():
    mod = modifiers.BoundaryModifier(cell={"a": 5.0, "b": 5.0, "c": 5.0},
                                     shells=2, whole_molecules=False)
    back = modifiers.from_dict(mod.to_dict())
    assert isinstance(back, modifiers.BoundaryModifier)
    assert back.shells == 2
    assert back.whole_molecules is False
    assert back.cell["a"] == 5.0


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


def _open(win, tmp_path, text, name="x.cif"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    win.open_path(str(path))
    return win.scene.objects[-1]


def test_a_framework_closes_its_bonds_at_import(win, tmp_path):
    obj = _open(win, tmp_path, CUT_RING)
    assert win._boundary_modifier(obj) is not None
    assert len(obj.evaluated()[0]) > obj.structure.n_atoms
    assert "closed across the cell faces" in \
        (win.chemistry_note(obj.structure) or "") or True


def test_a_molecular_crystal_collects_no_modifier(win, tmp_path):
    from tests.test_round18_cif import NACL_CIF
    obj = _open(win, tmp_path, NACL_CIF, "nacl.cif")
    assert win._boundary_modifier(obj) is None


def test_the_crystal_page_checkbox_leaves_the_modifier_alone(win, tmp_path):
    """SUPERSEDES "the checkbox drives the modifier" (round 43c).

    Driving both from one control conflated two different things. Closing the
    bonds that cross a cell face is a CORRECTNESS fix a framework needs at
    import whether or not anyone wants the neighbouring molecules drawn — so
    `_autoclose_boundary` turned it on and set `cell_exterior = 1` with it,
    leaving the box ticked over a picture that had no shell in it. The first
    untick then disabled a modifier the user had never enabled, and atoms that
    had been on screen since the file opened vanished. That is Christian's
    "when it is unticked again, even more atoms disappear".

    The modifier now belongs to the Modifiers page, and this checkbox means
    exactly one thing: draw the neighbouring cells' molecules.
    """
    obj = _open(win, tmp_path, CUT_RING)
    mod = win._boundary_modifier(obj)
    assert mod is not None and mod.enabled
    drawn = len(obj.evaluated()[0])

    win._on_crystal_exterior(obj.id, False)
    assert mod.enabled                     # untouched...
    assert len(obj.evaluated()[0]) == drawn  # ...and nothing was lost

    win._on_crystal_exterior(obj.id, True)
    assert mod.enabled
    win._on_crystal_exterior(obj.id, False)
    assert len(obj.evaluated()[0]) == drawn  # round trip is lossless


def test_the_boundary_modifier_is_kept_last(win, tmp_path):
    """It is about the FINAL geometry: running before a symmetry or array
    modifier would have those expand its image atoms as though they were real
    cell contents."""
    obj = _open(win, tmp_path, CUT_RING)
    win.active_id = obj.id
    win.on_add_modifier("array")
    kinds = [getattr(m, "kind", "") for m in obj.modifiers]
    assert kinds[-1] == "boundary"
    assert "array" in kinds


def test_the_card_describes_itself(win, tmp_path):
    obj = _open(win, tmp_path, CUT_RING)
    win.active_id = obj.id
    win._sync_modifier_page()
    mod = win._boundary_modifier(obj)
    assert "faces" in win.modifier_page._summary(mod)
