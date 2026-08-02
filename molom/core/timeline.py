"""One clock for the whole scene, so several trajectories can play at once.

Before this each `Structure` carried its own integer `current_frame` and the
trajectory bar drove whichever molecule happened to be active — so a second
trajectory simply could not play, and there was no shared notion of "now".

The model here is Blender's: **one playhead**, in scene FRAMES (a float), and
one `Track` per object mapping that playhead into the object's own frame
space via a start offset, a speed, and an end behaviour. Everything is a plain
value — no Qt, no timers — so the mapping is testable offline and the UI is
left with nothing but "advance the clock and repaint".

Scene time is measured in frames rather than seconds because that is what a
trajectory actually has; `fps` exists only to turn wall-clock ticks into
scene-frame steps during playback.
"""

from typing import Dict, List, Optional

HOLD = "hold"        # stay on the last frame once the track has run out
LOOP = "loop"        # wrap back to the start
PINGPONG = "pingpong"  # play forwards, then backwards, forever
END_MODES = (HOLD, LOOP, PINGPONG)

DEFAULT_FPS = 12.0


class Track(object):
    """How one object follows the scene playhead."""

    def __init__(self, obj_id, n_frames, start=0.0, speed=1.0, end=HOLD,
                 enabled=True):
        # type: (int, int, float, float, str, bool) -> None
        self.obj_id = int(obj_id)
        self.n_frames = max(int(n_frames), 1)
        self.start = float(start)      # scene frame this track begins on
        self.speed = float(speed)      # local frames per scene frame
        self.end = end if end in END_MODES else HOLD
        self.enabled = bool(enabled)

    def __repr__(self):
        return "Track(obj={}, n={}, start={:g}, speed={:g}, {})".format(
            self.obj_id, self.n_frames, self.start, self.speed, self.end)

    @property
    def length(self):
        # type: () -> float
        """Scene-frame span of one pass (0 for a still)."""
        if self.n_frames <= 1 or self.speed == 0.0:
            return 0.0
        return (self.n_frames - 1) / abs(self.speed)

    @property
    def end_time(self):
        # type: () -> float
        return self.start + self.length

    def frame_at(self, time):
        # type: (float) -> float
        """Fractional local frame for a scene time. Always in range."""
        last = self.n_frames - 1
        if last <= 0:
            return 0.0
        local = (float(time) - self.start) * self.speed
        if local <= 0.0 and self.end != LOOP and self.end != PINGPONG:
            return 0.0
        if self.end == LOOP:
            return local % last if last else 0.0
        if self.end == PINGPONG:
            period = 2.0 * last
            k = local % period
            return k if k <= last else period - k
        return max(0.0, min(local, float(last)))

    def to_dict(self):
        return {"obj_id": self.obj_id, "n_frames": self.n_frames,
                "start": self.start, "speed": self.speed, "end": self.end,
                "enabled": self.enabled}

    @classmethod
    def from_dict(cls, d):
        return cls(d["obj_id"], d.get("n_frames", 1), d.get("start", 0.0),
                   d.get("speed", 1.0), d.get("end", HOLD),
                   d.get("enabled", True))


class Timeline(object):
    """The scene playhead plus every track hanging off it."""

    def __init__(self, fps=DEFAULT_FPS):
        self.time = 0.0
        self.fps = float(fps)
        self.playing = False
        self.interpolate = True
        self.end = LOOP          # what the PLAYHEAD does at the end
        self._tracks = {}        # type: Dict[int, Track]

    # ------------------------------------------------------------- tracks
    def set_track(self, obj_id, n_frames, **kw):
        # type: (int, int, object) -> Track
        """Add or update a track. Keeps existing settings on update, so a
        re-sync after an edit does not reset a start offset the user chose."""
        existing = self._tracks.get(int(obj_id))
        if existing is not None:
            existing.n_frames = max(int(n_frames), 1)
            for key, value in kw.items():
                setattr(existing, key, value)
            return existing
        track = Track(obj_id, n_frames, **kw)
        self._tracks[track.obj_id] = track
        return track

    def remove_track(self, obj_id):
        self._tracks.pop(int(obj_id), None)

    def get(self, obj_id):
        # type: (int) -> Optional[Track]
        return self._tracks.get(int(obj_id))

    def tracks(self):
        # type: () -> List[Track]
        """Tracks in a stable order (by start, then id) for a track pane."""
        return sorted(self._tracks.values(),
                      key=lambda t: (t.start, t.obj_id))

    def animated_tracks(self):
        # type: () -> List[Track]
        return [t for t in self.tracks() if t.enabled and t.n_frames > 1]

    def sync(self, pairs):
        # type: (List) -> None
        """Reconcile against the scene: [(obj_id, n_frames), ...].

        Objects that vanished lose their track; new ones gain a default one.
        """
        seen = set()
        for obj_id, n_frames in pairs:
            self.set_track(obj_id, n_frames)
            seen.add(int(obj_id))
        for obj_id in [k for k in self._tracks if k not in seen]:
            del self._tracks[obj_id]

    # -------------------------------------------------------------- clock
    @property
    def duration(self):
        # type: () -> float
        """Scene frames until the last track has finished one pass."""
        ends = [t.end_time for t in self.animated_tracks()]
        return max(ends) if ends else 0.0

    @property
    def has_animation(self):
        # type: () -> bool
        return bool(self.animated_tracks())

    def seek(self, time):
        # type: (float) -> float
        self.time = self._wrap(float(time))
        return self.time

    def advance(self, seconds):
        # type: (float) -> float
        """Step the playhead by a wall-clock interval."""
        return self.seek(self.time + float(seconds) * self.fps)

    def step_frames(self, n):
        # type: (float) -> float
        return self.seek(self.time + float(n))

    def _wrap(self, time):
        span = self.duration
        if span <= 0.0:
            return 0.0
        if self.end == LOOP:
            return time % span
        if self.end == PINGPONG:
            period = 2.0 * span
            k = time % period
            return k if k <= span else period - k
        return max(0.0, min(time, span))

    def frame_for(self, obj_id):
        # type: (int) -> Optional[float]
        """Fractional local frame this object should show right now."""
        track = self._tracks.get(int(obj_id))
        if track is None or not track.enabled:
            return None
        return track.frame_at(self.time)

    def to_dict(self):
        return {"time": self.time, "fps": self.fps, "end": self.end,
                "interpolate": self.interpolate,
                "tracks": [t.to_dict() for t in self.tracks()]}

    @classmethod
    def from_dict(cls, d):
        # type: (dict) -> Timeline
        tl = cls(d.get("fps", DEFAULT_FPS))
        tl.time = float(d.get("time", 0.0))
        tl.end = d.get("end", LOOP)
        tl.interpolate = bool(d.get("interpolate", True))
        for raw in d.get("tracks", ()):
            track = Track.from_dict(raw)
            tl._tracks[track.obj_id] = track
        return tl
