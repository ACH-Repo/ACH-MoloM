"""Round 59: Shift+DRAG reaches the re-framing, and the release is consistent.

Christian, 2026-08-10: "There is just one thing I would like to add though:
Shift+drag to adjust the view when in camera mode."

Round 58 built the mechanism and reported it as shipped — `truck_camera` exists,
is correct, and has four tests. But every one of those tests CALLS IT DIRECTLY,
so none of them touched the routing, and the routing hung it off `_nav_drag ==
"pan"`, which `_nav_drag_kind` only returns for Shift+MIDDLE-drag. On the
plain gesture — Shift + left-drag — a camera view still started an additive box
select. That is the whole lesson of this file: a mechanism with tests and no
gesture test is a feature nobody can reach.

The second half pins the packaging metadata that the release itself depends on,
because a version that disagrees with itself is only discovered by a user.
"""

import os
import re

import numpy as np
import pytest

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def win():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.app import MainWindow
    QApplication.instance() or QApplication([])
    return MainWindow()


def _move(vp, x, y, mods=None):
    """One mouse-move event, as Qt would deliver it."""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    return vp.mouseMoveEvent(QMouseEvent(
        QEvent.MouseMove, QPointF(float(x), float(y)), Qt.NoButton,
        Qt.LeftButton, Qt.ShiftModifier if mods is None else mods))


def _press(vp, x, y, mods=None):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    return vp.mousePressEvent(QMouseEvent(
        QEvent.MouseButtonPress, QPointF(float(x), float(y)), Qt.LeftButton,
        Qt.LeftButton, Qt.ShiftModifier if mods is None else mods))


def _release(vp, x, y, mods=None):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    return vp.mouseReleaseEvent(QMouseEvent(
        QEvent.MouseButtonRelease, QPointF(float(x), float(y)), Qt.LeftButton,
        Qt.NoButton, Qt.ShiftModifier if mods is None else mods))


# ------------------------------------------- the gesture reaches the mechanism
def test_shift_LEFT_drag_re_frames_the_shot(win):
    """The plain gesture, on the button every mouse and trackpad has."""
    win.on_place_camera()
    vp = win.viewport
    cam = win.scene.active_camera()
    before = np.array(cam.center)
    aim = np.array(cam.rotation)
    dist = float(cam.distance)

    _press(vp, 400, 300)
    _move(vp, 440, 300)
    _move(vp, 470, 312)

    assert not np.allclose(cam.center, before), \
        "Shift+left-drag inside a camera view must move the camera object"
    # a truck slides the camera; it does not turn it or dolly it
    assert np.allclose(cam.rotation, aim)
    assert cam.distance == pytest.approx(dist)
    # and it is the CAMERA that moved, so the view follows it
    assert np.allclose(vp.camera.center, cam.center)
    _release(vp, 470, 312)


def test_shift_left_drag_does_not_box_select_inside_a_camera(win):
    """The bug this round fixes: the drag was starting an additive box select,
    so the gesture Christian asked for selected atoms instead of re-framing."""
    win.on_place_camera()
    vp = win.viewport
    _press(vp, 400, 300)
    _move(vp, 460, 340)
    assert vp._region_drag is None
    _release(vp, 460, 340)


def test_shift_left_drag_still_box_selects_OUTSIDE_a_camera(win):
    """Scoped to a camera view: additive box select is untouched everywhere
    else, which is where it is the established gesture."""
    from PySide6.QtCore import Qt
    win.open_path(os.path.join(DATA, "orca_freq_h3po4.out"))
    vp = win.viewport
    assert vp.looking_through is None
    _press(vp, 400, 300)
    _move(vp, 460, 340)
    assert vp._region_drag is not None
    assert vp._region_drag["additive"] is True
    _release(vp, 460, 340)


def test_an_armed_select_tool_still_wins_inside_a_camera(win):
    """Round 52's rule: an explicitly armed tool owns every click. Arming box
    or lasso is a deliberate statement, so it must not be shadowed."""
    win.on_place_camera()
    vp = win.viewport
    vp.set_select_tool("lasso")
    _press(vp, 400, 300)
    _move(vp, 460, 340)
    assert vp._region_drag is not None
    assert vp._region_drag["kind"] == "lasso"
    _release(vp, 460, 340)
    vp.set_select_tool(None)


def test_a_plain_left_drag_inside_a_camera_still_selects(win):
    """Without the modifier the drag is still a box select — the re-framing is
    the MODIFIED gesture, so nothing that worked before is taken away."""
    from PySide6.QtCore import Qt
    win.on_place_camera()
    vp = win.viewport
    cam = win.scene.active_camera()
    before = np.array(cam.center)
    _press(vp, 400, 300, mods=Qt.NoModifier)
    _move(vp, 460, 340, mods=Qt.NoModifier)
    assert vp._region_drag is not None
    assert vp._region_drag["additive"] is False
    assert np.allclose(cam.center, before)
    _release(vp, 460, 340, mods=Qt.NoModifier)


def test_the_whole_shift_left_drag_is_one_undo_step(win):
    win.on_place_camera()
    vp = win.viewport
    cam = win.scene.active_camera()
    depth = len(win.undo._stack) if hasattr(win.undo, "_stack") else None
    _press(vp, 400, 300)
    for k in range(8):
        _move(vp, 400 + 6 * (k + 1), 300)
    assert vp._truck_gesture == cam.id
    _release(vp, 460, 300)
    assert vp._truck_gesture is None
    if depth is not None:
        assert len(win.undo._stack) == depth + 1


def test_a_re_framing_drag_does_not_pick_on_release(win):
    """A drag that moved the camera must not also select whatever it started
    over — the same rule an orbit release already follows."""
    win.on_place_camera()
    vp = win.viewport
    vp.set_selection([])
    _press(vp, 400, 300)
    _move(vp, 460, 330)
    _release(vp, 460, 330)
    assert vp.selection == []


def test_a_frame_handle_still_wins_over_the_re_framing(win):
    """The handle is a deliberate target drawn on top of the scene, and it is
    tested before picking for exactly that reason (round 58). A Shift+drag
    starting on one must move the BORDER, not the camera."""
    win.on_place_camera()
    vp = win.viewport
    cam = win.scene.active_camera()
    rect = vp.camera_rect()
    if rect is None:
        pytest.skip("no frame rect in this window geometry")
    x, y, w, h = rect
    before = np.array(cam.center)
    _press(vp, x + w, y + h / 2.0)       # the right EDGE handle
    if vp._frame_drag is None:
        pytest.skip("frame handle not hit at this window size")
    _move(vp, x + w + 30, y + h / 2.0)
    assert np.allclose(cam.center, before), \
        "dragging a handle must not move the camera"
    _release(vp, x + w + 30, y + h / 2.0)


# ----------------------------------------------------- the release metadata
def _pyproject():
    with open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8") as fh:
        return fh.read()


def test_the_packaged_version_is_the_version_in_the_code():
    """Two places name the version and a release is the moment they disagree."""
    from molom import __version__
    text = _pyproject()
    declared = re.search(r'(?m)^version\s*=\s*"([^"]+)"', text).group(1)
    assert declared == __version__


def test_the_readme_is_the_long_description_and_is_valid_markdown():
    text = _pyproject()
    assert 'readme = "README.md"' in text
    body = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
    # A PyPI page is the shop window: it must not be the skeleton's page.
    assert "skeleton" not in body.lower()
    assert body.lstrip().startswith("#")


def test_every_shipped_subpackage_is_declared():
    """`packages = [...]` is a hand-written list, so a new subpackage is
    silently left out of the wheel — and `molom/addons/` is loaded by NAME at
    run time, so its absence is a broken feature rather than an import error."""
    text = _pyproject()
    declared = set(re.findall(r'"(molom(?:\.[a-z_]+)*)"', text))
    on_disk = set()
    for root, dirs, files in os.walk(os.path.join(ROOT, "molom")):
        dirs[:] = [d for d in dirs if d not in ("__pycache__",)]
        if "__init__.py" in files:
            rel = os.path.relpath(root, ROOT).replace(os.sep, ".")
            on_disk.add(rel)
    assert on_disk <= declared, \
        "not in pyproject's packages: {}".format(sorted(on_disk - declared))
