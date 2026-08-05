"""Grab (G) and Rotate (R) modal math: constraint solving for interactive
transforms, Blender semantics throughout.

- axis keys cycle GLOBAL -> LOCAL (object frame) -> off, like Blender's
  X, XX, XXX; plane locks (Shift+axis) cycle the same way
- Shift while dragging = precision mode (increments scaled by a settable
  factor, no jump when toggled mid-drag)
- typed numbers: exact Angstrom along the locked axis (G) or degrees (R)

Pure functions/state over rays and screen positions so the modal UI logic is
trivially testable. `frame` is a 3x3 whose COLUMNS are the object's local
axes in world coordinates (identity = world)."""

from typing import Optional, Tuple

import numpy as np

from .rotations import axis_angle_mat3

AXES = {
    0: np.array([1.0, 0.0, 0.0]),
    1: np.array([0.0, 1.0, 0.0]),
    2: np.array([0.0, 0.0, 1.0]),
}
AXIS_NAMES = {0: "X", 1: "Y", 2: "Z"}


#: Smallest |sin| of the angle between a ray and the plane it is being
#: intersected with (equivalently |cos| against the normal) that still counts
#: as a usable hit. 0.15 is about 8.5 degrees, which caps the lever at ~7x:
#: past that the intersection runs away toward infinity and then FLIPS SIGN
#: as the ray crosses parallel, which reads as the selection suddenly
#: reversing and accelerating away (Christian, 2026-08-03). Looking nearly
#: along a drag plane genuinely gives the cursor almost no information about
#: position in it, so refusing is more honest than amplifying the noise.
_GRAZE = 0.15


def ray_plane(origin, direction, p0, normal):
    # type: (np.ndarray, np.ndarray, np.ndarray, np.ndarray) -> Optional[np.ndarray]
    """Intersection of ray with the plane through p0 with `normal`.

    None when the ray only GRAZES the plane, or when the plane is behind the
    camera. Both are the same failure seen from different sides: as the
    cursor rises past the plane's horizon the intersection shoots off to
    infinity, crosses over, and comes back on the far side, so a grab that
    was tracking the mouse suddenly bolts the other way. Returning None makes
    the caller hold its last good value, which is what a modal should do when
    the pointer stops meaning anything.
    """
    origin = np.asarray(origin, float)
    direction = np.asarray(direction, float)
    p0 = np.asarray(p0, float)
    normal = np.asarray(normal, float)
    dn = float(np.linalg.norm(direction)) * float(np.linalg.norm(normal))
    if dn < 1e-12:
        return None
    denom = float(np.dot(direction, normal))
    if abs(denom) / dn < _GRAZE:
        return None
    t = float(np.dot(p0 - origin, normal)) / denom
    if t <= 0.0:
        return None                  # the plane is behind us; the hit is not
    return origin + t * direction


def ray_line_t(origin, direction, p0, axis):
    # type: (np.ndarray, np.ndarray, np.ndarray, np.ndarray) -> Optional[float]
    """Parameter t of the closest point `p0 + t*axis` to the given ray.

    Standard two-line closest-approach. None when the ray is nearly parallel
    to the axis: the closest point then slides enormous distances for a pixel
    of mouse movement, which is the axis-locked version of the runaway in
    `ray_plane`. Looking down an axis you are dragging along genuinely gives
    the cursor no information, so holding still is the honest answer.
    """
    origin = np.asarray(origin, float)
    d = np.asarray(direction, float)
    p0 = np.asarray(p0, float)
    e = np.asarray(axis, float)
    w0 = p0 - origin
    a = float(np.dot(d, d))
    b = float(np.dot(d, e))
    c = float(np.dot(e, e))
    if a < 1e-12 or c < 1e-12:
        return None
    # sin^2 of the angle between the ray and the axis
    denom = a * c - b * b
    if denom / (a * c) < _GRAZE * _GRAZE:
        return None
    return float((float(np.dot(w0, d)) * b - float(np.dot(w0, e)) * a) / denom)


def axis_screen_drag(axis_world, view_rot3, dx_px, dy_px):
    # type: (np.ndarray, np.ndarray, float, float) -> float
    """Signed 'pixels of rotation' for dragging (dx, dy) to spin about a world
    axis seen through `view_rot3` (the camera's rotation matrix).

    Dragging perpendicular to the axis's screen projection turns it; when the
    axis points at/away from the viewer there is no perpendicular, so a
    horizontal drag spins it instead. This is what makes an axis-locked
    anchored tumble behave sanely in an axis-aligned orthographic view, where
    a free tumble looks like it flips at random.
    """
    e = np.asarray(view_rot3, float) @ np.asarray(axis_world, float)
    exy = np.array([e[0], e[1]])
    n = float(np.linalg.norm(exy))
    drag = np.array([float(dx_px), -float(dy_px)])   # screen y is down
    if n < 1e-6:
        return -drag[0] * (1.0 if e[2] >= 0.0 else -1.0)
    t = np.array([-exy[1], exy[0]]) / n
    return float(np.dot(drag, t))


class _NumericEntry:
    """The type-a-number half of a modal: buffer, precision flag, parsing.

    Split out of `_ConstraintMixin` so the internal-coordinate modal
    (`ScalarState`) can reuse it. That modal has no axis or plane to lock —
    a bond length has exactly one degree of freedom — but "drag roughly, then
    type 1.54 and press Enter" is the whole reason to have a modal at all, and
    that part is identical.
    """

    def _init_numeric(self):
        self.precision = False
        self.precision_factor = 0.5
        self.number = ""

    def type_char(self, ch):
        # type: (str) -> bool
        if ch in "0123456789":
            self.number += ch
            return True
        if ch == "." and "." not in self.number:
            self.number += ch
            return True
        if ch == "-":
            self.number = self.number[1:] if self.number.startswith("-") \
                else "-" + self.number
            return True
        return False

    def backspace(self):
        self.number = self.number[:-1]

    def numeric_value(self):
        # type: () -> Optional[float]
        t = self.number
        if t in ("", "-", ".", "-."):
            return None
        try:
            return float(t)
        except ValueError:
            return None

    def set_precision(self, on):
        # type: (bool) -> None
        self.precision = bool(on)


class ScalarState(_NumericEntry):
    """One-number modal: drag left/right to change it, or type it exactly.

    Backs the internal-coordinate edits (bond length, angle, dihedral). Those
    have a single degree of freedom, so the axis/plane machinery of G and R
    would be noise — but everything else about the interaction is the same
    contract the user already knows: move to preview, type digits to be exact,
    Shift to creep, click or Enter to confirm, right-click or Esc to cancel.

    Horizontal drag only. A number has one dimension and the pointer has two,
    so binding both would make the value depend on a wobble the user did not
    intend; picking the axis that matches the mental image of "wider apart"
    is what makes a bond stretch feel direct.
    """

    def __init__(self, start, sensitivity, minimum=None, maximum=None,
                 unit="", label=""):
        # type: (float, float, Optional[float], Optional[float], str, str) -> None
        self._init_numeric()
        self.precision_factor = 0.1
        self.start = float(start)
        self.sensitivity = float(sensitivity)
        self.minimum = minimum
        self.maximum = maximum
        self.unit = unit
        self.label = label
        #: Show "(was X)" alongside the value. True for a coordinate being
        #: SET; false for a relative one (the twist), where the start is 0 by
        #: construction and reporting it is noise.
        self.show_start = True
        self._accum = 0.0
        self._ref = None            # type: Optional[float]

    def update_mouse(self, x_px):
        # type: (float) -> None
        """Accumulate a horizontal drag.

        The value is integrated from per-event DELTAS rather than measured
        from the press position, which is what lets Shift change the rate
        mid-drag without the number jumping, and lets `reseed` handle cursor
        wrapping by simply forgetting where the pointer was.
        """
        x = float(x_px)
        if self._ref is None:
            self._ref = x
            return
        rate = self.sensitivity * (self.precision_factor if self.precision
                                   else 1.0)
        self._accum += (x - self._ref) * rate
        self._ref = x

    def reseed(self):
        """Pointer teleported (edge wrap): re-anchor without accumulating."""
        self._ref = None

    def add_delta(self, amount):
        # type: (float) -> None
        """Nudge by an absolute amount — the scroll wheel's route in."""
        self._accum += float(amount)

    def value(self):
        # type: () -> float
        typed = self.numeric_value()
        v = float(typed) if typed is not None else self.start + self._accum
        if self.minimum is not None:
            v = max(v, self.minimum)
        if self.maximum is not None:
            v = min(v, self.maximum)
        return v

    def status_text(self):
        # type: () -> str
        if self.number:
            body = "{} [{}] {}".format(self.label, self.number, self.unit)
        else:
            body = "{} {:.3f} {}".format(self.label, self.value(), self.unit)
        was = "  (was {:.3f})".format(self.start) if self.show_start else ""
        return body.strip() + was


class _ConstraintMixin(_NumericEntry):
    """Shared axis/plane lock cycling + numeric buffer for G and R."""

    def _init_constraints(self, frame):
        self.frame = (np.eye(3) if frame is None
                      else np.asarray(frame, dtype=float))
        self.axis = None            # type: Optional[int]
        self.axis_local = False
        self.plane_excl = None      # type: Optional[int]
        self.plane_local = False
        self._init_numeric()
        self.precision_factor = 0.5

    # --------------------------------------------------------------- cycling
    def set_axis(self, axis):
        # type: (int) -> None
        """Blender cycle: X -> global lock, X again -> local, again -> off."""
        if self.axis != axis:
            self.axis, self.axis_local = axis, False
        elif not self.axis_local and self._has_local_frame():
            self.axis_local = True
        else:
            self.axis, self.axis_local = None, False
        self.plane_excl, self.plane_local = None, False
        self._reset_reference()

    def set_plane(self, excluded_axis):
        # type: (int) -> None
        if self.plane_excl != excluded_axis:
            self.plane_excl, self.plane_local = excluded_axis, False
        elif not self.plane_local and self._has_local_frame():
            self.plane_local = True
        else:
            self.plane_excl, self.plane_local = None, False
        self.axis, self.axis_local = None, False
        self._reset_reference()

    def _has_local_frame(self):
        return not np.allclose(self.frame, np.eye(3))

    def axis_vector(self):
        # type: () -> Optional[np.ndarray]
        if self.axis is None:
            return None
        return (self.frame[:, self.axis] if self.axis_local
                else AXES[self.axis])

    def plane_normal(self):
        # type: () -> Optional[np.ndarray]
        if self.plane_excl is None:
            return None
        return (self.frame[:, self.plane_excl] if self.plane_local
                else AXES[self.plane_excl])

    def constraint_label(self):
        # type: () -> str
        scope = lambda local: " (local)" if local else ""
        if self.axis is not None:
            return "along {}{}".format(AXIS_NAMES[self.axis],
                                       scope(self.axis_local))
        if self.plane_excl is not None:
            keep = [AXIS_NAMES[i] for i in (0, 1, 2) if i != self.plane_excl]
            return "in {}{} plane{}".format(keep[0], keep[1],
                                            scope(self.plane_local))
        return self._free_label()

    # --------------------------------------------------------------- numeric
    # (type_char / backspace / numeric_value / set_precision come from
    # _NumericEntry, shared with ScalarState.)

    def reseed(self):
        """Tell the next `update_mouse` to re-anchor WITHOUT accumulating.

        Used when the pointer is teleported (edge wrapping for infinite
        drags): the jump must move the reference, not the value, or the
        object leaps across the screen and further dragging cancels out."""
        self._skip_accum = True

    def _consume_reseed(self, raw, store):
        # type: (object, str) -> bool
        if getattr(self, "_skip_accum", False):
            self._skip_accum = False
            setattr(self, store, raw)
            return True
        return False


class GrabState(_ConstraintMixin):
    """One in-progress move. The caller snapshots coordinates on start and
    applies `delta()` to the snapshot each update (never cumulatively).

    Precision (Shift) scales mouse INCREMENTS, so toggling mid-drag never
    jumps: the accumulated delta just grows slower from that moment on."""

    def __init__(self, pivot, view_dir, frame=None):
        # type: (np.ndarray, np.ndarray, Optional[np.ndarray]) -> None
        self.pivot = np.asarray(pivot, dtype=float)
        self.view_dir = np.asarray(view_dir, dtype=float)
        self._init_constraints(frame)
        self._accum = np.zeros(3)
        self._last_raw = None       # type: Optional[np.ndarray]
        self._start_point = None
        self._start_t = None

    def _free_label(self):
        return "free (view plane)"

    def _reset_reference(self):
        self._accum = np.zeros(3)
        self._last_raw = None
        self._start_point = None
        self._start_t = None

    def update_mouse(self, ray_origin, ray_dir):
        # type: (np.ndarray, np.ndarray) -> None
        e = self.axis_vector()
        if e is not None:
            t = ray_line_t(ray_origin, ray_dir, self.pivot, e)
            if t is None:
                return              # grazing: hold, do not bolt
            if self._start_t is None:
                self._start_t = t
            raw = e * (t - self._start_t)
        else:
            n = self.plane_normal()
            if n is None:
                n = self.view_dir
            hit = ray_plane(ray_origin, ray_dir, self.pivot, n)
            if hit is None:
                return
            if self._start_point is None:
                self._start_point = hit
            raw = hit - self._start_point
        if self._last_raw is None:
            self._last_raw = np.zeros(3)
        if self._consume_reseed(raw, "_last_raw"):
            return
        inc = raw - self._last_raw
        self._last_raw = raw
        self._accum = self._accum + inc * (self.precision_factor
                                           if self.precision else 1.0)

    def delta(self):
        # type: () -> np.ndarray
        v = self.numeric_value()
        e = self.axis_vector()
        if v is not None and e is not None:
            return e * v
        return self._accum.copy()

    def status_text(self):
        # type: () -> str
        d = self.delta()
        txt = "Move {}  d = ({:+.3f}, {:+.3f}, {:+.3f}) A".format(
            self.constraint_label(), d[0], d[1], d[2])
        if self.number:
            txt += "   typed: {} A".format(self.number)
        elif self.axis is None and self.plane_excl is None:
            txt += "   [X/Y/Z axis (2x = local), Shift+X/Y/Z plane, " \
                   "Shift = precise, type = exact A]"
        if self.precision:
            txt += "   [precise]"
        return txt


class RotateState(_ConstraintMixin):
    """One in-progress rotation (Blender R). The mouse angle is measured
    around the pivot's SCREEN position; the world rotation axis is the view
    direction by default or a locked global/local axis. The screen sense is
    corrected so the selection always follows the cursor. Typed numbers are
    degrees, right-handed about the (unflipped) axis — Blender semantics."""

    def __init__(self, pivot, view_dir, frame=None):
        # type: (np.ndarray, np.ndarray, Optional[np.ndarray]) -> None
        self.pivot = np.asarray(pivot, dtype=float)
        self.view_dir = np.asarray(view_dir, dtype=float)
        self._init_constraints(frame)
        self._accum_angle = 0.0
        self._last_raw = None       # type: Optional[float]

    def _free_label(self):
        return "about view axis"

    def _reset_reference(self):
        self._accum_angle = 0.0
        self._last_raw = None

    # plane locks make no sense for rotation: Shift+axis just locks the axis
    def set_plane(self, excluded_axis):
        self.set_axis(excluded_axis)

    def effective_axis(self):
        # type: () -> np.ndarray
        e = self.axis_vector()
        if e is None:
            # rotate about the axis pointing AT the viewer (screen normal)
            e = -self.view_dir
        n = np.linalg.norm(e)
        return e / n if n else np.array([0.0, 0.0, 1.0])

    def update_mouse(self, mouse_xy, pivot_screen_xy):
        # type: (Tuple[float, float], Tuple[float, float]) -> None
        dx = mouse_xy[0] - pivot_screen_xy[0]
        dy = mouse_xy[1] - pivot_screen_xy[1]
        if abs(dx) < 1e-9 and abs(dy) < 1e-9:
            return
        raw = np.arctan2(dy, dx)
        if self._last_raw is None:
            self._last_raw = raw
        if self._consume_reseed(raw, "_last_raw"):
            return
        d = raw - self._last_raw
        d = (d + np.pi) % (2.0 * np.pi) - np.pi     # unwrap
        self._last_raw = raw
        self._accum_angle += d * (self.precision_factor
                                  if self.precision else 1.0)

    def add_angle(self, delta_rad):
        # type: (float) -> None
        """Direct angle increment — the laptop path: two-finger scroll while
        the R modal is active. Pre-divides by the view-sense factor so the
        FINAL angle (after `angle()` applies it) moves by exactly
        `delta_rad * precision`, keeping scroll direction view-independent."""
        self._accum_angle += (delta_rad
                              * (self.precision_factor if self.precision
                                 else 1.0)) * self._sense()

    def _sense(self):
        # type: () -> float
        toward_viewer = -float(np.dot(self.effective_axis(), self.view_dir))
        return -1.0 if toward_viewer >= 0.0 else 1.0

    def angle(self):
        # type: () -> float
        """Signed world rotation angle (radians) about effective_axis()."""
        v = self.numeric_value()
        if v is not None:
            return float(np.radians(v))
        # Screen y is DOWN, so atan2 grows with visually-CLOCKWISE cursor
        # motion. Visual clockwise = negative right-hand angle about an axis
        # pointing AT the viewer (and positive about one pointing away), so
        # flip the sense per axis orientation to keep the selection glued to
        # the cursor.
        return float(self._accum_angle * self._sense())

    def rotation_matrix(self):
        # type: () -> np.ndarray
        return axis_angle_mat3(self.effective_axis(), self.angle())

    def status_text(self):
        # type: () -> str
        txt = "Rotate {}  angle = {:+.2f} deg".format(
            self.constraint_label(), np.degrees(self.angle()))
        if self.number:
            txt += "   typed: {} deg".format(self.number)
        elif self.axis is None:
            txt += "   [X/Y/Z axis (2x = local), Shift = precise, " \
                   "type = degrees]"
        if self.precision:
            txt += "   [precise]"
        return txt
