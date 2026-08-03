"""Camera and projection math — pure numpy, no GL, unit-testable.

Column-vector convention: matrices are 4x4 float32, applied as M @ v. Upload
to OpenGL with transpose=GL_TRUE (or .T.tobytes() order='F') since GL expects
column-major storage.
"""

import numpy as np


def perspective(fovy_deg, aspect, near, far):
    # type: (float, float, float, float) -> np.ndarray
    f = 1.0 / np.tan(np.radians(fovy_deg) / 2.0)
    m = np.zeros((4, 4), dtype=np.float32)
    m[0, 0] = f / max(aspect, 1e-6)
    m[1, 1] = f
    m[2, 2] = (far + near) / (near - far)
    m[2, 3] = (2.0 * far * near) / (near - far)
    m[3, 2] = -1.0
    return m


def look_at(eye, center, up):
    # type: (np.ndarray, np.ndarray, np.ndarray) -> np.ndarray
    eye = np.asarray(eye, dtype=float)
    center = np.asarray(center, dtype=float)
    f = center - eye
    f = f / np.linalg.norm(f)
    u = np.asarray(up, dtype=float)
    s = np.cross(f, u)
    s = s / np.linalg.norm(s)
    u = np.cross(s, f)
    m = np.eye(4, dtype=np.float32)
    m[0, :3] = s
    m[1, :3] = u
    m[2, :3] = -f
    m[0, 3] = -np.dot(s, eye)
    m[1, 3] = -np.dot(u, eye)
    m[2, 3] = np.dot(f, eye)
    return m


# ------------------------------------------------------------- quaternions
# q = (w, x, y, z), unit norm.

def quat_identity():
    return np.array([1.0, 0.0, 0.0, 0.0])


def quat_mul(a, b):
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return np.array([
        aw * bw - ax * bx - ay * by - az * bz,
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
    ])


def quat_from_axis_angle(axis, angle_rad):
    axis = np.asarray(axis, dtype=float)
    n = np.linalg.norm(axis)
    if n == 0.0:
        return quat_identity()
    axis = axis / n
    half = angle_rad / 2.0
    return np.concatenate([[np.cos(half)], axis * np.sin(half)])


def quat_normalize(q):
    n = np.linalg.norm(q)
    return quat_identity() if n == 0.0 else q / n


def quat_to_mat3(q):
    w, x, y, z = quat_normalize(q)
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
        [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
        [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
    ])


def quat_from_mat3(m):
    # type: (np.ndarray) -> np.ndarray
    """Rotation matrix -> unit quaternion (Shepperd branch selection)."""
    m = np.asarray(m, dtype=float)
    t = np.trace(m)
    if t > 0:
        s = np.sqrt(t + 1.0) * 2.0
        q = np.array([0.25 * s,
                      (m[2, 1] - m[1, 2]) / s,
                      (m[0, 2] - m[2, 0]) / s,
                      (m[1, 0] - m[0, 1]) / s])
    elif m[0, 0] >= m[1, 1] and m[0, 0] >= m[2, 2]:
        s = np.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2.0
        q = np.array([(m[2, 1] - m[1, 2]) / s, 0.25 * s,
                      (m[0, 1] + m[1, 0]) / s,
                      (m[0, 2] + m[2, 0]) / s])
    elif m[1, 1] >= m[2, 2]:
        s = np.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2.0
        q = np.array([(m[0, 2] - m[2, 0]) / s,
                      (m[0, 1] + m[1, 0]) / s, 0.25 * s,
                      (m[1, 2] + m[2, 1]) / s])
    else:
        s = np.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2.0
        q = np.array([(m[1, 0] - m[0, 1]) / s,
                      (m[0, 2] + m[2, 0]) / s,
                      (m[1, 2] + m[2, 1]) / s, 0.25 * s])
    return quat_normalize(q)


def orthographic(half_h, aspect, near, far):
    # type: (float, float, float, float) -> np.ndarray
    """Symmetric orthographic projection with the given half-height."""
    half_w = half_h * max(aspect, 1e-6)
    m = np.eye(4, dtype=np.float32)
    m[0, 0] = 1.0 / half_w
    m[1, 1] = 1.0 / half_h
    m[2, 2] = -2.0 / (far - near)
    m[2, 3] = -(far + near) / (far - near)
    return m


class Camera:
    """Orbit camera: a rotation (quaternion) about a `center`, at `distance`.

    view = T(0,0,-distance) @ R(q) @ T(-center). Projection is perspective by
    default; `orthographic=True` switches to an ortho frustum with the SAME
    apparent size at the center plane (so toggling doesn't jump). All the
    viewport does is feed it mouse deltas.

    CAMERA orbit is a Blender-style TURNTABLE: horizontal drag yaws about the
    WORLD Z axis, vertical drag pitches about the view X axis — roll can never
    accumulate, so the horizon stays level (Christian's vertigo fix; the
    invariant `(R @ e_z).x == 0` is pinned by a test). Angles are strictly
    proportional to pixels (constant rate; the old Shoemake arcball
    accelerated towards the edges). `trackball_quat` remains for MODEL
    rotation (tumbling a molecule about an anchor atom, where the camera —
    and thus the horizon — does not move at all).

    Axis-aligned views (compass clicks, F3 "view along X") switch to
    orthographic automatically and pop back to perspective on the next
    turntable orbit, exactly like Blender (`auto_ortho` tracks this).
    """

    FOV_Y = 40.0            # degrees, Avogadro-ish
    PX_PER_REV = 600.0      # drag distance for a full turn at speed 1.0

    def __init__(self):
        self.center = np.zeros(3)
        self.distance = 10.0
        self.rotation = self.default_orientation()
        self.orthographic = False
        self.auto_ortho = False     # ortho came from an axis-view snap
        self.rotate_speed = 1.0

    @staticmethod
    def default_orientation():
        # type: () -> np.ndarray
        """Blender-like startup view: world Z up on screen, looking down at
        the XY floor grid from a 3/4 angle (azimuth 45, elevation ~25)."""
        qz = quat_from_axis_angle([0.0, 0.0, 1.0], np.radians(45.0))
        qx = quat_from_axis_angle([1.0, 0.0, 0.0], np.radians(-65.0))
        return quat_normalize(quat_mul(qx, qz))

    # ------------------------------------------------------------ matrices
    def view_matrix(self):
        # type: () -> np.ndarray
        m = np.eye(4, dtype=np.float32)
        m[:3, :3] = quat_to_mat3(self.rotation)
        m[:3, 3] = -m[:3, :3] @ self.center
        t = np.eye(4, dtype=np.float32)
        t[2, 3] = -self.distance
        return (t @ m).astype(np.float32)

    def projection_matrix(self, w, h):
        # type: (int, int) -> np.ndarray
        aspect = w / max(h, 1)
        near = max(self.distance * 0.01, 0.01)
        far = self.distance * 20.0 + 100.0
        if self.orthographic:
            half_h = np.tan(np.radians(self.FOV_Y) / 2.0) * self.distance
            # Ortho has no depth-driven clip pressure; pull near back so
            # geometry behind the pivot plane isn't clipped when zoomed in.
            return orthographic(half_h, aspect, -far, far)
        return perspective(self.FOV_Y, aspect, near, far)

    # ------------------------------------------------------------- control
    def trackball_quat(self, dx_px, dy_px):
        # type: (float, float) -> np.ndarray
        """View-space rotation for a pixel drag (constant rate everywhere)."""
        dist = np.hypot(dx_px, dy_px)
        if dist <= 0.0:
            return quat_identity()
        angle = self.rotate_speed * 2.0 * np.pi * dist / self.PX_PER_REV
        # Axis perpendicular to the drag direction, in view space (y up).
        axis = np.array([dy_px, dx_px, 0.0]) / dist
        return quat_from_axis_angle(axis, angle)

    def rotate(self, dx_px, dy_px, pivot=None):
        """Turntable-orbit by a pixel delta about `pivot` (world coords;
        default = self.center): yaw about world Z, pitch about view X."""
        rate = self.rotate_speed * 2.0 * np.pi / self.PX_PER_REV
        # Sign convention: dragging the scene right/down spins it that way
        # (same feel as the round-2 trackball); flip here if it feels wrong.
        q_yaw = quat_from_axis_angle([0.0, 0.0, 1.0], dx_px * rate)
        q_pitch = quat_from_axis_angle([1.0, 0.0, 0.0], dy_px * rate)
        r_old = quat_to_mat3(self.rotation)
        # R' = pitch(view-space, left) o R o yaw(world-space, right)
        self.rotation = quat_normalize(
            quat_mul(q_pitch, quat_mul(self.rotation, q_yaw)))
        self._reposition_center(r_old, pivot)
        if self.auto_ortho:            # Blender: orbiting an axis view
            self.orthographic = False  # pops back to perspective
            self.auto_ortho = False

    def align_view(self, axis, sign=1):
        # type: (int, int) -> None
        """Snap to look along a world axis (compass click / F3 view ops).

        `axis` 0/1/2 with `sign` +1 = view FROM the positive end (the clicked
        compass ball comes to face the viewer). Up is world +Z, except for the
        two Z views where it is +Y (Blender's top/bottom convention). Switches
        to orthographic; the next orbit pops back (see `rotate`)."""
        d = np.zeros(3)
        d[axis] = -float(sign)                       # look direction
        up = np.array([0.0, 1.0, 0.0]) if axis == 2 \
            else np.array([0.0, 0.0, 1.0])
        right = np.cross(d, up)
        right /= np.linalg.norm(right)
        true_up = np.cross(right, d)
        m = np.vstack([right, true_up, -d])          # rows: view basis
        self.rotation = quat_from_mat3(m)
        self.orthographic = True
        self.auto_ortho = True

    def orbit(self, dq_view, pivot=None):
        """Apply a view-space rotation about an arbitrary world-space pivot,
        keeping the pivot's SCREEN position invariant: with R' = dq (x) R,
        solve R'(P - C') = R(P - C) for the new center. When pivot == center
        this reduces to the classic in-place orbit."""
        r_old = quat_to_mat3(self.rotation)
        self.rotation = quat_normalize(quat_mul(dq_view, self.rotation))
        self._reposition_center(r_old, pivot)

    def _reposition_center(self, r_old, pivot):
        if pivot is None:
            return
        p = np.asarray(pivot, dtype=float)
        r_new = quat_to_mat3(self.rotation)
        self.center = p - r_new.T @ (r_old @ (p - self.center))

    def pan(self, dx_px, dy_px, w, h):
        """Shift the orbit center by a pixel delta (screen-parallel)."""
        # World-units per pixel at the center plane.
        half_h = np.tan(np.radians(self.FOV_Y) / 2.0) * self.distance
        per_px = 2.0 * half_h / max(h, 1)
        r = quat_to_mat3(self.rotation)
        right = r.T @ np.array([1.0, 0.0, 0.0])
        up = r.T @ np.array([0.0, 1.0, 0.0])
        self.center = self.center - right * dx_px * per_px + up * dy_px * per_px

    MIN_DISTANCE = 0.5
    MAX_DISTANCE = 5000.0

    def zoom(self, steps):
        """Dolly in/out; steps > 0 zooms in. Exponential so it feels uniform.
        Drives the ortho half-height too, so zoom works in both projections.

        Zooming in past the floor **carries the orbit centre forward** rather
        than stopping dead. Without that, zoom silently dies whenever the
        orbit centre has drifted away from what you are looking at — and it
        drifts on every pan and every anchored orbit, both of which move it
        by design. Measured: twelve ordinary pans put the centre 22 A from
        the molecule, after which the camera sat at the 0.5 A floor with
        nothing anywhere near it. That is the "max zoom knocked off course,
        and I am definitely not too close" report, and why F (which re-fits
        the centre) cured it. Blender behaves the same way — you can always
        keep travelling toward what is in front of you.
        """
        target = self.distance * (0.88 ** steps)
        if target < self.MIN_DISTANCE:
            shortfall = self.MIN_DISTANCE - target
            forward = quat_to_mat3(self.rotation).T @ np.array([0.0, 0.0, -1.0])
            self.center = self.center + forward * shortfall
            target = self.MIN_DISTANCE
        self.distance = float(np.clip(target, self.MIN_DISTANCE,
                                      self.MAX_DISTANCE))

    def fit(self, center, bounding_radius):
        """Frame a sphere (molecule centroid + bounding radius)."""
        self.center = np.asarray(center, dtype=float).copy()
        r = max(float(bounding_radius), 0.5)
        self.distance = r / np.tan(np.radians(self.FOV_Y) / 2.0) * 1.15
