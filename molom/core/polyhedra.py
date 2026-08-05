"""Coordination polyhedra — the way framework structures are actually shown.

A MOF drawn as balls and sticks is unreadable past a few nodes: what a reader
needs is the shape of each metal's coordination sphere, so the standard
picture (VESTA, Diamond, CrystalMaker, every MOF paper) draws a solid through
the donor atoms around each metal and leaves the linkers as sticks.

This module is the geometry half only — find the centres, collect their
donors, and build triangles through them. Nothing here imports Qt or GL.

The hull is computed directly rather than via scipy: a coordination sphere is
4-9 points, where a full Delaunay/QHull dependency would be absurd. For 4
points the tetrahedron is written down; beyond that a small gift-wrapping
pass over candidate face planes is exact at these sizes and needs no library.
"""

from typing import Dict, List, Optional, Tuple

import numpy as np

from . import bonding, elements

# Elements that get a polyhedron by default: the d/f block plus the metals
# and metalloids that actually sit at framework nodes (Al, Ga, In, Sn, Bi...).
# The list itself moved to `bonding` in round 38, where bond KINDS need the
# same question answered — one definition of "metal" for the whole package.
_NON_METALS = bonding.NON_METALS


def is_metal(symbol):
    # type: (str) -> bool
    return bonding.is_metal(symbol)


def find_centres(symbols, bonds, min_donors=3):
    # type: (list, list, int) -> Dict[int, List[int]]
    """{metal index: [bonded donor indices]} for every metal worth drawing.

    A centre with fewer than `min_donors` neighbours has no interior, so a
    polyhedron would be a line or a triangle floating in space.
    """
    neighbours = {}      # type: Dict[int, List[int]]
    for bond in bonds:
        i, j = int(bond[0]), int(bond[1])
        neighbours.setdefault(i, []).append(j)
        neighbours.setdefault(j, []).append(i)
    out = {}
    for index, symbol in enumerate(symbols):
        if not is_metal(symbol):
            continue
        donors = sorted(neighbours.get(index, []))
        if len(donors) >= int(min_donors):
            out[index] = donors
    return out


def hull_faces(points):
    # type: (np.ndarray) -> List[Tuple[int, int, int]]
    """Triangles of the convex hull of a small point set.

    Brute force over every candidate triple: a face of the hull is a plane
    with all remaining points strictly on one side. At n <= 12 that is a few
    hundred cheap tests — far less than the cost of taking a scipy
    dependency, and it degrades gracefully on degenerate (planar) input.
    """
    pts = np.asarray(points, dtype=float).reshape(-1, 3)
    n = len(pts)
    if n < 4:
        return [(0, 1, 2)] if n == 3 else []
    centre = pts.mean(axis=0)
    faces = []
    for a in range(n):
        for b in range(a + 1, n):
            for c in range(b + 1, n):
                normal = np.cross(pts[b] - pts[a], pts[c] - pts[a])
                length = float(np.linalg.norm(normal))
                if length < 1e-9:
                    continue                    # collinear triple
                normal = normal / length
                offset = float(normal @ pts[a])
                side = pts @ normal - offset
                # Ignore the three points forming the plane themselves.
                mask = np.ones(n, dtype=bool)
                mask[[a, b, c]] = False
                rest = side[mask]
                if rest.size == 0:
                    continue
                if np.all(rest <= 1e-7) or np.all(rest >= -1e-7):
                    # Wind the triangle so its normal points AWAY from the
                    # centre; a renderer with backface culling needs that.
                    if float(normal @ (pts[a] - centre)) < 0.0:
                        faces.append((a, c, b))
                    else:
                        faces.append((a, b, c))
    return faces


def build(symbols, coords, bonds, min_donors=3, max_donors=12):
    # type: (list, np.ndarray, list, int, int) -> List[dict]
    """One entry per metal centre: its index, colour, vertices and triangles.

    Colour comes from the metal itself, so a polyhedron reads as "this is an
    Fe node" without a legend.
    """
    xyz = np.asarray(coords, dtype=float).reshape(-1, 3)
    out = []
    for centre, donors in sorted(find_centres(symbols, bonds,
                                              min_donors).items()):
        if len(donors) > int(max_donors):
            continue                            # not a coordination sphere
        verts = xyz[donors]
        faces = hull_faces(verts)
        if not faces:
            continue
        z = elements.atomic_number(symbols[centre])
        out.append({
            "centre": int(centre),
            "symbol": elements.symbol(z),
            "color": elements.color_f(z),
            "vertices": verts,
            "faces": faces,
            "donors": list(donors),
        })
    return out


def triangle_soup(polys):
    # type: (List[dict]) -> Tuple[np.ndarray, np.ndarray]
    """Flatten built polyhedra into (Nx3 vertices, Nx3 colours) triangles,
    ready to hand straight to a renderer."""
    verts = []
    cols = []
    for poly in polys:
        for a, b, c in poly["faces"]:
            verts.extend([poly["vertices"][a], poly["vertices"][b],
                          poly["vertices"][c]])
            cols.extend([poly["color"]] * 3)
    if not verts:
        return np.zeros((0, 3)), np.zeros((0, 3))
    return np.asarray(verts, dtype=float), np.asarray(cols, dtype=float)
