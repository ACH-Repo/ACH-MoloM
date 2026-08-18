"""MOPAC as a geometry optimiser, contributed through the add-on API.

Why this is an ADD-ON and not a fourth tier in `core/forcefield.py`
------------------------------------------------------------------
Christian, scoping it: "the dependency is apparently tiny. Could probably run
it in molom itself. But idk how well we can integrate that as an addon that
doesn't mess with anything else in the software."

The answer this file takes: MoloM's core owns the CONTRACT and never the
implementation. `forcefield.register_method` is a dict and a signature; every
line that knows what MOPAC is - where the binary lives, what its input looks
like, how to run it, how to read what comes back - is in here. Disable the
add-on and `core/forcefield.py` is exactly the module it was before, with its
three force-field tiers and no subprocess of its own. That is the same
cordoning-off round 46 applied to the debug and sandbox pages, and it is why
`molom/core/` can go on being the offline-testable part.

The other half of "doesn't mess with anything else" is that it must not be a
SECOND optimise panel. A semiempirical method is the same gesture as a force
field - pick a method, press Start, get a geometry - so it belongs in the one
Method list, next to MMFF94 and UFF, or nobody will find it.

Where MOPAC earns its place
---------------------------
MMFF94 and UFF have no parameters for most of the periodic table, which is the
whole reason round 19's meta atoms exist: freeze the metal and its donors and
let the ligands relax, because the force field cannot describe the centre at
all. PM7 can. It is not DFT and is not meant to be - it is the tier between "a
force field has no parameters for this" and "start an ORCA job", which is
exactly the gap a builder leaves you standing in.

Nothing here is required. With no MOPAC installed the method simply does not
appear in the list, and MoloM behaves as it always has.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

import numpy as np

# ABSOLUTE, not relative. `core/addons.py` imports an add-on BY PATH under a
# synthetic module name (`molom_addon_<id>`), so the module has no package
# context and `from ..core import ...` dies with "attempted relative import
# with no known parent package" - which is a failure to LOAD AT ALL, reported
# in the preferences dialog as a red line under the add-on's name. Every other
# bundled add-on already imports absolutely; this file followed `core/` and
# `ui/`'s convention instead of `addons/`'s.
from molom.core import forcefield
from molom.core import io as io_mod

ADDON = {
    "id": "mopac_optimize",
    "name": "MOPAC (semiempirical optimisation)",
    "description": ("Adds PM7 / PM6 / AM1 / MNDO geometry optimisation to the "
                    "Optimize panel, for the molecules a force field has no "
                    "parameters for - metal complexes above all. Needs MOPAC "
                    "installed; the methods only appear when it is found."),
    "version": (1, 0),
    "author": "MoloM",
    "api": 1,
}

#: QSettings key holding a path the user picked by hand, same pattern as the
#: Blender and ffmpeg hints (rounds 50 and 61).
SETTINGS_KEY = "addons/mopac/path"

#: The Hamiltonians offered, newest first. PM7 is the default because it is
#: the current one and is parameterised for most of the periodic table
#: including the transition metals, which is the case that brings anyone here.
HAMILTONIANS = [
    ("mopac_pm7", "MOPAC PM7", "PM7"),
    ("mopac_pm6", "MOPAC PM6", "PM6"),
    ("mopac_am1", "MOPAC AM1", "AM1"),
    ("mopac_mndo", "MOPAC MNDO", "MNDO"),
]

#: A semiempirical optimisation on a big molecule is minutes, not seconds, so
#: the timeout is generous - but it is not absent, because a job that never
#: returns would hold the worker thread for the rest of the session.
DEFAULT_TIMEOUT_S = 900.0


class MopacNotFound(forcefield.ForceFieldError):
    """No MOPAC binary could be located."""


# --------------------------------------------------------------- discovery
def _settings_hint():
    """Whatever path the user last pointed us at, or None.

    Imported lazily so the discovery helpers below can be exercised from a
    plain pytest with no QApplication, and so a headless embedder that never
    builds a window pays nothing for it.
    """
    try:
        from PySide6.QtCore import QSettings
    except Exception:
        return None
    try:
        value = QSettings("MoloM", "MoloM").value(SETTINGS_KEY, "")
    except Exception:
        return None
    return str(value) if value else None


def mopac_candidates(hint=None):
    """Every path worth trying, best first.

    Same shape as `blender_export.find_blender` and
    `animation.ffmpeg_candidates` (rounds 50 and 61): an explicit hint wins,
    then PATH, then the usual install locations. Conda comes before the
    Windows installer because someone who has both almost certainly wants the
    one in the environment they are running MoloM from.
    """
    out = []

    def add(path):
        if path and path not in out:
            out.append(path)

    add(hint)
    add(_settings_hint())
    for name in ("mopac", "MOPAC", "mopac.exe", "MOPAC2016.exe"):
        add(shutil.which(name))
    # The conda environment this interpreter is running in.
    prefix = os.path.dirname(os.path.abspath(sys.executable))
    for rel in ("mopac", "mopac.exe",
                os.path.join("Library", "bin", "mopac.exe"),
                os.path.join("bin", "mopac")):
        add(os.path.join(prefix, rel))
    for root in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                 os.environ.get("ProgramFiles(x86)", ""),
                 "/usr/local", "/usr", "/opt"):
        if not root:
            continue
        for rel in (
                # The openmopac installer's own layout, measured on this
                # machine: C:\Program Files\MOPAC\bin\mopac.exe. The `bin`
                # level is easy to leave out and then discovery finds nothing
                # on a perfectly ordinary default install.
                os.path.join("MOPAC", "bin", "mopac.exe"),
                os.path.join("MOPAC", "bin", "mopac"),
                os.path.join("MOPAC", "mopac.exe"),
                os.path.join("MOPAC", "MOPAC2016.exe"),
                os.path.join("mopac", "bin", "mopac"),
                os.path.join("mopac", "mopac"),
                os.path.join("bin", "mopac")):
            add(os.path.join(root, rel))
    return [p for p in out if p and os.path.isfile(p)]


def find_mopac(hint=None):
    """The MOPAC executable to use, or None. Never raises: a missing MOPAC is
    an ordinary state, not an error."""
    found = mopac_candidates(hint)
    return found[0] if found else None


# ------------------------------------------------------------------- input
def build_input(symbols, coords, keywords, fixed=None, title="MoloM"):
    """A MOPAC input deck as text.

    THE FROZEN ATOMS ARE THE POINT. MOPAC carries a per-COORDINATE
    optimisation flag in the geometry block - 1 to optimise, 0 to hold - so
    `fixed` maps onto the format directly instead of being bolted on through a
    constraint object. That matters more here than anywhere else in MoloM:
    round 62 found that `_openbabel_optimize` ignored `fixed` entirely, and
    OpenBabel UFF is precisely the tier every metal complex fell through to,
    so the one case that most needed frozen atoms was the one case that never
    got them. A meta atom's locked coordination sphere reaches MOPAC as real
    constraints.
    """
    frozen = set(int(i) for i in (fixed or []))
    lines = [str(keywords), str(title), ""]
    xyz = np.asarray(coords, dtype=float).reshape(-1, 3)
    for i, sym in enumerate(symbols):
        flag = 0 if i in frozen else 1
        x, y, z = xyz[i]
        lines.append("{:<3s} {:14.8f} {:d} {:14.8f} {:d} {:14.8f} {:d}".format(
            str(sym), x, flag, y, flag, z, flag))
    lines.append("")
    return "\n".join(lines)


def build_keywords(hamiltonian="PM7", charge=0, multiplicity=1, steps=None,
                   extra=""):
    """The keyword line.

    `PRECISE` is deliberately NOT on by default: it tightens the gradient norm
    several-fold and this is a builder's clean-up step, not a publication
    geometry - the user who wants it can add it in the extra field. Charge and
    spin are stated explicitly because a metal complex is very often neither
    neutral nor a singlet, and MOPAC's default of both would optimise a
    different molecule from the one on screen.
    """
    words = [str(hamiltonian)]
    if int(charge):
        words.append("CHARGE={:d}".format(int(charge)))
    spin = {2: "DOUBLET", 3: "TRIPLET", 4: "QUARTET", 5: "QUINTET",
            6: "SEXTET", 7: "SEPTET"}.get(int(multiplicity or 1))
    if spin:
        words.append(spin)
    if steps:
        words.append("CYCLES={:d}".format(int(steps)))
    if extra:
        words.append(str(extra))
    return " ".join(words)


# ------------------------------------------------------------------ output
def read_output_geometry(path, timeout=60.0):
    """Optimised coordinates out of a MOPAC .out file.

    Read through OPENBABEL'S `mopout` reader, driven by MoloM's own
    `_obabel_worker` subprocess, rather than by a parser written here. Two
    reasons, and the second is this project's own rule. OpenBabel's reader is
    C++ that has been pointed at MOPAC output for twenty years and handles the
    format's variants; and CLAUDE.md says never to write a parser fixture from
    memory, which is exactly what a hand-rolled reader for a format I cannot
    run would require. Reusing the worker also inherits its timeout guard, the
    reason round 1 put OpenBabel in a subprocess at all.

    Returns (symbols, coords). The LAST record is the one that matters: MOPAC
    writes the geometry repeatedly as it goes, so the final block is the
    converged one.
    """
    from molom.core import io as io_mod      # absolute: see the header import
    structs, err = io_mod._read_with_openbabel(path, "mopout", timeout=timeout)
    if not structs:
        raise forcefield.ForceFieldError(
            "MOPAC finished but its output could not be read: {}".format(
                err or "no structures in the file"))
    atoms = structs[-1][0]
    symbols = [a[0] for a in atoms]
    coords = np.array([[a[1], a[2], a[3]] for a in atoms], dtype=float)
    return symbols, coords


def read_heat_of_formation(text):
    """Heat of formation in kcal/mol, or None.

    Deliberately tolerant and deliberately optional: it is reported to the
    user as information and nothing downstream depends on it, so a MOPAC build
    that words the line differently costs a label rather than the geometry.
    """
    value = None
    for line in text.splitlines():
        if "HEAT OF FORMATION" in line.upper():
            for token in line.replace("=", " ").split():
                try:
                    value = float(token)
                except ValueError:
                    continue
                else:
                    break
    return value


# ------------------------------------------------------------------- run it
def run_deck(symbols, coords, keywords, fixed=None, executable=None,
             timeout=DEFAULT_TIMEOUT_S, workdir=None, title="MoloM"):
    """Run one MOPAC job and return `(out_path, text, folder)`.

    Split out so an optimisation and a FORCE run share exactly one invocation
    path - the input writing, the timeout, the "did it produce an output at
    all" check and the error wording are things that must not drift between
    two calculation types. The caller owns `folder` when it passed `workdir`.
    """
    exe = executable or find_mopac()
    if not exe:
        raise MopacNotFound(
            "MOPAC was not found. Install it (conda install -c conda-forge "
            "mopac, or the installer from github.com/openmopac/mopac) or set "
            "the path in Preferences > Add-ons.")
    deck = build_input(symbols, coords, keywords, fixed=fixed, title=title)
    folder = workdir or tempfile.mkdtemp(prefix="molom_mopac_")
    stem = os.path.join(folder, "job")
    with open(stem + ".mop", "w", encoding="ascii", errors="replace") as fh:
        fh.write(deck)
    try:
        proc = subprocess.run([exe, stem + ".mop"], stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, timeout=timeout,
                              cwd=folder, **io_mod.quiet_subprocess_kwargs())
    except subprocess.TimeoutExpired:
        raise forcefield.ForceFieldError(
            "MOPAC did not finish within {:.0f} s.".format(timeout))
    except OSError as e:
        raise forcefield.ForceFieldError(
            "could not run MOPAC at {}: {}".format(exe, e))
    out_path = stem + ".out"
    if not os.path.isfile(out_path):
        tail = (proc.stderr or proc.stdout or b"").decode(
            "utf-8", "replace").strip()
        raise forcefield.ForceFieldError(
            "MOPAC wrote no output file{}".format(
                ": " + tail[:200] if tail else ""))
    text = open(out_path, encoding="utf-8", errors="replace").read()
    return out_path, text, folder


def run_frequencies(symbols, coords, fixed=None, hamiltonian="PM7", charge=0,
                    multiplicity=1, optimise_first=True, executable=None,
                    timeout=DEFAULT_TIMEOUT_S):
    """A FORCE job. Returns `(symbols, coords, modes, info)`.

    **It optimises first by default, and that is chemistry rather than
    convenience.** `FORCE` computes the Hessian AT THE GEOMETRY IT IS GIVEN,
    and a Hessian at a point that is not stationary has imaginary frequencies
    that mean nothing - they are an artefact of the gradient, not a transition
    state. MOPAC's own shipped example is a FORCE run "of a relaxed water
    molecule" for exactly this reason. Pass `optimise_first=False` when the
    geometry is already a stationary point and you want the Hessian there,
    which is also how you would look at a real transition state.

    The modes come back parsed by `core.vibrations`, so everything the
    ∿ page already does with an ORCA job works on these unchanged.
    """
    from molom.core import vibrations as vib

    symbols = list(symbols)
    xyz = np.asarray(coords, dtype=float).reshape(-1, 3)
    notes = []
    folder = tempfile.mkdtemp(prefix="molom_mopac_")
    try:
        if optimise_first:
            xyz, opt_info = run_mopac(symbols, xyz, fixed=fixed,
                                      hamiltonian=hamiltonian, charge=charge,
                                      multiplicity=multiplicity,
                                      executable=executable, timeout=timeout)
            notes += list(opt_info.get("notes", []))
        keywords = build_keywords(hamiltonian, charge, multiplicity,
                                  extra="FORCE")
        _path, text, _folder = run_deck(symbols, xyz, keywords, fixed=fixed,
                                        executable=executable,
                                        timeout=timeout, workdir=folder)
        modes = vib.parse_mopac_frequencies(text, n_atoms=len(symbols))
        imaginary = [m for m in modes if m.is_imaginary]
        if imaginary:
            # Reported, never hidden: an imaginary mode after an optimisation
            # says the structure is a saddle point, which is a fact about the
            # molecule and often the most interesting thing in the output.
            notes.append("{} imaginary mode(s) - this is a saddle point, not "
                         "a minimum".format(len(imaginary)))
        heat = read_heat_of_formation(text)
        info = {"engine": "mopac", "method": hamiltonian,
                "energy": heat if heat is not None else 0.0,
                "converged": True, "notes": notes}
        return symbols, xyz, modes, info
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def run_mopac(symbols, coords, bonds=None, steps=None, fixed=None,
              hamiltonian="PM7", charge=0, multiplicity=1, extra="",
              executable=None, timeout=DEFAULT_TIMEOUT_S, workdir=None):
    """Optimise with MOPAC. Returns `(coords, info)`, matching `optimize`.

    `bonds` is accepted and ignored: a semiempirical Hamiltonian derives its
    own bonding from the nuclei and the electrons, which is rather the point of
    reaching for one. It stays in the signature so this is drop-in wherever
    `forcefield.optimize` is.
    """
    exe = executable or find_mopac()
    if not exe:
        raise MopacNotFound(
            "MOPAC was not found. Install it (conda install -c conda-forge "
            "mopac, or the installer from github.com/openmopac/mopac) or set "
            "the path in Preferences > Add-ons.")
    symbols = list(symbols)
    xyz = np.asarray(coords, dtype=float).reshape(-1, 3)
    keywords = build_keywords(hamiltonian, charge, multiplicity, steps, extra)
    deck = build_input(symbols, xyz, keywords, fixed=fixed)

    own_dir = workdir is None
    folder = workdir or tempfile.mkdtemp(prefix="molom_mopac_")
    try:
        stem = os.path.join(folder, "job")
        with open(stem + ".mop", "w", encoding="ascii", errors="replace") as fh:
            fh.write(deck)
        try:
            proc = subprocess.run([exe, stem + ".mop"],
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, timeout=timeout,
                                  cwd=folder,
                                  **io_mod.quiet_subprocess_kwargs())
        except subprocess.TimeoutExpired:
            raise forcefield.ForceFieldError(
                "MOPAC did not finish within {:.0f} s.".format(timeout))
        except OSError as e:
            raise forcefield.ForceFieldError(
                "could not run MOPAC at {}: {}".format(exe, e))
        out_path = stem + ".out"
        if not os.path.isfile(out_path):
            tail = (proc.stderr or proc.stdout or b"").decode(
                "utf-8", "replace").strip()
            raise forcefield.ForceFieldError(
                "MOPAC wrote no output file{}".format(
                    ": " + tail[:200] if tail else ""))
        text = open(out_path, encoding="utf-8", errors="replace").read()
        new_symbols, new_coords = read_output_geometry(out_path)
        # THE ATOM ORDER IS THE CONTRACT. Everything upstream - the bonds, the
        # selection, per-atom colours, the meta table - is keyed by index, so a
        # reader that dropped or reordered an atom would silently rewire the
        # molecule. Checked rather than assumed, and refused rather than
        # patched up, because there is no honest way to guess the mapping.
        if len(new_coords) != len(xyz):
            raise forcefield.ForceFieldError(
                "MOPAC returned {} atoms for a {}-atom molecule".format(
                    len(new_coords), len(xyz)))
        if [s.upper() for s in new_symbols] != [s.upper() for s in symbols]:
            raise forcefield.ForceFieldError(
                "MOPAC returned the atoms in a different order")
        notes = []
        upper = text.upper()
        converged = "SCF FIELD WAS ACHIEVED" in upper or \
            "GEOMETRY OPTIMISED" in upper or "GEOMETRY OPTIMIZED" in upper
        if "EXCESS NUMBER OF OPTIMIZATION CYCLES" in upper or \
                "NOT ENOUGH TIME" in upper:
            notes.append("MOPAC stopped on its cycle limit - raise Max steps")
            converged = False
        if fixed:
            moved = float(np.max(np.linalg.norm(
                new_coords[list(fixed)] - xyz[list(fixed)], axis=1))) \
                if len(fixed) else 0.0
            if moved > 1e-6:
                notes.append("frozen atoms moved {:.4f} A".format(moved))
        heat = read_heat_of_formation(text)
        info = {"engine": "mopac", "method": hamiltonian,
                "energy": heat if heat is not None else 0.0,
                "converged": bool(converged), "notes": notes}
        if heat is not None:
            info["notes"] = notes + [
                "heat of formation {:.3f} kcal/mol".format(heat)]
        return new_coords, info
    finally:
        if own_dir:
            shutil.rmtree(folder, ignore_errors=True)


# ------------------------------------------------------------ registration
def _active_charge_and_spin(window):
    """(charge, multiplicity) of the molecule being optimised.

    A force field does not ask, so `forcefield.optimize`'s signature does not
    carry them - but a Hamiltonian must: a cationic iron complex optimised as
    a neutral singlet is a different species, converging confidently on the
    wrong geometry. `Structure` already reads both off its metadata, so the
    add-on takes them from the active object rather than inventing a second
    place for the user to state them.

    Read from the WORKER thread, which is safe here in the narrow sense that
    matters: two ints, read and never written, while the panel has disabled
    Start for the duration of the run. If MoloM ever grows a way to edit the
    charge mid-optimisation this has to be captured on the GUI thread instead.
    """
    try:
        obj = window.scene.get(window.viewport.active_obj_id)
        s = obj.structure
        return int(s.charge), int(s.multiplicity)
    except Exception:
        return 0, 1


def _make(hamiltonian, window):
    def optimise(symbols, coords, bonds, steps=None, fixed=None):
        charge, spin = _active_charge_and_spin(window)
        return run_mopac(symbols, coords, bonds, steps=steps, fixed=fixed,
                         hamiltonian=hamiltonian, charge=charge,
                         multiplicity=spin)
    optimise.__name__ = "mopac_{}".format(hamiltonian.lower())
    return optimise


FREQ_OP_ID = "mopac_frequencies"


def _run_frequencies_op(window):
    """F3: optimise the active molecule and compute its normal modes.

    Off the GUI thread, for the same reason `OptimizeWorker` exists: a FORCE
    calculation is a Hessian, which on anything past a few dozen atoms is
    minutes rather than seconds, and a frozen window looks like a crash.
    """
    from PySide6.QtCore import QThread, Signal

    obj = window._active_obj()
    if obj is None:
        window.statusBar().showMessage("Select a molecule first", 4000)
        return
    s = obj.structure
    if s.n_atoms < 2:
        window.statusBar().showMessage("Nothing to vibrate", 4000)
        return

    class _FreqWorker(QThread):
        done = Signal(object, object)          # (modes, info) or (None, error)

        def __init__(self, args, parent=None):
            super().__init__(parent)
            self._args = args

        def run(self):
            symbols, coords, charge, spin = self._args
            try:
                _sym, _xyz, modes, info = run_frequencies(
                    symbols, coords, charge=charge, multiplicity=spin)
            except Exception as e:
                self.done.emit(None, "{}: {}".format(type(e).__name__, e))
                return
            self.done.emit(modes, info)

    obj_id = obj.id
    running = getattr(window, "_mopac_freq_jobs", None) or {}
    if obj_id in running:
        window.statusBar().showMessage(
            "{} already has a frequency job running".format(obj.name), 5000)
        return
    charge, spin = _active_charge_and_spin(window)
    worker = _FreqWorker((list(s.symbols), s.coords.copy(), charge, spin),
                         window)

    def finished(modes, info):
        if modes is None:
            window.statusBar().showMessage("MOPAC: {}".format(info), 10000)
            return
        # Straight into the machinery the ORCA path already uses - the modes
        # are `vibrations.Mode`, so the page, the baked animation and the
        # selection ranking need to know nothing about where they came from.
        # `set_modes` also registers them as an ATTACHMENT, which is what puts
        # the molecule under overwrite protection and gets them marked
        # unphysical if it is edited afterwards.
        obj = window.scene.get(obj_id)
        if obj is None:
            return
        window.set_modes(obj, modes, detail="{} modes, MOPAC {}".format(
            len(modes), info.get("method", "PM7")))
        window.properties.setVisible(True)
        window.properties.show_page("vibrations")
        window._sync_vibration_page()
        real = [m for m in modes if not m.is_trivial]
        window.statusBar().showMessage(
            "MOPAC {}: {} modes ({} vibrational){} - pick one in the "
            "∿ page".format(
                info.get("method", "PM7"), len(modes), len(real),
                "; " + "; ".join(info["notes"]) if info.get("notes") else ""),
            12000)

    worker.done.connect(finished)
    # Held on the window PER MOLECULE, not in a single slot. One attribute
    # meant starting a second job dropped the only Python reference to the
    # first, so its QThread could be collected mid-run - the classic way a
    # QThread dies silently, and exactly what Christian asked about ("could it
    # lead to issues if multiple mols are selected and calcs started
    # simultaneously?"). Each job also gets its own scratch directory, so two
    # running at once cannot read each other's output.
    jobs = getattr(window, "_mopac_freq_jobs", None)
    if jobs is None:
        jobs = {}
        window._mopac_freq_jobs = jobs
    jobs[obj_id] = worker
    worker.finished.connect(lambda: jobs.pop(obj_id, None))
    # Tell the window, so the ∿ page can show a busy bar for THIS molecule.
    if hasattr(window, "freq_job_started"):
        window.freq_job_started(obj_id, "MOPAC PM7")
        worker.finished.connect(lambda: window.freq_job_finished(obj_id))
    window.statusBar().showMessage(
        "MOPAC: optimising, then computing the Hessian...", 0)
    worker.start()


def register(window):
    """Add the Hamiltonians to the Optimize panel's Method list.

    Registered even when no binary is present, and the reason is a UI one: a
    method that silently is not there teaches nobody that MOPAC exists, while
    one that is there and says "MOPAC was not found, install it or set the
    path" is a signpost. That is round 61's `NO_FFMPEG_HELP` rule - a message
    that only lists what is broken reads as a dead end, so it names the fix.
    """
    for key, label, hamiltonian in HAMILTONIANS:
        forcefield.register_method(key, label,
                                   _make(hamiltonian, window))
    panel = getattr(window, "optimize_panel", None)
    if panel is not None and hasattr(panel, "refresh_methods"):
        panel.refresh_methods()
    if hasattr(window, "register_frequency_provider"):
        window.register_frequency_provider(
            "MOPAC PM7", lambda w: _run_frequencies_op(w))
    ops = getattr(window, "ops", None)
    if ops is not None and ops.get(FREQ_OP_ID) is None:
        ops.register(
            FREQ_OP_ID, "MOPAC: vibrational frequencies (FORCE)",
            lambda: _run_frequencies_op(window),
            enabled=lambda ctx: window._active_obj() is not None,
            category="Compute",
            aliases=("normal modes", "ir spectrum", "hessian", "vibrations"))


def unregister(window):
    for key, _label, _h in HAMILTONIANS:
        forcefield.unregister_method(key)
    panel = getattr(window, "optimize_panel", None)
    if panel is not None and hasattr(panel, "refresh_methods"):
        panel.refresh_methods()
    if hasattr(window, "unregister_frequency_provider"):
        window.unregister_frequency_provider("MOPAC PM7")
    ops = getattr(window, "ops", None)
    if ops is not None:
        ops.unregister(FREQ_OP_ID)
