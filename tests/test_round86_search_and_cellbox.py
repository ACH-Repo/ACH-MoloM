"""Round 86: the crystal search remembers and sorts, and the unit-cell box
can stop being painted on top of everything.

The search half is `docs/OPEN_ITEMS.md` section I, which is Christian's own
list after using round 85: "only thing it really needs is to remember the
results of the last search and sorting via clicking on the headers (like by
temperature and year, ascending and descending)."

The cell-box half is his report of 2026-08-25: "the unit cell axes are always
rendered on top in normal image exports and in the viewport. I think it
shouldn't be. At least never in png exports."
"""
import time

import numpy as np
import pytest

from molom.core import cellbox, cif
from molom.core.cifsearch import Hit


@pytest.fixture
def dialog():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from molom.ui.dialogs import CifSearchDialog

    def build(hits=(), remembered=None):
        dlg = CifSearchDialog(None, remembered=remembered)
        if hits:
            dlg.hits = list(hits)
            dlg.table.refill()
        return dlg
    return build


def _hits():
    """Deliberately awkward: the two orderings that a LEXICAL sort gets wrong
    (100 before 98) and the blanks COD leaves constantly."""
    spec = [(100, 2008, "a"), (98, 1998, "b"), (293, None, "c"),
            (None, 2015, "d"), (9.5, 1975, "e"), (None, None, "f")]
    return [Hit("cod", str(k), formula="SiO2", name=name,
                temperature=t, year=y)
            for k, (t, y, name) in enumerate(spec)]


def _column(dlg, index):
    return [dlg.table.item(r, index).text()
            for r in range(dlg.table.rowCount())]


# ----------------------------------------------------------------- sorting
def test_temperature_sorts_numerically_not_lexically(dialog):
    """The trap `docs/OPEN_ITEMS.md` warned about before this was written:
    `QTableWidgetItem` compares as TEXT, so a plain `setSortingEnabled(True)`
    puts 100 K before 98 K and makes the column worth sorting by a liar."""
    dlg = dialog(_hits())
    dlg.table._sort_by(dlg.COL_TEMPERATURE)
    values = [v for v in _column(dlg, dlg.COL_TEMPERATURE) if v]
    assert values == ["9.5", "98", "100", "293"]
    assert sorted(values) != values          # i.e. text order really differs


def test_year_sorts_numerically_both_ways(dialog):
    dlg = dialog(_hits())
    dlg.table._sort_by(dlg.COL_YEAR)
    assert [v for v in _column(dlg, dlg.COL_YEAR) if v] == \
        ["1975", "1998", "2008", "2015"]
    dlg.table._sort_by(dlg.COL_YEAR)
    assert [v for v in _column(dlg, dlg.COL_YEAR) if v] == \
        ["2015", "2008", "1998", "1975"]


def test_unknowns_sink_to_the_bottom_whichever_way_the_column_points(dialog):
    """COD leaves temperature and year null constantly, and an unknown
    temperature is NOT 0 K. Reversing must not float the blanks to the top,
    which is what a plain `reverse=True` would do."""
    dlg = dialog(_hits())
    for _ in range(2):                       # ascending, then descending
        dlg.table._sort_by(dlg.COL_TEMPERATURE)
        column = _column(dlg, dlg.COL_TEMPERATURE)
        assert column[-2:] == ["", ""]
        assert all(v for v in column[:-2])


def test_a_third_click_goes_back_to_the_search_ranking(dialog):
    """The ranking is the one thing the search itself is for, so there has to
    be a way back to it - which `setSortingEnabled(True)` cannot give."""
    dlg = dialog(_hits())
    ranked = _column(dlg, dlg.COL_TEMPERATURE)
    dlg.table._sort_by(dlg.COL_TEMPERATURE)
    assert _column(dlg, dlg.COL_TEMPERATURE) != ranked
    dlg.table._sort_by(dlg.COL_TEMPERATURE)
    dlg.table._sort_by(dlg.COL_TEMPERATURE)
    assert _column(dlg, dlg.COL_TEMPERATURE) == ranked
    assert dlg.table._sort_column is None


def test_selecting_a_row_while_sorted_returns_the_right_structure(dialog):
    """`self.hits` stays in rank order and only the VIEW is sorted, so the
    mapping from a table row back to a hit has to go through `_shown`. Getting
    this wrong imports a different crystal from the one that was clicked."""
    dlg = dialog(_hits())
    dlg.table._sort_by(dlg.COL_TEMPERATURE)
    dlg.table._sort_by(dlg.COL_TEMPERATURE)                          # descending: 293 K first
    dlg.table.selectRow(0)
    assert dlg.chosen and dlg.chosen[0].temperature == 293


def test_sorting_by_a_text_column_folds_case(dialog):
    """Otherwise `Quartz` and `quartz` land in different halves of the list."""
    hits = [Hit("cod", "1", name="quartz"), Hit("cod", "2", name="Anatase"),
            Hit("cod", "3", name="Zircon")]
    dlg = dialog(hits)
    dlg.table._sort_by(dlg.COL_NAME)
    assert _column(dlg, dlg.COL_NAME) == ["Anatase", "quartz", "Zircon"]


# --------------------------------------------------------------- remembering
def test_the_last_search_comes_back_without_re_running_it(dialog):
    """Re-running would cost three network round trips to redisplay something
    that was on the screen a moment ago, and would silently change under you
    if a provider answered differently."""
    hits = _hits()
    dlg = dialog(remembered=("quartz", hits, time.time()))
    assert dlg.edit.text() == "quartz"
    assert dlg.table.rowCount() == len(hits)
    assert "last search" in dlg.info.text()
    assert dlg._worker is None               # nothing was fetched


def test_a_stale_result_says_how_old_it_is(dialog):
    """A stale list that looks live is worse than an empty one: a COD entry
    can be superseded between one session and the next."""
    fresh = dialog(remembered=("quartz", _hits(), time.time()))
    old = dialog(remembered=("quartz", _hits(), time.time() - 7200))
    assert "ago" not in fresh.info.text()
    assert "2 hours ago" in old.info.text()


def test_no_memory_opens_empty(dialog):
    dlg = dialog(remembered=None)
    assert dlg.table.rowCount() == 0
    assert dlg.edit.text() == ""
    assert dlg.info.text() == ""


def test_what_is_remembered_round_trips(dialog):
    hits = _hits()
    dlg = dialog(remembered=("benzoic acid", hits, time.time()))
    query, kept, when = dlg.remembered()
    assert query == "benzoic acid"
    assert len(kept) == len(hits)
    assert when > 0


def test_the_memory_lives_on_the_window_not_in_a_module(dialog):
    """Two windows - or the next test - must not inherit somebody else's
    result list. That is the shape of bug this project keeps finding in shared
    state (the round-37 circuit breaker, the round-46 module cache)."""
    pytest.importorskip("PySide6")
    from molom.ui.app import MainWindow
    a, b = MainWindow(), MainWindow()
    assert a._last_cif_search is None and b._last_cif_search is None
    a._last_cif_search = ("quartz", _hits(), time.time())
    assert b._last_cif_search is None


# ------------------------------------------------------------- the cell box
def _cell():
    return cif.Cell(10.0, 7.5, 5.8, 90.0, 121.0, 90.0)


def test_the_box_is_twelve_rods_three_of_them_axis_coloured():
    cell = _cell()
    rods = cellbox.rods(cell, cell.corners())
    assert len(rods) == 12
    coloured = [r for r in rods if tuple(r[2]) in cellbox.AXIS_RGB]
    assert len(coloured) == 3
    assert {tuple(r[2]) for r in coloured} == set(cellbox.AXIS_RGB)


def test_each_edge_is_emitted_exactly_once():
    """The overlay draws all twelve grey and then paints the three coloured
    ones ON TOP of their own grey copies. As geometry that would be twelve
    rods with three more inside them, z-fighting along their whole length."""
    cell = _cell()
    rods = cellbox.rods(cell, cell.corners())
    ends = {(tuple(np.round(p0, 6)), tuple(np.round(p1, 6)))
            for p0, p1, _rgb, _r in rods}
    assert len(ends) == 12


def test_the_rod_radius_is_proportional_to_the_cell():
    """These scenes run from a 3 A cell to a 200 A framework, and one constant
    is either invisible at one end or a girder at the other (round 66)."""
    small = cellbox.radius_for(cif.Cell(3.0, 3.0, 3.0, 90, 90, 90))
    big = cellbox.radius_for(cif.Cell(200.0, 200.0, 200.0, 90, 90, 90))
    assert big > small * 50
    # A 10 A cell lands on the radius the Blender export already defaulted to.
    assert cellbox.radius_for(
        cif.Cell(10.0, 10.0, 10.0, 90, 90, 90)) == pytest.approx(0.04)


def test_the_rods_follow_the_posed_corners_not_the_cells_own_frame():
    """A crystal can be grabbed and turned: the drawn box follows the atoms
    through a Kabsch fit (round 19), so handing the cell's own corners in
    would draw the box where the crystal used to be."""
    cell = _cell()
    corners = np.asarray(cell.corners(), dtype=float)
    moved = corners + np.array([5.0, -2.0, 1.0])
    here = cellbox.rods(cell, corners)
    there = cellbox.rods(cell, moved)
    assert np.allclose(there[0][0] - here[0][0], [5.0, -2.0, 1.0])


def test_no_cell_draws_nothing():
    assert cellbox.rods(None, None) == []
    assert cellbox.rods(_cell(), None) == []


def test_the_two_surfaces_are_switched_separately():
    """The viewport keeps the overlay - an always-visible box is a navigation
    aid - while an EXPORT defaults to real geometry, which is Christian's
    "at least never in png exports"."""
    pytest.importorskip("PySide6")
    from molom.ui.app import MainWindow
    win = MainWindow()
    assert win.viewport.cell_zorder == cellbox.OVERLAY
    assert win.viewport.cell_zorder_export == cellbox.DEPTH
    win.run_op("cell_zorder_view")
    assert win.viewport.cell_zorder == cellbox.DEPTH
    assert win.viewport.cell_zorder_export == cellbox.DEPTH   # untouched
    win.run_op("cell_zorder_export")
    assert win.viewport.cell_zorder_export == cellbox.OVERLAY
    win.run_op("cell_zorder_view")
    assert win.viewport.cell_zorder == cellbox.OVERLAY


def test_the_painted_overlay_is_skipped_when_the_box_is_geometry():
    """Both forms drawing at once would be the worst of the two: a rod with a
    hard-edged line down the middle of it, still painted over everything."""
    import inspect
    from molom.ui import viewport as vp_mod
    for name in ("_paint_overlays", "_paint_export_overlays"):
        source = inspect.getsource(getattr(vp_mod.MolViewport, name))
        assert "_paint_cells" in source
        assert "cellbox_mod.OVERLAY" in source


# ------------------------------------------------------- worker lifetime
@pytest.fixture
def offline_search(monkeypatch):
    """A crystal search that answers at once and never touches the network.

    These tests are about THREAD LIFETIME, not about searching, and round 84's
    rule for this module is that every test is offline. A real query also took
    16 s, which is not a price a lifetime check should make the suite pay.
    """
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from molom.core import cifsearch as cs
    monkeypatch.setattr(cs, "search",
                        lambda *a, **k: cs.Results("SiO2", hits=[]))
    from molom.ui import dialogs
    return dialogs


def test_a_lookup_thread_is_not_a_child_of_its_dialog(offline_search):
    """A QThread parented to the dialog is DESTROYED WITH IT, and destroying a
    running thread is an access violation that takes the whole process down
    with no Python traceback.

    Reachable from the GUI: start a lookup that has to wait out the web
    timeout, press Cancel. It is also what stopped `python -m pytest tests/`
    from finishing - once the suite began tearing its windows down (which it
    must, or it accumulates ~413 widgets per test until it thrashes), one test
    that left a resolve in flight killed the run.
    """
    from PySide6.QtCore import QThread
    dialogs = offline_search
    dlg = dialogs.CifSearchDialog(None)
    dlg.edit.setText("SiO2")
    dlg._start()
    try:
        assert dlg._worker is not None
        assert dlg._worker.parent() is None, "the thread must not be a child"
        assert not dlg.findChildren(QThread),             "destroying the dialog would destroy a running thread"
        # ...and something else has to keep it alive, or Python is free to
        # collect a QThread mid-run (round 76's trap from the other side).
        assert dlg._worker in dialogs._LIVE_WORKERS
    finally:
        dialogs.wait_for_workers()


def test_a_finished_worker_stops_being_held(offline_search):
    """`_LIVE_WORKERS` is a leak if nothing ever leaves it."""
    dialogs = offline_search
    dlg = dialogs.CifSearchDialog(None)
    dlg.edit.setText("SiO2")
    dlg._start()
    worker = dlg._worker
    assert dialogs.wait_for_workers(), "workers did not finish in time"
    assert worker not in dialogs._LIVE_WORKERS


def test_waiting_for_workers_is_safe_with_none_running():
    pytest.importorskip("PySide6")
    from molom.ui import dialogs
    assert dialogs.wait_for_workers() is True
