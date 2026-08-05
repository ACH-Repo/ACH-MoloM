"""Round 35: the 6DoF arcade handling model.

Everspace-style flight — strafe primacy, inertial dampening (auto-braking),
explicit roll on Q/E, and a reticle that drifts off the hull under turn. The
one deliberate divergence from a true space sim is that pitch stays clamped
short of vertical; see `core/flight.py` for why.
"""

import numpy as np
import pytest

from molom.core import flight
from molom.core.camera import Camera, quat_to_mat3


def _identity_basis():
    return np.eye(3)          # right = X, up = Y, forward = Z


def _terminal_speed(model, keys, ticks=400):
    for _ in range(ticks):
        model.step(1 / 60.0, keys, _identity_basis())
    return float(np.linalg.norm(model.velocity))


# ------------------------------------------------------------ strafe primacy
def test_strafe_is_as_responsive_as_forward_by_default():
    """Rule 2 of the brief: sidestepping must not feel like a nudge."""
    fwd, side = flight.FlightModel(), flight.FlightModel()
    for _ in range(20):
        fwd.step(1 / 60.0, (0, 0, 1), _identity_basis())
        side.step(1 / 60.0, (1, 0, 0), _identity_basis())
    assert np.linalg.norm(side.velocity) == \
        pytest.approx(np.linalg.norm(fwd.velocity), rel=1e-9)


def test_strafe_factor_actually_changes_lateral_acceleration():
    """It has to be applied to the ACCELERATION, not to the key vector.

    `thrust_world` normalises, so a weighting folded into the components
    would be divided straight back out and the tuning would silently do
    nothing — which is the trap this test exists to catch.
    """
    plain = flight.FlightModel()
    snappy = flight.FlightModel(strafe_factor=2.0)
    for _ in range(10):
        plain.step(1 / 60.0, (1, 0, 0), _identity_basis())
        snappy.step(1 / 60.0, (1, 0, 0), _identity_basis())
    assert np.linalg.norm(snappy.velocity) > \
        np.linalg.norm(plain.velocity) * 1.9
    # ...and it must leave pure FORWARD thrust completely alone.
    fa, fb = flight.FlightModel(), flight.FlightModel(strafe_factor=2.0)
    assert _terminal_speed(fa, (0, 0, 1)) == \
        pytest.approx(_terminal_speed(fb, (0, 0, 1)))


def test_accel_for_blends_the_axes_on_a_diagonal():
    model = flight.FlightModel(strafe_factor=3.0)
    assert model.accel_for((0, 0, 1)) == pytest.approx(model.accel)
    assert model.accel_for((1, 0, 0)) == pytest.approx(model.accel * 3.0)
    assert model.accel_for((1, 0, 1)) == pytest.approx(model.accel * 2.0)
    assert model.accel_for((0, 0, 0)) == pytest.approx(model.accel)


# -------------------------------------------------------- inertial dampening
def test_releasing_the_keys_brakes_harder_than_it_accelerated():
    """Rule 3: deceleration 1.5-2x acceleration, so nothing floats."""
    braking, coasting = flight.FlightModel(), flight.FlightModel(
        brake_factor=1.0)
    for m in (braking, coasting):
        for _ in range(60):
            m.step(1 / 60.0, (0, 0, 1), _identity_basis())

    def ticks_to_rest(m):
        n = 0
        while m.moving and n < 6000:
            m.step(1 / 60.0, (0, 0, 0), _identity_basis())
            n += 1
        return n

    assert ticks_to_rest(braking) < ticks_to_rest(coasting)


def test_auto_brake_does_not_apply_while_a_key_is_held():
    """The high drag is for LETTING GO. Applying it under thrust would just
    lower the top speed and make the ship feel underpowered."""
    held = flight.FlightModel(brake_factor=4.0)
    normal = flight.FlightModel(brake_factor=1.0)
    assert _terminal_speed(held, (0, 0, 1)) == \
        pytest.approx(_terminal_speed(normal, (0, 0, 1)))


def test_braking_still_leaves_a_visible_glide():
    """Auto-brake must not become an instant stop — you still need to be
    able to see the ship settle, or it reads as a teleport."""
    model = flight.FlightModel()
    for _ in range(60):
        model.step(1 / 60.0, (0, 0, 1), _identity_basis())
    moved, ticks = 0.0, 0
    while model.moving and ticks < 6000:
        moved += float(np.linalg.norm(
            model.step(1 / 60.0, (0, 0, 0), _identity_basis())))
        ticks += 1
    assert ticks > 5
    assert moved > 0.0
    assert not model.moving


# ------------------------------------------------------------------- roll
def test_roll_accumulates_only_while_a_roll_key_is_held():
    model = flight.FlightModel()
    for _ in range(30):
        model.step_roll(1 / 60.0, 1.0)
    rolled = model.roll
    assert rolled > 0.0
    for _ in range(30):
        model.step_roll(1 / 60.0, 0.0)
    assert model.roll == pytest.approx(rolled)   # no angular drift


def test_roll_wraps_instead_of_growing_without_bound():
    model = flight.FlightModel()
    for _ in range(10000):
        model.step_roll(1 / 60.0, 1.0)
    assert -np.pi <= model.roll <= np.pi


def test_level_puts_the_roll_back_to_zero():
    model = flight.FlightModel()
    model.step_roll(1.0, 1.0)
    assert model.roll != 0.0
    model.level()
    assert model.roll == 0.0


def test_camera_roll_tilts_the_horizon_and_zero_roll_is_unchanged():
    plain, rolled = Camera(), Camera()
    plain.fly_look(0.2, 0.1)
    rolled.fly_look(0.2, 0.1, roll=0.0)
    assert np.allclose(plain.rotation, rolled.rotation)
    rolled.fly_look(0.0, 0.0, roll=0.5)
    # The view DIRECTION is untouched by roll; only the up vector turns.
    assert np.allclose(plain.forward(), rolled.forward(), atol=1e-9)
    assert not np.allclose(plain.rotation, rolled.rotation)


def test_camera_roll_leaves_an_orthonormal_right_handed_basis():
    cam = Camera()
    for roll in (0.3, 1.2, -2.5, np.pi):
        cam.fly_look(0.1, 0.05, roll=roll)
        m = quat_to_mat3(cam.rotation)
        assert np.allclose(m @ m.T, np.eye(3), atol=1e-9)
        assert np.linalg.det(m) == pytest.approx(1.0)


def test_roll_is_not_fed_back_into_yaw_and_pitch():
    """Roll must stay a final twist. If it leaked into the angles, a long
    rolled flight would slowly corrupt the heading — the exact drift the
    azimuth/elevation rebuild exists to prevent."""
    cam = Camera()
    cam.fly_look(0.0, -2.0)                  # level out
    heading = cam.forward().copy()
    for _ in range(500):
        cam.fly_look(0.0, 0.0, roll=1.1)
    assert np.allclose(cam.forward(), heading, atol=1e-9)


def test_landing_level_restores_a_no_roll_camera():
    """The orbit camera is a turntable and cannot hold a rolled pose, so
    `(R @ e_z).x == 0` — the round-3 invariant — has to come back."""
    cam = Camera()
    cam.fly_look(0.4, 0.2, roll=0.9)
    cam.fly_look(0.0, 0.0, roll=0.0)
    assert abs((quat_to_mat3(cam.rotation) @ np.array([0.0, 0.0, 1.0]))[0]) \
        < 1e-9


# ------------------------------------------------- the aiming reticle
# Round 35, second pass. The first cut made the reticle chase the angular
# RATE and ease back to centre, which meant a turn stopped the moment the
# mouse stopped moving. Christian's spec is the flight-sim one: the mark
# STAYS where you put it and the ship keeps turning until you bring it home.
def test_the_reticle_stays_put_when_the_mouse_stops():
    aim = flight.AimReticle()
    for _ in range(20):
        aim.move(4.0, 0.0, 800.0)
    parked = aim.offset.copy()
    assert np.linalg.norm(parked) > 1.0
    for _ in range(500):                      # a long time with no input
        pass
    assert np.allclose(aim.offset, parked)    # nothing decays on its own


def test_a_deflected_reticle_keeps_commanding_a_turn():
    """The behaviour the whole rework exists for."""
    aim = flight.AimReticle()
    for _ in range(40):
        aim.move(5.0, 0.0, 800.0)
    first = aim.deflection(800.0)[0]
    assert first > 0.0
    # ...and it is still commanding the same turn many ticks later.
    assert aim.deflection(800.0)[0] == pytest.approx(first)


def test_bringing_the_reticle_back_to_centre_stops_the_turn():
    aim = flight.AimReticle()
    for _ in range(40):
        aim.move(5.0, 0.0, 800.0)
    assert not aim.centred(800.0)
    for _ in range(40):                       # exactly back the way we came
        aim.move(-5.0, 0.0, 800.0)
    assert aim.centred(800.0)
    assert np.allclose(aim.deflection(800.0), 0.0)


def test_the_reticle_is_clamped_to_a_disc():
    aim = flight.AimReticle(span=0.2)
    for _ in range(500):
        aim.move(30.0, 30.0, 800.0)
    assert np.linalg.norm(aim.offset) <= 0.2 * 800.0 * 1.001


def test_deflection_is_proportional_and_has_a_dead_zone():
    aim = flight.AimReticle(span=0.5, deadzone=0.1, expo=1.0)
    aim.move(400.0, 0.0, 800.0)               # full deflection
    assert aim.deflection(800.0)[0] == pytest.approx(1.0)
    aim.recentre()
    aim.move(20.0, 0.0, 800.0)                # 5% — inside the dead zone
    assert aim.deflection(800.0)[0] == 0.0
    aim.recentre()
    aim.move(200.0, 0.0, 800.0)               # 50%
    mid = aim.deflection(800.0)[0]
    assert 0.4 < mid < 0.5                    # dead zone rescaled, not clipped


# ------------------------------------------------------------------ expo
def test_expo_softens_the_centre_but_keeps_full_rate_at_full_stick():
    """Christian: "it is a bit sensitive... maybe it should get less
    sensitive towards the centre." A power curve gives f(0)=0 and f(1)=1
    exactly, and puts all its flattening where small corrections are made."""
    linear = flight.AimReticle(span=0.5, deadzone=0.0, expo=1.0)
    curved = flight.AimReticle(span=0.5, deadzone=0.0, expo=2.0)
    for aim in (linear, curved):
        aim.move(400.0, 0.0, 800.0)
    assert linear.deflection(800.0)[0] == pytest.approx(1.0)
    assert curved.deflection(800.0)[0] == pytest.approx(1.0)
    for aim in (linear, curved):
        aim.recentre()
        aim.move(100.0, 0.0, 800.0)           # a quarter out
    assert curved.deflection(800.0)[0] < linear.deflection(800.0)[0] * 0.4


def test_expo_bends_the_rate_not_the_direction():
    """The curve is applied to the MAGNITUDE. A diagonal stick must still
    turn diagonally, or aiming becomes unpredictable off-axis."""
    aim = flight.AimReticle(span=0.5, deadzone=0.0, expo=2.5)
    aim.move(150.0, 150.0, 800.0)
    d = aim.deflection(800.0)
    assert d[0] == pytest.approx(d[1])
    raw = aim.offset / np.linalg.norm(aim.offset)
    unit = d / np.linalg.norm(d)
    assert np.allclose(unit, raw, atol=1e-9)


def test_expo_is_monotone_so_pushing_further_always_turns_harder():
    aim = flight.AimReticle(span=0.5, deadzone=0.05, expo=2.0)
    last = -1.0
    for _ in range(60):
        aim.move(8.0, 0.0, 800.0)
        now = float(aim.deflection(800.0)[0])
        assert now >= last - 1e-12
        last = now


def test_expo_of_one_is_exactly_linear():
    """The escape hatch: nothing about the curve may be baked in."""
    aim = flight.AimReticle(span=0.5, deadzone=0.0, expo=1.0)
    aim.move(200.0, 0.0, 800.0)
    assert aim.deflection(800.0)[0] == pytest.approx(0.5)


def test_the_dead_zone_response_is_continuous_at_its_edge():
    """A step from "straight" to "turning" is felt as a jolt every time you
    cross it, so the remaining travel is rescaled rather than clipped."""
    aim = flight.AimReticle(span=0.5, deadzone=0.2)
    aim.move(0.5 * 800.0 * 0.2001, 0.0, 800.0)
    assert aim.deflection(800.0)[0] == pytest.approx(0.0, abs=1e-3)


# ------------------------------------------------------ automatic banking
def test_turning_banks_the_ship_and_holds_the_bank():
    model = flight.FlightModel()
    for _ in range(300):
        model.step_bank(1 / 60.0, 1.0)        # hard right, held
    banked = model.roll
    assert banked == pytest.approx(-model.bank_angle, rel=1e-3)
    for _ in range(120):                      # still deflected: it HOLDS
        model.step_bank(1 / 60.0, 1.0)
    assert model.roll == pytest.approx(banked, rel=1e-3)


def test_centring_the_stick_eases_the_bank_back_to_level():
    model = flight.FlightModel()
    for _ in range(120):
        model.step_bank(1 / 60.0, 1.0)
    assert abs(model.roll) > 0.1
    for _ in range(400):
        model.step_bank(1 / 60.0, 0.0)
    assert abs(model.roll) < 1e-3


def test_banking_is_mirrored_for_a_left_turn():
    right, left = flight.FlightModel(), flight.FlightModel()
    for _ in range(120):
        right.step_bank(1 / 60.0, 1.0)
        left.step_bank(1 / 60.0, -1.0)
    assert right.roll == pytest.approx(-left.roll)


def test_manual_roll_and_bank_add_without_destroying_each_other():
    model = flight.FlightModel()
    model.step_roll(1.0, 1.0)                 # Q held for a second
    manual = model.manual_roll
    for _ in range(120):
        model.step_bank(1 / 60.0, 1.0)
    assert model.manual_roll == pytest.approx(manual)   # bank did not eat it
    assert model.roll == pytest.approx(manual + model.bank)
    model.level()
    assert model.roll == 0.0


# ===================================================================== UI
# Everything above is offline maths. What follows can only go wrong once Qt
# is involved: which state owns the keyboard, and how the right button's two
# meanings (menu, flight) are told apart.
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def win():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.app import MainWindow
    QApplication.instance() or QApplication([])
    w = MainWindow()
    w.show()
    w.load_default_scene()
    return w


def test_latched_flight_survives_the_button_coming_up(win):
    vp = win.viewport
    vp.start_fly(latched=True)
    assert vp.flying() and vp._fly["latched"]
    vp._fly["keys"].clear()
    for _ in range(200):                    # plenty of idle ticks
        vp._fly_tick(1 / 60.0)
    assert vp.flying()                      # a held flight would have ended
    vp.stop_fly(coast=False)
    assert not vp.flying()


def test_starting_a_held_flight_then_double_clicking_promotes_it(win):
    """The first click of a double-click has already started an ordinary
    held flight; the second must latch it rather than open a second one."""
    vp = win.viewport
    vp.start_fly()
    assert not vp._fly["latched"]
    vp.start_fly(latched=True)
    assert vp._fly["latched"]
    vp.stop_fly(coast=False)


def test_space_and_ctrl_are_the_vertical_thrust_keys(win):
    from PySide6.QtCore import Qt
    vp = win.viewport
    assert Qt.Key_Space in vp._FLY_KEYS
    assert Qt.Key_Control in vp._FLY_KEYS
    assert vp._FLY_KEYS[Qt.Key_Space][1] > 0      # up
    assert vp._FLY_KEYS[Qt.Key_Control][1] < 0    # down
    # ...and Q/E gave up thrust for roll.
    assert Qt.Key_Q not in vp._FLY_KEYS
    assert Qt.Key_E not in vp._FLY_KEYS
    assert set(vp._ROLL_KEYS) == {Qt.Key_Q, Qt.Key_E}


def test_roll_keys_turn_the_camera_and_landing_levels_it(win):
    from PySide6.QtCore import Qt
    from molom.core.camera import quat_to_mat3
    vp = win.viewport
    vp.start_fly(latched=True)
    vp._fly["roll_keys"].add(Qt.Key_Q)
    for _ in range(30):
        vp._fly_tick(1 / 60.0)
    assert abs(vp._fly["model"].roll) > 0.01
    rolled = quat_to_mat3(vp.camera.rotation) @ np.array([0.0, 0.0, 1.0])
    assert abs(float(rolled[0])) > 1e-6          # horizon really is tilted
    vp.stop_fly(coast=False)
    # Landing restores the turntable invariant, or the next orbit would snap
    # the roll away and look like a glitch.
    level = quat_to_mat3(vp.camera.rotation) @ np.array([0.0, 0.0, 1.0])
    assert abs(float(level[0])) < 1e-9


def test_flight_keys_do_not_collide_with_the_operator_table(win):
    """W/A/S/D/Q/E/Space/Ctrl are only read while `_fly` is live and the
    viewport holds the keyboard, so they may safely shadow the object- and
    edit-mode bindings for the same letters. This pins the guard that makes
    that true, plus the registry staying clash-free."""
    vp = win.viewport
    assert not vp._keyboard_captured()
    vp.start_fly()
    assert vp._keyboard_captured()
    vp.stop_fly(coast=False)
    assert win.ops.duplicate_keys() == {}


def test_ctrl_no_longer_creeps_now_that_it_descends(win):
    """A key that both moves you and quarters your speed is unusable."""
    import inspect
    src = inspect.getsource(win.viewport._fly_tick)
    assert "AltModifier" in src
    assert "ControlModifier" not in src


def test_a_right_click_off_the_selection_opens_nothing(win):
    """`open_context_menu` refuses anywhere but on an already-selected atom,
    so an ordinary right click over empty space costs nothing at all."""
    from PySide6.QtCore import QPointF
    vp = win.viewport
    vp.set_selection([])
    vp.open_context_menu(QPointF(5.0, 5.0))
    assert vp._context_popup is None


def test_looking_around_does_not_move_the_camera(win):
    """Christian: "moving the cursor up and down moves the camera by a lot up
    and down as well. it should only tilt the view."

    The camera is an orbit rig — the eye sits `distance` behind `center` — so
    changing only the rotation swings the eye around the pivot on an arc. A
    pilot's head turns; it does not orbit a point in front of them.
    """
    vp = win.viewport
    vp.start_fly(latched=True)
    eye = vp._fly_eye().copy()
    for _ in range(40):
        vp._fly_turn(0.05, 0.04)
    assert np.allclose(vp._fly_eye(), eye, atol=1e-9)
    vp.stop_fly(coast=False)


def test_thrust_still_moves_the_camera(win):
    """The counterpart: pinning the eye during a TURN must not pin it during
    a translation, or flight stops working entirely."""
    from PySide6.QtCore import Qt
    vp = win.viewport
    vp.start_fly(latched=True)
    eye = vp._fly_eye().copy()
    vp._fly["keys"].add(Qt.Key_W)
    for _ in range(20):
        vp._fly_tick(1 / 60.0)
    assert np.linalg.norm(vp._fly_eye() - eye) > 0.01
    vp.stop_fly(coast=False)


def test_a_deflected_reticle_keeps_turning_with_no_further_mouse_input(win):
    """The headline behaviour: point the stick and the ship keeps coming
    round, tick after tick, with the mouse completely still."""
    vp = win.viewport
    vp.resize(800, 600)
    vp.start_fly(latched=True)
    vp._fly["aim"].move(120.0, 0.0, 600.0)
    headings = []
    for _ in range(30):
        vp._fly_tick(1 / 60.0)
        headings.append(vp.camera.forward().copy())
    # Every tick turned further in the same direction.
    turns = [float(np.dot(np.cross(headings[i], headings[i + 1]),
                          np.array([0.0, 0.0, 1.0])))
             for i in range(len(headings) - 1)]
    assert all(t < 0 for t in turns)          # consistently rightward
    vp.stop_fly(coast=False)


def test_centring_the_reticle_stops_the_turn(win):
    vp = win.viewport
    vp.resize(800, 600)
    vp.start_fly(latched=True)
    vp._fly["aim"].move(120.0, 0.0, 600.0)
    for _ in range(20):
        vp._fly_tick(1 / 60.0)
    vp._fly["aim"].recentre()
    for _ in range(20):
        vp._fly_tick(1 / 60.0)
    before = vp.camera.forward().copy()
    for _ in range(20):
        vp._fly_tick(1 / 60.0)
    assert np.allclose(vp.camera.forward(), before, atol=1e-6)
    vp.stop_fly(coast=False)


def test_flight_hides_and_captures_the_pointer(win):
    """No wrap: the pointer is hidden and held, so it can never reach the
    edge where the properties dock used to swallow the steering."""
    from PySide6.QtCore import Qt
    vp = win.viewport
    vp.start_fly(latched=True)
    assert vp.cursor().shape() == Qt.BlankCursor
    vp.stop_fly(coast=False)
    assert vp.cursor().shape() != Qt.BlankCursor


def test_turning_right_banks_right_and_centring_levels_it(win):
    vp = win.viewport
    vp.resize(800, 600)
    vp.start_fly(latched=True)
    vp._fly["aim"].move(160.0, 0.0, 600.0)
    for _ in range(200):
        vp._fly_tick(1 / 60.0)
    assert vp._fly["model"].roll < -0.05        # rolled into the turn
    vp._fly["aim"].recentre()
    for _ in range(400):
        vp._fly_tick(1 / 60.0)
    assert abs(vp._fly["model"].roll) < 1e-2    # and levelled again
    vp.stop_fly(coast=False)
