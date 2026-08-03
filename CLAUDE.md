# MoloM — context for Claude (read this first)

If you're an AI assistant picking up work on this repo: read this file first.
It's the durable memory of *why* things are the way they are. Keep it updated
when you finish meaningful work.

> Maintainer: Christian Nelle (AG Henke, TU Dortmund). Package/import name:
> `molom`. License MIT. Sibling project: ORCA Workbench
> (`ACH-Orca-Studio` on disk, repo `ACH-Repo/ACH-Orca-Workbench`).

## What this is
A **standalone, Python, Avogadro-like molecule viewer/builder** with
**Blender-style ergonomics**: a PySide6 + OpenGL ball-and-stick viewport with
ORCA Workbench's universal import cascade. It exists so OWB can eventually
point its `viewer_3d_path`/`editor_3d_path` program slots at a first-party
tool instead of external Avogadro/molden/PyMOL.

Round 1 (2026-07-30): import/paste/drop → perceive bonds → render;
click-selection with distance/angle/dihedral readout; trajectory playback;
editing stubs. Round 2 (2026-07-31, Christian's Blender batch): **multi-
molecule Scene + outliner** (visibility eye + per-mol style override +
rename/delete; imports ADD, never replace), Blender-grey background + floor
grid + rotating axis compass, Blender startup orientation (Z up, 3/4
view), constant-rate rotation with a Settings sensitivity slider,
persp/ortho on **O**, box/lasso select (dbl-click-drag box; Shift+Space,B /
Shift+Space,L tools), dbl-click / Ctrl+L select-whole-molecule, **G grab
modal**, **F3 operator search** over a registry with enabled-predicates
(docs/OPERATORS.md is the log), **Ctrl+Shift+N import-by-name** (vendored OWB
resolver: OPSIN → PubChem → did-you-mean), maximized startup (Settings can
switch to windowed anchored upper-right).

Round 3 (2026-07-31, second Blender batch): **turntable camera — NO ROLL**
(yaw world-Z + pitch view-X only; `(R@e_z).x == 0` invariant is tested),
**selection-anchored rotation tumbles the MOLECULE, not the camera** (rigid
model edit about the anchor with Avogadro-style yellow crosshair, one undo
entry per scroll-gesture; hover NEVER re-picks the pivot — Christian's
vertigo/focus-jump fix), **compass ball clicks = axis views** (auto-ortho,
next orbit pops back to perspective; hover lights labels white; also F3
"View along ±X/Y/Z"), **procedural infinite grid** (shader quad, 1 Å + 10 Å
lines, distance fade, drawn after opaque with depth-test-on/write-off),
**R rotate modal** mirroring G, **axis keys cycle global → object-local →
off** (Blender X/XX/XXX; object frames = per-MolObject origin+orientation),
**Shift+O origin-edit gizmo** (snaps to selection centroid, then G/R move/
rotate it; feeds the local locks and the N panel), **Shift = precision**
in modals (factor in Settings), **snapshot undo/redo Ctrl+Z/Ctrl+Y**
(core/undo.py; scene.snapshot/restore), **N transform panel** (drag-to-scrub
fields, click-to-type with safe arithmetic eval, location + Euler-XYZ),
**M outliner toggle + edge tab**, **atom element/index label checkboxes**,
**align-largest-planar-part to XY/XZ/YZ** (RANSAC plane clustering,
core/align.py).

## VERSION 0.2.0 (2026-08-03) — the line under the previous session
(Round 34 sits above it, unreleased.)
Everything below shipped between 0.1.0 and 0.2.0: the PC/mouse input preset,
the operator key table, CIF reading with symmetry, coordination polyhedra,
meta atoms, the scene clock with a multi-track timeline, vibrational modes,
per-element display control, and the symmetry modifier. 512 tests.

Round 34 (2026-08-04, geometry editing + flight + Blender selection):
**internal coordinates are editable at last** (`core/internal.py`) — the one
operation a purely Cartesian editor cannot fake. Select 2/3/4 atoms and the
right-click menu offers bond length / angle / dihedral; the molecule is SPLIT
at the coordinate's last bond and the whole trailing fragment follows
rigidly, so every other length and angle is preserved exactly. A ring bond
has no clean split (pulling the two apart would have to break a second bond),
so only the picked atom moves and the modal says so rather than silently
deforming the ring. Sign conventions are pinned by round-trip tests against
`core.measure`, not argued in a comment. Driven by `manipulate.ScalarState`,
a one-degree-of-freedom modal sharing the numeric-entry half of the G/R
mixin (`_NumericEntry`) — drag, scroll, or type; LMB/Enter set, RMB/Esc
cancel. **The right mouse button now FLIES** (`core/flight.py`): hold it and
WASD/QE thrust a world-space velocity with real acceleration, exponential
drag and a speed cap, Shift boosts, Ctrl creeps, scroll sets cruising speed,
and letting go COASTS. Velocity is world-space on purpose — turning does not
re-aim your momentum, which is the difference between flying and driving a
camera. **Shuttle mode was rewritten onto the same model**, which is what
fixes Christian's "it moved in a choppy way": the old one moved a fixed step
per key PRESS, i.e. at Qt's auto-repeat rhythm. **No roll anywhere**:
`Camera.fly_look` rebuilds the rotation from an explicit azimuth/elevation
pair rather than composing quaternion deltas (composition accumulates
floating-point roll over the thousands of steps a flight takes), and pitch
clamps short of vertical because over the pole the horizon inverts, which is
indistinguishable from roll. Ctrl+scroll roll in the shuttle is GONE for the
same reason. **Selection is Blender's orange outline** instead of Avogadro's
translucent blue bubble — an inverted hull (enlarged copy, front faces
culled, flat colour via a `uFlat` shader uniform) so only a rim survives the
depth test; bonds with both ends selected are outlined too, which is what
makes a selected fragment read as one object. Width tracks camera distance so
it stays constant on screen. **Ghosts were being shredded by the cell
boundary** — `images_of` wrapped each atom into [0,1) independently, so a
copy straddling a face came back in two halves still bonded across the box;
images are now wrapped by MOLECULE and their bonds re-tested in place
(`cif.direct_pairs`), which also handles the periodic component that cannot
be unwrapped at all. **The ❖ tab is always clickable** (the round-30 lesson,
applied: a greyed tab cannot explain itself, and this one greyed on whichever
molecule happened to be active), with the controls greying instead and the
page saying what to select — and `_sync_all` now refreshes the properties
pages, without which importing a .cif left the page still saying "no unit
cell" about the crystal that had just become active. **The symmetry arrow
worked exactly once**: `QToolButton.clicked` carries the button's checked
state and the button is not checkable, so it passed False — "collapse" —
every time; expanding also ticks the Symmetry elements box now, per
Christian. New file `beta_testers.md`, whose headline is that .cif import is
the least trustworthy part of the program. 679 tests.

Round 33 (2026-08-03, cell display researched properly): the round-32
boundary completion was HALF the convention and the missing half is what made
urea look broken. Researched against the two reference viewers rather than
guessed: **VESTA** draws atoms outside the cell that are bonded to atoms
inside it ("Search atoms if A1 is included in the boundary", on by default),
and **Mercury**'s packing dialog works in whole molecules, including one when
*any* of its atoms fits. So a boundary copy now carries its whole MOLECULE,
not just the atom — urea's C and O sit exactly on the x face and were being
copied alone, leaving a bare C=O floating in the cell with its two NH2 groups
on the other side. Rock salt must NOT be completed that way (Na and Cl fall
inside the covalent criterion, so the "molecule" is the whole lattice), which
needs a periodicity test that a two-atom cell can pass: the walk used by
`unwrap_molecules` finds no second route in a cell that small, so
`fragment_info` also asks whether a component **bonds to its own lattice
image** — Na is 2.48 A from the Cl next door, urea's molecule is 2.7 A clear
of its image and only H-bonded. NaCl: 8 corners + 1 centre. Urea: 4 complete
molecules, no stranded atoms. **Symmetry elements crawled** because
`_paint_symmetry` re-parsed 48 operators, re-classified them (an
eigen-decomposition each) and re-imaged the ghosts on EVERY repaint — 12 ms a
frame before anything was drawn, which a trackpad emitting 60+ events a
second cannot survive. Cached on the inputs: 12 ms -> 0.11 ms. **The symmetry
modifier now works on a plain molecule**, which is what Christian actually
wanted it for: take a fragment, stack single operations (a glide, a screw
axis) one at a time and watch an asymmetric unit become a cell. It invents a
box, and OFFSETS the cell origin so the molecule sits at a general position —
on the origin every operation through it maps the molecule onto itself and
adding a 2-fold appears to do nothing. The card has a preset list of the
standard elements plus a free-text field. **pymatgen was evaluated and NOT
adopted**: on Christian's own urea.cif it returns 12 of 16 sites disordered
with occupancy 2, because the CCDC file lists symmetry-redundant atoms
(N1/N1C) that it merges instead of de-duplicating. ASE and MoloM's own reader
both get 16 atoms right. pymatgen remains worth having for the P1-fallback
gap (a space-group SYMBOL with no symop loop), which is a different problem.

Round 32 (2026-08-03, five screenshot issues): **the drawn unit cell was not
a unit cell.** Two independent faults. (a) Nothing completed the cell
BOUNDARY, so rock salt showed one corner sodium instead of eight —
`cif.boundary_images` now repeats every atom lying on a face/edge/corner onto
its equivalent positions (per ATOM, not per fragment: NaCl's Na and Cl fall
inside the covalent criterion, so a fragment walk lumps them into one unit
whose centroid is nowhere near a face, and Mercury draws the boundary atom by
atom anyway). Halite now comes out as the textbook 14 Na + 13 Cl. The cell
CONTENT is unchanged — `expand(boundary=False)` still gives Z formula units.
(b) A molecule centred exactly ON a cell face (urea's, by symmetry) had a
centroid of exactly 1.0, so `floor()` decided between drawing it inside the
box and dumping it outside on a floating-point coin toss; that is what
"the asymmetric unit is left out from the unit cell" was. **The Symmetry
(CIF) modifier did nothing** because it was appended to a molecule that was
ALREADY the full cell — the operations de-duplicated straight back. Adding it
now reduces the base to the stored asymmetric unit, and the asym/cell/packing
switch drives the MODIFIER when one is present instead of rebuilding atoms
underneath it. **G ran away and reversed**: `ray_plane` guarded only against
|denom| < 1e-9, so as the cursor rose past the drag plane's horizon the
intersection shot toward infinity and then flipped sign — `_GRAZE` (0.15,
~8.5 degrees) now refuses the hit and the modal holds, and `ray_line_t` got
the same guard for axis locks. **The cursor wraps on BOTH axes** now, to the
opposite edge rather than the middle. **Zoom died while nothing was close**:
the orbit centre drifts on every pan and anchored orbit (by design), and the
fixed 0.5 A floor then stopped the dolly with the molecule 20 A away —
measured at 22 A after twelve ordinary pans. Zooming past the floor now
carries the centre forward, as Blender does, so it can never get stuck (F
"fixed" it only because F re-fits the centre). **Ghosts were blank for NaCl**:
every one of Pm-3m's 48 operations maps Na(0,0,0)+Cl(1/2,1/2,1/2) onto
itself, so after the identity check there was nothing left — `images_of` now
de-duplicates properly (one ghost per DISTINCT image, not per operator) and
adds the lattice images that actually exist. **The depth cue was scaled by
camera distance**, so a small cell occupied a sliver of the range and every
line came out at the same alpha; it is calibrated on the cell's own near-far
spread now and applies to the ghosts too. **The hidden-atoms row mark
vanished when selected** — a foreground brush loses to `HighlightedText`, so
the one row you clicked stopped warning you; `_HiddenMarkDelegate` overrides
both palette roles.

Round 31 (2026-08-03, hiding + mode picking + align preview): **hiding was
broken by an undo hole** — `atom_hidden` and `atom_scales` arrived in round
26 and were never added to `Scene.snapshot()`, so every restore silently
un-hid everything and reset every sphere size. It reads as "hiding is
broken", not as "undo is lossy", because a cancelled gesture restores a
snapshot without the user ever pressing Ctrl+Z: hide, brush the viewport,
atoms come back. Savepoints lost them too. **H hides the selection** across
every molecule it touches (Alt+H shows everything again), the selection is
cleared afterwards so the next G or Delete cannot act on atoms you cannot
see, and **ticking a molecule's eye back on un-hides all of its atoms** —
Christian's rule, because H only hides and there has to be one obvious way
back. **A molecule with hidden atoms gets a bright red outliner row**: hidden
atoms are invisible by definition, so the row is the only thing left that can
say they exist. **Hiding an animated molecule now actually saves the work**
(his question): bond perception ran regardless of visibility, so a hidden
track cost 105% of a visible one; it is deferred and caught up on unhide —
measured 5.96 -> 0.08 ms/tick at 600 atoms. **Vibration amplitude**: default
0.2 A, slider 0.05-1.00, plus a type-in box that may exceed the slider (2 A
put the whole usable range in the first fifth of the travel). The **stutter
while dragging it** was not the maths — every slider tick took a full deep
scene snapshot for undo AND rebuilt all 3N mode cards; the re-bake is
coalesced onto a 70 ms timer, the page is not rebuilt, and one undo step
covers the gesture. **Modes sort by frequency or IR intensity and filter by a
live cm-1 range**; the IR SPECTRUM block is parsed for the intensities, which
`Mode.intensity` had always left as None. Playback defaults are now
**smoothing 3, framerate 60**. **Roadmap 1f DELIVERED**: align is a preview
modal — an axis key applies and stays live, another axis key replaces it
(rewinding first, so previews never compound), left-click confirms as ONE
undo step, right-click/Esc reverts exactly. The single-atom case still
applies at once, as specified.

Round 30 (2026-08-03, playback spec): **frames, images and seconds are three
different things** and the player used to muddle them. A *frame* comes out of
an input file and its count is a property of the data; an *image* is one
picture drawn; `fps` is **images per second** and is global. So the `Smooth`
tick box — a switch that could say whether to interpolate but never how much
— became **`Smoothing`, a count of images per source-frame interval**, and
one playback timer tick now draws exactly one image (`timeline.advance_images`).
Consequence worth knowing: at a fixed framerate, doubling the smoothing plays
*slower* as well as smoother, exactly like shooting video at 60 fps and
playing it at 30; raise the framerate to match. The bar reads
`Loop [a]-[b]  Smoothing [n img]  Framerate [n fps]  Playback: cur / total`,
all in images. **Loop limits** (`Timeline.range_start/range_end`, stored in
FRAMES so changing the smoothing cannot move them) bound the interval the
playhead wraps over; they are on the bar and also draggable in the track
pane, which veils the excluded part. `seek()` now CLAMPS to the interval
while `advance`/`step_frames` wrap — scrubbing past a limit must park on it,
not teleport. **Normal-mode sampling always includes the extremes**: a mode
is sampled as `sin(2*pi*k/n)`, whose turning points sit at k = n/4 and 3n/4,
so unless four divides n the amplitude peaks are never reached (n = 6 tops
out at 0.87 of the requested amplitude). `vibrations.period_frames` snaps the
count; the spin box steps in fours. **Frames-per-period and amplitude moved
to the top of the ∿ page**, per FREQ object — they were always stored per
object and the per-card sliders merely reset themselves on every rebuild.
**The ∿ page is reachable at last** (Christian: "which I still cannot select
and look at btw"): opening an ORCA `.out` normally read the geometry through
OpenBabel and threw the modes away, so the tab stayed grey forever unless you
found the F3 loader — `_attach_frequencies` now picks modes up from any
opened file, and the tab is always clickable with the page explaining itself.

Round 29 (2026-08-03, pre-0.2.0 fixes): **SymmetryModifier** — the ❖ page's
asym/cell/packing switch REBUILDS the atom list, which throws away the
asymmetric unit you were editing; as a modifier the base stays the asymmetric
unit while the viewport and exporter see the full cell (verified: base 15,
display 60, na=2 -> 120). **A FREQ import now builds its own molecule** from
the output's `CARTESIAN COORDINATES (ANGSTROEM)` block if the active one does
not match — requiring the right structure to be open already, with atoms in
the same ORDER, is a promise no workflow keeps, and it was why the ∿ tab
stayed greyed. **A stray keypress no longer cancels an align**: ANY non-axis
key used to abort it, and the prompt lived in the status bar where a 4 s
timeout had already erased it, so the operation vanished with no clue why.
The prompt is painted in the viewport now, and Esc or RIGHT-CLICK cancel.
**"Did you mean?" suggestions are clickable** (a QListWidget, as OWB does) —
retyping a name you just misspelled is the one thing you have proved you
cannot do.

Round 28 (2026-08-03, modes page + ligand templates): **∿ Vibrations page**
in the properties dock — one collapsed card per mode (a FREQ run has 3N, so a
flat list of sliders is unreadable), with amplitude and frames-per-period
sliders inside and an "A" button that bakes the mode onto the scene clock.
The tab greys out exactly like ❖ does when the molecule has no FREQ data.
Nothing vibration-specific reaches the player: a mode becomes ordinary
frames, so it interpolates and plays alongside other trajectories.
**Ligand templates** (`core/templates.py`): mark the coordinating atoms on a
molecule ("Template: Set ligating atom(s)" — violet dots, no dialog), then
select the placeholder atoms on a centre and "Template: Coordinate ligand".
Kabsch for 3+ donors; 1 or 2 are under-determined so the free rotation is
resolved explicitly (point the bulk AWAY from the centre) rather than left to
a least-squares fluke. Also fixed: the outliner's Show/Hide and Radius squares
had NO text at all (an earlier escape-mangled edit never applied — they now
read H/S and R), and **Ctrl/Shift-click multi-select was undone by
`highlight()`**, whose `setCurrentItem` clears the selection; it now moves
the current index with `NoUpdate` when the row is already selected.

Round 27 (2026-08-03, vibrational modes + UI principles): **ORCA normal
modes** (`core/vibrations.py`) baked into a looping trajectory, so the scene
clock, interpolation, the track pane and (later) the export all animate a
vibration with NO vibration-specific code in the UI. `mode_frames` scales by
the biggest-moving atom, because ORCA's eigenvectors are normalised but not
to any physical amplitude — otherwise a stiff mode is invisible and a floppy
one explodes. **Validated on a real ORCA 6 job**, vendored verbatim at
`tests/data/orca_freq_h3po4.out`: 24 modes / 8 atoms, cross-checked against
the file's own IR SPECTRUM table. Also: per-element outliner squares got
LETTERS (H/S hide-show, R radius, L label), the radius popup anchors on its
RIGHT edge (the outliner sits against the window edge), the symmetry-kind
group got an expansion arrow, picking a crystal IN THE VIEWPORT now unlocks
its unit-cell page, symmetry line art is depth-cued (segment-wise fade and
thinning — 2D line art over a 3D scene otherwise gives no ordering), and
`ui/dragcheck.py` makes any row of checkboxes paintable by dragging.

Round 26 (2026-08-02, MOF display + symmetry corrections): **per-element
show/hide and sphere size in the outliner** (`MolObject.atom_hidden` /
`atom_scales`, two more squares on the shared RowControls). Sphere size was
global, so a MOF's Zn spheres burst out of their own coordination polyhedra
and the hydrogens buried the framework — the size square opens a slider under
itself so you can judge it against the viewport while dragging. Hidden atoms
lose their bonds too, and are not pickable. **A REAL MATHS ERROR fixed**: a
plane NORMAL is covariant and transforms with the inverse-transpose of the
cell matrix, not the matrix itself. Drawing mirrors and glides with the
direct matrix is only right for a CUBIC cell — in benzoic acid's monoclinic
cell an off-axis mirror came out **62 degrees wrong**, and MOF-5 being cubic
is exactly why it looked fine. `symmetry.world_direction` now picks the right
basis per element kind. **Ghosts are FRAGMENTS, not dots** — a scatter of
circles says nothing about what the copy is; a faint skeleton of the
asymmetric unit reads instantly as the same thing moved. **Symmetry elements
filter by KIND** (rotation / screw / mirror / glide / inversion /
rotoinversion), because Fm-3m draws every one of them at once and becomes an
orange hairball — and `symmetry.filter_ops` feeds BOTH the glyphs and the
ghosts from one list, so switching a kind off removes its elements and the
copies it generates together. `filter_ops` deliberately does not de-duplicate
(unlike `classify_all`): two distinct screw axes are one glyph but two
different images of the asymmetric unit.

Round 25 (2026-08-02, framework fix + symmetry + editing): **MOF-5 imported
sprawled over 4x2x2 cells** — and the PARSER was innocent (it read Fm-3m, all
192 operations, the right cell and the right 424 atoms). The bug was round
19's whole-molecule unwrapping: a FRAMEWORK's bonded network percolates
through the boundary, so walking it to make it "contiguous" marches it out
forever. `unwrap_molecules` now detects percolation while walking — if a bond
leads back to an already-placed atom demanding a DIFFERENT periodic image,
the component closes on itself and is left plainly wrapped. Molecular
crystals still get unwrapped. **`core/symmetry.py`**: classify a `SymOp` into
the ELEMENT it represents (rotation / screw / mirror / glide / inversion /
rotoinversion, with order, axis-or-normal, a point on it, and the intrinsic
screw-pitch or glide vector) — pure linear algebra on the 3x3, and it
collapses a 192-operation group to the handful of distinct elements worth
drawing. Rendered as the standard glyphs (lens/triangle/square/hexagon,
hollow = screw, dashed = glide) plus optional **ghost images** of the
asymmetric unit. **J = Join** (Blender): in edit mode with two atoms it bonds
them; across molecules it merges, asking new-vs-replace in an **at-the-cursor
ChoicePopup** (`ui/choice_popup.py`, generic — every "one key, two meanings"
case wants it). **D in edit mode duplicates INTO the same molecule** (with
internal bonds and meta specs) instead of spawning an outliner object.
**Whole-molecule transforms are fragment-scoped in edit mode**
(`Structure.connected_component`): shifting a metal centre no longer drags an
unbonded ligand sharing the object. **Meta glow fixed** — click-to-place
never attached the spec, so it made a bare Xx; only the drag path did.

Round 24 (2026-08-02, MOF batch): **coordination polyhedra**
(`core/polyhedra.py`) — a translucent solid through the donor atoms of every
metal centre, which is how MOFs and frameworks are actually drawn (VESTA,
Diamond, every framework paper); balls and sticks are unreadable past a few
nodes. Per-object toggle ("Poly" on the crystal's outliner row), coloured by
the metal, drawn depth-tested with depth-write OFF and culling off so linkers
read through it and a cage is visible from inside. The convex hull is
computed here rather than via scipy: a coordination sphere is 4-9 points, so
brute-force face-plane testing is exact and instant and saves a dependency.
**Outliner crystal row shortened** to Cell / Poly / Asym / Full / ⋯ with the
explanations in tooltips — it shares width with a narrow dock. **Selecting
several molecules in the outliner now selects them in the VIEWPORT**, so they
can be grabbed as a group (Shift+double-clicking each one in 3D was the only
way before). **The crystal page greys out properly**: `_on_obj_activated` was
never re-syncing it, so it kept describing whichever object was active when
the dock was last opened; the supercell counts are now disabled unless
Packing is chosen. **The transport slider is gone** (Christian's call) — the
pane's own playhead is draggable from the ruler strip or anywhere down its
line, and two scrubbers for one clock was redundant vertical space. The pane
opens itself when there is anything to play, and auto-fits its height as
tracks come and go unless you have dragged the grip yourself.
**imageio-ffmpeg** is now a declared dependency (Christian approved it),
ready for the animation export in roadmap 1d.

Round 23 (2026-08-02, timeline pane + per-crystal outliner rows):
**multi-row track pane** (`ui/timeline_panel.py`) — the transport bar gained
a ▾ toggle and a drag grip that open a row per animated object against a
shared time axis, with ONE playhead drawn across all of them. Rows are
custom-painted (a row IS a bar on a time axis; laying that out with widgets
would fight the mapping): drag a bar to slide the track's START, click the
dot to disable it, double-click to cycle hold/loop/pingpong, click empty
track space to seek. **Per-`.cif` outliner row** (Christian's annotated
mock-up): a crystal gets ONE extra child row carrying "Show unit cell",
"Asymmetric unit", "Full unit cell" and "Advanced…" — controls unique to that
kind of object, on that object's row. "Advanced…" opens the ❖ page with the
crystal you came from still active, and the ❖ TAB greys out when the active
molecule has no cell. **The Apply button is gone**: every control there is a
switch or a small count, and a change you have to confirm is a change you
cannot judge. Christian's note that the same pattern will suit proteins later
is recorded in `CrystalControls`' docstring.

Round 22 (2026-08-02, SCENE CLOCK): **one playhead for the whole scene**
(`core/timeline.py`). Each `Structure` used to own an integer `current_frame`
and the bar drove whichever molecule was ACTIVE, so a second trajectory could
not play at all. Now a `Timeline` holds scene time (a float, in frames) and a
`Track` per object maps it through a **start offset, a speed and an end mode**
(hold / loop / pingpong) — several trajectories run together, staggered or at
different rates, and the bar is the scene playhead. **Frame interpolation**
(`core/interpolate.py`) with the rotation fix: a plain lerp sends every atom
along the chord, so a rotating molecule visibly shrinks at the halfway point;
`rigid_lerp` splits out the Kabsch rigid part, turns it as a real rotation,
and lerps only the residual deformation. Measured at 3000 atoms: 0.008 ms per
frame plain, 0.25 ms rigid — far below the buffer upload that follows, so
smooth playback costs nothing. Interpolated coordinates are **display-only**
(`MolObject.play_position` -> `display_coords()` -> `evaluated()`); the stored
frames are never written, so scrubbing cannot damage a trajectory. Bonds are
re-perceived only when an object's nearest INTEGER frame changes, never per
tick.

Round 21 (2026-08-02, tools batch): **the measurement tool did not exist** —
the toolbar button only printed a hint, so clicking it genuinely did nothing.
It is a real checkable tool now: it owns clicks in both modes, collects up to
four atoms in click order (click again to unpick), never touches the
selection, and draws the value **in the viewport** rather than the status bar
where it kept being covered. Esc finishes. **Outliner columns were three
fixed pixel widths totalling 290 px**, so any narrower dock pushed the Style
column behind a horizontal scrollbar and the per-molecule display settings
could not be reached; the name column stretches now. **Tab in the array
modifier's spin boxes jumped into edit mode** — `on_tab_pressed` checked only
the transform panel, and now checks every panel. **Crystal page** in the
properties dock (❖): the asymmetric-unit / full-cell / packing switch, the
supercell counts, a cell-box checkbox and the cell parameters — it existed
only in a menu and F3 before, which is exactly where nobody finds it. **Meta
atoms glow** (three additively-blended shells, a cheap stand-in for bloom)
and are **dressed with placeholder hydrogens on creation** so the geometry
they enforce is visible and editable instead of being free-drawn over.

Round 20 (2026-08-02, session bug batch): **element TYPING removed — the
periodic table is the only way to pick an element.** Typing forced edit mode
to swallow every letter (costing every letter hotkey), still could not spell
Ge (G starts a grab), and the tool key `e` collided with the tail of
Ge/Fe/Be/He/Ne/Re/Se. Letters are ordinary hotkeys in BOTH modes again and
`E` is a normal operator key for the draw tool. **Measurement "tool
unresponsive" was the status bar**: `_measure_label` was added with
`addWidget`, and a temporary `showMessage` hides ordinary status widgets —
which every atom pick emits. Both labels are permanent now. **Deleting every
atom in edit mode no longer deletes the OBJECT** (you are standing inside it
with the draw tool; removing the outliner entry left edit mode pointing at
nothing, so nothing could be drawn). **Settings is modeless** — it
live-applies sliders, so locking the viewport and outliner while judging a
sphere size was backwards. **Meta atom opens regardless of selection** and
arms as the draw element; the button then reads "Meta: Fe - octahedral", and
picking a real element disarms it. Periodic-table cells nudge on press.
**The grid is genuinely infinite**: it was a 5000 A quad with fixed 1/10 A
rulings, so it had an edge and moired at distance. It is now a full-screen
triangle unprojected per fragment onto z = 0, writing `gl_FragDepth`, with
Blender-style spacing that steps by decades as the camera pulls back, and
axes drawn INSTEAD of the grid where they land rather than blended with it.

Round 19 (2026-08-02, crystal fixes + META ATOMS): **the cell box was drawn
at `obj.origin`, which is the CENTROID** — so it sat a whole centroid vector
away from its own atoms (Christian's benzoic-acid screenshot). It is now
placed by a **Kabsch fit against reference atoms** stored at import
(`cif.rigid_from_reference`), which also answers "update the frame DURING a
transform": the fit runs while painting, so the box tracks a grab or rotate
live. Hooking the transform paths instead was rejected — a plain grab moves
atom coordinates without touching `obj.origin`, so there is no single frame
to hang the cell off. **Molecules are reassembled across the cell boundary**
(`cif.unwrap_molecules` + `periodic_neighbours`, minimum-image): wrapping
each atom into [0,1) on its own left stray hydrogens stranded on the far
face, which is what differed from the CCDC reference. **Asymmetric unit /
full cell / packing** are switchable (View > Crystal, or F3), all regenerated
from the stored asymmetric unit so switching cannot drift. **Meta atoms**
(`core/meta.py` + the ✳ button on the periodic table): a centre carrying
geometry + donor distance + the element it becomes on export. Locked centres
freeze themselves AND their donors during optimisation, so the coordination
sphere cannot collapse under a force field with no parameters for the metal,
while the ligands still relax. Drawn as the dummy `Xx` in the app; written as
the real element on export, and an unset element is REPORTED rather than
guessed.

Round 18 (2026-08-02, CIF + edit-mode paper cuts): **native CIF reader**
(`core/cif.py`) that KEEPS the crystallography — cell, space group, symmetry
operators and the asymmetric unit all survive into
`Structure.metadata` (so they ride undo snapshots and `.molom` savepoints for
free), and `expand()` applies the operators with minimum-image de-duplication
so special positions do not pile atoms on top of each other. It runs BEFORE
OpenBabel for `.cif`/`.mmcif` (OpenBabel reads the file but throws the
symmetry away) and falls back to it silently. **Unit-cell box** drawn as a
QPainter overlay with a/b/c in the axis colours, F3 "Show unit cell box" +
"Unit cell: report cell parameters". Fixes from Christian's screenshot:
**the tool column moved below the edit header** (at y=8 the first button sat
on top of "EDIT | name | draw: X", which read as clipped text), banners now
size from `horizontalAdvance` not `boundingRect`, **Alt+A deselects again**
(the `&App` menu MNEMONIC claimed Alt+A — a mnemonic is a real shortcut, so
it went ambiguous with deselect-all and Qt fired neither; the menu is now
"A&pp" and `_check_menu_mnemonics()` guards it), **the draw tool is disarmed
when leaving edit mode** (the flag used to survive into object mode where the
toolbar reports "select", so Tabbing back came up armed and the periodic
table stayed hidden — the "sometimes doesn't show"), and **drawing or
converting an atom now leaves NOTHING selected** (otherwise the next pick
from the periodic table silently converts the atom you just made).

Round 17 (2026-08-02, element-picker batch): **floating periodic table**
(`ui/periodic_table.py` + `core/ptable.py` layout) over the viewport, right
of the tool column, in **plain edit mode only** — with the draw tool armed
the element is on the toolbar and every click is a drawing gesture, so the
chart would just be in the way. Cells are painted in the element's own Jmol
colour (the table doubles as the viewport legend) and clicking one goes
through the SAME path as typing (`MolViewport.apply_element`). **Typing now
accepts full element NAMES, case-insensitively** ("carbon", "IRON") next to
symbols — `elements.from_text`/`symbol_from_text`, which also stops a
mistyped name being truncated into an element ("unobtainium" used to give
uranium). **The draw toggle is unshifted `e` only**: Shift+E used to toggle
too, which made Er/Eu/Es untypeable, and CapsLock is deliberately ignored so
a stray CapsLock cannot turn "toggle the tool" into "type an element".
**Atom labels are much smaller, not bold, and in a wide sans** (Verdana
first), with a Settings size slider — and they are now sized by the atom's
RADIUS rather than fitted to the text's width, which is what made "C" 18 px
and "C12" 6 px on identical atoms.

Round 16 (2026-08-01, PC/mouse batch — first session on the DESKTOP, not the
laptop): **device-aware scroll** (`core/input_map.py`) — a notched mouse
wheel now ZOOMS (one detent = one step) while a precision trackpad still
orbits; Ctrl/Shift keep meaning zoom/pan on both, so only the plain gesture
differs. The preset is *auto* by default and decides **per event** from
`pixelDelta` (trackpads report it, wheels never do); Settings has an explicit
trackpad/mouse override. Mouse navigation filled in: **Shift+MMB pan,
Ctrl+MMB zoom-drag, Alt+LMB orbit** (mice whose wheel-click is unusable),
RMB pan unchanged. **Every shortcut now comes from the operator registry**
(`key=` on the op, installed by `_install_shortcuts`) instead of riding on a
menu entry — the round-15 menu thinning had silently unbound O, Home, End,
Shift+R, B, Shift+B, Ctrl+B, Ctrl+P and the box-select chord, and **F3 was
bound TWICE (Edit + App menus), which Qt treats as an ambiguous overload and
refuses to fire at all** — that is why the operator palette "disappeared".
Origin edit moved from `O` to **Alt+O** (plain O is oxygen in edit mode; see
the gotcha). `duplicate_keys()` makes a clash a startup error.

Round 15 (2026-07-31, unified right pane): **ONE right-hand dock** — the
outliner became a PAGE of the properties dock alongside Modifiers and Force
field (`ui/properties.py` tab strip); no more separate outliner dock or FF
edge tab, one ◀ tab remains. **Modifier rows are collapsible cards**
(header = enable checkbox + name + a one-line summary + delete; body
COLLAPSED by default), stacked in a QVBoxLayout column, with narrow spin
boxes and `ScrollBarAlwaysOff` so nothing is cut off horizontally.
**VESTA-style outliner tree**: molecule → per-element groups (`C (8)`) →
individual atoms, everything collapsed by default and atom rows built only
on expand. Element groups AND atom rows carry the SAME three
squares (`RowControls`): colour (right-click resets to the element colour),
label on/off, label type — a group click just applies to every atom of that
element, and a `~` marks a mixed state. Label type is per-atom
(`atom_label_modes`, falling back to the object's `label_mode`); custom text
and label colour hang off the type square's menu. These live on MolObject (`atom_colors`, `atom_labels`,
`atom_label_text`, `atom_label_colors`, `label_mode`), are sparse, and
round-trip through snapshots and `.molom` savepoints. Array copies inherit
the base atom's colour (`idx % n_base`).

Round 14 (2026-07-31, modifier batch): **non-destructive modifier stack**
(`core/modifiers.py`, `ArrayModifier`) — `MolObject.evaluated()` feeds
DISPLAY and EXPORT while picking/editing/the force field stay on the base
atoms, so a 3000-atom slab still edits like one unit cell;
`apply_modifiers()` bakes and clears. Stack survives undo snapshots and
`.molom` savepoints. **Properties dock** (`ui/properties.py`) with Blender's
vertical tab strip — pages: Modifiers, Force field (the optimise panel moved
in as a page rather than owning its own dock). **Deleting an atom takes its
terminal hydrogens** (`edits.delete_atoms(with_hydrogens=True)`).
**Shift/Ctrl + double-click adds a whole molecule to the selection**;
outliner rows are ExtendedSelection and offer **Merge** in the context menu.
The round-13 double-click-drag C2 builder was REMOVED — it collided with box
select and click-then-drag-from-the-atom does the same job.

Round 13 (2026-07-31, deferred items + render batch): **C2 fragment builder**
— double-click-drag on empty space in draw mode gives ethane/ethene/ethyne
by drag distance (order from the length ratio, hydrogens filled on release:
6/4/2 H). **Dragging off a terminal hydrogen now grows from its heavy atom
and consumes the H** (Avogadro semantics) — without it a freshly auto-filled
CH4 puts H's under the cursor and chains bonded to a hydrogen. **Suspected
H-bond overlay** (`bonding.find_hydrogen_bonds`, geometric D-H...A criterion,
computed across all VISIBLE molecules so inter-molecular contacts show;
dashed cyan + distance, F3 toggle). **Cursor wrap fixed**: it re-seeded by
*updating* the modal, so the teleport cancelled the drag —
`_ConstraintMixin.reseed()` now moves the reference without accumulating,
and modals `grabMouse()` so moves past the dock edge still arrive.
**`MolViewport.render_image()`** — offscreen FBO render with a resolution
multiplier, +2 mesh subdivisions, transparent background and NO viewport
furniture (compass, origin dot, grid, labels, halos), used by Ctrl+Shift+E.

Round 12 (2026-07-31, chemistry-correctness batch): **hydrogen placement
fixed** — `adjust_hydrogens` added H's ONE AT A TIME, re-deriving the
geometry after each (bare C went linear → bent → trigonal), so methane was
never tetrahedral; it now takes all missing directions at once from the final
**VSEPR domain count including lone pairs** (`bonding.LONE_PAIRS`), giving
CH4 109.5, NH3 pyramidal, H2O bent, ethene 120. **Focus follows the cursor**
into the viewport (`enterEvent`) so Space after a panel interaction does not
go to the panel. Default sphere scale **0.9**. **Home/Pos1 moves the
selection centroid to the world origin** (F still frames). Tabbing into a
transform field now **starts typing**. **Apply location/rotation/all** (atoms
are in world space, so applying just zeroes the reported transform).
**SMILES from the graph** (`io.structure_to_smiles`) + copy-to-clipboard and
**name-from-structure** via PubChem (`resolve.name_for_smiles`).
**Scene.merge** for FF work on H-bonded assemblies (originals kept+hidden by
default). **F3 grouped by category** with dividers, plus operator
**aliases** so "recalculate bonds" finds "re-perceive bonds". Ctrl+N is now
new-empty-molecule; add-from-SMILES moved to F3.

Round 11 (2026-07-31, startup + drawing-guidance batch): **OpenBabel UFF
fixed** — the wheel SETS `BABEL_DATADIR` itself, to a share dir containing
only splash.png, and re-sets it as the C extension initialises;
`forcefield.ensure_babel_datadir()` therefore VERIFIES `UFF.prm` is present
and overrides, and is called AFTER the import, immediately before
`FindForceField`. **cubane is the default scene** (`core/build.py`, built
analytically so it is exactly centred and axis-aligned — Blender's default
cube), replacing the import-instructions overlay. **Drag-draw guidance**:
hovering an atom rings it and snaps (ring closure is now obvious), otherwise
the length soft-snaps toward the single bond and **squeezing shorter raises
the bond order** using the same length ratios as import perception. **Bond
hover draws one stick per order, no text.** **Bond-order changes re-dress
hydrogens** (otherwise every order edit needed a manual H fix before FF).
**Edit mode owns every unmodified letter** (ShortcutOverride in
`MolViewport.event`) so Ar/Ag/Au/Dy type instead of firing align/duplicate —
G and R are still transforms. Optimize panel is edit-mode only with its tab
on the RIGHT edge (its dock's edge); **Tab inside the transform panel walks
fields** instead of switching mode.

Round 10 (2026-07-31, feel + drawing batch): **wheel resolution fixed** —
`angleDelta` was read as pixels, so ONE wheel notch (120 = 15 deg of wheel)
became ~43 deg of rotation; `_wheel_px` now prefers `pixelDelta` (precision
trackpads) and converts angleDelta via degrees. This was the "jagged
view"/"roll only in 30 deg steps" report. **Draw tool is behind E** (and the
toolbar's ✎) — clicks no longer grow atoms by accident; typed element +
Enter overwrites the SELECTION in place. **Ring closure**: dropping a
drag-drawn atom on another atom discards the temp atom and bonds the two.
**Blender-style viewport toolbar** (`ui/toolbar.py`, floating over the GL
widget, top-left). **Outliner "+ New molecule" row** → creates + renames →
Tab draws. **Compass hover lights ONE ball**. **Hover a bond + 0-4** sets its
order (4 = quadruple, rendered as four cylinders). **Alt+A** deselects.
**Horizontal cursor wrap** in G/R modals. `square_pyramidal`/`seesaw` added
to the coordination templates.

Round 9 (2026-07-31, force field batch): **`core/forcefield.py`** —
MMFF94 -> UFF -> OpenBabel-UFF tiering (same default as OWB's coordinate
pre-optimisation and Avogadro), `fixed` atoms supported (freeze-the-rest, and
the hook for coordination restraints) — driven by an **Optimize dock**
(Task/Method/Steps/Start, worker thread, one undo step, never touches
connectivity); **coordination-aware hydrogen re-placement** on drag-draw
(`edits.idealize_terminal_hydrogens` + `coordination.repel_directions`, a
VSEPR relaxation — the rigid template dropped H's onto existing bonds when
the heavy neighbours were not near-ideal); **origin handle now emits
`origin_active_changed`** so the transform panel switches to the origin by
itself; Ctrl+A/Space scoped to the edited molecule; edge tabs restyled
(translucent, 12 px, arrow-only, on their dock's own edge); and the
`_macro_serial` AttributeError fixed — it fired on EVERY edit commit
including each tumble gesture, which is what made orbiting feel like it
stuttered.

Round 8 (2026-07-31, pilot + drawing batch): **Shift+R repeats the whole
ACTION** (after D+X+6 it duplicates again and offsets by the same vector —
`MainWindow._repeat_macro`, superseded by any plain G/R via
`viewport.transform_serial`), **Ctrl+E geometry / Ctrl+Shift+E image (PNG)
export**, **sphere-size slider** (`viewport.atom_scale`, live), **shuttle
mode** (UE5 pilot: camera snaps into the origin, WASD+QE fly, scroll steers,
Ctrl+scroll rolls, Esc lands; cockpit-close atoms hidden; F3 only),
**Tab on an empty scene creates a molecule** to draw into, **drag-add is now
pure Avogadro** (view-plane follow, confirm on release + H adjust — the
Blender grab modal was removed from it), **bond lengths follow the element**
(`edits.adjust_bond_lengths`: H->Zn stretches the bond; terminal atoms only),
**transform panel docked BOTTOM** and compact, **origin snap / align-to-world
ops** plus the panel editing the ORIGIN while the handle is up, and the
anchored-tumble decision is now locked at gesture START.

Round 7 (2026-07-31, arrangement batch): **plain left-drag = box select**
(the double-click-only trigger never fired on a trackpad — third report;
lasso works the same way once armed), **origin editing moved into edit mode
as a persistent orange DOT handle** drawn on top of everything (click = pick
up + gizmo, click off = set down; O snaps it to the selection first),
**D duplicate** (new outliner object inheriting style/frame, partial copies
re-perceived + H-filled, grab starts immediately, duplicate+move is ONE undo
step), **Shift+R repeat last transform**, **End drops the selection centroid
to z = 0**, **local view `/`** (isolate + restore), **F frames the selection**
(scene only when nothing is selected), **export writes every VISIBLE
molecule** (not just the active one — `MainWindow.export_visible`),
**outliner eye drag-painting + Shift+click isolate/invert**, viewport picking
now sets the ACTIVE object (so Tab edits what you clicked), and the
**transform panel is its own floating window** beside the outliner.

Round 6 (2026-07-31, edit mode + chemistry batch): **Blender-style mode
system** (`Tab` object <-> edit; edit mode = orange border + header, picking
and edits scoped to ONE molecule), **draw tool** (click an atom -> becomes
the draw element, click empty space -> new atom; letters type an element
symbol confirmed with Enter, which also becomes the new draw element),
**hydrogen adjustment** (`edits.adjust_hydrogens` / `set_element_adjusted`,
placement via coordination templates), **bond ORDERS perceived once at
import** (`bonding.perceive_bond_orders`: length ratio + valence cap +
augmenting-path repair so rings come out Kekule-alternating; metals never get
multiple bonds) and **never re-perceived automatically after an edit**,
bond-order keys 1/2/3/0, **savepoint files** (`core/project.py`, `.molom`
JSON: scene + origins + orders + frames + camera/view; Ctrl+S / Ctrl+Shift+P),
**undo depth setting** (default 30), **origin edit now runs the REAL G/R
modals** (axis locks, local repress, typed numbers, precision), **anchored
tumble requires the cursor on the selected atom** and accepts **X/Y/Z axis
locks**, `core/coordination.py` geometry templates (the "meta atom"
foundation), and a picking fix: pick arrays rebuild on demand instead of
only inside `paintGL`.

Round 5 (2026-07-31, fix batch 2): **box/lasso select actually works on a
trackpad** (drag slop is now cumulative from the press — see gotchas),
**edge tabs track the viewport edge** via an eventFilter on the central
widget, **A = selection-aware align modal** (1 atom → world origin; 2 atoms
across 2 mols → dock at 3 Å; 2 atoms one mol → axis key; 3+ atoms → plane
key, Shift+Z = XY), add-atom moved to **Shift+A**, **multi-SMILES import**
(ChemDraw dot form) building one object per molecule, z-stacked with 2 Å
clearance and auto planar-aligned to XY — file imports stay untransformed.

Round 4 (2026-07-31, fix batch): R modal **scroll-to-rotate** + no orbiting
under modals (the actual "R doesn't work" fix), **R pivot = object origin**,
guide lines near-plane-clipped (`_segment_screen`), compass restyle (hover =
white LETTERS, full-size negative balls with −X labels), **Unreal-style
origin gizmo** (arrows + quarter arcs), anchored tumble restricted to
single-atom selections, **align-2-atoms-to-axis + flip** ops, **O = origin /
Shift+O = projection swap (final)**, app-wide dark Fusion palette
(`apply_dark_theme`), outliner rows click-select + context menu, transform
edge tab (◀ T under ◀ O; docks resize the viewport so the compass shifts
with them automatically).

## The golden architectural rule (inherited from OWB)
**`molom/core/` is UI-free AND GL-free** — pure numpy/stdlib, unit-testable
offline (`python -m pytest tests/ -q`, 679 tests, no display needed).
**`molom/ui/` is a thin shell**: `viewport.py` only uploads buffers and
forwards events; `app.py` only wires menus to core calls. Keep it that way:
new feature = core function + test first, then a UI hook.

## Data provenance (do not casually regenerate)
`molom/core/elements.py` is **GENERATED** from Avogadro 2's
`avogadro/core/elementdata.h` (BSD-3, Kitware) by `tools/gen_elements.py`;
the fetched header is vendored at `tools/avogadro_data/elementdata.h`
(fetched 2026-07-30). 119 entries (index = Z, 0 = "Xx" dummy). VdW radii =
Alvarez 2013; covalent radii = Pyykkö 2009; colours = Jmol scheme with
Avogadro's tweaks (H 240 not 255, C 50% grey, F shifted blue). See
THIRD_PARTY_NOTICES.md. NOTE: OWB's `transform.py` carries Cordero-2008
covalent radii — slightly different values; MoloM deliberately uses Avogadro's
Pyykkö set so bond perception matches Avogadro exactly.

Behavioural constants (verified against avogadrolibs sources, 2026-07-30):
- **Bond perception** (`core/bonding.py`) = `Molecule::perceiveBondsSimple`:
  bond iff `0.32² < d² < (r_cov_i + r_cov_j + 0.45)²`, He/Ne/Ar/Kr never
  bond (Xe DOES), H–H never bonds, radii ≤ 0 → 2.0 Å. All perceived bonds are
  order 1; `perceive_structure_bonds(keep_orders=True)` preserves user-drawn
  orders across re-perception (frame changes).
- **Ball-and-stick sizing** (`core/style.py`) = Avogadro's ballandstick.cpp:
  sphere = VdW × 0.3; bond cylinder r = 0.1 Å; double bond = 2 cylinders at
  ±1.0×r_bond offset, each 1.3×r_bond, NO centre cylinder; triple = 2 at
  ±2.0×r_bond offset, 1.15×r_bond, PLUS the centre one (C++ fallthrough);
  offset dir = unitOrthogonal(bond) rotated 45° about the bond axis.

## How the pieces fit
- `core/structure.py` — `Structure`: symbols, frames (list of Nx3 numpy),
  bonds [(i,j,order) i<j], charge/mult from metadata. `coords` aliases the
  current frame.
- `core/io.py` + `core/_obabel_worker.py` — **vendored port of OWB's
  `coords.py`** import cascade (keep diffable; upstream fixes both ways):
  native multi-frame xyz (JSON-comment metadata) → OpenBabel in a
  **timeout-guarded subprocess** (15 s; SWIG holds the GIL so threads can't
  be killed) → RDKit fallback → heuristic `Label x y z` salvage flagged
  VERIFY. Plus SMILES→3D (RDKit ETKDGv3+MMFF seed 42, OpenBabel UFF
  fallback), SMILES-list files, Qt name filters (`import_name_filters`).
  `frames_are_trajectory` = same symbol sequence in every record.
- `core/camera.py` — orbit camera (quaternion + arcball), `fit()` frames the
  VdW bounding sphere. Matrices are math-convention row-major; upload with
  `transpose=GL_TRUE`.
- `core/meshes.py` — unit icosphere (subdiv 2 = 320 tris) + open unit
  cylinder (+z, 24 segs); `cylinder_transforms` builds instance mat4s
  vectorised (guards zero-length segments → NaN-free).
- `core/picking.py` — CPU ray-sphere picking (no GL readback, testable).
- `core/edits.py` — add/delete atoms (all frames, bond reindexing),
  set_element, add/remove/cycle bond (none→1→2→3→none),
  `suggested_position` (least-crowded direction at covalent distance).
- `core/measure.py` — distance/angle/dihedral (atan2 convention; matches
  what a `describe_selection` status line needs for 1–4 picks).
- `core/scene.py` — Scene of MolObjects (structure + visible + style_key +
  unique `.001`-style names + **origin/orientation local frame** +
  snapshot/restore for undo). Selection/identity = (obj_id, atom).
- `core/ops.py` — operator registry for F3 (labels, categories, `enabled(ctx)`
  predicates; `search` ranks enabled-first). Carries BOTH `shortcut` (prose
  for the palette) and `key` (the QKeySequence string the window binds —
  the single source of truth for hotkeys, see `duplicate_keys`). Log:
  docs/OPERATORS.md — KEEP IN SYNC.
- `core/input_map.py` — ORBIT/ZOOM/PAN from the pointing-device preset plus
  whether the wheel event carried `pixelDelta`. The whole trackpad-vs-mouse
  decision, UI-free.
- `core/timeline.py` — the SCENE CLOCK: one playhead in scene frames, one
  `Track` per object (start offset / speed / hold-loop-pingpong). UI-free, so
  the whole mapping is testable without a timer. Also owns the round-30
  frames/images/seconds split (`smoothing`, `fps`, `advance_images`) and the
  looping interval (`range_start`/`range_end`, `play_start`/`play_end`).
- `core/interpolate.py` — coordinates BETWEEN frames. `rigid=True` splits the
  Kabsch rigid motion out and rotates it properly instead of cutting the
  chord; only the residual deformation is lerped.
- `core/cif.py` — CIF parsing that keeps the crystallography: `Cell`
  (fractional<->Cartesian matrix, corners/edges for the box), `SymOp`
  (parses "-x+1/2, y, -z"), `parse_cif` -> asymmetric unit, `expand` ->
  full cell with minimum-image de-duplication. No new dependency; the CIF
  subset real files use is small. `ui/viewport.cell_of(obj)` reads the cell
  back out of `Structure.metadata["cell"]`.
- `core/ptable.py` — where each element sits in the 18-column chart (f-block
  detached on rows 9/10) + the black-or-white text rule for a cell painted in
  the element's colour. Drawn by `ui/periodic_table.py`.
- `core/elements.py::from_text` — resolves a SYMBOL or a full NAME in any
  case ("fe", "IRON"). Everything user-typed should go through this, not
  `atomic_number`, which truncates and would read "iron" as iodine.
- `core/internal.py` — INTERNAL COORDINATES: split the molecule at a bond and
  set a distance / angle / dihedral so the trailing fragment follows rigidly.
  `moving_group` returns `(indices, blocked)`; `blocked` covers both a ring
  and a non-bonded pair inside one fragment, where "which half is the far
  half" has no answer and only the picked atom may move.
- `core/flight.py` — the flight model behind right-mouse fly AND shuttle mode.
  World-space velocity, thrust, exponential drag (stable at any dt), speed
  cap, scene-size scaling. No roll: pitch is clamped short of vertical and
  `Camera.fly_look` rebuilds from azimuth/elevation rather than composing
  quaternion deltas, so roll cannot accumulate over a long flight.
- `core/manipulate.py` — G/R modal math (`GrabState`/`RotateState` on a
  shared constraint mixin: global/local axis+plane cycling, Shift-precision
  increment scaling, numeric buffers; ray-plane / ray-line solvers; the
  rotate screen-sense flip is chirality-tested).
- `core/rotations.py` — axis-angle/Euler-XYZ (Blender order Rz·Ry·Rx) ↔
  matrix/quat + rigid rotate-about-pivot. `core/undo.py` — snapshot stack.
- `core/align.py` — RANSAC largest-planar-cluster + align-to-plane rotation,
  align-vector-to-axis + flip, z-stack offsets for SMILES batches.
- `core/coordination.py` — coordination-geometry templates + `fit_directions`
  (template fitted to existing bonds) + `CoordinationSpec` /
  `ideal_donor_positions`. Used NOW for hydrogen placement; it is the
  foundation for guided metal-complex pre-optimisation ("meta atoms").
- `core/project.py` — `.molom` savepoints (JSON, versioned, atomic write);
  pairs with `Scene.to_dict()/from_dict()`.
- `core/forcefield.py` — MMFF94/MMFF94s/UFF via RDKit, OpenBabel UFF as the
  last tier; `optimize(symbols, coords, bonds, method, steps, fixed)`.
  Degrades instead of raising: a half-drawn molecule is often not valid
  chemistry, and the user still wants the best geometry available.
- `core/modifiers.py` — non-destructive stack. `evaluate_stack` never mutates
  its input; the object's real atoms only change on Apply. Anything that
  DRAWS or EXPORTS should use `MolObject.evaluated()`; anything that EDITS
  (picking, force field, chemistry ops) must use `obj.structure` — mixing
  the two is how a modifier stack turns into a debugging nightmare.
- `core/mathexpr.py` — AST-whitelisted arithmetic eval for N-panel fields.
- `core/selection2d.py` — project_points + rect/polygon containment (box &
  lasso). `core/grid.py` — grid colour constants + fade distance (the grid
  itself is a shader in viewport.py since round 3).
- `core/resolve.py` — vendored OWB name resolver (OPSIN → PubChem PUG-REST →
  autocomplete; injectable `get` for offline tests).
- `ui/viewport.py` — QOpenGLWidget, GL 3.3 core, **instanced** rendering:
  ONE sphere mesh + ONE cylinder mesh across the whole scene (matrices
  transposed to GL column order at upload); bonds = two half-cylinders
  coloured by their atoms; wireframe = GL_LINES; procedural infinite grid
  quad. Selection = translucent enlarged spheres re-using the sphere buffer
  (sets `_needs_rebuild` after). Owns input modes: select tools, G/R modals,
  origin-edit gizmo, anchored model rotation, compass hover/click hit lists,
  QPainter overlays (compass/rubber band/lasso/constraint guides/anchor
  crosshair/atom labels). Flat pick arrays parallel `_atom_map`. Undo hooks:
  `on_model_edit_begin/_cancel` callbacks into the app.
- `ui/app.py` — scene owner; operators registered + menus that trigger them;
  outliner + transform-panel wiring; UndoStack pushes before every mutation;
  trajectory strip drives the ACTIVE object; measurement label via
  scene.pick_label + measure.describe_picks; Settings/QSettings.
- `ui/outliner.py` — dock tree: name (dbl-click renames), eye checkbox,
  style combo; Delete key removes; M toggles (plus ◀/▶ edge tab button).
- `ui/transform_panel.py` + `ui/widgets.py` — N panel over DragValueEdit
  (drag-scrub / click-type / arithmetic; committed-only signal for typed
  values so undo can snapshot first). `ui/dialogs.py` — Settings
  (sensitivity + precision sliders), F3 palette, ResolveNameDialog.
- `__main__.py` — `molom [file]`; `--selftest` = headless core check (no GL);
  `show_startup()` = maximized default / windowed-upper-right setting.

## Christian's cross-cutting UI principles (apply to EVERY new control)
Stated 2026-08-03 as general rules, not one-off requests:
- **rows of tick boxes must be paintable by dragging** — hold and sweep, like
  the outliner's visibility eyes (`ui/dragcheck.py::install`);
- **Tab walks fields in any panel** that takes typed input, never falling
  through to a global hotkey (`MainWindow.on_tab_pressed` checks every panel);
- **buttons carry a meaningful LETTER**, not just a glyph, with the
  explanation in the tooltip;
- **a group of sub-options needs a visible expansion arrow**, or nobody
  discovers it;
- **popups anchor so they stay on screen** (the outliner is against the right
  edge, so its popups anchor right).
He is a heavy Blender user: a control needing one click per item where a
sweep would do reads as unfinished.

## NEVER write a parser fixture from memory
Round 27: I wrote a synthetic ORCA FREQ block instead of using a real file,
and was rightly pulled up on it. Christian has real jobs on disk and will
supply one. Vendor a VERBATIM excerpt into `tests/data/`. **Check ORCA
Workbench first** — `ACH-Orca-Studio/orca_studio/core/orca_parser.py` already
parses frequencies, IR and thermochemistry against real jobs; MoloM only adds
the NORMAL MODES eigenvectors, and the shared parts are kept diffable exactly
like `io.py` is with OWB's `coords.py`. Bonus: one ORCA file often prints a
quantity twice (VIBRATIONAL FREQUENCIES and IR SPECTRUM), giving an
independent cross-check inside a single fixture.

## Ligand templates: the two design questions Christian asked (2026-08-03)
- **Only GEMINAL placeholders.** Every selected placeholder must hang off ONE
  shared atom (`templates.common_centre`). Placeholders on two different
  centres describe a BRIDGING ligand, which is a genuinely different
  operation — the ligand would have to span them, and "coordinate to what?"
  has no single answer. Refused with a clear message rather than guessed at.
- **Placeholders need NOT be hydrogen.** Any TERMINAL atom qualifies, so a
  Cl, a dummy or a meta atom's dressing H all work the same way. The check is
  "has exactly one bond", not "is hydrogen" — restricting to H would be an
  arbitrary limit with no geometric justification.
- Under-determined fits are resolved, not averaged: ONE donor gets translated
  onto the slot and rotated so the ligand's bulk points away from the centre
  (spin about the new bond left free for R); TWO donors align the donor-donor
  vector then spin so the backbone points outward.

## Hard-won gotchas (don't re-learn these)
- **Qt delivers events to a widget WHILE IT IS BEING CONSTRUCTED, and
  `MolViewport.event()` is overridden** (round 34). Creating the flight
  QTimer with `self` as parent sends a ChildAdded, the override runs
  `_keyboard_captured()` -> `modal_active()`, and that read `self._internal`
  before `__init__` had assigned it. The AttributeError happens inside a C++
  callback, so it does NOT surface as itself — the next PySide call failed
  with `SystemError: <class 'QTimer'> returned NULL without setting an
  exception`, which points nowhere near the cause and cost 133 test errors to
  chase. Every attribute `event()` can reach now has a CLASS-level default on
  `MolViewport` (`_fly`, `_internal`, `_grab`, `_rotate`, `_shuttle`,
  `_align_wait`, `_origin_active`, `_draw_drag`). Add to that list, not just
  to `__init__`, whenever a new modal state joins `modal_active()`.
- **`isVisible()` is False for anything on a non-current QStackedWidget page**
  (round 34). `CrystalPage._toggle_kinds` used `not isVisible()` to decide
  which way to toggle, so whenever the ❖ tab was not the page on screen the
  arrow expanded every time and never collapsed. Use `isHidden()` — the
  widget's OWN flag — for any "am I currently expanded?" test. The same trap
  applies to `isEnabled()`, which also folds in every ancestor.
- **`QToolButton.clicked` passes the button's CHECKED state** (round 34), and
  a non-checkable button therefore passes `False` forever. Connected straight
  to a `toggle(force=None)` handler that reads its first positional argument,
  it means "collapse" on every click. Symptom: the arrow works once (because
  something else opened the group) and then appears dead — Christian's
  "you have to untick and retick to get control over the arrow back". Swallow
  the argument: `lambda _checked=False: self._toggle()`.
- **A modal state that is not G or R must not reach `_paint_modal_guides`**
  (round 34). It reads `state.axis`, which `ScalarState` does not have — and
  because the call sits inside `paintGL`, Qt PRINTS the traceback and carries
  on, so the app looks fine while the overlays silently stop drawing. Found
  by a scripted GUI run, invisible to every logic test. Two lessons: guard
  the call site AND use `getattr` inside, and **run the GUI smoke script when
  touching paint paths** — the offscreen platform returns a null framebuffer,
  so pixel checks need a real window.
- **The properties pages describe the ACTIVE molecule, so they belong in
  `_sync_all`** (round 34). They were only refreshed by an outliner click or
  by toggling the dock, so importing a .cif left the ❖ page still saying "no
  unit cell" about the crystal that had just become active — which reads as
  "the page is greyed out even though a cif IS selected".
- **QPainter resets GL state.** Overlays (hint, compass, rubber band, grab
  guide) use QPainter every frame now; `paintGL` re-asserts
  `GL_DEPTH_TEST`/`GL_MULTISAMPLE`/blend-off EVERY frame. Symptom was bonds
  showing through spheres + black self-overlapping sphere shading.
- **QStatusBar temporary messages hide non-permanent widgets.** The
  trajectory bar originally lived in the status bar and `showMessage("Loaded
  ...")` made it invisible. It now sits in the central QVBoxLayout under the
  viewport. Don't move it back.
- **Single-letter QAction shortcuts (A/E/B/G...) would steal keys from the
  grab modal.** During grab the viewport accepts `QEvent.ShortcutOverride`
  (see `MolViewport.event`) so X/Y/Z/digits/B reach the modal; it also
  `grabKeyboard()`s. Don't remove either half.
- **The Shoemake arcball was deliberately replaced** (round 2): its
  pixel→sphere mapping accelerates toward the viewport edges — the exact
  non-uniformity Christian reported. Round 3 then replaced free-trackball
  CAMERA orbit with a Blender **turntable** (no roll — Christian's vertigo
  fix); `Camera.trackball_quat` remains only as a math utility.
  `Camera.orbit`/`rotate(pivot=...)` keep the pivot's SCREEN position
  invariant (`C' = P − R'ᵀR(P−C)`). Tests pin all of this.
- **Orbit-with-selection is a MODEL EDIT** (round 3): the gesture rigidly
  rotates the selected molecule(s) about the selection anchor — coordinates
  change, an undo entry is coalesced per gesture (>0.6 s scroll gap = new
  gesture), and origin/orientation ride along. Hover-under-cursor pivot
  picking was REMOVED on purpose (pivot jumped mid-rotation when the cursor
  grazed another atom). Don't reintroduce it — the anchor is the selection.
- **`O` keys, FINAL (round 4, Christian's call): O = origin edit,
  Shift+O = persp/ortho.** (Round 3 had it the other way.) Axis-key REPRESS
  went from "unlock" (round 2) to Blender's 3-state global→local→off cycle
  (round 3) — with an identity object frame the local step is skipped.
- **The round-3 R modal "didn't work" for two stacked reasons** (round 4
  post-mortem): (a) on a laptop the rotate instinct is two-finger SCROLL,
  but the modal only read mouse-position angles — worse, scroll fired the
  orbit/tumble path UNDERNEATH the modal, visibly fighting it. Scroll now
  feeds `RotateState.add_angle` while R is active and plain scroll is
  swallowed during any modal. (b) The constraint guide lines were skipped
  whenever one end of the ±1000 Å line projected behind the camera —
  `front.all()` — which in perspective is nearly always; `_segment_screen`
  now near-plane-clips instead. Keep both in mind for any new modal.
- **R pivots about the OBJECT ORIGIN** (axis locks spin about the axis
  PARALLEL through the origin, not the world axis line) — Christian's spec.
  G pivots about the selection centroid. Anchored scroll-tumble requires
  EXACTLY ONE selected atom (multi-atom anchoring felt confusing).
- The grid is drawn AFTER opaque geometry, blended, depth-test ON but
  depth-write OFF: molecules occlude it, it overlays below-floor atoms, and
  the fade never punches holes in the depth buffer. QSurfaceFormat needs
  GL 3.3 for `fwidth` AA (already required).
- **The grid is SCREEN-SPACE, not a quad** (round 20). It was a 5000 A quad,
  which has an edge you can zoom out to and one fixed spacing that moires at
  distance. Now a full-screen triangle is unprojected per fragment and
  intersected with z = 0 — truly infinite — and it writes `gl_FragDepth` so
  molecules still occlude it. Spacing steps by DECADES with camera distance
  (two levels, the finer fading out across each decade). A third, finer level
  was tried and removed: at 0.1x the main spacing it aliases into a
  crosshatch that reads as a texture on the molecule. Axes are drawn INSTEAD
  of the grid where they land, never max()'d with it — blending the two is
  what made them look chewed up when zoomed out.
- **Box select is a PLAIN left-drag** (round 7). Requiring a double-click
  first was reported broken three times: a trackpad "double-tap-drag" does
  not reliably produce DblClick + moves. Don't put box select behind a
  gesture again. In edit mode a drag that STARTS ON AN ATOM draws instead
  (armed in mousePressEvent, so a click still converts on release and a drag
  never does).
- **Build a coordination sphere in ONE step, not atom by atom** (round 12).
  Re-deriving the geometry after each added hydrogen means the count is
  wrong every time except the last. Compute the final VSEPR domain count
  (bonds + new atoms + LONE PAIRS) first, then place. Lone pairs are why
  NH3/H2O need template slots rather than pure repulsion, which would spread
  the bonds into the lone-pair positions and give a flat NH3.
- **openbabel-wheel sets BABEL_DATADIR to a directory without the .prm
  files** (round 11) and re-sets it during lazy extension init, so "the
  variable is set" proves nothing and setting it early gets clobbered.
  Verify `UFF.prm` exists, override, and do it right before use. Symptom:
  `OBForceFieldUFF::ParseParamFile Cannot open UFF.prm` and a UFF tier that
  silently never works.
- **Never read `QWheelEvent.angleDelta()` as pixels** (round 10). It is
  1/8 degree; one notch = 120. Prefer `pixelDelta()` (non-null on precision
  trackpads) and fall back to degrees * a small factor. Reading it as pixels
  is what quantised every view change into ~40 deg jumps.
- **A single-letter QAction shortcut silently outranks the viewport.** E was
  bound to "Change element..." and never reached the draw-tool toggle. Any
  key the edit mode wants must NOT also be a QAction shortcut — register the
  operator with NO `key=` (E, X, Y, Z; a test pins this).
- **`obj.origin` is the CENTROID, not the world origin** (round 19). Drawing
  the unit cell at `origin + corners` displaced the box by a whole centroid
  vector. Anything anchored to the atoms must be fitted to the ATOMS —
  `cif.rigid_from_reference` (Kabsch against a stored sample) — because a
  plain grab moves coordinates and leaves `obj.origin` alone. Doing the fit
  while PAINTING is also what makes overlays track a drag live instead of
  snapping at commit.
- **A FRAMEWORK must not be unwrapped at all** (round 25). Round 19's
  whole-molecule unwrapping assumed every bonded component is finite. In a
  MOF it percolates through the boundary and is infinite, so the walk marches
  the structure across cells (MOF-5 came out over 4x2x2). Detect it while
  walking: a bond returning to a placed atom with a DIFFERENT periodic image
  means the component closes on itself — leave that one wrapped.
- **Wrap crystals by MOLECULE, never by atom** (round 19). Putting each atom
  into [0,1) independently shreds anything straddling a face — the stray
  hydrogens against the CCDC reference. Walk each bonded fragment choosing
  the nearest periodic image, then shift the fragment by its centroid.
  Bond perception for this must use the minimum image or the fragments are
  cut open before you start (`cif.periodic_neighbours`).
- **A menu-bar MNEMONIC is a shortcut too** (round 18). `&App` claimed Alt+A,
  which is Blender's deselect-all, so the two went ambiguous and Alt+A
  silently stopped working — the same failure as F3, from a completely
  different direction. `MainWindow._check_menu_mnemonics()` compares every
  menu title's `&` letter against the operator key table; a test pins it.
- **Never let a tool flag outlive the mode that owns it** (round 18).
  `draw_tool_active` stayed True after Tabbing out to object mode, where the
  toolbar reports "select" — so the flag and the UI disagreed, and Tabbing
  back in came up armed with the periodic table hidden. `set_mode` disarms it
  on the way out.
- **A drawing/conversion command must clear the selection** (round 18).
  Leaving the new atom selected means the next element pick CONVERTS it
  instead of only setting what the next atom will be: you silently lose the
  atom you just drew. Clear in `_finish_draw_drag` and `apply_element`.
- **Overlays start below `_VIEWPORT_HEADER_H`** (round 18). The floating tool
  column at y = 8 covered the edit-mode header, which reads as the header
  text being clipped rather than as two widgets overlapping.
- **Two QActions with the same shortcut = NEITHER fires.** Qt reports an
  "ambiguous shortcut overload" and skips both, so a doubled key looks
  exactly like an unbound one. F3 sat on both the Edit and App menu entries
  and the operator palette stopped opening (round 16). `_install_shortcuts`
  now builds ONE action per operator and menus reuse those objects;
  `OperatorRegistry.duplicate_keys()` raises at startup if two ops claim a
  key.
- **Keys must NOT live on menu entries** (round 16). The menus are
  deliberately an essentials shortlist — thinning them in round 15 took the
  shortcuts down with them (O, Home/End, Shift+R, B/Shift+B, Ctrl+B, Ctrl+P,
  Shift+Space,B were bound nowhere). The binding belongs to the OPERATOR
  (`key=`), which is also what makes an F3-only operator keyboard-reachable.
- **Origin edit is Alt+O, not O** (round 16, supersedes the round-4 "final"
  call). Round 11 gave edit mode every unmodified letter, and O is oxygen —
  plain O could only ever type into the element buffer, so the binding was
  dead on arrival. Ctrl/Alt combos are the only ones that survive that
  policy; Shift+letter does NOT (it types capitals, e.g. the F of Fe), which
  is why Shift+O/Shift+A/Shift+R are object-mode bindings.
- **The wheel means different things on different devices** (round 16).
  MoloM was built on a laptop where two-finger scroll orbits; on a desktop
  mouse the same code turned every detent into a ~11 deg orbit jump and left
  zoom behind a modifier. `core/input_map.py` decides ORBIT/ZOOM/PAN from the
  preset + whether the event carried `pixelDelta`. Keep the decision there,
  UI-free and tested — do NOT sprinkle device checks through `wheelEvent`.
- **An exception raised inside a Qt slot does not stop the app — it prints
  and continues**, so a missing attribute in `_on_edit_committed` looked
  like a viewport *feel* problem ("orbiting gets stuck for a second"), not a
  crash. If input ever feels laggy, check stderr for slot tracebacks first.
- **Initialise every attribute the signal handlers touch in `__init__`.**
  `_macro_serial` was only assigned in the branch that set the macro.
- **`QWidget::event()` eats Tab for focus navigation BEFORE keyPressEvent**
  (round 8). While the viewport holds the keyboard (`_keyboard_captured()`:
  modals, shuttle, origin handle, draw drag) it routes Tab to keyPressEvent
  itself; otherwise the app's Tab QAction handles it. Same guard fixes
  shuttle mode's W/A/S/D and Esc, which collide with the duplicate/align/
  cancel shortcuts.
- **Camera-vs-tumble is decided at gesture START, never per event** (round 8):
  orbiting the view until the cursor happened to slide onto the selected
  atom used to flip mid-gesture into rotating the molecule.
  `_gesture_mode` latches for the whole gesture.
- **Qt fires the first click's action before a double-click arrives.** Any
  edit-mode gesture built on double-click will therefore run the single-click
  action first (this is why draw-drag is arming on PRESS, not on
  DblClick). Deferring the single click behind `doubleClickInterval()` was
  rejected: a ~500 ms lag on every element change is worse.
- **An operator that hands off to a modal must merge undo steps**
  (`_pending_suppress` / `_last_push_suppressed` in app.py): D duplicate
  pushes a snapshot and then starts a grab that would push another, so
  Ctrl+Z used to leave the copy behind. The cancel path must NOT discard the
  operator's own snapshot — Esc after D cancels the move, not the copy.
- **Drag slop MUST be cumulative from the press position** (round 5 bug):
  it was measured per mouse-move event, and a trackpad delivers 1–2 px per
  event, so the 4 px threshold never tripped and box/lasso select silently
  never started. `_press_pos` is the reference; don't reintroduce per-event
  deltas for the "did this become a drag?" test.
- **Bare modifier presses arrive as their own key events.** Any modal that
  waits for a key (the A align wait) must swallow Key_Shift/Control/Alt/Meta
  — holding Shift for "Shift+Z" delivers Key_Shift FIRST, which otherwise
  reads as "some other key" and cancels the wait (round-5 bug: plain Z
  worked, Shift+Z never did). See `_MODIFIER_KEYS` in viewport.py.
- **Dock visibilityChanged fires BEFORE the central widget resizes**, so
  floating overlay widgets (the ◀ O / ◀ T edge tabs) position off an
  `eventFilter` on the central widget's Resize instead. Symptom was tabs
  stranded mid-viewport after closing a dock.
- **Normalisation policy**: SMILES-derived geometry is generated, so MoloM
  may rotate/centre/stack it freely (`_install_smiles_batch`). Coordinates
  read from FILES are never silently transformed — Christian's call; they
  may be measured or computed structures where orientation matters.
- **Bonds are perceived ONCE, at import** (`MainWindow._perceive_fresh` =
  connectivity + orders). Round 6 removed the automatic
  `perceive_structure_bonds` that ran after every grab/rotate commit: it
  silently broke bonds when an atom was pulled away, and a force field must
  not have the GUI fighting it over connectivity. Do not add it back — the
  user-facing route is Ctrl+P (bonds) or "Re-assign bond orders".
- **Pick arrays must not depend on painting** (round 6 bug): `_atom_map` /
  `_flat_coords` / `_flat_pick_radii` used to be filled only inside
  `paintGL`, so a click arriving between an edit and the next repaint hit
  nothing (this is how the edit-mode draw tool first appeared "dead").
  `_ensure_pick_data()` rebuilds them on demand, CPU-only; every pick path
  calls it, and `refresh_geometry()` sets `_pick_dirty`.
- **Edit-mode key policy (round 20, FINAL): elements are PICKED, never
  typed.** The element buffer is gone, so letters are ordinary hotkeys in
  both modes and `E` is a plain operator key for the draw tool. The buffer
  cost every letter hotkey in edit mode, could not spell Ge (G starts a
  grab), and whichever key toggled the tool collided with the tail of
  Ge/Fe/Be/He/Ne/Re/Se. Do NOT reintroduce typing — the periodic table
  (round 17) is the answer, and it also carries the meta atom.
- **A readout the user must see belongs in the VIEWPORT, not the status bar**
  (round 21). Even as a permanent widget the measurement was easy to miss at
  the bottom of a maximised window; drawn over the molecule with the picked
  atoms ringed, it cannot be. The status bar is for things you may ignore.
- **Fixed pixel column widths make parts of a dock unreachable** (round 21).
  The outliner's three columns summed to 290 px, so a narrower dock hid the
  Style column behind a horizontal scrollbar with no hint it was there. Give
  the name column `QHeaderView.Stretch` and keep the controls fixed.
- **Tab-vs-mode is a PANEL question, not a transform-panel question**
  (round 21). `on_tab_pressed` special-cased the transform panel, so the
  array modifier's spin boxes still fell through to "toggle edit mode". Test
  focus against every panel.
- **A temporary `showMessage()` hides ordinary status widgets** — this bit
  twice. The trajectory bar (round 2) and then the MEASUREMENT readout
  (round 20), which looked like a dead tool because every atom pick emits a
  status message that covered it. Anything that must stay visible in the
  status bar is an `addPermanentWidget`.
- **Emptying a molecule in EDIT mode must not delete the object** (round 20).
  You are inside it with the draw tool; removing the outliner entry leaves
  `edit_obj_id` dangling and nothing can be drawn. Deleting the object is an
  object-mode action.
- **Size atom labels from the atom's RADIUS, never by fitting the text to a
  width** (round 17). Fitting each string to ~0.8 of the diameter meant the
  font shrank as the label got longer: "C" 18 px and "C12" 6 px on identical
  atoms, which is what made index labels look broken. Size by radius, then
  squeeze ONLY if the text would overhang. Also not bold, and in a wide sans
  — a condensed face at this size turns "8" and "B" into the same smudge.
- Bond-order perception is greedy-by-length **plus an augmenting-path repair**
  — plain greedy is maximal but not maximum, so a six-ring could stall at two
  double bonds instead of three. The repair is what makes benzene Kekule.
- The instanced mat4 attribute occupies locations 2–5 (one vec4 per column,
  divisor 1); numpy math-convention matrices must be per-instance
  **transposed** before upload (`np.transpose(mats, (0,2,1))`).
- Trajectory frame switches re-perceive bonds but KEEP user-assigned orders
  (`keep_orders=True`); `Ctrl+P` re-perceives from scratch. **Perception runs
  only when the nearest INTEGER frame changes** (round 22) — never per
  interpolated tick, or it would dominate playback cost.
- **Interpolated coordinates are DISPLAY-ONLY** (round 22). They live in
  `MolObject.play_position` and are evaluated by `display_coords()`, never
  written back into `structure.frames` — scrubbing a trajectory must not be
  able to damage it, and editing must still see real frame data. Same split
  as the modifier stack: draw/export use `evaluated()`, edit uses
  `obj.structure`.
- **A plain lerp between frames is wrong for ROTATION** (round 22). Every
  atom takes the straight chord, so the molecule contracts toward its
  centroid halfway through a turn and springs back — bonds lose real length.
  `interpolate.rigid_lerp` is the fix and is cheap (0.25 ms at 3000 atoms).
- **A panel writing its own widgets from `sync()` must guard against the
  signals that causes** (round 30). `TimelinePanel.sync` sets every spin box
  from the clock; `valueChanged` does not care who moved it, so each refresh
  fired "the user changed the framerate" back at the app — which then
  overwrote the clock it was displaying AND persisted the value to QSettings.
  The `_loading` flag around the writes is not optional. Same shape as the
  outliner's `highlight()`/`setCurrentItem` bug in round 28.
- **Tests must not write to the real QSettings** (round 30). `MainWindow`
  persists genuine preferences, so a test that drives a spin box writes its
  throwaway value into the developer's live config — a test run left MoloM
  starting at 10 fps with smoothing off, which then looked like a code bug.
  `tests/conftest.py` redirects QSettings into a temp INI. Note that
  `setDefaultFormat` is NOT enough on Windows: the two-argument
  `QSettings(org, app)` constructor always uses NativeFormat (the registry),
  where `setPath` has no effect — the four-argument form has to be forced.
- **`fps` means IMAGES per second, not frames per second** (round 30). With
  `smoothing` images per source frame, a scene of `d` frames runs for
  `d * smoothing / fps` seconds, so raising the smoothing at a fixed
  framerate slows playback down. That is the correct reading of the spec
  (more pictures in the same second), not a bug — the two knobs sit next to
  each other on the bar precisely so the trade is visible.
- **Sample a normal mode on a multiple of FOUR frames** (round 30). The
  turning points of `sin(2*pi*k/n)` are at k = n/4 and 3n/4, so any other n
  never reaches ±amplitude: n = 6 peaks at 0.87 of what was asked for, and
  the highest and lowest points of the chemical coordinate — the whole reason
  to look at a mode — are cut off. `vibrations.period_frames` snaps it, and
  rounds half-way cases UP explicitly because Python's banker's `round()`
  would send 10 down to 8 while sending 14 up to 16.
- **A boundary copy must carry its whole MOLECULE** (round 33). Completing
  the cell boundary atom-by-atom strands the rest of the molecule on the
  other side of the face — urea's C and O are exactly ON the x face, so the
  cell showed a bare C=O with no NH2 groups. Both reference viewers complete
  the molecule (VESTA searches for bonded atoms beyond the boundary, Mercury
  packs whole molecules), so `boundary_images` takes the atom's whole
  fragment. The exception is a PERIODIC component, which is infinite and
  cannot be completed — carry only the atom there, or rock salt sprouts a
  slab of chlorines.
- **A two-atom cell cannot reveal periodicity by walking** (round 33).
  `unwrap_molecules`'s test — two routes to the same atom disagreeing by a
  lattice vector — needs a loop inside the cell, and NaCl has two atoms and
  no loop, so it came back "finite" and got treated as a molecule.
  `fragment_info` therefore also asks whether the component **bonds to its
  own lattice image**: Na is 2.48 A from the Cl of the cell next door, while
  urea's molecule is 2.7 A clear of its image and only H-bonded (beyond the
  covalent criterion). Use `fragment_info`, not `fragments`, whenever the
  molecular-vs-framework distinction matters.
- **Nothing camera-independent may be recomputed in a paint path**
  (round 33). `_paint_symmetry` re-parsed 48 operators, re-classified them
  (an eigen-decomposition each) and re-imaged the ghosts every repaint: 12 ms
  per frame before a line was drawn, which turned trackpad zooming into a
  slideshow. `_symmetry_plan` caches on (object, symop strings, kind filter,
  asymmetric unit) — 0.11 ms. Overlays are cheap to write and expensive to
  leave uncached; check any new one.
- **pymatgen is not automatically a better CIF reader** (round 33). On a
  real CCDC file that lists symmetry-redundant atoms (urea's N1 and N1C are
  the same site), pymatgen merges them into partially-occupied sites and
  returns occupancy 2 — 12 of 16 sites disordered. ASE and our own reader
  both give the correct 16 atoms. Its real value would be the P1 fallback
  (space-group SYMBOL, no symop loop), which is a separate gap; adopt it
  there, as a tier, not as a replacement.
- **A drawn unit cell must COMPLETE ITS BOUNDARY** (round 32). Expanding the
  asymmetric unit into [0,1) gives the cell's contents, not its picture: an
  atom at the origin belongs to all eight corners, one on a face to both
  faces. Every crystallography viewer draws it that way, and without it rock
  salt is a single sodium in a corner. `cif.boundary_images` does it PER
  ATOM — a fragment walk lumps NaCl's Na and Cl into one unit whose centroid
  is nowhere near a face, and Mercury is per-atom too (which is why its urea
  picture shows part-molecules at the corners). Keep `expand(boundary=False)`
  for anything that wants the CONTENT, e.g. an export that must have Z
  formula units.
- **A modifier that regenerates a structure must not be added on top of an
  already-regenerated one** (round 32). The symmetry modifier was appended to
  a molecule showing the full cell, so it re-applied the operations, the
  de-duplication threw them all away, and the visible result was identical —
  "Add doesn't do anything". Adding it reduces the base to the stored
  asymmetric unit, and the ❖ page's asym/cell/packing switch drives the
  MODIFIER whenever one is present rather than rebuilding the atoms it feeds
  on. Any future generative modifier needs the same handshake.
- **A ray-plane solver needs a GRAZING guard, not just a parallel one**
  (round 32). `abs(denom) < 1e-9` is only the exactly-parallel case; well
  before that the intersection is already thousands of units away, and the
  moment the ray crosses parallel it FLIPS SIGN. In a grab that reads as the
  selection reversing and rocketing off, which is impossible to diagnose from
  the symptom. `manipulate._GRAZE` refuses the hit and the modal holds still.
  Same for `ray_line_t` when you sight along the locked axis.
- **The orbit centre drifts, so an absolute zoom floor eventually strands
  you** (round 32). `pan` and anchored `orbit` both move `camera.center` by
  design; after a dozen pans it can be 20 A from anything. Clamping distance
  at a fixed 0.5 A then kills zoom while the molecule is still far away, and
  the only cure is F (which re-fits the centre). Zooming past the floor now
  carries the centre forward along the view direction — Blender's dolly — so
  progress is always possible. Do not reintroduce a bare clamp.
- **Depth cues must be calibrated on WHAT IS DRAWN, not on camera distance**
  (round 32). A 2.9 A cell viewed from a normal distance spans a sliver of a
  camera-distance-scaled range, so every line comes out at the same alpha and
  the cue is invisible. `set_depth_cue_extent` normalises against the cell's
  own near-to-far spread, which makes the nearest line full and the furthest
  faint at any zoom.
- **A QTreeWidget foreground brush loses to the selection highlight**
  (round 32). Qt paints selected text with `QPalette.HighlightedText`, so a
  row coloured with `setForeground` goes blank the moment it is clicked — the
  one row you are looking at is the one that stops telling you anything. Flag
  the row with a Qt.UserRole and override BOTH palette roles in a
  `QStyledItemDelegate` (`outliner._HiddenMarkDelegate`).
- **Every new per-object display field MUST be added to `Scene.snapshot`
  AND `restore`** (round 31). `atom_hidden` / `atom_scales` were added in
  round 26 and forgotten there, so any restore threw them away — and because
  a cancelled viewport gesture restores a snapshot, the symptom was "I hide
  atoms and they come straight back", with no undo pressed and nothing in the
  UI to blame. `to_dict`/`from_dict` build on `snapshot`, so savepoints lost
  them as well. When adding a field to `MolObject`, grep for `atom_colors` —
  it appears in all four places, and that is the checklist.
- **Hiding must actually stop the work, not just the drawing** (round 31).
  `refresh_geometry` already skipped invisible objects, so hiding looked like
  an optimisation, but `_apply_timeline` re-perceived bonds for EVERY object
  regardless — the expensive part of a tick — and a hidden animated molecule
  measured 105% of a visible one. Perception is deferred while hidden and
  flushed by `_flush_stale_bonds` when the object comes back (in
  `_sync_all`, the eye handler, and isolate). Anything else added to the
  per-tick loop should ask the same question.
- **A slider that re-bakes geometry must not snapshot per tick** (round 31).
  The amplitude slider pushed a full deep scene copy for undo AND rebuilt all
  3N mode cards on every `valueChanged`, which at ~60 Hz is the stutter that
  got reported. Coalesce onto a short single-shot timer, push ONE undo at the
  start of the gesture, and do not rebuild the panel that owns the widget you
  are dragging — it feeds the value back at you.
- **A greyed tab cannot explain why it is greyed** (round 30). The ∿ page
  locked itself until FREQ data existed, and the only way to load FREQ data
  was an F3 operator — so opening an ORCA output and looking for the modes
  found a dead grey square. Prefer "always clickable, page says what is
  missing and offers the action" for anything the user has to DISCOVER; save
  the greyed-tab pattern (❖) for properties of an object that plainly either
  has a unit cell or does not.
- `elements.atomic_number` is tolerant ("C1"/"cl2" → 6/17) — same convention
  as OWB `transform._sym`. "D" (deuterium) is NOT in the table.
- **Wheel events are device-dependent** (round 16, was laptop-only): a
  trackpad scroll orbits, a mouse wheel zooms; Ctrl zooms and Shift pans on
  both. MMB drag orbits (Shift pan, Ctrl zoom), Alt+LMB orbits, RMB pans.
  LMB drag deliberately does NOT rotate — it box-selects. Scroll signs are
  marked in `wheelEvent` for easy flipping if the feel is inverted on some
  hardware.
- Grid lines drawing across atoms below z=0 is CORRECT (depth-tested floor,
  same as Blender); don't "fix" it.
- Selection is now a list of `(obj_id, atom_index)` tuples everywhere; bond
  edit ops require both picks in the SAME object.

## Environment
- TWO dev machines (this is why round 16 happened): the **laptop** (Windows,
  Python 3.10, precision trackpad) and the **desktop PC** (Windows, Python
  3.13, wheel mouse — `C:\Users\chris\Documents\GitHub\ACH-MoloM`). Assume
  input code must work on both; `pytest` had to be pip-installed on the PC.
- Deps: numpy, PySide6, PyOpenGL (+ rdkit, openbabel-wheel installed and
  optional at runtime — graceful degradation mirrors OWB's tiering).
- NOT a cluster tool. No SLURM/ssh anywhere. The LiDO gateway has no
  PySide6/GPU — MoloM is for local machines; the gateway keeps molden.
- It IS a git repo now (single "Initial commit", 2026-08-01), so behavioural
  changes are diffable from here on.

## Verification workflow
1. `python -m pytest tests/ -q` — 595 offline tests. `tests/conftest.py`
   sandboxes QSettings, so a GUI test can drive a real control without
   writing into your own MoloM configuration.
2. `python -m molom --selftest` — headless core sanity.
3. GUI smoke: a scripted QTimer run that opens examples, switches styles,
   selects atoms, drives the trajectory bar, and grabs framebuffers lives in
   the session scratchpad pattern (`smoke_gui.py`) — recreate as needed; the
   `grabFramebuffer()` PNGs are how rendering was verified without manual
   clicking (ethanol B&S, selection halos, stick, VdW, wireframe, ethene
   double bond, trajectory frame 3).

## Meta atoms (SHIPPED round 19 — `core/meta.py`)
Goal: pre-optimise metal-organic complexes without force-field parameters for
the metal. Christian's spec (2026-08-02): "open a small window in which
coordination geometry and bond distance can be set... the meta atom will act
as a constraint during optimization and keep that shape. After optimization
the meta atom needs to be converted on export to a specific element."

Shipped: `MetaAtom` (geometry + distance + export element + locked) stored in
`Structure.metadata["meta_atoms"]` under STRING keys (savepoints are JSON);
`MetaAtomDialog` off the periodic table's ✳ button; `idealize()` places the
bonded donors on the template directions at r; `frozen_atoms()` feeds the
optimiser's existing `fixed` list; `resolved_symbols()` swaps the dummy for
the real element on export.

**How the constraint actually works, and its limit:** the centre and its whole
first coordination sphere are FROZEN (`fixed`), so distances and angles around
the metal are held by construction while the ligands relax. That is rigid, not
harmonic — a true restrained minimisation (donors pulled toward
`ideal_donor_positions` by a penalty term, everything else free) needs RDKit
position constraints (`MMFFAddPositionConstraint` / `UFFAddPositionConstraint`)
and is the obvious next refinement. Freezing was chosen because it uses the
`fixed` support that already existed and cannot blow up.
Still open: index remapping is implemented (`remap`/`prune`) but NOT yet
called from `edits.delete_atoms`, so deleting atoms around a meta centre can
leave the table pointing at the wrong index.

## Rendering / image export (Christian asked about POV-Ray, 2026-07-31)
Shipped: `Ctrl+Shift+E` saves the viewport framebuffer as PNG/JPG at its
current resolution (already 4x MSAA). Good enough for slides and notes.
Options for publication-quality output, in the order they are worth doing:
1. **Blender export** — Christian lives in Blender; writing a .py that
   builds the scene there (metaballs/instanced UV spheres + Cycles) gives
   the best images and reuses skills he already has. Recommended.
2. **Offscreen supersampling** — render the existing GL scene into an FBO at
   4-8x and downsample. Cheap to add, no new dependency, no new look.
3. **POV-Ray** — what Avogadro 1 used. Still works and produces nice CPU
   ray-traced output, but it is an aging ecosystem (last release 2021), a
   separate binary the user must install, and its own scene language to
   maintain. Only worth it if a specific journal-style look is wanted.
NOT recommended: bundling a Python ray tracer (slow, another dependency).

## Roadmap
Round-1 skeleton and round-2 Blender batch: DELIVERED (see "What this is").
Christian said "there will be heaps more" — expect further Blender-parity
batches. Known next items, rough order:
1. ~~PC/mouse control preset~~ DELIVERED round 16 (`core/input_map.py`).
   Still worth a feel-check on real hardware: scroll SIGNS on both devices,
   the zoom step per detent (0.88^n), and whether mouse users want
   zoom-to-cursor rather than zoom-to-centre.
1b. **Crystallography / CIF.** Reader + cell box round 18; correct placement,
   live-tracking box, whole-molecule wrapping and asym/cell/packing switching
   round 19. Still open, in order:
   - **pymatgen** — Christian OK'd it as a dependency (2026-08-02) and it is
     NOT yet used. Worth it for: CIFs that give only a space-group SYMBOL and
     no symop loop (our reader falls back to P1 and then silently shows just
     the asymmetric unit — the biggest correctness gap left), disorder groups
     and partial occupancies, and `.cif` EXPORT with a space group re-derived
     by spglib. Keep our zero-dependency reader as the bottom tier and put
     pymatgen above it, mirroring the rdkit/openbabel tiering.
   - **displayed bonds are still non-periodic** — `unwrap_molecules` uses the
     minimum image, but the `perceive_structure_bonds` that runs afterwards
     does not, so a FRAMEWORK (as opposed to a molecular crystal) still shows
     cut open at the cell faces. Round 32's boundary completion helps the
     picture (the atoms are there now) but the bonds across a face are still
     perceived non-periodically.
   - packing as an ARRAY MODIFIER rather than the current destructive rebuild.
   - ~~SYMMETRY AS A MODIFIER~~ DELIVERED round 29 (`SymmetryModifier`): the
     base stays the asymmetric unit while the viewport and exporter see the
     full cell. Packing is still a destructive rebuild (above).
   - **PARTIAL OCCUPANCIES (`_atom_site_occupancy` != 1)**: the parser reads
     the column but IGNORES it, so a disordered structure currently shows
     every alternative position at once, superimposed. Christian flagged that
     many viewers handle this badly and wants a large test set. Needed:
     read occupancy and disorder-group tags, decide a display policy
     (dominant component by default, with a way to see the others), and
     carry it into export. Worth collecting several real disordered CIFs as
     fixtures before writing any of it.
   - ~~SCHEMATIC SYMMETRY OPERATIONS~~ DELIVERED round 25
     (`core/symmetry.py` + the viewport overlay). Original scoping kept
     below for the reasoning:
   - **SCHEMATIC SYMMETRY OPERATIONS** (scoped 2026-08-02):
     while "Asymmetric unit only" is on, show how that unit is repeated to
     fill the cell. This is very tractable because `cif.SymOp` already holds
     each operation as a rotation + translation, and crystallography has a
     settled visual language for it — we do not have to invent one:
       * a 2/3/4/6-fold ROTATION axis is a line along the invariant direction
         (the rotation's eigenvector for eigenvalue +1) with the standard
         lens/triangle/square/hexagon glyph at its end;
       * a MIRROR is the invariant plane, drawn as a translucent quad;
       * an INVERSION centre is a small open circle at the fixed point;
       * a SCREW axis / GLIDE plane is the same glyph plus an arrow for the
         translation part (`op.translation` projected on the axis/plane).
     Classifying an op is standard linear algebra on its 3x3: `det` = +1
     rotation / -1 rotoinversion, `trace` gives the order, the +1 eigenvector
     gives the axis, and the translation component splits into the part along
     the axis (screw/glide) and the part that can be removed by choosing the
     origin. So the core work is a `classify(SymOp) -> (kind, order, point,
     direction, glide_vector)` function — pure numpy, very testable — and the
     drawing is then a handful of QPainter/GL glyphs. Also worth a "ghost"
     mode: draw the asymmetric unit's symmetry images as faint outlines so
     you SEE where each copy lands, which may communicate more than the
     glyphs. Toggle-able, off by default. Estimate: the classifier is small;
     the glyph set is the bulk of the work.
   - the per-object row pattern (`outliner.CrystalControls`) is meant to be
     reused for PROTEINS: unique checkboxes on the object's own row plus a
     dedicated properties page, keeping awareness of which entry is being
     edited. Christian's call, 2026-08-02.
   - `fit_view` frames the ATOMS, so a cell box larger than its contents
     overflows the view.
   (Note AG Henke is a framework-materials group, so this is closer to the
   day job than anything else on this roadmap.)
1c. **Unified timeline + interpolation + keyframes** (Christian asked
   2026-08-02; nothing built yet — this is the scoping.)
   Today: `Structure.frames` is a list of Nx3 arrays, `set_frame(i)` snaps to
   one, and the trajectory bar drives the ACTIVE object only. So playback is
   integer-indexed, single-track, and a second trajectory cannot play.
   - **Linear interpolation is the easy part and is nearly free.** A frame is
     already a full coordinate array, so `lerp(frames[i], frames[i+1], t)` is
     one numpy op over N atoms — cheaper per tick than the buffer upload that
     follows it, which happens either way. Cost is O(atoms), not O(frames).
     Needs a float `time` on the object rather than an int index, and
     `coords` becoming an evaluated result. Watch two things: bond perception
     currently re-runs on frame change (must NOT run per interpolated tick —
     perceive on the nearest keyframe only), and interpolating a molecule
     that ROTATES gives atoms travelling through the chord, not the arc. The
     honest fix for that is per-fragment rigid (Kabsch) + residual lerp,
     which `cif.rigid_from_reference` already provides.
   - **Multiple simultaneous trajectories** need a scene-level clock instead
     of a per-object index: one `Scene.time`, each object mapping it through
     its own offset/scale/length. That is the real refactor; interpolation
     without it just animates one molecule more smoothly.
   - **The unified track pane** (draggable-taller, one playhead, one row per
     object, rows arrangeable) follows naturally once the clock is
     scene-level. Sensible order: scene clock -> interpolation -> multi-row
     pane. DELIVERED rounds 22/23; round 30 then split frames from images and
     added the loop limits (see the round-30 entry).
   - **Keyframes are a bigger step than they look — but not enormous**, and
     the ground is already prepared: a keyframe is "at time t, this property
     has this value", and `MolObject` already keeps `origin`/`orientation`
     transforms separate from atom coordinates. So keyframing the TRANSFORM
     (position/rotation per object) is a contained feature: a sorted list of
     (time, value) per channel, an interpolate-at-time, and the existing
     transform paths reading the evaluated value. Estimate: comparable to the
     modifier stack (round 14). Keyframing ATOM POSITIONS is a different
     animal — it is a trajectory by another name, and should reuse the frame
     machinery rather than a second system. Recommendation: do transform
     keyframes only, and treat trajectories as the coordinate channel.
1g. **RANK MODES BY A VIEWPORT SELECTION** (Christian's long-term idea,
   2026-08-03, NOT built): "allow the user to make a selection in the
   viewport of certain atoms whose vibrations they are interested in and
   calculate their offset during different modes, use that as a ranking
   parameter". A button — "Filter modes by selection" — next to the existing
   Sort by / Range controls on the ∿ page.
   **Yes, this is very tractable**, and cheaper than it sounds: a mode is
   already a displacement vector per atom, so the ranking number is
   `norm(mode.displacements[selected]).sum()` (or its RMS), which is one
   numpy slice per mode — 3N of those is microseconds. It wants normalising
   by the mode's total displacement, otherwise every high-amplitude mode
   ranks above a mode that is genuinely LOCALISED on the selection; the
   useful quantity is the FRACTION of the mode's motion carried by the
   selected atoms, which is exactly a participation ratio. So:
   `core/vibrations.py::selection_weight(mode, indices) -> 0..1`, then a
   third entry in the existing `SORT_KEYS` and a filter threshold. The sort
   and filter plumbing from round 31 already exists — this is one core
   function plus one combo entry. Worth doing when the ∿ page is next open.
   Mass-weighting is the one judgement call: a C-H stretch is nearly all
   hydrogen motion, so an unweighted ratio over-rewards hydrogens.

1f. ~~ALIGN NEEDS PREVIEW-THEN-CONFIRM~~ DELIVERED round 31: the axis key
   previews (rewinding the captured pose first, so X then Y is the Y
   alignment and not Y-on-top-of-X), left-click confirms as one undo step,
   right-click/Esc reverts. The single-atom case still applies immediately,
   as specified. Original report kept below.

   **(was open, reported twice).** Christian,
   2026-08-03: *"Align still cancels after a single axis input such as x,y,z
   for two (bond) and 2+ (plane). A on a single atom is ok the way it is
   because it is not dependent on axes."*
   What happens now: `arm_align_keys` waits, the first X/Y/Z key calls
   `on_align_key` and the operation ENDS immediately. What is wanted: the
   axis key APPLIES the alignment as a live preview and the operation stays
   active until **left-click confirms**; **right-click / Esc cancels** and
   reverts. That means you can press X, look, press Y instead, and only then
   commit — the same contract G and R already have.
   Explicitly OUT OF SCOPE: the **single-atom** case (A with one atom moves
   the molecule so that atom sits at the world origin). It takes no axis
   input, so it has nothing to preview — leave it applying immediately.
   Round 29 fixed only the adjacent bug (a stray non-axis key used to CANCEL
   the wait); the confirm step was deliberately not attempted before the
   0.2.0 cut because it needs a real preview state: snapshot the geometry on
   arm, re-apply from the snapshot on each axis press, restore on cancel.
   Look at how `_grab`/`_rotate` hold `snap` for the pattern to copy.
   Implementation note (round 31): the preview capture is per-OBJECT
   (`_align_capture`: frames + origin + orientation), not a whole-scene
   snapshot — `scene.restore` rebuilds every MolObject, and the outliner's
   row widgets hold direct object references that would then be dangling.

1e. **LIGAND TEMPLATE ATTACHMENT — SHIPPED BUT NOT WORKING PROPERLY.**
   Christian tried it 2026-08-03: "templating still not working. will need
   more work sometime else." The pieces exist (`core/templates.py`, the two
   F3 operators, violet donor markers, 16 passing geometry tests) and the
   synthetic case docks correctly, so the failure is in real use, NOT in the
   maths — likely the workflow around it: which molecule is "the ligand"
   when several are marked, what happens with a meta atom's dressing
   hydrogens specifically, and whether the resulting fragment is where the
   user expects to keep editing. START BY WATCHING THE ACTUAL FAILURE rather
   than re-deriving the geometry. Original design sketch (2026-08-02; he noted
   he is "not too sure how to implement it yet", so this is a design sketch,
   not a spec). Wanted: mark the coordinating atom(s) on a ligand, mark the
   replaceable hydrogens on a metal or meta atom, then F3 "Attach template
   molecule as ligand" and have it placed correctly. Advanced enough that F3
   alone is the right home for now — no tab.
   The pieces already exist, which is the encouraging part:
   - `meta.dress_with_hydrogens` already puts placeholder H's exactly on the
     template directions, so "the replaceable hydrogens" ARE the attachment
     points and their positions are already ideal;
   - `cif.rigid_from_reference` (Kabsch) is exactly the fit needed: build the
     donor atom(s) of the ligand as the source point set and the placeholder
     position(s) as the target, and it hands back the rotation+translation
     that docks the ligand;
   - `coordination.ideal_donor_positions` gives the targets when there are no
     placeholders to consume.
   So the core function is roughly `attach(host, host_hydrogens, ligand,
   ligand_donors) -> transform`, plus deleting the consumed H's and bonding
   donor-to-centre. One donor needs a torsion choice (the ligand can spin
   about the new bond) — default to minimising clashes, and let R adjust it
   afterwards since the ligand is a fragment by then. Two or more donors are
   fully determined by Kabsch. Store the marked atoms as a named "template"
   on the source molecule so it can be reused.

1d. **Animation EXPORT** (Christian asked 2026-08-02: "it sucks to have nice
   animations in a viewport but not being able to render them"). Nothing built
   yet. The viewport can already render one frame offscreen at a resolution
   multiplier (`MolViewport.render_image`, used by Ctrl+Shift+E), and the
   scene clock can now be stepped deterministically — so the export loop is
   "seek, render, write" and is genuinely small.
   Do NOT take a hard ffmpeg dependency:
   - **PNG frame sequence** first. Zero dependencies, works everywhere, and
     it is what you actually want feeding Blender/After Effects or a journal.
     This alone unblocks the feature.
   - **`imageio-ffmpeg`** as the OPTIONAL tier for direct mp4/gif. It pip-
     installs a static ffmpeg binary, so there is no system-level install and
     no PATH hunting — it fits the existing rdkit/openbabel graceful-
     degradation pattern exactly. A system ffmpeg should be used if present.
   - NOT OpenCV (heavy, and a video writer is all we need) and NOT Qt
     multimedia (its encoders vary by platform build).
   Watch: `render_image` currently excludes viewport furniture, which is
   right for figures; an animation may want the cell box and labels, so the
   exclusions need to be optional.
2. Editing polish: ~~element palette / periodic-table dialog~~ DELIVERED
   round 17; undo/redo (OWB snapshot-undo patterns), H-fill, force-field
   cleanup (RDKit MMFF / OB UFF on selection), R rotate modal to pair with G
   (bond-axis rotation of a selection is the chemically meaningful one).
3. Viewport: atom labels, measurement overlays drawn in-viewport, depth-cue
   fog, screenshot export, grid distance-fade, numbered-frame outliner rows
   for trajectories.
4. Outliner: duplicate object, per-object fit/zoom, drag-reorder, multi-mol
   arrangement helpers (align/snap — OWB transform.py has the math to port).
5. OWB integration: point OWB's `viewer_3d_path`/`editor_3d_path` at
   `molom`; `--select i,j,k` CLI for geomspec atom-index reading; xyz
   round-trip with coords_locked on reload.
6. Perf, if ever needed: impostor (billboard) spheres, partial buffer
   updates during grab instead of full rebuilds.
