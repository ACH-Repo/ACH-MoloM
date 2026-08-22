"""Round 57: what a camera view does, and what an animation does not break.

Christian's batch, 2026-08-10:

* "when a camera angle is viewed, then unless the camera is selected and
  grabbed, it should not move. rotating the view should immediately exit it
  like in blender, unless it is done with shift+drag or ctrl+drag. Any other
  regular view rotate should exit the view. Actually...Is it even possible to
  exit the current camera view?"
* "clicking on one of the scaling knobs of the camera view also resets a
  previous dolly for whatever reason. It shouldn't do that."
* "Can we also not just allow the scaling of the camera view to be
  more...arbitrary? Right now the corner drag buttons essentially do nothing."
* "clicking on animate for a mode of a freq job still resets the location of
  the molecule back to (0,0,0)... curiously, only the first animate click."
* "the orange selection highlight when an animation is played is out of sync
  with the position of the meshes."
* "when an animation shortens a bond far enough it is no longer drawn?"
"""

import os

import numpy as np
import pytest

from molom.core import blender_export as bx
from molom.core import bonding
from molom.core import cameras
from molom.core import vibrations as vib
from molom.core.camera import Camera, quat_to_mat3
from molom.core.scene import Scene

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
FREQ = os.path.join(DATA, "orca_freq_h3po4.out")


@pytest.fixture
def win():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.app import MainWindow
    QApplication.instance() or QApplication([])
    return MainWindow()


# ------------------------------------------------- the frame moves BORDERS
def _cam(width=1920, height=1080, focal=50.0):
    cam = cameras.CameraObject(1)
    cam.width, cam.height, cam.focal_mm = width, height, focal
    cam.fit_frame(800, 600)
    return cam


def _content_scale(cam, widget_w=800, widget_h=600):
    """Pixels per world unit at the pivot plane — what "the scene rescaled"
    means, measured rather than eyeballed."""
    rect = cameras.frame_rect(widget_w, widget_h, *cam.half_angles(),
                              zoom=cam.frame_zoom)
    fov = cameras.viewport_fov_y(cam.fov_y, rect[3], widget_h)
    return (widget_h / 2.0) / np.tan(np.radians(fov) / 2.0)


def test_dragging_a_handle_does_not_rescale_the_scene():
    """Christian: "when I pull the corners, the camera zooms out or is moved
    back. It shouldn't. I want the current camera position to not change and
    just adjust the borders of the camera view." """
    cam = _cam()
    before = _content_scale(cam)
    rect = cameras.frame_rect(800, 600, *cam.half_angles(), zoom=cam.frame_zoom)
    for handle, dx, dy in (("se", 40.0, 25.0), ("nw", 30.0, 30.0),
                           ("e", -50.0, 0.0), ("n", 0.0, 20.0)):
        sensor, w, h = cameras.resize_frame(handle, cam.focal_mm,
                                            cam.sensor_mm, cam.width,
                                            cam.height, dx, dy, rect)
        cam.sensor_mm, cam.width, cam.height = sensor, w, h
        assert _content_scale(cam) == pytest.approx(before, rel=1e-9)


def test_dragging_a_handle_moves_that_border():
    """It has to DO something: the shot gets wider or taller.

    The other axis holds to a tenth of a percent rather than exactly, because
    a resolution is whole pixels: `pixels_for_aspect` rounds, so the aspect —
    and with it the vertical half-angle — is quantised. The scale of the
    picture is not affected by that, which is why the test above can demand
    1e-9 of it.
    """
    cam = _cam()
    rect = cameras.frame_rect(800, 600, *cam.half_angles(), zoom=cam.frame_zoom)
    tx0, ty0 = cam.half_angles()

    sensor, w, h = cameras.resize_frame("e", cam.focal_mm, cam.sensor_mm,
                                        cam.width, cam.height, 40.0, 0.0, rect)
    tx, ty = cameras.half_angles(cam.focal_mm, sensor, w / h)
    assert tx > tx0                              # wider
    assert ty == pytest.approx(ty0, rel=2e-3)    # and no taller

    sensor, w, h = cameras.resize_frame("s", cam.focal_mm, cam.sensor_mm,
                                        cam.width, cam.height, 0.0, 30.0, rect)
    tx, ty = cameras.half_angles(cam.focal_mm, sensor, w / h)
    assert ty > ty0
    assert tx == pytest.approx(tx0, rel=2e-3)


def test_dragging_never_inflates_the_resolution():
    """The 6000x5000 Blender render: `build_render` takes the ACTIVE camera's
    resolution, and the handles were driving it directly, so a few drags
    ratcheted a 1x camera into a huge render."""
    cam = _cam(640, 360)
    for _ in range(40):
        rect = cameras.frame_rect(800, 600, *cam.half_angles(),
                                  zoom=cam.frame_zoom)
        sensor, w, h = cameras.resize_frame("se", cam.focal_mm, cam.sensor_mm,
                                            cam.width, cam.height,
                                            60.0, 40.0, rect)
        cam.sensor_mm, cam.width, cam.height = sensor, w, h
    assert max(cam.width, cam.height) == 640
    assert cam.render_size() == (640, int(round(640 / cam.aspect)))


# ---------------------------------------------------- the wheel is the zoom
def test_the_wheel_grows_the_frame_and_leaves_the_camera_alone():
    """"if I have made a frame ... way smaller than the viewport, scrolling
    forward should cause the frame to grow in the viewport." """
    cam = _cam()
    cam.frame_zoom = 0.3
    small = cameras.frame_rect(800, 600, *cam.half_angles(), zoom=cam.frame_zoom)
    cam.frame_zoom = cameras.zoom_frame(cam.frame_zoom, 4)
    bigger = cameras.frame_rect(800, 600, *cam.half_angles(), zoom=cam.frame_zoom)
    assert bigger[2] > small[2] and bigger[3] > small[3]
    # and scrolling back is exactly the inverse
    assert cameras.zoom_frame(cameras.zoom_frame(0.3, 4), -4) ==         pytest.approx(0.3)


def test_the_wheel_does_not_change_the_focal_length():
    """"Right now it is effectively changing the focal length as far as I can
    tell. It should not be doing that." """
    cam = _cam()
    before = (cam.focal_mm, cam.sensor_mm, cam.width, cam.height,
              float(cam.distance), tuple(cam.center))
    cam.frame_zoom = cameras.zoom_frame(cam.frame_zoom, 5)
    assert (cam.focal_mm, cam.sensor_mm, cam.width, cam.height,
            float(cam.distance), tuple(cam.center)) == before


def test_the_frame_zoom_rides_the_savefile():
    cam = cameras.CameraObject(3)
    cam.frame_zoom = 0.4
    assert cameras.CameraObject.from_dict(cam.to_dict()).frame_zoom ==         pytest.approx(0.4)


def test_the_frame_stays_centred_at_every_zoom():
    cam = _cam()
    for zoom in (0.1, 0.5, 1.0, 3.0):
        x, y, w, h = cameras.frame_rect(800, 600, *cam.half_angles(),
                                        zoom=zoom)
        assert x + w / 2.0 == pytest.approx(400.0)
        assert y + h / 2.0 == pytest.approx(300.0)


# ------------------------------------------------------------- the gizmo
def test_a_camera_draws_as_a_pyramid_with_a_drop_line():
    """Christian: "cones with a rectangular base as wireframes which have a
    dashed line attached to their tip that goes towards the xy plane." """
    cam = cameras.CameraObject(1)
    g = cameras.gizmo_geometry(cam, 2.0)
    assert len(g["base"]) == 4 and len(g["edges"]) == 4
    # the apex IS the camera, so grabbing it moves the camera
    assert np.allclose(g["apex"], cam.eye())
    # the base sits `size` in front of the apex, square to the view
    assert np.linalg.norm(np.mean(g["base"], axis=0) - g["apex"]) ==         pytest.approx(2.0)
    # and the drop line ends on the floor, straight down
    assert g["drop"][1][2] == pytest.approx(0.0)
    assert np.allclose(g["drop"][1][:2], g["apex"][:2])


def test_the_base_is_the_films_shape():
    """A 16:9 camera should say so while it sits in the scene."""
    cam = cameras.CameraObject(1)
    cam.width, cam.height = 1920, 1080
    g = cameras.gizmo_geometry(cam, 3.0)
    base = g["base"]
    wide = np.linalg.norm(base[1] - base[0])
    tall = np.linalg.norm(base[2] - base[1])
    assert wide / tall == pytest.approx(16.0 / 9.0, rel=1e-6)


def test_the_gizmo_scales_with_the_scene():
    assert cameras.gizmo_size(100.0) > cameras.gizmo_size(5.0)
    assert cameras.gizmo_size(1e9) <= cameras.GIZMO_MAX
    assert cameras.gizmo_size(1e-9) >= cameras.GIZMO_MIN


# ----------------------------------------------- the frame is a real framing
def test_the_field_of_view_lands_on_the_frame():
    """Otherwise the rectangle is a decoration: the scene was drawn at the
    viewport's own fixed 40 degrees over the whole window and the frame merely
    laid on top, so the focal length changed the label and nothing else."""
    # A frame filling the height needs exactly the camera's own FOV.
    assert cameras.viewport_fov_y(50.0, 600.0, 600.0) == pytest.approx(50.0)
    # Half the height: the widget has to show more, never less.
    wide = cameras.viewport_fov_y(50.0, 300.0, 600.0)
    assert wide > 50.0
    assert np.tan(np.radians(wide) / 2.0) == pytest.approx(
        2.0 * np.tan(np.radians(50.0) / 2.0))


def test_a_long_lens_frames_less_than_a_short_one():
    short = cameras.CameraObject(1)
    short.focal_mm = 18.0
    long_ = cameras.CameraObject(2)
    long_.focal_mm = 200.0
    assert cameras.viewport_fov_y(long_.fov_y, 500.0, 600.0) < \
        cameras.viewport_fov_y(short.fov_y, 500.0, 600.0)


# ------------------------------------------------------------------- roll
def test_roll_matches_fly_look_exactly():
    """Round 56 said roll is applied "exactly as `Camera.fly_look` does", and
    it has to be, or a rolled camera previews one way and renders the other."""
    cam = cameras.CameraObject(1)
    cam.roll = 0.35
    live = Camera()
    live.rotation = cam.rotation.copy()
    live.fly_look(0.0, 0.0, roll=0.35)
    assert np.allclose(quat_to_mat3(cam.rolled_rotation()),
                       quat_to_mat3(live.rotation), atol=1e-12)


def test_the_blender_export_rolls_the_same_way_as_the_viewport():
    """It did not: the twist matrix was transposed there, so the export rolled
    the OPPOSITE way. Invisible while the viewport ignored roll entirely."""
    cam = cameras.CameraObject(1)
    cam.roll = 0.35
    spec = bx.camera_object_setup(cam)
    world = np.array(spec["matrix"])[:3, :3]
    assert np.allclose(world, quat_to_mat3(cam.rolled_rotation()).T, atol=1e-8)


def test_capturing_a_rolled_view_does_not_roll_it_twice():
    """The view rotation already carries the roll, so `capture` must take it
    back off before storing the pose."""
    cam = cameras.CameraObject(1)
    cam.roll = 0.4
    live = Camera()
    cam.apply_to(live)                       # look through it
    before = quat_to_mat3(live.rotation).copy()
    cam.capture(live, roll=0.4)              # "this camera now looks from here"
    cam.apply_to(live)
    assert np.allclose(quat_to_mat3(live.rotation), before, atol=1e-9)


# ---------------------------------------------------- entering and leaving
def test_orbiting_leaves_the_camera_view_and_keeps_the_pose(win):
    """Blender's rule, and the answer to "is it even possible to exit?"."""
    win.on_place_camera()
    vp = win.viewport
    assert vp.looking_through is not None
    before = np.array(vp.camera.rotation, dtype=float)
    vp._orbit_input(40.0, 0.0)
    assert vp.looking_through is None
    # It ORBITED — leaving must not undo the gesture that caused it.
    assert not np.allclose(vp.camera.rotation, before)


def test_panning_and_zooming_stay_inside_the_camera(win):
    """"unless it is done with shift+drag or ctrl+drag" — which are pan and
    zoom on both input presets, so gating on the resolved ACTION gets the
    exception for free and gets it identically on a trackpad and a mouse."""
    win.on_place_camera()
    vp = win.viewport
    vp.camera.pan(20.0, 10.0, 800, 600)
    vp.camera.zoom(1.0)
    assert vp.looking_through is not None


def test_tumbling_a_molecule_does_not_leave_the_camera(win):
    """That gesture moves the MODEL. The camera has not moved, so there is
    nothing to exit."""
    win.open_path(FREQ)
    obj = win._active_obj()
    win.on_place_camera()
    vp = win.viewport
    vp.set_selection([(obj.id, 0)])
    vp._gesture_mode = "tumble"
    vp._last_orbit_t = 1e18            # inside the gesture: no re-decision
    vp._orbit_input(30.0, 0.0)
    assert vp.looking_through is not None


def test_numpad_0_still_toggles_back_to_where_you_were(win):
    vp = win.viewport
    win.on_place_camera()
    win.leave_camera()
    before = np.array(vp.camera.center, dtype=float)
    dist = float(vp.camera.distance)
    win.on_activate_camera()               # in
    win.on_activate_camera()               # and out again
    assert vp.looking_through is None
    assert np.allclose(vp.camera.center, before)
    assert vp.camera.distance == pytest.approx(dist)


def test_an_axis_view_leaves_the_camera(win):
    """A compass click is a view rotation, so it must not silently re-aim the
    shot you are composing."""
    win.on_place_camera()
    win.viewport.align_view_axis(0, 1)
    assert win.viewport.looking_through is None


# ---------------------------------------------- editing must not move it
def test_resizing_the_frame_does_not_reset_a_dolly(win):
    """Christian: "clicking on one of the scaling knobs of the camera view
    also resets a previous dolly for whatever reason." Every edit ran
    `apply_to`, which assigns centre, distance and rotation."""
    win.on_place_camera()
    vp = win.viewport
    cam = win.scene.active_camera()
    vp.camera.zoom(3.0)                    # dolly in while inside the shot
    dollied = float(vp.camera.distance)
    assert dollied != pytest.approx(cam.distance)

    cam.width, cam.height = 640, 480       # a knob drag, then the release
    win.camera_changed()
    assert vp.camera.distance == pytest.approx(dollied)

    cam.focal_mm = 85.0                    # and the properties page
    win.camera_changed()
    assert vp.camera.distance == pytest.approx(dollied)


def test_the_camera_object_itself_never_moves_while_looked_through(win):
    """"unless the camera is selected and grabbed, it should not move"."""
    win.on_place_camera()
    vp = win.viewport
    cam = win.scene.active_camera()
    pose = (np.array(cam.center), float(cam.distance),
            np.array(cam.rotation))
    vp.camera.zoom(2.0)
    vp.camera.pan(50.0, 30.0, 800, 600)
    win.camera_changed()
    assert np.allclose(cam.center, pose[0])
    assert cam.distance == pytest.approx(pose[1])
    assert np.allclose(cam.rotation, pose[2])


def test_leaving_restores_the_ordinary_field_of_view(win):
    win.on_place_camera()
    cam = win.scene.active_camera()
    cam.focal_mm = 200.0
    win.camera_changed()
    assert win.viewport.camera.FOV_Y != pytest.approx(Camera.FOV_Y)
    win.leave_camera()
    assert win.viewport.camera.FOV_Y == pytest.approx(Camera.FOV_Y)


# --------------------------------------------------------- the animation
def test_the_FIRST_animate_click_leaves_the_molecule_where_it_is(win):
    """Round 55 re-read the rest geometry only while a mode was ALREADY
    animating, so the first bake still used the capture taken when the
    frequencies were read — Christian: "curiously, only the first animate
    click resets the location of the molecule"."""
    win.open_path(FREQ)
    obj = win._active_obj()
    modes = [m for m in win._modes.get(obj.id, []) if not m.is_trivial]
    shift = np.array([7.0, -3.0, 2.0])
    for k in range(obj.structure.n_frames):
        obj.structure.frames[k] = np.asarray(obj.structure.frames[k]) + shift
    moved = np.asarray(obj.structure.frames[0]).mean(axis=0)

    win.on_animate_mode(modes[0].index)            # the FIRST one
    assert np.allclose(np.asarray(win.scene.get(obj.id).structure.frames[0]
                                  ).mean(axis=0), moved, atol=1e-9)


def test_a_vibration_never_loses_a_bond(win):
    """"when an animation shortens a bond far enough it is no longer drawn?"
    It was: the player re-perceives connectivity per frame, and a squeezed
    bond fails `IMPOSSIBLE_FACTOR`. Measured on this very file: at the DEFAULT
    0.2 A amplitude the 1346 cm-1 mode takes P=O to 1.127 A against a floor of
    1.13, and at 0.4 A the O-H stretches reach 0.56 A."""
    win.open_path(FREQ)
    obj = win._active_obj()
    modes = [m for m in win._modes.get(obj.id, []) if not m.is_trivial]
    win.on_animate_mode(modes[0].index, amplitude=1.0)
    expected = list(win.scene.get(obj.id).structure.bonds)
    assert expected, "the molecule has bonds at rest"

    for _ in range(60):                    # right through several periods
        win.timeline.advance_frames(1)
        win._apply_timeline()
        assert list(win.scene.get(obj.id).structure.bonds) == expected


def test_the_bare_perception_would_have_lost_them(win):
    """Pinning the cause, not just the cure: the chemistry filters are right,
    they were simply being asked about a phase of a vibration rather than
    about a structure."""
    win.open_path(FREQ)
    obj = win._active_obj()
    modes = [m for m in win._modes.get(obj.id, []) if not m.is_trivial]
    s = obj.structure
    rest = np.asarray(s.frames[0])
    at_rest = len(bonding.perceive_bonds(s.symbols, rest))
    worst = min(len(bonding.perceive_bonds(s.symbols, f))
                for m in modes
                for f in vib.mode_frames(rest, m, amplitude=1.0, n_frames=20))
    assert worst < at_rest


def test_the_selection_outline_follows_the_interpolated_atoms(win):
    """"the orange selection highlight ... is out of sync with the position of
    the meshes." The spheres are drawn from `evaluated()`, which interpolates
    between frames; the hull read the nearest STORED frame."""
    win.open_path(FREQ)
    obj = win._active_obj()
    modes = [m for m in win._modes.get(obj.id, []) if not m.is_trivial]
    win.on_animate_mode(modes[0].index, amplitude=0.8)
    vp = win.viewport
    vp.set_selection([(obj.id, 0)])

    obj = win.scene.get(obj.id)
    obj.play_position = 2.5                # half way between two frames
    assert not np.allclose(obj.display_coords()[0], obj.structure.coords[0])

    spheres, _cyl = vp._selection_hull()
    assert np.allclose(spheres[0][:3, 3], obj.display_coords()[0], atol=1e-9)


def test_picking_follows_the_interpolated_atoms_too(win):
    """A click during playback must hit where the sphere is DRAWN."""
    win.open_path(FREQ)
    obj = win._active_obj()
    modes = [m for m in win._modes.get(obj.id, []) if not m.is_trivial]
    win.on_animate_mode(modes[0].index, amplitude=0.8)
    obj = win.scene.get(obj.id)
    obj.play_position = 2.5
    vp = win.viewport
    vp._pick_dirty = True
    vp._ensure_pick_data()
    assert np.allclose(vp._flat_coords[0], obj.display_coords()[0], atol=1e-9)


def test_a_mode_bake_pins_the_connectivity_flag(win):
    """It rides `Structure.metadata`, so it survives undo and savepoints with
    no `Scene.snapshot` four-place checklist (the round-43 pattern)."""
    win.open_path(FREQ)
    obj = win._active_obj()
    assert not bonding.bonds_are_fixed(obj.structure)
    modes = [m for m in win._modes.get(obj.id, []) if not m.is_trivial]
    win.on_animate_mode(modes[0].index)
    assert bonding.bonds_are_fixed(win.scene.get(obj.id).structure)


def test_an_ordinary_trajectory_still_re_perceives():
    """An MD trajectory really does make and break bonds — the flag must be
    opt-in, not a blanket change to how the player works."""
    from molom.core.structure import Structure
    s = Structure(["C", "C"], np.array([[0.0, 0.0, 0.0], [1.5, 0.0, 0.0]]))
    assert not bonding.bonds_are_fixed(s)


# ------------------------------------------------------ F12 through a camera
def test_a_render_through_a_camera_is_the_frame_at_its_own_resolution(win):
    """The film back is a real framing now, so what F12 writes has to be what
    the frame showed — done as a CROP so there is still one projection and one
    overlay implementation."""
    win.on_place_camera()
    vp = win.viewport
    cam = win.scene.active_camera()
    cam.width, cam.height, cam.multiplier = 640, 360, 2.0
    cam.frame_zoom = 0.5
    win.camera_changed()

    crop = vp._render_crop(vp.width(), vp.height())
    assert crop["target"] == cam.render_size()
    # The buffer keeps the WIDGET's aspect, which is what lets the projection
    # stay identical to the screen's and every overlay land where it does.
    bw, bh = crop["buffer"]
    assert bw / bh == pytest.approx(vp.width() / vp.height(), rel=0.02)
    # and the kept box has the CAMERA's aspect
    _bx, _by, box_w, box_h = crop["box"]
    assert box_w / box_h == pytest.approx(cam.aspect, rel=0.02)


def test_a_small_frame_cannot_demand_a_giant_render_buffer(win):
    """The frame's size on screen is a VIEWING choice (the wheel), so it must
    not decide how much memory a render takes — `resolution / frame fraction`
    grows without bound as the frame is pulled in."""
    win.on_place_camera()
    vp = win.viewport
    cam = win.scene.active_camera()
    cam.width, cam.height = 1920, 1080
    cam.frame_zoom = cameras.MIN_FRAME_ZOOM
    win.camera_changed()
    bw, bh = vp._render_crop(vp.width(), vp.height())["buffer"]
    assert bw <= vp.width() * vp._MAX_RENDER_BUFFER
    assert bh <= vp.height() * vp._MAX_RENDER_BUFFER


def test_the_free_view_render_is_untouched(win):
    assert win.viewport._render_crop(800, 600) is None


# ------------------------------------------------ the camera never moves
def test_the_wheel_inside_a_camera_resizes_the_frame_only(win):
    """Christian: "mousewheel should also not move the camera, only scroll in
    the view.\" """
    win.on_place_camera()
    vp = win.viewport
    cam = win.scene.active_camera()
    pose = (np.array(cam.center), float(cam.distance), float(cam.focal_mm))
    view = (np.array(vp.camera.center), float(vp.camera.distance))
    zoom = cam.frame_zoom

    vp.zoom_camera_frame(3)
    assert cam.frame_zoom > zoom
    assert np.allclose(cam.center, pose[0])
    assert cam.distance == pytest.approx(pose[1])
    assert cam.focal_mm == pytest.approx(pose[2])
    assert np.allclose(vp.camera.center, view[0])
    assert vp.camera.distance == pytest.approx(view[1])


def test_a_frame_drag_never_moves_the_camera(win):
    from PySide6.QtCore import QPointF
    win.on_place_camera()
    vp = win.viewport
    cam = win.scene.active_camera()
    pose = (np.array(cam.center), float(cam.distance),
            np.array(cam.rotation), float(vp.camera.distance))
    rect = vp.camera_rect()
    vp._camera_handle_press(QPointF(rect[0] + rect[2], rect[1] + rect[3]))
    assert vp._frame_drag is not None
    vp._camera_handle_move(QPointF(rect[0] + rect[2] + 40,
                                   rect[1] + rect[3] + 30))
    assert np.allclose(cam.center, pose[0])
    assert cam.distance == pytest.approx(pose[1])
    assert np.allclose(cam.rotation, pose[2])
    assert vp.camera.distance == pytest.approx(pose[3])


def test_escape_leaves_the_camera_view(win):
    win.on_place_camera()
    vp = win.viewport
    assert vp.looking_through is not None
    assert vp.cancel_modes() is True
    assert vp.looking_through is None


def test_escape_cancels_a_modal_before_the_camera_view(win):
    """Esc backs out of the innermost thing you are in — cancelling a grab
    must not also throw you out of the shot."""
    win.open_path(FREQ)
    obj = win._active_obj()
    win.on_place_camera()
    vp = win.viewport
    vp.set_selection([(obj.id, 0)])
    vp.start_grab()
    assert vp.cancel_modes() is True
    assert vp.looking_through is not None       # still in the camera
    assert vp.cancel_modes() is True
    assert vp.looking_through is None


# ---------------------------------------------------- the viewport gizmo
def test_cameras_are_drawn_in_the_viewport_but_not_the_one_you_are_in(win):
    win.on_place_camera()
    vp = win.viewport
    assert vp.camera_gizmos() == []             # standing at its apex
    win.leave_camera()
    assert [c.id for c, _g in vp.camera_gizmos()] == \
        [c.id for c in win.scene.cameras]


def test_a_camera_can_be_picked_and_grabbed(win):
    from PySide6.QtCore import QPointF
    win.on_place_camera()
    win.leave_camera()
    vp = win.viewport
    # A camera placed here sits exactly AT your eye, so back off first or its
    # apex is on the near plane and projects to nothing — which is also true
    # in the app, and is why the gizmo appears as soon as you move.
    vp.camera.distance *= 4.0
    cam = win.scene.cameras[0]
    xy, front = vp._project(cam.eye()[None, :])
    assert bool(front[0])
    hit = vp._camera_gizmo_at(QPointF(float(xy[0][0]), float(xy[0][1])))
    assert hit is not None and hit.id == cam.id

    vp.select_camera(cam.id)
    before = np.array(cam.center)
    assert vp.start_camera_grab() is True
    vp._camera_drag_move(QPointF(100.0, 100.0))
    vp._camera_drag_move(QPointF(180.0, 140.0))
    assert not np.allclose(cam.center, before)
    vp.finish_camera_drag(commit=True)
    assert vp._camera_drag is None


def test_cancelling_a_camera_grab_puts_it_back(win):
    from PySide6.QtCore import QPointF
    win.on_place_camera()
    win.leave_camera()
    vp = win.viewport
    cam = win.scene.cameras[0]
    vp.select_camera(cam.id)
    before = (np.array(cam.center), np.array(cam.rotation))
    vp.start_camera_grab(rotate=True)
    vp._camera_drag_move(QPointF(100.0, 100.0))
    vp._camera_drag_move(QPointF(200.0, 160.0))
    assert not np.allclose(cam.rotation, before[1])
    vp.finish_camera_drag(commit=False)
    assert np.allclose(cam.center, before[0])
    assert np.allclose(cam.rotation, before[1])


def test_G_goes_to_the_camera_only_when_one_is_picked(win):
    win.open_path(FREQ)
    obj = win._active_obj()
    win.on_place_camera()
    win.leave_camera()
    vp = win.viewport
    vp.set_selection([(obj.id, 0)])
    assert vp.start_camera_grab() is False      # nothing picked: molecules
    vp.select_camera(win.scene.cameras[0].id)
    assert vp.start_camera_grab() is True
    vp.finish_camera_drag(commit=False)


def test_numpad_zero_is_bound_with_num_lock_OFF_too():
    """With NUM LOCK OFF the numpad's 0 sends Key_Insert, not Key_0 — so
    `Num+0` alone binds a key half the keyboards never send."""
    from molom.ui.app import MainWindow
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    win = MainWindow()
    op = win.ops.get("camera_activate")
    keys = ((op.key,) if op.key else ()) + op.extra_keys
    assert "Num+0" in keys and "Num+Ins" in keys
    assert not win.ops.duplicate_keys()


# ------------------------------------------- shift+drag re-frames the shot
def test_shift_drag_moves_the_camera_itself(win):
    """Christian: "all I need now is to bring back shift+drag so that I can do
    final adjustments to the camera view." It moves the camera OBJECT, not the
    free view — round 57 panned the interactive camera, so the framing you
    nudged was gone the next time you pressed Numpad 0."""
    win.on_place_camera()
    vp = win.viewport
    cam = win.scene.active_camera()
    before = np.array(cam.center)
    aim = np.array(cam.rotation)
    dist = float(cam.distance)

    assert vp.truck_camera(30.0, -12.0) is True
    assert not np.allclose(cam.center, before)
    # a truck slides the camera; it does not turn it or dolly it
    assert np.allclose(cam.rotation, aim)
    assert cam.distance == pytest.approx(dist)
    # sideways, in the camera's own screen plane — never along the view axis
    moved = np.asarray(cam.center) - before
    forward = quat_to_mat3(cam.rolled_rotation()).T @ np.array([0.0, 0.0, -1.0])
    assert float(np.dot(moved, forward)) == pytest.approx(0.0, abs=1e-9)
    # and the view follows, or you would be adjusting something you cannot see
    assert np.allclose(vp.camera.center, cam.center)


def test_a_re_framing_survives_leaving_and_coming_back(win):
    win.on_place_camera()
    vp = win.viewport
    cam = win.scene.active_camera()
    vp.truck_camera(40.0, 20.0)
    framed = np.array(cam.center)
    win.leave_camera()
    win.on_activate_camera(cam.id)
    assert np.allclose(cam.center, framed)
    assert np.allclose(vp.camera.center, framed)


def test_a_whole_shift_drag_is_one_undo_step(win):
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtCore import QEvent, QPointF, Qt
    win.on_place_camera()
    vp = win.viewport
    cam = win.scene.active_camera()
    depth = len(win.undo._stack) if hasattr(win.undo, "_stack") else None
    for _ in range(8):
        vp.truck_camera(5.0, 0.0)
    assert vp._truck_gesture == cam.id
    vp.mouseReleaseEvent(QMouseEvent(
        QEvent.MouseButtonRelease, QPointF(1.0, 1.0), Qt.MiddleButton,
        Qt.NoButton, Qt.ShiftModifier))
    assert vp._truck_gesture is None
    if depth is not None:
        assert len(win.undo._stack) == depth + 1


def test_the_nudge_is_one_to_one_on_screen_at_any_zoom(win):
    """A drag slides the shot by as many pixels as the hand moved, whatever
    the frame zoom — which is what makes it self-regulating for "final
    adjustments": scroll in and the same drag becomes a finer nudge, because
    more pixels then cover the same part of the shot."""
    win.on_place_camera()
    vp = win.viewport
    cam = win.scene.active_camera()

    def screen_shift(drag_px):
        start = np.array(cam.center)
        probe = np.array(cam.center)          # a point fixed in the world
        before, _f = vp._project(probe[None, :])
        vp.truck_camera(drag_px, 0.0)
        after, _f = vp._project(probe[None, :])
        cam.center = start.copy()
        cam.apply_to(vp.camera)
        vp.sync_camera_lens()
        return float(after[0][0] - before[0][0])

    wide = screen_shift(50.0)
    cam.frame_zoom = cameras.zoom_frame(cam.frame_zoom, -6)
    vp.sync_camera_lens()
    tight = screen_shift(50.0)
    assert abs(wide) == pytest.approx(50.0, abs=0.5)
    assert abs(tight) == pytest.approx(50.0, abs=0.5)
