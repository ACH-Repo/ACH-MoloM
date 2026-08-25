"""Editing operations on a Structure. Pure functions, fully implemented and
tested — the UI's "editing stubs" dispatch here, so polishing the front-end
later costs no core work.

Conventions:
- atom indices are 0-based;
- deleting atoms REINDEXES bonds (and drops bonds touching deleted atoms);
- add/delete apply across ALL frames of a trajectory (numpy row insert/delete
  per frame), so a trajectory stays consistent;
- functions mutate the structure in place and return it (chainable).
"""

from typing import List, Optional, Sequence, Tuple

import numpy as np

from . import coordination, elements
from .bonding import LONE_PAIRS, TYPICAL_VALENCE
from .structure import Structure


def add_atom(structure, symbol, position, bond_to=None):
    # type: (Structure, str, Sequence[float], Optional[int]) -> Structure
    """Append one atom at `position` (all frames get the same position).
    If `bond_to` is an existing atom index, a single bond to it is added."""
    pos = np.asarray(position, dtype=float).reshape(3)
    structure.symbols.append(str(symbol))
    for k in range(structure.n_frames):
        structure.frames[k] = np.vstack([structure.frames[k], pos])
    if bond_to is not None:
        new_idx = structure.n_atoms - 1
        add_bond(structure, bond_to, new_idx, order=1)
    return structure


def delete_atoms(structure, indices, with_hydrogens=False, report=None):
    # type: (Structure, Sequence[int], bool, Optional[dict]) -> Structure
    """Remove atoms by index; bonds touching them are dropped and the rest
    reindexed.

    `with_hydrogens` also removes the terminal hydrogens hanging off the
    doomed atoms — deleting a carbon and leaving its three H's floating in
    space is never what was meant.

    **Everything keyed by atom index is reindexed with the bonds** (round 80).
    A delete renumbers every atom above it, so any map keyed by index silently
    comes to mean different atoms — the round-42 rule, which this function
    obeyed for the bonds and the cell reference and for nothing else. See
    `_remap_atom_metadata`.

    `report` is filled with `remap` (old index -> new, survivors only) and
    `deleted`, because the caller's own per-atom state — a `MolObject`'s
    colours, labels, hidden set and sphere scales — lives outside the
    structure and cannot be reached from here. `MolObject.delete_atoms` is
    the paired call that uses it.
    """
    doomed = {int(i) for i in indices if 0 <= int(i) < structure.n_atoms}
    if with_hydrogens:
        for i in list(doomed):
            for j in structure.bonded_neighbors(i):
                if elements.atomic_number(structure.symbols[j]) == 1 \
                        and len(structure.bonded_neighbors(j)) == 1:
                    doomed.add(j)
    doomed = sorted(doomed)
    if report is not None:
        report["deleted"] = list(doomed)
        report["remap"] = {i: i for i in range(structure.n_atoms)}
    if not doomed:
        return structure
    doomed_set = set(doomed)
    # old index -> new index for the survivors
    remap = {}
    new = 0
    for old in range(structure.n_atoms):
        if old not in doomed_set:
            remap[old] = new
            new += 1
    structure.symbols = [s for i, s in enumerate(structure.symbols)
                         if i not in doomed_set]
    for k in range(structure.n_frames):
        structure.frames[k] = np.delete(structure.frames[k], doomed, axis=0)
    structure.bonds = [(remap[i], remap[j], o) for i, j, o in structure.bonds
                       if i not in doomed_set and j not in doomed_set]
    _remap_cell_reference(structure, remap, doomed_set)
    _remap_atom_metadata(structure, remap)
    if report is not None:
        report["remap"] = dict(remap)
    return structure


#: Metadata that is a LIST parallel to the atoms.
#:
#: `asym_rows` (round 87) is one entry per DRAWN atom in the asymmetric-unit
#: view, each holding the `_atom_site_` rows that atom stands for - normally
#: one, and four for a solid solution's shared site. Remapping it here is what
#: lets a DELETE work: the drawn atom goes, its whole group of rows goes with
#: it, and `sync_asymmetric_unit` compacts what is left.
_PER_ATOM_LISTS = ("content_of", "site_of", "asym_rows")
#: Metadata that is a dict keyed by atom index (as a string — it round-trips
#: through JSON in a savepoint, where an int key would come back as text).
_PER_ATOM_KEYED = ("site_occupancy",)
#: Metadata that is a list of atom PAIRS.
_PER_ATOM_PAIRS = ("refused_bonds",)


def _remap_atom_metadata(structure, remap):
    """Reindex every per-atom map in the structure's metadata.

    They are listed here rather than each module patching `delete_atoms`,
    because the failure is silent in every case — a map keyed by index stays
    perfectly VALID after a renumbering and simply means something else — so
    the one thing that must not happen is a new one being added and forgotten.
    One place to look, one place to add to.

    What is covered, and what each would do wrong if it were not:
      * `meta_atoms` — a meta centre's geometry and donor distance would
        attach itself to some other atom, which is the bug that put this on
        the open-items list;
      * `site_of` / `content_of` — the crystal columns; an edit would reach
        the wrong symmetry orbit or the wrong set of boundary copies;
      * `site_occupancy` — the occupancy pie spheres would be drawn on
        whichever atom inherited the index;
      * `refused_bonds` — the round-43 override would draw sticks between
        unrelated atoms.
    """
    meta = getattr(structure, "metadata", None)
    if not meta:
        return
    from . import meta as meta_mod
    meta_mod.remap(structure, remap)
    n = structure.n_atoms
    for key in _PER_ATOM_LISTS:
        column = meta.get(key)
        if not column:
            continue
        fresh = [None] * n
        for old, new in remap.items():
            if old < len(column):
                fresh[new] = column[old]
        if any(v is None for v in fresh):
            meta.pop(key, None)     # cannot be trusted; round 51's rule
        else:
            meta[key] = fresh
    for key in _PER_ATOM_KEYED:
        table = meta.get(key)
        if not table:
            continue
        fresh = {str(remap[int(k)]): v for k, v in table.items()
                 if int(k) in remap}
        if fresh:
            meta[key] = fresh
        else:
            meta.pop(key, None)
    for key in _PER_ATOM_PAIRS:
        pairs = meta.get(key)
        if not pairs:
            continue
        fresh = [(remap[int(i)], remap[int(j)]) for i, j in pairs
                 if int(i) in remap and int(j) in remap]
        if fresh:
            meta[key] = fresh
        else:
            meta.pop(key, None)


def _remap_cell_reference(structure, remap, doomed_set):
    """Keep the unit-cell box's reference atoms pointing at the same atoms.

    The box does not have a transform of its own: it is carried by a Kabsch
    fit from a handful of REFERENCE ATOMS recorded at import (round 19), held
    as indices. Deleting an atom renumbers everything after it, so those
    indices silently come to mean different atoms and the fit maps the box
    onto an unrelated set — which is Christian's "when I delete them the unit
    cell boundary flips". The out-of-range guard in `cell_corners_world` never
    fired, because the indices stayed perfectly valid; they just stopped
    meaning what they said.

    Reference atoms that were themselves deleted are dropped. Below three
    points a rigid fit is not determined, so the reference is cleared and the
    box falls back to its stored frame rather than to a wrong one.
    """
    meta = getattr(structure, "metadata", None)
    if not meta or not meta.get("cell_ref_idx"):
        return
    idx = list(meta.get("cell_ref_idx") or ())
    xyz = list(meta.get("cell_ref_xyz") or ())
    if len(xyz) != len(idx):
        meta.pop("cell_ref_idx", None)
        meta.pop("cell_ref_xyz", None)
        return
    kept = [(remap[i], p) for i, p in zip(idx, xyz)
            if i not in doomed_set and i in remap]
    if len(kept) < 3:
        meta.pop("cell_ref_idx", None)
        meta.pop("cell_ref_xyz", None)
        return
    meta["cell_ref_idx"] = [int(i) for i, _p in kept]
    meta["cell_ref_xyz"] = [list(p) for _i, p in kept]


def set_element(structure, indices, symbol):
    # type: (Structure, Sequence[int], str) -> Structure
    """Change the element of the given atoms (position/bonds untouched)."""
    sym = str(symbol)
    if elements.atomic_number(sym) == 0:
        raise ValueError("unknown element symbol: {!r}".format(symbol))
    for i in indices:
        i = int(i)
        if 0 <= i < structure.n_atoms:
            structure.symbols[i] = sym
    return structure


def add_bond(structure, i, j, order=1):
    # type: (Structure, int, int, int) -> Structure
    """Add (or re-order) a bond between existing atoms i and j."""
    i, j = int(i), int(j)
    if i == j:
        raise ValueError("cannot bond an atom to itself")
    for k in (i, j):
        if not 0 <= k < structure.n_atoms:
            raise ValueError("atom index out of range: {}".format(k))
    # 4 = quadruple: real chemistry for metal-metal bonds (Re2Cl8 2-), and
    # the number keys go up to 4, so don't clamp it away at 3.
    order = max(1, min(4, int(order)))
    a, b = (i, j) if i < j else (j, i)
    k = structure.find_bond(a, b)
    if k is None:
        structure.bonds.append((a, b, order))
    else:
        structure.bonds[k] = (a, b, order)
    return structure


def remove_bond(structure, i, j):
    # type: (Structure, int, int) -> Structure
    k = structure.find_bond(int(i), int(j))
    if k is not None:
        structure.bonds.pop(k)
    return structure


def cycle_bond_order(structure, i, j):
    # type: (Structure, int, int) -> int
    """Avogadro-style bond cycling between two atoms: none -> 1 -> 2 -> 3 ->
    none. Returns the resulting order (0 = no bond)."""
    k = structure.find_bond(int(i), int(j))
    if k is None:
        add_bond(structure, i, j, 1)
        return 1
    a, b, o = structure.bonds[k]
    if o >= 3:
        structure.bonds.pop(k)
        return 0
    structure.bonds[k] = (a, b, o + 1)
    return o + 1


def bond_order_sum(structure, i):
    # type: (Structure, int) -> int
    """Sum of bond orders at atom i (its current explicit valence)."""
    total = 0
    for a, b, o in structure.bonds:
        if a == i or b == i:
            total += o
    return total


def free_valence(structure, i):
    # type: (Structure, int) -> Optional[int]
    """Typical valence minus current bond orders, or None when the element
    has no assumed valence (metals — we never guess their H count)."""
    z = elements.atomic_number(structure.symbols[int(i)])
    cap = TYPICAL_VALENCE.get(z)
    if cap is None:
        return None
    return cap - bond_order_sum(structure, int(i))


def _neighbor_dirs(structure, i):
    origin = structure.coords[i]
    nbrs = structure.bonded_neighbors(i)
    if not nbrs:
        return np.zeros((0, 3))
    return structure.coords[nbrs] - origin


def adjust_hydrogens(structure, indices, add=True, remove=True,
                     report=None):
    # type: (Structure, Sequence[int], bool, bool, Optional[dict]) -> Tuple[int, int]
    """Add or remove hydrogens so the given atoms reach their typical
    valence. Returns (n_added, n_removed).

    New hydrogens go on free coordination-template directions (so a CH3
    fragment's fourth H lands on the missing tetrahedral vertex, not merely
    "away from the others"). Excess hydrogens — e.g. after turning a carbon
    into a nitrogen — are removed, plain terminal H first. Atoms whose
    element has no typical valence (metals) are skipped.
    """
    added = removed = 0
    to_delete = []   # type: List[int]
    for raw in sorted({int(i) for i in indices}):
        if not 0 <= raw < structure.n_atoms:
            continue
        if elements.atomic_number(structure.symbols[raw]) == 1:
            continue                        # never re-dress a hydrogen
        deficit = free_valence(structure, raw)
        if deficit is None or deficit == 0:
            continue
        if deficit > 0 and add:
            z_i = elements.atomic_number(structure.symbols[raw])
            dist = (elements.radius_covalent(z_i)
                    + elements.radius_covalent(1))
            origin = structure.coords[raw].copy()
            # ALL the missing directions in one go, from the FINAL VSEPR
            # domain count (bonds + hydrogens + lone pairs). Adding them one
            # at a time re-derived the geometry after every H — a bare carbon
            # went linear, then bent, then trigonal — so methane came out
            # anything but tetrahedral.
            existing = _neighbor_dirs(structure, raw)
            lone = LONE_PAIRS.get(z_i, 0)
            geom = coordination.geometry_for_count(
                len(existing) + deficit + lone)
            if lone:
                # Lone pairs occupy slots we cannot see, so take template
                # vertices rather than letting the bonds spread out into them.
                dirs = coordination.free_directions(
                    existing, geometry=geom, n_needed=deficit)
            else:
                dirs = coordination.repel_directions(existing, deficit,
                                                     geometry=geom)
            for k in range(deficit):
                d = (dirs[k] if k < len(dirs)
                     else np.array([1.0, 0.0, 0.0]))
                add_atom(structure, "H", origin + d * dist, bond_to=raw)
                added += 1
        elif deficit < 0 and remove:
            spare = [j for j in structure.bonded_neighbors(raw)
                     if elements.atomic_number(structure.symbols[j]) == 1
                     and len(structure.bonded_neighbors(j)) == 1
                     and j not in to_delete]
            for j in spare[:-deficit]:
                to_delete.append(j)
                removed += 1
    if to_delete:
        # REMOVING renumbers, and the caller may hold per-atom maps that
        # have to follow (round 80). Adding does not: a new hydrogen is
        # appended, so every existing index still means what it did.
        delete_atoms(structure, to_delete, report=report)
    return added, removed


def ideal_bond_length(structure, i, j):
    # type: (Structure, int, int) -> float
    """The length this bond wants: a META atom's stated distance if one end is
    a meta centre, otherwise the covalent-radius sum.

    A META ATOM'S DISTANCE IS A CONSTRAINT THE USER TYPED, not a default to be
    improved on. Christian: "changing atom types from hydrogen to another
    element on a meta-atom auto adjusts the bond length away from the
    constrained one". It did, and doubly wrongly - the dummy `Xx` is atomic
    number 0 with no covalent radius, so the radius sum was not even a
    meaningful number for the element the centre stands for. The whole promise
    of a locked meta atom is that the distance you set is the distance you
    get (round 62), and swapping a donor's element must not quietly break it.
    """
    from . import meta as meta_mod
    table = meta_mod.all_meta(structure)
    for centre, other in ((int(i), int(j)), (int(j), int(i))):
        spec = table.get(centre)
        if spec is not None and other in structure.bonded_neighbors(centre):
            return float(spec.distance)
    zi = elements.atomic_number(structure.symbols[int(i)])
    zj = elements.atomic_number(structure.symbols[int(j)])
    ri = elements.radius_covalent(zi) or 1.0
    rj = elements.radius_covalent(zj) or 1.0
    return float(ri + rj)


def _shift_atom(structure, i, shift):
    for k in range(structure.n_frames):
        structure.frames[k][i] = structure.frames[k][i] + shift


def adjust_bond_lengths(structure, indices, tol=0.05):
    # type: (Structure, Sequence[int], float) -> int
    """Push bonds to/from the changed atoms out to their covalent length.

    Turning an H into a Zn must lengthen the C-H bond into a C-Zn bond, or
    the new atom sits absurdly close to its neighbour. Only TERMINAL atoms
    are moved (the changed atom itself when it has one neighbour, otherwise
    its terminal neighbours), because moving an atom inside a ring or chain
    would distort geometry the user did not ask to change. Returns how many
    atoms moved.
    """
    moved = 0
    for raw in sorted({int(i) for i in indices}):
        if not 0 <= raw < structure.n_atoms:
            continue
        nbrs = structure.bonded_neighbors(raw)
        if not nbrs:
            continue
        if len(nbrs) == 1:
            targets = [(raw, nbrs[0])]          # move the changed atom
        else:                                   # move its terminal neighbours
            targets = [(j, raw) for j in nbrs
                       if len(structure.bonded_neighbors(j)) == 1]
        for mover, anchor in targets:
            v = structure.coords[mover] - structure.coords[anchor]
            n = float(np.linalg.norm(v))
            if n < 1e-6:
                continue
            want = ideal_bond_length(structure, mover, anchor)
            if abs(want - n) <= tol:
                continue
            _shift_atom(structure, mover, v / n * (want - n))
            moved += 1
    return moved


def idealize_terminal_hydrogens(structure, indices):
    # type: (Structure, Sequence[int]) -> int
    """Re-place the terminal hydrogens around the given atoms on ideal
    coordination directions, keeping every heavy neighbour where it is.

    This is the bit Avogadro leaves to the force field: its "adjust
    hydrogens" only fixes the COUNT, so after drawing a substituent onto a
    CH3 the leftover H's still sit in their old tetrahedral slots. Fitting
    the template to the heavy neighbours and moving only the H's is cheap,
    deterministic, and gets the geometry close enough that a force-field
    clean-up afterwards has nothing dramatic left to do. Returns how many
    hydrogens moved.
    """
    moved = 0
    for raw in sorted({int(i) for i in indices}):
        if not 0 <= raw < structure.n_atoms:
            continue
        if elements.atomic_number(structure.symbols[raw]) == 1:
            continue
        nbrs = structure.bonded_neighbors(raw)
        if len(nbrs) < 2:
            continue                    # nothing to arrange around
        origin = structure.coords[raw]
        hydros = [j for j in nbrs
                  if elements.atomic_number(structure.symbols[j]) == 1
                  and len(structure.bonded_neighbors(j)) == 1]
        heavy = [j for j in nbrs if j not in hydros]
        if not hydros or not heavy:
            continue
        heavy_dirs = structure.coords[heavy] - origin
        # Relaxation rather than a rigid template: the heavy neighbours can
        # sit at any angle (a just-drawn substituent lands where it was
        # dropped), and a fitted template would then put an H on top of one.
        free = coordination.repel_directions(heavy_dirs, len(hydros))
        for j, d in zip(hydros, free):
            dist = ideal_bond_length(structure, raw, j)
            target = origin + np.asarray(d, dtype=float) * dist
            _shift_atom(structure, j, target - structure.coords[j])
            moved += 1
    return moved


def set_element_adjusted(structure, indices, symbol, adjust_h=True,
                         adjust_lengths=True, report=None):
    # type: (Structure, Sequence[int], str, bool, bool, Optional[dict]) -> Tuple[int, int]
    """Change element(s), stretch their bonds to the new covalent length, and
    re-dress their hydrogens (the edit-mode draw tool's behaviour: C -> N
    drops an H, H -> Zn lengthens the bond it hangs off)."""
    set_element(structure, indices, symbol)
    if adjust_lengths:
        adjust_bond_lengths(structure, indices)
    if not adjust_h:
        return (0, 0)
    return adjust_hydrogens(structure, indices, report=report)


def suggested_position(structure, bond_to=None, distance=None, symbol="C"):
    # type: (Structure, Optional[int], Optional[float], str) -> np.ndarray
    """Where to place a NEW atom: covalent-distance away from `bond_to` in the
    least-crowded direction, or just right of the molecule when unattached.
    Keeps the add-atom stub usable before a real 3D placement tool exists."""
    z_new = elements.atomic_number(symbol)
    if structure.n_atoms == 0 or bond_to is None or \
            not 0 <= int(bond_to) < structure.n_atoms:
        if structure.n_atoms == 0:
            return np.zeros(3)
        c = structure.centroid()
        span = structure.coords[:, 0].max() - c[0]
        return c + np.array([span + 1.5, 0.0, 0.0])
    i = int(bond_to)
    z_i = elements.atomic_number(structure.symbols[i])
    if distance is None:
        distance = elements.radius_covalent(z_i) + elements.radius_covalent(z_new)
    # Least-crowded direction: opposite the mean unit vector to the neighbours.
    origin = structure.coords[i]
    nbrs = structure.bonded_neighbors(i)
    if nbrs:
        vecs = structure.coords[nbrs] - origin
        norms = np.linalg.norm(vecs, axis=1)
        norms[norms == 0.0] = 1.0
        mean_dir = (vecs / norms[:, None]).mean(axis=0)
        if np.linalg.norm(mean_dir) > 1e-6:
            direction = -mean_dir / np.linalg.norm(mean_dir)
        else:   # symmetric neighbours (e.g. linear) — pick any perpendicular
            direction = _any_perpendicular(vecs[0])
    else:
        direction = np.array([1.0, 0.0, 0.0])
    return origin + direction * float(distance)


def _any_perpendicular(v):
    # type: (np.ndarray) -> np.ndarray
    v = np.asarray(v, float)
    n = np.linalg.norm(v)
    if n == 0.0:
        return np.array([1.0, 0.0, 0.0])
    v = v / n
    other = np.array([1.0, 0.0, 0.0]) if abs(v[0]) < 0.9 else \
        np.array([0.0, 1.0, 0.0])
    p = np.cross(v, other)
    return p / np.linalg.norm(p)
