# MoloM

A standalone, Python-based molecule viewer/builder skeleton in the spirit of
Avogadro: an OpenGL ball-and-stick viewport with the same universal structure
import cascade as [ORCA Workbench](https://github.com/ACH-Repo/ACH-Orca-Workbench).

## Features (skeleton scope)

- **Import**: native multi-frame `.xyz` (with JSON-comment metadata),
  SDF/MOL/MOL2/PDB/CIF/... via OpenBabel (timeout-guarded subprocess) with an
  RDKit fallback and a last-resort heuristic `Label x y z` salvage; SMILES →
  3D (RDKit ETKDGv3 + MMFF, OpenBabel UFF fallback); paste-XYZ detection.
- **Rendering**: instanced-OpenGL ball-and-stick using Avogadro 2's element
  data (Alvarez VdW radii, Pyykkö covalent radii, Jmol-derived colours) and
  its exact sizing rules; stick / VdW / wireframe presets.
- **Bond perception**: Avogadro's `perceiveBondsSimple` rule (covalent radius
  sum + 0.45 Å tolerance, 0.32 Å minimum, noble gases and H-H excluded).
- **Selection & measurement**: click / Ctrl+click; 2, 3, 4 selected atoms show
  distance, angle, dihedral in the status bar.
- **Trajectory playback**: frame slider + play/pause for multi-frame files.
- **Editing (stubs)**: add/delete atoms, change element, add/remove/cycle
  bonds — wired UI dispatching into implemented, tested core functions.

## Install / run

```
pip install -e .          # core: numpy, PySide6, PyOpenGL
pip install -e .[chem]    # + rdkit, openbabel-wheel (SMILES + non-xyz formats)
molom [file.xyz]
python -m molom --selftest   # headless check, no GL needed
```

## Architecture

`molom/core/` is UI-free and GL-free (unit-testable offline);
`molom/ui/` is a thin PySide6/OpenGL shell over it. See `CLAUDE.md`.

Element data transcoded from Avogadro 2 (BSD 3-Clause) — see
`THIRD_PARTY_NOTICES.md`.
