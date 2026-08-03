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

**The transport bar reads in IMAGES** (round 30). `Smoothing` is how many
images are drawn per source-frame interval and `Framerate` is images per
second, so the two multiply out to a real playback speed no matter how many
frames the input file happened to contain — which was the problem with the
old `Smooth` tick box, a switch that could not say how much. The `Loop`
limits bound the interval the playhead runs over; they are stored in scene
frames so changing the smoothing does not move them.
"""

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import (QColor, QCursor, QFont, QPainter, QPen,
                           QPolygon)
from PySide6.QtWidgets import (QHBoxLayout, QLabel,
                               QSizePolicy, QSpinBox, QToolButton,
                               QVBoxLayout, QWidget)

from ..core import timeline as timeline_mod

_ROW_H = 21
_RULER_H = 14          # grabbable playhead strip above the rows
_GUTTER = 132          # name column width
_PAD = 10              # right margin of the time axis
_MIN_ROWS_H = 30
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

    def __init__(self, parent=None):
        super().__init__(parent)
        self.timeline = None
        self.names = {}
        self._drag = None          # {"obj_id", "grab_dt"} while moving a track
        self.setMouseTracking(True)
        self.setMinimumHeight(_MIN_ROWS_H)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_timeline(self, timeline, names):
        # type: (object, dict) -> None
        self.timeline = timeline
        self.names = dict(names or {})
        self.update()

    def rows(self):
        if self.timeline is None:
            return []
        return self.timeline.animated_tracks()

    def natural_height(self):
        return max(len(self.rows()) * _ROW_H + _RULER_H + 4, _MIN_ROWS_H)

    # ------------------------------------------------------- axis mapping
    def _span(self):
        if self.timeline is None:
            return 1.0
        return max(self.timeline.duration, 1e-6)

    def _x_for(self, time):
        usable = max(self.width() - _GUTTER - _PAD, 1)
        return _GUTTER + (float(time) / self._span()) * usable

    def _time_for(self, x):
        usable = max(self.width() - _GUTTER - _PAD, 1)
        return (float(x) - _GUTTER) / usable * self._span()

    def _row_at(self, y):
        index = int((y - _RULER_H) // _ROW_H)
        rows = self.rows()
        return rows[index] if 0 <= index < len(rows) else None

    def _limit_at(self, x):
        """"start" / "end" if the cursor is on a loop-range handle."""
        if self.timeline is None:
            return None
        for which, time in (("start", self.timeline.play_start),
                            ("end", self.timeline.play_end)):
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
        for i, track in enumerate(rows):
            top = _RULER_H + i * _ROW_H
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
            p.setBrush(_BAR if track.enabled else _BAR_OFF)
            p.setPen(QPen(_BAR_EDGE if track.enabled else _BAR_OFF, 1))
            p.drawRoundedRect(bar, 3, 3)
            if bar.width() > 58:
                p.setPen(QColor(255, 255, 255, 190))
                p.drawText(bar.adjusted(5, 0, -4, 0),
                           Qt.AlignVCenter | Qt.AlignLeft,
                           "{}f".format(track.n_frames))
                if track.end != "hold":
                    p.drawText(bar.adjusted(4, 0, -5, 0),
                               Qt.AlignVCenter | Qt.AlignRight, track.end)

        # Everything outside the looping interval is veiled: the limits are
        # only comprehensible if you can SEE which part of the scene they cut
        # off, and a veil says that without redrawing the rows twice.
        bottom = _RULER_H + len(rows) * _ROW_H
        if self.timeline is not None and rows:
            lo = int(self._x_for(self.timeline.play_start))
            hi = int(self._x_for(self.timeline.play_end))
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
            for time in (self.timeline.play_start, self.timeline.play_end):
                x = int(self._x_for(time))
                p.drawLine(x, 0, x, bottom)
            p.setPen(Qt.NoPen)
            p.setBrush(_LIMIT)
            xs = int(self._x_for(self.timeline.play_start))
            xe = int(self._x_for(self.timeline.play_end))
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
            return
        if pos.x() < 20:                       # the enable dot
            track.enabled = not track.enabled
            self.tracks_changed.emit()
            self.update()
            return
        if pos.x() < _GUTTER:
            return
        x0, x1 = self._x_for(track.start), self._x_for(track.end_time)
        if x0 - 3 <= pos.x() <= x1 + 3:
            # grab the bar: dragging slides the track's START offset
            self._drag = {"obj_id": track.obj_id,
                          "grab": self._time_for(pos.x()) - track.start}
            self.setCursor(QCursor(Qt.ClosedHandCursor))
            return
        self.seek_requested.emit(max(self._time_for(pos.x()), 0.0))

    def mouseMoveEvent(self, ev):
        pos = ev.position()
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
        track.start = max(0.0, self._time_for(pos.x()) - self._drag["grab"])
        self.tracks_changed.emit()
        self.update()

    def _move_limit(self, which, time):
        """Drag one loop limit. They may meet but never cross."""
        tl = self.timeline
        time = max(0.0, min(float(time), tl.duration))
        start, end = tl.play_start, tl.play_end
        if which == "start":
            start = min(time, end)
        else:
            end = max(time, start)
        tl.set_range(start, None if end >= tl.duration - 1e-9 else end)
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
    smoothing_changed = Signal(int)
    fps_changed = Signal(int)
    range_changed = Signal(float, float)
    tracks_changed = Signal()

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

        # Loop limits. In IMAGES, like everything else on this bar, so the
        # numbers here and the playback readout are the same quantity.
        self.start_spin = QSpinBox(bar)
        self.start_spin.setToolTip(
            "First image of the looping interval — playback wraps between "
            "these two limits instead of over the whole scene")
        self.end_spin = QSpinBox(bar)
        self.end_spin.setPrefix("- ")
        self.end_spin.setToolTip("Last image of the looping interval")
        for s in (self.start_spin, self.end_spin):
            s.setRange(1, 999999)
            s.setMaximumWidth(84)
            s.valueChanged.connect(self._emit_range)
        self.start_spin.setValue(1)
        self.end_spin.setValue(1)

        self.smooth_spin = QSpinBox(bar)
        self.smooth_spin.setRange(1, 120)
        self.smooth_spin.setValue(timeline_mod.DEFAULT_SMOOTHING)
        self.smooth_spin.setSuffix(" img")
        self.smooth_spin.setMaximumWidth(84)
        self.smooth_spin.setToolTip(
            "Images drawn per source frame. 1 shows the frames as they came "
            "out of the file; higher subdivides between them, turning "
            "rotating molecules rather than cutting across so bond lengths "
            "hold.")
        self.smooth_spin.valueChanged.connect(self._emit_smoothing)
        self.fps_spin = QSpinBox(bar)
        self.fps_spin.setRange(1, 120)
        self.fps_spin.setValue(int(timeline_mod.DEFAULT_FPS))
        self.fps_spin.setSuffix(" fps")
        self.fps_spin.setMaximumWidth(84)
        self.fps_spin.setToolTip(
            "Images shown per second — the playback speed for the whole "
            "scene, whatever each molecule's frame count happens to be")
        self.fps_spin.valueChanged.connect(self._emit_fps)
        self.label = QLabel("0 / 0", bar)
        self.label.setToolTip("Current image / images in the scene")
        self.expand_btn = QToolButton(bar)
        self.expand_btn.setText("▾")
        self.expand_btn.setCheckable(True)
        self.expand_btn.setToolTip("Show the per-molecule track rows")
        self.expand_btn.toggled.connect(self._set_expanded)
        lay.addWidget(self.play_btn, 0)
        lay.addStretch(1)
        for text, widget in (("Loop", self.start_spin),
                             ("", self.end_spin),
                             ("Smoothing", self.smooth_spin),
                             ("Framerate", self.fps_spin),
                             ("Playback:", self.label)):
            if text:
                lay.addWidget(QLabel(text, bar), 0)
            lay.addWidget(widget, 0)
        lay.addWidget(self.expand_btn, 0)
        outer.addWidget(bar)

        self.grip = _Grip(self)
        self.grip.dragged.connect(self._resize_rows)
        self.rows = TrackRows(self)
        self.rows.seek_requested.connect(self.seek_requested)
        self.rows.tracks_changed.connect(self.tracks_changed)
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

    def _resize_rows(self, delta):
        self._user_sized = True     # a deliberate height beats auto-fitting
        self._rows_h = max(_MIN_ROWS_H,
                           min(self.rows.height() + delta, _MAX_ROWS_H))
        self.rows.setFixedHeight(self._rows_h)

    def _emit_smoothing(self, value):
        if not self._loading:
            self.smoothing_changed.emit(int(value))

    def _emit_fps(self, value):
        if not self._loading:
            self.fps_changed.emit(int(value))

    def _emit_range(self, _value=0):
        """A limit spin box moved. Both are 1-based IMAGE numbers; the app
        turns them back into scene frames, which is what the clock stores."""
        if self._loading:
            return
        lo = min(self.start_spin.value(), self.end_spin.value()) - 1
        hi = max(self.start_spin.value(), self.end_spin.value()) - 1
        self.range_changed.emit(float(lo), float(hi))

    def sync(self, timeline, names, playing):
        # type: (object, dict, bool) -> None
        """Refresh everything from the scene clock."""
        n = len(timeline.animated_tracks())
        total = timeline.n_images
        self.label.setText("{} / {}{}".format(
            timeline.current_image + 1, total,
            "  ({} tracks)".format(n) if n > 1 else ""))
        self.label.setToolTip(
            "Image {} of {}  —  scene frame {:.2f} of {:.0f}, "
            "{:.1f} s at {:g} fps".format(
                timeline.current_image + 1, total, timeline.time,
                timeline.duration, total / max(timeline.fps, 1e-6),
                timeline.fps))
        self._loading = True
        self.smooth_spin.setValue(timeline.smoothing)
        self.fps_spin.setValue(int(round(timeline.fps)))
        first, last = timeline.range_images()
        for spin, value in ((self.start_spin, first + 1),
                            (self.end_spin, last + 1)):
            spin.setRange(1, max(total, 1))
            spin.setValue(value)
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
