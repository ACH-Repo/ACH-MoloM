"""Analytically built starter structures.

Blender opens on a default cube; MoloM opens on **cubane** (C8H8) — the
closest chemical joke, and genuinely useful as a scale reference: it is
strained, obviously three-dimensional, and its symmetry makes a wrong axis
alignment or a broken bond perception jump out immediately.

Built from geometry rather than parsed from a file or generated from SMILES,
so it is EXACTLY centred on the origin and aligned to the world axes (no
RDKit dependency at startup, no embedding jitter).
"""

import numpy as np

from .structure import Structure

CUBANE_CC = 1.571      # C-C edge, gas-phase electron diffraction
CUBANE_CH = 1.098      # C-H


def cubane():
    # type: () -> Structure
    """C8H8 on a cube centred at the origin, edges along X/Y/Z.

    Carbons sit on the eight (+-a, +-a, +-a) corners; each hydrogen points
    straight out along that corner's body diagonal.
    """
    a = CUBANE_CC / 2.0
    signs = [(sx, sy, sz) for sx in (1, -1) for sy in (1, -1)
             for sz in (1, -1)]
    carbons = np.array([[sx * a, sy * a, sz * a] for sx, sy, sz in signs])
    diag = carbons / np.linalg.norm(carbons, axis=1)[:, None]
    hydrogens = carbons + diag * CUBANE_CH
    atoms = [("C", *[float(v) for v in p]) for p in carbons]
    atoms += [("H", *[float(v) for v in p]) for p in hydrogens]
    s = Structure.from_atoms(atoms, name="cubane",
                             metadata={"comment": "built-in starter molecule",
                                       "source": "molom.core.build"})
    # Explicit bonds: cube edges join corners differing in ONE sign, plus the
    # eight C-H. Perception would find the same set, but being explicit keeps
    # the default scene identical regardless of tolerance tweaks.
    bonds = []
    for i in range(8):
        for j in range(i + 1, 8):
            if sum(1 for k in range(3) if signs[i][k] != signs[j][k]) == 1:
                bonds.append((i, j, 1))
    bonds += [(i, 8 + i, 1) for i in range(8)]
    s.bonds = bonds
    return s
