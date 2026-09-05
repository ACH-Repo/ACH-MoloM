"""Round 106 - the relaxed surface scan preview.

Christian: "If I want a more visual way of showing what a restraint/scan in
ORCA will do, I think it would be good to see it animated within molom."

The headline test is CHEMISTRY rather than arithmetic: butane's torsional
profile is a thing the world already knows the answer to, so a scan that
reproduces it is a scan that is doing what it says.
"""

import numpy as np
import pytest

from molom.core import bonding, internal, io, orca, scan


def _molecule(smiles):
    atoms = io.smiles_to_xyz(smiles)[0]
    symbols = [a[0] for a in atoms]
    coords = np.array([[a[1], a[2], a[3]] for a in atoms], dtype=float)
    bonds = bonding.perceive_bonds(symbols, coords)
    if isinstance(bonds, tuple):
        bonds = bonds[0]
    return symbols, coords, bonds


@pytest.fixture(scope="module")
def butane():
    pytest.importorskip("rdkit")
    return _molecule("CCCC")


def _carbons(symbols):
    return [i for i, s in enumerate(symbols) if s == "C"]


# ------------------------------------------------------------- the chemistry
def test_a_dihedral_scan_reproduces_BUTANE_S_TORSIONAL_PROFILE(butane):
    """The check that matters, and it is against the world rather than
    against numbers chosen here.

    Butane's rotation about the central C-C is one of the most measured
    curves in organic chemistry: an ANTI minimum at 180, GAUCHE minima near
    +-65 about 0.6-0.9 kcal/mol above it, an H-eclipsed barrier near +-120 of
    about 3.6, and the SYN barrier at 0 of about 4.5-6.5 where the two methyls
    meet. If the preview reproduces that, the relaxation is real and the
    coordinate is genuinely being held.
    """
    symbols, coords, bonds = butane
    item = orca.scan(_carbons(symbols)[:4], -180.0, 180.0, 36)
    frames, info = scan.scan_frames(symbols, coords, bonds, item)
    assert len(frames) == 37
    energies = info["energies"]
    assert len(energies) == 37, "an energy per point"

    def at(angle):
        return energies[int(np.argmin(np.abs(np.array(info["targets"])
                                             - angle)))]

    anti = min(at(-180.0), at(180.0))
    assert anti == pytest.approx(0.0, abs=1e-9), "anti is the global minimum"
    syn = at(0.0)
    assert 3.5 < syn < 8.0, "the two methyls eclipse: {}".format(syn)
    eclipsed = 0.5 * (at(-120.0) + at(120.0))
    assert 2.0 < eclipsed < 5.0, "H-eclipsed: {}".format(eclipsed)
    gauche = min(at(-60.0), at(60.0))
    assert 0.1 < gauche < 2.0, "gauche sits just above anti: {}".format(gauche)
    assert gauche < eclipsed < syn, "the barriers order correctly"
    # ...and the curve is symmetric, because butane is
    for a, b in zip(energies, list(reversed(energies))):
        assert a == pytest.approx(b, abs=0.05)


def test_the_scanned_coordinate_is_HELD_at_every_point(butane):
    """A relaxation that let the coordinate slide back would be a picture of
    the force field's minimum rather than of the scan - so the frozen set is
    the scanned atoms, and this is what proves it stayed frozen."""
    symbols, coords, bonds = butane
    item = orca.scan(_carbons(symbols)[:4], -170.0, -10.0, 8)
    _frames, info = scan.scan_frames(symbols, coords, bonds, item)
    assert info["worst_error"] < 1e-6
    assert info["frozen"] == _carbons(symbols)[:4]


def test_a_BOND_scan_really_moves_the_bond(butane):
    symbols, coords, bonds = butane
    pair = _carbons(symbols)[:2]
    item = orca.scan(pair, 1.5, 3.0, 6)
    frames, info = scan.scan_frames(symbols, coords, bonds, item)
    for frame, want in zip(frames, info["targets"]):
        got = internal.current_value(internal.DISTANCE, frame, pair)
        assert got == pytest.approx(want, abs=1e-6)
    # the rest of the molecule is not dragged along rigidly - it relaxes
    assert info["engine"] != "rigid"


def test_each_point_CONTINUES_from_the_last(butane):
    """What makes it a relaxed SCAN rather than a row of independent
    optimisations, and what keeps the path smooth: consecutive geometries
    differ by a small step, not by whichever basin each landed in."""
    symbols, coords, bonds = butane
    item = orca.scan(_carbons(symbols)[:4], -180.0, 180.0, 36)
    frames, _info = scan.scan_frames(symbols, coords, bonds, item)
    steps = [float(np.max(np.linalg.norm(b - a, axis=1)))
             for a, b in zip(frames, frames[1:])]
    assert max(steps) < 1.0, "no atom jumps between neighbouring points"


def test_the_first_frame_is_the_START_value_not_the_input_geometry(butane):
    """A scan that starts somewhere other than where the coordinate sits has
    to move it there first; showing the original as frame 0 would put a jump
    between the first two pictures."""
    symbols, coords, bonds = butane
    pair = _carbons(symbols)[:2]
    here = internal.current_value(internal.DISTANCE, coords, pair)
    item = orca.scan(pair, here + 0.5, here + 1.0, 4)
    frames, _info = scan.scan_frames(symbols, coords, bonds, item)
    assert internal.current_value(internal.DISTANCE, frames[0], pair) \
        == pytest.approx(here + 0.5, abs=1e-6)


# --------------------------------------------------------------- honesty
def test_a_structure_no_force_field_will_take_is_RIGID_and_SAYS_SO(butane,
                                                                   monkeypatch):
    """A preview that silently stopped relaxing is a rigid scan wearing a
    relaxed one's label. A metal complex is the ordinary case."""
    symbols, coords, bonds = butane

    def refuse(*_a, **_k):
        raise scan.forcefield.ForceFieldError("no parameters for Xx")

    monkeypatch.setattr(scan.forcefield, "optimize", refuse)
    item = orca.scan(_carbons(symbols)[:2], 1.5, 2.5, 4)
    frames, info = scan.scan_frames(symbols, coords, bonds, item)
    assert len(frames) == 5, "the preview still happens"
    assert info["engine"] == "rigid"
    assert any("rigid" in n for n in info["notes"])
    assert "rigid (not relaxed)" in scan.preview_note(info)
    # ...and the coordinate is still stepped exactly, because that half is
    # geometry and needs no force field at all
    assert info["worst_error"] < 1e-6


def test_relax_can_be_switched_off_for_a_rigid_preview(butane):
    symbols, coords, bonds = butane
    item = orca.scan(_carbons(symbols)[:4], 0.0, 90.0, 3)
    _frames, info = scan.scan_frames(symbols, coords, bonds, item, relax=False)
    assert info["engine"] == "rigid" and info["energies"] == []


def test_progress_is_reported_so_a_long_scan_can_show_one(butane):
    symbols, coords, bonds = butane
    seen = []
    item = orca.scan(_carbons(symbols)[:2], 1.4, 2.0, 5)
    scan.scan_frames(symbols, coords, bonds, item,
                     progress=lambda k, n: seen.append((k, n)))
    assert seen == [(1, 6), (2, 6), (3, 6), (4, 6), (5, 6), (6, 6)]


def test_the_note_says_what_was_actually_done(butane):
    symbols, coords, bonds = butane
    item = orca.scan(_carbons(symbols)[:2], 1.5, 2.5, 4)
    _frames, info = scan.scan_frames(symbols, coords, bonds, item)
    note = scan.preview_note(info)
    assert "5 points" in note and "1.5" in note and "2.5" in note
    assert "relaxed with" in note


def test_a_ring_coordinate_is_previewed_and_the_limit_is_stated():
    """`moving_group` refuses a coordinate whose ends are in one ring, since
    pulling them apart would have to break a second bond. The relaxation is
    what makes the ring follow, and that is worth saying rather than
    presenting a rigid step that did not happen."""
    pytest.importorskip("rdkit")
    symbols, coords, bonds = _molecule("C1CCCCC1")
    ring = [i for i, s in enumerate(symbols) if s == "C"][:2]
    item = orca.scan(ring, 1.5, 1.9, 4)
    frames, info = scan.scan_frames(symbols, coords, bonds, item)
    assert len(frames) == 5
    assert any("ring" in n for n in info["notes"])
    assert info["worst_error"] < 1e-6, "the bond still reaches its target"


def test_a_RING_DIHEDRAL_is_refused_rather_than_faked():
    """Found by driving the real dialog on cubane, which reported 180 degrees
    of drift and produced thirteen identical pictures.

    A blocked coordinate lets only `picks[2]` move, and for a DIHEDRAL that
    atom lies ON the j-k axis it would be turned about - so the value cannot
    change at all. A bond or an angle in the same ring is fine, because the
    one mover is off the axis in both, which is why this is decided by TRYING
    it rather than by a rule about rings.
    """
    pytest.importorskip("rdkit")
    symbols, coords, bonds = _molecule("C1CCCCC1")
    ring = [i for i, s in enumerate(symbols) if s == "C"][:4]
    with pytest.raises(scan.ScanError) as caught:
        scan.scan_frames(symbols, coords, bonds,
                         orca.scan(ring, -60.0, 60.0, 6))
    assert "ring" in str(caught.value)
    # ...while a bond and an angle over the same atoms still work
    for item in (orca.scan(ring[:2], 1.5, 1.8, 3),
                 orca.scan(ring[:3], 105.0, 115.0, 3)):
        _frames, info = scan.scan_frames(symbols, coords, bonds, item)
        assert info["worst_error"] < 1e-6


def test_a_scan_that_asks_for_nothing_is_not_refused():
    """start == end is a degenerate range, not a stuck coordinate."""
    pytest.importorskip("rdkit")
    symbols, coords, bonds = _molecule("CCCC")
    here = internal.current_value(
        internal.DISTANCE, coords, _carbons(symbols)[:2])
    item = orca.scan(_carbons(symbols)[:2], here, here, 2)
    frames, info = scan.scan_frames(symbols, coords, bonds, item)
    assert len(frames) == 3 and info["worst_error"] < 1e-6
