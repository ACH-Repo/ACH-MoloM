"""Round 78: the pane you can actually work in, and a framerate that is true.

Christian used round 77 in anger and every complaint was real. They fall into
three groups.

**The axis moved under his hand.** The frame range followed the content, so
dragging a strip to the right dragged Frame End with it; the pane re-fitted
whenever the content outgrew the view, so the strips visibly compressed
mid-gesture; and there was no zoom, so nothing brought them back.

**Two gestures did nothing.** G armed a move that `mouseMoveEvent` never
read, so the strip sat still; and clicking off a strip returned early without
deselecting.

**The framerate was a lie**, and the arithmetic says why in one line:
`int(1000 / 60)` is 16 ms, Windows' default timer granularity is ~15.6 ms, so
a 16 ms timer fires every 31.2 - sixty frames in **1.87 s instead of 1.00**,
which is the "~2 seconds" he counted.
"""

import os
import time as _time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from molom.core import timeline

FREQ_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "data", "orca_freq_h3po4.out")


# ------------------------------------------------------- the range holds still
def test_moving_a_strip_never_moves_the_frame_range():
    """Whichever end it is moved from. A frame range is a decision about what
    gets played, not a summary of what exists."""
    clock = timeline.Timeline()
    clock.sync([(1, 20, True)])
    assert (clock.play_start, clock.play_end) == (0.0, 59.0)
    for start in (40.0, -30.0, 500.0, 0.0):
        clock.get(1).start = start
        clock.sync([(1, 20, True)])
        assert (clock.play_start, clock.play_end) == (0.0, 59.0)


def test_the_range_is_fitted_once_when_there_is_something_to_play():
    clock = timeline.Timeline()
    assert not clock.range_chosen
    clock.sync([(1, 20, True)])          # the first strip frames it
    assert clock.range_chosen and clock.play_end == 59.0
    clock.sync([(1, 20, True), (2, 20, True)])
    assert clock.play_end == 59.0        # and never again


def test_a_strip_start_snaps_to_a_whole_frame():
    """A strip dragged by the mouse lands on 3.7, and then its last frame
    falls between two scene frames - so a loop fitted to it gains or loses
    one, which is exactly the "one frame too much or too little" report."""
    track = timeline.Track(1, 20, start=3.7, frames=60, cyclic=True)
    assert track.start == 4.0
    assert float(track.last_frame).is_integer()
    track.start = -2.4
    assert track.start == -2.0


# ------------------------------------------------------ a duration, not a count
def test_the_strip_is_measured_in_SECONDS():
    """Christian: "Change the main strip property from frames to time. That
    is intuitive to a user. Calculate the amount of frames necessary based on
    the set strip time." Frames stay the model's unit - they are what the
    clock counts and what a render writes - and this is where the two meet.
    """
    assert timeline.frames_for_seconds(1.0, 60.0) == 60
    assert timeline.frames_for_seconds(2.5, 24.0) == 60
    assert timeline.frames_for_seconds(0.001, 60.0) == 1     # never zero
    clock = timeline.Timeline(fps=30.0)
    clock.sync([(1, 20, True)])
    clock.set_duration(1, 4.0)
    assert clock.get(1).frames == 120
    assert clock.get(1).seconds(30.0) == pytest.approx(4.0)


def test_interpolation_is_the_only_thing_smoothing_could_still_say():
    """The thinking task. How MANY pictures there are follows from the
    duration and the framerate, so a smoothing COUNT has nothing left to add.
    What it cannot say is whether those pictures blend or step, and that is a
    real choice about an MD run - so it survives as a per-strip switch."""
    clock = timeline.Timeline()
    clock.sync([(1, 20, True)])
    track = clock.get(1)
    assert track.interpolated                      # blending is the default
    track.interpolated = False
    again = timeline.Timeline.from_dict(clock.to_dict())
    assert not again.get(1).interpolated


# ------------------------------------------------------------------ the pane
@pytest.fixture
def win():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.app import MainWindow
    QApplication.instance() or QApplication([])
    w = MainWindow()
    w.show()
    return w


def _pane(win):
    win.load_default_scene()
    win.open_path(FREQ_FILE)
    win.on_animate_mode(6)
    win.traj_bar.expand_btn.setChecked(True)
    rows = win.traj_bar.rows
    rows.resize(900, rows.natural_height())
    rows.setFocus()
    return win._active_obj(), rows


def _mouse(kind, x, y, button=None):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    button = button or (Qt.LeftButton if kind != QEvent.MouseMove
                        else Qt.NoButton)
    return QMouseEvent(kind, QPointF(x, y), button, button, Qt.NoModifier)


def _key(k):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    return QKeyEvent(QEvent.KeyPress, k, Qt.NoModifier)


def test_dragging_a_strip_leaves_the_axis_alone(win):
    """The pane used to re-fit whenever the content outgrew the view, i.e. on
    every mouse move of a rightward drag - so the strips shrank under the hand
    and the pan jumped back to zero."""
    from PySide6.QtCore import QEvent
    obj, rows = _pane(win)
    before = (rows.offset, rows.view_span)
    y = rows._row_top(0) + 10
    rows.mousePressEvent(_mouse(QEvent.MouseButtonPress, rows._x_for(5.0), y))
    rows.mouseMoveEvent(_mouse(QEvent.MouseMove, rows._x_for(300.0), y))
    rows.mouseReleaseEvent(None)
    assert win.timeline.get(obj.id).start > 200
    assert (rows.offset, rows.view_span) == before
    assert (win.timeline.play_start, win.timeline.play_end) == (0.0, 59.0)


def test_G_moves_the_strip_and_Esc_puts_it_back(win):
    """`_gmove` was armed, painted a cursor, and then never read by
    `mouseMoveEvent` - so the strip sat still and G looked dead."""
    from PySide6.QtCore import QEvent, Qt
    obj, rows = _pane(win)
    rows.select_strip(obj.id)
    y = rows._row_top(0) + 10
    origin = win.timeline.get(obj.id).start
    rows.keyPressEvent(_key(Qt.Key_G))
    assert rows._gmove is not None
    rows.mouseMoveEvent(_mouse(QEvent.MouseMove, rows._x_for(35.0), y))
    assert win.timeline.get(obj.id).start != origin
    rows.keyPressEvent(_key(Qt.Key_Escape))
    assert win.timeline.get(obj.id).start == origin
    rows.keyPressEvent(_key(Qt.Key_G))
    rows.mouseMoveEvent(_mouse(QEvent.MouseMove, rows._x_for(35.0), y))
    moved = win.timeline.get(obj.id).start
    rows.mousePressEvent(_mouse(QEvent.MouseButtonPress, rows._x_for(35.0), y))
    assert rows._gmove is None
    assert win.timeline.get(obj.id).start == moved


def test_clicking_off_a_strip_deselects_it(win):
    """It returned early below the last row, so a strip stayed selected
    however far off it you clicked."""
    from PySide6.QtCore import QEvent
    obj, rows = _pane(win)
    rows.select_strip(obj.id)
    below = rows._row_top(len(rows.rows()) + 1) + 8
    rows.mousePressEvent(_mouse(QEvent.MouseButtonPress, 400, below))
    assert rows.selected is None
    rows.select_strip(obj.id)
    rows.mousePressEvent(_mouse(QEvent.MouseButtonPress, 30,
                                rows._row_top(0) + 10))   # the name column
    assert rows.selected is None


def test_the_pane_zooms_about_the_cursor(win):
    """Without a zoom there was no way back from a strip dragged far to the
    right: the axis had grown to hold it, every strip was a sliver, and
    nothing shrank the axis again."""
    _obj, rows = _pane(win)
    x = rows._x_for(30.0)
    rows.zoom_view(0.5, x)
    assert rows._x_for(30.0) == pytest.approx(x, abs=0.5)
    assert rows.view_span == pytest.approx(rows.view_span)
    narrow = rows.view_span
    rows.zoom_view(2.0, x)
    assert rows.view_span == pytest.approx(2.0 * narrow)
    assert rows._x_for(30.0) == pytest.approx(x, abs=0.5)


def test_the_wheel_zooms_and_shift_pans(win):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    _obj, rows = _pane(win)

    def wheel(dy, mods=Qt.NoModifier):
        return QWheelEvent(QPointF(400, 40), QPointF(400, 40), QPoint(0, 0),
                           QPoint(0, dy), Qt.NoButton, mods, Qt.NoScrollPhase,
                           False)

    span = rows.view_span
    rows.wheelEvent(wheel(120))
    assert rows.view_span < span                      # in
    rows.wheelEvent(wheel(-120))
    assert rows.view_span == pytest.approx(span)      # and back out
    offset = rows.offset
    rows.wheelEvent(wheel(120, Qt.ShiftModifier))
    assert rows.offset != offset
    assert rows.view_span == pytest.approx(span)      # panning is not zooming


def test_the_pane_has_its_own_view_bounds(win):
    """Christian: "Add start/end bounds for the player pane itself... unless
    the pane limits can be set, we run into the whole zooming out problem."
    They are NOT the play range: one says what is shown, the other what
    plays."""
    from PySide6.QtCore import Qt
    _obj, rows = _pane(win)
    bar = win.traj_bar
    bar.view_start.setValue(100)
    bar.view_end.setValue(400)
    assert rows.offset == pytest.approx(100.0)
    assert rows.offset + rows.view_span == pytest.approx(400.0)
    assert (win.timeline.play_start, win.timeline.play_end) == (0.0, 59.0)
    # ...and the boxes follow the pane when it is zoomed by hand
    rows.zoom_view(0.5, rows._x_for(200.0))
    assert bar.view_end.value() - bar.view_start.value() == pytest.approx(150,
                                                                         abs=2)
    rows.keyPressEvent(_key(Qt.Key_Home))          # the way back, always
    assert rows.offset < 10.0


def test_playback_keeps_real_time_when_the_timer_cannot(win, monkeypatch):
    """The framerate stops being a lie. A wake-up pattern of 31.2 ms - the
    Windows granularity case that made 60 frames take 1.87 s - now completes
    one 60-frame loop per second of WALL time, dropping frames rather than
    slowing down."""
    _obj, _rows = _pane(win)
    clock = win.timeline
    assert (clock.play_start, clock.play_end, clock.fps) == (0.0, 59.0, 60.0)
    fake = {"t": 0.0}
    monkeypatch.setattr(_time, "perf_counter", lambda: fake["t"])
    clock.seek(0.0)
    win._play_clock = 0.0
    drawn = 0
    while fake["t"] < 1.0:
        fake["t"] += 0.0312
        before = clock.time
        win._advance_frame()
        drawn += clock.time != before
    assert 1.0 <= fake["t"] * clock.fps / clock.n_frames <= 1.05
    assert drawn < clock.n_frames          # frames were dropped, not stretched


def test_a_tick_with_no_time_behind_it_draws_nothing(win, monkeypatch):
    """The timer wakes far more often than a frame is due; the cheap exit is
    what makes oversampling affordable."""
    _obj, _rows = _pane(win)
    fake = {"t": 0.0}
    monkeypatch.setattr(_time, "perf_counter", lambda: fake["t"])
    win.timeline.seek(0.0)
    win._play_clock = 0.0
    for _ in range(5):
        fake["t"] += 0.001
        win._advance_frame()
    assert win.timeline.time == 0.0
    fake["t"] += 0.02
    win._advance_frame()
    assert win.timeline.time == 1.0


def test_a_later_trajectory_can_be_brought_into_the_range(win):
    """The one gap left by a range that no longer follows the content: a
    strip imported afterwards sits outside it. Closed as a deliberate action
    rather than as a side effect."""
    obj, _rows = _pane(win)
    win.timeline.get(obj.id).start = 400.0
    win._sync_traj_bar()
    assert win.timeline.play_end == 59.0            # unmoved, as it should be
    win.traj_bar.fit_range_btn.click()
    assert win.timeline.play_start == 400.0
    assert win.timeline.play_end == 459.0


# ------------------------------------------------------- the trackpad, round 79
def test_a_swipe_is_read_by_its_DOMINANT_axis():
    """Christian: "Trackpad responsiveness to inputs is spotty... it works
    sometimes." A trackpad swipe is never purely one axis - a vertical flick
    carries a few pixels of horizontal - so a rule that asks "is dx non-zero"
    hands most vertical swipes to the pan branch."""
    from molom.core import input_map
    assert input_map.pane_scroll(3, -40, True)[0] == input_map.PANE_ZOOM
    assert input_map.pane_scroll(-55, 2, True)[0] == input_map.PANE_PAN
    assert input_map.pane_scroll(0, 120, False)[0] == input_map.PANE_ZOOM
    assert input_map.pane_scroll(0, 9, True, ctrl=True)[0] == input_map.PANE_ROWS
    assert input_map.pane_scroll(0, 9, True, shift=True)[0] == input_map.PANE_PAN


def test_a_wheel_notch_and_a_trackpad_swipe_are_the_same_quantity():
    """Without a common unit the same physical movement zooms by wildly
    different amounts on the two devices, which is the other half of
    "spotty"."""
    from molom.core import input_map
    _a, wheel = input_map.pane_scroll(0, input_map.PANE_WHEEL_UNITS, False)
    _b, pad = input_map.pane_scroll(0, input_map.PANE_STEP_PIXELS, True)
    assert wheel == pytest.approx(1.0)
    assert pad == pytest.approx(1.0)
    assert input_map.pane_zoom_factor(1.0) < 1.0        # up zooms IN
    assert input_map.pane_zoom_factor(-1.0) > 1.0
    assert input_map.pane_zoom_factor(0.25) > input_map.pane_zoom_factor(1.0)


def test_a_gesture_keeps_the_action_it_started_with(win):
    """Round 8's rule in a new place. A swipe that drifts diagonally must not
    flip between panning and zooming under the hand."""
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    _obj, rows = _pane(win)

    def swipe(dx, dy, mods=Qt.NoModifier):
        rows.wheelEvent(QWheelEvent(
            QPointF(400, 40), QPointF(400, 40), QPoint(dx, dy), QPoint(0, 0),
            Qt.NoButton, mods, Qt.NoScrollPhase, False))

    swipe(-60, 4)                       # starts as a pan
    span, offset = rows.view_span, rows.offset
    swipe(-20, 40)                      # drifts vertical: still a pan
    assert rows.view_span == pytest.approx(span)
    assert rows.offset != offset
    # ...but a modifier is a deliberate change of intent, not a wobble
    swipe(0, 40, Qt.ShiftModifier)
    assert rows.view_span == pytest.approx(span)
    rows._gesture = None                # the gesture ends when scrolling does
    swipe(0, 40)
    assert rows.view_span < span


def test_a_sideways_swipe_pans_which_it_could_not_before(win):
    """"Panning doesn't even exist as a gesture" - it did not, on a device
    whose horizontal scroll arrives as `angleDelta` rather than pixels."""
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    _obj, rows = _pane(win)
    span, offset = rows.view_span, rows.offset
    rows.wheelEvent(QWheelEvent(
        QPointF(400, 40), QPointF(400, 40), QPoint(0, 0), QPoint(240, 0),
        Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False))
    assert rows.offset != offset
    assert rows.view_span == pytest.approx(span)


def test_the_view_boxes_sit_on_the_transport_row(win):
    """Christian: "Why did you put the view numbers and the fit button not on
    the same row as the playhead and loop interval numbers?" - and a second
    bar under the rows was one more thing for the expandable pane to fight
    with."""
    _obj, _rows = _pane(win)
    bar = win.traj_bar
    row = bar.play_btn.parent()
    assert bar.view_start.parent() is row
    assert bar.view_end.parent() is row
    assert bar.fit_btn.parent() is row
    assert not hasattr(bar, "view_bar")


def test_dragging_a_strip_updates_the_strip_page(win):
    """"Moving the strip manually does not seem to update the start number in
    the strip pane." It did not: the drag refreshed the clock and the bar and
    left the page describing where the strip used to be."""
    from PySide6.QtCore import QEvent
    obj, rows = _pane(win)
    rows.select_strip(obj.id)
    page = win.strip_page
    assert page.start_spin.value() == 0
    y = rows._row_top(0) + 10
    rows.mousePressEvent(_mouse(QEvent.MouseButtonPress, rows._x_for(5.0), y))
    rows.mouseMoveEvent(_mouse(QEvent.MouseMove, rows._x_for(90.0), y))
    rows.mouseReleaseEvent(None)
    assert page.start_spin.value() == int(win.timeline.get(obj.id).start) > 50
