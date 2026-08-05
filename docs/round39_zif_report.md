# Round 39 — the ZIF batch: diagnosis and periodic display bonds

Written 2026-08-05, after Christian reported "I have downloaded a bunch of new
ZIFs. molom fails on almost all of them."

Status: **periodic bonds done** (873 tests passing). **Occupancy display modes
not started** — they are the next piece of work.

---

## First, the diagnosis was narrower than "almost all"

Cross-referenced every file against ASE, pymatgen, **and** each file's own
`_chemical_formula_sum × Z`:

- **Six were already exact**: `168840`, `2200004`, `787428`, `2310855`,
  `2478154`, and MOF-5 (`938392`). On `7712836` MoloM is *better* than ASE —
  we get C60H140Si20 (the correct formula×Z) where ASE keeps both disorder
  groups and returns C80H280Si40.
- **`iq4001img1.cif` is the one Christian spotted** — imgCIF, detector axes
  and PILATUS geometry, no `_cell_length_*` anywhere. Not a structure file.
- **Three real failures**, and they are two different bugs.

| File | What it is | Verdict |
|---|---|---|
| `168840` | C144H98Cl2N8Ni2, P1 | exact match, all three references |
| `2200004` | co-crystal | exact |
| `787428` | benzoic acid | exact |
| `2310855` | HNCO | exact |
| `938392` | **MOF-5** | exact, 424 atoms |
| `2478154` | Eu2CuZn2As3 intermetallic | exact |
| `7712836` | FeSi10 organometallic, disordered | exact — better than ASE |
| `2130205` | **the ZIF** | atoms exact; **bonds wrong** |
| `1488011` | ice | **wrong** — 14 H drawn, truth is 8 |
| `2240539` | cyclohexane plastic crystal | **wrong** — C56H128 vs C24H48 |
| `iq4001img1` | not a structure | correct refusal |

## The ZIF bug: 28 bonds were never drawn

On `2130205` the connectivity genuinely has **224 bonds; only 196 were
drawable**. Display bonds are perceived from Cartesian coordinates with no
minimum image, so anything whose partner sits in the next cell simply is not
drawn — **48 atoms were each a bond short**, and every imidazolate at a face
collapsed to a two-atom stub. VESTA reports the same file as 276 atoms / 324
bonds precisely because it materialises those partners.

Fixed as a **`BoundaryModifier`**, added automatically at import when a crystal
needs it. Non-destructive on purpose: the base molecule stays exactly the cell
contents, so Z, the ❖ atom count, editing and unit-cell export are untouched,
while the viewport *and* the Blender export see a continuous framework. The ❖
page's "Bonded atoms outside the cell" checkbox now drives it instead of doing
a destructive rebuild.

Acceptance criterion, measured: **48 atoms drawn a bond short → 0**, for both
the ZIF and MOF-5.

Four rules, each added only after something exploded:

- **covalent bonds only** — every one of MOF-5's 24 cross-face bonds is a
  covalent C–C inside a linker; every one of rock salt's is ionic. Following
  coordination bonds turned NaCl's 9-atom cell into 59, and a coordination
  bond is where a framework is *meant* to be cut.
- **finite fragments only** — the intermetallic (`2478154`) and any covalent
  polymer are infinite; each shell looks as unfinished as the last. Round 35's
  explicit exterior search still works on those, since that is a deliberate
  request.
- **whole molecules** — half a five-ring is not a thing. Switchable in the
  card.
- **de-duplicate by position** — `bonded_exterior` keyed images by
  `(site, image)`, which assumes every input atom is its own (0,0,0) image.
  False once boundary copies exist: `7712836` grew to **6389 atoms**. Related:
  a fragment that straddles a face has to be walked contiguous *before*
  translating, or its far half lands two cells out bonded to nothing.

Result: ZIF 176/196 → 216/252, MOF-5 424/488 → 616/704, molecular crystals
untouched.

Also fixed: a test-isolation bug introduced in round 37 — the resolver's
circuit breaker is module-global, so anything touching the real network marked
OPSIN down and made unrelated tests fail in the full run while passing alone.
`tests/conftest.py` resets it per test now.

## Two notes before the occupancy work

`2130205` and `2310855` looked like they were "missing hydrogens" — they are
not. Neither file lists a single H site; the formula mentions hydrogens that
were never located. Worth surfacing in the import note, which will be folded
into the occupancy work.

A caution about the VESTA reading: the 276/324 numbers came from a screen
capture, but the second attempt grabbed Christian's browser instead of VESTA
because he was using the machine. It was stopped there and both shots deleted.
For more VESTA references, the reliable route is Christian opening a file and
reading out the Output line — or the formula×Z check, which needs no external
tool and caught everything here.

## Next

Occupancy display modes — half-white spheres (VESTA), omit partial, round up
to 1. See the round-38 entry in `CLAUDE.md` for why the geometric "resolve
overlaps" policy is not enough on its own: in ice the half-occupied hydrogens
sit 0.79–0.81 Å apart against a 0.80 Å threshold, so the rule half-fires and
draws 14 hydrogens where the truth is 8 and VESTA draws 16 half-spheres.
