"""Coordinates BETWEEN trajectory frames.

Plain per-atom lerp is what everyone writes first, and it is right whenever a
molecule mostly vibrates. It is wrong the moment one ROTATES: every atom
travels the straight chord between its two positions, so the molecule visibly
shrinks toward its centre at the halfway point and springs back — a bond can
lose 20% of its length on the way. `rigid=True` fixes that by splitting the
motion into the rigid part (Kabsch, interpolated as a real rotation about the
centroid) and the leftover deformation (lerped, which it should be).

Cost is O(atoms) either way — one numpy pass, plus a 3x3 SVD for the rigid
path. That is far less than the vertex-buffer upload that follows it, so
interpolated playback is not measurably dearer than snapping frame to frame.
"""

import numpy as np

from .cif import rigid_from_reference


def frame_pair(n_frames, position, cyclic=False):
    # type: (int, float, bool) -> tuple
    """(index_a, index_b, blend) for a fractional frame position.

    `cyclic` says the frames are one CLOSED period whose last sample is
    followed by its first - a baked normal mode, where `mode_frames` stores
    k = 0..n-1 of `sin(2*pi*k/n)` and deliberately omits the duplicate. The
    arc from frame n-1 back to frame 0 is then a real part of the period and
    the position may legitimately sit inside `[n-1, n)`, which the clamping
    branch below would freeze on the last sample instead of closing the loop
    - round 77's half of the mode-loop hitch.
    """
    n = int(n_frames)
    if n <= 1:
        return 0, 0, 0.0
    if cyclic:
        pos = float(position) % float(n)
        a = int(np.floor(pos))
        return a % n, (a + 1) % n, float(pos - a)
    last = n - 1
    pos = max(0.0, min(float(position), float(last)))
    a = int(np.floor(pos))
    if a >= last:
        return last, last, 0.0
    return a, a + 1, float(pos - a)


def lerp(a, b, t):
    # type: (np.ndarray, np.ndarray, float) -> np.ndarray
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    t = float(t)
    if t <= 0.0:
        return a.copy()
    if t >= 1.0:
        return b.copy()
    return a + (b - a) * t


def rigid_lerp(a, b, t):
    # type: (np.ndarray, np.ndarray, float) -> np.ndarray
    """Interpolate a -> b, rotating the rigid part instead of cutting across.

    Falls back to a plain lerp whenever the rigid fit is not meaningful (too
    few atoms, or a degenerate configuration).
    """
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    t = float(t)
    if t <= 0.0:
        return a.copy()
    if t >= 1.0:
        return b.copy()
    fit = rigid_from_reference(a, b)
    if fit is None:
        return lerp(a, b, t)
    rot, _trans = fit
    centre_a = a.mean(axis=0)
    centre_b = b.mean(axis=0)
    # A fraction of the rotation, via axis-angle: R^t.
    partial = _rotation_fraction(rot, t)
    rigid = (a - centre_a) @ partial.T + centre_a + (centre_b - centre_a) * t
    # Whatever the rigid motion did NOT explain is real deformation; that
    # part genuinely is linear, so lerp it on top.
    full_rigid = (a - centre_a) @ rot.T + centre_b
    residual = b - full_rigid
    return rigid + residual * t


def _rotation_fraction(rot, t):
    # type: (np.ndarray, float) -> np.ndarray
    """R^t for a rotation matrix, via axis-angle."""
    cos_angle = (np.trace(rot) - 1.0) / 2.0
    angle = float(np.arccos(np.clip(cos_angle, -1.0, 1.0)))
    if angle < 1e-9:
        return np.eye(3)
    axis = np.array([rot[2, 1] - rot[1, 2],
                     rot[0, 2] - rot[2, 0],
                     rot[1, 0] - rot[0, 1]])
    norm = float(np.linalg.norm(axis))
    if norm < 1e-12:            # 180 degrees: the antisymmetric part vanishes
        vals, vecs = np.linalg.eigh((rot + np.eye(3)) / 2.0)
        axis = vecs[:, int(np.argmax(vals))]
    else:
        axis = axis / norm
    return _axis_angle(axis, angle * t)


def _axis_angle(axis, angle):
    # type: (np.ndarray, float) -> np.ndarray
    x, y, z = axis
    c, s = np.cos(angle), np.sin(angle)
    k = 1.0 - c
    return np.array([
        [c + x * x * k, x * y * k - z * s, x * z * k + y * s],
        [y * x * k + z * s, c + y * y * k, y * z * k - x * s],
        [z * x * k - y * s, z * y * k + x * s, c + z * z * k],
    ])


def coords_at(frames, position, rigid=True, cyclic=False):
    # type: (list, float, bool, bool) -> np.ndarray
    """Interpolated coordinates at a fractional frame position."""
    if not frames:
        return np.zeros((0, 3))
    a, b, t = frame_pair(len(frames), position, cyclic=cyclic)
    if a == b or t <= 0.0:
        return np.asarray(frames[a], dtype=float).copy()
    fa = np.asarray(frames[a], dtype=float)
    fb = np.asarray(frames[b], dtype=float)
    if fa.shape != fb.shape:
        return fa.copy()
    return rigid_lerp(fa, fb, t) if rigid else lerp(fa, fb, t)
