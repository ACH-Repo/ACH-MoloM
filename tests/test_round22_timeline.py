"""Round 22: the scene clock and frame interpolation.

Round 77 re-cut the units underneath these: a strip is now a number
of SCENE FRAMES (`frames`) rather than a source length divided by a
speed, and the global smoothing that turned frames into pictures is
gone. Every claim below is round 22's; only the arithmetic that
states it has moved. A strip is given `frames=n` wherever the point
is the mapping itself, so that one scene frame is one source frame
and the mapping is readable.
"""

import numpy as np
import pytest

from molom.core import interpolate, timeline


# ------------------------------------------------------------------- tracks
def test_a_track_maps_scene_time_to_its_own_frames():
    t = timeline.Track(1, n_frames=11, frames=11)
    assert t.frame_at(0.0) == pytest.approx(0.0)
    assert t.frame_at(5.0) == pytest.approx(5.0)
    assert t.frame_at(10.0) == pytest.approx(10.0)


def test_a_start_offset_delays_a_track():
    t = timeline.Track(1, n_frames=11, frames=11, start=4.0)
    assert t.frame_at(0.0) == pytest.approx(0.0)     # not started yet
    assert t.frame_at(4.0) == pytest.approx(0.0)
    assert t.frame_at(9.0) == pytest.approx(5.0)


def test_the_frame_count_scales_a_track():
    """Round 77: what used to be a speed multiplier is now the strip's
    length, which says the same thing in a unit you can put on a timeline."""
    slow = timeline.Track(1, n_frames=11, frames=21)
    assert slow.frame_at(10.0) == pytest.approx(5.0)
    assert slow.frames == 21
    fast = timeline.Track(1, n_frames=11, frames=6)
    assert fast.frame_at(3.0) == pytest.approx(6.0)
    assert fast.frames == 6


def test_hold_clamps_at_both_ends():
    t = timeline.Track(1, n_frames=11, frames=11, end=timeline.HOLD)
    assert t.frame_at(-5.0) == pytest.approx(0.0)
    assert t.frame_at(999.0) == pytest.approx(10.0)


def test_loop_wraps():
    """Over the STRIP's own length. For linear data that means every real
    frame is shown, including the last, and then the loop cuts back - round
    77, where wrapping at `n - 1` instead was the mode-loop hitch."""
    t = timeline.Track(1, n_frames=11, frames=11, end=timeline.LOOP)
    assert t.frame_at(10.0) == pytest.approx(10.0)
    assert t.frame_at(11.0) == pytest.approx(0.0)
    assert t.frame_at(13.0) == pytest.approx(2.0)


def test_pingpong_turns_around():
    t = timeline.Track(1, n_frames=11, frames=11, end=timeline.PINGPONG)
    assert t.frame_at(5.0) == pytest.approx(5.0)
    assert t.frame_at(10.0) == pytest.approx(10.0)
    assert t.frame_at(13.0) == pytest.approx(7.0)     # coming back
    assert t.frame_at(20.0) == pytest.approx(0.0)


def test_a_still_object_never_leaves_frame_zero():
    t = timeline.Track(1, n_frames=1, frames=1)
    assert t.frame_at(0.0) == 0.0
    assert t.frame_at(100.0) == 0.0
    assert t.last_frame == t.start


# ----------------------------------------------------------------- timeline
def test_several_trajectories_play_at_once():
    """The whole point: one playhead, every track following it."""
    tl = timeline.Timeline()
    tl.set_track(1, 11, frames=11)
    tl.set_track(2, 21, frames=11)
    tl.set_track(3, 5, frames=5, start=10.0)
    tl.seek(5.0)
    assert tl.frame_for(1) == pytest.approx(5.0)
    assert tl.frame_for(2) == pytest.approx(10.0)
    assert tl.frame_for(3) == pytest.approx(0.0)      # has not started
    tl.seek(12.0)
    assert tl.frame_for(3) == pytest.approx(2.0)


def test_duration_is_the_longest_track():
    """`duration` is the LAST frame occupied, inclusive - round 77, because
    that is what a Frame End means."""
    tl = timeline.Timeline()
    tl.set_track(1, 11, frames=11)             # occupies 0..10
    tl.set_track(2, 5, frames=5, start=20.0)   # occupies 20..24
    assert tl.duration == pytest.approx(24.0)


def test_a_scene_of_stills_has_no_duration():
    tl = timeline.Timeline()
    tl.set_track(1, 1)
    tl.set_track(2, 1)
    assert tl.duration == 0.0
    assert not tl.has_animation
    assert tl.seek(50.0) == 0.0


def test_advance_uses_fps_to_step_scene_frames():
    """Round 77 left `fps` as the ONLY global playback number: it is scene
    frames per second, and a scene frame is a picture. Half a second at
    10 fps is five frames, whatever any strip is doing inside them."""
    tl = timeline.Timeline(fps=10.0)
    tl.set_track(1, 101, frames=101)
    tl.advance(0.5)
    assert tl.time == pytest.approx(5.0)
    tl.seek(0.0)
    tl.advance_frames(3)
    assert tl.time == pytest.approx(3.0)


def test_playhead_loops_when_it_runs_off_the_end():
    """Advancing wraps; SEEKING clamps. Dragging the playhead past a limit
    should park on it, not teleport to the other end (round 30)."""
    tl = timeline.Timeline()
    tl.end = timeline.LOOP
    tl.set_track(1, 11, frames=11)                  # occupies 0..10
    assert tl.seek(10.0) == pytest.approx(10.0)
    assert tl.seek(13.0) == pytest.approx(10.0)     # clamped, not wrapped
    tl.seek(0.0)
    # The range is INCLUSIVE, so frame 10 is played and frame 11 is frame 0
    # again - the old wrap over `end - start` skipped the last frame outright.
    assert tl.step_frames(10.0) == pytest.approx(10.0)
    assert tl.step_frames(1.0) == pytest.approx(0.0)
    assert tl.step_frames(3.0) == pytest.approx(3.0)


def test_sync_adds_and_drops_tracks_with_the_scene():
    tl = timeline.Timeline()
    tl.sync([(1, 10), (2, 5)])
    assert sorted(t.obj_id for t in tl.tracks()) == [1, 2]
    tl.sync([(2, 5), (3, 8)])
    assert sorted(t.obj_id for t in tl.tracks()) == [2, 3]


def test_sync_keeps_settings_the_user_chose():
    tl = timeline.Timeline()
    tl.set_track(1, 10, start=7.0, end=timeline.PINGPONG)
    tl.set_frames(1, 40)               # chosen by hand, so it is kept
    tl.sync([(1, 12)])                 # e.g. frames were appended
    t = tl.get(1)
    assert t.n_frames == 12
    assert t.start == pytest.approx(7.0)
    assert t.frames == 40
    assert t.end == timeline.PINGPONG


def test_disabled_tracks_are_ignored():
    tl = timeline.Timeline()
    tl.set_track(1, 11, enabled=False)
    assert tl.frame_for(1) is None
    assert not tl.has_animation


def test_timeline_round_trips_through_a_dict():
    tl = timeline.Timeline(fps=25.0)
    tl.set_track(4, 30, start=2.0, frames=90, cyclic=True,
                 end=timeline.PINGPONG)
    tl.seek(3.0)
    again = timeline.Timeline.from_dict(tl.to_dict())
    assert again.fps == pytest.approx(25.0)
    assert again.time == pytest.approx(3.0)
    t = again.get(4)
    assert (t.n_frames, t.start, t.frames, t.end) == (30, 2.0, 90,
                                                      timeline.PINGPONG)
    assert t.cyclic


# -------------------------------------------------------------- interpolation
def test_frame_pair_brackets_a_fractional_position():
    assert interpolate.frame_pair(5, 0.0) == (0, 1, 0.0)
    assert interpolate.frame_pair(5, 2.25) == (2, 3, 0.25)
    assert interpolate.frame_pair(5, 4.0) == (4, 4, 0.0)
    assert interpolate.frame_pair(1, 3.0) == (0, 0, 0.0)


def test_interpolation_hits_the_endpoints_exactly():
    frames = [np.zeros((3, 3)), np.ones((3, 3))]
    assert interpolate.coords_at(frames, 0.0) == pytest.approx(frames[0])
    assert interpolate.coords_at(frames, 1.0) == pytest.approx(frames[1])


def test_plain_lerp_halfway():
    frames = [np.zeros((2, 3)), np.full((2, 3), 4.0)]
    mid = interpolate.coords_at(frames, 0.5, rigid=False)
    assert mid == pytest.approx(np.full((2, 3), 2.0))


def test_a_pure_translation_is_interpolated_exactly():
    a = np.array([[0.0, 0, 0], [1.0, 0, 0], [0, 1.0, 0]])
    b = a + np.array([10.0, 0.0, 0.0])
    mid = interpolate.coords_at([a, b], 0.5)
    assert mid == pytest.approx(a + np.array([5.0, 0.0, 0.0]))


def test_a_rotating_molecule_keeps_its_bond_lengths():
    """The reason rigid interpolation exists: a plain lerp cuts the chord, so
    a molecule visibly shrinks and springs back as it turns."""
    a = np.array([[1.0, 0.0, 0.0], [-1.0, 0.0, 0.0], [0.0, 0.5, 0.0]])
    r90 = np.array([[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])
    b = a @ r90.T
    span_a = float(np.linalg.norm(a[0] - a[1]))

    naive = interpolate.coords_at([a, b], 0.5, rigid=False)
    rigid = interpolate.coords_at([a, b], 0.5, rigid=True)

    assert float(np.linalg.norm(naive[0] - naive[1])) < span_a * 0.95
    assert float(np.linalg.norm(rigid[0] - rigid[1])) == pytest.approx(span_a)


def test_rigid_interpolation_still_carries_real_deformation():
    a = np.array([[1.0, 0, 0], [-1.0, 0, 0], [0, 1.0, 0], [0, -1.0, 0]])
    b = a.copy()
    b[0] = [2.0, 0.0, 0.0]          # one atom genuinely moves out
    mid = interpolate.coords_at([a, b], 0.5)
    assert mid[0][0] == pytest.approx(1.5, abs=0.25)


def test_mismatched_frame_shapes_do_not_explode():
    frames = [np.zeros((3, 3)), np.zeros((4, 3))]
    out = interpolate.coords_at(frames, 0.5)
    assert out.shape == (3, 3)
