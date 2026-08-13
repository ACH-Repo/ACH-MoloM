"""Define or correct a unit cell on a structure.

Everything in `core/cif.py` CONSUMES a cell that arrived in a file. Nothing
could ever create one, or fix one that was wrong: the crystal page rendered
a, b, c, alpha, beta, gamma as read-only text, so a molecule with no cell could
never be given a box and an imported cell could never be corrected. This is
that missing half.

UI-free and GL-free, so every rule below is testable with no display.

THE DECISION THAT MATTERS is what happens to the atoms when the cell changes,
and there is no single right answer - which is why it is a parameter and not a
default buried in the code:

  * KEEP FRACTIONAL - the atoms stay at the same fractional positions and move
    in Cartesian space with the box, so the structure stretches and shears with
    it. This is what a cell edit MEANS crystallographically: fractional
    coordinates are the structure, and a, b, c are the frame they live in.
  * KEEP CARTESIAN - the atoms stay exactly where they are and only the drawn
    box changes. This is what you want when putting a box around a molecule
    that never had one, where there are no fractional coordinates to preserve.
"""

import math
from typing import Optional

import numpy as np

from .cif import Cell

#: Angles outside this are not a cell anybody means; it also keeps the
#: positive-definiteness test away from its own singularities.
MIN_ANGLE = 1.0
MAX_ANGLE = 179.0
MIN_LENGTH = 1e-3


class CellError(ValueError):
    """A cell that cannot exist, with a reason worth showing the user."""


def validate(a, b, c, alpha, beta, gamma):
    # type: (float, float, float, float, float, float) -> None
    """Raise `CellError` unless these six numbers describe a real cell.

    Lengths must be positive, which is obvious. The angles are the part that
    catches people out: they are NOT independently choosable. Three angles only
    close into a parallelepiped if

        1 - cos^2(a) - cos^2(b) - cos^2(g) + 2 cos(a) cos(b) cos(g)  >  0

    which is the squared volume factor, i.e. the condition for the metric
    tensor to be positive definite. Something like 30/30/120 passes every
    per-angle range check and still describes no solid at all - the faces
    cannot meet. Catching it here means `Cell.matrix()` never has to deal with
    a degenerate frame, and the user gets told which way they are wrong.
    """
    for name, value in (("a", a), ("b", b), ("c", c)):
        if not np.isfinite(value) or float(value) <= MIN_LENGTH:
            raise CellError("{} must be a positive length".format(name))
    for name, value in (("alpha", alpha), ("beta", beta), ("gamma", gamma)):
        if not np.isfinite(value) or not (MIN_ANGLE <= float(value)
                                          <= MAX_ANGLE):
            raise CellError("{} must be between {:g} and {:g} degrees".format(
                name, MIN_ANGLE, MAX_ANGLE))
    ca = math.cos(math.radians(float(alpha)))
    cb = math.cos(math.radians(float(beta)))
    cg = math.cos(math.radians(float(gamma)))
    factor = 1.0 - ca * ca - cb * cb - cg * cg + 2.0 * ca * cb * cg
    if factor <= 1e-12:
        raise CellError(
            "alpha, beta and gamma do not close into a cell (they would give "
            "zero or imaginary volume). Angles are not independent: each must "
            "be less than the sum of the other two, and their sum under 360.")


def make_cell(a, b, c, alpha=90.0, beta=90.0, gamma=90.0):
    # type: (float, float, float, float, float, float) -> Cell
    """A validated `Cell`."""
    validate(a, b, c, alpha, beta, gamma)
    return Cell(float(a), float(b), float(c),
                float(alpha), float(beta), float(gamma))


def cell_of(structure):
    # type: (object) -> object
    """The structure's cell, or None."""
    stored = (structure.metadata or {}).get("cell")
    if stored is None:
        return None
    return stored if isinstance(stored, Cell) else Cell.from_dict(stored)


def suggest_cell(structure, padding=2.0):
    # type: (object, float) -> Cell
    """A sensible starting box for a molecule that has none: its bounding box
    plus a margin, orthogonal.

    Offered rather than imposed - the point is that "define a cell" should not
    open on 1x1x1 and make the user type six numbers before seeing anything.
    """
    coords = np.asarray(structure.coords, dtype=float).reshape(-1, 3)
    if len(coords) == 0:
        return Cell(10.0, 10.0, 10.0)
    span = coords.max(axis=0) - coords.min(axis=0)
    span = np.maximum(span + 2.0 * float(padding), 1.0)
    return Cell(float(span[0]), float(span[1]), float(span[2]))


def apply_cell(structure, cell, keep_fractional=None, symops=None,
               spacegroup=None):
    # type: (object, object, bool, list, str) -> dict
    """Put `cell` on `structure`. Returns a report of what was done.

    `keep_fractional` decides what happens to the atoms (see the module
    docstring). `None` means "decide sensibly": keep the fractional
    coordinates if there WAS a cell to have them in, and the Cartesian ones if
    there was not - because in that case there are no fractional coordinates to
    preserve, only a box being drawn around what is already there.
    """
    validate(cell.a, cell.b, cell.c, cell.alpha, cell.beta, cell.gamma)
    old = cell_of(structure)
    if keep_fractional is None:
        keep_fractional = old is not None
    report = {"had_cell": old is not None,
              "kept": "fractional" if keep_fractional else "cartesian",
              "moved": 0}

    if keep_fractional and old is not None:
        # The atoms are re-expressed in the NEW frame at the same fractional
        # positions, which is what makes this "the same structure in a
        # corrected cell" rather than "a different structure".
        before = np.asarray(structure.coords, dtype=float).reshape(-1, 3)
        frac = old.to_fractional(before)
        after = frac @ cell.matrix()
        for k in range(structure.n_frames):
            f = old.to_fractional(np.asarray(structure.frames[k], dtype=float))
            structure.frames[k] = f @ cell.matrix()
        report["moved"] = int(np.count_nonzero(
            np.linalg.norm(after - before, axis=1) > 1e-9))

    meta = structure.metadata
    meta["cell"] = cell.to_dict()
    if symops is not None:
        meta["symops"] = list(symops)
        report["symops"] = len(symops)
    elif "symops" not in meta:
        # A cell with no symmetry is P1, and saying so explicitly is better
        # than leaving a reader to guess: P1 is true of every arrangement of
        # atoms, so it is the only honest default (round 52's reasoning).
        meta["symops"] = ["x,y,z"]
        report["symops"] = 1
    if spacegroup:
        meta["spacegroup"] = str(spacegroup)
    elif "spacegroup" not in meta:
        meta["spacegroup"] = "P 1"
    report["spacegroup"] = meta.get("spacegroup")
    return report


def fractional_of(structure, index, cell=None):
    # type: (object, int, object) -> Optional[np.ndarray]
    """The fractional coordinates of one atom, or None with no cell.

    This is how a crystallographer reads a position - "a quarter along a" is a
    statement about the structure, where 3.47 A is a statement about this
    particular cell. Reading them back out is half of being able to type them.
    """
    cell = cell or cell_of(structure)
    if cell is None or index < 0 or index >= structure.n_atoms:
        return None
    cart = np.asarray(structure.coords[int(index)], dtype=float)
    return cell.to_fractional(cart.reshape(1, 3))[0]


def set_fractional(structure, index, frac, cell=None, wrap=False):
    # type: (object, int, object, object, bool) -> bool
    """Move one atom to a fractional position, in EVERY frame.

    `wrap` brings the result into [0, 1) first, which is what you want when
    typing a site into a cell and emphatically not what you want when nudging
    an atom that legitimately sits outside one (a boundary copy, an unwrapped
    molecule), so it is off by default and offered as a tick.

    Returns False when there is no cell to be fractional in - a fractional
    coordinate is meaningless without the frame it is a fraction OF.
    """
    cell = cell or cell_of(structure)
    if cell is None or index < 0 or index >= structure.n_atoms:
        return False
    values = np.asarray(frac, dtype=float).reshape(3)
    if not np.all(np.isfinite(values)):
        raise CellError("fractional coordinates must be numbers")
    if wrap:
        values = values - np.floor(values)
    cart = (values.reshape(1, 3) @ cell.matrix())[0]
    for k in range(structure.n_frames):
        structure.frames[k][int(index)] = cart
    return True


def clear_cell(structure):
    # type: (object) -> bool
    """Take the cell off a structure, leaving the atoms exactly where they are.

    The crystallography goes with it - operators, the stored asymmetric unit,
    the derived columns - because keeping a space group for a cell that no
    longer exists is how a rebuild later invents a structure from nothing.
    """
    meta = structure.metadata or {}
    if "cell" not in meta:
        return False
    for key in ("cell", "symops", "spacegroup", "asym_symbols", "asym_frac",
                "asym_labels", "cell_content", "site_occupancy", "site_of",
                "cell_frozen", "asym_disorder_groups",
                "asym_disorder_assemblies"):
        meta.pop(key, None)
    return True
