"""Round 16: pointing-device wheel mapping + the operator key table.

The key table is checked WITHOUT starting Qt: `_register_operators` only ever
touches `self.ops`, so a stub context registers the whole thing offline. That
matters because the bug this guards against is invisible at runtime — Qt
answers an ambiguous shortcut by firing NEITHER action, which is exactly how
F3 (the operator palette) went dead while still looking bound.
"""

import types

import pytest

from molom.core import input_map
from molom.core.ops import OperatorRegistry


def _registry():
    """The real operator table, built against a stub context."""
    pytest.importorskip("PySide6")
    from molom.ui.app import MainWindow
    ctx = types.SimpleNamespace(ops=OperatorRegistry())
    MainWindow._register_operators(ctx)
    return ctx.ops


# ------------------------------------------------------------- wheel mapping
def test_trackpad_scroll_orbits_mouse_wheel_zooms():
    # The laptop scheme: a plain two-finger scroll orbits.
    assert input_map.wheel_action(input_map.PRESET_TRACKPAD, True) \
        == input_map.ORBIT
    # The desktop scheme: a notched wheel zooms, like every other program.
    assert input_map.wheel_action(input_map.PRESET_MOUSE, False) \
        == input_map.ZOOM
    # An explicit preset overrides the device evidence in BOTH directions.
    assert input_map.wheel_action(input_map.PRESET_TRACKPAD, False) \
        == input_map.ORBIT
    assert input_map.wheel_action(input_map.PRESET_MOUSE, True) \
        == input_map.ZOOM


def test_auto_reads_pixel_delta_as_the_device_signal():
    # Precision trackpads report pixelDelta; notched wheels never do.
    assert input_map.wheel_action(input_map.PRESET_AUTO, True) \
        == input_map.ORBIT
    assert input_map.wheel_action(input_map.PRESET_AUTO, False) \
        == input_map.ZOOM
    assert input_map.is_mouse_wheel(input_map.PRESET_AUTO, False)
    assert not input_map.is_mouse_wheel(input_map.PRESET_AUTO, True)


def test_modifiers_mean_the_same_thing_on_both_devices():
    for preset in input_map.PRESETS:
        for pixels in (True, False):
            assert input_map.wheel_action(preset, pixels, ctrl=True) \
                == input_map.ZOOM
            assert input_map.wheel_action(preset, pixels, shift=True) \
                == input_map.PAN
            # Shift wins: pan is the more specific gesture.
            assert input_map.wheel_action(preset, pixels, ctrl=True,
                                          shift=True) == input_map.PAN


def test_normalize_preset_tolerates_junk_from_qsettings():
    assert input_map.normalize_preset(None) == input_map.PRESET_AUTO
    assert input_map.normalize_preset("") == input_map.PRESET_AUTO
    assert input_map.normalize_preset("nonsense") == input_map.PRESET_AUTO
    assert input_map.normalize_preset(" Mouse ") == input_map.PRESET_MOUSE
    assert input_map.normalize_preset("trackpad") == input_map.PRESET_TRACKPAD


# --------------------------------------------------------- operator key table
def test_duplicate_keys_are_detected():
    reg = OperatorRegistry()
    reg.register("a", "A", lambda c: None, key="F3")
    reg.register("b", "B", lambda c: None, key="F3")
    reg.register("c", "C", lambda c: None, key="F4")
    reg.register("d", "D", lambda c: None)          # unbound: never a clash
    assert reg.duplicate_keys() == {"F3": ["a", "b"]}
    assert [op.id for op in reg.keyed()] == ["a", "b", "c"]


def test_no_two_operators_claim_the_same_key():
    """The F3 regression: two menu entries, one key, nothing happens."""
    assert _registry().duplicate_keys() == {}


EXPECTED_KEYS = {
    "operator_search": "F3",        # the one that went missing
    "origin_edit": "Alt+O",
    "repeat_transform": "Shift+R",
    "move_to_origin": "Home",
    "drop_floor": "End",
    "add_atom": "Shift+A",
    "cycle_bond": "B",
    "remove_bond": "Shift+B",
    "toggle_background": "Ctrl+B",
    "reperceive": "Ctrl+P",
    "box_select": "Shift+Space, B",
    "lasso_select": "Shift+Space, L",
    "toggle_mode": "Tab",
    "move_grab": "G",
    "rotate": "R",
    "align_smart": "A",
    "duplicate": "D",
    "fit": "F",
    "cancel": "Esc",
    "undo": "Ctrl+Z",
    "redo": "Ctrl+Y",
}


@pytest.mark.parametrize("op_id,key", sorted(EXPECTED_KEYS.items()))
def test_expected_operator_keys_are_bound(op_id, key):
    """These are bindings users have in their fingers. Menus come and go —
    thinning the menus is what unbound half of this list — so the key lives
    on the operator and is pinned here."""
    op = _registry().get(op_id)
    assert op is not None, "operator vanished: " + op_id
    assert op.key == key


@pytest.mark.parametrize("letter", ["X", "Y", "Z"])
def test_axis_lock_letters_stay_out_of_the_key_table(letter):
    """A single-letter QAction silently outranks the viewport, and X/Y/Z are
    the anchored-tumble axis locks, which must reach it."""
    claimed = {op.key: op.id for op in _registry().keyed()}
    assert letter not in claimed


def test_the_draw_tool_owns_e():
    """E became an ordinary operator key in round 20: elements are picked
    from the periodic table, so edit mode no longer swallows letters and
    nothing competes for it."""
    assert _registry().get("toggle_draw").key == "E"


def test_every_keyed_operator_also_documents_itself():
    """The palette shows `shortcut` prose; a key with no prose is a key the
    user can only find by accident."""
    missing = [op.id for op in _registry().keyed() if not op.shortcut]
    assert missing == []


def test_keys_are_parseable_key_sequences():
    QKeySequence = pytest.importorskip("PySide6.QtGui").QKeySequence
    for op in _registry().keyed():
        seq = QKeySequence(op.key)
        assert not seq.isEmpty(), "unparseable key {!r} on {}".format(
            op.key, op.id)
