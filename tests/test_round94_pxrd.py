"""Round 94: simulated powder diffraction, `core/pxrd.py`.

The physics is checked against an INDEPENDENT implementation (pymatgen's
`XRDCalculator`) rather than against numbers written here, and against
textbook multiplicities and systematic absences where a reference is not
needed. Measured on rock salt: all 9 peaks matched, max 2-theta difference
3.9e-4 deg, max intensity difference 0.0000 %.

pymatgen is NOT a MoloM dependency - it is an optional backstop for
space-group symbols - so the cross-check skips where it is absent.
"""
import math

import numpy as np
import pytest

from molom.core import cif as cif_mod
from molom.core import pxrd

NACL_A = 5.6402
NACL_FRAC = [(0, 0, 0), (0, .5, .5), (.5, 0, .5), (.5, .5, 0),
             (.5, .5, .5), (.5, 0, 0), (0, .5, 0), (0, 0, .5)]
NACL_SYM = ["Na"] * 4 + ["Cl"] * 4


def _nacl(**kw):
    cell = cif_mod.Cell(NACL_A, NACL_A, NACL_A, 90, 90, 90)
    kw.setdefault("wavelength", 1.540598)
    kw.setdefault("two_theta_range", (10, 90))
    return pxrd.compute(cell, NACL_SYM, NACL_FRAC, **kw)


# ------------------------------------------------- against another program
def test_the_pattern_matches_pymatgen_peak_for_peak():
    """The check that matters. Everything else here could agree with itself
    and still be wrong."""
    pytest.importorskip("pymatgen")
    from pymatgen.analysis.diffraction.xrd import XRDCalculator
    from pymatgen.core import Lattice
    from pymatgen.core import Structure as PS

    pattern = _nacl()
    top = pattern.strongest()
    mine = {r.two_theta: 100.0 * r.intensity / top for r in pattern.reflections}
    ref = XRDCalculator(wavelength=1.540598).get_pattern(
        PS(Lattice.cubic(NACL_A), NACL_SYM, NACL_FRAC),
        two_theta_range=(10, 90))
    matched = 0
    for angle, intensity in zip(ref.x, ref.y):
        nearest = min(mine, key=lambda k: abs(k - angle))
        assert abs(nearest - angle) < 0.01, angle
        assert abs(mine[nearest] - intensity) < 0.05, angle
        matched += 1
    assert matched == len(ref.x) >= 8


# ----------------------------------------------------- physics on its own
def test_multiplicities_are_the_textbook_ones():
    """Rock salt: 111 x8, 200 x6, 220 x12, 311 x24. They come out of merging
    coincident reflections rather than a rule, which is what makes them a
    real check on the enumeration."""
    got = {r.hkl: r.multiplicity for r in _nacl().reflections}
    expected = {(1, 1, 1): 8, (2, 0, 0): 6, (2, 2, 0): 12, (3, 1, 1): 24}
    for hkl, mult in expected.items():
        assert got.get(hkl) == mult, (hkl, got.get(hkl))


def test_systematic_absences_need_no_rule():
    """An F-centred lattice has no mixed-index reflections, and nothing in
    `compute` knows that - |F|^2 is simply zero there."""
    present = {r.hkl for r in _nacl().reflections}
    for absent in ((1, 0, 0), (1, 1, 0), (2, 1, 0), (2, 1, 1)):
        assert absent not in present


def test_the_form_factor_is_the_difference_from_Z_not_a_cromer_mann_sum():
    """At s = 0 an atom scatters as its electron count. Reading the vendored
    coefficients as a Cromer-Mann sum gives a plausible wrong number, which is
    exactly why the parameterisation is documented in two places."""
    assert pxrd.form_factor("Na", 0.0) == pytest.approx(11.0)
    assert pxrd.form_factor("Cl", 0.0) == pytest.approx(17.0)
    assert pxrd.form_factor("C", 0.0) == pytest.approx(6.0)
    # ...and it falls off with angle.
    assert pxrd.form_factor("Na", 0.25) < 11.0


def test_an_unknown_species_falls_back_to_Z_and_says_so():
    cell = cif_mod.Cell(4.0, 4.0, 4.0, 90, 90, 90)
    pattern = pxrd.compute(cell, ["Xx"], [(0, 0, 0)])
    assert "Xx" in pxrd.missing_species(["Xx"])
    assert "scattering factor" in pattern.note


def test_no_displacement_parameters_is_SAID():
    """A pattern computed at B = 0 overestimates high-angle intensity, and a
    plausible-looking curve that nobody qualified is the failure mode this
    project keeps finding."""
    assert "B = 0" in _nacl().note
    quiet = _nacl(debye_waller=[0.5] * len(NACL_SYM))
    assert "B = 0" not in quiet.note


def test_debye_waller_suppresses_the_high_angle_peaks():
    plain = _nacl()
    damped = _nacl(debye_waller=[1.5] * len(NACL_SYM))
    high = max(r.two_theta for r in plain.reflections)
    a = [r for r in plain.reflections if r.two_theta == high][0]
    b = [r for r in damped.reflections
         if abs(r.two_theta - high) < 1e-6][0]
    assert (b.intensity / damped.strongest()) < (a.intensity / plain.strongest())


# --------------------------------------------------------------- the axis
def test_q_and_two_theta_round_trip():
    lam = 1.540598
    for angle in (10.0, 31.7, 90.0, 150.0):
        q = pxrd.q_from_two_theta(angle, lam)
        assert float(pxrd.two_theta_from_q(q, lam)) == pytest.approx(angle)


def test_a_shared_axis_must_be_Q_when_wavelengths_differ():
    """Not a preference. The same reflection sits at two angles for two
    wavelengths, so a shared 2-theta axis would be drawing a lie."""
    assert pxrd.common_axis([1.5406, 1.5406]) == pxrd.AXIS_TWO_THETA
    assert pxrd.common_axis([1.5406, 0.7093]) == pxrd.AXIS_Q


def test_Q_is_the_same_number_whatever_the_wavelength():
    """Which is the reason it can be shared: one reflection, one Q."""
    d = NACL_A / 2.0                       # the (200) spacing
    for lam in (1.540598, 0.7093):
        angle = math.degrees(2.0 * math.asin(lam / (2.0 * d)))
        assert float(pxrd.q_from_two_theta(angle, lam)) == pytest.approx(
            2.0 * math.pi / d)


def test_an_angle_a_wavelength_cannot_reach_is_NaN_not_an_exception():
    """A shared Q axis legitimately asks a long wavelength about a Q it
    cannot access."""
    assert np.isnan(float(pxrd.two_theta_from_q(20.0, 2.2897)))


# ------------------------------------------------------------- the profile
def test_the_profile_has_a_peak_at_every_reflection():
    pattern = _nacl()
    x, y = pxrd.profile(pattern, fwhm=0.1, step=0.01)
    assert x.shape == y.shape and y.max() == pytest.approx(100.0)
    strongest = max(pattern.reflections, key=lambda r: r.intensity)
    assert abs(x[int(np.argmax(y))] - strongest.two_theta) < 0.05


def test_the_width_is_the_width_you_asked_for():
    """Measured off the curve rather than assumed from the maths."""
    cell = cif_mod.Cell(NACL_A, NACL_A, NACL_A, 90, 90, 90)
    pattern = pxrd.compute(cell, NACL_SYM, NACL_FRAC,
                           two_theta_range=(31.0, 32.5))
    for shape in (pxrd.SHAPE_GAUSSIAN, pxrd.SHAPE_LORENTZIAN):
        x, y = pxrd.profile(pattern, fwhm=0.2, step=0.001, shape=shape)
        above = x[y >= 50.0]
        assert abs((above[-1] - above[0]) - 0.2) < 0.01, shape


def test_a_profile_in_Q_is_sampled_in_Q():
    pattern = _nacl()
    x, _y = pxrd.profile(pattern, axis=pxrd.AXIS_Q, fwhm=0.01, step=0.002)
    assert x[0] < 1.0 and x[-1] < 7.0        # inverse Angstrom, not degrees


def test_an_empty_pattern_still_returns_a_grid():
    empty = pxrd.Pattern([], 1.54, (10, 90))
    x, y = pxrd.profile(empty)
    assert len(x) == len(y) and not y.any()


# ------------------------------------------------ per-structure settings
def test_settings_live_on_the_STRUCTURE_so_they_ride_the_savefile(tmp_path):
    """MoloM shows several crystals at once, so a pattern is per-structure -
    the same decision as `polyhedra` and `show_cell`, and the reason the plot
    window will own no per-structure state."""
    from molom.core import project
    from molom.core.scene import Scene
    from molom.core.structure import Structure

    scene = Scene()
    s = Structure.from_atoms([("Na", 0.0, 0.0, 0.0)], name="salt")
    obj = scene.add(s)
    pxrd.set_settings(s, wavelength=0.7093, fwhm=0.25)
    assert pxrd.settings_of(s)["wavelength"] == 0.7093
    path = str(tmp_path / "t.molom")
    project.save_project(path, scene)
    back = Scene()
    back.from_dict(project.load_project(path)["scene"])
    reloaded = [o for o in back.objects if o.name == "salt"][0]
    assert pxrd.settings_of(reloaded.structure)["wavelength"] == 0.7093
    assert pxrd.settings_of(reloaded.structure)["fwhm"] == 0.25


def test_defaults_are_not_written_into_the_file():
    """Ten keys per crystal saying "as shipped" is noise in a savefile."""
    from molom.core.structure import Structure
    s = Structure.from_atoms([("Na", 0.0, 0.0, 0.0)])
    pxrd.set_settings(s, wavelength=pxrd.DEFAULT_WAVELENGTH)
    assert pxrd.METADATA_KEY not in s.metadata
    pxrd.set_settings(s, fwhm=0.9)
    assert set(s.metadata[pxrd.METADATA_KEY]) == {"fwhm"}


def test_unknown_settings_are_ignored():
    from molom.core.structure import Structure
    s = Structure.from_atoms([("Na", 0.0, 0.0, 0.0)])
    pxrd.set_settings(s, nonsense=1)
    assert pxrd.METADATA_KEY not in s.metadata
