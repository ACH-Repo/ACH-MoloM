"""Round 49: occupancy in the readout and as a label type."""
import os

import numpy as np
import pytest

from molom.core import cif
from molom.core.scene import Scene
from molom.core.structure import Structure

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

SHARED = """data_shared
_cell_length_a 8.0
_cell_length_b 8.0
_cell_length_c 8.0
_cell_angle_alpha 90.0
_cell_angle_beta 90.0
_cell_angle_gamma 90.0
loop_
_symmetry_equiv_pos_as_xyz
'x,y,z'
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
Fe1 Fe 0.25 0.25 0.25 0.60
Ni1 Ni 0.25 0.25 0.25 0.40
O1  O  0.75 0.75 0.75 0.50
C1  C  0.10 0.10 0.10 1.00
"""


def _object_from(text):
    from molom.core import packing
    data = cif.parse_cif(text)
    symbols, coords, bonds, meta = packing.pack(data)
    s = Structure(list(symbols), coords)
    s.metadata.update(meta)          # carries site_of, remapped by pack()
    s.metadata["cell"] = data.cell.to_dict()
    s.metadata["asym_occupancy"] = [float(o) for o in data.occupancy]
    scene = Scene()
    return scene, scene.add(s)


def test_a_shared_site_reads_out_its_whole_composition():
    _scene, obj = _object_from(SHARED)
    shared = [k for k in range(obj.structure.n_atoms)
              if obj.site_composition(k)]
    assert shared
    text = obj.occupancy_text(shared[0])
    assert "Fe0.60" in text and "Ni0.40" in text


def test_a_plain_partial_site_reads_out_its_number():
    _scene, obj = _object_from(SHARED)
    partial = [k for k in range(obj.structure.n_atoms)
               if obj.structure.symbols[k] == "O"]
    assert partial
    assert obj.occupancy_text(partial[0]) == "0.50"


def test_a_full_site_says_nothing():
    """A label reading 1.00 on every atom of an ordered structure is noise."""
    _scene, obj = _object_from(SHARED)
    full = [k for k in range(obj.structure.n_atoms)
            if obj.structure.symbols[k] == "C"]
    assert full
    assert obj.occupancy_text(full[0]) == ""


def test_the_pick_label_carries_the_occupancy():
    scene, obj = _object_from(SHARED)
    shared = [k for k in range(obj.structure.n_atoms)
              if obj.site_composition(k)][0]
    label = scene.pick_label((obj.id, shared))
    assert "[" in label and "Fe0.60" in label


def test_a_molecule_without_a_cell_has_no_occupancy():
    scene = Scene()
    obj = scene.add(Structure(["C", "H"], np.array([[0.0, 0, 0],
                                                    [1.1, 0, 0]])))
    assert obj.occupancy_of(0) is None
    assert obj.occupancy_text(0) == ""
    assert scene.pick_label((obj.id, 0)) == "C0"      # unchanged


def test_the_occupancy_label_mode_renders():
    _scene, obj = _object_from(SHARED)
    shared = [k for k in range(obj.structure.n_atoms)
              if obj.site_composition(k)][0]
    obj.atom_label_modes[shared] = "occupancy"
    assert "Fe0.60" in obj.label_for(shared)


def test_the_mode_is_offered_but_gated_on_a_cell(qapp):
    from molom.ui import outliner
    assert ("occupancy", "Occupancy") in outliner.LABEL_MODES
    _scene, crystal = _object_from(SHARED)
    scene = Scene()
    molecule = scene.add(Structure(["C"], np.zeros((1, 3))))
    assert outliner._mode_is_available("occupancy", crystal)
    assert not outliner._mode_is_available("occupancy", molecule)
    # ...and a mode that is not crystal-only is always available
    assert outliner._mode_is_available("element", molecule)


@pytest.fixture
def qapp():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])
