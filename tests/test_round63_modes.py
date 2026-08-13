"""Round 63: rank modes by a viewport selection, plus the halo and the icon.

Roadmap item 1g, asked for 2026-08-03 and built 2026-08-12: "allow the user to
make a selection in the viewport of certain atoms whose vibrations they are
interested in and calculate their offset during different modes, use that as a
ranking parameter".

Also: "is the halo effect intended to have these multiple distinct rings?" (no)
and a `.molom` file icon for Explorer.
"""

import os

import numpy as np
import pytest

from molom.core import vibrations as vib

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
FREQ = os.path.join(DATA, "orca_freq_h3po4.out")


@pytest.fixture
def win():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.app import MainWindow
    QApplication.instance() or QApplication([])
    return MainWindow()


@pytest.fixture
def h3po4():
    """The real ORCA job — never a fixture written from memory (CLAUDE.md)."""
    text = open(FREQ, encoding="utf-8", errors="ignore").read()
    symbols = [row[0] for row in vib.parse_orca_geometry(text)]
    modes = vib.parse_orca_frequencies(text, n_atoms=len(symbols))
    return symbols, [m for m in modes if not m.is_trivial]


def _indices(symbols, element):
    return [i for i, s in enumerate(symbols) if s == element]


# ------------------------------------------------------- the measure itself
def test_the_weight_is_a_fraction():
    mode = vib.Mode(0, 1000.0, [[1.0, 0, 0], [0, 1.0, 0], [0, 0, 1.0]])
    for rows in ([0], [1], [0, 1], [0, 1, 2]):
        w = vib.selection_weight(mode, rows, ["C", "C", "C"])
        assert 0.0 <= w <= 1.0


def test_selecting_everything_is_all_of_the_motion():
    mode = vib.Mode(0, 1000.0, [[0.3, 0, 0], [0, 0.7, 0], [0, 0, 0.1]])
    w = vib.selection_weight(mode, [0, 1, 2], ["C", "O", "H"])
    assert w == pytest.approx(1.0)


def test_selecting_nothing_is_none_of_it():
    mode = vib.Mode(0, 1000.0, [[1.0, 0, 0], [0, 1.0, 0]])
    assert vib.selection_weight(mode, [], ["C", "C"]) == 0.0
    assert vib.selection_weight(mode, None, ["C", "C"]) == 0.0


def test_the_shares_of_disjoint_groups_add_up():
    """It is a participation RATIO, so the parts must sum to the whole."""
    mode = vib.Mode(0, 1000.0, [[0.4, 0, 0], [0, 0.9, 0], [0, 0, 0.2]])
    syms = ["C", "O", "H"]
    a = vib.selection_weight(mode, [0], syms)
    b = vib.selection_weight(mode, [1, 2], syms)
    assert a + b == pytest.approx(1.0)


def test_out_of_range_indices_are_ignored_not_crashed_on():
    mode = vib.Mode(0, 1000.0, [[1.0, 0, 0], [0, 1.0, 0]])
    assert vib.selection_weight(mode, [0, 99], ["C", "C"]) == pytest.approx(0.5)


def test_a_ratio_not_a_raw_amplitude():
    """A raw sum would rank every big mode above a genuinely localised one —
    the opposite of the question being asked."""
    small = vib.Mode(0, 100.0, [[0.10, 0, 0], [0.0, 0, 0]])   # all on atom 0
    big = vib.Mode(1, 200.0, [[1.00, 0, 0], [1.0, 0, 0]])     # shared
    syms = ["C", "C"]
    assert vib.selection_weight(small, [0], syms) == pytest.approx(1.0)
    assert vib.selection_weight(big, [0], syms) == pytest.approx(0.5)
    ranked = vib.rank_by_selection([small, big], [0], syms)
    assert ranked[0][0] is small, "the localised mode must win"


# ------------------------------------------------------- mass weighting
def test_mass_weighting_stops_hydrogens_dominating(h3po4):
    """An eigenvector is a CARTESIAN displacement, so a heavy atom's share is
    understated unless it is weighted by mass."""
    symbols, modes = h3po4
    phosphorus = _indices(symbols, "P")
    plain = max(vib.selection_weight(m, phosphorus, symbols, False)
                for m in modes)
    weighted = max(vib.selection_weight(m, phosphorus, symbols, True)
                   for m in modes)
    assert weighted > plain


def test_the_chemistry_comes_out_right(h3po4):
    """The real check: does it name the bands a chemist would name?"""
    symbols, modes = h3po4
    top_h = vib.rank_by_selection(modes, _indices(symbols, "H"), symbols)[0]
    # The hydrogens' own modes are the O-H stretches, up near 3800 cm-1.
    assert top_h[0].wavenumber > 3000.0
    assert top_h[1] > 0.8
    top_p = vib.rank_by_selection(modes, _indices(symbols, "P"), symbols)[0]
    # Phosphorus moves most in the P=O stretch, around 1350 cm-1 on this job.
    assert 1200.0 < top_p[0].wavenumber < 1500.0


# --------------------------------------------------------------- sorting
def test_sort_by_selection_is_most_involved_first(h3po4):
    symbols, modes = h3po4
    rows = _indices(symbols, "H")
    ordered = vib.sort_modes(modes, vib.SORT_SELECTION, selection=rows,
                             symbols=symbols)
    weights = [vib.selection_weight(m, rows, symbols) for m in ordered]
    assert weights == sorted(weights, reverse=True)


def test_sorting_by_selection_with_nothing_selected_falls_back(h3po4):
    """There is no question to answer yet, so an arbitrary order would be
    worse than the spectrum."""
    symbols, modes = h3po4
    assert vib.sort_modes(modes, vib.SORT_SELECTION, selection=[]) == \
        vib.sort_modes(modes, vib.SORT_FREQUENCY)


def test_sorting_keeps_every_mode(h3po4):
    symbols, modes = h3po4
    out = vib.sort_modes(modes, vib.SORT_SELECTION,
                         selection=_indices(symbols, "O"), symbols=symbols)
    assert sorted(m.index for m in out) == sorted(m.index for m in modes)


def test_the_new_key_is_registered():
    assert vib.SORT_SELECTION in vib.SORT_KEYS


# ------------------------------------------------------------ the UI wiring
def test_the_page_offers_the_ordering_and_takes_a_selection(win):
    page = win.vibration_page
    data = [page.sort_combo.itemData(i)
            for i in range(page.sort_combo.count())]
    assert vib.SORT_SELECTION in data
    page.set_selection([0, 1], ["C", "H"])
    assert page._selection == [0, 1]


def test_the_mass_tick_shows_only_for_that_ordering(win):
    page = win.vibration_page
    page.sort_combo.setCurrentIndex(
        [page.sort_combo.itemData(i)
         for i in range(page.sort_combo.count())].index(vib.SORT_FREQUENCY))
    assert page.mass_check.isHidden() or not page.mass_check.isVisible()


def test_the_window_pushes_the_selection_for_the_active_molecule(win):
    """Scoped to the active object: a mode belongs to ONE FREQ job, so another
    molecule's indices would mean different atoms here."""
    win.open_path(FREQ)
    obj = win._active_obj()
    win.viewport.set_selection([(obj.id, 0), (obj.id, 1)])
    assert win.vibration_page._selection == [0, 1]
    assert list(win.vibration_page._symbols) == list(obj.structure.symbols)


# ---------------------------------------------------------------- the halo
def test_the_glow_has_no_visible_steps(win):
    """Christian: "is the halo effect intended to have these multiple distinct
    rings?" It was three big shells, so it read as three edges."""
    shells = win.viewport._glow_shells()
    assert len(shells) >= 8, "too few shells still bands"
    alphas = [a for _r, a in shells]
    assert alphas == sorted(alphas, reverse=True), "must fade outward"
    # No single step may dominate — that is what makes an edge visible.
    steps = [alphas[i] - alphas[i + 1] for i in range(len(alphas) - 1)]
    assert max(steps) < 0.5 * alphas[0]


def test_more_shells_smooth_it_rather_than_brighten_it(win):
    """They blend ADDITIVELY, so without the 1/n the halo would blow out as
    soon as the count went up and the knobs could not be tuned apart."""
    vp = win.viewport
    before = sum(a for _r, a in vp._glow_shells())
    vp.GLOW_SHELLS = vp.GLOW_SHELLS * 2
    try:
        after = sum(a for _r, a in vp._glow_shells())
    finally:
        del vp.GLOW_SHELLS
    assert after == pytest.approx(before, rel=0.25)


# ----------------------------------------------------------- the file icon
def test_there_is_an_ico_for_explorer():
    from molom import resources
    path = os.path.join(os.path.dirname(resources.SVG), "molom.ico")
    assert os.path.exists(path)
    assert os.path.getsize(path) > 1000


def test_the_association_script_is_reversible_and_user_scope():
    """It changes the USER's machine, so it is opt-in, undoable, and needs no
    administrator rights."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = os.path.join(root, "tools", "associate_molom_files.ps1")
    assert os.path.exists(script)
    text = open(script, encoding="utf-8").read()
    assert "-Remove" in text and "HKCU" in text
    assert "HKLM" not in text, "must not need administrator rights"
