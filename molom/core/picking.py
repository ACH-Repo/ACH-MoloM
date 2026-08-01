"""Atom picking: unproject a mouse click into a world-space ray and hit-test
atom spheres. Pure numpy (CPU-side, no GL readback), testable offline."""

from typing import Optional, Tuple

import numpy as np


def ray_from_screen(x, y, w, h, view, proj):
    # type: (float, float, int, int, np.ndarray, np.ndarray) -> Tuple[np.ndarray, np.ndarray]
    """Pixel (x, y) (window coords, y down) -> world-space ray (origin, dir)."""
    inv = np.linalg.inv((proj @ view).astype(np.float64))
    ndc_x = 2.0 * x / max(w, 1) - 1.0
    ndc_y = 1.0 - 2.0 * y / max(h, 1)
    p_near = inv @ np.array([ndc_x, ndc_y, -1.0, 1.0])
    p_far = inv @ np.array([ndc_x, ndc_y, 1.0, 1.0])
    p_near = p_near[:3] / p_near[3]
    p_far = p_far[:3] / p_far[3]
    d = p_far - p_near
    return p_near, d / np.linalg.norm(d)


def pick_sphere(origin, direction, centers, radii):
    # type: (np.ndarray, np.ndarray, np.ndarray, np.ndarray) -> Optional[int]
    """Index of the closest sphere hit by the ray, or None.

    Vectorised quadratic: |o + t d - c|^2 = r^2. The nearest positive t wins,
    so an atom part-hidden behind a bigger sphere still picks correctly when
    its surface is closer along the ray.
    """
    centers = np.asarray(centers, dtype=float).reshape(-1, 3)
    if centers.size == 0:
        return None
    radii = np.asarray(radii, dtype=float).reshape(-1)
    oc = origin[None, :] - centers                      # (N, 3)
    b = np.einsum("ij,j->i", oc, direction)             # d . oc
    c = np.einsum("ij,ij->i", oc, oc) - radii * radii
    disc = b * b - c
    hit = disc >= 0.0
    if not hit.any():
        return None
    sq = np.sqrt(disc[hit])
    t1 = -b[hit] - sq        # near intersection
    t2 = -b[hit] + sq        # far intersection (ray origin inside the sphere)
    t = np.where(t1 > 1e-6, t1, t2)
    valid = t > 1e-6
    if not valid.any():
        return None
    idx_all = np.flatnonzero(hit)[valid]
    return int(idx_all[np.argmin(t[valid])])


def pick_segment(origin, direction, starts, ends, radius):
    # type: (np.ndarray, np.ndarray, np.ndarray, np.ndarray, float) -> Optional[int]
    """Index of the closest line segment the ray passes within `radius` of
    (a fat-cylinder hit test for bonds), or None.

    Closest approach between the ray and each segment (clamped to the
    segment), then the smallest ray-t among those within radius wins.
    """
    starts = np.asarray(starts, dtype=float).reshape(-1, 3)
    if starts.size == 0:
        return None
    ends = np.asarray(ends, dtype=float).reshape(-1, 3)
    o = np.asarray(origin, dtype=float)
    d = np.asarray(direction, dtype=float)

    seg = ends - starts                        # (N, 3)
    w0 = starts - o[None, :]
    a = 1.0                                    # d.d (unit ray)
    b = np.einsum("ij,j->i", seg, d)           # seg . d
    c = np.einsum("ij,ij->i", seg, seg)        # seg . seg
    c = np.where(c < 1e-12, 1e-12, c)
    e = np.einsum("ij,j->i", w0, d)            # w0 . d
    f = np.einsum("ij,ij->i", w0, seg)         # w0 . seg
    denom = a * c - b * b
    denom = np.where(np.abs(denom) < 1e-12, 1e-12, denom)
    s = (b * f - c * e) / -denom               # param along RAY
    u = (a * f - b * e) / -denom               # param along SEGMENT
    u = np.clip(u, 0.0, 1.0)
    # Re-derive the ray param for the clamped segment point.
    p_seg = starts + seg * u[:, None]
    s = np.einsum("ij,j->i", p_seg - o[None, :], d)
    p_ray = o[None, :] + d[None, :] * s[:, None]
    dist = np.linalg.norm(p_ray - p_seg, axis=1)
    ok = (dist <= radius) & (s > 1e-6)
    if not ok.any():
        return None
    idx = np.flatnonzero(ok)
    return int(idx[np.argmin(s[ok])])
