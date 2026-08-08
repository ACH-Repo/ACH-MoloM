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


def build_periodic(symbols, coords, cell, n_content, min_donors=3,
                   max_donors=12):
    # type: (list, np.ndarray, object, int, int, int) -> List[dict]
    """Polyhedra from the PERIODIC GRAPH, so they are always complete.

    `build` takes its donors from the drawn bonds, which makes a polyhedron
    only as complete as the picture: a metal sitting on a cell face is drawn
    as a boundary copy whose coordination is not completed unless the user
    ticks for it, so half of ZIF-8's zinc came out as flat triangles instead
    of tetrahedra.

    A coordination polyhedron is a property of the coordination SPHERE, not
    of what happens to be on screen. Here the donor POSITIONS come from the
    labelled graph — which knows where the fourth nitrogen is even when no
    atom is drawn there — so the solid closes whatever the display options
    say.
    """
    from . import bondgraph
    n = len(symbols)
    if n == 0 or n_content <= 0 or cell is None:
        return []
    n_content = min(int(n_content), n)
    xyz = np.asarray(coords, dtype=float).reshape(n, 3)
    frac = cell.to_fractional(xyz)
    matrix = np.asarray(cell.matrix(), dtype=float)
    graph = bondgraph.build(list(symbols)[:n_content], frac[:n_content], cell,
                            valence=False, cap_hydrogens=False)
    labels = bondgraph.label_instances(frac, cell, n_content)
    out = []
    for index in range(n):
        if not is_metal(symbols[index]):
            continue
        entry = labels[index] if index < len(labels) else None
        if entry is None:
            continue
        site, shift = entry
        points = []
        for j, eshift, _dist in graph.neighbours(site):
            if is_metal(symbols[j]):
                continue          # a polyhedron is drawn through its LIGANDS
            where = graph.frac[j] + np.array(
                [s + t for s, t in zip(shift, eshift)], dtype=float)
            points.append(where @ matrix)
        if len(points) < int(min_donors) or len(points) > int(max_donors):
            continue
        verts = np.asarray(points, dtype=float)
        faces = hull_faces(verts)
        if not faces:
            continue
        z = elements.atomic_number(symbols[index])
        out.append({
            "centre": int(index),
            "symbol": elements.symbol(z),
            "color": elements.color_f(z),
            "vertices": verts,
            "faces": faces,
            "donors": [],
        })
    return out


def hull_edges(polys):
    # type: (List[dict]) -> np.ndarray
    """Every distinct hull EDGE as a pair of points, for a wireframe pass.

    A translucent solid alone does not read as a shape — Christian's "edges
    are not visible enough". Outlining it is what makes a tetrahedron look
    like a tetrahedron rather than a coloured smudge.
    """
    segments = []
    for poly in polys:
        verts = np.asarray(poly["vertices"], dtype=float)
        seen = set()
        for tri in poly["faces"]:
            for a, b in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
                key = (min(a, b), max(a, b))
                if key in seen:
                    continue
                seen.add(key)
                segments.append(verts[key[0]])
                segments.append(verts[key[1]])
    if not segments:
        return np.zeros((0, 3))
    return np.asarray(segments, dtype=float)


def fresnel_colors(polys, eye, power=2.0, rim=0.85):
    # type: (List[dict], np.ndarray, float, float) -> np.ndarray
    """Per-vertex colours with a rim (Fresnel) term baked in.

    The face shader carries no normals and a single alpha uniform, so the
    grazing-angle brightening is computed here instead: a face seen edge-on
    is lightened toward white, one seen flat-on keeps the element colour.
    That is what gives a translucent solid a readable silhouette.
    """
    eye = np.asarray(eye, dtype=float).reshape(3)
    out = []
    for poly in polys:
        verts = np.asarray(poly["vertices"], dtype=float)
        base = np.asarray(poly["color"], dtype=float)[:3]
        for tri in poly["faces"]:
            a, b, c = verts[tri[0]], verts[tri[1]], verts[tri[2]]
            normal = np.cross(b - a, c - a)
            length = float(np.linalg.norm(normal))
            centroid = (a + b + c) / 3.0
            view = centroid - eye
            view_len = float(np.linalg.norm(view))
            if length < 1e-12 or view_len < 1e-12:
                facing = 1.0
            else:
                facing = abs(float(normal @ view) / (length * view_len))
            edge = (1.0 - facing) ** float(power)
            colour = base + (1.0 - base) * (float(rim) * edge)
            out.extend([colour, colour, colour])
    if not out:
        return np.zeros((0, 3))
    return np.clip(np.asarray(out, dtype=float), 0.0, 1.0)


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
