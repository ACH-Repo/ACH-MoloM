"""Round 56: camera OBJECTS — saved viewpoints that ride the savefile.

Christian, 2026-08-09: "introduce camera objects like in blender... that way a
savefile can retain previously used angles." Plus the lens and film settings,
the frame handles, Numpad 0, and what it all means for the Blender export.
"""

import os

import numpy as np
import pytest

from molom.core import blender_export as bx
from molom.core import cameras
from molom.core.camera import Camera
from molom.core.scene import Scene


# ------------------------------------------------------------------- lens
def test_focal_length_is_millimetres_against_a_sensor():
    """NOT Angstrom. Angstrom is the scene's unit; a focal length only means
    something relative to the film it projects onto, and (50 mm, 36 mm) is a
    pair every photographer and every Blender user can already picture."""
    # the textbook figure: 50 mm on full frame is ~39.6 deg horizontally
    assert cameras.fov_y_degrees(50.0, 36.0) == pytest.approx(39.6, abs=0.1)
    # a longer lens sees less
    assert cameras.fov_y_degrees(85.0, 36.0) < cameras.fov_y_degrees(50.0,
                                                                     36.0)


def test_the_aspect_ratio_changes_the_VERTICAL_field_of_view():
    """The sensor size is horizontal, so a 16:9 camera and a square one with
    the same lens must not frame the same height."""
    wide = cameras.fov_y_degrees(50.0, 36.0, aspect=16.0 / 9.0)
    square = cameras.fov_y_degrees(50.0, 36.0, aspect=1.0)
    assert wide < square


def test_focal_and_fov_are_inverses():
    for focal in (18.0, 35.0, 50.0, 135.0):
        fov = cameras.fov_y_degrees(focal, 36.0, 1.5)
        assert cameras.focal_from_fov(fov, 36.0, 1.5) == pytest.approx(focal)


def test_the_multiplier_is_separate_from_the_resolution():
    """512x512 at 2x is a different statement from 1024x1024: it says "this
    framing, finer", and survives deciding later that the figure wants 4x."""
    cam = cameras.CameraObject(1)
    cam.width, cam.height, cam.multiplier = 512, 512, 2.0
    assert cam.render_size() == (1024, 1024)
    cam.multiplier = 4.0
    assert cam.render_size() == (2048, 2048)
    assert (cam.width, cam.height) == (512, 512)      # untouched


# -------------------------------------------------------------- the scene
def test_a_camera_captures_the_view_and_gives_it_back():
    sc = Scene()
    live = Camera()
    live.fit(np.array([1.0, 2.0, 3.0]), 8.0)
    live.rotate(70.0, -30.0)
    cam = sc.add_camera("Front", camera=live, width=1280, height=720)
    assert cam.width == 1280 and cam.height == 720

    moved = Camera()
    moved.rotate(200.0, 40.0)
    cam.apply_to(moved)
    assert np.allclose(moved.rotation, live.rotation)
    assert np.allclose(moved.center, live.center)
    assert moved.distance == pytest.approx(live.distance)


def test_the_captured_lens_frames_what_the_user_was_looking_at():
    """"Place a camera here" must not silently widen the shot."""
    sc = Scene()
    live = Camera()
    cam = sc.add_camera(camera=live, width=1600, height=900)
    assert cam.fov_y == pytest.approx(Camera.FOV_Y, abs=1e-6)


def test_cameras_are_a_separate_list_from_the_molecules():
    """A camera has no atoms, so every loop that draws, picks, exports or
    perceives bonds would otherwise have to learn to skip it."""
    from molom.core import build
    sc = Scene()
    sc.add(build.cubane(), name="cubane")
    sc.add_camera("A", camera=Camera())
    assert sc.n_objects == 1
    assert len(sc.cameras) == 1
    assert all(hasattr(o, "structure") for o in sc.objects)


def test_camera_names_are_unique():
    sc = Scene()
    a = sc.add_camera("Shot", camera=Camera())
    b = sc.add_camera("Shot", camera=Camera())
    assert a.name != b.name
    assert sc.rename_camera(b.id, "Shot") != "Shot"


def test_deleting_the_active_camera_picks_another():
    sc = Scene()
    a = sc.add_camera("A", camera=Camera())
    b = sc.add_camera("B", camera=Camera())
    assert sc.active_camera_id == b.id
    sc.remove_camera(b.id)
    assert sc.active_camera_id == a.id
    sc.remove_camera(a.id)
    assert sc.active_camera_id is None


def test_cameras_survive_the_savefile_and_undo():
    """The whole point of them: "a savefile can retain previously used
    angles"."""
    import json
    sc = Scene()
    cam = sc.add_camera("Hero", camera=Camera(), width=800, height=450)
    cam.focal_mm, cam.roll, cam.multiplier = 85.0, 0.42, 2.0
    cam.projection = cameras.ORTHOGRAPHIC

    data = sc.to_dict()
    json.dumps(data)                       # must stay JSON-safe
    back = Scene()
    back.from_dict(data)
    got = back.cameras[0]
    assert got.name == "Hero" and got.focal_mm == 85.0
    assert got.roll == pytest.approx(0.42)
    assert got.projection == cameras.ORTHOGRAPHIC
    assert got.render_size() == (1600, 900)
    assert back.active_camera_id == cam.id

    snap = sc.snapshot()
    sc.remove_camera(cam.id)
    sc.restore(snap)
    assert [c.name for c in sc.cameras] == ["Hero"]


def test_from_dict_carries_everything_snapshot_produces():
    """`from_dict` rebuilds the snapshot dict BY HAND, so anything added to
    `snapshot` and not added there is silently lost on load — which is how
    the cameras vanished from the first savefile that had them."""
    sc = Scene()
    sc.add_camera("A", camera=Camera())
    keys = set(sc.snapshot())
    back = Scene()
    back.from_dict(sc.to_dict())
    assert keys <= set(back.snapshot())
    assert back.cameras


# --------------------------------------------------------------- the frame
def test_the_frame_keeps_the_cameras_aspect_inside_the_window():
    """Round 57 made the frame ANGULAR, so it is sized from the half-angles
    and a fitted zoom rather than from the aspect alone — see
    `cameras.frame_rect`."""
    cam = cameras.CameraObject(1)
    cam.width, cam.height = 1920, 1080
    tx, ty = cam.half_angles()
    zoom = cameras.fit_frame_zoom(800, 600, tx, ty)
    x, y, w, h = cameras.frame_rect(800, 600, tx, ty, zoom=zoom)
    assert w / h == pytest.approx(16.0 / 9.0)
    assert w <= 800 and h <= 600
    assert x == pytest.approx((800 - w) / 2.0)         # centred
    assert y == pytest.approx((600 - h) / 2.0)


def test_a_tall_camera_fits_by_height():
    cam = cameras.CameraObject(1)
    cam.width, cam.height = 500, 1000                 # aspect 0.5
    tx, ty = cam.half_angles()
    zoom = cameras.fit_frame_zoom(800, 600, tx, ty)
    _x, _y, w, h = cameras.frame_rect(800, 600, tx, ty, zoom=zoom)
    assert h <= 600 and w / h == pytest.approx(0.5)


def test_the_handles_are_where_they_look():
    rect = (10.0, 20.0, 100.0, 50.0)
    assert cameras.handle_at(rect, 10.0, 20.0) == "nw"
    assert cameras.handle_at(rect, 110.0, 70.0) == "se"
    assert cameras.handle_at(rect, 60.0, 20.0) == "n"
    assert cameras.handle_at(rect, 500.0, 500.0) is None


def test_a_corner_wins_over_an_edge():
    """Dragging the very corner of a rectangle should never resize only one
    edge, so corners are tested first."""
    rect = (0.0, 0.0, 20.0, 20.0)
    assert cameras.handle_at(rect, 0.0, 0.0, radius=30.0) in ("nw",)


def test_dragging_an_edge_changes_only_its_own_axis():
    """The ASPECT moves; the pixel count does not, because the longer side is
    pinned (round 57 — dragging must not be able to inflate the render)."""
    rect = (0.0, 0.0, 200.0, 100.0)
    w, h = cameras.resize_pixels("e", 400, 200, 20.0, 999.0, rect)
    assert w / h > 400 / 200              # wider shot
    assert max(w, h) == 400               # same pixel budget


def test_dragging_a_corner_changes_both():
    rect = (0.0, 0.0, 200.0, 100.0)
    wide = cameras.resize_pixels("se", 400, 200, 40.0, 0.0, rect)
    tall = cameras.resize_pixels("se", 400, 200, 0.0, 40.0, rect)
    assert wide[0] / wide[1] > 2.0        # dragged out sideways: wider
    assert tall[0] / tall[1] < 2.0        # dragged down: taller


def test_the_frame_can_never_be_dragged_to_nothing():
    rect = (0.0, 0.0, 200.0, 100.0)
    w, h = cameras.resize_pixels("se", 400, 200, -1e6, -1e6, rect)
    assert w >= 16 and h >= 16


# ------------------------------------------------------- the Blender export
def test_a_saved_camera_becomes_a_blender_camera():
    from molom.core import build
    from molom.core import style as style_mod
    sc = Scene()
    sc.add(build.cubane(), name="cubane")
    cam = sc.add_camera("Hero", camera=Camera(), width=640, height=360)
    cam.focal_mm, cam.multiplier = 85.0, 2.0
    data = bx.collect(sc, style_mod.BALL_AND_STICK, bx.ExportOptions())
    assert len(data["saved_cameras"]) == 1
    spec = data["saved_cameras"][0]
    assert spec["name"] == "Hero"
    assert spec["lens"] == pytest.approx(85.0)
    assert spec["sensor"] == pytest.approx(36.0)
    # the multiplier is baked into the render size, as it is everywhere else
    assert spec["resolution"] == [1280, 720]
    assert data["active_camera"] == "Hero"


def test_the_active_saved_camera_wins_over_the_viewport_pose():
    """Looking through a camera and exporting must render THAT shot."""
    from molom.core import build
    from molom.core import style as style_mod
    sc = Scene()
    sc.add(build.cubane(), name="cubane")
    live = Camera()
    live.fit(np.zeros(3), 4.0)
    cam = sc.add_camera("Hero", camera=Camera(), width=800, height=800)
    cam.distance = 99.0
    data = bx.collect(sc, style_mod.BALL_AND_STICK, bx.ExportOptions(),
                      camera=live)
    assert data["camera"]["name"] == "Hero"
    assert data["camera"]["resolution"] == [800, 800]


def test_roll_survives_into_the_matrix():
    """The interactive camera is a turntable and cannot hold a rolled pose,
    so a saved camera carries roll explicitly — and it has to reach Blender,
    or a deliberately tilted shot exports level."""
    cam = cameras.CameraObject(1, "Tilt")
    level = bx.camera_object_setup(cam)
    cam.roll = np.radians(30.0)
    tilted = bx.camera_object_setup(cam)
    assert not np.allclose(np.asarray(level["matrix"]),
                           np.asarray(tilted["matrix"]))
    # ...and it is a ROTATION: the eye does not move, only the framing turns
    assert np.allclose(level["eye"], tilted["eye"], atol=1e-6)


def test_the_script_builds_the_saved_cameras():
    from molom.core import build
    from molom.core import style as style_mod
    import ast
    sc = Scene()
    sc.add(build.cubane(), name="cubane")
    sc.add_camera("Hero", camera=Camera())
    opts = bx.ExportOptions()
    data = bx.collect(sc, style_mod.BALL_AND_STICK, opts)
    src = bx.build_script(data, opts)
    compile(src, "<script>", "exec")
    node = [n for n in ast.parse(src).body
            if isinstance(n, ast.Assign) and n.targets[0].id == "SAVED_CAMERAS"]
    assert len(ast.literal_eval(node[0].value)) == 1
    assert "def build_saved_cameras(" in src
    # the lens is set DIRECTLY, not round-tripped through a field of view
    assert "data.lens = spec[\"lens\"]" in src
    assert "sensor_width" in src


def test_no_cameras_still_exports_the_viewport_one():
    """Nothing is taken away from a scene that has never saved a view."""
    from molom.core import build
    from molom.core import style as style_mod
    sc = Scene()
    sc.add(build.cubane(), name="cubane")
    live = Camera()
    data = bx.collect(sc, style_mod.BALL_AND_STICK, bx.ExportOptions(),
                      camera=live)
    assert data["saved_cameras"] == []
    assert data["camera"] is not None


# ------------------------------------------------------------------ the UI
@pytest.fixture
def win():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.app import MainWindow
    QApplication.instance() or QApplication([])
    return MainWindow()


def test_numpad_zero_toggles_the_camera(win):
    """Toggling rather than only entering is what makes the key usable: you
    glance through the shot, then go back to composing."""
    win.load_default_scene()
    win.viewport.camera.rotate(80.0, -40.0)
    before = np.array(win.viewport.camera.rotation)
    win.on_place_camera()
    assert win.viewport.looking_through is not None

    win.on_activate_camera()                      # out
    assert win.viewport.looking_through is None
    win.viewport.camera.rotate(200.0, 10.0)
    win.on_activate_camera()                      # back in
    assert win.viewport.looking_through is not None
    assert np.allclose(win.viewport.camera.rotation, before, atol=1e-9)


def test_leaving_a_camera_restores_where_you_were(win):
    win.load_default_scene()
    win.on_place_camera()
    win.on_activate_camera()                      # leave
    free = np.array(win.viewport.camera.rotation)
    win.viewport.camera.rotate(150.0, 20.0)
    moved = np.array(win.viewport.camera.rotation)
    win.on_activate_camera()                      # enter
    win.on_activate_camera()                      # leave again
    assert np.allclose(win.viewport.camera.rotation, moved, atol=1e-9)
    assert not np.allclose(moved, free)


def test_the_operators_are_registered(win):
    for op_id in ("camera_place", "camera_activate", "camera_update",
                  "camera_delete"):
        assert win.ops.get(op_id) is not None
    assert win.ops.get("camera_activate").key == "Num+0"
    assert not win.ops.duplicate_keys()


def test_the_page_edits_the_camera_and_greys_out_without_one(win):
    win.load_default_scene()
    page = win.camera_page
    page.set_camera(None)
    assert not page.focal.isEnabled()
    win.on_place_camera()
    page.set_camera(win.scene.active_camera())
    assert page.focal.isEnabled()
    page.focal.setValue(105.0)
    assert win.scene.active_camera().focal_mm == pytest.approx(105.0)
    page.multiplier.setValue(3.0)
    assert win.scene.active_camera().multiplier == pytest.approx(3.0)


def test_the_frame_is_only_drawn_while_looking_through_one(win):
    win.load_default_scene()
    win.viewport.resize(800, 600)
    assert win.viewport.camera_rect() is None
    win.on_place_camera()
    rect = win.viewport.camera_rect()
    assert rect is not None and rect[2] > 0
    win.on_activate_camera()                      # leave
    assert win.viewport.camera_rect() is None
