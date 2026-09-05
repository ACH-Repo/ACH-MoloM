# Open items

Everything in CLAUDE.md that is scoped, measured or promised and **not done**,
swept out of the round log on 2026-08-13 (after 0.4.0 and the MOPAC add-on).
Struck-through items in CLAUDE.md are omitted; this is only what is left.

Nothing here is urgent. It is an inventory, not a plan.

**Round 90 (2026-08-26)** replaced Ctrl+Shift+N with a candidate LIST
(`core/molsearch.py`), added the skeletal preview (`core/depict.py`) and the
compound-properties add-on (`core/molprops.py` +
`molom/addons/mol_properties.py`), and extracted the shared results table
(`ui/search_table.py`). Its own leftovers are section **L**.

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

~~**A3. Editing a PACKED crystal desynchronises the boundary copies.**~~
**DONE, round 99** - and NOT the way this entry proposed. "Operate on the
cell CONTENT and re-pack" cannot work: `pack` unwraps molecules, so the drawn
content is not the canonical content and re-packing does not give the picture
back (round 52 measured 210 atoms coming back as 168), and it renumbers
everything. Propagating the DISPLACEMENT to every image does the same job
exactly, because images differ by a lattice translation and a translation
commutes with a Cartesian displacement. `edits.adjust_bond_lengths` needed
nothing: round 52 already gates it off for crystals.

What is still open from it, and is a smaller thing: **an atom moved OFF a
face keeps its copies.** They are no longer justified by the boundary, and a
re-pack would drop them; keeping them is the deliberate choice (round 52's
"the atoms in front of you ARE the structure"), but nothing tells the user
that the picture now has copies the crystallography no longer implies.

~~**A4. Occupancy pie spheres.**~~ **DONE.** Round 83 fixed the full cell (a
map keyed by DRAWN index was being overwritten by one keyed by CONTENT index,
so 2 of 10 Nb showed a composition). **Round 87 closed the asymmetric unit**,
which was the half left open - and it was blocked on a data-loss hazard rather
than on difficulty: merging the shared rows for display is easy, but
`sync_asymmetric_unit` would then have written `asym_occupancy = [1.0, 1.0]`
on the first edit and permanently reduced Nb/Ti/Ni/Co to pure NbO2.
Christian chose merge-AND-fix. `cif.asym_view` merges only GENUINE shared
sites and records `asym_rows` - which rows each drawn atom stands for - and
the write-back expands through it, giving every row the atom's new position
while keeping its own element and occupancy.

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

**E1b. A flat element group of a few hundred atoms still costs ~1.5 s to
open in a REAL window** (round 86: 3.0 s -> 1.5 s for 300 rows; the
much-quoted 473 -> 73 ms was measured offscreen, where nothing paints, and
understates it by about 20x). Refresh is the honest win at 178 -> 7 ms.

That is the MOLECULE case only: a crystal now splits by site, so ferrocene's
hundred carbons are five rows. The remaining cost is Qt laying out and
painting a widget per row - 300 rows carrying a single bare `QWidget` each
measured 14.5 ms offscreen, so the widget COUNT is no longer the driver;
the painting is. Fixing it further means not creating a widget per row at all
(a `QStyledItemDelegate` that paints the five squares straight into the tree
and hit-tests in `editorEvent`), which is a real piece of work. Worth doing
only if somebody actually hits it on a molecule - a crystal no longer does.

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


~~**I4. Favourites.**~~ **DONE, round 87** (Christian's side request).
A favourite is a REFERENCE - `Hit.to_dict()`, keyed on `(source, ref)` - never
the file, so it cannot go stale against COD and a hundred cost a few kilobytes
of settings. Shown on their own when the window opens with nothing remembered;
below a full-width rule (the F3 palette's device, `Qt.NoItemFlags`) once a
search runs; and never repeated when the search itself found them.

**I3. Related, raised while building it, NOT requested.** Unnamed COD entries
all score 0.95 and are indistinguishable in the list — five candidates for
nicotinic acid with nothing to choose between. Showing cell/Z/temperature more
prominently helps a little; actually ranking them would mean fetching each and
comparing connectivity against the resolved SMILES, which costs a download per
candidate. Worth a decision before anyone spends that.

---

## F. OWB integration (roadmap 5)

~~**F1.** Point ORCA Workbench's `viewer_3d_path`/`editor_3d_path` at
`molom`.~~ **DONE, round 92** - and it needed no code in either program, only
`molom --where` to find the launcher. See `docs/ORCA_WORKBENCH.md`.
~~**F2.** A `--select i,j,k` CLI so geomspec atom indices can be read.~~
**DONE, round 92**, 0-based to match ORCA.
~~**F3.** xyz round-trip with `coords_locked` on reload.~~ **DONE, round 92**:
Ctrl+S writes the geometry back over the opened file, which is what OWB's own
instruction means. `coords_locked` was always OWB's half and already worked.

**F4. The constraint traffic is ONE-WAY.** MoloM reads indices out of a
`%geom` block and cannot hand a selection back as one. "Copy selection as an
ORCA constraint" - two atoms to a `B`, three to an `A`, four to a `D` - is a
small, obvious next step, and MoloM already knows which kind a selection
implies because that is what the measurement readout decides.

**F5. MoloM does not know about OWB's project structure**, only about the one
file it is handed. That is all the program slots offer, so going further would
mean a different kind of integration than launching an external viewer.

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

## The order Christian wants

1. ~~**J4 - make the test suite runnable again.**~~ **DONE, round 86.**
2. ~~**A4 - the asymmetric-unit pie spheres**~~ **DONE, round 87.**
3. ~~**K1 - the focal length does nothing.**~~ **DONE, round 89.**
4. ~~**The name search, the skeletal preview and the properties tab.**~~
   **DONE, round 90.**

**Nothing is queued.** The next thing is whichever of the sections below he
picks; **F** (the OWB integration that motivated the whole project) and **G**
(isosurfaces) are the two that are neither cosmetic nor already circling.

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

---

## K. The camera lens (round 88, measured but NOT fixed)

~~**K1. The focal length does not change the focal length.**~~ **FIXED, round
89**, to Christian's own design: "dragging the handles [is] just selecting a
2D window porting of the viewport... if I change focal length, then things
should just transition to more perspective or more orthographic... that
doesn't change the camera view limits."

The frame is now THE FILM drawn at `zoom` pixels per mm, with a sensor per
axis. `tan(widget_fov/2) = REFERENCE_SENSOR_MM / (2 * focal * zoom)` - the
sensor cancels, so a handle cannot rescale the scene and the lens is the only
thing that can. Measured: 24 mm to 200 mm is 8.33x magnification with the
frame pixel-identical, and each handle moves its own border exactly.


---

## M. Raised by round 91

~~**M1. The ❖ crystal page acts on the ACTIVE object only.**~~ **DONE, round
91b.** Every tick on it now acts on every SELECTED crystal, with the active
one always included and a molecule caught in a select-all passed over. The
part that needed thought was putting the SELECTION back after a rebuild, since
`on_crystal_view` regenerates the atom list and the selection names atoms by
index - without that the first tick reached five crystals and the second one.

**M1b (was M1). The original wording, for the record.** Christian selected
five isostructural fluorides and unticked "draw atoms outside the cell
boundary" expecting all five to follow; `_on_packing_option` takes one
`obj_id`, so one did. Applying a per-crystal tick to every SELECTED crystal is
a small change and a real decision - one click would rewrite several
molecules' metadata and rebuild each of their views - so it wants saying out
loud before it is built. The same question applies to every other tick on that
page (polyhedra, symmetry elements, occupancy, the cell box).

**M3. A packed crystal comes back with a different atom count after an
asym/cell round trip.** Measured 2026-08-27 on `MF.molom`: `Griceite_9008667`
is stored with 27 atoms, and asym -> cell regenerates it as 39, stably (the
other four fluorides hold at 27). It is the only one of the five carrying
`packed` state, so its cell view goes through the packing path and legitimately
includes boundary copies the stored snapshot did not. Probably correct rather
than a bug, but nobody has checked which of the two counts the file SHOULD
have, and a count that changes when you look at a structure two different ways
is the kind of thing that needs an answer written down.

**M2. ~~A savefile can carry damage done by a fixed bug.~~ DONE, round 103.**
Investigated properly and it was smaller than this note implied. COD 9008621
is `F m -3 m` like its four siblings; round 91's bug demoted it and the
savefile recorded that. **The atoms were never touched** - `demote_to_p1`
replaces the asymmetric unit (2 atoms -> all 27) and the operators (192 -> 1),
so the structure is intact and spglib answers `Fm-3m`, number 225,
unambiguously from those 27 atoms. The F3 re-derivation already repaired it
completely. Two things were missing and both are now built: `cell_frozen` is
CLEARED by a successful re-derivation (earned, because `reevaluate_symmetry`
refuses any group that cannot rebuild the cell - so success is proof that the
condition the freeze guards against no longer holds), and the ❖ page OFFERS
it, with a dialog that says the atoms are not touched and that the file keeps
the old symmetry until saved again. Found while testing: the re-derived
`asym_frac` was not snapped, so `-9.45e-17 % 1.0` came back as
`0.9999999999999999` and the cell round-tripped 21 -> 22 atoms - round 87's
float-sign bug in a second place. The original wording: `MF.molom` has CsF
stored as `P 1` with `cell_frozen`, so opening it after the round-91 fix still
shows the demoted crystal - the fix stops it happening again and cannot undo
what is already written. `F3 > Crystal: re-derive the space group` is the
route back for a cell whose atoms are still in their right places, but it is
not offered automatically and a frozen cell refuses to regenerate. Worth
deciding whether the ❖ page should offer "this cell is frozen at P1 - unfreeze
and re-derive?".

---

## P. PXRD - what round 94 built and what it did not

~~**P0. The window does not exist.**~~ **DONE, rounds 95-98.** Reachable at
`Ctrl+Shift+D`, from the crystal page and from View > Crystal; painted rather
than plotted, so **matplotlib is still not a dependency** and that decision
stayed open the way round 94 wanted it to.

~~**P1. The plot window.**~~ **DONE.** Several structures at once,
per-structure colour / radiation / range / width / shape off a right-click,
a shared axis and a vertical stack offset. Of the four things worth lifting
from OWB's `ui/spectra.py`, three are in: a redraw caused by a SETTING does
not throw away a zoom (the pattern cache is keyed on what a pattern depends
on, and the view is separate), offsets are a fraction of a reference
amplitude, and the hover tolerance is a fraction of the visible range.
**Bottom-trace-in-front z-ordering is NOT** - the traces are drawn in scene
order, which only shows where two of them overlap.

~~**P2. Two traps waiting in the window.**~~ **BOTH HIT, BOTH FIXED.** There
is no matplotlib, so its key bindings were never a problem - but the
devicePixelRatio one landed exactly as predicted: the blitting cache was
allocated at LOGICAL size, covered two thirds of a 150% display, and looked
like a layout catastrophe rather than a pixmap one. A test now pins the
allocation at 1.0, 1.25, 1.5 and 2.0.

**P3. Ionic scattering factors are not used.** The table is keyed by element
symbol, because that is what a structure records; ionic factors differ mostly
at low angle. A stated limitation, not an oversight.

**P4. No preferred orientation and no background.** ~~No K-alpha2~~ - the
doublet is in (round 96), at the standard 2:1 and with the splitting growing
with angle as a real one does. The other two remain, and a background model
probably belongs with whatever compares a simulation to a measurement (Q2).

---

## N. Next up, and Christian's 2026-08-27 batch

**N0. WORKSPACE TABS - the next thing we work on, ergonomics first.** Blender's
top-level editor tabs (Modeling / Sculpting / UV Editing), for MoloM. Christian
wants to describe the ergonomics he is after in a fresh chat and have the
backend follow from that, so DO NOT design it before that conversation.

Surveyed 2026-08-27, so the numbers are known going in: the central area is a
`QWidget` + `QVBoxLayout` holding the viewport and the transport bar - six
lines, one `setCentralWidget` - and there are only TWO docks. The expensive
part is NOT the layout: it is the **51 window-global shortcut QActions** (of
129 operators), which would still fire inside another workspace. `MolViewport`
already intercepts `ShortcutOverride` while it holds the keyboard, so the
precedent for scoping keys exists. 273 `self.viewport.` references assume one
viewport that is on screen; most are fine, a few need an "is the 3D workspace
active" guard.
**The mechanism belongs in CORE and the demonstration in an add-on**, for
`core/molprops.py`'s reason: if the workspace system itself is an add-on, two
workspace-providing add-ons cannot coexist. `MainWindow.add_workspace(...)`
beside `PropertiesDock.add_page`.
**And a second viewport is a second GL context and a second set of instance
buffers** - one `QOpenGLWidget` cannot have two parents - so a workspace that
also shows the crystal doubles the rebuild cost per scene change.

**N1. ~~THE ROUND-TRIP BANNER APPEARS ON AN IMPORTED CRYSTAL.~~ DONE, round
102** - `open_path(path, temporary=True)`, which the crystal search's import
now passes. It suppresses BOTH the `source_path` claim and the recent-files
entry, because those are the same promise about a path that is about to be
deleted. The original report:** Christian: "I was looking at a benzoic acid cif from crystal
search... when I deleted it, suddenly the round-trip text popped up. I think it
shows up directly after importing any crystal structure." Diagnosed: `open_path`
claims `source_path` for the FIRST structure file opened, and the crystal search
writes its download into a temp directory that it deletes immediately
afterwards (round 84). So MoloM claims a round trip to a path that no longer
exists, and Ctrl+S would try to write there. A searched or otherwise temporary
import must not claim the document.

**N2. ~~"Rotate by the step angle" switches a crystal from orthographic to
perspective.~~ DONE, round 102** - `Camera.rotate(keep_projection=True)`. A
free DRAG still pops back, which is Blender's rule and round 3's; a stepped
rotation by a typed number of degrees is a different gesture. The report:** The VESTA ribbon's stepped rotation goes through the ordinary
orbit, which pops the camera back to perspective (round 3's `auto_ortho`).
Wrong for a crystal, where the axis views are deliberately orthographic.

**N3. ~~The column-width rules must be IDENTICAL in both search windows.~~
DONE, round 102 - and the width half was ALREADY FIXED.** Measured before
changing anything: both tables put the stretch column in `QHeaderView.Stretch`,
both word-wrap, and both sum their column widths to the viewport rather than
to the longest entry. The round-93 fix reached the molecule search through
`ResultTable` after all; that docket note was stale. A test now pins the two
against each other, which is the standing rule made mechanical.
**The CAS number IS new.** `Candidate.cas`, filled from PubChem's synonyms -
one bulk request for the whole CID list, the same shape as `_properties_for`,
and run CONCURRENTLY with it so the wait overlaps (measured: +1.0 s serial,
+0.27-0.59 s overlapped, on a ~5 s search). Validated by its CHECK DIGIT
rather than its shape, because a synonym list is full of hyphenated numbers.
It is exactly the discriminator this dialog exists for: the three xylenes
share a formula and a weight and have distinct registry numbers.

**N5. ~~Changing an element on a shared site only relabelled the dominant
species.~~ DONE, round 102b** - it now makes the site PURELY that element,
occupancy 1.0, and clears the pie sphere with it. Christian's call, and the
better one: picking an element off the periodic table says "this position is
iodine", not "call the 50% niobium iodine and leave the titanium, nickel and
cobalt". Stating a MIXTURE is a different gesture and already had its own
dialog (`F3 > Crystal: set the occupancies of a shared site`, round 52).

**N6. LOCAL OPSIN was considered and REFUSED.** `py2opsin` bundles the OPSIN
jar, so a systematic name would resolve with no network at all - but it
needs a Java runtime, and Christian's answer was no. Recorded so nobody
re-proposes it.

**N4. ~~A distribute operator.~~ DONE, round 103.** `align.axis_extent` +
`align.distribute_offsets` in core, driven by the existing scalar modal
(`viewport.DISTRIBUTE` rides `_internal` rather than adding a second modal -
that would have been 26 more touch points in `viewport.py` for one differing
line). Three decisions worth keeping: the extent is measured ALONG THE AXIS
rather than as a bounding radius (a long flat molecule laid along x is nearly
its own length wide in x, and a radius leaves a hole); the existing ORDER is
kept, so it tidies an arrangement rather than reshuffling it into scene-id
order; and the GROUP does not move, being recentred on the span it already
occupied.

**N7. Deleting an EMPTY molecule entry.** Christian, 2026-09-05: "if there is
a molecule entry with no atoms and the outliner entry is selected, does
pressing Del not delete the entry because no atoms can be selected?" Exactly
that - the window's Del runs the delete OPERATOR, which acts on selected
atoms, so the one object you could not get rid of was the one there was
nothing else to do with. The right-click menu had always offered it. DONE,
round 103: `OutlinerPanel.keyPressEvent` handles Delete on OBJECT rows.

**N8. The axis-view flip is now "in direct succession".** It used to survive
anything - view down a, rotate, press a again, and you got the far side.
Decided by comparing the camera's ORIENTATION rather than by hooking every
gesture that could change it, so a trackpad orbit, the ribbon's stepped
rotation, the compass and F3 all reset it without being listed. A PAN or ZOOM
deliberately does not: those leave you looking down the same axis. DONE,
round 103.

**N9. ~~The default axis view came in from the negative side.~~ DONE, round
103b.** Christian's call, and his reason is MoloM's rather than Mercury's:
"mercury doesn't have gridlines in its viewport which can be in front of what
is being looked at on a view rotate" - coming in from underneath puts the
floor grid between the eye and the crystal. Nothing is lost, since the far
side is still one more press of the same button. **Both halves reversed
together**: turning the camera round while leaving `k+2` pointing down would
be a MIRROR, which is what round 35b was fixing in the first place. `k+1`
still runs right, `k+2` now runs up, determinant +1 on every axis of every
cell tried. The original wording:
Christian: "I think that a,b,c views should always come in from the positive
direction by default." Measured: every default axis view puts the camera on
the NEGATIVE side of the axis, so "view along c" looks from underneath - and
for a cell with c near +z the eye is below the xy plane, which is what he
noticed. But that is DELIBERATE and is `orient.look_along`'s documented
convention, arrived at in round 35b after three tries against his own Mercury
screenshots: the cell origin sits top-left, the chosen axis goes INTO the
screen, and the other two run right and down in cyclic order. **Flipping only
the camera side would produce a MIRROR** - "axis away" plus "second axis
down" is what makes the layout match Mercury, and round 35b records that he
identified the mirror himself ("exactly mirrored around the red a axis"). To
come in from the positive side without mirroring, the second axis has to run
UP instead of down, which is a different presentation convention from
Mercury's. Wants his decision, not a guess.

---

## L. Raised or left open by round 90

**L1. `ResolveNameDialog` is superseded and unwired.** Nothing opens it any
more; it is kept only because round 29's clickable did-you-mean and round 61's
selectable-text contracts are pinned by tests that describe real behaviour.
Either adopt it for something or delete it and those tests together - an
unreachable dialog is the shape of drift this project keeps finding.

**L2. The molecule search has no LOCAL tier.** The crystal search can be
pointed at a folder of CIFs; there is no equivalent for a personal library of
structures, and there is a good case for one (a group's own compounds are
exactly what is not in PubChem under a name anybody would type).

**L3. A metallocene still arrives as two rows.** SMILES cannot express
hapticity (round 76), so OPSIN's cyclopentadienide form and PubChem's neutral
form hash to different InChIKeys and are correctly NOT merged. Both rows are
valid and the picture tells them apart, but it looks like a duplicate until
you look. No clean fix short of a connection-table format.

**L4. The throttle costs about two seconds.** Holding to PubChem's 5 requests
a second turns a 1.9 s search into 4.7 s. PubChem's POST/listkey interface
would let the twelve name-to-CID lookups become one request; worth measuring
before assuming it is simpler.

**L5b. The computed half duplicates things MoloM could work out itself.**
Molecular weight, heavy-atom count and formal charge are all derivable with
RDKit, and are shown as PubChem's values with PubChem's attribution instead.
That is deliberate - the tab reports what PubChem says about this CID - but if
the page ever grows a "computed here" column the two must stay visibly apart,
for the same reason measured and computed already are.

**L9. `molprops.ATTACHMENT_KEY` is now unused.** Round 90d dropped the
attachment, so the constant is dead. Left in place for one round in case the
decision is revisited; delete it if not.

**L8. The expanded/collapsed state is per PAGE, not per molecule.** Expanding
a property and switching molecules keeps that property expanded on the next
one. It is a viewing choice rather than data, so this is defensible, but it
has not been thought about properly.

**L5. Properties are cited VERBATIM, units and all.** One compound reports its
melting point in Fahrenheit and Celsius, and one value ("138-140") carries no
unit at all. Normalising would mean parsing free text and would silently
misread the unitless ones, so nothing is converted - but the page therefore
shows mixed units, and whether that is right is a decision rather than an
oversight.

**L6. The properties add-on is OFF by default**, like every add-on. Christian's
own framing was that if he ends up using it a lot it should become a mainstay;
promoting it means moving the fetch and the page out of `molom/addons/` while
leaving `core/molprops.py` exactly where it is, since the format is already in
core.

**L7. Nothing writes properties into an export other than the xyz comment.**
The Blender export and the CIF writer do not carry them, and probably should
not, but the decision has not been made explicitly.

## Q. The PXRD window (rounds 95-98)

**Q1. ~~The trace colour cannot be chosen.~~ DONE in round 96** - right-click
a line or its tick box.

**Q5. ~~The pattern is recomputed for every control change.~~ DONE in round
96** - cached on the structure, the source and the range, which is everything
it depends on. Eight patterns recompute in 37 ms and redraw in 0.5 ms.

**Q2. ~~No measured pattern can be loaded alongside.~~ DONE in round 100** -
`core/pxrdfile.py` for the text formats, `core/bruker.py` vendored from
`ACH-Diffraction-Analysis-Suite` for `.raw` and `.brml` (Christian's own
suggestion, and the right one - the RAW layout was reverse-engineered there).
Colour, height and 2-theta shift off a right-click on the line or its tick
box; reload from disk keeps all three.
**What was deliberately NOT done, and is Q9: the background.** A measurement
has one and a simulation does not, so the two curves disagree by a smooth
function of 2 theta before either has said anything about the phase. Right
now the eye does that subtraction. The options in ascending order of
commitment: a manual linear baseline between two clicked points; an
iterative rolling-ball or SNIP estimate (a few lines, no parameters worth
arguing about, and what every quickplot tool does); or leaving it alone on
the grounds that a background is a REFINEMENT decision and this window is a
comparison aid. Worth asking Christian, since `ACH-PXRD-Quickplot` presumably
already made the choice once.

**Q12b. The CCDC KEY HOLE is built; the key is not.** Round 102b:
`cifsearch.register_provider` / `unregister_provider` / `extra_providers`,
with a registered tier running in the same concurrent fan-out as local, COD
and OPTIMADE and failing the same way (a tier, never the search). Nothing
under `molom/core/` imports `ccdc` and a test asserts it. What remains is
`molom/addons/csd_search.py` - the licence probe and the API calls - left
unwritten deliberately, because it cannot be run or tested here and an
untested API layer is round 59's trap. Christian's own framing: "build the
key hole but not actually put in the key yet".

**Q13. A savefile carrying CSD structures is a redistribution question, and
the answer is mostly NO.** CCDC: the licence "does not allow external
sharing of original data from the CSD"; derived data needs their written
approval. So a `.molom` full of CSD entries must not leave the group, go in
an issue, or become a fixture. **Ambiguous and worth asking CCDC** (support
ticket, with the site licence's customer number): what counts as "bulk",
whether a savefile is original or derived data, and whether editing changes
that. **Not built, wanting a decision:** marking licensed-source structures
in the savefile so MoloM can warn on save or export - a real feature that
puts a dialog in front of an ordinary action. See `docs/CCDC.md` section 4b.

**Q12. CCDC / CSD access - SCOPED, NOT BUILT.** See `docs/CCDC.md` for the
licensing position (an activation key or a licence server, NOT a `.lic` file
like PyMOL), the three GitHub risks (the key, the DATA, the package - the
data being the dangerous one), and the provider architecture. The blocker is
not code: this machine has Mercury Community, no CSD database and no CSD
Python API, so nothing CSD-shaped is demonstrable until a licence and the
Portfolio are installed. Open questions for Christian are in section 5 of
that file.

**Q11. The ICDD PDF card reader was NOT taken, deliberately.**
`ACH-Diffraction-Analysis-Suite` has `read_pdf_xml`, and a PDF card is
exactly the reference you want to overlay - but it is a STICK pattern
(positions and relative intensities, no atoms), which maps onto MoloM's
`Pattern`/`Reflection` rather than onto `Measured`, and it carries a real
design decision upstream already made: a card only covers the 2-theta
interval that was measured, so the pattern is genuinely flat outside it and
upstream draws that region DASHED. Worth doing, and it is a different shape
of thing from a measured curve rather than one more file extension.

**Q10. ~~A measured trace cannot be put on a Q axis.~~ DONE, round 103b,
widened round 104** - `MeasuredTrace.wavelength`, stated in the right-click
settings, 0 meaning "not stated". Round 104 made the field TEXT rather than a
spin box, parsed by `pxrd.parse_source`: a spin box has one unit and a fixed
number of decimals and Christian needs neither - "I need to be able to input
0.161699 exactly, or 70 keV. (dimensionless input => Angstrom, with dimension
=> case-insensitive)". That parser has read wavelengths, energies in keV/eV
and named lines since round 96, so this is one reader rather than a second
that would drift from it. The conversion was never the problem; not knowing lambda was,
and that is a fact about the FILE rather than about the axis. Traces that
have been told are converted with `q_from_two_theta`; the rest are dropped
with the alert saying what to do about it. The original wording:

**Q9. ~~The background.~~ DONE, round 103b** - Christian's own proposal:
"doesn't topas use Chebyshev polynomial functions for bg subtractions? Can't
we just use those? another right click settings option of tickbox > turn on
chebyshev bg subtraction and then a integer selection box with a default of,
say, six?" Built exactly so. `core/background.py`, order 6 by default, and
the fit is a LOWER ENVELOPE rather than a least-squares curve - a plain
polynomial passes through the mean and is dragged up by every peak, then
subtracts intensity belonging to the phase. Measured: the clipped fit lands
within 1.0-1.5% of the tallest peak against a known foot and keeps 100% of
the peak, where a naive fit overshoots the true background by 30 on average.
The clip refits the ORIGINAL data each pass; clipping the already-clipped
copy compounds and the estimate creeps downwards (measured as a residual
drifting from 4.9 to 23 across one pattern).
**Round 104 added the half Chebyshev cannot do**: at synchrotron wavelengths
the direct beam leaves a steep decay near 2 theta 0 that a low-order
polynomial cannot represent alongside an otherwise flat pattern. Measured on
his `i15-1-70985_tth_det2_norm_0.xy`, the tallest point in the whole file is
**171 400 at 2 theta 0.080** - the beam-stop edge, nine times the tallest real
Bragg peak - so every peak was drawn at a tenth of its height. It is a POWER
LAW rather than the exponential it looks like (rms 2 630 against 9 443), and
it comes off FIRST, which is his own sequencing: "perhaps this should be
applied first so that chebyshev can work on a pre-processed pattern where it
can truly shine." The rise INTO the edge is dropped rather than fitted (no
smooth function takes out a nine-point ramp without taking peaks with it),
with `beam_stop_edge` finding it from the turning point. 171 400 at 0.080 ->
18 195 at 2.950. ~~**Still open, and it is why "Ignore below" is a dial**: a
single power law cannot follow the ramped shoulder at the very edge, so a
residual is left at the start.~~
**ROUND 105 REPLACED THE MODEL, on Christian's design, and the residual goes
with it.** "I still don't like the results... I think we can achieve
something very nice if we give up on capturing amorphous contributions and go
through the pattern from high to low angle." `background.rolling_background`
walks the pattern high to low and lets the background follow it only as fast
as a background plausibly changes, bridging anything steeper. Every prop the
Chebyshev needed - the clipping, the bolted-on power law, the beam-stop
finder telling it where to start - is gone, because a small-angle foot comes
off as part of the ordinary pass. Both models are kept and chosen in the
dialog: a real amorphous hump is a thing a polynomial can carry and the walk
deliberately cannot.
**And it turned up a bug in `beam_stop_edge` that had been eating a degree of
real data.** It answered with the in-window maximum, so on
`i15-1-84514_tth_det2_norm_0.xy` - which starts at 373 counts and climbs for
a whole degree, the stop being outside the recorded range - it returned 1.20
degrees, the tallest BRAGG PEAK in the file, and the trim threw away
everything below it. A maximum is believed to be an edge only if it is inside
`MAX_SHADOW` and the pattern has decayed to half of it by the end of the
window; otherwise nothing is dropped. That fix helps the Chebyshev path too.
**What the walk costs, measured rather than hoped about**: a peak has to
stand roughly `6 * slope * FWHM` above its background to survive, so weak
reflections on a strong background are lost and the knob is the lever. That
linearity is what set the default - amorphous rejection turned out NOT to
constrain it (two amorphous scans and an empty capillary come off to
0.3-0.7% of their range at every slope from 0.5 to 3.0), so 1.0 is chosen for
the weak peaks while still sitting an order of magnitude above every
peak-free background slope measured.

**Q10-old. A measured trace cannot be put on a Q axis, correctly, and that is a
dead end rather than a refusal to work around.** A file is in 2 theta and
carries no wavelength; the window says so and drops the trace. The fix is to
let the user STATE the wavelength a scan was taken at - one more field in
`MeasuredOptions`, defaulting to unset - after which the conversion is the
same `two_theta_to_q` everything else uses. Small, and it also unlocks
comparing a Cu measurement against a Mo simulation, which is the case Q
exists for.

**Q3. B = 0 everywhere, and it is stated rather than fixed.** No CIF vendored
here carries displacement parameters, so the high-angle intensities are
overestimated. `compute` already takes `debye_waller`, so the moment a file
with `_atom_site_U_iso_or_equiv` turns up the reader could carry it - nothing
downstream would change.

**Q4. Preferred orientation is not modelled at all.** A real powder of a
layered or needle-like crystal does not give the intensities computed here,
and no warning says so. March-Dollase is the standard correction and is a few
lines, but it needs an axis the user has to state, so it is a decision rather
than a default.

**Q6. The peak width is one number at all angles.** A real diffractometer's
resolution varies with 2-theta, which is what Caglioti's `U tan^2 t + V tan t
+ W` describes and what every Rietveld program fits. The shipping single FWHM
is right for a drawing aid and wrong for anything compared against a
measurement, so it belongs with M2 rather than before it.

**Q7. The K-beta line is in the table and not offered as a preset.**
`parse_source("Cu Kb")` works, so a user who knows to type it gets it; what is
missing is the thing a real unfiltered tube shows, which is K-alpha plus a
weak K-beta at a few percent. The ratio depends on the filter, so it is a
number somebody has to state rather than one to assume.

**Q8. The hkl tab describes ONE crystal at a time.** A combo picks which, and
with several isostructural crystals open the interesting comparison is
side by side. Whether that means several tables or one table with a source
column has not been thought about.
