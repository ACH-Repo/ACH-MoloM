"""Write a CIF that is actually a CRYSTAL.

Until this module existed there was no CIF writer at all: `io.
write_structure_file` handed OpenBabel an xyz block for any non-xyz
extension, so a `.cif` came out carrying coordinates and nothing else — no
`_cell_length_a`, no symmetry, no occupancies. Measured on a ZIF-8 export:
**MoloM's own parser rejected the file MoloM had just written** ("no unit cell
in this CIF"), and Mercury or VESTA would read it as a molecule at best.

What is written, and how it is decided
--------------------------------------
A CIF's content is `cell + operators + asymmetric unit`, so the question is
where to get those three from. There are two honest answers and the choice is
made by MEASUREMENT, not by a flag defaulted somewhere:

* **`asymmetric`** — the stored asymmetric unit, the file's own operators and
  its own space-group spelling, straight back out. Chosen when the stored unit
  still reproduces the drawn cell content, i.e. nothing has been edited. This
  is a lossless round trip, occupancies and disorder columns included, and it
  keeps the SETTING the file was written in (round 41: printing the standard
  `P2_1/c` for a file that says `P 21/n` reads as an outright error to the
  person who made the compound).
* **`cell`** — the cell CONTENT with its symmetry re-derived from the
  coordinates by spglib, reduced to one atom per orbit. This is the edited
  case: operators that no longer describe the structure would expand it into
  a cell that never existed, so they are never kept on trust.

`p1` writes the content with the identity alone, and is the fallback when
spglib finds nothing.

Two things are deliberately NOT guessed at. Occupancy cannot survive a
re-derivation — a drawn atom does not carry the site it came from — so the
`cell` policy writes 1.0 and SAYS so in the report rather than inventing
numbers. And a molecule with no cell gets a P1 box drawn round it, reported
as invented, because a bounding box is a container and not a crystal.

The operator loop is written under `_symmetry_equiv_pos_as_xyz`, the older of
the two synonymous spellings — pymatgen's choice, and what the installed base
of readers actually parses. Writing BOTH tags in one loop is what a first cut
did, and it doubles the operator count for any reader that recognises the
two: MoloM's own read the round trip back as 32 operations where the file had
16. The GROUP NAME is written under both spellings, which is safe because
those are single-valued tags rather than loop columns.

UI-free: numpy + stdlib.
"""

import datetime
from typing import List, Optional, Tuple

import numpy as np

from . import cif as cif_mod
from . import elements, spacegroups
from . import occupancy as occupancy_mod

#: How the crystallography for the written file is arrived at.
POLICY_ASYMMETRIC = "asymmetric"
POLICY_CELL = "cell"
POLICY_P1 = "p1"
POLICIES = (POLICY_ASYMMETRIC, POLICY_CELL, POLICY_P1)

#: Padding round a molecule that has no cell of its own, in Angstrom. Enough
#: that the P1 box never puts two images in contact — an invented cell must at
#: least not imply a bond that is not there.
INVENTED_PADDING = 6.0


# ---------------------------------------------------------------- formatting
def _quote(value):
    """CIF strings: bare where they can be, single-quoted otherwise.

    A value containing a quote has to go in a semicolon text field, which is
    the one case worth handling separately rather than emitting something a
    parser will choke on.
    """
    text = str(value).strip()
    if not text:
        return "?"
    if "'" in text or '"' in text or "\n" in text:
        return "\n;\n{}\n;".format(text.replace("\n;", "\n ;"))
    if any(c.isspace() for c in text) or text[0] in "_#$[]":
        return "'{}'".format(text)
    return text


def _num(value, places=5):
    return "{:.{}f}".format(float(value), places)


def site_labels(symbols, given=None):
    # type: (list, Optional[list]) -> List[str]
    """One UNIQUE `_atom_site_label` per row.

    The file's own labels are kept where they are present and distinct —
    they are what a crystallographer refers to their own atoms by, and a
    structure re-read after a round trip should still call C12A "C12A".
    Anything missing or repeated falls back to element + running number.
    """
    given = list(given or [])
    if len(given) == len(symbols) and all(str(g).strip() for g in given) \
            and len(set(str(g).strip() for g in given)) == len(symbols):
        return [str(g).strip() for g in given]
    counts, out = {}, []
    for symbol in symbols:
        sym = elements.symbol(elements.atomic_number(symbol)) or str(symbol)
        counts[sym] = counts.get(sym, 0) + 1
        out.append("{}{}".format(sym, counts[sym]))
    return out


def cif_text(cell, symbols, frac, symops=("x, y, z",), spacegroup="P 1",
             name="molom", occupancy=None, labels=None, it_number=0,
             info=None, notes=(), version="", disorder_groups=None,
             disorder_assemblies=None):
    # type: (object, list, object, tuple, str, str, list, list, int, dict, tuple, str, list, list) -> str
    """The finished file, as text. Pure formatting — every decision about
    WHAT to write is made by `from_object` above it."""
    frac = np.asarray(frac, dtype=float).reshape(-1, 3)
    symbols = list(symbols)
    labels = site_labels(symbols, labels)
    occupancy = ([float(o) for o in occupancy] if occupancy is not None
                 else [1.0] * len(symbols))
    block = "".join(c if (c.isalnum() or c == "_") else "_"
                    for c in (name or "molom")).strip("_") or "molom"
    lines = ["# Written by MoloM{}{}".format(
        " " + version if version else "",
        " on " + datetime.date.today().isoformat())]
    for note in notes:
        lines.append("# " + str(note))
    lines.append("")
    lines.append("data_{}".format(block))
    lines.append("_audit_creation_method{:<12}{}".format(
        "", _quote("MoloM" + (" " + version if version else ""))))
    for tag, key in (("_chemical_name_common", "name_common"),
                     ("_chemical_name_systematic", "name_systematic"),
                     ("_chemical_formula_sum", "formula_sum"),
                     ("_chemical_formula_weight", "formula_weight")):
        value = (info or {}).get(key)
        if value:
            lines.append("{:<34}{}".format(tag, _quote(value)))
    lines.append("")
    for tag, value in (("_cell_length_a", cell.a), ("_cell_length_b", cell.b),
                       ("_cell_length_c", cell.c),
                       ("_cell_angle_alpha", cell.alpha),
                       ("_cell_angle_beta", cell.beta),
                       ("_cell_angle_gamma", cell.gamma)):
        lines.append("{:<34}{}".format(tag, _num(value, 6)))
    lines.append("{:<34}{}".format("_cell_volume", _num(cell.volume(), 4)))
    lines.append("")
    # BOTH spellings of the group name and of the operator loop: they are
    # synonyms, and the pre-1991 ones are what most installed readers parse.
    for tag in ("_symmetry_space_group_name_H-M", "_space_group_name_H-M_alt"):
        lines.append("{:<34}{}".format(tag, _quote(spacegroup or "P 1")))
    if it_number:
        for tag in ("_symmetry_Int_Tables_number", "_space_group_IT_number"):
            lines.append("{:<34}{}".format(tag, int(it_number)))
    lines.append("")
    lines.append("loop_")
    lines.append("_symmetry_equiv_pos_site_id")
    lines.append("_symmetry_equiv_pos_as_xyz")
    for n, op in enumerate(symops or ("x, y, z",), start=1):
        lines.append("{:<4}{}".format(n, "'{}'".format(str(op).strip())))
    lines.append("")
    # The disorder columns are the crystallographer's OWN statement of which
    # alternatives go together, and `resolve_disorder` prefers them to
    # geometric overlap — so dropping them means the file we wrote resolves to
    # a different structure from the one we read (round 43c's bug, arriving
    # from the other direction). Written only when the file had them, since an
    # all-"." column is noise.
    groups = [str(g or "").strip() or "." for g in
              (disorder_groups or [""] * len(symbols))]
    assemblies = [str(a or "").strip() or "." for a in
                  (disorder_assemblies or [""] * len(symbols))]
    want_disorder = (len(groups) == len(symbols)
                     and len(assemblies) == len(symbols)
                     and (any(g != "." for g in groups)
                          or any(a != "." for a in assemblies)))
    lines.append("loop_")
    lines.append("_atom_site_label")
    lines.append("_atom_site_type_symbol")
    lines.append("_atom_site_fract_x")
    lines.append("_atom_site_fract_y")
    lines.append("_atom_site_fract_z")
    lines.append("_atom_site_occupancy")
    if want_disorder:
        lines.append("_atom_site_disorder_assembly")
        lines.append("_atom_site_disorder_group")
    for i, symbol in enumerate(symbols):
        sym = elements.symbol(elements.atomic_number(symbol)) or str(symbol)
        row = "{:<10}{:<6}{:>12}{:>12}{:>12}{:>10}".format(
            labels[i], sym, _num(frac[i][0]), _num(frac[i][1]),
            _num(frac[i][2]), _num(occupancy[i], 4))
        if want_disorder:
            row += "{:>8}{:>8}".format(assemblies[i], groups[i])
        lines.append(row)
    lines.append("")
    return "\n".join(lines)


# ------------------------------------------------------------------ policy
def _op_key(text):
    """A symmetry operation as a comparable key: rotation plus translation
    modulo one, rounded. Two files can spell the same operation half a dozen
    ways ("-x+1/2" / "0.5-x"), so string comparison answers the wrong
    question."""
    op = cif_mod.SymOp.from_xyz(str(text))
    rot = tuple(int(round(v)) for v in np.asarray(op.rotation).ravel())
    trans = tuple(int(round((v % 1.0) * 24.0)) % 24
                  for v in np.asarray(op.translation).ravel())
    return rot + trans


def operators_match(a, b):
    # type: (list, list) -> bool
    """Do two operator lists describe the same group?"""
    try:
        return {_op_key(t) for t in a} == {_op_key(t) for t in b}
    except (cif_mod.CifError, ValueError, TypeError):
        return False


def _wrapped(frac):
    return np.asarray(frac, dtype=float).reshape(-1, 3) % 1.0


def _site_keys(symbols, frac, grid=200):
    """{(element, rounded fractional position)} — a set to compare cells
    with. Rounded on a grid because two routes to the same site differ in the
    last few digits, and probing neighbours is not needed here: this asks
    whether a set is CONTAINED, and the containment test tries the neighbours
    itself."""
    keys = np.rint(_wrapped(frac) * grid).astype(int) % grid
    return {(str(s), tuple(int(v) for v in row))
            for s, row in zip(symbols, keys)}


def _covered(content_symbols, content_frac, expanded_symbols, expanded_frac,
             grid=200):
    """Is every drawn content atom reproduced by the stored asymmetric unit?

    The question is "has anything been edited?", and it is asked this way
    round on purpose: the drawn content may legitimately have FEWER atoms
    than the raw expansion, because the disorder policy dropped alternatives.
    A moved atom, by contrast, is simply not in the expansion at all.
    """
    have = _site_keys(expanded_symbols, expanded_frac, grid)
    for symbol, key in _site_keys(content_symbols, content_frac, grid):
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    probe = ((key[0] + dx) % grid, (key[1] + dy) % grid,
                             (key[2] + dz) % grid)
                    if (symbol, probe) in have:
                        break
                else:
                    continue
                break
            else:
                continue
            break
        else:
            return False
    return True


def invented_cell(coords, padding=INVENTED_PADDING):
    # type: (object, float) -> object
    """A P1 box round a molecule that has no cell.

    Not a crystal, and the caller is told so — but a CIF without a cell is not
    a CIF, and refusing to write one at all would be less useful than writing
    one honestly labelled.
    """
    xyz = np.asarray(coords, dtype=float).reshape(-1, 3)
    if not len(xyz):
        return cif_mod.Cell(10.0, 10.0, 10.0)
    span = xyz.max(axis=0) - xyz.min(axis=0) + 2.0 * float(padding)
    a, b, c = (max(float(v), 1.0) for v in span)
    return cif_mod.Cell(a, b, c, 90.0, 90.0, 90.0)


def from_object(obj, policy=None, version="", report=None):
    # type: (object, Optional[str], str, Optional[dict]) -> str
    """The CIF text for one scene object, choosing the policy by measurement.

    `report` collects what was decided, so the caller can put it in front of
    the user: a written file that quietly dropped the symmetry or invented a
    cell is the sort of wrongness that looks right.
    """
    report = report if report is not None else {}
    structure = obj.structure
    meta = dict(structure.metadata or {})
    symbols, coords, _bonds = obj.evaluated()
    coords = np.asarray(coords, dtype=float).reshape(-1, 3)
    name = meta.get("name") or getattr(obj, "name", "") or "molom"
    info = meta.get("cif_info") or {}
    notes = []

    cell_dict = meta.get("cell")
    if not cell_dict:
        cell = invented_cell(coords)
        report["invented_cell"] = True
        notes.append("No unit cell: this is a molecule in an invented P1 box, "
                     "not a crystal structure.")
        frac = _wrapped(cell.to_fractional(coords - coords.min(axis=0)
                                           + INVENTED_PADDING))
        report["policy"] = POLICY_P1
        report["n_sites"] = len(symbols)
        return cif_text(cell, symbols, frac, name=name, info=info,
                        notes=notes, version=version)

    cell = cif_mod.Cell.from_dict(cell_dict)
    # A rotated crystal's atoms are no longer in the cell's own frame, and
    # every fractional calculation assumes they are (round 43c). Undo the
    # pose before converting, or the written coordinates are the rotation.
    pose = obj.cell_pose(coords) if hasattr(obj, "cell_pose") else None
    if pose is not None:
        rotation, translation = pose
        coords = (coords - np.asarray(translation)) @ np.asarray(rotation)

    # Only the CONTENT: everything past `cell_content` is a boundary copy or a
    # completion, i.e. an exact lattice translate of an atom already listed.
    # Writing those would claim a cell with every face atom in it twice.
    n_content = int(meta.get("cell_content") or 0) or len(symbols)
    n_content = min(n_content, len(symbols))
    content_symbols = list(symbols[:n_content])
    content_frac = _wrapped(cell.to_fractional(coords[:n_content]))
    report["n_content"] = n_content
    report["n_drawn"] = len(symbols)

    file_ops = [str(t) for t in (meta.get("symops") or [])] or ["x, y, z"]
    asym_symbols = list(meta.get("asym_symbols") or [])
    asym_frac = np.asarray(meta.get("asym_frac") or [],
                           dtype=float).reshape(-1, 3)

    chosen = policy
    if chosen not in POLICIES:
        chosen = None
    # A composition the USER has set is not in the stored unit — that unit is
    # the file's own, from before they said otherwise. So it stops being a
    # verbatim round trip and the file has to be built from the drawn atoms,
    # where the edited compositions live.
    if chosen is None and meta.get("site_occupancy_edited"):
        chosen = POLICY_CELL
        notes.append("Site occupancies were edited in MoloM, so the sites "
                     "are written from the current structure.")
    if chosen in (None, POLICY_ASYMMETRIC) and len(asym_symbols):
        expanded_symbols, expanded_frac = _expand(asym_symbols, asym_frac,
                                                  file_ops)
        if _covered(content_symbols, content_frac,
                    expanded_symbols, expanded_frac):
            report["policy"] = POLICY_ASYMMETRIC
            report["n_sites"] = len(asym_symbols)
            report["spacegroup"] = meta.get("spacegroup") or "P 1"
            report["symops"] = len(file_ops)
            # NO shared-site expansion here. The stored unit is the file's
            # own, and a file that HAS a shared site already lists each
            # species as its own `_atom_site_` row — the solid solution's
            # asymmetric unit is [Nb, Ti, Ni, Co, O], five rows for four
            # species on one position. Expanding again writes Ti, Ni and Co
            # twice. This path is a verbatim round trip and needs no help.
            return cif_text(
                cell, asym_symbols, asym_frac, symops=file_ops,
                spacegroup=meta.get("spacegroup") or "P 1", name=name,
                occupancy=meta.get("asym_occupancy"),
                labels=meta.get("asym_labels"),
                disorder_groups=meta.get("asym_disorder_groups"),
                disorder_assemblies=meta.get("asym_disorder_assemblies"),
                it_number=int(meta.get("it_number") or 0), info=info,
                notes=notes, version=version)
        if chosen == POLICY_ASYMMETRIC:
            notes.append("The stored asymmetric unit no longer reproduces "
                         "these atoms, so the symmetry was re-derived.")
            report["asymmetric_stale"] = True
        chosen = None

    if chosen != POLICY_P1:
        derived = spacegroups.from_structure(cell, content_symbols,
                                             content_frac)
    else:
        derived = None
    if derived is not None and derived.xyz:
        reps = spacegroups.orbit_representatives(cell, content_symbols,
                                                 content_frac)
        if reps:
            # The file's own SETTING and spelling are kept whenever the
            # re-derived group is the same group: all nine settings of number
            # 14 share the standard symbol `P2_1/c`, so printing that for a
            # file written as `P 21/n` is a change nobody asked for.
            same = operators_match(derived.xyz, file_ops)
            spacegroup = (meta.get("spacegroup") if same and
                          meta.get("spacegroup") else derived.symbol or "P 1")
            symops = file_ops if same else list(derived.xyz)
            if not same:
                notes.append("Symmetry re-derived from the coordinates "
                             "(spglib): {} operations.".format(len(symops)))
                report["rederived"] = True
            report["policy"] = POLICY_CELL
            report["spacegroup"] = spacegroup
            report["symops"] = len(symops)
            report["n_sites"] = len(reps)
            # Occupancy DOES survive here, as long as the drawn atoms still
            # know which asymmetric-unit site they came from — which is
            # exactly what `packing.pack` records in `site_of`. Carrying it is
            # the difference between a re-exported solid solution and one that
            # silently claims full occupancy for every species on a shared
            # site. Where the mapping is absent (an edit that added atoms, a
            # non-packed import) it is REPORTED rather than guessed at.
            columns, missing = _site_columns(meta, reps, len(symbols))
            if missing:
                notes.append("Partial occupancies could not be carried for "
                             "every site; those are written as fully "
                             "occupied.")
                report["occupancy_lost"] = True
            rows = _split_shared(meta, [content_symbols[i] for i in reps],
                                 content_frac[list(reps)], columns,
                                 list(reps), report, notes)
            return cif_text(
                cell, rows["symbols"], rows["frac"], symops=symops,
                spacegroup=spacegroup, name=name,
                it_number=int(derived.number or 0) if not same
                else int(meta.get("it_number") or 0),
                info=info, notes=notes, version=version, **rows["columns"])

    if chosen != POLICY_P1:
        notes.append("No space group could be derived from the coordinates; "
                     "written as P1 with the whole cell content.")
    report["policy"] = POLICY_P1
    report["spacegroup"] = "P 1"
    report["symops"] = 1
    report["n_sites"] = len(content_symbols)
    return cif_text(cell, content_symbols, content_frac, name=name,
                    info=info, notes=notes, version=version)


def _split_shared(meta, symbols, frac, columns, indices, report, notes):
    # type: (dict, list, object, dict, list, dict, list) -> dict
    """One `_atom_site_` row per SPECIES on a shared site.

    A CIF has no way to put a composition in a single row: several species on
    one position are several rows at the same fractional coordinates, which is
    how the files that carry them are written. Without this a solid solution
    goes out as a pure compound — the site MoloM draws as a Nb/Ti/Ni/Co pie
    would be written as plain niobium.
    """
    shared = (meta or {}).get("site_occupancy") or {}
    out = {"symbols": list(symbols),
           "frac": np.asarray(frac, dtype=float).reshape(-1, 3),
           "columns": dict(columns)}
    if not shared:
        return out
    n = len(symbols)
    occ = list(columns.get("occupancy") or [1.0] * n)
    labels = list(columns.get("labels") or [""] * n)
    occ += [1.0] * max(0, n - len(occ))
    labels += [""] * max(0, n - len(labels))
    new_s, new_f, new_o, new_l = occupancy_mod.expand_shared(
        list(symbols), out["frac"], occ, labels, shared, indices)
    if len(new_s) == n:
        return out                      # nothing on these rows was shared
    out["symbols"], out["frac"] = new_s, new_f
    # The disorder columns described the OLD rows and there is no meaningful
    # value for a species that has just been split out, so they go rather
    # than being stretched to fit.
    out["columns"] = {"occupancy": new_o, "labels": new_l}
    report["shared_sites"] = len(new_s) - n + 1
    notes.append("Shared sites are written as one row per species at the "
                 "same position, which is how a CIF expresses them.")
    return out


def _site_columns(meta, indices, n_drawn):
    # type: (dict, list, int) -> Tuple[dict, bool]
    """Occupancy, labels and the disorder columns for chosen DRAWN atoms.

    `packing.pack` records `site_of` — which asymmetric-unit site each drawn
    atom came from — so a rebuilt cell can still say what its occupancies
    were. Round 42's rule applies and is why this is a lookup rather than a
    slice: everything between the file and the picture renumbers, and an index
    into the wrong list is exactly the silent wrongness that round worked on.

    Returns (kwargs for `cif_text`, whether anything had to be left out).
    """
    site_of = meta.get("site_of") or []
    columns = {}
    if not site_of or len(site_of) < n_drawn:
        # No mapping, so nothing can be claimed. Only actually a LOSS when
        # the file had partial occupancies to lose.
        return columns, any(float(o) < 1.0
                            for o in (meta.get("asym_occupancy") or ()))
    sites = [int(site_of[i]) if i < len(site_of) else -1 for i in indices]
    missing = any(s < 0 for s in sites)
    for key, source, fill in (("occupancy", "asym_occupancy", 1.0),
                              ("labels", "asym_labels", ""),
                              ("disorder_groups", "asym_disorder_groups", ""),
                              ("disorder_assemblies", "asym_disorder_assemblies",
                               "")):
        values = meta.get(source)
        if not values:
            if source == "asym_occupancy":
                missing = True
            continue
        columns[key] = [values[s] if 0 <= s < len(values) else fill
                        for s in sites]
    # Two images of one site would take the same label, and a repeated
    # `_atom_site_label` is not legal CIF — `site_labels` falls back on its
    # own when they collide, so hand it the file's names and let it decide.
    return columns, missing


def _expand(symbols, frac, symops):
    """Apply the operators to the asymmetric unit — no de-duplication, no
    disorder policy. Only ever used to ask whether the drawn atoms are still
    among the results, and for that a superset is exactly right."""
    frac = np.asarray(frac, dtype=float).reshape(-1, 3)
    out_symbols, out_frac = [], []
    for text in symops:
        try:
            op = cif_mod.SymOp.from_xyz(str(text))
        except (cif_mod.CifError, ValueError):
            continue
        out_symbols += list(symbols)
        out_frac.append(op.apply(frac))
    if not out_frac:
        return list(symbols), frac
    return out_symbols, np.vstack(out_frac)


def scene_text(objects, policy=None, version="", reports=None):
    # type: (list, Optional[str], str, Optional[list]) -> str
    """One data block per object — several structures in one file is ordinary
    CIF, and it is what a scene with two crystals in it means."""
    blocks = []
    for obj in objects:
        report = {}
        blocks.append(from_object(obj, policy=policy, version=version,
                                  report=report))
        report["name"] = getattr(obj, "name", "")
        if reports is not None:
            reports.append(report)
    return "\n\n".join(blocks)
