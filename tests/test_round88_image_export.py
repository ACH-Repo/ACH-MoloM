"""Round 88: one dialog owns every still-export option.

Christian: "I am also getting confused by the re-rendering/settings dialogue.
I don't think it shows the entire image export settings dialogue where
everything can be set. Like in GIMP I mean... We need a straight-forward way
of setting all these rendering options for simple PNG exports that do not
conflict with each other."

The confusion was real and structural. Exporting a still had **no dialog at
all** - a bare file picker - while the options that decide what comes out
(resolution multiplier, mesh subdivision, crop-to-content) lived in **App >
Settings**, and the unit-cell z-order only in F3. So the export asked one
question and silently obeyed four answers given elsewhere, one of which
deliberately differs from what the viewport is showing.
"""
import os

import pytest


@pytest.fixture
def win():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.app import MainWindow
    QApplication.instance() or QApplication([])
    w = MainWindow()
    w.load_default_scene()
    return w


@pytest.fixture
def dialog(win, tmp_path):
    from molom.ui.dialogs import ImageExportDialog

    def build(remembered=None, path=None):
        return ImageExportDialog(
            win, win.viewport,
            path=str(path or (tmp_path / "shot.png")),
            remembered=remembered)
    return build


# ------------------------------------------------------------ the options
def test_every_option_the_render_takes_is_on_the_dialog(dialog):
    """The point of the round: nothing that changes the output is set
    somewhere else. Each of these was previously in App > Settings or F3."""
    opts = dialog().options()
    assert set(opts) == {"path", "increment", "scale", "subdiv", "crop",
                         "margin", "transparent", "labels", "cell_depth"}


def test_the_pixel_size_is_shown_rather_than_implied(dialog):
    """A multiplier is abstract; a pixel count is the thing you check before
    pressing Export."""
    dlg = dialog()
    dlg.scale.setValue(1)
    one = dlg.pixel_size()
    dlg.scale.setValue(3)
    assert dlg.pixel_size() == (one[0] * 3, one[1] * 3)
    assert "{} x {}".format(*dlg.pixel_size()) in dlg.size_label.text()


def test_the_crop_margin_is_dead_while_cropping_is_off(dialog):
    """An enabled-looking control that applies to nothing is the thing this
    project keeps finding as a bug."""
    dlg = dialog()
    dlg.crop.setChecked(False)
    assert not dlg.margin.isEnabled()
    dlg.crop.setChecked(True)
    assert dlg.margin.isEnabled()
    assert "before cropping" in dlg.size_label.text()


def test_a_transparent_JPEG_is_warned_about(dialog, tmp_path):
    """JPEG has no alpha channel, so a transparent export comes out black -
    silently, and only once you open the file."""
    dlg = dialog(path=tmp_path / "shot.jpg")
    dlg.transparent.setChecked(True)
    assert "alpha" in dlg.note.text().lower()
    dlg.transparent.setChecked(False)
    assert "alpha" not in dlg.note.text().lower()


def test_it_opens_on_the_remembered_choices(dialog):
    """Re-picking six settings to change one is pure friction (round 61)."""
    remembered = {"scale": 4, "subdiv": 0, "crop": True, "margin": 40,
                  "transparent": False, "labels": True, "cell_depth": False,
                  "increment": False, "path": ""}
    opts = dialog(remembered=remembered).options()
    for key, value in remembered.items():
        if key != "path":
            assert opts[key] == value, key


# --------------------------------------------------------- one write path
def test_the_first_export_and_F12_use_ONE_code_path():
    """A repeat that can differ from the export that set it up is half of
    what made this confusing. Both routes go through `_write_still`."""
    import inspect
    from molom.ui.app import MainWindow
    for name in ("on_export_image", "_render_still_again"):
        source = inspect.getsource(getattr(MainWindow, name))
        assert "_write_still" in source


# The three checks that RENDER live in `tools/smoke_gui.py`, not here:
# `render_image` builds a `QOpenGLFramebufferObject`, and with no live GL
# context that is an ACCESS VIOLATION which takes the whole run down rather
# than failing one test (round 60). Written here first, and it duly
# segfaulted the suite.
#
#   * F12 renders the SAME size as the export that set it up
#   * the cell z-order tick reaches the file
#   * exporting does not leave the viewport's z-order changed


def test_asking_for_the_settings_again_keeps_the_last_ones(win):
    """The one route whose whole purpose is "let me change a setting" used to
    be the one route that threw them away: it popped the remembered target
    before reopening, so the dialog came up on the defaults."""
    import inspect
    source = inspect.getsource(win.__class__.on_render_settings)
    assert "_render_target.pop" not in source


# ------------------------------------------------- the camera branch
def test_the_dialog_opens_while_looking_through_a_camera(win, tmp_path):
    """It shipped raising `AttributeError: 'CameraObject' object has no
    attribute 'resolution'` the moment a camera was active.

    A CameraObject stores `width`/`height` and applies its own `multiplier`
    through `render_size()`; the attribute name was GUESSED. Every test wrote
    for this dialog drove it in the free view, so the camera branch had no
    test at all - and it is not an exotic path, it is the one you are on
    whenever you compose a shot. Christian hit it on the first try.
    """
    from molom.ui.dialogs import ImageExportDialog
    win.on_place_camera()
    cam = win.scene.cameras[-1]
    win.on_activate_camera(cam.id)
    assert win.viewport.active_camera_object() is cam

    dlg = ImageExportDialog(win, win.viewport, path=str(tmp_path / "s.png"))
    dlg.scale.setValue(1)
    assert dlg.pixel_size() == cam.render_size()
    assert "camera" in dlg.note.text().lower()


def test_the_cameras_own_multiplier_is_carried(win, tmp_path):
    """512x512 at 2x is a different statement from 1024x1024 (round 56), and
    the export honours it - so the dialog has to show it."""
    from molom.ui.dialogs import ImageExportDialog
    win.on_place_camera()
    cam = win.scene.cameras[-1]
    win.on_activate_camera(cam.id)
    cam.multiplier = 2.0
    dlg = ImageExportDialog(win, win.viewport, path=str(tmp_path / "s.png"))
    dlg.scale.setValue(1)
    assert dlg.pixel_size() == cam.render_size() == (cam.width * 2,
                                                     cam.height * 2)


def test_export_image_runs_as_an_operator_with_a_camera_active(win,
                                                               monkeypatch):
    """The exact path from the traceback: `run_op("export_image")`."""
    from PySide6.QtWidgets import QDialog
    from molom.ui import dialogs
    monkeypatch.setattr(dialogs.ImageExportDialog, "exec",
                        lambda self: QDialog.Rejected)
    win.on_place_camera()
    win.on_activate_camera(win.scene.cameras[-1].id)
    win.run_op("export_image")          # must not raise
