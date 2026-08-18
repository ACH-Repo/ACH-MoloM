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
trajectory actually has.

**Frames, images and seconds** (round 30, Christian's playback spec). Three
different things used to be muddled into one number:

* a **frame** is a coordinate set that came out of an input file — a
  trajectory step, a CIF, one sample of a normal mode. How many there are is
  a property of the data and nothing the player gets to choose.
* an **image** is one picture the player draws. `smoothing` says how many
  images fill the gap between two consecutive frames, so it is the
  subdivision of the source data (1 = no interpolation, draw frames only).
* `fps` is **images per second** — the only wall-clock quantity here, and
  global, because it is a property of the playback and not of any one
  molecule.

So one source frame lasts `smoothing / fps` seconds, and a scene of `d`
frames runs for `d * smoothing / fps` seconds. Keeping the two knobs separate
is what lets a 12-frame optimisation and a 200-frame trajectory both play at
a watchable speed without touching the data.

`range_start` / `range_end` bound the **looping interval**: the playhead
wraps (or ping-pongs, or holds) inside them instead of over the whole scene,
so you can loop the interesting 20 frames of a 500-frame run.
"""

from typing import Dict, List, Optional

HOLD = "hold"        # stay on the last frame once the track has run out
LOOP = "loop"        # wrap back to the start
PINGPONG = "pingpong"  # play forwards, then backwards, forever
END_MODES = (HOLD, LOOP, PINGPONG)

DEFAULT_FPS = 60.0          # IMAGES per second
DEFAULT_SMOOTHING = 3       # images per source-frame interval


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

    def __init__(self, fps=DEFAULT_FPS, smoothing=DEFAULT_SMOOTHING):
        self.time = 0.0
        self.fps = float(fps)            # IMAGES per second
        self.playing = False
        self.end = LOOP          # what the PLAYHEAD does at the end
        self._smoothing = max(int(smoothing), 1)
        # What `interpolate = True` restores. Never 1, or turning it back on
        # would be a no-op.
        self._smooth_memory = max(int(smoothing), 2)
        # None = "follow the scene", so a range the user never touched keeps
        # covering a trajectory that grows or shrinks under it.
        self.range_start = 0.0
        self.range_end = None    # type: Optional[float]
        self._tracks = {}             # type: Dict[int, Track]
        #: Objects the user has taken off the player by hand.
        self._excluded = set()        # type: set

    # ---------------------------------------------------------- subdivision
    @property
    def smoothing(self):
        # type: () -> int
        """Images drawn per source-frame interval. 1 = frames only."""
        return self._smoothing

    @smoothing.setter
    def smoothing(self, value):
        value = max(int(value), 1)
        self._smoothing = value
        if value > 1:
            self._smooth_memory = value

    @property
    def interpolate(self):
        # type: () -> bool
        """Kept as the old boolean so callers reading it still make sense —
        interpolation IS just a subdivision greater than one."""
        return self._smoothing > 1

    @interpolate.setter
    def interpolate(self, on):
        self._smoothing = self._smooth_memory if on else 1

    @property
    def step(self):
        # type: () -> float
        """Scene frames advanced by one image."""
        return 1.0 / float(self._smoothing)

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
        EXCLUDED ones gain nothing - taking a strip off the player is a
        decision, and a decision that the next rebuild silently undoes is not
        one. (Round 52 made the same call about an edited cell: once the user
        has said otherwise, stop regenerating.)
        """
        seen = set()
        for obj_id, n_frames in pairs:
            if int(obj_id) in self._excluded:
                continue
            self.set_track(obj_id, n_frames)
            seen.add(int(obj_id))
        for obj_id in [k for k in self._tracks if k not in seen]:
            del self._tracks[obj_id]

    def exclude(self, obj_id):
        # type: (int) -> None
        """Take this object OFF the player and keep it off.

        The frames are untouched - this is the animation's track, not the
        molecule's data, which is the whole point of Delete in the track pane
        being safe.
        """
        self._excluded.add(int(obj_id))
        self._tracks.pop(int(obj_id), None)

    def include(self, obj_id):
        # type: (int) -> None
        """Put it back; the next `sync` gives it a fresh default track."""
        self._excluded.discard(int(obj_id))

    def is_excluded(self, obj_id):
        return int(obj_id) in self._excluded

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

    # ------------------------------------------------------- looping range
    @property
    def play_start(self):
        # type: () -> float
        """First scene frame of the looping interval."""
        return max(0.0, min(float(self.range_start), self.duration))

    @property
    def play_end(self):
        # type: () -> float
        """Last scene frame of the looping interval."""
        if self.range_end is None:
            return self.duration
        return max(self.play_start, min(float(self.range_end), self.duration))

    @property
    def span(self):
        # type: () -> float
        """Scene frames inside the looping interval."""
        return self.play_end - self.play_start

    def set_range(self, start, end):
        # type: (Optional[float], Optional[float]) -> None
        """Bound the loop. Either end may be None for 'follow the scene'."""
        self.range_start = 0.0 if start is None else max(0.0, float(start))
        self.range_end = None if end is None else float(end)
        if self.range_end is not None and self.range_end < self.range_start:
            self.range_start, self.range_end = self.range_end, self.range_start
        self.time = self._clamp(self.time)

    # ------------------------------------------------------------- images
    @property
    def n_images(self):
        # type: () -> int
        """Images in the WHOLE scene at the current subdivision."""
        return int(round(self.duration * self._smoothing)) + 1

    def image_of(self, time):
        # type: (float) -> int
        """Which image a scene time falls on (0-based, from scene frame 0)."""
        return int(round(float(time) * self._smoothing))

    def time_of_image(self, index):
        # type: (float) -> float
        return float(index) / float(self._smoothing)

    @property
    def current_image(self):
        # type: () -> int
        return self.image_of(self.time)

    def range_images(self):
        # type: () -> tuple
        """The looping interval as (first, last) image indices."""
        return self.image_of(self.play_start), self.image_of(self.play_end)

    # -------------------------------------------------------------- moving
    def seek(self, time):
        # type: (float) -> float
        """Put the playhead somewhere. CLAMPS to the looping interval rather
        than wrapping: dragging the playhead past a limit should park on it,
        not teleport to the other end (which is what a wrap looks like when
        you are scrubbing by hand)."""
        self.time = self._clamp(float(time))
        return self.time

    def advance(self, seconds):
        # type: (float) -> float
        """Step the playhead by a wall-clock interval."""
        return self.advance_images(float(seconds) * self.fps)

    def advance_images(self, n=1.0):
        # type: (float) -> float
        """Step by whole images — what the playback timer does per tick."""
        return self.step_frames(float(n) * self.step)

    def step_frames(self, n):
        # type: (float) -> float
        """Step by scene frames, wrapping per the playhead's end mode."""
        self.time = self._wrap(self.time + float(n))
        return self.time

    def _clamp(self, time):
        lo, hi = self.play_start, self.play_end
        return max(lo, min(float(time), hi))

    def _wrap(self, time):
        lo, hi = self.play_start, self.play_end
        span = hi - lo
        if span <= 0.0:
            return lo
        local = float(time) - lo
        if self.end == LOOP:
            return lo + local % span
        if self.end == PINGPONG:
            period = 2.0 * span
            k = local % period
            return lo + (k if k <= span else period - k)
        return lo + max(0.0, min(local, span))

    def frame_for(self, obj_id):
        # type: (int) -> Optional[float]
        """Fractional local frame this object should show right now."""
        track = self._tracks.get(int(obj_id))
        if track is None or not track.enabled:
            return None
        return track.frame_at(self.time)

    def to_dict(self):
        return {"time": self.time, "fps": self.fps, "end": self.end,
                "smoothing": self._smoothing,
                "range_start": self.range_start, "range_end": self.range_end,
                "tracks": [t.to_dict() for t in self.tracks()]}

    @classmethod
    def from_dict(cls, d):
        # type: (dict) -> Timeline
        tl = cls(d.get("fps", DEFAULT_FPS))
        # Savepoints written before round 30 carry the old boolean instead.
        if "smoothing" in d:
            tl.smoothing = d.get("smoothing", DEFAULT_SMOOTHING)
        else:
            tl.interpolate = bool(d.get("interpolate", True))
        tl.end = d.get("end", LOOP)
        tl.range_start = float(d.get("range_start", 0.0) or 0.0)
        end = d.get("range_end", None)
        tl.range_end = None if end is None else float(end)
        for raw in d.get("tracks", ()):
            track = Track.from_dict(raw)
            tl._tracks[track.obj_id] = track
        tl.time = float(d.get("time", 0.0))
        return tl
