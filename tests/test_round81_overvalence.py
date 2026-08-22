"""Round 81: a CIF viewer draws the file, not the chemistry it wishes it had.

Christian's rule, and it dissolves open item A5 rather than patching it:

    "We are visualising information that is recorded in a cif file, not the
    physical reality. If someone made a shit refinement, then the cif is
    flawed and the visualiser should reflect that... We should not be
    silently glossing over bad refinements. Just draw the bond, even if it
    exceeds valence. It's a crystal structure. Due to occupancies and
    disorder, that comes with the territory. And those types of over-valences
    are informative because they either expose real, physical limitations, or
    because they indicate bad data refinement."

A5 was: a methyl disordered over two orientations at full occupancy gives one
carbon six hydrogens, the valence cap had to drop something, and the atoms
whose bonds were dropped floated as unbonded spheres - because dropping a
BOND does not drop an ATOM. Nothing is dropped now, so nothing floats.

What is deliberately NOT relaxed: an impossibly short contact (round 38), and
the cap on `periodic_pairs`, which answers a different question - what belongs
TOGETHER, for the fragment walks and the boundary completion (round 42d).
"""

import os

import numpy as np
import pytest

from molom.core import bonding, bondgraph, cif as cif_mod

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
FERROCENE = os.path.join(DATA, "cod_2101932_ferrocene.cif")


def _disordered_methyl():
    """A methyl over TWO orientations, written at full occupancy.

    Built here rather than copied from Christian's `4-ABA-oxime.cif`, which is
    CCDC data and cannot be redistributed. The numbers are the ones that file
    measures at: C-C 1.497 A, C-H 1.00 A, six H at 60 degree intervals.
    """
    cell = cif_mod.Cell(12.0, 12.0, 12.0, 90.0, 90.0, 90.0)
    symbols = ["C", "C"]
    cart = [[0.0, 0.0, 0.0], [1.497, 0.0, 0.0]]
    tilt = np.radians(180.0 - 109.5)          # H points AWAY from the ring C
    for k in range(6):
        phi = np.radians(60.0 * k)
        symbols.append("H")
        cart.append([-np.cos(tilt), np.sin(tilt) * np.cos(phi),
                     np.sin(tilt) * np.sin(phi)])
    cart = np.asarray(cart) + 3.0
    return symbols, cart, cell


def _degrees(graph, n):
    deg = dict.fromkeys(range(n), 0)
    for e in graph.edges:
        deg[e.i] += 1
        deg[e.j] += 1
    return deg


def test_the_fixture_is_the_geometry_it_claims_to_be():
    """Otherwise the test below demonstrates an artefact of my arithmetic."""
    _s, cart, _cell = _disordered_methyl()
    d = lambda a, b: float(np.linalg.norm(cart[a] - cart[b]))
    assert d(0, 1) == pytest.approx(1.497, abs=1e-3)      # C-C
    assert d(0, 2) == pytest.approx(1.000, abs=1e-3)      # C-H
    assert d(1, 2) == pytest.approx(2.059, abs=1e-2)      # ring C ... H
    assert d(2, 3) == pytest.approx(0.943, abs=1e-3)      # H...H at 60 deg


def test_a_disordered_methyl_keeps_all_six_hydrogens_and_its_skeleton():
    symbols, cart, cell = _disordered_methyl()
    frac = cell.to_fractional(cart)
    graph = bondgraph.build(symbols, frac, cell,
                            valence=False, cap_hydrogens=False)
    deg = _degrees(graph, len(symbols))
    assert deg[0] == 7                                    # 6 H + the C-C
    assert any({e.i, e.j} == {0, 1} for e in graph.edges)
    assert not [i for i, k in deg.items() if k == 0]      # nothing floating


def test_capping_is_what_used_to_leave_hydrogens_floating():
    """A5 stated as the measurement that made it a bug: the cap drops three
    bonds, and the three hydrogens on the other end of them are still in the
    atom list with nothing attached."""
    symbols, cart, cell = _disordered_methyl()
    frac = cell.to_fractional(cart)
    report = {}
    graph = bondgraph.build(symbols, frac, cell, report=report)
    deg = _degrees(graph, len(symbols))
    assert deg[0] == 4                                    # the cap
    orphans = [i for i, k in deg.items() if k == 0]
    assert len(orphans) == 3
    assert all(symbols[i] == "H" for i in orphans)
    assert len(report["dropped_bonds"]) == 3
    assert all(why == "over the covalent valence"
               for _i, _j, _d, why in report["dropped_bonds"])


def test_an_impossibly_short_contact_is_still_refused():
    """Not a valence judgement: no chemistry puts two nuclei that close, and
    round 43's tick already exists for looking at them."""
    cell = cif_mod.Cell(12.0, 12.0, 12.0, 90.0, 90.0, 90.0)
    symbols = ["C", "C"]
    cart = np.array([[3.0, 3.0, 3.0], [3.75, 3.0, 3.0]])   # 0.75 A, ratio 0.50
    report = {}
    graph = bondgraph.build(symbols, cell.to_fractional(cart), cell,
                            report=report, valence=False, cap_hydrogens=False)
    assert not graph.edges
    assert report["dropped_bonds"][0][3] == "impossibly short"


# ------------------------------------------------ what is deliberately NOT
def test_a_MOLECULE_still_gets_the_chemistry():
    """The rule is about a CIF. A molecule being drawn or edited is not a
    refinement, and the draw tool's whole behaviour - C -> N drops an H -
    rests on the cap being there."""
    symbols, cart, _cell = _disordered_methyl()
    bonds = bonding.perceive_bonds(symbols, cart)
    deg = dict.fromkeys(range(len(symbols)), 0)
    for i, j, _o in bonds:
        deg[i] += 1
        deg[j] += 1
    assert deg[0] == 4                        # capped, as before


def test_the_fragment_walk_still_caps():
    """`periodic_pairs` answers "what belongs TOGETHER", which is a different
    question from "what is drawn" (round 42d). It feeds the fragment walks,
    the boundary completion and the percolation test, where one bad contact
    fusing four molecules into a chain makes the whole cell read as a
    framework."""
    symbols, cart, cell = _disordered_methyl()
    pairs, _dists = cif_mod.periodic_pairs(symbols, cell.to_fractional(cart),
                                           cell)
    deg = dict.fromkeys(range(len(symbols)), 0)
    for i, j in pairs:
        deg[i] += 1
        deg[j] += 1
    assert deg[0] == 4


def test_the_drawn_crystal_path_is_the_uncapped_one():
    """`display_bonds` is the crystal's drawing path by definition, so this
    is its rule rather than a setting."""
    symbols, cart, cell = _disordered_methyl()
    bonds = cif_mod.display_bonds(symbols, cart, cell, len(symbols))
    deg = dict.fromkeys(range(len(symbols)), 0)
    for i, j, _o in bonds:
        deg[i] += 1
        deg[j] += 1
    assert deg[0] == 7
    assert not [i for i, k in deg.items() if k == 0]


def test_an_ordinary_crystal_is_unchanged():
    """Regression guard: the rule only bites where a file is over-valence,
    and neither vendored crystal is."""
    data = cif_mod.parse_cif(open(FERROCENE, encoding="utf-8",
                                  errors="replace").read())
    symbols, cart = cif_mod.expand(data, boundary=False)
    frac = data.cell.to_fractional(cart)
    capped = bondgraph.build(list(symbols), frac, data.cell)
    loose = bondgraph.build(list(symbols), frac, data.cell,
                            valence=False, cap_hydrogens=False)
    assert len(symbols) == 42
    assert len(capped.edges) == len(loose.edges) == 60
