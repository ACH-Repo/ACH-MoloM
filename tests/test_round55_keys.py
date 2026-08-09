"""Round 55: the vibration transform reset, chord keys, X, and F12.

Christian's batch:

* "selecting a different normal mode should not reset the transform location
  of the molecule back to the origin. Neither should changing any of the
  parameters in the frequency tab. Amplitude does it too."
* "since X is doing nothing right now: bind delete to it for now."
* "lasso hotkey does not work. Is it a lower/upper case issue with the combo?"
* F12 / Ctrl+F12 as Blender's render keys, with filename incrementing.
"""

import os

import numpy as np
import pytest

from molom.core import animation as anim
from molom.core import ops as ops_mod

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
FREQ = os.path.join(DATA, "orca_freq_h3po4.out")


@pytest.fixture
def win():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.app import MainWindow
    QApplication.instance() or QApplication([])
    return MainWindow()


# ------------------------------------------------- the mode transform reset
def test_re_baking_a_mode_leaves_the_molecule_where_it_is(win):
    """A mode is baked as `rest + eigenvector * sin(phase)`, and the rest was
    captured once when the frequencies were read — so every re-bake teleported
    the molecule back to where it was imported."""
    win.open_path(FREQ)
    obj = win._active_obj()
    modes = [m for m in win._modes.get(obj.id, []) if not m.is_trivial]
    assert len(modes) > 1
    win.on_animate_mode(modes[0].index)

    obj = win.scene.get(obj.id)
    shift = np.array([5.0, -2.0, 1.0])
    for k in range(obj.structure.n_frames):     # a grab moves EVERY frame
        obj.structure.frames[k] = np.asarray(obj.structure.frames[k]) + shift
    moved = np.asarray(obj.structure.frames[0]).mean(axis=0)

    win.on_animate_mode(modes[1].index)         # another mode
    assert np.allclose(np.asarray(win.scene.get(obj.id).structure.frames[0]
                                  ).mean(axis=0), moved, atol=1e-9)
    win.on_animate_mode(modes[1].index, amplitude=0.5)     # amplitude
    assert np.allclose(np.asarray(win.scene.get(obj.id).structure.frames[0]
                                  ).mean(axis=0), moved, atol=1e-9)
    win.on_animate_mode(modes[1].index, n_frames=16)       # frames/period
    assert np.allclose(np.asarray(win.scene.get(obj.id).structure.frames[0]
                                  ).mean(axis=0), moved, atol=1e-9)


def test_the_mode_itself_still_moves_the_atoms(win):
    """The fix must not turn the animation off — frame 0 is undisplaced, the
    quarter-period frame is not."""
    win.open_path(FREQ)
    obj = win._active_obj()
    modes = [m for m in win._modes.get(obj.id, []) if not m.is_trivial]
    win.on_animate_mode(modes[0].index, amplitude=0.4)
    frames = win.scene.get(obj.id).structure.frames
    assert len(frames) > 3
    spread = max(float(np.abs(np.asarray(f) - np.asarray(frames[0])).max())
                 for f in frames)
    assert spread > 0.1


def test_the_rest_geometry_survives_an_atom_count_it_cannot_match(win):
    """A structure edited since the frequencies were read has no valid rest
    geometry; falling back to the current coordinates beats an exception."""
    win.open_path(FREQ)
    obj = win._active_obj()
    rest = win._rest_for(obj)
    assert np.shape(rest)[0] == obj.structure.n_atoms


# ------------------------------------------------------------- chord keys
def test_a_shifted_chord_is_bound_both_ways():
    """`Shift+Space, L` only matches if Shift is RELEASED before the second
    key. Hold it through, as anyone does, and Qt looks for `Shift+L` and fires
    nothing — which is why the lasso hotkey "does not work" while the box one
    seemed to."""
    assert ops_mod.chord_variants("Shift+Space, L") == [
        "Shift+Space, L", "Shift+Space, Shift+L"]
    assert ops_mod.chord_variants("Shift+Space, B") == [
        "Shift+Space, B", "Shift+Space, Shift+B"]


def test_a_plain_key_is_left_alone():
    assert ops_mod.chord_variants("G") == ["G"]
    assert ops_mod.chord_variants("Ctrl+Shift+A") == ["Ctrl+Shift+A"]
    assert ops_mod.chord_variants("") == []


def test_a_chord_without_shift_needs_no_variant():
    assert ops_mod.chord_variants("Ctrl+K, S") == ["Ctrl+K, S"]


def test_both_spellings_reach_the_action(win):
    from PySide6.QtGui import QKeySequence
    bound = {s.toString() for s in win._op_actions["lasso_select"].shortcuts()}
    assert bound == {"Shift+Space, L", "Shift+Space, Shift+L"}
    assert QKeySequence("Shift+Space, Shift+L") in \
        win._op_actions["lasso_select"].shortcuts()


# ------------------------------------------------------------------- X
def test_x_deletes_as_well_as_del(win):
    """Blender deletes with X, and X was doing nothing here."""
    bound = {s.toString()
             for s in win._op_actions["delete_selected"].shortcuts()}
    assert bound == {"Del", "X"}
    assert not win.ops.duplicate_keys()


def test_extra_keys_are_counted_as_claims():
    """An extra binding is a claim like any other, or two operators could
    quietly share one and Qt would fire NEITHER."""
    reg = ops_mod.OperatorRegistry()
    reg.register("a", "A", lambda c: None, key="Del", extra_keys=("X",))
    reg.register("b", "B", lambda c: None, key="X")
    assert "X" in reg.duplicate_keys()


# ------------------------------------------------------------- F12 keys
def test_the_filename_increments_rather_than_overwriting(tmp_path):
    """What makes a render key safe to lean on: a key that silently replaces
    the last render is a key you cannot press twice."""
    first = str(tmp_path / "shot.png")
    assert anim.next_free(first) == first          # nothing there yet
    open(first, "w").close()
    second = anim.next_free(first)
    assert second.endswith("shot_001.png")
    open(second, "w").close()
    assert anim.next_free(first).endswith("shot_002.png")


def test_incrementing_can_be_turned_off(tmp_path):
    path = str(tmp_path / "shot.png")
    open(path, "w").close()
    assert anim.next_free(path, enabled=False) == path


def test_the_increment_is_always_measured_from_the_BASE_name(tmp_path):
    """Remembering the incremented name instead compounds the suffix — three
    presses gave shot.png, shot_001.png, shot_001_001.png."""
    base = str(tmp_path / "shot.png")
    written = []
    for _ in range(4):
        nxt = anim.next_free(base)
        open(nxt, "w").close()
        written.append(os.path.basename(nxt))
    assert written == ["shot.png", "shot_001.png", "shot_002.png",
                       "shot_003.png"]


def test_the_render_keys_are_registered(win):
    for op_id, key in (("render_still", "F12"),
                       ("render_animation", "Ctrl+F12")):
        op = win.ops.get(op_id)
        assert op is not None and op.key == key
        assert "render" in op.aliases
    assert not win.ops.duplicate_keys()


def test_the_first_press_opens_the_dialog_route(win):
    """Nothing is remembered yet, so F12 must fall through to the ordinary
    export rather than rendering to a path nobody chose."""
    assert win._render_target == {}
    called = []
    win.on_export_image = lambda: called.append("image")
    win.on_export_animation = lambda: called.append("animation")
    win.on_render_key(False)
    win.on_render_key(True)
    assert called == ["image", "animation"]


def test_the_deliberate_export_still_opens_every_time(win):
    """F12 is the shortcut; Ctrl+Shift+E is the route that always asks. Taking
    that away would leave no way to change the file."""
    assert win.ops.get("export_image").key == "Ctrl+Shift+E"
    assert win.ops.get("export_animation").key == "Ctrl+Shift+A"
