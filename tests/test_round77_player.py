"""Round 77: the player's numbers, reworked.

Christian's brief: "The global settings should only be Frame Start, Frame
End, Framerate. Smoothing is a property that should be unique to a particular
strip... Just set one number of total frames inside the strip properties.
User has to adjust them until they're satisfied with the fluidity of the
animation. Default: 60 FPS, ergo 59 frames per oscillation animation."

Two things are being pinned here. The obvious one is the new shape: one
global unit (a scene frame, which IS a picture), one per-strip number (how
many of them the strip occupies), and no global smoothing anywhere.

The one worth the round is the bug that fell out of the rework. The old LOOP
wrapped a track at `n_frames - 1` local frames - i.e. it assumed the last
stored frame duplicated the first. `vibrations.mode_frames` deliberately does
NOT store that duplicate, so a mode looped over 93.3% of its period and then
covered the remaining 1.33 source frames in a single image: a hitch once per
revolution, four times the normal step, on every vibration MoloM has ever
animated.
"""

import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from molom.core import animation as anim
from molom.core import interpolate, timeline, vibrations

FREQ_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "data", "orca_freq_h3po4.out")


def _cyclic(n_source=20, frames=60, **kw):
    kw.setdefault("end", timeline.LOOP)
    return timeline.Track(1, n_source, frames=frames, cyclic=True, **kw)


# ------------------------------------------------- one number, both cases
def test_a_strip_is_described_by_its_frame_count_alone():
    """Length, speed and smoothness were three ways of saying one thing."""
    track = _cyclic(n_source=20, frames=60)
    assert track.frames == 60
    assert track.last_frame == 59.0          # inclusive, 0-based
    assert track.subdivision == pytest.approx(3.0)
    assert track.interpolates
    assert not hasattr(track, "speed")


def test_the_default_is_a_second_at_sixty_frames_a_second():
    """Christian's stated default, and the arithmetic behind his 59: sixty
    frames counted from zero END at 59, which is where Frame End lands."""
    clock = timeline.Timeline()
    clock.set_track(1, vibrations.DEFAULT_PERIOD_FRAMES, cyclic=True)
    assert clock.fps == 60.0
    assert clock.get(1).frames == 60
    assert clock.play_start == 0.0
    assert clock.play_end == 59.0
    assert clock.n_frames == 60
    assert clock.n_frames / clock.fps == pytest.approx(1.0)


def test_one_default_rule_covers_a_mode_and_a_trajectory():
    """`max(n, 60)`: never fewer frames than the data really has, never so
    few that a three-step optimisation flashes past in a twentieth of a
    second."""
    assert timeline.default_frames(20) == 60          # a coarse mode
    assert timeline.default_frames(3) == 60           # an optimisation
    assert timeline.default_frames(500) == 500        # an MD run, intact


def test_raising_the_frame_count_is_the_old_smoothing():
    """The knob did not disappear, it moved and changed units."""
    assert _cyclic(20, 20).subdivision == pytest.approx(1.0)
    assert _cyclic(20, 60).subdivision == pytest.approx(3.0)
    assert not _cyclic(20, 20).interpolates


# ----------------------------------------------------- the loop that closes
def test_a_cyclic_strip_closes_its_loop_exactly():
    """THE bug. Sample a whole strip and the jump from its last frame back to
    its first must be one ordinary step - no more, no less."""
    track = _cyclic(n_source=20, frames=60)
    pos = [track.frame_at(k) for k in range(60)]
    step = pos[1] - pos[0]
    assert pos[0] == 0.0
    assert max(pos) == pytest.approx(20 - step)      # one arc short of home
    wrap = 20.0 - pos[-1]                            # last frame -> first
    assert wrap == pytest.approx(step)
    assert np.allclose(np.diff(pos), step)           # and nothing else jumps


def test_the_old_model_lost_a_twentieth_of_every_period():
    """What the fix is worth, stated as the thing that was wrong: wrapping at
    `n - 1` covers 19/20 of a 20-sample period and then leaps the rest."""
    n = 20
    old = [(k / 3.0) % (n - 1) for k in range(3 * (n - 1))]
    assert max(old) / n == pytest.approx(0.9333, abs=5e-4)
    assert (n - max(old)) / (old[1] - old[0]) == pytest.approx(4.0)
    now = [_cyclic(n_source=n, frames=60).frame_at(k) for k in range(60)]
    assert (max(now) + (now[1] - now[0])) / n == pytest.approx(1.0)


def test_a_linear_strip_lands_on_its_last_datum():
    """A trajectory has two distinct ends, so `frames - 1` scene intervals
    divide `n - 1` source intervals and the last frame IS the last frame."""
    track = timeline.Track(1, 5, frames=9, end=timeline.HOLD)
    pos = [track.frame_at(k) for k in range(9)]
    assert pos[0] == 0.0
    assert pos[-1] == pytest.approx(4.0)
    assert np.allclose(np.diff(pos), 0.5)


def test_a_linear_loop_shows_every_real_frame_then_cuts():
    """No invented morph from the last geometry back to the first: the last
    datum is held for its frame and the loop cuts, which is honest for data
    that is not periodic."""
    track = timeline.Track(1, 5, frames=5, end=timeline.LOOP)
    assert [track.frame_at(k) for k in range(6)] == [0, 1, 2, 3, 4, 0]


def test_the_end_mode_is_applied_in_the_strip_s_own_frames():
    """Which is what lets ONE rule serve both kinds of data."""
    hold = timeline.Track(1, 20, frames=10, cyclic=True, end=timeline.HOLD)
    assert hold.strip_frame(-5.0) == 0.0
    assert hold.strip_frame(99.0) == 9.0
    ping = timeline.Track(1, 20, frames=10, cyclic=True, end=timeline.PINGPONG)
    assert ping.strip_frame(9.0) == 9.0
    assert ping.strip_frame(12.0) == 6.0


# ------------------------------------------------- the interpolation across
def test_the_wrap_blends_the_last_sample_into_the_first():
    """The other half of the same bug: `frame_pair` CLAMPED, so a position in
    [n-1, n) froze on the last sample rather than closing the arc."""
    assert interpolate.frame_pair(20, 19.5, cyclic=True) == (19, 0, 0.5)
    assert interpolate.frame_pair(20, 19.5) == (19, 19, 0.0)
    assert interpolate.frame_pair(20, 20.25, cyclic=True) == (0, 1, 0.25)


def test_a_sine_stays_a_sine_across_the_wrap():
    """Measured on the real thing rather than asserted about indices: the
    step that closes the loop must be an ORDINARY step for that part of the
    oscillation, not a leap.

    A sine's steps are not all equal - they are widest at the zero crossing
    and narrowest at the turning points - so the test compares the wrap step
    against its own NEIGHBOUR, which is the honest local measure.
    """
    n = 20
    frames = [np.array([[np.sin(2 * np.pi * k / n), 0.0, 0.0],
                        [0.0, 0.0, 0.0]]) for k in range(n)]
    track = _cyclic(n_source=n, frames=60)

    def walk(cyclic):
        x = [float(interpolate.coords_at(frames, track.frame_at(k),
                                         rigid=False, cyclic=cyclic)[0][0])
             for k in range(60)]
        return np.abs(np.diff(x + [x[0]]))

    steps = walk(True)
    assert steps[-1] == pytest.approx(steps[-2], rel=0.05)
    # ...and without it the last arc is frozen and then leapt in one frame,
    # which is what the whole round is about.
    clamped = walk(False)
    assert clamped[-2] == pytest.approx(0.0, abs=1e-12)
    assert clamped[-1] > 3.0 * steps[-1]


# ------------------------------------------------------ range and savefile
def test_the_frame_range_is_inclusive():
    """Frame End is the last frame PLAYED. The old wrap ran over
    `end - start`, so the last frame of the range was never shown."""
    clock = timeline.Timeline()
    clock.set_track(1, 10, frames=10)
    clock.end = timeline.LOOP
    clock.set_range(0.0, 4.0)
    assert clock.span == 5.0 and clock.n_frames == 5
    seen = []
    for _ in range(10):
        seen.append(clock.time)
        clock.advance_frames(1)
    assert seen == [0, 1, 2, 3, 4, 0, 1, 2, 3, 4]


def test_a_length_set_by_hand_survives_a_re_sync():
    """Re-baking a mode at another sample count must not silently replace a
    number the user chose - but must move one they never touched."""
    clock = timeline.Timeline()
    clock.sync([(1, 20, True), (2, 20, True)])
    clock.set_frames(1, 240)
    clock.sync([(1, 40, True), (2, 40, True)])
    assert clock.get(1).frames == 240             # chosen, so kept
    assert clock.get(2).frames == 60              # never touched, so default


def test_the_strip_round_trips_through_a_savefile():
    clock = timeline.Timeline(fps=50.0)
    clock.set_track(7, 24, start=-5.0, frames=120, cyclic=True,
                    end=timeline.LOOP)
    clock.set_frames(7, 120)
    again = timeline.Timeline.from_dict(clock.to_dict())
    track = again.get(7)
    assert (track.frames, track.cyclic, track.start) == (120, True, -5.0)
    assert track.frames_locked


def test_a_pre_round_77_savepoint_is_read_in_frames():
    """The old file measured a strip in source frames over a speed, with one
    global smoothing turning those into pictures. A picture is now a frame,
    so that product IS the new length - and the whole axis scales with it."""
    again = timeline.Timeline.from_dict({
        "fps": 30.0, "smoothing": 3, "range_start": 0.0, "range_end": 4.0,
        "time": 2.0,
        "tracks": [{"obj_id": 1, "n_frames": 5, "start": 1.0, "speed": 1.0,
                    "end": "loop", "enabled": True, "channel": None}]})
    track = again.get(1)
    assert track.frames == 12               # 4 intervals x 3 images
    assert track.start == pytest.approx(3.0)
    assert again.play_end == pytest.approx(11.0)
    assert again.time == pytest.approx(6.0)


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


def _mode_win(win):
    win.load_default_scene()
    win.open_path(FREQ_FILE)
    win.on_animate_mode(6)
    return win._active_obj()


def test_a_baked_mode_gives_christians_arithmetic(win):
    """60 fps, 60 frames per oscillation, Frame End 59 - and every frame
    drawn is a real sample, because the two defaults are equal."""
    obj = _mode_win(win)
    track = win.timeline.get(obj.id)
    assert obj.structure.n_frames == 60
    assert track.cyclic and track.frames == 60
    assert not track.interpolates
    assert win.traj_bar.start_spin.value() == 0
    assert win.traj_bar.end_spin.value() == 59
    assert win.timeline.n_frames / win.timeline.fps == pytest.approx(1.0)


def test_the_mode_is_marked_cyclic_on_the_molecule(win):
    """Metadata, not a flag on the track - so it rides undo and the savefile
    and a strip removed and re-added still describes a period."""
    obj = _mode_win(win)
    assert timeline.frames_are_cyclic(obj.structure)
    win.timeline.exclude(obj.id)
    win.timeline.include(obj.id)
    win._sync_traj_bar()
    assert win.timeline.get(obj.id).cyclic


def test_playing_a_mode_never_leaves_its_frames(win):
    """A cyclic position runs up to but never reaches n, so the nearest
    STORED frame of the last arc is frame 0 again - not one past the end."""
    obj = _mode_win(win)
    for _ in range(200):
        win._advance_frame()
        assert 0 <= obj.structure.current_frame < obj.structure.n_frames
        assert 0.0 <= obj.play_position < obj.structure.n_frames
        assert obj.play_cyclic


def test_the_strip_page_edits_the_duration(win):
    """Round 78: the box is SECONDS, because that is what a person means.
    Christian: "Change the main strip property from frames to time." The
    frames follow from it and the framerate."""
    obj = _mode_win(win)
    win.traj_bar.rows.select_strip(obj.id)
    page = win.strip_page
    assert page.seconds_spin.value() == pytest.approx(1.0)   # 60 f at 60 fps
    assert not hasattr(page, "speed_spin")
    assert not hasattr(page, "frames_spin")
    assert "one closed period" in page.source.text()
    page.seconds_spin.setValue(3.0)
    track = win.timeline.get(obj.id)
    assert track.frames == 180 and track.frames_locked
    assert track.subdivision == pytest.approx(3.0)
    assert "180 scene frames" in page.sampling.text()


def test_changing_the_strip_never_touches_the_molecule(win):
    """The strip is the animation's track, not its data - the same rule that
    makes Delete on a strip safe (round 76)."""
    obj = _mode_win(win)
    before = [f.copy() for f in obj.structure.frames]
    win.traj_bar.rows.select_strip(obj.id)
    win.strip_page.seconds_spin.setValue(2.28)
    assert len(obj.structure.frames) == len(before)
    for a, b in zip(obj.structure.frames, before):
        assert a == pytest.approx(b)


def test_the_player_survives_a_savepoint(win, tmp_path):
    """A strip's length is now something you TUNE, so losing it on save is
    losing the work. It was never written to a `.molom` before - which cost
    nothing while a strip only carried a start and a speed nobody set."""
    obj = _mode_win(win)
    win.timeline.set_frames(obj.id, 150)
    win.timeline.set_range(10.0, 120.0)
    path = str(tmp_path / "player.molom")
    from molom.core import project
    project.save_project(path, win.scene, view=win._view_state(),
                         ui=win._ui_state())
    win.open_project(path)
    back = next(o for o in win.scene.objects if o.structure.n_frames > 1)
    track = win.timeline.get(back.id)
    assert track is not None and track.frames == 150 and track.cyclic
    assert track.frames_locked
    assert (win.timeline.play_start,
            win.timeline.play_end) == pytest.approx((10.0, 120.0))


def test_the_range_handles_sit_on_the_column_boundaries(win):
    """Frame k occupies the axis interval [x(k), x(k+1)), which is why a
    strip is drawn out to its EXCLUSIVE end. With Frame End now INCLUSIVE,
    drawing its handle through the frame itself would veil the last frame
    that plays - so the handle sits one column further along, and dragging
    it sets one frame back."""
    _mode_win(win)
    rows = win.traj_bar.rows
    rows.resize(900, 200)
    assert win.timeline.play_end == 59.0
    x_end = rows._x_for(60.0)
    assert rows._limit_at(int(x_end)) == "end"
    assert rows._limit_at(int(rows._x_for(59.0))) != "end"
    rows._move_limit("end", 41.0)
    assert win.timeline.play_end == pytest.approx(40.0)
    assert win.timeline.n_frames == 41


def test_the_loop_closes_seamlessly_in_the_real_window(win):
    """The headline, measured end to end on Christian's own FREQ job rather
    than on indices: walk a whole loop through `_apply_timeline` and the step
    that closes it must be the SAME SIZE as the step one frame later, which
    is at the same phase of the oscillation.

    A sine's steps are not all equal - widest at the zero crossing, narrowest
    at the turning points - so comparing against the mean would prove
    nothing. Comparing like phase with like is what makes 1.0000 meaningful.
    """
    obj = _mode_win(win)
    clock = win.timeline
    clock.seek(clock.play_start)
    previous, steps = None, []
    for _ in range(clock.n_frames + 1):
        win._apply_timeline()
        coords = obj.display_coords().copy()
        if previous is not None:
            steps.append(float(np.abs(coords - previous).max()))
        previous = coords
        clock.advance_frames(1)
    assert len(steps) == clock.n_frames
    assert steps[-1] == pytest.approx(steps[0], rel=1e-6)
