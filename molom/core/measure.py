"""Geometric measurements over atom coordinates. Pure numpy, degrees out."""

import numpy as np


def distance(p1, p2):
    # type: (np.ndarray, np.ndarray) -> float
    """Distance |p1-p2| in the coordinate unit (Angstrom)."""
    return float(np.linalg.norm(np.asarray(p2, float) - np.asarray(p1, float)))


def angle(p1, p2, p3):
    # type: (np.ndarray, np.ndarray, np.ndarray) -> float
    """Angle p1-p2-p3 (vertex at p2) in degrees."""
    a = np.asarray(p1, float) - np.asarray(p2, float)
    b = np.asarray(p3, float) - np.asarray(p2, float)
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0.0 or nb == 0.0:
        return 0.0
    cosang = np.clip(np.dot(a, b) / (na * nb), -1.0, 1.0)
    return float(np.degrees(np.arccos(cosang)))


def dihedral(p1, p2, p3, p4):
    # type: (np.ndarray, np.ndarray, np.ndarray, np.ndarray) -> float
    """Signed dihedral p1-p2-p3-p4 in degrees, in (-180, 180].

    atan2 formulation (numerically stable near 0/180), the same convention
    ORCA and ORCA Workbench's transform.set_dihedral use.
    """
    p1, p2, p3, p4 = (np.asarray(p, float) for p in (p1, p2, p3, p4))
    b1 = p2 - p1
    b2 = p3 - p2
    b3 = p4 - p3
    n1 = np.cross(b1, b2)
    n2 = np.cross(b2, b3)
    nb2 = np.linalg.norm(b2)
    if nb2 == 0.0:
        return 0.0
    x = np.dot(n1, n2)
    y = np.dot(np.cross(n1, n2), b2) / nb2
    ang = float(np.degrees(np.arctan2(y, x)))
    return 180.0 if ang == -180.0 else ang


def describe_picks(picks):
    # type: (list) -> str
    """Status-bar text for labelled picks [(label, xyz), ...] in click order.

    1 pick -> label + coordinates; 2 -> distance; 3 -> angle around the middle
    pick; 4 -> dihedral along the pick order; more -> a count. Labels carry
    the object prefix when several molecules are loaded ("water:O0"), so
    cross-molecule distances read correctly.
    """
    k = len(picks)
    if k == 0:
        return ""
    if k == 1:
        label, p = picks[0]
        return "{}  ({:.4f}, {:.4f}, {:.4f})".format(label, p[0], p[1], p[2])
    if k == 2:
        (la, a), (lb, b) = picks
        return "d({}-{}) = {:.3f} A".format(la, lb, distance(a, b))
    if k == 3:
        (la, a), (lb, b), (lc, c) = picks
        return "angle({}-{}-{}) = {:.2f} deg".format(la, lb, lc,
                                                     angle(a, b, c))
    if k == 4:
        (la, a), (lb, b), (lc, c), (ld, d) = picks
        return "dihedral({}-{}-{}-{}) = {:.2f} deg".format(
            la, lb, lc, ld, dihedral(a, b, c, d))
    return "{} atoms selected".format(k)


def describe_selection(structure, selection):
    # type: (object, list) -> str
    """Single-structure convenience wrapper around describe_picks (kept for
    tests and non-scene callers)."""
    c = structure.coords
    picks = [("{}{}".format(structure.symbols[i], i), c[i])
             for i in selection]
    return describe_picks(picks)
