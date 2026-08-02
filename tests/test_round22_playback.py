"""Round 22: the scene clock driving the real app."""

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
    win._sync_traj_bar()
    win.timeline.seek(3.0)
    win._apply_timeline()
    assert win.timeline.frame_for(a.id) == pytest.approx(3.0)
    assert win.timeline.frame_for(b.id) == pytest.approx(3.0)
    assert a.display_coords()[0][0] == pytest.approx(1.5)
    assert b.display_coords()[0][1] == pytest.approx(1.5)


def test_the_scene_runs_as_long_as_its_longest_track(win):
    win._install_structure(_traj("short", 5, 0))
    win._install_structure(_traj("long", 21, 1))
    win._sync_traj_bar()
    assert win.timeline.duration == pytest.approx(20.0)


def test_a_short_track_holds_while_a_long_one_continues(win):
    win._install_structure(_traj("short", 5, 0))
    win._install_structure(_traj("long", 21, 1))
    a, b = win.scene.objects[0], win.scene.objects[1]
    win._sync_traj_bar()
    win.timeline.seek(12.0)
    win._apply_timeline()
    assert win.timeline.frame_for(a.id) == pytest.approx(4.0)   # last frame
    assert win.timeline.frame_for(b.id) == pytest.approx(12.0)


def test_interpolation_never_damages_the_stored_frames(win):
    """Display-only: scrubbing must not be able to corrupt a trajectory."""
    win._install_structure(_traj("t", 5, 0))
    obj = win.scene.objects[0]
    before = [f.copy() for f in obj.structure.frames]
    win._sync_traj_bar()
    for t in (0.3, 1.7, 2.5, 3.9):
        win.timeline.seek(t)
        win._apply_timeline()
    assert len(obj.structure.frames) == len(before)
    for f, g in zip(obj.structure.frames, before):
        assert f == pytest.approx(g)


def test_between_frames_the_drawn_coordinates_are_blended(win):
    win._install_structure(_traj("t", 5, 0))
    obj = win.scene.objects[0]
    win._sync_traj_bar()
    win.timeline.seek(1.5)
    win._apply_timeline()
    # frames 1 and 2 are at x = 0.5 and 1.0, so halfway is 0.75
    assert obj.display_coords()[0][0] == pytest.approx(0.75)
    # ...and the modifier/export path sees the same thing
    _sym, coords, _b = obj.evaluated()
    assert coords[0][0] == pytest.approx(0.75)


def test_smooth_off_snaps_to_whole_frames(win):
    win._install_structure(_traj("t", 5, 0))
    obj = win.scene.objects[0]
    win._sync_traj_bar()
    win.timeline.interpolate = False
    win.timeline.seek(1.5)
    win._apply_timeline()
    assert obj.play_position is None
    assert obj.display_coords()[0][0] == pytest.approx(1.0)   # nearest frame


def test_bonds_are_not_re_perceived_every_tick(win):
    """Connectivity belongs to the frame; re-running perception 30x a second
    would dominate playback for no visible gain."""
    from molom.core import bonding
    win._install_structure(_traj("t", 21, 0))
    win._sync_traj_bar()
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


def test_per_track_offset_and_speed_survive_a_resync(win):
    from molom.core import timeline as timeline_mod
    win._install_structure(_traj("a", 9, 0))
    win._sync_traj_bar()
    track = win.timeline.get(win.scene.objects[0].id)
    track.start, track.speed, track.end = 3.0, 0.5, timeline_mod.PINGPONG
    win._sync_traj_bar()
    again = win.timeline.get(win.scene.objects[0].id)
    assert (again.start, again.speed, again.end) == (3.0, 0.5,
                                                     timeline_mod.PINGPONG)


def test_playback_advances_the_clock(win):
    win._install_structure(_traj("t", 21, 0))
    win._sync_traj_bar()
    win._fps_spin.setValue(10)
    start = win.timeline.time
    win._advance_frame()
    assert win.timeline.time > start
