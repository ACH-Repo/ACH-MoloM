"""Generate `molom/core/scattering.py` - X-ray atomic scattering factors.

Run:  python tools/gen_scattering.py

The same pattern as `tools/gen_elements.py`: a numeric table nobody should
type from memory is GENERATED from a source that is named, and the source is
recorded in THIRD_PARTY_NOTICES.md.

**Source.** pymatgen's `pymatgen/analysis/diffraction/atomic_scattering_params
.json` (MIT licence), which is itself the four-Gaussian parameterisation from
*International Tables for Crystallography* Vol. C, Table 6.1.1.4.

**The parameterisation matters and is easy to get wrong.** These coefficients
are NOT the Cromer-Mann `sum(a_i exp(-b_i s^2)) + c` form. They give the
DIFFERENCE from the atomic number:

    f(s) = Z - 41.78214 * s^2 * sum_i a_i * exp(-b_i * s^2),   s = sin(theta)/lambda

which is why there are four (a, b) pairs and no constant term. Using them in
the Cromer-Mann formula gives numbers that look plausible and are wrong.

pymatgen is NOT a MoloM dependency - it is an optional backstop tier for
space-group symbols - so the table is vendored rather than imported.
"""
import datetime
import json
import os
import sys


HEADER = '''"""X-ray atomic scattering factors. GENERATED - do not edit by hand.

Regenerate with `python tools/gen_scattering.py`. Source and the exact
parameterisation are documented there and in THIRD_PARTY_NOTICES.md.

    f(s) = Z - 41.78214 * s^2 * sum_i a_i * exp(-b_i * s^2)

with `s = sin(theta) / lambda` in inverse Angstrom. The coefficients are the
four-Gaussian set from International Tables for Crystallography Vol. C,
Table 6.1.1.4, by way of pymatgen (MIT).

Keys are ELEMENT SYMBOLS, not species: MoloM stores what a site is made of as
a symbol, and a table keyed by oxidation state would be asking a question the
structure cannot answer. Ionic factors differ from neutral ones mostly at low
angle; that is a stated limitation rather than an oversight.
"""

#: `{symbol: ((a1, b1), (a2, b2), (a3, b3), (a4, b4))}`
PARAMS = {
'''

FOOTER = '''}}

#: The constant in the formula above, kept named so nothing repeats it.
PREFACTOR = 41.78214

#: Generated {when} from {source}.
GENERATED = "{when}"
'''


def main():
    try:
        from pymatgen.analysis.diffraction.xrd import ATOMIC_SCATTERING_PARAMS
    except Exception as exc:                            # noqa: BLE001
        print("pymatgen is needed to regenerate this table:", exc)
        return 1
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "molom", "core", "scattering.py")
    lines = [HEADER]
    for symbol in sorted(ATOMIC_SCATTERING_PARAMS):
        pairs = ATOMIC_SCATTERING_PARAMS[symbol]
        if len(pairs) != 4:
            continue
        body = ", ".join("({:.6g}, {:.6g})".format(a, b) for a, b in pairs)
        lines.append('    "{}": ({}),\n'.format(symbol, body))
    when = datetime.date.today().isoformat()
    lines.append(FOOTER.format(when=when,
                               source="pymatgen ATOMIC_SCATTERING_PARAMS"))
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("".join(lines))
    print("wrote {} with {} species".format(out, len(ATOMIC_SCATTERING_PARAMS)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
