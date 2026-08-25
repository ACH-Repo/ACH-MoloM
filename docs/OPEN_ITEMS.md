# Open items

Everything in CLAUDE.md that is scoped, measured or promised and **not done**,
swept out of the round log on 2026-08-13 (after 0.4.0 and the MOPAC add-on).
Struck-through items in CLAUDE.md are omitted; this is only what is left.

Nothing here is urgent. It is an inventory, not a plan.

**Since the sweep** (rounds 74-86, to 2026-08-25): **A1 is done** (round 80),
**A5 is decided** (round 81) and **A4 is mostly done** (round 83); rounds
84-85 added the crystal search, and **round 86 closed I1, I2 and J4**, added
the outliner's crystallographic-site tier, and made the unit-cell box's
z-order a choice (see **J** below). Everything from round 81 on is on the
`crystal-overvalence` branch, awaiting Christian's testing. Nothing else here
was closed. Rounds 74-76 were the MOPAC
frequency reader, computed layers (`core/attachments.py`) and Christian's
MOPAC batch; rounds 77-79 reworked the player - one duration per strip, a
frame range that stays put, wall-clock playback, and a pane you can zoom and
pan. Two entries below are partly overtaken: **E3**'s input feel-check now
holds for the TRACK PANE (round 79 normalised wheel and trackpad into one
unit and latched the gesture) and still stands for the VIEWPORT; and **A2**'s
"integrate on the paint" is the same diagnosis round 78 acted on for playback,
so the fix there is a worked example for the shuttle.

---

## A. Real bugs, measured and standing

~~**A1. The meta-atom table is not reindexed on delete.**~~ **DONE, round 80**
— and it was one instance of a class. Nothing keyed by atom index followed a
delete: not the meta table, not `site_of` / `content_of` / `site_occupancy` /
`refused_bonds`, and not any of the seven per-atom display maps on
`MolObject`. `adjust_hydrogens` removing a surplus H turned out to be a second
renumbering path with the same hole. Fixed at both levels, with
`MolObject.ATOM_MAPS` and a test that compares it against the live object so a
new map cannot be added and forgotten.

**A2. Third-person shuttle jitter** (roadmap 6b, diagnosed 2026-08-13).
`_FLY_TICK_MS = 16` is 62.5 Hz against a 60 Hz display; the beat means a
presented frame occasionally carries two integration steps or none. Cosmetic,
third-person-only because the chase camera is a lagging filter of the ship
while the cockpit camera is rigidly on it. Fix is to integrate on the paint.

**A3. Editing a PACKED crystal desynchronises the boundary copies.** Flagged
with a message in round 50, never fixed. Edits should operate on the cell
CONTENT and re-pack. Related: `edits.adjust_bond_lengths` is cell-unaware and
can push an atom across a face.

**A4. Occupancy pie spheres.** **Mostly fixed, round 83.** It was not a
survival problem: `packing.pack` always built the map correctly, and two
callers overwrote it with one whose keys mean something else (CONTENT index
rather than DRAWN index), so 2 of 10 Nb showed a composition. Fixed at both,
along with `site_of` and a stale `content_of` that could make a delete take
the wrong atoms. **What remains is the ASYMMETRIC UNIT**, which shows no pie
because the four rows would have to be merged into one atom - and
`sync_asymmetric_unit` writes that view's atoms back into metadata, so a
merged view would destroy the solid solution on the first edit. Needs the
write-back taught about shared sites; three options are laid out in the
round-83 note. **DECIDED by Christian, 2026-08-25: merge the shared rows into
one pie atom in the asymmetric-unit view AND fix the write-back** - teach
`sync_asymmetric_unit` that one drawn atom can stand for several metadata
rows, which is the same one-to-many mapping `occupancy.expand_shared` already
performs for the CIF writer. Not the cheap option (locking shared sites
against editing) and not leaving it: nothing is taken away, and the mechanism
already exists on the write side. **Not yet built.**

~~**A5. `4-ABA-oxime.cif` floats 36 unbonded hydrogens.**~~ **DECIDED and done,
round 81** (branch `crystal-overvalence`, awaiting Christian's testing). The
decision was his and it dissolves the item: a CIF viewer draws the FILE, so
over-valence is drawn and nothing is dropped — which means nothing is left
floating. The geometric disorder sweep this entry proposed was the wrong
instrument anyway; an idealised staggered methyl puts its closest H pair at
0.943 A, outside `DISORDER_RADIUS` (0.8). Impossibly short contacts are still
refused, and `periodic_pairs` still caps for the fragment walks.

**A6. The desktop-only selection flicker was fixed by inference, not by
reproduction.** Overlays got their own buffers (round 35), which is right
either way, but the flicker was never reproduced here — so "most likely cause"
is still the honest description.

---

## B. Crystallography (roadmap 1b)

**B1. Packing as an ARRAY MODIFIER** instead of the current destructive
rebuild. The last piece of the "everything generative is a modifier" story;
symmetry already went this way in round 29.

**B2. The periodic bond graph is rebuilt per call, not cached.** `bondgraph`
should be keyed on (cell, ops, filtered sites, bond rules). Correct today, just
re-derived more often than it needs to be.

**B3. Occupancy reaches an export only on the LOSSLESS path.** A re-derived
cell writes 1.0 and says so. A shared site whose other species were merged away
at import (round 45e's ordering flaw) cannot be recovered at all — the solid
solution exports Nb 0.5 twice rather than Nb/Ti/Ni/Co.

**B4. The disorder policy is applied at IMPORT**, so switching it re-reads the
file rather than re-resolving in place.

**B5. A CIF round-trip sweep.** Every CIF on the machine through
read -> write -> read and diff. Stronger than the two vendored fixtures.

**B6. A large disordered test set is still wanted.** Two MIL-53 files are the
only real fixtures.

**B7. `fit_view` frames the ATOMS**, so a cell box larger than its contents
overflows the view.

**B8. Read the CIF's own `_geom_bond_` loop as a tier.** Its third column IS
the n_pqr code, i.e. a ready-made labelled graph. Cannot be trusted verbatim
(it lists Na...Na 3.43 A as a bond) but "worth a tier one day".

**B9. The per-object outliner row pattern was designed to be reused for
PROTEINS.** Christian's call, 2026-08-02.

### Sandbox / VESTA agreement (open questions, not bugs)
**B10.** Bonds from a FULL-occupancy O to partial ones survive the
alternatives rule — 1.475 A is exactly a peroxide bond, so no distance rule can
reject it.
**B11.** The shell growth is symmetric while VESTA's looks asymmetric (it adds
O to metals but not metals to O).
**B12.** On `4118335`, `Cu_trz_cub`, `2240539` our molecule completion is more
generous than VESTA's, because VESTA wraps atoms individually and we wrap by
molecule.

---

## C. Export and rendering

**C1. KEYFRAME ANIMATION in the Blender export** (roadmap 7) — fully scoped,
not built. Every atom is already its own object, so it is per-object keyframes
on `location`, bonds on `matrix_world`. Two decisions first: bake every frame
vs. source frames with explicitly-set LINEAR interpolation (Blender's default
Bezier would not match MoloM's player); and what to do when connectivity
changes mid-trajectory.

**C2. Merge polyhedra per object in the Blender export.** A tick, default off,
scoped to the polyhedra only — never the atoms, which must stay individually
selectable. Measure a real ZIF export first; 500 small meshes may be fine.

**C3. Offscreen supersampling** — render the GL scene into an FBO at 4-8x and
downsample. No new dependency, no new look.

**C4. POV-Ray** — evaluated and explicitly NOT recommended. Listed only so it
does not get re-proposed.

---

## D. Timeline (roadmap 1c)

**D1. Transform keyframes.** The recommendation is already written: keyframe
the per-object TRANSFORM only (a sorted list of (time, value) per channel), and
treat atom positions as the coordinate channel via the existing frame
machinery, rather than building a second animation system. Estimated at about
the size of the modifier stack.

---

## E. Polish, small items

**E1. Outliner:** duplicate object, per-object fit/zoom, drag-reorder,
multi-molecule arrangement helpers (align/snap — the maths is in OWB's
`transform.py`, ready to port).

**E1b. A flat element group of a few hundred atoms still costs ~70 ms to
open** (round 86 measured 73 ms for 300 rows, down from 512 ms). That is the
MOLECULE case only: a crystal now splits by site, so ferrocene's hundred
carbons are five rows and 4.5 ms. The floor is one widget per row - 300 rows
carrying a single bare `QWidget` each measured 14.5 ms - so the remaining
cost is the five painted squares plus `setItemWidget`. Fixing it further means
not creating a widget per row at all (a delegate that paints the squares
directly into the tree), which is a bigger change than the one that bought the
7x. Not worth it unless somebody hits it.

**E2. Viewport:** depth-cue fog; numbered-frame outliner rows for trajectories.

**E3. Input feel-check on real hardware** (roadmap 1): scroll SIGNS on both
devices, the zoom step per detent (0.88^n), and whether mouse users want
zoom-to-cursor rather than zoom-to-centre.

**E4. Performance, if ever needed:** impostor (billboard) spheres; partial
buffer updates during a grab instead of full rebuilds. Also worth re-measuring
a real frame with a packed MOF on screen — round 50 fixed the biggest cost in
the paint path, but it need not have been the only one.

---

## I. Crystal search (rounds 84-85, Ctrl+Shift+Alt+N)

Christian, 2026-08-25, after using it: **"search for crystals is very nice now.
only thing it really needs is..."** — so these two are the whole list, and
both are about the RESULTS rather than about finding them.

~~**I1. Remember the last search.**~~ **DONE, round 86.** The query and its
hits are kept on `MainWindow` (not in a module global - a second window, or
the next test, must not inherit someone else's results) and restored when the
dialog reopens, *without* re-running: that would cost three network round
trips to redisplay what was on the screen a moment ago, and could answer
differently. Both decisions the entry asked for were made as scoped, including
the second: a restored list older than a minute or two **says how old it is**,
because a stale list that looks live is worse than an empty one.

~~**I2. Sort by clicking a column header.**~~ **DONE, round 86**, and the trap
below was real - none of it uses `setSortingEnabled`. Temperature and year
carry their sort value in `Qt.EditRole` so Qt compares them as numbers, blanks
sink to the bottom whichever way the column points (an unknown temperature is
not 0 K, and reversing must not float them to the top), and a **third click
returns to the search ranking**, which Qt's own sorting has no way back to.
Text columns fold case, or `Quartz` and `quartz` end up in different halves.


**I3. Related, raised while building it, NOT requested.** Unnamed COD entries
all score 0.95 and are indistinguishable in the list — five candidates for
nicotinic acid with nothing to choose between. Showing cell/Z/temperature more
prominently helps a little; actually ranking them would mean fetching each and
comparing connectivity against the resolved SMILES, which costs a download per
candidate. Worth a decision before anyone spends that.

---

## F. OWB integration (roadmap 5)

**F1.** Point ORCA Workbench's `viewer_3d_path`/`editor_3d_path` at `molom`.
**F2.** A `--select i,j,k` CLI so geomspec atom indices can be read.
**F3.** xyz round-trip with `coords_locked` on reload.

*This is the item that motivated the whole project and is the least advanced.*

---

## G. New direction: physics-based visualisation

Raised 2026-08-13: "There is stuff in avogadro and vesta etc. that is more
physics based like iso-surfaces that we do not do at all."

Correct — MoloM draws **structure** and nothing derived from a wavefunction or
a field. The candidates, roughly in order of value per unit of work:

- **Molecular orbitals / electron density** from a cube file. ORCA already
  writes them (`orca_plot`), and MOPAC can too, so the data path exists.
- **Electrostatic potential mapped onto a density surface** — the picture
  everyone actually wants, and it is the same machinery plus a colour lookup.
- **Spin density**, same machinery again.
- **Vibrational displacement vectors as arrows** — trivial next to the above,
  since the eigenvectors are already parsed (`core/vibrations.py`).
- **Simulated PXRD from a loaded CIF** — structure factors are a closed-form
  sum over the asymmetric unit and the symmetry is already in metadata. This
  one needs no new file format at all.
- **Voids / solvent-accessible surface** for the framework work — same
  isosurface machinery over a distance field rather than a wavefunction.

The shared piece is **one isosurface pipeline**: a scalar field on a grid ->
marching cubes -> a mesh with optional per-vertex colour. Everything above is
that one pipeline with a different field and a different colour source.

See `docs/ISOSURFACES.md` for where such an object would live.

---

## H. Long term: MoloM as an interactive teaching tool

Raised 2026-08-13, explicitly **not a priority and not part of the base
install**: "I think molom could be more than just a visualiser... interactive,
visual educational purposes. Like: Show how diffracted x-rays at a unit cell
schematically lead to certain reflections and how those end up on a PXRD
pattern. Perhaps even as a small game engine in which you need to progress
through a platforming section by solving chemical problems in a visual way. I
am thinking of games like The Talos Principle as a template."

Two quite different things, and they should be kept apart because one is
cheap and one is a project of its own.

**H1. Interactive demonstrations of things MoloM already knows.** These are
small, because the physics is already in the repo:
- *Diffraction -> reflections -> PXRD.* The cell, the operators and the site
  occupancies are in metadata; the structure factor is a closed-form sum. The
  demonstration is the same arithmetic drawn instead of tabulated — Ewald
  sphere, reciprocal lattice, the reflections lighting up as the crystal
  turns, the pattern building underneath.
- *Symmetry operations acting on an asymmetric unit.* Already drawn as glyphs
  and ghosts (round 25/26); making them step, one operation at a time, is a
  presentation of what is there.
- *Normal modes.* Already animate. Naming them and asking the user to pick
  the C=O stretch is a quiz over existing machinery.
These fit MoloM as it is. They want a presentation MODE, not an engine.

**H2. The game.** A platformer with chemical puzzles is a different program
that happens to share a renderer, and the honest scoping note is that MoloM's
viewport is an orbit/fly camera over instanced meshes with no collision, no
character controller, no level format and no scripting. That is not an
argument against it — the shuttle flight model (`core/flight.py`) is already
a real 6DoF physics model with acceleration, drag and a chase camera, which is
further along than it sounds. But it belongs as a **separate application built
on molom as a library**, not as an add-on inside the viewer, and the first
step would be making `molom` importable as a rendering library with a scene
you can drive — which is roughly what `core/` already is.

The cheap first move, if this is ever picked up, is H1's PXRD demonstration:
it is useful to a working crystallographer on its own merits, it needs no new
dependency, and it would tell you whether the "explain a thing visually" mode
is worth building out before anything is bet on it.

---

## The order Christian wants (decided 2026-08-25)

1. ~~**J4 - make the test suite runnable again.**~~ **DONE, round 86.** His
   pick and the right one - a verification problem outranks features - and it
   turned up a real app bug on the way (a worker thread parented to its
   dialog). `python -m pytest tests/` is back to ~110 s in one process.
2. **A4 - the asymmetric-unit pie spheres**, by merging and fixing the
   write-back (see above). **Next up.**

---

## J. Raised in round 86, not built

**J1. The site tier is a CRYSTAL feature only.** A molecule still gets
element -> atom, which is right (there are no sites), but there are other
groupings a big molecule would want: by residue for a protein, by covalent
fragment for a solvate. `occupancy.site_groups` is the shape to copy - it
returns `[(key, label, indices), ...]` and the outliner does not care where
the partition came from. **B9** already records that the per-object row
pattern was designed to be reused for proteins; this is the same thought one
level down.

**J2. The viewport does not push its selection back into the outliner.**
Round 86 made the outliner drive the viewport, which is the direction
Christian asked for. The reverse - clicking an atom in 3D and having its row
highlight and scroll into view - is the obvious companion and was NOT built.
It needs a rule for what to do when the row does not exist yet, since rows are
built on expand and freed on collapse: expanding to reveal it is the useful
behaviour and also means a viewport click can silently build a few hundred
widgets, which is the cost round 86 just spent effort removing.

**J3. The depth-ordered cell box is a ROD, so it thickens as you zoom in.**
That is what real geometry does and what VESTA draws, but it is a different
feel from the constant-width painted line, and on a very large packing the
rods can read as heavier than the bonds. A screen-space-width line would need
its own shader (`glLineWidth` > 1 is invalid in a core profile - round 48),
which is why it is a rod. If it ever needs tuning, `cellbox.RADIUS_FRAC` is
the one number.

~~**J4. The test suite cannot be run as one process.**~~ **FIXED, round 86.**
`python -m pytest tests/` used to crawl from ~75% and never finish, appearing
to HANG in a different test each time. It now runs **1732 passed, 4 skipped in
about 110 s**, in one process, repeatedly.

Two separate causes, and the second is a real product bug rather than a test
one:

**(a) Nothing tore the windows down.** Each `MainWindow` left 17 top-level
widgets and 413 widgets behind - +340 / +8260 over 20 windows - until the
process was thrashing at ~2.8 GB. The trap is that the obvious fix looks like
it does nothing: `close()` + `deleteLater()` + `processEvents()` frees
**exactly as much as no teardown at all**, because **`processEvents()` does
not dispatch DeferredDelete**. `QCoreApplication.sendPostedEvents(None,
QEvent.DeferredDelete)` does, and then the ordinary idiom frees all of it -
measured **+0 and +0** over 40 shown windows.

`shiboken6.delete` also frees it and must NOT be used: a QMenu is a top-level
widget, its parent's destruction has already freed it, `isValid` still reports
it live, and touching one is an access violation that kills the run.

**(b) A worker QThread was a CHILD of the dialog that started it**, so
destroying the dialog destroyed a running thread. That is reachable from the
GUI - start a lookup that has to wait out the web timeout, press Cancel - and
it is why the suite then died silently (exit 127, no traceback, nothing from
`PYTHONFAULTHANDLER`) in `test_round29_fixes.py`, whose
`test_did_you_mean_suggestions_are_clickable` leaves a resolve in flight.
Workers are unparented now and held in `dialogs._LIVE_WORKERS` (un-parenting
alone would leave `self._worker` as the only reference, which dies with the
dialog - round 76's trap from the other side), and `wait_for_workers()` is
called from the test teardown and from `__main__` before the process exits,
because a thread outliving the DIALOG is correct while one outliving the
PROCESS is the same crash from the other end.

**A module- or session-scoped WIDGET fixture no longer works**, since its
widget is "new" during the first test of the module and dies at the end of it.
There was exactly one (`test_round17_labels.py::viewport`) and it is
function-scoped now.
