"""One clock for the whole scene, so several trajectories can play at once.

Before this each `Structure` carried its own integer `current_frame` and the
trajectory bar drove whichever molecule happened to be active - so a second
trajectory simply could not play, and there was no shared notion of "now".

The model here is Blender's: **one playhead**, in scene FRAMES, and one
`Track` per object mapping that playhead into the object's own frame space.
Everything is a plain value - no Qt, no timers - so the mapping is testable
offline and the UI is left with nothing but "advance the clock and repaint".

**Round 77 reworked what the numbers mean, and the point is that there is now
only ONE playback number per strip.** Christian: "The global settings should
only be Frame Start, Frame End, Framerate. Smoothing is a property that should
be unique to a particular strip... Just set one number of total frames inside
the strip properties."

So:

* the **scene clock** ticks in frames at `fps` frames per second, and
  `play_start` / `play_end` (Frame Start / Frame End) bound the interval it
  loops over. One timer tick is one frame. There is no second global
  subdivision knob and no separate notion of an "image": a frame IS a picture.
* a **strip** (`Track`) says how many scene frames it occupies - `frames` -
  and that single number is its speed, its length and its smoothness at once.
  Raise it and the strip runs longer and interpolates more finely; lower it
  and it runs faster and coarser.

**The one distinction that survives is CYCLIC vs LINEAR data**, because it is
a real difference in the source and not a preference:

* a baked normal mode is **cyclic** - `vibrations.mode_frames` samples one
  whole period at `2*pi*k/n` for k in 0..n-1, so sample `n` would BE sample 0
  and is deliberately not stored. Its `n` samples divide the strip's `frames`
  scene frames into `n` equal arcs, and the strip's last frame sits one arc
  short of the start it came from. That is Christian's "subtract the last
  frame for a proper loop", and it is why the loop closes exactly.
* an imported trajectory is **linear** - its `n` frames are `n - 1` real
  intervals with two distinct ends, so `frames - 1` scene frames divide
  `n - 1` source intervals and the strip's LAST frame lands exactly on the
  last datum.

One formula, one parameter, two spans. What used to be global `smoothing` is
recovered as `frames / n`, per strip, with no separate switch - interpolation
is simply what happens when a strip is longer than its data.

The bug that made the rework worth doing rather than merely tidier: the old
LOOP wrapped a track at `n_frames - 1` local frames, i.e. it assumed the last
stored frame duplicated the first. A baked mode does not store that duplicate,
so **a mode looped over 93.3% of its period and then jumped the remaining
1.33 source frames in one image** - a hitch once per revolution, four times
the normal step, on every vibration MoloM has ever animated.
"""

import math
from typing import Dict, List, Optional

HOLD = "hold"        # stay on the last frame once the strip has run out
LOOP = "loop"        # wrap back to the start
PINGPONG = "pingpong"  # play forwards, then backwards, forever
END_MODES = (HOLD, LOOP, PINGPONG)

DEFAULT_FPS = 60.0            # scene FRAMES per second

#: Scene frames a strip gets by default - one second at `DEFAULT_FPS`, which
#: is a watchable oscillation and a sane starting point for anything else.
#: Christian's default, stated as "60 FPS, ergo 59 frames per oscillation
#: animation": 60 frames counted from 0 end at 59, which is where the scene's
#: Frame End lands.
DEFAULT_STRIP_FRAMES = 60

#: Set on a `Structure.metadata` whose frames close on themselves. Metadata
#: rather than a field on the track because it is a property of the DATA (a
#: mode is a period; an MD run is not), so it rides undo and savefiles for
#: free and a strip removed and re-added comes back describing the same thing
#: - round 43's pattern.
CYCLIC_FRAMES = "cyclic_frames"


def frames_are_cyclic(structure):
    # type: (object) -> bool
    """Whether this structure's frames are one closed period."""
    meta = getattr(structure, "metadata", None) or {}
    return bool(meta.get(CYCLIC_FRAMES))


def frames_for_seconds(seconds, fps):
    # type: (float, float) -> int
    """How many scene frames a wanted DURATION comes to.

    Round 78 made seconds the number the strip page edits, because that is
    what a person actually means - Christian: "Change the main strip property
    from frames to time. That is intuitive to a user." Frames stay the
    model's unit, since they are what the clock counts and what a render
    writes, and this is the one place the two meet.
    """
    return max(int(math.floor(float(seconds) * float(fps) + 0.5)), 1)


def default_frames(n_source):
    # type: (int) -> int
    """Scene frames a strip of `n_source` data frames gets when first seen.

    `max(n, 60)` for both kinds, deliberately - a single rule rather than one
    per data type. A 20-sample mode and a 3-step optimisation both become a
    second of watchable animation; a 500-frame MD run keeps every real frame
    rather than being decimated to fit a default nobody asked for.
    """
    return max(int(n_source), DEFAULT_STRIP_FRAMES)


class Track(object):
    """How one object follows the scene playhead - one strip on the pane."""

    def __init__(self, obj_id, n_frames, start=0.0, frames=None, end=HOLD,
                 enabled=True, channel=None, cyclic=False, locked=False,
                 interpolated=True):
        # type: (int, int, float, Optional[int], str, bool, Optional[int], bool, bool) -> None
        self.obj_id = int(obj_id)
        #: Frames in the SOURCE data. Not the user's to choose.
        self.n_frames = max(int(n_frames), 1)
        self.start = start
        #: Scene frames the strip OCCUPIES. The only playback number a strip
        #: has: length, speed and smoothness in one.
        self.frames = max(int(default_frames(self.n_frames)
                              if frames is None else frames), 1)
        #: True once the length was chosen BY HAND, which is what stops a
        #: later re-sync replacing it with the default for a new source count.
        self.frames_locked = bool(locked)
        self.end = end if end in END_MODES else HOLD
        self.enabled = bool(enabled)
        #: Blend BETWEEN source frames, or step from one to the next?
        #:
        #: The last thing the old global `smoothing` could say that a duration
        #: cannot (round 78). How MANY pictures there are is `frames`, and it
        #: follows from the duration and the framerate - but whether those
        #: pictures interpolate or hold is a separate, genuinely different
        #: look, and it belongs to the strip: an MD run is sometimes better
        #: watched as the frames that were actually computed.
        self.interpolated = bool(interpolated)
        #: Does the source close on itself? See the module docstring.
        self.cyclic = bool(cyclic)
        #: Which row the strip sits on, so it can be moved up and
        #: down independently of the scene's object order. None
        #: until something places it, which keeps a scene that has
        #: never been arranged in its natural order.
        self.channel = None if channel is None else int(channel)

    def __repr__(self):
        return "Track(obj={}, n={}, start={:g}, frames={}, {}{})".format(
            self.obj_id, self.n_frames, self.start, self.frames, self.end,
            ", cyclic" if self.cyclic else "")

    # ------------------------------------------------------------- geometry
    @property
    def start(self):
        # type: () -> float
        """Scene frame this strip begins on.

        MAY BE NEGATIVE - a strip that starts before frame 0 is an ordinary
        thing to want when you are lining several up against each other, and
        the pane has canvas either side of the frame range for exactly that.

        **SNAPPED to a whole frame** (round 78), because a strip dragged by
        the mouse otherwise lands on 3.7 and every frame of it is then sampled
        off the grid - and, worse, its last frame falls between two scene
        frames, so a loop fitted to it gains or loses one. Blender's sequencer
        snaps strips for the same reason. The playhead only ever stops on
        whole frames, so nothing is lost.
        """
        return self._start

    @start.setter
    def start(self, value):
        self._start = float(int(math.floor(float(value) + 0.5)))

    @property
    def last_frame(self):
        # type: () -> float
        """Last scene frame the strip occupies (INCLUSIVE)."""
        return self.start + self.frames - 1

    @property
    def end_time(self):
        # type: () -> float
        """Where the strip stops, EXCLUSIVE - the frame at which it would
        begin repeating. This is the right edge to DRAW, because a one-frame
        strip still covers one frame's worth of the axis."""
        return self.start + self.frames

    @property
    def subdivision(self):
        # type: () -> float
        """Scene frames per source frame - what `smoothing` used to be, now
        DERIVED rather than set. 1.0 means the real frames and nothing else.
        """
        if self.cyclic:
            return float(self.frames) / float(max(self.n_frames, 1))
        if self.n_frames < 2:
            return float(self.frames)
        return float(max(self.frames - 1, 1)) / float(self.n_frames - 1)

    @property
    def interpolates(self):
        # type: () -> bool
        return self.subdivision > 1.0 + 1e-9

    def seconds(self, fps=DEFAULT_FPS):
        # type: (float) -> float
        """How long one pass lasts at a given framerate."""
        return float(self.frames) / max(float(fps), 1e-6)

    # -------------------------------------------------------------- mapping
    def strip_frame(self, time):
        # type: (float) -> float
        """Where in the STRIP's own span a scene time falls, in scene frames.

        The end mode is applied HERE, in the strip's own frames, and not in
        the source's - which is what lets one rule serve both kinds of data.
        A LOOP wraps over `frames`, so the strip occupies exactly the frames
        it says it does and the frame after its last is its first again.
        """
        span = float(self.frames)
        local = float(time) - self.start
        if span <= 1.0:
            return 0.0
        if self.end == LOOP:
            return local % span
        last = span - 1.0
        if self.end == PINGPONG:
            period = 2.0 * last
            k = local % period
            return k if k <= last else period - k
        return max(0.0, min(local, last))

    def frame_at(self, time):
        # type: (float) -> float
        """Fractional SOURCE frame for a scene time.

        For cyclic data the result may land in `[n-1, n)`, which is the arc
        between the last stored sample and the first - a real part of the
        period, and precisely the interval the old model skipped. Callers
        must interpolate cyclically there
        (`interpolate.coords_at(..., cyclic=True)`).
        """
        n = self.n_frames
        if n <= 1:
            return 0.0
        u = self.strip_frame(time)
        if self.cyclic:
            return (u * float(n) / float(self.frames)) % float(n)
        if self.frames <= 1:
            return 0.0
        return u * float(n - 1) / float(self.frames - 1)

    def to_dict(self):
        return {"obj_id": self.obj_id, "n_frames": self.n_frames,
                "start": self.start, "frames": self.frames, "end": self.end,
                "enabled": self.enabled, "channel": self.channel,
                "cyclic": self.cyclic, "locked": self.frames_locked,
                "interpolated": self.interpolated}

    @classmethod
    def from_dict(cls, d):
        return cls(d["obj_id"], d.get("n_frames", 1), d.get("start", 0.0),
                   d.get("frames"), d.get("end", HOLD),
                   d.get("enabled", True), d.get("channel"),
                   d.get("cyclic", False), d.get("locked", False),
                   d.get("interpolated", True))


class Timeline(object):
    """The scene playhead plus every strip hanging off it."""

    def __init__(self, fps=DEFAULT_FPS):
        self.time = 0.0
        self.fps = float(fps)            # scene FRAMES per second
        self.playing = False
        self.end = LOOP          # what the PLAYHEAD does at the end
        # None = "follow the scene", so a range the user never touched keeps
        # covering a trajectory that grows or shrinks under it.
        self.range_start = 0.0
        self.range_end = None    # type: Optional[float]
        self._tracks = {}             # type: Dict[int, Track]
        #: Objects the user has taken off the player by hand.
        self._excluded = set()        # type: set

    # ------------------------------------------------------------- tracks
    def set_track(self, obj_id, n_frames, **kw):
        # type: (int, int, object) -> Track
        """Add or update a strip. Keeps existing settings on update, so a
        re-sync after an edit does not reset a start offset the user chose.

        The one setting NOT kept is `frames` when the SOURCE count changes
        under a strip whose length was never chosen by hand: re-baking a mode
        at 40 samples instead of 20 must not leave the strip describing the
        old data. `frames_locked` marks a length the user set themselves.
        """
        existing = self._tracks.get(int(obj_id))
        if existing is not None:
            n_frames = max(int(n_frames), 1)
            if (n_frames != existing.n_frames and not existing.frames_locked
                    and "frames" not in kw):
                existing.frames = default_frames(n_frames)
            existing.n_frames = n_frames
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
        """Playable tracks in ROW order.

        Sorted by `channel` where one has been assigned, so dragging a strip
        up or down is a property of the strip and survives a rebuild - the
        alternative is that the rows follow the scene's object order and a
        re-arrangement silently undoes itself.
        """
        live = [t for t in self.tracks() if t.enabled and t.n_frames > 1]
        order = {t.obj_id: i for i, t in enumerate(live)}
        return sorted(live, key=lambda t: (t.channel if t.channel is not None
                                           else order[t.obj_id],
                                           order[t.obj_id]))

    def set_channel(self, obj_id, channel):
        # type: (int, int) -> None
        """Put a strip on a row. Every other track keeps its own, so this is
        a placement rather than a re-shuffle."""
        track = self.get(obj_id)
        if track is not None:
            track.channel = max(0, int(channel))

    def set_frames(self, obj_id, frames):
        # type: (int, int) -> Optional[Track]
        """Set a strip's length BY HAND, and remember that it was.

        The flag is what stops a later re-sync overwriting the choice with
        the default for whatever the source frame count has become.
        """
        track = self.get(obj_id)
        if track is None:
            return None
        track.frames = max(int(frames), 1)
        track.frames_locked = True
        return track

    def set_duration(self, obj_id, seconds):
        # type: (int, float) -> Optional[Track]
        """Set a strip's length in SECONDS - what the strip page edits."""
        return self.set_frames(obj_id, frames_for_seconds(seconds, self.fps))

    def sync(self, rows):
        # type: (List) -> None
        """Reconcile against the scene: [(obj_id, n_frames[, cyclic]), ...].

        Objects that vanished lose their strip; new ones gain a default one.
        EXCLUDED ones gain nothing - taking a strip off the player is a
        decision, and a decision that the next rebuild silently undoes is not
        one. (Round 52 made the same call about an edited cell: once the user
        has said otherwise, stop regenerating.)
        """
        seen = set()
        for row in rows:
            obj_id, n_frames = row[0], row[1]
            cyclic = bool(row[2]) if len(row) > 2 else False
            if int(obj_id) in self._excluded:
                continue
            self.set_track(obj_id, n_frames, cyclic=cyclic)
            seen.add(int(obj_id))
        for obj_id in [k for k in self._tracks if k not in seen]:
            del self._tracks[obj_id]
        # Resolve "not chosen yet" the first time there IS something to play,
        # and never again - see `play_end`. A scene that has just gained its
        # first trajectory should be framed by the range; one whose strips are
        # being arranged should not have the range moving under it.
        if self.range_end is None and self.animated_tracks():
            self.fit_range()

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
        """LAST scene frame any strip occupies, INCLUSIVE.

        Inclusive because that is what a Frame End means: a 60-frame strip
        placed at 0 runs 0..59, so the range that plays it exactly is 0-59.
        """
        ends = [t.last_frame for t in self.animated_tracks()]
        return max(ends) if ends else 0.0

    @property
    def has_animation(self):
        # type: () -> bool
        return bool(self.animated_tracks())

    # ------------------------------------------------------- looping range
    @property
    def play_start(self):
        # type: () -> float
        """Frame Start: first scene frame of the looping interval.

        NOT clamped to the content. Blender's frame range runs 1-250 whatever
        is in the scene, and the range is a statement about what gets PLAYED
        and RENDERED rather than a summary of what exists. Clamping it to
        `duration` had two visible consequences Christian reported: the green
        limits could not be moved past the end of the strips at all, and
        dragging a strip to the right dragged the right-hand limit with it -
        because `duration` grew under the hand and `play_end` was defined as
        `duration`.
        """
        return float(self.range_start)

    @property
    def play_end(self):
        # type: () -> float
        """Frame End: LAST scene frame of the looping interval, inclusive.

        **It does not follow the content** (round 78). `range_end` of None
        means "not chosen yet" and is resolved ONCE, by `fit_range`, the first
        time there is anything to play; from then on it is a fixed number.

        Making it track `duration` was the round-77 mistake and it broke three
        things at once, all of which Christian hit: dragging a strip to the
        right dragged Frame End along with it, which re-scaled the pane under
        the hand; and a strip nudged to a FRACTIONAL start made the range
        fractional too, so the loop period stopped being a whole number of
        frames and the wrap gained or lost one. A frame range is a decision
        about what gets played and rendered, not a summary of what exists.
        """
        if self.range_end is None:
            return max(self.duration, self.play_start)
        return max(self.play_start, float(self.range_end))

    def fit_range(self):
        # type: () -> None
        """Set the range to cover everything there is, once."""
        self.range_start = min([t.start for t in self.animated_tracks()]
                               or [0.0])
        self.range_end = self.duration
        self.time = self._clamp(self.time)

    @property
    def range_chosen(self):
        # type: () -> bool
        return self.range_end is not None

    @property
    def span(self):
        # type: () -> float
        """Scene frames INSIDE the looping interval - an inclusive count, so
        0-59 is 60 frames and 0-0 is one."""
        return self.play_end - self.play_start + 1.0

    @property
    def n_frames(self):
        # type: () -> int
        """Frames the range plays. What the transport bar counts."""
        return max(int(round(self.span)), 1)

    def set_range(self, start, end):
        # type: (Optional[float], Optional[float]) -> None
        """Bound the loop. Either end may be None for 'follow the scene'."""
        # Negative is allowed: a strip can sit before frame 0 (see
        # `Track.start`), so an interval that reaches back to it must be
        # expressible too.
        self.range_start = 0.0 if start is None else float(start)
        self.range_end = None if end is None else float(end)
        if self.range_end is not None and self.range_end < self.range_start:
            self.range_start, self.range_end = self.range_end, self.range_start
        self.time = self._clamp(self.time)

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
        return self.step_frames(float(seconds) * self.fps)

    def advance_frames(self, n=1.0):
        # type: (float) -> float
        """Step by whole frames - what the playback timer does per tick."""
        return self.step_frames(float(n))

    def step_frames(self, n):
        # type: (float) -> float
        """Step by scene frames, wrapping per the playhead's end mode."""
        self.time = self._wrap(self.time + float(n))
        return self.time

    def _clamp(self, time):
        lo, hi = self.play_start, self.play_end
        return max(lo, min(float(time), hi))

    def _wrap(self, time):
        """Wrap over the INCLUSIVE range [play_start, play_end].

        A LOOP therefore has period `span` = end - start + 1: the frame AFTER
        Frame End is Frame Start, which is Blender's rule and is what makes
        "Frame End 59" mean that 59 is played rather than skipped. The old
        code wrapped over `end - start`, so the last frame of the range was
        never shown at all.
        """
        lo, hi = self.play_start, self.play_end
        if hi <= lo:
            return lo
        local = float(time) - lo
        if self.end == LOOP:
            return lo + local % (hi - lo + 1.0)
        last = hi - lo
        if self.end == PINGPONG:
            period = 2.0 * last
            k = local % period
            return lo + (k if k <= last else period - k)
        return lo + max(0.0, min(local, last))

    def frame_for(self, obj_id):
        # type: (int) -> Optional[float]
        """Fractional local frame this object should show right now."""
        track = self._tracks.get(int(obj_id))
        if track is None or not track.enabled:
            return None
        return track.frame_at(self.time)

    def is_cyclic(self, obj_id):
        # type: (int) -> bool
        track = self._tracks.get(int(obj_id))
        return bool(track is not None and track.cyclic)

    # ------------------------------------------------------------ savefile
    def to_dict(self):
        return {"time": self.time, "fps": self.fps, "end": self.end,
                "range_start": self.range_start,
                "range_end": self.range_end,
                # A strip taken off the player by hand is a DECISION,
                # and one the next sync would silently undo (round 52).
                # It has to survive the savefile for the same reason.
                "excluded": sorted(self._excluded),
                "tracks": [t.to_dict() for t in self.tracks()]}

    @classmethod
    def from_dict(cls, d):
        # type: (dict) -> Timeline
        tl = cls(d.get("fps", DEFAULT_FPS))
        tl.end = d.get("end", LOOP)
        tl.range_start = float(d.get("range_start", 0.0) or 0.0)
        end = d.get("range_end", None)
        tl.range_end = None if end is None else float(end)
        raws = list(d.get("tracks", ()))
        for raw in raws:
            track = Track.from_dict(raw)
            tl._tracks[track.obj_id] = track
        tl._excluded = {int(k) for k in d.get("excluded", ())}
        tl.time = float(d.get("time", 0.0))
        legacy = int(d.get("smoothing", 0) or 0)
        if legacy:
            tl._migrate_from_images(raws, legacy)
        return tl

    def _migrate_from_images(self, raws, smoothing):
        # type: (List[dict], int) -> None
        """Read a savepoint written before round 77.

        A strip used to be measured in SOURCE frames scaled by a `speed`, with
        one GLOBAL `smoothing` turning those into pictures - so its length in
        pictures was `(n - 1) / speed * smoothing`, and a picture is now a
        frame. That expression IS the new `frames`, and the whole scene axis
        has been multiplied by `smoothing` along with it, which is why the
        range and the playhead are scaled to match.
        """
        for raw in raws:
            track = self._tracks.get(int(raw.get("obj_id", -1)))
            if track is None or "frames" in raw:
                continue
            speed = abs(float(raw.get("speed", 1.0))) or 1.0
            track.start = float(raw.get("start", 0.0)) * smoothing
            track.frames = max(int(round(
                (track.n_frames - 1) / speed * smoothing)), 1)
            track.frames_locked = True
        self.range_start *= smoothing
        if self.range_end is not None:
            # The old end was the WRAP point, i.e. the duplicate picture; the
            # new one is the last picture actually played.
            self.range_end = self.range_end * smoothing - 1
        self.time = self._clamp(self.time * smoothing)
