"""Crystallographic view orientations — the maths behind the ❖ ribbon.

VESTA's orientation toolbar is the fastest way to get a crystal into a view
you can reason about: look down **a**, down **c\\***, or drop into the standard
oblique drawing. All of that is a rotation, so all of it belongs here rather
than in the widget — UI-free numpy, testable without a display.

Two families of axis matter and they are NOT the same direction unless the
cell is orthogonal:

* the DIRECT axes **a**, **b**, **c** are the cell edges;
* the RECIPROCAL axes **a\\***, **b\\***, **c\\*** are the normals to the
  (100), (010) and (001) planes.

In a monoclinic or triclinic cell those differ by the cell angle, which is
precisely why VESTA offers both — "down the a axis" and "perpendicular to the
bc face" are different pictures of the same crystal. Getting this wrong is
the same class of error as round 26's mirror-plane bug, where a plane NORMAL
was transported with the direct matrix instead of the inverse-transpose.
"""

import numpy as np

#: The six axis buttons, in the order VESTA lays them out.
AXIS_KEYS = ("a", "b", "c", "a*", "b*", "c*")


def axis_vector(cell, key):
    # type: (object, str) -> np.ndarray
    """Unit Cartesian direction of a direct or reciprocal cell axis.

    `cell.matrix()` has the direct axes as ROWS, so the reciprocal axes are
    the rows of its inverse TRANSPOSE — a normal is covariant and does not
    transform with the matrix itself.
    """
    key = str(key).strip()
    if key not in AXIS_KEYS:
        raise ValueError("unknown axis {!r}".format(key))
    m = np.asarray(cell.matrix(), dtype=float)
    index = "abc".index(key[0])
    basis = np.linalg.inv(m).T if key.endswith("*") else m
    v = basis[index]
    norm = float(np.linalg.norm(v))
    if norm < 1e-12:
        raise ValueError("degenerate cell axis {!r}".format(key))
    return v / norm


def view_basis(forward, up_hint):
    # type: (np.ndarray, np.ndarray) -> np.ndarray
    """Rows (right, up, -forward): the view matrix's rotation block.

    `up_hint` only has to be non-parallel to `forward`; it is orthogonalised
    against it. When it IS parallel — looking straight down **c** with **c**
    offered as up — a fallback axis is substituted, because a view basis has
    to exist for every button and "you cannot look down c" is not an answer.
    """
    f = np.asarray(forward, dtype=float)
    f = f / np.linalg.norm(f)
    up = np.asarray(up_hint, dtype=float)
    right = np.cross(f, up)
    if float(np.linalg.norm(right)) < 1e-6:
        for alt in (np.array([0.0, 0.0, 1.0]), np.array([0.0, 1.0, 0.0]),
                    np.array([1.0, 0.0, 0.0])):
            right = np.cross(f, alt)
            if float(np.linalg.norm(right)) > 1e-6:
                break
    right /= np.linalg.norm(right)
    true_up = np.cross(right, f)
    return np.vstack([right, true_up, -f])


def look_along(cell, key, flip=False):
    # type: (object, str, bool) -> np.ndarray
    """View basis for an axis button, matching Mercury.

    **The cell origin sits top-left**, the chosen axis goes INTO the screen,
    and the other two run right and down from that corner in cyclic order —
    for axis *k*, axis *k+1* goes RIGHT and axis *k+2* goes DOWN:

    | button | right | down | into the screen |
    |---|---|---|---|
    | a  | b | c | a |
    | b  | c | a | b |
    | c  | a | b | c |

    Getting here took three tries, so the wrong turns are worth recording:

    * the up vector is **cyclic**, not "c unless you picked c". That is what
      makes the b view WIDE (c across) rather than tall, matching Christian's
      Mercury screenshot of a cell with c = 16 A;
    * the second axis points **down**, not up, and the chosen axis points
      **away**, not at you. Those two together are a MIRROR, and no camera
      rotation can undo a mirror — which is exactly why he could tell it was
      a reflection ("exactly mirrored around the red a axis") rather than a
      view from somewhere else. It also answers his question about the origin
      being top-left with positive displacements running downward: that is a
      presentation convention, not a property of the crystallography, and it
      is the one Mercury uses.

    `flip` views from the opposite side (Mercury's separate x−/x+ buttons);
    the ribbon puts it on a second click of the same button.

    For a RECIPROCAL axis the two in-plane directions are still the direct
    axes — a* is by definition normal to b and c, so the b–c plane is what you
    see, and showing it in the direct axes is what makes the picture readable.
    """
    index = "abc".index(str(key)[0])
    third = axis_vector(cell, "abc"[(index + 2) % 3])
    # THE CAMERA COMES IN FROM THE POSITIVE SIDE, so the chosen axis points AT
    # the viewer and `k+2` runs UP. Round 35b had it the other way round -
    # axis away, `k+2` down - which is Mercury's layout (origin top-left,
    # positive displacements running down the page) and was matched against
    # Christian's own Mercury screenshots at the time.
    #
    # He changed it on 2026-09-05, and the reason is MoloM's and not
    # Mercury's: "mercury doesn't have gridlines in its viewport which can be
    # in front of what is being looked at on a view rotate." Coming in from
    # underneath puts the floor grid between the eye and the crystal. Nothing
    # is lost - the far side is still one more press of the same button.
    #
    # BOTH are reversed together, and that is the part to get right: turning
    # the camera round while leaving `k+2` pointing down is a MIRROR, and no
    # camera rotation can undo a mirror. Round 35b found that out from the
    # other direction, when he reported a view "exactly mirrored around the
    # red a axis". Reversing the up vector with the forward one keeps the
    # handedness, so `k+1` still runs RIGHT.
    forward = -axis_vector(cell, key)
    up = third
    if flip:
        forward, up = -forward, -up
    return view_basis(forward, up)


#: The classical CLINOGRAPHIC projection, which is what "standard orientation
#: of the crystal shape" means: **c** vertical, the crystal turned about it by
#: arctan(1/3) and then tipped forward by arctan(1/6). Those two ratios are
#: the traditional draughtsman's values — they are chosen so all three axes
#: stay visibly distinct and no face is seen edge-on, which is exactly the
#: failure mode of a naive "look down [111]".
CLINO_AZIMUTH_DEG = float(np.degrees(np.arctan(1.0 / 3.0)))    # 18.435
CLINO_ELEVATION_DEG = float(np.degrees(np.arctan(1.0 / 6.0)))  # 9.462


def clinographic(cell, azimuth_deg=CLINO_AZIMUTH_DEG,
                 elevation_deg=CLINO_ELEVATION_DEG):
    # type: (object, float, float) -> np.ndarray
    """View basis for the standard oblique drawing of the cell.

    Built in the cell's OWN frame (c up, a toward the viewer) rather than in
    world axes, so a monoclinic cell is presented the way its own geometry
    asks to be — which is the entire point of a standard orientation.
    """
    c_hat = axis_vector(cell, "c")
    a_hat = axis_vector(cell, "a")
    # Horizontal reference: the part of a perpendicular to c.
    a_perp = a_hat - c_hat * float(np.dot(a_hat, c_hat))
    if float(np.linalg.norm(a_perp)) < 1e-9:      # a parallel to c: degenerate
        a_perp = np.cross(c_hat, np.array([0.0, 0.0, 1.0]))
        if float(np.linalg.norm(a_perp)) < 1e-9:
            a_perp = np.cross(c_hat, np.array([1.0, 0.0, 0.0]))
    a_perp /= np.linalg.norm(a_perp)
    side = np.cross(c_hat, a_perp)                # completes the right hand
    az = np.radians(float(azimuth_deg))
    el = np.radians(float(elevation_deg))
    # Turn about c, then tip the VIEW DOWN onto the crystal. The elevation
    # term is subtracted from the forward direction, not added: a crystal
    # drawing is looked down on from slightly above, and getting this sign
    # wrong puts the camera under the floor grid looking up through it —
    # which is exactly what Christian photographed.
    horizontal = a_perp * np.cos(az) + side * np.sin(az)
    forward = -horizontal * np.cos(el) - c_hat * np.sin(el)
    return view_basis(forward, c_hat)


def zoom_steps_for_percent(percent, base=0.88):
    # type: (float, float) -> float
    """Convert "zoom in by N%" into `Camera.zoom`'s exponential steps.

    The camera dollies by `base ** steps` so that a scroll detent feels the
    same at every distance; the ribbon speaks in percentages. Solving
    `base**steps = 1 - percent/100` keeps ONE zoom implementation — including
    its carry-the-centre-forward behaviour at the near floor, which a
    separate percentage path would have quietly lost.
    """
    factor = 1.0 - float(percent) / 100.0
    factor = float(np.clip(factor, 1e-3, 1e3))
    return float(np.log(factor) / np.log(float(base)))
