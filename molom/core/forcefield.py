"""Force-field geometry optimisation (the "clean up my drawing" button).

Tiering matches ORCA Workbench's coordinate pre-optimisation and Avogadro's
default: **RDKit MMFF94** first, **UFF** as the fallback when MMFF has no
parameters for an atom type (metals, exotic valences), and OpenBabel UFF as
the last resort when RDKit itself refuses the molecule. A drawn structure is
frequently chemically "wrong" mid-edit, so every tier degrades instead of
raising — you get the best geometry available plus a note about which
engine produced it.

UI-free: takes symbols/coords/bonds, returns new coordinates. `fixed` pins
atoms in place, which is also how the coordination "meta atom" restraints
will be applied later.
"""

from typing import List, Optional, Sequence, Tuple

import os

import numpy as np

METHODS = [
    ("mmff94", "MMFF94"),
    ("mmff94s", "MMFF94s"),
    ("uff", "UFF"),
]
DEFAULT_METHOD = "mmff94"     # same default as OWB / Avogadro

#: Optimisers contributed by ADD-ONS, {key: (label, callable)}.
#:
#: This is the whole extension point, and it exists so that a method living
#: entirely outside `core/` can still appear in the one Optimize panel rather
#: than growing a second, parallel one that nobody finds. Core knows the
#: CONTRACT and never the implementation: it does not import the add-on, does
#: not know what a semiempirical method is, and holds no subprocess or
#: binary-discovery code. Christian's constraint for MOPAC was "an addon that
#: doesn't mess with anything else in the software", and a dict plus a
#: signature is the smallest thing that satisfies it.
#:
#: The callable takes `(symbols, coords, bonds, steps, fixed)` — `optimize`'s
#: own arguments minus the method — and returns `(coords, info)` with the same
#: `info` keys the built-in tiers produce, or raises `ForceFieldError`.
_EXTERNAL = {}


def register_method(key, label, func):
    # type: (str, str, object) -> None
    """Add an optimiser to the Method list. Idempotent, so enabling an add-on
    twice cannot double the entry."""
    if not key or not callable(func):
        raise ValueError("register_method needs a key and a callable")
    _EXTERNAL[str(key)] = (str(label), func)


def unregister_method(key):
    # type: (str) -> None
    """Remove one. Silent when it was never there, so an add-on's
    `unregister` never has to guard against a half-finished `register`."""
    _EXTERNAL.pop(str(key), None)


def all_methods():
    # type: () -> list
    """`METHODS` plus whatever add-ons have registered, for the UI.

    Built fresh on every call rather than cached: an add-on can be enabled or
    disabled while the window is open, and a cached list is how the panel ends
    up offering a method that has just been unregistered.
    """
    return list(METHODS) + [(k, lab) for k, (lab, _f) in _EXTERNAL.items()]


def external_method(key):
    # type: (str) -> object
    """The callable for `key`, or None. Lets a caller ask "is this one of
    ours?" without reaching into the registry."""
    entry = _EXTERNAL.get(str(key))
    return entry[1] if entry else None


class ForceFieldError(Exception):
    """No backend could handle the molecule at all."""


def ensure_babel_datadir():
    # type: () -> Optional[str]
    """Point BABEL_DATADIR at the installed OpenBabel data files.

    The openbabel-wheel SETS BABEL_DATADIR itself on import — to a share
    directory that (on Windows at least) holds nothing but splash.png. Every
    UFF call then dies with "Cannot open UFF.prm". So the variable being set
    proves nothing: VERIFY that UFF.prm is actually there and override it
    otherwise. Overriding after import is fine — OpenBabel reads the variable
    per parameter-file load, not once at library init.

    Returns the directory in use, or None when no complete data set exists.
    """
    def usable(path):
        return bool(path) and os.path.isfile(os.path.join(path, "UFF.prm"))

    current = os.environ.get("BABEL_DATADIR")
    if usable(current):
        return current

    candidates = []
    try:                                   # inside the installed package
        from openbabel import openbabel as ob
        base = os.path.dirname(os.path.abspath(ob.__file__))
        candidates += [os.path.join(base, "data"),
                       os.path.join(base, "share", "openbabel"), base]
    except ImportError:
        pass
    # a full system OpenBabel install — where the wheels' missing .prm files
    # usually do exist
    import glob
    for root in (os.environ.get("APPDATA"), os.environ.get("PROGRAMFILES"),
                 os.environ.get("PROGRAMFILES(X86)"), "/usr/share",
                 "/usr/local/share"):
        if not root:
            continue
        candidates += sorted(glob.glob(os.path.join(root, "OpenBabel*", "data")))
        candidates += sorted(glob.glob(os.path.join(root, "openbabel*")))
    for path in candidates:
        if usable(path):
            os.environ["BABEL_DATADIR"] = path
            return path
    return None


def _rdkit():
    try:
        from rdkit import Chem
        from rdkit.Chem import AllChem
        from rdkit import RDLogger
        RDLogger.DisableLog("rdApp.*")
        return Chem, AllChem
    except ImportError:
        return None, None


def backends_available():
    # type: () -> dict
    """What this install can actually run (for greying out the UI)."""
    Chem, _ = _rdkit()
    ok_ob = True
    try:
        from openbabel import pybel  # noqa: F401
    except ImportError:
        try:
            import pybel  # noqa: F401
        except ImportError:
            ok_ob = False
    return {"rdkit": Chem is not None, "openbabel": ok_ob}


def _build_rdkit_mol(symbols, coords, bonds):
    """Our (symbols, coords, bonds) -> an RDKit mol with a conformer.

    Bonds come from MoloM's own perception/editing, so connectivity is taken
    as given; sanitisation is done permissively because a half-drawn
    structure often has odd valences."""
    Chem, _ = _rdkit()
    if Chem is None:
        return None, "RDKit is not installed"
    from rdkit.Geometry import Point3D
    rw = Chem.RWMol()
    order_map = {1: Chem.BondType.SINGLE, 2: Chem.BondType.DOUBLE,
                 3: Chem.BondType.TRIPLE}
    from . import elements
    for s in symbols:
        z = elements.atomic_number(s)
        if z <= 0:
            return None, "unknown element {!r}".format(s)
        atom = Chem.Atom(int(z))
        atom.SetNoImplicit(True)       # our hydrogens are explicit
        rw.AddAtom(atom)
    for i, j, o in bonds:
        rw.AddBond(int(i), int(j), order_map.get(int(o), Chem.BondType.SINGLE))
    mol = rw.GetMol()
    try:
        Chem.SanitizeMol(
            mol, sanitizeOps=Chem.SanitizeFlags.SANITIZE_ALL
            ^ Chem.SanitizeFlags.SANITIZE_PROPERTIES
            ^ Chem.SanitizeFlags.SANITIZE_KEKULIZE)
    except Exception as e:
        return None, "RDKit could not sanitise the molecule: {}".format(e)
    conf = Chem.Conformer(mol.GetNumAtoms())
    xyz = np.asarray(coords, dtype=float).reshape(-1, 3)
    for i in range(mol.GetNumAtoms()):
        conf.SetAtomPosition(i, Point3D(*[float(v) for v in xyz[i]]))
    mol.AddConformer(conf, assignId=True)
    return mol, None


def _rdkit_optimize(symbols, coords, bonds, method, steps, fixed):
    Chem, AllChem = _rdkit()
    if Chem is None:
        return None, "RDKit is not installed"
    mol, err = _build_rdkit_mol(symbols, coords, bonds)
    if mol is None:
        return None, err
    try:
        if method.startswith("mmff"):
            variant = "MMFF94s" if method == "mmff94s" else "MMFF94"
            props = AllChem.MMFFGetMoleculeProperties(mol, mmffVariant=variant)
            if props is None:
                return None, "MMFF has no parameters for this molecule"
            ff = AllChem.MMFFGetMoleculeForceField(mol, props)
        else:
            ff = AllChem.UFFGetMoleculeForceField(mol)
        if ff is None:
            return None, "{} could not set up a force field".format(method)
        for i in (fixed or ()):
            ff.AddFixedPoint(int(i))
        ff.Initialize()
        converged = ff.Minimize(maxIts=int(steps))
        energy = float(ff.CalcEnergy())
    except Exception as e:
        return None, "{} failed: {}: {}".format(method, type(e).__name__, e)
    conf = mol.GetConformer()
    out = np.array([[conf.GetAtomPosition(i).x, conf.GetAtomPosition(i).y,
                     conf.GetAtomPosition(i).z]
                    for i in range(mol.GetNumAtoms())], dtype=float)
    return (out, {"engine": "rdkit", "method": method, "energy": energy,
                  "converged": converged == 0}), None


def _openbabel_optimize(symbols, coords, bonds, steps, fixed=None):
    """Last resort — OpenBabel UFF, the same fallback OWB uses when RDKit
    cannot embed a structure (metal complexes, mostly).

    `fixed` is honoured through `OBFFConstraints`. It used to be silently
    DROPPED here — the parameter did not even exist — which mattered far more
    than it looks: this is precisely the tier a metal complex lands on, so the
    one case that most needs frozen atoms was the one case that never got them.
    On a meta centre that meant nothing held the coordination sphere and the
    donors collapsed onto the dummy (measured: 2.0 A set, 0.655 A after).
    """
    try:
        from openbabel import openbabel as ob
    except ImportError:
        try:
            import openbabel as ob
        except ImportError:
            return None, "OpenBabel is not installed"
    from . import elements
    # AFTER the import: the wheel (re)sets BABEL_DATADIR to its own share
    # directory as the extension initialises, so fixing it earlier gets
    # clobbered. Set it immediately before the force field is built.
    datadir = ensure_babel_datadir()
    if datadir is None:
        return None, ("OpenBabel has no parameter files (UFF.prm not found) "
                      "— install the full OpenBabel data set")
    try:
        mol = ob.OBMol()
        for s, p in zip(symbols, np.asarray(coords, dtype=float)):
            a = mol.NewAtom()
            a.SetAtomicNum(int(elements.atomic_number(s)))
            a.SetVector(float(p[0]), float(p[1]), float(p[2]))
        for i, j, o in bonds:
            mol.AddBond(int(i) + 1, int(j) + 1, int(o))
        ff = ob.OBForceField.FindForceField("UFF")
        if ff is None:
            return None, "OpenBabel UFF could not set up this molecule"
        # OpenBabel indexes atoms from 1, unlike RDKit and unlike us.
        constraints = None
        if fixed:
            constraints = ob.OBFFConstraints()
            for i in fixed:
                constraints.AddAtomConstraint(int(i) + 1)
        ok = (ff.Setup(mol, constraints) if constraints is not None
              else ff.Setup(mol))
        if not ok:
            return None, "OpenBabel UFF could not set up this molecule"
        ff.ConjugateGradients(int(steps))
        ff.GetCoordinates(mol)
        energy = float(ff.Energy())
    except Exception as e:
        return None, "OpenBabel failed: {}: {}".format(type(e).__name__, e)
    out = np.array([[mol.GetAtom(i + 1).GetX(), mol.GetAtom(i + 1).GetY(),
                     mol.GetAtom(i + 1).GetZ()]
                    for i in range(len(symbols))], dtype=float)
    return (out, {"engine": "openbabel", "method": "uff", "energy": energy,
                  "converged": True}), None


def optimize(symbols, coords, bonds, method=DEFAULT_METHOD, steps=500,
             fixed=None):
    # type: (List[str], np.ndarray, Sequence, str, int, Optional[Sequence[int]]) -> Tuple[np.ndarray, dict]
    """Minimise the geometry. Returns (coords, info); `info["notes"]` records
    any tier that had to be skipped. Raises ForceFieldError only when every
    backend refused."""
    if len(symbols) < 2:
        return np.asarray(coords, dtype=float).reshape(-1, 3), {
            "engine": "none", "method": method, "energy": 0.0,
            "converged": True, "notes": ["nothing to optimise"]}
    # AN ADD-ON METHOD DOES NOT FALL BACK, and that is deliberate. Dropping
    # from MMFF94 to UFF is a change of force field; dropping from a
    # semiempirical Hamiltonian to a force field is a change of PHYSICS, and
    # quietly returning an MMFF94 geometry labelled as the thing the user asked
    # for is exactly the kind of silent substitution round 38 argued against.
    # So it reports instead — the panel shows the message.
    external = external_method(method)
    if external is not None:
        return external(symbols, coords, bonds, steps=steps, fixed=fixed)
    notes = []
    chain = [method]
    if method != "uff":
        chain.append("uff")           # MMFF gaps -> UFF, as in OWB
    for m in chain:
        res, err = _rdkit_optimize(symbols, coords, bonds, m, steps, fixed)
        if res is not None:
            out, info = res
            info["notes"] = notes
            return out, info
        notes.append("{}: {}".format(m, err))
    res, err = _openbabel_optimize(symbols, coords, bonds, steps, fixed)
    if res is not None:
        out, info = res
        info["notes"] = notes + ["fell back to OpenBabel UFF"]
        return out, info
    notes.append("openbabel: {}".format(err))
    raise ForceFieldError("; ".join(notes))
