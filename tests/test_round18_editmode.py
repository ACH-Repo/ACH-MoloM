"""Round 18: edit-mode paper cuts Christian reported from the desktop.

Needs a QApplication (widgets + font metrics) but no display.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def win():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.app import MainWindow
    QApplication.instance() or QApplication([])
    w = MainWindow()
    w.load_default_scene()
    # Shown (offscreen) because isVisible() on a child is False while the
    # top-level window is hidden, whatever the child's own flag says.
    w.show()
    return w


def test_alt_a_is_not_stolen_by_a_menu_mnemonic(win):
    """A menu-bar mnemonic is a shortcut too, so "&App" made Alt+A ambiguous
    with deselect-all and Qt fired NEITHER."""
    assert win._check_menu_mnemonics() == {}


def test_no_menu_mnemonic_shadows_any_operator_key(win):
    clashes = win._check_menu_mnemonics()
    assert clashes == {}, "menu mnemonics shadowing operator keys: {}".format(
        clashes)


def test_leaving_edit_mode_disarms_the_draw_tool(win):
    """The flag used to survive into object mode, where the toolbar reports
    "select" — so Tabbing back in came up armed and the periodic table
    stayed hidden ("sometimes the periodic table doesn't show")."""
    vp = win.viewport
    vp.toggle_mode(win.active_id)
    vp.set_draw_tool(True)
    assert vp.draw_tool_active
    vp.toggle_mode()                       # -> object mode
    assert not vp.draw_tool_active
    vp.toggle_mode(win.active_id)          # -> back into edit
    assert not vp.draw_tool_active
    assert win.ptable.isVisible()


def test_periodic_table_follows_mode_and_draw_tool(win):
    vp = win.viewport
    assert not win.ptable.isVisible()       # object mode
    vp.toggle_mode(win.active_id)
    assert win.ptable.isVisible()           # plain edit mode
    vp.set_draw_tool(True)
    assert not win.ptable.isVisible()       # armed: chart would be in the way
    vp.set_draw_tool(False)
    assert win.ptable.isVisible()


def test_converting_an_element_clears_the_selection(win):
    """Otherwise the next pick from the periodic table converts the atom you
    just made, instead of only setting what the NEXT atom will be."""
    vp = win.viewport
    vp.toggle_mode(win.active_id)
    obj = win.scene.get(win.active_id)
    vp.set_selection([(obj.id, 0)])
    vp.apply_element("N")
    assert obj.structure.symbols[0] == "N"
    assert vp.selection == []


def test_drawing_an_atom_leaves_nothing_selected(win):
    vp = win.viewport
    vp.toggle_mode(win.active_id)
    obj = win.scene.get(win.active_id)
    before = obj.structure.n_atoms
    vp.set_draw_tool(True)
    vp._start_draw_drag(0, _pos(vp, 200.0, 200.0))
    assert vp.selection, "the drag itself selects the growing atom"
    vp._finish_draw_drag()
    assert obj.structure.n_atoms > before
    assert vp.selection == []


def test_overlays_start_below_the_edit_header_band(win):
    """The tool column at y = 8 sat ON TOP of "EDIT | name | draw: X", which
    reads as the header being clipped."""
    from molom.ui.app import _VIEWPORT_HEADER_H
    assert win.toolbar.y() >= _VIEWPORT_HEADER_H
    win.viewport.toggle_mode(win.active_id)
    assert win.ptable.y() >= _VIEWPORT_HEADER_H
    # ...and the chart sits clear of the tool column, not over it.
    assert win.ptable.x() >= win.toolbar.x() + win.toolbar.width()


def _pos(widget, x, y):
    from PySide6.QtCore import QPointF
    return QPointF(x, y)
