"""Where the CONTENT of a rendered image actually is.

"Crop to content" for an image export: find the smallest rectangle holding
everything that was drawn, so a figure is not mostly empty background. The
viewport is whatever shape the window happens to be and the molecule sits
wherever the camera left it, so an exported still routinely carries a third of
its pixels as dead space — which then has to be cropped by hand in something
else before it can go in a paper.

UI-free and GL-free on purpose (the golden rule): this takes a numpy array and
returns a box, so every rule below is testable with no display, no Qt and no
GL context. The caller converts its QImage to an array and applies the box.
"""

import numpy as np


def content_box(mask, margin=0, aspect=None, minimum=8):
    # type: (np.ndarray, int, float, int) -> tuple
    """The `(x, y, w, h)` box holding every True pixel of `mask`.

    `margin` pads the box outward in pixels — a figure cropped exactly to the
    van der Waals hull looks amputated, and a few pixels of air is what makes
    it read as deliberate. `aspect` (width / height) grows the box to that
    ratio rather than shrinking it, so asking for 16:9 never cuts anything off.
    `minimum` is a floor on each side, because a single drawn atom would
    otherwise crop to a handful of pixels.

    Returns the FULL image box when nothing is set — an empty scene has no
    content to crop to, and returning a zero-size box would make the caller
    write a broken file. Clamped to the image, so the result is always a valid
    crop rectangle.
    """
    mask = np.asarray(mask, dtype=bool)
    if mask.ndim != 2:
        raise ValueError("mask must be 2-D (height, width)")
    height, width = mask.shape
    if not mask.any():
        return (0, 0, int(width), int(height))

    rows = np.flatnonzero(mask.any(axis=1))
    cols = np.flatnonzero(mask.any(axis=0))
    top, bottom = int(rows[0]), int(rows[-1])
    left, right = int(cols[0]), int(cols[-1])

    box = [left - int(margin), top - int(margin),
           (right - left + 1) + 2 * int(margin),
           (bottom - top + 1) + 2 * int(margin)]

    # Enforce the floor about the box's own centre, so a tiny molecule stays
    # centred in the crop instead of being pushed into a corner.
    for axis in (0, 1):
        size_i, pos_i = 2 + axis, axis
        if box[size_i] < int(minimum):
            centre = box[pos_i] + box[size_i] / 2.0
            box[size_i] = int(minimum)
            box[pos_i] = int(round(centre - box[size_i] / 2.0))

    if aspect:
        box = _to_aspect(box, float(aspect))
    return _clamp(box, width, height)


def _to_aspect(box, aspect):
    # type: (list, float) -> list
    """Grow `box` to `aspect` (width / height) about its centre.

    Only ever GROWS. Shrinking to fit a ratio would crop away content the
    caller just asked to keep, which is the one thing this function must not
    do — the aspect is a framing preference and the content is the point.
    """
    x, y, w, h = box
    if w <= 0 or h <= 0 or aspect <= 0:
        return box
    if w / float(h) < aspect:                 # too tall: widen it
        want = h * aspect
        x -= (want - w) / 2.0
        w = want
    else:                                     # too wide: heighten it
        want = w / aspect
        y -= (want - h) / 2.0
        h = want
    return [int(round(x)), int(round(y)), int(round(w)), int(round(h))]


def _clamp(box, width, height):
    # type: (list, int, int) -> tuple
    """Bring `box` inside a `width` x `height` image, keeping as much of the
    requested size as the image can give."""
    x, y, w, h = (int(v) for v in box)
    w = max(1, min(w, int(width)))
    h = max(1, min(h, int(height)))
    x = max(0, min(x, int(width) - w))
    y = max(0, min(y, int(height) - h))
    return (x, y, w, h)


def alpha_mask(alpha, threshold=8):
    # type: (np.ndarray, int) -> np.ndarray
    """Content mask from an ALPHA channel — the transparent-export case.

    A threshold rather than `> 0` because a multisampled edge leaves a fringe
    of nearly-transparent pixels, and cropping to those adds a pixel or two of
    nothing on every side.
    """
    return np.asarray(alpha) >= int(threshold)


def colour_mask(rgb, background, tolerance=6):
    # type: (np.ndarray, tuple, int) -> np.ndarray
    """Content mask from COLOUR, for an export drawn on an opaque background.

    Anything differing from `background` by more than `tolerance` in any
    channel counts as content. The tolerance matters for the same reason the
    alpha threshold does, plus PNG/JPEG rounding on a colour that was never
    exactly the nominal one.
    """
    rgb = np.asarray(rgb, dtype=np.int16)
    ref = np.asarray(background, dtype=np.int16).reshape(1, 1, -1)
    return (np.abs(rgb - ref) > int(tolerance)).any(axis=2)
