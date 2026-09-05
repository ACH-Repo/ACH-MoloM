"""Round 106 - F4: a selection becomes an ORCA constraint or a scan.

The format is ORCA Workbench's, so the tests that matter here are the ones
that compare against OWB's own `geomspec` module rather than against numbers
written down in MoloM. They skip where the sibling repo is not checked out,
which is round 92's arrangement.
"""

import os
import sys

import numpy as np
import pytest

from molom.core import internal
from molom.core import orca


# ------------------------------------------------------------ OWB, if present
def _owb():
    """ORCA Workbench's `geomspec`, or None where it is not checked out."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for name in ("ACH-Orca-Studio", "ACH-Orca-Workbench"):
        root = os.path.join(os.path.dirname(here), name)
        if os.path.isdir(os.path.join(root, "orca_workbench")):
            if root not in sys.path:
                sys.path.insert(0, root)
            try:
                from orca_workbench.core import geomspec
                return geomspec
            except ImportError:
                return None
    return None


owb = _owb()
needs_owb = pytest.mark.skipif(owb is None,
                               reason="ORCA Workbench is not checked out")


# ------------------------------------------------- what a selection means
def test_the_number_of_atoms_decides_the_coordinate():
    """One atom freezes a position, two a bond, three an angle, four a
    dihedral - and the three internal ones are `internal.kind_for_count`,
    so the constraint and the measurement readout cannot disagree about what
    picking three atoms means."""
    assert orca.coord_type(1) == "C"
    assert orca.coord_type(2) == "B"
    assert orca.coord_type(3) == "A"
    assert orca.coord_type(4) == "D"
    assert orca.coord_type(5) is None
    assert orca.coord_type(0) is None
    for n, kind in ((2, internal.DISTANCE), (3, internal.ANGLE),
                    (4, internal.DIHEDRAL)):
        assert orca.COORD_FOR_KIND[internal.kind_for_count(n)] \
            == orca.coord_type(n)


def test_a_selection_that_is_not_a_coordinate_is_refused():
    with pytest.raises(orca.OrcaSpecError):
        orca.constraint([0, 1, 2, 3, 4])
    with pytest.raises(orca.OrcaSpecError):
        orca.constraint([])
    # ...and so is one that repeats an atom, which measures nothing
    with pytest.raises(orca.OrcaSpecError):
        orca.constraint([2, 2])
    with pytest.raises(orca.OrcaSpecError):
        orca.constraint([-1, 3])
    # a Cartesian freeze is not a scannable coordinate
    with pytest.raises(orca.OrcaSpecError):
        orca.scan([4], 0.0, 1.0, 5)


def test_a_constraint_defaults_to_freezing_where_it_is():
    """ORCA's own "no value means keep it here". Writing the number instead
    would only repeat what the geometry says, and is how a constraint comes
    to disagree with the structure it was read from."""
    assert "value" not in orca.constraint([0, 1])
    assert orca.constraint_line(orca.constraint([0, 1])) == "{ B 0 1 C }"
    assert orca.constraint_line(orca.constraint([0, 1], 1.5)) \
        == "{ B 0 1 1.5 C }"
    # a Cartesian freeze has no value to state at all
    assert orca.constraint_line(orca.constraint([5], 1.5)) == "{ C 5 C }"


# ------------------------------------------------- the text OWB would write
@needs_owb
def test_the_geom_block_is_BYTE_FOR_BYTE_what_OWB_builds():
    """Re-implemented rather than imported, because MoloM must not require
    OWB to be installed - so this is what stops the two drifting."""
    cases = [
        orca.spec([orca.constraint([0, 1])]),
        orca.spec([orca.constraint([0, 1], 1.5)]),
        orca.spec([orca.constraint([3, 1, 2], 109.47)]),
        orca.spec([orca.constraint([0, 1, 2, 3], -60.0)]),
        orca.spec([orca.constraint([7])]),
        orca.spec([], orca.scan([0, 1], 1.5, 3.0, 10)),
        orca.spec([orca.constraint([2, 3]), orca.constraint([9])],
                  orca.scan([0, 1, 2, 3], -180.0, 180.0, 36)),
    ]
    for spec in cases:
        assert orca.geom_inner(spec) == owb.build_geom_inner(spec), \
            orca.describe(spec)


@needs_owb
def test_the_spec_shape_is_one_OWB_accepts():
    """It is handed straight to `geomspec.validate`, which is what OWB runs
    before building an input."""
    spec = orca.spec([orca.constraint([0, 1]), orca.constraint([4])],
                     orca.scan([1, 2], 1.0, 2.0, 8))
    assert owb.validate(spec, n_atoms=10) == []
    # and an out-of-range index is caught by OWB, not silently written
    bad = orca.spec([orca.constraint([0, 99])])
    assert owb.validate(bad, n_atoms=10)


@needs_owb
def test_the_BOND_AND_ANGLE_measurements_agree_with_ORCA_WORKBENCH():
    rng = np.random.default_rng(11)
    for _ in range(40):
        coords = rng.normal(0.0, 1.5, (4, 3))
        atoms = [("C", float(p[0]), float(p[1]), float(p[2])) for p in coords]
        for ctype, idx in (("B", [0, 1]), ("A", [0, 1, 2])):
            assert orca.measure_value(ctype, idx, coords) == pytest.approx(
                owb.measure(ctype, idx, atoms), abs=1e-9), ctype


@needs_owb
def test_the_DIHEDRAL_SIGN_DISAGREES_WITH_OWB_AND_MOLOM_IS_RIGHT():
    """Found by the cross-check, and recorded rather than papered over.

    A dihedral of the wrong sign describes the MIRROR IMAGE, and an input
    file carrying it would look perfectly reasonable - which is why this was
    the one measurement worth checking against another program at all.

    Settled by a THIRD implementation rather than by argument: RDKit's
    `rdMolTransforms.GetDihedralDeg` is the IUPAC convention ORCA itself
    uses, and over 200 random geometries **MoloM agrees with it 200 times
    and ORCA Workbench none**. So `geomspec.measure` has an inverted sign,
    and this test exists to stop anyone "fixing" MoloM to match it.

    It does not affect what MoloM writes: a literal number passes through
    OWB unchanged, and only OWB's own `current` / `D(i,j,k,l)` value
    EXPRESSIONS are resolved through the faulty measurement.
    """
    rng = np.random.default_rng(11)
    for _ in range(40):
        coords = rng.normal(0.0, 1.5, (4, 3))
        atoms = [("C", float(p[0]), float(p[1]), float(p[2])) for p in coords]
        mine = orca.measure_value("D", [0, 1, 2, 3], coords)
        theirs = owb.measure("D", [0, 1, 2, 3], atoms)
        assert mine == pytest.approx(-theirs, abs=1e-9), \
            "the disagreement is a SIGN and nothing else"


def test_the_dihedral_matches_RDKIT_which_is_what_ORCA_expects():
    """The convention that actually matters, pinned without the sibling repo
    having to be checked out."""
    Chem = pytest.importorskip("rdkit.Chem")
    from rdkit.Chem import rdMolTransforms
    from rdkit.Geometry import Point3D

    def reference(coords):
        mol = Chem.RWMol()
        for _ in range(4):
            mol.AddAtom(Chem.Atom(6))
        for a, b in ((0, 1), (1, 2), (2, 3)):
            mol.AddBond(a, b, Chem.BondType.SINGLE)
        conf = Chem.Conformer(4)
        for i, p in enumerate(coords):
            conf.SetAtomPosition(i, Point3D(*(float(v) for v in p)))
        mol.AddConformer(conf)
        return rdMolTransforms.GetDihedralDeg(mol.GetConformer(), 0, 1, 2, 3)

    rng = np.random.default_rng(5)
    for _ in range(40):
        coords = rng.normal(0.0, 1.5, (4, 3))
        assert orca.measure_value("D", [0, 1, 2, 3], coords) == pytest.approx(
            reference(coords), abs=1e-6)


@needs_owb
def test_the_block_can_be_injected_into_a_real_input():
    """End to end through OWB's own injector, so what MoloM copies is what
    an input file would carry."""
    from orca_workbench.core import inputs
    spec = orca.spec([orca.constraint([0, 1], 1.5)],
                     orca.scan([1, 2], 1.0, 2.0, 5))
    text = inputs.add_geom_block("! Opt PBE def2-SVP\n\n* xyz 0 1\n*\n",
                                 orca.geom_inner(spec))
    assert "%geom" in text and "Constraints" in text and "Scan" in text
    assert "{ B 0 1 1.5 C }" in text
    assert "B 1 2 = 1, 2, 5" in text


# ------------------------------------------------------- measuring and text
def test_the_value_is_read_off_the_GEOMETRY():
    """So a constraint says what the structure says, rather than what
    somebody typed."""
    coords = np.array([[0.0, 0.0, 0.0], [1.5, 0.0, 0.0],
                       [1.5, 1.0, 0.0], [1.5, 1.0, 2.0]])
    assert orca.measure_value("B", [0, 1], coords) == pytest.approx(1.5)
    assert orca.measure_value("A", [0, 1, 2], coords) == pytest.approx(90.0)
    assert abs(orca.measure_value("D", [0, 1, 2, 3], coords)) \
        == pytest.approx(90.0)


def test_the_whole_block_is_pasteable():
    """OWB injects the inner text into a block it already has; somebody
    pasting into an editor needs the wrapper too."""
    spec = orca.spec([orca.constraint([0, 1])])
    assert orca.geom_block(spec).splitlines()[0] == "%geom"
    assert orca.geom_block(spec).splitlines()[-1] == "end"
    assert orca.geom_block(orca.spec()) == "", "nothing to say, nothing said"


def test_a_scan_walks_from_start_to_end_INCLUSIVE():
    """ORCA counts steps, so N steps is N + 1 geometries and the last one is
    the end value - a real datum, not a repeat of the first."""
    points = orca.scan_points(orca.scan([0, 1], 1.5, 3.0, 3))
    assert points == pytest.approx([1.5, 2.0, 2.5, 3.0])
    assert orca.scan_points(orca.scan([0, 1], 2.0, 1.0, 2)) \
        == pytest.approx([2.0, 1.5, 1.0]), "and backwards is fine"


def test_what_a_relaxation_has_to_hold_still():
    """The scanned coordinate's own atoms, plus anything separately
    constrained - a preview that let the scanned bond relax back would be a
    picture of the force field's minimum rather than of the scan."""
    s = orca.scan([0, 1], 1.5, 3.0, 5)
    assert orca.frozen_atoms(s) == [0, 1]
    assert orca.frozen_atoms(s, [orca.constraint([4, 5])]) == [0, 1, 4, 5]
    assert orca.frozen_atoms(s, [orca.constraint([1, 5])]) == [0, 1, 5], \
        "no atom counted twice"
