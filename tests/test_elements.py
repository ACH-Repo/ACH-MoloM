"""Element data sanity: counts, anchor values, Avogadro's colour tweaks."""

from molom.core import elements


def test_counts():
    assert elements.ELEMENT_COUNT == 119
    for arr in (elements.SYMBOLS, elements.NAMES, elements.MASSES,
                elements.RADII_VDW, elements.RADII_COVALENT, elements.COLORS):
        assert len(arr) == 119


def test_anchor_values():
    # Quoted directly in elementdata.h / its cited references.
    assert elements.SYMBOLS[0] == "Xx"
    assert elements.SYMBOLS[1] == "H"
    assert elements.SYMBOLS[118] == "Og"
    assert abs(elements.radius_vdw(1) - 1.2) < 1e-9       # Alvarez H
    assert abs(elements.radius_covalent(1) - 0.32) < 1e-9  # Pyykko H
    assert abs(elements.radius_covalent(6) - 0.75) < 1e-9  # Pyykko C
    assert abs(elements.mass(6) - 12.011) < 0.01


def test_avogadro_color_tweaks():
    # H off-white (not 255), C 50% grey — deliberate Avogadro deviations
    # from plain Jmol colours, documented in the header.
    assert elements.color(1) == (240, 240, 240)
    assert elements.color(6) == (127, 127, 127)
    r, g, b = elements.color_f(6)
    assert abs(r - 127 / 255.0) < 1e-9 and r == g == b


def test_symbol_lookup_tolerant():
    assert elements.atomic_number("C") == 6
    assert elements.atomic_number("c") == 6
    assert elements.atomic_number("C1") == 6
    assert elements.atomic_number("Cl") == 17
    assert elements.atomic_number("cl2") == 17
    assert elements.atomic_number("Fe") == 26
    assert elements.atomic_number("Xq") == 0
    assert elements.atomic_number("") == 0


def test_out_of_range():
    assert elements.symbol(500) == "Xx"
    assert elements.radius_vdw(-1) == 1.5
    assert elements.color(999) == elements.COLORS[0]
