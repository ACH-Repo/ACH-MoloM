"""Extra visualisation state hanging off a molecule - and what an edit does
to it.

An isosurface, a set of normal modes, a charge map: all of these are things
COMPUTED FOR ONE STRUCTURE and drawn on top of it. They are not atoms, so they
do not belong in `Structure`; they are per-molecule rather than per-atom, so
they do not belong in the outliner's element rows; and they can come from an
add-on, so core cannot know what they are.

**The two ways such a thing dies are different, and that is the whole design.**
Christian, 2026-08-17:

* An ISOSURFACE "is a property that belongs to a particular conformer that
  cannot be retained the moment anything changes about a mol even slightly. And
  it should be pretty easy to recalculate if it is lost." -> `POLICY_VOLATILE`:
  drop it, silently, on any edit. Keeping a surface that no longer matches the
  nuclei would draw a confident lie, and regenerating it is cheap.

* NORMAL MODES are not like that: "I might want to calculate the modes of a mol,
  but change some elements for the sake of a comparative visualisation in
  powerpoint that is not intended to be accurate. So there an edit should not
  get rid of modes, only declare itself as no longer physical in the GUI and in
  any potential export." -> `POLICY_FRAGILE`: keep it, mark it stale, and say
  so everywhere it is shown. Throwing away a twenty-minute calculation because
  somebody swapped an oxygen would be the worse failure.

So the policy is a property of the attachment, declared by whatever produced
it, and this module only applies it.

**Overwrite protection.** An object carrying any of this is LOCKED by default:
a chemistry edit is refused until the lock is off, which is the pattern ORCA
Workbench already uses (a tick box that must be cleared before the information
behind it can be altered). `needs_protection` is what keeps that off every
ordinary molecule - a lock on an object with nothing to lose is noise, and
noise is what teaches people to click through warnings.

UI-free: no Qt, no GL. The outliner draws what `attachments_of` returns and the
window asks `is_locked` before editing; neither decision is made here twice.
"""

from typing import Dict, List, Optional, Tuple

#: Cannot survive ANY change to the molecule, and is cheap to rebuild.
#: Dropped without ceremony - see the module docstring.
POLICY_VOLATILE = "volatile"

#: Survives an edit but stops being physical. Kept, flagged, and reported as
#: unphysical wherever it is drawn or exported.
POLICY_FRAGILE = "fragile"

#: What KIND of edit happened. A chemistry edit changes what the molecule IS
#: (an element, a bond, an atom added or removed); a geometry edit only moves
#: what is already there.
#:
#: Deliberately, a geometry edit does NOT stale a FRAGILE attachment. Moving a
#: whole molecule is the commonest gesture in the program and is a rigid
#: placement - the modes travel with it and remain exactly as valid. Dragging
#: one atom does invalidate them and is not caught here; that is a known gap
#: rather than an oversight, because the alternative is a warning on every
#: grab, which is a warning nobody reads (round 40's rule).
KIND_CHEMISTRY = "chemistry"
KIND_GEOMETRY = "geometry"


class Attachment(object):
    """One computed layer drawn over a molecule.

    `key` is stable and unique within the object (`"modes"`, `"mo_42"`), and is
    what an add-on uses to find its own again. `label` is what the outliner
    shows on the tick box, so it wants to be short.
    """

    def __init__(self, key, label, policy=POLICY_FRAGILE, visible=True,
                 stale=False, detail="", source="", toggleable=True):
        # type: (str, str, str, bool, bool, str, str, bool) -> None
        if policy not in (POLICY_VOLATILE, POLICY_FRAGILE):
            raise ValueError("unknown policy: {!r}".format(policy))
        self.key = str(key)
        self.label = str(label)
        self.policy = policy
        self.visible = bool(visible)
        self.stale = bool(stale)
        #: Free text for the tooltip - "24 modes, PM7" - so the tick box can
        #: stay short without the state becoming unreadable.
        self.detail = str(detail)
        #: Which add-on produced it, where one did. Empty for MoloM's own.
        self.source = str(source)
        #: Whether the row shows a TICK BOX or just a label.
        #:
        #: A drawn layer (an isosurface) can be switched off, so it gets a
        #: box. Normal modes cannot: they are a data source for the
        #: animation rather than something painted over the molecule, so a
        #: tick would have nothing to do - and a control that does nothing
        #: is the thing this project keeps finding as a bug. They still
        #: belong here, because the LOCK and the stale marking are exactly
        #: what they need.
        self.toggleable = bool(toggleable)

    def __repr__(self):
        return "Attachment({!r}, {}{})".format(
            self.key, self.policy, ", STALE" if self.stale else "")

    def to_dict(self):
        return {"key": self.key, "label": self.label, "policy": self.policy,
                "visible": self.visible, "stale": self.stale,
                "detail": self.detail, "source": self.source,
                "toggleable": self.toggleable}

    @classmethod
    def from_dict(cls, d):
        d = dict(d or {})
        return cls(d.get("key", ""), d.get("label", ""),
                   policy=d.get("policy", POLICY_FRAGILE),
                   visible=bool(d.get("visible", True)),
                   stale=bool(d.get("stale", False)),
                   detail=d.get("detail", ""), source=d.get("source", ""),
                   toggleable=bool(d.get("toggleable", True)))


def attachments_of(obj):
    # type: (object) -> Dict[str, Attachment]
    """Every attachment on `obj`, keyed. Empty for an ordinary molecule."""
    return getattr(obj, "attachments", None) or {}


def attach(obj, attachment):
    # type: (object, Attachment) -> Attachment
    """Add or replace one, and LOCK the object if this is its first.

    Locking on arrival rather than leaving it to the caller is what makes the
    protection a property of "this object has something to lose" instead of
    something each producer has to remember.
    """
    table = getattr(obj, "attachments", None)
    if table is None:
        table = {}
        obj.attachments = table
    first = not table
    table[attachment.key] = attachment
    if first:
        obj.edit_locked = True
    return attachment


def detach(obj, key):
    # type: (object, str) -> bool
    """Remove one. The lock is dropped with the last attachment, so an object
    that no longer has anything to protect stops asking to be unlocked."""
    table = getattr(obj, "attachments", None) or {}
    gone = table.pop(str(key), None) is not None
    if gone and not table:
        obj.edit_locked = False
    return gone


def note_edit(obj, kind=KIND_CHEMISTRY):
    # type: (object, str) -> Tuple[List[str], List[str]]
    """Apply the policies after an edit. Returns `(dropped, flagged)`.

    Call it AFTER the edit has happened - it describes consequences, it does
    not permit anything. Whether the edit was allowed at all is `is_locked`.
    """
    table = getattr(obj, "attachments", None) or {}
    dropped, flagged = [], []
    for key in sorted(table):
        att = table[key]
        if att.policy == POLICY_VOLATILE:
            dropped.append(key)
        elif kind == KIND_CHEMISTRY and not att.stale:
            att.stale = True
            flagged.append(key)
    for key in dropped:
        table.pop(key, None)
    if not table:
        obj.edit_locked = False
    return dropped, flagged


def needs_protection(obj):
    # type: (object) -> bool
    """Whether this object should show a lock at all.

    Only objects that actually carry something - Christian: "Only add overwrite
    protections to outliner objects that actually require them."
    """
    return bool(attachments_of(obj))


def is_locked(obj):
    # type: (object) -> bool
    """True when a chemistry edit should be refused until the user says
    otherwise. Always False where there is nothing to protect."""
    return bool(needs_protection(obj) and getattr(obj, "edit_locked", False))


def set_locked(obj, locked):
    # type: (object, bool) -> None
    obj.edit_locked = bool(locked)


def unphysical(obj):
    # type: (object) -> bool
    """Any attachment that no longer describes this structure."""
    return any(a.stale for a in attachments_of(obj).values())


def describe_stale(obj):
    # type: (object) -> Optional[str]
    """One phrase naming what has stopped being physical, or None.

    For the status bar, a tooltip and any EXPORT - Christian asked for the
    unphysical state to declare itself "in the GUI and in any potential
    export", and an export that quietly ships a stale overlay is round 38's
    silent-refusal problem wearing a different hat.
    """
    names = sorted(a.label for a in attachments_of(obj).values() if a.stale)
    if not names:
        return None
    joined = ", ".join(names)
    return ("{} no longer describes this structure - it was computed before "
            "the molecule was edited".format(joined) if len(names) == 1 else
            "{} no longer describe this structure - they were computed before "
            "the molecule was edited".format(joined))


def visible_attachments(obj):
    # type: (object) -> List[Attachment]
    """Those actually ticked on, in a stable order for drawing."""
    return [a for _k, a in sorted(attachments_of(obj).items()) if a.visible]
