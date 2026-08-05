"""Round 29: symmetry modifier, ORCA geometry, align robustness, suggestions."""

import os

import numpy as np
import pytest

from molom.core import modifiers as mod_mod
from molom.core import vibrations

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_FREQ = os.path.join(os.path.dirname(__file__), "data",
                     "orca_freq_h3po4.out")


# ------------------------------------------------------- symmetry modifier
def _nacl_meta():
    from tests.test_round18_cif import NACL_CIF
    from molom.core import cif
    data = cif.parse_cif(NACL_CIF)
    return data.cell.to_dict(), [op.as_xyz() for op in data.symops], data


def test_symmetry_modifier_expands_without_touching_the_base():
    """The point of a modifier: the base stays the asymmetric unit you edit
    while the viewport sees the full cell."""
    cell, ops, data = _nacl_meta()
    mod = mod_mod.SymmetryModifier(cell=cell, symops=ops)
    coords = data.frac @ data.cell.matrix()
    sym, xyz, bonds = mod.evaluate(list(data.symbols), coords, [])
    assert len(data.symbols) == 2          # untouched input
    assert len(sym) == 27                  # 2 sites x 4 ops, boundary completed
    assert xyz.shape == (27, 3)


def test_symmetry_modifier_can_pack():
    cell, ops, data = _nacl_meta()
    mod = mod_mod.SymmetryModifier(cell=cell, symops=ops, na=2, nb=2, nc=1)
    coords = data.frac @ data.cell.matrix()
    sym, _xyz, _b = mod.evaluate(list(data.symbols), coords, [])
    assert len(sym) == 27 * 4


def test_symmetry_modifier_without_a_cell_is_a_no_op():
    """It must degrade, not raise: a molecule can carry the modifier through
    a copy that has lost its crystallography."""
    mod = mod_mod.SymmetryModifier()
    sym, xyz, bonds = mod.evaluate(["C"], np.zeros((1, 3)), [])
    assert sym == ["C"] and xyz.shape == (1, 3)


def test_symmetry_modifier_round_trips_through_a_dict():
    cell, ops, _d = _nacl_meta()
    mod = mod_mod.SymmetryModifier(cell=cell, symops=ops, na=3)
    again = mod_mod.from_dict(mod.to_dict())
    assert isinstance(again, mod_mod.SymmetryModifier)
    assert again.na == 3
    assert len(again.symops) == len(ops)


def test_the_registry_knows_both_kinds():
    assert set(mod_mod._KINDS) == {"array", "symmetry", "boundary"}


# --------------------------------------------------------- ORCA geometry
@pytest.mark.skipif(not os.path.exists(_FREQ), reason="fixture missing")
def test_the_freq_output_carries_its_own_geometry():
    """So importing modes never depends on the right molecule already being
    open with the atoms in the same order."""
    with open(_FREQ, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    atoms = vibrations.parse_orca_geometry(text)
    modes = vibrations.parse_orca_frequencies(text)
    assert len(atoms) == modes[0].displacements.shape[0]
    assert [a[0] for a in atoms].count("O") == 4
    assert [a[0] for a in atoms].count("H") == 3
    assert [a[0] for a in atoms].count("P") == 1


def test_a_file_without_a_geometry_block_returns_empty():
    assert vibrations.parse_orca_geometry("no coordinates here") == []


# -------------------------------------------------------------- align wait
@pytest.fixture
def win():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.app import MainWindow
    QApplication.instance() or QApplication([])
    w = MainWindow()
    w.load_default_scene()
    w.show()
    return w


def test_a_stray_key_no_longer_cancels_an_align(win):
    """One stray keypress used to abandon the operation silently."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    vp = win.viewport
    vp.arm_align_keys("plane")
    assert vp._align_wait == "plane"
    for key in (Qt.Key_Q, Qt.Key_M, Qt.Key_7, Qt.Key_Space):
        QTest.keyClick(vp, key, Qt.NoModifier)
        QApplication.processEvents()
        assert vp._align_wait == "plane", "key {} cancelled it".format(key)


def test_escape_still_cancels_an_align(win):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    vp = win.viewport
    vp.arm_align_keys("axis")
    QTest.keyClick(vp, Qt.Key_Escape, Qt.NoModifier)
    QApplication.processEvents()
    assert vp._align_wait is None


def test_an_axis_key_previews_the_align_and_keeps_waiting(win):
    """Round 31 turned this into a preview modal: the axis key APPLIES the
    alignment but the operation stays live until you confirm, so you can try
    X, look at it, and press Y instead."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    vp = win.viewport
    got = []
    vp.on_align_key = lambda kind, axis: got.append((kind, axis))
    vp.arm_align_keys("axis")
    QTest.keyClick(vp, Qt.Key_Y, Qt.NoModifier)
    QApplication.processEvents()
    assert got == [("axis", 1)]
    assert vp._align_wait == "axis"          # still armed
    assert vp._align_previewed == 1
    QTest.keyClick(vp, Qt.Key_X, Qt.NoModifier)
    QApplication.processEvents()
    assert got == [("axis", 1), ("axis", 0)]
    assert vp._align_previewed == 0


def test_right_click_cancels_an_align(win):
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    vp = win.viewport
    vp.arm_align_keys("axis")
    pos = QPointF(50.0, 50.0)
    vp.mousePressEvent(QMouseEvent(
        QMouseEvent.MouseButtonPress, pos, vp.mapToGlobal(pos.toPoint()),
        Qt.RightButton, Qt.RightButton, Qt.NoModifier))
    assert vp._align_wait is None


def test_the_align_prompt_is_painted_not_just_announced(win):
    """It lived in the status bar, where a 4 s timeout wiped it out."""
    vp = win.viewport
    vp.arm_align_keys("plane")
    assert vp._align_wait == "plane"
    assert hasattr(vp, "_paint_modal_prompt")


# ---------------------------------------------------- clickable suggestions
def test_did_you_mean_suggestions_are_clickable(win):
    from molom.core.resolve import Resolution
    from molom.ui.dialogs import ResolveNameDialog
    dlg = ResolveNameDialog(win)
    assert not dlg.suggestions.isVisible()
    dlg._resolved(Resolution(query="asprin", error="no match",
                             candidates=["aspirin", "asparagine"]))
    assert dlg.suggestions.count() == 2
    dlg.edit.setText("")
    dlg._take_suggestion(dlg.suggestions.item(0))
    assert dlg.edit.text() == "aspirin", "clicking must fill the query"


def test_a_successful_resolve_shows_no_suggestion_list(win):
    from molom.core.resolve import Resolution
    from molom.ui.dialogs import ResolveNameDialog
    dlg = ResolveNameDialog(win)
    res = Resolution(query="water")
    res.smiles = "O"
    dlg._resolved(res)
    assert not dlg.suggestions.isVisible()
