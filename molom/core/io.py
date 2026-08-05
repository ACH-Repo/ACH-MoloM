"""Universal structure import/export + SMILES -> 3D.

Vendored port of ORCA Workbench's import cascade (orca_workbench/core/
coords.py, MIT, same author) so MoloM imports molecules exactly the way OWB
does. Four tiers:

1. native .xyz — dependency-free, multi-frame (trajectories), JSON-comment
   metadata convention preserved;
2. OpenBabel in a TIMEOUT-GUARDED SUBPROCESS (some readers loop forever on
   certain inputs; a thread can't be killed because SWIG holds the GIL);
3. RDKit fallback for the common formats when OpenBabel is absent;
4. last-resort heuristic "Label x y z" salvage for write-only/input-deck
   formats, flagged for the user to VERIFY.

Changes vs the OWB original: worker module path, Qt name filters instead of
Tk filetypes, element table shared with molom.core.elements, and a
frames_are_trajectory helper for the viewer. Keep diffable with upstream.
"""

import json
import os
import re
import subprocess
import sys
from typing import List, Optional, Tuple

from . import elements

Atom = Tuple[str, float, float, float]

_loggers_silenced = False


def _ensure_loggers_silenced():
    """Silence the chem-backend loggers once, lazily — on first actual use
    (importing RDKit/OpenBabel at module load would slow every launch)."""
    global _loggers_silenced
    if _loggers_silenced:
        return
    _loggers_silenced = True
    _silence_chem_loggers()


def _silence_chem_loggers():
    try:
        from rdkit import RDLogger
        RDLogger.DisableLog("rdApp.*")
    except Exception:
        pass
    try:
        try:
            from openbabel import openbabel as _ob
        except ImportError:
            import openbabel as _ob  # type: ignore
        try:
            _ob.obErrorLog.StopLogging()
        except AttributeError:
            _ob.obErrorLog.SetOutputLevel(0)
    except Exception:
        pass


class CoordGenError(Exception):
    """Raised when a structure can't be read or coordinates can't be generated."""


def _atomic_number_to_symbol(z):
    # type: (int) -> str
    s = elements.symbol(z)
    return s if s != "Xx" else "X"


# ------------------------------------------------------------------ SMILES

def smiles_to_xyz(smiles, prefer_rdkit_only=False):
    # type: (str, bool) -> Tuple[List[Atom], str]
    """Generate 3D coords for a SMILES string. Returns (atoms, method) where
    method is "rdkit" or "pybel"; raises CoordGenError with both backends'
    errors on failure."""
    _ensure_loggers_silenced()
    rdkit_atoms, rdkit_err = _try_rdkit(smiles)
    if rdkit_atoms is not None:
        return rdkit_atoms, "rdkit"
    if prefer_rdkit_only:
        raise CoordGenError(
            "RDKit could not generate coordinates (RDKit-only mode):\n  {}".format(
                rdkit_err or "unknown error"))
    pybel_atoms, pybel_err = _try_pybel(smiles)
    if pybel_atoms is not None:
        return pybel_atoms, "pybel"
    raise CoordGenError(
        "Both backends failed for SMILES {!r}:\n"
        "  RDKit:    {}\n"
        "  OpenBabel: {}".format(smiles, rdkit_err or "unknown error",
                                 pybel_err or "unknown error"))


def smiles_charge_and_mult(smiles):
    # type: (str) -> Tuple[Optional[int], Optional[int]]
    """(net_charge, spin_multiplicity) from a SMILES via RDKit, or (None, None)."""
    if not smiles or not smiles.strip():
        return None, None
    _ensure_loggers_silenced()
    try:
        from rdkit import Chem
    except ImportError:
        return None, None
    try:
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return None, None
        charge = sum(a.GetFormalCharge() for a in mol.GetAtoms())
        n_radical = sum(a.GetNumRadicalElectrons() for a in mol.GetAtoms())
        return int(charge), int(n_radical + 1)
    except Exception:
        return None, None


def smiles_is_valid(smiles):
    # type: (str) -> bool
    """True if RDKit can parse this SMILES (False when RDKit is absent)."""
    if not smiles or not smiles.strip():
        return False
    _ensure_loggers_silenced()
    try:
        from rdkit import Chem
    except ImportError:
        return False
    try:
        return Chem.MolFromSmiles(smiles) is not None
    except Exception:
        return False


def _try_rdkit(smiles):
    # type: (str) -> Tuple[Optional[List[Atom]], Optional[str]]
    try:
        from rdkit import Chem
        from rdkit.Chem import AllChem
    except ImportError as e:
        return None, "RDKit not installed ({})".format(e)
    except Exception as e:
        return None, "RDKit import raised: {}: {}".format(type(e).__name__, e)
    try:
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return None, "RDKit could not parse SMILES (MolFromSmiles returned None)"
        mol = Chem.AddHs(mol)
        params = AllChem.ETKDGv3()
        params.randomSeed = 42
        rc = AllChem.EmbedMolecule(mol, params)
        if rc == -1:
            return None, "RDKit ETKDGv3 failed to embed a 3D conformer"
        try:
            AllChem.MMFFOptimizeMolecule(mol)
        except Exception:
            pass   # missing MMFF params — accept the unoptimised embed
        conf = mol.GetConformer()
        atoms = []
        for atom in mol.GetAtoms():
            pos = conf.GetAtomPosition(atom.GetIdx())
            atoms.append((atom.GetSymbol(), float(pos.x), float(pos.y),
                          float(pos.z)))
        return atoms, None
    except Exception as e:
        return None, "RDKit raised {}: {}".format(type(e).__name__, e)


def _try_pybel(smiles):
    # type: (str) -> Tuple[Optional[List[Atom]], Optional[str]]
    try:
        try:
            from openbabel import pybel
        except ImportError:
            import pybel  # type: ignore
    except ImportError as e:
        return None, "OpenBabel/Pybel not installed ({})".format(e)
    except Exception as e:
        return None, "OpenBabel import raised: {}: {}".format(type(e).__name__, e)
    try:
        mol = pybel.readstring("smi", smiles)
        mol.addh()
        mol.make3D(steps=50)
        mol.localopt(forcefield="uff", steps=200)
        atoms = []
        for atom in mol.atoms:
            symbol = _atomic_number_to_symbol(atom.atomicnum)
            x, y, z = atom.coords
            atoms.append((symbol, float(x), float(y), float(z)))
        return atoms, None
    except Exception as e:
        return None, "OpenBabel raised {}: {}".format(type(e).__name__, e)


def structure_to_smiles(symbols, bonds, charge=0):
    # type: (List[str], List, int) -> Tuple[Optional[str], Optional[str]]
    """SMILES from the connectivity graph — the drawn molecule IS a molecular
    graph, so this is exact rather than a guess. Returns (smiles, error).

    Coordinates are not used: atoms + bonds + orders fully determine the
    constitution (stereochemistry is not inferred, which is why the caller
    should treat the result as constitutional, not configurational)."""
    _ensure_loggers_silenced()
    try:
        from rdkit import Chem
    except ImportError:
        return None, "RDKit is not installed"
    from . import elements
    rw = Chem.RWMol()
    order_map = {1: Chem.BondType.SINGLE, 2: Chem.BondType.DOUBLE,
                 3: Chem.BondType.TRIPLE, 4: Chem.BondType.QUADRUPLE}
    for s in symbols:
        z = elements.atomic_number(s)
        if z <= 0:
            return None, "unknown element {!r}".format(s)
        rw.AddAtom(Chem.Atom(int(z)))
    for i, j, o in bonds:
        rw.AddBond(int(i), int(j), order_map.get(int(o), Chem.BondType.SINGLE))
    mol = rw.GetMol()
    try:
        Chem.SanitizeMol(mol)
    except Exception as e:
        return None, "could not sanitise the structure: {}".format(e)
    try:
        return Chem.MolToSmiles(Chem.RemoveHs(mol)), None
    except Exception as e:
        return None, "SMILES generation failed: {}".format(e)


def parse_smiles_list(text):
    # type: (str) -> List[Tuple[str, Optional[str]]]
    """Parse pasted SMILES content: single-line dot-separated, one per line,
    or a two-column SMILES+name table (column order auto-detected by RDKit
    parse-success rate). Returns (smiles, name_or_None) pairs."""
    text = (text or "").strip()
    if not text:
        return []
    if "\n" not in text and "." in text:
        return [(s.strip(), None) for s in text.split(".") if s.strip()]
    rows = []
    for line in text.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        fields = [f for f in re.split(r"[\s,;\t]+", line) if f]
        if fields:
            rows.append(fields)
    if not rows:
        return []
    max_cols = max(len(r) for r in rows)
    if max_cols == 1:
        return [(r[0], None) for r in rows]
    valid_counts = [0] * max_cols
    for r in rows:
        for i, field in enumerate(r):
            if smiles_is_valid(field):
                valid_counts[i] += 1
    smiles_col = valid_counts.index(max(valid_counts)) if max(valid_counts) > 0 else 0
    name_col = None
    candidates = [i for i in range(max_cols) if i != smiles_col]
    if candidates:
        name_col = candidates[0]
    result = []
    for r in rows:
        if smiles_col >= len(r):
            continue
        s = r[smiles_col]
        n = r[name_col] if (name_col is not None and name_col < len(r)) else None
        result.append((s, n))
    return result


SMILES_LIST_FORMATS = [
    ("smi", "SMILES list"),
    ("smiles", "SMILES list"),
    ("csv", "CSV (SMILES + name)"),
]
_SMILES_LIST_EXTS = {ext for ext, _ in SMILES_LIST_FORMATS}


def is_smiles_list_file(path):
    # type: (str) -> bool
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    return ext in _SMILES_LIST_EXTS


def read_smiles_file(path):
    # type: (str) -> List[Tuple[str, Optional[str]]]
    """Read a .smi/.smiles/.csv into (smiles, name) pairs; header rows and
    non-parsing lines are dropped when RDKit is available."""
    if not os.path.isfile(path):
        raise CoordGenError("File not found: {}".format(path))
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError as e:
        raise CoordGenError("Could not read {}: {}".format(path, e))
    pairs = parse_smiles_list(text)
    if smiles_is_valid("C"):   # True only if RDKit is importable
        pairs = [(s, n) for s, n in pairs if smiles_is_valid(s)]
    if not pairs:
        raise CoordGenError(
            "No valid SMILES found in {} (expected one SMILES per line, or a "
            "SMILES,name table).".format(os.path.basename(path)))
    return pairs


# ------------------------------------------------------------- xyz native

def write_xyz(path, atoms, metadata=None):
    # type: (str, List[Atom], Optional[dict]) -> None
    """Write an .xyz; metadata (if given) goes in the comment line as JSON."""
    comment = json.dumps(metadata) if metadata else ""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("{}\n".format(len(atoms)))
        f.write("{}\n".format(comment))
        for symbol, x, y, z in atoms:
            clean = "".join(ch for ch in symbol if ch.isalpha())
            f.write("{:<2} {:10.5f} {:10.5f} {:10.5f}\n".format(clean, x, y, z))


def read_xyz(path):
    # type: (str) -> Tuple[List[Atom], Optional[dict]]
    """Read the FIRST frame of an .xyz. Returns (atoms, metadata_or_None)."""
    frames = _read_xyz_frames(path)
    if not frames:
        raise CoordGenError("No atoms found in {}".format(path))
    return frames[0]


def parse_xyz_frames_text(text):
    # type: (str) -> List[Tuple[List[Atom], Optional[dict]]]
    """Parse every frame of XYZ-format *text* into [(atoms, metadata), ...].

    A leading integer atom-count line is required, so this returns [] for text
    that isn't XYZ — callers use that to *detect* pasted coordinates."""
    lines = (text or "").split("\n")
    frames = []
    n_lines = len(lines)
    i = 0
    while i < n_lines:
        while i < n_lines and not lines[i].strip():
            i += 1
        if i >= n_lines:
            break
        try:
            n = int(lines[i].strip())
        except ValueError:
            break
        comment = lines[i + 1] if i + 1 < n_lines else ""
        atoms = []
        for j in range(i + 2, min(i + 2 + n, n_lines)):
            parts = lines[j].split()
            if len(parts) < 4:
                continue
            try:
                atoms.append((parts[0], float(parts[1]), float(parts[2]),
                              float(parts[3])))
            except ValueError:
                continue
        metadata = None
        if comment.strip().startswith("{"):
            try:
                metadata = json.loads(comment)
            except ValueError:
                metadata = None
        frames.append((atoms, metadata))
        i = i + 2 + n
    return frames


def _read_xyz_frames(path):
    # type: (str) -> List[Tuple[List[Atom], Optional[dict]]]
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return parse_xyz_frames_text(f.read())


def _xyz_block(atoms, name=""):
    lines = ["{}".format(len(atoms)), name or ""]
    for symbol, x, y, z in atoms:
        clean = "".join(ch for ch in symbol if ch.isalpha())
        lines.append("{:<2} {:14.8f} {:14.8f} {:14.8f}".format(clean, x, y, z))
    return "\n".join(lines)


# --------------------------------------------------------------- exporters

MULTI_STRUCTURE_FORMATS = ("xyz", "sdf", "pdb", "mol2")


def write_structure_file(path, atoms, name=""):
    # type: (str, List[Atom], str) -> str
    """Write atoms in the format the EXTENSION names (.xyz native; else
    OpenBabel, RDKit fallback for mol/sdf/pdb). Returns the backend used."""
    ext = os.path.splitext(path)[1].lower().lstrip(".") or "xyz"
    if ext == "xyz":
        write_xyz(path, atoms, {"name": name} if name else None)
        return "native"
    xyz_text = _xyz_block(atoms, name) + "\n"
    errors = []
    try:
        try:
            from openbabel import pybel
        except ImportError:
            import pybel  # type: ignore
        if ext not in pybel.outformats:
            errors.append("OpenBabel doesn't write '{}'".format(ext))
        else:
            mol = pybel.readstring("xyz", xyz_text)
            if name:
                mol.title = name
            mol.write(ext, path, overwrite=True)
            return "openbabel"
    except ImportError as e:
        errors.append("OpenBabel/Pybel not installed ({})".format(e))
    except Exception as e:
        errors.append("OpenBabel raised {}: {}".format(type(e).__name__, e))
    if ext in ("mol", "sdf", "pdb"):
        try:
            from rdkit import Chem
            mol = Chem.MolFromXYZBlock(xyz_text)
            if mol is None:
                raise ValueError("RDKit could not read the geometry")
            try:
                from rdkit.Chem import rdDetermineBonds
                rdDetermineBonds.DetermineConnectivity(mol)
            except Exception:
                pass
            if ext == "pdb":
                Chem.MolToPDBFile(mol, path)
            elif ext == "sdf":
                with Chem.SDWriter(path) as w:
                    w.write(mol)
            else:
                Chem.MolToMolFile(mol, path)
            return "rdkit"
        except ImportError as e:
            errors.append("RDKit not installed ({})".format(e))
        except Exception as e:
            errors.append("RDKit raised {}: {}".format(type(e).__name__, e))
    raise ValueError("could not write '{}': {}".format(ext, "; ".join(errors)))


def write_structures_file(path, structures):
    # type: (str, List) -> str
    """Write MANY structures into ONE file (trajectory / multi-record).
    `structures` is a list of (atoms, name)."""
    if not structures:
        raise ValueError("nothing to write")
    ext = os.path.splitext(path)[1].lower().lstrip(".") or "xyz"
    if ext == "xyz":
        text = "\n".join(_xyz_block(atoms, nm) for atoms, nm in structures) + "\n"
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        return "native"
    errors = []
    try:
        try:
            from openbabel import pybel
        except ImportError:
            import pybel  # type: ignore
        if ext not in pybel.outformats:
            errors.append("OpenBabel doesn't write '{}'".format(ext))
        else:
            out = pybel.Outputfile(ext, path, overwrite=True)
            try:
                for atoms, nm in structures:
                    mol = pybel.readstring("xyz", _xyz_block(atoms, nm) + "\n")
                    if nm:
                        mol.title = nm
                    out.write(mol)
            finally:
                out.close()
            return "openbabel"
    except ImportError as e:
        errors.append("OpenBabel/Pybel not installed ({})".format(e))
    except Exception as e:
        errors.append("OpenBabel raised {}: {}".format(type(e).__name__, e))
    if ext == "sdf":
        try:
            from rdkit import Chem
            with Chem.SDWriter(path) as w:
                for atoms, nm in structures:
                    mol = Chem.MolFromXYZBlock(_xyz_block(atoms, nm) + "\n")
                    if mol is None:
                        raise ValueError("RDKit could not read a geometry")
                    try:
                        from rdkit.Chem import rdDetermineBonds
                        rdDetermineBonds.DetermineConnectivity(mol)
                    except Exception:
                        pass
                    if nm:
                        mol.SetProp("_Name", nm)
                    w.write(mol)
            return "rdkit"
        except ImportError as e:
            errors.append("RDKit not installed ({})".format(e))
        except Exception as e:
            errors.append("RDKit raised {}: {}".format(type(e).__name__, e))
    raise ValueError("could not write a multi-structure '{}': {}".format(
        ext, "; ".join(errors)))


# --------------------------------------------------------------- universal import

# (extension, openbabel format code, human label) — order drives the dialog.
SUPPORTED_IMPORT_FORMATS = [
    ("xyz", "xyz", "XYZ"),
    ("sdf", "sdf", "MDL SDF"),
    ("mol", "mol", "MDL MOL"),
    ("mol2", "mol2", "Sybyl MOL2"),
    ("pdb", "pdb", "PDB"),
    ("pdbqt", "pdbqt", "AutoDock PDBQT"),
    ("cif", "cif", "CIF"),
    ("mmcif", "mmcif", "mmCIF"),
    ("gro", "gro", "GROMACS"),
    ("hin", "hin", "HyperChem"),
    ("cml", "cml", "Chemical Markup"),
    ("gzmat", "gzmat", "Gaussian Z-matrix"),
    ("mdl", "mdl", "MDL"),
]
_EXT_TO_OBABEL = {ext: fmt for ext, fmt, _ in SUPPORTED_IMPORT_FORMATS}

IMPORT_READ_TIMEOUT_S = 15

_obabel_informats_cache = None   # None = not probed yet; set() once probed


def _openbabel_informats():
    # type: () -> Optional[set]
    """Cached set of OpenBabel-readable format codes, or None if OpenBabel
    isn't importable. Listing formats can't hang (only readfile can), so this
    rejects write-only formats instantly without a subprocess."""
    global _obabel_informats_cache
    if _obabel_informats_cache is not None:
        return _obabel_informats_cache or None
    try:
        try:
            from openbabel import pybel
        except ImportError:
            import pybel  # type: ignore
        _obabel_informats_cache = set(pybel.informats.keys())
    except Exception:
        _obabel_informats_cache = set()
    return _obabel_informats_cache or None


def _meta_from_title(title, source_path=None):
    # type: (Optional[str], Optional[str]) -> Optional[dict]
    """Title/comment -> metadata dict ({"name": ...} or parsed JSON), dropping
    path-like titles OpenBabel defaults in for some formats."""
    if not title:
        return None
    t = title.strip()
    if t.startswith("{"):
        try:
            d = json.loads(t)
        except ValueError:
            return None
        return d if isinstance(d, dict) else None
    if "/" in t or "\\" in t:
        return None
    if source_path:
        base = os.path.basename(source_path)
        if t == base or t == os.path.splitext(base)[0]:
            return None
    return {"name": t}


def is_supported_import_file(path):
    # type: (str) -> bool
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    return ext in _EXT_TO_OBABEL


def import_name_filters():
    # type: () -> List[str]
    """Qt file-dialog name filters: 'all coordinate files' first, then one per
    format, then SMILES lists, then all files. Single source of truth for the
    format list (kept out of the UI so it stays testable)."""
    all_pat = " ".join("*.{}".format(ext) for ext, _, _ in SUPPORTED_IMPORT_FORMATS)
    filters = ["Coordinate files ({})".format(all_pat)]
    smi_pat = " ".join("*.{}".format(ext) for ext, _ in SMILES_LIST_FORMATS)
    filters.append("SMILES lists ({})".format(smi_pat))
    for ext, _fmt, label in SUPPORTED_IMPORT_FORMATS:
        filters.append("{} (*.{})".format(label, ext))
    filters.append("All files (*)")
    return filters


def _read_with_openbabel(path, fmt, timeout=IMPORT_READ_TIMEOUT_S):
    # type: (str, str, float) -> Tuple[Optional[list], Optional[str]]
    """Read all records via OpenBabel in a killable subprocess."""
    cmd = [sys.executable, "-m", "molom.core._obabel_worker", fmt, path]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, ("reading timed out after {}s - the OpenBabel reader for '{}' "
                      "hung on this file (the format/file may be unreadable).".format(
                          timeout, fmt))
    except Exception as e:
        return None, "could not launch reader subprocess: {}: {}".format(
            type(e).__name__, e)
    out = (proc.stdout or b"").decode("utf-8", "replace").strip()
    if not out:
        err = (proc.stderr or b"").decode("utf-8", "replace").strip()
        return None, "reader produced no output{}".format(
            ": " + err[:200] if err else "")
    try:
        data = json.loads(out.splitlines()[-1])
    except ValueError:
        return None, "reader output not understood: {}".format(out[:200])
    if not data.get("ok"):
        return None, data.get("error", "unknown error")
    structs = []
    for s in data.get("structures", []):
        atoms = [(a[0], float(a[1]), float(a[2]), float(a[3]))
                 for a in s.get("atoms", [])]
        structs.append((atoms, _meta_from_title(s.get("name"), path)))
    return structs, None


def _read_with_rdkit(path, fmt):
    # type: (str, str) -> Tuple[Optional[list], Optional[str]]
    """Fallback reader for the common formats (reads existing 3D coords)."""
    try:
        from rdkit import Chem
    except Exception as e:
        return None, "RDKit not available ({})".format(e)
    f = fmt.lower()
    try:
        mols = []
        if f in ("sdf", "sd", "mdl"):
            mols = [m for m in Chem.SDMolSupplier(path, removeHs=False,
                                                  sanitize=False)
                    if m is not None]
        elif f == "mol":
            m = Chem.MolFromMolFile(path, removeHs=False, sanitize=False)
            mols = [m] if m is not None else []
        elif f == "mol2":
            m = Chem.MolFromMol2File(path, removeHs=False, sanitize=False)
            mols = [m] if m is not None else []
        elif f in ("pdb", "ent"):
            m = Chem.MolFromPDBFile(path, removeHs=False, sanitize=False)
            mols = [m] if m is not None else []
        else:
            return None, "RDKit has no reader for '{}'".format(fmt)
        structs = []
        for m in mols:
            if m.GetNumConformers() == 0:
                continue
            conf = m.GetConformer()
            atoms = []
            for atom in m.GetAtoms():
                pos = conf.GetAtomPosition(atom.GetIdx())
                atoms.append((atom.GetSymbol(), float(pos.x), float(pos.y),
                              float(pos.z)))
            name = m.GetProp("_Name").strip() if m.HasProp("_Name") else ""
            structs.append((atoms, _meta_from_title(name, path)))
        if not structs:
            return None, "RDKit found no 3D structures in {}".format(path)
        return structs, None
    except Exception as e:
        return None, "RDKit failed: {}: {}".format(type(e).__name__, e)


# --- heuristic Cartesian-block salvage (write-only / input-deck formats) ---

_HEUR_ELEMENTS = {s.upper() for s in elements.SYMBOLS[1:]}
_HEUR_FLOAT = r"[-+]?(?:\d+\.\d*|\.\d+)(?:[eEdD][-+]?\d+)?"
_HEUR_ATOM_RE = re.compile(
    r"^\s*([A-Za-z]{1,2})\d*\s+(" + _HEUR_FLOAT + r")\s+(" + _HEUR_FLOAT
    + r")\s+(" + _HEUR_FLOAT + r")\s*$")


def _heur_float(tok):
    # type: (str) -> float
    return float(tok.replace("D", "E").replace("d", "e"))


def heuristic_atoms_from_text(text):
    # type: (str) -> List[Atom]
    """Longest contiguous run of `<element> x y z` lines in arbitrary text
    (>= 2 lines), so input decks/outputs still yield their geometry."""
    best = []      # type: List[Atom]
    run = []       # type: List[Atom]
    for line in text.split("\n"):
        m = _HEUR_ATOM_RE.match(line)
        if m and m.group(1).upper() in _HEUR_ELEMENTS:
            run.append((m.group(1), _heur_float(m.group(2)),
                        _heur_float(m.group(3)), _heur_float(m.group(4))))
        else:
            if len(run) > len(best):
                best = run
            run = []
    if len(run) > len(best):
        best = run
    return best if len(best) >= 2 else []


def _try_heuristic_file(path, fmt):
    # type: (str, str) -> Optional[list]
    try:
        with open(path, "rb") as fh:
            raw = fh.read(1024 * 1024)
    except OSError:
        return None
    if b"\x00" in raw:
        return None   # looks binary — don't text-scan it
    atoms = heuristic_atoms_from_text(raw.decode("utf-8", "replace"))
    if not atoms:
        return None
    meta = {"name": os.path.splitext(os.path.basename(path))[0],
            "source": "heuristic",
            "comment": "coordinates heuristically extracted from .{} - VERIFY "
                       "before use".format(fmt)}
    return [(atoms, meta)]


def _read_cif(path, disorder=None):
    # type: (str, Optional[str]) -> Optional[List[Tuple[List[Atom], Optional[dict]]]]
    """Native CIF read -> one record with the crystallography in metadata.

    Returns None (not an exception) if this file is not usable CIF, so the
    caller simply falls through to the OpenBabel cascade.

    `disorder` picks what to do with partially occupied sites; None takes
    `cif.POLICY_DOMINANT`, which resolves superimposed alternatives.
    """
    from . import cif as _cif
    disorder = disorder or _cif.POLICY_DOMINANT
    from . import cif as cif_mod
    report = {}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            data = cif_mod.parse_cif(fh.read())
        symbols, coords = cif_mod.expand(data, disorder=disorder,
                                         report=report)
    except (cif_mod.CifError, ValueError, OSError):
        return None
    if not symbols:
        return None
    atoms = [(s, float(c[0]), float(c[1]), float(c[2]))
             for s, c in zip(symbols, coords)]
    meta = {
        "source": "cif",
        "cell": data.cell.to_dict(),
        "spacegroup": data.spacegroup,
        "symops": [op.as_xyz() for op in data.symops],
        # The asymmetric unit, kept so the full cell can be rebuilt (or
        # re-exported) without re-reading the file. Occupancies ride along:
        # without them a rebuild would resolve the disorder differently from
        # the import, which is the sort of drift nobody would ever spot.
        "asym_symbols": list(data.symbols),
        "asym_frac": [[float(v) for v in row] for row in data.frac],
        "asym_occupancy": [float(o) for o in data.occupancy],
        "disorder_policy": disorder,
    }
    if report.get("disorder"):
        meta["disorder"] = dict(report["disorder"])
    if data.name:
        meta["name"] = data.name
    return [(atoms, meta)]


def read_structures(path, fmt=None, timeout=IMPORT_READ_TIMEOUT_S,
                    disorder=None):
    # type: (str, Optional[str], float, Optional[str]) -> List[Tuple[List[Atom], Optional[dict]]]
    """Read ALL structures (records/frames) from a coordinate file.

    Returns [(atoms, metadata), ...]; raises CoordGenError if nothing could
    be read. Non-xyz formats go through OpenBabel in a timeout-guarded
    subprocess, then RDKit, then the heuristic salvage."""
    _ensure_loggers_silenced()
    if not os.path.isfile(path):
        raise CoordGenError("File not found: {}".format(path))
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    fmt = (fmt or _EXT_TO_OBABEL.get(ext, ext)).lower()

    if fmt == "xyz":
        frames = _read_xyz_frames(path)
        if not frames or not any(a for a, _ in frames):
            raise CoordGenError("No atoms found in {}".format(path))
        return frames

    if fmt in ("cif", "mmcif"):
        # OUR reader first: OpenBabel reads .cif fine but discards the cell
        # and the space group, and those are the whole point of the format.
        # It stays as the fallback for the exotic dialects.
        native = _read_cif(path, disorder=disorder)
        if native is not None:
            return native

    informats = _openbabel_informats()
    if informats is not None and fmt not in informats:
        heur = _try_heuristic_file(path, fmt)
        if heur:
            return heur
        raise CoordGenError(
            "'{}' is not a readable structure format - OpenBabel can only write "
            "it, not read it (it's an input-deck/output/non-coordinate format). "
            "No xyz-style coordinate block was found to salvage either.".format(fmt))

    structs, ob_err = _read_with_openbabel(path, fmt, timeout=timeout)
    if structs:
        return structs
    rd_structs, rd_err = _read_with_rdkit(path, fmt)
    if rd_structs:
        return rd_structs
    heur = _try_heuristic_file(path, fmt)
    if heur:
        return heur
    raise CoordGenError(
        "Could not read {} (format '{}').\n  OpenBabel: {}\n  RDKit: {}".format(
            path, fmt, ob_err or "no structures returned", rd_err or "no reader"))


def read_coords_file(path, conformer_index=0, timeout=IMPORT_READ_TIMEOUT_S):
    # type: (str, int, float) -> Tuple[List[Atom], Optional[dict], int]
    """Read ONE structure -> (atoms, metadata, n_total)."""
    structs = read_structures(path, timeout=timeout)
    n = len(structs)
    try:
        atoms, meta = structs[conformer_index]
    except IndexError:
        raise CoordGenError(
            "Conformer index {} out of range: {} has {} structure(s) "
            "(valid {}..{}).".format(conformer_index, os.path.basename(path),
                                     n, -n, n - 1))
    if not atoms:
        raise CoordGenError("Selected structure in {} has no atoms.".format(
            os.path.basename(path)))
    return atoms, meta, n


def frames_are_trajectory(structs):
    # type: (List[Tuple[List[Atom], Optional[dict]]]) -> bool
    """True if a multi-structure read can be shown as ONE molecule animated
    over frames: every record has the same atom-symbol sequence."""
    if len(structs) < 2:
        return False
    first = [a[0] for a in structs[0][0]]
    return all([a[0] for a in atoms] == first for atoms, _m in structs[1:])
