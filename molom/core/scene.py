"""Multi-molecule scene: the data model behind the Blender-style outliner.

A Scene holds MolObjects (a Structure + display state). Everything the
outliner shows lives here so it stays UI-free and testable: visibility,
per-object style override, unique Blender-style names ("water", "water.001").
Atom identity anywhere above this layer is a (obj_id, atom_index) pair.
"""

from typing import List, Optional, Tuple

import numpy as np

from . import elements, modifiers
from .camera import quat_identity, quat_to_mat3
from .structure import Structure


class MolObject:
    """One molecule in the scene, with a Blender-style local frame.

    `origin` (world point) + `orientation` (quat) define the object's LOCAL
    axes — what double-pressed axis locks (G/R "XX") and the N-panel
    transform refer to. Defaults: origin = centroid at add time, orientation
    = identity (a fresh object's local axes are the world axes)."""

    def __init__(self, obj_id, structure, name="", visible=True,
                 style_key=None):
        # type: (int, Structure, str, bool, Optional[str]) -> None
        self.id = obj_id
        self.structure = structure
        self.name = name or (structure.name or "molecule")
        self.visible = visible
        # None = follow the app-wide style; else a core.style key override.
        self.style_key = style_key
        self.origin = structure.centroid() if structure.n_atoms else np.zeros(3)
        self.orientation = quat_identity()
        self.modifiers = []          # non-destructive stack (core.modifiers)
        # Per-atom display overrides (the VESTA-style outliner writes these).
        # Sparse on purpose: an untouched atom costs nothing and keeps using
        # the element's colour and the object's label mode.
        self.atom_colors = {}        # idx -> (r, g, b) floats 0..1
        self.atom_labels = set()     # idx with a label switched on
        self.atom_label_text = {}    # idx -> custom label string
        self.atom_label_colors = {}  # idx -> (r, g, b) for the label text
        self.atom_label_modes = {}   # idx -> mode override
        self.label_mode = "element"  # element | index | element_index | custom

    def label_mode_for(self, index):
        # type: (int) -> str
        """Per-atom label mode, falling back to the molecule's."""
        return self.atom_label_modes.get(int(index), self.label_mode)

    def label_for(self, index):
        # type: (int) -> str
        """The label text for one atom under its effective mode."""
        i = int(index)
        mode = self.label_mode_for(i)
        if mode == "custom":
            return self.atom_label_text.get(i, "")
        sym = self.structure.symbols[i] if i < self.structure.n_atoms else "?"
        if mode == "index":
            return str(i)
        if mode == "element_index":
            return "{}{}".format(sym, i)
        return sym

    def evaluated(self):
        # type: () -> tuple
        """(symbols, coords, bonds) after the modifier stack. Display and
        export use this; editing, picking and the force field use the base
        structure, so a 3000-atom slab still edits like one unit cell."""
        s = self.structure
        if not modifiers.stack_is_active(self.modifiers):
            return s.symbols, s.coords, s.bonds
        return modifiers.evaluate_stack(self.modifiers, s.symbols, s.coords,
                                        s.bonds)

    def apply_modifiers(self):
        # type: () -> int
        """Bake the stack into real atoms and clear it. Returns the new atom
        count. Trajectory frames beyond the current one are dropped — a baked
        array has no meaningful correspondence to the original frames."""
        if not modifiers.stack_is_active(self.modifiers):
            return self.structure.n_atoms
        sym, xyz, bnd = self.evaluated()
        s = self.structure
        s.symbols = list(sym)
        s.frames = [np.asarray(xyz, dtype=float).reshape(len(sym), 3)]
        s.current_frame = 0
        s.bonds = list(bnd)
        self.modifiers = []
        return s.n_atoms

    def local_axes(self):
        # type: () -> np.ndarray
        """3x3 whose COLUMNS are the local X/Y/Z axes in world coords."""
        return quat_to_mat3(self.orientation)

    def __repr__(self):
        return "MolObject({}, {!r}, {} atoms)".format(
            self.id, self.name, self.structure.n_atoms)


class Scene:
    """Ordered collection of MolObjects with unique display names."""

    def __init__(self):
        self.objects = []          # type: List[MolObject]
        self._next_id = 1

    # -------------------------------------------------------------- lookup
    def get(self, obj_id):
        # type: (int) -> Optional[MolObject]
        for o in self.objects:
            if o.id == obj_id:
                return o
        return None

    def visible_objects(self):
        # type: () -> List[MolObject]
        return [o for o in self.objects if o.visible]

    @property
    def n_objects(self):
        return len(self.objects)

    # ------------------------------------------------------------- mutation
    def add(self, structure, name=""):
        # type: (Structure, str) -> MolObject
        base = (name or structure.name or "molecule").strip() or "molecule"
        obj = MolObject(self._next_id, structure, self.unique_name(base))
        self._next_id += 1
        self.objects.append(obj)
        return obj

    def duplicate(self, obj_id, rows=None):
        # type: (int, Optional[List[int]]) -> Optional[MolObject]
        """Copy an object — or just `rows` of its atoms — into a NEW object.

        Display settings and the local frame are inherited from the parent;
        the name gets the usual `.001` treatment. Bonds are carried over for
        the atoms that survive; a partial copy leaves dangling valences that
        the caller is expected to fix up (re-perceive + adjust hydrogens).
        """
        src = self.get(obj_id)
        if src is None:
            return None
        s = src.structure
        keep = (list(range(s.n_atoms)) if rows is None
                else sorted({int(i) for i in rows if 0 <= int(i) < s.n_atoms}))
        if not keep:
            return None
        remap = {old: new for new, old in enumerate(keep)}
        new_s = Structure([s.symbols[i] for i in keep],
                          s.frames[s.current_frame][keep],
                          name=s.name, metadata=dict(s.metadata))
        new_s.frames = [f[keep].copy() for f in s.frames]
        new_s.current_frame = s.current_frame
        new_s.bonds = [(remap[i], remap[j], o) for i, j, o in s.bonds
                       if i in remap and j in remap]
        obj = MolObject(self._next_id, new_s, self.unique_name(src.name),
                        src.visible, src.style_key)
        self._next_id += 1
        obj.origin = (src.origin.copy() if rows is None
                      else new_s.centroid())
        obj.orientation = src.orientation.copy()
        self.objects.append(obj)
        return obj

    def merge(self, obj_ids, name=None, keep_originals=True):
        # type: (List[int], Optional[str], bool) -> Optional[MolObject]
        """Combine several molecules into ONE new object, preserving every
        atom's world position and its bonds (reindexed).

        The point is force-field work on assemblies: two molecules
        pre-arranged into an H-bonded pair have to become a single object
        before an optimiser will see them as one system. Originals are kept
        by default (hidden by the caller if wanted) so the arrangement is not
        lost if the merge turns out wrong.
        """
        objs = [self.get(i) for i in obj_ids]
        objs = [o for o in objs if o is not None and o.structure.n_atoms]
        if len(objs) < 2:
            return None
        symbols, frames, bonds = [], [], []
        n_frames = min(o.structure.n_frames for o in objs)
        offset = 0
        for o in objs:
            s = o.structure
            symbols += list(s.symbols)
            bonds += [(i + offset, j + offset, k) for i, j, k in s.bonds]
            offset += s.n_atoms
        for f in range(n_frames):
            frames.append(np.vstack([o.structure.frames[f] for o in objs]))
        merged = Structure(symbols, frames[0],
                           name=name or "+".join(o.name for o in objs))
        merged.frames = frames
        merged.bonds = bonds
        obj = MolObject(self._next_id, merged, self.unique_name(merged.name),
                        True, objs[0].style_key)
        self._next_id += 1
        obj.origin = merged.centroid()
        self.objects.append(obj)
        if not keep_originals:
            for o in objs:
                self.remove(o.id)
        return obj

    def remove(self, obj_id):
        # type: (int) -> bool
        for k, o in enumerate(self.objects):
            if o.id == obj_id:
                self.objects.pop(k)
                return True
        return False

    def clear(self):
        self.objects = []

    def rename(self, obj_id, new_name):
        # type: (int, str) -> str
        """Rename with uniqueness enforcement; returns the name actually set."""
        o = self.get(obj_id)
        if o is None:
            return ""
        new_name = (new_name or "").strip() or o.name
        if new_name != o.name:
            o.name = self.unique_name(new_name, ignore=obj_id)
        return o.name

    def unique_name(self, base, ignore=None):
        # type: (str, Optional[int]) -> str
        """Blender-style dedup: 'water', then 'water.001', 'water.002', ..."""
        taken = {o.name for o in self.objects if o.id != ignore}
        if base not in taken:
            return base
        k = 1
        while True:
            cand = "{}.{:03d}".format(base, k)
            if cand not in taken:
                return cand
            k += 1

    # ------------------------------------------------------------- geometry
    def centroid(self):
        # type: () -> np.ndarray
        pts = [o.structure.coords for o in self.visible_objects()
               if o.structure.n_atoms]
        if not pts:
            return np.zeros(3)
        return np.vstack(pts).mean(axis=0)

    def bounding_radius(self):
        # type: () -> float
        """Radius about the scene centroid enclosing every visible atom's
        VdW sphere (what camera fit frames)."""
        c = self.centroid()
        best = 1.0
        for o in self.visible_objects():
            s = o.structure
            if not s.n_atoms:
                continue
            d = np.linalg.norm(s.coords - c, axis=1)
            vdw = np.array([elements.radius_vdw(z) for z in s.atomic_numbers])
            best = max(best, float((d + vdw).max()))
        return best

    # ------------------------------------------------------------ selection
    def resolve_pick(self, pick):
        # type: (Tuple[int, int]) -> Optional[Tuple[MolObject, int]]
        """(obj_id, atom_idx) -> (MolObject, atom_idx) if still valid."""
        obj = self.get(pick[0])
        if obj is None or not 0 <= pick[1] < obj.structure.n_atoms:
            return None
        return obj, pick[1]

    def pick_label(self, pick, with_object=None):
        # type: (Tuple[int, int], Optional[bool]) -> str
        """Display label for a pick, e.g. 'O0' or 'water:O0' (object prefix
        added automatically when the scene holds several objects)."""
        r = self.resolve_pick(pick)
        if r is None:
            return "?"
        obj, i = r
        tag = "{}{}".format(obj.structure.symbols[i], i)
        if with_object is None:
            with_object = self.n_objects > 1
        return "{}:{}".format(obj.name, tag) if with_object else tag

    def pick_coords(self, pick):
        # type: (Tuple[int, int]) -> Optional[np.ndarray]
        r = self.resolve_pick(pick)
        if r is None:
            return None
        obj, i = r
        return obj.structure.coords[i]

    # ---------------------------------------------------------- undo support
    def snapshot(self):
        # type: () -> dict
        """Deep-copyable full state for the snapshot-undo stack. Object ids
        are preserved so (obj_id, atom) selections stay meaningful across
        undo when the object still exists."""
        objs = []
        for o in self.objects:
            s = o.structure
            objs.append({
                "id": o.id, "name": o.name, "visible": o.visible,
                "style_key": o.style_key,
                "origin": o.origin.copy(),
                "orientation": o.orientation.copy(),
                "sname": s.name, "symbols": list(s.symbols),
                "frames": [f.copy() for f in s.frames],
                "current_frame": s.current_frame,
                "bonds": list(s.bonds), "metadata": dict(s.metadata),
                "modifiers": [m.to_dict() for m in o.modifiers],
                "atom_colors": {int(k): tuple(v)
                                for k, v in o.atom_colors.items()},
                "atom_labels": sorted(int(i) for i in o.atom_labels),
                "atom_label_text": {int(k): str(v)
                                    for k, v in o.atom_label_text.items()},
                "atom_label_colors": {int(k): tuple(v) for k, v
                                      in o.atom_label_colors.items()},
                "atom_label_modes": {int(k): str(v) for k, v
                                     in o.atom_label_modes.items()},
                "label_mode": o.label_mode,
            })
        return {"objects": objs, "next_id": self._next_id}

    def to_dict(self):
        # type: () -> dict
        """JSON-safe scene state for savepoint files (core/project.py).
        Same shape as `snapshot()` with numpy arrays turned into lists, so
        the two never drift apart."""
        snap = self.snapshot()
        for o in snap["objects"]:
            o["origin"] = [float(v) for v in o["origin"]]
            o["orientation"] = [float(v) for v in o["orientation"]]
            o["frames"] = [f.tolist() for f in o["frames"]]
            o["bonds"] = [[int(i), int(j), int(k)] for i, j, k in o["bonds"]]
        return snap

    def from_dict(self, d):
        # type: (dict) -> None
        snap = {"next_id": int(d.get("next_id", 1)), "objects": []}
        for o in d.get("objects", []):
            snap["objects"].append(dict(
                o,
                origin=np.asarray(o["origin"], dtype=float),
                orientation=np.asarray(o["orientation"], dtype=float),
                frames=[np.asarray(f, dtype=float).reshape(-1, 3)
                        for f in o["frames"]],
                bonds=[(int(i), int(j), int(k)) for i, j, k in o["bonds"]],
            ))
        self.restore(snap)

    def restore(self, snap):
        # type: (dict) -> None
        self.objects = []
        for d in snap["objects"]:
            s = Structure(d["symbols"], d["frames"][0], name=d["sname"],
                          metadata=d["metadata"])
            s.frames = [f.copy() for f in d["frames"]]
            s.current_frame = d["current_frame"]
            s.bonds = list(d["bonds"])
            obj = MolObject(d["id"], s, d["name"], d["visible"],
                            d["style_key"])
            obj.origin = d["origin"].copy()
            obj.orientation = d["orientation"].copy()
            obj.modifiers = [m for m in (modifiers.from_dict(md)
                                         for md in d.get("modifiers", []))
                             if m is not None]
            obj.atom_colors = {int(k): tuple(v) for k, v
                               in (d.get("atom_colors") or {}).items()}
            obj.atom_labels = {int(i) for i in (d.get("atom_labels") or [])}
            obj.atom_label_text = {int(k): str(v) for k, v
                                   in (d.get("atom_label_text") or {}).items()}
            obj.atom_label_colors = {
                int(k): tuple(v) for k, v
                in (d.get("atom_label_colors") or {}).items()}
            obj.atom_label_modes = {
                int(k): str(v) for k, v
                in (d.get("atom_label_modes") or {}).items()}
            obj.label_mode = d.get("label_mode", "element")
            self.objects.append(obj)
        self._next_id = snap["next_id"]
