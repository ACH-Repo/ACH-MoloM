"""Multi-molecule scene: the data model behind the Blender-style outliner.

A Scene holds MolObjects (a Structure + display state). Everything the
outliner shows lives here so it stays UI-free and testable: visibility,
per-object style override, unique Blender-style names ("water", "water.001").
Atom identity anywhere above this layer is a (obj_id, atom_index) pair.
"""

from typing import List, Optional, Sequence, Tuple

import numpy as np

from . import elements, modifiers
from .camera import quat_identity, quat_to_mat3
from . import cameras as cameras_mod
from . import attachments
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
        # Per-atom display, both sparse like the colours above. Essential for
        # framework pictures: a MOF is unreadable until the hydrogens are off
        # and the metal spheres are small enough not to burst their polyhedra.
        self.atom_hidden = set()     # idx NOT drawn (still there, still real)
        self.atom_scales = {}        # idx -> sphere-radius multiplier
        self.label_mode = "element"  # element | index | element_index | custom
        # Computed layers drawn OVER this molecule - normal modes, and later
        # isosurfaces. Per-molecule rather than per-atom, so they get their own
        # tick-box row in the outliner rather than a column on the element
        # rows. See `core/attachments.py` for what an edit does to them, which
        # differs by attachment and is the whole reason they are modelled at
        # all. `edit_locked` is the overwrite protection: only meaningful
        # while there IS an attachment, so an ordinary molecule never shows a
        # lock it has no use for.
        self.attachments = {}        # key -> attachments.Attachment
        self.edit_locked = False
        # Set by the scene clock while playing: a FRACTIONAL frame position,
        # or None to show the stored frame as-is. Display only — never
        # written back into `structure.frames`.
        self.play_position = None    # type: Optional[float]
        self.play_rigid = True
        #: Do these frames close on themselves (a baked normal mode)? Set by
        #: the clock each tick from the strip, so the interpolation across the
        #: wrap blends the last sample into the first instead of freezing on
        #: it. Display-only, like the two above - never snapshotted.
        self.play_cyclic = False

    # ------------------------------------------------------ renumbering
    #: Every per-atom map on this object. They are all keyed by atom INDEX and
    #: are all sparse, so a delete leaves each of them perfectly valid and
    #: quietly describing different atoms - which is why they are enumerated
    #: once here rather than remembered at each call site (round 80). Anything
    #: added beside them belongs in this tuple; a test asserts as much.
    ATOM_MAPS = ("atom_colors", "atom_labels", "atom_label_text",
                 "atom_label_colors", "atom_label_modes", "atom_hidden",
                 "atom_scales")

    def remap_atoms(self, old_to_new):
        # type: (dict) -> None
        """Reindex the display maps after the atoms were renumbered.

        `old_to_new` is `edits.delete_atoms`'s report: survivors only, so an
        entry whose atom is gone is dropped rather than carried onto whatever
        inherited its index.
        """
        for name in self.ATOM_MAPS:
            current = getattr(self, name)
            if not current:
                continue
            if isinstance(current, set):
                setattr(self, name, {old_to_new[i] for i in current
                                     if i in old_to_new})
            else:
                setattr(self, name, {old_to_new[int(k)]: v
                                     for k, v in current.items()
                                     if int(k) in old_to_new})

    def delete_atoms(self, indices, with_hydrogens=False):
        # type: (Sequence[int], bool) -> dict
        """Delete atoms AND keep this object's own per-atom maps in step.

        The paired call to `edits.delete_atoms`: that one can only reach what
        is on the structure, and a molecule's colours, labels, hidden atoms
        and sphere sizes are not. Delete through here whenever there is an
        object to hand.
        """
        from . import edits
        report = {}
        edits.delete_atoms(self.structure, indices,
                           with_hydrogens=with_hydrogens, report=report)
        self.remap_atoms(report.get("remap") or {})
        return report

    def adjust_hydrogens(self, indices, **kw):
        # type: (Sequence[int], object) -> tuple
        """Re-dress hydrogens, keeping the display maps in step.

        Adding a hydrogen appends and disturbs nothing; REMOVING one - which
        is what happens on C -> O, or when a bond order goes up - renumbers
        every atom above it, so a colour or a hidden flag would slide onto a
        different atom exactly as a delete does.
        """
        from . import edits
        report = {}
        result = edits.adjust_hydrogens(self.structure, indices,
                                        report=report, **kw)
        self.remap_atoms(report.get("remap") or {})
        return result

    def set_element_adjusted(self, indices, symbol, **kw):
        # type: (Sequence[int], str, object) -> tuple
        """Change element(s) and re-dress their hydrogens, keeping the
        display maps in step - see `adjust_hydrogens`."""
        from . import edits
        report = {}
        result = edits.set_element_adjusted(self.structure, indices, symbol,
                                            report=report, **kw)
        self.remap_atoms(report.get("remap") or {})
        return result

    def atom_scale_for(self, index):
        # type: (int) -> float
        return float(self.atom_scales.get(int(index), 1.0))

    # --------------------------------------------------------- hiding atoms
    @property
    def has_hidden(self):
        # type: () -> bool
        """Whether anything on this molecule is hidden.

        Worth a name of its own: hidden atoms are invisible BY DEFINITION, so
        the only way to know they exist is for something else to say so — the
        outliner marks the molecule's row.
        """
        return bool(self.atom_hidden)

    def hide_atoms(self, indices):
        # type: (object) -> int
        """Hide these atoms. Returns how many newly went away."""
        n = self.structure.n_atoms
        wanted = {int(i) for i in indices if 0 <= int(i) < n}
        added = wanted - self.atom_hidden
        self.atom_hidden |= wanted
        return len(added)

    def unhide_all(self):
        # type: () -> int
        """Show everything again. Returns how many came back."""
        n = len(self.atom_hidden)
        self.atom_hidden = set()
        return n

    def element_indices(self, symbol):
        # type: (str) -> list
        return [i for i, s in enumerate(self.structure.symbols) if s == symbol]

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
        if mode == "occupancy":
            return self.occupancy_text(i)
        return sym

    def site_composition(self, index):
        # type: (int) -> list
        """`[(element, occupancy), ...]` for this atom's SITE, or [].

        A shared position — several species on one Gitterplatz — is drawn as
        one atom carrying the whole composition (round 42), so the question
        "what is this atom?" has more than one answer and the readout should
        give all of them.
        """
        table = (self.structure.metadata or {}).get("site_occupancy") or {}
        entry = table.get(str(int(index)))
        if not entry:
            return []
        return [(str(sym), float(occ)) for sym, occ in entry]

    def occupancy_text(self, index):
        # type: (int) -> str
        """Occupancy as a label: `0.50` for a partial site, `Nb.50/Ti.25` for
        a shared one, and nothing at all for an ordinary full atom — a label
        reading "1.00" on every atom of an ordered structure is noise."""
        parts = self.site_composition(index)
        if parts:
            return " ".join("{}{:.2f}".format(sym, occ)
                            for sym, occ in parts)
        occ = self.occupancy_of(index)
        if occ is None or occ >= 1.0 - 1e-6:
            return ""
        return "{:.2f}".format(occ)

    def occupancy_of(self, index):
        # type: (int) -> Optional[float]
        """This atom's occupancy, or None when the file did not say.

        Read from the asymmetric unit through the drawn atom's site, which is
        the only place it survives: `expand`'s de-duplication drops the
        co-located species before occupancy is ever consulted (round 42).
        """
        meta = self.structure.metadata or {}
        parts = self.site_composition(index)
        if parts:
            return float(sum(o for _s, o in parts))
        occupancy = meta.get("asym_occupancy")
        sites = meta.get("site_of")
        i = int(index)
        if occupancy and sites and i < len(sites):
            site = int(sites[i])
            if 0 <= site < len(occupancy):
                return float(occupancy[site])
        return None

    def display_coords(self):
        # type: () -> np.ndarray
        """Coordinates to DRAW: the stored frame, or an interpolated blend of
        two frames while the timeline sits between them.

        `play_position` is set by the scene clock each tick and is display-only
        — the stored frames are never overwritten, so scrubbing a trajectory
        cannot damage it and editing still works on real frame data.
        """
        s = self.structure
        if self.play_position is None or s.n_frames < 2:
            return s.coords
        from . import interpolate
        return interpolate.coords_at(s.frames, self.play_position,
                                     rigid=self.play_rigid,
                                     cyclic=self.play_cyclic)

    def evaluated(self):
        # type: () -> tuple
        """(symbols, coords, bonds) after the modifier stack. Display and
        export use this; editing, picking and the force field use the base
        structure, so a 3000-atom slab still edits like one unit cell."""
        s = self.structure
        coords = self.display_coords()
        if not modifiers.stack_is_active(self.modifiers):
            return s.symbols, coords, s.bonds
        return modifiers.evaluate_stack(self.modifiers, s.symbols, coords,
                                        s.bonds, pose=self.cell_pose(coords))

    def cell_pose(self, coords=None):
        # type: (object) -> Optional[tuple]
        """The rigid motion from this crystal's OWN frame onto its atoms.

        A cell is stored as lengths and angles, so its matrix is built in a
        canonical orientation and every fractional-coordinate calculation
        assumes the atoms are still in it. Rotate the crystal and that stops
        being true — which is why a cell-based modifier has to be handed this
        and undo it first.

        Recovered from the same reference sample the cell BOX follows (round
        19), so the box and the modifiers cannot disagree about which way the
        crystal is facing. None when there is no cell, no reference, or the
        fit is not determined.
        """
        from . import cif as cif_mod
        meta = getattr(self.structure, "metadata", None) or {}
        ref = meta.get("cell_ref_xyz")
        idx = meta.get("cell_ref_idx")
        if not ref or not idx:
            return None
        xyz = self.structure.coords if coords is None else np.asarray(coords)
        try:
            cur = np.asarray([xyz[int(i)] for i in idx], dtype=float)
        except (IndexError, ValueError):
            return None
        return cif_mod.rigid_from_reference(np.asarray(ref, dtype=float), cur)

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
        #: Saved viewpoints. A separate list from `objects` on purpose: a
        #: camera has no atoms, so every loop that draws, picks, exports or
        #: perceives bonds would have to learn to skip it. Keeping them apart
        #: means none of that code changes at all, and the outliner shows the
        #: two as separate sections because that is what they are.
        self.cameras = []          # type: List[cameras_mod.CameraObject]
        #: Which camera Numpad 0 goes back to.
        self.active_camera_id = None    # type: Optional[int]
        self._next_id = 1
        self._next_camera_id = 1

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

    # --------------------------------------------------------------- cameras
    def camera(self, cam_id):
        # type: (int) -> Optional[object]
        for c in self.cameras:
            if c.id == cam_id:
                return c
        return None

    def add_camera(self, name="", camera=None, width=None, height=None):
        # type: (str, object, int, int) -> object
        """A new saved viewpoint, optionally capturing the live camera."""
        cam = cameras_mod.CameraObject(
            self._next_camera_id,
            self.unique_camera_name(name or "Camera"))
        self._next_camera_id += 1
        if camera is not None:
            cam.capture(camera, width, height)
        self.cameras.append(cam)
        self.active_camera_id = cam.id
        return cam

    def remove_camera(self, cam_id):
        # type: (int) -> bool
        cam = self.camera(cam_id)
        if cam is None:
            return False
        self.cameras.remove(cam)
        if self.active_camera_id == cam_id:
            self.active_camera_id = (self.cameras[-1].id if self.cameras
                                     else None)
        return True

    def unique_camera_name(self, base, ignore=None):
        # type: (str, Optional[int]) -> str
        taken = {c.name for c in self.cameras if c.id != ignore}
        if base not in taken:
            return base
        n = 1
        while "{}.{:03d}".format(base, n) in taken:
            n += 1
        return "{}.{:03d}".format(base, n)

    def rename_camera(self, cam_id, new_name):
        # type: (int, str) -> Optional[str]
        cam = self.camera(cam_id)
        if cam is None:
            return None
        cam.name = self.unique_camera_name(
            (new_name or "Camera").strip() or "Camera", ignore=cam_id)
        return cam.name

    def active_camera(self):
        # type: () -> Optional[object]
        return (self.camera(self.active_camera_id)
                if self.active_camera_id is not None else None)

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
        # Occupancy rides in the readout whenever it is not a plain full
        # site: "which atom is this?" has a different answer on a shared
        # position, and the picture alone cannot say so.
        occupancy = obj.occupancy_text(i)
        if occupancy:
            tag = "{} [{}]".format(tag, occupancy)
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
                # Round 26 added these two and forgot to snapshot them, so
                # every undo silently un-hid whatever you had hidden and
                # reset every sphere size — which reads as "hiding is
                # broken", not as "undo is lossy". Sorted list, not a set,
                # so `to_dict` stays JSON-safe for savepoints.
                "atom_hidden": sorted(int(i) for i in o.atom_hidden),
                "atom_scales": {int(k): float(v)
                                for k, v in o.atom_scales.items()},
                "label_mode": o.label_mode,
                # Round 31's checklist, honoured on arrival this time: a new
                # per-object field that is not in BOTH `snapshot` and
                # `restore` is silently thrown away by every undo AND by every
                # cancelled viewport gesture, which reads as the feature being
                # broken rather than as undo being lossy.
                "attachments": [a.to_dict()
                                for _k, a in sorted(o.attachments.items())],
                "edit_locked": bool(o.edit_locked),
            })
        return {"objects": objs, "next_id": self._next_id,
                # Cameras ride the snapshot stack and the savefile like
                # everything else, which is the whole point of them being
                # scene objects: "a savefile can retain previously used
                # angles". `to_dict` is already JSON-safe, so `to_dict` and
                # `snapshot` need no separate handling here (round 31's
                # four-place checklist, satisfied by having one shape).
                "cameras": [c.to_dict() for c in self.cameras],
                "active_camera_id": self.active_camera_id,
                "next_camera_id": self._next_camera_id}

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
        # Everything `snapshot` produces has to be carried, not just the
        # objects: this function rebuilds the dict by hand, so anything added
        # to the snapshot and not added HERE is silently lost on load. That
        # is how the cameras vanished from the first savefile that had them.
        snap = {"next_id": int(d.get("next_id", 1)), "objects": [],
                "cameras": d.get("cameras", []),
                "active_camera_id": d.get("active_camera_id"),
                "next_camera_id": d.get("next_camera_id", 1)}
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
        self.cameras = [cameras_mod.CameraObject.from_dict(c)
                        for c in snap.get("cameras", [])]
        self.active_camera_id = snap.get("active_camera_id")
        self._next_camera_id = int(
            snap.get("next_camera_id",
                     max([c.id for c in self.cameras] or [0]) + 1))
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
            obj.atom_hidden = {int(i) for i in (d.get("atom_hidden") or [])}
            obj.atom_scales = {int(k): float(v) for k, v
                               in (d.get("atom_scales") or {}).items()}
            obj.label_mode = d.get("label_mode", "element")
            obj.attachments = {}
            for entry in (d.get("attachments") or []):
                att = attachments.Attachment.from_dict(entry)
                obj.attachments[att.key] = att
            obj.edit_locked = bool(d.get("edit_locked", False))
            self.objects.append(obj)
        self._next_id = snap["next_id"]
