"""Round 64: the Blender export's geometry and glow options, and the mode rows.

Christian, 2026-08-12:
* "I am not entirely sure that subdivision subsurface is applied to the blender
  export. In blender atoms do not show a modifier and look a little blocky?"
* "the bloom for meta atoms is not passed on to blender? ... Make it a checkbox
  in the export that is off by default for now."
* "the percentage makes the button disappear off to the right. Can you make the
  entire row the button to animate? ... I do not like the frames on top of
  frames look."
"""

import os

import numpy as np
import pytest

from molom.core import blender_export as bx
from molom.core import meta as meta_mod
from molom.core import style as style_mod
from molom.core.scene import Scene
from molom.core.structure import Structure

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def win():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.app import MainWindow
    QApplication.instance() or QApplication([])
    return MainWindow()


def _meta_scene():
    s = Structure(["Xx", "O", "O"],
                  np.array([[0., 0., 0.], [2., 0., 0.], [-1., 1.7, 0.]]))
    s.bonds = [(0, 1, 1), (0, 2, 1)]
    meta_mod.set_meta(s, 0, meta_mod.MetaAtom(
        geometry="bent", distance=2.0, element="Fe", locked=True))
    scene = Scene()
    scene.add(s, name="meta")
    return scene


def _collect(options):
    return bx.collect(_meta_scene(), style_mod.BALL_AND_STICK, options,
                      cell_of=lambda _o: None)


# ------------------------------------------------------ subdivision surface
def test_atoms_get_a_real_subdivision_modifier_by_default():
    """Smooth shading fixes the inside of a sphere, not its silhouette - and a
    modifier is what a Blender user expects to find and raise."""
    options = bx.ExportOptions()
    assert options.subsurf is True
    script = bx.build_script(_collect(options), options)
    assert "add_subsurf(ob)" in script
    assert '"SUBSURF"' in script


def test_the_subdivision_levels_reach_the_script():
    options = bx.ExportOptions()
    options.subsurf_viewport, options.subsurf_render = 2, 4
    script = bx.build_script(_collect(options), options)
    assert '"subsurf_viewport": 2' in script
    assert '"subsurf_render": 4' in script


def test_subdivision_can_be_switched_off():
    options = bx.ExportOptions()
    options.subsurf = False
    script = bx.build_script(_collect(options), options)
    assert '"subsurf": false' in script.lower()


# ------------------------------------------------------------- the meta glow
def test_the_meta_glow_is_OFF_by_default():
    """A glowing atom is a deliberate look, not a fact about the structure."""
    options = bx.ExportOptions()
    assert options.meta_glow is False
    mats = _collect(options)["materials"]
    assert all(m["emission"] == 0.0 for m in mats)


def test_switching_the_glow_on_emits_only_the_meta_centre():
    options = bx.ExportOptions()
    options.meta_glow = True
    mats = {m["name"]: m["emission"] for m in _collect(options)["materials"]}
    glowing = [n for n, e in mats.items() if e > 0]
    assert len(glowing) == 1
    assert glowing[0].startswith(bx.META_MATERIAL_PREFIX)
    # the ordinary oxygens must not light up with it
    assert all(e == 0.0 for n, e in mats.items() if "meta" not in n)


def test_a_meta_atom_exports_in_its_RESOLVED_element_colour():
    """The viewport draws it as Fe (round 62), so the export must too - an
    export that disagrees with the screen is the round-37 rule broken."""
    names = [m["name"] for m in _collect(bx.ExportOptions())["materials"]]
    assert any("Fe" in n for n in names)
    assert not any("Xx" in n for n in names)


def test_the_generated_script_stays_pure_ascii():
    """Round 37: one cp1252 write turns a dash into a byte Blender refuses."""
    options = bx.ExportOptions()
    options.meta_glow = True
    script = bx.build_script(_collect(options), options, title="probe")
    assert all(ord(c) < 128 for c in script)


def test_the_dialog_exposes_both_new_options(win):
    from molom.ui.dialogs import BlenderExportDialog
    dlg = BlenderExportDialog(win, bx.ExportOptions())
    assert hasattr(dlg, "subsurf") and hasattr(dlg, "meta_glow")
    assert dlg.meta_glow.isChecked() is False
    assert dlg.subsurf.isChecked() is True


# ------------------------------------------------------------- the mode rows
def test_a_mode_row_is_itself_the_button(win):
    """No nested frames and no separate "A" button - the share percentage was
    pushing it off the right edge of a narrow dock."""
    from molom.ui.properties import _ModeRow
    row = _ModeRow(7)
    got = []
    row.clicked.connect(got.append)
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    row.resize(200, 24)
    row.mouseReleaseEvent(QMouseEvent(
        QEvent.MouseButtonRelease, QPointF(100.0, 12.0), Qt.LeftButton,
        Qt.NoButton, Qt.NoModifier))
    assert got == [7]


def test_releasing_outside_the_row_does_not_fire(win):
    """The same contract every other button has: drag away and it cancels."""
    from molom.ui.properties import _ModeRow
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    row = _ModeRow(3)
    got = []
    row.clicked.connect(got.append)
    row.resize(200, 24)
    row.mouseReleaseEvent(QMouseEvent(
        QEvent.MouseButtonRelease, QPointF(400.0, 12.0), Qt.LeftButton,
        Qt.NoButton, Qt.NoModifier))
    assert got == []


def test_the_mode_list_builds_clickable_rows(win):
    freq = os.path.join(ROOT, "tests", "data", "orca_freq_h3po4.out")
    win.open_path(freq)
    page = win.vibration_page
    from molom.ui.properties import _ModeRow
    rows = [page.column.itemAt(i).widget() for i in range(page.column.count())]
    rows = [r for r in rows if isinstance(r, _ModeRow)]
    assert rows, "no mode rows built"


# ----------------------------------------------- the association script again
def test_the_association_script_is_pure_ascii():
    """It broke on Christian's machine: PowerShell 5.1 reads a BOM-less file as
    cp1252, so a UTF-8 em-dash arrives as three bytes and the string never
    terminates. Round 37's rule, in a new language."""
    path = os.path.join(ROOT, "tools", "associate_molom_files.ps1")
    data = open(path, "rb").read()
    assert data, "script is empty"
    assert max(data) < 128, "non-ASCII byte in a PowerShell script"
