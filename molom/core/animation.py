"""Turn the scene clock into a file — a PNG sequence, or a video.

Christian, 2026-08-02: "it sucks to have nice animations in a viewport but not
being able to render them." Everything needed was already here — the clock can
be stepped deterministically (round 22/30) and the viewport can render one
image offscreen at a resolution multiplier (round 13) — so the export is
"seek, render, write" and the only real design work is what to write it to.

**A PNG SEQUENCE is the primary format and takes no dependency.** It works
everywhere, it is what you actually want feeding Blender, DaVinci or a
journal's submission system, and a failed export leaves you the frames that
did render rather than a corrupt container. **Video is the optional tier**,
through `imageio-ffmpeg` — which pip-installs a static binary, so there is no
system-wide install and no PATH hunting, matching the rdkit/openbabel
degradation pattern the rest of the project uses. A system `ffmpeg` is
preferred when there is one.

This module is UI-free: it plans the frames and owns the writers, and the
caller hands it a `render(index, time) -> QImage`-shaped callable. That split
is what makes the frame arithmetic testable without a GL context, which is
most of what can go wrong — an off-by-one at a loop boundary produces a video
that stutters once per cycle and is invisible in any single frame.
"""

import math
import os
import shutil
import subprocess

from . import io as _io
from typing import List, Optional, Tuple

#: Output formats, best-supported first.
FORMAT_PNG = "png"
FORMAT_MP4 = "mp4"
FORMAT_GIF = "gif"
FORMATS = (FORMAT_PNG, FORMAT_MP4, FORMAT_GIF)
#: The formats that need an ffmpeg. A PNG sequence deliberately does not, which
#: is what keeps the animation export working with no optional dependency at
#: all — see `NO_FFMPEG_HELP`.
VIDEO_FORMATS = (FORMAT_MP4, FORMAT_GIF)

#: A video encoder wants even dimensions; H.264 in particular refuses odd ones
#: with a message nobody reads to the end.
EVEN_DIMENSIONS = (FORMAT_MP4,)


class ExportError(RuntimeError):
    pass


def frame_times(clock, loops=1.0, whole_scene=False):
    # type: (object, float, bool) -> List[float]
    """The scene FRAMES to render, in order.

    Taken from the clock's own looping interval, so what you export is what
    the transport bar plays - the alternative (an independent range on the
    export dialog) is two sources of truth for the same thing.

    The interval is INCLUSIVE (round 77): Frame Start 0 / Frame End 59 is
    sixty frames, and frame 60 is frame 0 again. So a loop no longer has a
    last image to drop - the drop moved to where it belongs, which is the
    frame range itself and each strip's own length. Playing two loops back to
    back therefore repeats the plan exactly, with no picture shown twice in a
    row and no hitch once per revolution.
    """
    start = 0.0 if whole_scene else float(clock.play_start)
    end = float(clock.duration) if whole_scene else float(clock.play_end)
    per_loop = int(round(end - start)) + 1
    loops = max(float(loops), 0.0)
    if per_loop <= 1:
        return [start] if loops > 0 else []
    # Half-way cases round UP explicitly. Python's `round` is banker's,
    # so half of a five-frame loop would come out as two frames while
    # half of a seven-frame one came out as four - the same trap
    # `vibrations.period_frames` documents.
    total = int(math.floor(per_loop * loops + 0.5))
    return [start + float(k % per_loop) for k in range(total)]


def even(value):
    # type: (int) -> int
    return int(value) - (int(value) % 2)


def sequence_path(directory, base, index, digits=4, suffix=".png"):
    # type: (str, str, int, int, str) -> str
    return os.path.join(directory or "",
                        "{}_{:0{}d}{}".format(base or "molom", int(index),
                                              int(digits), suffix))


def plan(path, fmt, n_frames):
    # type: (str, str, int) -> dict
    """Where the output goes, and how many digits the numbering needs.

    A sequence is written into a DIRECTORY named after the file the user
    chose, rather than beside it: a few hundred PNGs dropped into whatever
    folder they picked is a mess they then have to sort out by hand.
    """
    fmt = str(fmt or FORMAT_PNG).lower()
    if fmt not in FORMATS:
        raise ExportError("unknown format: {!r}".format(fmt))
    root, _ext = os.path.splitext(path)
    base = os.path.basename(root) or "molom"
    digits = max(4, len(str(max(int(n_frames) - 1, 0))))
    if fmt == FORMAT_PNG:
        return {"format": fmt, "directory": root, "base": base,
                "digits": digits, "path": root}
    return {"format": fmt, "directory": os.path.dirname(root), "base": base,
            "digits": digits, "path": root + "." + fmt}


#: Where an ffmpeg tends to live when it is not on PATH. Windows installers and
#: the common package managers put it in a handful of predictable places, and
#: checking them costs nothing next to making the user hunt for the binary.
FFMPEG_LOCATIONS = (
    r"C:\ffmpeg\bin\ffmpeg.exe",
    r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
    r"C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe",
    os.path.expanduser(r"~\scoop\shims\ffmpeg.exe"),
    os.path.expanduser(r"~\AppData\Local\Microsoft\WinGet\Links\ffmpeg.exe"),
    "/usr/bin/ffmpeg",
    "/usr/local/bin/ffmpeg",
    "/opt/homebrew/bin/ffmpeg",
    "/snap/bin/ffmpeg",
)


def ffmpeg_candidates(hint=None):
    # type: (str) -> list
    """Every place to look for ffmpeg, best first, as `(path, source)`.

    Order is the point. A HINT the user set wins, because they set it to be
    obeyed. A SYSTEM ffmpeg comes next: it is usually newer and already has the
    codecs they installed it for. `imageio_ffmpeg`'s static binary is LAST
    rather than first — it is the fallback that makes the feature work out of
    the box, not the preferred tool — and it is optional, so this whole
    function has to survive it being absent.
    """
    out = []
    if hint:
        out.append((str(hint), "the path set in Settings"))
    found = shutil.which("ffmpeg")
    if found:
        out.append((found, "ffmpeg on PATH"))
    for path in FFMPEG_LOCATIONS:
        out.append((path, "an ffmpeg installed at {}".format(path)))
    try:
        import imageio_ffmpeg
        out.append((str(imageio_ffmpeg.get_ffmpeg_exe()),
                    "the bundled imageio-ffmpeg binary"))
    except Exception:
        pass                      # optional tier: absence is not an error
    return out


def ffmpeg_source(hint=None):
    # type: (str) -> tuple
    """`(path, where_it_came_from)`, or `("", "")` when there is none.

    The UI needs the second half. "No ffmpeg" and "using the one you pointed
    me at" are very different things to a user staring at a disabled combo box,
    and only one of them is worth acting on.
    """
    for path, source in ffmpeg_candidates(hint):
        if path and (os.path.isfile(path) or shutil.which(path)):
            return path, source
    return "", ""


def ffmpeg_executable(hint=None):
    # type: (str) -> str
    """The ffmpeg to run, or "" if there is none."""
    return ffmpeg_source(hint)[0]


def video_available(hint=None):
    # type: (str) -> bool
    return bool(ffmpeg_executable(hint))


#: What to tell someone who has no ffmpeg. Deliberately not a dead end: the
#: PNG sequence is a real answer, not a consolation prize.
NO_FFMPEG_HELP = (
    "No ffmpeg found, so only a PNG image sequence can be written — which "
    "needs no ffmpeg at all and is what feeds Blender or a journal anyway. "
    "For MP4 or GIF: install ffmpeg and put it on PATH, or "
    "`pip install imageio-ffmpeg` for a self-contained one, or point MoloM at "
    "an ffmpeg.exe below.")


#: A GIF stores each frame's delay as an integer number of CENTISECONDS, so
#: the only exactly representable rates are 100/n. Everything else has to be
#: rounded by the encoder, and the rounding is not uniform across frames —
#: which is seen as a stutter that no amount of re-rendering fixes. 60 fps
#: wants 1.667 cs and gets 2 (i.e. 50 fps), unevenly.
GIF_CENTISECONDS = 100


def gif_delay(fps):
    # type: (float) -> int
    """The integer centisecond delay a GIF will actually store for `fps`.

    Clamped at 1: a delay of 0 means "as fast as possible" and is treated
    wildly differently by different players.
    """
    return max(1, int(round(GIF_CENTISECONDS / max(float(fps), 1e-6))))


def gif_fps(fps):
    # type: (float) -> float
    """The nearest frame rate a GIF can actually play `fps` at.

    Snapping BEFORE encoding is what removes the jitter: ask for 60 and the
    file says 2 cs per frame, which is 50 fps played evenly, rather than a
    mixture of 1 cs and 2 cs frames that reads as a stutter. Returning the
    honest number also lets the UI say what it is going to do.
    """
    return GIF_CENTISECONDS / float(gif_delay(fps))


def gif_note(fps):
    # type: (float) -> str
    """A one-line explanation when the requested rate is not representable."""
    real = gif_fps(fps)
    if abs(real - float(fps)) < 1e-6:
        return ""
    return ("GIF stores whole centiseconds per frame, so {:g} fps is not "
            "representable — this will be written at {:g} fps ({} cs per "
            "frame). Use MP4 for exact timing, or pick 50, 33.3, 25, 20 or "
            "10 fps.".format(float(fps), real, gif_delay(fps)))


def encode_command(exe, pattern, out_path, fps, fmt=FORMAT_MP4, quality=18):
    # type: (str, str, str, float, str, int) -> list
    """ffmpeg's arguments for turning a numbered sequence into a video.

    `-crf` is quality, not bitrate: 18 is visually lossless for the flat
    shading a molecule render produces, and a fixed bitrate would waste space
    on a still scene and starve a fast one. `yuv420p` is not optional — the
    default `yuv444p` plays in nothing but VLC.
    """
    rate = gif_fps(fps) if fmt == FORMAT_GIF else float(fps)
    cmd = [exe, "-y", "-framerate", "{:.6g}".format(rate),
           "-i", pattern]
    if fmt == FORMAT_GIF:
        # SNAPPED to a rate the format can hold (see `gif_fps`), because a GIF
        # only stores whole centiseconds per frame. Asking for 60 fps otherwise
        # produces a mixture of 1 cs and 2 cs frames, which plays as a stutter
        # — and `-r` is set as well as `-framerate` so the output rate cannot
        # drift back to something unrepresentable.
        #
        # One pass with a generated palette; a GIF from the default 216-colour
        # web palette bands badly on smooth spheres.
        cmd += ["-vf", "split[a][b];[a]palettegen[p];[b][p]paletteuse",
                "-r", "{:.6g}".format(rate), out_path]
        return cmd
    cmd += ["-c:v", "libx264", "-preset", "slow",
            "-crf", str(int(quality)), "-pix_fmt", "yuv420p", out_path]
    return cmd


def encode(pattern, out_path, fps, fmt=FORMAT_MP4, quality=18, timeout=1800,
           hint=None):
    # type: (str, str, float, str, int, float, str) -> Tuple[bool, str]
    """Run ffmpeg over an already-written sequence. Never raises."""
    exe = ffmpeg_executable(hint)
    if not exe:
        return False, NO_FFMPEG_HELP
    try:
        proc = subprocess.run(encode_command(exe, pattern, out_path, fps, fmt,
                                             quality),
                              stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=timeout,
                              **_io.quiet_subprocess_kwargs())
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)
    out = (proc.stdout or b"").decode("utf-8", "replace")
    if proc.returncode != 0:
        return False, "ffmpeg exited {}\n{}".format(proc.returncode,
                                                    out[-2000:])
    if not os.path.exists(out_path):
        return False, "ffmpeg ran but wrote no file\n" + out[-2000:]
    return True, out


def summarise(n_frames, fps, fmt):
    # type: (int, float, str) -> str
    seconds = float(n_frames) / max(float(fps), 1e-6)
    return "{} image(s) at {:g} fps — {:.1f} s of {}".format(
        n_frames, fps, seconds, str(fmt).upper())


def next_free(path, enabled=True, limit=9999):
    # type: (str, bool, int) -> str
    """`shot.png` -> `shot_001.png` when `shot.png` already exists.

    Overwrite protection for the F12 keys, and the reason they can be
    press-and-forget at all: a render key that silently replaces the last
    render is a key you cannot press twice. Blender's own output settings work
    the same way, and the suffix is separate from the frame numbering so a
    sequence's `_0000` counters are never confused with a take number.

    Off returns the path unchanged, so "I want to overwrite" stays possible.
    """
    if not enabled or not os.path.exists(path):
        return path
    root, ext = os.path.splitext(path)
    for n in range(1, int(limit) + 1):
        candidate = "{}_{:03d}{}".format(root, n, ext)
        if not os.path.exists(candidate):
            return candidate
    return path
