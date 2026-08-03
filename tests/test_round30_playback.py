"""Round 30: frames vs images vs seconds, loop limits, and the ∿ page.

Christian's playback spec (2026-08-03) separated three things the player had
muddled into one number:

  * FRAMES come from the input file and vary with the data;
  * IMAGES are what the player draws — `smoothing` per frame interval;
  * `fps` is IMAGES per second, and is global.

Plus: normal modes have no inherent frames, so the generated sampling must
always land on the extremes of the oscillation, and the count must be
settable per imported FREQ object — on a page that can actually be opened.
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


# --------------------------------------------------------- images vs frames
def test_smoothing_is_a_count_not_a_switch():
    """The old `Smooth` tick box could say whether to interpolate but not
    how much, which is the whole complaint."""
    tl = timeline.Timeline(smoothing=10)
    assert tl.smoothing == 10
    assert tl.step == pytest.approx(0.1)
    tl.smoothing = 1
    assert tl.step == pytest.approx(1.0)
    assert tl.smoothing >= 1            # never zero, never negative
    tl.smoothing = 0
    assert tl.smoothing == 1


def test_interpolate_still_reads_as_a_boolean():
    """Existing callers ask 'are we interpolating?' — that is just
    'is the subdivision greater than one?'."""
    tl = timeline.Timeline(smoothing=8)
    assert tl.interpolate
    tl.interpolate = False
    assert tl.smoothing == 1 and not tl.interpolate
    tl.interpolate = True
    assert tl.smoothing == 8            # the count it had is remembered


def test_one_image_per_tick_at_the_chosen_framerate():
    """30 fps with 10 images per frame = 3 source frames a second."""
    tl = timeline.Timeline(fps=30.0, smoothing=10)
    tl.set_track(1, 101)
    for _ in range(30):
        tl.advance_images(1)
    assert tl.time == pytest.approx(3.0)


def test_more_smoothing_at_a_fixed_framerate_plays_slower():
    """The consequence of `fps` meaning IMAGES per second, and worth pinning
    because it is the one thing about the two knobs that can surprise: twice
    as many images in the same second is half the trajectory per second —
    smoother AND slower, exactly like shooting video at 60 fps and playing it
    back at 30. Raise the framerate too if you want the original speed."""
    slow = timeline.Timeline(fps=30.0, smoothing=10)
    fine = timeline.Timeline(fps=30.0, smoothing=20)
    for tl in (slow, fine):
        tl.set_track(1, 101)
        tl.advance(1.0)                 # one second of wall clock
    assert slow.time == pytest.approx(3.0)
    assert fine.time == pytest.approx(1.5)
    # ...and both drew the same number of IMAGES in that second.
    assert slow.image_of(slow.time) == fine.image_of(fine.time) == 30

    matched = timeline.Timeline(fps=60.0, smoothing=20)
    matched.set_track(1, 101)
    matched.advance(1.0)
    assert matched.time == pytest.approx(slow.time)


def test_image_counts_follow_the_subdivision():
    tl = timeline.Timeline(smoothing=10)
    tl.set_track(1, 5)                  # 4 frame intervals
    assert tl.duration == pytest.approx(4.0)
    assert tl.n_images == 41            # 40 steps, plus the first image
    tl.smoothing = 1
    assert tl.n_images == 5             # just the frames themselves


def test_images_and_times_round_trip():
    tl = timeline.Timeline(smoothing=10)
    tl.set_track(1, 5)
    for image in (0, 7, 25, 40):
        assert tl.image_of(tl.time_of_image(image)) == image


# ------------------------------------------------------------- loop limits
def test_the_loop_runs_between_the_limits():
    tl = timeline.Timeline(smoothing=1)
    tl.end = timeline.LOOP
    tl.set_track(1, 21)                 # 0 .. 20
    tl.set_range(5.0, 9.0)
    tl.seek(5.0)
    for _ in range(12):
        tl.step_frames(1.0)
        assert 5.0 - 1e-9 <= tl.time <= 9.0 + 1e-9
    assert tl.time == pytest.approx(5.0)   # 12 steps over a span of 4


def test_seeking_outside_the_limits_parks_on_them():
    """Scrubbing must not teleport: a wrap under the cursor is unreadable."""
    tl = timeline.Timeline()
    tl.set_track(1, 21)
    tl.set_range(5.0, 9.0)
    assert tl.seek(0.0) == pytest.approx(5.0)
    assert tl.seek(100.0) == pytest.approx(9.0)


def test_limits_that_cross_are_swapped_not_rejected():
    tl = timeline.Timeline()
    tl.set_track(1, 21)
    tl.set_range(12.0, 3.0)
    assert (tl.play_start, tl.play_end) == pytest.approx((3.0, 12.0))


def test_an_open_end_follows_a_growing_scene():
    """range_end=None means 'to the end', so appending frames keeps them in
    the loop instead of silently cutting them off."""
    tl = timeline.Timeline()
    tl.set_track(1, 11)
    tl.set_range(0.0, None)
    assert tl.play_end == pytest.approx(10.0)
    tl.set_track(1, 31)
    assert tl.play_end == pytest.approx(30.0)


def test_limits_are_stored_in_frames_so_smoothing_cannot_move_them():
    tl = timeline.Timeline(smoothing=10)
    tl.set_track(1, 21)
    tl.set_range(4.0, 8.0)
    assert tl.range_images() == (40, 80)
    tl.smoothing = 5                    # the same moment in the trajectory
    assert (tl.play_start, tl.play_end) == pytest.approx((4.0, 8.0))
    assert tl.range_images() == (20, 40)


def test_the_clock_round_trips_with_its_new_settings():
    tl = timeline.Timeline(fps=24.0, smoothing=6)
    tl.set_track(1, 21)
    tl.set_range(2.0, 8.0)
    tl.seek(5.0)
    again = timeline.Timeline.from_dict(tl.to_dict())
    again.set_track(1, 21)
    assert again.smoothing == 6
    assert again.fps == pytest.approx(24.0)
    assert (again.play_start, again.play_end) == pytest.approx((2.0, 8.0))
    assert again.time == pytest.approx(5.0)


def test_an_old_savepoint_still_loads():
    """Pre-round-30 files carry the boolean, not a count."""
    off = timeline.Timeline.from_dict({"fps": 12.0, "interpolate": False})
    assert off.smoothing == 1
    on = timeline.Timeline.from_dict({"fps": 12.0, "interpolate": True})
    assert on.smoothing > 1


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


def test_the_bar_reads_in_images(win):
    win._install_structure(_traj("t", 5))
    win._sync_traj_bar()
    win.timeline.smoothing = 10
    win._apply_timeline()
    assert win.traj_bar.label.text().startswith("1 / 41")
    assert win.traj_bar.smooth_spin.value() == 10
    assert win.traj_bar.smooth_spin.suffix() == " img"
    assert win.traj_bar.fps_spin.suffix() == " fps"


def test_there_is_no_smooth_tick_box_any_more(win):
    assert not hasattr(win.traj_bar, "interp_check")


def test_the_loop_limits_are_on_the_bar(win):
    win._install_structure(_traj("t", 5))
    win.timeline.smoothing = 10                   # 4 frames -> 41 images
    win._sync_traj_bar()
    bar = win.traj_bar
    assert bar.start_spin.value() == 1
    assert bar.end_spin.value() == win.timeline.n_images == 41
    bar.end_spin.setValue(21)                     # image 21 of 41 = frame 2
    assert win.timeline.play_end == pytest.approx(2.0)
    assert win.timeline.play_start == pytest.approx(0.0)


def test_playing_stays_inside_the_limits(win):
    win._install_structure(_traj("t", 9))
    win.timeline.smoothing = 10
    win._sync_traj_bar()
    win.timeline.end = timeline.LOOP
    win.traj_bar.start_spin.setValue(11)          # frames 1 .. 3
    win.traj_bar.end_spin.setValue(31)
    for _ in range(200):
        win._advance_frame()
        assert 1.0 - 1e-9 <= win.timeline.time <= 3.0 + 1e-9


def test_the_panel_does_not_push_its_own_defaults_back(win):
    """sync() writes every spin box; a programmatic write must not look like
    a user edit, or the panel overwrites the clock it is displaying."""
    win._install_structure(_traj("t", 5))
    win.timeline.smoothing = 4
    win.timeline.fps = 17.0
    win._sync_traj_bar()
    assert win.timeline.smoothing == 4
    assert win.timeline.fps == pytest.approx(17.0)


def test_smoothing_one_snaps_to_whole_frames(win):
    win._install_structure(_traj("t", 5))
    obj = win.scene.objects[0]
    win._sync_traj_bar()
    win.traj_bar.smooth_spin.setValue(1)
    win.timeline.seek(1.5)
    win._apply_timeline()
    assert obj.play_position is None
    assert obj.display_coords()[0][0] == pytest.approx(1.0)


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
    assert obj.structure.n_frames == 20
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
    assert win.vibration_page.frames_spin.value() == 20


def test_a_mode_plays_through_the_ordinary_scene_clock(win):
    _freq_win(win)
    obj = win._active_obj()
    win.on_animate_mode(6)
    track = win.timeline.get(obj.id)
    assert track.end == timeline.LOOP
    assert win.timeline.duration == pytest.approx(19.0)
    assert win.traj_bar.isVisible()


def test_an_ordinary_file_is_not_scanned_for_modes(win, tmp_path):
    path = tmp_path / "plain.xyz"
    path.write_text("2\n\nC 0.0 0.0 0.0\nO 1.2 0.0 0.0\n", encoding="utf-8")
    win.open_path(str(path))
    assert win._modes == {}
