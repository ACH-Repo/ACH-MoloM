"""Planar alignment: find the largest (near-)planar group of atoms in a
molecule and the rotation that lays it into a target world plane.

"Largest planar element" is found RANSAC-style: candidate planes from the
overall best fit plus random atom triples, scored by inlier count within a
tolerance, then refined by PCA on the inliers. Works without any ring
perception, so a phenyl ring, an amide plane, or a flat sheet all win
naturally. Pure numpy, offline-testable."""

from typing import Tuple

import numpy as np

PLANE_NORMALS = {
    "xy": np.array([0.0, 0.0, 1.0]),
    "xz": np.array([0.0, 1.0, 0.0]),
    "yz": np.array([1.0, 0.0, 0.0]),
}


def best_fit_plane(coords):
    # type: (np.ndarray) -> Tuple[np.ndarray, np.ndarray]
    """(centroid, unit normal) of the least-squares plane through points.
    The normal is the smallest-variance principal axis."""
    pts = np.asarray(coords, dtype=float).reshape(-1, 3)
    centroid = pts.mean(axis=0)
    if pts.shape[0] < 3:
        return centroid, np.array([0.0, 0.0, 1.0])
    _u, _s, vt = np.linalg.svd(pts - centroid, full_matrices=False)
    return centroid, vt[-1]


def plane_inliers(coords, centroid, normal, tol):
    # type: (np.ndarray, np.ndarray, np.ndarray, float) -> np.ndarray
    """Boolean mask of points within `tol` (A) of the plane."""
    pts = np.asarray(coords, dtype=float).reshape(-1, 3)
    return np.abs((pts - centroid) @ normal) <= tol


def largest_planar_cluster(coords, tol=0.15, samples=400, seed=0):
    # type: (np.ndarray, float, int, int) -> np.ndarray
    """Mask of the largest coplanar-within-tol subset (>= 3 atoms).

    Candidates: the global best-fit plane plus planes through random atom
    triples; the best by inlier count (ties: smaller rms) wins and is refined
    once by PCA over its inliers."""
    pts = np.asarray(coords, dtype=float).reshape(-1, 3)
    n = pts.shape[0]
    if n < 3:
        return np.ones(n, dtype=bool)

    def score(centroid, normal):
        d = np.abs((pts - centroid) @ normal)
        mask = d <= tol
        rms = float(np.sqrt((d[mask] ** 2).mean())) if mask.any() else 1e9
        return mask, int(mask.sum()), rms

    best_mask, best_n, best_rms = score(*best_fit_plane(pts))
    rng = np.random.default_rng(seed)
    for _ in range(min(samples, n * (n - 1) * (n - 2) // 6 + 1)):
        i, j, k = rng.choice(n, size=3, replace=False)
        v1, v2 = pts[j] - pts[i], pts[k] - pts[i]
        nrm = np.cross(v1, v2)
        ln = np.linalg.norm(nrm)
        if ln < 1e-9:
            continue        # collinear triple defines no plane
        mask, cnt, rms = score(pts[i], nrm / ln)
        if cnt > best_n or (cnt == best_n and rms < best_rms):
            best_mask, best_n, best_rms = mask, cnt, rms
    # refine on the inliers (PCA), then re-collect inliers once
    if best_n >= 3:
        c, nrm = best_fit_plane(pts[best_mask])
        best_mask = plane_inliers(pts, c, nrm, tol)
    return best_mask


def rotation_between(a, b):
    # type: (np.ndarray, np.ndarray) -> np.ndarray
    """Smallest rotation matrix taking unit vector a to unit vector b
    (Rodrigues; antiparallel handled via an arbitrary perpendicular)."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    a = a / np.linalg.norm(a)
    b = b / np.linalg.norm(b)
    v = np.cross(a, b)
    c = float(np.dot(a, b))
    s = np.linalg.norm(v)
    if s < 1e-12:
        if c > 0:
            return np.eye(3)
        # 180 deg: rotate about any axis perpendicular to a
        perp = np.cross(a, [1.0, 0.0, 0.0])
        if np.linalg.norm(perp) < 1e-6:
            perp = np.cross(a, [0.0, 1.0, 0.0])
        perp /= np.linalg.norm(perp)
        return 2.0 * np.outer(perp, perp) - np.eye(3)
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + vx + vx @ vx * ((1 - c) / (s * s))


def align_vector_to_axis(v, axis_unit):
    # type: (np.ndarray, np.ndarray) -> np.ndarray
    """Smallest rotation taking direction v onto the LINE of `axis_unit`
    (sign chosen for the smaller turn — use `flip_about_axis` afterwards if
    the molecule ends up the wrong way around)."""
    v = np.asarray(v, dtype=float)
    n = np.linalg.norm(v)
    if n < 1e-12:
        return np.eye(3)
    v = v / n
    t = np.asarray(axis_unit, dtype=float)
    t = t / np.linalg.norm(t)
    if np.dot(v, t) < 0:
        t = -t
    return rotation_between(v, t)


def flip_about_axis(axis_unit):
    # type: (np.ndarray) -> np.ndarray
    """180-degree rotation about an axis PERPENDICULAR to `axis_unit` —
    reverses a just-aligned direction while keeping it on the same line."""
    a = np.asarray(axis_unit, dtype=float)
    a = a / np.linalg.norm(a)
    perp = np.cross(a, [0.0, 0.0, 1.0])
    if np.linalg.norm(perp) < 1e-6:
        perp = np.cross(a, [0.0, 1.0, 0.0])
    perp /= np.linalg.norm(perp)
    return 2.0 * np.outer(perp, perp) - np.eye(3)


def zstack_offsets(radii, gap=2.0):
    # type: (list, float) -> list
    """Z centers for stacking molecules (given bounding radii) along the Z
    axis so neighbouring bounding spheres keep `gap` A of clearance —
    multi-SMILES imports land arranged instead of superimposed."""
    zs, z = [], 0.0
    for k, r in enumerate(radii):
        if k > 0:
            z += radii[k - 1] + gap + r
        zs.append(z)
    return zs


def distribute_offsets(extents, positions, gap=2.0):
    # type: (list, list, float) -> list
    """Where each object's CENTRE goes so neighbours clear each other by `gap`.

    `extents` is each object's FULL width along the chosen axis and
    `positions` its current centre on that axis. Returns the new centres, in
    the same order as the input.

    Three decisions, and the first two are what make this feel right rather
    than merely correct.

    **The extent is measured along the AXIS, not as a bounding radius.**
    `zstack_offsets` uses radii, which is fine for dropping SMILES results in
    a column but wrong here: a long flat molecule laid along x is nearly its
    own length wide in x and almost nothing in y, and spacing it by its
    radius leaves a hole you did not ask for.

    **The existing ORDER is kept.** Objects are laid out in the order of their
    current positions along the axis, so distributing tidies an arrangement
    up rather than reshuffling it into scene-id order - which would move
    things past each other for no reason the user can see.

    **The GROUP does not move.** The result is recentred on the span the
    objects already occupy, so distributing three molecules does not also
    slide them off to one side.
    """
    n = len(extents)
    if n == 0:
        return []
    if n != len(positions):
        raise ValueError("one extent and one position per object")
    order = sorted(range(n), key=lambda i: float(positions[i]))
    gap = float(gap)
    centres = [0.0] * n
    cursor = 0.0
    for k, i in enumerate(order):
        half = abs(float(extents[i])) / 2.0
        if k:
            prev = order[k - 1]
            cursor += abs(float(extents[prev])) / 2.0 + gap + half
        centres[i] = cursor
    before = sum(float(p) for p in positions) / n
    after = sum(centres) / n
    shift = before - after
    return [c + shift for c in centres]


def axis_extent(coords, axis_unit):
    # type: (np.ndarray, np.ndarray) -> tuple
    """`(centre, width)` of these atoms projected on a unit axis.

    The width a molecule really occupies along the direction it is about to
    be spread along - which is the number `distribute_offsets` wants and the
    one a bounding sphere cannot give.
    """
    xyz = np.asarray(coords, dtype=float).reshape(-1, 3)
    if not len(xyz):
        return 0.0, 0.0
    t = xyz @ np.asarray(axis_unit, dtype=float)
    lo, hi = float(t.min()), float(t.max())
    return 0.5 * (lo + hi), hi - lo


def align_planar_to_plane(coords, target_normal, tol=0.15):
    # type: (np.ndarray, np.ndarray, float) -> Tuple[np.ndarray, np.ndarray, np.ndarray]
    """Rotation laying the molecule's largest planar cluster into the target
    plane. Returns (rot3, pivot, cluster_mask); apply as
    R @ (x - pivot) + pivot. The normal's sign is chosen for the smaller
    rotation (a plane has two normals)."""
    mask = largest_planar_cluster(coords, tol=tol)
    centroid, normal = best_fit_plane(np.asarray(coords)[mask])
    t = np.asarray(target_normal, dtype=float)
    t = t / np.linalg.norm(t)
    if np.dot(normal, t) < 0:
        normal = -normal
    return rotation_between(normal, t), centroid, mask
