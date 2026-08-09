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

import os
import shutil
import subprocess
from typing import List, Optional, Tuple

#: Output formats, best-supported first.
FORMAT_PNG = "png"
FORMAT_MP4 = "mp4"
FORMAT_GIF = "gif"
FORMATS = (FORMAT_PNG, FORMAT_MP4, FORMAT_GIF)

#: A video encoder wants even dimensions; H.264 in particular refuses odd ones
#: with a message nobody reads to the end.
EVEN_DIMENSIONS = (FORMAT_MP4,)


class ExportError(RuntimeError):
    pass


def frame_times(clock, loops=1.0, whole_scene=False):
    # type: (object, float, bool) -> List[float]
    """The scene TIMES to render, in order.

    Taken from the clock's own looping interval, so what you export is what
    the transport bar plays — the alternative (an independent range on the
    export dialog) is two sources of truth for the same thing.

    The last image of a loop is dropped when there is more than one, because
    it is the same picture as the first of the next: a cycle of n distinct
    images played back to back must not show frame 0 twice, which reads as a
    hitch once per revolution and is invisible in any single frame.
    """
    start = 0.0 if whole_scene else float(clock.play_start)
    end = float(clock.duration) if whole_scene else float(clock.play_end)
    smoothing = max(int(getattr(clock, "smoothing", 1)), 1)
    per_loop = max(int(round((end - start) * smoothing)), 0)
    loops = max(float(loops), 0.0)
    if per_loop <= 0:
        return [start] if loops > 0 else []
    total = int(round(per_loop * loops))
    step = 1.0 / float(smoothing)
    return [start + (k % per_loop) * step for k in range(total)]


def even(value):
    # type: (int) -> int
    return int(value) - (int(value) % 2)


def sequence_path(directory, base, index, digits=4, suffix=".png"):
    # type: (str, str, int, int, str) -> str
    return os.path.join(directory or "",
                        "{}_{:0{}d}{}".format(base or "molom", int(index),
                                              int(digits), suffix))


def plan(path, fmt, n_images):
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
    digits = max(4, len(str(max(int(n_images) - 1, 0))))
    if fmt == FORMAT_PNG:
        return {"format": fmt, "directory": root, "base": base,
                "digits": digits, "path": root}
    return {"format": fmt, "directory": os.path.dirname(root), "base": base,
            "digits": digits, "path": root + "." + fmt}


def ffmpeg_executable():
    # type: () -> str
    """A system ffmpeg if there is one, else the wheel's static binary, else
    "". Preferring the system one matters: it is usually newer and has the
    codecs a user has already installed for everything else."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
    except ImportError:
        return ""
    try:
        return str(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:
        return ""


def video_available():
    # type: () -> bool
    return bool(ffmpeg_executable())


def encode_command(exe, pattern, out_path, fps, fmt=FORMAT_MP4, quality=18):
    # type: (str, str, str, float, str, int) -> list
    """ffmpeg's arguments for turning a numbered sequence into a video.

    `-crf` is quality, not bitrate: 18 is visually lossless for the flat
    shading a molecule render produces, and a fixed bitrate would waste space
    on a still scene and starve a fast one. `yuv420p` is not optional — the
    default `yuv444p` plays in nothing but VLC.
    """
    cmd = [exe, "-y", "-framerate", "{:.6g}".format(float(fps)),
           "-i", pattern]
    if fmt == FORMAT_GIF:
        # One pass with a generated palette; a GIF from the default 216-colour
        # web palette bands badly on smooth spheres.
        cmd += ["-vf", "split[a][b];[a]palettegen[p];[b][p]paletteuse",
                out_path]
        return cmd
    cmd += ["-c:v", "libx264", "-preset", "slow",
            "-crf", str(int(quality)), "-pix_fmt", "yuv420p", out_path]
    return cmd


def encode(pattern, out_path, fps, fmt=FORMAT_MP4, quality=18, timeout=1800):
    # type: (str, str, float, str, int, float) -> Tuple[bool, str]
    """Run ffmpeg over an already-written sequence. Never raises."""
    exe = ffmpeg_executable()
    if not exe:
        return False, ("No ffmpeg. `pip install imageio-ffmpeg` brings a "
                       "self-contained one, or put ffmpeg on PATH.")
    try:
        proc = subprocess.run(encode_command(exe, pattern, out_path, fps, fmt,
                                             quality),
                              stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)
    out = (proc.stdout or b"").decode("utf-8", "replace")
    if proc.returncode != 0:
        return False, "ffmpeg exited {}\n{}".format(proc.returncode,
                                                    out[-2000:])
    if not os.path.exists(out_path):
        return False, "ffmpeg ran but wrote no file\n" + out[-2000:]
    return True, out


def summarise(n_images, fps, fmt):
    # type: (int, float, str) -> str
    seconds = float(n_images) / max(float(fps), 1e-6)
    return "{} image(s) at {:g} fps — {:.1f} s of {}".format(
        n_images, fps, seconds, str(fmt).upper())


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
