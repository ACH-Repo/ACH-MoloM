"""Round 90c: the selection outline came back on double and triple bonds.

Christian: "orange highlight outline does no longer show on double and triple
bonds. Some kind of regression happened."

It had, and it was round 35's. `_selection_hull` drew ONE cylinder on the bond
AXIS, which is right only for a single bond: a double is drawn as two
cylinders offset by +-1.0*r at radius 1.3*r, so the pair OVERLAPS the axis and
swallows an axis cylinder of radius r + width whole. That was survivable while
the outline was five times fatter; round 35 divided `_OUTLINE_WIDTH_FRAC` by
five (rightly - the outline was merging cubane's carbons into one blob) and
the hull sank inside the bond it was outlining.

The fix is the rule this project keeps reaching for: draw the outline from the
SAME decomposition the scene draws, so the two cannot diverge again.
"""
import numpy as np
import pytest

from molom.core import style as style_mod
from molom.core.structure import Structure


@pytest.fixture
def viewport():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from molom.ui.app import MainWindow
    return MainWindow()


def _molecule(order):
    """Two carbons joined by one bond of the given order, plus a hydrogen so
    there is something the bond is not."""
    s = Structure.from_atoms([("C", 0.0, 0.0, 0.0), ("C", 1.4, 0.0, 0.0),
                              ("H", -0.6, 0.9, 0.0)], name="probe")
    s.bonds = [(0, 1, order), (0, 2, 1)]
    return s


def _hull_for(win, order):
    obj = win.scene.add(_molecule(order))
    win.active_id = obj.id
    win.viewport.set_selection([(obj.id, 0), (obj.id, 1)])
    return win.viewport._selection_hull()


def test_a_double_bond_gets_an_outline_at_all(viewport):
    """The report, as an assertion. One cylinder is not enough for a bond
    drawn as two."""
    _spheres, cylinders = _hull_for(viewport, 2)
    assert len(cylinders) == 2


def test_a_triple_bond_gets_all_three(viewport):
    _spheres, cylinders = _hull_for(viewport, 3)
    assert len(cylinders) == 3


def test_a_single_bond_is_unchanged(viewport):
    _spheres, cylinders = _hull_for(viewport, 1)
    assert len(cylinders) == 1


def test_the_hull_matches_the_DRAWN_geometry_cylinder_for_cylinder(viewport):
    """The invariant that stops this recurring: the outline is the scene's own
    `bond_cylinders` decomposition, each one fattened by the outline width.
    Anything else is a second implementation of the multi-bond layout waiting
    to fall out of step with the first."""
    win = viewport
    obj = win.scene.add(_molecule(2))
    win.active_id = obj.id
    win.viewport.set_selection([(obj.id, 0), (obj.id, 1)])
    _s, cylinders = win.viewport._selection_hull()
    st = win.viewport._object_style(obj)
    xyz = obj.display_coords()
    drawn = style_mod.bond_cylinders(
        xyz[0], xyz[1], 2, bond_radius=st.bond_radius,
        show_multiple=st.show_multiple_bonds)
    width = win.viewport.outline_width()
    assert len(cylinders) == len(drawn)
    for (ha, hb, hr), (da, db, dr) in zip(cylinders, drawn):
        assert np.allclose(ha, da) and np.allclose(hb, db)
        assert hr == pytest.approx(dr + width)


def test_the_outline_pokes_OUT_of_the_bond_it_outlines(viewport):
    """Which is what makes it visible. Before the fix the hull's radius was
    `bond_radius + width` on the AXIS, while a double bond's own cylinders
    reach 2.3x that far from it - so the outline was strictly inside the
    geometry it was supposed to ring."""
    win = viewport
    obj = win.scene.add(_molecule(2))
    win.active_id = obj.id
    win.viewport.set_selection([(obj.id, 0), (obj.id, 1)])
    _s, cylinders = win.viewport._selection_hull()
    st = win.viewport._object_style(obj)
    drawn_radius = st.bond_radius * style_mod.DOUBLE_BOND_RADIUS_FACTOR
    assert all(r > drawn_radius for _a, _b, r in cylinders)
    # ...and the OLD behaviour would not have.
    old_style_radius = st.bond_radius + win.viewport.outline_width()
    assert old_style_radius < drawn_radius, (
        "the regression only bites while the outline is thinner than the "
        "multi-bond radius factor; if that stops being true, so does the test")
