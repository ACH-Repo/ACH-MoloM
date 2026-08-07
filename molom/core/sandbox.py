"""SANDBOX pipeline — an alternative crystal algorithm, under experiment.

Nothing in the app reads this. It exists so a different ordering can be tried
and looked at, one stage at a time, without touching what MoloM ships.

**The idea being tried (Christian, 2026-08-06), in his own terms.** Wrap is
the correct placement of sites for a picture with no atoms outside the
boundary — it is what VESTA shows, and on `242083.cif` it is exactly right.
So the completion step that follows should COMPLETE every fragment that
reaches into the cell, in place, rather than relocating one of them:

    "if wrap is the correct placement of sites for the visualisation without
     atoms outside the boundary, then molecules should complete all four
     quarter fullerenes for the visualisation including atoms outside the
     boundary"

That is Mercury's packing rule, and it differs from what MoloM does today.
The shipping pipeline makes each fragment CONTIGUOUS instead, moving it
bodily so its centroid lands in the cell — which preserves the cell content
exactly (312 atoms = Z formula units on that file) but relocates the
fullerene that was split across the four c-edges, and once it has moved it is
no longer on a face, so the boundary step has nothing left to repeat. One
fullerene is completed where five belong.

Here the order is different:

    0 cell        the box alone
    1 sites       the atoms as the file lists them
    2 operators   x' = Wx + w, nothing else
    3 wrap        x - floor(x), atom by atom  -- the VESTA picture
    4 dedupe      merge coincident images
    5 bonds       connectivity from the PERIODIC graph, drawn only where both
                  ends are inside the cell
    6 molecules   every fragment reaching into the cell, drawn WHOLE

Stage 5 is where this pipeline stops pretending the wrap is harmless: the
wrap tears a molecule across a face, so straight-line bonds on wrapped
coordinates are simply wrong. Connectivity is taken from the labelled
periodic graph, which is translation-invariant and therefore still sees the
torn molecule as one thing. Stage 6 then materialises the missing parts.
"""
from __future__ import annotations

import numpy as np

from . import bonding
from . import bondgraph
from . import cif as cif_mod
from . import pipeline
from .pipeline import Result, Stage, StageInfo

__all__ = ["STAGES", "run", "stage_index", "complete_molecules"]


STAGES = list(pipeline.STAGES[:pipeline.stage_index("dedupe") + 1]) + [
    Stage("occupancy", "Occupancy",
          "Settle what a partially occupied SITE is, as an atom. Two cases, "
          "and they need opposite treatment: alternatives that are spatially "
          "DISTINCT are drawn as full atoms (a methyl over two orientations "
          "then shows six hydrogens, which is an honest cue that it rotates); "
          "alternatives sitting on TOP of each other are one position shared "
          "by several species and collapse to a single pie-chart atom."),
    Stage("boundary", "Boundary",
          "An atom lying exactly ON a face belongs to both faces, on an edge "
          "to four, on a corner to all eight -- 2^k copies for k coordinates "
          "on a boundary. The wrap cannot produce these (it is a function: "
          "0 maps to 0, never to 1), so they are added here, and the "
          "completion downstream works off them."),
    Stage("bonds", "Bonds",
          "Connectivity from the labelled PERIODIC graph, drawn only where "
          "both ends are present. Over-valence is ALLOWED: a carbon carrying "
          "six hydrogens is what a methyl disordered over two orientations "
          "should look like, and both VESTA and Mercury draw it."),
    Stage("molecules", "Molecules",
          "Every fragment with at least one atom inside the cell, drawn "
          "WHOLE. Mercury's packing rule: nothing is relocated, the parts "
          "that were missing are materialised, so a molecule split across "
          "four corners becomes four complete molecules."),
]


def stage_index(key):
    # type: (str) -> int
    for i, stage in enumerate(STAGES):
        if stage.key == key:
            return i
    raise KeyError(key)


def run(text, upto, outside=True, disorder=None):
    # type: (str, int, bool, str) -> Result
    """Run the sandbox up to stage `upto`, from scratch.

    Stages 0-4 are `pipeline.run`'s own, so the part that is not under
    experiment cannot drift. `outside` is the checkbox: with it off, stage 6
    keeps only the atoms inside the cell (but with correct connectivity);
    with it on, every fragment reaching in is completed outwards.
    """
    upto = max(0, min(int(upto), len(STAGES) - 1))
    last_shared = pipeline.stage_index("dedupe")
    base = pipeline.run(text, min(upto, last_shared), disorder=disorder)
    if upto <= last_shared or base.error:
        return base

    try:
        data = cif_mod.parse_cif(text)
    except (cif_mod.CifError, ValueError) as exc:
        return Result([], np.zeros((0, 3)), [], base.cell, base.trace,
                      str(exc))

    cell = base.cell
    symbols = list(base.symbols)
    frac = cell.to_fractional(np.asarray(base.coords, dtype=float))
    trace = list(base.trace)

    # ----------------------------------------------------- 5 occupancy
    composition, occ_info, occupancy_of = classify_occupancy(data,
                                                             len(symbols))
    meta = {"site_occupancy": composition} if composition else {}
    trace.append(StageInfo(
        "occupancy", "Occupancy", len(symbols), 0,
        _occupancy_note(occ_info)))
    if upto == stage_index("occupancy"):
        return Result(symbols, frac @ cell.matrix(), [], cell, trace, "",
                      meta)

    # ------------------------------------------------------ 6 boundary
    instances, face_info = boundary_instances(frac)
    b_symbols = [symbols[i] for i, _s in instances]
    b_frac = np.array([frac[i] + np.array(s, dtype=float)
                       for i, s in instances], dtype=float)
    if composition:
        meta = {"site_occupancy": {
            str(k): composition[str(i)]
            for k, (i, _s) in enumerate(instances) if str(i) in composition}}
    trace.append(StageInfo(
        "boundary", "Boundary", len(b_symbols), 0,
        _boundary_note(face_info, len(symbols), len(b_symbols))))
    if upto == stage_index("boundary"):
        return Result(b_symbols, b_frac @ cell.matrix(), [], cell, trace,
                      "", meta)

    # Over-valence is allowed here, on purpose -- see the stage summary.
    graph = bondgraph.build(symbols, frac, cell, valence=False,
                            cap_hydrogens=False)
    graph = _without_metal_metal(graph)
    graph, refused_alt = _without_alternatives(graph, occupancy_of)

    # --------------------------------------------------------- 7 bonds
    drawable = graph.instantiate(instances)
    trace.append(StageInfo(
        "bonds", "Bonds", len(b_symbols), len(drawable),
        _bond_note(graph, drawable, b_symbols)))
    if upto == stage_index("bonds"):
        return Result(b_symbols, b_frac @ cell.matrix(), drawable, cell,
                      trace, "", meta)

    # ----------------------------------------------------- 8 molecules
    out_symbols, out_frac, out_bonds, info, source = complete_molecules(
        symbols, frac, cell, graph=graph, outside=outside, seeds=instances)
    # A copy of a shared site is still that site, so the composition has to
    # be carried onto the copies or the cell shows one pie sphere in the
    # middle and plain ones at every corner (round 42's rule).
    if composition:
        meta = {"site_occupancy": {
            str(k): composition[str(src)]
            for k, src in enumerate(source) if str(src) in composition}}
    trace.append(StageInfo(
        "molecules", "Molecules", len(out_symbols), len(out_bonds),
        _molecule_note(info, outside, len(symbols), len(out_symbols))))
    return Result(out_symbols, out_frac @ cell.matrix(), out_bonds, cell,
                  trace, "", meta)


def classify_occupancy(data, n_drawn, tol=0.1):
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
                   disorder=cif_mod.POLICY_ALL, report=report)
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
                       max_atoms=200000, seeds=None):
    # type: (list, np.ndarray, object, object, bool, int, list) -> tuple
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
                for i, s in list(seeded):
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
                        for k in families[root]:
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


def _in_cell(f, tol=1e-9):
    # type: (np.ndarray, float) -> bool
    """Inside the CLOSED cell, give or take numerical noise.

    Closed rather than half-open, and tolerant, because a symmetry operator
    routinely produces an exact 0 as -0.0 and a bare `>= 0` then calls that
    atom outside — which is enough to lose a whole molecule here.
    """
    return bool(np.all(f >= -tol) and np.all(f <= 1.0 + tol))


def _occupancy_note(info):
    # type: (dict) -> str
    lines = []
    if not info["shared_atoms"] and not info["distinct"]:
        return "no partial occupancies: every site is fully occupied"
    lines.append("A) spatially DISTINCT partial occupancies: {} atom(s), "
                 "drawn as full atoms".format(info["distinct"]))
    lines.append("B) SHARED positions: {} atom(s) carrying a composition, "
                 "drawn as pie spheres".format(info["shared_atoms"]))
    for comp in info["compositions"]:
        lines.append("     {}".format(" / ".join(
            "{} {:.2f}".format(sym, occ) for sym, occ in comp)))
    if info["merged_away"]:
        lines.append("note: {} site(s) of a shared position were merged away "
                     "by Dedupe before occupancy was consulted -- the "
                     "composition is recovered from the asymmetric "
                     "unit".format(info["merged_away"]))
    return "\n".join(lines)


def _boundary_note(counts, before, after):
    # type: (dict, int, int) -> str
    lines = ["{} atom(s) ({:+d} copies)".format(after, after - before)]
    for k, label in ((1, "a face"), (2, "an edge"), (3, "a corner")):
        if counts.get(k):
            lines.append("{} atom(s) on {} -> {} position(s) each".format(
                counts[k], label, 2 ** k))
    if after == before:
        lines.append("no atom sits exactly on a boundary, so there is "
                     "nothing to repeat")
    return "\n".join(lines)


def _bond_note(graph, drawable, symbols):
    # type: (object, list, list) -> str
    crossing = len(graph.crossing_edges())
    ranks = sorted({rank for _g, rank in graph.components()})
    names = {0: "molecule", 1: "chain", 2: "layer", 3: "framework"}
    degree = {}
    for i, j, _o in drawable:
        degree[i] = degree.get(i, 0) + 1
        degree[j] = degree.get(j, 0) + 1
    lines = [
        "{} bond(s) drawable on the atoms present".format(len(drawable)),
        "the periodic graph has {} edge(s), {} of them crossing a cell "
        "face".format(len(graph.edges), crossing),
        "components: {}".format(", ".join(names.get(r, str(r))
                                          for r in ranks) or "none"),
    ]
    # Over-valence is allowed here, so say where it happened rather than
    # leaving the picture to be second-guessed.
    over = [(symbols[k], d) for k, d in degree.items()
            if symbols[k] == "C" and d > 4]
    if over:
        lines.append("{} carbon(s) with more than four bonds (allowed: a "
                     "disordered methyl really does want six H)".format(
                         len(over)))
    multi_h = sum(1 for k, d in degree.items()
                  if symbols[k] == "H" and d > 1)
    if multi_h:
        lines.append("{} hydrogen(s) with more than one bond".format(multi_h))
    return "\n".join(lines)


def _molecule_note(info, outside, before, after):
    # type: (dict, bool, int, int) -> str
    lines = [
        "{} component(s): {} finite, {} periodic".format(
            info["components"], info["finite"], info["periodic"]),
        "{} whole copy(ies) drawn -- one per lattice position that reaches "
        "into the cell".format(info["copies"]),
        "{} atom(s) ({:+d})".format(after, after - before),
    ]
    if not outside:
        lines.append("atoms outside the boundary are HIDDEN (tick the box to "
                     "draw the completed molecules)")
    if info["periodic"]:
        lines.append("{} chain/layer/framework component(s): no 'whole' to "
                     "complete, so each drawn atom's own coordination is "
                     "closed instead -- {} partner(s) materialised".format(
                         info["periodic"], info["shell"]))
    if info["capped"]:
        lines.append("INSTANCE CAP HIT -- output truncated")
    return "\n".join(lines)
