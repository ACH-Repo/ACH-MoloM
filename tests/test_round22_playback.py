"""Round 22: the scene clock driving the real app.

Round 77 made a strip's LENGTH the only playback number it has, so a
trajectory no longer runs at one scene frame per source frame by default -
it is stretched to at least a second (`timeline.default_frames`). These
tests are about the clock rather than about the default, so `_one_to_one`
pins each strip back to its own frame count and the arithmetic below reads
exactly as it did.
"""

import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _traj(name, n, axis, step=0.5):
    from molom.core.structure import Structure
    s = Structure.from_atoms([("C", 0.0, 0.0, 0.0), ("O", 1.2, 0.0, 0.0)],
                             name=name)
    for k in range(1, n):
        frame = s.frames[0].copy()
        frame[:, axis] += k * step
        s.frames.append(frame)
    return s


def _one_to_one(win):
    """One scene frame per source frame, so scene time IS frame index."""
    win._sync_traj_bar()
    for obj in win.scene.objects:
        win.timeline.set_frames(obj.id, obj.structure.n_frames)
    win._sync_traj_bar()


@pytest.fixture
def win():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.app import MainWindow
    QApplication.instance() or QApplication([])
    w = MainWindow()
    w.show()
    return w


def test_two_trajectories_share_one_playhead(win):
    """The headline: the bar drove only the ACTIVE molecule before, so a
    second trajectory could not play at all."""
    win._install_structure(_traj("short", 5, 0))
    win._install_structure(_traj("long", 21, 1))
    a, b = win.scene.objects[0], win.scene.objects[1]
    _one_to_one(win)
    win.timeline.seek(3.0)
    win._apply_timeline()
    assert win.timeline.frame_for(a.id) == pytest.approx(3.0)
    assert win.timeline.frame_for(b.id) == pytest.approx(3.0)
    assert a.display_coords()[0][0] == pytest.approx(1.5)
    assert b.display_coords()[0][1] == pytest.approx(1.5)


def test_the_scene_runs_as_long_as_its_longest_track(win):
    win._install_structure(_traj("short", 5, 0))
    win._install_structure(_traj("long", 21, 1))
    _one_to_one(win)
    assert win.timeline.duration == pytest.approx(20.0)


def test_a_short_track_holds_while_a_long_one_continues(win):
    win._install_structure(_traj("short", 5, 0))
    win._install_structure(_traj("long", 21, 1))
    a, b = win.scene.objects[0], win.scene.objects[1]
    _one_to_one(win)
    win.timeline.seek(12.0)
    win._apply_timeline()
    assert win.timeline.frame_for(a.id) == pytest.approx(4.0)   # last frame
    assert win.timeline.frame_for(b.id) == pytest.approx(12.0)


def test_interpolation_never_damages_the_stored_frames(win):
    """Display-only: scrubbing must not be able to corrupt a trajectory."""
    win._install_structure(_traj("t", 5, 0))
    obj = win.scene.objects[0]
    before = [f.copy() for f in obj.structure.frames]
    _one_to_one(win)
    for t in (0.3, 1.7, 2.5, 3.9):
        win.timeline.seek(t)
        win._apply_timeline()
    assert len(obj.structure.frames) == len(before)
    for f, g in zip(obj.structure.frames, before):
        assert f == pytest.approx(g)


def test_between_frames_the_drawn_coordinates_are_blended(win):
    win._install_structure(_traj("t", 5, 0))
    obj = win.scene.objects[0]
    _one_to_one(win)
    win.timeline.seek(1.5)
    win._apply_timeline()
    # frames 1 and 2 are at x = 0.5 and 1.0, so halfway is 0.75
    assert obj.display_coords()[0][0] == pytest.approx(0.75)
    # ...and the modifier/export path sees the same thing
    _sym, coords, _b = obj.evaluated()
    assert coords[0][0] == pytest.approx(0.75)


def test_a_strip_as_long_as_its_data_interpolates_nothing(win):
    """Round 77 retired the global smoothing switch, and nothing had to
    replace it: a strip whose length equals its frame count puts every
    scene frame ON a source frame, so the blend is a no-op by
    construction rather than by a flag somebody has to remember."""
    win._install_structure(_traj("t", 5, 0))
    obj = win.scene.objects[0]
    _one_to_one(win)
    assert not win.timeline.get(obj.id).interpolates
    for k in range(5):
        win.timeline.seek(float(k))
        win._apply_timeline()
        assert obj.play_position == pytest.approx(k)
        assert obj.display_coords()[0][0] == pytest.approx(0.5 * k)


def test_bonds_are_not_re_perceived_every_tick(win):
    """Connectivity belongs to the frame; re-running perception 30x a second
    would dominate playback for no visible gain."""
    from molom.core import bonding
    win._install_structure(_traj("t", 21, 0))
    _one_to_one(win)
    calls = []
    original = bonding.perceive_structure_bonds
    bonding.perceive_structure_bonds = lambda *a, **k: calls.append(1)
    try:
        for k in range(10):
            win.timeline.seek(1.0 + k * 0.05)     # all within one frame
            win._apply_timeline()
    finally:
        bonding.perceive_structure_bonds = original
    assert len(calls) <= 1


def test_a_scene_of_stills_hides_the_bar(win):
    from molom.core.structure import Structure
    win._install_structure(Structure.from_atoms([("C", 0.0, 0.0, 0.0)]))
    win._sync_traj_bar()
    assert not win.traj_bar.isVisible()
    assert not win.timeline.has_animation


def test_deleting_a_molecule_drops_its_track(win):
    win._install_structure(_traj("a", 5, 0))
    win._install_structure(_traj("b", 7, 1))
    win._sync_traj_bar()
    assert len(win.timeline.tracks()) == 2
    win.scene.remove(win.scene.objects[0].id)
    win._sync_traj_bar()
    assert len(win.timeline.tracks()) == 1


def test_per_track_offset_and_length_survive_a_resync(win):
    from molom.core import timeline as timeline_mod
    win._install_structure(_traj("a", 9, 0))
    win._sync_traj_bar()
    obj_id = win.scene.objects[0].id
    track = win.timeline.get(obj_id)
    track.start, track.end = 3.0, timeline_mod.PINGPONG
    win.timeline.set_frames(obj_id, 33)
    win._sync_traj_bar()
    again = win.timeline.get(obj_id)
    assert (again.start, again.frames, again.end) == (3.0, 33,
                                                      timeline_mod.PINGPONG)


def test_playback_advances_the_clock(win):
    """Round 78: the step comes from the WALL CLOCK, not from the tick, so
    the assertion is about elapsed time rather than about calls. A tick with
    no time behind it draws nothing, which is the point - the timer wakes far
    more often than a frame is due."""
    import time as _time
    win._install_structure(_traj("t", 21, 0))
    _one_to_one(win)
    win._fps_spin.setValue(10)
    win.timeline.seek(0.0)
    win._play_clock = _time.perf_counter()
    win._advance_frame()
    assert win.timeline.time == 0.0            # no time has passed yet
    win._play_clock -= 0.5                     # half a second at 10 fps
    win._advance_frame()
    assert win.timeline.time == pytest.approx(5.0)
