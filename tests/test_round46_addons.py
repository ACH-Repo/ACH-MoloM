"""Round 46: installable add-ons, Blender's model.

The contract: an add-on is a module with an ADDON dict and register() /
unregister(); metadata is read WITHOUT importing; enabling is opt-in and a
broken one must never take the application with it.
"""
import os
import textwrap

import pytest

from molom.core import addons

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

GOOD = '''\
ADDON = {"id": "unit_good", "name": "Good One",
         "description": "Does a thing.", "version": (2, 1),
         "author": "Tester"}
CALLS = []
def register(window):
    CALLS.append(("register", window))
def unregister(window):
    CALLS.append(("unregister", window))
'''

NO_METADATA = "def register(window):\n    pass\n"
BROKEN_IMPORT = ('ADDON = {"id": "unit_boom", "name": "Boom"}\n'
                 'raise RuntimeError("exploded on import")\n')
BROKEN_REGISTER = ('ADDON = {"id": "unit_bad_reg", "name": "Bad Register"}\n'
                   'def register(window):\n'
                   '    raise ValueError("no")\n')
SIDE_EFFECT = ('import pathlib\n'
               'pathlib.Path(__file__).with_suffix(".ran").write_text("x")\n'
               'ADDON = {"id": "unit_side", "name": "Side Effect"}\n'
               'def register(window):\n    pass\n')


@pytest.fixture(autouse=True)
def _forget_loaded_addons():
    """Purge imported add-ons between tests.

    `AddOnManager._import` caches in `sys.modules` on purpose — enabling
    twice must not re-execute a module — but that makes the loaded module
    (and any list it keeps) SHARED ACROSS THE SUITE, which is the round-37
    circuit-breaker trap in a new place: a test passes alone and fails in the
    full run, in a different file, for no visible reason.
    """
    import sys

    def purge():
        for name in [n for n in sys.modules if n.startswith("molom_addon_")]:
            del sys.modules[name]

    purge()
    yield
    purge()


@pytest.fixture
def addon_dir(tmp_path):
    def write(name, text):
        path = tmp_path / (name + ".py")
        path.write_text(textwrap.dedent(text), encoding="utf-8")
        return path
    return tmp_path, write


# ------------------------------------------------------------- discovery
def test_metadata_is_read_without_importing(addon_dir):
    """Listing add-ons must not execute third-party code — otherwise one
    broken module takes the whole preferences dialog down with it."""
    root, write = addon_dir
    write("side", SIDE_EFFECT)
    found = addons.discover([str(root)])
    assert [a.id for a in found] == ["unit_side"]
    assert not (root / "side.ran").exists()      # never imported


def test_discovery_reads_the_declared_fields(addon_dir):
    root, write = addon_dir
    write("good", GOOD)
    info = addons.discover([str(root)])[0]
    assert (info.id, info.name, info.version, info.author) == (
        "unit_good", "Good One", (2, 1), "Tester")
    assert not info.error


def test_a_module_without_metadata_is_listed_with_its_problem(addon_dir):
    """Listed, not hidden: an add-on the user cannot see is worse than one
    they can see is broken."""
    root, write = addon_dir
    write("plain", NO_METADATA)
    info = addons.discover([str(root)])[0]
    assert info.error
    assert info.id == "plain"


def test_packages_are_discovered_too(tmp_path):
    package = tmp_path / "thing"
    package.mkdir()
    (package / "__init__.py").write_text(GOOD, encoding="utf-8")
    assert [a.id for a in addons.discover([str(tmp_path)])] == ["unit_good"]


def test_private_and_dotted_entries_are_skipped(addon_dir):
    root, write = addon_dir
    write("_helper", GOOD)
    write(".hidden", GOOD)
    assert addons.discover([str(root)]) == []


# ------------------------------------------------------ enable / disable
def test_enable_calls_register_with_the_window(addon_dir):
    root, write = addon_dir
    write("good", GOOD)
    manager = addons.AddOnManager([str(root)])
    sentinel = object()
    ok, message = manager.enable("unit_good", sentinel)
    assert ok and not message
    assert manager.is_enabled("unit_good")
    module = manager._modules["unit_good"]
    assert module.CALLS == [("register", sentinel)]


def test_disable_calls_unregister(addon_dir):
    root, write = addon_dir
    write("good", GOOD)
    manager = addons.AddOnManager([str(root)])
    sentinel = object()
    manager.enable("unit_good", sentinel)
    module = manager._modules["unit_good"]
    manager.disable("unit_good", sentinel)
    assert not manager.is_enabled("unit_good")
    assert module.CALLS[-1] == ("unregister", sentinel)


def test_a_module_that_explodes_on_import_is_reported_not_raised(addon_dir):
    root, write = addon_dir
    write("boom", BROKEN_IMPORT)
    manager = addons.AddOnManager([str(root)])
    ok, message = manager.enable("unit_boom", object())
    assert not ok
    assert "exploded on import" in message
    assert not manager.is_enabled("unit_boom")


def test_a_register_that_raises_is_reported_not_raised(addon_dir):
    root, write = addon_dir
    write("bad", BROKEN_REGISTER)
    manager = addons.AddOnManager([str(root)])
    ok, message = manager.enable("unit_bad_reg", object())
    assert not ok
    assert "ValueError" in message
    assert not manager.is_enabled("unit_bad_reg")


def test_enable_all_collects_failures_instead_of_stopping(addon_dir):
    root, write = addon_dir
    write("good", GOOD)
    write("bad", BROKEN_REGISTER)
    manager = addons.AddOnManager([str(root)])
    failed = manager.enable_all(["unit_bad_reg", "unit_good"], object())
    assert set(failed) == {"unit_bad_reg"}
    assert manager.is_enabled("unit_good")       # the good one still loaded


def test_enabling_twice_is_a_no_op(addon_dir):
    root, write = addon_dir
    write("good", GOOD)
    manager = addons.AddOnManager([str(root)])
    manager.enable("unit_good", object())
    module = manager._modules["unit_good"]
    manager.enable("unit_good", object())
    assert len(module.CALLS) == 1


# ------------------------------------------------- the bundled ones
def test_the_bundled_pipeline_pages_are_present_and_off_by_default():
    found = {a.id: a for a in addons.discover()}
    assert "debug_pipeline" in found
    assert "sandbox_pipeline" in found
    assert all(found[k].bundled and not found[k].error
               for k in ("debug_pipeline", "sandbox_pipeline"))


def test_a_fresh_window_has_no_pipeline_tabs(qapp_window):
    """The whole point of moving them out: MoloM starts clean."""
    window = qapp_window
    assert "debug" not in window.properties.buttons
    assert "sandbox" not in window.properties.buttons
    assert not window.addons.enabled


def test_enabling_adds_the_tab_and_disabling_removes_it(qapp_window):
    window = qapp_window
    ok, message = window.addons.enable("sandbox_pipeline", window)
    assert ok, message
    assert "sandbox" in window.properties.buttons
    assert hasattr(window, "sandbox_page")
    window.addons.disable("sandbox_pipeline", window)
    assert "sandbox" not in window.properties.buttons


def test_both_can_be_on_at_once(qapp_window):
    window = qapp_window
    window.addons.enable("debug_pipeline", window)
    window.addons.enable("sandbox_pipeline", window)
    assert {"debug", "sandbox"} <= set(window.properties.buttons)
    # ...and the built-in tabs are untouched
    assert {"outliner", "modifiers", "crystal"} <= set(
        window.properties.buttons)


def test_the_enabled_set_is_persisted(qapp_window):
    window = qapp_window
    window.addons.enable("debug_pipeline", window)
    window.save_enabled_addons()
    stored = window.settings.value("addons/enabled", [])
    if isinstance(stored, str):
        stored = [stored]
    assert "debug_pipeline" in list(stored)


@pytest.fixture
def qapp_window():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.app import MainWindow
    QApplication.instance() or QApplication([])
    window = MainWindow()
    window.load_default_scene()
    return window
