"""Round 92: the ORCA Workbench integration - roadmap F, and the reason MoloM
exists at all.

OWB launches an external 3D program as `[program, file.xyz]` and nothing more
(`orca_workbench/ui/molecules_tab.py::open_xyz_3d`), so `molom mol.xyz` was
already the whole of what its `viewer_3d_path` slot needs. What it could not
do was the two things that make the integration worth having:

* **the round-trip**: OWB opens the file in the EDITOR slot, tells the user to
  "adjust the geometry, then Save so it overwrites the .xyz", and re-reads
  that same file, setting `coords_locked` so a hand-edited geometry is not
  clobbered by SMILES regeneration. MoloM's Ctrl+S saved a `.molom` PROJECT,
  so the round-trip failed silently - OWB reloaded an unchanged file and
  reported success.
* **`--select`**: paste the 0-based indices out of a `%geom` constraint and
  see which atoms they are. `orca_workbench/core/geomspec.py` states the
  convention outright: "ORCA atom indices are 0-based."
"""
import os

import pytest

from molom.__main__ import parse_indices


@pytest.fixture
def opened(tmp_path):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from molom.ui.app import MainWindow

    path = tmp_path / "mol.xyz"
    path.write_text("3\nwater\n"
                    "O 0.000000 0.000000  0.117000\n"
                    "H 0.000000 0.757000 -0.469000\n"
                    "H 0.000000 -0.757000 -0.469000\n", encoding="utf-8")
    win = MainWindow()
    # AS ORCA WORKBENCH LAUNCHES IT. Round 102: opening a file is no longer a
    # round trip by itself - `molom some.xyz` imports it and Ctrl+S saves a
    # project - so the launcher has to ask for the write-back explicitly.
    win.open_path(str(path), roundtrip=True)
    return win, str(path)


# ------------------------------------------------------------ index parsing
def test_indices_accept_commas_or_spaces():
    """A `%geom` block is written with spaces and a shell argument is easier
    with commas; there is no reason to make the user care which."""
    assert parse_indices("3,7,11") == [3, 7, 11]
    assert parse_indices("3 7 11") == [3, 7, 11]
    assert parse_indices("3, 7 ,11") == [3, 7, 11]
    assert parse_indices("") == []


def test_a_bad_token_is_refused_not_dropped():
    """A constraint quietly missing an atom is worse than a refusal."""
    with pytest.raises(ValueError):
        parse_indices("3,seven,11")


# --------------------------------------------------------------- --select
def test_select_is_ZERO_based_like_ORCA(opened):
    """The whole point of the flag. Renumbering here would make it worse than
    useless."""
    win, _path = opened
    picked, missing = win.select_atom_indices([0])
    assert picked == [0] and not missing
    obj = win.scene.objects[-1]
    assert win.viewport.selection == [(obj.id, 0)]
    assert obj.structure.symbols[0] == "O"      # atom 0 IS the oxygen


def test_selecting_three_atoms_reports_the_ANGLE_they_define(opened):
    """Which is exactly what a three-atom `%geom` constraint means, so the
    readout answers the question the indices were pasted to ask."""
    win, _path = opened
    win.select_atom_indices([1, 0, 2])
    text = win._measure_label.text()
    assert "angle" in text and "104." in text


def test_an_out_of_range_index_is_reported(opened):
    """A constraint that names an atom this file does not have is exactly the
    mistake somebody would want to be told about."""
    win, _path = opened
    picked, missing = win.select_atom_indices([0, 99])
    assert picked == [0] and missing == [99]


# ------------------------------------------------------------ the round-trip
def test_opening_a_structure_file_records_it_as_the_document(opened):
    win, path = opened
    assert win.source_path == os.path.abspath(path)
    assert win.project_path is None


def test_ctrl_s_writes_the_geometry_back_over_that_file(opened):
    """OWB's instruction is "Save so it overwrites the .xyz". If Ctrl+S put up
    a project dialog instead, the round-trip would fail SILENTLY: OWB reloads
    an unchanged file and reports success."""
    import numpy as np
    from molom.core import io as io_mod
    win, path = opened
    obj = win.scene.objects[-1]
    obj.structure.coords = obj.structure.coords + np.array([0.0, 0.0, 0.25])
    win.on_save()
    atoms, _meta = io_mod.read_xyz(path)
    assert len(atoms) == 3
    assert atoms[0][3] == pytest.approx(0.367, abs=1e-3)


def test_a_second_import_does_not_steal_the_document(opened, tmp_path):
    """Imports ADD in MoloM (round 2). Re-pointing "Save" at whatever was
    opened most recently is how a round-trip writes the wrong file."""
    win, path = opened
    other = tmp_path / "other.xyz"
    other.write_text("1\nx\nHe 0 0 0\n", encoding="utf-8")
    win.open_path(str(other))
    assert win.source_path == os.path.abspath(path)


def test_a_project_takes_over_as_the_document(opened, tmp_path):
    """Once a `.molom` is saved, Ctrl+S means the project again - the xyz is
    no longer the thing being edited."""
    from molom.core import project
    win, _path = opened
    target = str(tmp_path / "scene" + project.EXTENSION) \
        if False else os.path.join(str(tmp_path), "scene" + project.EXTENSION)
    project.save_project(target, win.scene)
    win.project_path = target
    win.source_path = None
    win.on_save()                          # must not raise, must not prompt
    assert os.path.isfile(target)


def test_save_geometry_back_refuses_politely_with_no_source_file():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from molom.ui.app import MainWindow
    win = MainWindow()
    win.on_save_geometry_back()
    assert "not opened from a structure file" in win.statusBar().currentMessage()


def test_the_operator_is_disabled_without_a_source_file(opened):
    """`run_op` refuses a disabled operator, so the predicate is what decides
    whether F3 and the shortcut can reach it at all (round 60's lesson)."""
    win, _path = opened
    op = win.ops.get("save_geometry_back")
    assert op is not None
    assert op.enabled(win) is True
    win.source_path = None
    assert op.enabled(win) is False


# ------------------------------------------------------------ what OWB reads
def test_what_MoloM_writes_is_what_OWB_reads(opened):
    """The interop check that matters, run against ORCA Workbench's OWN reader
    where the sibling repo is on this machine. MoloM writes a plain comment
    line rather than its JSON metadata block, which is what keeps the file
    readable by every other program - round 76's rule."""
    import sys
    owb = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "ACH-Orca-Studio")
    if not os.path.isdir(owb):
        pytest.skip("ORCA Workbench is not checked out beside MoloM")
    win, path = opened
    win.scene.objects[-1].structure.metadata["comment"] = "edited in MoloM"
    win.on_save()
    sys.path.insert(0, owb)
    try:
        from orca_workbench.core import coords as owb_coords
    except Exception:                                   # noqa: BLE001
        pytest.skip("ORCA Workbench is not importable here")
    finally:
        sys.path.remove(owb)
    atoms, _meta = owb_coords.read_xyz(path)
    assert [a[0] for a in atoms] == ["O", "H", "H"]


def test_the_launcher_path_is_findable():
    """`--where` exists because "point OWB at molom" is only easy once you
    know where the console script landed - and a per-user pip install puts it
    nowhere near `sys.executable`."""
    from molom.__main__ import launcher_path
    found = launcher_path()
    assert found == "" or os.path.isfile(found)
