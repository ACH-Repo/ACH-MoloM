"""Round 65: launch-time regression guards (roadmap item 8).

Christian, 2026-08-11: "Add periodic launch time tests. The startup is getting
slow." Nothing in the suite would have noticed: 1378 tests build `MainWindow()`
over and over and none of them times it, so startup could regress by half a
second a round and only ever be felt.

WHAT IS AND IS NOT ASSERTED HERE. A wall-clock threshold is a MACHINE-SPEED
assertion, and this project runs on a laptop and a desktop with very different
CPUs - `assert t < 2.0` would either pass everywhere (useless) or fail on the
slower machine (noise). So these tests assert STRUCTURE, which is portable and
is where regressions actually come from:

  * heavy third-party modules must not be imported to use `molom.core`
  * the network stack must not be imported just to open a window
  * expensive widgets must not be built before anything asks for them

The wall-clock breakdown a human reads lives in `tools/startup_profile.py`.

Measured on the desktop PC, 2026-08-12, for the record: 3269 ms before this
round and 2877 ms after. `MainWindow()` is ~940 ms cold and ~43 ms warm, so
almost all of that is Qt's one-off font and style caching rather than MoloM's
own widgets - which is the honest answer to "why is startup slow" and the
reason these guards are about not ADDING to it.
"""

import subprocess
import sys

import pytest

#: Modules that cost real time and must not be dragged in by an import that
#: does not need them. rdkit/openbabel are the optional chemistry tiers;
#: pymatgen is a CIF backstop; the urllib/http/email chain is the name
#: resolver and costs about 130 ms on its own.
HEAVY = ("rdkit", "openbabel", "pymatgen", "matplotlib", "scipy",
         "urllib.request", "http.client", "email.parser")


def _imported_by(statement, watch=HEAVY):
    """Which of `watch` end up in `sys.modules` after `statement`.

    Run in a FRESH interpreter: within this one the test suite has already
    imported half the world, so an in-process check would prove nothing.
    """
    code = ("import sys\n{}\n"
            "print(','.join(m for m in {!r} if m in sys.modules))").format(
                statement, list(watch))
    proc = subprocess.run([sys.executable, "-c", code],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        pytest.fail("{!r} failed:\n{}".format(
            statement, proc.stderr.decode("utf-8", "replace")[-2000:]))
    out = proc.stdout.decode("utf-8", "replace").strip()
    return [m for m in out.split(",") if m]


# ------------------------------------------------------- core stays light
def test_core_pulls_in_nothing_heavy():
    """`molom/core` is the UI-free, offline-testable half. rdkit and openbabel
    are OPTIONAL tiers reached at run time, so importing core must not pay for
    them - that is the whole point of the tiering."""
    assert _imported_by("import molom.core") == []


@pytest.mark.parametrize("module", ["molom.core.io", "molom.core.cif",
                                    "molom.core.structure",
                                    "molom.core.bonding",
                                    "molom.core.animation"])
def test_individual_core_modules_stay_light(module):
    assert _imported_by("import " + module) == []


def test_the_import_cascade_is_lazy():
    """`core.io` names rdkit and openbabel all through it, but only inside the
    functions that use them - if that ever moves to module scope, every launch
    pays for a parser most files do not need."""
    assert "rdkit" not in _imported_by("import molom.core.io")


# -------------------------------------------- opening a window stays light
def test_opening_the_ui_does_not_import_the_network_stack():
    """`core.resolve` (import-by-name, PubChem lookups) drags in
    urllib/http/email for about 130 ms. Most launches never resolve a name, so
    it is imported at its use sites instead."""
    got = _imported_by("import molom.ui.app")
    assert "urllib.request" not in got, \
        "the network stack is being imported just to open a window"
    assert "http.client" not in got


def test_the_ui_does_not_import_the_optional_chemistry_tiers():
    got = _imported_by("import molom.ui.app")
    assert "rdkit" not in got and "openbabel" not in got


def test_resolve_is_not_imported_at_module_scope():
    """Pinned as SOURCE too, because the import check above would still pass if
    something else happened to pull urllib in first."""
    import inspect
    import molom.ui.app as app_mod
    import molom.ui.dialogs as dialogs_mod
    for module in (app_mod, dialogs_mod):
        head = inspect.getsource(module).split("\ndef ", 1)[0]
        head = head.split("\nclass ", 1)[0]
        assert "import resolve" not in head, \
            "{} imports the resolver at module scope".format(module.__name__)
        # `molsearch` reaches the resolver, so importing IT at module scope
        # costs exactly the same 130 ms by a different route - which is how
        # round 90 reintroduced this, caught by the runtime check above.
        assert "import molsearch" not in head, (
            "{} imports molsearch at module scope".format(module.__name__))


# --------------------------------------- expensive widgets are built lazily
def test_the_periodic_table_is_not_built_until_it_is_needed():
    """118 painted cells, hidden at startup - it only appears in plain edit
    mode. Building it eagerly meant every launch paid for a widget nobody had
    asked to see."""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.app import MainWindow
    QApplication.instance() or QApplication([])
    win = MainWindow()
    assert win._ptable is None, "the periodic table was built eagerly"


def test_asking_for_the_periodic_table_builds_it_once():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.app import MainWindow
    QApplication.instance() or QApplication([])
    win = MainWindow()
    first = win.ptable
    assert first is not None
    assert win.ptable is first, "it must be built once, not per access"


def test_leaving_edit_mode_does_not_build_it():
    """`_sync_ptable` runs on every mode change, so a careless `self.ptable`
    there would undo the laziness immediately."""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.app import MainWindow
    QApplication.instance() or QApplication([])
    win = MainWindow()
    win._sync_ptable()
    assert win._ptable is None


# ----------------------------------------------- the profiler still works
def test_the_startup_profiler_runs():
    """It is the human-readable half of this feature, so it has to keep
    working - a tool nobody can run is a tool nobody will run."""
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = os.path.join(root, "tools", "startup_profile.py")
    assert os.path.exists(script)
    proc = subprocess.run([sys.executable, script, "--imports"],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          cwd=root, timeout=300)
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")[-1500:]
    assert b"cumulative ms" in proc.stdout
