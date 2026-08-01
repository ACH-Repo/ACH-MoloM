"""IO cascade: xyz round-trips, frame parsing, heuristic salvage, SMILES."""

import os

import pytest

from molom.core import io

WATER = [("O", 0.0, 0.0, 0.117), ("H", 0.0, 0.757, -0.469),
         ("H", 0.0, -0.757, -0.469)]


def test_xyz_roundtrip_with_metadata(tmp_path):
    p = str(tmp_path / "w.xyz")
    io.write_xyz(p, WATER, {"name": "water", "charge": 0})
    atoms, meta = io.read_xyz(p)
    assert [a[0] for a in atoms] == ["O", "H", "H"]
    assert abs(atoms[1][2] - 0.757) < 1e-6
    assert meta == {"name": "water", "charge": 0}


def test_parse_xyz_frames_text_multi():
    text = "\n".join(["2", "one", "H 0 0 0", "H 0 0 0.74",
                      "2", "two", "H 0 0 0", "H 0 0 0.80"])
    frames = io.parse_xyz_frames_text(text)
    assert len(frames) == 2
    assert frames[1][0][1][3] == 0.80


def test_parse_xyz_frames_rejects_smiles():
    assert io.parse_xyz_frames_text("CCO\nc1ccccc1") == []


def test_frames_are_trajectory():
    f1 = ([("H", 0, 0, 0), ("H", 0, 0, 0.74)], None)
    f2 = ([("H", 0, 0, 0), ("H", 0, 0, 0.8)], None)
    f3 = ([("O", 0, 0, 0), ("H", 0, 0, 0.8)], None)
    assert io.frames_are_trajectory([f1, f2])
    assert not io.frames_are_trajectory([f1, f3])
    assert not io.frames_are_trajectory([f1])


def test_read_structures_multiframe_xyz(tmp_path):
    p = str(tmp_path / "traj.xyz")
    io.write_structures_file(p, [(WATER, "a"), (WATER, "b")])
    structs = io.read_structures(p)
    assert len(structs) == 2


def test_heuristic_salvage():
    text = "\n".join([
        "some header", "! input deck stuff",
        "C   0.000  0.000  0.000",
        "O   1.200  0.000  0.000",
        "H  -0.600  0.900  0.000",
        "trailing junk 1 2",
    ])
    atoms = io.heuristic_atoms_from_text(text)
    assert [a[0] for a in atoms] == ["C", "O", "H"]


def test_heuristic_rejects_numeric_tables():
    text = "\n".join(["1.0 2.0 3.0 4.0", "5.0 6.0 7.0 8.0"])
    assert io.heuristic_atoms_from_text(text) == []


def test_heuristic_fortran_exponents():
    text = "\n".join(["C 1.0D+00 0.0 0.0", "O 2.5d-01 0.0 0.0"])
    atoms = io.heuristic_atoms_from_text(text)
    assert atoms[0][1] == 1.0
    assert atoms[1][1] == 0.25


def test_missing_file_raises():
    with pytest.raises(io.CoordGenError):
        io.read_structures(os.path.join("definitely", "not", "here.xyz"))


def test_name_filters_shape():
    filters = io.import_name_filters()
    assert filters[0].startswith("Coordinate files (")
    assert "*.xyz" in filters[0]
    assert filters[-1] == "All files (*)"


def test_meta_from_title():
    assert io._meta_from_title('{"name": "x", "charge": 1}') == \
        {"name": "x", "charge": 1}
    assert io._meta_from_title("benzene") == {"name": "benzene"}
    assert io._meta_from_title("C:\\path\\to\\file") is None
    assert io._meta_from_title("mol", source_path="/tmp/mol.sdf") is None
    assert io._meta_from_title('{"broken":') is None


# ---- backends present on this dev machine (rdkit + openbabel installed) ----

def test_smiles_to_xyz_water():
    atoms, method = io.smiles_to_xyz("O")
    assert method in ("rdkit", "pybel")
    assert sorted(a[0] for a in atoms) == ["H", "H", "O"]


def test_smiles_charge_and_mult():
    assert io.smiles_charge_and_mult("O") == (0, 1)
    assert io.smiles_charge_and_mult("[NH4+]") == (1, 1)
    assert io.smiles_charge_and_mult("[CH3]") == (0, 2)


def test_parse_smiles_list_two_column():
    pairs = io.parse_smiles_list("CCO ethanol\nc1ccccc1 benzene")
    assert pairs == [("CCO", "ethanol"), ("c1ccccc1", "benzene")]
    # name-first order auto-detected too
    pairs = io.parse_smiles_list("ethanol CCO\nbenzene c1ccccc1")
    assert pairs == [("CCO", "ethanol"), ("c1ccccc1", "benzene")]


def test_sdf_roundtrip_via_backends(tmp_path):
    p = str(tmp_path / "w.sdf")
    backend = io.write_structure_file(p, WATER, name="water")
    assert backend in ("openbabel", "rdkit")
    structs = io.read_structures(p)
    assert len(structs) == 1
    assert sorted(a[0] for a in structs[0][0]) == ["H", "H", "O"]
