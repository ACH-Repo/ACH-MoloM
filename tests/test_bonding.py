"""Bond perception must reproduce Avogadro's perceiveBondsSimple behaviour."""

import numpy as np

from molom.core import bonding
from molom.core.structure import Structure

WATER = [("O", 0.0, 0.0, 0.117), ("H", 0.0, 0.757, -0.469),
         ("H", 0.0, -0.757, -0.469)]


def test_water_bonds():
    s = Structure.from_atoms(WATER)
    bonds = bonding.perceive_bonds(s.symbols, s.coords)
    pairs = {(i, j) for i, j, _o in bonds}
    assert pairs == {(0, 1), (0, 2)}   # two O-H, no H-H


def test_no_h_h_bond():
    # H2 at typical bond length: distance-wise bondable, but the rule says no.
    bonds = bonding.perceive_bonds(["H", "H"],
                                   np.array([[0.0, 0, 0], [0.74, 0, 0]]))
    assert bonds == []


def test_noble_gases_never_bond():
    # He right next to an O — within any cutoff, still excluded.
    bonds = bonding.perceive_bonds(["He", "O"],
                                   np.array([[0.0, 0, 0], [1.0, 0, 0]]))
    assert bonds == []
    # Xe is NOT in Avogadro's exclusion list (only He/Ne/Ar/Kr).
    bonds = bonding.perceive_bonds(["Xe", "F"],
                                   np.array([[0.0, 0, 0], [1.9, 0, 0]]))
    assert bonds == [(0, 1, 1)]


def test_min_distance_cutoff():
    # Two carbons essentially on top of each other: closer than 0.32 A -> no bond.
    bonds = bonding.perceive_bonds(["C", "C"],
                                   np.array([[0.0, 0, 0], [0.2, 0, 0]]))
    assert bonds == []


def test_tolerance_window():
    # C-C covalent sum = 1.50; cutoff = 1.95. 1.9 bonds, 2.0 doesn't.
    bonds = bonding.perceive_bonds(["C", "C"],
                                   np.array([[0.0, 0, 0], [1.9, 0, 0]]))
    assert len(bonds) == 1
    bonds = bonding.perceive_bonds(["C", "C"],
                                   np.array([[0.0, 0, 0], [2.0, 0, 0]]))
    assert bonds == []


def test_keep_orders_on_reperception():
    s = Structure.from_atoms([("C", 0, 0, 0), ("C", 1.34, 0, 0),
                              ("H", -1.0, 0.6, 0)])
    bonding.perceive_structure_bonds(s)
    # user draws a double bond
    s.bonds = [(i, j, 2 if (i, j) == (0, 1) else o) for i, j, o in s.bonds]
    bonding.perceive_structure_bonds(s)              # keep_orders default
    orders = {(i, j): o for i, j, o in s.bonds}
    assert orders[(0, 1)] == 2
    bonding.perceive_structure_bonds(s, keep_orders=False)
    orders = {(i, j): o for i, j, o in s.bonds}
    assert orders[(0, 1)] == 1


def test_blocked_sweep_matches_direct():
    # Force multiple blocks through a small block size via monkeypatching.
    rng = np.random.default_rng(1)
    n = 40
    coords = rng.uniform(-6, 6, size=(n, 3))
    symbols = ["C"] * n
    ref = bonding.perceive_bonds(symbols, coords)
    old = bonding._BLOCK
    try:
        bonding._BLOCK = 17
        blocked = bonding.perceive_bonds(symbols, coords)
    finally:
        bonding._BLOCK = old
    assert ref == blocked
