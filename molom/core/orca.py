"""ORCA geometry constraints and a relaxed surface scan, from a selection.

Roadmap F4: the constraint traffic used to be ONE-WAY. MoloM has been able to
read indices out of a `%geom` block since round 92 (`--select 3,7,11`) and
could not hand a selection back as one - which is the half you want when you
are looking at a structure and deciding what to freeze.

**THE FORMAT IS ORCA WORKBENCH'S, NOT ONE INVENTED HERE.**
`orca_workbench/core/geomspec.py` is already a complete `%geom` builder
covering constraints AND one relaxed surface scan, with a defined spec shape
and geometry-derived expressions. So this module produces that same spec and
that same text, and a test IMPORTS OWB's module and compares the two strings
- round 92's arrangement, and the same discipline that keeps `io.py`
diffable with OWB's `coords.py`. It is re-implemented rather than imported
because MoloM must not require OWB to be installed; the cross-check is what
stops the two drifting.

**INDICES ARE 0-BASED**, because ORCA's are and because the entire point is
to paste the numbers between the two programs. Round 92 settled this for
`--select` and it is the same decision here: renumbering would make the
feature worse than useless.

**WHICH COORDINATE A SELECTION MEANS is not decided here either.** One atom
is a Cartesian freeze, two a bond, three an angle, four a dihedral - which is
exactly what `internal.kind_for_count` already says and what the measurement
readout has always shown. Reaching for a second rule would be a second
answer to a question already settled.

Nothing here knows about Qt, and nothing writes a file: it returns a spec and
the text for it.
"""

import math

from typing import List, Optional, Sequence, Tuple   # noqa: F401

import numpy as np

from . import internal
from . import measure as measure_mod

#: MoloM's internal-coordinate kind -> ORCA's letter.
COORD_FOR_KIND = {
    internal.DISTANCE: "B",
    internal.ANGLE: "A",
    internal.DIHEDRAL: "D",
}

#: ORCA's letter -> (label, how many atoms, unit). `C` freezes one atom's
#: Cartesian position and is not a scannable one-dimensional coordinate,
#: which is why it is absent from `SCAN_TYPES`.
COORD_TYPES = {
    "B": ("Bond", 2, "A"),
    "A": ("Angle", 3, "deg"),
    "D": ("Dihedral", 4, "deg"),
    "C": ("Cartesian position", 1, ""),
}

SCAN_TYPES = ("B", "A", "D")

#: What `steps` means when nothing says otherwise. ORCA counts the number of
#: geometries in the scan, so this is 11 points from start to end inclusive.
DEFAULT_SCAN_STEPS = 10


class OrcaSpecError(ValueError):
    """The selection cannot be turned into a constraint."""


def coord_type(n_atoms):
    # type: (int) -> Optional[str]
    """The ORCA letter a selection of this size implies, or None.

    One atom is a Cartesian freeze, and the other three follow
    `internal.kind_for_count` - so the two modules cannot disagree about what
    picking three atoms means.
    """
    n = int(n_atoms)
    if n == 1:
        return "C"
    kind = internal.kind_for_count(n)
    return COORD_FOR_KIND.get(kind)


def n_atoms_for(ctype):
    # type: (str) -> int
    return COORD_TYPES.get(ctype, ("", 0, ""))[1]


def unit_for(ctype):
    # type: (str) -> str
    return COORD_TYPES.get(ctype, ("", 0, ""))[2]


def measure_value(ctype, atoms, coords):
    # type: (str, Sequence, object) -> float
    """The coordinate's present value: Angstrom for `B`, degrees for `A`/`D`.

    Measured with MoloM's own `core/measure.py` rather than a second
    implementation. The DIHEDRAL SIGN is the thing to be careful about - a
    sign convention that disagreed with ORCA's would constrain the mirror
    image, silently and plausibly - so a test compares this against OWB's
    `geomspec.measure` on random geometries.
    """
    c = np.asarray(coords, dtype=float)
    idx = [int(a) for a in atoms]
    if ctype == "B":
        return float(measure_mod.distance(c[idx[0]], c[idx[1]]))
    if ctype == "A":
        return float(measure_mod.angle(c[idx[0]], c[idx[1]], c[idx[2]]))
    if ctype == "D":
        return float(measure_mod.dihedral(c[idx[0]], c[idx[1]],
                                          c[idx[2]], c[idx[3]]))
    raise OrcaSpecError("cannot measure a {!r} coordinate".format(ctype))


def constraint(atoms, value=None, ctype=None):
    # type: (Sequence, object, Optional[str]) -> dict
    """One constraint, in ORCA Workbench's spec shape.

    `value=None` is ORCA's own "freeze where it is", which is the common case
    and is why it is the default: the number in the input file would only
    repeat what the geometry already says, and typing it in is how a
    constraint comes to disagree with the structure it was read from.
    """
    idx = [int(a) for a in atoms]
    ctype = ctype or coord_type(len(idx))
    if ctype is None:
        raise OrcaSpecError(
            "{} atoms is not a constraint - pick 1 (freeze), 2 (bond), "
            "3 (angle) or 4 (dihedral)".format(len(idx)))
    _check(ctype, idx)
    out = {"type": ctype, "atoms": idx}
    if value is not None and ctype != "C":
        out["value"] = float(value)
    return out


def scan(atoms, start, end, steps=DEFAULT_SCAN_STEPS, ctype=None):
    # type: (Sequence, float, float, int, Optional[str]) -> dict
    """One relaxed surface scan, in ORCA Workbench's spec shape."""
    idx = [int(a) for a in atoms]
    ctype = ctype or coord_type(len(idx))
    if ctype not in SCAN_TYPES:
        raise OrcaSpecError(
            "a scan needs a bond, angle or dihedral - 2, 3 or 4 atoms")
    _check(ctype, idx)
    if int(steps) < 1:
        raise OrcaSpecError("a scan needs at least one step")
    return {"type": ctype, "atoms": idx, "start": float(start),
            "end": float(end), "steps": int(steps)}


def _check(ctype, idx):
    want = n_atoms_for(ctype)
    if len(idx) != want:
        raise OrcaSpecError("{} takes {} atom(s), got {}".format(
            ctype, want, len(idx)))
    if any(a < 0 for a in idx):
        raise OrcaSpecError("atom indices are 0-based and cannot be negative")
    if len(set(idx)) != len(idx):
        raise OrcaSpecError("an internal coordinate cannot repeat an atom")


def spec(constraints=(), scan_item=None):
    # type: (Sequence, Optional[dict]) -> dict
    """OWB's spec shape: `{"constraints": [...], "scan": {...} or None}`."""
    return {"constraints": [dict(c) for c in constraints],
            "scan": dict(scan_item) if scan_item else None}


def is_empty(spec_dict):
    # type: (Optional[dict]) -> bool
    if not spec_dict:
        return True
    return not spec_dict.get("constraints") and not spec_dict.get("scan")


def _fmt(v):
    """`%g`, which is what OWB writes - 1.5 rather than 1.50000."""
    try:
        return "%g" % float(v)
    except (TypeError, ValueError):
        return str(v)


def constraint_line(c):
    # type: (dict) -> str
    """`{ B 0 1 1.5 C }`, `{ B 0 1 C }` or `{ C 5 C }`.

    The trailing `C` is ORCA's own marker for "constrained" and has nothing
    to do with the Cartesian type letter, which is why `{ C 5 C }` reads
    strangely and is nonetheless right.
    """
    ctype = c["type"]
    atoms = " ".join(str(int(a)) for a in c.get("atoms") or ())
    value = c.get("value")
    if ctype == "C" or value is None or value == "":
        return "{{ {} {} C }}".format(ctype, atoms)
    return "{{ {} {} {} C }}".format(ctype, atoms, _fmt(value))


def scan_line(s):
    # type: (dict) -> str
    """`B 0 1 = 1.5, 3.0, 10`."""
    atoms = " ".join(str(int(a)) for a in s.get("atoms") or ())
    return "{} {} = {}, {}, {}".format(
        s["type"], atoms, _fmt(s["start"]), _fmt(s["end"]), int(s["steps"]))


def geom_inner(spec_dict):
    # type: (Optional[dict]) -> str
    """The INNER text of the `%geom` block, two-space indented.

    Byte for byte what `geomspec.build_geom_inner` produces, so OWB's
    `inputs.add_geom_block` can take it unchanged - and so a test can compare
    the two directly rather than comparing two descriptions of them.
    """
    if is_empty(spec_dict):
        return ""
    lines = []
    cons = spec_dict.get("constraints") or []
    if cons:
        lines.append("  Constraints")
        for c in cons:
            lines.append("    " + constraint_line(c))
        lines.append("  end")
    s = spec_dict.get("scan")
    if s:
        lines.append("  Scan")
        lines.append("    " + scan_line(s))
        lines.append("  end")
    return "\n".join(lines)


def geom_block(spec_dict):
    # type: (Optional[dict]) -> str
    """The whole `%geom ... end`, ready to paste into an input file.

    OWB injects the inner text into an existing block; somebody pasting into
    an editor wants the wrapper too, and it is the same wrapper
    `inputs.add_geom_block` writes when there is no block to merge into.
    """
    inner = geom_inner(spec_dict)
    if not inner:
        return ""
    return "%geom\n" + inner + "\nend"


def describe(spec_dict):
    # type: (Optional[dict]) -> str
    """A short summary for a status line."""
    if is_empty(spec_dict):
        return "(none)"
    bits = []
    cons = spec_dict.get("constraints") or []
    if cons:
        bits.append("{} constraint{}".format(
            len(cons), "" if len(cons) == 1 else "s"))
    s = spec_dict.get("scan")
    if s:
        atoms = ",".join(str(int(a)) for a in s.get("atoms") or ())
        bits.append("scan {}({}) {} -> {} {} in {} steps".format(
            s.get("type"), atoms, _fmt(s.get("start")), _fmt(s.get("end")),
            unit_for(s.get("type", "")), int(s.get("steps", 0) or 0)))
    return "; ".join(bits)


# ------------------------------------------------------- the scan preview
#: How many geometries a scan of `steps` steps produces. ORCA walks from
#: start to end INCLUSIVE, so N steps is N + 1 points - the same off-by-one
#: that round 77 settled for the frame range, and for the same reason: the
#: last one is a real datum and not a repeat of the first.
def scan_points(scan_item):
    # type: (dict) -> List[float]
    """The values the scanned coordinate takes, in order."""
    steps = max(1, int(scan_item["steps"]))
    start = float(scan_item["start"])
    end = float(scan_item["end"])
    return [start + (end - start) * k / float(steps)
            for k in range(steps + 1)]


def scan_kind(scan_item):
    # type: (dict) -> str
    """The `internal` kind for a scan, for driving the geometry."""
    for kind, letter in COORD_FOR_KIND.items():
        if letter == scan_item.get("type"):
            return kind
    raise OrcaSpecError("not a scannable coordinate")


def frozen_atoms(scan_item, constraints=()):
    # type: (dict, Sequence) -> List[int]
    """Every atom a relaxation must hold still.

    The scanned coordinate's own atoms, plus anything separately constrained
    - because a preview that let the scanned bond relax back would be a
    picture of the force field's minimum rather than of the scan.
    """
    out = list(int(a) for a in scan_item.get("atoms") or ())
    for c in constraints or ():
        for a in c.get("atoms") or ():
            if int(a) not in out:
                out.append(int(a))
    return out
