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


# --------------------------------------------------- the timeline pane
#: What a scroll over the track pane does. The pane is a HORIZONTAL axis with
#: rows stacked down it, so it wants a different vocabulary from the viewport:
#: there is nothing to orbit, and panning along time is the gesture a trackpad
#: user reaches for first.
PANE_ZOOM = "zoom"
PANE_PAN = "pan"
PANE_ROWS = "rows"

#: Trackpad pixels that count as one wheel notch. A wheel delivers 120 units
#: per detent and a trackpad delivers a stream of small pixel deltas, so
#: without a common unit the same physical movement zooms by wildly different
#: amounts on the two devices - which is what "spotty" looks like.
PANE_STEP_PIXELS = 60.0
PANE_WHEEL_UNITS = 120.0

#: Span multiplier per notch. 0.8 is about a fifth in or out per detent.
PANE_ZOOM_BASE = 0.8


def pane_scroll(dx, dy, has_pixel_delta, ctrl=False, shift=False):
    # type: (float, float, bool, bool, bool) -> tuple
    """(action, steps) for a scroll over the track pane.

    `steps` is in WHEEL NOTCHES, positive for scroll-up / swipe-left, so a
    trackpad's stream of small deltas and a mouse's single detent are the same
    quantity by the time they reach the widget.

    **The axis is chosen by which one DOMINATES**, not by "is dx non-zero".
    A trackpad swipe is never purely one axis - a vertical flick carries a few
    pixels of horizontal - so a rule that checks `dx` first hands most vertical
    swipes to the pan branch, which is exactly the reported symptom: it works
    sometimes. The caller should also LATCH the action for the duration of one
    gesture (round 8's rule about deciding at gesture start), or a swipe that
    drifts diagonally flips between panning and zooming under the hand.
    """
    unit = PANE_STEP_PIXELS if has_pixel_delta else PANE_WHEEL_UNITS
    if ctrl:
        return PANE_ROWS, float(dy) / unit
    if shift:
        return PANE_PAN, float(dy) / unit
    if abs(dx) > abs(dy):
        return PANE_PAN, float(dx) / unit
    return PANE_ZOOM, float(dy) / unit


def pane_zoom_factor(steps):
    # type: (float) -> float
    """Span multiplier for a number of notches. Scroll up zooms IN."""
    return float(PANE_ZOOM_BASE) ** float(steps)
