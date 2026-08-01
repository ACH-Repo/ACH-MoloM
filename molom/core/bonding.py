"""Bond perception — a faithful port of Avogadro 2's rule.

Source: avogadrolibs `Molecule::perceiveBondsSimple(tolerance=0.45,
minDistance=0.32)` (avogadro/core/molecule.cpp):

    bond(i, j)  iff  minDistance^2 < d^2 < (r_cov(i) + r_cov(j) + tolerance)^2

with two chemistry guards: atoms whose element is He/Ne/Ar/Kr never bond, and
H-H pairs never bond. Covalent radii <= 0 fall back to 2.0 Angstrom (dummy
atoms). All perceived bonds are single (order 1) — order assignment is an
editing/format concern, not a distance one.
"""

from typing import List, Tuple

import numpy as np

from . import elements

TOLERANCE = 0.45       # Angstrom, Avogadro default
MIN_DISTANCE = 0.32    # Angstrom, Avogadro default
_NOBLE = frozenset((2, 10, 18, 36))   # He, Ne, Ar, Kr

# Pairs per numpy block in the O(N^2) sweep — bounds peak memory (~3 float64
# arrays of this length) while keeping the vectorised inner loop long.
_BLOCK = 2 ** 20


def covalent_radii(symbols):
    # type: (List[str]) -> np.ndarray
    """Per-atom covalent radii with Avogadro's <=0 -> 2.0 fallback."""
    r = np.array([elements.radius_covalent(elements.atomic_number(s))
                  for s in symbols], dtype=float)
    r[r <= 0.0] = 2.0
    return r

def perceive_bonds(symbols, coords, tolerance=TOLERANCE, min_distance=MIN_DISTANCE):
    # type: (List[str], np.ndarray, float, float) -> List[Tuple[int, int, int]]
    """Perceive bonds from geometry. Returns [(i, j, 1), ...] with i < j.

    Vectorised numpy over all unique pairs, processed in blocks so a large
    molecule doesn't allocate an N^2 matrix at once. For the sizes a molecule
    builder edits (10^2..10^4 atoms) this is comfortably fast without a
    spatial index.
    """
    n = len(symbols)
    if n < 2:
        return []
    xyz = np.asarray(coords, dtype=float).reshape(n, 3)
    radii = covalent_radii(symbols)
    z = np.array([elements.atomic_number(s) for s in symbols], dtype=int)
    noble = np.isin(z, list(_NOBLE))
    hydrogen = z == 1

    ii, jj = np.triu_indices(n, k=1)
    bonds = []  # type: List[Tuple[int, int, int]]
    min_sq = float(min_distance) ** 2
    for s in range(0, ii.size, _BLOCK):
        bi = ii[s:s + _BLOCK]
        bj = jj[s:s + _BLOCK]
        diff = xyz[bi] - xyz[bj]
        d2 = np.einsum("ij,ij->i", diff, diff)
        cutoff = radii[bi] + radii[bj] + tolerance
        ok = (d2 < cutoff * cutoff) & (d2 > min_sq)
        ok &= ~(noble[bi] | noble[bj])          # noble gases never auto-bond
        ok &= ~(hydrogen[bi] & hydrogen[bj])    # no H-H bonds
        for a, b in zip(bi[ok], bj[ok]):
            bonds.append((int(a), int(b), 1))
    return bonds


def perceive_structure_bonds(structure, tolerance=TOLERANCE,
                             min_distance=MIN_DISTANCE, keep_orders=True):
    # type: (object, float, float, bool) -> None
    """Re-perceive `structure.bonds` in place from the current frame.

    With keep_orders=True (default), a re-perceived bond that already existed
    keeps its user-assigned order, so switching trajectory frames or nudging
    an atom doesn't silently flatten a drawn double bond back to single.

    NOTE: this is never called automatically after an edit (round 6 —
    dragging an atom away used to silently break its bonds, and a force field
    run must not fight the user over connectivity). Bonds are perceived ONCE
    on import and thereafter only on explicit request (Ctrl+P).
    """
    old = {(i, j): o for i, j, o in structure.bonds} if keep_orders else {}
    fresh = perceive_bonds(structure.symbols, structure.coords,
                           tolerance=tolerance, min_distance=min_distance)
    structure.bonds = [(i, j, old.get((i, j), 1)) for i, j, _ in fresh]


# --------------------------------------------------------------- bond orders
# Typical maximum valence (sum of bond orders) for elements whose bond orders
# we are willing to raise. Anything absent — every metal, most metalloids — is
# left at order 1: guessing multiplicity around a metal centre is exactly the
# fight a user preparing a coordination complex does not want.
# Lone pairs on a neutral, typically-bonded atom. They take up coordination
# slots without being atoms, which is why ammonia is pyramidal and water bent
# rather than the flat/linear arrangements pure repulsion between the bonds
# would give.
LONE_PAIRS = {
    5: 0, 6: 0, 7: 1, 8: 2, 9: 3,
    14: 0, 15: 1, 16: 2, 17: 3,
    32: 0, 33: 1, 34: 2, 35: 3, 53: 3,
}

TYPICAL_VALENCE = {
    1: 1, 5: 3, 6: 4, 7: 3, 8: 2, 9: 1,
    14: 4, 15: 3, 16: 2, 17: 1,
    32: 4, 33: 3, 34: 2, 35: 1, 53: 1,
}

# d / (r_cov_i + r_cov_j) below which a bond looks like a double / triple.
# Reference ratios with Pyykko radii: C-C 1.03, C=C 0.89, C#C 0.80,
# aromatic C~C 0.93, C-O 1.04, C=O 0.88, C-N 1.01, C=N 0.88, C#N 0.80.
DOUBLE_RATIO = 0.95
TRIPLE_RATIO = 0.83


def perceive_bond_orders(symbols, coords, bonds):
    # type: (List[str], np.ndarray, List[Tuple[int, int, int]]) -> List[Tuple[int, int, int]]
    """Assign bond orders 1/2/3 from geometry, capped by typical valence.

    Bonds are considered shortest-relative-first and raised toward the order
    their length suggests, but only while BOTH atoms still have spare
    valence. The valence cap is what makes rings come out Kekule-alternating
    (a benzene ring's six equal bonds cannot all be double) instead of
    every ring bond claiming a double.

    Returns a new bond list; the input is not modified.
    """
    out = [(int(i), int(j), 1) for i, j, _o in bonds]
    if not out:
        return out
    xyz = np.asarray(coords, dtype=float).reshape(len(symbols), 3)
    z = [elements.atomic_number(s) for s in symbols]
    radii = covalent_radii(symbols)

    valence = {}          # atom -> current sum of bond orders
    for i, j, o in out:
        valence[i] = valence.get(i, 0) + o
        valence[j] = valence.get(j, 0) + o

    def spare(a):
        cap = TYPICAL_VALENCE.get(z[a])
        if cap is None:
            return 0      # unknown/metal: never raise
        return cap - valence.get(a, 0)

    want = {}
    ranked = []
    for k, (i, j, _o) in enumerate(out):
        ref = radii[i] + radii[j]
        ratio = float(np.linalg.norm(xyz[i] - xyz[j]) / ref) if ref > 0 else 1.0
        w = 3 if ratio < TRIPLE_RATIO else (2 if ratio < DOUBLE_RATIO else 1)
        want[k] = w
        if w > 1:
            ranked.append((ratio, k))
    ranked.sort()

    adj = {}
    for k, (i, j, _o) in enumerate(out):
        adj.setdefault(i, []).append(k)
        adj.setdefault(j, []).append(k)

    def other(k, a):
        i, j, _o = out[k]
        return j if a == i else i

    def bump(k, delta):
        i, j, o = out[k]
        out[k] = (i, j, o + delta)
        valence[i] = valence.get(i, 0) + delta
        valence[j] = valence.get(j, 0) + delta

    # 1) greedy: shortest relative bond first
    for _ratio, k in ranked:
        while out[k][2] < want[k] and spare(out[k][0]) > 0 \
                and spare(out[k][1]) > 0:
            bump(k, 1)

    # 2) repair: greedy leaves a MAXIMAL assignment, which is not always the
    # MAXIMUM one — on a six-ring it can stall at two double bonds instead of
    # the three a Kekule structure needs. Walk an alternating chain to free
    # capacity without losing a raise elsewhere (textbook augmenting path;
    # even rings are bipartite so a plain DFS suffices).
    def free_up(a, visited):
        if spare(a) > 0:
            return True
        for k in adj.get(a, ()):
            if k in visited or out[k][2] <= 1:
                continue
            visited.add(k)
            bump(k, -1)                       # frees both ends of k
            b = other(k, a)
            for k2 in adj.get(b, ()):
                if k2 == k or k2 in visited or out[k2][2] >= want[k2]:
                    continue
                c = other(k2, b)
                if c == a or spare(b) <= 0:
                    continue
                if free_up(c, visited):
                    bump(k2, 1)               # net raises unchanged, a freed
                    return True
            bump(k, 1)                        # no gain: put it back
            visited.discard(k)
        return False

    for _ratio, k in ranked:
        while out[k][2] < want[k]:
            i, j, _o = out[k]
            if spare(i) <= 0 and not free_up(i, {k}):
                break
            if spare(j) <= 0 and not free_up(j, {k}):
                break
            if spare(i) <= 0 or spare(j) <= 0:
                break
            bump(k, 1)
    return out


# --------------------------------------------------------------- H bonds
# Geometric hydrogen-bond criterion (Jeffrey / IUPAC-ish, deliberately
# generous so weak contacts still show): D-H...A with H...A within
# HBOND_MAX_HA and the D-H...A angle at least HBOND_MIN_ANGLE.
HBOND_DONORS = frozenset((7, 8, 9, 16))      # N, O, F, S
HBOND_ACCEPTORS = frozenset((7, 8, 9, 16, 17))
HBOND_MAX_HA = 2.6        # Angstrom, H...acceptor
HBOND_MIN_ANGLE = 120.0   # degrees, D-H...A


def find_hydrogen_bonds(symbols, coords, bonds, max_ha=HBOND_MAX_HA,
                        min_angle=HBOND_MIN_ANGLE):
    # type: (List[str], np.ndarray, List, float, float) -> List[Tuple[int, int, float]]
    """Suspected hydrogen bonds as [(h_index, acceptor_index, distance), ...].

    Purely geometric — no energy, no charges — so it is a VISUALISATION aid
    for judging a hand-built arrangement before optimisation, not a claim
    about the chemistry. The acceptor must not be what the hydrogen is
    covalently bound to, and both partners must be electronegative.
    """
    n = len(symbols)
    if n < 3:
        return []
    xyz = np.asarray(coords, dtype=float).reshape(n, 3)
    z = [elements.atomic_number(s) for s in symbols]
    attached = {}
    for i, j, _o in bonds:
        attached.setdefault(i, []).append(j)
        attached.setdefault(j, []).append(i)
    out = []
    acceptors = [k for k in range(n) if z[k] in HBOND_ACCEPTORS]
    for h in range(n):
        if z[h] != 1:
            continue
        donors = [d for d in attached.get(h, []) if z[d] in HBOND_DONORS]
        if not donors:
            continue
        d = donors[0]
        for a in acceptors:
            if a == d or a in attached.get(h, []):
                continue
            v_ha = xyz[a] - xyz[h]
            dist = float(np.linalg.norm(v_ha))
            if not 1e-6 < dist <= max_ha:
                continue
            v_hd = xyz[d] - xyz[h]
            nd = float(np.linalg.norm(v_hd))
            if nd < 1e-6:
                continue
            cosang = float(np.dot(v_hd, v_ha) / (nd * dist))
            angle = np.degrees(np.arccos(np.clip(cosang, -1.0, 1.0)))
            if angle >= min_angle:          # D-H...A angle, 180 = linear
                out.append((h, a, dist))
    return out


def perceive_structure_bond_orders(structure):
    # type: (object) -> int
    """Assign bond orders on `structure` in place. Returns the number of
    multiple bonds found. Called ONCE at import when the source format
    carried no orders, and thereafter only on explicit user request."""
    structure.bonds = perceive_bond_orders(structure.symbols,
                                           structure.coords, structure.bonds)
    return sum(1 for _i, _j, o in structure.bonds if o > 1)
