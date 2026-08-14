"""Round 73: MOPAC as an add-on, and the extension point that lets it in.

Christian's constraint, scoped 2026-08-10 and built 2026-08-13: "the dependency
is apparently tiny. Could probably run it in molom itself. But idk how well we
can integrate that as an addon that doesn't mess with anything else in the
software."

So `core/forcefield.py` gains a registry - a dict and a signature - and nothing
else. Every line that knows what MOPAC is lives in `molom/addons/`. The tests
below are mostly about that boundary holding: core must not import the add-on,
the add-on must not be imported to be LISTED, and disabling it must leave the
Method list exactly as it was.

The live round trip is verified separately by running a real MOPAC job; this
project does not write parser fixtures from memory (round 27), so no synthetic
MOPAC output appears here.
"""

import os

import numpy as np
import pytest

from molom.core import forcefield


@pytest.fixture(autouse=True)
def _clean_registry():
    """Leave the registry as it was found.

    A module-level dict is shared across the whole suite, and round 39's
    circuit-breaker bug is what happens when that is forgotten: a test that
    passes alone and fails in the full run, in a different file, with no
    obvious connection.
    """
    from molom.addons import mopac_optimize
    for key, _label, _h in mopac_optimize.HAMILTONIANS:
        forcefield.unregister_method(key)
    yield
    for key, _label, _h in mopac_optimize.HAMILTONIANS:
        forcefield.unregister_method(key)


@pytest.fixture
def win():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.app import MainWindow
    QApplication.instance() or QApplication([])
    win = MainWindow()
    win.load_default_scene()
    return win


# ------------------------------------------------------- the extension point
def test_the_builtin_methods_are_untouched_by_the_registry():
    assert [k for k, _ in forcefield.all_methods()] == \
        [k for k, _ in forcefield.METHODS]


def test_a_registered_method_appears_in_the_list():
    forcefield.register_method("mopac_pm7", "MOPAC PM7", lambda *a, **k: None)
    keys = [k for k, _ in forcefield.all_methods()]
    assert "mopac_pm7" in keys
    assert keys[:len(forcefield.METHODS)] == [k for k, _ in forcefield.METHODS]


def test_registering_twice_does_not_double_the_entry():
    """Enabling an add-on twice is an ordinary thing to do."""
    for _ in range(3):
        forcefield.register_method("mopac_pm7", "MOPAC PM7",
                                   lambda *a, **k: None)
    assert [k for k, _ in forcefield.all_methods()].count("mopac_pm7") == 1


def test_unregistering_something_that_was_never_there_is_silent():
    """So an add-on's `unregister` never has to guard against a `register`
    that failed half way."""
    forcefield.unregister_method("never_existed")


def test_the_method_list_is_built_fresh_every_time():
    """Add-ons are enabled while the window is open, so a cached list is how
    the panel ends up offering a method that has just been removed."""
    forcefield.register_method("mopac_pm7", "x", lambda *a, **k: None)
    assert "mopac_pm7" in [k for k, _ in forcefield.all_methods()]
    forcefield.unregister_method("mopac_pm7")
    assert "mopac_pm7" not in [k for k, _ in forcefield.all_methods()]


def test_optimize_routes_to_the_registered_callable():
    seen = {}

    def fake(symbols, coords, bonds, steps=None, fixed=None):
        seen.update(n=len(symbols), steps=steps, fixed=fixed)
        return np.zeros((len(symbols), 3)), {"engine": "fake"}

    forcefield.register_method("mopac_pm7", "MOPAC PM7", fake)
    out, info = forcefield.optimize(["C", "H"], np.array([[0., 0., 0.],
                                                          [1., 0., 0.]]),
                                    [(0, 1, 1)], method="mopac_pm7",
                                    steps=77, fixed=[0])
    assert info["engine"] == "fake"
    assert seen == {"n": 2, "steps": 77, "fixed": [0]}


def test_an_external_method_does_NOT_fall_back_to_a_force_field():
    """Dropping MMFF94 -> UFF is a change of force field. Dropping a
    semiempirical Hamiltonian to a force field is a change of PHYSICS, and
    returning an MMFF94 geometry labelled as the thing the user asked for is
    the silent substitution round 38 argued against."""
    def boom(symbols, coords, bonds, steps=None, fixed=None):
        raise forcefield.ForceFieldError("MOPAC was not found")

    forcefield.register_method("mopac_pm7", "MOPAC PM7", boom)
    with pytest.raises(forcefield.ForceFieldError) as excinfo:
        forcefield.optimize(["C", "H"], np.array([[0., 0., 0.], [1., 0., 0.]]),
                            [(0, 1, 1)], method="mopac_pm7")
    assert "not found" in str(excinfo.value)


def test_core_does_not_import_the_addon():
    """The dependency runs one way only, which is what keeps an add-on
    removable - and what keeps `core/` free of subprocesses it does not own.

    Checked as IMPORTS, via the AST, not by grepping the source for the word:
    the first cut did the latter and failed on the comment that explains why
    the extension point exists, which is round 71's "a test that pinned the
    wrong thing" all over again. Core is allowed to say `mopac`; it is not
    allowed to import it.
    """
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(forcefield))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    assert not [m for m in imported
                if "addons" in m or "mopac" in m.lower()], imported


def test_importing_core_does_not_pull_the_addon_in():
    """The runtime half of the same claim."""
    import subprocess
    import sys
    code = ("import molom.core.forcefield, sys; "
            "print(any('mopac' in m for m in sys.modules))")
    out = subprocess.run([sys.executable, "-c", code],
                         stdout=subprocess.PIPE).stdout.decode().strip()
    assert out.endswith("False"), out


# ------------------------------------------------------------- the input deck
def _deck(fixed=None):
    from molom.addons import mopac_optimize as m
    return m.build_input(["C", "H", "O"],
                         np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]]),
                         "PM7", fixed=fixed)


def test_the_deck_has_a_keyword_line_a_title_and_one_row_per_atom():
    lines = _deck().splitlines()
    assert lines[0] == "PM7"
    assert lines[2] == ""                      # MOPAC wants the blank line
    rows = [l for l in lines[3:] if l.strip()]
    assert len(rows) == 3
    assert rows[0].split()[0] == "C"


def test_every_coordinate_is_flagged_for_optimisation_by_default():
    rows = [l for l in _deck().splitlines()[3:] if l.strip()]
    for row in rows:
        assert row.split()[2::2][:3] == ["1", "1", "1"]


def test_a_FROZEN_atom_gets_zero_flags_on_all_three_coordinates():
    """The whole reason MOPAC is worth having for metal complexes: round 62
    found OpenBabel UFF ignoring `fixed` entirely, and that is the tier every
    metal complex fell through to. Here the constraint is in the format."""
    rows = [l for l in _deck(fixed=[1]).splitlines()[3:] if l.strip()]
    assert rows[0].split()[2::2][:3] == ["1", "1", "1"]
    assert rows[1].split()[2::2][:3] == ["0", "0", "0"]
    assert rows[2].split()[2::2][:3] == ["1", "1", "1"]


def test_the_deck_is_pure_ascii():
    """Round 37's rule, in a third language: a file written for another
    program must not carry whatever encoding the writing step happened to
    use."""
    from molom.addons import mopac_optimize as m
    deck = m.build_input(["C"], np.zeros((1, 3)), "PM7", title="MoloM")
    deck.encode("ascii")


# ---------------------------------------------------------------- keywords
def test_a_neutral_singlet_says_nothing_extra():
    from molom.addons import mopac_optimize as m
    assert m.build_keywords("PM7") == "PM7"


def test_charge_and_spin_are_stated_explicitly():
    """A metal complex is very often neither neutral nor a singlet, and
    MOPAC's default of both would optimise a different species from the one on
    screen - confidently, and with no warning."""
    from molom.addons import mopac_optimize as m
    words = m.build_keywords("PM7", charge=2, multiplicity=3).split()
    assert "PM7" in words and "CHARGE=2" in words and "TRIPLET" in words


def test_the_step_count_reaches_mopac():
    from molom.addons import mopac_optimize as m
    assert "CYCLES=250" in m.build_keywords("PM7", steps=250)


def test_precise_is_not_on_by_default():
    """This is a builder's clean-up, not a publication geometry."""
    from molom.addons import mopac_optimize as m
    assert "PRECISE" not in m.build_keywords("PM7")
    assert "PRECISE" in m.build_keywords("PM7", extra="PRECISE")


# ------------------------------------------------------- degrading gracefully
def test_a_missing_mopac_is_an_ordinary_state_not_an_error():
    from molom.addons import mopac_optimize as m
    assert m.find_mopac(hint="/nowhere/at/all/mopac") is None or \
        os.path.isfile(m.find_mopac(hint="/nowhere/at/all/mopac"))


def test_running_without_a_binary_says_how_to_get_one(monkeypatch):
    """Round 61's rule: a message that only lists what is broken reads as a
    dead end, so it names the fix.

    The absence is FORCED rather than assumed. The first cut just passed an
    empty path and relied on this machine having no MOPAC - which stopped
    being true half an hour later, and would never have been true on the other
    dev machine. A test about the missing-binary path has to create the
    missing binary.
    """
    from molom.addons import mopac_optimize as m
    monkeypatch.setattr(m, "find_mopac", lambda *a, **k: None)
    with pytest.raises(forcefield.ForceFieldError) as excinfo:
        m.run_mopac(["C", "H"], np.array([[0., 0., 0.], [1., 0., 0.]]))
    message = str(excinfo.value)
    assert "conda" in message or "github.com/openmopac" in message


def test_a_nonexistent_executable_is_reported_not_raised_raw():
    from molom.addons import mopac_optimize as m
    with pytest.raises(forcefield.ForceFieldError):
        m.run_mopac(["C", "H"], np.array([[0., 0., 0.], [1., 0., 0.]]),
                    executable=os.path.join(os.sep, "nope", "mopac.exe"))


# --------------------------------------------------------------- the add-on
def test_the_addon_is_discovered_and_listed(win):
    from molom.core import addons as addons_mod
    found = [a for a in addons_mod.discover() if a.id == "mopac_optimize"]
    assert found, "the bundled add-on is not discovered"
    assert "MOPAC" in found[0].name


def test_listing_the_addon_does_not_IMPORT_it():
    """Round 46's rule: metadata is parsed with `ast`, so one broken add-on
    cannot take the preferences dialog down with it."""
    import sys
    for name in [n for n in list(sys.modules)
                 if "mopac_optimize" in n]:
        del sys.modules[name]
    from molom.core import addons as addons_mod
    addons_mod.discover()
    assert not [n for n in sys.modules if n.endswith("mopac_optimize")], \
        "discovery imported the module"


def test_registering_puts_the_methods_in_the_PANEL(win):
    from molom.addons import mopac_optimize as m
    combo = win.optimize_panel.method_combo
    before = combo.count()
    m.register(win)
    labels = [combo.itemText(i) for i in range(combo.count())]
    assert combo.count() == before + len(m.HAMILTONIANS)
    assert "MOPAC PM7" in labels
    m.unregister(win)
    assert combo.count() == before


def test_unregistering_leaves_the_panel_exactly_as_it_was(win):
    from molom.addons import mopac_optimize as m
    combo = win.optimize_panel.method_combo
    before = [(combo.itemText(i), combo.itemData(i))
              for i in range(combo.count())]
    m.register(win)
    m.unregister(win)
    after = [(combo.itemText(i), combo.itemData(i))
             for i in range(combo.count())]
    assert after == before


def test_enabling_an_addon_does_not_reset_the_users_method(win):
    """The combo is rebuilt, so a naive implementation silently drops the user
    back to MMFF94 every time an unrelated add-on is toggled."""
    from molom.addons import mopac_optimize as m
    combo = win.optimize_panel.method_combo
    combo.setCurrentIndex(combo.findData("uff"))
    m.register(win)
    assert combo.currentData() == "uff"
    m.unregister(win)
    assert combo.currentData() == "uff"


def test_the_registered_method_survives_a_round_trip_through_optimize(
        win, monkeypatch):
    """The panel hands `optimize` a key; that key has to reach the add-on.

    Driven with the binary forced ABSENT so it runs the same on both dev
    machines - what is under test is the routing and the refusal to fall back,
    not MOPAC. The live job is `test_a_real_PM7_job` below.
    """
    from molom.addons import mopac_optimize as m
    monkeypatch.setattr(m, "find_mopac", lambda *a, **k: None)
    m.register(win)
    try:
        assert forcefield.external_method("mopac_pm7") is not None
        with pytest.raises(forcefield.ForceFieldError):
            forcefield.optimize(["C", "H"],
                                np.array([[0., 0., 0.], [1., 0., 0.]]),
                                [(0, 1, 1)], method="mopac_pm7")
    finally:
        m.unregister(win)


# --------------------------------------------------- live, when MOPAC is here
def _no_mopac():
    from molom.addons import mopac_optimize as m
    return m.find_mopac() is None


needs_mopac = pytest.mark.skipif(_no_mopac(),
                                 reason="no MOPAC on this machine")


@needs_mopac
def test_a_real_PM7_job_optimises_water():
    """Cross-checked against CHEMISTRY, not against a number I chose: PM7 is
    fitted to the experimental heat of formation of water, so -57.8 kcal/mol
    is an independent statement that the whole path - deck, invocation,
    read-back - did what it claims. The geometry has to be water's too."""
    from molom.addons import mopac_optimize as m
    out, info = m.run_mopac(["O", "H", "H"],
                            np.array([[0., 0., 0.], [0.95, 0., 0.],
                                      [-0.3, 0.9, 0.]]))
    assert info["engine"] == "mopac" and info["converged"]
    assert info["energy"] == pytest.approx(-57.8, abs=0.3)
    d1 = float(np.linalg.norm(out[1] - out[0]))
    v1, v2 = out[1] - out[0], out[2] - out[0]
    angle = np.degrees(np.arccos(float(v1 @ v2)
                                 / (np.linalg.norm(v1) * np.linalg.norm(v2))))
    assert 0.93 < d1 < 0.99, d1
    assert 100.0 < angle < 110.0, angle


@needs_mopac
def test_a_real_job_holds_the_FROZEN_atoms_exactly():
    """Round 62's bug from the other side: the tier every metal complex lands
    on was the one that ignored `fixed`. MOPAC's per-coordinate flags are the
    constraint, so this is 0.000000 and not merely small."""
    from molom.addons import mopac_optimize as m
    xyz = np.array([[0., 0., 0.], [0.95, 0., 0.], [-0.3, 0.9, 0.]])
    out, _info = m.run_mopac(["O", "H", "H"], xyz, fixed=[0, 1])
    assert float(np.max(np.linalg.norm(out[[0, 1]] - xyz[[0, 1]],
                                       axis=1))) == 0.0
    assert float(np.linalg.norm(out[2] - xyz[2])) > 0.0


@needs_mopac
def test_a_real_job_on_a_metal_a_force_field_cannot_touch():
    """The reason this add-on exists. MMFF94 has no parameters for platinum
    and quietly hands back a UFF guess; PM7 gives PtCl4(2-) its four equal
    Pt-Cl bonds at the experimental ~2.31 A."""
    from molom.addons import mopac_optimize as m
    sym = ["Pt", "Cl", "Cl", "Cl", "Cl"]
    xyz = np.array([[0, 0, 0], [2.4, 0, 0], [-2.4, 0, 0],
                    [0, 2.4, 0], [0, -2.4, 0]], dtype=float)
    out, info = m.run_mopac(sym, xyz, charge=-2)
    lengths = [float(np.linalg.norm(out[j] - out[0])) for j in range(1, 5)]
    assert info["converged"]
    for d in lengths:
        assert 2.2 < d < 2.45, lengths
    assert max(lengths) - min(lengths) < 0.02, lengths


@needs_mopac
def test_the_atom_ORDER_is_preserved_through_a_real_job():
    """Everything upstream is keyed by index - bonds, selection, per-atom
    colours, the meta table - so a reader that reordered atoms would silently
    rewire the molecule."""
    from molom.addons import mopac_optimize as m
    sym = ["O", "H", "C", "H", "H", "H"]
    xyz = np.array([[0., 0., 0.], [0.96, 0., 0.], [-0.6, 1.2, 0.],
                    [-1.6, 1.0, 0.2], [-0.3, 1.9, 0.8], [-0.5, 1.7, -0.9]])
    out, _info = m.run_mopac(sym, xyz)
    assert out.shape == (6, 3)
    # The C-O bond is still between the atoms that had it.
    assert 1.3 < float(np.linalg.norm(out[2] - out[0])) < 1.6


# ------------------------------------------- against a REAL MOPAC output
# `tests/data/mopac_pm7_water.out` is verbatim from MOPAC v23.2.5 on this
# machine, per the rule that a parser fixture is never written from memory
# (round 27). It is the water job whose result cross-checks itself: PM7 is
# fitted to the experimental heat of formation of water, so -57.8 kcal/mol
# coming back out is an independent statement that the right number was read
# and not merely a number.
FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "data", "mopac_pm7_water.out")


def test_the_geometry_reads_back_through_openbabel():
    from molom.addons import mopac_optimize as m
    symbols, coords = m.read_output_geometry(FIXTURE)
    assert symbols == ["O", "H", "H"]
    assert coords.shape == (3, 3)
    d1 = float(np.linalg.norm(coords[1] - coords[0]))
    d2 = float(np.linalg.norm(coords[2] - coords[0]))
    assert 0.90 < d1 < 1.02 and 0.90 < d2 < 1.02, (d1, d2)


def test_the_angle_is_waters_angle_not_the_input_geometry():
    """The input was a deliberately bent 108-degree guess; a reader that
    returned the FIRST geometry block rather than the last would hand back
    what was put in and look perfectly plausible."""
    from molom.addons import mopac_optimize as m
    _sym, coords = m.read_output_geometry(FIXTURE)
    v1 = coords[1] - coords[0]
    v2 = coords[2] - coords[0]
    angle = np.degrees(np.arccos(float(v1 @ v2)
                                 / (np.linalg.norm(v1) * np.linalg.norm(v2))))
    assert 100.0 < angle < 110.0, angle


def test_the_heat_of_formation_is_read():
    from molom.addons import mopac_optimize as m
    text = open(FIXTURE, encoding="utf-8", errors="replace").read()
    assert m.read_heat_of_formation(text) == pytest.approx(-57.8, abs=0.2)


def test_a_file_with_no_heat_of_formation_returns_None_rather_than_raising():
    """It is reported as information and nothing downstream depends on it, so
    a MOPAC build that words the line differently costs a label, not the
    geometry."""
    from molom.addons import mopac_optimize as m
    assert m.read_heat_of_formation("nothing to see here") is None


# ------------------------------------- loading it the way the DIALOG does
def _purge():
    """Add-on modules are cached in `sys.modules` under `molom_addon_*`
    deliberately (enabling twice must not re-execute), which makes a loaded
    add-on shared across the whole suite - round 46's trap."""
    import sys
    for name in [n for n in list(sys.modules) if n.startswith("molom_addon_")]:
        del sys.modules[name]


def test_every_bundled_addon_ENABLES_through_the_real_loader(win):
    """The test that was missing, and the bug it would have caught.

    `core/addons.py` imports an add-on BY PATH under a synthetic module name,
    so the module has NO package context and any relative import fails with
    "attempted relative import with no known parent package" - a failure to
    load at all, shown as a red line in the preferences dialog. The MOPAC
    add-on shipped with `from ..core import forcefield` and did exactly that.

    Every other test here imported the module as `molom.addons.mopac_optimize`,
    which HAS package context and works perfectly - so the whole file passed
    while the feature was unreachable in the application. Same shape as round
    59's "a mechanism with tests and no gesture test is a feature nobody can
    reach": the tests exercised the module, never the loading path.

    Written over ALL bundled add-ons rather than just this one, because the
    next add-on is the one that will repeat it.
    """
    from molom.core import addons as addons_mod
    _purge()
    try:
        manager = addons_mod.AddOnManager()
        bundled = [a for a in addons_mod.discover()
                   if os.path.abspath(os.path.dirname(a.path))
                   == os.path.abspath(addons_mod.bundled_dir())]
        assert bundled, "no bundled add-ons discovered"
        for info in bundled:
            ok, message = manager.enable(info.id, win)
            assert ok, "{} failed to enable: {}".format(info.id, message)
            manager.disable(info.id, win)
    finally:
        _purge()


def test_no_bundled_addon_uses_a_RELATIVE_import():
    """The same claim as a static one, so it fails at the line rather than at
    the symptom - and without needing a window."""
    import ast
    from molom.core import addons as addons_mod
    folder = addons_mod.bundled_dir()
    offenders = []
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".py"):
            continue
        tree = ast.parse(open(os.path.join(folder, name),
                              encoding="utf-8").read())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level:
                offenders.append("{}:{}".format(name, node.lineno))
    assert not offenders, (
        "relative imports cannot work in an add-on loaded by path: "
        + ", ".join(offenders))
