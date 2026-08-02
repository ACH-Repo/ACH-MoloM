"""Meta atoms: a coordination centre that HOLDS ITS SHAPE during optimisation.

The problem this solves (Christian's, since round 9): MMFF and UFF have no
usable parameters for most transition metals, so pre-optimising a metal-organic
complex either refuses to run or collapses the coordination sphere. A meta atom
sidesteps that. You place a dummy centre, tell it "trigonal bipyramidal, r = 2",
and the optimiser is not asked to understand the metal at all — the centre and
its donors are held rigid while the organic ligands relax around them. On
export the dummy becomes the element you actually meant.

Three pieces of state, all on the atom:
- `geometry`  one of core.coordination's templates,
- `distance`  the centre-donor distance to hold, in Angstrom,
- `element`   what this becomes when the geometry is written to a file.

Stored in `Structure.metadata["meta_atoms"]` keyed by atom index as a STRING,
because that metadata is JSON (savepoints) and JSON keys are strings. Indices
shift when atoms are deleted, so `remap`/`prune` keep the table honest.
"""

from typing import Dict, List, Optional

import numpy as np

from . import coordination, elements

META_SYMBOL = "Xx"          # the dummy element a meta atom is drawn as
_KEY = "meta_atoms"


class MetaAtom(object):
    """A coordination constraint sitting on one atom."""

    def __init__(self, geometry="octahedral", distance=2.0, element="",
                 locked=True):
        # type: (str, float, str, bool) -> None
        if geometry not in coordination.GEOMETRY_DIRECTIONS:
            raise ValueError("unknown geometry: {!r}".format(geometry))
        self.geometry = geometry
        self.distance = float(distance)
        # What the dummy becomes on export. Empty = leave it as the dummy.
        self.element = elements.symbol_from_text(element) if element else ""
        self.locked = bool(locked)

    def __repr__(self):
        return "MetaAtom({!r}, r={:.2f}, -> {!r})".format(
            self.geometry, self.distance, self.element or META_SYMBOL)

    @property
    def n_donors(self):
        return len(coordination.GEOMETRY_DIRECTIONS[self.geometry])

    def spec(self):
        # type: () -> coordination.CoordinationSpec
        return coordination.CoordinationSpec(self.geometry, self.distance,
                                             self.locked)

    def to_dict(self):
        return {"geometry": self.geometry, "distance": self.distance,
                "element": self.element, "locked": self.locked}

    @classmethod
    def from_dict(cls, d):
        # type: (dict) -> MetaAtom
        return cls(d.get("geometry", "octahedral"), d.get("distance", 2.0),
                   d.get("element", ""), d.get("locked", True))


# ------------------------------------------------------------------- storage
def all_meta(structure):
    # type: (object) -> Dict[int, MetaAtom]
    out = {}
    for key, value in (structure.metadata.get(_KEY) or {}).items():
        try:
            out[int(key)] = MetaAtom.from_dict(value)
        except (TypeError, ValueError):
            continue
    return out


def get_meta(structure, index):
    # type: (object, int) -> Optional[MetaAtom]
    raw = (structure.metadata.get(_KEY) or {}).get(str(int(index)))
    if raw is None:
        return None
    try:
        return MetaAtom.from_dict(raw)
    except (TypeError, ValueError):
        return None


def set_meta(structure, index, meta, retype=True):
    # type: (object, int, MetaAtom, bool) -> None
    """Attach a constraint to an atom. `retype` also turns it into the dummy
    element, which is the visible signal that it is no longer ordinary."""
    table = structure.metadata.setdefault(_KEY, {})
    table[str(int(index))] = meta.to_dict()
    if retype and 0 <= int(index) < structure.n_atoms:
        structure.symbols[int(index)] = META_SYMBOL


def clear_meta(structure, index):
    # type: (object, int) -> None
    table = structure.metadata.get(_KEY)
    if table:
        table.pop(str(int(index)), None)
        if not table:
            structure.metadata.pop(_KEY, None)


def remap(structure, old_to_new):
    # type: (object, Dict[int, Optional[int]]) -> None
    """Rewrite the index keys after atoms moved or were deleted."""
    table = structure.metadata.get(_KEY)
    if not table:
        return
    fresh = {}
    for key, value in table.items():
        new = old_to_new.get(int(key), None)
        if new is not None:
            fresh[str(int(new))] = value
    if fresh:
        structure.metadata[_KEY] = fresh
    else:
        structure.metadata.pop(_KEY, None)


def prune(structure):
    # type: (object) -> None
    """Drop entries pointing past the end of the atom list."""
    table = structure.metadata.get(_KEY)
    if not table:
        return
    fresh = {k: v for k, v in table.items() if 0 <= int(k) < structure.n_atoms}
    if fresh:
        structure.metadata[_KEY] = fresh
    else:
        structure.metadata.pop(_KEY, None)


# --------------------------------------------------------------- optimisation
def frozen_atoms(structure):
    # type: (object) -> List[int]
    """Atoms the force field must NOT move: every locked meta centre and the
    donors bonded to it.

    Freezing the whole first coordination sphere is what "keeps that shape":
    the centre-donor distances and the donor-centre-donor angles are then
    fixed by construction, and the force field — which has no parameters for
    the metal anyway — is only asked about the organic part it does know.
    """
    out = set()
    for index, meta in all_meta(structure).items():
        if not meta.locked or index >= structure.n_atoms:
            continue
        out.add(index)
        out.update(int(j) for j in structure.bonded_neighbors(index))
    return sorted(out)


def dress_with_hydrogens(structure, index, meta=None, symbol="H"):
    # type: (object, int, Optional[MetaAtom], str) -> int
    """Fill a meta centre's EMPTY donor slots with placeholder atoms.

    A bare dummy shows nothing about the geometry it is supposed to enforce,
    so the obvious thing to do with it — free-draw ligands onto it — produces
    a coordination number the spec was never meant for. Dressing it on
    creation makes the shape visible and gives something to build FROM: swap
    a placeholder for the real donor rather than guessing where it goes.

    Returns how many were added.
    """
    from . import edits
    meta = meta or get_meta(structure, index)
    if meta is None or index >= structure.n_atoms:
        return 0
    centre = np.asarray(structure.coords[index], dtype=float)
    existing = [int(j) for j in structure.bonded_neighbors(index)]
    n_free = meta.n_donors - len(existing)
    if n_free <= 0:
        return 0
    vectors = np.array([structure.coords[j] - centre for j in existing]) \
        if existing else np.zeros((0, 3))
    dirs = coordination.free_directions(vectors, meta.geometry, n_free)
    added = 0
    for d in np.asarray(dirs).reshape(-1, 3)[:n_free]:
        edits.add_atom(structure, symbol, centre + d * meta.distance,
                       bond_to=index)
        added += 1
    return added


def idealize(structure, index, meta=None):
    # type: (object, int, Optional[MetaAtom]) -> int
    """Move the donors bonded to a meta centre onto its ideal directions.

    Returns how many donors were moved. Existing bond directions are fitted
    to the template first (`coordination.fit_directions`), so a complex that
    is already roughly right only gets tidied rather than scrambled.
    """
    meta = meta or get_meta(structure, index)
    if meta is None or index >= structure.n_atoms:
        return 0
    donors = [int(j) for j in structure.bonded_neighbors(index)]
    if not donors:
        return 0
    centre = np.asarray(structure.coords[index], dtype=float)
    existing = np.array([structure.coords[j] - centre for j in donors])
    dirs = coordination.fit_directions(existing, meta.geometry)
    moved = 0
    for slot, donor in enumerate(donors):
        if slot >= len(dirs):
            break
        target = centre + dirs[slot] * meta.distance
        for frame in structure.frames:
            frame[donor] = target
        moved += 1
    return moved


# --------------------------------------------------------------------- export
def resolved_symbols(structure):
    # type: (object) -> List[str]
    """The symbol list as it should be WRITTEN: every meta atom swapped for
    the element it stands in for. Meta atoms with no element set stay as the
    dummy, which is honest — nothing silently becomes carbon."""
    symbols = list(structure.symbols)
    for index, meta in all_meta(structure).items():
        if meta.element and 0 <= index < len(symbols):
            symbols[index] = meta.element
    return symbols


def unresolved(structure):
    # type: (object) -> List[int]
    """Meta atoms that would be exported as dummies (no element chosen)."""
    return sorted(i for i, m in all_meta(structure).items()
                  if not m.element and 0 <= i < structure.n_atoms)
