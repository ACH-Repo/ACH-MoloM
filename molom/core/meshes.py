"""Unit meshes for instanced rendering — pure numpy, no GL.

The viewport draws every atom as ONE icosphere mesh instanced per atom, and
every bond cylinder as ONE unit cylinder mesh instanced per (half-)bond, so a
10k-atom molecule is two draw calls.
"""

from typing import Tuple

import numpy as np


def icosphere(subdivisions=2):
    # type: (int) -> Tuple[np.ndarray, np.ndarray, np.ndarray]
    """Unit icosphere. Returns (vertices (V,3) f32, normals (V,3) f32,
    indices (F,3) u32). For a unit sphere the normals equal the vertices.

    subdivisions=2 -> 320 triangles: smooth enough at ball-and-stick sizes,
    small enough that 10^4 instances stay cheap."""
    t = (1.0 + np.sqrt(5.0)) / 2.0
    verts = np.array([
        [-1, t, 0], [1, t, 0], [-1, -t, 0], [1, -t, 0],
        [0, -1, t], [0, 1, t], [0, -1, -t], [0, 1, -t],
        [t, 0, -1], [t, 0, 1], [-t, 0, -1], [-t, 0, 1],
    ], dtype=np.float64)
    verts /= np.linalg.norm(verts[0])
    faces = [
        (0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11),
        (1, 5, 9), (5, 11, 4), (11, 10, 2), (10, 7, 6), (7, 1, 8),
        (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8), (3, 8, 9),
        (4, 9, 5), (2, 4, 11), (6, 2, 10), (8, 6, 7), (9, 8, 1),
    ]
    verts = [tuple(v) for v in verts]

    def midpoint(cache, a, b):
        key = (a, b) if a < b else (b, a)
        if key in cache:
            return cache[key]
        va, vb = np.array(verts[a]), np.array(verts[b])
        m = (va + vb) / 2.0
        m /= np.linalg.norm(m)
        verts.append(tuple(m))
        cache[key] = len(verts) - 1
        return cache[key]

    for _ in range(subdivisions):
        cache = {}
        new_faces = []
        for a, b, c in faces:
            ab = midpoint(cache, a, b)
            bc = midpoint(cache, b, c)
            ca = midpoint(cache, c, a)
            new_faces += [(a, ab, ca), (b, bc, ab), (c, ca, bc), (ab, bc, ca)]
        faces = new_faces

    v = np.array(verts, dtype=np.float32)
    n = v.copy()   # unit sphere: normal == position
    f = np.array(faces, dtype=np.uint32)
    return v, n, f


def cylinder(segments=24):
    # type: (int) -> Tuple[np.ndarray, np.ndarray, np.ndarray]
    """Unit cylinder along +z, radius 1, z in [0, 1], open-ended (bond ends
    are hidden inside atom spheres). Returns (verts, normals, indices).

    Vertex layout: ring at z=0 then ring at z=1, `segments` vertices each."""
    ang = np.linspace(0.0, 2.0 * np.pi, segments, endpoint=False)
    x, y = np.cos(ang), np.sin(ang)
    bottom = np.stack([x, y, np.zeros_like(x)], axis=1)
    top = np.stack([x, y, np.ones_like(x)], axis=1)
    verts = np.vstack([bottom, top]).astype(np.float32)
    normals = np.vstack([np.stack([x, y, np.zeros_like(x)], axis=1)] * 2) \
        .astype(np.float32)
    idx = []
    for i in range(segments):
        j = (i + 1) % segments
        # two triangles per quad (bottom_i, bottom_j, top_i/top_j)
        idx += [(i, j, segments + i), (j, segments + j, segments + i)]
    return verts, normals, np.array(idx, dtype=np.uint32)


def cylinder_transforms(starts, ends, radii):
    # type: (np.ndarray, np.ndarray, np.ndarray) -> np.ndarray
    """Model matrices (N, 4, 4) f32 mapping the unit cylinder (+z, r=1,
    z 0..1) onto each start->end segment with the given radius. Vectorised.

    Rotation columns: two unit vectors orthogonal to the axis (scaled by r)
    and the full axis vector; translation = start point."""
    starts = np.asarray(starts, dtype=np.float64).reshape(-1, 3)
    ends = np.asarray(ends, dtype=np.float64).reshape(-1, 3)
    radii = np.asarray(radii, dtype=np.float64).reshape(-1)
    n = starts.shape[0]
    axis = ends - starts                                   # full-length z column
    length = np.linalg.norm(axis, axis=1)
    degenerate = length < 1e-12
    if degenerate.any():
        # Zero-length segment: give it a +z hair so the basis stays finite
        # (the cylinder itself collapses to nothing).
        axis[degenerate] = [0.0, 0.0, 1e-12]
        length[degenerate] = 1e-12
    unit = axis / length[:, None]
    # Build an orthonormal basis per axis: pick the world axis least aligned
    # with each bond, cross to get u, then v.
    helper = np.where(np.abs(unit[:, 0:1]) < 0.9,
                      np.tile([1.0, 0.0, 0.0], (n, 1)),
                      np.tile([0.0, 1.0, 0.0], (n, 1)))
    u = np.cross(helper, unit)
    u /= np.linalg.norm(u, axis=1)[:, None]
    v = np.cross(unit, u)
    m = np.zeros((n, 4, 4), dtype=np.float32)
    m[:, :3, 0] = u * radii[:, None]
    m[:, :3, 1] = v * radii[:, None]
    m[:, :3, 2] = axis
    m[:, :3, 3] = starts
    m[:, 3, 3] = 1.0
    return m
