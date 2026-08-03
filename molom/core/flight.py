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

**No roll.** Look is yaw about world Z plus pitch about the view X axis, the
same pair the turntable orbit uses, so the horizon can never tilt. Pitch is
CLAMPED just short of vertical: passing straight over the pole would flip the
horizon, and an upside-down horizon is indistinguishable from roll — which is
the thing being avoided. `roll` is deliberately not implemented here; if it is
ever wanted it belongs as an explicit extra term with a one-key reset, not as
an accident of the pitch integration.

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
PRECISION_FACTOR = 0.25     # Ctrl/Alt: creep

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
                 damping=DEFAULT_DAMPING, scale=1.0):
        self.accel = float(accel)
        self.max_speed = float(max_speed)
        self.damping = float(damping)
        self.scale = max(float(scale), 1e-3)
        self.velocity = np.zeros(3)

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

    def step(self, dt, keys, basis, boost=1.0):
        # type: (float, Tuple[float, float, float], np.ndarray, float) -> np.ndarray
        """Advance one tick; returns the DISPLACEMENT to apply this tick.

        Trapezoidal in the velocity (the mean of before and after), which is
        what keeps a tap of W from being swallowed at 60 Hz.
        """
        dt = max(float(dt), 0.0)
        if dt <= 0.0:
            return np.zeros(3)
        boost = max(float(boost), 1e-3)
        before = self.velocity.copy()
        direction = self.thrust_world(keys, basis)
        self.velocity = self.velocity + direction * (
            self.accel * self.scale * boost * dt)
        # Exponential drag: stable at any dt, and never crosses zero.
        self.velocity *= float(np.exp(-self.damping * dt))
        cap = self.max_speed * self.scale * boost
        speed = float(np.linalg.norm(self.velocity))
        if speed > cap:
            self.velocity *= cap / speed
        elif speed < _REST_SPEED * self.scale and not np.any(direction):
            self.velocity = np.zeros(3)
        return (before + self.velocity) * 0.5 * dt

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
