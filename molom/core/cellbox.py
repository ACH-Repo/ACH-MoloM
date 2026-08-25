"""The unit-cell box as drawable geometry, and where it sits in the picture.

MoloM has always drawn the cell as a QPainter overlay: twelve near-plane
clipped segments painted after the GL passes. That is cheap, needs no buffer
rebuild when a molecule moves, and gives an outline that reads THROUGH the
structure - which is what a crystallography viewer usually wants while you are
navigating.

**It is the wrong thing for a published still**, and Christian is right about
why: an overlay has no depth, so a cell edge that runs behind the framework is
painted straight over it, and the picture then says the edge is in front. On a
dense cell that is not a subtle artefact - the a, b and c vectors cut visibly
across every molecule they pass behind.

So the box can be drawn either way, and the choice is made SEPARATELY for the
viewport and for an image export, because they are answering different
questions. On screen an always-visible box is a navigation aid: you want to
know where the cell is even when it is behind something. In an export the
picture has to be true.

This module owns the GEOMETRY of the depth-respecting form - one thin rod per
edge, which is what VESTA and Diamond draw and what `blender_export.cell_edges`
already produced for a render. Keeping the rule here means the viewport, the
export and the .blend cannot disagree about which edge is the a axis.

UI-free.
"""

from typing import List, Optional, Sequence, Tuple

import numpy as np

#: a = red, b = green, c = blue, matching the compass and the axis colours the
#: overlay has always used.
AXIS_RGB = ((0.90, 0.25, 0.25),
            (0.35, 0.80, 0.30),
            (0.30, 0.50, 0.95))

#: Every other edge. Pale and slightly cool, so it reads as a frame rather
#: than as part of the structure.
BOX_RGB = (0.78, 0.78, 0.82)

#: Rod radius as a fraction of the cell's mean edge length. PROPORTIONAL and
#: not a constant, for the reason round 66 gives about chase cameras: these
#: scenes run from a 3 A cell to a 200 A framework, and one number is either
#: invisible at one end or a girder at the other. 0.004 puts a 10 A cell at
#: 0.04 A, which is exactly the radius the Blender export already defaulted to.
RADIUS_FRAC = 0.004

#: Below this the rod stops being drawable at all.
MIN_RADIUS = 1e-3

#: The two ways the box can be drawn. Names rather than a bool, because a bool
#: called `cell_on_top` reads as a preference and this is a statement about
#: what the picture claims.
OVERLAY = "overlay"      # painted after everything: always visible
DEPTH = "depth"          # real geometry: occluded by what is in front of it
ZORDERS = (OVERLAY, DEPTH)

#: Cell fractional coordinates in `Cell.corners()` order, so an edge can be
#: told which of a, b, c it runs along.
_FRAC = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1],
                  [1, 1, 0], [1, 0, 1], [0, 1, 1], [1, 1, 1]], dtype=float)


def edge_axis(i, j):
    # type: (int, int) -> int
    """Which of a (0), b (1), c (2) the edge between two corners runs along."""
    return int(np.argmax(np.abs(_FRAC[int(j)] - _FRAC[int(i)])))


def radius_for(cell, frac=RADIUS_FRAC):
    # type: (object, float) -> float
    """A rod radius proportional to the cell it is drawing."""
    if cell is None:
        return MIN_RADIUS
    try:
        mean_edge = (float(cell.a) + float(cell.b) + float(cell.c)) / 3.0
    except (AttributeError, TypeError, ValueError):
        return MIN_RADIUS
    return max(float(frac) * mean_edge, MIN_RADIUS)


def rods(cell, corners, radius=None):
    # type: (object, Sequence, Optional[float]) -> List[Tuple]
    """The box as `[(p0, p1, rgb, radius), ...]` in WORLD coordinates.

    `corners` is passed in rather than taken from `cell.corners()` because a
    crystal can have been grabbed and turned: the drawn box follows the atoms
    through a Kabsch fit against the reference sample (round 19), so the cell's
    own frame is not where the box is. Handing the posed corners in keeps that
    one source of truth.

    The three edges leaving the origin corner carry the axis colours and the
    other nine are neutral. The overlay draws all twelve grey and then paints
    the three coloured ones ON TOP of their own grey copies; as geometry that
    would be twelve rods with three more inside them, z-fighting along their
    whole length, so each edge is emitted exactly once in its final colour.
    """
    if cell is None or corners is None:
        return []
    pts = np.asarray(corners, dtype=float)
    if pts.shape[0] < 8:
        return []
    r = radius_for(cell) if radius is None else float(radius)
    axis_edges = {(0, 1): 0, (0, 2): 1, (0, 3): 2}
    out = []
    for i, j in cell.edges():
        key = (min(int(i), int(j)), max(int(i), int(j)))
        axis = axis_edges.get(key)
        rgb = AXIS_RGB[axis] if axis is not None else BOX_RGB
        out.append((pts[int(i)], pts[int(j)], rgb, r))
    return out
