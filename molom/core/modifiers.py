"""Non-destructive modifier stack (Blender's model, chemistry edition).

A modifier does not touch the molecule's atoms: it produces a DERIVED
structure that the viewport draws and the exporter writes, while editing,
picking and the force field keep working on the small base molecule. That
distinction is the whole point — an adsorption surface can be 40x40 unit
cells on screen and export as 3200 atoms while you still edit the one unit
cell that generates it.

Only the array modifier for now. `apply` on the object bakes the result into
real atoms and drops the modifier, exactly like Blender's Apply.
"""

from typing import List, Optional, Tuple

import numpy as np


class Modifier:
    """Base: name, on/off, and a transform from one geometry to another."""

    kind = "modifier"

    def __init__(self, name="", enabled=True):
        self.name = name or self.kind
        self.enabled = bool(enabled)

    def evaluate(self, symbols, coords, bonds):
        raise NotImplementedError

    def to_dict(self):
        return {"kind": self.kind, "name": self.name,
                "enabled": self.enabled}


class ArrayModifier(Modifier):
    """`count` copies displaced by a constant offset.

    Offsets are in Angstrom (`relative=False`) or in multiples of the
    molecule's bounding-box size along each axis (`relative=True`), which is
    what makes "one unit cell -> a slab" a two-number operation.
    """

    kind = "array"

    def __init__(self, count=3, offset=(5.0, 0.0, 0.0), relative=False,
                 name="", enabled=True):
        super().__init__(name or "Array", enabled)
        self.count = max(1, int(count))
        self.offset = np.asarray(offset, dtype=float).reshape(3)
        self.relative = bool(relative)

    def step(self, coords):
        # type: (np.ndarray) -> np.ndarray
        """The world-space displacement between neighbouring copies."""
        if not self.relative:
            return self.offset.copy()
        pts = np.asarray(coords, dtype=float).reshape(-1, 3)
        if pts.size == 0:
            return self.offset.copy()
        size = pts.max(axis=0) - pts.min(axis=0)
        return self.offset * size

    def evaluate(self, symbols, coords, bonds):
        # type: (List[str], np.ndarray, List) -> Tuple[List[str], np.ndarray, List]
        n = len(symbols)
        if self.count <= 1 or n == 0:
            return list(symbols), np.asarray(coords, dtype=float), list(bonds)
        base = np.asarray(coords, dtype=float).reshape(n, 3)
        d = self.step(base)
        out_sym, out_xyz, out_bonds = [], [], []
        for k in range(self.count):
            out_sym += list(symbols)
            out_xyz.append(base + d * k)
            out_bonds += [(i + k * n, j + k * n, o) for i, j, o in bonds]
        return out_sym, np.vstack(out_xyz), out_bonds

    def to_dict(self):
        d = super().to_dict()
        d.update({"count": self.count, "offset": [float(v) for v in self.offset],
                  "relative": self.relative})
        return d


_KINDS = {"array": ArrayModifier}


def from_dict(d):
    # type: (dict) -> Optional[Modifier]
    cls = _KINDS.get(d.get("kind"))
    if cls is None:
        return None
    if cls is ArrayModifier:
        return ArrayModifier(d.get("count", 3), d.get("offset", (5, 0, 0)),
                             d.get("relative", False), d.get("name", ""),
                             d.get("enabled", True))
    return None


def evaluate_stack(modifiers, symbols, coords, bonds):
    # type: (List[Modifier], List[str], np.ndarray, List) -> Tuple[List[str], np.ndarray, List]
    """Run the enabled modifiers in order. Returns fresh lists/arrays; the
    inputs are never modified."""
    sym = list(symbols)
    xyz = np.asarray(coords, dtype=float).reshape(len(symbols), 3).copy()
    bnd = list(bonds)
    for mod in modifiers or ():
        if mod.enabled:
            sym, xyz, bnd = mod.evaluate(sym, xyz, bnd)
    return sym, xyz, bnd


def stack_is_active(modifiers):
    # type: (Optional[List[Modifier]]) -> bool
    return any(m.enabled for m in (modifiers or ()))
