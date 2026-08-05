"""Round 36: the bond-axis twist (methyl rotor) and the right-button rules.

Two independent things, both from the same session:

* `internal.torsion_split` — which fragment a selection means, and which bond
  it turns about. All the interesting failure modes are graph-shaped (rings,
  whole-molecule selections, one atom on the axis), so they are tested offline
  on hand-built connectivity where the answer can be reasoned out by hand.
* the right button no longer starts flight on the PRESS, which is what made
  the geometry context menu unreachable.
"""

import numpy as np
import pytest

from molom.core import internal, measure
from molom.core.structure import Structure


# ---------------------------------------------------------------- fixtures
def _ethane_bonds():
    """C0(H2,H3,H4)-C1(H5,H6,H7) as plain connectivity."""
    return [(0, 1, 1), (0, 2, 1), (0, 3, 1), (0, 4, 1),
            (1, 5, 1), (1, 6, 1), (1, 7, 1)]


def _toluene_bonds():
    """Ring C0-C5, H6-H10 on C1-C5, methyl C11 with H12-H14 on C0."""
    ring = [(i, (i + 1) % 6, 1) for i in range(6)]
    hs = [(i, 5 + i, 1) for i in range(1, 6)]
    me = [(0, 11, 1), (11, 12, 1), (11, 13, 1), (11, 14, 1)]
    return ring + hs + me


def _ethane_structure():
    """Real staggered-ish geometry, so the rotation can be measured."""
    s = Structure.from_atoms([
        ("C", 0.0, 0.0, 0.0), ("C", 1.53, 0.0, 0.0),
        ("H", -0.36, 1.02, 0.0), ("H", -0.36, -0.51, 0.88),
        ("H", -0.36, -0.51, -0.88),
        ("H", 1.89, -1.02, 0.0), ("H", 1.89, 0.51, 0.88),
        ("H", 1.89, 0.51, -0.88),
    ], name="ethane")
    s.bonds = _ethane_bonds()
    return s


# ------------------------------------------------------- which group is it?
@pytest.mark.parametrize("selected", [[0], [2], [2, 3, 4], [0, 2, 3, 4]])
def test_every_way_of_pointing_at_a_methyl_gives_the_same_rotor(selected):
    """The carbon, one hydrogen, the three hydrogens or the whole group: a
    user means the same rotor by all four, and picking the literal selection
    would rotate nothing at all in the first case (the carbon sits ON the
    axis)."""
    moving, anchor, pivot = internal.torsion_split(8, _ethane_bonds(),
                                                   selected)
    assert moving == {0, 2, 3, 4}
    assert (anchor, pivot) == (1, 0)


def test_the_far_methyl_is_a_rotor_too():
    moving, anchor, pivot = internal.torsion_split(8, _ethane_bonds(), [5])
    assert moving == {1, 5, 6, 7}
    assert (anchor, pivot) == (0, 1)


def test_the_whole_molecule_has_no_rotor():
    assert internal.torsion_split(8, _ethane_bonds(), list(range(8))) is None


def test_water_has_no_rotor():
    """Both sides of a cut must be a real group. Rotating everything about a
    terminal O-H is a rigid rotation of the molecule, which is what R does."""
    assert internal.torsion_split(3, [(0, 1, 1), (0, 2, 1)], [1]) is None


def test_a_ring_atom_never_yields_a_ring_split():
    """No single bond frees an atom inside a ring — cutting one ring bond
    leaves the ring joined by the other route. Toluene's aromatic CH resolves
    to the PHENYL turning about the C-CH3 bond, never to part of the ring."""
    moving, anchor, pivot = internal.torsion_split(15, _toluene_bonds(), [2])
    assert moving == set(range(11))          # the whole ring, with its H's
    assert (anchor, pivot) == (11, 0)


def test_the_methyl_of_toluene_is_the_smaller_side():
    """Two sides contain the selection here; the SMALLEST wins, which is what
    makes "select the methyl, spin the methyl" work next to a big ring."""
    for sel in ([11], [12], [11, 12, 13, 14]):
        moving, anchor, pivot = internal.torsion_split(15, _toluene_bonds(),
                                                       sel)
        assert moving == {11, 12, 13, 14}
        assert (anchor, pivot) == (0, 11)


def test_a_hydroxyl_hydrogen_gives_the_OH_rotor():
    """Methanol: C0(H1,H2,H3)-O4-H5."""
    bonds = [(0, 1, 1), (0, 2, 1), (0, 3, 1), (0, 4, 1), (4, 5, 1)]
    moving, anchor, pivot = internal.torsion_split(6, bonds, [5])
    assert moving == {4, 5}
    assert (anchor, pivot) == (0, 4)


def test_a_selection_spanning_two_fragments_has_no_rotor():
    bonds = _ethane_bonds() + [(8, 9, 1), (8, 10, 1), (8, 11, 1), (8, 12, 1)]
    assert internal.torsion_split(13, bonds, [2, 9]) is None


def test_a_duplicated_bond_does_not_fake_a_ring():
    """`_edge_adjacency` de-duplicates: listing C-C twice must not make the
    bridge search believe there are two independent routes."""
    bonds = _ethane_bonds() + [(1, 0, 1)]
    assert internal.torsion_split(8, bonds, [0]) is not None


# -------------------------------------------------------------- the maths
def test_a_twist_moves_the_group_and_nothing_else():
    s = _ethane_structure()
    moving, anchor, pivot = internal.torsion_split(s.n_atoms, s.bonds, [2])
    out = internal.set_twist(s.coords, moving, anchor, pivot, 60.0)
    fixed = [i for i in range(s.n_atoms) if i not in moving]
    assert np.allclose(out[fixed], s.coords[fixed])
    assert not np.allclose(out[3], s.coords[3])


def test_a_twist_preserves_every_length_inside_the_group():
    s = _ethane_structure()
    moving, anchor, pivot = internal.torsion_split(s.n_atoms, s.bonds, [2])
    out = internal.set_twist(s.coords, moving, anchor, pivot, 137.0)
    for i, j, _o in s.bonds:
        assert measure.distance(out[i], out[j]) == pytest.approx(
            measure.distance(s.coords[i], s.coords[j]), abs=1e-9)


def test_the_twist_sign_matches_the_dihedral_convention():
    """+theta must RAISE an x-anchor-pivot-y torsion by exactly theta, the
    same convention `set_dihedral` and `core.measure` already use — otherwise
    typing a number into this modal and into the dihedral one would mean
    opposite things."""
    s = _ethane_structure()
    moving, anchor, pivot = internal.torsion_split(s.n_atoms, s.bonds, [2])
    before = measure.dihedral(s.coords[5], s.coords[anchor], s.coords[pivot],
                              s.coords[2])
    out = internal.set_twist(s.coords, moving, anchor, pivot, 40.0)
    after = measure.dihedral(out[5], out[anchor], out[pivot], out[2])
    assert ((after - before + 180.0) % 360.0) - 180.0 == pytest.approx(
        40.0, abs=1e-6)


def test_a_full_turn_is_the_identity():
    s = _ethane_structure()
    moving, anchor, pivot = internal.torsion_split(s.n_atoms, s.bonds, [2])
    out = internal.set_twist(s.coords, moving, anchor, pivot, 360.0)
    assert np.allclose(out, s.coords, atol=1e-9)


def test_kind_for_count_never_returns_the_twist():
    """It is not chosen by how many atoms are picked, so the count table must
    not offer it — 2/3/4 picks still mean length/angle/dihedral."""
    for n in range(0, 8):
        assert internal.kind_for_count(n) != internal.TWIST
    assert internal.label_for(internal.TWIST) != internal.TWIST
    assert internal.unit_for(internal.TWIST) == "deg"


# =================================================================== UI
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def win():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.app import MainWindow
    QApplication.instance() or QApplication([])
    w = MainWindow()
    w.show()
    w.load_default_scene()
    return w


@pytest.fixture
def ethane(win):
    obj = win._install_structure(_ethane_structure())
    if obj is None:
        obj = win.scene.objects[-1]
    win.active_id = obj.id
    return win, obj


# ------------------------------------------------- the right button arbitrates
def _press(vp, pos, button):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QMouseEvent
    vp.mousePressEvent(QMouseEvent(
        QMouseEvent.MouseButtonPress, pos, vp.mapToGlobal(pos.toPoint()),
        button, button, Qt.NoModifier))


def _release(vp, pos, button):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QMouseEvent
    vp.mouseReleaseEvent(QMouseEvent(
        QMouseEvent.MouseButtonRelease, pos, vp.mapToGlobal(pos.toPoint()),
        button, Qt.NoButton, Qt.NoModifier))


def _move(vp, pos):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QMouseEvent
    vp.mouseMoveEvent(QMouseEvent(
        QMouseEvent.MouseMove, pos, vp.mapToGlobal(pos.toPoint()),
        Qt.NoButton, Qt.RightButton, Qt.NoModifier))


def test_a_right_press_arms_flight_but_does_not_start_it(win):
    """Round 35 took off on the press. That captures the pointer — hides it
    and parks it at the viewport centre — so the release landed in the middle
    of the screen, picked nothing, and the context menu never opened."""
    from PySide6.QtCore import QPointF, Qt
    vp = win.viewport
    _press(vp, QPointF(60.0, 60.0), Qt.RightButton)
    assert not vp.flying()
    assert vp._fly_pending is not None
    assert vp._fly_hold_timer.isActive()
    _release(vp, QPointF(60.0, 60.0), Qt.RightButton)
    assert not vp.flying()
    assert vp._fly_pending is None


def test_holding_the_right_button_past_the_threshold_flies(win):
    from PySide6.QtCore import QPointF, Qt
    vp = win.viewport
    _press(vp, QPointF(60.0, 60.0), Qt.RightButton)
    vp._fly_hold_elapsed()                   # what the timer does on timeout
    assert vp.flying()
    assert not vp._fly["latched"]
    vp.stop_fly(coast=False)


def test_dragging_the_right_button_flies_at_once(win):
    """Waiting out the hold with the mouse already moving would feel stuck."""
    from PySide6.QtCore import QPointF, Qt
    vp = win.viewport
    _press(vp, QPointF(60.0, 60.0), Qt.RightButton)
    _move(vp, QPointF(90.0, 75.0))
    assert vp.flying()
    vp.stop_fly(coast=False)


def test_a_short_right_click_on_the_selection_opens_the_menu(ethane):
    """The bug Christian reported: the geometry menu had become unreachable
    because the right button always went flying."""
    from PySide6.QtCore import QPointF, Qt
    win, obj = ethane
    vp = win.viewport
    vp.set_selection([(obj.id, 0), (obj.id, 1)])
    opened = []
    vp.open_context_menu = lambda pos: opened.append(pos)
    pos = QPointF(60.0, 60.0)
    _press(vp, pos, Qt.RightButton)
    _release(vp, pos, Qt.RightButton)
    assert opened and not vp.flying()
    # ...and at the PRESS position. Round 35 passed the release position,
    # which flight had already teleported to the viewport centre.
    assert (opened[0].x(), opened[0].y()) == (pos.x(), pos.y())


def test_zero_hold_leaves_double_click_as_the_only_way_in(win):
    """The Settings escape hatch: 0 ms means a right press never flies, no
    matter how long it is held or how far it is dragged."""
    from PySide6.QtCore import QPointF, Qt
    vp = win.viewport
    vp.fly_hold_ms = 0.0
    _press(vp, QPointF(60.0, 60.0), Qt.RightButton)
    assert not vp._fly_hold_timer.isActive()
    _move(vp, QPointF(200.0, 200.0))
    assert not vp.flying()
    vp.mouseDoubleClickEvent(_dbl(vp, QPointF(60.0, 60.0)))
    assert vp.flying() and vp._fly["latched"]
    vp.stop_fly(coast=False)


def _dbl(vp, pos):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QMouseEvent
    return QMouseEvent(QMouseEvent.MouseButtonDblClick, pos,
                       vp.mapToGlobal(pos.toPoint()), Qt.RightButton,
                       Qt.RightButton, Qt.NoModifier)


def test_a_double_click_latches_and_a_press_lands(win):
    from PySide6.QtCore import QPointF, Qt
    vp = win.viewport
    vp.mouseDoubleClickEvent(_dbl(vp, QPointF(60.0, 60.0)))
    assert vp.flying() and vp._fly["latched"]
    assert vp._fly_pending is None            # the arm was cancelled
    _press(vp, QPointF(60.0, 60.0), Qt.RightButton)
    assert not vp.flying()


def test_escape_drops_a_pending_arm(win):
    """A timer that outlives whatever interrupted it would take off later, at
    a moment nobody asked for."""
    from PySide6.QtCore import QPointF, Qt
    vp = win.viewport
    _press(vp, QPointF(60.0, 60.0), Qt.RightButton)
    vp.cancel_modes()
    assert vp._fly_pending is None
    assert not vp._fly_hold_timer.isActive()


# --------------------------------------------------------------- the modal
def test_t_starts_the_twist_modal_and_left_click_commits(ethane):
    from PySide6.QtCore import QPointF, Qt
    win, obj = ethane
    vp = win.viewport
    before = obj.structure.coords.copy()
    vp.set_selection([(obj.id, 2)])
    win.run_op("twist_bond")
    assert vp._internal is not None
    assert vp._internal["kind"] == internal.TWIST
    assert vp._internal["rows"] == [0, 2, 3, 4]
    vp._internal["state"].add_delta(45.0)
    vp._apply_internal()
    _press(vp, QPointF(10.0, 10.0), Qt.LeftButton)      # confirm
    assert vp._internal is None
    assert not np.allclose(obj.structure.coords[2], before[2])
    assert np.allclose(obj.structure.coords[5], before[5])


def test_right_click_cancels_the_twist_exactly(ethane):
    from PySide6.QtCore import QPointF, Qt
    win, obj = ethane
    vp = win.viewport
    before = obj.structure.coords.copy()
    vp.set_selection([(obj.id, 2)])
    win.run_op("twist_bond")
    vp._internal["state"].add_delta(90.0)
    vp._apply_internal()
    _press(vp, QPointF(10.0, 10.0), Qt.RightButton)     # cancel
    assert vp._internal is None
    assert np.allclose(obj.structure.coords, before)


def test_the_twist_says_why_it_cannot_run(ethane):
    """A refusal has to explain itself: "nothing happened" is the one
    response that cannot be acted on."""
    win, obj = ethane
    vp = win.viewport
    said = []
    vp.status_message.connect(said.append)
    vp.set_selection([(obj.id, i) for i in range(obj.structure.n_atoms)])
    vp.start_twist()
    assert vp._internal is None
    assert said and "terminal group" in said[-1]


def test_the_twist_is_offered_in_the_context_menu(ethane):
    win, obj = ethane
    vp = win.viewport
    vp.set_selection([(obj.id, 2), (obj.id, 3)])
    keys = [k for k, _label, _tip in vp.context_entries()]
    # Two atoms: the bond-length edit comes first (it is chosen by the pick
    # COUNT and is the more specific answer), the rotor under it.
    assert keys[0] == "internal:" + internal.DISTANCE
    assert keys[1] == "internal:" + internal.TWIST


def test_the_twist_key_does_not_clash(win):
    assert win.ops.duplicate_keys() == {}
    assert win.ops.get("twist_bond").key == "T"


def test_the_twist_is_one_undo_step(ethane):
    from PySide6.QtCore import QPointF, Qt
    win, obj = ethane
    vp = win.viewport
    before = obj.structure.coords.copy()
    vp.set_selection([(obj.id, 2)])
    win.run_op("twist_bond")
    vp._internal["state"].add_delta(75.0)
    vp._apply_internal()
    _press(vp, QPointF(10.0, 10.0), Qt.LeftButton)
    win.on_undo()
    assert np.allclose(win.scene.get(obj.id).structure.coords, before)
