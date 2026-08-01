"""Display-style presets and Avogadro 2's exact sizing rules.

Constants verified against avogadrolibs sources on 2026-07-30:

- ballandstick.cpp: atom sphere radius = radiusVDW(Z) * atom_scale with
  atom_scale default 0.3 (slider 0.1..0.9); bond cylinder radius default 0.1
  (slider 0.1..0.8).
- Multiple bonds (same file): double bond = TWO cylinders offset by
  +-1.0*bond_radius, each of radius 1.3*bond_radius (no central cylinder);
  triple bond = TWO cylinders offset by +-2.0*bond_radius at radius
  1.15*bond_radius PLUS the central full-radius cylinder (C++ fallthrough).
  The offset direction is any unit vector orthogonal to the bond, rotated 45
  degrees about the bond axis.
"""

from typing import List, Tuple

import numpy as np

# Avogadro defaults
ATOM_SCALE_BALL_AND_STICK = 0.3     # x VdW radius
BOND_RADIUS_DEFAULT = 0.1           # Angstrom
DOUBLE_BOND_RADIUS_FACTOR = 1.3
DOUBLE_BOND_OFFSET_FACTOR = 1.0     # x bond_radius
TRIPLE_BOND_RADIUS_FACTOR = 1.15
TRIPLE_BOND_OFFSET_FACTOR = 2.0     # x bond_radius


class Style:
    """One display preset. atom_scale scales VdW radii; fixed_atom_radius (if
    not None) overrides that with a constant sphere size (stick style)."""

    def __init__(self, key, label, atom_scale=ATOM_SCALE_BALL_AND_STICK,
                 fixed_atom_radius=None, bond_radius=BOND_RADIUS_DEFAULT,
                 show_bonds=True, show_multiple_bonds=True, wireframe=False):
        # type: (str, str, float, float, float, bool, bool, bool) -> None
        self.key = key
        self.label = label
        self.atom_scale = atom_scale
        self.fixed_atom_radius = fixed_atom_radius
        self.bond_radius = bond_radius
        self.show_bonds = show_bonds
        self.show_multiple_bonds = show_multiple_bonds
        self.wireframe = wireframe

    def atom_radius(self, vdw_radius):
        # type: (float) -> float
        if self.wireframe:
            return 0.0
        if self.fixed_atom_radius is not None:
            return self.fixed_atom_radius
        return vdw_radius * self.atom_scale


BALL_AND_STICK = Style("ball_and_stick", "Ball and stick")
STICK = Style("stick", "Stick (licorice)", fixed_atom_radius=0.15,
              bond_radius=0.15, show_multiple_bonds=False)
VDW = Style("vdw", "Van der Waals spheres", atom_scale=1.0, show_bonds=False)
WIREFRAME = Style("wireframe", "Wireframe", wireframe=True,
                  show_multiple_bonds=False)

STYLES = [BALL_AND_STICK, STICK, VDW, WIREFRAME]
STYLE_BY_KEY = {s.key: s for s in STYLES}


def bond_cylinders(p1, p2, order, bond_radius=BOND_RADIUS_DEFAULT,
                   show_multiple=True):
    # type: (np.ndarray, np.ndarray, int, float, bool) -> List[Tuple[np.ndarray, np.ndarray, float]]
    """Decompose one bond into cylinders [(start, end, radius), ...] following
    Avogadro's multi-bond layout (see module docstring). Cylinder colouring is
    the renderer's job (each half takes its atom's colour)."""
    p1 = np.asarray(p1, dtype=float)
    p2 = np.asarray(p2, dtype=float)
    order = int(order) if show_multiple else 1
    if order <= 1:
        return [(p1, p2, bond_radius)]
    axis = p2 - p1
    n = np.linalg.norm(axis)
    if n == 0.0:
        return [(p1, p2, bond_radius)]
    axis = axis / n
    delta = _unit_orthogonal(axis)
    delta = _rotate_about(delta, axis, np.pi / 4.0)   # Avogadro's 45 deg twist
    if order == 2:
        off = delta * (DOUBLE_BOND_OFFSET_FACTOR * bond_radius)
        r = bond_radius * DOUBLE_BOND_RADIUS_FACTOR
        return [(p1 + off, p2 + off, r), (p1 - off, p2 - off, r)]
    if order >= 4:
        # Quadruple — not an Avogadro case, but real chemistry for
        # metal-metal bonds (Re2Cl8 2-). Four cylinders on a square section.
        off = delta * (TRIPLE_BOND_OFFSET_FACTOR * bond_radius)
        off2 = np.cross(axis, delta) * (TRIPLE_BOND_OFFSET_FACTOR * bond_radius)
        r = bond_radius * TRIPLE_BOND_RADIUS_FACTOR
        return [(p1 + off, p2 + off, r), (p1 - off, p2 - off, r),
                (p1 + off2, p2 + off2, r), (p1 - off2, p2 - off2, r)]
    # order >= 3: two offset cylinders + the central one (C++ fallthrough)
    off = delta * (TRIPLE_BOND_OFFSET_FACTOR * bond_radius)
    r = bond_radius * TRIPLE_BOND_RADIUS_FACTOR
    return [(p1 + off, p2 + off, r), (p1 - off, p2 - off, r),
            (p1, p2, bond_radius)]


def _unit_orthogonal(v):
    # type: (np.ndarray) -> np.ndarray
    """A unit vector orthogonal to v (Eigen's unitOrthogonal equivalent)."""
    v = np.asarray(v, dtype=float)
    if abs(v[0]) < 0.9:
        p = np.cross(v, [1.0, 0.0, 0.0])
    else:
        p = np.cross(v, [0.0, 1.0, 0.0])
    return p / np.linalg.norm(p)


def _rotate_about(vec, axis, angle_rad):
    # type: (np.ndarray, np.ndarray, float) -> np.ndarray
    """Rodrigues rotation of `vec` about unit `axis`."""
    c, s = np.cos(angle_rad), np.sin(angle_rad)
    return (vec * c + np.cross(axis, vec) * s
            + axis * np.dot(axis, vec) * (1.0 - c))
