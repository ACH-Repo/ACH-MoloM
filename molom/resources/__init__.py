"""Bundled image resources — the application icon, for now.

Kept as a real PACKAGE with an `__init__.py` rather than a bare data folder so
`[tool.setuptools] packages` (a hand-written list, see round 59) picks it up the
same way every other subpackage does, and so the path can be found from the
module's own location instead of guessed relative to the current directory.
"""

import os

HERE = os.path.dirname(os.path.abspath(__file__))

#: The source of truth. Everything else in here is rendered FROM this.
SVG = os.path.join(HERE, "logo.svg")

#: Pre-rendered fallbacks. `QIcon` can read the SVG directly when Qt's svg
#: imageformat plugin is present, but that is a deployment detail we do not
#: control — and an application with no icon falls back to the generic Python
#: one, which is exactly what this exists to stop. PNGs always work.
SIZES = (16, 24, 32, 48, 64, 128, 256)


def png(size):
    # type: (int) -> str
    return os.path.join(HERE, "logo_{}.png".format(int(size)))


def app_icon():
    """A `QIcon` carrying every rendered size, or None if Qt is unavailable.

    Several sizes rather than one scaled image: Windows picks a different one
    for the taskbar, the title bar and Alt-Tab, and letting it downscale a
    256 px logo to 16 px turns fine strokes into mush.
    """
    try:
        from PySide6.QtGui import QIcon
    except ImportError:                      # core stays importable headless
        return None
    icon = QIcon()
    for size in SIZES:
        path = png(size)
        if os.path.exists(path):
            icon.addFile(path)
    if icon.isNull() and os.path.exists(SVG):
        icon.addFile(SVG)                    # last resort, needs the plugin
    return None if icon.isNull() else icon
