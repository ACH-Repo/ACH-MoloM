"""Bond perception — a faithful port of Avogadro 2's rule, plus the chemistry
a pure distance rule cannot have.

Source: avogadrolibs `Molecule::perceiveBondsSimple(tolerance=0.45,
minDistance=0.32)` (avogadro/core/molecule.cpp):

    bond(i, j)  iff  minDistance^2 < d^2 < (r_cov(i) + r_cov(j) + tolerance)^2

with two chemistry guards: atoms whose element is He/Ne/Ar/Kr never bond, and
H-H pairs never bond. Covalent radii <= 0 fall back to 2.0 Angstrom (dummy
atoms). All perceived bonds are single (order 1) — order assignment is an
editing/format concern, not a distance one.

**Round 38: distance alone is not enough, and it never was.** Christian's
argument, which is correct: MOF-5 is infinite through its bonds, benzoic acid
is fine on distance alone, and HpPyBz breaks because its geometry is not
physical — so no combination of "how far apart" and "what is connected to
what" can be robust. Two pieces of chemistry are added here, and a third
(occupancy) lives in `cif.py`:

* **BOND KINDS.** A bond between a metal and a non-metal is a COORDINATION
  bond, and that is the logical place to cut a framework into molecules —
  which is how Mercury knows to stop after the carboxylate rather than
  following Zn-O-Zn forever. It is derived from the element pair rather than
  stored, so it cannot go stale, cannot be lost by an edit, and needs no
  reindexing when atoms are deleted.
* **VALENCE SANITY.** A carbon with nine neighbours is not a carbon with nine
  neighbours; it is a file with a problem. Bonds that push an atom past a
  possible coordination number are dropped LONGEST FIRST, and bonds far
  shorter than any real one are dropped outright. Both apply to the covalent
  bonds only: a chloride bridging three metals is perfectly ordinary.
"""

from typing import Dict, List, Optional, Tuple

import numpy as np

from . import elements

TOLERANCE = 0.45       # Angstrom, Avogadro default
MIN_DISTANCE = 0.32    # Angstrom, Avogadro default
_NOBLE = frozenset((2, 10, 18, 36))   # He, Ne, Ar, Kr

# ------------------------------------------------------------------- kinds
#: What a bond IS, as opposed to how long it is.
COVALENT = "covalent"
#: Metal-to-non-metal. Ionic contacts (Na-Cl) land here too: the distinction
#: matters to a chemist but not to the one decision that hangs off this —
#: "does this link hold a molecule together?" — where both answer no.
COORDINATION = "coordination"

#: Everything that is NOT a metal. The d/f block plus Al/Ga/In/Sn/Pb/Bi and
#: friends are metals; this is the canonical list for the whole package
#: (`polyhedra.is_metal` delegates here).
NON_METALS = frozenset(
    "H He B C N O F Ne Si P S Cl Ar As Se Br Kr Te I Xe At Rn".split())


def is_metal(symbol):
    # type: (str) -> bool
    z = elements.atomic_number(symbol)
    if z <= 0:
        return False
    return elements.symbol(z) not in NON_METALS and z > 2


def bond_kind(symbol_i, symbol_j):
    # type: (str, str) -> str
    """COVALENT or COORDINATION, from the element pair alone.

    Metal-to-metal stays COVALENT on purpose: a Re-Re quadruple bond is a real
    covalent bond, and more practically an SBU (a Zn4O cluster, a paddlewheel)
    is ONE node of a framework and must not be dissected into loose atoms.
    Exactly one metal in the pair is what makes a bond the framework's weak
    link — and the place a chemist would cut it.
    """
    a, b = is_metal(symbol_i), is_metal(symbol_j)
    return COORDINATION if (a != b) else COVALENT


def classify_bonds(symbols, bonds):
    # type: (List[str], List[tuple]) -> List[str]
    """Kind per bond, parallel to `bonds`."""
    return [bond_kind(symbols[int(b[0])], symbols[int(b[1])]) for b in bonds]


def covalent_bonds(symbols, bonds):
    # type: (List[str], List[tuple]) -> List[tuple]
    """Just the covalent ones — the connectivity that defines a MOLECULE.

    Walking THIS graph instead of the full one is what makes a framework
    finite: MIL-53's 152-atom periodic component becomes 8 BDC linkers, 8
    hydroxide bridges, 8 waters and 8 aluminium centres, every one of them a
    finite fragment that can be completed at the cell boundary.
    """
    return [b for b in bonds
            if bond_kind(symbols[int(b[0])], symbols[int(b[1])]) == COVALENT]


# ---------------------------------------------------------- valence sanity
#: Maximum number of COVALENT bonds, by atomic number. Deliberately generous —
#: this is a test for the IMPOSSIBLE, not for the unusual, so hypervalent
#: phosphorus (PF5) and sulfur (SF6) are allowed and only chemistry that
#: cannot exist is refused. Anything absent is uncapped, which includes every
#: metal: a metal's high coordination number is real, and its bonds are
#: COORDINATION bonds that this never looks at anyway.
MAX_COVALENT = {
    1: 1,                                     # H  (see _cap_hydrogens)
    5: 4, 6: 4, 7: 4, 8: 3, 9: 1,             # B  C  N  O  F
    14: 4, 15: 5, 16: 6, 17: 4,               # Si P  S  Cl (perchlorate)
    33: 5, 34: 6, 35: 4, 52: 6, 53: 6,        # As Se Br Te I
}

#: A bond shorter than this FRACTION of the two covalent radii is not a bond,
#: whatever the distance test says. Calibrated against the shortest real
#: bonds: with Pyykko radii a C#C triple bond sits at ratio 0.80, C#O at 0.82,
#: an X-ray riding C-H at 0.87 — while HpPyBz_th.cif's spurious contact is a
#: 0.75 A C...C, ratio 0.50. 0.65 sits in the gap with room on both sides.
IMPOSSIBLE_FACTOR = 0.65


def _removal_order(symbols, pairs, distances):
    # type: (List[str], List[tuple], np.ndarray) -> List[int]
    """The order in which over-valence bonds are sacrificed.

    Longest first is right when the excess comes from an over-generous
    distance cutoff -- a spurious long contact really is the least likely
    bond. It is exactly WRONG when the excess comes from DUPLICATE atoms,
    because every real C-C (~1.5 A) is longer than every real C-H (~1.0 A),
    so the skeleton bond is sacrificed to keep the duplicates.

    Round 40, on Christian's `4-ABA-oxime.cif`: a methyl disordered over two
    orientations is written at FULL occupancy, so one carbon carries four to
    six hydrogens at 0.88-1.04 A plus its ring carbon at 1.497 A. Longest
    first drops the C-C -- a textbook single bond -- and the methyl becomes a
    loose fragment. It then sits inside the cell as its own "molecule", so
    whole-molecule boundary completion never carries it out with the rest,
    which is the visible difference from VESTA.

    So a bond that is some atom's LAST link to the heavy-atom skeleton goes
    last. Nothing else changes: a spurious long C...C on a carbon that has
    other heavy neighbours is not a last link, and is still dropped first.
    """
    count = len(pairs)
    if not count:
        return []
    heavy_degree = {}
    for i, j in pairs:
        if symbols[i] != "H" and symbols[j] != "H":
            heavy_degree[i] = heavy_degree.get(i, 0) + 1
            heavy_degree[j] = heavy_degree.get(j, 0) + 1
    dist = np.asarray(distances, dtype=float)
    keys = []
    for k, (i, j) in enumerate(pairs):
        strands = (symbols[i] != "H" and symbols[j] != "H"
                   and (heavy_degree.get(i, 0) <= 1
                        or heavy_degree.get(j, 0) <= 1))
        keys.append((1 if strands else 0, -float(dist[k]), k))
    keys.sort()
    return [k for _, _, k in keys]


def prune_pairs(symbols, pairs, distances, impossible=True, valence=True):
    # type: (List[str], List[tuple], np.ndarray, bool, bool) -> Tuple[List[int], List[tuple]]
    """Which of these candidate bonds survive the chemistry.

    Returns `(keep_indices, dropped)`, where `dropped` is
    `[(i, j, distance, reason), ...]` so the caller can SAY what it threw
    away — a bond quietly disappearing is worse than a bond wrongly drawn.

    Takes explicit distances because the two callers measure differently:
    `perceive_bonds` uses straight lines and `cif.periodic_neighbours` uses
    the minimum image. The chemistry is identical; only the metric differs.
    """
    n = len(symbols)
    radii = covalent_radii(symbols)
    dropped = []
    alive = [True] * len(pairs)
    order = _removal_order(symbols, pairs, distances)
    if impossible:
        for k, (i, j) in enumerate(pairs):
            if not (0 <= i < n and 0 <= j < n):
                alive[k] = False
                continue
            floor = IMPOSSIBLE_FACTOR * (radii[i] + radii[j])
            if float(distances[k]) < floor:
                alive[k] = False
                dropped.append((int(i), int(j), float(distances[k]),
                                "impossibly short"))
    if valence:
        # Longest first: an over-coordinated atom keeps its SHORTEST bonds,
        # which are the ones a real structure would have.
        degree = {}                       # atom -> covalent bonds still alive
        for k, (i, j) in enumerate(pairs):
            if not alive[k]:
                continue
            if bond_kind(symbols[i], symbols[j]) != COVALENT:
                continue
            degree[i] = degree.get(i, 0) + 1
            degree[j] = degree.get(j, 0) + 1
        for k in order:
            if not alive[k]:
                continue
            i, j = pairs[k]
            if bond_kind(symbols[i], symbols[j]) != COVALENT:
                continue
            cap_i = MAX_COVALENT.get(elements.atomic_number(symbols[i]))
            cap_j = MAX_COVALENT.get(elements.atomic_number(symbols[j]))
            over = ((cap_i is not None and degree.get(i, 0) > cap_i)
                    or (cap_j is not None and degree.get(j, 0) > cap_j))
            if not over:
                continue
            alive[k] = False
            degree[i] -= 1
            degree[j] -= 1
            dropped.append((int(i), int(j), float(distances[k]),
                            "over the covalent valence"))
    return [k for k, ok in enumerate(alive) if ok], dropped

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

def perceive_bonds(symbols, coords, tolerance=TOLERANCE,
                   min_distance=MIN_DISTANCE, sanity=True, report=None):
    # type: (List[str], np.ndarray, float, float, bool, Optional[dict]) -> List[Tuple[int, int, int]]
    """Perceive bonds from geometry. Returns [(i, j, 1), ...] with i < j.

    Vectorised numpy over all unique pairs, processed in blocks so a large
    molecule doesn't allocate an N^2 matrix at once. For the sizes a molecule
    builder edits (10^2..10^4 atoms) this is comfortably fast without a
    spatial index.

    `sanity` applies the chemistry on top of the distance rule (see the module
    docstring): impossibly short contacts and over-valence bonds are dropped.
    Pass a dict as `report` to be told what went, and why — `dropped_bonds`
    explains each refusal, and `refused` is the same set as a drawable pair
    list, for the round-43 visualisation override (see `_refused_display`).
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
    dists = []  # type: List[float]
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
        for a, b, d in zip(bi[ok], bj[ok], np.sqrt(d2[ok])):
            bonds.append((int(a), int(b), 1))
            dists.append(float(d))
    if sanity and bonds:
        keep, dropped = prune_pairs(symbols, [(i, j) for i, j, _o in bonds],
                                    np.asarray(dists))
        kept = [bonds[k] for k in keep]
        if report is not None:
            report.setdefault("dropped_bonds", []).extend(dropped)
            if dropped:
                report["refused"] = _refused_display(bonds, kept, xyz,
                                                     hydrogen)
        bonds = kept
    return _cap_hydrogens(bonds, xyz, hydrogen)


def _refused_display(candidates, kept, xyz, hydrogen):
    # type: (List[tuple], List[tuple], np.ndarray, np.ndarray) -> List[tuple]
    """The bonds the chemistry refused, as a list something can DRAW.

    Round 43, for the visualisation override. MoloM's rule is that only a real
    bond is drawn as a bond, and that rule stays — but on a wholly disordered
    structure it hides the shape of the thing entirely. Christian's
    `2240539.cif` is a plastic crystal, one molecule smeared over 192
    operations of Fm-3m: 752 contacts pass the distance test, `prune_pairs`
    refuses 528 of them (432 over-valence, 96 impossibly short), and what is
    left is 77 components of about five atoms — a cloud of spheres where VESTA
    shows four solid cages.

    Note what this is NOT: the difference between the sane list and the raw
    candidates. The HYDROGEN CAP still applies, because a hydrogen drawn with
    five sticks is never a picture worth having (round 35b), and it is free to
    keep: capped and uncapped give the SAME four 70-atom components on that
    file (368 sticks against 752). So the override restores every bond the
    CHEMISTRY filters refused and none of the ones the cap refused.
    """
    final = _cap_hydrogens(list(kept), xyz, hydrogen)
    have = {(int(i), int(j)) for i, j, _o in final}
    # Which hydrogens already have their one stick. Capping the refused list
    # against the KEPT list, rather than capping the two separately and taking
    # the union, is the whole subtlety here: a hydrogen's nearest neighbour
    # among ALL candidates is often one of the impossibly short contacts, so
    # two independent caps choose two different partners and the union hands
    # that hydrogen two sticks. Measured on 2240539.cif: 240 refused bonds
    # that way against 144 this way, and 96 double-bonded hydrogens.
    bonded_h = set()
    for i, j, _o in final:
        for a in (i, j):
            if hydrogen[a]:
                bonded_h.add(int(a))
    rest = []
    for i, j, _o in candidates:
        if (int(i), int(j)) in have:
            continue
        d = float(np.linalg.norm(np.asarray(xyz[i]) - np.asarray(xyz[j])))
        rest.append((d, int(i), int(j)))
    rest.sort()                       # nearest first: an unbonded hydrogen
    out = []                          # keeps its closest partner, as the cap
    for _d, i, j in rest:             # would have chosen
        hs = [a for a in (i, j) if hydrogen[a]]
        if any(a in bonded_h for a in hs):
            continue
        out.append((i, j))
        bonded_h.update(hs)
    return out


def _cap_hydrogens(bonds, xyz, hydrogen):
    # type: (List[Tuple[int, int, int]], np.ndarray, np.ndarray) -> List[Tuple[int, int, int]]
    """A hydrogen gets ONE bond — its nearest heavy neighbour.

    Avogadro's `perceiveBondsSimple` is purely a distance test, so any atom
    that strays inside H's covalent window becomes a bond. That is fine on a
    clean molecule and wrong on a crystal: symmetry expansion routinely brings
    a neighbouring molecule within 1.4 A of a hydrogen, and the picture then
    shows an H with two sticks, which is not a thing chemistry allows. It
    showed up on Christian's HpPyBz_th.cif as eight two-bonded hydrogens.

    (Worth being clear about what this does NOT fix: that file has a genuine
    0.75 A atom-atom contact, and ASE reads exactly the same 192 atoms and the
    same clash, so the geometry really is broken in the file. Capping the
    valence stops MoloM DRAWING an impossible bond; it cannot invent a
    structure that is not there.)

    Bridging hydrides — B-H-B in diboranes — are the one real exception, and
    they are not something a distance-based perceiver ever got right anyway:
    it would need the electron count, not the geometry. Ctrl+P after adding
    the second bond by hand keeps it, since perception is never automatic.
    """
    if not bonds or not hydrogen.any():
        return bonds
    best = {}
    for index, (i, j, _o) in enumerate(bonds):
        for h, other in ((i, j), (j, i)):
            if not hydrogen[h]:
                continue
            d = float(np.linalg.norm(xyz[h] - xyz[other]))
            if h not in best or d < best[h][0]:
                best[h] = (d, index)
    if not best:
        return bonds
    keep = {index for _d, index in best.values()}
    out = []
    for index, bond in enumerate(bonds):
        i, j, _o = bond
        if (hydrogen[i] or hydrogen[j]) and index not in keep:
            continue
        out.append(bond)
    return out


def perceive_structure_bonds(structure, tolerance=TOLERANCE,
                             min_distance=MIN_DISTANCE, keep_orders=True,
                             report=None):
    # type: (object, float, float, bool, Optional[dict]) -> None
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
                           tolerance=tolerance, min_distance=min_distance,
                           report=report)
    structure.bonds = [(i, j, old.get((i, j), 1)) for i, j, _ in fresh]


#: Metadata flag: this structure's frames are one MOLECULE seen at different
#: phases, so its connectivity must not be re-derived per frame. Set when a
#: normal mode is baked (`ui/app.on_animate_mode`).
FIXED_BONDS = "fixed_bonds"


def bonds_are_fixed(structure):
    # type: (object) -> bool
    """Should the player leave this structure's bonds alone as it steps?

    An MD trajectory really does make and break bonds, so re-perceiving per
    frame is right for it. A baked NORMAL MODE is the opposite case: it is one
    molecule at successive phases of an oscillation about equilibrium, and
    nothing bonds or unbonds along the way — so re-perceiving it can only ever
    lose bonds, never find real ones.

    And it does. Round 57, Christian: "when an animation shortens a bond far
    enough it is no longer drawn." Measured on his own H3PO4 FREQ job: at the
    DEFAULT 0.2 A amplitude the 1346 cm-1 mode squeezes P=O to 1.127 A against
    an `IMPOSSIBLE_FACTOR` floor of 1.13, and the bond is refused; at 0.4 A
    the O-H stretches reach 0.56 A and go too. The filters are right — no
    static structure with a 0.56 A O-H is real — but they are answering a
    question nobody asked here, because the phase of a vibration is not a
    structure to be judged. So the honest fix is to stop asking.
    """
    meta = getattr(structure, "metadata", None) or {}
    return bool(meta.get(FIXED_BONDS))


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
