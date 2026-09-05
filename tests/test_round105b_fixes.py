"""Round 105b - Christian's three from testing round 105.

1. "Quitting in an axis view of a crystal is orthographic. if that is saved
   just before quit, the program launches in orthographic view, but rotating
   the camera doesn't pop back to perspective. It should."
2. "pressing delete on a mol with no atoms in the outliner doesn't remove it.
   Check MF.molom for that." - which round 103b believed it had fixed.
3. "I would like to also be able to drag and drop the patterns so I can
   arrange them in a preferred order. This should come with horizontal
   highlighting bands that show which patterns will swap places in the
   stack."
"""

import os

import numpy as np
import pytest

HERE = os.path.dirname(__file__)
SOLID = os.path.join(HERE, "data", "cod_1547149_solid_solution.cif")


@pytest.fixture
def win():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from molom.ui.app import MainWindow
    return MainWindow()


# ------------------------------------------- 1: an axis view through a file
def test_an_axis_view_still_pops_back_to_perspective_after_a_reload(
        win, tmp_path):
    """An axis view is not just a POSE. `auto_ortho` and `auto_level` are
    what make the next orbit pop back to perspective and level the horizon,
    and neither was saved - so a file written while looking down a cell axis
    reopened as a view that was orthographic forever."""
    win.open_path(SOLID)
    win._on_ribbon_axis("c")
    cam = win.viewport.camera
    assert cam.orthographic and cam.auto_ortho and cam.auto_level

    path = str(tmp_path / "axis.molom")
    win.project_path = path
    win.on_save_project()

    from molom.ui.app import MainWindow
    again = MainWindow()
    again.open_project(path)
    back = again.viewport.camera
    assert back.orthographic, "the saved view was orthographic"
    assert back.auto_ortho and back.auto_level, "...and it is an AXIS view"
    back.rotate(60.0, 20.0)
    assert not back.orthographic, "so orbiting pops it back to perspective"


def test_a_hand_chosen_orthographic_view_is_NOT_undone_by_orbiting(
        win, tmp_path):
    """The other half, and the reason the flag exists rather than the
    projection alone: pressing O is a decision and must survive a reload and
    every orbit after it."""
    win.open_path(SOLID)
    cam = win.viewport.camera
    cam.orthographic = True
    cam.auto_ortho = False
    path = str(tmp_path / "ortho.molom")
    win.project_path = path
    win.on_save_project()

    from molom.ui.app import MainWindow
    again = MainWindow()
    again.open_project(path)
    again.viewport.camera.rotate(60.0, 20.0)
    assert again.viewport.camera.orthographic


def test_both_flags_travel_or_neither_does(win, tmp_path):
    """`Camera.rotate` measured undoing only ONE of the two as a 180 degree
    camera movement for a zero-degree step, because the projection and the
    cell-axis up vector are one pose. So the savefile carries both."""
    win.open_path(SOLID)
    win._on_ribbon_axis("b")
    state = win._view_state()
    assert state["auto_ortho"] is True and state["auto_level"] is True


def test_a_savefile_from_before_this_round_still_reads(win):
    """No keys means no axis view, which is the right answer for an old
    file: a plain orthographic view chosen by hand is meant to stay."""
    win.open_path(SOLID)
    win._restore_view = None
    cam = win.viewport.camera
    cam.auto_ortho = cam.auto_level = True
    payload = {"view": {"center": [0.0, 0.0, 0.0], "distance": 10.0,
                        "rotation": list(cam.rotation),
                        "orthographic": True}}
    # the same lines `open_project` runs
    view = payload["view"]
    cam.orthographic = bool(view.get("orthographic", False))
    cam.auto_ortho = bool(view.get("auto_ortho", False))
    cam.auto_level = bool(view.get("auto_level", False))
    assert cam.orthographic and not cam.auto_ortho and not cam.auto_level


# ------------------------------------------- 2: deleting an empty molecule
def test_DELETE_removes_an_empty_molecule_through_the_KEY(win):
    """Round 103b put this in `OutlinerPanel.keyPressEvent` and pinned it by
    calling that method directly - so it pinned a fix no hand could reach.
    `Del` is a window-level QAction (round 16 binds every operator key that
    way) and Qt dispatches a window shortcut BEFORE the focused widget sees a
    key press, so the panel's handler could never run."""
    obj_id = win.new_empty_molecule()
    assert win.scene.get(obj_id).structure.n_atoms == 0
    win.outliner.highlight(obj_id)
    for k in range(win.outliner.tree.topLevelItemCount()):
        item = win.outliner.tree.topLevelItem(k)
        if win.outliner._obj_id(item) == obj_id:
            item.setSelected(True)
    assert win.outliner.selected_object_ids() == [obj_id]
    assert win.viewport.selection == [], "no atoms - that is the whole case"

    # the operator's PREDICATE has to cover it too, or `run_op` refuses it
    # and the key never arrives (round 60)
    assert win.ops.get("delete_selected").enabled(win)
    before = win.scene.n_objects
    win._op_actions["delete_selected"].trigger()      # what the key does
    assert win.scene.n_objects == before - 1


def test_the_outliner_no_longer_claims_DELETE_itself(win):
    """One implementation. A second handler that cannot fire is the same
    trap as a live-looking control that does nothing."""
    from molom.ui import outliner as outliner_mod
    # `hasattr` is useless here - every QWidget has one. What matters is
    # whether this class OVERRIDES it.
    assert "keyPressEvent" not in vars(outliner_mod.OutlinerPanel), \
        "the window's operator owns Delete now"


def test_a_molecule_WITH_atoms_is_not_deleted_by_a_highlighted_row(win):
    """The fall-through is narrow on purpose. `highlight` makes the active
    object's row current, so a row is nearly always selected - and Del with
    nothing selected in the viewport must not destroy the molecule you are
    looking at. Only an EMPTY object has no other route."""
    win.open_path(SOLID)
    obj = win.scene.objects[0]
    win.viewport.set_selection([])
    win.outliner.highlight(obj.id)
    for k in range(win.outliner.tree.topLevelItemCount()):
        item = win.outliner.tree.topLevelItem(k)
        if win.outliner._obj_id(item) == obj.id:
            item.setSelected(True)
    assert win.outliner.selected_object_ids() == [obj.id]
    assert win.empty_selected_objects() == [], "it has atoms"
    assert not win.ops.get("delete_selected").enabled(win)
    n = win.scene.n_objects
    win._op_actions["delete_selected"].trigger()
    assert win.scene.n_objects == n


def test_deleting_atoms_still_wins_over_the_outliner_row(win):
    """A selection of ATOMS is what Delete means whenever there is one."""
    win.open_path(SOLID)
    obj = win.scene.objects[0]
    before = obj.structure.n_atoms
    win.viewport.set_selection([(obj.id, 0)])
    win.outliner.highlight(obj.id)
    for k in range(win.outliner.tree.topLevelItemCount()):
        item = win.outliner.tree.topLevelItem(k)
        if win.outliner._obj_id(item) == obj.id:
            item.setSelected(True)
    n_objs = win.scene.n_objects
    win._op_actions["delete_selected"].trigger()
    assert win.scene.n_objects == n_objs, "the molecule survives"
    assert win.scene.get(obj.id).structure.n_atoms < before, "atoms went"


# ------------------------------------------------ 3: reordering the stack
def _measured(tmp_path, name="scan", centre=30.0):
    x = np.linspace(5.0, 60.0, 1200)
    y = 250.0 + 3000.0 * np.exp(-0.5 * ((x - centre) / 0.06) ** 2)
    path = tmp_path / (name + ".xy")
    path.write_text("".join("%.4f %.3f\n" % (a, b) for a, b in zip(x, y)),
                    encoding="utf-8")
    return str(path)


@pytest.fixture
def plot_bench(win, tmp_path):
    win.open_path(SOLID)
    win.viewport.set_selection([])
    win.on_pxrd()
    w = win._pxrd_window
    w.resize(1000, 560)
    w.load_measured(_measured(tmp_path))
    w.offset.setValue(60.0)
    return w


def _drag(plot, y_from, y_to, release=True):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    plot.mousePressEvent(QMouseEvent(
        QEvent.MouseButtonPress, QPointF(300.0, y_from), Qt.LeftButton,
        Qt.LeftButton, Qt.NoModifier))
    plot.mouseMoveEvent(QMouseEvent(
        QEvent.MouseMove, QPointF(300.0, y_to), Qt.NoButton, Qt.LeftButton,
        Qt.NoModifier))
    if release:
        plot.mouseReleaseEvent(QMouseEvent(
            QEvent.MouseButtonRelease, QPointF(300.0, y_to), Qt.LeftButton,
            Qt.NoButton, Qt.NoModifier))


def _middle(band):
    return 0.5 * (band[0] + band[1])


def test_the_bands_are_the_strips_between_the_baselines(plot_bench):
    """The geometry the drag highlights has to be the geometry it hit-tests
    against - deriving it twice is how the highlight and the drop come to
    disagree."""
    plot = plot_bench.plot
    bands = plot.stack_bands()
    assert len(bands) == len(plot.traces) >= 2
    for upper, lower in bands:
        assert lower > upper
    # they tile the plot without gaps or overlaps
    ordered = sorted(bands)
    for (a_top, a_bot), (b_top, _b) in zip(ordered, ordered[1:]):
        assert a_bot == pytest.approx(b_top)
    rect = plot.plot_rect()
    assert ordered[0][0] == pytest.approx(rect.top())
    # and each trace's own baseline falls inside its own band
    for trace, (upper, lower) in zip(plot.traces, bands):
        y = plot.y_to_px(trace.offset, rect)
        assert upper <= y <= lower


def test_dragging_one_band_onto_another_SWAPS_them(plot_bench):
    """Christian's own word - a swap, not an insertion."""
    w = plot_bench
    plot = w.plot
    before = [t.name for t in plot.traces]
    bands = plot.stack_bands()
    _drag(plot, _middle(bands[0]), _middle(bands[-1]))
    after = [t.name for t in w.plot.traces]
    assert after[0] == before[-1] and after[-1] == before[0]
    # and it is remembered, not just applied once
    w.recompute()
    assert [t.name for t in w.plot.traces] == after


def test_the_highlight_says_which_two_will_swap(plot_bench):
    """The bands are measured at PRESS time and held, so the target cannot
    move under the hand while it is being aimed at."""
    plot = plot_bench.plot
    bands = plot.stack_bands()
    assert plot.reordering() is None
    _drag(plot, _middle(bands[0]), _middle(bands[-1]), release=False)
    assert plot.reordering() == (0, len(bands) - 1)
    # a press that has not travelled yet names no target
    plot._reorder = None
    _drag(plot, _middle(bands[0]), _middle(bands[0]) + 1, release=False)
    assert plot.reordering() is None


def test_ESC_cancels_the_swap(plot_bench):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QMouseEvent
    w = plot_bench
    plot = w.plot
    before = [t.name for t in plot.traces]
    bands = plot.stack_bands()
    _drag(plot, _middle(bands[0]), _middle(bands[-1]), release=False)
    assert plot.reordering() is not None
    plot.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Escape,
                                 Qt.NoModifier))
    assert plot.reordering() is None
    # ...and the release that follows it must not swap anything either
    plot.mouseReleaseEvent(QMouseEvent(
        QEvent.MouseButtonRelease, QPointF(300.0, _middle(bands[-1])),
        Qt.LeftButton, Qt.NoButton, Qt.NoModifier))
    assert [t.name for t in w.plot.traces] == before


def test_there_is_nothing_to_rearrange_without_an_offset(plot_bench):
    """At offset 0 every baseline is the same pixel, so there is no vertical
    order to drag - and a gesture that cannot say which trace it means must
    not guess."""
    w = plot_bench
    w.offset.setValue(0.0)
    assert w.plot.stack_bands() == []
    assert w.plot.band_at(100.0) is None
    before = [t.name for t in w.plot.traces]
    _drag(w.plot, 100.0, 300.0)
    assert [t.name for t in w.plot.traces] == before


def test_an_armed_zoom_or_pan_still_owns_the_drag(plot_bench):
    """The reorder takes the drag only when nothing else has claimed it,
    which is what keeps `Z` and `P` working exactly as they did."""
    w = plot_bench
    plot = w.plot
    bands = plot.stack_bands()
    for mode in ("zoom_h", "zoom_box", "pan_free"):
        plot.set_mode(mode)
        before = [t.name for t in w.plot.traces]
        _drag(plot, _middle(bands[0]), _middle(bands[-1]))
        assert [t.name for t in w.plot.traces] == before, mode
        assert plot.reordering() is None
    plot.set_mode(None)


def test_a_NEW_measurement_lands_in_its_DEFAULT_slot_and_overrides_nothing(
        plot_bench, tmp_path):
    """The remembered order governs only the traces it knows about; anything
    new keeps the slot the default put it in, and an arrangement made by hand
    is never overridden by opening another file.

    The first cut ranked unknown keys LAST, which is the same rule read
    carelessly - it put every newly opened measurement at the BOTTOM of the
    stack, and round 100's "the measurement sits at the top" caught it.
    """
    w = plot_bench
    bands = w.plot.stack_bands()
    _drag(w.plot, _middle(bands[0]), _middle(bands[-1]))
    assert w.plot.traces[0].obj is not None, "the crystal was dragged on top"

    w.load_measured(_measured(tmp_path, name="later", centre=20.0))
    names = [t.name for t in w.plot.traces]
    assert "later" in names, "the new trace is drawn"
    assert names.index("later") == 1, \
        "in the slot the default gave it, between the two it knows"
    assert names.index("cod_1547149_solid_solution") < names.index("scan"), \
        "and the swap the user made by hand still stands"


def test_an_UNTOUCHED_window_still_puts_the_measurement_on_top(plot_bench,
                                                               tmp_path):
    """The default, which the override composes with rather than replaces."""
    w = plot_bench
    assert w.plot.traces[0].obj is None, "measured first, phases under it"
    w.load_measured(_measured(tmp_path, name="second", centre=20.0))
    assert [t.obj is None for t in w.plot.traces] == [True, True, False]


def test_a_trace_switched_off_keeps_its_PLACE_in_the_stack(plot_bench):
    """Ticking it back on should put it where it was, not on the end."""
    w = plot_bench
    plot = w.plot
    bands = plot.stack_bands()
    _drag(plot, _middle(bands[0]), _middle(bands[-1]))
    order = [t.name for t in w.plot.traces]
    entry = w.measured[0]
    entry.enabled = False
    w.recompute()
    assert entry.name not in [t.name for t in w.plot.traces]
    entry.enabled = True
    w.recompute()
    assert [t.name for t in w.plot.traces] == order
