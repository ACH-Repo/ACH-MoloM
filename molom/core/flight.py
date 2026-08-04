"""Flying a camera (or a molecule) through the scene, with acceleration and
inertia — the UE5 right-mouse fly, not a step-per-keypress jog.

The round-8 shuttle moved a fixed step on every key PRESS, so holding W gave
Qt's auto-repeat rhythm: a jump, a pause, then a stutter of jumps. That reads
as broken however good the rest is, because flight is the one interaction
where the eye is judging *velocity*. So this integrates a proper little
physics model instead:

* keys set a THRUST direction, not a position;
* thrust accelerates a world-space VELOCITY, which is what carries the inertia
  — let go and you coast to a stop instead of stopping dead;
* velocity is damped exponentially, which is both the cheapest realistic drag
  and unconditionally stable at any frame time (`exp(-k dt)` can never
  overshoot through zero the way `v -= k*v*dt` does at large dt);
* speed is clamped, so holding W does not eventually put you in the next
  postcode.

Velocity is kept in WORLD space on purpose. Keeping it in the camera frame
would mean a turn instantly re-aims your momentum, which feels like a
video-game camera and not like flying; in world space you keep drifting the
way you were going while you look somewhere else, which is exactly the
sensation Christian asked for.

**Roll is an EXPLICIT term, and only inside flight** (round 35). The round-34
note here said roll, if ever wanted, "belongs as an explicit extra term with a
one-key reset, not as an accident of the pitch integration" — that is exactly
what `FlightModel.roll` now is. Look is still built from an (azimuth,
elevation) pair, so roll cannot *accumulate*; it is a separate angle the
camera applies about the view axis at the very end, driven by Q/E and zeroed
on landing. Pitch stays CLAMPED just short of vertical, which is the one place
this diverges from a true 6DoF space sim: passing over the pole with a
world-Z-referenced azimuth is a gimbal flip, and the orbit camera you land
back into is a turntable that cannot represent an inverted pose anyway.

UI-free numpy: no Qt, no GL, no timer. The caller supplies `dt` and the
current camera basis, which is what makes the whole model testable offline.
"""

from typing import Optional, Tuple

import numpy as np

#: Defaults, in scene units (Angstrom) and seconds. Tuned so that on a typical
#: molecule (~10 A across) a tap of W nudges and a held W crosses the scene in
#: about a second, with roughly a third of a second of coasting afterwards.
DEFAULT_ACCEL = 60.0        # A/s^2 at full thrust
DEFAULT_MAX_SPEED = 18.0    # A/s
DEFAULT_DAMPING = 4.5       # 1/s; higher = stops sooner
BOOST_FACTOR = 3.0          # Shift
PRECISION_FACTOR = 0.25     # Alt: creep (Ctrl is DESCEND, round 35)

#: STRAFE PRIMACY. Lateral (A/D) and vertical (Space/Ctrl) thrust get the same
#: acceleration as forward, so sidestepping is as immediate as flying at
#: something — in an arcade 6DoF handling model strafe is a primary way to
#: move, not a nudge. Raise above 1.0 to make it snappier still.
DEFAULT_STRAFE_FACTOR = 1.0
DEFAULT_LIFT_FACTOR = 1.0

#: INERTIAL DAMPENING. With no thrust key held the drag coefficient is
#: multiplied by this, so letting go brakes rather than drifts. 1.8 sits in
#: the middle of the 1.5-2x band that stops the ship promptly without the
#: dead, frictional feel of an instant halt — there is still a glide, it is
#: just short enough to aim with.
DEFAULT_BRAKE_FACTOR = 1.8

#: Roll rate at full Q/E deflection, radians per second. Direct, not
#: accelerated: rule 1 of the brief is that aiming has no angular drag, and a
#: roll that keeps turning after the key comes up is exactly that.
DEFAULT_ROLL_RATE = 2.2

#: AUTOMATIC BANKING. Turning rolls the ship into the turn, as every space sim
#: does — it is most of what makes a turn read as a turn rather than as the
#: scenery sliding sideways. The bank is proportional to how far the aiming
#: reticle is deflected, HOLDS while it stays there, and eases back to level
#: when the reticle is brought back to centre (Christian's description
#: exactly). Radians at full deflection.
DEFAULT_BANK_ANGLE = 0.55
#: How quickly the bank chases its target, 1/s. Slower than the turn itself,
#: so the roll visibly follows the turn rather than arriving with it.
DEFAULT_BANK_EASE = 3.2

#: Below this the drift is invisible and should be snapped away, or a fly
#: session never technically ends and the repaint timer never stops. Measured:
#: at 1e-3 the exponential tail keeps the timer alive for ~2.2 s after the
#: button comes up, having travelled a fraction of a milli-Angstrom for most
#: of it. 2e-2 stops in well under a second and gives up 0.004 * scale of
#: coasting distance — far below one pixel.
_REST_SPEED = 2e-2

#: How far short of straight up/down the pitch is allowed to go, in degrees.
PITCH_LIMIT_DEG = 88.0


class FlightModel(object):
    """World-space velocity with thrust, drag and a speed cap.

    One instance per flying thing. `scale` multiplies every speed so that
    flying around a 3 A cell and a 300 A framework both feel the same — the
    caller sets it from the scene size once at take-off.
    """

    def __init__(self, accel=DEFAULT_ACCEL, max_speed=DEFAULT_MAX_SPEED,
                 damping=DEFAULT_DAMPING, scale=1.0,
                 strafe_factor=DEFAULT_STRAFE_FACTOR,
                 lift_factor=DEFAULT_LIFT_FACTOR,
                 brake_factor=DEFAULT_BRAKE_FACTOR,
                 roll_rate=DEFAULT_ROLL_RATE,
                 bank_angle=DEFAULT_BANK_ANGLE,
                 bank_ease=DEFAULT_BANK_EASE):
        self.accel = float(accel)
        self.max_speed = float(max_speed)
        self.damping = float(damping)
        self.scale = max(float(scale), 1e-3)
        self.strafe_factor = float(strafe_factor)
        self.lift_factor = float(lift_factor)
        self.brake_factor = max(float(brake_factor), 1.0)
        self.roll_rate = float(roll_rate)
        self.bank_angle = float(bank_angle)
        self.bank_ease = float(bank_ease)
        self.velocity = np.zeros(3)
        #: Roll about the view axis, radians, split into the two things that
        #: cause it. The camera applies the SUM as a final twist; neither is
        #: ever fed back into the look angles, so roll cannot leak into
        #: yaw/pitch and cannot drift.
        self.manual_roll = 0.0        # Q/E — held until you roll back
        self.bank = 0.0               # automatic, follows the turn

    @property
    def roll(self):
        # type: () -> float
        return self.manual_roll + self.bank

    @roll.setter
    def roll(self, value):
        """Assigning `roll` sets the MANUAL component; the bank is derived and
        cannot meaningfully be written to."""
        self.manual_roll = float(value) - self.bank

    # ------------------------------------------------------------- dynamics
    def thrust_world(self, keys, basis):
        # type: (Tuple[float, float, float], np.ndarray) -> np.ndarray
        """Turn (right, up, forward) key input into a world direction.

        `basis` has the three unit world vectors as ROWS, in that order. The
        result is normalised, so pressing W+D is not 1.41x faster than W —
        the diagonal-speed bug every first flight controller has.
        """
        rows = np.asarray(basis, dtype=float).reshape(3, 3)
        vec = np.asarray(keys, dtype=float).reshape(3) @ rows
        norm = float(np.linalg.norm(vec))
        return vec / norm if norm > 1e-9 else np.zeros(3)

    def accel_for(self, keys):
        # type: (Tuple[float, float, float]) -> float
        """Effective acceleration for a thrust triple.

        A convex blend of the three per-axis accelerations weighted by how
        much of the input is on each axis, so pure A gets the strafe figure,
        pure W the forward one, and W+A the mean. Blending here rather than
        scaling the key vector matters: `thrust_world` normalises, so any
        weighting applied to the components would be divided straight back
        out and the per-axis tuning would silently do nothing.
        """
        k = np.abs(np.asarray(keys, dtype=float).reshape(3))
        total = float(k.sum())
        if total <= 1e-9:
            return self.accel
        factors = np.array([self.strafe_factor, self.lift_factor, 1.0])
        return self.accel * float((k * factors).sum() / total)

    def step(self, dt, keys, basis, boost=1.0):
        # type: (float, Tuple[float, float, float], np.ndarray, float) -> np.ndarray
        """Advance one tick; returns the DISPLACEMENT to apply this tick.

        Trapezoidal in the velocity (the mean of before and after), which is
        what keeps a tap of W from being swallowed at 60 Hz.

        Drag is asymmetric: while a thrust key is held it is `damping`, and
        the moment every key comes up it jumps to `damping * brake_factor`.
        That is the inertial dampening an arcade 6DoF handling model lives on
        — you still coast, but you stop where you meant to instead of sailing
        past it. A single symmetric coefficient cannot do both: low enough to
        build speed against, and high enough to park.
        """
        dt = max(float(dt), 0.0)
        if dt <= 0.0:
            return np.zeros(3)
        boost = max(float(boost), 1e-3)
        before = self.velocity.copy()
        direction = self.thrust_world(keys, basis)
        thrusting = bool(np.any(np.abs(np.asarray(keys, dtype=float)) > 1e-9))
        self.velocity = self.velocity + direction * (
            self.accel_for(keys) * self.scale * boost * dt)
        # Exponential drag: stable at any dt, and never crosses zero.
        drag = self.damping if thrusting else self.damping * self.brake_factor
        self.velocity *= float(np.exp(-drag * dt))
        cap = self.max_speed * self.scale * boost
        speed = float(np.linalg.norm(self.velocity))
        if speed > cap:
            self.velocity *= cap / speed
        elif speed < _REST_SPEED * self.scale and not np.any(direction):
            self.velocity = np.zeros(3)
        return (before + self.velocity) * 0.5 * dt

    def step_roll(self, dt, direction, boost=1.0):
        # type: (float, float, float) -> float
        """Advance the roll angle; `direction` is -1/0/+1 from Q/E.

        Deliberately un-accelerated and un-damped — see `DEFAULT_ROLL_RATE`.
        Returns the new absolute roll.
        """
        dt = max(float(dt), 0.0)
        self.manual_roll += float(direction) * self.roll_rate * dt * max(
            float(boost), 1e-3)
        # Keep it bounded so a long flight cannot grow a float big enough to
        # lose precision in the trig downstream.
        self.manual_roll = float(
            (self.manual_roll + np.pi) % (2.0 * np.pi) - np.pi)
        return self.roll

    def step_bank(self, dt, deflection_x):
        # type: (float, float) -> float
        """Ease the automatic bank toward the turn. Returns the total roll.

        Sign: deflecting the reticle RIGHT (positive x) must drop the right
        wing, and a positive `Camera.fly_look` roll turns the world clockwise
        on screen — which is a LEFT bank. Hence the negation. Getting it
        backwards is not subtle to fly but is very easy to write.
        """
        dt = max(float(dt), 0.0)
        target = -float(deflection_x) * self.bank_angle
        alpha = 1.0 - float(np.exp(-self.bank_ease * dt))
        self.bank += (target - self.bank) * alpha
        return self.roll

    def level(self):
        # type: () -> None
        """Roll back upright. Called on landing, because the orbit camera you
        return to is a turntable with no way to express a rolled pose."""
        self.manual_roll = 0.0
        self.bank = 0.0

    @property
    def moving(self):
        # type: () -> bool
        """Still drifting — the caller keeps ticking until this goes False,
        so releasing the key coasts to a stop instead of freezing mid-glide."""
        return bool(np.linalg.norm(self.velocity) > _REST_SPEED * self.scale)

    def stop(self):
        self.velocity = np.zeros(3)


def key_vector(forward=0.0, right=0.0, up=0.0):
    # type: (float, float, float) -> Tuple[float, float, float]
    """(right, up, forward) in the order `thrust_world` expects."""
    return (float(right), float(up), float(forward))


def keys_from_set(pressed, mapping=None):
    # type: (object, Optional[dict]) -> Tuple[float, float, float]
    """Collapse a set of held keys into one thrust triple.

    `mapping` is {key: (right, up, forward)}; the default is WASD on the
    horizontal pair and Q/E on the vertical, which is what UE5, Unity and
    Blender's own fly mode all use.
    """
    mapping = mapping or {}
    total = np.zeros(3)
    for key in pressed:
        vec = mapping.get(key)
        if vec is not None:
            total += np.asarray(vec, dtype=float)
    return (float(total[0]), float(total[1]), float(total[2]))


#: The aiming reticle: how far off centre it may travel, as a fraction of the
#: viewport's short side, and the dead zone at the middle (also a fraction of
#: that travel) inside which the ship flies straight.
DEFAULT_AIM_SPAN = 0.30
DEFAULT_AIM_DEADZONE = 0.06
#: Turn rate at FULL deflection, radians per second.
DEFAULT_TURN_RATE = 1.9

#: EXPO. The response curve applied to the stick's magnitude: `out = in**expo`
#: on the normalised 0..1 travel. 1.0 is linear; above that the curve is flat
#: near the middle and steepens toward the edge, which buys fine control for
#: small corrections without giving up the full turn rate at full deflection.
#:
#: A power curve is used rather than a scaled zero-shifted softplus. Softplus
#: is smooth and monotone and would work, but its shape is wrong for this job
#: in two ways: its slope at the origin is already HALF the asymptotic slope,
#: so it barely softens the centre where the softening is wanted, and it is
#: asymptotically linear rather than bounded, so it has to be renormalised to
#: make full stick mean full rate. `x**expo` gives f(0)=0 and f(1)=1 exactly,
#: puts all of its flattening where the hand is making small corrections, and
#: has one interpretable parameter. It is also what RC transmitters and every
#: flight sim call "expo", so the number means something to anyone tuning it.
DEFAULT_AIM_EXPO = 2.0


class AimReticle(object):
    """The separated aiming mark — a VIRTUAL JOYSTICK, not a lagging cursor.

    Round 35's first cut made the reticle chase the angular RATE and ease back
    to centre, which is wrong in the way that matters: it meant a turn stopped
    the moment you stopped moving the mouse. Christian's spec is the flight-sim
    one — *"if my mouse points right, the right turn should continue
    indefinitely until I have moved it back to the centre of the screen"*.

    So the offset is **persistent**. Mouse movement drags the reticle around
    (clamped to `span` of the short side); the ship then turns continuously
    toward it at a rate proportional to how far out it sits, and only stops
    when the reticle is brought back to the middle. That makes the mark a
    control input you can read — where it is IS what the ship is doing — and
    it is what the hull/reticle separation is for.

    Nothing here decays on its own. The only things that move it are the
    mouse and an explicit `recentre()`.
    """

    def __init__(self, span=DEFAULT_AIM_SPAN, deadzone=DEFAULT_AIM_DEADZONE,
                 expo=DEFAULT_AIM_EXPO):
        self.span = float(span)
        self.deadzone = float(np.clip(deadzone, 0.0, 0.9))
        self.expo = max(float(expo), 1.0)
        self.offset = np.zeros(2)     # pixels from centre, +x right, +y down

    def limit(self, short_side):
        # type: (float) -> float
        return max(self.span * max(float(short_side), 1.0), 1.0)

    def move(self, dx_px, dy_px, short_side=600.0):
        # type: (float, float, float) -> np.ndarray
        """Drag the reticle by a mouse delta. Clamped to a disc, so a long
        sweep parks it at full deflection instead of running off screen and
        leaving you with no way to know how far back centre is."""
        limit = self.limit(short_side)
        moved = self.offset + np.array([float(dx_px), float(dy_px)])
        mag = float(np.linalg.norm(moved))
        if mag > limit:
            moved *= limit / mag
        self.offset = moved
        return self.offset.copy()

    def deflection(self, short_side=600.0):
        # type: (float) -> np.ndarray
        """Normalised control input in [-1, 1] per axis, dead zone removed
        and `expo` applied.

        The dead zone is rescaled rather than merely clipped, so the response
        is continuous at its edge — a hard step from "straight" to "turning at
        6% rate" is felt as a jolt every time you cross it. The expo curve is
        then applied to the MAGNITUDE, not per axis, so the direction the
        stick points is never bent — only how hard it pulls.
        """
        v = self.offset / self.limit(short_side)
        mag = float(np.linalg.norm(v))
        if mag <= self.deadzone:
            return np.zeros(2)
        travel = (mag - self.deadzone) / (1.0 - self.deadzone)
        if self.expo != 1.0:
            travel = travel ** self.expo
        return v * (travel / mag)

    def recentre(self):
        self.offset = np.zeros(2)

    # Kept so "is the stick centred?" reads the same way at every call site.
    def centred(self, short_side=600.0):
        # type: (float) -> bool
        return not bool(np.any(self.deflection(short_side)))


def clamp_pitch_delta(forward, d_pitch, limit_deg=PITCH_LIMIT_DEG):
    # type: (np.ndarray, float, float) -> float
    """Trim a pitch step so the view stops just short of straight up/down.

    Without this a fast flick takes the camera over the pole, the horizon
    inverts, and the result is indistinguishable from the roll this whole
    camera exists to avoid. Returns the allowed part of `d_pitch` — 0 when
    already pinned and still pushing, the full value otherwise.
    """
    f = np.asarray(forward, dtype=float)
    norm = float(np.linalg.norm(f))
    if norm < 1e-9:
        return 0.0
    # Elevation of the view direction above the XY plane, in radians.
    elevation = float(np.arcsin(np.clip(f[2] / norm, -1.0, 1.0)))
    limit = np.radians(float(limit_deg))
    target = elevation + float(d_pitch)
    if target > limit:
        return max(limit - elevation, 0.0)
    if target < -limit:
        return min(-limit - elevation, 0.0)
    return float(d_pitch)
