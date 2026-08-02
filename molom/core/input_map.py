"""What a scroll gesture MEANS, per input device (UI-free, so it is testable).

MoloM was built on a laptop, where two-finger scroll is the natural orbit
gesture and zoom hangs off Ctrl. On a desktop with a notched wheel that is
exactly backwards: every program on the machine zooms with the wheel, and one
notch of "orbit" is a ~11 degree jump, which reads as a broken viewport rather
than a different convention.

So the wheel is interpreted per device:

- **trackpad** — plain scroll orbits, Ctrl zooms, Shift pans (the original
  laptop scheme, unchanged).
- **mouse** — plain wheel zooms, Ctrl zooms, Shift pans; orbiting is MMB drag
  (or Alt+LMB), which is what a mouse has buttons for.
- **auto** (default) — decide per event: a precision trackpad reports
  `pixelDelta`, a notched wheel only reports `angleDelta`. This is the same
  signal `_wheel_px` already relies on for smoothness, so no configuration is
  needed for the common case of one project opened on both machines.

The viewport passes in what Qt told it; nothing here imports Qt.
"""

PRESET_AUTO = "auto"
PRESET_TRACKPAD = "trackpad"
PRESET_MOUSE = "mouse"
PRESETS = (PRESET_AUTO, PRESET_TRACKPAD, PRESET_MOUSE)

PRESET_LABELS = {
    PRESET_AUTO: "Auto-detect (trackpad scrolls smoothly, wheels notch)",
    PRESET_TRACKPAD: "Trackpad (scroll orbits, Ctrl+scroll zooms)",
    PRESET_MOUSE: "Mouse (wheel zooms, middle-drag orbits)",
}

ORBIT = "orbit"
ZOOM = "zoom"
PAN = "pan"


def normalize_preset(preset):
    # type: (object) -> str
    """Tolerate whatever QSettings hands back (None, stale string, ...)."""
    text = str(preset or "").strip().lower()
    return text if text in PRESETS else PRESET_AUTO


def is_mouse_wheel(preset, has_pixel_delta):
    # type: (str, bool) -> bool
    """True when this scroll should be read as a notched mouse wheel."""
    preset = normalize_preset(preset)
    if preset == PRESET_MOUSE:
        return True
    if preset == PRESET_TRACKPAD:
        return False
    return not has_pixel_delta


def wheel_action(preset, has_pixel_delta, ctrl=False, shift=False):
    # type: (str, bool, bool, bool) -> str
    """ORBIT / ZOOM / PAN for a wheel event.

    Ctrl and Shift mean the same thing on both devices — only the PLAIN
    gesture differs — so muscle memory carries across machines.
    """
    if shift:
        return PAN
    if ctrl:
        return ZOOM
    return ZOOM if is_mouse_wheel(preset, has_pixel_delta) else ORBIT
