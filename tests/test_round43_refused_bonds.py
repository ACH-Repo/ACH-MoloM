"""Round 43: the refused-bond visualisation override.

MoloM's standing rule is that only a real bond is drawn as a bond, and round
38 gave the reader the chemistry to enforce it. On a WHOLLY DISORDERED
structure that rule hides the thing itself: Christian's `2240539.cif` is a
plastic crystal, one molecule smeared over 192 operations of Fm-3m, and the
refused contacts are the only thing tying its cages together. Round 42d had
already established that grouping those atoms geometrically gives VESTA's four
cages; this round lets the user DRAW them, as a deliberate override.

Three properties matter and each has a test here:

  * the override is ADDITIVE and disjoint — a refused bond is never also a
    real one, so nothing is drawn twice;
  * the HYDROGEN CAP survives the union. This is the one genuinely subtle
    part: capping the kept and the candidate lists separately picks different
    partners for the same hydrogen, and their union hands it two sticks;
  * it is OFF unless asked for, and greying/thinning make it visibly a weaker
    claim than the chemistry beside it.
"""

import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from molom.core import blender_export as bx
from molom.core import bonding, build
from molom.core import style as style_mod
from molom.core.camera import Camera
from molom.core.scene import Scene
from molom.core.structure import Structure


def _clashing_pair():
    """Two carbons at 0.60 A — ratio 0.40 of the covalent radii, well under
    IMPOSSIBLE_FACTOR, so the distance test proposes a bond and the chemistry
    refuses it. The shape of every disorder-alternative contact."""
    return Structure.from_atoms([
        ("C", 0.0, 0.0, 0.0),
        ("C", 0.6, 0.0, 0.0),
    ], name="clash")


def _overloaded_carbon():
    """A carbon with six hydrogens at ordinary bonding distance: the valence
    cap has to drop two, which is round 41's disordered-methyl shape."""
    atoms = [("C", 0.0, 0.0, 0.0)]
    for k in range(6):
        a = 2.0 * np.pi * k / 6.0
        atoms.append(("H", 1.09 * np.cos(a), 1.09 * np.sin(a), 0.0))
    return Structure.from_atoms(atoms, name="CH6")


# ------------------------------------------------------------ the core list
def test_an_impossible_contact_is_refused_but_reported_as_drawable():
    s = _clashing_pair()
    report = {}
    bonding.perceive_structure_bonds(s, report=report)
    assert s.bonds == []                      # the rule still holds
    assert report["refused"] == [(0, 1)]      # and the override can draw it


def test_over_valence_bonds_are_refused_as_drawable_too():
    """Christian's file is refused mostly by VALENCE, not by shortness — 432
    of its 528 drops — so the override would barely change the picture if it
    only covered the impossibly short ones."""
    s = _overloaded_carbon()
    report = {}
    bonding.perceive_structure_bonds(s, report=report)
    assert len(s.bonds) == 4                  # carbon keeps four
    assert len(report["refused"]) == 2        # the other two are drawable
    reasons = {why for _i, _j, _d, why in report["dropped_bonds"]}
    assert reasons == {"over the covalent valence"}


def test_refused_and_real_bonds_are_disjoint():
    s = _overloaded_carbon()
    report = {}
    bonding.perceive_structure_bonds(s, report=report)
    real = {(i, j) for i, j, _o in s.bonds}
    assert real.isdisjoint(set(report["refused"]))


def test_nothing_refused_means_no_refused_key():
    """A clean molecule must not carry an empty override around, or the ❖
    page would offer a live-looking tick that does nothing."""
    report = {}
    bonding.perceive_structure_bonds(build.cubane(), report=report)
    assert not report.get("refused")


def test_the_hydrogen_cap_survives_the_union():
    """The subtle one. Capping the kept list and the full candidate list
    separately chooses different partners for the same hydrogen, so their
    union gives it two sticks — which is never a picture worth drawing
    (round 35b). Here H is 0.55 A from C2 (impossible, refused) and 1.05 A
    from C1 (real), so the two caps disagree by construction."""
    s = Structure.from_atoms([
        ("C", 0.00, 0.0, 0.0),
        ("C", 1.60, 0.0, 0.0),
        ("H", 1.05, 0.0, 0.0),
    ], name="H between two C")
    report = {}
    bonding.perceive_structure_bonds(s, report=report)
    both = [(i, j) for i, j, _o in s.bonds] + list(report.get("refused", []))
    sticks_on_h = sum(1 for i, j in both if 2 in (i, j))
    assert sticks_on_h <= 1
    assert len(both) == len(set(both))         # and nothing drawn twice


# ------------------------------------------------------------- the appearance
def test_muted_moves_toward_grey_not_toward_black():
    r, g, b = style_mod.muted((1.0, 0.0, 0.0), 0.5)
    assert r == pytest.approx(0.75)
    assert g == pytest.approx(0.25) and b == pytest.approx(0.25)


def test_muted_is_clamped_and_keeps_three_channels():
    assert style_mod.muted((1.0, 1.0, 1.0), 5.0) == pytest.approx((0.5,) * 3)
    assert style_mod.muted((0.2, 0.4, 0.6, 1.0), 0.0) == pytest.approx(
        (0.2, 0.4, 0.6))


def test_a_refused_bond_is_thinner_than_a_real_one():
    assert 0.0 < style_mod.REFUSED_BOND_SCALE < 1.0


# ------------------------------------------------------- the Blender export
def _scene_with_refused():
    s = _overloaded_carbon()
    report = {}
    bonding.perceive_structure_bonds(s, report=report)
    s.metadata["refused_bonds"] = [[int(i), int(j)]
                                   for i, j in report["refused"]]
    sc = Scene()
    sc.add(s, name="CH6")
    return sc, s


def _bond_count(scene, style):
    cam = Camera()
    cam.fit(np.zeros(3), 3.0)
    data = bx.collect(scene, style, bx.ExportOptions(), camera=cam)
    return len(data["bonds"])


@pytest.fixture
def ball_and_stick():
    return style_mod.BALL_AND_STICK


def test_the_export_omits_refused_bonds_unless_asked(ball_and_stick):
    scene, s = _scene_with_refused()
    s.metadata.pop("show_refused_bonds", None)
    off = _bond_count(scene, ball_and_stick)
    s.metadata["show_refused_bonds"] = True
    on = _bond_count(scene, ball_and_stick)
    # Two halves per bond, and the override adds exactly the refused ones.
    assert on - off == 2 * len(s.metadata["refused_bonds"])


def test_exported_refused_bonds_get_their_own_materials(ball_and_stick):
    scene, s = _scene_with_refused()
    s.metadata["show_refused_bonds"] = True
    cam = Camera()
    cam.fit(np.zeros(3), 3.0)
    data = bx.collect(scene, ball_and_stick, bx.ExportOptions(), camera=cam)
    names = {b[0] for b in data["bonds"]}
    assert any("refused" in n for n in names)
    # ...so they stay adjustable as a group in Blender, and never silently
    # share a material with the real bonds.
    assert any("refused" not in n for n in names)


# ------------------------------------------- boundary completion of a cage
# Christian: "only one third of the CH polyhedra are shown." On 2240539 the
# four cages sit on the F-centred lattice points, so the corner one belongs to
# all EIGHT corners and each face-centred one to two faces -- 14 images, and
# MoloM drew 4. Three separate faults, each pinned below.
def _corner_group():
    """One molecule straddling the origin, with atoms on the x, y and z faces
    but NONE with all three coordinates at zero. That is exactly the corner
    cage's shape, and the case per-atom shift logic cannot complete."""
    frac = np.array([
        [0.0, 0.10, 0.10],      # on the x face only
        [0.10, 0.0, 0.10],      # on the y face only
        [0.10, 0.10, 0.0],      # on the z face only
        [0.10, 0.10, 0.10],     # inside
    ])
    return ["C"] * 4, frac


def test_boundary_shifts_are_pooled_over_the_whole_molecule():
    from molom.core import cif

    symbols, frac = _corner_group()
    groups = [([0, 1, 2, 3], False)]           # one finite molecule
    added, _coords = cif.boundary_images(symbols, frac, groups)
    # Seven non-zero corner shifts, each carrying all four atoms. Per-atom
    # shifts can only reach the three faces and the three edges between them:
    # the (1,1,1) corner needs an atom with all three coordinates at zero, and
    # there is none.
    assert len(added) == 7 * 4


def test_a_periodic_component_still_travels_atom_by_atom():
    """The round-33 guard: rock salt's 'molecule' is the whole lattice, so a
    periodic group must copy only the atom that is on the boundary — or NaCl
    sprouts a slab instead of eight corner sodiums."""
    from molom.core import cif

    symbols, frac = _corner_group()
    groups = [([0, 1, 2, 3], True)]            # periodic
    added, _coords = cif.boundary_images(symbols, frac, groups)
    assert len(added) == 3                     # one copy per boundary atom


def test_reaches_into_cell_judges_a_disordered_fragment_whole():
    """With the chemistry graph a disordered cage shatters, so the shards that
    happen to lie outside are dropped one by one and the copy comes back
    TRUNCATED. Two atoms 0.5 A apart are an impossible contact — refused by
    round 38 — but they are one fragment geometrically."""
    from molom.core import cif

    # A 2-atom fragment: one inside the cell, one just outside, 0.9 A apart —
    # under the 0.975 A floor for C-C, so the chemistry refuses the bond and
    # they become two fragments. The distance has to be genuinely impossible
    # or the test passes either way and proves nothing.
    matrix = np.eye(3) * 10.0
    frac = np.array([[0.5, 0.5, 0.5],          # content atom
                     [0.95, 0.5, 0.5],         # copy, inside
                     [1.04, 0.5, 0.5]])        # copy, outside, 0.9 A from it
    symbols = ["C", "C", "C"]
    whole = cif._reaches_into_cell(symbols, frac, matrix, 1, geometric=True)
    assert whole.all()                 # one fragment, it reaches in, both stay
    shattered = cif._reaches_into_cell(symbols, frac, matrix, 1)
    assert not shattered[2]            # chemistry: a lone atom, outside, cut


# -------------------------------------------------------------- the ❖ page
def test_the_tick_is_greyed_when_nothing_was_refused():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.properties import CrystalPage
    from molom.core.cif import Cell

    QApplication.instance() or QApplication([])
    page = CrystalPage()
    cell = Cell(5.0, 5.0, 5.0, 90.0, 90.0, 90.0)
    page.set_cell(cell, refused=0)
    assert not page.refused_check.isEnabled()
    page.set_cell(cell, refused=144)
    assert page.refused_check.isEnabled()
    assert "144" in page.refused_check.text()


def test_syncing_the_page_does_not_emit_a_user_change():
    """The round-30 TimelinePanel bug in a different costume: a panel writing
    its own widgets from sync must not fire that back at the app, or opening
    a crystal would silently switch the override on for it."""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.properties import CrystalPage
    from molom.core.cif import Cell

    QApplication.instance() or QApplication([])
    page = CrystalPage()
    seen = []
    page.refused_toggled.connect(seen.append)
    page.set_cell(Cell(5.0, 5.0, 5.0, 90.0, 90.0, 90.0),
                  refused=10, refused_on=True)
    assert page.refused_check.isChecked()
    assert seen == []
    page.refused_check.setChecked(False)       # a REAL click still reports
    assert seen == [False]
