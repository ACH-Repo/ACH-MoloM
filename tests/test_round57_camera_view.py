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


# ------------------------------------------------------- the frame is a size
def test_the_frame_can_be_an_arbitrary_size_and_stays_centred():
    """The film back was always the largest rectangle of its aspect that fits,
    so only its SHAPE could ever show — which is why a corner drag "did
    nothing"."""
    full = cameras.frame_rect(800, 600, 1.5)
    half = cameras.frame_rect(800, 600, 1.5, zoom=0.5)
    assert half[2] == pytest.approx(full[2] / 2.0)
    assert half[3] == pytest.approx(full[3] / 2.0)
    for rect in (full, half):
        x, y, w, h = rect
        assert x + w / 2.0 == pytest.approx(400.0)     # centred, both ways
        assert y + h / 2.0 == pytest.approx(300.0)


def test_a_corner_drag_along_the_diagonal_used_to_change_nothing_visible():
    """The exact reason for the complaint: dragging a corner along the
    rectangle's own diagonal gives scale_x == scale_y, so the ASPECT — the
    only thing the drawn rectangle could express — is untouched."""
    rect = (0.0, 0.0, 400.0, 200.0)
    w, h = cameras.resize_pixels("se", 400, 200, 40.0, 20.0, rect)
    assert w / h == pytest.approx(400.0 / 200.0)       # same shape as before

    # With the frame zoom carried, the same drag is now visible.
    _w, _h, zoom = cameras.resize_frame("se", 400, 200, 0.5, 40.0, 20.0, rect)
    assert zoom > 0.5


def test_a_corner_carries_the_frame_zoom_and_an_edge_does_not():
    rect = (0.0, 0.0, 400.0, 200.0)
    _w, _h, zoom = cameras.resize_frame("se", 400, 200, 0.5, -60.0, -30.0,
                                        rect)
    assert zoom < 0.5                                  # dragged in: smaller
    _w, _h, zoom = cameras.resize_frame("e", 400, 200, 0.5, 60.0, 0.0, rect)
    assert zoom == pytest.approx(0.5)                  # an edge is aspect only


def test_the_frame_zoom_is_clamped_at_the_fit():
    """A frame larger than the window puts its own drag handles off screen,
    which is a state with no way out of it."""
    rect = (0.0, 0.0, 400.0, 200.0)
    _w, _h, zoom = cameras.resize_frame("se", 400, 200, 1.0, 5000.0, 5000.0,
                                        rect)
    assert zoom == pytest.approx(cameras.MAX_FRAME_ZOOM)
    _w, _h, zoom = cameras.resize_frame("se", 400, 200, 1.0, -5000.0, -5000.0,
                                        rect)
    assert zoom == pytest.approx(cameras.MIN_FRAME_ZOOM)


def test_the_frame_zoom_rides_the_savefile():
    cam = cameras.CameraObject(3)
    cam.frame_zoom = 0.4
    assert cameras.CameraObject.from_dict(cam.to_dict()).frame_zoom == \
        pytest.approx(0.4)


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
        win.timeline.advance_images(1)
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
    assert crop["box"][2:] == cam.render_size()
    # The buffer keeps the WIDGET's aspect, which is what lets the projection
    # stay identical to the screen's and every overlay land where it does.
    bw, bh = crop["buffer"]
    assert bw / bh == pytest.approx(vp.width() / vp.height(), rel=0.02)
    # and it is never upscaled
    assert bw >= cam.render_size()[0] and bh >= cam.render_size()[1]


def test_the_free_view_render_is_untouched(win):
    assert win.viewport._render_crop(800, 600) is None
