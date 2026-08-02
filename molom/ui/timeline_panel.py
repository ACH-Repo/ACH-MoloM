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
"""

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import (QColor, QCursor, QFont, QPainter, QPen,
                           QPolygon)
from PySide6.QtWidgets import (QCheckBox, QHBoxLayout, QLabel,
                               QSizePolicy, QSpinBox, QToolButton,
                               QVBoxLayout, QWidget)

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

        # ONE playhead across the ruler AND every row — drag it anywhere.
        if self.timeline is not None:
            x = int(self._x_for(self.timeline.time))
            bottom = _RULER_H + len(rows) * _ROW_H
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
        if self._drag is not None and self._drag.get("playhead"):
            self.seek_requested.emit(max(self._time_for(pos.x()), 0.0))
            return
        if self._drag is None:
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
    interpolate_toggled = Signal(bool)
    fps_changed = Signal(int)
    tracks_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
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
        self.label = QLabel("0/0", bar)
        self.interp_check = QCheckBox("Smooth", bar)
        self.interp_check.setChecked(True)
        self.interp_check.setToolTip(
            "Interpolate between frames. Rotating molecules are turned "
            "rather than cut across, so bond lengths hold.")
        self.interp_check.toggled.connect(self.interpolate_toggled)
        self.fps_spin = QSpinBox(bar)
        self.fps_spin.setRange(1, 60)
        self.fps_spin.setValue(10)
        self.fps_spin.setSuffix(" fps")
        self.fps_spin.valueChanged.connect(self.fps_changed)
        self.expand_btn = QToolButton(bar)
        self.expand_btn.setText("▾")
        self.expand_btn.setCheckable(True)
        self.expand_btn.setToolTip("Show the per-molecule track rows")
        self.expand_btn.toggled.connect(self._set_expanded)
        lay.addWidget(self.play_btn, 0)
        lay.addStretch(1)
        for w in (self.label, self.interp_check, self.fps_spin,
                  self.expand_btn):
            lay.addWidget(w, 0)
        outer.addWidget(bar)

        self.grip = _Grip(self)
        self.grip.dragged.connect(self._resize_rows)
        self.rows = TrackRows(self)
        self.rows.seek_requested.connect(self.seek_requested)
        self.rows.tracks_changed.connect(self.tracks_changed)
        outer.addWidget(self.grip)
        outer.addWidget(self.rows)
        self.grip.setVisible(False)
        self.rows.setVisible(False)
        self._rows_h = 0
        self._user_sized = False   # once dragged, stop auto-fitting

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

    def sync(self, timeline, names, playing):
        # type: (object, dict, bool) -> None
        """Refresh everything from the scene clock."""
        span = timeline.duration
        n = len(timeline.animated_tracks())
        self.label.setText("{:.2f} / {:.0f}{}".format(
            timeline.time, span,
            "  ({} tracks)".format(n) if n > 1 else ""))
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
