"""Round 21: measure tool, outliner columns, panel Tab, crystal page, meta dressing."""

import os

import numpy as np
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


# ------------------------------------------------------------- measure tool
def test_measure_button_actually_arms_the_tool(win):
    """It used to only print a hint, so clicking it did nothing at all."""
    assert not win.viewport.measure_active
    win._on_tool_clicked("measure")
    assert win.viewport.measure_active
    assert win.toolbar.buttons["measure"].isChecked()


def test_measure_reports_distance_angle_and_dihedral(win):
    vp = win.viewport
    obj = win._active_obj()
    win._on_tool_clicked("measure")
    vp._measure_picks = [(obj.id, 0), (obj.id, 1)]
    assert "d(" in vp.measure_text() and " A" in vp.measure_text()
    vp._measure_picks.append((obj.id, 2))
    assert "angle(" in vp.measure_text()
    vp._measure_picks.append((obj.id, 3))
    assert "dihedral(" in vp.measure_text()


def test_measuring_never_disturbs_the_selection(win):
    vp = win.viewport
    obj = win._active_obj()
    vp.set_selection([(obj.id, 5)])
    win._on_tool_clicked("measure")
    vp._measure_picks = [(obj.id, 0), (obj.id, 1)]
    assert vp.selection == [(obj.id, 5)]


def test_escape_finishes_the_measurement(win):
    vp = win.viewport
    win._on_tool_clicked("measure")
    obj = win._active_obj()
    vp._measure_picks = [(obj.id, 0)]
    assert vp.cancel_modes()
    assert not vp.measure_active
    assert vp._measure_picks == []


def test_arming_draw_disarms_measure_and_back(win):
    vp = win.viewport
    vp.toggle_mode(win.active_id)
    win._on_tool_clicked("measure")
    assert vp.measure_active
    win._on_tool_clicked("draw")
    assert not vp.measure_active


# ------------------------------------------------------------ outliner width
def test_name_column_stretches_so_style_stays_reachable(win):
    """All three columns were fixed pixel widths totalling 290, so a narrower
    dock hid the Style column behind a horizontal scrollbar."""
    from PySide6.QtWidgets import QHeaderView
    head = win.outliner.tree.header()
    assert head.sectionResizeMode(0) == QHeaderView.Stretch
    assert head.sectionResizeMode(2) == QHeaderView.Fixed


def test_style_column_survives_a_narrow_dock(win):
    from PySide6.QtWidgets import QApplication
    win.outliner.tree.resize(180, 300)
    QApplication.processEvents()
    head = win.outliner.tree.header()
    # every column still inside the viewport width => nothing is unreachable
    total = sum(head.sectionSize(i) for i in range(3))
    assert total <= win.outliner.tree.viewport().width() + 2


# ------------------------------------------------------------------ panel Tab
def test_tab_walks_fields_in_the_properties_dock(win):
    """Tab in the array modifier's spin boxes jumped into edit mode instead
    of moving to the next number."""
    from PySide6.QtWidgets import QApplication, QSpinBox
    win.properties.setVisible(True)
    win.properties.show_page("crystal")
    QApplication.processEvents()
    box = win.crystal_page.na
    box.setFocus()
    QApplication.processEvents()
    if QApplication.focusWidget() is not box:
        pytest.skip("offscreen platform would not focus the spin box")
    before = win.viewport.mode
    win.on_tab_pressed()
    assert win.viewport.mode == before, "Tab must not toggle mode from a panel"


def test_tab_still_toggles_mode_from_the_viewport(win):
    from PySide6.QtWidgets import QApplication
    win.viewport.setFocus()
    QApplication.processEvents()
    before = win.viewport.mode
    win.on_tab_pressed()
    assert win.viewport.mode != before


# --------------------------------------------------------------- crystal page
def test_crystal_page_is_disabled_without_a_cell(win):
    win._sync_crystal_page()
    assert not win.crystal_page.asym_radio.isEnabled()


def test_crystal_page_switches_the_view(tmp_path, win):
    from PySide6.QtWidgets import QApplication
    from tests.test_round18_cif import NACL_CIF
    path = tmp_path / "nacl.cif"
    path.write_text(NACL_CIF, encoding="utf-8")
    win.open_path(str(path))
    win._sync_crystal_page()
    page = win.crystal_page
    assert page.asym_radio.isEnabled()
    assert win._active_obj().structure.n_atoms == 8      # full cell
    page.asym_radio.setChecked(True)
    page._apply()
    QApplication.processEvents()
    assert win._active_obj().structure.n_atoms == 2      # asymmetric unit
    page.pack_radio.setChecked(True)
    page.na.setValue(2), page.nb.setValue(1), page.nc.setValue(1)
    page._apply()
    QApplication.processEvents()
    assert win._active_obj().structure.n_atoms == 16


def test_cell_box_checkbox_drives_the_viewport(win):
    win.crystal_page.box_check.setChecked(False)
    assert not win.viewport.show_cell
    win.crystal_page.box_check.setChecked(True)
    assert win.viewport.show_cell


# ----------------------------------------------------------- meta atom dressing
@pytest.mark.parametrize("geometry,n", [
    ("tetrahedral", 4), ("octahedral", 6), ("square_planar", 4),
    ("trigonal_bipyramidal", 5), ("linear", 2),
])
def test_a_meta_atom_is_dressed_to_show_its_geometry(geometry, n):
    """A bare dummy shows nothing of the shape it enforces, so people
    free-draw a coordination number it was never meant for."""
    from molom.core import meta as meta_mod
    from molom.core.structure import Structure
    s = Structure.from_atoms([("Zn", 0.0, 0.0, 0.0)])
    m = meta_mod.MetaAtom(geometry, 2.0, "Fe")
    meta_mod.set_meta(s, 0, m)
    assert meta_mod.dress_with_hydrogens(s, 0, m) == n
    assert s.n_atoms == n + 1
    assert len(s.bonded_neighbors(0)) == n
    for j in range(1, s.n_atoms):
        assert np.linalg.norm(s.coords[j] - s.coords[0]) == pytest.approx(2.0)


def test_dressing_only_fills_the_free_slots():
    from molom.core import meta as meta_mod
    from molom.core.structure import Structure
    s = Structure.from_atoms([("Zn", 0.0, 0.0, 0.0), ("N", 2.0, 0.0, 0.0)])
    s.bonds.append((0, 1, 1))
    m = meta_mod.MetaAtom("octahedral", 2.0)
    meta_mod.set_meta(s, 0, m)
    assert meta_mod.dress_with_hydrogens(s, 0, m) == 5      # 6 - 1 existing
    assert s.n_atoms == 7


def test_dressing_a_full_centre_adds_nothing():
    from molom.core import meta as meta_mod
    from molom.core.structure import Structure
    s = Structure.from_atoms([("Zn", 0.0, 0.0, 0.0)])
    m = meta_mod.MetaAtom("linear", 2.0)
    meta_mod.set_meta(s, 0, m)
    meta_mod.dress_with_hydrogens(s, 0, m)
    assert meta_mod.dress_with_hydrogens(s, 0, m) == 0
