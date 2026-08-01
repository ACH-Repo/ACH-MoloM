"""Rotation helpers shared by the R modal, object frames, and the N panel:
Euler XYZ (Blender's default order: R = Rz @ Ry @ Rx) <-> matrix <-> quat,
and rigid-transform application to coordinate arrays. Pure numpy."""

from typing import Tuple

import numpy as np

from .camera import quat_from_mat3, quat_to_mat3  # noqa: F401 (re-export)


def axis_angle_mat3(axis, angle_rad):
    # type: (np.ndarray, float) -> np.ndarray
    """Rodrigues rotation matrix about a (not necessarily unit) axis."""
    axis = np.asarray(axis, dtype=float)
    n = np.linalg.norm(axis)
    if n == 0.0 or angle_rad == 0.0:
        return np.eye(3)
    x, y, z = axis / n
    c, s = np.cos(angle_rad), np.sin(angle_rad)
    C = 1.0 - c
    return np.array([
        [x * x * C + c, x * y * C - z * s, x * z * C + y * s],
        [y * x * C + z * s, y * y * C + c, y * z * C - x * s],
        [z * x * C - y * s, z * y * C + x * s, z * z * C + c],
    ])


def euler_xyz_to_mat3(rx, ry, rz):
    # type: (float, float, float) -> np.ndarray
    """Euler XYZ (radians, Blender order: X applied first) -> matrix."""
    return (axis_angle_mat3([0, 0, 1], rz)
            @ axis_angle_mat3([0, 1, 0], ry)
            @ axis_angle_mat3([1, 0, 0], rx))


def mat3_to_euler_xyz(m):
    # type: (np.ndarray) -> Tuple[float, float, float]
    """Matrix -> Euler XYZ radians (inverse of euler_xyz_to_mat3; gimbal-safe
    branch returns rz = 0 there, like Blender does)."""
    m = np.asarray(m, dtype=float)
    sy = -m[2, 0]
    sy = np.clip(sy, -1.0, 1.0)
    ry = np.arcsin(sy)
    if abs(sy) < 0.999999:
        rx = np.arctan2(m[2, 1], m[2, 2])
        rz = np.arctan2(m[1, 0], m[0, 0])
    else:                                  # gimbal lock: fold into rx
        rx = np.arctan2(-m[1, 2], m[1, 1])
        rz = 0.0
    return float(rx), float(ry), float(rz)


def rotate_points_about(points, rot3, pivot):
    # type: (np.ndarray, np.ndarray, np.ndarray) -> np.ndarray
    """Rigidly rotate (N,3) points about a pivot: R @ (p - pivot) + pivot."""
    pts = np.asarray(points, dtype=float)
    pivot = np.asarray(pivot, dtype=float)
    return (pts - pivot) @ np.asarray(rot3, dtype=float).T + pivot
