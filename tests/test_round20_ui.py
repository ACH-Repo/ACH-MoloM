"""Round 20: the edit-mode and status-bar fixes from Christian's session."""

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
    w.show()
    return w


def test_measurement_label_survives_a_status_message(win):
    """`showMessage` hides ordinary status widgets, and picking an atom emits
    one every time — which is why the measurement readout looked dead."""
    win.statusBar().showMessage("something transient", 5000)
    assert win._measure_label.isVisible()


def test_measurement_readout_fills_in_from_a_selection(win):
    obj = win._active_obj()
    win.viewport.set_selection([(obj.id, 0), (obj.id, 1)])
    assert win._measure_label.text().strip() != ""
    assert win._measure_label.isVisible()


def test_emptying_the_edited_molecule_keeps_it(win):
    """Deleting every atom in edit mode used to remove the outliner entry,
    leaving edit mode pointing at nothing — so nothing could be drawn."""
    vp = win.viewport
    vp.toggle_mode(win.active_id)
    obj = win._active_obj()
    vp.select_whole_molecules([obj.id])
    win.on_delete_selected()
    assert win.scene.n_objects == 1
    assert win._active_obj().structure.n_atoms == 0
    assert vp.mode == "edit"
    assert vp.edit_obj_id is not None


def test_emptying_in_object_mode_still_removes_it(win):
    vp = win.viewport
    obj = win._active_obj()
    vp.select_whole_molecules([obj.id])
    win.on_delete_selected()
    assert win.scene.n_objects == 0


def test_element_typing_is_gone(win):
    """Elements are picked from the chart now; edit mode no longer swallows
    letters, which is what made Ge/Fe/Be/He awkward."""
    assert not hasattr(win.viewport, "_element_buffer")


def test_letters_reach_their_hotkeys_in_edit_mode(win):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    vp = win.viewport
    vp.toggle_mode(win.active_id)
    vp.setFocus()
    # The offscreen window needs one event cycle before shortcuts deliver.
    QApplication.processEvents()
    fired = []
    win.run_op = lambda op_id: fired.append(op_id)
    QTest.keyClick(vp, Qt.Key_E, Qt.NoModifier)
    QApplication.processEvents()
    assert fired == ["toggle_draw"]


def test_meta_atom_arms_without_any_selection(win):
    from molom.core import meta as meta_mod
    vp = win.viewport
    vp.set_selection([])
    vp.set_meta_template(meta_mod.MetaAtom("octahedral", 2.1, "Fe"))
    assert vp.draw_element == meta_mod.META_SYMBOL
    assert vp.meta_template is not None


def test_picking_a_real_element_disarms_the_meta_template(win):
    from molom.core import meta as meta_mod
    vp = win.viewport
    vp.set_meta_template(meta_mod.MetaAtom("octahedral", 2.1, "Fe"))
    vp.apply_element("C")
    assert vp.meta_template is None
    assert vp.draw_element == "C"


def test_meta_button_reports_what_is_armed(win):
    win.ptable.set_meta_label("Fe", "trigonal_bipyramidal")
    text = win.ptable.meta_button.text()
    assert "Meta:" in text and "Fe" in text and "trigonal bipyramidal" in text


def test_settings_dialog_is_modeless(win):
    """It live-applies sliders, so being locked out of the viewport and the
    outliner while judging a sphere size was backwards."""
    win.on_settings()
    dlg = win._settings_dlg
    assert dlg is not None
    assert not dlg.isModal()
    assert win.properties.isEnabled()
    dlg.reject()
    assert win._settings_dlg is None
