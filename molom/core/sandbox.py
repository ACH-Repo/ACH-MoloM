"""The packing pipeline, exposed ONE STAGE AT A TIME, for the 🧪 add-on.

**This is no longer an experiment.** The algorithm was promoted to
`core.packing` and is what MoloM draws; this module imports it and adds only
the stage boundaries and the per-stage trace, so the page cannot describe
something the application does not do. What follows is kept because it is the
reasoning that produced the algorithm.

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

from . import bondgraph
from . import cif as cif_mod
from . import pipeline
from . import packing
from .packing import (boundary_instances, classify_occupancy,
                      complete_molecules, _without_alternatives,
                      _without_metal_metal)
from .pipeline import Result, Stage, StageInfo

__all__ = ["STAGES", "run", "stage_index", "complete_molecules",
           "boundary_instances", "classify_occupancy"]


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


def run(text, upto, outside=True, disorder=None, grow_from_copies=False):
    # type: (str, int, bool, str, bool) -> Result
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
    if not packing.wholly_disordered(data):
        graph, _refused_alt = _without_alternatives(graph, occupancy_of)

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
        symbols, frac, cell, graph=graph, outside=outside, seeds=instances,
        grow_from_copies=grow_from_copies)
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
