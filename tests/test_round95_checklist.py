"""Round 95: Christian's checklist against round 93.

Three complaints, and two of them are the same bug wearing different clothes:
a ❖ control that fans out over the selection put the ACTIVE object back
BEFORE re-selecting, and `select_whole_molecules` then moved it to the last
crystal in the list. So the page came back describing a structure the user had
not chosen, its ticks read that structure's state, and if that structure
happened to be the edited P1 one the whole page greyed.
"""
import pytest

from tests.test_round91_multi_crystal import _crystal, _select_everything


@pytest.fixture
def bench():
    """Four crystals and a plain molecule, as his savefile has."""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from molom.core import build as build_mod
    from molom.ui.app import MainWindow

    win = MainWindow()
    crystals = [_crystal(win, "LiF"), _crystal(win, "NaF"),
                _crystal(win, "KF"), _crystal(win, "CsF")]
    molecule = win.scene.add(build_mod.cubane())
    molecule.name = "cubane"
    win.properties.setVisible(True)
    win.active_id = crystals[0].id
    return win, crystals, molecule


# ------------------------------------- 3: the tick appeared to turn itself on
def test_a_fan_out_leaves_the_active_object_where_it_was(bench):
    """Christian: "the active structure turned on Draw atoms outside the cell
    boundary for some reason when switching back."

    It did not: the ACTIVE object moved. `select_whole_molecules` emits
    `selection_changed`, picking moves the active object to the last thing
    selected, and the restore ran BEFORE it - so after any fan-out the page
    described the last crystal in the list and read ITS tick back.
    """
    win, crystals, _mol = bench
    _select_everything(win)
    win.active_id = crystals[0].id            # LiF is the one being looked at
    win._sync_crystal_page()
    win.crystal_page.outside_check.setChecked(False)
    assert win.active_id == crystals[0].id
    assert win.crystal_page.outside_check.isChecked() is False
    win._on_crystal_view_chosen("asym")
    assert win.active_id == crystals[0].id
    assert win.crystal_page.outside_check.isChecked() is False


def test_the_tick_still_reaches_every_selected_crystal(bench):
    """Putting the active object back later must not undo round 91b."""
    win, crystals, _mol = bench
    _select_everything(win)
    win.active_id = crystals[0].id
    win.crystal_page.outside_check.setChecked(False)
    assert all(c.structure.metadata.get("pack_outside") is False
               for c in crystals)


# ---------------------------------- 4: one edited cell greyed the whole page
def test_one_frozen_crystal_does_not_grey_the_other_four(bench):
    """Christian: "if the P1 CsF is selected, the message that an edit has
    been made pops up and you have to deselect it to use controls on the
    other four again."

    An edited cell cannot be regenerated and is passed over - which is the
    same rule `_crystal_targets` already applies to a molecule. It is not a
    reason to disable a switch that would work perfectly well on the rest.
    """
    win, crystals, _mol = bench
    crystals[-1].structure.metadata["cell_frozen"] = True
    _select_everything(win)
    # CsF is the ACTIVE one - which is what a click on it, or (before this
    # round) any fan-out, left behind.
    win.active_id = crystals[-1].id
    win._sync_crystal_page()
    assert win._crystal_subject() is crystals[-1]
    assert win.crystal_page.cell_radio.isEnabled()
    assert not win.crystal_page._frozen


def test_a_frozen_crystal_ON_ITS_OWN_still_greys(bench):
    """The greying is right when it is the only thing the controls reach:
    there is nothing left for them to regenerate."""
    win, crystals, _mol = bench
    crystals[-1].structure.metadata["cell_frozen"] = True
    win.viewport.set_selection([(crystals[-1].id, 0)])
    win.active_id = crystals[-1].id
    win._sync_crystal_page()
    assert not win.crystal_page.cell_radio.isEnabled()
    assert "edited" in win.crystal_page.cell_radio.toolTip()


def test_the_fan_out_reports_once_and_counts_the_frozen_ones(bench):
    """Each frozen target posts its own "was edited in the full cell" line on
    the way past, and the last one to speak wins - so a single edited cell
    made the click look as though it had done nothing but complain."""
    win, crystals, _mol = bench
    crystals[-1].structure.metadata["cell_frozen"] = True
    _select_everything(win)
    win.active_id = crystals[0].id
    win._on_crystal_view_chosen("asym")
    message = win.statusBar().currentMessage()
    assert "4 crystals" in message and "asymmetric unit only" in message
    assert "1 edited into P1" in message


def test_picking_a_molecule_ON_ITS_OWN_describes_that_molecule(bench):
    """Round 93's fallback is for a crystal swept up by Ctrl+A, and with
    nothing else selected it correctly finds nothing - so the page greys and
    names the molecule. Pinned because the half of Christian's report that
    WAS broken (the page not noticing a selection change at all) is fixed by
    re-syncing, and a fix there must not start describing the wrong crystal
    here."""
    win, crystals, molecule = bench
    win.viewport.set_selection([(molecule.id, 0)])
    win.active_id = molecule.id
    win._sync_crystal_page()
    assert win._crystal_subject() is molecule
    assert not win.crystal_page._has_cell
    assert "cubane" in win.crystal_page.summary.text()


def test_a_select_all_still_falls_back_to_a_crystal(bench):
    """Round 93's case is untouched: the molecule is the active object only
    because it happened to be picked last."""
    win, crystals, molecule = bench
    _select_everything(win)
    win.active_id = molecule.id
    assert win._crystal_subject() in crystals
    win._sync_crystal_page()
    assert win.crystal_page._has_cell


def test_the_page_follows_a_selection_that_leaves_the_active_object_alone(
        bench):
    """The ❖ page describes `_crystal_subject()`, which depends on the
    SELECTION and not only on the active object - so it went stale on a
    selection change that did not move the active object, and a page naming
    one crystal while its controls reach another is the whole complaint."""
    win, crystals, molecule = bench
    _select_everything(win)
    win.active_id = molecule.id
    win._sync_crystal_page()
    assert win.crystal_page._has_cell, "a crystal is in the selection"
    win.viewport.set_selection([(molecule.id, 0)])
    assert not win.crystal_page._has_cell, "the page has to follow"


def test_the_cell_box_tick_is_read_back_from_the_crystal(bench):
    """Round 93 made the box per crystal and left the page's tick reading
    whichever crystal was looked at last - round 51's bug, one control on."""
    win, crystals, _mol = bench
    crystals[0].structure.metadata["show_cell"] = False
    win.viewport.set_selection([(crystals[0].id, 0)])
    win.active_id = crystals[0].id
    win._sync_crystal_page()
    assert not win.crystal_page.box_check.isChecked()
    win.viewport.set_selection([(crystals[1].id, 0)])
    win.active_id = crystals[1].id
    win._sync_crystal_page()
    assert win.crystal_page.box_check.isChecked(), "absent means SHOWN"


# ------------------------------------------- 5: the search table's own width
@pytest.fixture
def table():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from molom.core import cifsearch
    from molom.ui.dialogs import CifSearchDialog

    names = ["Luciferin 6'-ethyl ether sodium salt monohydrate, a very long "
             "entry name indeed", "Quartz", "Griceite"]
    hits = [cifsearch.Hit(source=cifsearch.SOURCE_COD, ref=str(900 + i),
                          formula="C{}H{}O{}".format(i + 4, i + 6, i + 2),
                          name=name, spacegroup="P 21/c", year=2001 + i)
            for i, name in enumerate(names)]
    dlg = CifSearchDialog(None)
    dlg.resize(820, 470)
    dlg.hits = hits
    dlg.show()
    app.processEvents()
    return dlg, app


def test_the_bulk_resize_really_does_ignore_the_stretch_mode(table):
    """The measurement behind the fix, rather than an argument about Qt.

    `QTableView.resizeColumnsToContents` calls `resizeSections
    (ResizeToContents)`, which by documented design ignores the per-section
    resize mode - so it fits the STRETCH column to its longest entry too.
    Measured here: a long name takes it to 1771 px inside a 796 px viewport,
    which is the "full width used" half of what Christian saw. A relayout
    then snaps it back, which is the other half.
    """
    dlg, _app = table
    t = dlg.table
    before = t.columnWidth(dlg.COL_NAME)
    t.resizeColumnsToContents()
    assert t.columnWidth(dlg.COL_NAME) > t.viewport().width()
    t.refill()
    assert t.columnWidth(dlg.COL_NAME) == before


def test_refill_never_calls_the_bulk_resize(table):
    """So the flip cannot happen at all. `refill` runs on every sort and on
    every batch a provider lands, which is how often it used to happen."""
    dlg, app = table
    calls = []
    dlg.table.resizeColumnsToContents = lambda *a: calls.append(1)
    dlg.table.append_results(list(dlg.hits))
    dlg.table._sort_by(dlg.COL_YEAR)
    app.processEvents()
    assert calls == []


def test_the_columns_do_not_move_when_more_results_arrive(table):
    dlg, app = table
    before = [dlg.table.columnWidth(c) for c in range(dlg.table.columnCount())]
    dlg.table.append_results(list(dlg.hits))
    app.processEvents()
    after = [dlg.table.columnWidth(c) for c in range(dlg.table.columnCount())]
    assert before == after


def test_the_table_never_needs_a_horizontal_scrollbar(table):
    """The columns add up to the viewport, which is what the stretch column
    is for - and what a name fitted to its own length destroys."""
    dlg, _app = table
    total = sum(dlg.table.columnWidth(c)
                for c in range(dlg.table.columnCount()))
    assert total == dlg.table.viewport().width()


def test_a_long_name_wraps_instead_of_stretching_the_column(table):
    """Eliding would hide the half that tells two entries of one compound
    apart, which is what this list exists to show."""
    dlg, _app = table
    heights = [dlg.table.rowHeight(r) for r in range(dlg.table.rowCount())]
    assert heights[0] > heights[1], "the long name takes more than one line"


def test_sorting_still_does_not_resize_anything(table):
    """Round 93's fix, which this round must not undo."""
    dlg, app = table
    before = [dlg.table.columnWidth(c) for c in range(dlg.table.columnCount())]
    dlg.table._sort_by(dlg.COL_YEAR)
    app.processEvents()
    assert [dlg.table.columnWidth(c)
            for c in range(dlg.table.columnCount())] == before


def test_double_clicking_the_stretch_column_border_is_a_no_op(table):
    """It already occupies every pixel the others leave, so fitting it to its
    contents would take it out of Stretch until the next relayout snapped it
    back - which is the flicker."""
    dlg, app = table
    before = dlg.table.columnWidth(dlg.COL_NAME)
    dlg.table._fit_column(dlg.COL_NAME)
    app.processEvents()
    assert dlg.table.columnWidth(dlg.COL_NAME) == before


def test_a_fixed_column_border_still_fits_to_contents(table):
    """Excel's gesture, untouched for the columns it means something for."""
    dlg, app = table
    dlg.table.setColumnWidth(dlg.COL_FORMULA, 400)
    dlg.table._fit_column(dlg.COL_FORMULA)
    app.processEvents()
    assert dlg.table.columnWidth(dlg.COL_FORMULA) < 400


def test_the_rows_alternate_shade(table):
    """Christian: "do the alternating shades of grey to highlight bordering
    row contrast. I think we do that in the animation player already." """
    from molom.ui import search_table
    dlg, _app = table
    assert dlg.table.alternatingRowColors()
    from PySide6.QtGui import QPalette
    pal = dlg.table.palette()
    assert pal.color(QPalette.Base) == search_table.ROW_BG
    assert pal.color(QPalette.AlternateBase) == search_table.ROW_ALT
    assert search_table.ROW_BG != search_table.ROW_ALT
