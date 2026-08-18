"""Round 74: MOPAC FORCE feeds MoloM's existing vibrations page.

Christian, after asking what else MOPAC does: "do the vibrations reader".

The point of this round is how little there is of it. Rounds 27-31 and 63 built
the whole vibrational UI - mode cards, the mode baked onto the scene clock,
sort by frequency or IR intensity, the mass-weighted selection ranking - and it
was reachable only if you had an ORCA output. All that was missing was a
reader, because everything downstream consumes `vibrations.Mode` and nothing
else. So `parse_mopac_frequencies` is a new function next to
`parse_orca_frequencies` and not one line of the page changed.

Both fixtures are verbatim from MOPAC v23.2.5 on this machine (round 27's
rule). The methanol one is the interesting one: 12 modes, so the eigenvector
matrix WRAPS into two column blocks; a genuine imaginary mode; and A' / A"
symmetry labels, whose prime and quote characters defeat any numeric test.
"""

import os

import numpy as np
import pytest

from molom.core import vibrations as V

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
WATER = os.path.join(DATA, "mopac_pm7_water_force.out")
METHANOL = os.path.join(DATA, "mopac_pm7_methanol_force.out")


def _text(path):
    return open(path, encoding="utf-8", errors="replace").read()


# ------------------------------------------------------------ the basics
def test_water_gives_its_three_vibrations():
    """3N-6 = 3. MOPAC prints only the genuine vibrations in this block -
    translations and rotations are already projected out, unlike ORCA, where
    the first six come back at ~0 cm-1."""
    modes = V.parse_mopac_frequencies(_text(WATER), n_atoms=3)
    assert len(modes) == 3
    assert all(m.displacements.shape == (3, 3) for m in modes)
    assert not any(m.is_trivial for m in modes)


def test_the_frequencies_are_waters_frequencies():
    """A bend well below two stretches - the shape of water's spectrum. (The
    absolute values are PM7's: it puts the OH stretches near 2800 where
    experiment says 3700. That is the method, not the reader.)"""
    modes = V.parse_mopac_frequencies(_text(WATER), n_atoms=3)
    freqs = sorted(m.wavenumber for m in modes)
    assert 1300 < freqs[0] < 1500
    assert 2700 < freqs[1] < 3000 and 2700 < freqs[2] < 3000
    assert freqs[1] - freqs[0] > 1000


def test_the_symmetry_labels_come_through():
    """MOPAC names each mode's irreducible representation; ORCA does not. Water
    is C2v, so its three modes are A1, B2, A1."""
    modes = V.parse_mopac_frequencies(_text(WATER), n_atoms=3)
    assert [m.symmetry for m in modes] == ["A1", "B2", "A1"]


def test_the_symbol_is_stripped_of_its_ordinal():
    """MOPAC writes '2 A1' - the 2 counts modes within that representation and
    is not part of the symbol."""
    modes = V.parse_mopac_frequencies(_text(WATER), n_atoms=3)
    for m in modes:
        assert not m.symmetry[0].isdigit(), m.symmetry


def test_the_transition_dipole_is_read_and_LABELLED_as_one():
    """MOPAC reports a transition dipole, ORCA an IR intensity in km/mol. The
    conversion is not something to invent, so the number carries its unit
    rather than being displayed under the wrong one."""
    modes = V.parse_mopac_frequencies(_text(WATER), n_atoms=3)
    assert all(m.intensity is not None for m in modes)
    assert all(m.intensity_unit == V.INTENSITY_DEBYE for m in modes)
    assert all(m.intensity > 0.0 for m in modes)


def test_an_ORCA_job_still_says_km_per_mol():
    """The default must not have moved under the existing path."""
    orca = os.path.join(DATA, "orca_freq_h3po4.out")
    modes = V.parse_orca_frequencies(_text(orca))
    assert modes[0].intensity_unit == V.INTENSITY_KM_MOL
    assert modes[0].symmetry is None


# ------------------------------------------ the wrapped, imaginary-mode case
def test_methanol_gives_all_twelve_modes_across_TWO_column_blocks():
    """3N-6 = 12 and MOPAC prints eight columns at a time, so a reader that
    handled only the first block would return 8 and look entirely plausible."""
    modes = V.parse_mopac_frequencies(_text(METHANOL), n_atoms=6)
    assert len(modes) == 12
    assert all(m.displacements.shape == (6, 3) for m in modes)


def test_the_imaginary_mode_survives():
    """A negative wavenumber is a saddle point, and it is often the most
    interesting line in the output - it must not be dropped or made positive."""
    modes = V.parse_mopac_frequencies(_text(METHANOL), n_atoms=6)
    imaginary = [m for m in modes if m.is_imaginary]
    assert len(imaginary) == 1
    assert imaginary[0].wavenumber < -100.0


def test_labels_with_primes_and_quotes_are_read():
    """Cs gives A' and A". Any 'is this token numeric' test fails on them."""
    modes = V.parse_mopac_frequencies(_text(METHANOL), n_atoms=6)
    syms = {m.symmetry for m in modes}
    assert syms <= {"A'", 'A"'}, syms
    assert len(syms) == 2


def test_the_modes_are_in_the_order_the_file_lists_them():
    modes = V.parse_mopac_frequencies(_text(METHANOL), n_atoms=6)
    assert [m.index for m in modes] == list(range(12))
    rest = [m.wavenumber for m in modes[1:]]
    assert rest == sorted(rest), "frequencies should ascend after the first"


# -------------------------------------------------- the block that is a TRAP
def test_the_CARTESIAN_block_is_read_and_not_the_MASS_WEIGHTED_one():
    """MOPAC prints the eigenvectors twice, identically laid out, under
    NORMAL COORDINATE ANALYSIS and then MASS-WEIGHTED COORDINATE ANALYSIS.
    Mass-weighted vectors would animate every hydrogen far too little and every
    heavy atom far too much - a wrong animation that looks fine.

    Water tells the two apart cleanly: in Cartesian displacements the hydrogens
    move much further than the oxygen, and mass weighting is exactly what
    removes that.
    """
    modes = V.parse_mopac_frequencies(_text(WATER), n_atoms=3)
    for m in modes:
        magnitudes = np.linalg.norm(m.displacements, axis=1)
        assert magnitudes[1] > magnitudes[0] * 3.0, (
            "the oxygen is moving as much as the hydrogens - this looks like "
            "the mass-weighted block")


def test_a_file_with_no_frequency_block_is_refused_clearly():
    plain = os.path.join(DATA, "mopac_pm7_water.out")     # a geometry job
    with pytest.raises(V.VibrationError) as excinfo:
        V.parse_mopac_frequencies(_text(plain))
    assert "FORCE" in str(excinfo.value)


def test_the_atom_count_is_checked():
    with pytest.raises(V.VibrationError):
        V.parse_mopac_frequencies(_text(WATER), n_atoms=99)


# ------------------------------------------- it drives the existing machinery
def test_the_modes_bake_onto_the_scene_clock_unchanged():
    """The whole point: `mode_frames` was written for ORCA and needs to know
    nothing about where these came from."""
    modes = V.parse_mopac_frequencies(_text(WATER), n_atoms=3)
    rest = np.zeros((3, 3))
    frames = V.mode_frames(rest, modes[0], amplitude=0.2,
                           n_frames=16)
    assert len(frames) == 16
    assert all(f.shape == (3, 3) for f in frames)
    # `amplitude` is the peak displacement of the atom that moves MOST,
    # measured as a vector norm - not as a single component, which is
    # smaller for any atom travelling diagonally.
    span = max(float(np.max(np.linalg.norm(f - rest, axis=1)))
               for f in frames)
    assert span == pytest.approx(0.2, abs=1e-6)


def test_the_selection_ranking_works_on_them():
    """Round 63's participation ratio, on a MOPAC mode. Water's stretches are
    hydrogen motion, so the two H must carry most of the unweighted share."""
    modes = V.parse_mopac_frequencies(_text(WATER), n_atoms=3)
    stretch = max(modes, key=lambda m: m.wavenumber)
    share = V.selection_weight(stretch, [1, 2], ["O", "H", "H"], False)
    assert share > 0.8, share


# ------------------------------------------------------- opening such a file
def test_opening_a_MOPAC_out_attaches_its_modes():
    """Round 30's discoverability fix, extended: opening a FREQ output must
    pick the modes up, and the EXTENSION cannot say which program wrote it -
    ORCA and MOPAC both write `.out`, so the header decides."""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from molom.ui.app import MainWindow
    QApplication.instance() or QApplication([])
    win = MainWindow()
    from molom.core.structure import Structure
    obj = win.scene.add(Structure(["O", "H", "H"],
                                  [np.array([[0., 0., 0.], [0.96, 0., 0.],
                                             [-0.24, 0.93, 0.]])]),
                        name="water")
    note = win._attach_frequencies(obj, WATER)
    assert note and "normal modes" in note
    assert len(win._modes[obj.id]) == 3
