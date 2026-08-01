"""Screen-space selection math for box and lasso select. Pure numpy."""

from typing import Tuple

import numpy as np


def project_points(points, view, proj, w, h):
    # type: (np.ndarray, np.ndarray, np.ndarray, int, int) -> Tuple[np.ndarray, np.ndarray]
    """World points -> (screen_xy (N,2), in_front (N,) bool).

    Screen coords are window pixels (y down), matching mouse events.
    `in_front` is False for points behind the camera (they must never be
    selectable by a screen region)."""
    pts = np.asarray(points, dtype=float).reshape(-1, 3)
    n = pts.shape[0]
    hom = np.hstack([pts, np.ones((n, 1))])
    clip = (proj.astype(float) @ view.astype(float) @ hom.T).T   # (N, 4)
    wclip = clip[:, 3]
    # Perspective: in front iff w > 0. Ortho: w == 1 everywhere; use clip z
    # within [-w, w] instead (points outside far/near still "project" fine
    # for region tests, so only reject the degenerate w<=0 case).
    in_front = wclip > 1e-9
    safe_w = np.where(in_front, wclip, 1.0)
    ndc = clip[:, :3] / safe_w[:, None]
    sx = (ndc[:, 0] + 1.0) * 0.5 * w
    sy = (1.0 - ndc[:, 1]) * 0.5 * h
    return np.stack([sx, sy], axis=1), in_front


def points_in_rect(screen_xy, x0, y0, x1, y1):
    # type: (np.ndarray, float, float, float, float) -> np.ndarray
    """Boolean mask of points inside the (any-corner-order) rectangle."""
    xa, xb = min(x0, x1), max(x0, x1)
    ya, yb = min(y0, y1), max(y0, y1)
    p = np.asarray(screen_xy, dtype=float).reshape(-1, 2)
    return ((p[:, 0] >= xa) & (p[:, 0] <= xb)
            & (p[:, 1] >= ya) & (p[:, 1] <= yb))


def points_in_polygon(screen_xy, polygon):
    # type: (np.ndarray, np.ndarray) -> np.ndarray
    """Boolean mask of points inside a closed polygon (lasso path).

    Vectorised even-odd ray casting; the polygon closes itself. Degenerate
    polygons (< 3 vertices) select nothing."""
    p = np.asarray(screen_xy, dtype=float).reshape(-1, 2)
    poly = np.asarray(polygon, dtype=float).reshape(-1, 2)
    if poly.shape[0] < 3:
        return np.zeros(p.shape[0], dtype=bool)
    x, y = p[:, 0], p[:, 1]
    inside = np.zeros(p.shape[0], dtype=bool)
    x1s, y1s = poly[:, 0], poly[:, 1]
    x2s, y2s = np.roll(x1s, -1), np.roll(y1s, -1)
    for x1, y1, x2, y2 in zip(x1s, y1s, x2s, y2s):
        if y1 == y2:
            continue   # horizontal edge contributes no crossing
        crosses = ((y1 > y) != (y2 > y))
        with np.errstate(divide="ignore", invalid="ignore"):
            xint = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
        inside ^= crosses & (x < xint)
    return inside
