"""Classifying a crystallographic symmetry operation so it can be DRAWN.

`cif.SymOp` already stores each operation as a 3x3 rotation plus a
translation. Turning that into a picture only needs to answer: what kind of
element is it, where does it sit, and which way does it point? All of which
falls out of standard linear algebra on the matrix:

- `det` = +1 is a proper rotation, -1 is a rotoinversion (mirror, inversion,
  or an S_n axis);
- `trace` fixes the ORDER: for a proper rotation trace = 1 + 2cos(2pi/n);
- the eigenvector for eigenvalue +1 is the ROTATION AXIS; for det = -1 the
  eigenvector for -1 is the MIRROR NORMAL;
- the translation splits into the part ALONG the invariant direction — which
  is intrinsic, and makes the element a screw axis or a glide plane — and the
  part perpendicular to it, which merely says where the element sits and can
  be solved for a point on it.

Everything here is numpy on 3x3s, so it is exact, fast, and testable without
a viewport. The drawing (glyphs and ghosts) is the UI's problem.
"""

from typing import List, Optional

import numpy as np

IDENTITY = "identity"
ROTATION = "rotation"
SCREW = "screw"
MIRROR = "mirror"
GLIDE = "glide"
INVERSION = "inversion"
ROTOINVERSION = "rotoinversion"
TRANSLATION = "translation"


class Element(object):
    """A symmetry ELEMENT: what to draw, where, and pointing where."""

    def __init__(self, kind, order=1, point=None, direction=None,
                 intrinsic=None, text=""):
        self.kind = kind
        self.order = int(order)
        # A point the element passes through, in FRACTIONAL coordinates.
        self.point = (np.zeros(3) if point is None
                      else np.asarray(point, dtype=float))
        # Axis direction (rotation/screw) or plane NORMAL (mirror/glide).
        self.direction = (None if direction is None
                          else np.asarray(direction, dtype=float))
        # The translation that cannot be removed: screw pitch / glide vector.
        self.intrinsic = (np.zeros(3) if intrinsic is None
                          else np.asarray(intrinsic, dtype=float))
        self.text = text

    @property
    def is_plane(self):
        return self.kind in (MIRROR, GLIDE)

    @property
    def is_axis(self):
        return self.kind in (ROTATION, SCREW, ROTOINVERSION)

    def __repr__(self):
        return "Element({}, order={}, {!r})".format(self.kind, self.order,
                                                    self.text)


def _order_from_trace(trace, proper):
    """n for a rotation of 2pi/n. trace = 1 + 2cos(theta) when proper."""
    value = trace if proper else -trace
    cos_theta = np.clip((value - 1.0) / 2.0, -1.0, 1.0)
    theta = float(np.arccos(cos_theta))
    if theta < 1e-6:
        return 1
    n = 2.0 * np.pi / theta
    for candidate in (2, 3, 4, 6):
        if abs(n - candidate) < 0.05:
            return candidate
    return max(int(round(n)), 1)


def _invariant_direction(rot, eigenvalue):
    """Unit eigenvector of `rot` for `eigenvalue`, or None."""
    vals, vecs = np.linalg.eig(rot)
    best, best_err = None, 1e-3
    for k in range(3):
        err = abs(complex(vals[k]) - eigenvalue)
        if err < best_err:
            best_err = err
            best = np.real(vecs[:, k])
    if best is None:
        return None
    norm = float(np.linalg.norm(best))
    return best / norm if norm > 1e-9 else None


def _fixed_point(rot, trans, direction, along):
    """A point the element passes through.

    Solve (I - R) p = t_perp in the subspace perpendicular to the invariant
    direction; `lstsq` handles the singular directions for us.
    """
    perp = np.asarray(trans, dtype=float) - along
    try:
        point, _res, _rank, _sv = np.linalg.lstsq(np.eye(3) - rot, perp,
                                                  rcond=None)
    except np.linalg.LinAlgError:
        return np.zeros(3)
    if direction is not None:
        # Slide the point onto the "first" cell for a tidier picture.
        point = point - direction * float(direction @ point)
    return np.where(np.isfinite(point), point, 0.0)


def classify(op):
    # type: (object) -> Element
    """Turn a `cif.SymOp` into the ELEMENT it represents."""
    rot = np.asarray(op.rotation, dtype=float).reshape(3, 3)
    trans = np.asarray(op.translation, dtype=float).reshape(3)
    text = getattr(op, "text", "") or ""
    det = float(np.linalg.det(rot))
    trace = float(np.trace(rot))
    proper = det > 0.0

    if proper and abs(trace - 3.0) < 1e-6:          # R = I
        if np.allclose(trans, 0.0, atol=1e-6):
            return Element(IDENTITY, 1, text=text)
        return Element(TRANSLATION, 1, intrinsic=trans, text=text)

    if not proper and abs(trace + 3.0) < 1e-6:      # R = -I
        return Element(INVERSION, 1, point=trans / 2.0, text=text)

    if proper:
        order = _order_from_trace(trace, True)
        axis = _invariant_direction(rot, 1.0)
        if axis is None:
            return Element(ROTATION, order, text=text)
        along = axis * float(axis @ trans)
        point = _fixed_point(rot, trans, axis, along)
        kind = SCREW if float(np.linalg.norm(along)) > 1e-6 else ROTATION
        return Element(kind, order, point=point, direction=axis,
                       intrinsic=along, text=text)

    # Improper. trace == 1 is a mirror (S_2); anything else is a rotoinversion.
    if abs(trace - 1.0) < 1e-6:
        normal = _invariant_direction(rot, -1.0)
        if normal is None:
            return Element(MIRROR, 2, text=text)
        along = trans - normal * float(normal @ trans)   # IN-plane part
        point = _fixed_point(rot, trans, None, along)
        kind = GLIDE if float(np.linalg.norm(along)) > 1e-6 else MIRROR
        return Element(kind, 2, point=point, direction=normal,
                       intrinsic=along, text=text)

    order = _order_from_trace(trace, False)
    axis = _invariant_direction(rot, -1.0)
    point = _fixed_point(rot, trans, None, np.zeros(3))
    return Element(ROTOINVERSION, order, point=point, direction=axis,
                   text=text)


def world_direction(element, cell_matrix):
    # type: (Element, np.ndarray) -> Optional[np.ndarray]
    """The element's direction in CARTESIAN space, as a unit vector.

    An AXIS is a direction along the lattice and transforms with the cell
    matrix. A PLANE NORMAL does NOT: normals are covariant and transform with
    the inverse transpose (the reciprocal basis). Using the direct matrix for
    both is only right for a cubic cell — in a monoclinic one an off-axis
    mirror comes out up to 60 degrees wrong, which is exactly the kind of
    error that looks plausible on screen.
    """
    if element.direction is None:
        return None
    matrix = np.asarray(cell_matrix, dtype=float).reshape(3, 3)
    if element.is_plane:
        try:
            basis = np.linalg.inv(matrix).T
        except np.linalg.LinAlgError:
            return None
    else:
        basis = matrix
    out = np.asarray(element.direction, dtype=float) @ basis
    norm = float(np.linalg.norm(out))
    return out / norm if norm > 1e-12 else None


def filter_ops(ops, kinds=None):
    # type: (list, Optional[object]) -> List
    """The operations whose ELEMENT kind is enabled.

    Both the glyphs and the ghosts are built from the result, so what you see
    drawn and which copies appear can never disagree: switching off "glide"
    removes the glide planes AND the copies the glides produce.

    NOT de-duplicated, unlike `classify_all` — two distinct screw axes are
    one glyph each but two different images of the asymmetric unit.
    """
    if kinds is None:
        return list(ops)
    wanted = set(kinds)
    out = []
    for op in ops:
        element = classify(op)
        # The identity is what maps the asymmetric unit to itself; it is not
        # an "element" the user can switch off, and dropping it here would
        # only matter to callers that keep it.
        if element.kind in (IDENTITY, TRANSLATION) or element.kind in wanted:
            out.append(op)
    return out


def classify_all(ops, skip_identity=True):
    # type: (list, bool) -> List[Element]
    """Classify a whole operation list, dropping duplicates.

    A space group lists every coset representative, so the same physical
    element turns up many times (192 operations for Fm-3m over a handful of
    distinct axes and planes). Drawing each one would be a hairball.
    """
    out = []
    seen = set()
    for op in ops:
        element = classify(op)
        if skip_identity and element.kind in (IDENTITY, TRANSLATION):
            continue
        key = (element.kind, element.order,
               _round_key(element.direction), _round_key(element.point),
               _round_key(element.intrinsic))
        if key in seen:
            continue
        seen.add(key)
        out.append(element)
    return out


def _round_key(vec, places=3):
    if vec is None:
        return None
    arr = np.round(np.asarray(vec, dtype=float), places) + 0.0
    # A direction and its negative describe the same axis/plane.
    for value in arr:
        if value > 1e-9:
            break
        if value < -1e-9:
            arr = -arr
            break
    return tuple(arr.tolist())


def images_of(points, ops, keep_identity=False, lattice=True, tol=1e-4,
              normalize=None):
    # type: (np.ndarray, list, bool, bool, float, Optional[object]) -> List[np.ndarray]
    """Every DISTINCT symmetry image of a fractional point set — the "ghosts".

    Showing where each copy of the asymmetric unit LANDS is often clearer
    than the formal glyphs: you see the pattern being built rather than the
    machinery that builds it.

    Three things this has to get right, and each of them is a real bug that
    was reported from a screenshot:

    * **Distinct images, not one per operator.** A 48-operator group maps a
      site on a special position onto itself over and over; drawing one ghost
      per operator stacks 47 identical skeletons on the original.
    * **Lattice images.** In Pm-3m every operator maps Na(0,0,0)+Cl(1/2,1/2,1/2)
      onto itself exactly, so after de-duplication there is nothing left and
      the display goes blank — "ghost atoms don't work for NaCl at all".
      The copies that actually exist there are the ones a lattice
      translation away, so a point set touching the cell boundary also gets
      its neighbouring-cell images. That is the same completion the drawn
      unit cell does, and it is what makes the eight corner sodiums appear.
    * **WHOLE MOLECULES.** The default `normalize` puts every atom into
      [0, 1) on its own, which shreds any image straddling a cell face: half
      the molecule reappears on the far side, and since the ghost's bonds come
      from a minimum-image adjacency the skeleton is then drawn with lines
      stretching clear across the box, pointing the wrong way — Christian's
      "the ghost atoms are glitched" report, and exactly the same mistake the
      round-19 unit cell made with real atoms. Pass
      `normalize=lambda f: cif.unwrap_molecules(symbols, f, cell)` to wrap by
      MOLECULE instead. It stays a parameter rather than a hard import because
      `symmetry` knows nothing about elements or covalent radii, and the
      caller already has both.
    """
    base = np.asarray(points, dtype=float).reshape(-1, 3)
    wrap = normalize if normalize is not None else \
        (lambda f: np.asarray(f, dtype=float) - np.floor(f))
    wrapped = np.asarray(wrap(base), dtype=float)
    seen = [wrapped] if not keep_identity else []
    out = []

    def add(candidate):
        for other in seen:
            if other.shape == candidate.shape and \
                    np.allclose(other, candidate, atol=tol):
                return
        seen.append(candidate)
        out.append(candidate)

    for op in ops:
        add(np.asarray(wrap(op.apply(base)), dtype=float))
    if lattice:
        # Which axes the SET as a whole sits against; only those give a
        # neighbouring cell that still touches this one.
        for image in [wrapped] + list(out):
            options = []
            for axis in range(3):
                shifts = [0.0]
                column = image[:, axis]
                if np.any(np.abs(column) <= tol):
                    shifts.append(1.0)
                if np.any(np.abs(column - 1.0) <= tol):
                    shifts.append(-1.0)
                options.append(shifts)
            for da in options[0]:
                for db in options[1]:
                    for dc in options[2]:
                        if da == 0.0 and db == 0.0 and dc == 0.0:
                            continue
                        add(image + np.array([da, db, dc]))
    return out
