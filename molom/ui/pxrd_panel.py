"""The powder-pattern window: `core/pxrd.py` made visible.

Round 94 computed the physics and deliberately built no UI, so that
matplotlib would not become a dependency by accident. It has not: the plot is
PAINTED, the way the timeline pane is painted, because a diffractogram is a
polyline against an axis and there is nothing in it a plotting library would
do better than a page of QPainter.

**The navigation is ORCA Workbench's**, deliberately and key for key - its NMR
plotter is the most refined thing either program has and Christian uses it
daily: `Z` cycles zoom horizontal / vertical / box, `P` cycles pan, `Esc`
leaves the mode, `F` is the two-stage reset (x, then y, then the intensity
scale), `M` jumps to the limit boxes, `R` redraws, `Ctrl+S` saves, `Ctrl+W`
closes. The wheel scales intensity about each trace's own baseline and
`Ctrl+wheel` zooms x about the cursor, which is Mestrenova's convention and
OWB's.

**Painting is cached into a pixmap.** Everything that does not move with the
cursor - grid, curves, tick strips, labels - is drawn ONCE into a QPixmap and
blitted; only the crosshair and the rubber band are painted per event. A
mouse move over the plot is then a blit and two lines instead of a rebuild of
several thousand QPointF, which is the whole of why this used to crawl. The
curves are also decimated to a min/max envelope per pixel COLUMN, so the cost
of a repaint depends on the width of the window and not on how many points
the profile has.

**No per-structure state lives here.** Every setting is on the crystal
(`pxrd.settings_of` / `set_settings`), so it rides undo and the savefile, and
deleting a crystal takes its trace with it because the trace was never the
window's.
"""

import math

from PySide6.QtCore import QLocale, QPoint, QPointF, QRect, Qt, Signal
from PySide6.QtGui import (QColor, QFont, QPainter, QPen, QPixmap, QPolygonF)
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QColorDialog,
                               QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QMenu,
                               QPushButton, QSizePolicy, QSlider, QSpinBox,
                               QTableWidget, QTableWidgetItem, QTabWidget,
                               QVBoxLayout, QWidget)

import numpy as np

from ..core import pxrd
from .widgets import FlowLayout

_BG = QColor(38, 38, 38)
_AXIS = QColor(150, 150, 150)
_GRID = QColor(64, 64, 64)
_TEXT_DIM = QColor(150, 150, 150)
_CURSOR = QColor(240, 200, 90)
_BAND = QColor(240, 200, 90, 60)
_BAND_EDGE = QColor(240, 200, 90)

#: One colour per trace, in the order the crystals appear in the scene.
#: Chosen to stay apart on a dark background and when printed grey.
PALETTE = ("#6ea8ff", "#ffb04e", "#7fd08a", "#e07b7b", "#c79bef",
           "#4fd0c8", "#d8d16a", "#f08ac0")

_LEFT = 10          # no intensity numbers to leave room for
_RIGHT = 12
_TOP = 10
_BOTTOM = 42        # axis labels plus the reflection tick strip
_TICKS_H = 12       # the tick strip of reflection positions

#: One wheel notch scales the intensities by this, Mestrenova's step and
#: OWB's. Ctrl+wheel zooms x by the same factor about the cursor.
WHEEL_STEP = 1.2
Y_SCALE_LIMITS = (1e-3, 1e4)


#: How many samples a peak gets across its own FWHM.
#:
#: Sampling every `d` leaves the nearest sample up to `d/2` from the true
#: centre, and a Gaussian there is down by `exp(-0.5 (d/2 sigma)^2)`. Holding
#: that to 1% needs `d <= 0.12 FWHM`, i.e. about eight samples across it -
#: and the Gaussian is the worst case, since a Lorentzian is flatter on top.
#: Three was the first guess and it clipped peak tops by 4 px.
SAMPLES_PER_FWHM = 8.0

#: Sub-samples per pixel column are capped here, so a pathologically narrow
#: peak cannot turn one repaint into a million evaluations.
MAX_SUBSAMPLES = 16


class NumberBox(QDoubleSpinBox):
    """A spin box that reads "1.5" and "1,5" alike.

    Christian is on a German locale, where Qt's own decimal separator is a
    comma - so a typed "0.15" is not a number and the box quietly keeps its
    old value. A plot is exactly the place where somebody pastes a number
    from a paper, so the box has to take whichever one they have.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        locale = QLocale(QLocale.C)
        locale.setNumberOptions(QLocale.OmitGroupSeparator)
        self.setLocale(locale)

    @staticmethod
    def _normalise(text):
        return str(text).strip().replace(",", ".")

    def validate(self, text, pos):
        return super().validate(self._normalise(text), pos)

    def valueFromText(self, text):
        return super().valueFromText(self._normalise(text))


class Trace(object):
    """One crystal's curve, plus the reflections it was drawn from.

    `x` / `y` are the profile on a regular grid, which is what an EXPORT
    wants. `sampler` evaluates the same profile at arbitrary positions, which
    is what DRAWING wants - see `PxrdPlot._envelope`.
    """

    __slots__ = ("obj", "name", "colour", "x", "y", "pattern", "offset",
                 "sampler", "fwhm")

    def __init__(self, obj, name, colour, x, y, pattern, offset=0.0,
                 sampler=None, fwhm=0.0):
        self.obj = obj
        self.name = name
        self.colour = QColor(colour)
        self.x, self.y = x, y
        self.pattern = pattern
        self.offset = float(offset)
        #: `f(x_array) -> y_array`, already on the same scale as `y`.
        self.sampler = sampler
        #: The peak width in the units of the axis, which is what says how
        #: finely a pixel column has to be sampled.
        self.fwhm = float(fwhm)


class PxrdPlot(QWidget):
    """The painted diffractogram, navigated the way OWB's spectra are."""

    hovered = Signal(str)
    mode_changed = Signal(str)
    view_changed = Signal()
    trace_menu = Signal(object, QPoint)     # (Trace or None, global pos)

    ZOOM_CYCLE = ("zoom_h", "zoom_v", "zoom_box", None)
    PAN_CYCLE = ("pan_h", "pan_v", "pan_free", None)
    MODE_TEXT = {
        "zoom_h": "ZOOM horizontal - drag a range (Esc exits)",
        "zoom_v": "ZOOM vertical - drag a range (Esc exits)",
        "zoom_box": "ZOOM box - drag a rectangle (Esc exits)",
        "pan_h": "PAN horizontal - drag (Esc exits)",
        "pan_v": "PAN vertical - drag (Esc exits)",
        "pan_free": "PAN free - drag (Esc exits)",
    }
    MODE_CURSOR = {"zoom_h": Qt.SizeHorCursor, "zoom_v": Qt.SizeVerCursor,
                   "zoom_box": Qt.CrossCursor, "pan_h": Qt.SizeHorCursor,
                   "pan_v": Qt.SizeVerCursor, "pan_free": Qt.SizeAllCursor}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(240)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.traces = []
        self.axis = pxrd.AXIS_TWO_THETA
        self.y_margin = 0.05
        #: A multiplier on every trace's amplitude, applied about its OWN
        #: baseline so a stack keeps its spacing (Mestrenova / OWB).
        self.y_scale = 1.0
        self._view_x = None          # None means "the data range"
        self._view_y = None
        self._cursor = None
        self._mode = None
        self._drag = None
        #: The blitted background: everything that does not follow the mouse.
        self._cache = None
        self._cache_key = None

    # ------------------------------------------------------------- content
    def set_traces(self, traces, axis, keep_view=True):
        self.traces = list(traces)
        self.axis = axis
        if not keep_view:
            self._view_x = self._view_y = None
        self.invalidate()

    def invalidate(self):
        """Throw the blitted background away and repaint."""
        self._cache = None
        self.update()

    # -------------------------------------------------------------- ranges
    def data_x(self):
        lows = [float(t.x[0]) for t in self.traces if len(t.x)]
        highs = [float(t.x[-1]) for t in self.traces if len(t.x)]
        if not lows:
            return (0.0, 50.0)
        lo, hi = min(lows), max(highs)
        return (lo, hi) if hi > lo else (lo, lo + 1.0)

    def data_y(self):
        top = 100.0 + max((t.offset for t in self.traces), default=0.0)
        pad = (top or 1.0) * float(self.y_margin)
        return (-pad, top + pad)

    def view_x(self):
        return self._view_x or self.data_x()

    def view_y(self):
        return self._view_y or self.data_y()

    def set_view_x(self, lo, hi):
        if hi > lo:
            self._view_x = (float(lo), float(hi))
            self.invalidate()
            self.view_changed.emit()

    def set_view_y(self, lo, hi):
        if hi > lo:
            self._view_y = (float(lo), float(hi))
            self.invalidate()
            self.view_changed.emit()

    def at_home_x(self):
        return self._view_x is None or _close(self._view_x, self.data_x())

    def at_home_y(self):
        return self._view_y is None or _close(self._view_y, self.data_y())

    def reset_view(self):
        """OWB's two-stage `F`: x first, then y, then the intensity scale.

        Staged rather than all-at-once because the three are undone in the
        order they are usually done - you zoom in x, you rarely touch y, and
        the wheel is a separate gesture. One key that puts everything back at
        once cannot say "just the x range, please"."""
        if not self.at_home_x():
            self._view_x = None
        elif not self.at_home_y():
            self._view_y = None
        elif abs(self.y_scale - 1.0) > 1e-9:
            self.y_scale = 1.0
        else:
            return False
        self.invalidate()
        self.view_changed.emit()
        return True

    def set_y_scale(self, value):
        lo, hi = Y_SCALE_LIMITS
        self.y_scale = max(lo, min(hi, float(value)))
        self.invalidate()
        self.view_changed.emit()

    # -------------------------------------------------------------- mapping
    def plot_rect(self):
        return QRect(_LEFT, _TOP,
                     max(10, self.width() - _LEFT - _RIGHT),
                     max(10, self.height() - _TOP - _BOTTOM))

    def x_to_px(self, value, rect=None, view=None):
        rect = rect or self.plot_rect()
        lo, hi = view or self.view_x()
        return rect.left() + (value - lo) / max(hi - lo, 1e-12) * rect.width()

    def px_to_x(self, px, rect=None, view=None):
        rect = rect or self.plot_rect()
        lo, hi = view or self.view_x()
        return lo + (px - rect.left()) / max(1.0, rect.width()) * (hi - lo)

    def y_to_px(self, value, rect=None, view=None):
        rect = rect or self.plot_rect()
        lo, hi = view or self.view_y()
        usable = max(10, rect.height() - _TICKS_H)
        return (rect.top() + usable
                * (1.0 - (value - lo) / max(hi - lo, 1e-12)))

    def px_to_y(self, px, rect=None, view=None):
        rect = rect or self.plot_rect()
        lo, hi = view or self.view_y()
        usable = max(10, rect.height() - _TICKS_H)
        return lo + (1.0 - (px - rect.top()) / usable) * (hi - lo)

    # ---------------------------------------------------------- navigation
    def cycle_mode(self, cycle):
        current = self._mode if self._mode in cycle else None
        index = cycle.index(current) if current in cycle else -1
        self.set_mode(cycle[(index + 1) % len(cycle)])

    def set_mode(self, mode):
        self._drag = None
        self._mode = mode
        self.setCursor(self.MODE_CURSOR.get(mode, Qt.ArrowCursor))
        self.mode_changed.emit(self.MODE_TEXT.get(mode, ""))
        self.update()

    def mode(self):
        return self._mode

    def keyPressEvent(self, ev):
        key = ev.key()
        if key == Qt.Key_Z:
            self.cycle_mode(self.ZOOM_CYCLE)
        elif key == Qt.Key_P:
            self.cycle_mode(self.PAN_CYCLE)
        elif key == Qt.Key_Escape:
            self.set_mode(None)
        elif key in (Qt.Key_F, Qt.Key_Home):
            self.reset_view()
        else:
            super().keyPressEvent(ev)
            return
        ev.accept()

    def wheelEvent(self, ev):
        step = ev.angleDelta().y() / 120.0
        if not step:
            step = ev.pixelDelta().y() / 60.0
        if not step:
            return
        factor = WHEEL_STEP ** step
        if ev.modifiers() & Qt.ControlModifier:
            lo, hi = self.view_x()
            anchor = self.px_to_x(ev.position().x())
            span = (hi - lo) / factor
            frac = (anchor - lo) / max(hi - lo, 1e-12)
            self.set_view_x(anchor - span * frac, anchor + span * (1 - frac))
        else:
            # The wheel scales the DATA about each trace's own baseline, not
            # the view: a stack then keeps its spacing and the traces higher
            # up do not fly off the top, which is the whole point of the
            # gesture in Mestrenova and in OWB.
            self.set_y_scale(self.y_scale * factor)
        ev.accept()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.RightButton:
            self.trace_menu.emit(self._trace_at(ev.position()),
                                 ev.globalPosition().toPoint())
            ev.accept()
            return
        if ev.button() != Qt.LeftButton or not self._mode:
            super().mousePressEvent(ev)
            return
        rect = self.plot_rect()
        self._drag = {"px": ev.position().x(), "py": ev.position().y(),
                      "x": self.px_to_x(ev.position().x(), rect),
                      "y": self.px_to_y(ev.position().y(), rect),
                      "view_x": self.view_x(), "view_y": self.view_y(),
                      "mode": self._mode}
        ev.accept()

    def mouseMoveEvent(self, ev):
        self._cursor = ev.position()
        drag = self._drag
        if drag is not None and drag["mode"].startswith("pan"):
            rect = self.plot_rect()
            # Measured in PIXELS through the PRESS-time view, never through
            # the live one: `px_to_x` is derived from the limits the pan is
            # changing, so reading it back feeds the motion into itself and
            # the pan accelerates away. OWB's lesson, and it is the same
            # mistake as reading `event.xdata` during a matplotlib pan.
            x0, x1 = drag["view_x"]
            y0, y1 = drag["view_y"]
            dx = ((drag["px"] - ev.position().x()) / max(1.0, rect.width())
                  * (x1 - x0))
            dy = ((ev.position().y() - drag["py"])
                  / max(1.0, rect.height() - _TICKS_H) * (y1 - y0))
            if drag["mode"] in ("pan_h", "pan_free"):
                self._view_x = (x0 + dx, x1 + dx)
            if drag["mode"] in ("pan_v", "pan_free"):
                self._view_y = (y0 + dy, y1 + dy)
            # NOT `invalidate`: a pan is exactly the gesture that can afford
            # to blit, because the picture is unchanged and only its ORIGIN
            # moved. `paintEvent` draws the cached pixmap shifted and the
            # rebuild waits for the release - which is the difference between
            # a smooth drag and one repaint per quarter second with eight
            # patterns open.
            self.update()
            self.view_changed.emit()
            return
        self.hovered.emit(self.readout(ev.position().x(), ev.position().y()))
        self.update()

    def mouseReleaseEvent(self, ev):
        drag, self._drag = self._drag, None
        if drag is None or ev.button() != Qt.LeftButton:
            super().mouseReleaseEvent(ev)
            return
        mode = drag["mode"]
        if mode.startswith("pan"):
            self.invalidate()          # the blit was provisional; redraw it
            return
        rect = self.plot_rect()
        x1 = self.px_to_x(_clamp(ev.position().x(), rect.left(), rect.right()),
                          rect, drag["view_x"])
        y1 = self.px_to_y(_clamp(ev.position().y(), rect.top(),
                                 rect.bottom() - _TICKS_H),
                          rect, drag["view_y"])
        if mode in ("zoom_h", "zoom_box") and abs(x1 - drag["x"]) > 1e-9:
            self.set_view_x(min(drag["x"], x1), max(drag["x"], x1))
        if mode in ("zoom_v", "zoom_box") and abs(y1 - drag["y"]) > 1e-9:
            self.set_view_y(min(drag["y"], y1), max(drag["y"], y1))
        self.update()

    def enterEvent(self, ev):
        """Focus follows the cursor into the plot, so the key map is live
        without a click first - round 12's rule for the viewport, and the
        reason OWB binds its plot keys on the canvas."""
        self.setFocus(Qt.MouseFocusReason)
        super().enterEvent(ev)

    def leaveEvent(self, _ev):
        self._cursor = None
        self.hovered.emit("")
        self.update()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.invalidate()

    # ------------------------------------------------------------- picking
    def _trace_at(self, pos):
        """The trace whose CURVE is nearest the cursor, or None.

        Nearest in y at the cursor's x, because that is what "this line" means
        when several run across one another - a nearest-point search over the
        whole curve picks whichever trace happens to have a peak nearby.
        """
        if not self.traces:
            return None
        rect = self.plot_rect()
        x = self.px_to_x(pos.x(), rect)
        best, best_gap = None, 1e30
        for trace in self.traces:
            if not len(trace.x):
                continue
            i = int(np.searchsorted(trace.x, x))
            i = max(0, min(len(trace.x) - 1, i))
            py = self.y_to_px(trace.y[i] * self.y_scale + trace.offset, rect)
            gap = abs(py - pos.y())
            if gap < best_gap:
                best, best_gap = trace, gap
        return best if best_gap < 60 else None

    def readout(self, px, py=None):
        """The nearest reflection to the cursor, named the way a
        crystallographer writes it. The label is the whole reason to hover: a
        peak with no index is a bump."""
        if not self.traces:
            return ""
        x = self.px_to_x(px)
        unit = "2th" if self.axis == pxrd.AXIS_TWO_THETA else "Q"
        best, best_trace, best_gap = None, None, 1e30
        for trace in self.traces:
            for r in trace.pattern.reflections:
                value = (r.two_theta if self.axis == pxrd.AXIS_TWO_THETA
                         else r.q)
                gap = abs(value - x)
                if gap < best_gap:
                    best, best_trace, best_gap = r, trace, gap
        if best is None:
            return "{} = {:.3f}".format(unit, x)
        rect = self.plot_rect()
        reach = abs(self.px_to_x(rect.left() + 30) - self.px_to_x(rect.left()))
        if best_gap > reach:
            return "{} = {:.3f}".format(unit, x)
        more = ("" if best.multiplicity <= 1
                else " and {} more".format(best.multiplicity - 1))
        return ("{}   {}{}   2th = {:.3f} deg   d = {:.4f} A   "
                "Q = {:.4f} 1/A".format(best_trace.name, best.label(), more,
                                        best.two_theta, best.d, best.q))

    # ------------------------------------------------------------- painting
    def _key(self):
        # The device pixel ratio is IN the key: dragging the window to a
        # monitor at a different scale needs a different pixmap and changes
        # nothing else about the picture.
        return (self.width(), self.height(), self.devicePixelRatioF(),
                self.axis, self.y_scale,
                self.view_x(), self.view_y(),
                tuple((id(t), t.offset, t.colour.rgb(), len(t.x))
                      for t in self.traces))

    def paintEvent(self, _ev):
        painter = QPainter(self)
        drag = self._drag
        if (drag is not None and drag["mode"].startswith("pan")
                and self._cache is not None and self._cursor is not None):
            # The blitted pan: the same picture, moved. The gap the shift
            # leaves is background rather than stale pixels, so what is
            # outside the data reads as outside the data.
            painter.fillRect(self.rect(), _BG)
            painter.drawPixmap(
                int(self._cursor.x() - drag["px"])
                if drag["mode"] in ("pan_h", "pan_free") else 0,
                int(self._cursor.y() - drag["py"])
                if drag["mode"] in ("pan_v", "pan_free") else 0,
                self._cache)
            return
        key = self._key()
        if self._cache is None or self._cache_key != key:
            self._cache = self._render()
            self._cache_key = key
        painter.drawPixmap(0, 0, self._cache)
        # Only what follows the mouse is painted per event. That is the whole
        # blitting argument: a mouse move over the plot must not rebuild
        # several thousand points.
        self._paint_cursor(painter)
        self._paint_band(painter)

    def _render(self):
        """Everything that does not move with the cursor, into a pixmap.

        **Allocated in DEVICE pixels.** `QPixmap(w, h)` makes w x h device
        pixels, and `setDevicePixelRatio(1.5)` then declares them to be
        w/1.5 x h/1.5 LOGICAL ones - so a pixmap made at the widget's logical
        size covers two thirds of it on a 150% display, and everything past
        that is clipped while the crosshair (drawn on the widget, at full
        size) sails on past the edge. Round 59 met the same trap from the
        other side, in `tools/screenshots.py`.

        The painter works in LOGICAL coordinates on such a pixmap either way,
        which is why nothing else in the drawing has to know about this.
        """
        ratio = float(self.devicePixelRatioF() or 1.0)
        pixmap = QPixmap(max(1, int(round(self.width() * ratio))),
                         max(1, int(round(self.height() * ratio))))
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(_BG)
        p = QPainter(pixmap)
        rect = self.plot_rect()
        if not self.traces:
            p.setPen(_TEXT_DIM)
            p.drawText(self.rect(), Qt.AlignCenter,
                       "Nothing to plot.\nOpen a .cif - a powder pattern "
                       "needs a unit cell.")
            p.end()
            return pixmap
        p.setRenderHint(QPainter.Antialiasing, True)
        self._paint_grid(p, rect)
        for trace in self.traces:
            self._paint_trace(p, rect, trace)
        p.setRenderHint(QPainter.Antialiasing, False)
        p.setPen(QPen(_AXIS, 1))
        p.drawLine(rect.left(), rect.bottom() - _TICKS_H,
                   rect.right(), rect.bottom() - _TICKS_H)
        p.drawLine(rect.left(), rect.top(),
                   rect.left(), rect.bottom() - _TICKS_H)
        p.setPen(_TEXT_DIM)
        p.drawText(QRect(rect.left(), self.height() - 15, rect.width(), 14),
                   Qt.AlignHCenter,
                   "2 theta / degrees" if self.axis == pxrd.AXIS_TWO_THETA
                   else "Q / inverse Angstrom")
        p.end()
        return pixmap

    @staticmethod
    def _nice_step(span, target=8):
        raw = span / float(target)
        power = 10.0 ** math.floor(math.log10(max(raw, 1e-12)))
        for mult in (1, 2, 5, 10):
            if raw <= mult * power:
                return mult * power
        return 10.0 * power

    def _paint_grid(self, p, rect):
        lo, hi = self.view_x()
        f = QFont(p.font())
        f.setPointSizeF(max(7.0, f.pointSizeF() - 1.0))
        p.setFont(f)
        step = self._nice_step(hi - lo)
        value = math.ceil(lo / step) * step
        while value <= hi + 1e-9:
            x = int(self.x_to_px(value, rect))
            p.setPen(QPen(_GRID, 1))
            p.drawLine(x, rect.top(), x, rect.bottom() - _TICKS_H)
            p.setPen(_TEXT_DIM)
            p.drawText(QRect(x - 32, rect.bottom() + 1, 64, 13),
                       Qt.AlignHCenter, "{:g}".format(round(value, 6)))
            value += step
        # The intensity axis is per TRACE: with the traces stacked, 100 means
        # "this pattern's strongest peak", once per pattern, which is what a
        # relative intensity is.
        # The intensity LINES stay and the numbers go: every trace is
        # normalised to its own strongest peak, so "100" says the same thing
        # on every one of them and says nothing about any of them. The
        # baseline and the half-height rule are what the eye uses.
        y_lo, y_hi = self.view_y()
        for trace in self.traces:
            for level in (0, 50, 100):
                value = level + trace.offset
                if not (y_lo - 1 <= value <= y_hi + 1):
                    continue
                y = int(self.y_to_px(value, rect))
                p.setPen(QPen(_GRID if level else _AXIS.darker(160), 1))
                p.drawLine(rect.left(), y, rect.right(), y)

    def _paint_trace(self, p, rect, trace):
        lo, hi = self.view_x()
        poly = self._envelope(trace, rect, lo, hi)
        p.setPen(QPen(trace.colour, 1.4))
        if poly is not None:
            p.drawPolyline(poly)
        p.setPen(QPen(trace.colour, 1))
        base = (int(self.y_to_px(trace.offset, rect)) + 1 if trace.offset
                else rect.bottom() - _TICKS_H)
        for r in trace.pattern.reflections:
            value = (r.two_theta if self.axis == pxrd.AXIS_TWO_THETA else r.q)
            if value < lo or value > hi:
                continue
            x = int(self.x_to_px(value, rect))
            p.drawLine(x, base + 1, x, base + 6)

    def columns(self, rect):
        """How many sample columns the plot is worth - in DEVICE pixels.

        `rect.width()` is LOGICAL, so on a 150% display one logical pixel is
        one and a half real ones and a min/max envelope built per logical
        pixel is a staircase with 1.5-device-pixel treads. That is the "a lot
        of steps visible" Christian reported, and it is not an antialiasing
        failure: antialiasing cannot smooth a step it has been asked to draw.
        Reduce at the resolution the screen actually has and the treads fall
        below one device pixel, where they belong.
        """
        return max(1, int(round(rect.width()
                                * float(self.devicePixelRatioF() or 1.0))))

    def _view_samples(self, trace, rect, lo, hi):
        """`(xs, ys)` for the visible range - at the PIXELS about to be drawn.

        The count is bounded by the width of the window at every zoom level,
        which is what makes a repaint cost the same whether the view is the
        whole pattern or one peak. The sub-sample count comes from the FWHM:
        a peak narrower than a pixel would otherwise fall between two samples
        and be drawn at a fraction of its height, or not at all.
        """
        width = self.columns(rect)
        span = max(hi - lo, 1e-12)
        if trace.sampler is None or trace.fwhm <= 0.0:
            return None
        px_per_fwhm = trace.fwhm / span * width
        per_px = int(math.ceil(SAMPLES_PER_FWHM / max(px_per_fwhm, 1e-9)))
        per_px = max(1, min(MAX_SUBSAMPLES, per_px))
        n = width * per_px
        # ...but only if that is FINER than the curve already stored. Zoomed
        # out, the stored grid is denser than any per-pixel sampling can be,
        # and resampling there would throw detail away rather than add it -
        # measured as peak tops drawn 4 px low. Whichever samples the profile
        # more finely wins, so the picture can only get better.
        if len(trace.x) > 1:
            stored = float(trace.x[1] - trace.x[0])
            if 0.0 < stored <= span / n:
                return None
        xs = lo + (np.arange(n) + 0.5) * (span / n)
        return xs, trace.sampler(xs), per_px

    def _envelope(self, trace, rect, lo, hi):
        """The curve as at most two points per pixel COLUMN, and usually one.

        Two ways in, one reduction. Where the trace can be RESAMPLED it is
        evaluated at this view's own pixels (`_view_samples`); where it
        cannot - a Trace built by hand, or one whose profile is already
        stored - the stored grid is decimated instead. Both then go through
        the same min/max per column, because that is the part that decides
        what is drawn.

        **Why min/max per column at all**: 4501 stored points cost 6.4 ms to
        build and 25 ms to stroke, so eight patterns were a quarter of a
        second a frame. Two points per column keeps every narrow peak and is
        2.5x cheaper; but a diffractogram is mostly FLAT, so a column whose
        samples span less than half a pixel needs ONE point and only a column
        holding a peak edge needs its min and its max. That is about one
        point per pixel - 871 from 4501 - and 6 ms a trace instead of 31.
        """
        sampled = self._view_samples(trace, rect, lo, hi)
        width = max(1, rect.width())
        if sampled is not None:
            xs, values, per_px = sampled
            columns = self.columns(rect)
            ys = values * self.y_scale + trace.offset
            px = rect.left() + (xs - lo) / max(hi - lo, 1e-12) * rect.width()
            py = self.y_to_px(ys, rect)
            if per_px > 1:
                # Exactly `per_px` samples per column by construction, so the
                # reduction is a reshape rather than a search. The x kept is
                # the column's CENTRE, so the curve sits where its samples
                # are rather than being nudged left by half a column.
                block_x = px.reshape(columns, per_px)
                block_y = py.reshape(columns, per_px)
                return self._columns(block_x.mean(axis=1),
                                     block_y.min(axis=1),
                                     block_y.max(axis=1))
            return self._polyline(px, py)
        x, y = trace.x, trace.y
        if not len(x):
            return None
        bounds = np.searchsorted(x, [lo, hi])
        i0 = max(0, int(bounds[0]) - 1)
        i1 = min(len(x), int(bounds[1]) + 1)
        if i1 - i0 < 2:
            return None
        xs, ys = x[i0:i1], y[i0:i1] * self.y_scale + trace.offset
        px = rect.left() + (xs - lo) / max(hi - lo, 1e-12) * rect.width()
        py = self.y_to_px(ys, rect)
        columns = self.columns(rect)
        if len(px) <= columns:
            return self._polyline(px, py)
        # Columns are contiguous because x increases, so the group boundaries
        # are a comparison and the reduction is a `reduceat` - no per-point
        # Python anywhere in the decimation itself.
        col = np.clip(((px - rect.left()) / max(1, rect.width())
                       * columns).astype(np.int64), 0, columns - 1)
        starts = np.flatnonzero(np.concatenate(([True], col[1:] != col[:-1])))
        return self._columns(px[starts],
                             np.minimum.reduceat(py, starts),
                             np.maximum.reduceat(py, starts))

    def _columns(self, cx, top, bottom):
        """One point where the column is flat, two where it is not - top then
        bottom, so the polyline goes DOWN through a peak instead of jumping
        over it.

        Built with `repeat` and a cumulative index rather than a loop over
        columns: a Python loop over a thousand columns costs more than the
        points it saves, which is how the first cut of this made the window
        slower rather than faster.
        """
        spiky = (bottom - top) > 0.5
        counts = np.where(spiky, 2, 1)
        ends = np.cumsum(counts)
        heads = ends - counts
        px = np.repeat(cx, counts)
        py = np.empty(int(ends[-1]), dtype=float)
        py[heads] = top
        py[ends[spiky] - 1] = bottom[spiky]
        return self._polyline(px, py)

    @staticmethod
    def _polyline(px, py):
        poly = QPolygonF()
        for a, b in zip(px.tolist(), py.tolist()):
            poly.append(QPointF(a, b))
        return poly

    def _paint_cursor(self, p):
        if self._cursor is None:
            return
        rect = self.plot_rect()
        x = int(self._cursor.x())
        if not (rect.left() <= x <= rect.right()):
            return
        p.setPen(QPen(_CURSOR, 1, Qt.DashLine))
        p.drawLine(x, rect.top(), x, rect.bottom() - _TICKS_H)

    def _paint_band(self, p):
        drag = self._drag
        if drag is None or not drag["mode"].startswith("zoom") \
                or self._cursor is None:
            return
        rect = self.plot_rect()
        top, bottom = rect.top(), rect.bottom() - _TICKS_H
        x0, y0 = drag["px"], drag["py"]
        x1 = _clamp(self._cursor.x(), rect.left(), rect.right())
        y1 = _clamp(self._cursor.y(), top, bottom)
        if drag["mode"] == "zoom_h":
            band = QRect(int(min(x0, x1)), top, int(abs(x1 - x0)),
                         bottom - top)
        elif drag["mode"] == "zoom_v":
            band = QRect(rect.left(), int(min(y0, y1)), rect.width(),
                         int(abs(y1 - y0)))
        else:
            band = QRect(int(min(x0, x1)), int(min(y0, y1)),
                         int(abs(x1 - x0)), int(abs(y1 - y0)))
        p.fillRect(band, _BAND)
        p.setPen(QPen(_BAND_EDGE, 1, Qt.DashLine))
        p.drawRect(band)


def _clamp(value, lo, hi):
    return max(lo, min(hi, value))


def _close(a, b, tol=1e-3):
    span = abs(b[1] - b[0]) or 1.0
    return abs(a[0] - b[0]) < span * tol and abs(a[1] - b[1]) < span * tol


class TraceOptions(QDialog):
    """One crystal's own settings: colour, source, range.

    Reached by right-clicking the LINE or its tick box, which is Christian's
    call and the right one - "clicking the line is more intuitive and doesn't
    require tab switching". Everything here is stored on the structure, so it
    survives the window being closed and rides the savefile.
    """

    def __init__(self, parent, obj, colour):
        super().__init__(parent)
        self.setWindowTitle("Pattern settings - {}".format(obj.name))
        self.obj = obj
        settings = pxrd.settings_of(obj.structure)
        self._colour = QColor(settings.get("colour") or colour)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        lay.addLayout(form)

        self.colour_btn = QPushButton()
        self.colour_btn.setFixedHeight(22)
        self._show_colour()
        self.colour_btn.clicked.connect(lambda _c=False: self._pick_colour())
        form.addRow("Colour", self.colour_btn)

        self.source = QComboBox()
        self.source.setEditable(True)
        self.source.setInsertPolicy(QComboBox.NoInsert)
        self.source.setMinimumWidth(240)
        for label, spec in pxrd.SOURCES:
            self.source.addItem(label, spec)
        text = settings.get("source") or ""
        if not text:
            text = format_wavelength(settings["wavelength"])
        index = self.source.findData(text)
        if index >= 0:
            self.source.setCurrentIndex(index)
        else:
            self.source.setCurrentText(text)
        self.source.setToolTip(SOURCE_HELP)
        form.addRow("Radiation", self.source)

        self.energy = QLabel("")
        form.addRow("", self.energy)

        row = QHBoxLayout()
        self.tt_min = NumberBox()
        self.tt_max = NumberBox()
        for spin, value in ((self.tt_min, settings["two_theta_min"]),
                            (self.tt_max, settings["two_theta_max"])):
            spin.setRange(0.5, 179.0)
            spin.setDecimals(1)
            spin.setSingleStep(5.0)
            spin.setValue(float(value))
            spin.setMaximumWidth(80)
            row.addWidget(spin)
        row.addStretch(1)
        form.addRow("2 theta range", _wrap(row))

        # Everything the GLOBAL row can set, this can set for one line -
        # which is the whole point of calling those globals "overrides".
        self.fwhm = NumberBox()
        self.fwhm.setRange(0.001, 5.0)
        self.fwhm.setDecimals(3)
        self.fwhm.setSingleStep(0.05)
        self.fwhm.setValue(float(settings["fwhm"]))
        self.fwhm.setMaximumWidth(90)
        form.addRow("Peak width (FWHM)", self.fwhm)

        self.shape = QComboBox()
        for key, label in ((pxrd.SHAPE_PSEUDO_VOIGT, "pseudo-Voigt"),
                           (pxrd.SHAPE_GAUSSIAN, "Gaussian"),
                           (pxrd.SHAPE_LORENTZIAN, "Lorentzian")):
            self.shape.addItem(label, key)
        index = self.shape.findData(settings["shape"])
        self.shape.setCurrentIndex(index if index >= 0 else 0)
        form.addRow("Peak shape", self.shape)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                        | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)
        self.source.currentTextChanged.connect(lambda _t: self._describe())
        self._describe()

    def _show_colour(self):
        self.colour_btn.setStyleSheet(
            "background: {}; border: 1px solid #666;".format(
                self._colour.name()))
        self.colour_btn.setText(self._colour.name())

    def _pick_colour(self):
        chosen = QColorDialog.getColor(self._colour, self, "Trace colour")
        if chosen.isValid():
            self._colour = chosen
            self._show_colour()

    def _describe(self):
        """Say what the source text was UNDERSTOOD as, while it is being
        typed. A source box that silently falls back to Cu when it cannot
        read what you wrote is how a whole pattern comes out at the wrong
        angles with nothing on screen to say so."""
        try:
            components = pxrd.parse_source(self.source_text())
        except pxrd.SourceError as exc:
            self.energy.setText("<span style='color:#d08a8a;'>{}</span>"
                                .format(exc))
            self.buttons.button(QDialogButtonBox.Ok).setEnabled(False)
            return
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(True)
        primary = components[0][0]
        self.energy.setText(
            "<span style='color:#9a9a9a;'>{}  =  {:.4f} keV</span>".format(
                pxrd.source_label(components), pxrd.energy_kev(primary)))

    def source_text(self):
        """See `PxrdWindow.source_text` - a typed row has no item data."""
        typed = self.source.currentText().strip()
        index = self.source.currentIndex()
        if index >= 0 and typed == self.source.itemText(index):
            data = self.source.itemData(index)
            if data:
                return str(data)
        return typed

    def apply(self):
        """Write it back onto the structure."""
        if self.tt_max.value() <= self.tt_min.value():
            self.tt_max.setValue(min(179.0, self.tt_min.value() + 1.0))
        pxrd.set_settings(self.obj.structure,
                          source=self.source_text(),
                          colour=self._colour.name(),
                          two_theta_min=float(self.tt_min.value()),
                          two_theta_max=float(self.tt_max.value()),
                          fwhm=float(self.fwhm.value()),
                          shape=str(self.shape.currentData()))


#: A tick box carries a NAME, and a COD entry's name is a sentence
#: ("Luciferin 6'-ethyl ether sodium salt monohydrate"). Christian: abbreviate
#: "with '...' after like 10 chars and the full name only be shown on hover".
LABEL_CHARS = 12


def short_name(name, limit=LABEL_CHARS):
    name = str(name or "")
    return name if len(name) <= limit else name[:limit].rstrip() + "..."


SOURCE_HELP = (
    "A wavelength in Angstrom (1.5406), an ENERGY (17.5 keV, 8040 eV), a "
    "named line (Cu Ka1, Mo Ka2), or a doublet with its intensity ratio "
    "(Cu Ka1+Ka2 2:1). A lab tube really does emit the doublet, which is why "
    "peaks past about 40 degrees look split.")


def format_wavelength(value):
    """A wavelength as text that reads back as the SAME number.

    `{:.5f}` renders Cu K-alpha1 as "1.54060", and a box that hands that back
    is describing a different wavelength - which silently recomputed every
    pattern on every edit and moved every peak by a ten-thousandth of a
    degree. Ten significant figures round-trips and still reads cleanly.
    """
    return "{:.10g}".format(float(value))


def _wrap(layout):
    holder = QWidget()
    layout.setContentsMargins(0, 0, 0, 0)
    holder.setLayout(layout)
    return holder


class AxisLimits(QDialog):
    """Type the x and y range. Reached by `M` or from the right-click menu,
    because it is a thing people do twice a session and it was costing a row
    of the window the whole time."""

    def __init__(self, parent, x_range, y_range, x_label):
        super().__init__(parent)
        self.setWindowTitle("Axis limits")
        lay = QVBoxLayout(self)
        form = QFormLayout()
        lay.addLayout(form)
        self.boxes = {}
        for key, label, value in (("x0", x_label + " from", x_range[0]),
                                  ("x1", x_label + " to", x_range[1]),
                                  ("y0", "Intensity from", y_range[0]),
                                  ("y1", "Intensity to", y_range[1])):
            box = QLineEdit("{:g}".format(round(float(value), 6)))
            box.setPlaceholderText("auto")
            self.boxes[key] = box
            form.addRow(label, box)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                   | QDialogButtonBox.Cancel
                                   | QDialogButtonBox.Reset)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.Reset).setText("Auto")
        buttons.button(QDialogButtonBox.Reset).clicked.connect(self._auto)
        lay.addWidget(buttons)

    def _auto(self):
        for box in self.boxes.values():
            box.clear()

    def value(self, key):
        """A decimal COMMA is a decimal point here too."""
        try:
            return float(self.boxes[key].text().strip().replace(",", "."))
        except (TypeError, ValueError):
            return None

    def ranges(self):
        """`(x_range, y_range)`, each None where it should go back to auto."""
        x0, x1 = self.value("x0"), self.value("x1")
        y0, y1 = self.value("y0"), self.value("y1")
        x = None if x0 is None or x1 is None or x1 <= x0 else (x0, x1)
        y = None if y0 is None or y1 is None or y1 <= y0 else (y0, y1)
        return x, y


class ReflectionTable(QWidget):
    """The hkl list, with the systematically absent reflections in it.

    The columns are the ones a reflection table carries: the indices, the
    d-spacing, the angle, Q, the multiplicity, |F|^2, the
    Lorentz-polarisation factor and the relative intensity. The ABSENT ones
    are the reason the tab exists - a list that only shows what is there
    cannot tell you why something is missing, and "is 100 allowed?" is the
    question people open an hkl list to answer.
    """

    COLUMNS = ("h", "k", "l", "d / A", "2 theta", "Q / 1/A", "mult",
               "|F|^2", "LP", "I rel", "note")

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        # Wrapping, so an eleven-column table and a long combo cannot set the
        # WINDOW's minimum width - which is what stopped it being made narrow
        # even though the plot itself is happy at any size.
        row = FlowLayout(spacing=6)
        row.addWidget(QLabel("Crystal"))
        self.which = QComboBox()
        self.which.setMinimumWidth(140)
        row.addWidget(self.which)
        self.show_absent = QCheckBox("Show absences")
        self.show_absent.setChecked(True)
        self.show_absent.setToolTip(
            "A reflection the lattice allows and the symmetry extinguishes. "
            "|F|^2 being zero IS the definition here - nothing in the "
            "calculation knows what an F-centred lattice is, which is what "
            "makes the list worth trusting.")
        row.addWidget(self.show_absent)
        self.count = QLabel("")
        row.addWidget(self.count)
        self.export_btn = QPushButton("Export list...")
        row.addWidget(self.export_btn)
        lay.addLayout(row)

        self.table = QTableWidget(0, len(self.COLUMNS), self)
        self.table.setHorizontalHeaderLabels(list(self.COLUMNS))
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMinimumWidth(1)
        self.table.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        lay.addWidget(self.table, 1)
        self.note = QLabel("")
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color: #c8a45a;")
        lay.addWidget(self.note)
        self._pattern = None

    def set_pattern(self, pattern):
        self._pattern = pattern
        self.refill()

    def refill(self):
        pattern = self._pattern
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        if pattern is None:
            self.count.setText("")
            self.note.setText("")
            self.table.setSortingEnabled(True)
            return
        keep = [r for r in pattern.reflections
                if self.show_absent.isChecked() or not r.absent]
        top = max((r.intensity for r in pattern.reflections), default=0.0) or 1.0
        self.table.setRowCount(len(keep))
        for row, r in enumerate(keep):
            values = (r.h, r.k, r.l, r.d, r.two_theta, r.q, r.multiplicity,
                      r.f2, r.lp, 100.0 * r.intensity / top,
                      "absent" if r.absent else "")
            for column, value in enumerate(values):
                if isinstance(value, str):
                    item = QTableWidgetItem(value)
                else:
                    item = _NumericItem(value, self._format(column, value))
                if r.absent:
                    item.setForeground(QColor(140, 140, 140))
                self.table.setItem(row, column, item)
        self.table.setSortingEnabled(True)
        absent = sum(1 for r in pattern.reflections if r.absent)
        self.count.setText("{} shown, {} absent".format(len(keep), absent))
        self.note.setText(pattern.note)
        self.table.resizeColumnsToContents()

    @staticmethod
    def _format(column, value):
        if column in (0, 1, 2, 6):
            return "{:d}".format(int(value))
        if column == 3:
            return "{:.5f}".format(value)
        if column in (4, 5):
            return "{:.4f}".format(value)
        if column == 9:
            return "{:.2f}".format(value)
        return "{:.4g}".format(value)

    def rows(self):
        """The table as plain data, for an export."""
        pattern = self._pattern
        if pattern is None:
            return []
        top = max((r.intensity for r in pattern.reflections),
                  default=0.0) or 1.0
        return [(r.h, r.k, r.l, r.d, r.two_theta, r.q, r.multiplicity, r.f2,
                 r.lp, 100.0 * r.intensity / top, "absent" if r.absent else "")
                for r in pattern.reflections
                if self.show_absent.isChecked() or not r.absent]


class _NumericItem(QTableWidgetItem):
    """Sorts as a NUMBER. `QTableWidgetItem` compares its TEXT, so 100 would
    sort before 98 and a d-spacing column would be nonsense (round 86's
    lesson, in the one place where letting Qt sort is the right call because
    there is no ranking to preserve)."""

    def __init__(self, value, text):
        super().__init__(text)
        self._value = float(value)

    def __lt__(self, other):
        if isinstance(other, _NumericItem):
            return self._value < other._value
        return super().__lt__(other)


class PxrdWindow(QDialog):
    """Simulated powder patterns for the crystals in the scene.

    Modeless on purpose: the comparison being made is between this and the
    viewport, so a window that blocks the program is the wrong shape.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Simulated powder pattern (PXRD)")
        self.setModal(False)
        # A QDialog gets a close button and nothing else. This is a TOOL
        # WINDOW - modeless, kept open beside the viewport, and a plot is the
        # first thing anyone wants full-screen - so it asks for the ordinary
        # frame. OWB's spectrum windows are Toplevels with real WM
        # decorations for exactly this reason.
        self.setWindowFlags(Qt.Window | Qt.WindowMinimizeButtonHint
                            | Qt.WindowMaximizeButtonHint
                            | Qt.WindowCloseButtonHint)
        self.rows = []              # [(obj, QCheckBox, colour)]
        self._loading = False
        #: Computed patterns, keyed on what they were computed FROM. A change
        #: to the peak width or the stacking must not re-run the structure
        #: factor sum - that is the expensive half, and it depends on the
        #: structure, the source and the range and on nothing else.
        self._patterns = {}
        self._profiles = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        self.tabs = QTabWidget(self)
        lay.addWidget(self.tabs, 1)
        self.tabs.addTab(self._build_pattern_page(), "Pattern")
        self.tabs.addTab(self._build_advanced_page(), "Advanced")
        self.hkl = ReflectionTable(self)
        self.hkl.which.currentIndexChanged.connect(lambda _i: self._sync_hkl())
        self.hkl.show_absent.toggled.connect(lambda _o: self._sync_hkl())
        self.hkl.export_btn.clicked.connect(
            lambda _c=False: self.export_reflections())
        self.tabs.addTab(self.hkl, "Reflections (hkl)")
        self.tabs.currentChanged.connect(lambda _i: self._sync_hkl())
        self._hkl_tab = self.tabs.count() - 1
        self.resize(*self.opening_size())

    #: What the window opens at, before it is clamped to the screen. Wider
    #: than tall because a diffractogram is, and small enough to sit beside
    #: the viewport rather than cover it.
    PREFERRED_SIZE = (900, 560)

    def opening_size(self):
        """`(width, height)` in LOGICAL pixels, clamped to the screen.

        `resize` takes logical pixels, so at 150% scaling a 980 x 660 window
        is 1470 x 990 real ones - taller than the working area of a 1080p
        display, which is why the controls ended up below the bottom edge
        with no way to reach them. Asked of the screen rather than assumed,
        because that is the number that differs between the two dev machines.
        """
        width, height = self.PREFERRED_SIZE
        screen = self.screen()
        if screen is not None:
            available = screen.availableGeometry()
            width = min(width, int(available.width() * 0.9))
            height = min(height, int(available.height() * 0.85))
        return max(480, width), max(360, height)

    # -------------------------------------------------------- construction
    def _build_pattern_page(self):
        page = QWidget(self)
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(5)

        self.plot = PxrdPlot(page)
        # Low enough that the WINDOW can be made small; the plot still gets
        # every pixel the layout has left over.
        self.plot.setMinimumHeight(160)
        self.plot.hovered.connect(self._on_hover)
        self.plot.mode_changed.connect(self._on_mode)
        self.plot.view_changed.connect(self._show_view)
        self.plot.trace_menu.connect(self._trace_menu)

        # The offset slider is VERTICAL and beside the plot, because that is
        # what it does - and because a horizontal one under the plot spends
        # height the plot wanted.
        middle = QHBoxLayout()
        middle.setContentsMargins(0, 0, 0, 0)
        middle.setSpacing(4)
        middle.addWidget(self.plot, 1)
        self.offset = QSlider(Qt.Vertical)
        self.offset.setRange(0, 200)
        self.offset.setValue(110)
        self.offset.setMaximumWidth(20)
        self.offset.setToolTip(
            "Vertical spacing between stacked traces, as a percentage of one "
            "pattern's full height. 0 draws them on top of one another.")
        middle.addWidget(self.offset)
        lay.addLayout(middle, 1)

        self.readout = QLabel(" ")
        self.readout.setMinimumHeight(16)
        self.readout.setMinimumWidth(1)
        self.readout.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        lay.addWidget(self.readout)

        self.which = QWidget(page)
        self._which_lay = FlowLayout(self.which, spacing=10)
        self._which_lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.which)

        # THE FOUR CONTROLS THAT ARE TOUCHED CONSTANTLY, and no others. Each
        # is a GLOBAL OVERRIDE: changing it here writes to every crystal, and
        # each crystal can still be given its own from the right-click menu.
        controls = FlowLayout(spacing=6)
        controls.addWidget(QLabel("Radiation"))
        self.source = QComboBox()
        self.source.setEditable(True)
        self.source.setMinimumWidth(150)
        # NoInsert, or pressing Return on a typed wavelength makes it an ITEM
        # with no data behind it - and `source_text` then reads that empty
        # data instead of what was typed, which is why a custom wavelength
        # "was not accepted".
        self.source.setInsertPolicy(QComboBox.NoInsert)
        for label, spec in pxrd.SOURCES:
            self.source.addItem(label, spec)
        self.source.setToolTip(SOURCE_HELP)
        controls.addWidget(self.source)
        controls.addWidget(QLabel("2 theta"))
        self.tt_min = NumberBox()
        self.tt_max = NumberBox()
        for spin, value in ((self.tt_min, pxrd.DEFAULT_TWO_THETA[0]),
                            (self.tt_max, pxrd.DEFAULT_TWO_THETA[1])):
            spin.setRange(0.5, 179.0)
            spin.setDecimals(1)
            spin.setSingleStep(5.0)
            spin.setValue(value)
            spin.setMaximumWidth(70)
            controls.addWidget(spin)
        controls.addWidget(QLabel("FWHM"))
        self.fwhm = NumberBox()
        self.fwhm.setRange(0.001, 5.0)
        self.fwhm.setDecimals(3)
        self.fwhm.setSingleStep(0.05)
        self.fwhm.setValue(pxrd.DEFAULT_FWHM)
        self.fwhm.setMaximumWidth(74)
        self.fwhm.setToolTip(
            "Peak width, in the units of the axis. An INSTRUMENT property, "
            "not the structure's - it does not move a single peak.")
        controls.addWidget(self.fwhm)
        lay.addLayout(controls)

        self.note = QLabel("")
        self.note.setWordWrap(True)
        self.note.setMinimumWidth(1)
        self.note.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Minimum)
        # CAPPED. A word-wrapped QLabel reports the height it needs AT ITS
        # MINIMUM WIDTH, so this one asked for 219 px and pushed the window's
        # own minimum height to 634 - which no `resize` can undo. Two lines,
        # and the whole text is the tooltip (round 90d, from the other side:
        # there the label had to be allowed to shrink, here it has to be
        # stopped from demanding).
        self.note.setMaximumHeight(30)
        self.note.setStyleSheet("color: #c8a45a; font-size: 11px;")
        lay.addWidget(self.note)

        self.mode_label = QLabel("")
        self.mode_label.setStyleSheet("color: #6ea8ff; font-weight: bold;")
        self.mode_label.setMinimumWidth(1)
        self.mode_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        lay.addWidget(self.mode_label)

        # A QPushButton in a QDialog is an AUTO-DEFAULT button, so Return
        # would fire whichever one Qt picked from anywhere in the window. On
        # a plot, Return means nothing at all.
        for button in page.findChildren(QPushButton):
            button.setAutoDefault(False)
            button.setDefault(False)
        self.source.currentIndexChanged.connect(self._source_chosen)
        self.source.lineEdit().editingFinished.connect(self._changed)
        for spin in (self.tt_min, self.tt_max, self.fwhm):
            spin.valueChanged.connect(self._changed)
        self.offset.valueChanged.connect(self._layout_changed)
        return page

    def _build_advanced_page(self):
        """Everything that is set once and then left alone.

        The Pattern tab is for the four controls that are touched constantly;
        putting the rest beside them spent the plot's own height on things
        nobody moves twice in a session.
        """
        page = QWidget(self)
        lay = QVBoxLayout(page)
        form = QFormLayout()
        # The FIELD column is allowed to shrink: a form whose widest row sets
        # the window's minimum width is the same fault as a fixed control row
        # (round 21), and this page is the one nobody has open while they are
        # trying to make the window small.
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        lay.addLayout(form)

        self.shape = QComboBox()
        for key, label in ((pxrd.SHAPE_PSEUDO_VOIGT, "pseudo-Voigt"),
                           (pxrd.SHAPE_GAUSSIAN, "Gaussian"),
                           (pxrd.SHAPE_LORENTZIAN, "Lorentzian")):
            self.shape.addItem(label, key)
        self.shape.setToolTip(
            "A real diffractometer peak is neither a Gaussian nor a "
            "Lorentzian; pseudo-Voigt is the mixture of the two.")
        form.addRow("Peak shape", self.shape)

        self.q_axis = QCheckBox("Q instead of 2 theta")
        self.q_axis.setToolTip(
            "2 theta depends on the wavelength and Q does not, so patterns "
            "simulated at different wavelengths can only honestly share a Q "
            "axis. Forced on when they differ.")
        form.addRow("Axis", self.q_axis)

        self.margin = QSpinBox()
        self.margin.setRange(0, 40)
        self.margin.setValue(5)
        self.margin.setSuffix(" %")
        self.margin.setMaximumWidth(70)
        self.margin.setToolTip("Breathing room above and below the traces. A "
                               "peak touching the frame reads as clipped.")
        form.addRow("Vertical margin", self.margin)

        row = FlowLayout(spacing=6)
        for label, slot, tip in (
                ("Fit view", lambda _c=False: self._fit(),
                 "Frame everything again (F, or Home)"),
                ("Axis limits...", lambda _c=False: self.edit_limits(),
                 "Type the x and y range (M)"),
                ("Save image...", lambda _c=False: self.save_image(),
                 "The plot as a PNG (Ctrl+S)"),
                ("Export data...", lambda _c=False: self.export(),
                 "The curves and the indexed reflection list, as CSV")):
            button = QPushButton(label)
            button.setAutoDefault(False)
            button.setToolTip(tip)
            button.clicked.connect(slot)
            row.addWidget(button)
        lay.addLayout(row)

        keys = QLabel(
            "<b>Over the plot</b><br>"
            "wheel = scale intensity &nbsp; Ctrl+wheel = zoom x<br>"
            "<b>Z</b> zoom (horizontal / vertical / box) &nbsp; "
            "<b>P</b> pan &nbsp; <b>Esc</b> leave the mode<br>"
            "<b>F</b> or <b>Home</b> reset (x, then y, then intensity) &nbsp; "
            "<b>M</b> axis limits<br>"
            "<b>R</b> recompute &nbsp; <b>Ctrl+S</b> save &nbsp; "
            "<b>Ctrl+W</b> close<br>"
            "<b>Right-click</b> a line or its tick box for that crystal's "
            "own colour, radiation, range and width")
        keys.setStyleSheet("color: #9a9a9a;")
        keys.setWordWrap(True)
        keys.setMinimumWidth(1)
        lay.addWidget(keys)
        lay.addStretch(1)

        self.shape.currentIndexChanged.connect(self._changed)
        self.q_axis.toggled.connect(self._changed)
        self.margin.valueChanged.connect(self._layout_changed)
        return page

    # ------------------------------------------------------------ hotkeys
    def keyPressEvent(self, ev):
        """OWB's plot keys. The plain letters only fire when a TEXT FIELD does
        not have focus, so typing a range into a box cannot redraw the
        window - which is the same rule OWB uses by binding them on the
        canvas rather than on the window."""
        key, mods = ev.key(), ev.modifiers()
        if mods & Qt.ControlModifier and key == Qt.Key_S:
            self.save_image()
            return
        if mods & Qt.ControlModifier and key == Qt.Key_W:
            self.close()
            return
        if isinstance(self.focusWidget(), (QLineEdit, QDoubleSpinBox,
                                           QSpinBox, QComboBox)):
            super().keyPressEvent(ev)
            return
        if key in (Qt.Key_R, Qt.Key_F5):
            self._patterns.clear()
            self._profiles.clear()
            self.recompute()
        elif key == Qt.Key_M:
            self.edit_limits()
        elif key == Qt.Key_Escape:
            # Never let Escape CLOSE the window: this is a plot, and Esc is
            # what leaves a zoom mode.
            self.plot.set_mode(None)
        else:
            self.plot.keyPressEvent(ev)
            if not ev.isAccepted():
                super().keyPressEvent(ev)

    # ------------------------------------------------------------- content
    def set_objects(self, objects, selected=()):
        """Which crystals the window is about, and which start ticked.

        Christian: "If I select 3 structures and then launch it, only those
        three should be ticked and shown." A selection is a statement about
        what you are working on, and a window that opens on everything makes
        you untick the rest by hand - so a selection that names any crystal
        decides the ticks, and only an empty one falls back to what each
        crystal last remembered.
        """
        crystals = [o for o in objects
                    if (getattr(getattr(o, "structure", None), "metadata", None)
                        or {}).get("cell")]
        chosen = {int(i) for i in (selected or ())}
        chosen &= {o.id for o in crystals}
        while self._which_lay.count():
            item = self._which_lay.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # setParent(None) first: `deleteLater` alone leaves the widget
                # a child of the layout's parent, still painting at its old
                # geometry until the event loop gets round to it (round 90c).
                widget.setParent(None)
                widget.deleteLater()
        self.rows = []
        self._loading = True
        for i, obj in enumerate(crystals):
            settings = pxrd.settings_of(obj.structure)
            colour = settings.get("colour") or PALETTE[i % len(PALETTE)]
            box = QCheckBox(short_name(obj.name))
            box.setChecked(obj.id in chosen if chosen
                           else bool(settings.get("enabled", True)))
            box.setStyleSheet("QCheckBox { color: " + colour + "; }")
            # The FULL name on hover: the label is a legend entry and has to
            # fit a row of them, but the name is what tells two determinations
            # of one compound apart.
            box.setToolTip("{}\n\nRight-click for this crystal's own colour, "
                           "radiation, range and peak width".format(obj.name))
            box.setContextMenuPolicy(Qt.CustomContextMenu)
            box.customContextMenuRequested.connect(
                lambda pos, o=obj, b=box: self._label_menu(o, b, pos))
            box.toggled.connect(self._on_enabled)
            self._which_lay.addWidget(box)
            self.rows.append((obj, box, colour))
        self.hkl.which.clear()
        for obj, _box, _c in self.rows:
            self.hkl.which.addItem(obj.name, obj.id)
        self._loading = False
        # DELIBERATELY not written back. A selection says which crystals this
        # OPENING is about; it is not a decision about the crystals, and
        # writing it would mean opening the window on one of five silently
        # switched the other four off in the savefile. Ticking a box by hand
        # does write, because that IS the decision.
        self._load_settings()
        self.recompute(keep_view=False)
        self.plot.setFocus(Qt.OtherFocusReason)

    def _subject(self):
        """The crystal whose stored settings the shared controls show: the
        first ticked one, because that is the trace the eye starts on."""
        for obj, box, _c in self.rows:
            if box.isChecked():
                return obj
        return self.rows[0][0] if self.rows else None

    def _load_settings(self):
        subject = self._subject()
        if subject is None:
            return
        s = pxrd.settings_of(subject.structure)
        self._loading = True
        text = s.get("source") or format_wavelength(s["wavelength"])
        index = self.source.findData(text)
        if index >= 0:
            self.source.setCurrentIndex(index)
        else:
            self.source.setCurrentText(text)
        self.tt_min.setValue(float(s["two_theta_min"]))
        self.tt_max.setValue(float(s["two_theta_max"]))
        self.fwhm.setValue(float(s["fwhm"]))
        shape = self.shape.findData(s["shape"])
        self.shape.setCurrentIndex(shape if shape >= 0 else 0)
        self._loading = False

    def source_text(self):
        """What the user means by the radiation box.

        A preset carries its SPEC as item data ("Cu Ka1+Ka2 2:1" behind the
        label "Cu Ka1+Ka2 (2:1)"), so a chosen row is read from the data; but
        anything TYPED is the text, and `itemData` for a typed row is None.
        The first cut returned `str(None)` for exactly that case, which is
        why a custom wavelength "was not accepted".
        """
        typed = self.source.currentText().strip()
        index = self.source.currentIndex()
        if index >= 0 and typed == self.source.itemText(index):
            data = self.source.itemData(index)
            if data:
                return str(data)
        return typed

    def _source_chosen(self, _index):
        if not self._loading:
            self._changed()

    def _on_enabled(self, _on=False):
        if self._loading:
            return
        for obj, box, _c in self.rows:
            pxrd.set_settings(obj.structure, enabled=bool(box.isChecked()))
        self._load_settings()
        self.recompute()

    def _changed(self, *_a):
        """A shared control moved: it is a GLOBAL OVERRIDE.

        Christian: "The options radiation, FWHM, 2theta range should all be
        global overwrites while every one of them should be also be settable
        per line." So this writes to EVERY crystal, ticked or not - an
        override that skipped the ones you cannot see would leave a crystal
        with a stale wavelength waiting to surprise you - and the right-click
        menu is where one line is given its own afterwards.
        """
        if self._loading:
            return
        if self.tt_max.value() <= self.tt_min.value():
            self.tt_max.setValue(min(179.0, self.tt_min.value() + 1.0))
        text = self.source_text()
        try:
            pxrd.parse_source(text)
        except pxrd.SourceError as exc:
            # SAID, not swallowed. A source box that quietly keeps the old
            # wavelength draws a whole pattern at the wrong angles.
            self.note.setText("Radiation: {} - the pattern is still at {}"
                              .format(exc, pxrd.source_label(
                                  pxrd.components_of(
                                      pxrd.settings_of(
                                          self._subject().structure))
                                  if self._subject() is not None else [])))
            return
        for obj, _box, _c in self.rows:
            pxrd.set_settings(
                obj.structure, source=text,
                two_theta_min=float(self.tt_min.value()),
                two_theta_max=float(self.tt_max.value()),
                fwhm=float(self.fwhm.value()),
                shape=str(self.shape.currentData()))
        self.note.setText("")
        self.recompute()

    def _layout_changed(self, *_a):
        """The stacking or the margin: a DRAWING change, so nothing is
        recomputed - only the traces are re-laid-out."""
        self.offset.setToolTip(
            "Vertical spacing between stacked traces: {}% of one pattern's "
            "full height.".format(self.offset.value()))
        if not self._loading:
            self.recompute()

    # ---------------------------------------------------------- the traces
    @staticmethod
    def _signature(obj, settings):
        """What a pattern depends on. Deliberately NOT the peak width or the
        shape: those are the profile's business, and re-running the structure
        factor sum for them is the expensive mistake this cache exists to
        stop."""
        s = obj.structure
        coords = getattr(s, "coords", None)
        stamp = 0.0 if coords is None else float(np.asarray(coords).sum())
        return (obj.id, s.n_atoms, round(stamp, 6),
                tuple(tuple(c) for c in pxrd.components_of(settings)),
                round(float(settings["two_theta_min"]), 4),
                round(float(settings["two_theta_max"]), 4))

    def pattern_of(self, obj, keep_absent=False):
        """This crystal's pattern, computed at most once per input."""
        settings = pxrd.settings_of(obj.structure)
        key = self._signature(obj, settings) + (bool(keep_absent),)
        cached = self._patterns.get(key)
        if cached is None:
            cached = pxrd.pattern_for(obj.structure, name=obj.name,
                                      keep_absent=keep_absent)
            if cached is None:
                return None
            # Bounded so a long session cannot grow without limit; the key
            # carries the coordinates, so an edited crystal makes new entries.
            if len(self._patterns) > 64:
                self._patterns.clear()
            self._patterns[key] = cached
        return cached

    def recompute(self, keep_view=True):
        """Rebuild the traces and draw them."""
        patterns, notes = [], []
        for obj, box, colour in self.rows:
            if not box.isChecked():
                continue
            try:
                pattern = self.pattern_of(obj)
            except Exception as exc:          # never take the window down
                notes.append("{}: {}".format(obj.name, exc))
                continue
            if pattern is None:
                continue
            settings = pxrd.settings_of(obj.structure)
            patterns.append((obj, settings.get("colour") or colour, pattern))
            if pattern.note:
                notes.append("{}: {}".format(obj.name, pattern.note))
        axis = pxrd.common_axis([p.wavelength for _o, _c, p in patterns])
        forced = axis == pxrd.AXIS_Q
        if forced:
            notes.insert(0, "Simulated at different wavelengths, so these are "
                            "drawn against Q - the same reflection would sit "
                            "at two angles on a 2 theta axis.")
        self._loading = True
        if forced:
            self.q_axis.setChecked(True)
        self.q_axis.setEnabled(not forced)
        self._loading = False
        if self.q_axis.isChecked():
            axis = pxrd.AXIS_Q
        gap = float(self.offset.value())
        traces = []
        n = max(1, len(patterns))
        for i, (obj, colour, pattern) in enumerate(patterns):
            settings = pxrd.settings_of(obj.structure)
            x, y, sampler, fwhm = self.profile_of(pattern, axis, settings)
            traces.append(Trace(obj, obj.name, colour, x, y, pattern,
                                gap * (n - 1 - i), sampler=sampler,
                                fwhm=fwhm))
        self.plot.y_margin = self.margin.value() / 100.0
        self.plot.set_traces(traces, axis, keep_view=keep_view)
        self.note.setText("  -  ".join(notes[:2]))
        self.note.setToolTip("\n".join(notes))
        self._show_view()
        self._sync_hkl()

    def profile_of(self, pattern, axis, settings):
        """The sampled curve, cached on everything it depends on."""
        fwhm, step = float(settings["fwhm"]), float(settings["step"])
        if axis == pxrd.AXIS_Q:
            # A width is in the units of the axis, and 0.1 degrees is not 0.1
            # inverse Angstrom. Converted at the middle of the range, which is
            # the honest single number for a curve that is a drawing aid
            # rather than a measurement.
            mid = sum(pattern.two_theta_range) / 2.0
            scale = abs(float(
                pxrd.q_from_two_theta(mid + 0.5, pattern.wavelength)
                - pxrd.q_from_two_theta(mid - 0.5, pattern.wavelength)))
            fwhm, step = fwhm * scale, step * scale
        key = (id(pattern), axis, round(fwhm, 6), round(step, 8),
               str(settings["shape"]))
        cached = self._profiles.get(key)
        if cached is None:
            shape = str(settings["shape"])
            x, raw = pxrd.profile(pattern, axis=axis, fwhm=fwhm, step=step,
                                  shape=shape, normalise=False)
            top = float(raw.max()) if raw.size else 0.0
            # ONE scale factor, shared by the stored curve and the sampler.
            # Normalising each view separately would make the curve rescale
            # itself as you zoom, which is the one thing a y axis must not do.
            scale = (100.0 / top) if top > 0.0 else 1.0
            # The peak list is the same at every zoom, so it is computed once
            # here rather than per frame.
            peaks = pxrd.peak_positions(pattern, axis)

            def sampler(xs, _p=pattern, _a=axis, _f=fwhm, _s=shape,
                        _k=scale, _peaks=peaks):
                return pxrd.profile_at(_p, xs, axis=_a, fwhm=_f, shape=_s,
                                       peaks=_peaks) * _k

            cached = (x, raw * scale, sampler, fwhm)
            if len(self._profiles) > 64:
                self._profiles.clear()
            self._profiles[key] = cached
        return cached

    # -------------------------------------------------------- the hkl list
    def _sync_hkl(self):
        if self.tabs.currentIndex() != self._hkl_tab:
            return
        obj_id = self.hkl.which.currentData()
        obj = None
        for candidate, _box, _c in self.rows:
            if candidate.id == obj_id:
                obj = candidate
                break
        if obj is None:
            self.hkl.set_pattern(None)
            return
        self.hkl.set_pattern(self.pattern_of(obj, keep_absent=True))

    # ------------------------------------------------------ per-trace menus
    def build_trace_menu(self, trace):
        """The right-click menu for the PLOT, with the trace under the cursor
        first.

        Built separately from being shown, because `QMenu.exec` runs a modal
        event loop - a test that reaches it HANGS rather than failing, which
        is round 75's lesson about the worst shape a test problem can take.
        """
        menu = QMenu(self)
        if trace is not None:
            act = menu.addAction("Settings for {}...".format(trace.name))
            act.triggered.connect(
                lambda _c=False, o=trace.obj: self.edit_trace(o))
            hide = menu.addAction("Hide {}".format(trace.name))
            hide.triggered.connect(
                lambda _c=False, o=trace.obj: self._set_enabled(o, False))
            menu.addSeparator()
        for obj, _box, _c in self.rows:
            act = menu.addAction("{}...".format(obj.name))
            act.triggered.connect(lambda _c=False, o=obj: self.edit_trace(o))
        if not self.rows:
            menu.addAction("No crystals").setEnabled(False)
        menu.addSeparator()
        limits = menu.addAction("Axis limits...\tM")
        limits.triggered.connect(lambda _c=False: self.edit_limits())
        fit = menu.addAction("Fit view\tF")
        fit.triggered.connect(lambda _c=False: self._fit())
        return menu

    def build_label_menu(self, obj):
        """Right-click on a tick box - the same settings, for one crystal.

        Both routes, because Christian asked for both: "right clicking on a
        line in the plotting pane as well as right clicking on a label where
        the tick boxes are".
        """
        menu = QMenu(self)
        act = menu.addAction("Settings for {}...".format(obj.name))
        act.triggered.connect(lambda _c=False: self.edit_trace(obj))
        return menu

    def _trace_menu(self, trace, pos):
        self.build_trace_menu(trace).exec(pos)

    def _label_menu(self, obj, box, pos):
        self.build_label_menu(obj).exec(box.mapToGlobal(pos))

    def edit_trace(self, obj):
        dlg = TraceOptions(self, obj, self._colour_for(obj))
        if dlg.exec():
            dlg.apply()
            self._recolour(obj)
            self._load_settings()
            self.recompute()

    def _colour_for(self, obj):
        for candidate, _box, colour in self.rows:
            if candidate.id == obj.id:
                return colour
        return PALETTE[0]

    def _recolour(self, obj):
        colour = pxrd.settings_of(obj.structure).get("colour")
        if not colour:
            return
        for i, (candidate, box, _c) in enumerate(self.rows):
            if candidate.id == obj.id:
                box.setStyleSheet("QCheckBox { color: " + colour + "; }")
                self.rows[i] = (candidate, box, colour)

    def _set_enabled(self, obj, on):
        for candidate, box, _c in self.rows:
            if candidate.id == obj.id:
                box.setChecked(bool(on))

    # ------------------------------------------------------------- the view
    def _on_hover(self, text):
        self.readout.setText(text or " ")

    def _on_mode(self, text):
        self.mode_label.setText(text)
        if not text:
            self._show_view()

    def _show_view(self):
        """The view moved. Nothing to write any more - the limits live in a
        dialog now - but the readout of what is on screen still belongs
        somewhere, and the mode label is where the eye already is."""
        if self.plot.at_home_x() and self.plot.at_home_y():
            return
        lo, hi = self.plot.view_x()
        unit = ("deg" if self.plot.axis == pxrd.AXIS_TWO_THETA else "1/A")
        self.mode_label.setText(
            "{}    view {:g} - {:g} {}".format(
                self.plot.MODE_TEXT.get(self.plot.mode(), ""),
                round(lo, 4), round(hi, 4), unit))

    def edit_limits(self):
        """Type the x and y range (`M`, or the right-click menu)."""
        label = ("2 theta" if self.plot.axis == pxrd.AXIS_TWO_THETA else "Q")
        dlg = AxisLimits(self, self.plot.view_x(), self.plot.view_y(), label)
        if not dlg.exec():
            return
        x, y = dlg.ranges()
        self.plot._view_x = x
        self.plot._view_y = y
        self.plot.invalidate()
        self.plot.view_changed.emit()

    def _fit(self):
        while self.plot.reset_view():
            pass
        self.mode_label.setText("")

    # ----------------------------------------------------------- exporting
    def save_image(self, path=None):
        """The plot as it stands, as a PNG. Ctrl+S, which is what it is in
        OWB."""
        if path is None:
            path, _f = QFileDialog.getSaveFileName(
                self, "Save the plot", "pxrd.png",
                "PNG image (*.png);;JPEG image (*.jpg)")
        if not path:
            return None
        self.plot.grab().save(path)
        return path

    def export_reflections(self, path=None):
        rows = self.hkl.rows()
        if not rows:
            return None
        if path is None:
            path, _f = QFileDialog.getSaveFileName(
                self, "Export the reflection list", "reflections.csv",
                "Comma-separated values (*.csv)")
        if not path:
            return None
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("h,k,l,d_angstrom,two_theta_deg,q,multiplicity,"
                     "f_squared,lorentz_polarisation,relative_intensity,"
                     "note\n")
            for row in rows:
                fh.write(",".join(str(v) for v in row) + "\n")
        return path

    def export(self, path=None):
        """The curves AND the indexed reflection list, as one CSV.

        Both, because they answer different questions: the curve is what you
        overlay on a measurement, the reflection list is what you look an
        index up in.
        """
        if not self.plot.traces:
            return None
        if path is None:
            path, _f = QFileDialog.getSaveFileName(
                self, "Export the simulated pattern", "pxrd.csv",
                "Comma-separated values (*.csv)")
        if not path:
            return None
        axis = ("two_theta_deg" if self.plot.axis == pxrd.AXIS_TWO_THETA
                else "q_inv_angstrom")
        traces = self.plot.traces
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("# MoloM simulated powder pattern\n")
            for t in traces:
                fh.write("# {}: {}{}\n".format(
                    t.name, pxrd.source_label(t.pattern.components),
                    ("  (" + t.pattern.note + ")") if t.pattern.note else ""))
            fh.write(axis + "," + ",".join(t.name for t in traces) + "\n")
            first = traces[0]
            for i, x in enumerate(first.x):
                values = ["{:.6g}".format(t.y[i]) if i < len(t.y) else ""
                          for t in traces]
                fh.write("{:.6g},".format(x) + ",".join(values) + "\n")
            fh.write("\n# reflections\n")
            fh.write("structure,h,k,l,d_angstrom,two_theta_deg,q,"
                     "relative_intensity,multiplicity\n")
            for t in traces:
                top = t.pattern.strongest() or 1.0
                for r in t.pattern.reflections:
                    fh.write("{},{},{},{},{:.5f},{:.5f},{:.5f},{:.3f},{}\n"
                             .format(t.name, r.h, r.k, r.l, r.d, r.two_theta,
                                     r.q, 100.0 * r.intensity / top,
                                     r.multiplicity))
        return path
