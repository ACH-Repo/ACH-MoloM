"""Round 45d: the sandbox's alternative completion rule.

The experiment: wrap atom by atom (the VESTA picture), take connectivity from
the periodic graph, then draw every fragment that reaches into the cell WHOLE
— instead of relocating it so its centroid lands inside, which is what the
shipping pipeline does.

The regression case is Christian's `242083.cif`: one C60 split across the four
c-edges. The shipping pipeline reassembles it into ONE fullerene that sticks
out of the box; this one completes all four, plus the central one, for five.
"""
import os
from collections import Counter

import numpy as np
import pytest

from molom.core import pipeline, sandbox
from tests.test_round18_cif import NACL_CIF

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def qapp():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _components(symbols, bonds):
    n = len(symbols)
    adjacency = [[] for _ in range(n)]
    for i, j, _o in bonds:
        adjacency[i].append(j)
        adjacency[j].append(i)
    seen = [False] * n
    sizes = []
    for seed in range(n):
        if seen[seed]:
            continue
        seen[seed] = True
        stack, count = [seed], 0
        while stack:
            i = stack.pop()
            count += 1
            for j in adjacency[i]:
                if not seen[j]:
                    seen[j] = True
                    stack.append(j)
        sizes.append(count)
    return Counter(sizes)


# ------------------------------------------------------------- the stages
def test_the_early_stages_are_the_real_pipelines():
    """Cell / Sites / Operators / Wrap / Dedupe are not reimplemented — the
    sandbox calls `pipeline.run` for them, so the part not under experiment
    cannot drift."""
    shared = pipeline.stage_index("dedupe") + 1
    assert sandbox.STAGES[:shared] == list(pipeline.STAGES[:shared])
    for index in range(shared):
        a = pipeline.run(NACL_CIF, index)
        b = sandbox.run(NACL_CIF, index)
        assert a.symbols == b.symbols
        assert a.coords == pytest.approx(b.coords)


def test_the_sandbox_stops_after_molecules():
    assert [s.key for s in sandbox.STAGES] == [
        "cell", "sites", "operators", "wrap", "dedupe", "occupancy",
        "boundary", "bonds", "molecules"]


def test_a_stage_is_a_pure_function_of_the_text():
    index = sandbox.stage_index("bonds")
    first = sandbox.run(NACL_CIF, index)
    sandbox.run(NACL_CIF, len(sandbox.STAGES) - 1)     # run the whole thing
    second = sandbox.run(NACL_CIF, index)
    assert first.symbols == second.symbols
    assert first.coords == pytest.approx(second.coords)
    assert first.bonds == second.bonds


def test_rubbish_text_is_reported_not_raised():
    result = sandbox.run("not a CIF", len(sandbox.STAGES) - 1)
    assert result.error
    assert not result.symbols


# ---------------------------------------------------------- the occupancy
#: Two half-occupied species on ONE position (case B) plus a half-occupied
#: atom on its own (case A), so both branches are exercised by one file.
SHARED_CIF = """data_shared
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
"""


def test_a_shared_position_becomes_one_pie_chart_atom():
    """Case B: several species on one Gitterplatz collapse to a single atom
    carrying the composition."""
    result = sandbox.run(SHARED_CIF, sandbox.stage_index("occupancy"))
    table = (result.meta or {}).get("site_occupancy") or {}
    assert len(table) == 1
    composition = {sym: occ for sym, occ in list(table.values())[0]}
    assert composition == pytest.approx({"Fe": 0.6, "Ni": 0.4})
    note = result.trace[-1].note
    assert "SHARED positions: 1 atom" in note


def test_a_distinct_partial_occupancy_stays_a_full_atom():
    """Case A: spatially separate alternatives are drawn as ordinary atoms —
    a methyl over two orientations showing six hydrogens is a wanted cue."""
    result = sandbox.run(SHARED_CIF, sandbox.stage_index("occupancy"))
    assert "DISTINCT partial occupancies: 1 atom" in result.trace[-1].note
    assert "O" in result.symbols            # kept, not dropped


def test_the_composition_survives_dedupe_eating_the_site():
    """The ordering flaw this stage exists to work around: `expand`'s
    minimum-image merge removes the co-located species BEFORE occupancy is
    consulted, so the shared site cannot be recovered from the drawn atoms
    and has to come from the asymmetric unit."""
    from molom.core import cif
    data = cif.parse_cif(SHARED_CIF)
    drawn, _c = cif.expand(data, whole_molecules=False, boundary=False,
                           disorder=cif.POLICY_ALL)
    assert drawn.count("Ni") == 0          # merged away by Dedupe
    composition, info = sandbox.classify_occupancy(data, len(drawn))
    assert info["merged_away"] >= 1
    assert composition                      # recovered anyway


def test_nothing_to_say_when_every_site_is_full():
    result = sandbox.run(NACL_CIF, sandbox.stage_index("occupancy"))
    assert "no partial occupancies" in result.trace[-1].note
    assert not (result.meta or {}).get("site_occupancy")


def test_the_composition_rides_onto_the_completed_copies():
    """A copy of a shared site is still that site (round 42), or the cell
    shows one pie sphere in the middle and plain spheres at the corners."""
    result = sandbox.run(SHARED_CIF, len(sandbox.STAGES) - 1)
    table = (result.meta or {}).get("site_occupancy") or {}
    assert table
    assert all(int(k) < len(result.symbols) for k in table)
    for key in table:
        assert result.symbols[int(key)] == "Fe"


# ----------------------------------------------------------- the boundary
def test_an_atom_on_a_boundary_is_repeated_2_to_the_k():
    """k coordinates on a boundary -> 2^k positions. The wrap cannot produce
    these: it is a function, so 0 maps to 0 and never to 1."""
    frac = np.array([[0.0, 0.0, 0.0],     # a corner  -> 8
                     [0.0, 0.5, 0.5],     # a face    -> 2
                     [0.0, 0.0, 0.5],     # an edge   -> 4
                     [0.3, 0.4, 0.5]])    # interior  -> 1
    instances, counts = sandbox.boundary_instances(frac)
    assert counts == {1: 1, 2: 1, 3: 1}
    assert len(instances) == 8 + 2 + 4 + 1
    # the untranslated atoms come first and keep their indices
    assert instances[:4] == [(0, (0, 0, 0)), (1, (0, 0, 0)),
                             (2, (0, 0, 0)), (3, (0, 0, 0))]


def test_an_atom_at_the_high_face_is_repeated_downwards():
    """A coordinate of 1.0 is the same boundary as 0.0, so its copy is at
    -1, not +1."""
    instances, counts = sandbox.boundary_instances(
        np.array([[1.0, 0.5, 0.5]]))
    assert counts[1] == 1
    assert sorted(instances) == [(0, (-1, 0, 0)), (0, (0, 0, 0))]


def test_nothing_on_a_boundary_means_nothing_repeated():
    instances, counts = sandbox.boundary_instances(
        np.array([[0.25, 0.5, 0.75]]))
    assert instances == [(0, (0, 0, 0))]
    assert not any(counts.values())


# -------------------------------------------------------------- the bonds
def test_over_valence_is_allowed():
    """Christian's call, and VESTA and Mercury agree: a methyl disordered
    over two orientations should show six hydrogens. `4-ABA-oxime.cif` is the
    case — but the rule is what is tested, not the file."""
    from molom.core import bondgraph, cif
    cell = cif.Cell(20.0, 20.0, 20.0)
    # one carbon with six hydrogens around it at 1.1 A
    symbols = ["C"] + ["H"] * 6
    offsets = np.array([[0, 0, 0], [1.1, 0, 0], [-1.1, 0, 0], [0, 1.1, 0],
                        [0, -1.1, 0], [0, 0, 1.1], [0, 0, -1.1]])
    frac = (np.array([10.0, 10.0, 10.0]) + offsets) / 20.0
    capped = bondgraph.build(symbols, frac, cell)
    loose = bondgraph.build(symbols, frac, cell, valence=False,
                            cap_hydrogens=False)
    assert capped.coordination()[0] == 4          # the shipping rule
    assert loose.coordination()[0] == 6           # what the sandbox draws
def test_bonds_are_only_drawn_where_both_ends_are_present():
    """The wrap tears molecules, so some bonds are KNOWN (the periodic graph
    has them) but not drawable — their partner is not on screen."""
    result = sandbox.run(NACL_CIF, sandbox.stage_index("bonds"))
    note = result.trace[-1].note
    assert "the periodic graph has" in note
    n = len(result.symbols)
    assert all(0 <= i < n and 0 <= j < n for i, j, _o in result.bonds)


def test_the_wrap_is_left_exactly_where_it_was():
    """Nothing is relocated: later stages only ADD, so every atom the wrap
    placed is still at that exact position, at the same index."""
    wrapped = sandbox.run(NACL_CIF, sandbox.stage_index("dedupe"))
    n = len(wrapped.symbols)
    for later in ("occupancy", "boundary", "bonds", "molecules"):
        result = sandbox.run(NACL_CIF, sandbox.stage_index(later))
        assert result.symbols[:n] == wrapped.symbols
        assert result.coords[:n] == pytest.approx(wrapped.coords)


# ---------------------------------------------------------- the completion
def test_completion_only_ever_adds():
    before = sandbox.run(NACL_CIF, sandbox.stage_index("bonds"))
    after = sandbox.run(NACL_CIF, sandbox.stage_index("molecules"))
    assert len(after.symbols) >= len(before.symbols)


def test_the_checkbox_hides_the_outside_atoms():
    with_outside = sandbox.run(NACL_CIF, len(sandbox.STAGES) - 1,
                               outside=True)
    without = sandbox.run(NACL_CIF, len(sandbox.STAGES) - 1, outside=False)
    assert len(without.symbols) <= len(with_outside.symbols)
    assert "HIDDEN" in without.trace[-1].note


def test_a_molecule_reaching_in_is_completed_not_moved():
    """A diatomic straddling the x face: the shipping pipeline would walk it
    contiguous and shift it bodily inside. Here both images that reach in are
    drawn whole, so no atom that was in the cell has moved."""
    cell_text = """data_pair
_cell_length_a 10.0
_cell_length_b 10.0
_cell_length_c 10.0
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
C1 C 0.03 0.50 0.50
C2 C 0.90 0.50 0.50
"""
    wrapped = sandbox.run(cell_text, sandbox.stage_index("dedupe"))
    done = sandbox.run(cell_text, len(sandbox.STAGES) - 1)
    # the two original atoms are still exactly where the wrap put them
    for row in np.asarray(wrapped.coords):
        assert np.min(np.linalg.norm(np.asarray(done.coords) - row,
                                     axis=1)) < 1e-9
    # and the molecule is whole at both ends
    assert len(done.symbols) > len(wrapped.symbols)
    assert set(_components(done.symbols, done.bonds)) == {2}


def test_periodic_components_are_not_completed():
    """A framework has no 'whole' to complete; it keeps its in-cell atoms and
    says so, rather than growing without bound."""
    result = sandbox.run(NACL_CIF, len(sandbox.STAGES) - 1)
    assert "no 'whole' to complete" in result.trace[-1].note


def test_the_completion_is_deterministic():
    a = sandbox.run(NACL_CIF, len(sandbox.STAGES) - 1)
    b = sandbox.run(NACL_CIF, len(sandbox.STAGES) - 1)
    assert a.symbols == b.symbols
    assert a.coords == pytest.approx(b.coords)
    assert a.bonds == b.bonds


def test_complete_molecules_pools_shifts_over_the_group():
    """Round 43b's lesson: a fragment on a corner can have atoms on the x, y
    and z faces and no atom with all three coordinates at zero, so per-atom
    shift options reach three faces and three edges but never the far corner.
    A molecule sitting on the origin corner must come out at all eight."""
    from molom.core import cif
    cell = cif.Cell(10.0, 10.0, 10.0)
    # A diatomic with one atom exactly ON the origin: that atom belongs to
    # all eight corners, so the molecule must be drawn eight times.
    symbols = ["C", "C"]
    frac = np.array([[0.00, 0.00, 0.00],
                     [0.15, 0.00, 0.00]])    # 1.5 A apart
    out_s, _out_f, bonds, info, source = sandbox.complete_molecules(
        symbols, frac, cell, outside=True)
    assert len(source) == len(out_s)
    assert info["finite"] == 1
    assert info["copies"] == 8            # all eight corners
    assert len(out_s) == 16
    assert len(bonds) == 8                # each copy still bonded


# ---------------------------------------------------------------- the page
def test_the_page_has_a_button_per_stage_and_the_checkbox(qapp):
    from molom.ui.sandbox_page import SandboxPage
    page = SandboxPage()
    assert len(page.stage_buttons) == len(sandbox.STAGES)
    assert page.options() == {"outside": True}
    page.outside.setChecked(False)
    assert page.options() == {"outside": False}
