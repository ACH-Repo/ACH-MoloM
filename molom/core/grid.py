"""Blender-style floor grid constants.

Round 3 replaced the finite CPU line grid with a procedural shader grid (an
apparently infinite plane with distance fade — see `_GRID_FRAG` in
ui/viewport.py). What remains here are the shared colour constants, kept in
core so tests and any future exporters agree with the viewport."""

GRID_GREY = (0.32, 0.32, 0.32)
AXIS_X_COLOR = (0.62, 0.30, 0.32)   # Blender-ish red
AXIS_Y_COLOR = (0.41, 0.56, 0.27)   # Blender-ish green
BACKGROUND = (0.239, 0.239, 0.239)  # Blender default viewport grey (#3D3D3D)


def fade_distance(camera_distance):
    # type: (float) -> float
    """How far (in A) the grid stays visible for a given camera distance —
    scales with zoom so the horizon fade always sits well beyond the scene."""
    return max(60.0, float(camera_distance) * 8.0)
