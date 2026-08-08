"""The LABELLED PERIODIC BOND GRAPH — stage 4 of the crystal pipeline.

Every edge carries the symmetry label that produced it: `(i, j, shift)` means
"atom i bonds to the image of atom j translated by `shift` lattice vectors".
That label is the CIF `n_pqr` code (`npqr`, below), and it is what makes the
graph independent of the display window: packing, boundary completion, growing
a shell and clipping are then cheap traversals over a fixed structure rather
than fresh perception on whatever atoms happen to be on screen.

**Why this module exists.** Bonds used to be perceived from Cartesian
coordinates AFTER the structure had been clipped to the cell, with boundary
copies and a `BoundaryModifier` patching the damage afterwards. Two things
went wrong, both measured:

* Clip-then-bond loses the bonds that cross a face. An atom sitting exactly ON
  a face is drawn twice (once per face, which is the crystallographic
  convention) and the two copies then SPLIT one coordination sphere between
  them: every Zn in ZIF-8 came out with three N instead of four, on all twelve
  of them, and no number of boundary shells fixed it because the atoms were
  present all along — it was the bonds that were missing.
* `cif.periodic_pairs` used the minimum image unguarded. That convention is
  only valid while the bond cutoff is under HALF the smallest PERPENDICULAR
  cell width — not the smallest cell edge, which is the tempting mistake in a
  skewed cell — and it can never return more than one bond per pair of atoms
  nor any bond from an atom to its own image. Alpha-iron came out with one
  bond where there are eight.

Both are cured by generating candidates over the whole translation shell and
keeping the label, which is what everything here does.

The chemistry is NOT re-implemented: candidates go through the same
`bonding.prune_pairs` the molecular path uses, so a bond kind, a valence cap
and an impossible contact mean the same thing in a crystal as in a molecule.
Only the metric differs, exactly as it did before.
"""
from __future__ import annotations

import itertools
import math
from collections import namedtuple

import numpy as np

from . import bonding, elements

__all__ = ["Edge", "PeriodicGraph", "build", "perpendicular_widths",
           "translation_shell", "npqr", "minimum_image_is_safe"]


#: One periodic bond. `shift` is the integer lattice translation applied to
#: `j`, so the partner sits at `frac[j] + shift`. `dist` is in Angstrom.
Edge = namedtuple("Edge", "i j shift dist")


def perpendicular_widths(cell):
    # type: (object) -> tuple
    """The three PERPENDICULAR cell widths, `V / |b x c|` and friends.

    Not the cell edge lengths: in a skewed cell they are strictly smaller, and
    every "is this cutoff safe?" question is about these. Using `min(a, b, c)`
    instead is the classic way to convince yourself a minimum-image sweep is
    valid when it is not.
    """
    m = np.asarray(cell.matrix(), dtype=float)
    volume = abs(float(np.linalg.det(m)))
    a, b, c = m[0], m[1], m[2]
    return (volume / float(np.linalg.norm(np.cross(b, c))),
            volume / float(np.linalg.norm(np.cross(c, a))),
            volume / float(np.linalg.norm(np.cross(a, b))))


def minimum_image_is_safe(cell, cutoff):
    # type: (object, float) -> bool
    """Is the minimum-image convention valid for this cutoff in this cell?

    Kept as a named predicate because it is the guard whose ABSENCE was the
    bug, and a reader should be able to find it. Measured across the 37-file
    test set, six files fail it — every one of them a dense inorganic with a
    small cell, none of them a framework.
    """
    return float(cutoff) < min(perpendicular_widths(cell)) / 2.0


def translation_shell(cell, cutoff):
    # type: (object, float) -> np.ndarray
    """Integer lattice translations that can bring an atom within `cutoff`.

    `n_i = ceil(cutoff / d_i)` on the PERPENDICULAR widths — anything further
    out cannot reach, whatever the cell shape.
    """
    widths = perpendicular_widths(cell)
    n = [int(math.ceil(float(cutoff) / w)) if w > 0 else 1 for w in widths]
    return np.array(list(itertools.product(range(-n[0], n[0] + 1),
                                           range(-n[1], n[1] + 1),
                                           range(-n[2], n[2] + 1))),
                    dtype=int)


def npqr(edge, operator=1):
    # type: (Edge, int) -> str
    """The CIF symmetry code for an edge's partner: `1_555` is no translation.

    The digits are `5 + t`, so they only survive translations in -4..+4 — far
    beyond anything a bond can reach, but clamped rather than allowed to spill
    into a second digit and produce a code that reads as a different cell.
    """
    digits = "".join(str(max(1, min(9, 5 + int(t)))) for t in edge.shift)
    return "{}_{}".format(int(operator), digits)


def _canonical_shifts(shell):
    # type: (np.ndarray) -> list
    """Half the shell — one representative per `+t` / `-t` pair, plus zero.

    An edge and its inverse are the same bond written from the two ends
    (`(i, j, t)` is `(j, i, -t)`), so generating both would double every
    edge. Taking only the lexicographically positive half of the shell, and
    handling `t = 0` separately with `i < j`, keeps exactly one of each.
    """
    out = []
    for t in shell:
        key = (int(t[0]), int(t[1]), int(t[2]))
        if key > (0, 0, 0):
            out.append(key)
    return out


class PeriodicGraph(object):
    """A crystal's bonds as a labelled periodic graph.

    Indices are into the CELL CONTENT — the atoms as stored — and the graph is
    a property of (content, cell, bond rules) alone. Nothing here knows how
    many cells are on screen.
    """

    def __init__(self, symbols, frac, cell, edges):
        self.symbols = list(symbols)
        self.frac = np.asarray(frac, dtype=float).reshape(len(symbols), 3)
        self.cell = cell
        self.edges = list(edges)

    def __repr__(self):
        return "PeriodicGraph({} atoms, {} edges)".format(
            len(self.symbols), len(self.edges))

    # ------------------------------------------------------------ queries
    def degree(self, i):
        # type: (int) -> int
        """Coordination number of atom `i` in the infinite structure.

        A self-image edge counts TWICE: an atom bonded to its own image at
        `+t` is equally bonded to the one at `-t`, and both are neighbours.
        Alpha-iron's single stored atom has four such edges and coordination
        eight, which is the correct bcc answer.
        """
        total = 0
        for e in self.edges:
            if e.i == i:
                total += 1
            if e.j == i:
                total += 1
        return total

    def coordination(self):
        # type: () -> np.ndarray
        out = np.zeros(len(self.symbols), dtype=int)
        for e in self.edges:
            out[e.i] += 1
            out[e.j] += 1
        return out

    def neighbours(self, i):
        # type: (int) -> list
        """`[(j, shift, dist), ...]` — every neighbour of `i`, both directions."""
        out = []
        for e in self.edges:
            if e.i == i:
                out.append((e.j, e.shift, e.dist))
            if e.j == i:
                out.append((e.i, tuple(-t for t in e.shift), e.dist))
        return out

    def crossing_edges(self):
        # type: () -> list
        """Edges whose label is not `1_555`, i.e. those that leave the cell.

        For a 3-periodic framework this must be non-empty; zero means the
        structure was perceived as a heap of isolated molecules, which is the
        headline failure this whole module exists to prevent.
        """
        return [e for e in self.edges if any(e.shift)]

    def components(self):
        # type: () -> list
        """`[(indices, rank), ...]` — connected components and their periodicity.

        `rank` is the dimension of the lattice spanned by the translation
        mismatches found while walking: 0 = molecule, 1 = chain, 2 = layer,
        3 = framework. That is the honest test for "can this be completed as a
        molecule?", and it replaces guessing from a bond count.
        """
        n = len(self.symbols)
        adjacency = [[] for _ in range(n)]
        for e in self.edges:
            adjacency[e.i].append((e.j, np.array(e.shift, dtype=int)))
            adjacency[e.j].append((e.i, -np.array(e.shift, dtype=int)))
        seen = [False] * n
        out = []
        for seed in range(n):
            if seen[seed]:
                continue
            seen[seed] = True
            placed = {seed: np.zeros(3, dtype=int)}
            stack = [seed]
            group = [seed]
            vectors = []
            while stack:
                i = stack.pop()
                for j, shift in adjacency[i]:
                    target = placed[i] + shift
                    if j not in placed:
                        placed[j] = target
                        seen[j] = True
                        group.append(j)
                        stack.append(j)
                    else:
                        diff = target - placed[j]
                        if np.any(diff):
                            vectors.append(diff)
            out.append((sorted(group), _lattice_rank(vectors)))
        return out

    # ------------------------------------------------- stage 5: instantiate
    def instantiate(self, instances):
        # type: (list) -> list
        """Bonds among a set of drawn atoms — stage 5, and a pure lookup.

        `instances` is `[(content_index, shift), ...]`, one entry per DRAWN
        atom. Returns `[(a, b, 1), ...]` as indices into that list.

        This is what makes an atom on a cell face come out right. It is drawn
        twice, once at each face; each copy carries a different `shift`, so
        each looks up its own neighbours and gets its OWN full coordination
        sphere — provided the partner is on screen. Nothing is re-perceived
        and nothing depends on how many cells are shown.
        """
        index = {}
        by_site = {}
        for k, entry in enumerate(instances):
            if entry is None:
                continue
            site, shift = entry
            key = (int(site), tuple(int(s) for s in shift))
            index.setdefault(key, k)
            by_site.setdefault(int(site), []).append((k, key[1]))
        bonds = []
        seen = set()
        for e in self.edges:
            for k, shift in by_site.get(e.i, ()):
                partner = (e.j, tuple(s + t for s, t in zip(shift, e.shift)))
                other = index.get(partner)
                if other is None or other == k:
                    continue
                pair = (min(k, other), max(k, other))
                if pair in seen:
                    continue
                seen.add(pair)
                bonds.append((pair[0], pair[1], 1))
        return bonds


def _lattice_rank(vectors):
    # type: (list) -> int
    if not vectors:
        return 0
    return int(np.linalg.matrix_rank(np.asarray(vectors, dtype=float),
                                     tol=1e-8))


def build(symbols, frac, cell, slack=None, sanity=True, report=None,
          valence=True, cap_hydrogens=True):
    # type: (list, np.ndarray, object, float, bool, dict, bool, bool) -> PeriodicGraph
    """The periodic bond graph of one cell's content.

    `frac` is FRACTIONAL and need not be wrapped: the atoms are wrapped
    internally for the search and the resulting labels are corrected back to
    the coordinates that were passed in, so an unwrapped molecule gives the
    same graph as a wrapped one. That matters because `unwrap_molecules` moves
    whole fragments by lattice vectors to make them contiguous — searching a
    shell of radius one around the coordinates as given would simply not reach
    an atom that had been carried two cells out.
    """
    if slack is None:
        slack = bonding.TOLERANCE
    n = len(symbols)
    if n == 0:
        return PeriodicGraph(symbols, np.zeros((0, 3)), cell, [])
    original = np.asarray(frac, dtype=float).reshape(n, 3)
    # Wrap for the SEARCH, and remember by how much: an edge found between
    # wrapped atoms i and j + t means, in the coordinates the caller gave us,
    # a shift of `t - w[j] + w[i]`. Doing it this way keeps the graph a
    # property of the structure rather than of how the atoms happen to be
    # written down.
    offset = np.floor(original)
    frac = original - offset
    matrix = np.asarray(cell.matrix(), dtype=float)
    radii = bonding.covalent_radii(symbols)
    z = np.array([elements.atomic_number(s) for s in symbols], dtype=int)
    noble = np.isin(z, list(bonding._NOBLE))
    hydrogen = z == 1
    cutoff_max = float(radii.max() * 2.0 + slack)
    shell = translation_shell(cell, cutoff_max)

    pairs, dists, shifts = [], [], []

    def collect(i_idx, j_idx, delta, shift):
        """Candidate edges for one block of index pairs."""
        if not len(i_idx):
            return
        dist = np.linalg.norm(delta @ matrix, axis=1)
        limit = radii[i_idx] + radii[j_idx] + slack
        ok = (dist > bonding.MIN_DISTANCE) & (dist < limit)
        ok &= ~(noble[i_idx] | noble[j_idx])        # noble gases never bond
        ok &= ~(hydrogen[i_idx] & hydrogen[j_idx])  # and no H-H
        for a, b, d in zip(i_idx[ok], j_idx[ok], dist[ok]):
            pairs.append((int(a), int(b)))
            dists.append(float(d))
            shifts.append(shift)

    # t = 0: the ordinary intra-cell pairs, each once.
    ii, jj = np.triu_indices(n, k=1)
    collect(ii, jj, frac[jj] - frac[ii], (0, 0, 0))

    # t != 0: every ordered pair INCLUDING i == j, since an atom bonding to its
    # own periodic image is ordinary in a framework (and is the whole of the
    # structure in a metal). Only the positive half of the shell is walked, so
    # each edge appears once.
    all_i = np.repeat(np.arange(n), n)
    all_j = np.tile(np.arange(n), n)
    for shift in _canonical_shifts(shell):
        delta = frac[all_j] + np.array(shift, dtype=float) - frac[all_i]
        collect(all_i, all_j, delta, shift)

    if sanity and pairs:
        # `valence` and `cap_hydrogens` are separable from `sanity` on
        # purpose. An impossibly short contact is never a bond and dropping
        # it is not a judgement call; an over-valence atom, by contrast, may
        # be exactly what a disordered site should LOOK like — a methyl over
        # two orientations really does want six hydrogens drawn, which is
        # what VESTA and Mercury show.
        keep, dropped = bonding.prune_pairs(symbols, pairs,
                                            np.asarray(dists, dtype=float),
                                            valence=valence)
        if report is not None and dropped:
            report.setdefault("dropped_bonds", []).extend(dropped)
        pairs = [pairs[k] for k in keep]
        shifts = [shifts[k] for k in keep]
        dists = [dists[k] for k in keep]

    edges = [Edge(i, j,
                  tuple(int(t) - int(offset[j][k]) + int(offset[i][k])
                        for k, t in enumerate(s)),
                  d)
             for (i, j), s, d in zip(pairs, shifts, dists)]
    if cap_hydrogens:
        edges = _cap_hydrogens(edges, hydrogen)
    return PeriodicGraph(symbols, original, cell, edges)


def _cap_hydrogens(edges, hydrogen):
    # type: (list, np.ndarray) -> list
    """A hydrogen keeps ONE bond — its nearest partner — periodically.

    `bonding._cap_hydrogens` measures straight lines from a coordinate array,
    which is exactly what cannot be done here: the partner may be in the next
    cell and the same pair of INDICES can be bonded through several different
    translations. The edge already carries its own distance, so the rule is
    the same rule with the metric it was given.
    """
    if not edges or not hydrogen.any():
        return edges
    best = {}
    for k, e in enumerate(edges):
        for h, _other in ((e.i, e.j), (e.j, e.i)):
            if not hydrogen[h]:
                continue
            if h not in best or e.dist < best[h][0]:
                best[h] = (e.dist, k)
    if not best:
        return edges
    keep = {k for _d, k in best.values()}
    return [e for k, e in enumerate(edges)
            if not (hydrogen[e.i] or hydrogen[e.j]) or k in keep]


def label_instances(frac, cell, n_content, tol=0.05):
    # type: (np.ndarray, object, int, float) -> list
    """Tag every drawn atom as `(content index, integer lattice shift)`.

    Everything a crystal draws beyond its own content — a boundary copy, an
    exterior shell atom, a supercell repeat — is an exact LATTICE TRANSLATE of
    one of the content atoms, so the label can be recovered from the
    coordinate instead of being threaded through every function that appends
    atoms. That is what lets `PeriodicGraph.instantiate` bond a picture it
    never helped build.

    Returns `None` in place of a label for anything that is not a translate of
    a content atom (an edited or hand-drawn atom), so the caller can fall back
    to ordinary perception for those.
    """
    frac = np.asarray(frac, dtype=float).reshape(-1, 3)
    content = frac[:n_content]
    matrix = np.asarray(cell.matrix(), dtype=float)
    out = [(k, (0, 0, 0)) for k in range(min(n_content, len(frac)))]
    for row in frac[n_content:]:
        delta = row - content
        shift = np.round(delta)
        residual = np.linalg.norm((delta - shift) @ matrix, axis=1)
        hit = int(np.argmin(residual)) if len(residual) else -1
        if hit < 0 or residual[hit] > tol:
            out.append(None)
            continue
        out.append((hit, tuple(int(s) for s in shift[hit])))
    return out
