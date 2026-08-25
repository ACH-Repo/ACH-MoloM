"""Round 89: the focal length finally changes the picture (open item K1).

Christian: "why isn't dragging the handles just selecting a 2D window porting
of the viewport though? If I change focal length, then things should just
transition to 'more perspective' or 'more orthographic'... blender also has an
apparent zoom in/out when changing focal length. But that doesn't change the
camera view limits. It only changes the way the viewport looks."

Measured before the change: `cam.fov_y` moved correctly from 84.86 deg at
24 mm to 12.52 deg at 200 mm, and the WIDGET's field of view stayed at 43.17
deg throughout. The lens was inert. `frame_rect` was ANGULAR (half-height
`Z * tan(fov_y/2)`) and `viewport_fov_y` divides by that same rectangle, so
`tan(fov_y/2)` cancelled exactly and the widget field of view came out as
`1/zoom`.

The fix is Christian's model: the frame IS THE FILM, drawn at `zoom` pixels
per mm, with two independent sensor dimensions. Then
`tan(widget_fov/2) = REFERENCE_SENSOR_MM / (2 * focal * zoom)` - the sensor
cancels, so a handle cannot rescale the scene, and the focal length is the
only thing that can.
"""
import numpy as np
import pytest

from molom.core import cameras

WIDGET_W, WIDGET_H = 1000.0, 700.0


def _rect(cam):
    return cameras.frame_rect(WIDGET_W, WIDGET_H, cam.sensor_w, cam.sensor_h,
                              zoom=cam.frame_zoom)


def _widget_fov(cam):
    return cameras.viewport_fov_y(cam.fov_y, _rect(cam)[3], WIDGET_H)


def _content_scale(cam):
    """On-screen size of a fixed object: 1 / tan(half the widget's FOV)."""
    return 1.0 / np.tan(np.radians(_widget_fov(cam)) / 2.0)


def _drag(cam, handle, dx, dy):
    sw, sh, w, h = cameras.resize_frame(handle, cam.sensor_w, cam.sensor_h,
                                        cam.width, cam.height, dx, dy,
                                        _rect(cam))
    cam.sensor_w, cam.sensor_h, cam.width, cam.height = sw, sh, w, h
    return cam


def _cam():
    cam = cameras.CameraObject(1)
    cam.fit_frame(WIDGET_W, WIDGET_H)
    return cam


# ------------------------------------------------------------- the lens
def test_the_focal_length_changes_the_widget_field_of_view():
    """It did not. 43.17 degrees at every focal length from 24 to 200 mm."""
    seen = {}
    for focal in (24, 50, 85, 135, 200):
        cam = _cam()
        cam.focal_mm = focal
        seen[focal] = _widget_fov(cam)
    assert len(set(round(v, 6) for v in seen.values())) == 5
    # ...and it goes the right way: a longer lens sees LESS.
    assert seen[24] > seen[50] > seen[85] > seen[135] > seen[200]
    # At zoom 1 the widget shows exactly what a REFERENCE-sized film would -
    # that is what `frame_zoom = 1` means, since the frame is the film drawn
    # at `REFERENCE_SENSOR_MM` across the full widget height. NOT the camera's
    # own `fov_y`, which depends on its own film.
    cam = _cam()
    cam.frame_zoom = 1.0
    cam.focal_mm = 50
    assert _widget_fov(cam) == pytest.approx(
        cameras.fov_degrees(50, cameras.REFERENCE_SENSOR_MM), rel=1e-9)


def test_a_longer_lens_magnifies_and_does_not_saturate():
    """The old apparent magnification was the render cropping to a smaller
    box, which stops changing: 135 mm and 200 mm gave an identical 528 px
    span. A real lens keeps going."""
    scales = {}
    for focal in (24, 50, 85, 135, 200):
        cam = _cam()
        cam.focal_mm = focal
        scales[focal] = _content_scale(cam)
    assert scales[200] / scales[24] == pytest.approx(200.0 / 24.0, rel=1e-6)
    assert scales[200] > scales[135] * 1.4


def test_the_lens_does_not_move_the_frame():
    """"That doesn't change the camera view limits. It only changes the way
    the viewport looks." The borders are the film's, and a lens is not film."""
    wide, long_ = _cam(), _cam()
    wide.focal_mm, long_.focal_mm = 24, 200
    assert _rect(wide) == _rect(long_)


def test_the_projection_depends_only_on_the_lens_and_the_zoom():
    """`tan(widget_fov/2) = REFERENCE_SENSOR_MM / (2 * focal * zoom)`, derived
    rather than arranged - which is why the sensor cannot leak into it."""
    for focal in (24, 50, 200):
        for zoom in (0.5, 1.0, 2.0):
            cam = _cam()
            cam.focal_mm, cam.frame_zoom = focal, zoom
            expected = cameras.REFERENCE_SENSOR_MM / (2.0 * focal * zoom)
            assert np.tan(np.radians(_widget_fov(cam)) / 2.0) == \
                pytest.approx(expected, rel=1e-9)


# ----------------------------------------------------------- the handles
def test_a_handle_moves_only_its_own_border():
    """"Dragging the handles [is] just selecting a 2D window porting of the
    viewport." A side drag must not change the vertical framing."""
    cam = _cam()
    _x, _y, w0, h0 = _rect(cam)
    fx0, fy0 = cam.fov_x, cam.fov_y
    _drag(cam, "e", 60.0, 0.0)
    _x, _y, w1, h1 = _rect(cam)
    assert w1 > w0 and h1 == pytest.approx(h0, rel=1e-12)
    assert cam.fov_x > fx0 and cam.fov_y == pytest.approx(fy0, rel=1e-12)

    cam = _cam()
    _x, _y, w0, h0 = _rect(cam)
    fx0, fy0 = cam.fov_x, cam.fov_y
    _drag(cam, "s", 40.0, 0.0 + 40.0)
    _x, _y, w1, h1 = _rect(cam)
    assert h1 > h0 and w1 == pytest.approx(w0, rel=1e-12)
    assert cam.fov_y > fy0 and cam.fov_x == pytest.approx(fx0, rel=1e-12)


def test_no_handle_rescales_the_scene():
    """Round 58's guarantee, kept - and now EXACT rather than nearly, because
    the sensor cancels algebraically instead of via a rounded aspect."""
    cam = _cam()
    before = _content_scale(cam)
    for handle, dx, dy in (("se", 40.0, 25.0), ("nw", 30.0, 30.0),
                           ("e", -50.0, 0.0), ("n", 0.0, 20.0),
                           ("s", 0.0, 15.0), ("w", 12.0, 0.0)):
        _drag(cam, handle, dx, dy)
        assert _content_scale(cam) == pytest.approx(before, rel=1e-12)


def test_dragging_still_never_inflates_the_resolution():
    """The 6000x5000 Blender render (round 58) must stay fixed."""
    cam = _cam()
    cam.set_resolution(640, 360)
    for _ in range(40):
        _drag(cam, "se", 60.0, 40.0)
    assert max(cam.width, cam.height) == 640


# ------------------------------------------------------------- the film
def test_the_aspect_comes_from_the_film():
    cam = cameras.CameraObject(1)
    cam.set_sensor(36.0, 18.0)
    assert cam.aspect == pytest.approx(2.0)
    assert cam.width / float(cam.height) == pytest.approx(2.0, rel=1e-3)


def test_typing_a_resolution_reshapes_the_film():
    """Otherwise a 500x1000 camera would still frame 16:9 - more pixels of the
    same picture."""
    cam = cameras.CameraObject(1)
    cam.set_resolution(500, 1000)
    assert cam.aspect == pytest.approx(0.5)
    assert cam.sensor_h == pytest.approx(cam.sensor_w * 2.0)


def test_sensor_mm_still_means_the_horizontal_film():
    """The properties page and the Blender export both speak of one sensor
    width, and it still is one - setting it keeps the shot's shape."""
    cam = cameras.CameraObject(1)
    aspect = cam.aspect
    cam.sensor_mm = 24.0
    assert cam.sensor_w == pytest.approx(24.0)
    assert cam.aspect == pytest.approx(aspect)


# ------------------------------------------------------------ savefiles
def test_a_camera_saved_before_round_89_is_framed_identically():
    """A pre-89 file has ONE horizontal `sensor_mm` and takes its aspect from
    the pixels, so the vertical sensor that reproduces its framing is
    `sensor_mm / aspect`. Reading it any other way silently re-frames every
    saved shot."""
    for width, height, sensor, focal in ((1920, 1080, 36.0, 50.0),
                                         (640, 360, 24.0, 85.0),
                                         (500, 1000, 36.0, 35.0)):
        old = {"id": 1, "focal_mm": focal, "sensor_mm": sensor,
               "width": width, "height": height}
        cam = cameras.CameraObject.from_dict(old)
        expected = cameras.fov_y_degrees(focal, sensor,
                                         width / float(height))
        assert cam.fov_y == pytest.approx(expected, rel=1e-12)
        assert cam.aspect == pytest.approx(width / float(height), rel=1e-9)


def test_the_film_round_trips():
    cam = cameras.CameraObject(1)
    cam.set_sensor(30.0, 12.0)
    back = cameras.CameraObject.from_dict(cam.to_dict())
    assert back.sensor_w == pytest.approx(cam.sensor_w)
    assert back.sensor_h == pytest.approx(cam.sensor_h)


def test_the_blender_export_carries_both_sensor_dimensions():
    from molom.core import blender_export
    cam = cameras.CameraObject(1)
    cam.set_sensor(36.0, 18.0)
    spec = blender_export.camera_object_setup(cam)
    assert spec["sensor"] == pytest.approx(36.0)
    assert spec["sensor_h"] == pytest.approx(18.0)
