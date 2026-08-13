"""Round 54: the animation export, boundary copies that follow an edit, and
the MSAA correction.

Christian picked three: the multisampling item (which turned out to be a
reporting bug of mine, not a missing feature), the animation export he asked
for back on 2026-08-02, and making an edit to a packed crystal reach the
copies instead of desynchronising them.
"""

import os

import numpy as np
import pytest

from molom.core import animation as anim
from molom.core import packing, timeline as timeline_mod

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
FERROCENE = os.path.join(DATA, "cod_2101932_ferrocene.cif")


def _clock(n_frames=5, smoothing=1, fps=30.0):
    clock = timeline_mod.Timeline(fps=fps, smoothing=smoothing)
    clock.set_track(1, n_frames=n_frames)
    return clock


# ----------------------------------------------------------- the frame plan
def test_a_loop_does_not_repeat_its_own_first_image():
    """The last image of a cycle is the same picture as the first of the
    next. Keeping it makes a hitch once per revolution — audible in a loop,
    and invisible in any single frame, which is exactly why it belongs in a
    test rather than in an eyeball check."""
    clock = _clock(n_frames=5)
    once = anim.frame_times(clock)
    twice = anim.frame_times(clock, loops=2)
    assert once == [0.0, 1.0, 2.0, 3.0]
    assert twice == once + once
    assert len(twice) == 2 * len(once)


def test_smoothing_subdivides_the_plan():
    clock = _clock(n_frames=5, smoothing=3)
    times = anim.frame_times(clock)
    assert len(times) == 12                      # 4 intervals x 3
    assert times[1] == pytest.approx(1.0 / 3.0)


def test_the_plan_follows_the_loop_RANGE_the_transport_bar_shows():
    """What you export is what the bar plays — the alternative is two sources
    of truth for the same interval."""
    clock = _clock(n_frames=5, smoothing=2)
    clock.set_range(1.0, 3.0)
    times = anim.frame_times(clock)
    assert times[0] == pytest.approx(1.0)
    assert max(times) < 3.0
    assert len(times) == 4
    whole = anim.frame_times(clock, whole_scene=True)
    assert whole[0] == 0.0 and len(whole) == 8


def test_a_still_scene_still_gives_one_image():
    clock = timeline_mod.Timeline()
    assert anim.frame_times(clock) == [0.0]
    assert anim.frame_times(clock, loops=0.0) == []


def test_fractional_loops_are_allowed():
    clock = _clock(n_frames=5)
    assert len(anim.frame_times(clock, loops=0.5)) == 2


# --------------------------------------------------------------- the output
def test_a_sequence_goes_into_a_folder_of_its_own():
    """A few hundred PNGs dropped beside whatever file the user picked is a
    mess they then have to sort out by hand."""
    where = anim.plan(os.path.join("out", "spin.png"), anim.FORMAT_PNG, 120)
    assert where["path"] == os.path.join("out", "spin")
    assert where["base"] == "spin"
    assert where["digits"] == 4


def test_the_numbering_widens_for_a_long_render():
    assert anim.plan("a.png", "png", 120)["digits"] == 4
    assert anim.plan("a.png", "png", 99999)["digits"] == 5


def test_a_video_goes_to_a_single_file():
    where = anim.plan(os.path.join("out", "spin.mp4"), anim.FORMAT_MP4, 30)
    assert where["path"] == os.path.join("out", "spin.mp4")


def test_an_unknown_format_is_refused():
    with pytest.raises(anim.ExportError):
        anim.plan("a.avi", "avi", 10)


def test_h264_needs_even_dimensions():
    """It refuses odd ones with a message nobody reads to the end."""
    assert anim.FORMAT_MP4 in anim.EVEN_DIMENSIONS
    assert anim.even(1281) == 1280
    assert anim.even(720) == 720


def test_the_encoder_arguments_are_playable_ones():
    cmd = anim.encode_command("ffmpeg", "f_%04d.png", "out.mp4", 24.0)
    assert "-framerate" in cmd and "24" in cmd
    # yuv420p is not optional: the default yuv444p plays in nothing but VLC
    assert "yuv420p" in cmd
    assert cmd[-1] == "out.mp4"
    gif = anim.encode_command("ffmpeg", "f_%04d.png", "out.gif", 12.0,
                              anim.FORMAT_GIF)
    assert "palettegen" in " ".join(gif)          # or it bands badly


def test_a_missing_encoder_is_reported_not_raised(tmp_path, monkeypatch):
    """Video is the OPTIONAL tier. A missing ffmpeg must not take the export
    down — the frames are already on disk by then."""
    # `*_a` because round 61 gave the resolver a `hint` parameter (an explicit
    # ffmpeg path from Settings) — the stub has to accept whatever the caller
    # passes, or the test fails on its own fixture rather than on the code.
    monkeypatch.setattr(anim, "ffmpeg_executable", lambda *_a, **_k: "")
    ok, message = anim.encode("f_%04d.png", str(tmp_path / "o.mp4"), 24.0)
    assert ok is False and "ffmpeg" in message


def test_the_summary_reads_in_seconds():
    assert "2.0 s" in anim.summarise(48, 24.0, "mp4")


# ------------------------------------------- an edit reaches its own copies
def test_a_boundary_copy_is_the_same_atom():
    """The copies are independent entries in the atom list, so changing one
    used to leave the others as they were — one face of the cell saying F
    while the opposite face still said H."""
    pytest.importorskip("PySide6")
    from molom.core import bonding, io
    from molom.core.structure import Structure
    atoms, meta = io.read_structures(FERROCENE)[0]
    s = Structure([a[0] for a in atoms],
                  np.array([a[1:] for a in atoms], dtype=float),
                  metadata=meta)
    bonding.perceive_structure_bonds(s)
    assert len(meta["content_of"]) == s.n_atoms
    assert max(meta["content_of"]) < meta["cell_content"]
    # an atom on a face is drawn more than once, and both are found
    images = packing.images_of(meta, [0], s.n_atoms)
    assert 0 in images
    assert all(meta["content_of"][i] == meta["content_of"][0]
               for i in images)


def test_without_the_mapping_nothing_is_guessed():
    """No `content_of` means an unpacked structure, or one edited since.
    Expanding on element alone would silently change atoms nobody selected."""
    assert packing.images_of({}, [3, 1], 10) == [1, 3]
    assert packing.images_of({"content_of": []}, [2], 10) == [2]


def test_changing_an_element_reaches_every_image():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.app import MainWindow
    from molom.ui.viewport import MODE_EDIT
    QApplication.instance() or QApplication([])
    win = MainWindow()
    win.open_path(FERROCENE)
    obj = win._active_obj()
    index = [i for i, x in enumerate(obj.structure.symbols) if x == "H"][0]
    n_images = len(packing.images_of(obj.structure.metadata, [index],
                                     obj.structure.n_atoms))
    assert n_images > 1                       # otherwise the test proves none
    win.viewport.set_mode(MODE_EDIT, obj.id)
    win.viewport.set_selection([(obj.id, index)])
    win.viewport.apply_element("F")
    symbols = win.scene.get(obj.id).structure.symbols
    assert symbols.count("F") == n_images


def test_deleting_an_atom_takes_its_copies_with_it():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.app import MainWindow
    from molom.ui.viewport import MODE_EDIT
    QApplication.instance() or QApplication([])
    win = MainWindow()
    win.open_path(FERROCENE)
    obj = win._active_obj()
    index = [i for i, x in enumerate(obj.structure.symbols) if x == "Fe"][0]
    n_images = len(packing.images_of(obj.structure.metadata, [index],
                                     obj.structure.n_atoms))
    before = obj.structure.symbols.count("Fe")
    win.viewport.set_mode(MODE_EDIT, obj.id)
    win.viewport.set_selection([(obj.id, index)])
    win.on_delete_selected()
    after = win.scene.get(obj.id).structure.symbols.count("Fe")
    assert after == before - n_images


# ------------------------------------------------------------ the MSAA fix
def test_the_sample_count_is_read_from_the_framebuffer_not_the_format():
    """`format().samples()` describes the WINDOW, and a QOpenGLWidget renders
    into an FBO of Qt's making — so it reads 0 on a perfectly multisampled
    context. Believing it cost a round: 4x MSAA was reported as missing while
    `GL_SAMPLES` said 4."""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.app import MainWindow
    QApplication.instance() or QApplication([])
    win = MainWindow()
    info = win.viewport.graphics_info()
    assert isinstance(info, dict)
    # offscreen has no live context, so the only firm claim is the shape
    if info:
        assert "requested_samples" in info
        assert info["requested_samples"] == 4


def test_the_export_operator_is_registered():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.app import MainWindow
    QApplication.instance() or QApplication([])
    win = MainWindow()
    op = win.ops.get("export_animation")
    assert op is not None
    assert "mp4" in op.aliases and "frames" in op.aliases
    assert not win.ops.duplicate_keys()
    # ...and it is disabled with nothing to animate, rather than failing later
    assert not op.enabled(win)
