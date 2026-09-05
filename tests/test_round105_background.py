"""Round 105 - the derivative-gated background, drag and drop, live settings.

Christian, after using round 104 on his own synchrotron scans: "I still don't
like the results... I think we can achieve something very nice if we give up
on capturing amorphous contributions and go through the pattern from high to
low angle. I want to basically run a rolling first derivative on a smoothed
pattern so that spikes stand out and do not get flattened while also
continuous rises will be taken out because the rolling derivative has a
sensitivity parameter that dictates when background subtraction hits a peak
and needs to stop fitting the pattern."

The tests here are written as PROPERTIES of the walk rather than as numbers
off one file, because the whole argument for it is that it is one rule and
not a stack of special cases.
"""

import os

import numpy as np
import pytest

from molom.core import background as bg
from molom.core import pxrdfile

SOLID_SOLUTION = os.path.join(os.path.dirname(__file__), "data",
                              "cod_1547149_solid_solution.cif")


# --------------------------------------------------------------- fixtures
@pytest.fixture
def bench(tmp_path):
    """A real MainWindow with the PXRD window open on a real crystal."""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from molom.ui.app import MainWindow
    win = MainWindow()
    win.open_path(str(SOLID_SOLUTION))
    win.viewport.set_selection([])
    win.on_pxrd()
    return win

def _pattern(x=None, bg_level=None, peaks=(), noise=0.0, seed=3):
    """A background with Gaussian peaks on it, and the truth alongside."""
    if x is None:
        x = np.linspace(2.0, 60.0, 4000)
    base = np.full_like(x, 200.0 if bg_level is None else 0.0)
    if bg_level is not None:
        base = base + bg_level
    total = base.copy()
    for centre, height, fwhm in peaks:
        total = total + height * np.exp(
            -0.5 * ((x - centre) / (fwhm / 2.3548)) ** 2)
    if noise:
        total = total + np.random.default_rng(seed).normal(0, noise, x.size)
    return x, total, base


def _height_at(x, corrected, centre, window=0.5):
    near = np.abs(x - centre) < window
    return float(corrected[near].max()) if near.any() else 0.0


# ------------------------------------------------------- the walk's rules
def test_the_background_is_never_above_the_pattern():
    """The one thing an envelope must not do. It is a `min` against the
    smoothed data by construction, and a floor under the logarithm is the
    only way that could be broken - which is why the clamp is there."""
    for noise in (0.0, 5.0, 200.0):
        x, y, _true = _pattern(peaks=[(20.0, 3000, 0.1), (35.0, 900, 0.1)],
                               noise=noise)
        estimate = bg.rolling_background(x, y)
        assert np.all(estimate <= bg.smooth(y, bg.DEFAULT_SMOOTH) + 1e-9)
    # ...including where a previous subtraction has left zeros and negatives,
    # which `pxrdfile` warns about in its own note and which a logarithm
    # cannot take.
    x = np.linspace(5.0, 50.0, 800)
    y = np.zeros_like(x)
    y[400] = 500.0
    y[:50] = -3.0
    estimate = bg.rolling_background(x, y)
    assert np.all(np.isfinite(estimate))
    assert estimate[400] < 500.0


def test_a_flat_background_is_recovered_and_the_peak_survives():
    x, y, true = _pattern(peaks=[(20.0, 3000, 0.1)])
    corrected, estimate = bg.subtract_rolling(x, y)
    away = np.abs(x - 20.0) > 1.0
    assert float(np.max(np.abs(estimate[away] - true[away]))) < 1e-6
    assert _height_at(x, corrected, 20.0) > 0.9 * 3000


def test_a_SLOPING_background_is_followed_and_the_peak_still_survives():
    """The limit is on the RELATIVE slope, so it has to cope with a
    background that spans a large factor within one pattern - which is what
    a synchrotron scan does."""
    x = np.linspace(2.0, 60.0, 4000)
    falling = 20000.0 * np.exp(-0.25 * (x - 2.0)) + 150.0
    _x, y, true = _pattern(x, falling, peaks=[(30.0, 2000, 0.1)])
    corrected, estimate = bg.subtract_rolling(x, y)
    away = np.abs(x - 30.0) > 1.0
    assert float(np.max(np.abs(estimate[away] - true[away])
                        / true[away])) < 0.01
    assert _height_at(x, corrected, 30.0) > 0.9 * 2000


def test_the_walk_goes_HIGH_TO_LOW_and_that_is_what_handles_a_beam_stop():
    """Christian's instruction, and it does more work than it looks.

    The climb into a beam-stop shadow is a FALL walking leftwards, so the
    rise limit never applies to it and the envelope follows it down. A peak
    is the opposite: walking leftwards its high-angle flank is a rise, the
    limit binds, and the peak is bridged. One rule, opposite outcomes, and
    the asymmetry IS the model - so it is asserted rather than assumed.
    """
    x = np.linspace(0.0, 20.0, 4000)
    shadow = 1.0 - np.exp(-(np.maximum(x, 0.0) / 0.05) ** 3)
    y = 9000.0 * shadow + 300.0 + 22000.0 * np.exp(
        -0.5 * ((x - 8.0) / 0.05) ** 2)
    estimate = bg.rolling_background(x, y)
    # the ramp is background: the envelope sits ON it, all the way down
    ramp = x < 0.04
    assert float(np.max(np.abs(estimate[ramp] - bg.smooth(y, 5)[ramp]))) < 1e-6
    # the peak is not: the envelope holds at the shoulder instead of
    # following it up
    top = int(np.argmin(np.abs(x - 8.0)))
    shoulder = float(estimate[int(np.argmin(np.abs(x - 8.5)))])
    climbed = float(estimate[top]) - shoulder
    assert climbed < 0.2 * (float(y[top]) - shoulder), \
        "the envelope covers a fifth of the peak at most, not all of it"


def test_a_peak_is_bridged_from_BOTH_sides_by_the_single_pass():
    """The low-angle flank needs no separate rule: by the time the walk
    reaches it the envelope is already at the baseline, so the `min` simply
    keeps it there until the data comes back to meet it."""
    x, y, true = _pattern(peaks=[(30.0, 4000, 0.2)])
    corrected, estimate = bg.subtract_rolling(x, y)
    inside = np.abs(x - 30.0) < 0.4
    # the envelope is allowed to climb at `slope` while it bridges, so what
    # is asserted is that it stays near the BASELINE rather than following
    # the peak - and that both flanks come back, not only the one the walk
    # met first
    climbed = float(np.max(estimate[inside])) - float(true.mean())
    assert climbed < 0.1 * 4000
    assert _height_at(x, corrected, 30.0) > 0.85 * 4000
    left = corrected[(x > 29.0) & (x < 29.6)]
    right = corrected[(x > 30.4) & (x < 31.0)]
    assert float(left.max()) < 0.02 * 4000 and float(right.max()) < 0.02 * 4000


def test_the_vectorised_walk_IS_the_recursion_it_replaces():
    """`b[i] = min(s[i], b[i+1] * exp(slope * dx))` unrolls to a suffix
    minimum in log space, which is one `np.minimum.accumulate` instead of a
    Python loop over every point - 0.23 ms against 3.4 ms at 3841 points.
    It is an identity, not an approximation, so it is pinned as one."""
    x = np.linspace(1.0, 40.0, 1500)
    _x, y, _t = _pattern(x, 400.0 + 30.0 * np.cos(x / 3.0),
                         peaks=[(9.0, 900, 0.2), (25.0, 400, 0.2)], noise=4.0)
    slope, tail = 1.7, 0.9
    smoothed = bg.smooth(y, bg.DEFAULT_SMOOTH)
    floor = max(bg.point_noise(y), 1e-12)
    level = np.log(max(smoothed[-1], floor))
    loop = np.empty_like(smoothed)
    loop[-1] = level
    for i in range(smoothed.size - 2, -1, -1):
        ceiling = level + slope * (x[i + 1] - x[i]) \
            + tail * (np.log(x[i + 1]) - np.log(x[i]))
        level = min(np.log(max(smoothed[i], floor)), ceiling)
        loop[i] = level
    fast = bg.rolling_background(x, y, slope=slope, tail=tail)
    assert np.allclose(np.minimum(np.exp(loop), smoothed), fast, rtol=1e-9)


# ----------------------------------------------------- what it distinguishes
def test_an_AMORPHOUS_hump_is_background_and_a_BRAGG_peak_is_not():
    """The discrimination the whole thing exists for, and the price
    Christian named: "give up on capturing amorphous contributions".

    Measured on his own files before this was written - a peak-free
    background runs 0.02 to 0.06 per degree, a purely amorphous sample
    (i15-1-84519) tops out at 1.18, and Bragg peaks run 3 to 24 - which is
    why the default sits at 2.0.
    """
    x = np.linspace(2.0, 60.0, 4000)
    halo = 200.0 + 3000.0 * np.exp(-0.5 * ((x - 18.0) / 4.0) ** 2)
    amorphous, _e = bg.subtract_rolling(x, halo)
    assert float(amorphous.max()) < 0.02 * float(np.ptp(halo)), \
        "a broad halo is background and comes off"

    _x, crystalline, _t = _pattern(x, halo, peaks=[(30.0, 1500, 0.1)])
    corrected, _e = bg.subtract_rolling(x, crystalline)
    assert _height_at(x, corrected, 30.0) > 0.85 * 1500, \
        "...and a sharp peak sitting on the same halo does not"


def test_the_sensitivity_trades_peak_WIDTH_against_how_much_comes_off():
    """The knob is a slope, so it is the peak's WIDTH it is traded against:
    roughly, 0.5 divided by the width in degrees. Lower treats more of the
    pattern as peak, which is what a broad peak needs and what lets an
    amorphous hump through."""
    x = np.linspace(2.0, 60.0, 4000)
    _x, y, _t = _pattern(x, 400.0, peaks=[(30.0, 2000, 1.0)])
    eaten = bg.subtract_rolling(x, y, slope=4.0)[0]
    kept = bg.subtract_rolling(x, y, slope=0.4)[0]
    assert _height_at(x, eaten, 30.0, 1.5) < 0.3 * 2000
    assert _height_at(x, kept, 30.0, 1.5) > 0.8 * 2000
    # and a NARROW peak survives either way, which is why the default can be
    # set for amorphous rejection rather than for peak width
    _x, sharp, _t = _pattern(x, 400.0, peaks=[(30.0, 2000, 0.05)])
    for slope in (0.4, 2.0, 4.0):
        assert _height_at(x, bg.subtract_rolling(x, sharp, slope=slope)[0],
                          30.0) > 0.8 * 2000


def test_a_peak_must_STAND_OUT_of_its_background_to_be_seen():
    """The real cost of the model, measured rather than hoped about.

    The envelope is allowed to climb at `slope` while it crosses a peak, so
    a peak that is small compared with the background it sits on is followed
    rather than bridged. The floor goes as `slope * FWHM`: for a 0.06 degree
    peak it is 8.9% of the background at slope 0.5, 16.1% at 1.0 and 31.6%
    at 2.0. That linearity is why the default was lowered to 1.0 - amorphous
    rejection turned out not to constrain it, and the weak reflections do.
    """
    x = np.linspace(2.0, 40.0, 6000)

    def survives(ratio, slope):
        y = 1000.0 * (1.0 + ratio * np.exp(-0.5 * ((x - 20.0) / 0.0255) ** 2))
        corrected, _e = bg.subtract_rolling(x, y, slope=slope)
        return _height_at(x, corrected, 20.0) > 0.5 * 1000.0 * ratio

    assert survives(0.30, bg.DEFAULT_SLOPE)
    assert not survives(0.05, bg.DEFAULT_SLOPE)
    # ...and turning the knob down is the lever, which is the whole point of
    # it being a knob
    assert survives(0.12, 0.5)
    assert not survives(0.12, 2.0)


def test_the_small_angle_allowance_is_what_a_POWER_LAW_foot_needs():
    """Christian named this case: "starts low, spikes strongly, then decays
    by power law until zero". A power law's relative slope is b/x, which
    diverges as 2 theta goes to zero - so a constant relative limit is
    certain to be exceeded there however it is set, and the whole foot is
    read as one enormous peak. Measured on the round-104 fixture: a real
    peak is 1.9% of the scale without the allowance and 29.6% with it."""
    x = np.linspace(0.0, 20.0, 4000)
    foot = (6000.0 * np.maximum(x, 1e-6) ** -0.8) * (
        1.0 - np.exp(-(np.maximum(x, 0.0) / 0.05) ** 3))
    y = foot + 200.0 + sum(
        900.0 * np.exp(-0.5 * ((x - c) / 0.05) ** 2) for c in (6.0, 9.0, 13.0))

    def share(tail):
        corrected, _e = bg.subtract_rolling(x, y, tail=tail)
        return _height_at(x, corrected, 6.0, 0.3) / float(corrected.max())

    assert share(0.0) < 0.05, "without it the foot swamps the pattern"
    assert share(bg.DEFAULT_TAIL) > 0.25
    # ...and it costs an ORDINARY pattern almost nothing, because at 30
    # degrees the extra allowance is 1.5/30 per degree and does not bite
    xf, flat, _t = _pattern(peaks=[(30.0, 2000, 0.1)])
    with_tail = _height_at(xf, bg.subtract_rolling(xf, flat)[0], 30.0)
    without = _height_at(xf, bg.subtract_rolling(xf, flat, tail=0.0)[0], 30.0)
    assert with_tail > 0.95 * without


def test_smoothing_is_what_stops_NOISE_reading_as_a_slope():
    """Without it the envelope sits on the bottom of the noise band, which
    is a systematic UNDERESTIMATE of the background - the corrected baseline
    then sits above zero everywhere instead of straddling it."""
    x, y, true = _pattern(peaks=[(30.0, 3000, 0.1)], noise=40.0)
    away = np.abs(x - 30.0) > 1.0
    raw = bg.rolling_background(x, y, smooth_points=1)
    smoothed = bg.rolling_background(x, y, smooth_points=9)
    assert float(np.mean(true[away] - raw[away])) > \
        float(np.mean(true[away] - smoothed[away])) > -1.0


def test_the_noise_is_read_off_the_SECOND_difference():
    """The first difference of a pattern with a steep foot under it is
    mostly signal; the second difference of any smooth curve is nearly
    zero, so what is left in it is noise."""
    x = np.linspace(1.0, 40.0, 4000)
    steep = 50000.0 * np.exp(-0.4 * x) + 100.0
    for sigma in (5.0, 50.0):
        y = steep + np.random.default_rng(1).normal(0, sigma, x.size)
        assert bg.point_noise(y) == pytest.approx(sigma, rel=0.15)


# ------------------------------------------- the beam stop, and the trim
def test_a_scan_that_never_reaches_the_shadow_is_left_ALONE():
    """The regression this fix is for. `beam_stop_edge` answered with the
    in-window maximum, so on Christian's own i15-1-84514 - which starts at
    373 counts and climbs for a whole degree, because the stop is outside
    the recorded range - it returned 1.20 degrees, the tallest BRAGG PEAK in
    the pattern, and the trim then threw away every point below it."""
    x = np.linspace(0.0, 6.0, 601)
    climbing = 400.0 + 3200.0 * (x / 6.0) + 9000.0 * np.exp(
        -0.5 * ((x - 1.2) / 0.03) ** 2)
    assert bg.beam_stop_edge(x, climbing) == pytest.approx(0.0)
    kept_x, kept_y, start = bg.trim_below(x, climbing)
    assert start == pytest.approx(0.0) and kept_x.size == x.size
    # ...while a real shadow is still found and dropped
    shadow = np.where(x < 0.08, 8000 + 2e6 * x ** 2,
                      1400.0 / np.maximum(x, 0.08))
    assert bg.beam_stop_edge(x, shadow) == pytest.approx(0.08, abs=0.011)
    kept_x, _y, start = bg.trim_below(x, shadow)
    assert start == pytest.approx(0.08, abs=0.011)
    assert float(kept_x.min()) >= 0.07

    # a stated angle always wins over the search
    kept_x, _y, start = bg.trim_below(x, shadow, start=0.5)
    assert start == 0.5 and float(kept_x.min()) >= 0.5


def test_a_pattern_too_short_to_trim_is_returned_whole():
    x = np.linspace(0.0, 1.0, 6)
    y = np.array([10.0, 900.0, 500.0, 300.0, 200.0, 150.0])
    kept_x, kept_y, _s = bg.trim_below(x, y, start=0.9)
    assert kept_x.size == x.size and kept_y.size == y.size


def test_the_reader_refuses_an_obvious_mis_drop_and_nothing_else():
    """Extension only, and a list of what to REFUSE: the text formats have
    no standard and a pattern turns up under .txt and half a dozen house
    extensions, so a whitelist would refuse real data."""
    for name in ("scan.xy", "scan.xye", "scan.dat", "scan.txt", "scan.raw",
                 "scan.brml", "scan.csv", "house_format.q01"):
        assert pxrdfile.looks_like_pattern(name), name
    for name in ("mol.xyz", "crystal.cif", "project.molom", "shot.png",
                 "paper.pdf", "run.py"):
        assert not pxrdfile.looks_like_pattern(name), name


# -------------------------------------------------------------- the window
def _write(tmp_path, name="scan", peaks=((30.0, 3000.0),)):
    x = np.linspace(5.0, 60.0, 1800)
    y = np.full_like(x, 250.0)
    for centre, height in peaks:
        y = y + height * np.exp(-0.5 * ((x - centre) / 0.06) ** 2)
    path = tmp_path / (name + ".xy")
    path.write_text("".join("%.4f %.3f\n" % (a, b) for a, b in zip(x, y)),
                    encoding="utf-8")
    return str(path)


def test_a_measured_pattern_can_be_DROPPED_on_the_window(bench, tmp_path):
    """Christian: "I want drag and drop into the PXRD window to work with
    data files containing diffraction data.\""""
    pytest.importorskip("PySide6")
    from PySide6.QtCore import QMimeData, QPoint, QUrl, Qt
    from PySide6.QtGui import QDragEnterEvent, QDropEvent
    w = bench._pxrd_window
    good = [_write(tmp_path, "one"), _write(tmp_path, "two")]
    structure = tmp_path / "mol.xyz"
    structure.write_text("1\n\nC 0 0 0\n", encoding="utf-8")

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(p) for p in good + [str(structure)]])
    assert len(w.dropped_patterns(mime)) == 2, "the .xyz is not a pattern"

    enter = QDragEnterEvent(QPoint(10, 10), Qt.CopyAction, mime,
                            Qt.LeftButton, Qt.NoModifier)
    w.dragEnterEvent(enter)
    assert enter.isAccepted()
    drop = QDropEvent(QPoint(10, 10), Qt.CopyAction, mime,
                      Qt.LeftButton, Qt.NoModifier)
    w.dropEvent(drop)
    assert [e.name for e in w.measured] == ["one", "two"], \
        "several at once, and the structure file was not one of them"

    # a drop carrying nothing readable is refused rather than swallowed
    only = QMimeData()
    only.setUrls([QUrl.fromLocalFile(str(structure))])
    ev = QDragEnterEvent(QPoint(10, 10), Qt.CopyAction, only, Qt.LeftButton,
                         Qt.NoModifier)
    w.dragEnterEvent(ev)
    assert not ev.isAccepted()


def test_one_unreadable_file_does_not_cost_the_others(bench, tmp_path):
    w = bench._pxrd_window
    junk = tmp_path / "notes.txt"
    junk.write_text("this is prose, not a diffractogram\n", encoding="utf-8")
    w.load_measured_files([_write(tmp_path, "good"), str(junk)])
    assert [e.name for e in w.measured] == ["good"]
    assert "Could not read" in w.note.text() and "notes.txt" in w.note.text()


def test_the_settings_dialog_redraws_AS_THE_KNOBS_MOVE(bench, tmp_path):
    """Christian: "Changing the parameters in the settings where the
    settings for bg subtraction live, should update the plot immediately:
    Direct when values are changed via the arrows and after hitting enter to
    confirm when something is typed in a text box."

    The two halves are one Qt property apart - `setKeyboardTracking(False)`
    emits for the step arrows at once and for typed text only on Enter or
    focus-out - so what is pinned here is the BEHAVIOUR rather than the
    property.
    """
    pytest.importorskip("PySide6")
    from molom.ui import pxrd_panel
    w = bench._pxrd_window
    w.load_measured(_write(tmp_path))
    entry = w.measured[0]
    calls = []
    dlg = pxrd_panel.MeasuredOptions(w, entry, on_change=lambda: calls.append(1))

    dlg.background.setChecked(True)
    assert entry.background is True and len(calls) == 1
    dlg.bg_slope.setValue(0.8)
    assert entry.bg_slope == pytest.approx(0.8) and len(calls) == 2
    dlg.bg_smooth.setValue(9)
    assert entry.bg_smooth == 9 and len(calls) == 3

    # typed text waits for Enter
    before = len(calls)
    dlg.wavelength.setText("0.16")
    dlg.wavelength.setText("0.161699")
    assert len(calls) == before, "a half-typed number is not a value"
    dlg.wavelength.editingFinished.emit()
    assert len(calls) == before + 1
    assert entry.wavelength == pytest.approx(0.161699)


def test_cancel_puts_back_what_the_dialog_opened_with(bench, tmp_path):
    """It has to: a dialog that edits as it goes has already changed the
    trace a dozen times by the time Cancel is pressed."""
    pytest.importorskip("PySide6")
    from molom.ui import pxrd_panel
    w = bench._pxrd_window
    w.load_measured(_write(tmp_path))
    entry = w.measured[0]
    entry.scale = 1.25
    dlg = pxrd_panel.MeasuredOptions(w, entry)
    dlg.background.setChecked(True)
    dlg.bg_slope.setValue(0.4)
    dlg.scale.setValue(3.0)
    assert entry.background is True and entry.scale == pytest.approx(3.0)
    dlg.reject()
    assert entry.background is False
    assert entry.bg_slope == pytest.approx(bg.DEFAULT_SLOPE)
    assert entry.scale == pytest.approx(1.25)


def test_every_setting_a_trace_has_is_one_cancel_can_restore():
    """`MeasuredTrace.SETTINGS` is derived from `__slots__` rather than
    listed again, because a knob added to one and not the other is a knob
    Cancel silently keeps. Pinned so it stays derived."""
    pytest.importorskip("PySide6")
    from molom.ui import pxrd_panel
    assert set(pxrd_panel.MeasuredTrace.SETTINGS) == \
        set(pxrd_panel.MeasuredTrace.__slots__) - {"data"}


def test_the_model_chooses_which_rows_the_dialog_shows(bench, tmp_path):
    """Both models are on one form, so the alternative is a page of controls
    of which half do nothing - and a live-looking control that is not in the
    path is the thing this project keeps finding as a bug."""
    pytest.importorskip("PySide6")
    from molom.ui import pxrd_panel
    w = bench._pxrd_window
    w.load_measured(_write(tmp_path))
    dlg = pxrd_panel.MeasuredOptions(w, w.measured[0])
    form = dlg._form

    # the model's own parameters go with the tick...
    dlg.background.setChecked(False)
    for widget in (dlg.bg_slope, dlg.bg_tail, dlg.bg_smooth, dlg.bg_order):
        assert not form.isRowVisible(widget) and not widget.isEnabled()
    # ...but the low-angle rows do not, because they are in the path whether
    # or not a background is being subtracted, and a control that acts while
    # its row is hidden is the same bug as a dead control that is shown
    assert form.isRowVisible(dlg.trim) and dlg.trim.isEnabled()
    assert form.isRowVisible(dlg.bg_method)

    dlg.background.setChecked(True)
    dlg.bg_method.setCurrentIndex(0)                   # rolling
    for widget in (dlg.bg_slope, dlg.bg_tail, dlg.bg_smooth, dlg.trim):
        assert form.isRowVisible(widget), widget
    for widget in (dlg.bg_order, dlg.low_angle, dlg.low_cutoff):
        assert not form.isRowVisible(widget), widget
    assert form.isRowVisible(dlg.low_start)

    dlg.bg_method.setCurrentIndex(1)                   # chebyshev
    for widget in (dlg.bg_order, dlg.low_angle, dlg.low_cutoff):
        assert form.isRowVisible(widget), widget
    for widget in (dlg.bg_slope, dlg.bg_tail, dlg.bg_smooth, dlg.trim):
        assert not form.isRowVisible(widget), widget

    # "Ignore below" is live only while something is actually dropping points
    assert not dlg.low_start.isEnabled()
    dlg.low_angle.setChecked(True)
    assert dlg.low_start.isEnabled()


def test_the_curve_follows_the_model_that_was_chosen(bench, tmp_path):
    """And the power-law tail belongs to the Chebyshev alone: the rolling
    walk has its own allowance for a small-angle foot and wants no second
    model fitted underneath it."""
    w = bench._pxrd_window
    x = np.linspace(0.2, 40.0, 3000)
    y = 4000.0 * x ** -0.8 + 150.0 + 2500.0 * np.exp(
        -0.5 * ((x - 12.0) / 0.06) ** 2)
    path = tmp_path / "foot.xy"
    path.write_text("".join("%.4f %.3f\n" % (a, b) for a, b in zip(x, y)),
                    encoding="utf-8")
    w.load_measured(str(path))
    entry = w.measured[0]

    raw_x, raw_y = w.measured_curve(entry)
    assert raw_x[int(np.argmax(raw_y))] < 1.0, \
        "raw, the foot is the tallest thing in the pattern"

    entry.background = True
    entry.bg_method = bg.METHOD_ROLLING
    roll_x, roll_y = w.measured_curve(entry)
    assert roll_x[int(np.argmax(roll_y))] == pytest.approx(12.0, abs=0.2), \
        "the walk takes the foot off and leaves the peak on top"

    entry.bg_method = bg.METHOD_CHEBYSHEV
    entry.low_angle = True
    cheb_x, cheb_y = w.measured_curve(entry)
    assert cheb_x[int(np.argmax(cheb_y))] == pytest.approx(12.0, abs=0.2)
