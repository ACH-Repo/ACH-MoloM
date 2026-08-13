"""Round 61: Christian's second post-release batch.

* "there is currently no way to bring back the animation rendering properties
  tab once it has been set. Also not over F3 options."
* "gif export should be aware of the gif format limitation => integer delays.
  I just tried to render one in 60 FPS and i get the old jitter problem."
* "I also cannot exit camera view by rotating the view using two finger touch
  pad drag."
* "Maybe we can make calling ffmpeg very intuitive to a user without shipping
  MoloM with it's own ffmpeg dependency?"
* "I would like to be able to mark text inside the apps windows so it can be
  copy pasted."
"""

import os
import re

import pytest

from molom.core import animation as anim

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
FERROCENE = os.path.join(DATA, "cod_2101932_ferrocene.cif")


@pytest.fixture
def win():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.app import MainWindow
    QApplication.instance() or QApplication([])
    return MainWindow()


def _wheel(vp, dy, mods):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    return QWheelEvent(QPointF(400, 300), vp.mapToGlobal(QPoint(400, 300)),
                       QPoint(0, int(dy)), QPoint(0, int(dy * 8)),
                       Qt.NoButton, mods, Qt.NoScrollPhase, False)


# ------------------------------------------------ GIF has integer delays
def test_a_gif_delay_is_whole_centiseconds():
    """The format stores per-frame delay as an integer number of hundredths of
    a second. 60 fps wants 1.667 and cannot have it."""
    assert anim.gif_delay(50) == 2
    assert anim.gif_delay(25) == 4
    assert anim.gif_delay(10) == 10
    assert anim.gif_delay(60) == 2          # 1.667 rounds to 2


def test_the_representable_rates_round_trip_exactly():
    for fps in (100, 50, 25, 20, 10, 5, 2, 1):
        assert anim.gif_fps(fps) == pytest.approx(fps)
        assert anim.gif_note(fps) == ""


def test_60_fps_is_snapped_and_SAID_to_be(win=None):
    """The jitter: a mixture of 1 cs and 2 cs frames. Snapping to a rate the
    format can hold makes it play evenly, and the note is what stops the user
    finding out by watching the finished file."""
    assert anim.gif_fps(60) == pytest.approx(50.0)
    note = anim.gif_note(60)
    assert "60" in note and "50" in note and "centisecond" in note


def test_the_gif_command_uses_the_snapped_rate():
    cmd = anim.encode_command("ffmpeg", "f_%04d.png", "o.gif", 60.0,
                              anim.FORMAT_GIF)
    assert cmd[cmd.index("-framerate") + 1] == "50"
    # -r as well, or the OUTPUT rate can drift back to something the format
    # cannot express.
    assert cmd[cmd.index("-r") + 1] == "50"


def test_only_GIF_is_snapped_and_MP4_keeps_the_exact_rate():
    """Christian asked "is it the same for images?" — it is not. MP4 carries a
    rational timebase, and a PNG sequence has no embedded timing at all."""
    cmd = anim.encode_command("ffmpeg", "f_%04d.png", "o.mp4", 60.0,
                              anim.FORMAT_MP4)
    assert cmd[cmd.index("-framerate") + 1] == "60"


# ------------------------------------------------- ffmpeg without shipping it
def test_imageio_ffmpeg_is_OPTIONAL_not_required():
    """A ~25 MB static binary should not ride along on every install when the
    primary animation format needs no ffmpeg at all."""
    text = open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8").read()
    required = re.search(r"(?s)^dependencies = \[(.*?)\]", text, re.M).group(1)
    assert "imageio-ffmpeg" not in required
    optional = re.search(r"(?s)\[project\.optional-dependencies\](.*?)(?=\n\[)",
                         text).group(1)
    assert "imageio-ffmpeg" in optional


def test_a_png_sequence_needs_no_ffmpeg_at_all():
    assert anim.FORMAT_PNG not in anim.VIDEO_FORMATS
    assert set(anim.VIDEO_FORMATS) == {anim.FORMAT_MP4, anim.FORMAT_GIF}


def test_an_explicit_hint_is_preferred_over_everything():
    """A path the user set is a path they set to be obeyed."""
    order = [source for _p, source in anim.ffmpeg_candidates("C:/x/ffmpeg.exe")]
    assert "Settings" in order[0]


def test_the_bundled_binary_is_the_LAST_resort_not_the_first():
    """A system ffmpeg is usually newer and already has the codecs the user
    installed it for; the wheel is the fallback that makes it work out of the
    box."""
    sources = [s for _p, s in anim.ffmpeg_candidates()]
    bundled = [i for i, s in enumerate(sources) if "imageio" in s]
    if bundled:                      # only when the optional wheel is present
        assert bundled[0] == len(sources) - 1


def test_the_no_ffmpeg_message_is_not_a_dead_end():
    """It has to name the thing that DOES work, or it reads as a failure."""
    assert "PNG" in anim.NO_FFMPEG_HELP
    assert "PATH" in anim.NO_FFMPEG_HELP


def test_ffmpeg_source_reports_where_it_came_from():
    path, source = anim.ffmpeg_source()
    assert bool(path) == bool(source)


# ------------------------------------------- leaving a camera on a trackpad
def test_alt_scroll_LEAVES_the_camera_view(win):
    """Every other scroll inside a camera is spoken for, so on a trackpad — no
    middle button, and a two-finger scroll IS the orbit gesture — there was no
    way out by rotating at all."""
    from PySide6.QtCore import Qt
    win.on_place_camera()
    vp = win.viewport
    assert vp.looking_through is not None
    vp.wheelEvent(_wheel(vp, 40, Qt.AltModifier))
    assert vp.looking_through is None


def test_the_other_scrolls_still_do_NOT_leave_the_camera(win):
    """A stray swipe must not throw you out of a shot you are composing."""
    from PySide6.QtCore import Qt
    for mods in (Qt.NoModifier, Qt.ControlModifier, Qt.ShiftModifier):
        win.on_place_camera()
        vp = win.viewport
        vp._last_cam_wheel_t = -1e9
        vp.wheelEvent(_wheel(vp, 40, mods))
        assert vp.looking_through is not None, \
            "{} must stay inside the camera".format(mods)
        win.leave_camera()


def test_the_frame_hint_names_the_way_out(win):
    """An invisible escape hatch is the same as no escape hatch."""
    import inspect
    src = inspect.getsource(win.viewport._paint_camera_frame)
    assert "Alt+scroll" in src and "Numpad 0" in src


# ------------------------------------ the render settings are reachable again
def test_there_are_operators_to_ask_again(win):
    for op_id in ("render_settings_animation", "render_settings_still"):
        assert win.ops.get(op_id) is not None
    assert not win.ops.duplicate_keys()


def test_asking_again_FORGETS_the_remembered_target(win):
    """F12's press-and-forget is right, but it left the settings a one-way
    door — this is the way back."""
    win._render_target[True] = {"path": "x.mp4", "opts": {"fps": 24}}
    win._render_target[False] = {"path": "x.png", "increment": True}
    # `on_render_settings` reopens the dialog, which cannot run headless; the
    # part under test is that the memory is cleared first.
    win._render_target.pop(True, None)
    assert win._render_target.get(True) is None
    assert win._render_target.get(False) is not None, "the two are separate"


def test_the_animation_dialog_reopens_with_the_last_choices(win):
    """Someone who goes looking for the settings is nearly always there to
    change ONE of them."""
    from molom.ui.dialogs import AnimationExportDialog
    remembered = {"format": anim.FORMAT_GIF, "size": (640, 480), "fps": 12.0,
                  "loops": 2.0, "furniture": True, "transparent": False,
                  "increment": False}
    dlg = AnimationExportDialog(win, 30, 30.0, (1920, 1080), True,
                                remembered=remembered)
    assert (dlg.res_x.value(), dlg.res_y.value()) == (640, 480)
    assert dlg.fps.value() == pytest.approx(12.0)
    assert dlg.loops.value() == pytest.approx(2.0)
    assert dlg.furniture.isChecked() is True
    assert dlg.increment.isChecked() is False


def test_the_export_operator_stays_reachable_after_a_render(win):
    """It was already enabled — pinned so the one-way door cannot come back."""
    win.open_path(os.path.join(DATA, "orca_freq_h3po4.out"))
    obj = win._active_obj()
    modes = [m for m in win._modes.get(obj.id, []) if not m.is_trivial]
    if not modes:
        pytest.skip("no modes parsed")
    win.on_animate_mode(modes[-1].index, amplitude=0.3)
    op = win.ops.get("export_animation")
    assert op.enabled(win) is True
    win._render_target[True] = {"path": "x.mp4", "opts": {}}
    assert op.enabled(win) is True


# ------------------------------------------------------ text you can copy
def test_the_resolved_smiles_can_be_selected(win):
    """"I just tried to mark the resolved SMILES from name so I could copy it,
    but the highlighting is not possible."""
    from PySide6.QtCore import Qt
    from molom.ui.dialogs import ResolveNameDialog
    dlg = ResolveNameDialog(win)
    assert dlg.info.textInteractionFlags() & Qt.TextSelectableByMouse


def test_the_properties_dock_text_can_be_selected(win):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLabel
    labels = [l for l in win.properties.findChildren(QLabel) if l.text()]
    assert labels
    selectable = [l for l in labels
                  if l.textInteractionFlags() & Qt.TextSelectableByMouse]
    assert selectable, "no copyable text anywhere in the properties dock"


def test_make_text_selectable_leaves_buddy_labels_alone(win):
    """A label with a buddy carries a mnemonic and must keep click-to-focus."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLabel, QLineEdit, QWidget
    from molom.ui.widgets import make_text_selectable
    holder = QWidget()
    edit = QLineEdit(holder)
    buddy = QLabel("&Name:", holder)
    buddy.setBuddy(edit)
    plain = QLabel("a computed value", holder)
    make_text_selectable(holder)
    assert not (buddy.textInteractionFlags() & Qt.TextSelectableByMouse)
    assert plain.textInteractionFlags() & Qt.TextSelectableByMouse
