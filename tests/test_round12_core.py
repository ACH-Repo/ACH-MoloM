"""Round-12 core: VSEPR hydrogen geometry, molecule merging, SMILES from the
graph, and operator aliases."""

import numpy as np
import pytest

from molom.core import bonding, build, edits, io
from molom.core.ops import OperatorRegistry
from molom.core.scene import Scene
from molom.core.structure import Structure


def _angles(s, centre):
    d = s.coords[s.bonded_neighbors(centre)] - s.coords[centre]
    d /= np.linalg.norm(d, axis=1)[:, None]
    return [np.degrees(np.arccos(np.clip(float(np.dot(d[a], d[b])), -1, 1)))
            for a in range(len(d)) for b in range(a)]


# ------------------------------------------------------- hydrogen geometry

@pytest.mark.parametrize("symbol,n_h,want", [
    ("C", 4, 109.47),      # tetrahedral
    ("N", 3, 109.47),      # pyramidal: 3 bonds + 1 lone pair
    ("O", 2, 109.47),      # bent: 2 bonds + 2 lone pairs
])
def test_hydride_geometry(symbol, n_h, want):
    """Adding hydrogens one at a time used to re-derive the geometry after
    each one (linear, then bent, then trigonal), so methane came out flat."""
    s = Structure.from_atoms([(symbol, 0, 0, 0)])
    added, _removed = edits.adjust_hydrogens(s, [0])
    assert added == n_h
    for ang in _angles(s, 0):
        assert abs(ang - want) < 2.0, "{}H{}: {:.1f} deg".format(
            symbol, n_h, ang)


def test_halide_and_bond_lengths():
    s = Structure.from_atoms([("F", 0, 0, 0)])
    assert edits.adjust_hydrogens(s, [0]) == (1, 0)
    d = float(np.linalg.norm(s.coords[1] - s.coords[0]))
    assert d == pytest.approx(edits.ideal_bond_length(s, 0, 1), abs=1e-9)


def test_double_bond_gives_planar_120():
    s = Structure.from_atoms([("C", 0, 0, 0), ("C", 1.33, 0, 0)])
    bonding.perceive_structure_bonds(s)
    bonding.perceive_structure_bond_orders(s)
    assert s.bonds[0][2] == 2
    edits.adjust_hydrogens(s, [0, 1])
    assert s.n_atoms == 6                     # ethene, not ethane
    for ang in _angles(s, 0):
        assert abs(ang - 120.0) < 3.0, ang


# ------------------------------------------------------------------- merge

def _two_molecules():
    sc = Scene()
    a = Structure.from_atoms([("O", 0, 0, 0), ("H", 0.96, 0, 0),
                              ("H", -0.24, 0.93, 0)], name="water")
    b = Structure.from_atoms([("N", 3.0, 0, 0), ("H", 3.9, 0, 0)],
                             name="ammonia")
    for s in (a, b):
        bonding.perceive_structure_bonds(s)
    return sc, sc.add(a), sc.add(b)


def test_merge_keeps_positions_and_reindexes_bonds():
    sc, a, b = _two_molecules()
    before = np.vstack([a.structure.coords, b.structure.coords])
    merged = sc.merge([a.id, b.id])
    assert merged is not None
    assert merged.structure.n_atoms == 5
    assert np.allclose(merged.structure.coords, before), \
        "merging moved atoms — the arrangement must be preserved"
    assert merged.structure.symbols == ["O", "H", "H", "N", "H"]
    # water's O-H bonds plus ammonia's N-H, shifted by 3
    assert (3, 4, 1) in merged.structure.bonds
    assert len(merged.structure.bonds) == 3
    assert sc.n_objects == 3, "originals kept by default"


def test_merge_can_consume_the_originals():
    sc, a, b = _two_molecules()
    merged = sc.merge([a.id, b.id], keep_originals=False)
    assert sc.n_objects == 1 and sc.objects[0] is merged
    assert merged.name.startswith("water+ammonia")


def test_merge_needs_two_molecules():
    sc, a, _b = _two_molecules()
    assert sc.merge([a.id]) is None
    assert sc.merge([]) is None


# ------------------------------------------------------------------ SMILES

def test_smiles_from_graph():
    s = Structure.from_atoms([("C", 0, 0, 0), ("C", 1.33, 0, 0)])
    bonding.perceive_structure_bonds(s)
    bonding.perceive_structure_bond_orders(s)
    edits.adjust_hydrogens(s, [0, 1])
    smiles, err = io.structure_to_smiles(s.symbols, s.bonds)
    assert err is None and smiles == "C=C", smiles


def test_smiles_of_cubane_is_a_cage():
    s = build.cubane()
    smiles, err = io.structure_to_smiles(s.symbols, s.bonds)
    assert err is None
    # Round-trip it: the graph we drew must come back with cubane's own
    # counts (8 carbons, 12 C-C edges) however RDKit chose to write it.
    from rdkit import Chem
    mol = Chem.MolFromSmiles(smiles)
    assert mol is not None, smiles
    assert mol.GetNumAtoms() == 8, smiles
    assert mol.GetNumBonds() == 12, smiles
    assert all(b.GetBondType() == Chem.BondType.SINGLE
               for b in mol.GetBonds()), smiles


def test_smiles_reports_errors_not_exceptions():
    smiles, err = io.structure_to_smiles(["Zz"], [])
    assert smiles is None and "unknown element" in err


# ----------------------------------------------------------------- aliases

def test_operator_aliases_are_searchable():
    r = OperatorRegistry()
    r.register("reperceive", "Re-perceive bonds", lambda c: None,
               category="Molecule",
               aliases=("recalculate bonds", "redetect bonds"))
    for term in ("re-perceive", "recalculate", "redetect bonds"):
        assert [op.id for op, _e in r.search(term, None)] == ["reperceive"], \
            term
    assert r.search("nonsense", None) == []
