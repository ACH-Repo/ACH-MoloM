# Where would an isosurface live?

Design note, 2026-08-13. Christian: *"Where does an isosurface visualisation
live? can it be cleanly added to an existing molecule/cif object in the
outliner? Does it ride the save file? Can it be exported to .blend for proper
rendering?"*

Nothing below is built. It is written now because the answers are already
determined by decisions this codebase has made — every one of the three
questions has a precedent, and the precedents disagree with the obvious answer
in two places.

---

## 1. What an isosurface IS, structurally

A scalar field sampled on a grid, contoured at a value, giving a triangle mesh
with optional per-vertex colour. Molecular orbitals, electron density,
electrostatic potential, spin density and solvent-accessible voids are **all
that one object** with a different field and a different colour source. So
there is one pipeline, not five features:

```
field on a grid  ->  marching cubes  ->  mesh (+ per-vertex colour)
```

Which means the thing to design is the OBJECT, not the orbital.

---

## 2. Where it lives in the scene

**Not a `MolObject`.** Round 56 settled the shape of this question for camera
objects and the reasoning transfers exactly: a camera has no atoms, so every
loop that draws, picks, exports or perceives bonds would have had to learn to
skip it — and keeping cameras in their own list meant *none of that code
changed at all*. An isosurface has no atoms either.

**Not a modifier.** `evaluate_stack` returns `(symbols, coords, bonds)`. It is
an atom-list transformation, and a surface is not atoms. Forcing it in would
make the stack return a heterogeneous thing, which is how a clean abstraction
becomes a debugging nightmare.

**A separate list, with an owner.** `Scene.surfaces`, each entry carrying an
`owner_id` into `Scene.objects`. That is the camera pattern plus the one thing
a camera does not have: a surface is *derived from* a particular molecule, is
meaningless without it, and must be deleted with it. In the outliner it is a
child row under its molecule — which is also where the eye/colour/style squares
already live, so it inherits `RowControls` for free.

### The part that is easy to get wrong: it must follow the atoms, not the origin

Round 19's lesson, in a new place. `obj.origin` is the CENTROID and a plain
grab moves atom coordinates without touching it, so anything anchored to
`origin` drifts a whole centroid vector away — that was the unit-cell box bug.
The surface must be posed by the same Kabsch fit against stored reference atoms
(`cif.rigid_from_reference`) that the cell box uses, evaluated while painting
so it tracks a drag live.

### And it must go STALE, not follow, on an edit

Round 43e: **an edit is not a rigid motion**, so a pose measured across one
reports a rotation nobody performed. Worse here than for the cell box: a
surface describes a wavefunction of a *particular geometry*, so once an atom
moves the surface is not merely mis-posed, it is wrong. It should mark itself
stale and say so on the row, and offer to recompute — never silently follow.
A viewer that quietly shows the orbital of a molecule you no longer have is the
worst failure available.

---

## 3. Does it ride the savefile?

**The recipe does. The mesh does not.**

A 100^3 grid is ~4 MB of floats and `.molom` is JSON (round 6). Embedding a
mesh would bloat the savefile hopelessly, and — the sharper problem — round 31
requires every scene field to be added to `Scene.snapshot`/`restore`, which
runs on **every undo step and every cancelled gesture**. A few MB copied per
grab is not acceptable.

So the scene stores:

```
{source path, field kind, isovalue, sign/phase, colour mapping, style, owner}
```

about 200 bytes, and the mesh is regenerated (marching cubes on 100^3 is tens
of milliseconds) and held in a cache keyed on exactly those inputs — the
`_poly_key`/`_poly_cache` pattern from round 48, for the same reason: it is
camera-independent and must never be recomputed in a paint path.

The cost of storing a path is that the savefile depends on the cube file still
being there. That is the ordinary linked-asset problem every DCC has; the
honest handling is a clearly-reported "source missing" state on load, and a
*Pack* option later (Blender's own word for it) for people who need the file to
be self-contained.

**The four-place checklist applies**: `snapshot`, `restore`, `to_dict`,
`from_dict`. Round 56's cameras were lost from the first savefile that had them
because `from_dict` rebuilds the snapshot dict by hand. Grep for `next_id`.

---

## 4. Can it go to Blender?

**Yes, and this is the easiest of the three.** `blender_export.collect()`
already returns plain data and `build_script()` renders it into source, and
round 50 added coordination polyhedra — one closed mesh per centre on a
translucent, never-metallic material. An isosurface is the same kind of payload.

Three differences worth writing down now:

1. **Smooth shading, not flat.** Polyhedra are flat-shaded because a
   coordination polyhedron has real creases. An isosurface has none, so
   marching-cubes normals must be smoothed or it arrives faceted — which is
   precisely the round-64 complaint about the atoms.
2. **Per-vertex colour needs a Color Attribute**, plus an Attribute node wired
   into the material. A plain material colour cannot express an ESP-mapped
   surface, which is the single most wanted picture in this whole area.
3. **One source of truth for which surfaces show.** Round 50 made
   `polyhedra.for_object` the one place that decides, called by both the
   viewport and the exporter, so a render cannot disagree with the screen
   (round 37's rule). `surfaces.for_object` must be the same.

Viewport drawing follows the polyhedra rules verbatim: depth-test on,
**depth-write off**, culling off (you need to see the molecule through it, and
a cage from inside), its **own** `_InstancedMesh` and never the scene's
(round 35's flicker), cached on its inputs.

---

## 5. What goes in core, and what is an add-on

The MOPAC round settled this pattern and it applies again:

- **`core/` owns the pipeline.** Grid, marching cubes, colour mapping, the
  scene object. Pure numpy, UI-free, GL-free, offline-testable — and shared by
  every field kind, which is the whole reason not to let each one bring its
  own.
- **Reading a cube file is core**, the same way CIF parsing is: it is a plain
  text format, not a program.
- **Anything that has to RUN something is an add-on.** `orca_plot` to make a
  cube from an ORCA job, MOPAC's `GRAPHF`, a future void-analysis tool. Binary
  discovery and subprocesses stay out of `core/`, exactly as they now do for
  MOPAC.

**And the cube reader needs a real file before a line of it is written**
(round 27's rule). ORCA Workbench can produce one; so can MOPAC. No fixture
from memory.

---

## 6. The one that needs no new file format

**Simulated PXRD from a loaded CIF.** Structure factors are a closed-form sum
over the asymmetric unit, and the cell, the operators and the site occupancies
are already in `Structure.metadata`. No cube file, no external program, no new
parser — and for a framework group it is arguably the single most useful
physics MoloM could add, because it is the measurement people actually take.

It also happens to be the thing that makes the *educational* idea tractable:
showing how a lattice diffracts and where the reflections land is the same
arithmetic, drawn instead of tabulated.
