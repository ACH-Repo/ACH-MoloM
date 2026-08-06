"""Non-destructive modifier stack (Blender's model, chemistry edition).

A modifier does not touch the molecule's atoms: it produces a DERIVED
structure that the viewport draws and the exporter writes, while editing,
picking and the force field keep working on the small base molecule. That
distinction is the whole point — an adsorption surface can be 40x40 unit
cells on screen and export as 3200 atoms while you still edit the one unit
cell that generates it.

Two so far: ARRAY (copies on a lattice) and SYMMETRY (a crystal's space-group
operations, so the base molecule stays the asymmetric unit you edit while the
viewport shows the full cell). `apply` on the object bakes the result into
real atoms and drops the modifier, exactly like Blender's Apply.
"""

from typing import List, Optional, Tuple

import numpy as np


class Modifier:
    """Base: name, on/off, and a transform from one geometry to another."""

    kind = "modifier"

    #: Whether `evaluate` takes the crystal's `pose` (see `evaluate_stack`).
    #: True only for modifiers that do FRACTIONAL-coordinate arithmetic, which
    #: is meaningless on atoms the user has rotated away from the cell frame.
    wants_pose = False

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


class SymmetryModifier(Modifier):
    """Apply a crystal's symmetry operations, non-destructively.

    The asym/cell/packing switch on the ❖ page REBUILDS the atom list, which
    means the asymmetric unit you were editing is gone until you switch back.
    As a modifier the base molecule stays the asymmetric unit — the thing you
    actually edit — while the viewport and the exporter see the full cell.
    That is the same bargain the array modifier makes for a slab.

    The cell and the operations come from the structure's metadata, so this
    modifier carries only the switches; it is not a place to store
    crystallography twice.
    """

    kind = "symmetry"

    def __init__(self, cell=None, symops=None, na=1, nb=1, nc=1,
                 name="", enabled=True, origin=None, exterior=0):
        super().__init__(name or "Symmetry", enabled)
        self.cell = cell                 # dict, as stored in metadata
        self.symops = list(symops or [])
        self.na, self.nb, self.nc = int(na), int(nb), int(nc)
        #: Shells of VESTA-style bonded-outside-the-cell atoms. 0 = off, the
        #: default, so an existing structure never changes under you.
        self.exterior = int(exterior)
        # WHERE the cell sits in world space. A CIF's cell starts at the
        # world origin and its atoms are already placed against it, so this
        # is zero there. It matters for a hand-built cell: a molecule sitting
        # ON the origin is mapped onto ITSELF by every operation through the
        # origin, so adding a 2-fold appears to do nothing at all.
        self.origin = (np.zeros(3) if origin is None
                       else np.asarray(origin, dtype=float).reshape(3))

    def evaluate(self, symbols, coords, bonds):
        from . import cif as cif_mod
        if not self.cell or not self.symops:
            return symbols, coords, bonds
        try:
            cell = cif_mod.Cell.from_dict(self.cell)
            ops = [cif_mod.SymOp.from_xyz(t) for t in self.symops]
        except (KeyError, TypeError, ValueError, cif_mod.CifError):
            return symbols, coords, bonds
        origin = np.asarray(self.origin, dtype=float).reshape(3)
        frac = cell.to_fractional(np.asarray(coords, dtype=float) - origin)
        out_symbols, out_coords = cif_mod.build_view(
            cell, list(symbols), frac, ops,
            mode="packing" if max(self.na, self.nb, self.nc) > 1 else "cell",
            na=self.na, nb=self.nb, nc=self.nc, exterior=self.exterior)
        if not out_symbols:
            return symbols, coords, bonds
        # Bonds are NOT carried: the copies are new atoms whose connectivity
        # is a perception job, and guessing it here would be wrong at the
        # cell faces anyway (see the framework note in core/cif.py).
        return out_symbols, np.asarray(out_coords) + origin, []

    def to_dict(self):
        d = super().to_dict()
        d.update({"cell": self.cell, "symops": list(self.symops),
                  "na": self.na, "nb": self.nb, "nc": self.nc,
                  "exterior": int(self.exterior),
                  "origin": [float(v) for v in self.origin]})
        return d


class BoundaryModifier(Modifier):
    """Close the bonds that cross a cell face — the periodic display bonds.

    Bond perception measures straight lines, so a bond whose partner is in the
    next cell is simply not drawn: a ZIF's imidazolate linkers come out severed
    at every face and the framework reads as a heap of loose fragments. On
    Christian's `2130205.cif` the connectivity really has 224 bonds and only
    196 of them were drawable; VESTA shows the same file as 276 atoms and 324
    bonds precisely because it materialises the partners.

    That is what this does, via `cif.bonded_exterior`: follow every bond that
    leaves the cell and add the periodic IMAGE at the far end, then bond to it.
    As a MODIFIER rather than a rebuild, the base structure stays exactly the
    cell content — so Z, the ❖ page's atom count, editing and export of the
    unit cell are all untouched — while the viewport (and the Blender export,
    which reads `evaluated()`) see a continuous framework.

    `shells` is how far to follow: 1 closes every bond that crosses a face,
    which is the honest minimum and matches VESTA's default. 2 also completes
    the group on the far side, which looks tidier on a linker.
    """

    kind = "boundary"

    def __init__(self, cell=None, shells=1, name="", enabled=True,
                 covalent_only=True, whole_molecules=True):
        super().__init__(name or "Boundary bonds", enabled)
        self.cell = cell                 # dict, as stored in metadata
        self.shells = max(1, int(shells))
        #: Follow COVALENT bonds only. A molecule cut by a cell face is what
        #: needs closing; a coordination bond is where a framework is meant to
        #: be cut, and following those as well turns rock salt's 9-atom cell
        #: into 59 without telling anyone anything new.
        self.covalent_only = bool(covalent_only)
        #: Bring the WHOLE molecule on the far side of a cut bond, not just
        #: the one atom that closes it. Half an imidazolate ring is not a
        #: thing that exists (the round-33 rule for boundary copies, applied
        #: to the same question one step further out).
        self.whole_molecules = bool(whole_molecules)
        self._cache_key = None
        self._cache = None

    wants_pose = True

    def evaluate(self, symbols, coords, bonds, pose=None):
        from . import bonding
        from . import cif as cif_mod
        if not self.cell or not len(symbols):
            return symbols, coords, bonds
        xyz = np.asarray(coords, dtype=float).reshape(len(symbols), 3)
        # EVERYTHING below is fractional-coordinate arithmetic against a cell
        # whose matrix is built in a canonical orientation, so it is only
        # meaningful on atoms that are still in the cell's own frame. Rotating
        # the crystal in the viewport used to change the answer — 2130205 went
        # from 216 drawn atoms to 230, 276 and 246 at 10, 37 and 90 degrees,
        # with nothing else touched, which is Christian's "not invariant under
        # rotation of the unit cell". Undo the pose, work, put it back.
        world = xyz
        if pose is not None:
            rot, shift = pose
            xyz = (xyz - np.asarray(shift)) @ np.asarray(rot)
        # Cached on the GEOMETRY, not per call: `evaluated()` runs on every
        # viewport rebuild, and re-deriving a framework's boundary each frame
        # is the round-33 mistake in a new place.
        key = (xyz.tobytes(), tuple(symbols), self.shells,
               self.covalent_only, self.whole_molecules,
               tuple(sorted(self.cell.items())))
        def to_world(local):
            """Cell frame -> the pose the atoms actually arrived in."""
            if pose is None:
                return local
            rot, shift = pose
            return np.asarray(local) @ np.asarray(rot).T + np.asarray(shift)

        if key == self._cache_key:
            return (self._cache[0], to_world(self._cache[1].copy()),
                    list(self._cache[2]))
        try:
            cell = cif_mod.Cell.from_dict(self.cell)
        except (KeyError, TypeError, ValueError, cif_mod.CifError):
            return symbols, coords, bonds
        frac = cell.to_fractional(xyz)
        if self.whole_molecules:
            ex_symbols, ex_frac = cif_mod.crossing_fragments(
                list(symbols), frac, cell)
        else:
            ex_symbols, ex_frac = cif_mod.bonded_exterior(
                list(symbols), frac, cell, depth=self.shells,
                covalent_only=self.covalent_only, finite_only=True)
        if not ex_symbols:
            return symbols, coords, bonds
        n = len(symbols)
        out_symbols = list(symbols) + list(ex_symbols)
        out_xyz = np.vstack([xyz, np.asarray(ex_frac) @ cell.matrix()])
        # The incoming bonds are kept EXACTLY as they are — they may carry
        # orders the user drew — and only the pairs that touch a new atom are
        # perceived. Re-perceiving everything would quietly undo bond edits.
        fresh = bonding.perceive_bonds(out_symbols, out_xyz)
        out_bonds = list(bonds) + [(i, j, o) for i, j, o in fresh
                                   if i >= n or j >= n]
        self._cache_key = key
        self._cache = (out_symbols, out_xyz, out_bonds)
        return out_symbols, to_world(out_xyz.copy()), list(out_bonds)

    def to_dict(self):
        d = super().to_dict()
        d.update({"cell": self.cell, "shells": int(self.shells),
                  "covalent_only": bool(self.covalent_only),
                  "whole_molecules": bool(self.whole_molecules)})
        return d


_KINDS = {"array": ArrayModifier, "symmetry": SymmetryModifier,
          "boundary": BoundaryModifier}


def from_dict(d):
    # type: (dict) -> Optional[Modifier]
    cls = _KINDS.get(d.get("kind"))
    if cls is None:
        return None
    if cls is ArrayModifier:
        return ArrayModifier(d.get("count", 3), d.get("offset", (5, 0, 0)),
                             d.get("relative", False), d.get("name", ""),
                             d.get("enabled", True))
    if cls is SymmetryModifier:
        return SymmetryModifier(d.get("cell"), d.get("symops"),
                                d.get("na", 1), d.get("nb", 1),
                                d.get("nc", 1), d.get("name", ""),
                                d.get("enabled", True),
                                d.get("origin"),
                                d.get("exterior", 0))
    if cls is BoundaryModifier:
        return BoundaryModifier(d.get("cell"), d.get("shells", 1),
                                d.get("name", ""), d.get("enabled", True),
                                d.get("covalent_only", True),
                                d.get("whole_molecules", True))
    return None


def evaluate_stack(modifiers, symbols, coords, bonds, pose=None):
    # type: (List[Modifier], List[str], np.ndarray, List, Optional[tuple]) -> Tuple[List[str], np.ndarray, List]
    """Run the enabled modifiers in order. Returns fresh lists/arrays; the
    inputs are never modified.

    `pose` is the rigid motion carrying the crystal's own frame onto the
    coordinates as they stand — `(R, t)` with `world = local @ R.T + t`, from
    `cif.rigid_from_reference`. Only modifiers declaring `wants_pose` are
    given it, because only they work in fractional coordinates.
    """
    sym = list(symbols)
    xyz = np.asarray(coords, dtype=float).reshape(len(symbols), 3).copy()
    bnd = list(bonds)
    for mod in modifiers or ():
        if not mod.enabled:
            continue
        if pose is not None and getattr(mod, "wants_pose", False):
            sym, xyz, bnd = mod.evaluate(sym, xyz, bnd, pose=pose)
        else:
            sym, xyz, bnd = mod.evaluate(sym, xyz, bnd)
    return sym, xyz, bnd


def stack_is_active(modifiers):
    # type: (Optional[List[Modifier]]) -> bool
    return any(m.enabled for m in (modifiers or ()))
