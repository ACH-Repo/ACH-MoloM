"""Round 34: internal-coordinate editing (bond length / angle / dihedral)
with the rest of the molecule following, and the flight model behind the
right-mouse fly.

The round trip is the real test in both halves: after asking for a value, the
measurement has to come back as that value, and the rest of the molecule has
to be untouched. Sign conventions are pinned here rather than argued in a
comment.
"""

import numpy as np
import pytest

from molom.core import flight, internal, measure
from molom.core.camera import Camera


# ------------------------------------------------------------------ splitting
def _chain_bonds(n):
    """0-1-2-...-(n-1)."""
    return [(i, i + 1, 1) for i in range(n - 1)]


def test_moving_group_takes_the_whole_tail_of_a_chain():
    moving, blocked = internal.moving_group(5, _chain_bonds(5), 1, 2)
    assert moving == {2, 3, 4}
    assert blocked is False


def test_moving_group_stops_at_the_anchor():
    moving, _ = internal.moving_group(5, _chain_bonds(5), 2, 1)
    assert moving == {0, 1}


def test_a_ring_bond_has_no_clean_split():
    ring = [(0, 1, 1), (1, 2, 1), (2, 0, 1)]
    moving, blocked = internal.moving_group(3, ring, 0, 1)
    assert blocked is True
    assert moving == {1}          # honest minimum, not a deformed ring


def test_two_separate_fragments_split_cleanly():
    bonds = [(0, 1, 1), (2, 3, 1)]
    moving, blocked = internal.moving_group(4, bonds, 1, 2)
    assert blocked is False
    assert moving == {2, 3}       # the whole second molecule slides


def test_non_bonded_pair_in_one_fragment_is_blocked():
    """A 1,3 contact has no far side — "which half moves" has no answer."""
    moving, blocked = internal.moving_group(3, _chain_bonds(3), 0, 2)
    assert blocked is True
    assert moving == {2}


def test_split_for_cuts_the_last_bond_of_the_coordinate():
    bonds = _chain_bonds(4)
    assert internal.split_for(internal.DISTANCE, 4, bonds, [0, 1])[0] \
        == {1, 2, 3}
    assert internal.split_for(internal.ANGLE, 4, bonds, [0, 1, 2])[0] \
        == {2, 3}
    assert internal.split_for(internal.DIHEDRAL, 4, bonds, [0, 1, 2, 3])[0] \
        == {2, 3}


# ------------------------------------------------------------------ distance
def test_set_distance_hits_the_target_and_carries_the_fragment():
    coords = np.array([[0.0, 0, 0], [1.0, 0, 0], [2.0, 0, 0], [2.0, 1.0, 0]])
    bonds = [(0, 1, 1), (1, 2, 1), (2, 3, 1)]
    moving, _ = internal.moving_group(4, bonds, 0, 1)
    out = internal.set_distance(coords, moving, 0, 1, 1.5)
    assert measure.distance(out[0], out[1]) == pytest.approx(1.5)
    # everything downstream moved rigidly: internal geometry is untouched
    assert measure.distance(out[1], out[2]) == pytest.approx(1.0)
    assert measure.distance(out[2], out[3]) == pytest.approx(1.0)
    assert np.allclose(out[0], coords[0])       # the anchor never moves


def test_set_distance_shrinks_as_well_as_stretches():
    coords = np.array([[0.0, 0, 0], [2.0, 0, 0]])
    out = internal.set_distance(coords, {1}, 0, 1, 0.75)
    assert measure.distance(out[0], out[1]) == pytest.approx(0.75)


def test_set_distance_ignores_coincident_atoms():
    coords = np.zeros((2, 3))
    out = internal.set_distance(coords, {1}, 0, 1, 1.5)
    assert np.allclose(out, coords)     # no direction exists; no NaNs either


# --------------------------------------------------------------------- angle
def test_set_angle_round_trips():
    coords = np.array([[1.0, 0, 0], [0.0, 0, 0], [0.0, 1.0, 0],
                       [0.0, 2.0, 0.5]])
    bonds = [(0, 1, 1), (1, 2, 1), (2, 3, 1)]
    moving, _ = internal.moving_group(4, bonds, 1, 2)
    for target in (109.5, 60.0, 175.0):
        out = internal.set_angle(coords, moving, 0, 1, 2, target)
        assert measure.angle(out[0], out[1], out[2]) == pytest.approx(target)


def test_set_angle_leaves_the_moving_fragment_rigid():
    coords = np.array([[1.0, 0, 0], [0.0, 0, 0], [0.0, 1.0, 0],
                       [0.0, 2.0, 0.5]])
    moving = {2, 3}
    out = internal.set_angle(coords, moving, 0, 1, 2, 70.0)
    assert measure.distance(out[2], out[3]) == \
        pytest.approx(measure.distance(coords[2], coords[3]))
    assert np.allclose(out[:2], coords[:2])


def test_set_angle_survives_a_collinear_start():
    coords = np.array([[1.0, 0, 0], [0.0, 0, 0], [-1.0, 0, 0]])
    out = internal.set_angle(coords, {2}, 0, 1, 2, 90.0)
    assert measure.angle(out[0], out[1], out[2]) == pytest.approx(90.0)


# ------------------------------------------------------------------ dihedral
def _butane_like():
    """Four atoms with a well-defined, non-degenerate torsion."""
    return np.array([[1.0, 1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 0.0],
                     [0.0, -1.0, 0.6]])


def test_set_dihedral_round_trips_over_the_whole_circle():
    coords = _butane_like()
    for target in (0.0, 60.0, 120.0, -60.0, 179.0, -179.0):
        out = internal.set_dihedral(coords, {3}, 0, 1, 2, 3, target)
        got = measure.dihedral(out[0], out[1], out[2], out[3])
        assert got == pytest.approx(target, abs=1e-6)


def test_set_dihedral_moves_only_the_far_side():
    coords = _butane_like()
    out = internal.set_dihedral(coords, {3}, 0, 1, 2, 3, 45.0)
    assert np.allclose(out[:3], coords[:3])


def test_set_dihedral_carries_a_substituent_rigidly():
    coords = np.vstack([_butane_like(), [[0.0, -2.0, 1.2]]])
    bonds = [(0, 1, 1), (1, 2, 1), (2, 3, 1), (3, 4, 1)]
    moving, blocked = internal.moving_group(5, bonds, 1, 2)
    assert blocked is False and moving == {2, 3, 4}
    out = internal.set_dihedral(coords, moving, 0, 1, 2, 3, 90.0)
    assert measure.dihedral(out[0], out[1], out[2], out[3]) \
        == pytest.approx(90.0)
    assert measure.distance(out[3], out[4]) == \
        pytest.approx(measure.distance(coords[3], coords[4]))


def test_apply_dispatches_the_same_way_as_the_setters():
    coords = _butane_like()
    a = internal.apply(internal.DIHEDRAL, coords, {3}, [0, 1, 2, 3], 33.0)
    b = internal.set_dihedral(coords, {3}, 0, 1, 2, 3, 33.0)
    assert np.allclose(a, b)
    with pytest.raises(ValueError):
        internal.apply("torsion-ish", coords, {3}, [0, 1, 2, 3], 1.0)


def test_kind_for_count_drives_the_context_menu():
    assert internal.kind_for_count(2) == internal.DISTANCE
    assert internal.kind_for_count(3) == internal.ANGLE
    assert internal.kind_for_count(4) == internal.DIHEDRAL
    assert internal.kind_for_count(1) is None
    assert internal.kind_for_count(5) is None
    assert internal.unit_for(internal.ANGLE) == "deg"
    assert internal.label_for(internal.DISTANCE) == "Bond length"


def test_current_value_matches_measure():
    coords = _butane_like()
    assert internal.current_value(internal.DISTANCE, coords, [0, 1]) == \
        pytest.approx(measure.distance(coords[0], coords[1]))
    assert internal.current_value(internal.ANGLE, coords, [0, 1, 2]) == \
        pytest.approx(measure.angle(coords[0], coords[1], coords[2]))


# -------------------------------------------------------------------- flight
def _identity_basis():
    return np.eye(3)          # right = X, up = Y, forward = Z


def test_thrust_is_normalised_so_diagonals_are_not_faster():
    model = flight.FlightModel()
    one = model.thrust_world((0, 0, 1), _identity_basis())
    two = model.thrust_world((1, 0, 1), _identity_basis())
    assert np.linalg.norm(one) == pytest.approx(1.0)
    assert np.linalg.norm(two) == pytest.approx(1.0)


def test_holding_thrust_accelerates_then_settles_at_a_cap():
    model = flight.FlightModel()
    speeds = []
    for _ in range(400):
        model.step(1 / 60.0, (0, 0, 1), _identity_basis())
        speeds.append(float(np.linalg.norm(model.velocity)))
    assert speeds[0] < speeds[5] < speeds[40]          # it accelerates
    assert speeds[-1] <= model.max_speed * 1.001       # and is capped
    assert speeds[-1] == pytest.approx(speeds[-2], rel=1e-3)   # steady state


def test_releasing_thrust_coasts_to_a_stop_rather_than_stopping_dead():
    model = flight.FlightModel()
    for _ in range(60):
        model.step(1 / 60.0, (0, 0, 1), _identity_basis())
    coasting = float(np.linalg.norm(model.velocity))
    moved = 0.0
    ticks = 0
    while model.moving and ticks < 6000:
        moved += float(np.linalg.norm(model.step(1 / 60.0, (0, 0, 0),
                                                 _identity_basis())))
        ticks += 1
    assert coasting > 0.0
    assert moved > 0.0              # it kept travelling after the key went up
    assert ticks > 5                # for a perceptible glide, not one frame
    assert not model.moving         # and it does come to rest


def test_velocity_stays_in_world_space_when_the_view_turns():
    """Turning must not re-aim the momentum you already have."""
    model = flight.FlightModel()
    for _ in range(30):
        model.step(1 / 60.0, (0, 0, 1), _identity_basis())
    before = model.velocity.copy()
    turned = np.array([[0.0, 0, 1.0], [0, 1.0, 0], [-1.0, 0, 0]])
    model.step(1 / 60.0, (0, 0, 0), turned)
    assert np.allclose(before / np.linalg.norm(before),
                       model.velocity / np.linalg.norm(model.velocity))


def test_boost_raises_both_the_cap_and_the_acceleration():
    plain, fast = flight.FlightModel(), flight.FlightModel()
    for _ in range(200):
        plain.step(1 / 60.0, (0, 0, 1), _identity_basis())
        fast.step(1 / 60.0, (0, 0, 1), _identity_basis(),
                  boost=flight.BOOST_FACTOR)
    assert np.linalg.norm(fast.velocity) > np.linalg.norm(plain.velocity) * 2


def test_damping_is_stable_at_a_silly_frame_time():
    """exp(-k dt) can never overshoot through zero; v -= k*v*dt would."""
    model = flight.FlightModel()
    model.velocity = np.array([5.0, 0.0, 0.0])
    model.step(2.0, (0, 0, 0), _identity_basis())
    assert model.velocity[0] >= 0.0


def test_scale_makes_a_big_scene_fly_proportionally_faster():
    small, big = flight.FlightModel(scale=1.0), flight.FlightModel(scale=10.0)
    for _ in range(300):
        small.step(1 / 60.0, (0, 0, 1), _identity_basis())
        big.step(1 / 60.0, (0, 0, 1), _identity_basis())
    assert np.linalg.norm(big.velocity) == \
        pytest.approx(np.linalg.norm(small.velocity) * 10.0, rel=1e-6)


def test_keys_from_set_sums_opposing_keys_to_nothing():
    mapping = {"w": (0, 0, 1), "s": (0, 0, -1), "d": (1, 0, 0)}
    assert flight.keys_from_set({"w", "s"}, mapping) == (0.0, 0.0, 0.0)
    assert flight.keys_from_set({"w", "d"}, mapping) == (1.0, 0.0, 1.0)


def test_clamp_pitch_delta_stops_short_of_the_pole():
    up_ish = np.array([0.0, 0.02, 0.999])
    assert flight.clamp_pitch_delta(up_ish, 1.0) < 0.05      # trimmed hard
    assert flight.clamp_pitch_delta(up_ish, -0.3) == pytest.approx(-0.3)
    level = np.array([1.0, 0.0, 0.0])
    assert flight.clamp_pitch_delta(level, 0.2) == pytest.approx(0.2)


# ---------------------------------------------------------------- fly camera
def test_fly_look_never_rolls():
    """The no-roll invariant: world Z must stay in the screen's Y-Z plane."""
    cam = Camera()
    rng = np.random.RandomState(7)
    for _ in range(300):
        cam.fly_look(float(rng.uniform(-0.4, 0.4)),
                     float(rng.uniform(-0.4, 0.4)))
        from molom.core.camera import quat_to_mat3
        assert abs((quat_to_mat3(cam.rotation) @ np.array([0, 0, 1.0]))[0]) \
            < 1e-9


def test_fly_look_yaw_turns_left_and_pitch_looks_up():
    cam = Camera()
    cam.fly_look(0.0, -2.0)              # level out first
    before = cam.forward()
    cam.fly_look(0.3, 0.0)
    after = cam.forward()
    # +yaw is anticlockwise seen from +Z, i.e. to the viewer's left
    assert np.cross(before, after)[2] > 0.0
    cam.fly_look(0.0, 0.2)
    assert cam.forward()[2] > after[2]


def test_fly_look_pitch_is_clamped_short_of_vertical():
    cam = Camera()
    for _ in range(50):
        cam.fly_look(0.0, 0.5)
    assert cam.forward()[2] < 0.9999      # never straight up
    assert cam.forward()[2] > 0.99        # but it did get most of the way


def test_fly_move_carries_the_orbit_centre():
    cam = Camera()
    before = cam.center.copy()
    cam.fly_move(np.array([1.0, 2.0, 3.0]))
    assert np.allclose(cam.center, before + np.array([1.0, 2.0, 3.0]))


def test_basis_rows_are_orthonormal_and_forward_matches():
    cam = Camera()
    rows = cam.basis_rows()
    assert np.allclose(rows @ rows.T, np.eye(3), atol=1e-9)
    assert np.allclose(rows[2], cam.forward())


def test_fly_look_pops_an_axis_view_back_to_perspective():
    cam = Camera()
    cam.align_view(0, 1)
    assert cam.orthographic and cam.auto_ortho
    cam.fly_look(0.1, 0.0)
    assert not cam.orthographic
