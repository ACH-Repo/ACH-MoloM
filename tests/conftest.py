"""Shared test setup.

**Tests must never touch the developer's real configuration.** `MainWindow`
persists genuine preferences through `QSettings("ACH", "MoloM")` — the input
preset, sphere size, undo depth, the playback framerate — and a test that
drives one of those widgets writes the value it poked straight into the live
config. That is exactly how a test run once left MoloM starting at 10 fps
with smoothing off: the test set the spin box, the app dutifully remembered
it, and the next real session inherited a test's throwaway value. (The
smoothing box itself is gone as of round 77 - it became a per-strip frame
count, which lives in the scene rather than in a preference - but the
framerate beside it is still persisted, and the trap is the same.)

Redirecting QSettings to an INI file under a temp directory keeps the whole
suite in a sandbox. It must happen before any `MainWindow` is constructed,
which is why it lives at import time in conftest rather than in a fixture.
"""

import os
import tempfile

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def _fresh_resolver_state():
    """Forget any recorded service outage between tests.

    The resolver's circuit breaker (round 37) is module-global by design — it
    exists so a session does not pay a dead service's timeout twice. That
    makes it shared state across the suite: anything that reaches the real
    network once (a resolver dialog, a live probe) marks OPSIN down, and every
    later test that expects OPSIN to be TRIED then fails, in a different file,
    with no obvious connection. It presented as two round-37 tests failing in
    the full run and passing alone, which is the signature of exactly this.
    """
    try:
        from molom.core import resolve
    except ImportError:
        yield
        return
    resolve.reset_service_state()
    yield
    resolve.reset_service_state()

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

    @pytest.fixture(autouse=True)
    def _fresh_settings():
        """Empty the sandbox between tests.

        The sandbox stops a test writing into the DEVELOPER's config; it does
        nothing about one test writing into the NEXT test's. `MainWindow`
        reads its preferences on construction, so a test that pokes a
        persisted widget - `win._fps_spin.setValue(10)` is the real one -
        hands its throwaway value to every window built after it, in a
        different file, with no visible connection. Round 77's playback tests
        were the first to assert anything derived from the framerate and duly
        failed only in the full run, which is the same signature as the
        round-37 circuit breaker above and the round-46 module cache.

        Cleared AFTER each test rather than before, so a window built at
        collection time still sees a clean slate.
        """
        yield
        _SandboxSettings("ACH", "MoloM").clear()
