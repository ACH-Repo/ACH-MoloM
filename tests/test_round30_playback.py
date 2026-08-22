"""Round 30: loop limits, sampling the extremes, and the ∿ page.

Christian's playback spec (2026-08-03) separated three things the player had
muddled into one number - frames, images and seconds - and round 77 then
collapsed two of them back together on purpose: an IMAGE and a scene FRAME
are now the same thing, `fps` is scene frames per second, and the
subdivision that used to be global (`smoothing`) is each strip's own frame
count. See `tests/test_round77_player.py` for that half.

What is round 30's and still stands is here: the looping interval, the rule
that a generated mode must be sampled on its extremes, and the ∿ page being
reachable at all.
"""

import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from molom.core import timeline, vibrations

FREQ_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "data", "orca_freq_h3po4.out")


def _traj(name, n, axis=0, step=0.5):
    from molom.core.structure import Structure
    s = Structure.from_atoms([("C", 0.0, 0.0, 0.0), ("O", 1.2, 0.0, 0.0)],
                             name=name)
    for k in range(1, n):
        frame = s.frames[0].copy()
        frame[:, axis] += k * step
        s.frames.append(frame)
    return s


# ------------------------------------------------------- one tick, one frame
def test_one_frame_per_tick_at_the_chosen_framerate():
    """Round 30's claim, in round 77's units: the timer runs at `fps` and
    each tick is exactly one picture. There is no second factor."""
    tl = timeline.Timeline(fps=30.0)
    tl.set_track(1, 101, frames=101)
    for _ in range(30):
        tl.advance_frames(1)
    assert tl.time == pytest.approx(30.0)
    assert tl.time / tl.fps == pytest.approx(1.0)


def test_the_loop_runs_between_the_limits():
    tl = timeline.Timeline()
    tl.end = timeline.LOOP
    tl.set_track(1, 21, frames=21)      # 0 .. 20
    tl.set_range(5.0, 9.0)
    tl.seek(5.0)
    for _ in range(15):
        tl.step_frames(1.0)
        assert 5.0 - 1e-9 <= tl.time <= 9.0 + 1e-9
    # The interval is INCLUSIVE (round 77), so 5-9 is FIVE frames and fifteen
    # steps land back on the start. The old exclusive wrap skipped frame 9.
    assert tl.time == pytest.approx(5.0)
    assert tl.n_frames == 5


def test_seeking_outside_the_limits_parks_on_them():
    """Scrubbing must not teleport: a wrap under the cursor is unreadable."""
    tl = timeline.Timeline()
    tl.set_track(1, 21, frames=21)
    tl.set_range(5.0, 9.0)
    assert tl.seek(0.0) == pytest.approx(5.0)
    assert tl.seek(100.0) == pytest.approx(9.0)


def test_limits_that_cross_are_swapped_not_rejected():
    tl = timeline.Timeline()
    tl.set_track(1, 21, frames=21)
    tl.set_range(12.0, 3.0)
    assert (tl.play_start, tl.play_end) == pytest.approx((3.0, 12.0))


def test_an_open_end_follows_a_growing_scene():
    """range_end=None means 'to the end', so appending frames keeps them in
    the loop instead of silently cutting them off."""
    tl = timeline.Timeline()
    tl.set_track(1, 11, frames=11)
    tl.set_range(0.0, None)
    assert tl.play_end == pytest.approx(10.0)
    tl.set_track(1, 31, frames=31)
    assert tl.play_end == pytest.approx(30.0)


def test_the_clock_round_trips_with_its_new_settings():
    tl = timeline.Timeline(fps=24.0)
    tl.set_track(1, 21, frames=21)
    tl.set_range(2.0, 8.0)
    tl.seek(5.0)
    again = timeline.Timeline.from_dict(tl.to_dict())
    assert again.fps == pytest.approx(24.0)
    assert (again.play_start, again.play_end) == pytest.approx((2.0, 8.0))
    assert again.time == pytest.approx(5.0)
    assert again.get(1).frames == 21


# -------------------------------------------------------- normal modes
def test_sampling_always_reaches_both_extremes():
    """A mode sampled at n points hits +A and -A only when 4 divides n. With
    n = 6 the animation used to peak at 0.87 A of a requested 1.0 A, so the
    turning points of the coordinate — the thing you are looking at — never
    appeared."""
    modes = vibrations.parse_orca_frequencies(
        open(FREQ_FILE, encoding="utf-8", errors="replace").read())
    rest = np.array([[0.0, 0.0, 0.0]] * modes[0].displacements.shape[0])
    for requested in (4, 6, 7, 10, 20, 33):
        frames = vibrations.mode_frames(rest, modes[6], amplitude=1.0,
                                        n_frames=requested)
        peaks = [float(np.max(np.linalg.norm(f - rest, axis=1)))
                 for f in frames]
        assert max(peaks) == pytest.approx(1.0, abs=1e-9)
        assert len(frames) % 4 == 0


def test_period_frames_snaps_predictably():
    assert vibrations.period_frames(20) == 20      # a good count is untouched
    assert vibrations.period_frames(6) == 8        # half-way rounds UP
    assert vibrations.period_frames(10) == 12
    assert vibrations.period_frames(1) == 4        # never degenerate
    assert vibrations.period_frames(0) == 4


def test_a_mode_still_loops_seamlessly():
    """One whole period, so the last frame steps back onto the first."""
    modes = vibrations.parse_orca_frequencies(
        open(FREQ_FILE, encoding="utf-8", errors="replace").read())
    rest = np.zeros((modes[0].displacements.shape[0], 3))
    frames = vibrations.mode_frames(rest, modes[6], n_frames=20)
    assert frames[0] == pytest.approx(rest)
    assert len(frames) == 20


# ------------------------------------------------------------------ the app
@pytest.fixture
def win():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.app import MainWindow
    QApplication.instance() or QApplication([])
    w = MainWindow()
    w.show()
    return w


def test_the_bar_reads_in_scene_frames(win):
    win._install_structure(_traj("t", 5))
    win._sync_traj_bar()
    win._apply_timeline()
    # A 5-frame trajectory gets the default 60-frame strip, so the range is
    # 0-59 and the readout counts scene frames, not a second unit.
    assert win.traj_bar.label.text().startswith("0 / 59")
    assert win.traj_bar.fps_spin.suffix() == " fps"


def test_there_is_no_smooth_tick_box_any_more(win):
    assert not hasattr(win.traj_bar, "interp_check")


def test_the_bar_carries_three_numbers_and_no_more(win):
    """Christian's brief: "The global settings should only be Frame Start,
    Frame End, Framerate." Smoothing is a strip property now, so there is
    nowhere on the bar to set it."""
    from PySide6.QtWidgets import QSpinBox
    bar = win.traj_bar
    assert not hasattr(bar, "smooth_spin")
    assert not hasattr(bar, "smoothing_changed")
    playback = {id(bar.start_spin), id(bar.end_spin), id(bar.fps_spin)}
    viewing = {id(bar.view_start), id(bar.view_end)}
    row = bar.play_btn.parent()          # the transport row itself
    spins = {id(s) for s in row.findChildren(QSpinBox)}
    assert spins == playback | viewing
    # Round 78 put the View boxes on the same row (Christian asked why they
    # were not), and they are still not a fourth playback number: they say
    # what the PANE SHOWS and reach the clock through nothing at all.
    assert not viewing & playback
    win.traj_bar.view_start.setValue(1000)
    assert (win.timeline.play_start, win.timeline.play_end) == (0.0, 0.0)
    assert win.timeline.fps == pytest.approx(60.0)


def test_the_frame_range_is_on_the_bar(win):
    win._install_structure(_traj("t", 5))
    win._sync_traj_bar()
    bar = win.traj_bar
    assert bar.start_spin.value() == 0
    assert bar.end_spin.value() == 59            # inclusive, 60 frames
    assert win.timeline.n_frames == 60
    bar.end_spin.setValue(20)
    assert win.timeline.play_end == pytest.approx(20.0)
    assert win.timeline.play_start == pytest.approx(0.0)


def test_playing_stays_inside_the_limits(win):
    win._install_structure(_traj("t", 9))
    win._sync_traj_bar()
    win.timeline.end = timeline.LOOP
    win.traj_bar.start_spin.setValue(1)
    win.traj_bar.end_spin.setValue(3)
    for _ in range(200):
        win._advance_frame()
        assert 1.0 - 1e-9 <= win.timeline.time <= 3.0 + 1e-9


def test_the_panel_does_not_push_its_own_defaults_back(win):
    """sync() writes every spin box; a programmatic write must not look like
    a user edit, or the panel overwrites the clock it is displaying."""
    win._install_structure(_traj("t", 5))
    win.timeline.fps = 17.0
    win.timeline.set_range(2.0, 7.0)
    win._sync_traj_bar()
    assert win.timeline.fps == pytest.approx(17.0)
    assert (win.timeline.play_start,
            win.timeline.play_end) == pytest.approx((2.0, 7.0))


# -------------------------------------------------- the ∿ page, reachable
def _freq_win(win):
    win.load_default_scene()
    win.open_path(FREQ_FILE)
    return win


def test_opening_a_freq_output_picks_up_its_modes(win):
    """It read the geometry and threw the modes away, so the page stayed
    grey with no hint why — Christian: 'which I still cannot select and look
    at btw'."""
    _freq_win(win)
    obj = win._active_obj()
    assert len(win._modes.get(obj.id, [])) == 24


def test_the_vibration_tab_can_always_be_opened(win):
    """A greyed square cannot say why it is greyed. The page explains
    itself instead."""
    tab = win.properties.buttons["vibrations"][0]
    assert tab.isEnabled()                     # plain scene, no FREQ data
    win.properties.show_page("vibrations")
    assert win.vibration_page.isEnabled()
    assert win.vibration_page.load_btn.isEnabled()


def _flush_rebake(win):
    """The re-bake is coalesced onto a timer; fire it now."""
    win._mode_rebake.stop()
    win._rebake_mode()


def test_frames_per_period_is_settable_per_freq_object(win):
    _freq_win(win)
    obj = win._active_obj()
    win.on_animate_mode(6)
    assert obj.structure.n_frames == vibrations.DEFAULT_PERIOD_FRAMES == 60
    win.vibration_page.frames_spin.setValue(40)
    assert win._mode_frames[obj.id] == 40
    _flush_rebake(win)
    assert obj.structure.n_frames == 40         # the playing mode re-bakes


def test_mode_settings_belong_to_the_object_not_the_card(win):
    """They were stored per object all along; the per-card sliders just
    reset themselves on every rebuild and made it look otherwise."""
    _freq_win(win)
    obj = win._active_obj()
    win.on_animate_mode(6)
    win.vibration_page.amp_spin.setValue(0.35)
    assert win._mode_amplitude[obj.id] == pytest.approx(0.35)
    win._sync_vibration_page()                  # a rebuild must not lose it
    assert win.vibration_page.amp_spin.value() == pytest.approx(0.35)
    assert win.vibration_page.frames_spin.value() == 60


def test_a_mode_plays_through_the_ordinary_scene_clock(win):
    _freq_win(win)
    obj = win._active_obj()
    win.on_animate_mode(6)
    track = win.timeline.get(obj.id)
    assert track.end == timeline.LOOP
    assert track.cyclic                       # a period, not a run
    # 60 samples over a 60-frame strip: one second at 60 fps, ending on 59,
    # which is Christian's stated default (round 77).
    assert win.timeline.duration == pytest.approx(59.0)
    assert win.traj_bar.isVisible()


def test_an_ordinary_file_is_not_scanned_for_modes(win, tmp_path):
    path = tmp_path / "plain.xyz"
    path.write_text("2\n\nC 0.0 0.0 0.0\nO 1.2 0.0 0.0\n", encoding="utf-8")
    win.open_path(str(path))
    assert win._modes == {}
