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

#: How large the film back is DRAWN, as pixels-per-unit-of-tan-half-angle
#: over half the widget height. Purely a viewing property: it changes nothing
#: about the render, only how big the shot appears while you compose it, and
#: it is what the WHEEL drives inside a camera view — Blender's camera-view
#: zoom. See `frame_rect` for why the frame is angular rather than fitted.
MIN_FRAME_ZOOM = 0.05
MAX_FRAME_ZOOM = 20.0

#: Room left round the frame at the default fit, for the drag handles.
FRAME_FIT_MARGIN = 0.92

#: The film size that `frame_zoom = 1` draws across the whole widget height.
#: Only a unit for the frame's on-screen scale - it fixes what "zoom 1" means
#: and cancels out of the projection entirely (see `frame_rect`).
REFERENCE_SENSOR_MM = DEFAULT_SENSOR_MM


def fov_degrees(focal_mm, sensor_mm):
    """Field of view for a lens on ONE sensor dimension.

    **Per axis, with no aspect term** (round 89). The sensor used to be a
    single HORIZONTAL number with the vertical one derived by dividing by the
    aspect - which meant the aspect fed the vertical field of view, so
    dragging a side handle changed how much of the scene you saw vertically.
    Two independent sensor dimensions is what a film back actually is, and it
    is Blender's own model (`sensor_fit` with `sensor_width`/`sensor_height`).
    """
    focal = max(float(focal_mm), 1e-6)
    sensor = max(float(sensor_mm), 1e-6)
    return float(np.degrees(2.0 * np.arctan(0.5 * sensor / focal)))


def fov_y_degrees(focal_mm, sensor_mm=DEFAULT_SENSOR_MM, aspect=None):
    """Vertical field of view. Kept for the old signature.

    `aspect` divides the sensor exactly as it used to, so a caller that still
    passes a horizontal sensor and an aspect gets the same answer as before.
    """
    sensor = float(sensor_mm)
    if aspect and float(aspect) > 0:
        sensor = sensor / float(aspect)
    return fov_degrees(focal_mm, sensor)


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


def focal_for_fov(fov_deg, sensor_mm):
    """The lens that gives `fov_deg` across a sensor dimension of `sensor_mm`."""
    half = np.tan(np.radians(max(min(float(fov_deg), 179.0), 0.01)) / 2.0)
    return float(0.5 * max(float(sensor_mm), 1e-6) / max(half, 1e-9))


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
        #: The film back, in mm, PER AXIS. Two numbers rather than one plus an
        #: aspect: the aspect used to divide the sensor to get the vertical
        #: field of view, so dragging a side handle changed the vertical
        #: framing as well - the coupling that made K1's fix impossible to
        #: state. Here a horizontal handle moves `sensor_w` and only `fov_x`,
        #: which is what a wider film does.
        self.sensor_w = DEFAULT_SENSOR_MM
        self.sensor_h = DEFAULT_SENSOR_MM * DEFAULT_HEIGHT / float(DEFAULT_WIDTH)
        self.width = DEFAULT_WIDTH
        self.height = DEFAULT_HEIGHT
        self.multiplier = 1.0
        #: Viewport-only: how big the film back is drawn. See MIN_FRAME_ZOOM.
        self.frame_zoom = 1.0

    # ----------------------------------------------------------- geometry
    @property
    def aspect(self):
        """The shot's shape, from the FILM. The pixels follow it (see
        `set_sensor`), so the two cannot drift apart."""
        return float(self.sensor_w) / max(float(self.sensor_h), 1e-6)

    @property
    def sensor_mm(self):
        """The horizontal sensor size, under its old name.

        The properties page and the Blender export both speak of one sensor
        width, and that is still exactly what `sensor_w` is; setting it keeps
        the film's SHAPE, so the old control still means what it did.
        """
        return float(self.sensor_w)

    @sensor_mm.setter
    def sensor_mm(self, value):
        aspect = self.aspect
        self.sensor_w = float(value)
        self.sensor_h = float(value) / max(aspect, 1e-6)

    def set_resolution(self, width, height):
        """Set the pixel size AND reshape the film to match.

        The shot's SHAPE comes from the film now (`aspect` is
        `sensor_w / sensor_h`), so setting the resolution boxes alone would
        change how many pixels the render has without changing what is in it -
        a 500x1000 camera that still framed 16:9. Typing a resolution IS a
        statement about the shape, so it reshapes the film; the horizontal
        sensor is kept, exactly as `sensor_mm`'s setter does.
        """
        self.width = max(int(width), 1)
        self.height = max(int(height), 1)
        aspect = float(self.width) / float(self.height)
        self.sensor_h = float(min(max(self.sensor_w / max(aspect, 1e-6),
                                      MIN_SENSOR_MM), MAX_SENSOR_MM))
        return self

    def set_sensor(self, sensor_w, sensor_h):
        """Set the film and bring the resolution to its shape."""
        self.sensor_w = float(min(max(float(sensor_w), MIN_SENSOR_MM),
                                  MAX_SENSOR_MM))
        self.sensor_h = float(min(max(float(sensor_h), MIN_SENSOR_MM),
                                  MAX_SENSOR_MM))
        self.width, self.height = pixels_for_aspect(
            self.width, self.height, self.aspect)

    @property
    def fov_x(self):
        """Horizontal field of view in degrees."""
        return fov_degrees(self.focal_mm, self.sensor_w)

    @property
    def fov_y(self):
        """Vertical field of view in degrees — what the projection wants."""
        return fov_degrees(self.focal_mm, self.sensor_h)

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

    def half_angles(self):
        """`(tan(fov_x/2), tan(fov_y/2))` — where this shot's borders fall."""
        return half_angles(self.focal_mm, self.sensor_w, self.sensor_h)

    def fit_frame(self, widget_w, widget_h, margin=FRAME_FIT_MARGIN):
        """Size the drawn frame to this viewport. Called when a camera is
        made and by "fit the frame" — never per draw, which is what made the
        frame's size depend on its own shape."""
        self.frame_zoom = fit_frame_zoom(widget_w, widget_h, self.sensor_w,
                                         self.sensor_h, margin)
        return self.frame_zoom

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
            # Capturing "place a camera here" takes the viewport's shape, so
            # the FILM is reshaped to it before the lens is derived - the
            # aspect comes from the film now, not from the pixels.
            self.width, self.height = int(width), int(height)
            aspect = float(width) / max(float(height), 1e-6)
            self.sensor_h = self.sensor_w / max(aspect, 1e-6)
        self.focal_mm = focal_for_fov(
            float(getattr(camera, "FOV_Y", 40.0)), self.sensor_h)
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
            # `sensor_mm` is still written, so a file made now still opens in
            # an older MoloM with the same horizontal framing.
            "sensor_mm": float(self.sensor_w),
            "sensor_w": float(self.sensor_w),
            "sensor_h": float(self.sensor_h),
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
        cam.width = int(d.get("width", DEFAULT_WIDTH))
        cam.height = int(d.get("height", DEFAULT_HEIGHT))
        # MIGRATION. A file written before round 89 has one horizontal
        # `sensor_mm` and takes its aspect from the PIXELS, so the vertical
        # sensor that reproduces its framing exactly is `sensor_mm / aspect`.
        # Reading it any other way would silently re-frame every saved shot.
        if d.get("sensor_h") is not None:
            cam.sensor_w = float(d.get("sensor_w", DEFAULT_SENSOR_MM))
            cam.sensor_h = float(d["sensor_h"])
        else:
            sensor = float(d.get("sensor_mm", DEFAULT_SENSOR_MM))
            aspect = float(cam.width) / max(float(cam.height), 1e-6)
            cam.sensor_w = sensor
            cam.sensor_h = sensor / max(aspect, 1e-6)
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


def half_angles(focal_mm, sensor_w, sensor_h):
    """`(tan(fov_x/2), tan(fov_y/2))` for a lens on a film.

    One term per axis and no aspect anywhere: each half-angle is that
    dimension of the film over twice the focal length. These two numbers are
    what the projection wants, and - since round 89 - NOT what decides how
    big the frame is drawn (see `frame_rect`).
    """
    focal = max(float(focal_mm), 1e-6)
    tx = 0.5 * max(float(sensor_w), 1e-6) / focal
    ty = 0.5 * max(float(sensor_h), 1e-6) / focal
    return float(tx), float(ty)


def frame_rect(widget_w, widget_h, sensor_w, sensor_h, zoom=1.0):
    """The camera's FILM back as a rectangle inside the viewport.

    **THE FRAME IS A 2D WINDOW ON THE VIEWPORT.** Its height is `zoom *
    widget_h` and its width that times the shot's `aspect`. Size is a pure
    VIEWING choice (the wheel); shape is the film. **There is no lens term at
    all**, and that absence is the whole of round 89.

    Round 57 fitted the frame to the window and widened the projection to
    match, so a handle drag rescaled the scene - Christian's "when I pull the
    corners, the camera zooms out". Round 58 fixed that by making the frame
    ANGULAR, half-height `Z * tan(fov_y/2)`. That removed the handle's effect
    on scale and removed the LENS's too: `viewport_fov_y` then divides by this
    same rectangle, so `tan(fov_y/2)` cancelled exactly and the widget field
    of view came out as `1/zoom` - measured at a constant 43.17 degrees from
    24 mm to 200 mm, with the only apparent magnification being the render
    cropping to a smaller box, which saturates.

    Christian's own diagnosis is the fix: "dragging the handles [is] just
    selecting a 2D window ... if I change focal length, then things should
    just transition to more perspective or more orthographic ... that doesn't
    change the camera view limits. It only changes the way the viewport
    looks."

    **So the rectangle IS THE FILM, drawn at `zoom` pixels per mm.** Both
    dimensions are free and each follows its own sensor axis, which is what
    makes a south drag move the bottom border rather than - as the first cut
    of this did, with the height pinned to `zoom` and only the width following
    the aspect - narrowing the frame instead.

    Work the projection out from here and it comes to
    `tan(widget_fov/2) = REFERENCE_SENSOR_MM / (2 * focal * zoom)`: the sensor
    CANCELS, so a handle drag cannot rescale the scene, and the focal length
    is the only thing that can. Both of Christian's requirements at once, and
    neither arranged - they fall out of drawing the film at a fixed scale.
    Returns (x, y, w, h), centred.
    """
    widget_h = max(float(widget_h), 1.0)
    scale = clamp_frame_zoom(zoom) * widget_h / REFERENCE_SENSOR_MM
    w = scale * max(float(sensor_w), 1e-6)
    h = scale * max(float(sensor_h), 1e-6)
    return ((max(float(widget_w), 1.0) - w) / 2.0, (widget_h - h) / 2.0, w, h)


def fit_frame_zoom(widget_w, widget_h, sensor_w, sensor_h,
                   margin=FRAME_FIT_MARGIN):
    """The zoom at which the frame just fits the widget.

    Used when a camera is CREATED, so a new one is framed sensibly, and by
    "fit the frame" — not on every draw, which is what made the frame's size
    depend on its own shape. Takes the FILM now: the frame's size is the film
    at `zoom` pixels per mm, so fitting it involves no lens either.
    """
    widget_w = max(float(widget_w), 1.0)
    widget_h = max(float(widget_h), 1.0)
    by_h = float(margin) * REFERENCE_SENSOR_MM / max(float(sensor_h), 1e-6)
    by_w = (float(margin) * (widget_w / widget_h) * REFERENCE_SENSOR_MM
            / max(float(sensor_w), 1e-6))
    return clamp_frame_zoom(min(by_h, by_w))


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

#: A camera's film cannot be arbitrarily large or vanishingly small.
MIN_SENSOR_MM, MAX_SENSOR_MM = 1.0, 200.0
MIN_ASPECT, MAX_ASPECT = 0.05, 20.0
#: The most pixels a DRAG may put on the long side. Dragging changes the
#: SHAPE of the shot; the resolution boxes on the properties page change how
#: many pixels it has. Keeping the two apart is not tidiness — coupling them
#: is how a few corner drags turned a 1x camera into a 6000x5000 Blender
#: render (`build_render` takes the active camera's resolution).
MAX_DRAG_PIXELS = 8192


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


def pixels_for_aspect(width, height, aspect):
    """Resolution of that aspect keeping the LONGER side's pixel count.

    A drag reshapes the shot; it must never change how many pixels the render
    has. Anchoring the long side means repeated dragging cannot ratchet the
    resolution anywhere — which it did, all the way to 6000x5000.
    """
    aspect = float(min(max(float(aspect), MIN_ASPECT), MAX_ASPECT))
    longest = max(int(width), int(height), 16)
    if aspect >= 1.0:
        w, h = longest, longest / aspect
    else:
        w, h = longest * aspect, longest
    return (min(max(int(round(w)), 16), MAX_DRAG_PIXELS),
            min(max(int(round(h)), 16), MAX_DRAG_PIXELS))


def resize_pixels(handle, width, height, dx, dy, rect):
    """New (width, height) in PIXELS after dragging a handle by (dx, dy).

    The drag changes the ASPECT RATIO, which is what the handles are for —
    the pixel count follows so the longer side keeps its size.
    """
    scale_x, scale_y = handle_scales(handle, dx, dy, rect)
    aspect = (float(width) / max(float(height), 1e-6)) * scale_x / scale_y
    return pixels_for_aspect(width, height, aspect)


def resize_frame(handle, sensor_w, sensor_h, width, height, dx, dy, rect):
    """New `(sensor_w, sensor_h, width, height)` after dragging a handle.

    A handle moves a BORDER of the shot by resizing the FILM on that axis, and
    only that axis - which is what the border of a film back physically is.
    A horizontal drag changes `sensor_w` and therefore `fov_x` alone, so you
    see more or less to the sides and the vertical framing does not move.

    That per-axis independence is the reason round 89 split the sensor in two.
    With one horizontal sensor and a derived aspect, a side drag changed the
    aspect, the aspect divided the sensor to give `fov_y`, and the vertical
    field of view moved with it - so "the handles only move borders" could not
    be made true at the same time as "the lens changes the magnification".

    The resolution follows the film's shape with the longer side pinned, so
    dragging reshapes the shot and never inflates it (round 58: a few corner
    drags used to turn a 1x camera into a 6000x5000 Blender render).
    """
    scale_x, scale_y = handle_scales(handle, dx, dy, rect)
    new_w = float(min(max(float(sensor_w) * scale_x, MIN_SENSOR_MM),
                      MAX_SENSOR_MM))
    new_h = float(min(max(float(sensor_h) * scale_y, MIN_SENSOR_MM),
                      MAX_SENSOR_MM))
    w, h = pixels_for_aspect(width, height, new_w / max(new_h, 1e-9))
    return new_w, new_h, w, h


def zoom_frame(zoom, steps, rate=1.15):
    """The frame zoom after `steps` wheel detents — positive scrolls IN.

    The wheel inside a camera view resizes the FRAME, not the camera. Christian
    was explicit twice: "mousewheel should also not move the camera, only
    scroll in the view", and "if I have made a frame ... way smaller than the
    viewport, scrolling forward should cause the frame to grow in the
    viewport."
    """
    return clamp_frame_zoom(float(zoom) * (float(rate) ** float(steps)))


# --------------------------------------------------- the viewport gizmo
#: How big a camera is DRAWN in the viewport, as a fraction of the scene
#: radius. Blender draws its cameras at a fixed size in Blender units; MoloM's
#: scenes run from a 3 A molecule to a 200 A framework, so a fixed size would
#: be either invisible or the whole screen.
GIZMO_SCENE_FRACTION = 0.22
GIZMO_MIN, GIZMO_MAX = 0.4, 40.0


def gizmo_size(scene_radius):
    """The world length of a camera gizmo's axis in this scene."""
    r = float(scene_radius) if np.isfinite(scene_radius) else 1.0
    return float(min(max(abs(r) * GIZMO_SCENE_FRACTION, GIZMO_MIN), GIZMO_MAX))


def gizmo_geometry(cam, size):
    """A camera drawn the way Blender draws one.

    Returns a dict of WORLD-space pieces:

    * `apex`        — the eye, which is the point you grab;
    * `base`        — the four corners of the film back, in order, so the
                      caller closes the loop;
    * `edges`       — apex-to-corner, the four sides of the pyramid;
    * `up`          — the little triangle marking which way is up, which is
                      the only thing that tells a rolled camera from a level
                      one at a glance;
    * `drop`        — apex to the XY plane, drawn DASHED. Blender's, and it is
                      what turns a floating wireframe into something you can
                      place: without it a camera above the floor and a camera
                      below it look identical.

    A rectangular base and not a circular one: the base IS the film, so its
    shape is the aspect ratio, and a camera whose shot is 16:9 should say so
    while it sits in the scene.
    """
    rot = camera_mod.quat_to_mat3(cam.rolled_rotation())
    right, up, back = rot[0], rot[1], rot[2]      # rows: the view basis
    forward = -back
    apex = np.asarray(cam.eye(), dtype=float)
    tx, ty = cam.half_angles()
    depth = float(size)
    centre = apex + forward * depth
    hx, hy = right * (tx * depth), up * (ty * depth)
    base = [centre - hx - hy, centre + hx - hy, centre + hx + hy,
            centre - hx + hy]
    peak = centre + up * (ty * depth * 1.9)
    return {
        "apex": apex,
        "base": base,
        "edges": [(apex, corner) for corner in base],
        "up": [base[3], peak, base[2]],
        # Straight down to z = 0. `apex` itself when the camera is already on
        # the floor, which draws as nothing rather than as a stray dot.
        "drop": (apex, np.array([apex[0], apex[1], 0.0])),
    }
