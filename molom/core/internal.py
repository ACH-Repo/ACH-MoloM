"""Editing INTERNAL COORDINATES — a bond length, a valence angle, a torsion —
with the rest of the molecule following.

This is the operation every chemistry editor has and a pure Cartesian one
does not: "make this bond 1.54 A" must not drag one atom out of its
substituent, it must slide the whole trailing fragment along the bond axis so
every other length and angle in the molecule is left exactly as it was. Same
for an angle (the far fragment swings about the vertex) and a torsion (the far
fragment spins about the central bond). That is what makes it worth a modal of
its own rather than "select an atom and press G".

The whole job is therefore two steps, and only the first is interesting:

1. **Split the molecule** at the bond being edited. Everything reachable from
   the moving atom WITHOUT crossing back through the anchor is the part that
   follows. If the anchor is reachable anyway the two atoms are in a RING, and
   there is no split: pulling them apart would have to break a second bond, so
   only the atom itself can move and the caller is told as much.
2. **Apply one rigid transform** to that set — a translation along the bond,
   or a rotation about the vertex/central axis.

A fourth operation, `torsion_split` + `set_twist`, is the same idea driven by
a SELECTION rather than by an ordered pick list: spin a terminal group (a
methyl, an OH, a whole phenyl) about the single bond that holds it on. The
maths is a torsion; all the work is deciding which fragment the user meant.

Sign conventions are pinned against `core.measure`, which is the same atan2
dihedral convention ORCA and ORCA Workbench use: rotating the moving side
about (p_k - p_j) by +theta raises the i-j-k-l dihedral by exactly theta, and
rotating about (p_i - p_j) x (p_k - p_j) by +phi raises the i-j-k angle by
phi. The round trips are tested rather than argued.

UI-free numpy, like everything else in `core/`.
"""

from typing import List, Optional, Sequence, Set, Tuple

import numpy as np

from . import measure
from .rotations import axis_angle_mat3, rotate_points_about

#: What the kinds are called on the operator/menu side.
DISTANCE = "distance"
ANGLE = "angle"
DIHEDRAL = "dihedral"
#: The odd one out: a RELATIVE spin of a whole terminal group about the single
#: bond that holds it on (a methyl rotor). It takes a SELECTION rather than an
#: ordered pick list, and its value is a change, not a coordinate — see
#: `torsion_split`.
TWIST = "twist"

#: Below this the geometry is degenerate and no sensible axis exists.
_EPS = 1e-9


def _adjacency(n_atoms, bonds):
    # type: (int, Sequence) -> List[List[int]]
    adj = [[] for _ in range(int(n_atoms))]
    for bond in bonds:
        a, b = int(bond[0]), int(bond[1])
        if 0 <= a < n_atoms and 0 <= b < n_atoms:
            adj[a].append(b)
            adj[b].append(a)
    return adj


def moving_group(n_atoms, bonds, anchor, mover):
    # type: (int, Sequence, int, int) -> Tuple[Set[int], bool]
    """Which atoms follow `mover` when the anchor-mover distance changes.

    Returns `(indices, blocked)`. The set is everything reachable from `mover`
    without stepping onto `anchor`; `blocked` is True when `anchor` turns out
    to be reachable ANYWAY, by some route other than the direct bond, so no
    clean two-part split exists. In that case only `mover` itself is returned
    — moving more would silently deform whatever holds the two together, and
    refusing outright would be worse than the honest minimum.

    Two things land in the blocked case, and both deserve to:

    * a RING — pulling two ring atoms apart would have to break a second bond;
    * a pair that is NOT directly bonded but sits in one fragment (a 1,3
      contact, say), where "which side is the far side" has no answer.

    Picks in two DIFFERENT fragments split cleanly, so setting a "bond length"
    between two molecules simply slides the second molecule — a genuinely
    useful thing to do, and the reason this is not restricted to real bonds.
    """
    anchor, mover = int(anchor), int(mover)
    adj = _adjacency(n_atoms, bonds)
    seen = {mover}
    stack = [mover]
    blocked = False
    while stack:
        i = stack.pop()
        for j in adj[i]:
            if j == anchor:
                # Only the DIRECT anchor-mover bond is the cut; reaching the
                # anchor from anywhere else means a second route exists.
                if i != mover:
                    blocked = True
                continue
            if j not in seen:
                seen.add(j)
                stack.append(j)
    if blocked:
        return {mover}, True
    return seen, False


def _edge_adjacency(n_atoms, bonds):
    # type: (int, Sequence) -> Tuple[List[List[Tuple[int, int]]], List[Tuple[int, int]]]
    """Adjacency as (neighbour, edge id), plus the de-duplicated edge list.

    Edge IDs matter here in a way they do not for `moving_group`: the bridge
    search must skip the edge it arrived BY, and doing that by atom index
    instead would also skip a genuine second bond between the same pair — and
    a duplicated bond in the input would silently turn a real bridge into a
    ring.
    """
    n = int(n_atoms)
    adj = [[] for _ in range(n)]        # type: List[List[Tuple[int, int]]]
    edges = []                          # type: List[Tuple[int, int]]
    seen = set()
    for bond in bonds:
        a, b = int(bond[0]), int(bond[1])
        if a == b or not (0 <= a < n and 0 <= b < n):
            continue
        key = (min(a, b), max(a, b))
        if key in seen:
            continue
        seen.add(key)
        eid = len(edges)
        edges.append(key)
        adj[a].append((b, eid))
        adj[b].append((a, eid))
    return adj, edges


def _bridge_edges(adj, n_atoms):
    # type: (List[List[Tuple[int, int]]], int) -> Set[int]
    """Every bond whose removal disconnects the molecule (Tarjan, iterative).

    A bond that is NOT a bridge lies on a ring, and cutting a ring bond does
    not give two parts — which is exactly the case `torsion_split` must
    refuse. Recursion was avoided on purpose: a 3000-atom framework is far
    past CPython's default limit and this runs on import-sized structures.
    """
    n = int(n_atoms)
    disc = [-1] * n
    low = [0] * n
    out = set()                          # type: Set[int]
    timer = 0
    for root in range(n):
        if disc[root] != -1:
            continue
        disc[root] = low[root] = timer
        timer += 1
        stack = [(root, -1, iter(adj[root]))]
        while stack:
            v, parent_edge, it = stack[-1]
            pushed = False
            for w, eid in it:
                if eid == parent_edge:
                    continue
                if disc[w] == -1:
                    disc[w] = low[w] = timer
                    timer += 1
                    stack.append((w, eid, iter(adj[w])))
                    pushed = True
                    break
                low[v] = min(low[v], disc[w])
            if pushed:
                continue
            stack.pop()
            if stack:
                u = stack[-1][0]
                low[u] = min(low[u], low[v])
                if low[v] > disc[u]:
                    out.add(parent_edge)
    return out


def _ring_blocks(adj, n_atoms, bridges):
    # type: (List[List[Tuple[int, int]]], int, Set[int]) -> Tuple[List[int], List[List[int]]]
    """Collapse the molecule to its 2-edge-connected components.

    Everything inside one component is joined by at least two routes (a ring
    system), so no single bond can separate it; the components and the bridges
    between them form a TREE, and every possible "cut one bond" split of the
    molecule is one edge of that tree. Searching the tree instead of the atoms
    is what keeps this linear.
    """
    n = int(n_atoms)
    comp = [-1] * n
    members = []                         # type: List[List[int]]
    for start in range(n):
        if comp[start] != -1:
            continue
        cid = len(members)
        comp[start] = cid
        group = [start]
        stack = [start]
        while stack:
            i = stack.pop()
            for j, eid in adj[i]:
                if eid in bridges or comp[j] != -1:
                    continue
                comp[j] = cid
                group.append(j)
                stack.append(j)
        members.append(group)
    return comp, members


def _subtree_atoms(tree, parent, members, node):
    # type: (List[List[Tuple[int, int]]], dict, List[List[int]], int) -> Set[int]
    """Atoms of `node` and everything hanging below it in the rooted tree."""
    out = set()                          # type: Set[int]
    stack = [node]
    while stack:
        c = stack.pop()
        out.update(members[c])
        for d, _eid in tree[c]:
            if parent.get(d, (None, None))[0] == c:
                stack.append(d)
    return out


def torsion_split(n_atoms, bonds, selected):
    # type: (int, Sequence, Sequence[int]) -> Optional[Tuple[Set[int], int, int]]
    """The rotor a selection implies: `(moving, anchor, pivot)`, or None.

    This is the "spin a methyl group about its C-R bond" operation, and the
    interesting half is deciding what the group IS. The user selects the
    *idea* of a group — one hydrogen of it, the three hydrogens, the carbon,
    or the whole thing — and expects the same rotor every time. So instead of
    rotating the literal selection (which does nothing at all when the atom
    picked sits on the axis) this finds the **smallest fragment that contains
    the whole selection and hangs off the rest of the molecule by exactly one
    bond**. That bond is the axis, its inner end is the pivot and its outer
    end is the anchor that stays put.

    Two guards, both of which refuse rather than do something useless:

    * a candidate needs at least two atoms on EACH side. A moving side of one
      atom sits on its own axis and cannot move; an anchor side of one atom
      (rotating everything about a terminal C-H) is a rigid rotation of the
      whole molecule, which is what R is for.
    * the cut bond must be a bridge, so a selection inside a ring — half a
      cyclohexane, an aromatic CH — yields nothing. There is no single bond
      that frees it, and pretending otherwise would deform the ring.
    """
    n = int(n_atoms)
    sel = sorted({int(i) for i in selected if 0 <= int(i) < n})
    if not sel:
        return None
    adj, edges = _edge_adjacency(n, bonds)
    bridges = _bridge_edges(adj, n)
    if not bridges:
        return None
    comp, members = _ring_blocks(adj, n, bridges)
    tree = [[] for _ in members]         # type: List[List[Tuple[int, int]]]
    for eid in bridges:
        a, b = edges[eid]
        tree[comp[a]].append((comp[b], eid))
        tree[comp[b]].append((comp[a], eid))
    # Root the tree at the selection, then walk it once: `order` is a preorder,
    # so accumulating sizes in reverse gives every subtree in one pass.
    root = comp[sel[0]]
    parent = {root: (None, None)}
    order = [root]
    stack = [root]
    while stack:
        c = stack.pop()
        for d, eid in tree[c]:
            if d in parent:
                continue
            parent[d] = (c, eid)
            order.append(d)
            stack.append(d)
    if any(comp[i] not in parent for i in sel):
        return None                      # selection spans separate molecules
    size = {c: len(members[c]) for c in order}
    picked = {c: 0 for c in order}
    for i in sel:
        picked[comp[i]] += 1
    total_atoms = sum(size[c] for c in order)
    total_sel = len(sel)
    for c in reversed(order[1:]):
        up = parent[c][0]
        size[up] += size[c]
        picked[up] += picked[c]
    best = None                          # (moving size, node, side)
    for c in order[1:]:
        below, rest = size[c], total_atoms - size[c]
        if picked[c] == total_sel:       # the selection is all BELOW the cut
            moving_n, fixed_n, side = below, rest, "below"
        elif picked[c] == 0:             # ...all above it
            moving_n, fixed_n, side = rest, below, "above"
        else:
            continue                     # the cut runs through the selection
        if moving_n < 2 or fixed_n < 2:
            continue
        if best is None or moving_n < best[0]:
            best = (moving_n, c, side)
    if best is None:
        return None
    _n, node, side = best
    below_atoms = _subtree_atoms(tree, parent, members, node)
    if side == "below":
        moving = below_atoms
    else:
        moving = {i for c in order for i in members[c]} - below_atoms
    a, b = edges[parent[node][1]]
    pivot, anchor = (a, b) if a in moving else (b, a)
    return moving, anchor, pivot


def set_twist(coords, moving, anchor, pivot, angle_deg):
    # type: (np.ndarray, Sequence, int, int, float) -> np.ndarray
    """Spin `moving` about the anchor->pivot axis by `angle_deg`.

    A RELATIVE rotation, unlike the three setters above: a rotor has no
    natural zero to set — which of a methyl's three hydrogens would define it?
    — so the modal starts at 0 and the number is how far you have turned it.
    The sign follows `set_dihedral`: +theta raises every x-anchor-pivot-y
    torsion by exactly theta, since the axis line is the same one.
    """
    out = np.array(coords, dtype=float)
    anchor, pivot = int(anchor), int(pivot)
    axis = out[pivot] - out[anchor]
    if float(np.linalg.norm(axis)) < _EPS:
        return out
    rows = sorted(int(m) for m in moving)
    if rows:
        out[rows] = rotate_points_about(
            out[rows], axis_angle_mat3(axis, np.radians(float(angle_deg))),
            out[pivot])
    return out


def split_for(kind, n_atoms, bonds, picks):
    # type: (str, int, Sequence, Sequence) -> Tuple[Set[int], bool]
    """The moving set for one of the three edits, from picks in click order.

    The cut is always the LAST bond of the internal coordinate, so the tail of
    the selection is what moves and the head stays put: i-[j] for a distance,
    j-[k] for an angle, and j-[k] for a torsion (the whole k/l side swings).
    """
    picks = [int(p) for p in picks]
    if kind == DISTANCE:
        return moving_group(n_atoms, bonds, picks[0], picks[1])
    if kind == ANGLE:
        return moving_group(n_atoms, bonds, picks[1], picks[2])
    if kind == DIHEDRAL:
        return moving_group(n_atoms, bonds, picks[1], picks[2])
    raise ValueError("unknown internal coordinate: {!r}".format(kind))


def current_value(kind, coords, picks):
    # type: (str, np.ndarray, Sequence) -> float
    """The coordinate's present value — Angstrom for a distance, degrees for
    an angle or a torsion."""
    c = np.asarray(coords, dtype=float)
    p = [int(x) for x in picks]
    if kind == DISTANCE:
        return measure.distance(c[p[0]], c[p[1]])
    if kind == ANGLE:
        return measure.angle(c[p[0]], c[p[1]], c[p[2]])
    if kind == DIHEDRAL:
        return measure.dihedral(c[p[0]], c[p[1]], c[p[2]], c[p[3]])
    if kind == TWIST:
        return 0.0                       # relative: it starts where it starts
    raise ValueError("unknown internal coordinate: {!r}".format(kind))


def set_distance(coords, moving, i, j, target):
    # type: (np.ndarray, Sequence, int, int, float) -> np.ndarray
    """Slide `moving` along the i->j direction until |ij| == target.

    A pure translation, so every bond length and angle inside the moving
    fragment is preserved exactly — the point of the whole exercise.
    """
    out = np.array(coords, dtype=float)
    v = out[int(j)] - out[int(i)]
    length = float(np.linalg.norm(v))
    if length < _EPS:
        return out
    rows = sorted(int(m) for m in moving)
    if rows:
        out[rows] += v / length * (float(target) - length)
    return out


def set_angle(coords, moving, i, j, k, target_deg):
    # type: (np.ndarray, Sequence, int, int, int, float) -> np.ndarray
    """Swing `moving` about the vertex j until the i-j-k angle == target.

    The rotation axis is the plane normal (p_i - p_j) x (p_k - p_j), about
    which a positive turn OPENS the angle (pinned by a round-trip test). A
    collinear i-j-k has no plane and therefore no defined swing direction, so
    any perpendicular is picked rather than producing NaNs.
    """
    out = np.array(coords, dtype=float)
    i, j, k = int(i), int(j), int(k)
    a, b = out[i] - out[j], out[k] - out[j]
    if np.linalg.norm(a) < _EPS or np.linalg.norm(b) < _EPS:
        return out
    axis = np.cross(a, b)
    if float(np.linalg.norm(axis)) < 1e-8:
        axis = _any_perpendicular(b)
    delta = np.radians(float(target_deg) - measure.angle(out[i], out[j],
                                                         out[k]))
    rows = sorted(int(m) for m in moving)
    if rows:
        out[rows] = rotate_points_about(out[rows],
                                        axis_angle_mat3(axis, delta), out[j])
    return out


def set_dihedral(coords, moving, i, j, k, l, target_deg):
    # type: (np.ndarray, Sequence, int, int, int, int, float) -> np.ndarray
    """Spin `moving` about the j-k axis until the i-j-k-l torsion == target.

    Rotating about (p_k - p_j) by +theta raises the dihedral by exactly theta
    under `measure.dihedral`'s atan2 convention: both plane normals are
    perpendicular to the axis, so the rotation adds theta to the second
    normal's angle and nothing else moves.
    """
    out = np.array(coords, dtype=float)
    i, j, k, l = int(i), int(j), int(k), int(l)
    axis = out[k] - out[j]
    if float(np.linalg.norm(axis)) < _EPS:
        return out
    delta = np.radians(float(target_deg)
                       - measure.dihedral(out[i], out[j], out[k], out[l]))
    rows = sorted(int(m) for m in moving)
    if rows:
        out[rows] = rotate_points_about(out[rows],
                                        axis_angle_mat3(axis, delta), out[j])
    return out


def apply(kind, coords, moving, picks, target):
    # type: (str, np.ndarray, Sequence, Sequence, float) -> np.ndarray
    """Dispatch to the right setter — what the modal actually calls."""
    p = [int(x) for x in picks]
    if kind == DISTANCE:
        return set_distance(coords, moving, p[0], p[1], target)
    if kind == ANGLE:
        return set_angle(coords, moving, p[0], p[1], p[2], target)
    if kind == DIHEDRAL:
        return set_dihedral(coords, moving, p[0], p[1], p[2], p[3], target)
    if kind == TWIST:
        return set_twist(coords, moving, p[0], p[1], target)
    raise ValueError("unknown internal coordinate: {!r}".format(kind))


def _any_perpendicular(v):
    # type: (np.ndarray) -> np.ndarray
    """Some unit vector perpendicular to v (v assumed non-zero)."""
    v = np.asarray(v, dtype=float)
    other = np.array([1.0, 0.0, 0.0])
    if abs(float(v @ other)) > 0.9 * float(np.linalg.norm(v)):
        other = np.array([0.0, 1.0, 0.0])
    out = np.cross(v, other)
    return out / float(np.linalg.norm(out))


#: (kind, number of atoms, unit, "what the modal is called"). TWIST carries
#: None because it is not chosen by a pick COUNT — any selection that resolves
#: to a rotor offers it, so `kind_for_count` must never return it.
KINDS = (
    (DISTANCE, 2, "A", "Bond length"),
    (ANGLE, 3, "deg", "Angle"),
    (DIHEDRAL, 4, "deg", "Dihedral"),
    (TWIST, None, "deg", "Twist"),
)


def kind_for_count(n_picks):
    # type: (int) -> Optional[str]
    """Which edit a selection of this size implies — 2 atoms a length, 3 an
    angle, 4 a torsion. None for anything else, which is what makes the
    right-click menu build itself from the selection."""
    for kind, count, _unit, _label in KINDS:
        if count == int(n_picks):
            return kind
    return None


def unit_for(kind):
    # type: (str) -> str
    for k, _count, unit, _label in KINDS:
        if k == kind:
            return unit
    return ""


def label_for(kind):
    # type: (str) -> str
    for k, _count, _unit, label in KINDS:
        if k == kind:
            return label
    return kind
