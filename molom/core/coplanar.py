"""Make a substituent coplanar with the ring it hangs off.

Christian's ask (2026-08-06): "some kind of way to ensure that if I add a
substituent to an imidazolate ring, the substituent is coplanar with the
plane." It is the geometric statement behind a chemical fact — an sp2 ring
carbon's substituent lies in the ring plane, and conjugation keeps a planar
substituent flat with it — and it is exactly the operation a Cartesian editor
cannot do by dragging.

The whole thing is a RIGID motion of the substituent, never a projection.
Flattening by projecting atoms onto the plane would shorten every bond that
was out of it, so the result is coplanar and chemically wrong. Instead the
group is rotated twice about the atom it is attached to:

1. swing the attachment BOND into the plane, and
2. spin the group about that bond until it lies flattest.

Step 2 has a closed form. With `d` the (now in-plane) bond axis, `n` the plane
normal and `u = n x d`, an atom at `r` from the anchor has out-of-plane
component `a sin(t) + b cos(t)` after a spin of `t`, where `a = r.u` and
`b = r.n`. Minimising the sum of squares over the group gives
`t = (atan2(B, (C-A)/2) + pi) / 2` for `A = sum a^2`, `B = sum a*b`,
`C = sum b^2` — one atan2, no iteration, and it lands on the MINIMUM rather
than the maximum because of the explicit `+ pi`.

UI-free, like everything in `core`.
"""

from typing import List, Optional, Sequence, Tuple

import numpy as np

from .align import best_fit_plane
from .rotations import axis_angle_mat3, rotate_points_about

_EPS = 1e-9

#: Largest ring worth treating as "the plane this substituent belongs to".
#: Imidazolates and benzenes are 5 and 6; beyond about 8 a cycle is not planar
#: in any useful sense and fitting a plane to it says nothing.
MAX_RING = 8


def ring_through(index, bonds, n_atoms, max_size=MAX_RING):
    # type: (int, Sequence, int, int) -> Optional[List[int]]
    """The smallest ring containing `index`, or None if it is not in one.

    Breadth-first from the atom, looking for the shortest cycle back to it.
    Small by construction — an imidazolate's 5 beats the 8 of a fused pair —
    because the SMALLEST ring is the one whose plane the substituent is
    conjugated with.
    """
    n = int(n_atoms)
    start = int(index)
    if not (0 <= start < n):
        return None
    adj = [[] for _ in range(n)]
    for bond in bonds:
        i, j = int(bond[0]), int(bond[1])
        if 0 <= i < n and 0 <= j < n and i != j:
            adj[i].append(j)
            adj[j].append(i)
    best = None
    # One BFS per neighbour: drop the start-neighbour edge, then the shortest
    # path from that neighbour back to the start closes the smallest cycle
    # through it. Cheap for the sizes a molecule editor deals with.
    for first in adj[start]:
        prev = {first: start}
        seen = {start, first}
        queue = [first]
        while queue:
            nxt = []
            for node in queue:
                for other in adj[node]:
                    if other == start:
                        if node == first:
                            continue          # the edge we came along
                        path, walk = [start], node
                        while walk != start:
                            path.append(walk)
                            walk = prev[walk]
                        if len(path) <= max_size and (best is None
                                                      or len(path) < len(best)):
                            best = path
                        continue
                    if other in seen:
                        continue
                    seen.add(other)
                    prev[other] = node
                    nxt.append(other)
            if best is not None and len(best) <= len(seen):
                break
            queue = nxt
    return best


def plane_of(coords, indices):
    # type: (np.ndarray, Sequence[int]) -> Optional[Tuple[np.ndarray, np.ndarray]]
    """(point, unit normal) of the least-squares plane through those atoms."""
    rows = [int(i) for i in indices]
    if len(rows) < 3:
        return None
    pts = np.asarray(coords, dtype=float)[rows]
    centroid, normal = best_fit_plane(pts)
    norm = float(np.linalg.norm(normal))
    if norm < _EPS:
        return None
    return centroid, np.asarray(normal, dtype=float) / norm


def flatness(coords, indices, point, normal):
    # type: (np.ndarray, Sequence[int], np.ndarray, np.ndarray) -> float
    """RMS distance of those atoms from the plane, in Angstrom.

    The number the operator reports, so "coplanar" is a measurement rather
    than a claim.
    """
    rows = [int(i) for i in indices]
    if not rows:
        return 0.0
    pts = np.asarray(coords, dtype=float)[rows]
    d = (pts - np.asarray(point, dtype=float)) @ np.asarray(normal, dtype=float)
    return float(np.sqrt(np.mean(d * d)))


def _swing_into_plane(coords, moving, stay, attach, normal, outward):
    """Rotate the group so the stay->attach BOND lies in the plane."""
    out = np.array(coords, dtype=float)
    base = out[stay]
    vec = out[attach] - base
    length = float(np.linalg.norm(vec))
    if length < _EPS:
        return out
    in_plane = vec - float(vec @ normal) * normal
    if float(np.linalg.norm(in_plane)) < _EPS:
        # The bond points straight through the plane, so "its in-plane part"
        # is undefined. Fall back to pointing away from the ring, which is
        # where a substituent goes.
        in_plane = np.asarray(outward, dtype=float)
        if float(np.linalg.norm(in_plane)) < _EPS:
            return out
    target = in_plane / float(np.linalg.norm(in_plane)) * length
    axis = np.cross(vec, target)
    scale = float(np.linalg.norm(axis))
    if scale < _EPS:
        return out                       # already in plane (or exactly anti)
    angle = float(np.arctan2(scale, float(vec @ target)))
    rows = sorted(int(m) for m in moving)
    out[rows] = rotate_points_about(out[rows],
                                    axis_angle_mat3(axis, angle), base)
    return out


def _spin_flattest(coords, moving, stay, attach, normal):
    """Spin the group about its bond until it lies flattest in the plane."""
    out = np.array(coords, dtype=float)
    base = out[stay]
    axis = out[attach] - base
    length = float(np.linalg.norm(axis))
    if length < _EPS:
        return out
    d = axis / length
    n = np.asarray(normal, dtype=float)
    u = np.cross(n, d)
    if float(np.linalg.norm(u)) < _EPS:
        return out
    u = u / float(np.linalg.norm(u))
    rows = sorted(int(m) for m in moving)
    a_sum = b_sum = ab_sum = 0.0
    for row in rows:
        r = out[row] - base
        a = float(r @ u)
        b = float(r @ n)
        a_sum += a * a
        b_sum += b * b
        ab_sum += a * b
    if abs(ab_sum) < _EPS and abs(b_sum - a_sum) < _EPS:
        return out                       # already flat, or nothing off-axis
    # + pi picks the MINIMUM of the sum of squares; without it this lands on
    # the maximum exactly as often.
    theta = 0.5 * (float(np.arctan2(ab_sum, 0.5 * (b_sum - a_sum))) + np.pi)
    out[rows] = rotate_points_about(out[rows],
                                    axis_angle_mat3(d, theta), base)
    return out


def make_coplanar(coords, moving, stay, attach, ring=None, normal=None,
                  point=None):
    # type: (np.ndarray, Sequence[int], int, int, Optional[Sequence[int]], object, object) -> np.ndarray
    """Rotate `moving` rigidly until it lies in the ring's plane.

    `stay` is the ring atom the group hangs off and never moves; `attach` is
    the group's own first atom, bonded to it. Give either a `ring` (its atoms
    define the plane) or an explicit `normal`/`point`.

    Bond lengths and every internal angle of the group are preserved exactly,
    because this is two rotations about `stay` and nothing else.
    """
    xyz = np.asarray(coords, dtype=float)
    if normal is None or point is None:
        if not ring:
            return np.array(xyz)
        found = plane_of(xyz, ring)
        if found is None:
            return np.array(xyz)
        point, normal = found
    normal = np.asarray(normal, dtype=float)
    norm = float(np.linalg.norm(normal))
    if norm < _EPS:
        return np.array(xyz)
    normal = normal / norm
    stay, attach = int(stay), int(attach)
    outward = xyz[stay] - np.asarray(point, dtype=float)
    outward = outward - float(outward @ normal) * normal
    out = _swing_into_plane(xyz, moving, stay, attach, normal, outward)
    return _spin_flattest(out, moving, stay, attach, normal)
