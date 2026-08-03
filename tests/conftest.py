"""Shared test setup.

**Tests must never touch the developer's real configuration.** `MainWindow`
persists genuine preferences through `QSettings("ACH", "MoloM")` — the input
preset, sphere size, undo depth, the playback framerate — and a test that
drives one of those widgets writes the value it poked straight into the live
config. That is exactly how a test run once left MoloM starting at 10 fps
with smoothing off: the test set the spin box, the app dutifully remembered
it, and the next real session inherited a test's throwaway value.

Redirecting QSettings to an INI file under a temp directory keeps the whole
suite in a sandbox. It must happen before any `MainWindow` is constructed,
which is why it lives at import time in conftest rather than in a fixture.
"""

import os
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import QSettings
except ImportError:                       # PySide6 absent: core-only run
    pass
else:
    _SANDBOX = tempfile.mkdtemp(prefix="molom-test-settings-")
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, _SANDBOX)

    class _SandboxSettings(QSettings):
        """An INI file in a temp directory, wherever the app asks for one.

        `setDefaultFormat` is not enough: on Windows the two-argument
        `QSettings(org, app)` constructor always uses NativeFormat, i.e. the
        REGISTRY, and `setPath` has no effect on that. Forcing the four-
        argument form is the only redirect that actually holds.
        """

        def __init__(self, *args, **_kw):
            super().__init__(QSettings.IniFormat, QSettings.UserScope,
                             args[0] if args else "ACH",
                             args[1] if len(args) > 1 else "MoloM")

    from molom.ui import app as _app_module
    _app_module.QSettings = _SandboxSettings
