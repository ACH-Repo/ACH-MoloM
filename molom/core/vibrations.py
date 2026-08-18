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

import math
import re
from typing import List, Optional

import numpy as np

_FREQ_HEADER = "VIBRATIONAL FREQUENCIES"
_MODE_HEADER = "NORMAL MODES"
_FREQ_LINE = re.compile(r"^\s*(\d+):\s*(-?\d+\.\d+)\s*cm\*\*-1")
_TRIVIAL_CM = 1.0        # |v| below this is a translation/rotation

#: Units an engine can report a mode's brightness in. ORCA gives a real IR
#: intensity; MOPAC gives the transition dipole it comes from.
INTENSITY_KM_MOL = "km/mol"
INTENSITY_DEBYE = "D"


class VibrationError(ValueError):
    """Raised when a file carries no usable frequency data."""


class Mode(object):
    """One normal mode: a frequency and a displacement per atom."""

    def __init__(self, index, wavenumber, displacements, intensity=None,
                 intensity_unit=INTENSITY_KM_MOL, symmetry=None):
        self.index = int(index)
        self.wavenumber = float(wavenumber)       # cm^-1, negative = imaginary
        self.displacements = np.asarray(displacements,
                                        dtype=float).reshape(-1, 3)
        self.intensity = intensity
        #: WHAT `intensity` IS MEASURED IN, because two engines report two
        #: different quantities. ORCA gives an IR intensity in km/mol; MOPAC
        #: reports a TRANSITION DIPOLE, and the conversion between them is not
        #: something to invent - so the number is carried with its unit rather
        #: than silently displayed under the wrong one. Sorting is unaffected
        #: either way: intensity goes as the square of the transition dipole,
        #: and squaring is monotonic over non-negative values, so the ORDER a
        #: dipole gives is the order an intensity would give.
        self.intensity_unit = intensity_unit
        #: Mulliken symbol for the mode ("A1", "B2", "A'"), where the engine
        #: says. MOPAC prints it; ORCA does not, so this is usually None.
        self.symmetry = symmetry

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
    intensities = _parse_ir_intensities(lines)
    modes = []
    for k, freq in enumerate(freqs):
        if k >= vectors.shape[1]:
            break
        modes.append(Mode(k, freq, vectors[:, k].reshape(count, 3),
                          intensity=intensities.get(k)))
    return modes


#: Public, because the app has to tell an ORCA `.out` from a MOPAC one and
#: the extension cannot: both programs write `.out`.
MOPAC_FREQ_HEADER = "NORMAL COORDINATE ANALYSIS"
_MOPAC_CART_HEADER = MOPAC_FREQ_HEADER
_MOPAC_MASS_HEADER = "MASS-WEIGHTED COORDINATE ANALYSIS"
_MOPAC_ROOT = "Root No."


def parse_mopac_frequencies(text, n_atoms=None):
    # type: (str, Optional[int]) -> List[Mode]
    """Frequencies + normal modes from a MOPAC FORCE output.

    MoloM's whole vibrational UI - the mode cards, the baked animation on the
    scene clock, the IR sort, round 63's selection ranking - was built against
    ORCA and needs nothing but a list of `Mode`. So this is a reader and
    nothing else; not one line downstream changes.

    **The trap is which block to read.** MOPAC prints the eigenvectors TWICE,
    under `NORMAL COORDINATE ANALYSIS (Total motion = 1 Angstrom)` and then
    again under `MASS-WEIGHTED COORDINATE ANALYSIS`, and both are laid out
    identically with the same `Root No.` header. The second is in mass-weighted
    coordinates, so animating it would move every hydrogen far too little and
    every heavy atom far too much - a plausible-looking, wrong animation. Only
    the first is a Cartesian displacement, which is what `Mode.displacements`
    means, so the search stops at the mass-weighted header.

    Rows are 3N Cartesian components in atom order (x, y, z per atom), columns
    are modes, wrapped eight at a time. MOPAC lists only the 3N-6 genuine
    vibrations here - translations and rotations are already removed.
    """
    lines = str(text).splitlines()
    start = None
    for i, line in enumerate(lines):
        if _MOPAC_CART_HEADER in line:
            start = i                    # later blocks win, as with ORCA
    if start is None:
        raise VibrationError(
            "no NORMAL COORDINATE ANALYSIS block found - is this a MOPAC "
            "FORCE output?")
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if _MOPAC_MASS_HEADER in lines[i]:
            end = i
            break

    freqs, syms, columns = [], [], []
    i = start
    while i < end:
        if _MOPAC_ROOT not in lines[i]:
            i += 1
            continue
        roots = [int(t) for t in lines[i].split() if t.isdigit()]
        n = len(roots)
        i += 1
        # The frequency line is the first all-numeric line with one value per
        # root. Anything non-blank before it is the symmetry-label line, which
        # is identified by ELIMINATION rather than by position - it is absent
        # for some point groups, and a label can carry a prime or a quote
        # ("1 A'", '2 A"') that no numeric test would accept anyway.
        block_syms, block_freqs = None, None
        while i < end:
            parts = lines[i].split()
            if not parts:
                i += 1
                continue
            values = _floats(parts)
            if values is not None and len(values) == n:
                block_freqs = values
                i += 1
                break
            if block_syms is None:
                # "1 A1  1 B2  2 A1" -> one label per root, when it divides.
                block_syms = ([" ".join(parts[k:k + 2])
                               for k in range(0, len(parts), 2)]
                              if len(parts) == 2 * n else None)
            i += 1
        if block_freqs is None:
            break
        rows = []
        while i < end:
            parts = lines[i].split()
            if len(parts) == n + 1 and parts[0].isdigit():
                values = _floats(parts[1:])
                if values is None:
                    break
                rows.append(values)
                i += 1
                continue
            if not parts:
                i += 1
                if rows:
                    break
                continue
            break
        if not rows:
            break
        freqs.extend(block_freqs)
        syms.extend(block_syms or [None] * n)
        columns.append(np.array(rows, dtype=float))     # (3N, n)

    if not freqs:
        raise VibrationError("MOPAC frequency block found but no modes in it")
    vectors = np.hstack(columns)
    count = vectors.shape[0] // 3
    if n_atoms is not None and count != int(n_atoms):
        raise VibrationError(
            "the file has {} atoms but the structure has {}".format(
                count, n_atoms))
    dipoles = _parse_mopac_transition_dipoles(lines)
    modes = []
    for k, freq in enumerate(freqs):
        if k >= vectors.shape[1]:
            break
        modes.append(Mode(k, freq, vectors[:, k].reshape(count, 3),
                          intensity=dipoles.get(k),
                          intensity_unit=INTENSITY_DEBYE,
                          symmetry=_clean_symmetry(syms[k])))
    return modes


def _floats(tokens):
    """The tokens as floats, or None if any of them is not a number."""
    out = []
    for t in tokens:
        try:
            out.append(float(t))
        except ValueError:
            return None
    return out


def _clean_symmetry(raw):
    """'1 A1' -> 'A1'. The leading number is the mode's index WITHIN its
    irreducible representation, not the symbol, and the card wants the
    symbol."""
    if not raw:
        return None
    parts = str(raw).split()
    return parts[-1] if parts else None


_MOPAC_DIPOLE = re.compile(r"^\s*TRANSITION DIPOLE\s+(-?\d+\.\d+)")
_MOPAC_VIBRATION = re.compile(r"^\s*VIBRATION\s+(\d+)")


def _parse_mopac_transition_dipoles(lines):
    # type: (list) -> dict
    """Mode index -> transition dipole, from DESCRIPTION OF VIBRATIONS.

    Zero-based to match `Mode.index`, where MOPAC numbers from one. Absent for
    a job that did not print the block, and that is not an error: the modes are
    perfectly usable and anything sorting by intensity already copes with None
    (round 31).
    """
    out = {}
    current = None
    for line in lines:
        m = _MOPAC_VIBRATION.match(line)
        if m:
            current = int(m.group(1)) - 1
            continue
        if current is None:
            continue
        m = _MOPAC_DIPOLE.match(line)
        if m:
            out[current] = float(m.group(1))
            current = None
    return out


_IR_HEADER = "IR SPECTRUM"
_IR_LINE = re.compile(
    r"^\s*(\d+):\s+(-?\d+\.\d+)\s+(-?\d+\.\d+(?:[eE][-+]?\d+)?)"
    r"\s+(-?\d+\.\d+(?:[eE][-+]?\d+)?)")


def _parse_ir_intensities(lines):
    # type: (list) -> dict
    """Mode index -> IR intensity in km/mol, from ORCA's IR SPECTRUM table.

    Optional on purpose: a Raman-only or a plain Hessian job has no such
    block, and the modes are still perfectly usable — `Mode.intensity` is
    None and anything ranking by intensity has to cope. The table only lists
    the non-trivial modes, so the translations and rotations simply never
    appear as keys.

    The columns are `Mode: freq eps Int T**2 (TX TY TZ)`; the third number is
    the one spectroscopists mean by "intensity". Later blocks win, as
    everywhere else in this module.
    """
    out = {}
    for start, line in enumerate(lines):
        if _IR_HEADER not in line:
            continue
        found = {}
        for row in lines[start + 1:]:
            match = _IR_LINE.match(row)
            if match:
                found[int(match.group(1))] = float(match.group(4))
            elif found and row.strip() and not row.strip().startswith("-"):
                break
        if found:
            out = found
    return out


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


DEFAULT_PERIOD_FRAMES = 20      # a multiple of 4 — see period_frames()


def period_frames(n):
    # type: (float) -> int
    """Snap a requested frames-per-period to a multiple of four.

    A mode is sampled as `sin(2*pi*k/n)`, so the turning points of the
    oscillation sit at k = n/4 and k = 3n/4. Unless n divides by four those
    indices are not integers and **the extremes are never sampled** — with
    n = 6 the animation only ever reaches 0.87 of the amplitude, so the
    highest and lowest points of the chemical coordinate, which are exactly
    what you are looking at a mode to see, get cut off. Christian's point,
    2026-08-03: fine sampling hides it, but sampling should always include
    the extremes rather than nearly reach them.

    Rounding to the NEAREST multiple of four (not up) keeps the default of 20
    untouched and never silently doubles anyone's frame count. Half-way cases
    round up explicitly rather than through `round()`, whose banker's
    rounding would send 10 down to 8 but 14 up to 16.
    """
    return max(int(math.floor(float(n) / 4.0 + 0.5)), 1) * 4


def mode_frames(coords, mode, amplitude=0.6, n_frames=DEFAULT_PERIOD_FRAMES):
    # type: (np.ndarray, Mode, float, int) -> List[np.ndarray]
    """One full period of a mode as a list of coordinate frames.

    `amplitude` is the peak displacement in Angstrom of the atom that moves
    most, so the animation reads the same whether the eigenvector happened to
    be normalised or mass-weighted. A whole period (not half) means the loop
    joins seamlessly and the timeline can simply set the track to LOOP.

    `n_frames` is snapped by `period_frames` so both turning points are
    sampled exactly; the player's own smoothing then subdivides between these
    frames, which is why a fairly small count still looks continuous.
    """
    base = np.asarray(coords, dtype=float).reshape(-1, 3)
    vector = np.asarray(mode.displacements, dtype=float).reshape(-1, 3)
    if vector.shape != base.shape:
        raise VibrationError(
            "mode has {} atoms, structure has {}".format(len(vector),
                                                         len(base)))
    peak = float(np.max(np.linalg.norm(vector, axis=1)))
    scale = (float(amplitude) / peak) if peak > 1e-12 else 0.0
    count = period_frames(n_frames)
    frames = []
    for k in range(count):
        phase = 2.0 * np.pi * k / float(count)
        frames.append(base + vector * (scale * np.sin(phase)))
    return frames


def describe(modes, include_trivial=False):
    # type: (List[Mode], bool) -> List[str]
    return [m.label() for m in modes
            if include_trivial or not m.is_trivial]


# --------------------------------------------------------- picking a mode
SORT_FREQUENCY = "frequency"
SORT_INTENSITY = "intensity"
SORT_SELECTION = "selection"
SORT_KEYS = (SORT_FREQUENCY, SORT_INTENSITY, SORT_SELECTION)

#: Atomic masses, for the mass-weighted participation ratio. Only the elements
#: that turn up in ordinary FREQ jobs are worth listing; anything else falls
#: back to a middling value, which is harmless because the ratio NORMALISES —
#: a wrong mass shifts one atom's share slightly, it cannot break the measure.
_MASSES = {"H": 1.008, "D": 2.014, "C": 12.011, "N": 14.007, "O": 15.999,
           "F": 18.998, "P": 30.974, "S": 32.06, "Cl": 35.45, "Br": 79.904,
           "I": 126.90, "B": 10.81, "Si": 28.085, "Se": 78.97}
_DEFAULT_MASS = 30.0


def selection_weight(mode, indices, symbols=None, mass_weighted=True):
    # type: (Mode, Sequence[int], Optional[Sequence[str]], bool) -> float
    """How much of `mode`'s motion the SELECTED atoms carry, from 0 to 1.

    Christian's idea (2026-08-03): "allow the user to make a selection in the
    viewport of certain atoms whose vibrations they are interested in and
    calculate their offset during different modes, use that as a ranking
    parameter".

    It is a PARTICIPATION RATIO, not a raw displacement sum, and that is the
    whole design. A raw sum ranks every high-amplitude mode above a mode that
    is genuinely localised on the selection, which is the opposite of the
    question being asked — "which modes are about THESE atoms" is a question
    about the FRACTION of the motion they carry, so the sum over the selection
    is divided by the sum over everything.

    `mass_weighted` is on by default, and it matters: an eigenvector is the
    Cartesian displacement, so a C-H stretch is nearly all hydrogen motion by
    amplitude. Unweighted, every mode involving a hydrogen scores highly and
    selecting a heavy atom returns almost nothing. Weighting by mass measures
    the share of the kinetic ENERGY instead, which is what "this mode belongs
    to that part of the molecule" actually means.
    """
    vector = np.asarray(mode.displacements, dtype=float).reshape(-1, 3)
    n = len(vector)
    rows = sorted({int(i) for i in (indices or ()) if 0 <= int(i) < n})
    if not rows or n == 0:
        return 0.0
    share = np.sum(vector * vector, axis=1)          # |d_i|^2 per atom
    if mass_weighted:
        masses = np.full(n, _DEFAULT_MASS)
        for i, sym in enumerate(list(symbols or [])[:n]):
            masses[i] = _MASSES.get(str(sym).strip().capitalize(),
                                    _DEFAULT_MASS)
        share = share * masses
    total = float(share.sum())
    if total <= 0.0:
        return 0.0
    return float(share[rows].sum() / total)


def rank_by_selection(modes, indices, symbols=None, mass_weighted=True):
    # type: (List[Mode], Sequence[int], Optional[Sequence[str]], bool) -> List[tuple]
    """`[(mode, weight), ...]`, most-involved FIRST.

    Descending for the same reason intensity is: the question "which modes move
    these atoms" is answered from the top of the list, not the bottom.
    """
    scored = [(m, selection_weight(m, indices, symbols, mass_weighted))
              for m in modes]
    scored.sort(key=lambda pair: (-pair[1], pair[0].wavenumber))
    return scored


def sort_modes(modes, key=SORT_FREQUENCY, selection=None, symbols=None,
               mass_weighted=True):
    # type: (List[Mode], str, Optional[Sequence[int]], Optional[Sequence[str]], bool) -> List[Mode]
    """Order modes for the list.

    By frequency it is the spectrum, ascending — the order ORCA prints and
    the order you read a spectrum in. By intensity it is strongest FIRST,
    because the question that ordering answers is "which bands would I
    actually see", and that is a descending question. By SELECTION it is the
    modes that move the picked atoms most, first (`selection_weight`).

    Modes with no intensity (the translations and rotations, which ORCA
    leaves out of the IR table, and every mode of a job that produced no IR
    block at all) sort to the end rather than being dropped: the list must
    still show everything it was given.

    Sorting by selection with NOTHING selected falls back to frequency rather
    than returning an arbitrary order — there is no question to answer yet.
    """
    if key == SORT_SELECTION:
        if not selection:
            return sort_modes(modes, SORT_FREQUENCY)
        return [m for m, _w in rank_by_selection(modes, selection, symbols,
                                                 mass_weighted)]
    if key == SORT_INTENSITY:
        return sorted(modes,
                      key=lambda m: (m.intensity is None,
                                     -(m.intensity or 0.0), m.wavenumber))
    return sorted(modes, key=lambda m: (m.wavenumber, m.index))


def filter_modes(modes, low=None, high=None, include_trivial=False):
    # type: (List[Mode], Optional[float], Optional[float], bool) -> List[Mode]
    """Modes inside a wavenumber window. Either bound may be None.

    Bounds are inclusive and order-insensitive, so a half-typed range never
    empties the list in a way that looks like a crash — typing "1" while
    aiming for "1000" simply shows everything from 1 cm-1 up.
    """
    if low is not None and high is not None and low > high:
        low, high = high, low
    out = []
    for m in modes:
        if not include_trivial and m.is_trivial:
            continue
        if low is not None and m.wavenumber < float(low):
            continue
        if high is not None and m.wavenumber > float(high):
            continue
        out.append(m)
    return out
