"""Ligand templates: dock a molecule onto a centre by replacing placeholders.

The workflow Christian specified (2026-08-03), in two steps so the marking
survives while you build the other half:

1. Pick the coordinating atom(s) on an existing molecule and mark them —
   "Template: Set ligating atom(s)". Nothing moves; the atoms just gain a
   marker.
2. Build a centre, select the placeholder atoms on it (usually the hydrogens
   a meta atom was dressed with), and "Template: Coordinate ligand". The
   ligand is rotated and translated so its ligating atoms land where the
   placeholders were, the placeholders are deleted, and bonds are made from
   the ligating atoms to the centre.

The fit is Kabsch (`cif.rigid_from_reference`) once there are three or more
pairs. With one or two it is under-determined, so the missing freedom is
resolved explicitly rather than left to a least-squares fluke:

- **one** pair: translate the donor onto the placeholder, then rotate so the
  ligand points AWAY from the centre — the one orientation that is never
  wrong — leaving the spin about that bond for the user to adjust with R.
- **two** pairs: align the donor-donor vector to the placeholder-placeholder
  vector, then spin about it to put the ligand's bulk away from the centre.

Nothing here mutates anything: `coordinate` returns the transform and the
bonds to make, and the caller decides whether to commit.
"""

from typing import List, Optional, Sequence, Tuple

import numpy as np

from .cif import rigid_from_reference

_KEY = "ligating"


class TemplateError(ValueError):
    """Raised when a request cannot be satisfied geometrically."""


# ------------------------------------------------------------------ marking
def set_ligating(structure, indices):
    # type: (object, Sequence[int]) -> List[int]
    rows = sorted({int(i) for i in indices
                   if 0 <= int(i) < structure.n_atoms})
    if rows:
        structure.metadata[_KEY] = rows
    else:
        structure.metadata.pop(_KEY, None)
    return rows


def get_ligating(structure):
    # type: (object) -> List[int]
    rows = structure.metadata.get(_KEY) or []
    return [int(i) for i in rows if 0 <= int(i) < structure.n_atoms]


def clear_ligating(structure):
    structure.metadata.pop(_KEY, None)


# ------------------------------------------------------------- the placeholders
def common_centre(structure, placeholders):
    # type: (object, Sequence[int]) -> Optional[int]
    """The atom every placeholder hangs off, or None.

    Christian asked whether only GEMINAL placeholders should be allowed. Yes,
    and this is the check: every placeholder must share one neighbour, which
    is the atom the ligand will bond to. Without it "coordinate to what?" has
    no answer — two hydrogens on opposite ends of a molecule describe a
    bridge, which is a different (and much harder) operation.

    Deliberately NOT restricted to hydrogen: any terminal atom is a valid
    placeholder, so a Cl or a dummy can be replaced the same way.
    """
    shared = None
    for index in placeholders:
        neighbours = {int(j) for j in structure.bonded_neighbors(int(index))}
        shared = neighbours if shared is None else (shared & neighbours)
        if not shared:
            return None
    if not shared or len(shared) != 1:
        return None
    return int(next(iter(shared)))


def check_placeholders(structure, placeholders):
    # type: (object, Sequence[int]) -> int
    """Validate the placeholder set and return the centre they hang off."""
    rows = [int(i) for i in placeholders]
    if not rows:
        raise TemplateError("select the placeholder atom(s) to replace")
    for index in rows:
        if len(structure.bonded_neighbors(index)) != 1:
            raise TemplateError(
                "placeholder {} is not terminal — it has {} bonds".format(
                    index, len(structure.bonded_neighbors(index))))
    centre = common_centre(structure, rows)
    if centre is None:
        raise TemplateError(
            "the placeholders must all hang off ONE atom (geminal); "
            "bridging two centres is a different operation")
    return centre


# ------------------------------------------------------------------ the fit
def coordinate(host_coords, placeholders, centre, ligand_coords, ligating):
    # type: (np.ndarray, Sequence[int], int, np.ndarray, Sequence[int]) -> Tuple[np.ndarray, np.ndarray]
    """Where the ligand must go. Returns (rotation, translation).

    Apply as `ligand_coords @ rotation.T + translation`.
    """
    host = np.asarray(host_coords, dtype=float).reshape(-1, 3)
    lig = np.asarray(ligand_coords, dtype=float).reshape(-1, 3)
    slots = [int(i) for i in placeholders]
    donors = [int(i) for i in ligating]
    if not donors:
        raise TemplateError(
            "no ligating atoms marked — use 'Template: Set ligating atom(s)' "
            "on the ligand first")
    if len(donors) != len(slots):
        raise TemplateError(
            "{} ligating atom(s) but {} placeholder(s) selected — they must "
            "match".format(len(donors), len(slots)))

    target = host[slots]
    source = lig[donors]
    metal = host[int(centre)]

    if len(donors) >= 3:
        fit = rigid_from_reference(source, target)
        if fit is None:
            raise TemplateError("could not fit the ligand onto those slots")
        return fit

    if len(donors) == 1:
        # Point the ligand's bulk away from the centre: the only orientation
        # that is never simply wrong. The spin about the new bond is free and
        # is left for the user to adjust with R.
        want = target[0] - metal
        rest = np.delete(np.arange(len(lig)), donors[0])
        bulk = (lig[rest].mean(axis=0) - source[0]) if len(rest) \
            else np.array([1.0, 0.0, 0.0])
        rot = _align(bulk, want)
        trans = target[0] - source[0] @ rot.T
        return rot, trans

    # Two donors: match the donor-donor vector, then spin about it so the
    # rest of the ligand points away from the centre.
    src_axis = source[1] - source[0]
    dst_axis = target[1] - target[0]
    rot = _align(src_axis, dst_axis)
    moved = lig @ rot.T
    src_mid = moved[donors].mean(axis=0)
    dst_mid = target.mean(axis=0)
    axis = dst_axis / max(float(np.linalg.norm(dst_axis)), 1e-12)
    rest = np.delete(np.arange(len(lig)), donors)
    if len(rest):
        bulk = moved[rest].mean(axis=0) - src_mid
        outward = dst_mid - metal
        spin = _spin_about(axis, bulk, outward)
        rot = spin @ rot
        moved = lig @ rot.T
        src_mid = moved[donors].mean(axis=0)
    return rot, dst_mid - src_mid


def _align(a, b):
    """Rotation taking direction `a` onto direction `b`."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if na < 1e-12 or nb < 1e-12:
        return np.eye(3)
    a, b = a / na, b / nb
    v = np.cross(a, b)
    c = float(a @ b)
    if float(np.linalg.norm(v)) < 1e-12:
        if c > 0:
            return np.eye(3)
        # Antiparallel: any perpendicular axis gives the 180 degree turn.
        perp = np.array([1.0, 0.0, 0.0])
        if abs(float(a @ perp)) > 0.9:
            perp = np.array([0.0, 1.0, 0.0])
        axis = np.cross(a, perp)
        axis /= np.linalg.norm(axis)
        return _rotation(axis, np.pi)
    axis = v / np.linalg.norm(v)
    return _rotation(axis, float(np.arccos(np.clip(c, -1.0, 1.0))))


def _spin_about(axis, current, wanted):
    """Rotation about `axis` bringing `current` as near `wanted` as it can."""
    axis = np.asarray(axis, dtype=float)
    cur = np.asarray(current, dtype=float)
    want = np.asarray(wanted, dtype=float)
    cur = cur - axis * float(axis @ cur)
    want = want - axis * float(axis @ want)
    if float(np.linalg.norm(cur)) < 1e-9 or float(np.linalg.norm(want)) < 1e-9:
        return np.eye(3)
    cur /= np.linalg.norm(cur)
    want /= np.linalg.norm(want)
    angle = float(np.arctan2(float(np.cross(cur, want) @ axis),
                             float(cur @ want)))
    return _rotation(axis, angle)


def _rotation(axis, angle):
    x, y, z = np.asarray(axis, dtype=float)
    c, s = np.cos(angle), np.sin(angle)
    k = 1.0 - c
    return np.array([
        [c + x * x * k, x * y * k - z * s, x * z * k + y * s],
        [y * x * k + z * s, c + y * y * k, y * z * k - x * s],
        [z * x * k - y * s, z * y * k + x * s, c + z * z * k],
    ])
