"""Round 96: Christian's PXRD batch - performance, sources, hkl, navigation.

The window from round 95 was reachable and slow, monochromatic, and navigated
by nothing but a horizontal wheel zoom. This is the pass that makes it a
spectrum window: ORCA Workbench's own key map (its NMR plotter, which is the
most refined thing either program has), a K-alpha doublet, an hkl list with
the systematic absences in it, per-crystal settings off a right-click, and a
painting path that blits instead of rebuilding.
"""
import os
import time

import numpy as np
import pytest

from molom.core import cif as cif_mod
from molom.core import io as io_mod
from molom.core import pxrd
from molom.core.structure import Structure

HERE = os.path.dirname(__file__)
FERROCENE = os.path.join(HERE, "data", "cod_2101932_ferrocene.cif")
SOLID_SOLUTION = os.path.join(HERE, "data", "cod_1547149_solid_solution.cif")

NACL_A = 5.6402
NACL_FRAC = [(0, 0, 0), (0, .5, .5), (.5, 0, .5), (.5, .5, 0),
             (.5, .5, .5), (.5, 0, 0), (0, .5, 0), (0, 0, .5)]
NACL_SYM = ["Na"] * 4 + ["Cl"] * 4


def _nacl(**kw):
    cell = cif_mod.Cell(NACL_A, NACL_A, NACL_A, 90, 90, 90)
    kw.setdefault("two_theta_range", (10, 120))
    return pxrd.compute(cell, NACL_SYM, NACL_FRAC, **kw)


def _open(path, name="crystal"):
    atoms, meta = io_mod.read_structures(path)[0]
    s = Structure.from_atoms(atoms, name=name)
    s.metadata.update(meta or {})
    return s


# ----------------------------------------------------------- the source
def test_a_wavelength_an_energy_and_a_named_line_all_parse():
    """One parser for the presets and for anything typed, which is what lets
    a source that can be chosen also be written down."""
    assert pxrd.parse_source("1.5406") == [(1.5406, 1.0)]
    assert pxrd.parse_source("1.5406 A") == [(1.5406, 1.0)]
    assert pxrd.parse_source("Cu Ka1") == [(pxrd.LINES["Cu"]["Ka1"], 1.0)]
    assert pxrd.parse_source("Mo Ka2") == [(pxrd.LINES["Mo"]["Ka2"], 1.0)]


def test_an_energy_in_keV_is_hc_over_E():
    """A synchrotron user states an energy and never a wavelength."""
    lam = pxrd.parse_source("12 keV")[0][0]
    assert lam == pytest.approx(pxrd.ENERGY_ANGSTROM / 12.0, rel=1e-12)
    # eV as well, because a soft beamline states one and a hard one the other
    # and the factor of a thousand between them is easy to miss.
    assert (pxrd.parse_source("8040 eV")[0][0]
            == pytest.approx(pxrd.ENERGY_ANGSTROM / 8.040, rel=1e-12))
    # And the textbook value the other way round.
    assert pxrd.energy_kev(pxrd.LINES["Cu"]["Ka1"]) == pytest.approx(8.0478,
                                                                     abs=1e-3)


def test_the_doublet_defaults_to_the_standard_two_to_one():
    """K-alpha2 comes at half the intensity of K-alpha1 - a property of the
    ATOM (the 2p level degeneracies), not of the instrument, so it is the
    same 0.5 for every tube."""
    assert pxrd.parse_source("Cu Ka") == [(1.540598, 1.0), (1.544426, 0.5)]
    assert pxrd.parse_source("Cu Ka1+Ka2") == pxrd.parse_source("Cu Ka")
    assert pxrd.parse_source("Cu Ka1+Ka2 2:1") == pxrd.parse_source("Cu Ka")


def test_a_stated_ratio_is_normalised_to_the_first_component():
    assert pxrd.parse_source("Cu Ka1 Cu Ka2 3:1")[1][1] == pytest.approx(1 / 3)
    assert pxrd.parse_source("1.5+1.6 4:1")[1][1] == pytest.approx(0.25)


def test_nonsense_is_refused_and_says_why():
    for bad in ("", "banana", "Ka1", "Cu Ka1+Ka2 2:1:3", "-3", "0 keV"):
        with pytest.raises(pxrd.SourceError):
            pxrd.parse_source(bad)


def test_a_doublet_splits_and_the_split_grows_with_angle():
    """The signature of a real K-alpha doublet, and the reason it is one
    calculation rather than two: |F|^2 is shared because s = 1/(2d) has no
    wavelength in it, so only the ANGLE moves."""
    doublet = _nacl(components=pxrd.parse_source("Cu Ka1+Ka2 2:1"))
    single = _nacl()
    assert [r.hkl for r in doublet.reflections] == [r.hkl
                                                    for r in single.reflections]
    peaks = pxrd.peak_positions(doublet)
    assert len(peaks) == 2 * len(single.reflections)
    splits = []
    for r in (doublet.reflections[0], doublet.reflections[-1]):
        near = sorted(x for x, _h in peaks if abs(x - r.two_theta) < 1.5)
        splits.append(near[-1] - near[0])
    assert splits[0] > 0.0
    assert splits[-1] > 3 * splits[0], "the split has to grow with angle"


def test_the_second_line_comes_in_at_its_stated_share():
    doublet = _nacl(components=pxrd.parse_source("Cu Ka1+Ka2 2:1"))
    first = doublet.reflections[0]
    heights = sorted((h for x, h in pxrd.peak_positions(doublet)
                      if abs(x - first.two_theta) < 1.5), reverse=True)
    # Not exactly 0.5: the two lines diffract at slightly different angles, so
    # their Lorentz-polarisation factors differ a little. That is physics, not
    # a rounding error.
    assert heights[1] / heights[0] == pytest.approx(0.5, abs=0.01)


def test_a_doublet_does_NOT_split_on_the_Q_axis():
    """Q is wavelength-independent, so both lines put a reflection at the same
    Q. Not a bug: it is the reason the axis exists."""
    doublet = _nacl(components=pxrd.parse_source("Cu Ka1+Ka2 2:1"))
    peaks = pxrd.peak_positions(doublet, axis=pxrd.AXIS_Q)
    assert len({round(x, 9) for x, _h in peaks}) == len(doublet.reflections)


def test_source_and_wavelength_are_kept_in_step():
    s = Structure.from_atoms([("Na", 0.0, 0.0, 0.0)])
    pxrd.set_settings(s, source="Mo Ka1")
    assert pxrd.settings_of(s)["wavelength"] == pytest.approx(
        pxrd.LINES["Mo"]["Ka1"])
    # ...and a bare wavelength clears the source, because a number cannot
    # describe a doublet and leaving the old text would ignore the request.
    pxrd.set_settings(s, wavelength=0.4)
    assert pxrd.settings_of(s)["source"] == ""
    assert pxrd.components_of(pxrd.settings_of(s)) == [(0.4, 1.0)]


# --------------------------------------------------------- absences / hkl
def test_rock_salt_absences_are_exactly_the_mixed_parity_reflections():
    """Textbook: an F-centred lattice reflects only where h, k and l have the
    same parity. Nothing in `compute` knows what F-centring is - the absence
    is |F|^2 coming out zero - which is what makes the agreement meaningful.
    """
    pattern = _nacl(two_theta_range=(10, 90), keep_absent=True)
    absent = [r for r in pattern.reflections if r.absent]
    assert absent, "there must be some"
    for r in absent:
        parities = {abs(v) % 2 for v in r.hkl}
        assert len(parities) > 1, "{} is not mixed parity".format(r.label())
    for r in pattern.reflections:
        if not r.absent:
            assert len({abs(v) % 2 for v in r.hkl}) == 1


def test_keeping_the_absences_adds_rows_and_changes_nothing_else():
    plain = _nacl(two_theta_range=(10, 90))
    full = _nacl(two_theta_range=(10, 90), keep_absent=True)
    assert len(full) > len(plain)
    kept = [r for r in full.reflections if not r.absent]
    assert [r.hkl for r in kept] == [r.hkl for r in plain.reflections]
    for a, b in zip(kept, plain.reflections):
        assert a.intensity == pytest.approx(b.intensity)


def test_a_reflection_carries_what_an_hkl_table_lists():
    """d, the angle, Q, the multiplicity, |F|^2 and the Lorentz-polarisation
    factor - the columns a reflection list is made of."""
    r = _nacl().reflections[0]
    assert r.d > 0 and r.two_theta > 0 and r.q > 0
    assert r.multiplicity >= 1
    assert r.f2 > 0 and r.lp > 0
    assert r.intensity == pytest.approx(r.f2 * r.lp, rel=1e-9)


# ------------------------------------------------------------ the window
@pytest.fixture
def bench():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from molom.ui.app import MainWindow
    win = MainWindow()
    win.open_path(FERROCENE)
    win.open_path(SOLID_SOLUTION)
    return win


def _crystals(win):
    return [o for o in win.scene.objects
            if (o.structure.metadata or {}).get("cell")]


def test_the_default_range_stops_at_fifty_degrees(bench):
    """Christian's call. A lab pattern's information is below it, and the sum
    is over a sphere of radius 1/d_min - so asking for 90 is three times the
    work for the tail of the pattern."""
    assert pxrd.DEFAULT_TWO_THETA == (5.0, 50.0)
    win = bench
    win.on_pxrd()
    assert win._pxrd_window.plot.view_x()[1] == pytest.approx(50.0, abs=0.5)


def test_a_selection_decides_which_crystals_are_ticked(bench):
    """Christian: "If I select 3 structures and then launch it, only those
    three should be ticked and shown." """
    win = bench
    crystals = _crystals(win)
    win.viewport.set_selection([(crystals[1].id, 0)])
    win.on_pxrd()
    ticked = {o.name for o, box, _c in win._pxrd_window.rows if box.isChecked()}
    assert ticked == {crystals[1].name}


def test_the_selection_is_not_written_back_onto_the_crystals(bench):
    """A selection says which crystals this OPENING is about. Writing it would
    mean opening the window on one of five silently switched the other four
    off in the savefile."""
    win = bench
    crystals = _crystals(win)
    win.viewport.set_selection([(crystals[1].id, 0)])
    win.on_pxrd()
    assert "enabled" not in (crystals[0].structure.metadata.get(
        pxrd.METADATA_KEY) or {})
    # With nothing selected the ticks come back from what each crystal knows.
    win.viewport.set_selection([])
    win.on_pxrd()
    assert all(box.isChecked() for _o, box, _c in win._pxrd_window.rows)


def test_ticking_a_box_by_hand_IS_remembered(bench):
    win = bench
    win.viewport.set_selection([])
    win.on_pxrd()
    obj, box, _c = win._pxrd_window.rows[0]
    box.setChecked(False)
    assert pxrd.settings_of(obj.structure)["enabled"] is False


# ------------------------------------------------------------ navigation
def _plot(win):
    win.viewport.set_selection([])
    win.on_pxrd()
    window = win._pxrd_window
    window.resize(900, 600)
    window.show()
    window.plot.setFixedSize(820, 320)
    return window, window.plot


def test_Z_cycles_the_zoom_modes_and_Esc_leaves(bench):
    """OWB's key map, which is what Christian uses daily."""
    window, plot = _plot(bench)
    assert plot.mode() is None
    for expected in ("zoom_h", "zoom_v", "zoom_box", None):
        plot.keyPressEvent(_key(Qt().Key_Z))
        assert plot.mode() == expected
    plot.keyPressEvent(_key(Qt().Key_P))
    assert plot.mode() == "pan_h"
    plot.keyPressEvent(_key(Qt().Key_Escape))
    assert plot.mode() is None


def test_a_box_drag_zooms_BOTH_axes(bench):
    """"I cannot select an area as a box, or as a vertical or horizontal
    strip." Now all three."""
    window, plot = _plot(bench)
    before_x, before_y = plot.view_x(), plot.view_y()
    _drag(plot, "zoom_box", 120, 60, 300, 200)
    assert plot.view_x() != before_x
    assert plot.view_y() != before_y


def test_a_vertical_strip_leaves_x_alone(bench):
    window, plot = _plot(bench)
    before_x = plot.view_x()
    _drag(plot, "zoom_v", 120, 60, 300, 200)
    assert plot.view_x() == before_x
    assert not plot.at_home_y()


def test_a_horizontal_strip_leaves_y_alone(bench):
    window, plot = _plot(bench)
    before_y = plot.view_y()
    _drag(plot, "zoom_h", 120, 60, 300, 200)
    assert plot.view_y() == before_y
    assert not plot.at_home_x()


def test_F_is_the_two_stage_reset(bench):
    """x first, then y, then the intensity scale - OWB's staging, because the
    three are undone in the order they are usually done."""
    window, plot = _plot(bench)
    _drag(plot, "zoom_box", 120, 60, 300, 200)
    plot.set_y_scale(2.0)
    assert not plot.at_home_x() and not plot.at_home_y()
    plot.reset_view()
    assert plot.at_home_x() and not plot.at_home_y()
    plot.reset_view()
    assert plot.at_home_y() and plot.y_scale == 2.0
    plot.reset_view()
    assert plot.y_scale == 1.0
    assert plot.reset_view() is False, "nothing left to undo"


def test_the_wheel_scales_intensity_and_ctrl_wheel_zooms_x(bench):
    window, plot = _plot(bench)
    plot.wheelEvent(_wheel(plot, 120))
    assert plot.y_scale == pytest.approx(1.2)
    assert plot.at_home_x(), "a plain wheel must not move the x range"
    before = plot.view_x()
    from PySide6.QtCore import Qt as _Qt
    plot.wheelEvent(_wheel(plot, 120, _Qt.ControlModifier))
    assert plot.view_x() != before
    assert plot.y_scale == pytest.approx(1.2), "and must not scale again"


def test_the_offset_slider_and_the_margin_move_the_layout(bench):
    """"I can also not set the percentual vertical offset as a slider nor the
    vertical margins." """
    window, plot = _plot(bench)
    window.offset.setValue(0)
    assert all(t.offset == 0.0 for t in plot.traces), "0 is a plain overlay"
    window.offset.setValue(150)
    assert max(t.offset for t in plot.traces) == pytest.approx(150.0)
    window.margin.setValue(20)
    assert plot.y_margin == pytest.approx(0.2)
    lo, hi = plot.data_y()
    assert lo < 0 and hi > 250


# ----------------------------------------------------------- performance
def test_a_hover_does_not_rebuild_the_picture(bench):
    """The blit. Everything that does not follow the cursor is drawn once
    into a pixmap, so a mouse move is a blit and two lines - which is the
    whole of why this used to crawl."""
    window, plot = _plot(bench)
    plot.grab()                                  # build the cache
    key = plot._cache_key
    cache = plot._cache
    plot.mouseMoveEvent(_move(plot, 200, 100))
    plot.grab()
    assert plot._cache is cache, "the cursor must not invalidate the cache"
    assert plot._cache_key == key


def test_a_pan_drag_blits_instead_of_rebuilding(bench):
    """A pan is the one gesture that can afford to blit: the picture is
    unchanged and only its origin moved."""
    window, plot = _plot(bench)
    plot.grab()
    cache = plot._cache
    plot.set_mode("pan_h")
    plot.mousePressEvent(_press(plot, 200, 100))
    plot.mouseMoveEvent(_move(plot, 260, 100))
    plot.grab()
    assert plot._cache is cache, "still the same pixmap, drawn shifted"
    assert not plot.at_home_x(), "...and the view really did move"
    plot.mouseReleaseEvent(_release(plot, 260, 100))
    assert plot._cache is None, "the release redraws it properly"


def test_the_curve_is_decimated_to_about_one_point_per_pixel(bench):
    window, plot = _plot(bench)
    rect = plot.plot_rect()
    trace = plot.traces[0]
    poly = plot._envelope(trace, rect, *plot.view_x())
    assert len(trace.x) > 3 * rect.width(), "the profile really is dense"
    assert poly.size() < 2 * rect.width()


def test_the_decimation_keeps_every_peak(bench):
    """The point of a min/max envelope: a peak one pixel wide is exactly what
    a diffractogram is made of, so losing one would be losing the data.

    Measured against the UNDECIMATED curve rather than looked at - and note
    the check has to allow a pixel of slack in x, because a column boundary
    is not a sample position. A first cut that did not reported seven lost
    peaks that were all present, which is this project's recurring lesson
    about the measuring instrument.
    """
    window, plot = _plot(bench)
    rect = plot.plot_rect()
    trace = plot.traces[0]
    lo, hi = plot.view_x()
    poly = plot._envelope(trace, rect, lo, hi)
    drawn = np.array([[poly.at(i).x(), poly.at(i).y()]
                      for i in range(poly.size())])
    px = rect.left() + (trace.x - lo) / (hi - lo) * rect.width()
    py = plot.y_to_px(trace.y * plot.y_scale + trace.offset, rect)
    top = float(trace.y.max())
    peaks = [i for i in range(1, len(trace.y) - 1)
             if trace.y[i] > trace.y[i - 1] and trace.y[i] >= trace.y[i + 1]
             and trace.y[i] > 0.02 * top]
    assert len(peaks) > 10
    for i in peaks:
        near = drawn[np.abs(drawn[:, 0] - px[i]) <= 1.5]
        assert len(near), "no point drawn near a real peak"
        assert near[:, 1].min() - py[i] < 1.0


def test_a_pattern_is_not_recomputed_for_a_drawing_change(bench):
    """The structure factor sum depends on the structure, the source and the
    range and on nothing else - re-running it because the peak width moved is
    the expensive mistake."""
    window, _plot_ = _plot(bench)
    before = [t.pattern for t in window.plot.traces]
    window.fwhm.setValue(0.4)
    assert [t.pattern for t in window.plot.traces] == before
    window.offset.setValue(60)
    assert [t.pattern for t in window.plot.traces] == before
    # ...and changing the RANGE does recompute, because it must.
    window.tt_max.setValue(70.0)
    assert [t.pattern for t in window.plot.traces] != before


def test_eight_patterns_still_redraw_quickly(bench):
    """Christian: "Scales poorly with number of PXRDs." The numbers this
    guards are the ones in CLAUDE.md; the threshold is deliberately loose
    because a wall-clock assertion is a machine-speed assertion (round 65),
    and it is here to catch a REGRESSION of the kind that put a Python loop
    back into the paint path."""
    win = bench
    for _ in range(3):
        win.open_path(FERROCENE)
    window, plot = _plot(win)
    assert len(plot.traces) >= 5
    plot.grab()
    start = time.perf_counter()
    for _ in range(10):
        plot.grab()
    per_paint = (time.perf_counter() - start) / 10
    assert per_paint < 0.05, "a blitted repaint is milliseconds, not tens"


# ------------------------------------------------- per-crystal settings
def test_right_clicking_a_line_finds_that_trace(bench):
    """Christian: "clicking the line is more intuitive and doesn't require
    tab switching"."""
    from PySide6.QtCore import QPointF
    window, plot = _plot(bench)
    rect = plot.plot_rect()
    trace = plot.traces[0]
    x = rect.left() + rect.width() * 0.6
    y = plot.y_to_px(trace.offset, rect)          # on its baseline
    assert plot._trace_at(QPointF(x, y)) is trace
    # ...and far from every curve it finds nothing rather than guessing.
    assert plot._trace_at(QPointF(x, rect.top() - 500)) is None


def test_the_trace_dialog_writes_colour_source_and_range(bench):
    from molom.ui.pxrd_panel import TraceOptions
    window, plot = _plot(bench)
    obj = window.rows[0][0]
    dlg = TraceOptions(window, obj, "#6ea8ff")
    dlg._colour = _colour("#ff0000")
    dlg.source.setCurrentText("Mo Ka1")
    dlg.tt_min.setValue(3.0)
    dlg.tt_max.setValue(40.0)
    dlg.apply()
    settings = pxrd.settings_of(obj.structure)
    assert settings["colour"] == "#ff0000"
    assert settings["source"] == "Mo Ka1"
    assert settings["two_theta_max"] == pytest.approx(40.0)
    assert pxrd.pattern_for(obj.structure).wavelength == pytest.approx(
        pxrd.LINES["Mo"]["Ka1"])


def test_the_trace_dialog_refuses_an_unreadable_source(bench):
    """A source box that silently falls back to Cu when it cannot read what
    you wrote is how a whole pattern comes out at the wrong angles with
    nothing on screen to say so."""
    from PySide6.QtWidgets import QDialogButtonBox
    from molom.ui.pxrd_panel import TraceOptions
    window, plot = _plot(bench)
    dlg = TraceOptions(window, window.rows[0][0], "#6ea8ff")
    dlg.source.setCurrentText("banana")
    assert not dlg.buttons.button(QDialogButtonBox.Ok).isEnabled()
    assert "banana" in dlg.energy.text()
    dlg.source.setCurrentText("13.5 keV")
    assert dlg.buttons.button(QDialogButtonBox.Ok).isEnabled()
    assert "keV" in dlg.energy.text()


def test_two_crystals_can_have_different_sources_and_share_a_Q_axis(bench):
    window, plot = _plot(bench)
    a, b = window.rows[0][0], window.rows[1][0]
    pxrd.set_settings(a.structure, source="Cu Ka1")
    pxrd.set_settings(b.structure, source="Mo Ka1")
    window.recompute()
    assert plot.axis == pxrd.AXIS_Q
    assert not window.q_axis.isEnabled()


# ------------------------------------------------------------- hkl table
def test_the_hkl_tab_lists_the_absences(bench):
    window, plot = _plot(bench)
    window.tabs.setCurrentIndex(window._hkl_tab)
    with_absent = window.hkl.table.rowCount()
    assert "absent" in window.hkl.count.text()
    window.hkl.show_absent.setChecked(False)
    assert window.hkl.table.rowCount() < with_absent


def test_the_hkl_table_sorts_numerically(bench):
    """`QTableWidgetItem` compares its TEXT, so 100 would sort before 98 and a
    d-spacing column would be nonsense."""
    from molom.ui.pxrd_panel import _NumericItem
    window, plot = _plot(bench)
    window.tabs.setCurrentIndex(window._hkl_tab)
    assert _NumericItem(98.0, "98") < _NumericItem(100.0, "100")
    assert not (_NumericItem(100.0, "100") < _NumericItem(98.0, "98"))


def test_the_reflection_list_exports(bench, tmp_path):
    window, plot = _plot(bench)
    window.tabs.setCurrentIndex(window._hkl_tab)
    out = str(tmp_path / "hkl.csv")
    assert window.export_reflections(out) == out
    text = open(out, encoding="utf-8").read()
    assert text.splitlines()[0].startswith("h,k,l,d_angstrom")
    assert len(text.splitlines()) == window.hkl.table.rowCount() + 1


# ---------------------------------------------------------------- helpers
def Qt():
    from PySide6.QtCore import Qt as _Qt
    return _Qt


def _colour(name):
    from PySide6.QtGui import QColor
    return QColor(name)


def _key(code, mods=None):
    from PySide6.QtCore import QEvent, Qt as _Qt
    from PySide6.QtGui import QKeyEvent
    return QKeyEvent(QEvent.KeyPress, code, mods or _Qt.NoModifier)


def _point(plot, x, y):
    from PySide6.QtCore import QPointF
    rect = plot.plot_rect()
    return QPointF(rect.left() + x, rect.top() + y)


def _press(plot, x, y):
    from PySide6.QtCore import QEvent, Qt as _Qt
    from PySide6.QtGui import QMouseEvent
    return QMouseEvent(QEvent.MouseButtonPress, _point(plot, x, y),
                       _Qt.LeftButton, _Qt.LeftButton, _Qt.NoModifier)


def _move(plot, x, y):
    from PySide6.QtCore import QEvent, Qt as _Qt
    from PySide6.QtGui import QMouseEvent
    return QMouseEvent(QEvent.MouseMove, _point(plot, x, y), _Qt.NoButton,
                       _Qt.LeftButton, _Qt.NoModifier)


def _release(plot, x, y):
    from PySide6.QtCore import QEvent, Qt as _Qt
    from PySide6.QtGui import QMouseEvent
    return QMouseEvent(QEvent.MouseButtonRelease, _point(plot, x, y),
                       _Qt.LeftButton, _Qt.LeftButton, _Qt.NoModifier)


def _wheel(plot, delta, mods=None):
    from PySide6.QtCore import QPoint, QPointF, Qt as _Qt
    from PySide6.QtGui import QWheelEvent
    centre = QPointF(plot.plot_rect().center())
    return QWheelEvent(centre, centre, QPoint(0, 0), QPoint(0, delta),
                       _Qt.NoButton, mods or _Qt.NoModifier,
                       _Qt.NoScrollPhase, False)


def _drag(plot, mode, x0, y0, x1, y1):
    plot.set_mode(mode)
    plot.mousePressEvent(_press(plot, x0, y0))
    plot.mouseMoveEvent(_move(plot, x1, y1))
    plot.mouseReleaseEvent(_release(plot, x1, y1))

def test_the_tick_box_offers_the_same_menu_as_the_line(bench):
    """Christian asked for BOTH routes: "right clicking on a line in the
    plotting pane as well as right clicking on a label where the tick boxes
    are".

    The menus are BUILT here and not shown: `QMenu.exec` runs a modal event
    loop, so a test that reaches it hangs rather than failing.
    """
    window, plot = _plot(bench)
    obj, box, _colour = window.rows[0]
    assert box.contextMenuPolicy() == Qt().CustomContextMenu
    from_label = [a.text() for a in window.build_label_menu(obj).actions()]
    from_line = [a.text() for a in
                 window.build_trace_menu(plot.traces[0]).actions()]
    assert any(obj.name in text for text in from_label)
    assert any(obj.name in text for text in from_line)
    # Every crystal is reachable from the plot menu, not only the one the
    # cursor happened to be over.
    for other, _b, _c in window.rows:
        assert any(other.name in text for text in from_line)


def test_hiding_from_the_plot_menu_unticks_the_box(bench):
    window, plot = _plot(bench)
    obj = plot.traces[0].obj
    menu = window.build_trace_menu(plot.traces[0])
    hide = [a for a in menu.actions() if a.text().startswith("Hide")][0]
    hide.trigger()
    ticked = {o.id for o, b, _c in window.rows if b.isChecked()}
    assert obj.id not in ticked


def test_the_plot_has_focus_when_the_window_opens(bench):
    """Otherwise the first focusable widget is a text box, `Z` types a letter
    into it, and the whole key map looks dead until you happen to click the
    plot. Round 12's focus-follows-the-cursor rule, applied here."""
    win = bench
    win.viewport.set_selection([])
    win.on_pxrd()
    window = win._pxrd_window
    assert window.focusWidget() is window.plot


def test_the_cached_pixmap_is_allocated_in_DEVICE_pixels(bench):
    """Round 59's DPR trap, walked into again and photographed by Christian.

    `QPixmap(w, h)` allocates w x h DEVICE pixels; `setDevicePixelRatio(1.5)`
    then declares them to be w/1.5 x h/1.5 LOGICAL ones. A pixmap made at the
    widget's LOGICAL size therefore covers two thirds of a 150% display - the
    plot drew into the top-left corner, the x axis and the right-hand peaks
    were clipped away, and the crosshair (painted on the widget, at full
    size) ran on past the edge of it.

    Pinned by shadowing the ratio rather than by running the suite at 150%,
    because a QApplication reads its scale factor once, at construction.
    """
    window, plot = _plot(bench)
    for ratio in (1.0, 1.25, 1.5, 2.0):
        plot.devicePixelRatioF = lambda r=ratio: r
        plot.invalidate()
        plot.grab()
        cache = plot._cache
        assert cache.devicePixelRatio() == pytest.approx(ratio)
        assert cache.width() == round(plot.width() * ratio), ratio
        assert cache.height() == round(plot.height() * ratio), ratio
        # ...which is the property that actually matters: the pixmap covers
        # the widget when it is drawn at (0, 0).
        assert cache.width() / ratio == pytest.approx(plot.width(), abs=1)
        assert cache.height() / ratio == pytest.approx(plot.height(), abs=1)


def test_the_cache_is_rebuilt_when_the_scale_changes(bench):
    """Dragging the window to a monitor at a different scale needs a
    different pixmap and changes nothing else about the picture."""
    window, plot = _plot(bench)
    plot.devicePixelRatioF = lambda: 1.0
    plot.invalidate()
    plot.grab()
    first = plot._cache_key
    plot.devicePixelRatioF = lambda: 1.5
    plot.grab()
    assert plot._cache_key != first
    assert plot._cache.width() == round(plot.width() * 1.5)


# ------------------------------------------------- resolution-independence
def test_the_window_has_minimise_and_maximise_buttons(bench):
    """A QDialog gets a close button and nothing else. This is a tool window
    kept open beside the viewport, and a plot is the first thing anybody
    wants full-screen."""
    win = bench
    win.viewport.set_selection([])
    win.on_pxrd()
    flags = win._pxrd_window.windowFlags()
    assert flags & Qt().WindowMinimizeButtonHint
    assert flags & Qt().WindowMaximizeButtonHint
    assert flags & Qt().Window


def test_the_window_can_be_made_small(bench):
    """`resize` takes LOGICAL pixels, so at 150% a 980 x 660 window is
    1470 x 990 real ones - taller than a 1080p working area, which is how
    the controls ended up below the bottom edge. And no `resize` could undo
    it, because the window's own MINIMUM was 902 x 634: a word-wrapped note
    label reports the height it needs at its minimum WIDTH, and the control
    rows were fixed. The note is capped and the rows wrap."""
    win = bench
    win.viewport.set_selection([])
    win.on_pxrd()
    window = win._pxrd_window
    minimum = window.minimumSizeHint()
    assert minimum.height() <= 400, minimum
    assert minimum.width() <= 480, minimum
    window.resize(560, 380)
    window.show()
    assert window.height() == 380
    assert window.width() == 560


def test_the_opening_size_is_clamped_to_the_screen(bench):
    win = bench
    win.viewport.set_selection([])
    win.on_pxrd()
    window = win._pxrd_window
    width, height = window.opening_size()
    available = window.screen().availableGeometry()
    assert width <= available.width()
    assert height <= available.height()
    assert (width, height) <= window.PREFERRED_SIZE


def test_the_curve_is_about_one_point_per_pixel_at_EVERY_zoom(bench):
    """Christian's question, and the half his sketch was missing: a stored
    grid is simultaneously too dense zoomed out and too sparse zoomed in.
    Zoomed to a tenth of a degree it was twelve points across 754 pixels -
    68 px per straight segment, i.e. a polygon.

    The profile is an analytic sum of peaks, so it is evaluated AT THE PIXELS
    being drawn instead. The point count is then bounded by the width of the
    window at every zoom level, which is the whole answer.
    """
    window, plot = _plot(bench)
    rect = plot.plot_rect()
    trace = plot.traces[0]
    peak = max(trace.pattern.reflections, key=lambda r: r.intensity)
    for span in (45.0, 5.0, 1.0, 0.3, 0.1, 0.02):
        lo, hi = peak.two_theta - span / 2, peak.two_theta + span / 2
        plot.set_view_x(lo, hi)
        poly = plot._envelope(trace, rect, lo, hi)
        per_segment = rect.width() / max(1, poly.size() - 1)
        assert poly.size() <= 2 * rect.width(), span
        assert per_segment < 2.0, (span, per_segment)


def test_the_zoomed_curve_lies_ON_the_analytic_profile(bench):
    """Not merely smooth - right. Interpolating a stored grid would be
    smooth and wrong; evaluating the function is neither."""
    window, plot = _plot(bench)
    rect = plot.plot_rect()
    trace = plot.traces[0]
    peak = max(trace.pattern.reflections, key=lambda r: r.intensity)
    lo, hi = peak.two_theta - 0.05, peak.two_theta + 0.05
    plot.set_view_x(lo, hi)
    poly = plot._envelope(trace, rect, lo, hi)
    pts = np.array([[poly.at(i).x(), poly.at(i).y()]
                    for i in range(poly.size())])
    xs = lo + (pts[:, 0] - rect.left()) / rect.width() * (hi - lo)
    truth = plot.y_to_px(trace.sampler(xs) * plot.y_scale + trace.offset, rect)
    assert np.abs(pts[:, 1] - truth).max() < 0.5


def test_a_peak_narrower_than_a_pixel_still_reaches_its_height(bench):
    """The aliasing the supersampling exists to prevent. One sample per pixel
    lands wherever it lands, so a peak six times narrower than a pixel gets
    drawn at whatever fraction of its height the sample happened to catch."""
    window, plot = _plot(bench)
    obj = window.rows[0][0]
    pxrd.set_settings(obj.structure, fwhm=0.01,
                      two_theta_min=5.0, two_theta_max=50.0)
    window._profiles.clear()
    window.recompute(keep_view=False)
    trace = plot.traces[0]
    rect = plot.plot_rect()
    lo, hi = plot.view_x()
    assert trace.fwhm / (hi - lo) * rect.width() < 0.5, "narrower than a pixel"
    poly = plot._envelope(trace, rect, lo, hi)
    drawn = min(poly.at(i).y() for i in range(poly.size()))
    baseline = plot.y_to_px(trace.offset, rect)
    full = plot.y_to_px(100.0 + trace.offset, rect)
    reached = (baseline - drawn) / (baseline - full)
    assert reached > 0.95, reached
    # ...and what it would have been WITHOUT the supersampling, measured
    # rather than argued: one sample per pixel finds about 60% of it.
    naive = trace.sampler(lo + (np.arange(rect.width()) + 0.5)
                          * ((hi - lo) / rect.width())).max()
    assert naive < 90.0


def test_the_sampler_never_samples_more_coarsely_than_the_stored_grid(bench):
    """Zoomed out the stored 0.01 degree grid is denser than any per-pixel
    sampling, and resampling there would THROW DETAIL AWAY - measured as peak
    tops drawn 4 px low, which is what caught the first cut of this."""
    window, plot = _plot(bench)
    rect = plot.plot_rect()
    trace = plot.traces[0]
    lo, hi = plot.view_x()
    assert plot._view_samples(trace, rect, lo, hi) is None, "stored is finer"
    peak = trace.pattern.reflections[0]
    plot.set_view_x(peak.two_theta - 0.2, peak.two_theta + 0.2)
    assert plot._view_samples(trace, rect, *plot.view_x()) is not None


# ------------------------------------------------- round 97: the batch
def test_the_pattern_tab_keeps_only_the_four_live_controls(bench):
    """Christian: "Everything that is not the offset slider, Radiation
    selection, 2theta range and FWHM should either be in the advanced tab or
    a per line option." The rest was spending the plot's own height."""
    win = bench
    win.viewport.set_selection([])
    win.on_pxrd()
    window = win._pxrd_window
    assert [window.tabs.tabText(i) for i in range(window.tabs.count())] == [
        "Pattern", "Advanced", "Reflections (hkl)"]
    page = window.tabs.widget(0)
    for widget in (window.source, window.tt_min, window.tt_max, window.fwhm,
                   window.offset):
        assert widget.parent() is not None
        assert window.tabs.indexOf(_page_of(widget, window)) == 0
    # ...and the ones that moved really are on the Advanced page.
    for widget in (window.shape, window.q_axis, window.margin):
        assert window.tabs.indexOf(_page_of(widget, window)) == 1


def _page_of(widget, window):
    node = widget
    pages = {window.tabs.widget(i) for i in range(window.tabs.count())}
    while node is not None and node not in pages:
        node = node.parent()
    return node


def test_the_offset_slider_is_vertical_and_beside_the_plot(bench):
    win = bench
    win.viewport.set_selection([])
    win.on_pxrd()
    window = win._pxrd_window
    assert window.offset.orientation() == Qt().Vertical
    window.resize(900, 560)
    window.show()
    # To the RIGHT of the plot, and sharing its height rather than costing it.
    assert window.offset.x() > window.plot.x()
    assert window.offset.height() >= window.plot.height() * 0.8


def test_a_decimal_comma_is_a_decimal_point(bench):
    """Christian is on a German locale, where Qt's own separator is a comma -
    so a typed "0.15" was not a number and the box quietly kept its old
    value."""
    from molom.ui.pxrd_panel import NumberBox
    win = bench
    win.viewport.set_selection([])
    win.on_pxrd()
    window = win._pxrd_window
    for box in (window.fwhm, window.tt_min, window.tt_max):
        assert isinstance(box, NumberBox)
    assert window.fwhm.valueFromText("0,25") == pytest.approx(0.25)
    assert window.fwhm.valueFromText("0.25") == pytest.approx(0.25)
    # ...and in the radiation box, which is free text.
    assert pxrd.parse_source("1,5406") == [(1.5406, 1.0)]
    assert pxrd.parse_source("17,5 keV")[0][0] == pytest.approx(
        pxrd.ENERGY_ANGSTROM / 17.5)


def test_a_typed_wavelength_is_accepted(bench):
    """It was not. An editable QComboBox INSERTS what you type as a new item,
    and `itemData` for that row is None - so `source_text` returned the
    string "None" and the source was refused. The pattern then stayed at
    whatever it was, which is a whole diffractogram at the wrong angles."""
    win = bench
    win.viewport.set_selection([])
    win.on_pxrd()
    window = win._pxrd_window
    assert window.source.insertPolicy() == QComboBox_NoInsert()
    window.source.setCurrentText("0.7")
    assert window.source_text() == "0.7"
    window._changed()
    for obj, _box, _c in window.rows:
        assert pxrd.settings_of(obj.structure)["source"] == "0.7"
    assert all(t.pattern.wavelength == pytest.approx(0.7)
               for t in window.plot.traces)


def QComboBox_NoInsert():
    from PySide6.QtWidgets import QComboBox
    return QComboBox.NoInsert


def test_the_shared_controls_are_GLOBAL_overrides(bench):
    """"The options radiation, FWHM, 2theta range should all be global
    overwrites" - every crystal, ticked or not, because an override that
    skipped the ones you cannot see would leave a stale wavelength waiting."""
    win = bench
    win.viewport.set_selection([])
    win.on_pxrd()
    window = win._pxrd_window
    window.rows[0][1].setChecked(False)           # unticked, still overridden
    window.source.setCurrentText("Mo Ka1")
    window.fwhm.setValue(0.3)
    window._changed()
    for obj, _box, _c in window.rows:
        settings = pxrd.settings_of(obj.structure)
        assert settings["source"] == "Mo Ka1"
        assert settings["fwhm"] == pytest.approx(0.3)


def test_every_global_is_also_settable_per_line(bench):
    from molom.ui.pxrd_panel import TraceOptions
    win = bench
    win.viewport.set_selection([])
    win.on_pxrd()
    window = win._pxrd_window
    obj = window.rows[0][0]
    dlg = TraceOptions(window, obj, "#6ea8ff")
    for attr in ("source", "tt_min", "tt_max", "fwhm", "shape"):
        assert hasattr(dlg, attr), attr
    dlg.fwhm.setValue(0.42)
    dlg.shape.setCurrentIndex(dlg.shape.findData(pxrd.SHAPE_GAUSSIAN))
    dlg.apply()
    settings = pxrd.settings_of(obj.structure)
    assert settings["fwhm"] == pytest.approx(0.42)
    assert settings["shape"] == pxrd.SHAPE_GAUSSIAN


def test_the_tick_labels_are_abbreviated_with_the_full_name_on_hover(bench):
    from molom.ui.pxrd_panel import LABEL_CHARS, short_name
    win = bench
    win.viewport.set_selection([])
    win.on_pxrd()
    window = win._pxrd_window
    obj, box, _c = window.rows[0]
    assert len(box.text()) <= LABEL_CHARS + 3
    assert obj.name in box.toolTip()
    assert short_name("short") == "short"
    assert short_name("a very long crystal name indeed").endswith("...")


def test_the_axis_limits_are_a_dialog_not_a_row(bench):
    """"The view x view y options should also be a right click option and not
    take up space by default"."""
    from molom.ui.pxrd_panel import AxisLimits
    window, plot = _plot(bench)
    assert not hasattr(window, "lim"), "the boxes are gone"
    actions = [a.text() for a in window.build_trace_menu(None).actions()]
    assert any("Axis limits" in text for text in actions)
    dlg = AxisLimits(window, (5.0, 50.0), (0.0, 100.0), "2 theta")
    dlg.boxes["x0"].setText("12,5")          # a decimal comma here too
    dlg.boxes["x1"].setText("20")
    x, y = dlg.ranges()
    assert x == (12.5, 20.0)
    dlg._auto()
    assert dlg.ranges() == (None, None)


def test_the_curve_is_reduced_at_DEVICE_resolution(bench):
    """`rect.width()` is LOGICAL, so a min/max envelope built per logical
    pixel is a staircase with 1.5-device-pixel treads on a 150% display -
    which is the "a lot of steps visible" report, and is not an antialiasing
    failure: antialiasing cannot smooth a step it was asked to draw."""
    window, plot = _plot(bench)
    rect = plot.plot_rect()
    for ratio in (1.0, 1.5, 2.0):
        plot.devicePixelRatioF = lambda r=ratio: r
        assert plot.columns(rect) == round(rect.width() * ratio)

