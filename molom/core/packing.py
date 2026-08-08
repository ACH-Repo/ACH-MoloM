"""Cell PACKING — how a crystal becomes the atoms and bonds you see.

This is the shipping algorithm. It was prototyped on the 🧪 sandbox page and
promoted here once Christian was satisfied with it; `core.sandbox` now imports
these functions and only adds the stage-by-stage trace on top, so the page can
never describe something the application does not do.

The order, and why:

    expand (operators, wrap, dedupe)   the cell CONTENT, atom by atom
    classify_occupancy                 decide what a partial SITE is
    boundary_instances                 an atom on a face belongs to 2^k places
    bondgraph.build                    connectivity, labelled and periodic
    complete_molecules                 every fragment reaching in, drawn WHOLE

The step that differs from what MoloM used to do is the last one. The old path
made each fragment CONTIGUOUS and shifted it bodily so its centroid landed in
the cell, which preserves the cell content exactly but relocates a molecule
split across several corners — and once it has moved it is no longer on a face,
so the boundary completion that follows has nothing to repeat. On `242083.cif`
that drew one fullerene where five belong. Here nothing is relocated: the parts
that were missing are materialised instead.

Three bond rules are folded in, each measured rather than assumed:

* **over-valence is allowed.** A methyl disordered over two orientations really
  does want six hydrogens drawn; VESTA and Mercury both do it.
* **no metal-to-metal bonds at all**, VESTA's convention. A 1.55 A sodium
  radius otherwise licenses Na...Na at 3.43 A, and following those grew a
  superfluous outer layer of metal.
* **no bonds between disorder ALTERNATIVES.** Two partial atoms whose
  occupancies sum to about one cannot both be there. Distance cannot settle
  it — ZIF-7's alternatives sit 1.359 A apart and a peroxide bond is 1.48 A.
"""
from __future__ import annotations

import numpy as np

from . import bonding
from . import bondgraph
from . import cif as cif_mod

__all__ = ["pack", "boundary_instances", "complete_molecules",
           "classify_occupancy"]


def pack(data, disorder=None, outside=True, grow_from_copies=False, tol=0.1):
    # type: (object, str, bool, bool, float) -> tuple
    """A parsed CIF -> `(symbols, CARTESIAN coords, bonds, meta)`.

    `outside` draws the completed molecules beyond the cell wall; with it off
    the same connectivity is kept but only the in-cell atoms are drawn.
    `grow_from_copies` additionally completes the coordination of every
    boundary COPY — fuller on a dense oxide, ruinous on a phosphate, hence
    off by default (measured both ways; see CLAUDE.md round 45i).
    """
    cell = data.cell
    content_report = {}
    symbols, cart = cif_mod.expand(
        data, whole_molecules=False, boundary=False,
        disorder=disorder or cif_mod.POLICY_ALL, tol=tol,
        report=content_report)
    if not symbols:
        return [], np.zeros((0, 3)), [], {}
    frac = cell.to_fractional(cart)

    composition, _info, occupancy_of = classify_occupancy(
        data, len(symbols), tol=tol, disorder=disorder)
    instances, _counts = boundary_instances(frac)

    graph = bondgraph.build(symbols, frac, cell, valence=False,
                            cap_hydrogens=False)
    graph = _without_metal_metal(graph)
    if not wholly_disordered(data):
        graph, _dropped = _without_alternatives(graph, occupancy_of)

    out_symbols, out_frac, out_bonds, _stats, source = complete_molecules(
        symbols, frac, cell, graph=graph, outside=outside, seeds=instances,
        grow_from_copies=grow_from_copies)

    meta = {}
    # How many atoms the packing DREW. `cell_content` counts the cell's own
    # content, which is deliberately smaller — so the two differing proves
    # nothing, and only this number can say whether an edit has since added or
    # removed an atom.
    meta["packed_n"] = len(out_symbols)
    # `complete_molecules` REORDERS and duplicates, so anything keyed by the
    # content index has to be remapped through `source` — an index-based map
    # carried across it silently describes the wrong atoms.
    site_of = content_report.get("site_of") or []
    if site_of:
        meta["site_of"] = [int(site_of[i]) if i < len(site_of) else -1
                           for i in source]
    if composition:
        # A copy of a shared site is still that site (round 42), or the cell
        # shows one pie sphere in the middle and plain ones at the corners.
        table = {str(k): composition[str(src)]
                 for k, src in enumerate(source) if str(src) in composition}
        if table:
            meta["site_occupancy"] = table
    return out_symbols, out_frac @ cell.matrix(), out_bonds, meta


def boundary_instances(frac, tol=1e-6):
    # type: (np.ndarray, float) -> tuple
    """Every atom, plus its copies on the equivalent faces of the cell.

    An atom with k of its three coordinates sitting on a boundary belongs to
    2^k positions. The wrap cannot produce these — it is a function, so an
    atom at 0 maps to 0 and never to 1 — which is exactly why this is its own
    step rather than part of wrapping.

    Returns `([(atom index, shift), ...], counts)` with the untranslated
    instance of every atom first, so indices below `len(frac)` are unchanged.
    """
    frac = np.asarray(frac, dtype=float).reshape(-1, 3)
    instances = [(i, (0, 0, 0)) for i in range(len(frac))]
    counts = {1: 0, 2: 0, 3: 0}
    for i, row in enumerate(frac):
        axes = []
        for axis, x in enumerate(row):
            r = x - np.floor(x)
            if abs(r) >= tol and abs(r - 1.0) >= tol:
                continue
            # Which way the equivalent position lies has to come from the
            # coordinate itself, not from the wrapped residual: x = 1.0 has
            # residual 0.0 but sits at the TOP of the cell, so its partner
            # is at 0.0 (shift -1), not at 2.0.
            axes.append((axis, -1 if x > 0.5 else 1))
        if not axes:
            continue
        counts[len(axes)] = counts.get(len(axes), 0) + 1
        # Every non-empty subset of the boundary axes gives one more copy.
        for mask in range(1, 1 << len(axes)):
            shift = [0, 0, 0]
            for bit, (axis, direction) in enumerate(axes):
                if mask & (1 << bit):
                    shift[axis] = direction
            instances.append((i, tuple(shift)))
    return instances, counts


def complete_molecules(symbols, frac, cell, graph=None, outside=True,
                       max_atoms=200000, seeds=None, grow_from_copies=False,
                       carry_fragment=True, metal_origins_only=False):
    # type: (list, np.ndarray, object, object, bool, int, list, bool, bool) -> tuple
    """Draw every fragment that reaches into the cell, whole.

    Mercury's rule. For each connected component, the lattice translations
    worth trying are POOLED OVER THE WHOLE GROUP rather than taken per atom
    (round 43b's lesson: a fragment on a corner can have atoms on the x, y
    and z faces and yet no atom with all three coordinates at zero, so
    per-atom shifts reach three faces and three edges but never the far
    corner). Each candidate translation is then kept if any atom of the
    translated component lands in the closed cell.

    Returns `(symbols, fractional coords, bonds, info, source indices)`.
    """
    frac = np.asarray(frac, dtype=float).reshape(len(symbols), 3)
    if graph is None:
        graph = bondgraph.build(symbols, frac, cell)
    instances = []          # [(atom index, shift)]
    info = {"components": 0, "finite": 0, "periodic": 0, "copies": 0,
            "shell": 0, "capped": False}
    for group, rank in graph.components():
        info["components"] += 1
        place, periodic = _contiguous(group, graph)
        if periodic or rank > 0:
            # A chain, layer or framework has no "whole" to complete, so the
            # molecular rule cannot apply. What CAN be completed is each
            # drawn atom's own coordination: one bonded shell, materialising
            # any partner not already present. That is what gives the metal
            # sitting exactly on a cell face its full set of oxygens, and it
            # needs no chemistry-specific rule -- it follows from the bonds.
            info["periodic"] += 1
            members = set(group)
            seeded = [(i, tuple(s)) for i, s in (seeds or [])
                      if i in members
                      and _in_cell(frac[i] + np.array(s, dtype=float))]
            if not seeded:
                seeded = [(i, (0, 0, 0)) for i in group if _in_cell(frac[i])]
            instances.extend(seeded)
            if outside:
                place, families = _covalent_fragments(graph, symbols)
                have = set(seeded)
                # WHERE the shell grows from. Growing off every drawn atom
                # including the boundary copies multiplies the work: a
                # 6-coordinate Mg with copies on three faces completes its
                # sphere once per copy.
                origins = seeded if grow_from_copies else [
                    (i, s) for i, s in seeded if not any(s)]
                if metal_origins_only:
                    # VESTA's apparent asymmetry: a metal gets its ligands
                    # completed, a ligand does not pull in further metal.
                    origins = [(i, s) for i, s in origins
                               if bonding.is_metal(symbols[i])]
                for i, s in list(origins):
                    for j, eshift, _d in graph.neighbours(i):
                        # NEVER follow metal to metal. Those are the bonds a
                        # 1.55 A sodium radius licenses between two cations
                        # that merely sit near each other, and following them
                        # drags in a whole extra layer of metal — 1547149
                        # came out with 19 Nb from a content of 2.
                        if (bonding.is_metal(symbols[i])
                                and bonding.is_metal(symbols[j])):
                            continue
                        base = np.array(s, dtype=int) + np.array(eshift,
                                                                 dtype=int)
                        # Bring the partner's whole COVALENT fragment, not
                        # just the partner: an imidazolate N arriving alone
                        # is a blue dot with no ring (2130251).
                        root, rel_j = place[j]
                        family = families[root] if carry_fragment else [j]
                        for k in family:
                            offset = base + (place[k][1] - rel_j)
                            key = (k, tuple(int(v) for v in offset))
                            if key in have:
                                continue
                            have.add(key)
                            instances.append(key)
                            info["shell"] += 1
            continue
        info["finite"] += 1
        laid = {i: frac[i] + place[i] for i in group}
        # Candidate translations, POOLED OVER THE GROUP and per axis: every
        # integer that could put SOME atom of the group inside the closed
        # cell on that axis. The closed cell matters — an atom at exactly 0
        # is equally an atom at 1, so it must propose both, or a molecule
        # sitting on the origin corner is drawn once instead of at all eight
        # corners (round 43b, re-learned here).
        per_axis = []
        for axis in range(3):
            values = set()
            for i in group:
                x = laid[i][axis]
                lo = int(np.ceil(-x - 1e-9))
                hi = int(np.floor(1.0 - x + 1e-9))
                values.update(range(lo, hi + 1))
            per_axis.append(sorted(values) or [0])
        candidates = [(a, b, c) for a in per_axis[0]
                      for b in per_axis[1] for c in per_axis[2]]
        for t in sorted(candidates):
            shifted = {i: laid[i] + np.array(t, dtype=float) for i in group}
            if not any(_in_cell(shifted[i]) for i in group):
                continue
            info["copies"] += 1
            for i in group:
                if not outside and not _in_cell(shifted[i]):
                    continue
                instances.append((i, tuple(int(v) for v in place[i] + np.array(t))))
            if len(instances) > max_atoms:
                info["capped"] = True
                break
        if info["capped"]:
            break

    # De-duplicate: two components can propose the same instance.
    seen = {}
    for entry in instances:
        seen.setdefault(entry, len(seen))
    ordered = sorted(seen, key=lambda e: seen[e])
    out_symbols = [symbols[i] for i, _s in ordered]
    out_frac = np.array([frac[i] + np.array(s, dtype=float)
                         for i, s in ordered], dtype=float) \
        if ordered else np.zeros((0, 3))
    out_bonds = graph.instantiate(ordered)
    # Which input atom each drawn atom is a copy of, so anything keyed by
    # atom index (a shared site's composition) can ride along.
    source = [i for i, _s in ordered]
    return out_symbols, out_frac, out_bonds, info, source


def _contiguous(group, graph):
    # type: (list, object) -> tuple
    """Lay a component out contiguously. `(placement, periodic)`.

    `placement` maps atom index -> the integer lattice shift that puts it
    next to its neighbours. A component that closes on itself through the
    boundary (a chain, layer or framework) cannot be laid out at all, and
    says so.
    """
    adjacency = {}
    for e in graph.edges:
        adjacency.setdefault(e.i, []).append((e.j, np.array(e.shift, int)))
        adjacency.setdefault(e.j, []).append((e.i, -np.array(e.shift, int)))
    wanted = set(group)
    place = {group[0]: np.zeros(3, dtype=int)}
    stack = [group[0]]
    periodic = False
    while stack:
        i = stack.pop()
        for j, shift in adjacency.get(i, ()):
            if j not in wanted:
                continue
            target = place[i] + shift
            if j not in place:
                place[j] = target
                stack.append(j)
            elif np.any(place[j] != target):
                periodic = True
    return place, periodic


def _covalent_fragments(graph, symbols):
    # type: (object, list) -> tuple
    """`(place, families)` for the COVALENT fragments of the graph.

    `place[i]` is `(root, relative shift)`, so a whole fragment can be
    carried to a new lattice position without re-walking it. Metal-to-metal
    is excluded: it is covalent by `bond_kind`'s design (so an SBU is not
    dissected) but it is not what holds a MOLECULE together, and following
    it here would grow a slab of metal.
    """
    place = {}
    adjacency = {}
    for e in graph.edges:
        if bonding.bond_kind(symbols[e.i],
                             symbols[e.j]) != bonding.COVALENT:
            continue
        if bonding.is_metal(symbols[e.i]) and bonding.is_metal(symbols[e.j]):
            continue
        shift = np.array(e.shift, dtype=int)
        adjacency.setdefault(e.i, []).append((e.j, shift))
        adjacency.setdefault(e.j, []).append((e.i, -shift))
    for seed in range(len(symbols)):
        if seed in place:
            continue
        place[seed] = (seed, np.zeros(3, dtype=int))
        stack = [seed]
        while stack:
            i = stack.pop()
            for j, shift in adjacency.get(i, ()):
                if j in place:
                    continue
                place[j] = (seed, place[i][1] + shift)
                stack.append(j)
    families = {}
    for atom, (root, _rel) in place.items():
        families.setdefault(root, []).append(atom)
    return place, families


def _without_metal_metal(graph):
    # type: (object) -> object
    """Drop every metal-to-metal edge — VESTA's convention.

    Christian's call, twice over: VESTA draws none of these, not even for
    lithium, and a metal-metal "bond" can be 6 A long, which makes it a
    genuinely different animal from every other kind. Here it was also
    producing a superfluous outer layer of metal, because the shell growth
    followed it. Excluding it outright costs the real cases (an intermetallic
    draws bare, a paddlewheel loses its M-M contact) and buys a picture whose
    rule can be stated in one line.
    """
    keep = [e for e in graph.edges
            if not (bonding.is_metal(graph.symbols[e.i])
                    and bonding.is_metal(graph.symbols[e.j]))]
    return bondgraph.PeriodicGraph(graph.symbols, graph.frac, graph.cell,
                                   keep)


def wholly_disordered(data):
    # type: (object) -> bool
    """Is EVERY site partially occupied?

    Then there is no ordered skeleton and no atom is an "alternative" to any
    other in the usual sense — the honest picture of a smeared molecule is the
    smear (round 42c). `2240539.cif` is the case: a plastic crystal over 192
    operations of Fm-3m with every site at 0.21-0.43, where the occupancy-sum
    rule would otherwise refuse EVERY bond in the structure and draw 310 loose
    spheres.
    """
    occ = getattr(data, "occupancy", None)
    return bool(occ) and all(float(o) < 1.0 - 1e-6 for o in occ)


def _without_alternatives(graph, occupancy, ceiling=1.05):
    # type: (object, np.ndarray, float) -> tuple
    """Drop bonds between atoms that cannot both be there.

    Two partially occupied atoms whose occupancies sum to about one (or less)
    are ALTERNATIVES — the same guest modelled in two orientations — so a
    bond between them is never real, whatever the distance says. And distance
    genuinely cannot settle it: ZIF-7's disordered water alternatives sit
    1.359 A apart, which is squarely inside the O-O window (a peroxide bond
    is 1.48 A). The information that separates them lives in the occupancy
    column, not in the geometry.

    It also fixes a second symptom. Those spurious bonds fuse the guest
    oxygens into one multi-atom fragment, and the completion then computes
    the fragment's lattice positions as a GROUP — so an oxygen on a cell edge
    came out at three of its four positions instead of all four.
    """
    if occupancy is None or not len(occupancy):
        return graph, 0
    keep = []
    dropped = 0
    for e in graph.edges:
        a = occupancy[e.i] if e.i < len(occupancy) else 1.0
        b = occupancy[e.j] if e.j < len(occupancy) else 1.0
        if a < 1.0 - 1e-6 and b < 1.0 - 1e-6 and a + b <= ceiling:
            dropped += 1
            continue
        keep.append(e)
    return bondgraph.PeriodicGraph(graph.symbols, graph.frac, graph.cell,
                                   keep), dropped


def classify_occupancy(data, n_drawn, tol=0.1, disorder=None):
    # type: (object, int, float) -> tuple
    """Split partial occupancies into "distinct" and "shared", per Christian.

    Returns `({drawn index (str): [(element, occupancy), ...]}, info)` — the
    composition map for the SHARED sites, which is what a pie sphere is drawn
    from, plus counts for the trace.

    **The subtlety that makes this stage necessary at all**: by the time the
    atoms exist, the shared site has already been destroyed. `expand`'s
    minimum-image de-duplication merges the co-located species before
    occupancy is ever consulted — on `SodiumNicotinate.cif` a nitrogen at
    exactly the same coordinates as a carbon comes out with multiplicity ZERO
    and simply is not there. So the composition cannot be recovered from the
    drawn atoms; it has to be computed from the ASYMMETRIC UNIT, which is what
    `cif.site_composition` does.

    Note there is no CIF tag that declares this case. `_atom_site_disorder_
    group`/`_assembly` declare the OTHER one (mutually exclusive alternatives
    of a molecule). A shared crystallographic position is written as several
    `_atom_site_` rows with identical fractional coordinates and occupancies
    summing to about one, and has to be recognised geometrically.
    """
    report = {}
    cif_mod.expand(data, whole_molecules=False, boundary=False,
                   disorder=disorder or cif_mod.POLICY_ALL,
                   tol=tol, report=report)
    site_of = report.get("site_of") or []
    shared = cif_mod.site_composition(data, tol=tol)
    composition = {}
    for k, site in enumerate(site_of[:n_drawn]):
        if site in shared:
            composition[str(k)] = [[str(sym), float(occ)]
                                   for sym, occ in shared[site]]
    occupancy = [float(o) for o in (data.occupancy or [])]
    distinct = set()
    for k, site in enumerate(site_of[:n_drawn]):
        if str(k) in composition:
            continue
        if site < len(occupancy) and occupancy[site] < 1.0 - 1e-6:
            distinct.add(k)
    occupancy_of = np.array(
        [occupancy[s] if s < len(occupancy) else 1.0
         for s in site_of[:n_drawn]] + [1.0] * max(0, n_drawn - len(site_of)),
        dtype=float)
    info = {
        "shared_atoms": len(composition),
        "shared_sites": len({tuple(v) for v in
                             (tuple(map(tuple, c)) for c in
                              composition.values())}),
        "distinct": len(distinct),
        "compositions": sorted({tuple((s, o) for s, o in v)
                                for v in composition.values()}),
        "merged_away": sum(1 for s in shared
                           if s not in set(site_of)),
    }
    return composition, info, occupancy_of


def _in_cell(f, tol=1e-9):
    # type: (np.ndarray, float) -> bool
    """Inside the CLOSED cell, give or take numerical noise.

    Closed rather than half-open, and tolerant, because a symmetry operator
    routinely produces an exact 0 as -0.0 and a bare `>= 0` then calls that
    atom outside — which is enough to lose a whole molecule here.
    """
    return bool(np.all(f >= -tol) and np.all(f <= 1.0 + tol))
