"""Round 28: ligand templates — marking donors and docking onto placeholders."""

import numpy as np
import pytest

from molom.core import templates
from molom.core.structure import Structure


def _centre(n_h=4, r=2.0):
    """A metal with `n_h` tetrahedral-ish placeholder hydrogens."""
    dirs = np.array([[1.0, 1, 1], [1, -1, -1], [-1, 1, -1], [-1, -1, 1]])
    dirs = dirs / np.linalg.norm(dirs, axis=1)[:, None]
    atoms = [("Zn", 0.0, 0.0, 0.0)]
    for k in range(n_h):
        p = dirs[k] * r
        atoms.append(("H", p[0], p[1], p[2]))
    s = Structure.from_atoms(atoms)
    for j in range(1, n_h + 1):
        s.bonds.append((0, j, 1))
    return s


def _ligand():
    """A water-like ligand: donor O plus two H, sitting away from origin."""
    s = Structure.from_atoms([("O", 5.0, 5.0, 5.0), ("H", 5.8, 5.6, 5.0),
                              ("H", 4.2, 5.6, 5.0)])
    s.bonds = [(0, 1, 1), (0, 2, 1)]
    return s


def _bidentate():
    """Two donors 2.8 A apart, with a carbon backbone behind them."""
    s = Structure.from_atoms([("N", 0.0, 0.0, 0.0), ("N", 2.8, 0.0, 0.0),
                              ("C", 0.7, -1.2, 0.0), ("C", 2.1, -1.2, 0.0)])
    s.bonds = [(0, 2, 1), (2, 3, 1), (3, 1, 1)]
    return s


# ------------------------------------------------------------------ marking
def test_marking_and_reading_back_ligating_atoms():
    lig = _ligand()
    assert templates.set_ligating(lig, [0]) == [0]
    assert templates.get_ligating(lig) == [0]
    templates.clear_ligating(lig)
    assert templates.get_ligating(lig) == []


def test_marking_ignores_out_of_range_indices():
    lig = _ligand()
    assert templates.set_ligating(lig, [0, 99, -1]) == [0]


def test_marks_survive_a_json_round_trip():
    import json
    lig = _ligand()
    templates.set_ligating(lig, [0])
    assert json.loads(json.dumps(lig.metadata))["ligating"] == [0]


# ------------------------------------------------------------- placeholders
def test_geminal_placeholders_resolve_to_their_centre():
    host = _centre()
    assert templates.check_placeholders(host, [1, 2]) == 0


def test_non_geminal_placeholders_are_refused():
    """Christian's question: only geminal. Two placeholders on DIFFERENT
    centres describe a bridge, which is a different operation."""
    s = Structure.from_atoms([("Zn", 0, 0, 0), ("H", 2.0, 0, 0),
                              ("Zn", 9, 0, 0), ("H", 11.0, 0, 0)])
    s.bonds = [(0, 1, 1), (2, 3, 1)]
    with pytest.raises(templates.TemplateError, match="geminal"):
        templates.check_placeholders(s, [1, 3])


def test_a_non_terminal_placeholder_is_refused():
    s = Structure.from_atoms([("Zn", 0, 0, 0), ("C", 2.0, 0, 0),
                              ("C", 3.5, 0, 0)])
    s.bonds = [(0, 1, 1), (1, 2, 1)]
    with pytest.raises(templates.TemplateError, match="terminal"):
        templates.check_placeholders(s, [1])


def test_placeholders_need_not_be_hydrogen():
    """Christian's other question: any terminal atom works — a Cl or a dummy
    is as good a placeholder as an H."""
    s = Structure.from_atoms([("Zn", 0, 0, 0), ("Cl", 2.0, 0, 0),
                              ("Cl", -2.0, 0, 0)])
    s.bonds = [(0, 1, 1), (0, 2, 1)]
    assert templates.check_placeholders(s, [1, 2]) == 0


def test_no_placeholders_selected_is_refused():
    with pytest.raises(templates.TemplateError):
        templates.check_placeholders(_centre(), [])


# -------------------------------------------------------------------- the fit
def test_one_donor_lands_exactly_on_its_placeholder():
    host, lig = _centre(), _ligand()
    slot = 1
    rot, trans = templates.coordinate(host.coords, [slot], 0, lig.coords, [0])
    moved = lig.coords @ rot.T + trans
    assert moved[0] == pytest.approx(host.coords[slot], abs=1e-9)


def test_one_donor_points_the_ligand_away_from_the_centre():
    """The rotation is otherwise free, so the one thing it must get right is
    not burying the ligand inside the metal."""
    host, lig = _centre(), _ligand()
    slot = 1
    rot, trans = templates.coordinate(host.coords, [slot], 0, lig.coords, [0])
    moved = lig.coords @ rot.T + trans
    outward = host.coords[slot] - host.coords[0]
    outward /= np.linalg.norm(outward)
    bulk = moved[1:].mean(axis=0) - moved[0]
    assert float(bulk @ outward) > 0.0


def test_the_ligand_is_not_distorted_by_the_fit():
    host, lig = _centre(), _ligand()
    rot, trans = templates.coordinate(host.coords, [1], 0, lig.coords, [0])
    moved = lig.coords @ rot.T + trans
    for a in range(len(lig.coords)):
        for b in range(a + 1, len(lig.coords)):
            before = np.linalg.norm(lig.coords[a] - lig.coords[b])
            after = np.linalg.norm(moved[a] - moved[b])
            assert after == pytest.approx(before, abs=1e-9)


def test_two_donors_land_on_both_placeholders():
    host = _centre(r=2.0)
    lig = _bidentate()
    # Space the two slots to match the donor separation as closely as the
    # tetrahedron allows; the fit still puts each donor on its own slot.
    rot, trans = templates.coordinate(host.coords, [1, 2], 0, lig.coords,
                                      [0, 1])
    moved = lig.coords @ rot.T + trans
    gap_before = np.linalg.norm(lig.coords[0] - lig.coords[1])
    gap_after = np.linalg.norm(moved[0] - moved[1])
    assert gap_after == pytest.approx(gap_before, abs=1e-9)
    # the donor midpoint sits on the placeholder midpoint
    assert moved[[0, 1]].mean(axis=0) == pytest.approx(
        host.coords[[1, 2]].mean(axis=0), abs=1e-9)


def test_two_donors_put_the_backbone_away_from_the_metal():
    host = _centre()
    lig = _bidentate()
    rot, trans = templates.coordinate(host.coords, [1, 2], 0, lig.coords,
                                      [0, 1])
    moved = lig.coords @ rot.T + trans
    donors_mid = moved[[0, 1]].mean(axis=0)
    backbone = moved[[2, 3]].mean(axis=0) - donors_mid
    outward = donors_mid - host.coords[0]
    assert float(backbone @ outward) > 0.0


def test_three_or_more_donors_use_the_kabsch_fit():
    host = _centre()
    # A tripod ligand whose donors already match three of the slots.
    target = host.coords[[1, 2, 3]]
    atoms = [("N", *target[0] + [9.0, 0, 0]), ("N", *target[1] + [9.0, 0, 0]),
             ("N", *target[2] + [9.0, 0, 0]), ("C", 9.0, 0.0, 0.0)]
    lig = Structure.from_atoms(atoms)
    rot, trans = templates.coordinate(host.coords, [1, 2, 3], 0, lig.coords,
                                      [0, 1, 2])
    moved = lig.coords @ rot.T + trans
    assert moved[:3] == pytest.approx(target, abs=1e-6)


def test_a_donor_placeholder_count_mismatch_is_refused():
    host, lig = _centre(), _ligand()
    with pytest.raises(templates.TemplateError, match="match"):
        templates.coordinate(host.coords, [1, 2], 0, lig.coords, [0])


def test_an_unmarked_ligand_is_refused():
    host, lig = _centre(), _ligand()
    with pytest.raises(templates.TemplateError, match="ligating"):
        templates.coordinate(host.coords, [1], 0, lig.coords, [])
