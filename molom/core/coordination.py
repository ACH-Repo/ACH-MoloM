"""Coordination-geometry templates: ideal donor directions around a centre.

Two jobs, one small table:

1. NOW — placing hydrogens and drawn atoms. Fitting the template to the bonds
   an atom already has and taking a leftover direction beats "opposite the
   mean neighbour", which collapses for symmetric environments.
2. LATER — the "meta atom" idea (guided pre-optimisation of metal-organic
   complexes): a centre annotated with a target geometry + donor distance
   gives a force field explicit restraints instead of needing metal
   parameters it does not have. `CoordinationSpec` is that annotation and
   `ideal_donor_positions` produces the restraint targets.

Pure numpy. Directions are unit vectors in a canonical orientation; callers
fit them to the existing bonds with `fit_directions`.
"""

from typing import List, Optional

import numpy as np

_SQ3 = np.sqrt(3.0)

# Canonical unit directions per geometry, keyed by name.
GEOMETRY_DIRECTIONS = {
    "linear": np.array([[0.0, 0.0, 1.0], [0.0, 0.0, -1.0]]),
    "bent": np.array([[0.0, 0.0, 1.0],
                      [0.0, np.sin(np.radians(104.5)),
                       np.cos(np.radians(104.5))]]),
    "trigonal_planar": np.array([[0.0, 0.0, 1.0],
                                 [0.0, _SQ3 / 2.0, -0.5],
                                 [0.0, -_SQ3 / 2.0, -0.5]]),
    "tetrahedral": np.array([[1.0, 1.0, 1.0], [1.0, -1.0, -1.0],
                             [-1.0, 1.0, -1.0], [-1.0, -1.0, 1.0]]) / _SQ3,
    "square_planar": np.array([[1.0, 0.0, 0.0], [-1.0, 0.0, 0.0],
                               [0.0, 1.0, 0.0], [0.0, -1.0, 0.0]]),
    # Apex along +z, four basal donors tipped slightly below the equator
    # (~101 deg apex-basal, the usual d(5) square-pyramidal compromise).
    "square_pyramidal": np.array([
        [0.0, 0.0, 1.0],
        [1.0, 0.0, -0.19], [-1.0, 0.0, -0.19],
        [0.0, 1.0, -0.19], [0.0, -1.0, -0.19]]),
    "seesaw": np.array([[0.0, 0.0, 1.0], [0.0, 0.0, -1.0],
                        [1.0, 0.0, 0.0], [-0.5, _SQ3 / 2.0, 0.0]]),
    "trigonal_bipyramidal": np.array([[0.0, 0.0, 1.0], [0.0, 0.0, -1.0],
                                      [1.0, 0.0, 0.0],
                                      [-0.5, _SQ3 / 2.0, 0.0],
                                      [-0.5, -_SQ3 / 2.0, 0.0]]),
    "octahedral": np.array([[1.0, 0.0, 0.0], [-1.0, 0.0, 0.0],
                            [0.0, 1.0, 0.0], [0.0, -1.0, 0.0],
                            [0.0, 0.0, 1.0], [0.0, 0.0, -1.0]]),
}

# Default geometry for a given coordination number (main-group VSEPR habit;
# a metal centre should be told explicitly — square planar vs tetrahedral is
# a chemical decision, not a geometric one).
DEFAULT_BY_COUNT = {
    1: "linear", 2: "bent", 3: "trigonal_planar", 4: "tetrahedral",
    5: "trigonal_bipyramidal", 6: "octahedral",
}


class CoordinationSpec:
    """A centre's intended coordination environment (the 'meta atom' hook).

    Carries no geometry itself — it is the *instruction* a builder or force
    field follows: n donors of `geometry` at `distance` Angstrom.
    """

    def __init__(self, geometry="tetrahedral", distance=2.0, locked=True):
        # type: (str, float, bool) -> None
        if geometry not in GEOMETRY_DIRECTIONS:
            raise ValueError("unknown geometry: {!r}".format(geometry))
        self.geometry = geometry
        self.distance = float(distance)
        self.locked = bool(locked)   # True = restrain during optimisation

    @property
    def n_donors(self):
        return len(GEOMETRY_DIRECTIONS[self.geometry])

    def to_dict(self):
        return {"geometry": self.geometry, "distance": self.distance,
                "locked": self.locked}

    @classmethod
    def from_dict(cls, d):
        return cls(d.get("geometry", "tetrahedral"),
                   d.get("distance", 2.0), d.get("locked", True))


def directions(geometry):
    # type: (str) -> np.ndarray
    """Canonical unit donor directions (n, 3) for a named geometry."""
    if geometry not in GEOMETRY_DIRECTIONS:
        raise ValueError("unknown geometry: {!r}".format(geometry))
    d = GEOMETRY_DIRECTIONS[geometry]
    return d / np.linalg.norm(d, axis=1)[:, None]


def geometry_for_count(n):
    # type: (int) -> str
    """VSEPR-ish default geometry name for a coordination number."""
    return DEFAULT_BY_COUNT.get(int(n), "octahedral" if n > 6 else "linear")


def _rotation_between(a, b):
    """Smallest rotation taking unit a to unit b (local copy so this module
    stays independent of core.align)."""
    a = np.asarray(a, float)
    b = np.asarray(b, float)
    a = a / np.linalg.norm(a)
    b = b / np.linalg.norm(b)
    v = np.cross(a, b)
    c = float(np.dot(a, b))
    s = float(np.linalg.norm(v))
    if s < 1e-12:
        if c > 0:
            return np.eye(3)
        perp = np.cross(a, [1.0, 0.0, 0.0])
        if np.linalg.norm(perp) < 1e-6:
            perp = np.cross(a, [0.0, 1.0, 0.0])
        perp /= np.linalg.norm(perp)
        return 2.0 * np.outer(perp, perp) - np.eye(3)
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + vx + vx @ vx * ((1 - c) / (s * s))


def _spin(axis, angle):
    axis = np.asarray(axis, float)
    axis = axis / np.linalg.norm(axis)
    x, y, z = axis
    c, s = np.cos(angle), np.sin(angle)
    C = 1.0 - c
    return np.array([
        [x * x * C + c, x * y * C - z * s, x * z * C + y * s],
        [y * x * C + z * s, y * y * C + c, y * z * C - x * s],
        [z * x * C - y * s, z * y * C + x * s, z * z * C + c]])


def fit_directions(existing, geometry):
    # type: (np.ndarray, str) -> np.ndarray
    """Rotate the template so it lines up with the bonds already present.

    `existing` is (m, 3) of (not necessarily unit) directions from the centre
    to its current neighbours; returns the full rotated template (n, 3).
    Alignment: first template direction onto the first existing one, then a
    spin about that axis chosen to maximise agreement with the rest.
    """
    tmpl = directions(geometry)
    ex = np.asarray(existing, dtype=float).reshape(-1, 3)
    if ex.shape[0] == 0:
        return tmpl
    norms = np.linalg.norm(ex, axis=1)
    keep = norms > 1e-9
    ex = ex[keep] / norms[keep][:, None]
    if ex.shape[0] == 0:
        return tmpl
    rot = _rotation_between(tmpl[0], ex[0])
    tmpl = tmpl @ rot.T
    if ex.shape[0] > 1:
        best, best_score = 0.0, -np.inf
        for angle in np.linspace(0.0, 2.0 * np.pi, 72, endpoint=False):
            cand = tmpl @ _spin(ex[0], angle).T
            # agreement = how well each existing bond finds a template slot
            score = float(np.sum(np.max(cand @ ex.T, axis=0)))
            if score > best_score:
                best, best_score = angle, score
        tmpl = tmpl @ _spin(ex[0], best).T
    return tmpl


def free_directions(existing, geometry=None, n_needed=1):
    # type: (np.ndarray, Optional[str], int) -> np.ndarray
    """Unit directions for `n_needed` NEW neighbours around a centre that
    already has `existing` ones (each (m,3) row = centre -> neighbour).

    Picks a geometry from the total coordination number unless told, fits the
    template to the existing bonds, greedily consumes the slots those bonds
    occupy, and returns the leftovers — so a CH3 fragment yields the missing
    tetrahedral vertex rather than "somewhere opposite-ish".
    """
    ex = np.asarray(existing, dtype=float).reshape(-1, 3)
    m = ex.shape[0]
    if geometry is None:
        geometry = geometry_for_count(m + max(int(n_needed), 1))
    tmpl = fit_directions(ex, geometry)
    used = set()
    if m:
        norms = np.linalg.norm(ex, axis=1)
        unit = ex[norms > 1e-9] / norms[norms > 1e-9][:, None]
        for v in unit:
            dots = tmpl @ v
            for cand in np.argsort(-dots):
                if int(cand) not in used:
                    used.add(int(cand))
                    break
    free = [tmpl[k] for k in range(len(tmpl)) if k not in used]
    if len(free) < n_needed:      # more neighbours than the template holds
        extra = directions("octahedral")
        free += [d for d in extra][:n_needed - len(free)]
    return np.array(free[:max(int(n_needed), 0)])


def repel_directions(fixed_dirs, n_needed, geometry=None, iters=250,
                     step=0.12):
    # type: (np.ndarray, int, int, float) -> np.ndarray
    """VSEPR by relaxation: unit directions for `n_needed` new neighbours
    that push as far as possible from `fixed_dirs` and from each other.

    The rigid template in `free_directions` assumes the existing bonds are
    already near-ideal. They often are not — a freshly drawn substituent sits
    wherever the cursor was dropped — and a fitted template can then hand
    back a slot that nearly overlaps a real bond. This Thomson-style
    relaxation (seeded FROM the template, so symmetric cases still land
    exactly on it) copes with any starting arrangement.
    """
    n_needed = max(int(n_needed), 0)
    if n_needed == 0:
        return np.zeros((0, 3))
    fixed = np.asarray(fixed_dirs, dtype=float).reshape(-1, 3)
    if fixed.size:
        norms = np.linalg.norm(fixed, axis=1)
        fixed = fixed[norms > 1e-9] / norms[norms > 1e-9][:, None]
    free = np.asarray(free_directions(fixed, geometry=geometry,
                                      n_needed=n_needed), dtype=float)
    free = free.reshape(-1, 3)[:n_needed]
    if free.shape[0] < n_needed:            # pad deterministically
        extra = directions("octahedral")[:n_needed - free.shape[0]]
        free = np.vstack([free, extra]) if free.size else extra
    for _ in range(int(iters)):
        moved = free.copy()
        for i in range(free.shape[0]):
            others = [d for k, d in enumerate(free) if k != i]
            pool = np.vstack([fixed] + [np.array(others)]) if others \
                else fixed
            if pool.size == 0:
                continue
            diff = free[i][None, :] - pool
            dist = np.linalg.norm(diff, axis=1)
            dist = np.where(dist < 1e-6, 1e-6, dist)
            force = (diff / (dist ** 3)[:, None]).sum(axis=0)
            force -= free[i] * float(np.dot(force, free[i]))   # tangential
            v = free[i] + force * step
            n = float(np.linalg.norm(v))
            if n > 1e-9:
                moved[i] = v / n
        free = moved
    return free


def ideal_donor_positions(center, spec, existing=None):
    # type: (np.ndarray, CoordinationSpec, Optional[np.ndarray]) -> np.ndarray
    """Where a spec's donors ought to sit around `center` — the restraint
    targets a guided pre-optimisation would pull toward."""
    center = np.asarray(center, dtype=float).reshape(3)
    dirs = (fit_directions(existing, spec.geometry)
            if existing is not None and len(existing)
            else directions(spec.geometry))
    return center[None, :] + dirs * spec.distance
