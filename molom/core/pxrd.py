"""Simulated powder X-ray diffraction from a crystal MoloM already has open.

The one piece of physics that needs no new file format: the cell, the symmetry
operators, the asymmetric unit and the site occupancies are all in
`Structure.metadata` already, and a structure factor is a closed-form sum over
them. For a framework group it is also the measurement people actually take.

UI-free and offline, like everything in `core/`. The plot window is a separate
concern and this module knows nothing about it.

**Where the settings live, and why it is not here.** MoloM shows several
crystals in one scene, so a pattern is per-STRUCTURE: wavelength, step, peak
width and range belong in that structure's `metadata`, beside `polyhedra` and
`show_cell`, which is what makes them ride undo and the savefile for free.
This module takes them as arguments and stores nothing.

**Q or 2-theta is a real choice, not a display preference.** `two_theta`
depends on the wavelength; `q = 4 pi sin(theta) / lambda` does not. So two
structures simulated at different wavelengths CANNOT honestly share a 2-theta
axis - the same reflection would sit at two angles for no physical reason -
while they can always share a Q axis. `common_axis` is what a caller should
ask before drawing several patterns together.

**The formula**, and the part that is easy to get wrong is the scattering
factor: the vendored coefficients give the DIFFERENCE from Z, not a
Cromer-Mann sum (see `core/scattering.py`).

    s      = sin(theta) / lambda
    f_j(s) = Z_j - 41.78214 * s^2 * sum_i a_i exp(-b_i s^2)
    F(hkl) = sum_j f_j * occ_j * exp(2 pi i (h x_j + k y_j + l z_j)) * exp(-B_j s^2)
    LP     = (1 + cos^2 2theta) / (sin^2 theta * cos theta)
    I(hkl) = |F|^2 * LP

Systematic absences need no special-casing: they fall out of `|F|^2` being
zero. Multiplicity needs none either - every `hkl` in the sphere is
enumerated and reflections landing at the same angle are merged, which
accumulates it. That is also what makes this checkable against an independent
implementation, and the tests do exactly that.

**Debye-Waller is only applied when the file carried a displacement
parameter.** A pattern computed at B = 0 has visibly wrong high-angle
intensities, so `Pattern.note` says when that is what happened rather than
letting a plausible-looking curve stand unqualified.
"""

import math
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from . import scattering
from .elements import atomic_number

#: Common laboratory sources, in Angstrom. The default is Cu K-alpha1 because
#: it is what a lab diffractometer produces unless somebody says otherwise.
WAVELENGTHS = {
    "Cu Ka1": 1.540598,
    "Cu Ka": 1.541874,          # K-alpha1/K-alpha2 weighted average
    "Mo Ka1": 0.709300,
    "Co Ka1": 1.788965,
    "Cr Ka1": 2.289700,
    "Fe Ka1": 1.936042,
    "Ag Ka1": 0.559422,
}
DEFAULT_WAVELENGTH = WAVELENGTHS["Cu Ka1"]

#: Axis units. Q is the one that survives a wavelength difference.
AXIS_TWO_THETA = "two_theta"
AXIS_Q = "q"

#: Reflections closer together than this in 2-theta are one peak. Chosen well
#: below any real instrumental width, so merging can only ever combine
#: reflections that are genuinely coincident (the symmetry-equivalent set).
MERGE_TOL_DEG = 1e-5

#: Below this fraction of the strongest peak a reflection is dropped from the
#: returned list. A full sphere for a large cell is tens of thousands of
#: reflections, almost all of them numerically zero.
MIN_RELATIVE = 1e-6

DEFAULT_TWO_THETA = (5.0, 90.0)
DEFAULT_FWHM = 0.10             # degrees 2-theta
DEFAULT_STEP = 0.01             # degrees 2-theta

SHAPE_GAUSSIAN = "gaussian"
SHAPE_LORENTZIAN = "lorentzian"
SHAPE_PSEUDO_VOIGT = "pseudo_voigt"
SHAPES = (SHAPE_GAUSSIAN, SHAPE_LORENTZIAN, SHAPE_PSEUDO_VOIGT)


class Reflection(object):
    """One merged reflection: where it is, how strong, and what it is called."""

    __slots__ = ("h", "k", "l", "d", "two_theta", "q", "intensity",
                 "multiplicity", "equivalents")

    def __init__(self, hkl, d, two_theta, q, intensity, equivalents=None):
        self.h, self.k, self.l = (int(v) for v in hkl)
        self.d = float(d)
        self.two_theta = float(two_theta)
        self.q = float(q)
        self.intensity = float(intensity)
        #: Every `hkl` that landed at this angle. Its length is the
        #: multiplicity, and it is what a hover readout should show - "(1 1 1)
        #: and 7 more" is the honest label for a cubic reflection.
        self.equivalents = [tuple(int(v) for v in e)
                            for e in (equivalents or [tuple(hkl)])]
        self.multiplicity = len(self.equivalents)

    @property
    def hkl(self):
        return (self.h, self.k, self.l)

    def label(self):
        # type: () -> str
        return "({} {} {})".format(self.h, self.k, self.l)

    def __repr__(self):
        return "<Reflection {} 2th={:.3f} I={:.1f} x{}>".format(
            self.label(), self.two_theta, self.intensity, self.multiplicity)


class Pattern(object):
    """A simulated diffractogram plus what it was computed from."""

    __slots__ = ("reflections", "wavelength", "two_theta_range", "note",
                 "name")

    def __init__(self, reflections, wavelength, two_theta_range, note="",
                 name=""):
        self.reflections = list(reflections)
        self.wavelength = float(wavelength)
        self.two_theta_range = tuple(float(v) for v in two_theta_range)
        #: Anything the caller should say out loud - above all that no
        #: displacement parameters were available.
        self.note = str(note or "")
        self.name = str(name or "")

    def __len__(self):
        return len(self.reflections)

    def strongest(self):
        # type: () -> float
        return max((r.intensity for r in self.reflections), default=0.0)

    def x(self, axis=AXIS_TWO_THETA):
        return np.array([r.two_theta if axis == AXIS_TWO_THETA else r.q
                         for r in self.reflections], dtype=float)

    def y(self):
        return np.array([r.intensity for r in self.reflections], dtype=float)


# ------------------------------------------------------------ axis conversion
def q_from_two_theta(two_theta_deg, wavelength):
    """Q = 4 pi sin(theta) / lambda, in inverse Angstrom."""
    theta = np.radians(np.asarray(two_theta_deg, dtype=float)) / 2.0
    return 4.0 * math.pi * np.sin(theta) / float(wavelength)


def two_theta_from_q(q, wavelength):
    """The inverse. Values beyond the Ewald limit come back as NaN rather
    than raising - a caller plotting a shared Q axis will legitimately ask
    about angles a longer wavelength cannot reach."""
    arg = np.asarray(q, dtype=float) * float(wavelength) / (4.0 * math.pi)
    arg = np.where(np.abs(arg) <= 1.0, arg, np.nan)
    return np.degrees(2.0 * np.arcsin(arg))


def common_axis(wavelengths, tol=1e-9):
    # type: (Sequence[float], float) -> str
    """Which axis several patterns can HONESTLY share.

    2-theta only when they were all computed at the same wavelength; Q
    otherwise. Not a preference - plotting two wavelengths on one 2-theta axis
    puts the same reflection at two angles for no physical reason.
    """
    values = [float(w) for w in wavelengths if w]
    if not values:
        return AXIS_TWO_THETA
    return (AXIS_TWO_THETA
            if max(values) - min(values) <= tol else AXIS_Q)


# ------------------------------------------------------- scattering factors
def form_factor(symbol, s2):
    """f(s) for one element at s^2 = (sin(theta)/lambda)^2.

    Falls back to the bare atomic number for anything the table does not
    cover, which is the high-angle limit rather than a guess - and is flagged
    by `missing_species` so a caller can say so.
    """
    z = atomic_number(symbol)
    params = scattering.PARAMS.get(_table_symbol(symbol))
    if not params:
        return float(z) * np.ones_like(np.asarray(s2, dtype=float))
    s2 = np.asarray(s2, dtype=float)
    total = np.zeros_like(s2)
    for a, b in params:
        total = total + a * np.exp(-b * s2)
    return float(z) - scattering.PREFACTOR * s2 * total


def _table_symbol(symbol):
    text = str(symbol or "").strip()
    return text[:1].upper() + text[1:2].lower() if text else ""


def missing_species(symbols):
    # type: (Sequence[str]) -> List[str]
    """Species with no tabulated form factor, in first-seen order."""
    out, seen = [], set()
    for sym in symbols:
        key = _table_symbol(sym)
        if key and key not in seen and key not in scattering.PARAMS:
            seen.add(key)
            out.append(key)
    return out


# --------------------------------------------------------------- the pattern
def _hkl_range(cell, d_min):
    """How far along each reciprocal axis a sphere of radius 1/d_min reaches.

    Derived from the RECIPROCAL cell lengths, not the direct ones: `h` is
    bounded by `|a*| h <= 1/d_min`. Using the direct lengths gets a skewed
    cell wrong in exactly the way round 44's minimum-image guard was wrong.
    """
    matrix = np.asarray(cell.matrix(), dtype=float)
    recip = np.linalg.inv(matrix).T          # rows are a*, b*, c*
    lengths = np.linalg.norm(recip, axis=1)
    limit = 1.0 / float(d_min)
    return [max(1, int(math.floor(limit / max(v, 1e-12)))) for v in lengths]


def compute(cell, symbols, frac, occupancy=None, wavelength=DEFAULT_WAVELENGTH,
            two_theta_range=DEFAULT_TWO_THETA, debye_waller=None, name=""):
    """The pattern for one crystal. `frac` is the FULL cell contents.

    Not the asymmetric unit: the sum runs over every atom in the cell, which
    is what `cif.expand` already produces and what makes the arithmetic the
    textbook one rather than a symmetry-aware special case.
    """
    frac = np.asarray(frac, dtype=float)
    if frac.ndim != 2 or frac.shape[0] == 0:
        return Pattern([], wavelength, two_theta_range, "no atoms", name)
    symbols = list(symbols)
    occ = (np.ones(len(symbols)) if occupancy is None
           else np.asarray(occupancy, dtype=float))
    dw = (np.zeros(len(symbols)) if debye_waller is None
          else np.asarray(debye_waller, dtype=float))

    lo, hi = (float(two_theta_range[0]), float(two_theta_range[1]))
    lo = max(lo, 1e-3)
    hi = min(hi, 179.9)
    lam = float(wavelength)
    # The smallest d the wavelength can reach at the top of the range.
    d_min = lam / (2.0 * math.sin(math.radians(hi) / 2.0))
    d_max = lam / (2.0 * math.sin(math.radians(lo) / 2.0))

    matrix = np.asarray(cell.matrix(), dtype=float)
    recip = np.linalg.inv(matrix).T
    hmax, kmax, lmax = _hkl_range(cell, d_min)

    zs = np.array([atomic_number(s) for s in symbols], dtype=float)
    params = [scattering.PARAMS.get(_table_symbol(s)) for s in symbols]

    merged = {}          # rounded 2-theta -> [intensity, d, [hkl, ...]]
    for h in range(-hmax, hmax + 1):
        for k in range(-kmax, kmax + 1):
            for l in range(-lmax, lmax + 1):
                if h == 0 and k == 0 and l == 0:
                    continue
                g = h * recip[0] + k * recip[1] + l * recip[2]
                g_len = float(np.linalg.norm(g))
                if g_len <= 0.0:
                    continue
                d = 1.0 / g_len
                if d < d_min or d > d_max:
                    continue
                s = g_len / 2.0                     # sin(theta)/lambda
                arg = s * lam
                if abs(arg) > 1.0:
                    continue
                theta = math.asin(arg)
                two_theta = math.degrees(2.0 * theta)
                if not (lo <= two_theta <= hi):
                    continue
                s2 = s * s
                # f(s) per ATOM, with the difference-from-Z parameterisation.
                f = np.empty(len(symbols))
                for i, p in enumerate(params):
                    if p:
                        total = 0.0
                        for a, b in p:
                            total += a * math.exp(-b * s2)
                        f[i] = zs[i] - scattering.PREFACTOR * s2 * total
                    else:
                        f[i] = zs[i]
                phase = 2.0 * math.pi * (frac @ np.array([h, k, l], dtype=float))
                amp = f * occ * np.exp(-dw * s2)
                f_hkl = complex(np.sum(amp * np.cos(phase)),
                                np.sum(amp * np.sin(phase)))
                i_hkl = (f_hkl * f_hkl.conjugate()).real
                if i_hkl <= 0.0:
                    continue
                lorentz = ((1.0 + math.cos(2.0 * theta) ** 2)
                           / (math.sin(theta) ** 2 * math.cos(theta)))
                key = round(two_theta / MERGE_TOL_DEG)
                entry = merged.get(key)
                if entry is None:
                    merged[key] = [i_hkl * lorentz, d, two_theta, [(h, k, l)]]
                else:
                    entry[0] += i_hkl * lorentz
                    entry[3].append((h, k, l))

    # Built BEFORE the early return: a species with no tabulated form factor
    # is worth saying whether or not the pattern came out empty - and an
    # all-`Xx` structure scatters nothing, so the empty case is exactly where
    # the warning explains the emptiness.
    absent = missing_species(symbols)
    factor_note = ("no tabulated scattering factor for {} (used Z)".format(
        ", ".join(absent)) if absent else "")
    if not merged:
        return Pattern([], lam, (lo, hi),
                       "; ".join(x for x in ("no reflections in range",
                                             factor_note) if x), name)
    peak = max(v[0] for v in merged.values()) or 1.0
    reflections = []
    for intensity, d, two_theta, hkls in merged.values():
        if intensity / peak < MIN_RELATIVE:
            continue
        reflections.append(Reflection(_representative(hkls), d, two_theta,
                                      q_from_two_theta(two_theta, lam),
                                      intensity, equivalents=hkls))
    reflections.sort(key=lambda r: r.two_theta)
    notes = []
    if debye_waller is None or not np.any(dw):
        notes.append("no displacement parameters in the file, so B = 0 - "
                     "high-angle intensities are overestimated")
    if factor_note:
        notes.append(factor_note)
    return Pattern(reflections, lam, (lo, hi), "; ".join(notes), name)


def _representative(hkls):
    """The hkl a merged peak is NAMED by: the one a crystallographer would
    write, i.e. all-positive first, then lexicographically largest."""
    return max(hkls, key=lambda t: (sum(1 for v in t if v >= 0), t))


# ---------------------------------------------------------------- the profile
def profile(pattern, axis=AXIS_TWO_THETA, fwhm=DEFAULT_FWHM,
            step=DEFAULT_STEP, shape=SHAPE_PSEUDO_VOIGT, eta=0.5,
            x_range=None, normalise=True):
    """The continuous curve: `(x, y)` sampled on `step`.

    `fwhm` and `step` are always in the units of `axis`, so switching a shared
    plot from 2-theta to Q does not silently reinterpret a width as a
    different physical quantity. A caller that wants to keep an angular width
    across a unit switch has to convert it, and should - the two are not the
    same number.

    Pseudo-Voigt by default because a real diffractometer peak is neither a
    Gaussian nor a Lorentzian, and `eta` is the one knob that spans them.
    """
    if x_range is None:
        if axis == AXIS_Q:
            lo = float(q_from_two_theta(pattern.two_theta_range[0],
                                        pattern.wavelength))
            hi = float(q_from_two_theta(pattern.two_theta_range[1],
                                        pattern.wavelength))
        else:
            lo, hi = pattern.two_theta_range
    else:
        lo, hi = (float(x_range[0]), float(x_range[1]))
    step = abs(float(step)) or DEFAULT_STEP
    n = max(2, int(round((hi - lo) / step)) + 1)
    x = np.linspace(lo, hi, n)
    y = np.zeros_like(x)
    if not pattern.reflections:
        return x, y
    centres = pattern.x(axis)
    heights = pattern.y()
    w = abs(float(fwhm)) or DEFAULT_FWHM
    # Cheap and correct: a peak contributes nothing measurable beyond a few
    # widths, and evaluating every reflection over the whole grid is what
    # makes a naive implementation unusable on a big cell.
    reach = w * 12.0
    sigma = w / (2.0 * math.sqrt(2.0 * math.log(2.0)))
    half = w / 2.0
    for centre, height in zip(centres, heights):
        if centre < lo - reach or centre > hi + reach:
            continue
        i0 = max(0, int((centre - reach - lo) / step))
        i1 = min(n, int((centre + reach - lo) / step) + 2)
        if i1 <= i0:
            continue
        dx = x[i0:i1] - centre
        if shape == SHAPE_GAUSSIAN:
            y[i0:i1] += height * np.exp(-0.5 * (dx / sigma) ** 2)
        elif shape == SHAPE_LORENTZIAN:
            y[i0:i1] += height / (1.0 + (dx / half) ** 2)
        else:
            g = np.exp(-0.5 * (dx / sigma) ** 2)
            lo_r = 1.0 / (1.0 + (dx / half) ** 2)
            y[i0:i1] += height * (eta * lo_r + (1.0 - eta) * g)
    if normalise:
        top = float(y.max()) if y.size else 0.0
        if top > 0.0:
            y = y * (100.0 / top)
    return x, y


# ----------------------------------------------- what a structure remembers
#: Per-structure settings live in `Structure.metadata` under this key, beside
#: `polyhedra` and `show_cell` - so they ride undo and the savefile, and the
#: plot window owns no per-structure state at all. Deleting a crystal takes
#: its trace with it because the trace was never the window's.
METADATA_KEY = "pxrd"

DEFAULTS = {
    "wavelength": DEFAULT_WAVELENGTH,
    "two_theta_min": DEFAULT_TWO_THETA[0],
    "two_theta_max": DEFAULT_TWO_THETA[1],
    "fwhm": DEFAULT_FWHM,
    "step": DEFAULT_STEP,
    "shape": SHAPE_PSEUDO_VOIGT,
    "eta": 0.5,
    "enabled": True,
    "colour": "",
    "offset": 0.0,
}


def settings_of(structure):
    # type: (object) -> dict
    """This crystal's PXRD settings, defaults filled in."""
    meta = getattr(structure, "metadata", None) or {}
    stored = meta.get(METADATA_KEY) or {}
    out = dict(DEFAULTS)
    if isinstance(stored, dict):
        for key, value in stored.items():
            if key in out:
                out[key] = value
    return out


def set_settings(structure, **changes):
    """Change some of them, leaving the rest alone."""
    meta = getattr(structure, "metadata", None)
    if meta is None:
        return
    current = settings_of(structure)
    current.update({k: v for k, v in changes.items() if k in DEFAULTS})
    # Only what DIFFERS from the defaults is stored, so a savefile does not
    # carry ten keys per crystal saying "as shipped".
    trimmed = {k: v for k, v in current.items() if v != DEFAULTS[k]}
    if trimmed:
        meta[METADATA_KEY] = trimmed
    else:
        meta.pop(METADATA_KEY, None)
