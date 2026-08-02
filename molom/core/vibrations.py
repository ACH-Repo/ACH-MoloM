"""Vibrational normal modes from an ORCA FREQ output, as playable frames.

A normal mode is a displacement VECTOR per atom, not a set of coordinates.
Animating one is therefore just

    x(t) = x0 + A * sin(2*pi*t) * d

so the natural way to make it play is to bake a short trajectory and hand it
to the existing scene clock: interpolation, the multi-track pane and (later)
the animation export all work on it for free, with no special "vibration
mode" anywhere in the UI. A mode is a loop, so the frame list is generated
over one full period and the track is set to LOOP.

**Relationship to ORCA Workbench.** OWB's `core/orca_parser.py` already has
`parse_frequencies`, `parse_ir` and `parse_thermochemistry`, written against
real jobs — it does NOT read the eigenvectors, which is the only part added
here. The frequency regex and the "last block in the file wins" rule are kept
deliberately identical so the two stay diffable (same policy as `io.py`); if
the frequency parsing ever needs fixing, fix it in both.

Validated against a real ORCA 6 FREQ run (H3PO4), vendored verbatim at
`tests/data/orca_freq_h3po4.out` — including its IR SPECTRUM block, which
lists the same frequencies again and so cross-checks the parse.

ORCA writes two blocks we need. `VIBRATIONAL FREQUENCIES` gives one line per
mode ("   6:       123.45 cm**-1"), and `NORMAL MODES` gives the eigenvectors
as a column-block matrix — 3N rows by 3N columns, printed six columns at a
time, which is the fiddly part. ORCA states in that block that the vectors
are already the CARTESIAN displacements (mass-weighting divided out), so they
can be used as displacements directly; they are normalised but not
orthogonal, and not to any physical amplitude — hence `mode_frames` scaling
by the biggest-moving atom. The first six modes of a non-linear molecule
are the translations and rotations and come out at ~0 cm-1; they are kept but
flagged, since seeing them is occasionally how you spot a bad optimisation.
"""

import re
from typing import List, Optional

import numpy as np

_FREQ_HEADER = "VIBRATIONAL FREQUENCIES"
_MODE_HEADER = "NORMAL MODES"
_FREQ_LINE = re.compile(r"^\s*(\d+):\s*(-?\d+\.\d+)\s*cm\*\*-1")
_TRIVIAL_CM = 1.0        # |v| below this is a translation/rotation


class VibrationError(ValueError):
    """Raised when a file carries no usable frequency data."""


class Mode(object):
    """One normal mode: a frequency and a displacement per atom."""

    def __init__(self, index, wavenumber, displacements, intensity=None):
        self.index = int(index)
        self.wavenumber = float(wavenumber)       # cm^-1, negative = imaginary
        self.displacements = np.asarray(displacements,
                                        dtype=float).reshape(-1, 3)
        self.intensity = intensity

    def __repr__(self):
        return "Mode({}, {:.2f} cm-1)".format(self.index, self.wavenumber)

    @property
    def is_trivial(self):
        """Translation or rotation — near-zero frequency, not a vibration."""
        return abs(self.wavenumber) < _TRIVIAL_CM

    @property
    def is_imaginary(self):
        """A negative wavenumber: a saddle point, not a minimum. Worth
        seeing — it is the mode that walks toward the transition state."""
        return self.wavenumber < -_TRIVIAL_CM

    @property
    def max_displacement(self):
        if self.displacements.size == 0:
            return 0.0
        return float(np.max(np.linalg.norm(self.displacements, axis=1)))

    def label(self):
        tag = ""
        if self.is_imaginary:
            tag = "  (imaginary)"
        elif self.is_trivial:
            tag = "  (translation / rotation)"
        return "{:>4}: {:9.2f} cm-1{}".format(self.index, self.wavenumber, tag)


def parse_orca_frequencies(text, n_atoms=None):
    # type: (str, Optional[int]) -> List[Mode]
    """Frequencies + normal modes from an ORCA output file.

    Later blocks win: a job that re-runs the Hessian writes the block twice,
    and the last one is the answer.
    """
    lines = str(text).splitlines()
    freqs = _parse_frequencies(lines)
    if not freqs:
        raise VibrationError(
            "no VIBRATIONAL FREQUENCIES block found — is this an ORCA FREQ "
            "output?")
    vectors = _parse_normal_modes(lines, len(freqs))
    if vectors is None:
        raise VibrationError("frequencies found but no NORMAL MODES block")
    count = vectors.shape[0] // 3
    if n_atoms is not None and count != int(n_atoms):
        raise VibrationError(
            "the file has {} atoms but the structure has {}".format(
                count, n_atoms))
    modes = []
    for k, freq in enumerate(freqs):
        if k >= vectors.shape[1]:
            break
        modes.append(Mode(k, freq, vectors[:, k].reshape(count, 3)))
    return modes


_GEOM_HEADER = "CARTESIAN COORDINATES (ANGSTROEM)"
_GEOM_LINE = re.compile(
    r"^\s*([A-Za-z]{1,2})\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s*$")


def parse_orca_geometry(text):
    # type: (str) -> List[tuple]
    """The optimised geometry the FREQ job was run on, as (sym, x, y, z).

    A FREQ output carries its own structure, so loading modes never has to
    depend on the user already having the right molecule open with the atoms
    in the right ORDER — which is a promise no workflow can keep. Later
    blocks win, as everywhere else here.
    """
    lines = str(text).splitlines()
    out = []
    for start, line in enumerate(lines):
        if _GEOM_HEADER not in line:
            continue
        found = []
        for row in lines[start + 1:]:
            match = _GEOM_LINE.match(row)
            if match:
                found.append((match.group(1),
                              float(match.group(2)), float(match.group(3)),
                              float(match.group(4))))
            elif found:
                break
        if found:
            out = found
    return out


def _parse_frequencies(lines):
    # type: (list) -> List[float]
    out = []
    for start, line in enumerate(lines):
        if _FREQ_HEADER not in line:
            continue
        found = []
        for row in lines[start + 1:]:
            match = _FREQ_LINE.match(row)
            if match:
                found.append(float(match.group(2)))
            elif found and row.strip() and not row.strip().startswith("-"):
                break
        if found:
            out = found          # keep the LAST block in the file
    return out


def _parse_normal_modes(lines, n_modes):
    # type: (list, int) -> Optional[np.ndarray]
    """The 3N x 3N eigenvector matrix, printed six columns at a time."""
    start = None
    for index, line in enumerate(lines):
        if _MODE_HEADER in line:
            start = index
    if start is None:
        return None
    size = int(n_modes)
    matrix = np.zeros((size, size))
    columns = []
    seen_any = False
    for row in lines[start + 1:]:
        stripped = row.strip()
        if not stripped:
            continue
        parts = stripped.split()
        # A header row is a list of bare column indices.
        if all(p.lstrip("-").isdigit() for p in parts) and len(parts) <= 6:
            columns = [int(p) for p in parts]
            seen_any = True
            continue
        if not columns:
            continue
        try:
            row_index = int(parts[0])
            values = [float(v) for v in parts[1:]]
        except (ValueError, IndexError):
            if seen_any and columns:
                break            # past the end of the block
            continue
        if row_index >= size:
            continue
        for offset, value in enumerate(values):
            if offset < len(columns) and columns[offset] < size:
                matrix[row_index, columns[offset]] = value
        if row_index == size - 1 and columns and columns[-1] == size - 1:
            break
    return matrix if seen_any else None


def mode_frames(coords, mode, amplitude=0.6, n_frames=20):
    # type: (np.ndarray, Mode, float, int) -> List[np.ndarray]
    """One full period of a mode as a list of coordinate frames.

    `amplitude` is the peak displacement in Angstrom of the atom that moves
    most, so the animation reads the same whether the eigenvector happened to
    be normalised or mass-weighted. A whole period (not half) means the loop
    joins seamlessly and the timeline can simply set the track to LOOP.
    """
    base = np.asarray(coords, dtype=float).reshape(-1, 3)
    vector = np.asarray(mode.displacements, dtype=float).reshape(-1, 3)
    if vector.shape != base.shape:
        raise VibrationError(
            "mode has {} atoms, structure has {}".format(len(vector),
                                                         len(base)))
    peak = float(np.max(np.linalg.norm(vector, axis=1)))
    scale = (float(amplitude) / peak) if peak > 1e-12 else 0.0
    frames = []
    for k in range(int(max(n_frames, 2))):
        phase = 2.0 * np.pi * k / float(n_frames)
        frames.append(base + vector * (scale * np.sin(phase)))
    return frames


def describe(modes, include_trivial=False):
    # type: (List[Mode], bool) -> List[str]
    return [m.label() for m in modes
            if include_trivial or not m.is_trivial]
