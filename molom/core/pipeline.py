"""The CIF visualisation pipeline, exposed ONE STAGE AT A TIME.

For debugging by inspection: run a file up to stage N and see exactly what is
on screen at that point, with nothing from the later stages applied. Every run
starts from the CIF TEXT and rebuilds from scratch, so a stage can never show
you state left behind by a previous click — which is the whole reason this
exists rather than a set of toggles on the crystal page.

The stages are the ones the code really has, in the order `cif.expand` really
runs them:

    0 cell        the box alone, no atoms
    1 sites       the atoms as the file lists them (the asymmetric unit)
    2 symmetry    the operators applied, duplicates on special positions merged
    3 disorder    partially occupied alternatives resolved
    4 molecules   fragments made contiguous across the cell faces
    5 boundary    atoms lying ON a face repeated onto their other faces
    6 bonds       bonds instantiated from the labelled periodic graph
    7 complete    bonded partners outside the box materialised

Stages 2-5 are NOT reimplemented here: they are `cif.expand`'s own flags, so
this cannot drift from what an ordinary import does. Stages 6-7 are the
round-44 graph (`cif.display_bonds` / `cif.missing_partners`).
"""
from __future__ import annotations

from collections import namedtuple

import numpy as np

from . import cif as cif_mod

__all__ = ["STAGES", "Stage", "StageInfo", "Result", "run", "stage_index"]


#: One step of the pipeline. `label` is what the button says.
Stage = namedtuple("Stage", "key label summary")

#: What one stage did, for the trace the debug page prints.
StageInfo = namedtuple("StageInfo", "key label atoms bonds note")

#: The finished picture plus the trace that produced it. `meta` is merged into
#: the drawn structure's metadata, which is how a stage hands the viewport
#: something it cannot infer from coordinates — the per-atom composition of a
#: shared site, for instance.
Result = namedtuple("Result", "symbols coords bonds cell trace error meta")
Result.__new__.__defaults__ = (None,)


STAGES = [
    Stage("cell", "Cell",
          "The unit cell box alone, straight from _cell_length_* and "
          "_cell_angle_*. No atoms at all."),
    Stage("sites", "Sites",
          "The atoms exactly as the file lists them in _atom_site_*, with no "
          "symmetry applied and no bonds. For most files this is the "
          "asymmetric unit, which is a fraction of the cell."),
    Stage("operators", "Operators",
          "Every symmetry operator applied to every site -- x' = Wx + w and "
          "nothing else. No wrapping and no merging, so copies land wherever "
          "the arithmetic puts them, including well outside the box."),
    Stage("wrap", "Wrap",
          "Each atom brought into [0, 1) by x - floor(x). This is what puts "
          "the structure inside the box; the operators alone do not. Note it "
          "wraps ATOM BY ATOM, so a molecule straddling a face is torn in "
          "half here and only reassembled at the Molecules stage."),
    Stage("dedupe", "Dedupe",
          "Copies landing on an atom already placed are merged (0.1 A, "
          "minimum image). This is what stops a site on a special position "
          "piling up duplicates, and it is where a symmetry-redundant row in "
          "the file quietly disappears."),
    Stage("disorder", "Disorder",
          "Partially occupied alternatives resolved, so atoms that are never "
          "present together are not drawn together."),
    Stage("molecules", "Molecules",
          "Fragments split by the cell boundary walked back together, so a "
          "molecule is whole instead of having atoms stranded on a far face. "
          "A periodic framework is left wrapped -- it cannot be made "
          "contiguous."),
    Stage("boundary", "Boundary",
          "Atoms lying exactly ON a face, edge or corner repeated onto the "
          "equivalent positions. This is why rock salt shows eight corner "
          "sodiums rather than one."),
    Stage("bonds", "Bonds",
          "Bonds instantiated from the labelled periodic graph. Built on the "
          "cell content once, then looked up per drawn atom, so an atom "
          "drawn twice at opposite faces gets a full sphere at each copy."),
    Stage("fragments", "Fragments",
          "Molecules that straddle a face carried over WHOLE, rather than "
          "cut at the wall. Half a five-ring is not a thing that exists."),
    Stage("complete", "Complete",
          "Bonded partners that fall outside the box materialised, one shell, "
          "so a linker crossing a face is not left dangling. A lone ion in a "
          "lattice is deliberately NOT followed, or the cell fills with a "
          "slab. After this the picture is what an ordinary import draws."),
]


def stage_index(key):
    # type: (str) -> int
    for i, stage in enumerate(STAGES):
        if stage.key == key:
            return i
    raise KeyError(key)


def operator_images(data):
    # type: (object) -> tuple
    """`(symbols, FRACTIONAL coords)` for every (site, operator) pair.

    The Operators stage, in fractional space. Shared with `core.sandbox` and
    returned as FRACTIONS on purpose: a caller that needs to reason about
    cell boundaries must not have to convert back from Cartesian, because the
    round trip through the cell matrix moves a coordinate of exactly 0.0 or
    1.0 by an epsilon and every `< 1.0` test then disagrees with itself.
    """
    frac = np.asarray(data.frac, dtype=float).reshape(data.n_sites, 3)
    symbols = []
    raw = []
    for site in range(data.n_sites):
        for op in data.symops:
            raw.append(op.apply(frac[site]))
            symbols.append(data.symbols[site])
    return symbols, (np.asarray(raw, dtype=float).reshape(-1, 3) if raw
                     else np.zeros((0, 3)))


def _empty(cell=None, trace=None, error=""):
    return Result([], np.zeros((0, 3)), [], cell, list(trace or []), error)


def run(text, upto, disorder=None):
    # type: (str, int, str) -> Result
    """Run the pipeline up to and including stage `upto`, from scratch.

    `upto` is an index into `STAGES`. Returns the atoms, the bonds and a
    per-stage trace of what each step did to the count.
    """
    upto = max(0, min(int(upto), len(STAGES) - 1))
    disorder = disorder or cif_mod.POLICY_DOMINANT
    trace = []

    try:
        data = cif_mod.parse_cif(text)
    except (cif_mod.CifError, ValueError) as exc:
        return _empty(error="Could not read that as CIF: {}".format(exc))

    cell = data.cell
    note = "a={:.4f} b={:.4f} c={:.4f}  alpha={:.3f} beta={:.3f} " \
           "gamma={:.3f}\nvolume {:.2f} A^3".format(
               cell.a, cell.b, cell.c, cell.alpha, cell.beta, cell.gamma,
               cell.volume())
    trace.append(StageInfo("cell", "Cell", 0, 0, note))
    if upto == 0:
        return Result([], np.zeros((0, 3)), [], cell, trace, "")

    # ---------------------------------------------------------- 1 sites
    symbols = list(data.symbols)
    frac = np.asarray(data.frac, dtype=float).reshape(len(symbols), 3)
    ops = len(data.symops)
    note = "{} site(s) listed in the file\n{} symmetry operator(s) " \
           "available ({})".format(len(symbols), ops,
                                   data.symmetry_source or "file")
    if data.symmetry_note:
        note += "\n" + data.symmetry_note
    trace.append(StageInfo("sites", "Sites", len(symbols), 0, note))
    result = (symbols, frac @ cell.matrix(), [])
    if upto == 1:
        return Result(result[0], result[1], [], cell, trace, "")

    # ------------------------------------------- 2-3 operators, then wrap
    # These two do not exist as `cif.expand` configurations — they are the
    # inside of its inner loop, split open. The stage BELOW them is expand's
    # real output, and a test pins the three together so this cannot drift.
    op_symbols, raw = operator_images(data)
    outside = int(((raw < 0.0) | (raw >= 1.0)).any(axis=1).sum())
    trace.append(StageInfo(
        "operators", "Operators", len(op_symbols), 0,
        "{} site(s) x {} operator(s) = {} atom(s)\n{} of them lie OUTSIDE "
        "[0, 1) -- the operators do not put anything in the box".format(
            data.n_sites, ops, len(op_symbols), outside)))
    if upto == 2:
        return Result(op_symbols, raw @ cell.matrix(), [], cell, trace, "")

    wrapped = raw - np.floor(raw)
    moved = int((np.abs(wrapped - raw) > 1e-12).any(axis=1).sum())
    trace.append(StageInfo(
        "wrap", "Wrap", len(op_symbols), 0,
        "{} atom(s) ({} moved, none created or destroyed)\nevery atom is now "
        "inside the box, but a molecule across a face is torn in two".format(
            len(op_symbols), moved)))
    if upto == 3:
        return Result(op_symbols, wrapped @ cell.matrix(), [], cell, trace, "")

    # ------------------------------------------------ 4-7 via cif.expand
    # The REAL import path, one flag at a time, so this page cannot describe
    # a pipeline the app does not run.
    previous = len(op_symbols)
    plan = [
        ("dedupe", dict(whole_molecules=False, boundary=False,
                        disorder=cif_mod.POLICY_ALL)),
        ("disorder", dict(whole_molecules=False, boundary=False,
                          disorder=disorder)),
        ("molecules", dict(whole_molecules=True, boundary=False,
                           disorder=disorder)),
        ("boundary", dict(whole_molecules=True, boundary=True,
                          disorder=disorder)),
    ]
    n_content = len(symbols)
    for offset, (key, kwargs) in enumerate(plan):
        index = 4 + offset
        report = {}
        try:
            symbols, coords = cif_mod.expand(data, report=report, **kwargs)
        except (cif_mod.CifError, ValueError) as exc:
            return Result(result[0], result[1], [], cell, trace,
                          "{} failed: {}".format(key, exc))
        n_content = int(report.get("n_content", len(symbols)))
        note = _stage_note(key, previous, len(symbols), report, n_content,
                           data=data)
        trace.append(StageInfo(key, STAGES[index].label, len(symbols), 0,
                               note))
        previous = len(symbols)
        result = (symbols, coords, [])
        if upto == index:
            return Result(symbols, coords, [], cell, trace, "")

    symbols, coords = result[0], result[1]

    # ------------------------------------------------------- 6 bonds
    bonds = cif_mod.display_bonds(symbols, coords, cell, n_content)
    graph_note = _graph_note(symbols, coords, cell, n_content)
    trace.append(StageInfo("bonds", "Bonds", len(symbols), len(bonds),
                           "{} bond(s) drawn\n{}".format(len(bonds),
                                                         graph_note)))
    if upto == stage_index("bonds"):
        return Result(symbols, coords, bonds, cell, trace, "")

    # ----------------------------------------------------- whole molecules
    # The same two steps `BoundaryModifier` runs, in the same order, so the
    # last stage of this page is the picture an ordinary import produces.
    before = len(symbols)
    frac = cell.to_fractional(coords)
    ex_symbols, ex_frac = cif_mod.crossing_fragments(list(symbols), frac, cell)
    if len(ex_symbols):
        symbols = list(symbols) + list(ex_symbols)
        coords = np.vstack([coords,
                            np.asarray(ex_frac).reshape(-1, 3)
                            @ cell.matrix()])
    bonds = cif_mod.display_bonds(symbols, coords, cell, n_content)
    trace.append(StageInfo(
        "fragments", "Fragments", len(symbols), len(bonds),
        "{} atom(s) added carrying whole molecules over the "
        "faces\n{} bond(s) drawn".format(len(symbols) - before, len(bonds))))
    if upto == stage_index("fragments"):
        return Result(symbols, coords, bonds, cell, trace, "")

    # -------------------------------------------------------- completion
    add_symbols, add_frac = cif_mod.missing_partners(
        symbols, coords, cell, n_content)
    if len(add_symbols):
        keep = cif_mod._unseen(add_symbols, add_frac, symbols,
                               cell.to_fractional(coords))
        add_symbols = [s for s, k in zip(add_symbols, keep) if k]
        add_frac = np.asarray(add_frac)[keep]
        if len(add_symbols):
            symbols = list(symbols) + list(add_symbols)
            coords = np.vstack([coords,
                                np.asarray(add_frac).reshape(-1, 3)
                                @ cell.matrix()])
    bonds = cif_mod.display_bonds(symbols, coords, cell, n_content)
    trace.append(StageInfo(
        "complete", "Complete", len(symbols), len(bonds),
        "{} partner(s) outside the box materialised\n{} bond(s) drawn\n"
        "this is what an ordinary import of this file draws".format(
            len(add_symbols), len(bonds))))
    return Result(symbols, coords, bonds, cell, trace, "")


def _stage_note(key, before, after, report, n_content, data=None):
    # type: (str, int, int, dict, int, object) -> str
    delta = after - before
    change = ("+{}".format(delta) if delta > 0
              else str(delta) if delta else "no change")
    lines = ["{} atom(s) ({})".format(after, change)]
    if key == "dedupe":
        lines.append("{} copy(ies) merged onto an atom already "
                     "placed".format(max(0, -delta)))
        lines.extend(_multiplicity_lines(data, after))
    if key == "disorder":
        info = report.get("disorder") or {}
        if info.get("wholly_disordered"):
            lines.append("every site is partially occupied, so nothing is "
                         "dominant and the smear is drawn as it stands")
        elif info:
            lines.append("dropped {} (by group {}, by overlap {}, below "
                         "threshold {})".format(
                             info.get("dropped", 0), info.get("by_group", 0),
                             info.get("by_overlap", 0),
                             info.get("by_threshold", 0)))
        else:
            lines.append("nothing to resolve: no partial occupancies")
    if key == "boundary":
        lines.append("{} of these are the cell CONTENT; the rest are "
                     "copies".format(n_content))
    return "\n".join(lines)


def _multiplicity_lines(data, total):
    # type: (object, int) -> list
    """Per-site multiplicity, which is the cheapest correctness check there is.

    A site's multiplicity must DIVIDE the number of operators; anything else
    means the site is refined slightly off a special position and the answer
    is tolerance-dependent. A site contributing NOTHING is the other case
    worth naming out loud: it is a symmetry-redundant row, the pattern that
    makes pymatgen report occupancy 2 on urea, and it vanishes here silently.
    """
    if data is None or not data.n_sites:
        return []
    matrix = data.cell.matrix()
    frac = np.asarray(data.frac, dtype=float).reshape(data.n_sites, 3)
    placed = []
    counts = []
    for site in range(data.n_sites):
        before = len(placed)
        for op in data.symops:
            f = op.apply(frac[site])
            f = f - np.floor(f)
            if cif_mod._is_new(f, placed, matrix, 0.1, True):
                placed.append(f)
        counts.append(len(placed) - before)
    if len(placed) != total:
        # The breakdown is recomputed rather than reported by `expand`, so if
        # the two ever disagree say so instead of printing a confident lie.
        return ["(per-site breakdown unavailable: {} vs {})".format(
            len(placed), total)]
    ops = len(data.symops)
    general = sum(1 for c in counts if c == ops)
    special = [c for c in counts if 0 < c < ops]
    empty = sum(1 for c in counts if c == 0)
    odd = [c for c in special if ops % c]
    lines = ["{} site(s) on a general position ({} images each)".format(
        general, ops)]
    if special:
        lines.append("{} site(s) on a SPECIAL position, multiplicity {}"
                     .format(len(special), sorted(set(special))))
    if empty:
        lines.append("{} site(s) contributed NOTHING -- symmetry-redundant "
                     "row(s) in the file".format(empty))
    if odd:
        lines.append("WARNING: multiplicity {} does not divide {} -- a site "
                     "is refined slightly off a special position".format(
                         sorted(set(odd)), ops))
    return lines


def _graph_note(symbols, coords, cell, n_content):
    # type: (list, np.ndarray, object, int) -> str
    from . import bondgraph
    frac = cell.to_fractional(np.asarray(coords, dtype=float))
    graph = bondgraph.build(list(symbols)[:n_content], frac[:n_content], cell)
    ranks = sorted({rank for _group, rank in graph.components()})
    names = {0: "molecule", 1: "chain", 2: "layer", 3: "framework"}
    kinds = ", ".join(names.get(r, str(r)) for r in ranks)
    return ("graph: {} edge(s) on {} content atom(s), {} of them crossing a "
            "cell face\ncomponents: {}".format(
                len(graph.edges), n_content, len(graph.crossing_edges()),
                kinds or "none"))
