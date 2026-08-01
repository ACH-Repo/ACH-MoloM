"""MoloM savepoint files (`.molom`) — the program's own project format.

A savepoint is everything an xyz cannot carry: several molecules with their
names, visibility, per-object display style, object origins and local frames,
bond orders, trajectory frames, plus the camera and view settings. Losing any
of that on save/reload is what makes a builder frustrating to live in.

Plain UTF-8 JSON (readable, diffable, git-friendly) with an explicit format
tag and version so old files stay loadable as the schema grows. UI-free: the
app hands in a Scene and a view dict and gets them back.
"""

import datetime
import json
import os
from typing import Optional

FORMAT = "molom-project"
VERSION = 1
EXTENSION = ".molom"
FILE_FILTER = "MoloM project (*.molom)"


class ProjectError(Exception):
    """Raised for unreadable/foreign/corrupt savepoint files."""


def save_project(path, scene, view=None, ui=None):
    # type: (str, object, Optional[dict], Optional[dict]) -> str
    """Write a savepoint. Returns the path actually written (extension added
    when missing). The write is atomic-ish: a temp file is renamed into place
    so a crash mid-write cannot shred an existing project."""
    if not os.path.splitext(path)[1]:
        path += EXTENSION
    payload = {
        "format": FORMAT,
        "version": VERSION,
        "saved": datetime.datetime.now().isoformat(timespec="seconds"),
        "scene": scene.to_dict(),
        "view": dict(view or {}),
        "ui": dict(ui or {}),
    }
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=1)
        if os.path.exists(path):
            os.remove(path)
        os.rename(tmp, path)
    except OSError as e:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise ProjectError("could not write {}: {}".format(path, e))
    return path


def load_project(path):
    # type: (str) -> dict
    """Read a savepoint; returns the payload dict. Raises ProjectError on
    anything that is not a readable MoloM project."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except OSError as e:
        raise ProjectError("could not read {}: {}".format(path, e))
    except ValueError as e:
        raise ProjectError("{} is not valid JSON: {}".format(path, e))
    if not isinstance(payload, dict) or payload.get("format") != FORMAT:
        raise ProjectError(
            "{} is not a MoloM project file".format(os.path.basename(path)))
    if int(payload.get("version", 0)) > VERSION:
        raise ProjectError(
            "{} was written by a newer MoloM (file version {}, this build "
            "reads {})".format(os.path.basename(path),
                               payload.get("version"), VERSION))
    if "scene" not in payload:
        raise ProjectError("project file has no scene")
    return payload


def is_project_file(path):
    # type: (str) -> bool
    return os.path.splitext(path)[1].lower() == EXTENSION
