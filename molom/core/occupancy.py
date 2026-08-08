"""Shared crystallographic sites: reading them, editing them, writing them.

A *shared site* is one Gitterplatz occupied by several species — a
substitutional solid solution. `1547149.cif` puts **Nb 0.50, Ti 0.25, Ni 0.15
and Co 0.10 on one position** and names itself after the mixture. MoloM draws
it as VESTA does, one pie sphere per site (round 42).

Two things this module exists for.

**It can be EDITED.** Round 42 could only ever report what the file said, and
round 45e recorded why that is a real limit: `expand`'s minimum-image merge
discards the co-located species *before* occupancy is ever consulted, so the
information is only in the composition table and is lost outright the moment
the cell has to be rebuilt. There is no coordinate that implies it and no
derivation that can recover it — so the honest answer is to let the user say
what the site is. Christian's suggestion, and the right one.

**It can be WRITTEN.** A shared site is not one `_atom_site_` row with a funny
occupancy; it is one row PER SPECIES at the same fractional coordinates, which
is exactly how the files that carry them are written. `expand_shared` does
that split for the writer.

The composition rides in `Structure.metadata["site_occupancy"]` — `{drawn atom
index as a STRING: [(element, occupancy), ...]}` — so it round-trips through
undo snapshots and `.molom` savepoints for free, the same bargain every other
per-object display state takes.

UI-free.
"""

from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from . import elements

#: Below this a wedge is not worth drawing and is almost certainly a typo.
MIN_OCCUPANCY = 1e-4


def composition_of(meta, index):
    # type: (dict, int) -> List[Tuple[str, float]]
    """`[(element, occupancy), ...]` for one drawn atom, or []."""
    table = (meta or {}).get("site_occupancy") or {}
    entry = table.get(str(int(index)))
    if not entry:
        return []
    return [(str(sym), float(occ)) for sym, occ in entry]


def orbit_of(meta, index, n_atoms):
    # type: (dict, int, int) -> List[int]
    """Every drawn atom belonging to the same crystallographic SITE.

    A cubic cell draws one site eight, twenty-four or ninety-six times, and
    editing its composition one image at a time is not a thing anyone would
    do. `packing.pack` records `site_of` — which asymmetric-unit site each
    drawn atom came from — so the orbit is a lookup rather than a search.

    Falls back to the atom alone when there is no mapping (a structure that
    was not packed, or one edited since), which is the honest answer: without
    it there is nothing to say the other atoms are the same site rather than
    merely the same element.
    """
    index = int(index)
    site_of = (meta or {}).get("site_of") or []
    if not site_of or index >= len(site_of):
        return [index]
    site = int(site_of[index])
    if site < 0:
        return [index]
    return [i for i in range(min(n_atoms, len(site_of)))
            if int(site_of[i]) == site]


def normalise(parts, drop_zero=True):
    # type: (Sequence, bool) -> List[Tuple[str, float]]
    """Clean a user-entered composition: real element symbols, real numbers.

    Occupancies are NOT rescaled to sum to one. A site can be genuinely
    part-vacant, and silently normalising would erase that — the total is the
    user's business, and `total_note` says what it currently is.
    """
    out = []
    for sym, occ in parts:
        z = elements.atomic_number(str(sym))
        if not z:
            continue
        value = float(occ)
        if drop_zero and value <= MIN_OCCUPANCY:
            continue
        out.append((elements.symbol(z), max(0.0, value)))
    return out


def total(parts):
    # type: (Sequence) -> float
    return float(sum(float(o) for _s, o in parts))


def total_note(parts):
    # type: (Sequence) -> str
    """A sentence about the total, or "" when there is nothing to say.

    Over one is an error — more than a whole atom on one position. Under one
    is a legitimate partly-vacant site, so it is described rather than warned
    about.
    """
    if not parts:
        return ""
    t = total(parts)
    if t > 1.0 + 1e-6:
        return ("Total {:.3f} — more than one atom's worth on a single "
                "position.".format(t))
    if t < 1.0 - 1e-6:
        return "Total {:.3f} — the site is {:.1f}% vacant.".format(
            t, 100.0 * (1.0 - t))
    return "Total 1.000 — the site is fully occupied."


def is_shared(parts):
    # type: (Sequence) -> bool
    """More than one species: the case that needs a pie sphere and several
    `_atom_site_` rows. One species at a partial occupancy is an ordinary
    partial site and rides in the occupancy column."""
    return len({str(s) for s, _o in parts}) > 1


def set_composition(meta, indices, parts, n_atoms=None):
    # type: (dict, Sequence[int], Sequence, Optional[int]) -> int
    """Write one composition onto every given atom. Returns how many.

    A single species at full occupancy CLEARS the entry rather than storing
    it: an atom the user has put back to ordinary should stop being a pie
    sphere, and a table full of `[("C", 1.0)]` is noise that every consumer
    then has to filter.
    """
    parts = normalise(parts)
    table = dict((meta or {}).get("site_occupancy") or {})
    plain = (len(parts) == 1 and abs(parts[0][1] - 1.0) < 1e-6) or not parts
    for i in indices:
        key = str(int(i))
        if plain:
            table.pop(key, None)
        else:
            table[key] = [(str(s), float(o)) for s, o in parts]
    if table:
        meta["site_occupancy"] = table
    else:
        meta.pop("site_occupancy", None)
    return len(list(indices))


def dominant(parts):
    # type: (Sequence) -> str
    """Which element the site is DRAWN as when it is not drawn as a pie."""
    if not parts:
        return ""
    return max(parts, key=lambda p: float(p[1]))[0]


def expand_shared(symbols, frac, occupancy, labels, shared, indices=None):
    # type: (list, object, list, list, dict, Optional[list]) -> tuple
    """Split shared sites into one row PER SPECIES, for the CIF writer.

    A CIF says "Nb and Ti share this position" by listing both at the same
    fractional coordinates with occupancies that sum to one — not by putting
    a composition in a single row, which the format has no way to express.
    So a site MoloM draws as one pie sphere has to become several rows on the
    way out, or the file claims a pure compound.

    `shared` is keyed by DRAWN index; `indices` says which drawn atom each row
    of `symbols` came from (the writer's rows are a subset — one per orbit).
    """
    frac = np.asarray(frac, dtype=float).reshape(-1, 3)
    if indices is None:
        indices = list(range(len(symbols)))
    out_s, out_f, out_o, out_l = [], [], [], []
    for row, drawn in enumerate(indices):
        parts = composition_of({"site_occupancy": shared}, drawn) \
            if shared else []
        if not is_shared(parts):
            out_s.append(symbols[row])
            out_f.append(frac[row])
            out_o.append(occupancy[row] if row < len(occupancy) else 1.0)
            out_l.append(labels[row] if row < len(labels) else "")
            continue
        base = labels[row] if row < len(labels) else ""
        for n, (sym, occ) in enumerate(parts):
            out_s.append(sym)
            out_f.append(frac[row])
            out_o.append(float(occ))
            # Distinct labels, because a repeated `_atom_site_label` is not
            # legal CIF and two species on one position are two rows.
            out_l.append("{}_{}".format(base, sym) if base else "")
    return out_s, np.asarray(out_f, dtype=float).reshape(-1, 3), out_o, out_l


def describe(parts):
    # type: (Sequence) -> str
    """`Nb 0.50 / Ti 0.25` — the one-line form for a menu or a status bar."""
    return " / ".join("{} {:.2f}".format(s, float(o)) for s, o in parts)
