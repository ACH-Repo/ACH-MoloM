"""Round 27: ORCA normal modes -> playable frames.

Every test here runs against `tests/data/orca_freq_h3po4.out`, a VERBATIM
excerpt of a real ORCA 6 FREQ run on H3PO4 (8 atoms, 24 modes). Hand-written
fixtures were tried first and were a mistake: a made-up block only proves the
parser reads the format I imagined, and the whole job of this parser is to
read what ORCA actually emits — trailing spaces, the "Scaling factor" line
between the header and the data, six-column blocking and all.

The file also carries ORCA's own IR SPECTRUM block, which lists the mode
frequencies a second time. That gives an INDEPENDENT check: the frequencies
we pull out of VIBRATIONAL FREQUENCIES must agree with the ones ORCA printed
in the IR table.
"""

import os
import re

import numpy as np
import pytest

from molom.core import vibrations

_DATA = os.path.join(os.path.dirname(__file__), "data",
                     "orca_freq_h3po4.out")
N_ATOMS = 8              # P + 4 O + 3 H
N_MODES = 3 * N_ATOMS    # 24
N_TRIVIAL = 6            # translations + rotations of a non-linear molecule


@pytest.fixture(scope="module")
def text():
    if not os.path.exists(_DATA):
        pytest.skip("real ORCA fixture missing")
    with open(_DATA, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


@pytest.fixture(scope="module")
def modes(text):
    return vibrations.parse_orca_frequencies(text)


# --------------------------------------------------------------- parsing
def test_all_modes_are_read(modes):
    assert len(modes) == N_MODES
    assert modes[0].displacements.shape == (N_ATOMS, 3)


def test_the_atom_count_follows_from_the_mode_count(text):
    """3N modes means N atoms; the parser must not need telling."""
    parsed = vibrations.parse_orca_frequencies(text, n_atoms=N_ATOMS)
    assert len(parsed) == N_MODES


def test_translations_and_rotations_are_flagged(modes):
    assert sum(1 for m in modes if m.is_trivial) == N_TRIVIAL
    assert all(m.is_trivial for m in modes[:N_TRIVIAL])
    assert len(vibrations.describe(modes)) == N_MODES - N_TRIVIAL


def test_frequencies_match_orcas_own_ir_table(text, modes):
    """Independent cross-check: the IR SPECTRUM block lists the same mode
    frequencies, printed by ORCA from its own data."""
    ir = {}
    inside = False
    for line in text.splitlines():
        if "IR SPECTRUM" in line:
            inside = True
            continue
        if not inside:
            continue
        match = re.match(r"\s*(\d+):\s+(-?\d+\.\d+)", line)
        if match:
            ir[int(match.group(1))] = float(match.group(2))
    assert len(ir) >= 10, "the fixture must carry the IR table"
    for index, freq in ir.items():
        assert modes[index].wavenumber == pytest.approx(freq, abs=0.01)


def test_the_known_frequencies_of_this_molecule(modes):
    real = [m for m in modes if not m.is_trivial]
    assert real[0].wavenumber == pytest.approx(161.70)
    # Three O-H stretches at the top end, as H3PO4 must have.
    assert sum(1 for m in real if m.wavenumber > 3500) == 3


def test_no_imaginary_modes_in_a_converged_minimum(modes):
    assert not any(m.is_imaginary for m in modes)


def test_an_imaginary_mode_is_recognised(text):
    """A saddle point prints a negative wavenumber; that mode is the most
    interesting one in the file, so it must never be filtered out silently."""
    doctored = text.replace("161.70", "-161.70", 1)
    modes = vibrations.parse_orca_frequencies(doctored)
    imaginary = [m for m in modes if m.is_imaginary]
    assert len(imaginary) == 1
    assert not imaginary[0].is_trivial
    assert "imaginary" in imaginary[0].label()


def test_every_vibrational_mode_actually_moves_something(modes):
    for m in modes:
        if not m.is_trivial:
            assert m.max_displacement > 1e-3, m.label()


def test_a_wrong_atom_count_is_refused(text):
    with pytest.raises(vibrations.VibrationError):
        vibrations.parse_orca_frequencies(text, n_atoms=5)


def test_a_file_without_frequencies_is_refused():
    with pytest.raises(vibrations.VibrationError):
        vibrations.parse_orca_frequencies("SCF CONVERGED\nnothing here")


# ------------------------------------------------------------- animation
def _rest():
    return np.arange(N_ATOMS * 3, dtype=float).reshape(N_ATOMS, 3) * 0.3


def test_frames_start_at_rest_so_the_loop_joins(modes):
    frames = vibrations.mode_frames(_rest(), modes[6], n_frames=20)
    assert len(frames) == 20
    assert frames[0] == pytest.approx(_rest())


def test_amplitude_is_the_peak_displacement_in_angstrom(modes):
    """ORCA's vectors are normalised but not to any physical size, so the
    animation must be scaled by the biggest-moving atom or a stiff mode is
    invisible and a floppy one explodes."""
    frames = vibrations.mode_frames(_rest(), modes[6], amplitude=0.5,
                                    n_frames=40)
    swing = max(float(np.max(np.linalg.norm(f - _rest(), axis=1)))
                for f in frames)
    assert swing == pytest.approx(0.5, abs=0.02)


def test_every_mode_animates_to_the_same_visual_size(modes):
    """Whatever the frequency, each mode should read equally clearly."""
    for m in modes:
        if m.is_trivial:
            continue
        frames = vibrations.mode_frames(_rest(), m, amplitude=0.4,
                                        n_frames=16)
        swing = max(float(np.max(np.linalg.norm(f - _rest(), axis=1)))
                    for f in frames)
        assert swing == pytest.approx(0.4, abs=0.05), m.label()


def test_atoms_move_along_their_own_displacement_vector(modes):
    mode = modes[6]
    frames = vibrations.mode_frames(_rest(), mode, n_frames=40)
    peak = frames[10] - _rest()                    # sin = 1
    busiest = int(np.argmax(np.linalg.norm(mode.displacements, axis=1)))
    want = mode.displacements[busiest]
    want = want / np.linalg.norm(want)
    got = peak[busiest] / np.linalg.norm(peak[busiest])
    assert abs(float(want @ got)) == pytest.approx(1.0, abs=1e-6)


def test_a_mode_for_the_wrong_molecule_is_refused(modes):
    with pytest.raises(vibrations.VibrationError):
        vibrations.mode_frames(np.zeros((5, 3)), modes[6])


def test_a_genuinely_zero_eigenvector_produces_a_still():
    """Guards the divide-by-peak: a null vector must not become NaN."""
    dead = vibrations.Mode(0, 0.0, np.zeros((N_ATOMS, 3)))
    for frame in vibrations.mode_frames(_rest(), dead, n_frames=8):
        assert frame == pytest.approx(_rest())
        assert np.all(np.isfinite(frame))
