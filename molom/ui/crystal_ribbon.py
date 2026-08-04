"""VESTA's orientation ribbon, for crystals — a horizontal strip that POPS IN
over the top of the viewport whenever a `.cif` object is the one you are
looking at, and gets out of the way again when it is not.

Christian's annotated screenshot asked for exactly this, and for the strip to
sit on the app's own background rather than arriving as a foreign toolbar.
The four groups, confirmed with him rather than guessed:

1. **a b c a\\* b\\* c\\***  — look down a direct or reciprocal cell axis. Both
   families are offered because in anything less symmetric than an
   orthorhombic cell they are different directions (see `core/orient.py`);
2. **◈** — the standard orientation of the crystal shape, i.e. the classical
   clinographic oblique projection;
3. **rotate** by `Step (°)` per click;
4. **pan** by `Step (px)`, then **zoom** by `Step (%)` and a fit button.

Every button is a camera move, so this widget holds no state of its own
beyond the three step boxes — it reads the active crystal's cell, computes
with `core.orient`, and hands the result to the viewport.

One deliberate omission: there is **no in-plane rotation**. MoloM's camera is
a Blender turntable (yaw about world Z, pitch about view X) and a level
horizon is an invariant the whole thing is built on — Christian's original
vertigo fix. Roll exists only inside flight mode, where it is an explicit
term that zeroes on landing. Adding a roll button here would put the camera
in a state the orbit path cannot represent, and the next drag would silently
snap it back.
"""

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (QDoubleSpinBox, QFrame, QHBoxLayout, QLabel,
                               QSpinBox, QToolButton, QWidget)

from ..core import orient

_STYLE = """
QWidget#ribbon {
    background: rgba(48, 48, 48, 225);
    border: 1px solid rgba(0, 0, 0, 110);
    border-radius: 6px;
}
QToolButton {
    background: rgba(64, 64, 64, 200);
    color: rgba(232, 232, 232, 230);
    border: 1px solid rgba(0, 0, 0, 70);
    border-radius: 4px;
    font-size: 13px;
}
QToolButton:hover    { background: rgba(90, 90, 90, 225); color: #ffffff; }
QToolButton:pressed  { background: rgba(70, 115, 175, 240); }
QToolButton:disabled { color: rgba(150, 150, 150, 110); }
QLabel { color: rgba(220, 220, 220, 210); font-size: 11px; }
QSpinBox, QDoubleSpinBox {
    background: rgba(32, 32, 32, 220);
    color: rgba(232, 232, 232, 235);
    border: 1px solid rgba(0, 0, 0, 80);
    border-radius: 3px;
    font-size: 11px;
}
"""


class CrystalRibbon(QWidget):
    """Floating orientation strip. Emits intent; the app does the work."""

    #: axis key, one of orient.AXIS_KEYS
    axis_view = Signal(str)
    #: the standard clinographic orientation
    standard_view = Signal()
    #: dx, dy in DEGREES (turntable yaw / pitch)
    rotate_view = Signal(float, float)
    #: dx, dy in PIXELS
    pan_view = Signal(float, float)
    #: signed percentage; positive zooms in
    zoom_view = Signal(float)
    #: frame the crystal
    fit_view = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ribbon")
        # Without this a PLAIN QWidget ignores its own background/border rules
        # — Qt only styles subclasses it knows how to paint — so the strip
        # came out as floating controls on the bare viewport instead of the
        # panel Christian asked for ("background of ribbon should match app").
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(_STYLE)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(3)

        # ---- 1: the six axis views ------------------------------------
        self._axis_buttons = {}
        for key in orient.AXIS_KEYS:
            reciprocal = key.endswith("*")
            b = self._button(
                key,
                "View along {} — perpendicular to the ({}) planes. In a "
                "non-orthogonal cell this is NOT the same direction as {}. "
                "Click again to view from the other side.".format(
                    key, {"a*": "100", "b*": "010", "c*": "001"}[key], key[0])
                if reciprocal else
                "View along the {} axis ({} points towards you, {} across, "
                "{} up). Click again to view from the other side.".format(
                    key, key, "abc"[("abc".index(key) + 1) % 3],
                    "abc"[("abc".index(key) + 2) % 3]))
            b.clicked.connect(lambda _c=False, k=key: self.axis_view.emit(k))
            self._axis_buttons[key] = b
            lay.addWidget(b)

        # ---- 2: standard orientation ----------------------------------
        self.std_button = self._button(
            "◈", "Standard orientation of the crystal shape — the classical "
                 "clinographic oblique projection (c vertical, turned "
                 "{:.1f}° and tipped {:.1f}°), so no face is seen edge-on "
                 "and all three axes stay distinct".format(
                     orient.CLINO_AZIMUTH_DEG, orient.CLINO_ELEVATION_DEG))
        self.std_button.clicked.connect(
            lambda _c=False: self.standard_view.emit())
        lay.addWidget(self.std_button)
        lay.addWidget(self._separator())

        # ---- 3: stepped rotation --------------------------------------
        self.rot_step = QDoubleSpinBox(self)
        self.rot_step.setRange(0.1, 180.0)
        self.rot_step.setValue(5.0)
        self.rot_step.setDecimals(1)
        self.rot_step.setSingleStep(1.0)
        self.rot_step.setFixedWidth(72)
        self.rot_step.setToolTip("Degrees turned per click")
        # Curved arrows for rotation, straight ones for pan, so the two
        # direction groups cannot be mistaken for each other at a glance.
        # ⤒/⤓ were tried and render as a bar-and-stem smudge at 13 px on
        # Windows; ⤴/⤵ are legible at this size.
        for glyph, tip, sx, sy in (
                ("↺", "Rotate left", -1.0, 0.0),
                ("↻", "Rotate right", 1.0, 0.0),
                ("⤴", "Rotate up", 0.0, -1.0),
                ("⤵", "Rotate down", 0.0, 1.0)):
            b = self._button(glyph, tip + " by the step angle")
            b.clicked.connect(
                lambda _c=False, ax=sx, ay=sy:
                self.rotate_view.emit(ax * self.rot_step.value(),
                                      ay * self.rot_step.value()))
            lay.addWidget(b)
        lay.addWidget(QLabel("Step (°):", self))
        lay.addWidget(self.rot_step)
        lay.addWidget(self._separator())

        # ---- 4: stepped pan -------------------------------------------
        self.pan_step = QSpinBox(self)
        self.pan_step.setRange(1, 2000)
        self.pan_step.setValue(200)
        self.pan_step.setFixedWidth(76)
        self.pan_step.setToolTip("Pixels moved per click")
        for glyph, tip, sx, sy in (
                ("⬅", "Pan left", -1.0, 0.0),
                ("➡", "Pan right", 1.0, 0.0),
                ("⬆", "Pan up", 0.0, -1.0),
                ("⬇", "Pan down", 0.0, 1.0)):
            b = self._button(glyph, tip + " by the step distance")
            b.clicked.connect(
                lambda _c=False, ax=sx, ay=sy:
                self.pan_view.emit(ax * self.pan_step.value(),
                                   ay * self.pan_step.value()))
            lay.addWidget(b)
        lay.addWidget(QLabel("Step (px):", self))
        lay.addWidget(self.pan_step)
        lay.addWidget(self._separator())

        # ---- 5: stepped zoom + fit ------------------------------------
        self.zoom_step = QSpinBox(self)
        self.zoom_step.setRange(1, 90)
        self.zoom_step.setValue(10)
        self.zoom_step.setSuffix("%")
        self.zoom_step.setFixedWidth(72)
        self.zoom_step.setToolTip("Percentage zoomed per click")
        for glyph, tip, sign in (("+", "Zoom in", 1.0),
                                 ("−", "Zoom out", -1.0)):
            b = self._button(glyph, tip + " by the step percentage")
            b.clicked.connect(
                lambda _c=False, s=sign:
                self.zoom_view.emit(s * self.zoom_step.value()))
            lay.addWidget(b)
        self.fit_button = self._button(
            "⤢", "Fit the crystal to the viewport")
        self.fit_button.clicked.connect(
            lambda _c=False: self.fit_view.emit())
        lay.addWidget(self.fit_button)
        lay.addWidget(QLabel("Step (%):", self))
        lay.addWidget(self.zoom_step)

        lay.addStretch(1)
        self.setVisible(False)

    # ------------------------------------------------------------ helpers
    def _button(self, text, tip):
        b = QToolButton(self)
        b.setText(text)
        b.setToolTip(tip)
        b.setFixedSize(QSize(26, 24))
        # NOT checkable. `QToolButton.clicked` carries the CHECKED state, and
        # a non-checkable button therefore passes False forever — the round-34
        # symmetry-arrow bug. Every slot above swallows the argument with a
        # `_c=False` default so it can never be read by accident.
        b.setCheckable(False)
        return b

    def _separator(self):
        line = QFrame(self)
        line.setFrameShape(QFrame.VLine)
        line.setStyleSheet("color: rgba(0, 0, 0, 90);")
        line.setFixedWidth(2)
        return line

    def set_crystal(self, cell, name=""):
        """Show or hide the strip for the object now in focus.

        `cell=None` hides it outright rather than greying it: unlike the ❖
        tab — which has to stay clickable so it can explain itself — this is
        a floating overlay eating viewport space, and a dead strip over a
        molecule with no cell is pure obstruction.
        """
        self.setVisible(cell is not None)
        if cell is not None:
            self.setToolTip("Crystal orientation — {}".format(name))
