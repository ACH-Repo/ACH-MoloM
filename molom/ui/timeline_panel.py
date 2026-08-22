"""The timeline pane: transport bar plus one draggable row per trajectory.

Collapsed it is the old single-line bar. Expanded (the ▾ button, or by
dragging the grip above it) it shows a row per animated object against a
shared time axis, with ONE playhead drawn across all of them — which is the
point of the scene clock: seeing that two trajectories are staggered is much
easier than reading two numbers.

Rows are custom-painted rather than built from widgets: a row is a bar on a
time axis, and laying that out with spacers would fight the axis mapping.
Everything the rows can change lives on `core.timeline`, so this file only
maps pixels to frames and back.

**The transport bar carries three numbers and no more** (round 77):
`Frame Start`, `Frame End` and `Framerate`. They are scene frames and frames
per second, exactly as written - there is no conversion layer between the bar
and the clock any more, because there is no longer a second unit to convert
into. Everything about how one strip is sampled (how long it runs, and
therefore how finely it interpolates) is that strip's own `frames`, edited on
the Animation strip page.

The range is INCLUSIVE: Frame End 59 is played, and frame 60 is Frame Start
again.
"""

import time as _time

from PySide6.QtCore import QEvent, QPoint, QRect, Qt, Signal
from PySide6.QtGui import (QColor, QCursor, QFont, QPainter, QPen,
                           QPolygon)
from PySide6.QtWidgets import (QHBoxLayout, QLabel,
                               QSizePolicy, QSpinBox, QToolButton,
                               QVBoxLayout, QWidget)

from ..core import input_map
from ..core import timeline as timeline_mod

_ROW_H = 21
_RULER_H = 14          # grabbable playhead strip above the rows
_GUTTER = 132          # name column width
_PAD = 10              # right margin of the time axis
_MIN_ROWS_H = 30
#: How far the time axis may be zoomed. Under a couple of frames the
#: pane says nothing; past a few thousand every strip is a hairline.
_MIN_VIEW_SPAN = 2.0
_MAX_VIEW_SPAN = 200000.0
_MAX_ROWS_H = 320

_BG = QColor(38, 38, 38)
_ROW_BG = QColor(48, 48, 48)
_ROW_ALT = QColor(54, 54, 54)
_BAR = QColor(78, 118, 176)
_BAR_OFF = QColor(80, 80, 80)
_BAR_EDGE = QColor(130, 170, 225)
_PLAYHEAD = QColor(240, 200, 90)
_TEXT = QColor(226, 226, 226)
_TEXT_DIM = QColor(150, 150, 150)
_OUTSIDE = QColor(0, 0, 0, 110)        # veil over frames outside the loop
_LIMIT = QColor(150, 195, 120)         # the loop-range handles
_LIMIT_GRAB = 5                        # px either side of a limit line


#: Blender's selection orange, matching `viewport._OUTLINE_COLOR`.
_SELECTED = QColor(255, 150, 40)


def _tick_step(span):
    """A round tick interval giving roughly 6-12 labels."""
    for step in (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 5000):
        if span / step <= 12:
            return float(step)
    return max(span / 10.0, 1.0)


class TrackRows(QWidget):
    """One row per track: name, enable dot, and its span on the time axis."""

    seek_requested = Signal(float)
    tracks_changed = Signal()
    range_moved = Signal()      # a limit was dragged; already on the clock
    view_changed = Signal(float, float)   # the visible interval moved
    strip_selected = Signal(int)     # obj_id, or -1 for none
    strip_removed = Signal(int)      # obj_id: taken OFF the player only

    def __init__(self, parent=None):
        super().__init__(parent)
        self.timeline = None
        self.names = {}
        self._drag = None          # {"obj_id", "grab_dt"} while moving a track
        #: Which strip is selected, or None. A strip is a thing you act on -
        #: grab it, delete it, read its numbers - so it needs to be nameable,
        #: and ORANGE is what "selected" already means everywhere else in
        #: MoloM (the viewport outline, round 34).
        self.selected = None
        #: Horizontal pan, in the same units as the axis, and a vertical one
        #: in pixels. The pane shows every track at once and a scene with
        #: twenty of them does not fit; without this the ones past the bottom
        #: are simply unreachable, which is the round-21 lesson again.
        self.offset = 0.0
        self.scroll_y = 0
        #: Visible width of the axis, in frames. See `_span`.
        self.view_span = 60.0
        #: Has the axis ever been framed? Until it has, the first sync fits
        #: it to the content; after that it is the user's to move.
        self._framed = False
        #: A keyboard move in progress: G, then the mouse, then
        #: click/Enter to confirm or Esc to put it back.
        self._gmove = None
        #: (action, when) of the scroll gesture in progress.
        self._gesture = None
        self.setFocusPolicy(Qt.StrongFocus)     # or Delete never arrives
        self.setMouseTracking(True)
        self.setMinimumHeight(_MIN_ROWS_H)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_timeline(self, timeline, names):
        # type: (object, dict) -> None
        """Point the pane at the clock. **Never re-frames the axis.**

        It used to widen the view whenever the content outgrew it, which
        sounds helpful and is the bug Christian hit: dragging a strip to the
        right grows the content, so the axis re-fitted ON EVERY MOUSE MOVE -
        the strips visibly shrank under the hand and the pan jumped back to
        zero mid-gesture. An axis is a viewing choice; the only things that
        may change it are the ones that mean to (`fit_view`, the zoom, the
        pan, the View boxes).
        """
        first = self.timeline is None
        self.timeline = timeline
        self.names = dict(names or {})
        if first or not self._framed:
            self.fit_view()
        self.update()

    def rows(self):
        if self.timeline is None:
            return []
        return self.timeline.animated_tracks()

    #: Empty channels drawn under the real ones. Blender's sequencer always
    #: shows somewhere to drop the next strip; a pane that ends exactly at the
    #: last track looks full even when it is not, and gives the eye no room to
    #: read a re-ordering into.
    SPARE_ROWS = 4

    def total_rows(self):
        return len(self.rows()) + self.SPARE_ROWS

    def natural_height(self):
        return max(self.total_rows() * _ROW_H + _RULER_H + 4, _MIN_ROWS_H)

    # ------------------------------------------------------- axis mapping
    def _span(self):
        """The VISIBLE width of the axis in frames - a viewing property, not
        the content's length.

        It used to be `timeline.duration`, which made the pane exactly as wide
        as whatever happened to be in it: there was nowhere to put a strip
        except on top of the others, and dragging one past the end simply
        stretched the axis under your hand. Blender's sequencer works the other
        way round - the render range (our green limits) is a marked INTERVAL,
        and the space either side of it is ordinary canvas you can arrange
        tracks in. Christian: "everything outside of that is also accessible
        space in which tracks can be arranged at will".
        """
        return max(float(self.view_span), 1e-6)

    def _content_span(self):
        if self.timeline is None:
            return 1.0
        return max(self.timeline.duration, 1.0)

    def fit_view(self):
        """Frame everything there is, with a little room either side."""
        lo, hi = self._content_bounds()
        margin = max((hi - lo) * 0.12, 2.0)
        self.set_view(lo - margin, hi + margin)

    def _content_bounds(self):
        """(first, last) scene frame worth showing - strips AND the range."""
        rows = self.rows()
        lo = [t.start for t in rows]
        hi = [t.end_time for t in rows]
        if self.timeline is not None:
            lo.append(self.timeline.play_start)
            hi.append(self.timeline.play_end + 1.0)
        return (min(lo) if lo else 0.0), (max(hi) if hi else 60.0)

    def set_view(self, first, last):
        """Show exactly this interval. The pane's own bounds, which is what
        stops a strip dragged far to the right becoming a sliver with no way
        back - Christian: "unless the pane limits can be set, we run into the
        whole zooming out problem"."""
        first, last = float(first), float(last)
        if last < first:
            first, last = last, first
        self.offset = first
        self.view_span = max(last - first, _MIN_VIEW_SPAN)
        self._framed = True
        self.view_changed.emit(self.offset, self.offset + self.view_span)
        self.update()

    def zoom_view(self, factor, pivot_x=None):
        """Scale the axis about a point on it, keeping that point still."""
        pivot = (self._time_for(pivot_x) if pivot_x is not None
                 else self.offset + self._span() / 2.0)
        span = max(min(self._span() * float(factor), _MAX_VIEW_SPAN),
                   _MIN_VIEW_SPAN)
        share = (pivot - self.offset) / self._span()
        self.set_view(pivot - share * span, pivot - share * span + span)

    def _x_for(self, time):
        usable = max(self.width() - _GUTTER - _PAD, 1)
        return _GUTTER + ((float(time) - self.offset) / self._span()) * usable

    def _time_for(self, x):
        usable = max(self.width() - _GUTTER - _PAD, 1)
        return (float(x) - _GUTTER) / usable * self._span() + self.offset

    def _row_top(self, index):
        return _RULER_H + index * _ROW_H - self.scroll_y

    def _row_at(self, y):
        index = int((y - _RULER_H + self.scroll_y) // _ROW_H)
        rows = self.rows()
        return rows[index] if 0 <= index < len(rows) else None

    def _max_scroll(self):
        return max(0, self.total_rows() * _ROW_H - (self.height() - _RULER_H))

    #: A scroll gesture is one action from start to finish. A trackpad swipe
    #: is never purely one axis, so without this a vertical flick that drifts
    #: a few pixels sideways flips between zooming and panning under the hand -
    #: round 8's rule ("decided at gesture START, never per event") in a new
    #: place, and the whole of what "spotty" meant.
    _GESTURE_GAP_S = 0.35

    def wheelEvent(self, ev):
        """Zoom, pan or scroll the rows, per device and per gesture.

        The decision lives in `core.input_map.pane_scroll` with the rest of
        the trackpad-vs-mouse reasoning (round 16), so it is testable without
        a widget. Here we only latch it: whichever action a gesture starts
        with, it keeps until the fingers leave the pad or the scrolling stops.

        | gesture | does |
        |---|---|
        | swipe / wheel up-down | zoom time about the cursor |
        | swipe left-right | pan time |
        | Shift + vertical | pan time |
        | Ctrl + vertical | scroll the rows |
        """
        pixels = ev.pixelDelta()
        has_px = not pixels.isNull()
        angle = ev.angleDelta()
        dx = pixels.x() if has_px else angle.x()
        dy = pixels.y() if has_px else angle.y()
        mods = ev.modifiers()
        action, steps = input_map.pane_scroll(
            dx, dy, has_px,
            ctrl=bool(mods & Qt.ControlModifier),
            shift=bool(mods & Qt.ShiftModifier))

        phase = ev.phase()
        if phase == Qt.ScrollBegin:
            self._gesture = None
        now = _time.monotonic()
        # The latch holds for as long as the gesture does - but pressing a
        # modifier is a deliberate change of intent, not a wobble in the
        # swipe, so it starts a new one.
        held = (bool(mods & Qt.ControlModifier),
                bool(mods & Qt.ShiftModifier))
        if (self._gesture is not None and self._gesture[2] == held
                and now - self._gesture[1] < self._GESTURE_GAP_S):
            action = self._gesture[0]          # keep doing what we started
        self._gesture = (action, now, held)
        if phase == Qt.ScrollEnd:
            self._gesture = None

        if steps:
            if action == input_map.PANE_ROWS:
                self.scroll_y = int(min(
                    max(self.scroll_y - steps * input_map.PANE_STEP_PIXELS, 0),
                    self._max_scroll()))
                self.update()
            elif action == input_map.PANE_PAN:
                self.pan_view(-steps * input_map.PANE_STEP_PIXELS)
            else:
                self.zoom_view(input_map.pane_zoom_factor(steps),
                               ev.position().x())
        ev.accept()

    def pan_view(self, pixels):
        """Slide the visible interval by a number of PIXELS."""
        usable = max(self.width() - _GUTTER - _PAD, 1)
        shift = float(pixels) / usable * self._span()
        self.set_view(self.offset + shift,
                      self.offset + shift + self._span())

    #: Keys this pane claims while a strip is selected. A single-letter
    #: QAction on the window fires wherever focus is (round 16), so G would
    #: otherwise grab the MOLECULE while you are trying to move its strip -
    #: which is exactly what Christian saw. The viewport solves this with
    #: `ShortcutOverride` and so does this.
    _CLAIMED = None

    def event(self, ev):
        if ev.type() == QEvent.ShortcutOverride and (
                self._claiming(ev.key()) or self._claims_always(ev.key())):
            ev.accept()
            return True
        return super().event(ev)

    def _live(self):
        """Is this pane the thing the keyboard is talking to?

        **Focus OR the pointer** (round 78). Blender routes a hotkey by which
        editor the mouse is over, which is what a Blender user expects - and
        relying on focus alone is why G appeared dead: a click here selects
        the strip, but anything that moves focus afterwards (the properties
        dock refreshing, the viewport's own focus-follows-cursor) leaves the
        pane holding a selection it cannot act on.
        """
        return self.hasFocus() or self.underMouse()

    def _claiming(self, key):
        if self._gmove is not None:
            return True
        if self.selected is None or not self._live():
            return False
        return key in (Qt.Key_G, Qt.Key_Delete, Qt.Key_Backspace, Qt.Key_X)

    def _claims_always(self, key):
        """Keys the pane takes whenever it is live, selection or not."""
        return self._live() and key in (Qt.Key_Home, Qt.Key_Escape)

    def keyPressEvent(self, ev):
        """Delete takes the strip OFF THE PLAYER and nothing else.

        The frames stay on the molecule - this is the animation's track, not
        its data, and a Delete here that destroyed a trajectory would be
        unforgivable. Re-adding it is one click on the object.
        """
        if self._gmove is not None:
            if ev.key() == Qt.Key_Escape:
                self._cancel_gmove()
                ev.accept()
                return
            if ev.key() in (Qt.Key_Return, Qt.Key_Enter):
                self._commit_gmove()
                ev.accept()
                return
        if ev.key() == Qt.Key_Home:
            self.fit_view()            # the way back from any zoom or pan
            ev.accept()
            return
        if ev.key() == Qt.Key_Escape and self.selected is not None:
            self._select(None)
            ev.accept()
            return
        if (ev.key() == Qt.Key_G and self.selected is not None
                and self.timeline is not None):
            track = self.timeline.get(self.selected)
            if track is not None:
                # Blender's G: the strip follows the pointer until a click or
                # Enter drops it, Esc puts it back exactly where it was.
                # The anchor is where the POINTER is, so the strip moves
                # with the hand rather than jumping to it. If the pointer is
                # not over the pane there is no sensible anchor, and taking
                # the mapped-in garbage would fling the strip across the
                # scene - so it anchors on the strip itself and the first
                # move is a no-op.
                anchor = (self._time_for(
                    self.mapFromGlobal(QCursor.pos()).x())
                    if self.underMouse() else float(track.start))
                self._gmove = {"obj_id": self.selected,
                               "orig": float(track.start),
                               "anchor": anchor}
                self.setCursor(QCursor(Qt.SizeHorCursor))
                ev.accept()
                return
        if (ev.key() in (Qt.Key_Delete, Qt.Key_Backspace, Qt.Key_X)
                and self.selected is not None):
            obj_id = int(self.selected)
            self.selected = None
            if self.timeline is not None:
                self.timeline.exclude(obj_id)
            self.strip_removed.emit(obj_id)
            self.strip_selected.emit(-1)
            self.tracks_changed.emit()
            self.update()
            ev.accept()
            return
        super().keyPressEvent(ev)

    def _limit_at(self, x):
        """"start" / "end" if the cursor is on a loop-range handle.

        Frame k occupies the axis interval [x(k), x(k+1)) - which is why
        a strip is drawn out to its EXCLUSIVE `end_time`. The range is
        inclusive of Frame End (round 77), so its right-hand handle sits
        one frame further along than the number it sets.
        """
        if self.timeline is None:
            return None
        for which, time in (("start", self.timeline.play_start),
                            ("end", self.timeline.play_end + 1.0)):
            if abs(x - self._x_for(time)) <= _LIMIT_GRAB:
                return which
        return None

    # ------------------------------------------------------------- paint
    def paintEvent(self, _ev):
        p = QPainter(self)
        p.fillRect(self.rect(), _BG)
        rows = self.rows()
        font = QFont()
        font.setPixelSize(11)
        p.setFont(font)
        # THE EMPTY CHANNELS FIRST. Blender's sequencer always shows somewhere
        # to put the next strip; a pane that stops at the last track reads as
        # full, and gives the eye nothing to arrange a re-ordering into.
        for i in range(len(rows), self.total_rows()):
            top = self._row_top(i)
            if top + _ROW_H < _RULER_H or top > self.height():
                continue
            p.fillRect(QRect(0, top, self.width(), _ROW_H),
                       _ROW_ALT if i % 2 else _ROW_BG)
        for i, track in enumerate(rows):
            top = self._row_top(i)
            if top + _ROW_H < _RULER_H or top > self.height():
                continue                      # scrolled out of view
            row_rect = QRect(0, top, self.width(), _ROW_H)
            p.fillRect(row_rect, _ROW_ALT if i % 2 else _ROW_BG)

            # enable dot + name
            dot = QRect(7, top + _ROW_H // 2 - 4, 8, 8)
            p.setPen(Qt.NoPen)
            p.setBrush(_BAR_EDGE if track.enabled else _BAR_OFF)
            p.drawEllipse(dot)
            p.setPen(_TEXT if track.enabled else _TEXT_DIM)
            name = self.names.get(track.obj_id, str(track.obj_id))
            metrics = p.fontMetrics()
            p.drawText(QRect(22, top, _GUTTER - 30, _ROW_H),
                       Qt.AlignVCenter | Qt.AlignLeft,
                       metrics.elidedText(name, Qt.ElideRight, _GUTTER - 34))

            # the track's span
            x0 = self._x_for(track.start)
            x1 = self._x_for(track.end_time)
            bar = QRect(int(x0), top + 4, max(int(x1 - x0), 3), _ROW_H - 9)
            chosen = self.selected == track.obj_id
            p.setBrush(_BAR if track.enabled else _BAR_OFF)
            # ORANGE for the selected strip, the same colour and the same
            # meaning as the viewport's selection outline (round 34) - a
            # second convention for "this is the one you are acting on" would
            # be one to learn for nothing.
            p.setPen(QPen(_SELECTED, 2) if chosen else
                     QPen(_BAR_EDGE if track.enabled else _BAR_OFF, 1))
            p.drawRoundedRect(bar, 3, 3)
            if bar.width() > 58:
                p.setPen(QColor(255, 255, 255, 190))
                # The strip's OWN length, which is what the bar's width
                # measures. Printing the source count here instead would
                # label a 60-frame bar "20f" as soon as the two differ.
                p.drawText(bar.adjusted(5, 0, -4, 0),
                           Qt.AlignVCenter | Qt.AlignLeft,
                           "{}f".format(track.frames))
                if track.end != "hold":
                    p.drawText(bar.adjusted(4, 0, -5, 0),
                               Qt.AlignVCenter | Qt.AlignRight, track.end)

        # Everything outside the looping interval is veiled: the limits are
        # only comprehensible if you can SEE which part of the scene they cut
        # off, and a veil says that without redrawing the rows twice.
        bottom = min(self._row_top(self.total_rows()),
                     self.height())
        if self.timeline is not None and rows:
            lo = int(self._x_for(self.timeline.play_start))
            hi = int(self._x_for(self.timeline.play_end + 1.0))
            p.setPen(Qt.NoPen)
            p.setBrush(_OUTSIDE)
            if lo > _GUTTER:
                p.drawRect(QRect(_GUTTER, _RULER_H, lo - _GUTTER,
                                 bottom - _RULER_H))
            if hi < self.width():
                p.drawRect(QRect(hi, _RULER_H, self.width() - hi,
                                 bottom - _RULER_H))

        # The ruler: a full-width strip whose only job is to be a big target
        # for the playhead, so the transport slider is not needed at all.
        p.fillRect(QRect(0, 0, self.width(), _RULER_H), QColor(44, 44, 44))
        if self.timeline is not None:
            span = self._span()
            step = _tick_step(span)
            p.setPen(QColor(105, 105, 105))
            tick = 0.0
            while tick <= span + 1e-9:
                x = int(self._x_for(tick))
                p.drawLine(x, _RULER_H - 4, x, _RULER_H - 1)
                p.drawText(x + 3, _RULER_H - 4, "{:g}".format(tick))
                tick += step

        # The two loop limits, grabbable down the whole pane.
        if self.timeline is not None and rows:
            p.setPen(QPen(_LIMIT, 1.5))
            # Drawn on the BOUNDARIES of the played columns, so the line
            # sits after Frame End rather than through it - see
            # `_limit_at`.
            xs = int(self._x_for(self.timeline.play_start))
            xe = int(self._x_for(self.timeline.play_end + 1.0))
            for x in (xs, xe):
                p.drawLine(x, 0, x, bottom)
            p.setPen(Qt.NoPen)
            p.setBrush(_LIMIT)
            p.drawPolygon(QPolygon([QPoint(xs, bottom - 8), QPoint(xs + 7,
                                    bottom), QPoint(xs, bottom)]))
            p.drawPolygon(QPolygon([QPoint(xe, bottom - 8), QPoint(xe - 7,
                                    bottom), QPoint(xe, bottom)]))

        # ONE playhead across the ruler AND every row — drag it anywhere.
        if self.timeline is not None:
            x = int(self._x_for(self.timeline.time))
            p.setPen(QPen(_PLAYHEAD, 1.5))
            p.drawLine(x, 0, x, bottom)
            p.setBrush(_PLAYHEAD)
            p.setPen(Qt.NoPen)
            p.drawPolygon(QPolygon([QPoint(x - 6, 0), QPoint(x + 6, 0),
                                    QPoint(x + 6, 6), QPoint(x, 12),
                                    QPoint(x - 6, 6)]))
        p.end()

    # ------------------------------------------------------------- input
    def _on_playhead(self, pos):
        if self.timeline is None:
            return False
        return abs(pos.x() - self._x_for(self.timeline.time)) <= 6

    def mousePressEvent(self, ev):
        self.setFocus(Qt.MouseFocusReason)     # or Delete/G never arrive
        if self._gmove is not None:
            if ev.button() == Qt.RightButton:
                self._cancel_gmove()
            else:
                self._commit_gmove()
            return
        if self.timeline is None:
            return
        pos = ev.position()
        # A loop limit is a thinner target than the playhead, so it is tested
        # first — otherwise the playhead sitting on a limit (which is where it
        # parks, since seeking clamps) would make the limit ungrabbable.
        limit = self._limit_at(pos.x()) if self.rows() else None
        if limit is not None:
            self._drag = {"limit": limit}
            self.setCursor(QCursor(Qt.SplitHCursor))
            return
        # The ruler strip, or the playhead itself anywhere down the pane:
        # scrubbing is the most common thing to do here, so it wins.
        if pos.y() < _RULER_H or self._on_playhead(pos):
            self._drag = {"playhead": True}
            self.setCursor(QCursor(Qt.SizeHorCursor))
            self.seek_requested.emit(max(self._time_for(pos.x()), 0.0))
            return
        track = self._row_at(pos.y())
        if track is None:
            # Below the last row, in the spare channels. This used to return
            # without doing anything, so a strip stayed selected however far
            # off it you clicked - Christian: "clicking off a strip does not
            # deselect it". Clicking nothing means nothing is selected.
            self._select(None)
            return
        if pos.x() < 20:                       # the enable dot
            track.enabled = not track.enabled
            self.tracks_changed.emit()
            self.update()
            return
        if pos.x() < _GUTTER:
            self._select(None)                 # the name column is not a strip
            return
        x0, x1 = self._x_for(track.start), self._x_for(track.end_time)
        if x0 - 3 <= pos.x() <= x1 + 3:
            # SELECT, then grab: clicking a strip is how you name the thing a
            # Delete or the strip page will act on, and the drag that slides
            # its start offset begins from the same press.
            self._select(track.obj_id)
            self._drag = {"obj_id": track.obj_id,
                          "grab": self._time_for(pos.x()) - track.start}
            self.setCursor(QCursor(Qt.ClosedHandCursor))
            return
        self._select(None)         # empty track space: deselect and seek
        self.seek_requested.emit(max(self._time_for(pos.x()), 0.0))

    def _commit_gmove(self):
        self._gmove = None
        self.unsetCursor()
        self.tracks_changed.emit()
        self.update()

    def _cancel_gmove(self):
        move = self._gmove
        self._gmove = None
        self.unsetCursor()
        if move and self.timeline is not None:
            track = self.timeline.get(move["obj_id"])
            if track is not None:
                track.start = move["orig"]
        self.tracks_changed.emit()
        self.update()

    def _select(self, obj_id):
        if self.selected == obj_id:
            return
        self.selected = obj_id
        self.strip_selected.emit(-1 if obj_id is None else int(obj_id))
        self.update()

    def select_strip(self, obj_id):
        """Select from outside (the strip page, the outliner)."""
        self._select(None if obj_id is None else int(obj_id))

    def mouseMoveEvent(self, ev):
        pos = ev.position()
        if self._gmove is not None:
            # THE strip-grab bug: `_gmove` was armed by G, painted a cursor,
            # and was then never read here - so the strip sat still, the click
            # that "confirmed" it committed nothing, and G looked dead.
            track = self.timeline.get(self._gmove["obj_id"])
            if track is not None:
                track.start = (self._time_for(pos.x())
                               - self._gmove["anchor"] + self._gmove["orig"])
                self.tracks_changed.emit()
                self.update()
            return
        if self._drag is not None and self._drag.get("limit"):
            self._move_limit(self._drag["limit"], self._time_for(pos.x()))
            return
        if self._drag is not None and self._drag.get("playhead"):
            self.seek_requested.emit(max(self._time_for(pos.x()), 0.0))
            return
        if self._drag is None:
            if self.rows() and self._limit_at(pos.x()) is not None:
                self.setCursor(QCursor(Qt.SplitHCursor))
                return
            if pos.y() < _RULER_H or self._on_playhead(pos):
                self.setCursor(QCursor(Qt.SizeHorCursor))
                return
            track = self._row_at(pos.y())
            over = False
            if track is not None and pos.x() >= _GUTTER:
                x0, x1 = self._x_for(track.start), self._x_for(track.end_time)
                over = x0 - 3 <= pos.x() <= x1 + 3
            self.setCursor(QCursor(Qt.OpenHandCursor if over
                                   else Qt.ArrowCursor))
            return
        track = self.timeline.get(self._drag["obj_id"])
        if track is None:
            return
        # No clamp at zero: a strip may sit before frame 0. The pane has
        # canvas either side of the loop range precisely so it can.
        track.start = self._time_for(pos.x()) - self._drag["grab"]
        # Vertical drag re-channels it, so strips can be arranged up and down
        # the way they can in the sequencer.
        row = int((pos.y() - _RULER_H + self.scroll_y) // _ROW_H)
        if 0 <= row < self.total_rows() and self.timeline is not None:
            self.timeline.set_channel(track.obj_id, row)
        self.tracks_changed.emit()
        self.update()

    def _move_limit(self, which, time):
        """Drag one loop limit. They may meet but never cross."""
        tl = self.timeline
        # A limit is a CHOSEN interval, not a summary of the content, so it
        # is free to sit anywhere - including past the last strip and before
        # frame 0. See `Timeline.play_start`.
        # The end handle is dragged on the BOUNDARY after Frame End (see
        # `_limit_at`), so what it sets is one frame back from where the
        # hand is.
        time = round(float(time))
        start, end = tl.play_start, tl.play_end
        if which == "start":
            start = min(time, end)
        else:
            end = max(time - 1.0, start)
        tl.set_range(start, end)
        self.range_moved.emit()
        self.update()

    def mouseReleaseEvent(self, _ev):
        if self._drag is not None:
            self._drag = None
            self.setCursor(QCursor(Qt.ArrowCursor))
            self.tracks_changed.emit()

    def mouseDoubleClickEvent(self, ev):
        """Double-click a bar cycles its end behaviour."""
        if ev.position().y() < _RULER_H:
            return
        track = self._row_at(ev.position().y())
        if track is None or ev.position().x() < _GUTTER:
            return
        order = ["hold", "loop", "pingpong"]
        track.end = order[(order.index(track.end) + 1) % len(order)]
        self.tracks_changed.emit()
        self.update()


class _Grip(QWidget):
    """Thin drag handle that resizes the rows area."""

    dragged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(5)
        self.setCursor(QCursor(Qt.SizeVerCursor))
        self._y = None

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(60, 60, 60))
        p.setPen(QColor(120, 120, 120))
        cx = self.width() // 2
        for dx in (-9, 0, 9):
            p.drawLine(cx + dx, 2, cx + dx + 4, 2)
        p.end()

    def mousePressEvent(self, ev):
        self._y = ev.globalPosition().y()

    def mouseMoveEvent(self, ev):
        if self._y is None:
            return
        delta = self._y - ev.globalPosition().y()
        self._y = ev.globalPosition().y()
        self.dragged.emit(int(delta))

    def mouseReleaseEvent(self, _ev):
        self._y = None


class TimelinePanel(QWidget):
    """Transport bar + the expandable multi-track pane below it."""

    play_pause = Signal()
    seek_requested = Signal(float)
    fps_changed = Signal(int)
    range_changed = Signal(float, float)
    fit_range_requested = Signal()
    tracks_changed = Signal()
    strip_selected = Signal(int)     # obj_id, or -1 for none
    strip_removed = Signal(int)      # taken off the player, data untouched

    def __init__(self, parent=None):
        super().__init__(parent)
        # Set FIRST: sync() writes every spin box, and a programmatic write
        # must never be mistaken for a user edit — that round trip is what
        # made the panel push its own defaults back into the app (and into
        # QSettings) the moment the clock reported anything different.
        self._loading = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        bar = QWidget(self)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(6, 2, 6, 2)
        self.play_btn = QToolButton(bar)
        self.play_btn.setText(">")
        self.play_btn.setToolTip("Play / pause (Space)")
        self.play_btn.clicked.connect(self.play_pause)
        # NO transport slider: the pane's own playhead is draggable, and two
        # scrubbers for one clock is redundant vertical space. Christian's
        # call — the ruler strip is always visible when the pane is open, and
        # the pane opens itself as soon as there is anything to play.

        # The frame range, in SCENE FRAMES exactly as the clock holds them -
        # no image conversion, because a frame is now a picture. Negative is
        # allowed: a strip may sit before frame 0 (see `Track.start`), so an
        # interval that reaches back to it has to be expressible.
        self.start_spin = QSpinBox(bar)
        self.start_spin.setToolTip(
            "First scene frame that plays. Playback wraps between Frame "
            "Start and Frame End instead of over the whole scene.")
        self.end_spin = QSpinBox(bar)
        self.end_spin.setPrefix("- ")
        self.end_spin.setToolTip(
            "Last scene frame that plays, INCLUSIVE - the frame after it is "
            "Frame Start again. A 60-frame oscillation placed at frame 0 "
            "therefore ends at 59, which is what makes the loop seamless.")
        for s in (self.start_spin, self.end_spin):
            s.setRange(-999999, 999999)
            s.setMaximumWidth(84)
            s.valueChanged.connect(self._emit_range)
        self.start_spin.setValue(0)
        self.end_spin.setValue(0)

        self.fit_range_btn = QToolButton(bar)
        self.fit_range_btn.setText("⤢")
        self.fit_range_btn.setToolTip(
            "Fit the frame range to every strip. "
            "The range does not follow the content by itself - arranging "
            "strips must not move it - so this is how a trajectory imported "
            "later gets brought into the loop.")
        self.fit_range_btn.clicked.connect(
            lambda _c=False: self.fit_range_requested.emit())

        self.fps_spin = QSpinBox(bar)
        self.fps_spin.setRange(1, 120)
        self.fps_spin.setValue(int(timeline_mod.DEFAULT_FPS))
        self.fps_spin.setSuffix(" fps")
        self.fps_spin.setMaximumWidth(84)
        self.fps_spin.setToolTip(
            "Scene frames shown per second — the playback speed for the "
            "whole scene. How finely each strip is sampled is the strip's "
            "own frame count, on the Animation strip page.")
        self.fps_spin.valueChanged.connect(self._emit_fps)
        # The PANE's own bounds, on the SAME ROW as everything else -
        # Christian asked why they were not, and he is right: a second bar
        # under the rows is another thing for the expandable pane to fight
        # with, and these are read alongside the frame range, not apart from
        # it. They are a different QUANTITY, though: the frame range says what
        # PLAYS, this says what the pane SHOWS.
        self.view_start = QSpinBox(bar)
        self.view_end = QSpinBox(bar)
        self.view_end.setPrefix("- ")
        for s in (self.view_start, self.view_end):
            s.setRange(-999999, 999999)
            s.setMaximumWidth(84)
            s.setToolTip(
                "The stretch of the timeline the pane SHOWS. Nothing to do "
                "with what plays - that is Frame Start / Frame End. The wheel "
                "zooms the same interval and a sideways swipe pans it.")
            s.valueChanged.connect(self._emit_view)
        self.fit_btn = QToolButton(bar)
        self.fit_btn.setText("Fit")
        self.fit_btn.setToolTip(
            "Frame every strip and the whole play range (Home)")
        self.fit_btn.clicked.connect(lambda _c=False: self.rows.fit_view())

        self.label = QLabel("0 / 0", bar)
        self.label.setToolTip("Current scene frame / last frame of the range")
        self.expand_btn = QToolButton(bar)
        self.expand_btn.setText("▾")
        self.expand_btn.setCheckable(True)
        self.expand_btn.setToolTip("Show the per-molecule track rows")
        self.expand_btn.toggled.connect(self._set_expanded)
        lay.addWidget(self.play_btn, 0)
        lay.addStretch(1)
        for text, widget in (("Frame", self.start_spin),
                             ("", self.end_spin),
                             ("", self.fit_range_btn),
                             ("Framerate", self.fps_spin),
                             ("View", self.view_start),
                             ("", self.view_end),
                             ("", self.fit_btn),
                             ("Playback:", self.label)):
            if text:
                lay.addWidget(QLabel(text, bar), 0)
            lay.addWidget(widget, 0)
        lay.addWidget(self.expand_btn, 0)
        outer.addWidget(bar)

        self.grip = _Grip(self)
        self.grip.dragged.connect(self._resize_rows)
        self.rows = TrackRows(self)
        self.rows.view_changed.connect(self._on_view_changed)
        self.rows.seek_requested.connect(self.seek_requested)
        self.rows.tracks_changed.connect(self.tracks_changed)
        self.rows.strip_selected.connect(self.strip_selected)
        self.rows.strip_removed.connect(self.strip_removed)
        # A dragged limit has already been written to the clock, so it only
        # needs the same "re-apply and re-sync" a track edit gets.
        self.rows.range_moved.connect(self.tracks_changed)
        outer.addWidget(self.grip)
        outer.addWidget(self.rows)
        self.grip.setVisible(False)
        self.rows.setVisible(False)
        self._rows_h = 0
        self._user_sized = False   # once dragged, stop auto-fitting
        self._loading = False      # while sync() writes the spin boxes

    def _set_expanded(self, on):
        self.expand_btn.setText("▴" if on else "▾")
        if on and not self._user_sized:
            self._rows_h = self.rows.natural_height()
        self.rows.setFixedHeight(max(self._rows_h, _MIN_ROWS_H))
        self.grip.setVisible(on)
        self.rows.setVisible(on)

    def _on_view_changed(self, first, last):
        """The pane zoomed or panned itself; show where it now is."""
        self._loading = True
        try:
            self.view_start.setValue(int(round(first)))
            self.view_end.setValue(int(round(last)))
        finally:
            self._loading = False

    def _emit_view(self, _value=0):
        """A View box was typed into.

        The two are edited one at a time, so a start moved past the current
        end would invert the interval and land somewhere nobody asked for.
        The end is CARRIED instead, keeping the width the pane already had -
        which is what "move the window I am looking through" means.
        """
        # `rows` is built after these boxes, and Qt is perfectly capable of
        # delivering a signal to a half-constructed widget (round 34) - so the
        # guard is cheap insurance against a failure that would surface
        # somewhere else entirely.
        if self._loading or getattr(self, "rows", None) is None:
            return
        lo = float(self.view_start.value())
        hi = float(self.view_end.value())
        if hi <= lo:
            hi = lo + max(self.rows.view_span, _MIN_VIEW_SPAN)
        self.rows.set_view(lo, hi)

    def _resize_rows(self, delta):
        self._user_sized = True     # a deliberate height beats auto-fitting
        self._rows_h = max(_MIN_ROWS_H,
                           min(self.rows.height() + delta, _MAX_ROWS_H))
        self.rows.setFixedHeight(self._rows_h)

    def _emit_fps(self, value):
        if not self._loading:
            self.fps_changed.emit(int(value))

    def _emit_range(self, _value=0):
        """A limit spin box moved. Both are SCENE FRAMES, which is what the
        clock stores, so nothing is converted on the way through."""
        if self._loading:
            return
        lo = min(self.start_spin.value(), self.end_spin.value())
        hi = max(self.start_spin.value(), self.end_spin.value())
        self.range_changed.emit(float(lo), float(hi))

    def sync(self, timeline, names, playing):
        # type: (object, dict, bool) -> None
        """Refresh everything from the scene clock."""
        n = len(timeline.animated_tracks())
        total = timeline.n_frames
        self.label.setText("{:.0f} / {:.0f}{}".format(
            timeline.time, timeline.play_end,
            "  ({} tracks)".format(n) if n > 1 else ""))
        self.label.setToolTip(
            "Scene frame {:.2f}, in a range of {} frames "
            "({:g} to {:g})  —  {:.2f} s at {:g} fps".format(
                timeline.time, total, timeline.play_start,
                timeline.play_end, total / max(timeline.fps, 1e-6),
                timeline.fps))
        self._loading = True
        self.fps_spin.setValue(int(round(timeline.fps)))
        for spin, value in ((self.start_spin, timeline.play_start),
                            (self.end_spin, timeline.play_end)):
            spin.setValue(int(round(value)))
        self._loading = False
        self.play_btn.setText("||" if playing else ">")
        self.expand_btn.setEnabled(n > 0)
        self.rows.set_timeline(timeline, names)
        # Open by default the moment there is something to play: with the
        # slider gone, a collapsed pane would leave nothing to scrub.
        if n and not self.expand_btn.isChecked():
            self.expand_btn.setChecked(True)
        elif self.rows.isVisible() and not self._user_sized:
            # Grow (or shrink) to fit as trajectories come and go — the pane
            # used to keep whatever height the FIRST track needed.
            self._set_expanded(True)
