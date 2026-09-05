"""A relaxed surface scan, previewed as frames MoloM can already play.

Christian: "If I want a more visual way of showing what a restraint/scan in
ORCA will do, I think it would be good to see it animated within molom."

**IT IS A FEW LINES ON TOP OF WHAT WAS ALREADY THERE, which is why it is
worth having.** `internal.apply` already steps a bond, an angle or a torsion
and carries the trailing fragment rigidly; `forcefield.optimize` already
takes a list of atoms to hold still; `Structure.frames` and the scene clock
already animate a list of geometries. So a scan preview is: walk the
coordinate over its range, and at each stop let the force field relax
everything the scan is not holding.

**WHAT IT IS AND IS NOT.** It is the same SHAPE of calculation ORCA runs -
one geometry per scan point, the scanned coordinate held, the rest relaxed -
at force-field level. It is not a substitute for the ORCA job and cannot be:
MMFF94 has no transition states, no bond breaking worth the name, and no
electronic structure at all. What it answers is the question you ask before
submitting anything - which atoms move, how far, and does the thing fold
into itself halfway through - and that question does not need DFT.

**EACH STEP CONTINUES FROM THE LAST**, which is what makes it a relaxed
SCAN rather than a row of independent optimisations. ORCA does the same, and
for the same reason: the previous converged geometry is the best starting
guess for the next one, and starting each point from the original structure
would let the relaxation fall into a different basin partway along and put a
discontinuity in the middle of what should be a smooth path.

**CONNECTIVITY IS FROZEN by default**, which is round 57's rule reaching a
new place. The preview exists to show MOTION, and MoloM's bond perception is
a distance rule rather than a bond-breaking criterion - so a stick that
blinks out halfway along a stretch is a distraction from the thing being
looked at rather than a statement about chemistry. `fixed_bonds=False` gets
the live perception back for a dissociation scan, where the disappearance is
the point.

Nothing here knows about Qt.
"""

from typing import Callable, List, Optional, Sequence, Tuple  # noqa: F401

import numpy as np

from . import forcefield
from . import internal
from . import orca as orca_mod

#: How hard to relax at each point. A scan point does not need a tight
#: minimum - it needs to be settled enough that the NEXT point starts
#: somewhere sensible - and the count is multiplied by the number of points,
#: so this is the knob that decides whether a preview takes one second or
#: thirty.
DEFAULT_RELAX_STEPS = 200


class ScanError(ValueError):
    """The scan cannot be previewed."""


def scan_frames(symbols, coords, bonds, scan_item, constraints=(),
                method=None, relax=True, relax_steps=DEFAULT_RELAX_STEPS,
                progress=None):
    # type: (...) -> Tuple[List[np.ndarray], dict]
    """`(frames, info)` - one geometry per scan point, in order.

    `frames[0]` is the structure at the scan's START value, which is NOT
    necessarily the geometry handed in: a scan that starts somewhere other
    than where the coordinate currently sits has to move it there first, and
    quietly showing the original as frame 0 would put a jump between the
    first two pictures.

    `info` carries the engine that was used, the value actually reached at
    each point, and any note worth surfacing - a relaxation that had to be
    skipped above all, because a preview that silently stopped relaxing is a
    rigid scan wearing a relaxed one's label.
    """
    coords = np.asarray(coords, dtype=float).reshape(-1, 3)
    symbols = list(symbols)
    kind = orca_mod.scan_kind(scan_item)
    picks = [int(a) for a in scan_item.get("atoms") or ()]
    targets = orca_mod.scan_points(scan_item)
    frozen = orca_mod.frozen_atoms(scan_item, constraints)
    moving, blocked = internal.split_for(kind, len(symbols), bonds, picks)
    notes = []
    if blocked:
        # `moving_group` refuses when the two ends are in one ring, because
        # pulling them apart would have to break a second bond. Only the
        # picked atom moves then, and the relaxation is what makes the rest
        # of the ring follow - so the preview still works and is worth
        # saying out loud, since the step is no longer rigid.
        notes.append("the coordinate is inside a ring, so only the picked "
                     "atom is moved and the rest follows the relaxation")
    # CAN THE COORDINATE MOVE AT ALL? For a blocked DIHEDRAL it cannot: the
    # only atom `moving_group` allows to move is `picks[2]`, which lies ON
    # the j-k rotation axis, so rotating it about that axis moves it nowhere
    # and every frame comes out identical. Measured on cubane, where a
    # dihedral scan reported 180 degrees of drift and thirteen identical
    # pictures. A bond or an angle in a ring is fine - the one mover is off
    # the axis in both - so this is checked rather than assumed, by trying it.
    _refuse_if_stuck(kind, coords, moving, picks, targets)
    frames, reached, energies = [], [], []
    engine = "rigid"
    current = coords.copy()
    for k, target in enumerate(targets):
        stepped = internal.apply(kind, current, moving, picks, float(target))
        if relax:
            try:
                stepped, run = forcefield.optimize(
                    symbols, stepped, bonds,
                    **_kwargs(method, relax_steps, frozen))
                engine = run.get("engine", engine)
                energies.append(float(run.get("energy", 0.0)))
                for note in run.get("notes") or ():
                    if note not in notes:
                        notes.append(note)
            except forcefield.ForceFieldError as exc:
                # A force field with no parameters for this chemistry is an
                # ordinary outcome - a metal complex is the common case - and
                # a rigid preview is still worth having. What must not happen
                # is it being called relaxed.
                relax = False
                notes.append("no force field would take this structure ({}), "
                             "so the rest of the scan is rigid".format(exc))
        current = np.asarray(stepped, dtype=float).reshape(-1, 3)
        frames.append(current.copy())
        reached.append(float(internal.current_value(kind, current, picks)))
        if progress is not None:
            progress(k + 1, len(targets))
    # THE ENERGY PROFILE IS WHAT A RELAXED SCAN IS FOR, and the optimiser
    # already returns it, so not recording it would be throwing away the
    # answer while keeping the pictures. Relative to the lowest point,
    # because a force field's absolute energy means nothing on its own.
    if energies and len(energies) == len(frames):
        low = min(energies)
        info_energies = [e - low for e in energies]
    else:
        info_energies = []
    info = {"engine": engine if relax else "rigid",
            "energies": info_energies,
            "kind": kind, "atoms": picks, "targets": list(targets),
            "reached": reached, "frozen": frozen, "notes": notes,
            "unit": internal.unit_for(kind)}
    info["worst_error"] = _worst(targets, reached, kind)
    return frames, info


def _refuse_if_stuck(kind, coords, moving, picks, targets):
    """Raise if stepping the coordinate cannot change it.

    Tried rather than reasoned about: apply the largest step the scan asks
    for and see whether the value actually moves. That catches every
    degenerate case rather than the one that was thought of, and it costs one
    geometry operation.
    """
    here = internal.current_value(kind, coords, picks)
    far = max(targets, key=lambda t: abs(float(t) - here))
    if abs(float(far) - here) < 1e-9:
        return                                  # nothing is being asked for
    probe = internal.apply(kind, coords, moving, picks, float(far))
    got = internal.current_value(kind, probe, picks)
    if abs(got - here) < 1e-6:
        raise ScanError(
            "this {} cannot be scanned: it is inside a ring, so the only "
            "atom that may move lies on the axis it would turn about. Pick "
            "a coordinate with a rotatable bond in it, or scan a bond "
            "length instead.".format(internal.label_for(kind).lower()))


def _kwargs(method, steps, frozen):
    out = {"steps": int(steps), "fixed": list(frozen)}
    if method:
        out["method"] = method
    return out


def _worst(targets, reached, kind):
    """How far the geometry missed the value it was asked for, at worst.

    A relaxation with the scanned atoms frozen cannot move the coordinate, so
    this should be zero - and where it is not, something has quietly stopped
    holding the scan, which is exactly the failure a preview must not hide.
    Angles wrap, so the comparison does too.
    """
    worst = 0.0
    for want, got in zip(targets, reached):
        delta = float(got) - float(want)
        if kind in (internal.ANGLE, internal.DIHEDRAL):
            delta = (delta + 180.0) % 360.0 - 180.0
        worst = max(worst, abs(delta))
    return worst


def preview_note(info):
    # type: (dict) -> str
    """One line for the status bar."""
    bits = ["{} points, {} {} to {} {}".format(
        len(info["targets"]), _g(info["targets"][0]), info["unit"],
        _g(info["targets"][-1]), info["unit"])]
    bits.append("relaxed with {}".format(info["engine"])
                if info["engine"] != "rigid" else "rigid (not relaxed)")
    if info.get("worst_error", 0.0) > 1e-3:
        bits.append("the coordinate drifted by up to {} {}".format(
            _g(info["worst_error"]), info["unit"]))
    bits += list(info.get("notes") or ())
    return "; ".join(bits)


def _g(v):
    return "%g" % round(float(v), 4)
