"""Round 72: first person made to work at all, and the chase judder found.

Christian, 2026-08-13, after round 71 claimed to have fixed both:

* "Check if the cockpit is put at the location of the selected atom regardless
  of object origin."
* "Also make sure that the distance of the camera from the center of the
  selected atom is always large enough so there is no clipping with the sphere.
  Not useful if all you see is the inside of an atom while steering."
* "The jitter of the camera and spring arm nonsense are still happening."

All three reproduced by measurement, and none of them was where round 71
looked. First person had round 69's and round 70's bugs still in it, because
both fixes were written into the chase branch only: the camera was re-anchored
inside `_fly_object`, i.e. only when the ship TRANSLATED, and the molecule was
turned about `obj.origin`, which round 71 had itself measured at 8.10 A from
the centroid. Three seconds of pure steering took the eye 0.35 A -> 9.41 A off
the atom it was supposed to be sitting on.

The chase judder is not the spring and never was: the hard clamp fires on 0 of
240 ticks, and the reason is that a cap of 3 molecule RADII is about 58 degrees
off the view axis against a 20 degree half-frame. The ship left the picture
long before anything engaged. Measured on a small ship in a large scene: it
wandered to 30.5 degrees below the axis with per-tick steps of 4.6 degrees.
"""

import numpy as np
import pytest

from molom.core import flight
from molom.core.camera import quat_to_mat3


@pytest.fixture
def win():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.app import MainWindow
    QApplication.instance() or QApplication([])
    win = MainWindow()
    win.load_default_scene()
    return win


def _key_w():
    from PySide6.QtCore import Qt
    return Qt.Key_W


def _drift_origin(obj, offset=(8.1, 0.0, 0.0)):
    """The meta-ship's condition: an origin nowhere near the centroid, which is
    what free-drawing a molecule far from its object origin leaves behind."""
    obj.origin = np.asarray(obj.origin, dtype=float) + np.asarray(offset,
                                                                 dtype=float)


def _ship_angle(vp, point):
    """Where `point` sits in the picture, in degrees off the view axis."""
    r = quat_to_mat3(vp.camera.rotation)
    eye = vp.camera.center + r.T @ np.array([0.0, 0.0, vp.camera.distance])
    v = np.asarray(point, dtype=float) - eye
    fwd = r.T @ np.array([0.0, 0.0, -1.0])
    depth = float(v @ fwd)
    if depth <= 1e-9:
        return 180.0
    perp = v - depth * fwd
    return float(np.degrees(np.arctan2(float(np.linalg.norm(perp)), depth)))


# ------------------------------------------------ the cockpit clears the atom
def test_the_eye_sits_OUTSIDE_the_cockpit_atoms_own_sphere(win):
    """It sat at a flat 0.35 A, and an ordinary carbon is drawn at 0.409 - so
    the camera was inside the atom and the picture was its inner surface."""
    obj = win._active_obj()
    vp = win.viewport
    vp.set_selection([(obj.id, 0)])
    win.on_shuttle()
    drawn = vp._cockpit_radius(obj)
    assert drawn > 0.0
    eye = vp._shuttle_eye()
    atom = np.asarray(obj.structure.coords[0], dtype=float)
    assert float(np.linalg.norm(eye - atom)) > drawn


def test_the_clearance_follows_the_atom_that_was_picked(win):
    """A hydrogen is drawn much smaller than a carbon, so one fixed distance
    cannot be right for both."""
    small = flight.cockpit_distance(0.2)
    big = flight.cockpit_distance(2.0)
    assert big > small
    assert big > 2.0                     # outside a 2.0 A sphere
    assert small >= flight.COCKPIT_MIN_DISTANCE


def test_the_clearance_follows_the_sphere_size_slider(win):
    """The slider scales what is DRAWN, so a clearance measured against the
    unscaled radius would be no clearance at all."""
    obj = win._active_obj()
    vp = win.viewport
    vp.set_selection([(obj.id, 0)])
    vp.atom_scale = 2.0
    win.on_shuttle()
    drawn = vp._cockpit_radius(obj)
    assert float(np.linalg.norm(vp._shuttle_eye()
                                - obj.structure.coords[0])) > drawn


def test_the_cull_reaches_past_the_atom_the_eye_is_standing_by(win):
    obj = win._active_obj()
    vp = win.viewport
    vp.set_selection([(obj.id, 0)])
    win.on_shuttle()
    assert vp._shuttle["clip"] > vp.camera.distance + vp._cockpit_radius(obj)


def test_a_culled_atom_takes_its_BONDS_with_it(win):
    """Hiding the sphere and keeping its sticks leaves the eye inside the
    CYLINDERS, which looks exactly like being inside the atom."""
    obj = win._active_obj()
    vp = win.viewport
    vp.set_selection([(obj.id, 0)])
    win.on_shuttle()
    block = vp._build_object_block(obj)
    eye = vp._shuttle_eye()
    clip = float(vp._shuttle["clip"])
    for start, end in zip(block["cyl_starts"], block["cyl_ends"]):
        near = min(float(np.linalg.norm(np.asarray(start) - eye)),
                   float(np.linalg.norm(np.asarray(end) - eye)))
        assert near >= clip - 1e-6, "a stick on a culled atom was still drawn"


def test_the_SELECTION_OUTLINE_of_the_cockpit_atom_is_culled(win):
    """The loudest of the five, and the one only a real window showed: the
    outline is an ENLARGED sphere with its front faces culled, so a camera
    inside one sees its entire inner surface. In the cockpit the selected atom
    IS the atom the camera sits on, always - that is how the cockpit is named -
    so first person rendered as a flat orange screen. Measured on a real
    window: 54% of the frame was outline before, 3% after.
    """
    obj = win._active_obj()
    vp = win.viewport
    vp.set_selection([(obj.id, 0)])
    win.on_shuttle()
    spheres, cylinders = vp._selection_hull()
    eye = vp._shuttle_eye()
    clip = float(vp._shuttle["clip"])
    for m in spheres:
        assert float(np.linalg.norm(np.asarray(m)[:3, 3] - eye)) >= clip
    for a, b, _r in cylinders:
        assert min(float(np.linalg.norm(np.asarray(a) - eye)),
                   float(np.linalg.norm(np.asarray(b) - eye))) >= clip


def test_the_outline_comes_back_in_third_person_and_after_landing(win):
    """Nothing is culled in the chase view - the ship is the subject - and the
    cull must not outlive the flight."""
    obj = win._active_obj()
    vp = win.viewport
    vp.set_selection([(obj.id, 0)])
    win.on_shuttle(third_person=True)
    assert len(vp._selection_hull()[0]) == 1
    vp.stop_shuttle()
    assert len(vp._selection_hull()[0]) == 1


def test_a_meta_atoms_HALO_is_culled_at_the_cockpit_too(win):
    """The halo is a stack of shells LARGER than the atom, blended additively,
    so parking the camera on one washes the frame out. The ship in the report
    that opened this round is a meta complex."""
    from molom.core import meta as meta_mod
    obj = win._active_obj()
    vp = win.viewport
    meta_mod.set_meta(obj.structure, 0,
                      meta_mod.MetaAtom(geometry="octahedral", element="Fe"))
    assert len(vp._meta_glow_instances()[0]) > 0     # drawn when not flying
    vp.set_selection([(obj.id, 0)])
    win.on_shuttle()
    mats, _rgba = vp._meta_glow_instances()
    eye = vp._shuttle_eye()
    for m in mats:
        assert float(np.linalg.norm(np.asarray(m)[:3, 3] - eye)) \
            >= float(vp._shuttle["clip"])


# ------------------------------- first person anchors on the atom, and STAYS
def test_a_pure_turn_does_not_move_the_cockpit_atom_in_FIRST_person(win):
    """Round 70 fixed this for the chase camera and left first person turning
    about `obj.origin` - a point 8 A out in empty space on a real file."""
    obj = win._active_obj()
    vp = win.viewport
    _drift_origin(obj)
    vp.set_selection([(obj.id, 4)])
    win.on_shuttle()
    before = np.asarray(obj.structure.coords[4], dtype=float).copy()
    vp._fly["aim"].move(150.0, 40.0, 600.0)
    for _ in range(180):
        vp._fly_tick(dt=1.0 / 60.0)
    after = np.asarray(obj.structure.coords[4], dtype=float)
    assert float(np.linalg.norm(after - before)) < 1e-9


def test_the_cockpit_view_survives_three_seconds_of_pure_STEERING(win):
    """The measured regression: 0.35 A off the picked atom at take-off, 9.41 A
    after three seconds of steering with no thrust at all. The follow only ran
    when the ship TRANSLATED."""
    obj = win._active_obj()
    vp = win.viewport
    _drift_origin(obj)
    vp.set_selection([(obj.id, 4)])
    win.on_shuttle()
    vp._fly["aim"].move(150.0, 40.0, 600.0)
    for _ in range(180):
        vp._fly_tick(dt=1.0 / 60.0)
    gap = float(np.linalg.norm(vp._shuttle_eye() - obj.structure.coords[4]))
    assert gap == pytest.approx(vp.camera.distance, abs=1e-6)


def test_the_chase_view_survives_pure_steering_too(win):
    obj = win._active_obj()
    vp = win.viewport
    _drift_origin(obj)
    vp.set_selection([(obj.id, 4)])
    win.on_shuttle(third_person=True)
    vp._fly["aim"].move(150.0, 40.0, 600.0)
    for _ in range(180):
        vp._fly_tick(dt=1.0 / 60.0)
    assert _ship_angle(vp, obj.structure.coords[4]) < 20.0


# --------------------------------------------- the limit is the FRAME, not r
def test_the_slip_limit_is_an_ANGLE_off_the_view_axis():
    """The gap is only ever seen as an angle. A cap of 3 radii at a viewing
    distance of 1.9 radii is 58 degrees, against a 40 degree field of view -
    which is why the backstop measured as "never fires" while the ship was
    visibly leaving the picture."""
    from molom.core.camera import Camera
    for distance in (2.0, 7.0, 50.0):
        limit = flight.slip_limit(distance)
        angle = np.degrees(np.arctan2(limit, distance))
        assert angle == pytest.approx(flight.CHASE_FRAME_ANGLE)
        assert angle < Camera.FOV_Y / 2.0, "the cap allows the ship off screen"
    assert flight.slip_limit(20.0) > flight.slip_limit(5.0)


def test_the_old_radius_based_cap_would_have_allowed_this(win):
    """Kept as the arithmetic that explains four rounds of reports."""
    radius = 3.7
    old = 3.0 * radius                       # CHASE_MAX_SLIP * radius
    distance = flight.chase_distance(radius)
    assert np.degrees(np.arctan2(old, distance)) > 45.0


def test_the_follow_rate_rises_with_the_SHIPS_SPEED():
    """An exponential follow settles at gap = speed / rate, so a fixed rate
    means the gap grows with the speed until no easing can close it. That is
    the "vastly more inertia than the camera" report; the spring alone only
    ever addressed a TRANSIENT gap."""
    limit = flight.slip_limit(7.0)
    assert flight.follow_rate(0.0, limit) == pytest.approx(flight.CHASE_LAG)
    assert flight.follow_rate(0.5, limit) == pytest.approx(flight.CHASE_LAG)
    fast = flight.follow_rate(60.0, limit)
    assert fast > flight.CHASE_LAG * 5.0
    # ...and it is exactly the rate that holds the steady gap in the soft zone.
    assert 60.0 / fast <= flight.CHASE_SOFT_ZONE * limit + 1e-9


def test_the_gap_settles_inside_the_frame_at_any_speed():
    """Pure model arithmetic, no window: the steady-state gap must stay inside
    the angular limit whether the ship is crawling or boosting."""
    for distance in (3.0, 7.0, 40.0):
        limit = flight.slip_limit(distance)
        for speed in (0.1, 1.0, 5.0, 25.0, 120.0):
            gap = speed / flight.follow_rate(speed, limit)
            assert gap <= limit + 1e-9


# ----------------------------------------------- speed is scaled by the SHIP
def test_shuttle_speed_scales_with_the_SHIP_not_the_scene(win):
    """Flying a molecule is a PLACEMENT gesture judged against the molecule.
    Scaling it by the whole scene gave a 3.7 A ship in a 60 A scene a 105 A/s
    top speed - 1.75 A of travel per frame, which no chase camera can hold
    because the gap opens faster than any easing closes it."""
    from molom.core.structure import Structure
    obj = win._active_obj()
    vp = win.viewport
    vp.set_selection([(obj.id, 0)])
    win.on_shuttle(third_person=True)
    alone = float(vp._fly["model"].scale)
    vp.stop_shuttle()

    pts = np.random.default_rng(1).normal(scale=18.0, size=(400, 3))
    win.scene.add(Structure(["C"] * 400, [pts]), name="framework")
    vp.set_selection([(obj.id, 0)])
    win.on_shuttle(third_person=True)
    assert float(vp._fly["model"].scale) == pytest.approx(alone)


def test_camera_flight_still_scales_with_the_whole_scene(win):
    """The other half of the same argument: crossing a scene IS a navigation
    gesture, so nothing about right-mouse flight changes."""
    from molom.core.structure import Structure
    vp = win.viewport
    small = vp._scene_scale()
    pts = np.random.default_rng(2).normal(scale=18.0, size=(400, 3))
    win.scene.add(Structure(["C"] * 400, [pts]), name="framework")
    assert vp._scene_scale() > small * 2.0


# ------------------------------------------------------------- the judder
def test_the_ship_stays_in_frame_through_a_burn_with_a_JITTERY_frame_time(win):
    """The judder is a frame-time artefact only in so far as the gap is large:
    a doubled frame moves the ship twice as far, and how much of that reaches
    the screen is proportional to the lag. Bounding the lag bounds the judder.
    """
    from molom.core.structure import Structure
    obj = win._active_obj()
    vp = win.viewport
    # The condition that actually broke: a small ship in a LARGE scene, which
    # is what `docking.molom` is. Measured on the old code, the ship wandered
    # 30.5 degrees below the view axis (the half-frame is 20) in steps of up to
    # 4.6 degrees a tick.
    pts = np.random.default_rng(3).normal(scale=18.0, size=(400, 3))
    win.scene.add(Structure(["C"] * 400, [pts]), name="framework")
    vp.set_selection([(obj.id, 0)])
    win.on_shuttle(third_person=True)
    vp._fly["keys"].add(_key_w())
    vp._fly["aim"].move(150.0, 0.0, 600.0)
    rng = np.random.default_rng(0)
    angles = []
    for _ in range(300):
        dt = (1.0 / 60.0) * (2.0 if rng.random() < 0.12 else 1.0)
        vp._fly_tick(dt=dt)
        angles.append(_ship_angle(vp, obj.structure.coords[0]))
    angles = np.array(angles)
    assert angles.max() < 20.0, "the ship left the frame"
    step = np.abs(np.diff(angles))
    assert step.max() < 1.0, "a visible jump in the ship's screen position"


def test_the_hard_clamp_never_fires_in_ordinary_flight(win):
    """It is a backstop for a stalled frame. Hitting it every tick is a WALL,
    and ease-ease-snap is the judder itself."""
    obj = win._active_obj()
    vp = win.viewport
    vp.set_selection([(obj.id, 0)])
    win.on_shuttle(third_person=True)
    vp._fly["keys"].add(_key_w())
    fired = 0
    for _ in range(300):
        vp._fly_tick(dt=1.0 / 60.0)
        target = flight.chase_pivot(vp._cockpit_pos(obj),
                                    radius=vp._shuttle["radius"])
        limit = flight.slip_limit(vp.camera.distance)
        if float(np.linalg.norm(target - vp.camera.center)) > limit - 1e-9:
            fired += 1
    assert fired == 0


# ------------------------------------------------- the round-71 cache is safe
def test_the_draw_cache_is_off_while_the_cockpit_CULLS(win):
    """`_shuttle_hidden` measures every atom against the EYE, which moves every
    tick - so a cached block froze the mask of the moment it was built, and
    flying up to another molecule drew its atoms straight through the lens."""
    from molom.core.structure import Structure
    obj = win._active_obj()
    vp = win.viewport
    other = win.scene.add(Structure(["C", "O"],
                                    [np.array([[30.0, 0.0, 0.0],
                                               [31.4, 0.0, 0.0]])]),
                          name="bystander")
    vp.set_selection([(obj.id, 0)])
    win.on_shuttle()
    vp._object_block(other)
    assert vp._draw_cache is not None      # flight still caches in general
    assert other.id not in vp._draw_cache


def test_the_draw_cache_is_still_used_in_third_person(win):
    """Nothing is culled there, so the block is camera-independent and round
    71's measurement stands."""
    from molom.core.structure import Structure
    obj = win._active_obj()
    vp = win.viewport
    other = win.scene.add(Structure(["C"], [np.array([[30.0, 0.0, 0.0]])]),
                          name="bystander")
    vp.set_selection([(obj.id, 0)])
    win.on_shuttle(third_person=True)
    vp._object_block(other)
    assert other.id in vp._draw_cache
