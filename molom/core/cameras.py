"""Camera OBJECTS — saved viewpoints, the way Blender has them.

Christian, 2026-08-09: "a savefile can retain previously used angles." The
orbit camera in `core/camera.py` is the one you fly around with and there is
exactly one of it; a `CameraObject` is a *remembered* one — a pose plus the
lens and film settings a render needs — that lives in the scene, appears in
the outliner and rides savepoints and undo like any other object.

Three things are worth being precise about.

**Focal length is in MILLIMETRES against a SENSOR SIZE, not in Angstrom.**
Angstrom is the scene's unit; a focal length only means anything relative to
the film it projects onto, and the pair (50 mm, 36 mm sensor) is a number
every photographer and every Blender user can already picture. Expressed in
Angstrom it would be a number with no reference. The conversion to the vertical
field of view MoloM's projection actually wants is one `arctan`, and it is here
rather than in the viewport so both the screen and the Blender export ask the
same function.

**Roll is a real parameter.** The interactive camera is a TURNTABLE and cannot
represent a rolled pose (round 3 — that is the whole no-roll fix), so a saved
camera has to carry roll explicitly rather than hoping the orbit rig can hold
it. Activating a camera therefore restores yaw/pitch through the turntable and
applies roll on top, exactly as `Camera.fly_look` does.

**Resolution is pixels PLUS a multiplier.** 512x512 at 2x is a different
statement from 1024x1024: the first says "this framing, rendered finer", which
is what a resolution multiplier is for, and it survives someone later deciding
the figure should be 4x.

UI-free: numpy + stdlib.
"""

import numpy as np

from . import camera as camera_mod

#: Blender's default 36 mm horizontal sensor, so a focal length here means
#: what it means there and in a camera shop.
DEFAULT_SENSOR_MM = 36.0
DEFAULT_FOCAL_MM = 50.0
DEFAULT_WIDTH = 1920
DEFAULT_HEIGHT = 1080

PERSPECTIVE = "perspective"
ORTHOGRAPHIC = "orthographic"
PROJECTIONS = (PERSPECTIVE, ORTHOGRAPHIC)

#: How large the film back is DRAWN, as a fraction of the largest rectangle of
#: its aspect that fits the viewport. Purely a viewing property — it changes
#: nothing about the render, only how much of the scene around the shot you
#: can see while composing it, which is Blender's camera-view zoom.
#: Capped at the fit: a frame larger than the window puts its own drag handles
#: off screen, which is a state with no way out of it.
MIN_FRAME_ZOOM = 0.12
MAX_FRAME_ZOOM = 1.0


def fov_y_degrees(focal_mm, sensor_mm=DEFAULT_SENSOR_MM, aspect=None):
    """Vertical field of view for a lens on a sensor.

    `sensor_mm` is the HORIZONTAL sensor size (Blender's default fit), so the
    vertical one is scaled by the aspect ratio — otherwise a 16:9 camera and a
    square one with the same lens would frame the same height, which is not
    how a camera works.
    """
    focal = max(float(focal_mm), 1e-6)
    sensor = max(float(sensor_mm), 1e-6)
    if aspect and float(aspect) > 0:
        sensor = sensor / float(aspect)
    return float(np.degrees(2.0 * np.arctan(0.5 * sensor / focal)))


def twist_rotation(rotation, roll):
    """`rotation` twisted about the VIEW axis by `roll` radians.

    The stored pose of a camera is a turntable one and therefore level; roll
    sits on top of it. Built exactly as `Camera.fly_look` builds its own —
    `right, up -> right c + up s, up c - right s`, which is the pre-multiplied
    view-space delta `Camera.orbit` already uses — so the two conventions
    cannot drift apart. Pass `-roll` to take a roll back off.
    """
    q = np.asarray(rotation, dtype=float)
    if not roll:
        return q.copy()
    c, s = np.cos(float(roll)), np.sin(float(roll))
    twist = np.array([[c, s, 0.0], [-s, c, 0.0], [0.0, 0.0, 1.0]])
    return camera_mod.quat_normalize(
        camera_mod.quat_mul(camera_mod.quat_from_mat3(twist), q))


def focal_from_fov(fov_deg, sensor_mm=DEFAULT_SENSOR_MM, aspect=None):
    """The inverse, for "place a camera here" — the interactive view has a
    field of view and no lens, so one has to be derived from it."""
    sensor = max(float(sensor_mm), 1e-6)
    if aspect and float(aspect) > 0:
        sensor = sensor / float(aspect)
    half = np.radians(max(min(float(fov_deg), 179.0), 0.1)) / 2.0
    return float(0.5 * sensor / np.tan(half))


class CameraObject(object):
    """One saved viewpoint: where it is, where it looks, and what it renders.

    The pose is stored the same way the interactive camera holds one — a
    pivot, a distance and an orientation quaternion — rather than as an
    eye/target pair, so activating a camera is an assignment and orbiting
    away from it behaves exactly as orbiting always does.
    """

    kind = "camera"

    def __init__(self, cam_id, name="Camera"):
        self.id = int(cam_id)
        self.name = name
        self.visible = True             # drawn in the viewport as a frustum
        self.center = np.zeros(3)
        self.distance = 10.0
        self.rotation = camera_mod.Camera.default_orientation()
        #: Radians, applied AFTER the yaw/pitch pair — see the module note.
        self.roll = 0.0
        self.projection = PERSPECTIVE
        self.focal_mm = DEFAULT_FOCAL_MM
        self.sensor_mm = DEFAULT_SENSOR_MM
        self.width = DEFAULT_WIDTH
        self.height = DEFAULT_HEIGHT
        self.multiplier = 1.0
        #: Viewport-only: how big the film back is drawn. See MIN_FRAME_ZOOM.
        self.frame_zoom = 1.0

    # ----------------------------------------------------------- geometry
    @property
    def aspect(self):
        return float(self.width) / max(float(self.height), 1.0)

    @property
    def fov_y(self):
        """Vertical field of view in degrees — what the projection wants."""
        return fov_y_degrees(self.focal_mm, self.sensor_mm, self.aspect)

    @property
    def orthographic(self):
        return self.projection == ORTHOGRAPHIC

    def render_size(self):
        """(width, height) in pixels after the multiplier, both at least 1."""
        m = max(float(self.multiplier), 0.01)
        return (max(int(round(self.width * m)), 1),
                max(int(round(self.height * m)), 1))

    def eye(self):
        """Where the camera sits in world space."""
        rot = camera_mod.quat_to_mat3(self.rotation)
        return np.asarray(self.center, dtype=float) + rot.T @ np.array(
            [0.0, 0.0, float(self.distance)])

    def rolled_rotation(self):
        """The view rotation INCLUDING this camera's roll — what the viewport
        has to be given so that looking through a rolled camera is actually
        tilted, rather than showing a level view of a shot that is not."""
        return twist_rotation(self.rotation, self.roll)

    # -------------------------------------------------------- interchange
    def apply_to(self, camera):
        """Put the interactive camera into this pose AND this lens."""
        camera.center = np.asarray(self.center, dtype=float).copy()
        camera.distance = float(self.distance)
        camera.rotation = self.rolled_rotation()
        self.apply_lens_to(camera)
        return camera

    def apply_lens_to(self, camera):
        """Only the things that change how the scene is PROJECTED.

        Separate from the pose because editing a camera while looking through
        it must not teleport the view: round 57, Christian — "clicking on one
        of the scaling knobs of the camera view also resets a previous dolly."
        It did, because every edit re-applied the whole thing, pose included,
        and a dolly is exactly a change to the pose.
        """
        camera.orthographic = self.orthographic
        camera.auto_ortho = False
        # The turntable cannot hold a rolled pose, so a rolled camera must
        # not be levelled by the next orbit without the user asking (round
        # 35c's `auto_level` is for axis views, which are a different case).
        camera.auto_level = False
        return camera

    def capture(self, camera, width=None, height=None, roll=0.0):
        """Take this camera's pose FROM the interactive one — "place a camera
        here". The lens is derived from the viewport's field of view so the
        saved camera frames what the user is looking at, not something wider.

        `roll` is whatever twist the view being captured already carries: it
        is TAKEN BACK OFF the stored rotation and kept as `self.roll`, because
        the two are added together again by `rolled_rotation` and a pose
        captured from a rolled view would otherwise come back rolled twice.
        """
        self.center = np.asarray(camera.center, dtype=float).copy()
        self.distance = float(camera.distance)
        self.roll = float(roll)
        self.rotation = twist_rotation(camera.rotation, -float(roll))
        self.projection = (ORTHOGRAPHIC if camera.orthographic
                           else PERSPECTIVE)
        if width and height:
            self.width, self.height = int(width), int(height)
        self.focal_mm = focal_from_fov(
            float(getattr(camera, "FOV_Y", 40.0)), self.sensor_mm, self.aspect)
        return self

    # ------------------------------------------------------- persistence
    def to_dict(self):
        return {
            "id": int(self.id), "name": str(self.name),
            "visible": bool(self.visible),
            "center": [float(v) for v in self.center],
            "distance": float(self.distance),
            "rotation": [float(v) for v in self.rotation],
            "roll": float(self.roll), "projection": str(self.projection),
            "focal_mm": float(self.focal_mm),
            "sensor_mm": float(self.sensor_mm),
            "width": int(self.width), "height": int(self.height),
            "multiplier": float(self.multiplier),
            "frame_zoom": float(self.frame_zoom),
        }

    @classmethod
    def from_dict(cls, d):
        cam = cls(int(d.get("id", 1)), str(d.get("name", "Camera")))
        cam.visible = bool(d.get("visible", True))
        cam.center = np.asarray(d.get("center", [0, 0, 0]), dtype=float)
        cam.distance = float(d.get("distance", 10.0))
        rotation = d.get("rotation")
        if rotation is not None:
            cam.rotation = np.asarray(rotation, dtype=float)
        cam.roll = float(d.get("roll", 0.0))
        cam.projection = (str(d.get("projection", PERSPECTIVE))
                          if d.get("projection") in PROJECTIONS
                          else PERSPECTIVE)
        cam.focal_mm = float(d.get("focal_mm", DEFAULT_FOCAL_MM))
        cam.sensor_mm = float(d.get("sensor_mm", DEFAULT_SENSOR_MM))
        cam.width = int(d.get("width", DEFAULT_WIDTH))
        cam.height = int(d.get("height", DEFAULT_HEIGHT))
        cam.multiplier = float(d.get("multiplier", 1.0))
        cam.frame_zoom = clamp_frame_zoom(d.get("frame_zoom", 1.0))
        return cam

    def copy(self):
        return CameraObject.from_dict(self.to_dict())

    def __repr__(self):
        return "CameraObject({!r}, {:.0f}mm, {}x{})".format(
            self.name, self.focal_mm, self.width, self.height)


# ------------------------------------------------------------ the frame
def clamp_frame_zoom(value):
    """A frame zoom that is inside the range and is a number."""
    try:
        z = float(value)
    except (TypeError, ValueError):
        return 1.0
    if not np.isfinite(z):
        return 1.0
    return float(min(max(z, MIN_FRAME_ZOOM), MAX_FRAME_ZOOM))


def frame_rect(widget_w, widget_h, aspect, margin=0.92, zoom=1.0):
    """The camera's FILM back as a rectangle inside the viewport.

    Looking through a camera whose aspect differs from the window has to show
    what will actually be rendered, or the framing you compose is not the
    framing you get. Returns (x, y, w, h) in widget pixels, centred, the
    largest rectangle of that aspect that fits with a little room round it for
    the drag handles — scaled by `zoom`, which is what lets the frame be an
    arbitrary size rather than always filling the window.
    """
    widget_w = max(float(widget_w), 1.0)
    widget_h = max(float(widget_h), 1.0)
    aspect = max(float(aspect), 1e-6)
    scale = clamp_frame_zoom(zoom) * float(margin)
    w = widget_w * scale
    h = w / aspect
    if h > widget_h * scale:
        h = widget_h * scale
        w = h * aspect
    return ((widget_w - w) / 2.0, (widget_h - h) / 2.0, w, h)


def viewport_fov_y(cam_fov_y, rect_h, widget_h):
    """The field of view the WHOLE WIDGET must use so that `cam_fov_y` lands
    exactly on a centred rectangle of height `rect_h`.

    Without this the film back is a decoration rather than a framing: the
    scene was drawn at the viewport's own fixed 40 degrees over the whole
    window and the rectangle merely laid on top, so the focal length changed
    the label and nothing else, and what you composed inside the frame was not
    what would be rendered. A centred rectangle in a symmetric frustum scales
    the half-height linearly, so one `tan` each way is exact.

    Clamped short of 180: a frame pulled very small would otherwise ask for a
    field of view that has no projection matrix.
    """
    rect_h = max(float(rect_h), 1e-6)
    widget_h = max(float(widget_h), 1e-6)
    half = np.tan(np.radians(max(min(float(cam_fov_y), 179.0), 0.1)) / 2.0)
    half *= widget_h / rect_h
    return float(min(np.degrees(2.0 * np.arctan(half)), 179.0))


#: The eight handles of the frame, as (name, u, v) in 0..1 rectangle space.
#: Corners first so a corner wins where two overlap — dragging the very corner
#: of a rectangle should never resize only one edge.
HANDLES = (("nw", 0.0, 0.0), ("ne", 1.0, 0.0), ("sw", 0.0, 1.0),
           ("se", 1.0, 1.0), ("n", 0.5, 0.0), ("s", 0.5, 1.0),
           ("w", 0.0, 0.5), ("e", 1.0, 0.5))


def handle_at(rect, x, y, radius=9.0):
    """Which frame handle the cursor is on, or None."""
    rx, ry, rw, rh = rect
    for name, u, v in HANDLES:
        hx, hy = rx + u * rw, ry + v * rh
        if (x - hx) ** 2 + (y - hy) ** 2 <= radius * radius:
            return name
    return None


CORNERS = ("nw", "ne", "sw", "se")


def handle_scales(handle, dx, dy, rect):
    """(scale_x, scale_y) the frame grows by when `handle` is dragged.

    Both edges move, so a drag of dx widens the frame by 2*dx about the centre
    — the rectangle stays centred, which is how it is drawn and the whole
    reason the arithmetic is this short.
    """
    _rx, _ry, rw, rh = rect
    fx = {"e": 1.0, "w": -1.0, "ne": 1.0, "se": 1.0, "nw": -1.0,
          "sw": -1.0}.get(handle, 0.0)
    fy = {"s": 1.0, "n": -1.0, "se": 1.0, "sw": 1.0, "ne": -1.0,
          "nw": -1.0}.get(handle, 0.0)
    scale_x = max(1.0 + (2.0 * fx * float(dx)) / max(rw, 1.0), 0.05)
    scale_y = max(1.0 + (2.0 * fy * float(dy)) / max(rh, 1.0), 0.05)
    return scale_x, scale_y


def resize_pixels(handle, width, height, dx, dy, rect):
    """New (width, height) in PIXELS after dragging a handle by (dx, dy).

    The drag changes the ASPECT RATIO, which is what the handles are for —
    the pixel count follows so the longer side keeps its size. A corner moves
    both, an edge only its own axis, and both are clamped well above zero
    because a camera 0 pixels wide is not a state worth being able to reach.
    """
    scale_x, scale_y = handle_scales(handle, dx, dy, rect)
    w = int(round(max(float(width) * scale_x, 16)))
    h = int(round(max(float(height) * scale_y, 16)))
    return min(w, 16384), min(h, 16384)


def resize_frame(handle, width, height, zoom, dx, dy, rect):
    """New (width, height, frame_zoom) after dragging a handle.

    Round 57, Christian: "the corner drag buttons essentially do nothing".
    They were doing exactly what they were written to do — changing the pixel
    count — and none of it was VISIBLE, because `frame_rect` normalised the
    result back to the largest rectangle that fits. Only the aspect could ever
    show, and a corner dragged along the rectangle's own diagonal is precisely
    the direction that leaves the aspect alone: `scale_x == scale_y`, same
    shape, same drawn size, nothing on screen moves.

    So a corner now also carries the FRAME ZOOM, by the geometric mean of the
    two scale factors — drag out and the frame grows, drag in and it shrinks,
    while the resolution still follows both axes independently so any width
    and height remain reachable ("more arbitrary"). An EDGE keeps its one job:
    that axis's pixels, i.e. the aspect, with the zoom untouched.
    """
    scale_x, scale_y = handle_scales(handle, dx, dy, rect)
    w, h = resize_pixels(handle, width, height, dx, dy, rect)
    if handle in CORNERS:
        zoom = clamp_frame_zoom(float(zoom) * float(np.sqrt(scale_x * scale_y)))
    else:
        zoom = clamp_frame_zoom(zoom)
    return w, h, zoom
