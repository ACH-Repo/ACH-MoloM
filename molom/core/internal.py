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

#: What the three kinds are called on the operator/menu side.
DISTANCE = "distance"
ANGLE = "angle"
DIHEDRAL = "dihedral"

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


#: (kind, number of atoms, unit, "what the modal is called")
KINDS = (
    (DISTANCE, 2, "A", "Bond length"),
    (ANGLE, 3, "deg", "Angle"),
    (DIHEDRAL, 4, "deg", "Dihedral"),
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
