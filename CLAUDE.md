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

## VERSION 0.3.0 (2026-08-10) — the line under this session
(Rounds 34-58 sit above 0.2.0; everything from the PC/mouse preset through
camera objects and the camera view is in this release.) Headline items since
0.2.0: CIF import that keeps the crystallography honest (space groups from a
symbol, the labelled periodic bond graph, disorder and occupancy policies, a
real CIF writer), coordination polyhedra, the Blender export as a .blend with
polyhedra and saved cameras, installable add-ons, the animation export, and
camera objects with a viewport frame you compose in. 1265 tests.

Round 59 (2026-08-10, THE PYPI RELEASE — and Shift+drag reaching the code that
already existed): Christian asked for the release to be prepared, "just one
thing I would like to add though: Shift+drag to adjust the view when in camera
mode" — which round 58 reports as shipped. **It was built and it was
unreachable.** `truck_camera` exists, is correct and has four tests, and every
one of those tests CALLS IT DIRECTLY; the routing hung it off `_nav_drag ==
"pan"`, and `_nav_drag_kind` only returns that for Shift+**MIDDLE**-drag. So the
plain gesture — Shift + left-drag — still started an additive box select, on the
machine whose stiff scroll-wheel click is the reason round 16 had to alias orbit
onto Alt+LMB in the first place. **A mechanism with tests and no gesture test is
a feature nobody can reach**, and that is the lesson worth keeping: the tests
proved the arithmetic and said nothing about whether any hand could get to it.
Fixed by resolving a Shift+left-drag inside a camera view to `_nav_drag =
"pan"`, which reuses the existing truck branch AND the existing release
handling (one undo step, no pick on release). Scoped to a camera view, so
additive box select is untouched everywhere else; an explicitly armed box/lasso
tool still wins, on round 52's rule.
**Three real bugs fell out of packaging**, all of which would have shipped.
(1) **`molom.addons` was not in `[tool.setuptools] packages`** — a hand-written
list, so round 46's add-ons were simply absent from the wheel, and since
add-ons are imported BY NAME at run time that ships as a broken feature rather
than an ImportError. (2) **`pyproject` said 0.2.0 while `molom.__version__`
said 0.3.0**; both are now pinned against each other by a test, because a
release is exactly the moment two sources of one number disagree. (3) **An
orphan dock shell floated over the menu bar.** Round 15 moved `OptimizeDock`'s
WIDGET into the properties dock as a page and left the dock behind, parented to
the window but never added to a dock area — and `QWidget.show()` shows every
child not explicitly hidden, so an empty titled husk sat at (0, 0) on top of
"File" and "Edit". Invisible for 44 rounds because nobody photographs a fresh
window; the first screenshot made it unmissable.
**`tools/screenshots.py` generates the PyPI images**, and the interesting part
is that a screenshot tool has its own silent failure mode. **`win.grab()` drops
every QPainter overlay the GL widget draws** — measured, not assumed: the same
frame grabbed both ways gives the film back, eight handles, the veil and the
hint line through `grabFramebuffer()` and NONE of them through `win.grab()`.
Since the overlays are most of what MoloM draws (camera frame, cell box,
compass, labels, symmetry elements, measurements), a window grab photographs
the program with its features apparently switched off, and the picture looks
perfectly fine. So `compose()` takes both and pastes the framebuffer over the
viewport — then pastes the viewport's CHILD widgets back **out of the original
window grab**, because they are real widgets over the GL surface (the floating
tool column, the crystal ribbon) and a flat framebuffer paste erased them,
while re-grabbing each one throws away the translucency they are styled with
and came back white. **The DPR trap on top of that**: both grabs carry a
devicePixelRatio (1.5 here) and a QPainter on such an image works in LOGICAL
coordinates, so device-pixel offsets get multiplied a second time and everything
lands 1.5x too low — visible as a ghost ribbon 27 px above the real one.
`setDevicePixelRatio(1.0)` makes one pixel of arithmetic mean one pixel of
image. Two more rules the tool holds: **a fresh window per shot** (imports ADD
in MoloM and never replace, so the first draft's camera shot contained cubane, a
ferrocene packing and a solid solution at once, 247 atoms of unrelated
structures), and **drive the CONTROLS, not the metadata** — setting
`metadata["polyhedra"]` draws the solids and leaves the tick box unticked, i.e.
round 51's bug staged for the camera.
**README rewritten as the PyPI page** (it still described the round-1
"skeleton": import, render, "editing stubs"). Images are absolute
`raw.githubusercontent.com` URLs because PyPI does not render relative paths —
so they only appear once `docs/screenshots/` is pushed to `main`. `twine check
--strict` passes both artefacts; the built wheel was installed and its
`--selftest` run. 1281 tests. **NOT UPLOADED — that is Christian's to run.**

Round 60 (2026-08-11, Christian's post-release batch — three gestures, two
exports, one bug that hid in plain sight):
**(1) Ctrl+drag and Shift+drag inside a camera did the SAME THING**, and the
reason is a single line: round 58 sent EVERY scroll to `zoom_camera_frame` on
the argument that a camera being looked through must not move, so both
modifiers fell through to the frame zoom. The argument holds for the plain
gesture and not for a held modifier — which is round 59's own reasoning for
putting re-framing on Shift+drag. So **Ctrl+scroll now DOLLIES** (`dolly_camera`
walks `cam.distance`, and round 58's `scale = Z / distance` is what makes that
visibly different from a lens change: the frame keeps its size while everything
inside it grows) and **Shift+scroll TRUCKS**. Keyed on the MODIFIERS, not on
`input_map`'s resolved action, deliberately: a mouse resolves a plain wheel to
ZOOM and a trackpad resolves it to ORBIT, so keying off the action would make
the unmodified gesture mean two different things on the two dev machines, which
is the round-16 mistake. **A scroll has no release**, so the one-undo-step-per-
gesture flag needed a timeout — `_begin_camera_gesture` reuses `_GESTURE_GAP_S`
(0.6 s), the same constant `_orbit_input` uses, or the first Ctrl+scroll of a
session would have swallowed every later one into its undo step.
**(2) `render_image`'s `furniture=False` was excluding SCENE CONTENT**, not
furniture. Christian reported the visible half — "screenshots of cifs are
missing the unit cell boundaries, not legible without them" — but the same gate
was also dropping coordination polyhedra, occupancy pie spheres, symmetry
elements and, worst, the WIREFRAME buffer, so exporting a wireframe-styled
molecule produced an empty picture. Every one of those is already behind its own
user-facing toggle, so they are now unconditional and `furniture` means only the
atom LABELS (round 13's argument against labels in a published still stands; it
never applied to the cell box). The genuine furniture — compass, grid, origin
dot, selection halos — was never in `render_image` at all, which is why the
conflation survived.
**(3) "Crop to content"** (`core/crop.py` + a Settings tick): the viewport is
whatever shape the window happens to be and the molecule sits wherever the
camera left it, so an export routinely carries a third of its pixels as dead
background. The geometry is in `core/` and takes a numpy mask, so every rule is
testable with no GL: an ALPHA mask for a transparent export and a COLOUR mask
against the background for an opaque one, a margin, a floor, and an `aspect`
that only ever GROWS the box (shrinking to a ratio would crop away the content
just asked for). Applied AFTER the camera crop, because a film back is a
deliberate framing and must win. Measured: 1260x1292 -> 882x746 on ferrocene.
**The QImage->numpy bridge is the part that bites**: `bytesPerLine` can exceed
`4 * width`, and assuming a tight buffer shears the image, so the stride is read
and the pixels sliced back out.
**(4) A SUPERCELL DREW NO BONDS**, and it is a pure omission with a
long-lived cover story. `build_view`'s packing branch replicated `symbols` and
`coords` per lattice offset and never touched the bonds, so
`report["packed_bonds"]` still described ONE cell while the atom list had grown
by `na*nb*nc` — every cell past the first came out as loose spheres. Nothing
failed and nothing warned; it just looked like a cloud. Fixed by replicating the
bonds with the index stride, and — the part that needed thought — remapping them
through the coincident-atom merge. `_first_of_coincident` returned only a keep
mask, so it could say an atom was dropped but not WHICH atom it was the same as;
`_coincident_map` now also returns `canonical`, because a dropped atom is not
lost, it is the same physical atom as the one it landed on, and the bonds that
reference it are exactly the ones crossing an internal face of the block, i.e.
the ones holding the supercell together. Verified as an invariant rather than a
number: bonds/atoms is 1.4286 for 1x1x1, 2x1x1, 2x2x1 and 2x2x2 alike.
**(5) MEASUREMENTS PERSIST** — "persistent in the viewport, but deletable by
selecting + Delete or hovering over them + Delete". Several live at once,
committed on the click that would have started a new one (previously that click
silently discarded the finished measurement), drawn SOLID where a live one is
dashed, and the hovered or selected one drawn white, which is what makes
"hover + Delete" discoverable rather than secret. Two decisions worth keeping:
they live on the VIEWPORT and not in the scene, so they stay out of
`Scene.snapshot`'s four-place checklist (round 31) and out of savefiles — a
measurement is an annotation on the current view; and `selected_measurement` is
a separate field from `selection` for round 56's reason, because a measurement
owns no atoms and every loop over `(obj_id, atom)` would otherwise have to learn
to skip it. **The Delete key needed the operator's PREDICATE widened**:
`run_op` refuses a disabled operator, so `enabled=sel` meant the key never
reached the measurement when no atoms were selected — `has_measurement_target()`
is public for exactly that. Stale-pruning was extracted out of `_paint_measure`
into `prune_measurements()`: pruning inside a paint path is a hidden mutation
that only fires once a frame is drawn, and it is untestable offscreen.
**`render_image` cannot be tested by pytest at all** — it builds an FBO, and
`QOpenGLFramebufferObject` with no live context is an ACCESS VIOLATION that
takes the whole run down, not an exception. That is the round-48 lesson from the
other side, and the two export fixes are verified in `tools/smoke_gui.py`
instead, which now measures the crop and counts ink with and without the cell
box. 1310 tests.

Round 102 (2026-09-03, three off the docket - N1, N2, N3, and one of them
was already fixed):
**(1) N1: A SEARCHED CRYSTAL CLAIMED THE SESSION'S DOCUMENT, and Ctrl+S would
have written into a deleted directory.** Christian saw the symptom as the
round-trip banner appearing on an imported crystal. The cause is two correct
decisions meeting: `open_path` claims `source_path` for the FIRST structure
file of a session (round 92, so a round trip cannot be re-pointed at whatever
was opened last), and the crystal search writes its download into a temp
DIRECTORY it deletes immediately afterwards (round 84, so the object is named
after a real filename rather than `molom_d2dtna96`). Measured: after a search
import, `source_path` names a path where `os.path.exists` is False, and
`on_save` prefers `on_save_geometry_back()` over the project dialog whenever
it is set.
**`open_path(path, temporary=True)` is the fix, and it suppresses TWO things**
- the document claim and the recent-files entry - because they are the same
promise about a path that is about to stop existing. A recent-files entry into
a deleted temp directory is the same bug one menu along, and it was there too.
`_install_structure` keeps taking `path` when `remember` is False, because the
file is still where the FREQUENCIES are read from: "is this worth remembering"
and "what file did this come from" are different questions.
**(2) N2: THE STEPPED ROTATION DROPPED A CRYSTAL OUT OF ORTHOGRAPHIC.** The
VESTA ribbon's "rotate by the step angle" goes through `Camera.rotate`, which
pops `auto_ortho` back to perspective - Blender's rule, and round 3's, and
right for a DRAG, where the pose stops being an axis view the moment the mouse
moves. A rotation by a TYPED number of degrees is a different gesture: it is
how the ribbon walks around a cell, and the axis views it walks between are
deliberately orthographic. `keep_projection=True` holds it; the free drag is
untouched and a test pins both halves. The parameter is on the CAMERA rather
than the handler so there is still ONE orbit implementation - the no-roll
construction is not something a second path should have to re-earn.
**(3) N3: THE WIDTH HALF WAS ALREADY FIXED, which measuring found before
anything was changed.** The docket said round 93's resize-on-sort fix had not
reached the molecule search. It had: both tables put their stretch column in
`QHeaderView.Stretch`, both word-wrap, and both sum their column widths to the
VIEWPORT rather than to the longest entry - it arrived through `ResultTable`,
which round 90 extracted. The note was stale. A test now pins the two tables
against each other, which is Christian's standing rule (a control in both
search windows behaves the same in both) made mechanical rather than
remembered.
**THE CAS NUMBER IS THE REAL WORK.** `Candidate.cas`, from PubChem's
synonyms - and it is **validated by its CHECK DIGIT**, not by its shape,
because a synonym list is full of hyphenated numbers that look like registry
numbers. Measured: benzoic acid has 264 synonyms of which 2 are CAS-shaped
and 2 valid, aspirin 698 of which 3 and 3. One BULK request for the whole CID
list, the same shape as `_properties_for` and for the same reason (round 90:
PubChem refuses the sixth request in a second, silently), and run
CONCURRENTLY with it so the two round trips wait together: **+1.0 s serial,
+0.27-0.59 s overlapped** on a ~5 s search. It rides `to_dict`, or a starred
row would lose the column on reopening. And it is exactly the discriminator
this dialog exists for - o-, m- and p-xylene share a formula and a weight and
come back as 95-47-6, 108-38-3 and 106-42-3.
15 tests. 2101 tests.

Round 102b (2026-09-03, Christian's test pass on round 102 - a span that
outlived its row, and the round trip re-cut to HIS design):
**(0) THE DESIGN WAS MINE AND IT WAS WRONG.** Round 92 recorded "opening a
structure file arms the write-back" as though it were his instruction; it was
an INFERENCE of mine from "OWB launches `[program, file.xyz]` and nothing
else". His actual design: "round trips that automatically overwrite geometry
should only activate if molom is used as an external editor launched from
OWB. On its own saving in molom should only save the .molom save file state.
If an edited structure is intended to be saved, then that is a geometry
export, which should be a different pathway. Even if I launch `molom
some.xyz` that should just import that xyz."
**THE LAUNCHER ASKS THROUGH THE ENVIRONMENT, and that is the whole trick.**
`MOLOM_ROUNDTRIP_FILE=<abs path>`, plus `--roundtrip` for driving it by hand.
His own question was whether a flag could crash another editor, and the worry
is justified - whether Avogadro or molden ignores an unknown argument, exits
non-zero, or opens a file called `--roundtrip` is not consistent and is not
something OWB can know, because the slot holds whatever the user put there.
**A program that does not read an environment variable cannot be affected by
one**, so OWB can set it on EVERY editor launch and only MoloM notices -
including after the slot is repointed. It carries the PATH rather than a bare
"1", so a variable left in a shell cannot arm a write-back for something
opened later. The OWB half is one line and is written into that repo's TODO.
**(1) A SPAN OUTLIVES THE ROW IT WAS SET ON**, which is the blank second row
he reported twice. `_add_divider` spans the FAVOURITES rule across every
column, and `setSpan` belongs to the TABLE at that row index rather than to
the item - so when the next provider batch lands and the divider moves down,
the old span stays behind and hides columns 1..n of whatever candidate now
sits there. It draws blank except for its star while the candidate is
perfectly intact behind it, **which is why his preview pane showed the
compound the row would not** - that screenshot is what solved it, because it
proved the data was fine and only the drawing was wrong. It needs favourites
AND incremental batches, which is why the first repro missed it. `clearSpans()`.
Two more found on the way: `_merge` was not carrying `cas` at all, so a CAS
arriving in a later batch could not fill an existing row; and `_finished`
DISCARDED the finished enriched list whenever rows had arrived incrementally,
so any row the incremental path left half-filled stayed that way until the
dialog was reopened.
**(2) MOVING A CRYSTAL IN THE ASYMMETRIC VIEW REWROTE ITS ASYMMETRIC UNIT.**
His report was that the cell box did not follow "only in asymmetric mode
though not in full cell view", and that shape is the diagnosis:
`sync_asymmetric_unit` runs ONLY when the base is the asymmetric unit, and it
wrote back unconditionally. Measured on his `test_DMSO.molom`: a 5 A
translation rewrote `asym_frac[0]` from (0,0,0) to (1.2321,0,0) and re-pinned
the cell reference against the moved atoms, so the recovered pose read as
identity and the box stayed at the origin. **The box was the visible half of
a data change.** Round 91's rule - a rigid motion is not an edit - one
function along: the asym branch returned before `_edit_was_rigid` was ever
consulted.
**(3) THE NAME COLUMN'S BORDER WAS DEAD BECAUSE QT WILL NOT DRAG A STRETCH
SECTION.** Not fixed-width by intent; collateral from round 95's fix for the
width jumping. It is INTERACTIVE now and takes whatever the other columns
leave (`_reflow`), so it still grows with the window - until the user drags
it, after which their width stands. "The user did it" is decided by watching
the header for a mouse button rather than by `sectionResized`, which fires
for our own writes too and made a programmatic bulk resize pin the column.
**(4) THE WIDTH HALF OF N3 WAS ALREADY FIXED**, which measuring found before
anything was changed - both tables were already Stretch + word-wrap + summing
to the viewport. The docket note was stale. A test pins the two against each
other now.
**(5) AN ELEMENT CHANGE ON A SHARED SITE MAKES IT PURE.** Christian: "change
should make something purely that element, not just change the dominant one."
Round 87 re-laballed the majority species and kept the rest; picking iodine
off the periodic table says "this position is iodine", not "call the 50%
niobium iodine and leave the titanium, nickel and cobalt where they are",
which is a composition nobody asked for and cannot be read off the picture.
The site collapses to one row at occupancy 1.0 **and the pie sphere goes with
it** - `site_occupancy` is what the wedges are drawn from and leaving it
behind was his "the pie chart is still the underlying partial occupancies".
Stating a MIXTURE is a different gesture and already had its own dialog since
round 52.
**(6) THE CCDC KEY HOLE, WITH NO KEY IN IT** - his framing.
`cifsearch.register_provider` is the extension point, on round 73's MOPAC
shape: core owns a registry and a signature, every line that knows the vendor
lives in an add-on. A registered tier joins the concurrent fan-out and fails
the same way (a tier, never the search). **A test asserts that nothing under
`molom/core/` imports `ccdc`.** The add-on itself is deliberately unwritten -
it cannot be run or tested on a machine with Mercury Community and no CSD.
**AND THE SAVEFILE QUESTION HAS AN ANSWER: mostly no.** CCDC's licence "does
not allow external sharing of original data from the CSD", and derived data
needs their written approval - so a `.molom` full of CSD entries must not
leave the group. What is genuinely ambiguous is what counts as "bulk" and
whether a savefile is original or derived; `docs/CCDC.md` 4b says so and
names the support-ticket route rather than guessing.
17 tests. 2118 tests.

Round 101 (2026-09-02, a refusal nobody can see - and the plot becomes a
figure):
Christian, testing round 100: "I have also loaded in multiple files and the
checkboxes for them show up, but none are actually displayed." Plus a
question: "is it by design that there is no svg export for the plots?"
**(1) THE REFUSAL WAS CORRECT AND EFFECTIVELY SILENT, WHICH IS THE SAME AS A
BUG.** Reproduced on the Q axis, where dropping a measured trace is right - a
measurement is in 2 theta and carries no wavelength, so converting it would
mean inventing one (round 100's own rule). What was wrong is that the
explanation was `notes.append`ed LAST, and the note line shows `notes[:2]` -
so with one crystal open its standing "no displacement parameters, B = 0"
caveat took a slot and the one sentence saying where two files had gone was
truncated away. Measured: the note read "cod_1547149...: B = 0..." and
mentioned the measurement nowhere at all.
**Two fixes, and the second is the one that matters.** `alerts` are now a
separate list from `notes` and are shown FIRST - an explanation for something
the user just asked for and cannot see must outrank a caveat that is true of
every pattern in the window. And the TICK BOX says it itself: a suppressed
measurement greys to #7a7a7a and its tooltip says why, because the note line
is four seconds of attention and the box is what somebody is looking at when
they wonder where their file went. The tooltip keeps everything, which is
what caught a bug I introduced doing this - `load_measured` was overwriting
the tooltip with its own summary, so the caveats stopped being said anywhere.
**(2) SVG WAS NOT BY DESIGN, JUST NOT BUILT** - `save_image` was
`plot.grab().save(path)`, and a QPixmap has no vector format. A
diffractogram is a polyline against an axis, i.e. vector content all the way
down, so a raster figure is one nobody can rescale or restyle.
**THE OBSTACLE IS THE BLITTING CACHE** (round 96): rendering the widget into
a `QSvgGenerator` would embed that QPixmap and produce an SVG with a bitmap
in it, which is worthless and looks fine until somebody zooms. So `_render`
was split - `PxrdPlot.paint_into(painter, columns=)` does the drawing and
`_render` only allocates the pixmap - and the export paints through the same
method the screen does, which is round 37's rule (an export that quietly
disagrees with the screen is worse than none). Verified by reading the file:
0 `<image>` elements, 0 base64, 24 paths, 8317 vertices, 135 kB.
**TWO THINGS ARE DELIBERATELY NOT THE SCREEN'S.** The curve is sampled at
`SVG_SCALE` (4x) as many columns, because the min/max envelope is a per-PIXEL
reduction and an SVG has no pixels - at screen resolution it reads as
polygonal the moment the figure is enlarged. And the PALETTE is the light
one, because the plot's is a dark-theme palette and does not survive a page.
**THE MEASUREMENT CHANGED THAT RULE.** The first cut darkened only colours
above a luminance threshold, on the assumption that the chosen blues and
oranges print fine and only the near-white measured palette does not. They
do not: the trace palette runs **0.567 to 0.796** and the measured palette
**0.776 to 0.910**, so the two OVERLAP and no threshold separates them - and
every screen colour has a contrast ratio between **1.24:1 and 1.70:1**
against white, where WCAG asks 3:1 for line art. So every trace is scaled
down to `PAPER_LUMA` (0.30, i.e. exactly 3:1), by one factor across all three
channels, which preserves the HUE - the thing that says which trace is which.
A colour already dark enough is left exactly alone, which is what protects
one somebody picked by hand. The swap is a context manager over the module
globals restoring in a `finally`, since those colours are read by name in a
dozen places and threading a palette through each would be a far larger
change than the behaviour asked for.
**AND `.dat` FROM HIS OWN MACHINE CONFIRMED ROUND 100'S GUARD.** His
`CN-64-Cl-0.05-dry.dat` is a real Riet7 file - header, then bare intensities
- and reads as 2251 points from 5 to 50 deg through the vendored reader.
**(3) "THE EXPORT IS BLOCKY WHEN ZOOMED OUT", AND THE CEILING WAS NEVER THE
STORED GRID.** He asked whether doubling the point density on the peaks would
cost performance, and whether it could be doubled again for an export. The
answer to the first is NO, measured; and the second turned out to be the
whole of the bug.
**The stored step now follows the PEAK** (`pxrd.step_for`,
`STORED_PER_FWHM = 20`). A fixed 0.01 deg is 10 points across a 0.1 deg peak
and 2 across a 0.02 deg one, so it is simultaneously too coarse for a sharp
pattern and wasteful for a broad one; points per FWHM is the invariant that
means something. `DEFAULT_STEP = 0` means "derive it", and an explicit step
in a savefile still wins.
**IT IS FREE BECAUSE THE ENVELOPE BOUNDS WHAT IS STROKED** (round 96): the
min/max reduction emits about one point per column whatever is stored, so
quadrupling the stored density moves the DRAWN point count from 9508 to
9624 - 1.2% - and the whole cost is building the profile, 6.2 -> 9.1 ms for
eight patterns. **The wall clock could not have shown this**: the same
configuration measured 42, 70 and 62 ms on three interleaved runs, so the
timing on this machine drifts by 50% and the drawn-point count is the
instrument that settles it. Round 89's rule again - measure the quantity,
not the picture.
**AND THE EXPORT'S RESOLUTION COMES FROM THE PEAK TOO** (`export_columns`,
`SVG_PER_FWHM = 32`). This is what "blocky" was: the widget's own width is
the wrong ruler for a vector file, and a 939 px plot over 45 degrees gives
**2.1 columns across a 0.1 degree peak - 8.3 even at the 4x scale**, so the
peak is an octagon the moment the figure is enlarged. The count is now taken
from the narrowest trace's FWHM, with the width-based figure as a FLOOR and
a hard cap so a very sharp peak over a very wide range cannot ask for a
ten-megabyte file. Measured: 8.3 -> 32.0 columns per FWHM, 101 -> 265 kB,
37 -> 59 ms to write, and the ledge on the peak flank is gone.
**(4) AND THE COLOURS WERE TOO DARK - he was right.** `PAPER_LUMA` was 0.30,
i.e. exactly the WCAG 3:1 for non-text contrast, and WCAG is the wrong anchor
for a plot line. Measured against the palettes people actually publish with:
matplotlib `tab10` runs **1.69-3.01 (mean 2.23)**, ColorBrewer Set1 2.22,
Okabe-Ito 1.90 - so 3:1 was darker than nearly every member of all three.
0.42 is 2.23:1, `tab10`'s own mean.
**And the curve is stroked 30% thinner** on his call - `CURVE_WIDTH`, 1.4 ->
0.98, shared by the screen and the export because they share `paint_into`.
**(5) HIS SYMMETRY QUESTION, ANSWERED BY BUILDING IT.** "Is it not possible to
exploit the y-symmetry of any of the given peak shapes to just mirror one half
of points sampled over a peak?" The shapes ARE even in d - and the samples are
not. A peak centre lands BETWEEN grid points, so the offsets on the left are
not the negatives of those on the right and no two samples share a value.
Mirroring requires snapping the centre to a grid point, which was built and
measured: **1.53 -> 1.21 ms, 21% faster, and peaks displaced by up to half a
step (0.0025 deg) with a 1.45% height error.** That is the wrong trade in this
window of all places - round 98 verified peak positions at 0.00000 deg against
pymatgen. The textbook version, a table indexed by |d| (which stores only half
the domain and IS the symmetry exploitation), is **slower**: 1.75 ms, because
numpy's `exp` is vectorised and a fancy-indexing gather is not.
**WHAT THE MEASUREMENT DID TURN UP is that the two components need completely
different windows.** Both used `12 * FWHM`: a Gaussian there is `exp(-399)`,
exactly zero in double precision, while a Lorentzian is still 1.7e-3 because
its tail goes as 1/d^2. `REACH_GAUSSIAN = 3` makes the pure-Gaussian shape
**1.75 -> 0.79 ms (2.2x)** for a 1.3e-9 % change in the profile.
**AND IT BUYS THE DEFAULT NOTHING, which is the part worth recording.**
Splitting a pseudo-Voigt's two halves into separate windows was built and came
out SLOWER - **1.44 -> 1.53 ms** - because the extra slice and the extra
accumulate into `y` cost more than the exponentials they remove. So it keeps
one window. My first prototype reported 1.46 -> 1.17 for exactly this and was
comparing two differently-structured loops rather than the real one: a
benchmark whose baseline is not the shipping code is measuring its own
scaffolding.
23 tests. 2086 tests.

Round 100 (2026-09-02, a measured pattern at last - and Christian answered the
hardest part of it himself):
"Could you add the loading in of another pattern for comparison now?" - which
is the whole point of simulating one, and the window could not read a file at
all. Then, mid-round: **"should there not be plenty of pxrd data file readers
available in the diffract suite project?"** There are, and taking them is the
right call rather than a shortcut.
**THE TEXT FORMATS HAVE NO STANDARD AND THE BINARY ONES CANNOT BE GUESSED.**
That split is the whole design. `core/pxrdfile.py` reads the text half against
the only thing every vendor agrees on - two or three columns of numbers under
some header lines - so it is written to that shape rather than to any one
instrument, and a third column is the ESD rather than a second pattern.
`core/bruker.py` is VENDORED from `ACH-Diffraction-Analysis-Suite` (MIT, his),
kept diffable the way `io.py` is with OWB's `coords.py`, because the `.raw`
layout was reverse-engineered there against a PowDLL export and is not
something to re-derive from memory.
**AND TAKING ONLY HALF OF THEM WAS ITSELF A BUG.** The first cut vendored the
Bruker readers and left Riet7 `.dat` behind - which is a header line plus a
block of BARE INTENSITIES with no x column, so the generic two-column reader
paired them off against one another and produced 276 points running to 1290
degrees, drawn without an error anywhere. Two fixes, and the general one
matters far more than the format: `read_riet7` is vendored too, AND
`pxrdfile.MAX_TWO_THETA` refuses any first column leaving 0-180 deg. That is
geometry rather than a plausibility check - backscattering is 180 and there
is nothing past it - so it catches every format whose numbers are not an
(x, y) table, including the ones nobody has met yet. `.dat` is tried as Riet7
first and falls back to the text path, because half a dozen programs write an
ordinary table into the same extension.
**AND THE VENDORED READER CARRIES A TRAP WORTH THE WHOLE EXERCISE.** A RAW
range header holds the start angle TWICE - theta at offset 8 and 2-theta at
offset 16 - and reading the wrong one gives a pattern at HALF the angles,
which looks like a perfectly ordinary pattern of a different compound. Nothing
about the numbers says which was read. `.brml` has the same trap one column
along (`<Datum>` is `time, 1, 2theta, theta, intensity`). It was a comment in
the vendored source and is now `_RH_THETA`, a named constant a test pins
against `_RH_START_2THETA - 8`, because the next person to touch the offsets
should fail at the line rather than at a plausible picture.
**A MEASUREMENT IS NOT A CRYSTAL, so it lives on the WINDOW.** Everything else
this window draws hangs off a `Structure` (round 94's rule: per-structure
settings live on the structure, so deleting a crystal takes its trace with
it). A measurement belongs to no crystal - it is somebody's file - so
`MeasuredTrace` is session state on `PxrdWindow`, remembering the path it came
from so it can be RE-READ. Reload keeps the colour, scale and shift, because a
scan gets re-integrated and background-subtracted and repeated, and the
alternative is losing the alignment you just spent ten minutes on.
**THE TWO NUMBERS ARE KNOBS AND ARE LABELLED AS SUCH.** A measurement and a
simulation agree on where the peaks ARE and not on how tall they are -
preferred orientation, absorption, the displacement parameters no CIF here
carries (round 94) - so the height is a multiplier the eye sets and calling it
a correction would be a lie. The 2-theta shift is the one that IS physics: a
flat sample displaced from the focusing circle moves the whole pattern, and to
first order the shift is a constant.
**IT SITS AT THE TOP OF THE STACK**, which is where the data belongs in every
comparison figure - the measurement, and the candidate phases under it.
**THREE PLACES ASSUME A TRACE HAS REFLECTIONS** and a measurement has none:
the tick marks, the hover readout and the hkl export all walk
`trace.pattern.reflections`. `pattern=None` is the honest representation and
the three guards are the cost of it; inventing a reflection list would have
been worse in every direction.
**AND TWO REFUSALS RATHER THAN A WRONG PICTURE.** A file is in 2 theta and
carries no wavelength, so it cannot be put on a Q axis without inventing one -
Q is what makes two simulations at different wavelengths comparable (round
94), and that argument does not reach a measurement whose source is unknown.
And a measurement running past where the simulation stops is a silently
TRUNCATED comparison: the curve simply goes flat, which reads as the phase
having no reflections up there rather than as nothing having been calculated.
Both are stated in the note line, and the truncation one is recomputed every
time so raising the range clears it by itself. **The load summary no longer
overwrites it** - the first cut set the note after `recompute`, so the one
message that was about a problem lost to "2751 points, 5.000 - 60.000 deg".
Found by a test.
**`build_measured_menu` is split from showing it**, like the other two menus:
`QMenu.exec` spins a modal event loop and a test that calls it never returns
(round 96, and it would have hung the suite again).
**VERIFIED AGAINST THE SUITE IT CAME FROM, on his own files.** All three
shapes - the zipped XML `.brml`, the header-driven Riet7 `.dat` and a plain
`.xy` - come back **bit-identical** to `achdiff.tools.quickplot`'s own
readers: same point count, same first and last angle, same first intensity,
same sum to 1e-12. That is the point of vendoring rather than re-deriving,
and it is pinned by a test that skips where the sibling repo is not checked
out (round 92's arrangement with OWB). All **13** pattern files across his
four PXRD repos read, none refused, and three of them were then stacked over
a simulation in a real window and looked at.
32 tests. 2070 tests.

Round 99 (2026-09-01, A3 closed - a boundary copy is the same atom, and now
it moves like one):
The oldest standing item on the docket, flagged in round 50 and warned about
ever since. A crystal is DRAWN with copies - an atom on a cell face appears
twice and one on a corner eight times, as independent entries in the atom
list, which is correct and is what every crystallography viewer does. Round
54 taught an ELEMENT change and a DELETE to reach every image
(`packing.images_of`); a GEOMETRY edit never learned. Measured on ferrocene
before anything was changed: **content atom 0 is drawn EIGHT times, and a
0.5 A drag moved exactly one of them.**
**THE DOCKET SAID "EDIT THE CONTENT AND RE-PACK", AND THAT IS THE ONE THING
THAT CANNOT WORK.** `packing.pack` unwraps molecules to keep them whole, so
the drawn content is not the canonical content and packing it again does not
give the picture back - round 52 measured ferrocene coming back as 168 atoms
of 210. It would also renumber everything, which invalidates every per-atom
map (round 80).
**PROPAGATING THE DISPLACEMENT DOES THE SAME JOB EXACTLY, and "exactly" is
the word.** Two images of one content atom differ by a LATTICE TRANSLATION,
and a translation commutes with a Cartesian displacement - so applying the
same delta to every image keeps them exactly one lattice vector apart, which
is the definition of their being the same atom. Nothing is renumbered, so
every per-atom map stays valid. Pinned by the property rather than by which
atoms moved: two images are one lattice vector apart to **< 1e-9 A** after a
single-atom drag, a whole-molecule grab, and a 14 A move.
**AN ATOM MOVED OFF A FACE KEEPS ITS COPIES, deliberately.** Re-packing would
delete them, since it no longer sits on a boundary - but round 52's rule for
an edited cell is that the atoms in front of you ARE the structure, and
removing an atom the user did not touch is a worse surprise than keeping the
picture self-consistent.
**IT RUNS BEFORE THE RIGIDITY TEST AND CANNOT CHANGE ITS ANSWER.** A rigid
motion has already moved every image by the same delta, so the sync is a
no-op there and round 91's rule stands: a plain translation of a whole
crystal still keeps `P 1 21/a 1`. A single-atom drag still demotes to P1,
which is round 52's.
**THE ONE CASE WITH NO RIGHT ANSWER IS SAID OUT LOUD.** If two images of one
atom are moved DIFFERENTLY, the first move wins - averaging would be a third
answer nobody asked for - and the status line says so, because it is the only
outcome here where atoms end up somewhere nobody put them. Three things want
the status bar after one edit and they are not equal: the demotion matters
more than "eight copies came along", and the disagreement matters more than
either, so the plain count is posted BEFORE the demotion (and harmlessly
overwritten by it) and the disagreement after.
**The round-50 WARNING is gone**, and its two tests moved with the code
(round 71's rule): one of them was a promise to fix this, which is now kept.
`edits.adjust_bond_lengths`, the other half of A3's note, needed nothing -
round 52 already gates it off for crystals.
2038 tests.

Round 98 (2026-09-01, the plot gets its window back - and the pattern was
right all along):
**(0) "THE PEAK POSITIONS ARE CLEARLY WRONG" - CHECKED, AND THEY ARE NOT.**
Round 94 cross-checked a synthetic rock salt; this checks the REAL files
through the whole `cell_contents` path against pymatgen's `XRDCalculator`.
**Ferrocene (monoclinic P2_1/c) and the solid solution: worst 2-theta
difference 0.00000 deg, worst intensity difference 0.00 %.** And the DISPLAY
half separately, because the fault could have been between the number and the
pixel: every drawn peak sits within **0.02 px** of where the reflection list
puts it, and a gridline value maps to a pixel and back with zero error.
**What he almost certainly hit is the next item.** A typed wavelength was
REFUSED, silently leaving the pattern at Cu K-alpha1 - which is exactly what
"every peak in the wrong place" looks like from the outside.
**(1) A TYPED WAVELENGTH WAS NOT ACCEPTED, and it is one Qt default.** An
editable `QComboBox` INSERTS what you type as a new item (`InsertAtBottom`),
and `itemData` for that row is None - so `source_text` returned the string
`"None"`, `parse_source` refused it, and the pattern stayed where it was.
`NoInsert`, plus reading the text whenever the item carries no spec.
**(2) A DECIMAL COMMA IS A DECIMAL POINT.** He is on a German locale, so
Qt's own separator is a comma and a typed `0.15` is not a number - the spin
box keeps its old value and says nothing. `NumberBox` normalises both ways in
`validate` and `valueFromText`, `parse_source` converts a comma BETWEEN
DIGITS (so a comma separating two components still separates them), and the
axis-limits dialog does the same. A plot is exactly where somebody pastes a
number out of a paper.
**(3) THE "STEPS" WERE NOT AN ANTIALIASING FAULT.** "The anti-aliasing seems
to not work properly unless zoomed in very close. A lot of steps visible."
The min/max envelope reduces to one column per **`rect.width()`**, which is
LOGICAL - so on a 150% display every tread is one and a half REAL pixels, and
antialiasing cannot smooth away a step it has been asked to draw. Reduced at
`width * devicePixelRatioF()` now, which puts the treads below one device
pixel. It only looked right zoomed in because at high zoom the sampler
returns one point per column and the envelope is skipped entirely.
**(4) THE PATTERN TAB KEEPS FOUR CONTROLS AND NO MORE** - radiation, the
2-theta range, the FWHM and the offset - because those are the ones touched
constantly and the rest was spending the plot's own height. Everything else
is on a new **Advanced** tab (peak shape, Q axis, margin, fit, save, export,
the key map) or on the line itself. **The offset slider is VERTICAL and
beside the plot**, which is both what it does and free of height.
**(5) THE GLOBALS ARE OVERRIDES, and every one of them is also per line.**
Radiation, FWHM and the range write to EVERY crystal, ticked or not - an
override that skipped the ones you cannot see would leave a stale wavelength
waiting - and the right-click menu gives one line its own afterwards. The
per-line dialog grew the FWHM and the peak shape to match.
**(6) THE LEGEND AND THE INTENSITY NUMBERS GO.** The tick boxes are already
coloured, so the name inside the plot said it twice; and every trace is
normalised to its own strongest peak, so "100" means the same thing on every
one of them and nothing about any of them. The 0 and 50 rules stay, because
those are what the eye measures against. `_LEFT` drops from 54 px to 10.
**(7) THE TICK LABELS ARE ABBREVIATED** to twelve characters with the full
name on hover - a COD entry's name is a sentence, and a legend is a row.
**(8) THE AXIS LIMITS ARE A DIALOG**, off the right-click menu, `M`, and the
Advanced tab; they were four boxes and a button across the top of a plot that
wanted the height, typed twice a session at most.
**AND THE WINDOW CAN BE MADE SMALL AT LAST.** Round 97 got the minimum from
902 x 634 to 356 x 366; the Advanced tab put it back up to 700 wide through
a `QFormLayout` whose widest row sets the width. `AllNonFixedFieldsGrow` plus
`WrapLongRows` and a wrapping button row: **308 x 329**.
**A DEBUG TICK AT EVERY SAMPLED POINT** was added to the Advanced tab so the
sampling could be LOOKED at rather than reasoned about, and removed again
before this was committed, which is what it was for ("When we commit this, it
will be reverted"). What it showed: one marker per DEVICE column at every
zoom, evenly spaced, which is the claim the round makes.
**AND THE WHEEL'S COST HAS A MEASURED ANSWER**, asked out of curiosity and
worth keeping because the obvious explanation is the wrong one. Scaling the
intensity up does NOT explode the point count - 990 to 1417 over a 500x
scale, +43%, because more columns become "spiky" and emit two points instead
of one, and that saturates at two per column by construction. What explodes
is the **stroked path LENGTH: 3817 px to 1.53 million**, 400x, because a
stroked antialiased polyline costs per PIXEL COVERED and a taller peak has
more vertical pixels in it. It is self-limiting: the paint peaks at 52 ms
around 30x and falls back to 34 ms at 500x, where most of the curve is
off-screen and clipped cheaply. **Clamping the off-screen excursions was
tried and REJECTED on measurement** - 0.69x the speed at 100x scale (a
segment ending just outside the rect has to be rasterised to the boundary,
where one entirely outside is rejected outright) and it moved 1.5% of the
pixels. Left alone deliberately.
2025 tests.

Round 97 (2026-09-01, the window fits the screen, and the curve is sampled
where it is drawn - Christian's two reports and one good question):
**(1) NO MINIMISE OR MAXIMISE BUTTON.** A `QDialog` gets a close button and
nothing else. This is a TOOL window - modeless, kept open beside the viewport,
and a plot is the first thing anybody wants full-screen - so it asks for the
ordinary frame (`Qt.Window` plus the two hints). OWB's spectrum windows are
Toplevels with real WM decorations for exactly this reason.
**(2) "THE LAUNCH SIZE IS WAY TOO BIG NOW", and the `resize` call was not the
problem.** `resize` takes LOGICAL pixels, so at his 150% scaling a 980 x 660
window is **1470 x 990 real ones** - taller than the working area of a 1080p
display, which is why the controls were below the bottom edge. **And no
`resize` could have fixed it, because the window's own minimum was 902 x 634.**
Three causes, and the first is round 90d's trap from the other side: a
word-wrapped QLabel reports the height it needs AT ITS MINIMUM WIDTH, so the
note label asked for **219 px** and set the window's minimum height. Capped at
two lines, with the full text in the tooltip. The control rows were fixed
QHBoxLayouts summing to 816 px, and the hkl tab's own row to 870 - both are
`FlowLayout`s now, which MoloM already had for exactly this (round 45's stage
buttons, round 75's attachment ticks, round 21's rule that a fixed row makes
part of a panel unreachable). Minimum **902 x 634 -> 356 x 366**, and the
opening size is asked of the SCREEN rather than assumed.
**(3) THE SAMPLING QUESTION, and his instinct was right on both halves.**
"Is it possible to improve peak shapes and performance by exploiting the fact
that any given peak type has a known FWHM? ... the only thing I am not clear
on is: what to do at high zoom levels."
**The half he had is right**: a peak of known FWHM contributes nothing beyond
a few widths, so the space between peaks costs nothing - `profile`'s `reach =
12 x FWHM` windowing has always exploited that. **The half he was missing is
that the answer is to stop resampling a stored curve at all.** A stored grid
has ONE sampling for every zoom level, so it is wrong at both ends: zoomed
out it is thousands of points landing on the same pixel, and zoomed in it is
a dozen points across the window. Measured before anything was changed:
**at a 0.1 degree span, 12 points across 754 pixels - 68 px per straight
segment**, which is a polygon, exactly as he predicted ("then 10 ish points
would suddenly be too little").
The profile is an analytic sum of peaks, so `profile_at` evaluates it **at
the pixel columns of the view being drawn**. The point count is then bounded
by the WIDTH of the window at every zoom level: measured **1.00 px per
segment from a 45 degree view down to 0.02**, with the repaint cost flat at
10-15 ms for four traces instead of growing.
**THE TRAP HE DID NOT ASK ABOUT IS ALIASING, and it is the reason for
supersampling.** A peak narrower than a pixel can fall between two samples
and be drawn at a fraction of its height, or vanish. So each pixel column is
sampled several times and reduced by MIN and MAX - which is what a waveform
editor does and what the decimation path here already did - with the count
from the FWHM. Measured on a peak **0.168 pixels wide**: the supersampled
draw reaches **99.7%** of its true height where one sample per pixel finds
**62.6%**.
**AND THE FIRST CUT MADE IT WORSE, caught by a test.** Resampling at every
zoom is wrong: at full zoom the per-pixel sampling is COARSER than the stored
0.01 degree grid, so peak tops came out **4 px low**. Two corrections. The two
paths are chosen by **which samples the profile more finely**, so the drawing
can only ever improve; and `SAMPLES_PER_FWHM` is 8 rather than 3, which is
what a 1% worst-case height error costs (sampling every `d` leaves the nearest
sample `d/2` from the centre, and `exp(-0.5 (d/2 sigma)^2) >= 0.99` gives
`d <= 0.12 FWHM`). The Gaussian is the worst case; a Lorentzian is flatter on
top. **The test that caught it is the one comparing the drawn curve against
the stored samples - written for the decimation, and it had no reason to
exist until the drawing stopped using them.**
2016 tests.

Round 96 (2026-08-31, the PXRD window becomes a spectrum window - Christian's
batch, and OWB's key map poached wholesale):
Round 95 made the pattern reachable. It was also slow, monochromatic, and
navigated by nothing but a horizontal wheel zoom. Nine items, and the
navigation one is the biggest because it is not invention: **the keys, the
modes and the two-stage reset are ORCA Workbench's NMR plotter's**, on
Christian's instruction ("that should be the most refined"), key for key -
`Z` cycles zoom horizontal / vertical / box, `P` cycles pan, `Esc` leaves the
mode, `F` resets x then y then the intensity scale, `M` jumps to the limit
boxes, `R` redraws, `Ctrl+S` saves, `Ctrl+W` closes, the wheel scales
intensity about each trace's own baseline and `Ctrl+wheel` zooms x about the
cursor. Two of OWB's own hard-won details came with them: a PAN is measured
in pixels through the PRESS-TIME view (reading the live one feeds the motion
into itself and the pan accelerates away), and the rubber band is drawn over
a cached picture rather than by redrawing the plot.
**(1) THE PERFORMANCE, AND IT WAS THREE SEPARATE THINGS.** "Scales poorly
with number of PXRDs and is even not very fluid with a single one."
**(a) The structure-factor sum was a Python loop over hkl** with an inner
loop over the scattering parameters per atom. Vectorised and chunked over
reflections (the (n_hkl x n_atom) phase array is what needs bounding, and the
form factors are evaluated per ELEMENT rather than per atom - three curves
instead of forty-two): **ferrocene to 90 degrees, 150 ms -> 10.9 ms**, and
pymatgen still agrees peak for peak.
**(b) It was recomputed for things it does not depend on.** A structure
factor depends on the structure, the source and the range - not on the peak
width, the shape, the stacking or the margin. Cached on exactly that
signature: a full recompute of eight patterns is **37 ms**, a repeat is
**0.2 ms**, and dragging the offset slider is **0.2 ms** instead of a second.
**(c) The paint path rebuilt several thousand QPointF EVERY event**, so
moving the mouse across the plot was as expensive as drawing it. Two fixes.
Everything that does not follow the cursor is drawn ONCE into a QPixmap and
blitted, so a hover is a blit plus two lines; and the curve is decimated to a
min/max envelope per pixel COLUMN. Measured: 4501 samples cost 6.4 ms to
build and 25 ms to stroke, so eight traces were a quarter of a second a
frame. **The envelope emits ONE point for a flat column and two only where
the column has real spread** - a diffractogram is mostly baseline - which
takes it to about one point per pixel: **871 points from 4501, 35 ms for a
full rebuild of eight traces and 0.48 ms for a blitted repaint.**
**AND THE FIRST CUT OF THAT MADE IT SLOWER** (343 ms), because the flat/spiky
selection was a Python loop over a thousand columns - more expensive than the
points it saved. `repeat` plus a cumulative index instead.
**A PAN BLITS TOO**, and it is the one gesture that can: the picture is
unchanged and only its origin moved, so `paintEvent` draws the cached pixmap
SHIFTED and the rebuild waits for the release.
**(2) THE DEFAULT RANGE IS 50 DEGREES**, Christian's call. The sum is over a
sphere of radius 1/d_min, so the cost grows as the CUBE of how far you ask,
and a molecular crystal has almost nothing above 50.
**(3) THE SELECTION DECIDES THE TICKS.** "If I select 3 structures and then
launch it, only those three should be ticked and shown." And deliberately
**not written back**: a selection says what this OPENING is about, so opening
the window on one of five must not silently switch the other four off in the
savefile. Ticking a box by hand DOES write, because that is the decision.
**(4) A LAB TUBE EMITS A DOUBLET, and one calculation covers it.**
`parse_source` reads a wavelength (`1.5406`), an ENERGY (`17.5 keV`,
`8040 eV` - a synchrotron user states one and never the other), a named line
(`Cu Ka1`, `Mo Ka2`), or a doublet with its ratio (`Cu Ka1+Ka2 2:1`). One
parser for the presets and for anything typed, which is what lets a source
that can be chosen also be written down.
**The doublet costs nothing extra because `s = sin(theta)/lambda = 1/(2d)`
has no wavelength in it**: `|F|^2` is shared and only the ANGLE and the
Lorentz-polarisation factor differ, so `Reflection` carries `f2` and
`peak_positions` places one peak per component. Measured on rock salt: the
split grows from **0.069 deg at 27 deg to 0.49 deg at 119 deg**, which is the
signature of a real K-alpha doublet, and the alpha2 comes in at **0.497** of
alpha1 rather than exactly 0.5 - the two lines diffract at slightly different
angles, so their LP factors differ. **On the Q axis a doublet does not split
at all**, which is not a bug but the reason that axis exists.
2:1 is the standard ratio and it is a property of the ATOM (the 2p level
degeneracies), not of the instrument, so it is the same for every tube here.
**(5) AN hkl TAB, WITH THE SYSTEMATIC ABSENCES IN IT.** The columns a
reflection list carries: h k l, d, 2-theta, Q, multiplicity, |F|^2, the
Lorentz-polarisation factor, the relative intensity, and whether the
reflection is absent. **The absences are the reason the tab exists** - a list
that shows only what is there cannot answer "is 100 allowed?". `keep_absent`
merges them in rather than dropping them at `|F|^2 <= ABSENT_F2`, and the
check is textbook: on rock salt every absent reflection has MIXED-parity
indices and every present one does not, which is F-centring falling out of
the arithmetic rather than out of a rule.
**(6) PER-CRYSTAL SETTINGS OFF A RIGHT-CLICK**, on the line or on the tick
box - both, as asked, and the line because "clicking the line is more
intuitive and doesn't require tab switching". Colour, radiation and range,
stored on the structure like everything else here. The dialog SAYS what it
understood the source text to be, and refuses OK while it cannot read it: a
source box that quietly falls back to Cu is how a whole pattern comes out at
the wrong angles with nothing on screen to say so.
**(7) AND A PRECISION BUG THAT ONLY THE CACHE MADE VISIBLE.** The source box
showed a bare wavelength as `{:.5f}`, so Cu K-alpha1 became "1.54060" and the
box handed that back as a DIFFERENT wavelength - which changed the cache key
on every edit, recomputed every pattern, and moved every peak by a
ten-thousandth of a degree. Ten significant figures round-trips.
Found by the test asserting that a peak-width change reuses the pattern,
which is the second time this session a cache has been the thing that made an
invisible wrongness visible.
**(8) A FOURTH FAULTY MEASURING INSTRUMENT.** The first check that the
decimation keeps every peak reported SEVEN lost peaks - and it had assigned
samples to pixel columns with `round` while the envelope uses truncation, so
it was comparing adjacent columns. Allowing a pixel of slack in x: **worst
peak-top error 0.000 px**, and the tallest drawn point equals the tallest
true one. Rounds 86, 86 again, 89 and now this: **a measurement that
disagrees with the code is as likely to be the instrument as the code.**
Also: `QMenu.exec` runs a modal event loop, so the menus are BUILT by
`build_trace_menu` / `build_label_menu` and shown by one line - a test that
reaches `exec` hangs rather than fails, which is round 75's lesson.
**(9) AND IT SHIPPED BROKEN ON HIS DISPLAY, which is ROUND 59'S OWN TRAP.**
Christian: "something is completely screwed" - a screenshot with the plot
drawn into the top-left two thirds of the widget, no x axis, no right-hand
peaks, one flat blue line, and the crosshair running on past the edge of the
picture into bare grey.
`QPixmap(w, h)` allocates w x h DEVICE pixels; `setDevicePixelRatio(1.5)`
then declares them to be **w/1.5 x h/1.5 LOGICAL** ones. So the blitting
cache, made at the widget's logical size, covered exactly two thirds of a
150% display and everything past that was clipped - while the crosshair,
painted on the WIDGET, was drawn at full size. Both halves of the screenshot,
from one line. **The bare grey was the unpainted widget showing through**,
which is what makes it look like a layout catastrophe rather than a pixmap
one.
**And the flat line was the same bug, not a second one.** Griceite is LiF,
whose only reflections below 50 degrees are 111 at 38.70 and 200 at 44.99 -
both in the right-hand third, i.e. exactly the part that was clipped away.
The visible left two thirds of an LiF pattern is a flat line, correctly.
Round 59 met this from the other side, in `tools/screenshots.py`, and this
file has carried the lesson since. **Pinned now rather than remembered**: a
test shadows `devicePixelRatioF` at 1.0, 1.25, 1.5 and 2.0 and asserts the
pixmap is allocated in DEVICE pixels and covers the widget - which is
testable at any scale, where running the suite at 150% is not (a
QApplication reads its scale factor once, at construction).
2009 tests.

Round 95 (2026-08-31, the powder pattern gets a window - and the active object
stopped wandering off):
Christian's checklist against round 93: make PXRD reachable, and three things
that were still wrong.
**(1) THE PXRD WINDOW, AND THE BRIDGE IS WHERE THE MISTAKES LIVE.** Round 94
returned arrays and deliberately built no UI, so **matplotlib is still not a
dependency**: `ui/pxrd_panel.py` PAINTS the diffractogram, the way the
timeline pane is painted, because a pattern is a polyline against an axis and
a plotting library would do nothing here that thirty lines of QPainter do not.
Reachable three ways - **Ctrl+Shift+D**, a button on the crystal page, and
View > Crystal - because a property OF the crystal belongs beside the
crystal's other properties (round 21's rule).
**`pxrd.cell_contents` NEVER READS THE DRAWN ATOMS**, and that is the whole
design. A structure factor is a property of the CELL, so the picture is the
wrong input three times over: boundary copies are the same atom drawn twice
(an atom on a face would be counted twice), a packing is many cells, and both
are in the VIEWPORT's frame rather than the cell's. It regenerates from the
asymmetric unit and the operators every time, which makes the invariant
testable and it is: **asymmetric unit, full cell and a 2x2x2 packing give an
identical pattern**, and so does a crystal that has been dragged across the
viewport.
**A SHARED SITE HAD TO BE PUT BACK TOGETHER.** `expand`'s minimum-image merge
keeps the first species of a shared position and discards the rest (round 42's
ordering flaw), which costs a picture a pie sphere and costs a structure
factor the actual scatterer - the solid solution would have diffracted as
half-empty Nb. `site_composition` restores it as one term per species at one
position, which is what the sum wants anyway. Checked against chemistry rather
than against our own numbers: it is a rutile-type oxide and comes out with
110, 101 and 211 as its three strongest reflections, 110 at 26.81 deg.
**Q IS FORCED WHEN THE WAVELENGTHS DIFFER**, `common_axis` deciding rather
than the user - two patterns at two wavelengths put the same reflection at two
angles on a 2-theta axis, and drawing that would be a lie the window is
perfectly able to avoid. The tick is then disabled rather than merely wrong.
**(2) "THE ACTIVE STRUCTURE TURNED ON DRAW ATOMS OUTSIDE THE CELL BOUNDARY FOR
SOME REASON WHEN SWITCHING BACK."** It did not - the ACTIVE OBJECT moved.
Round 91b's fan-out restored `self.active_id` and THEN called
`select_whole_molecules` to put the selection back, and picking moves the
active object to the last thing selected (round 7). So after any fan-out the
crystal page described the last crystal in the list and read ITS ticks back,
which looks exactly like a tick turning itself on. Restored AFTER the
re-selection now, in both fan-outs. Measured: with LiF being looked at and
five crystals selected, a single tick used to leave CsF active.
**(3) AND THAT IS ALSO HOW ONE EDITED CELL GREYED THE WHOLE PAGE.** "If the P1
CsF is selected, the message that an edit has been made pops up and you have
to deselect it to use controls on the other four again." Two causes on top of
the drift: `frozen` was read off the SUBJECT alone, so one `cell_frozen`
crystal disabled the contents radio for every other crystal the controls would
have reached; and each frozen target posts its own "was edited in the full
cell" status line on the way past, so with five selected the complaint was the
last thing said and the click looked as though it had done nothing else.
Frozen now means EVERY target is frozen - the same rule `_crystal_targets`
already applies to a molecule swept up by Ctrl+A - and the fan-out reports
once, counting them ("4 crystals: asymmetric unit only (1 edited into P1, left
as it is)").
**(4) THE CRYSTAL PAGE NOW FOLLOWS THE SELECTION, not only the active
object.** "Luciferin 6'-ethyl ether sodium salt when selected still shows the
crystal page for Griceite. When clicking the controls, nothing about Griceite
changes though." The page describes `_crystal_subject()`, which reads the
SELECTION, and `_sync_crystal_page` ran from four paths none of which was a
plain selection change - so a selection that left the active object alone left
a page naming one crystal while its controls reached another, which is
precisely what "nothing changes" looks like. Re-synced from
`_on_selection_changed`, and only when the SUBJECT really moved, because that
runs on every mouse move of a box select. **And the box tick was the one
per-crystal flag never read back**: round 93 made the cell box per crystal
(round 51's four-place lesson) and `_sync_crystal_page` never passed `box=`,
so it kept whichever crystal was looked at last.
**(4b) AND SIMULATING A PATTERN BEFORE AND AFTER A DEMOTION FOUND A REAL
PRE-EXISTING BUG.** The two must be the same crystal, and they were not - 298
reflections became 335 with intensities up to 18% apart.
`resync_derived_asymmetric_unit` took the FIRST `cell_content` drawn atoms as
the content, and `packing.pack`'s own comment says why that cannot work:
"`complete_molecules` REORDERS and duplicates". Measured on ferrocene, the
first 42 drawn atoms are ONE molecule plus a lattice copy of it, where the
cell holds two molecules related by a screw axis - so demoting an edited
ferrocene wrote an asymmetric unit of 21 atoms listed TWICE, `expand` merged
the duplicates on the way back, and the P1 cell was half the crystal. The
file's own `Z 2` and `C10 H10 Fe` settle which of the two is right.
`content_of` - which cell-content atom each drawn atom is an image of - is the
map that answers it properly, and it has been recorded since round 54.
`_content_atom_indices` takes the first drawn image of each. **Verified by the
invariant that found it: a demotion to P1 now changes the pattern by 6.7e-16,
i.e. not at all.** It also reached the CIF writer's re-derived path and
`demote_to_p1`, so an exported edited crystal was carrying the same halved
unit.
**(5) THE SEARCH TABLE'S WIDTH, AND THE CULPRIT IS A DOCUMENTED Qt
BEHAVIOUR.** "The width jumps back and forth between contracted and full width
used... I think the name column is the culprit." It is, and the mechanism is
that **`QTableView.resizeColumnsToContents` calls
`resizeSections(ResizeToContents)`, which by design IGNORES the per-section
resize mode** - so it fitted the STRETCH column to its longest entry too.
Measured: a long name takes it to **1771 px inside a 796 px viewport**, and a
relayout then snaps it back. Round 93 had already stopped it running on every
SORT; it still ran on every batch a provider landed. The stretch column is now
set up once in `__init__` and never refitted, and only the fixed columns are
fitted, one by one.
**A long name WRAPS instead**, which is Christian's own suggestion and the
only honest option once the column cannot grow: eliding hides the half that
tells two entries of one compound apart, which is what the list exists to
show. `setWordWrap` plus `ElideNone` plus a `ResizeToContents` vertical
header, and a `resizeEvent` that re-fits the rows - **a wrapped cell's height
depends on the column's width and nothing in Qt propagates that**, so widening
the window otherwise leaves a two-line name in a two-line row with one line in
it. Alternating row shading uses the timeline pane's own pair, so the two
lists in the program look like the same program.
Double-clicking the border of the stretch column is now a NO-OP rather than a
half-working gesture ("border clicking kind of works"): it already occupies
every pixel the others leave, and fitting it would take it out of Stretch
until the next relayout put it back - i.e. it would re-create the flicker on
demand.
1968 tests.

Round 94 (2026-08-27, the diffraction a crystal already knows how to give -
`core/pxrd.py`, the physics only):
Christian asked for the plot window to be designed first and then set up "what
you can right now", so this round is the CALCULATION and none of the UI. That
split is the point: `core/pxrd.py` returns arrays, so **matplotlib is still
not a dependency** and the window's decision is still open.
**IT IS CHECKED AGAINST ANOTHER PROGRAM, not against numbers written here.**
pymatgen's `XRDCalculator` on rock salt: **all 9 peaks matched, max 2-theta
difference 3.9e-4 deg, max intensity difference 0.0000 %.** pymatgen is not a
MoloM dependency (it is the optional backstop for space-group symbols), so the
cross-check skips where it is absent and the rest of the suite stands on
textbook facts instead - the multiplicities of rock salt (111 x8, 200 x6, 220
x12, 311 x24) and the absence of every mixed-index reflection.
**BOTH OF THOSE COME OUT OF MERGING, NOT OUT OF A RULE.** Every `hkl` in the
sphere is enumerated and reflections landing at the same angle are summed, so
multiplicity accumulates and systematic absences are just `|F|^2` being zero.
Nothing in `compute` knows what an F-centred lattice is, which is exactly what
makes the agreement meaningful.
**THE SCATTERING FACTORS ARE VENDORED AND THE PARAMETERISATION IS THE TRAP.**
`tools/gen_scattering.py` generates `core/scattering.py` from pymatgen's table
(MIT, itself International Tables Vol. C Table 6.1.1.4), the same way
`gen_elements.py` generates the element data - a numeric table nobody should
type from memory. The coefficients give the DIFFERENCE from Z,
`f(s) = Z - 41.78214 s^2 sum a_i exp(-b_i s^2)`, NOT a Cromer-Mann sum with a
constant term; using them in the wrong formula gives numbers that look
entirely plausible. A test pins `f(0) == Z` for three elements because that is
the cheapest way to catch it.
**Q IS NOT A DISPLAY PREFERENCE.** 2-theta depends on the wavelength and Q
does not, so two structures simulated at different wavelengths cannot honestly
share a 2-theta axis - the same reflection would sit at two angles for no
physical reason. `common_axis` is what the window will ask before drawing
several patterns together, and a test pins that one reflection gives one Q at
two wavelengths.
**PER-STRUCTURE SETTINGS LIVE ON THE STRUCTURE**, in `metadata` beside
`polyhedra` and `show_cell` - which is the round 91b/93 decision applied
again, and it means the plot window will own no per-structure state at all:
deleting a crystal takes its trace with it because the trace was never the
window's. Only what DIFFERS from the defaults is written, so a savefile does
not carry ten keys per crystal saying "as shipped".
**AND IT SAYS WHAT IT DOES NOT KNOW.** No CIF here carries displacement
parameters, so B = 0 and the high-angle intensities are overestimated;
`Pattern.note` says so rather than letting a plausible curve stand
unqualified. A species with no tabulated factor falls back to Z and says that
too - assembled BEFORE the empty-pattern early return, because an all-`Xx`
structure scatters nothing and the emptiness is exactly what the warning
explains. Found by a test.
Measured on the vendored files: the solid solution is 27 reflections, ferrocene
335 from a 42-atom cell in 0.15 s.
1934 tests.

Round 93 (2026-08-27, the rest of Christian's checklist - and a crash that had
been waiting for the right crystal):
**(1) "HAVING BENZENE IN THE SELECTION GREYS OUT ALL CONTROLS OF CRYSTAL
PROPERTIES TAB."** Picking atoms makes the last one ACTIVE, so sweeping up a
solvent molecule with Ctrl+A killed the whole ❖ page - while its controls
would have worked perfectly well, since `_crystal_targets` filters
non-crystals out anyway. The page was the only thing that had not been told.
`_crystal_subject()` is the fix: the active object when it IS a crystal,
otherwise the first selected one. With no crystal anywhere the page greys as
before.
**(2) THE VIEW RADIO WAS LEFT BEHIND BY ROUND 91b**, which is the worse half
to leave: "Switch to asymmetric unit view only works on the active crystal
when all except CsF are selected." A view mode is exactly the control you want
to apply to a row of isostructural crystals at once. `_on_crystal_view_chosen`
fans out over `_crystal_targets()`; `on_crystal_view` itself stays
single-object, because F3, the outliner row and `_on_packing_option` all call
it and a fan-out inside would recurse.
**(3) THE CELL BOX IS PER CRYSTAL NOW**, and Christian's argument is the right
one: "Show unit cell box is applied to every crystal structure, even not
selected ones... Is it not a crystal's own internal coordinate system that
should be displayable relative to the viewport's absolute euclidian space?" A
cell belongs to ONE crystal and with several open you want one box and not the
other. `viewport.show_cell` stays as the MASTER behind the View menu - "show
me no boxes at all" is a different request from "not this crystal's" - and
`cell_shown(obj)` is the per-object refinement, ABSENT MEANING SHOWN so every
file from before this draws as it always did. Two round-21/23 tests pinned the
old global contract and moved with the code (round 71's rule).
**(4) SORTING RESIZED THE COLUMNS.** "Sorting also rescales hspace of column
which should only happen on double click of border between two columns."
`refill` runs on every sort and called `resizeColumnsToContents` each time, so
asking for an ORDER rearranged the LAYOUT. It now fits the columns only when
the row set itself changes, and `sectionHandleDoubleClicked` gives Excel's
gesture - the column to the LEFT of the handle, which is the index Qt reports.
**(5) AND A PRE-EXISTING CRASH, found by driving the above.** Switching
`Griceite_9008667` to the asymmetric unit threw `IndexError: index 5 is out of
bounds for axis 0 with size 2`, while its four siblings switched happily.
`packed_bonds` is a bond list keyed by DRAWN atom index; an asymmetric unit
produces none, so `on_crystal_view` - which set the key only `if
report.get("packed_bonds") is not None` - left the previous FULL CELL's list
in metadata for `_perceive_fresh` to apply to two atoms. It only bit a crystal
that had actually been packed, which is why one of five threw. Dropped and
re-set TOGETHER now, which is round 83's rule in the one place that
regenerates the atom list wholesale.
1916 tests.

Round 92c (2026-08-27, Christian's round-trip pass - and the ZIF-8 that was
never a crystal):
**(1) "IT OPENS THE .cif NOT AS A CRYSTAL STRUCTURE BUT A MOLECULE" - and the
file is the reason.** His `Desktop\ZIF-8.cif` carries the line "# CIF file
generated by openbabel 3.1.0", has **no `_cell_length_a` at all**, and puts
CARTESIAN values (4.2475, 8.4950, 12.7425) in the `_atom_site_fract_*`
columns. MoloM's reader refuses it and falls back to OpenBabel, which reads
the atoms and throws the crystallography away - so a molecule is the only
honest outcome. **ASE refuses the same file** ("You have 0 lattice vectors"),
which is the round-35b check: ask an independent reader before blaming your
own. His other copy, `Desktop	est cifs\ZIF-8.cif`, is a proper file and
opens as `I -4 3 m` with 696 atoms.
**What was wrong was the SILENCE.** The fallback said nothing, so a file that
is not a crystal and a reader that failed look identical from the outside.
`cif_fallback_note` now adds "no unit cell in the file, so it opened as a
plain molecule - the crystal page stays greyed" to the import message. It
keys on the FILE'S EXTENSION, because a fallback import loses every other
trace: OpenBabel's reader sets no `source: cif` and the object is named after
the stem, so neither can be asked.
**(2) Ctrl+Alt+S DID NOTHING DIFFERENT, and he was right to ask.** "Don't know
what the difference with Ctrl+Alt+S is supposed to be though." Round 92 gave
it as the always-available route to the round trip - and `on_save_project_as`
cleared `source_path` on the way past, so the two shortcuts could never both
be live: `Ctrl+Alt+S` was disabled in exactly the situation it exists for.
Saving a project no longer ends the round trip. OWB is still waiting for that
.xyz whatever MoloM has decided its own document is, so `source_path` is kept
and the banner names the key that now writes back (`Ctrl+Alt+S` once a
project has taken over, `Ctrl+S` before that).
**(3) The banner and the flash are confirmed working, and the SMILES half is
OWB'S.** "Could it be that SMILES is updated in the comments of the xyz
filestring but not in the entry of the molecules tab?" - exactly so, and it is
the half recorded in the sibling repo's TODO rather than a MoloM bug.
**(4) The launch delay is not MoloM'S to fix, measured.** "On first launch
MoloM is kinda slow and there is no indication after double click that
anything is happening." `tools/startup_profile.py` says **2.35 s**, of which
`MainWindow()` is 926 ms and the first paint 595 ms - Qt's cold font and style
caching, which round 65 already established is most of the bill and is not
something MoloM can shrink. So the fix is a launcher-side one and is written
into OWB's TODO: an indeterminate indicator between the double-click and the
window appearing. Worth noting the total has NOT regressed across rounds
90-92 (round 65 measured 2877 ms).
1909 tests.

Round 92b (2026-08-27, Christian's test batch - what a round trip looks like,
and two bugs found by using it):
**(1) NOTHING ON SCREEN SAID A SAVE WOULD OVERWRITE SOMEBODY ELSE'S FILE.**
"There is no indication that an edit will be forwarded to OWB or that we are
currently in a round-trip situation." Round 92 made Ctrl+S write back to the
structure file the session was opened from - which is exactly right and is
also a keystroke that quietly does something quite different from what it does
in an ordinary session. `viewport.set_roundtrip` puts a banner top RIGHT
("Round trip - Ctrl+S writes back to mol.xyz"), clear of the edit-mode header
on the left, and only for the round-trip case: a `.molom` project is MoloM's
own document and needs no warning that saving it saves it.
**(2) AND THE SAVE ITSELF NOW SAYS SO WHERE THE EYE IS.** `viewport.flash`
fades a confirmation over the viewport, because the status bar is in the far
corner of the window and a save is precisely the moment nobody is looking
there. It holds at full opacity for the first third and then fades - a message
that starts fading immediately is one you read half of.
**(3) THE DERIVED SMILES IS FORWARDED.** "Since MoloM can derive SMILES from
struct, it should also forward the updated SMILES (if possible) to OWB so the
skeletal structure updates." `io.structure_to_smiles` reads the GRAPH, so
after an edit it is the edited constitution: cubane goes out as
`C12C3C4C1C1C2C3C41` and comes back `C12C3C4C1C1C2C3N41` once one carbon is
changed. It rides the xyz COMMENT line, the one channel an .xyz has and the
one place every other program already looks (round 76). **Silent on anything
it cannot honestly answer** - a crystal (a SMILES of a packed cell means
nothing), a structure with no bonds, or a graph RDKit refuses - because a
wrong SMILES forwarded into another program is far worse than none. Reading
it back is OWB's side and is written into that repo's TODO.
**(4) A PASTED CAS NUMBER WAS HANDED TO THE CHEMISTRY BACKENDS AS A SMILES.**
Christian pasted `2591-17-5` and got a dialog carrying "RDKit could not parse
SMILES" and "OpenBabel raised OSError" - two complaints about a question
nobody should have asked. `on_paste` tried xyz and then assumed everything
else was a SMILES, while `resolve.classify` has always been able to tell a
CAS number, a name and an InChIKey apart. Those now open the molecule search
pre-filled and run it, so pasting a CAS behaves like searching for one.
**(5) "ASYMMETRIC UNIT ONLY" MOVED THE CRYSTAL TO THE ORIGIN, and the cause is
a guard doing half its job.** His report: "Unit cell of RbF jumped from
position of RbF to (0,0,0) as an anchor. Clicking full unit cell again shifted
the full crystal back to (0,0,0)." A crystal's placement is RECOVERED from a
sample of reference atoms (round 19), and `set_cell_reference` refuses to pin
one below three atoms - correctly, since two points cannot fit a rotation.
What it did not do was CLEAR the old sample, so an `F m -3 m` fluoride whose
asymmetric unit is TWO atoms kept 24 indices into a 27-atom list that no
longer existed: the fit then failed silently and the next rebuild regenerated
the crystal in the cell frame, at the origin. Round 80's lesson exactly - an
index map that survives a renumbering does not stop being wrong, it stops
being obvious.
Fixed at both ends: the stale reference is dropped, and the pose is RECORDED
explicitly (`set_cell_pose` / `stored_cell_pose`, in metadata so it rides the
savefile) for the case where no sample can exist. `cell_corners_world` and
`_rebuild_pose` both fall back to it, which is why the box stopped jumping
too. Measured on his own MF.molom: RbF holds x = 36.82 and its box origin
x = 34.0 across repeated asym/cell switches, where before the first switch
put the box at 0 and the trip back put the crystal at 2.82.
1905 tests.

Round 92 (2026-08-27, ORCA Workbench at last - roadmap F, the item that
motivated the whole project):
**F1 NEEDED NO CODE IN EITHER PROGRAM, and finding that out was most of the
work.** OWB launches an external 3D program as `[program, file.xyz]` and
nothing else (`orca_workbench/ui/molecules_tab.py::open_xyz_3d`), so
`molom mol.xyz` was already the whole of what `viewer_3d_path` needs - and
`traj_viewer_path` too, since MoloM reads a multi-frame xyz as a trajectory
and gives it the scene clock. What was missing was the two things that make
the integration worth having, plus knowing where to point it.
**`--where` PRINTS THE LAUNCHER PATH**, because "point OWB at molom" is only
easy once you know where the console script landed. The first cut looked
beside `sys.executable` and reported "not installed" for a perfectly working
install: a per-user pip install puts the interpreter in `C:\Program FilesPython310` and the script in `%APPDATA%\Python\Python310\Scripts`.
`shutil.which` first - which is what OWB's own `_on_path` uses to decide
whether a program is usable.
**THE ROUND-TRIP WAS FAILING SILENTLY, which is the worst way to fail.** OWB
opens the file in the EDITOR slot, tells the user to "adjust the geometry,
then Save so it overwrites the .xyz", and re-reads that file, setting
`coords_locked` so a hand-edited geometry is not clobbered by SMILES
regeneration. MoloM's Ctrl+S saved a `.molom` PROJECT - so the user would
save, OWB would reload an unchanged file, and BOTH programs would report
success. Ctrl+S now saves the DOCUMENT: the project where there is one,
otherwise the structure file the session was opened from. `Ctrl+Alt+S` always
means the second, so the round-trip is reachable whatever else happened.
**Only the FIRST structure file claims it**, because imports ADD in MoloM
(round 2) and silently re-pointing Save at whatever was opened most recently
is how a round-trip overwrites the wrong file.
**`--select 3,7,11` IS 0-BASED BECAUSE ORCA IS.**
`orca_workbench/core/geomspec.py` states it outright - "ORCA atom indices are
0-based" - and the entire point of the flag is to paste the numbers out of a
`%geom` constraint and see which atoms they are. Renumbering them would make
the feature worse than useless. Commas or spaces, since a `%geom` block is
written with spaces and a shell argument is easier with commas; a token that
is not an index is REFUSED rather than dropped, and an index the file does not
have is reported. Two, three or four atoms also print the bond, angle or
dihedral they define, which is exactly what the constraint means - water with
`--select 1,0,2` reads `angle(H1-O0-H2) = 104.51 deg`.
**VERIFIED AGAINST OWB'S OWN READER**, not against an assumption: the sibling
repo is checked out beside MoloM, so the test writes a file with MoloM and
reads it back with `orca_workbench.core.coords.read_xyz`. It comes back as
three atoms in the right order, because MoloM writes a PLAIN comment line
rather than its JSON metadata block (round 76's rule, and this is what that
rule was for). The test skips where OWB is not checked out.
`docs/ORCA_WORKBENCH.md` is the setup page.
**STILL ONE-WAY**: MoloM can read indices out of a constraint and cannot hand
a selection back as a `%geom` block. "Copy selection as an ORCA constraint" is
the obvious next step and is recorded rather than built.
1890 tests.

Round 91b (2026-08-27, one tick, every selected crystal):
Christian, after the P1 fix: "do the tick changes for multiple at once."
`_crystal_targets()` is the whole of it - every SELECTED object that has a
cell, with the ACTIVE one always included (the tick shows its state, so it
would be strange for that to be the one left behind), falling back to the
active object alone when nothing is selected, which is the old behaviour and
the common case. It drives the two packing options, the four display flags
(polyhedra, refused bonds, symmetry elements, ghosts) and the symmetry-kind
filters. `_set_cell_box` is deliberately untouched: `viewport.show_cell` is
one flag for the whole viewport rather than a per-object one.
**A MOLECULE CAUGHT IN A SELECT-ALL IS PASSED OVER.** The page is the crystal
page and its ticks are crystallographic, so cubane swept up by Ctrl+A is not
given a `show_symmetry` it can do nothing with.
**THE SELECTION HAS TO BE PUT BACK, and missing that would have shipped the
same surprise one click later.** A packing change calls `on_crystal_view`,
which regenerates the atom list - so the selection, which names atoms BY
INDEX, is dropped. Measured: five selected objects before the click, zero
after. The first tick would have reached five crystals and the second exactly
one. `select_whole_molecules` restores them, and whole molecules is the right
unit because the old indices no longer refer to anything.
Two of my own logic errors, both caught by tests rather than by reading.
`on_crystal_view` rebuilds THE ACTIVE crystal, so each target takes its turn
at being active and the original has to be restored, or clicking a tick
quietly changes which molecule the rest of the UI describes. And the escape
hatch for the outliner's own row control was first written as "an object that
is not in the selection acts alone", which is the wrong test - a row control
for a crystal that happens to be selected would broadcast to all of them. The
discriminator is whether the caller passed the ACTIVE id, because that is what
the page's own ticks pass.
1877 tests.

Round 91 (2026-08-27, moving a crystal is not editing it - Christian's
alkali-fluoride savefile):
"I have a savefile called MF.molom... It contains isostructural alkali
fluorides. I wanted to change a tick box in the cif props pane for all of them
simultaneously => Select all, untick draw atoms outside boundary. I think it
basically just selected the last in the list CsF and then some edit happened,
which converted it to P1 and made the tickbox i wanted to change unresponsive."
**Both halves confirmed, and the tick box was innocent.** His file opens with
four fluorides still `F m -3 m` and CsF alone at `P 1` with `cell_frozen`
already set - the damage is IN the savefile, so it happened while he was
working and was then written out. Reproduced in one line: **a plain 0.5 A
translation of a whole crystal demotes `F m -3 m` to `P 1`.**
**A SPACE GROUP DESCRIBES THE STRUCTURE, NOT WHERE IT SITS IN WORLD SPACE.**
`_reevaluate_edited_crystal` ran `demote_to_p1` on every edit commit without
ever asking what the edit WAS, so a grab, a rotate or an anchored tumble - the
commonest gestures in the program - destroyed the symmetry of whatever crystal
happened to be active. And `demote_to_p1` sets `cell_frozen` (round 52, so a
hand-edited cell is not regenerated underneath the user), which greys the ❖
controls: that is the "tickbox unresponsive" half, an entirely correct
response to a state the crystal should never have been put into.
Round 43e already knew this - "an EDIT is not a rigid motion, so never measure
a pose across one" - and captured the cell pose BEFORE an edit so the cell box
would not creep. The same distinction simply had not been applied to the
symmetry.
**`_edit_was_rigid` asks the structure rather than trusting the gesture.**
`begin_model_edit` now stashes the coordinates, the symbols and the bonds
alongside the pose (both edit paths go through it - `begin_chemistry_edit`
calls it), and the commit fits the two coordinate sets with Kabsch. A rigid
motion leaves float noise, so the group is kept; anything else demotes.
**THE COMPOSITION CHECK COMES FIRST, AND A TEST IS WHAT PUT IT THERE.** The
first cut compared coordinates only - and an element change MOVES NOTHING, so
`set_element` read as a rigid placement and kept a space group that no longer
held. Caught by the test that drives a real chemistry edit rather than by
reading the code, which is the third time this session a test earned its place
that way.
Deliberately still demoting: dragging SOME of a crystal's atoms, because the
fit is over all of them and a partial move is not rigid. And the capture is
consumed on read, so a leftover snapshot from an earlier gesture cannot make a
later real edit look rigid.
**WHAT IS NOT FIXED, and is a feature rather than a bug: the ❖ page acts on
the ACTIVE object only.** `_on_packing_option` takes one `obj_id`, so
"select all, untick" changes exactly one crystal - which is what he saw before
the P1 damage distracted from it. Applying a per-crystal tick to every
SELECTED crystal is a small change and a real decision (it would make one
click rewrite several molecules' metadata), so it is recorded in
`docs/OPEN_ITEMS.md` rather than assumed.
1867 tests.

Round 90d (2026-08-27, the molecule IS the identifier - and the properties
page stops needing a lock):
Christian: "I would like to be able to search for properties even on
drawn/edited molecules. We already have a way to derive the SMILES from a
structure. Shouldn't it be possible to just use that as an identifier for
queries? maybe even obtain the inchikey and then do it the most reliable way?
no need anymore to guard against edits (i think?). Also right now I cannot use
it on the cubane the app launches with. same reason?"
**Yes to all of it, and the last question answers itself: the app's own
default cubane now comes back as PubChem CID 136090.** `io.structure_to_smiles`
reads the drawn GRAPH - atoms, bonds and orders - so it is exact rather than a
guess, and hashing it gives the same InChIKey a searched compound gets. Round
90's identity came from the SEARCH and was therefore absent on anything drawn,
built or opened from a file; it now comes from the structure, every time.
**AND THE LOCK GOES, for a better reason than convenience.** Round 90 attached
the record through `core/attachments.py` as POLICY_FRAGILE so a chemistry edit
would mark it stale. That works, and it is the wrong instrument here: an
overwrite lock exists to protect something expensive and irreplaceable (round
75's twenty-minute frequency job), whereas this is a web lookup keyed on the
structure. Once the identity can be RE-DERIVED, the question can simply be
ASKED - `Record.describes(inchikey)` compares the stored key against the
molecule in front of you - which is strictly better than a flag because it
catches an edit made by ANY route rather than only one that went through the
edit path. Measured end to end: cubane fetches as Cubane/136090, `C -> N` with
its hydrogens re-dressed is caught as "now a different compound", and fetching
again identifies it as **Azacubane, CID 85608268**.
Two refusals rather than a wrong answer: a structure with a `cell` is not a
compound (a SMILES of a packed cell means nothing) and anything over
`MAX_IDENTIFY_ATOMS` is declined, because identification is 0.93 ms on cubane
and 13 ms at 300 atoms and `sync` runs on every selection change. It is also
CACHED against a cheap signature of the graph, on the page rather than in
metadata - derived data does not belong in a savefile.
**"ARE ALTERNATIVE NAMES SHOWN ANYWHERE?" They were not; they are now.**
PubChem lists **264 synonyms for benzoic acid and 698 for aspirin** (6.6 kB
and 16.5 kB), so "show the synonyms" is not an option - `MAX_SYNONYMS` keeps
the first 8 as PubChem ranks them, which is the common name, the CAS number
and a trade name or two. Benzoic acid reads "Also known as: benzoic acid,
65-85-0, Dracylic acid, benzenecarboxylic acid".
**THE FRAME ON EVERY ROW WAS ONE LINE OF CSS.** "I think properties in the
computed section do not need frames on every row... Especially having frames
for both key and val is overkill." Correct, and it was never intentional: **a
stylesheet set on a widget applies to its CHILDREN too**, so
`setStyleSheet("background: ...")` on a card painted every label inside it as
its own little box. `QFrame#propcard { ... }` confines it to the card. One
frame per property, one per computed group, and the producer stated once
BELOW its table ("Have the sources also below the groups of keyvals not
above").
**SELECTABLE TEXT HAS TO SAY IT IS SELECTABLE.** "I do not like programs that
do not allow me to copy paste the text that is shown in them. Even worse: You
can, but there is no highlighting informing you that you can." Every label
goes through `_selectable`, which sets the flags AND the I-BEAM CURSOR -
that is the affordance every other program uses and it costs nothing.
**A LONG CITATION IS SHORTENED TO WHAT THE SOURCE CALLS ITSELF.** Most of
PubChem's long names carry their own acronym, so there is nothing to invent:
"Hazardous Substances Data Bank (HSDB)" -> HSDB, "ILO-WHO International
Chemical Safety Cards (ICSCs)" -> ICSCs. The ones without an acronym introduce
themselves before a comma - "Haz-Map, Information on Hazardous Chemicals and
Occupational Diseases" -> Haz-Map. A name that is already short is left alone,
and the full name plus the URL is the tooltip.
**AND A LAYOUT FIX THAT UNDID ITSELF.** Round 90c used
`QLayout.SetMinimumSize` to stop cards being squashed - and that makes a card
as wide as its widest child's minimum, so a long value pushed the card past
the dock and the text CLIPPED instead of wrapping. Both problems are the same
one: a word-wrapped QLabel's height depends on its width and nothing in the
chain propagates `heightForWidth`. The fix that solves both is to let the
label SHRINK (`setMinimumWidth(1)` plus a `Minimum` vertical policy) rather
than to force the layout to grow: `_wrapped()`. Verified by rendering the page
at 380 px and reading it.
Values within a property are separated by a hairline instead of a box apiece,
which is the "vertical dashes for separation in between them" reading that
seemed most defensible - one card per property, and a rule between one reading
and the next.
1860 tests.

Round 90c (2026-08-26, the page follows the molecule, the sources become
links, and a five-round-old outline regression - Christian's second batch):
**(1) "FETCHED DATA IS NOT PERSISTENT AND PER-MOLECULE" - and the data was
never the problem.** It rides `Structure.metadata`, so it survives switching
molecules AND the savefile; both are pinned by tests now. What did not follow
was the PAGE. `page_sync_hooks` ran from `_sync_all` alone, which covers
imports and scene changes and NOT selection - so clicking another molecule
left the properties tab describing the previous one, and its Fetch button
acting on the previous one, which looks exactly like data that was lost.
**That is round 51's bug reintroduced inside the hook built to prevent round
51's bug**, and the reason is that MoloM has FOUR paths that change the active
object and each re-syncs its panels by hand: `_sync_all`, `_on_obj_activated`
(outliner row), `_on_outliner_atoms` and `_on_selection_changed` (viewport
pick). `_sync_addon_pages()` is now called from all four. His inference that
"this probably also means the data does not ride the save file" was the one
part that was wrong, and worth saying plainly.
**(2) EVERY VALUE IS STORED NOW, so "+N more" EXPANDS instead of taunting.**
He is right that knowing there is more and having no way to it is worse than
not being told. Keeping them beats being able to re-fetch them: it works
offline, costs no round trip, and the spread is the entire reason the
citations exist. `MAX_VALUES` 3 -> 8 (aspirin's worst heading has seven) with
`PREVIEW_VALUES = 3` as a DISPLAY choice, and "Show all 7 values" is a
hover-highlighted clickable label. `extra` now means what it says - the record
had more than we keep - and is rare rather than routine.
**(3) A SOURCE IS A LINK.** Every PubChem reference carries a real `URL` to
the record the value came from (the CAMEO datasheet, the HMDB entry, the NIOSH
pocket guide), so the citation is clickable, on its own line, at 10 px.
Stored ONCE per record as `{name: url}` rather than on every value - PubChem's
own payload is built that way and for the same reason: a dozen sources across
fifty values would otherwise repeat a 60-character URL fifty times. **Only
http(s) is kept**, because these strings come from a web service and end up in
something the user clicks.
**(4) COMPUTED VALUES GROUP BY THE PROGRAM THAT MADE THEM.** His words: "If
everything is basically calculated by cactvs 3... then there should be a table
that just says something like: Simple Computed Properties (Cactvs v. ...) and
then list all of them." So the computed half is grouped by `Property.
producer()` and drawn as a two-column table under one citation - four groups
on aspirin (PubChem 2.2, XLogP3 3.0, Cactvs 3.4.8.18, PubChem) instead of
twelve rows each repeating a 50-character string. A property whose values
DISAGREE about their source correctly reports no producer and keeps its
per-value citations, which is what every measured property does.
**AND THE CARDS EXPOSED TWO REAL QT TRAPS.** `_clear_rows` used
`deleteLater()` alone, so the old rows stayed children of the page and went on
painting at their old geometry over the new ones until the event loop got
round to them - a ghost of the previous layout on every expand. `setParent
(None)` first. And **a wrapped QLabel has a height that depends on its width
while a QFrame does not propagate `heightForWidth`**, so a card full of
wrapped labels could be handed less height than its contents need and drew
them on top of one another - invisible until a property was expanded to seven
values with seven citations under them. `QLayout.SetMinimumSize` on the card's
own layout makes the frame refuse to be squashed.
**(5) THE ORANGE OUTLINE WAS MISSING ON DOUBLE AND TRIPLE BONDS, and the
regression is ROUND 35'S.** `_selection_hull` drew ONE cylinder on the bond
AXIS at `bond_radius + width`. That is right only for a single bond: a double
is drawn as two cylinders offset by +-1.0*r at radius **1.3*r**, so the pair
overlaps the axis and swallows the hull whole; a triple's central cylinder is
radius r and leaves the hull poking out by the outline width alone. It was
survivable while the outline was five times fatter - and round 35 divided
`_OUTLINE_WIDTH_FRAC` by five for a good reason (the outline was merging
cubane's carbons into one orange blob), which is what sank the hull inside the
bond it was outlining. Five rounds later it is fixed by the rule this project
keeps reaching for: the hull is built from the SAME `style.bond_cylinders`
decomposition the scene draws, each cylinder fattened by the width, so the two
cannot drift apart again. Verified in a real window on ethene, not just in the
arithmetic.
1850 tests.

Round 90b (2026-08-26, the properties tab said "no properties" about an entry
full of them - Christian's report):
He opened Cassipourine (CID 101821144), which has a PubChem page with data on
it, and got "PubChem has no experimental properties for CID 101821144". His
own diagnosis was right and is the fix: **"Are the displayed properties
irrelevant to the currently picked ones? Because all of them seem to be
computed on pubchem."**
**A COMPOUND CAN HAVE COMPUTED PROPERTIES AND NO MEASURED ONES, and round 90
only ever asked for the measured half.** Measured: that CID answers
`PUGVIEW.NotFound` with a 404 for `Experimental Properties` and returns a
full **16 kB Computed Properties section**. So the add-on asked one of the
two questions and reported the answer as though it were both. A natural
product with little literature behind it is the ORDINARY case here rather
than a corner one, which is what makes this worse than it looks - the tab
would have been empty for most of what is not a bulk chemical.
**BOTH SECTIONS ARE FETCHED NOW, AND THEY ARE KEPT APART.** A computed logP
and a measured melting point are different KINDS of claim, so `Property`
carries a `kind`, the record groups measured first and computed second, and
the page heads them separately ("COMPUTED BY PUBCHEM - derived from the
structure, not measured"). Running them together would have been the quiet
kind of dishonesty this page exists to avoid. Schema version 2; a version-1
record still reads, and its properties are `KIND_MEASURED`, because
everything in one was.
**THE CITATION FOR A COMPUTED VALUE IS A DIFFERENT FIELD FROM THE MEASURED
ONE.** PubChem's reference table calls every computed value "PubChem", which
is true and useless - it would be the same word on every row. The Information
block's own citation says **"Computed by XLogP3 3.0 (PubChem release
2025.04.14)"**, i.e. WHICH MODEL produced the number, and for a value nobody
measured that is the whole of what a citation is for. So `_source_for` takes
the kind and prefers the opposite field for each: the table's short
`SourceName` for a measurement ("CAMEO Chemicals"), the free-text citation
for a computed value.
**AND THAT ONE WAS FOUND BY PHOTOGRAPHING THE PAGE, NOT BY A TEST.** The
first computed fixture was captured WITHOUT its `Reference` table, so
`_source_for` fell through to the Information citation and the test asserting
"Computed by" passed - on a payload the service does not actually send. The
real page rendered `[PubChem]` twelve times. Re-captured with the table, the
test failed exactly as it should have, and then the fix made it pass.
**A fixture pruned of a field the code branches on is not a capture of the
service, it is a capture of what you expected.**
**A UNIT IS A SIBLING OF THE VALUE, ON BOTH SHAPES.** PubChem writes
Molecular Weight as the STRING `"346.6"` with `Unit: g/mol`; round 90 read
the unit only off the `Number` shape, so the weight would have rendered as a
bare `346.6`. Experimental values rarely carry a `Unit` at all, which is why
it went unnoticed.
`MAX_PROPERTIES` is 32 rather than 24, because a compound with both halves
now has up to 26 headings; aspirin's full record is **4.6 kB** and
Cassipourine's **1.8 kB**, against the 1.81 MB they came from.
1835 tests.

Round 90 (2026-08-26, a name gives a LIST, and a molecule gets a properties
tab - Christian's batch, and the join key is the whole design):
He asked for Ctrl+Shift+N to work like the crystal search (multiple results,
favourites, header sorting, molecular weight), to show the skeletal structure
of the selected row, and for a properties tab on a plain molecule, as an
add-on for now. Then he asked the question that settled the architecture:
"if the tiered search quits after finding something on OPSIN, then the
fundamental structure of the search algorithm has to change? ... Or are you
using CIDs as the ground truth because they are the most reliable/universal?"
**THE ANSWER IS THAT THE JOIN KEY IS THE STRUCTURE, AND IT IS NEITHER THE
NAME NOR THE CID.** A CID is PubChem-local and is what you get AFTER the
join; a SMILES is not canonical across toolkits (RDKit and OpenBabel disagree
for the same molecule) so it cannot join two databases. An **InChIKey** is a
hash designed for exactly this, every service indexes on it, and RDKit
computes it offline. Which means **the cascade answering first is not a
problem at all**: enrichment is keyed on the structure, so it does not care
which tier found it. Nothing about `core/resolve.py` had to change.
**AND THE 404 IS A NAME-INDEX MISS, NOT MISSING DATA - measured.**
`/name/xylene/cids` and `/name/cresol/cids` both fail, and PubChem has both
compounds perfectly well: hash OPSIN's answer and ask by InChIKey and o-xylene
comes back as CID 7237 with a full record, o-cresol as CID 335, ferrocene as
CID 7611. So a search is three operations rather than one changed one -
**resolve** (name to one structure, a cascade, unchanged), **search** (name to
a candidate list, a fan-out, new), **enrich** (structure to data, keyed on the
InChIKey, new).
**A MOLECULE NAME IS NOT A CRYSTAL NAME, and the columns follow from that.**
A crystal name has many right answers (polymorphs, redeterminations); a
molecule name has ONE right structure and many candidate COMPOUNDS, so this is
a DISAMBIGUATION list. Measured: PubChem's exact-name endpoint returns exactly
one CID for benzoic acid, ferrocene, aspirin and glucose. Formula and weight
are on every row because RDKit computes both offline from the SMILES whatever
found it - and for the case the whole feature exists to fix they are useless,
since o-, m- and p-xylene share both. **That is what the picture is for.**
`core/depict.py` draws the selected row from its SMILES; PNG through RDKit's
Cairo backend rather than SVG, because Qt's svg imageformat plugin is a
deployment detail we do not control (round 62) and the failure mode is a
silently missing picture. It draws from a STRING and never from a Structure,
deliberately: laying out a depiction runs `Compute2DCoords`, which WRITES a
conformer, and taking a string makes flattening the molecule you were about to
import unrepresentable.
**THE CANDIDATE SOURCE IS AUTOCOMPLETE, AND THE OBVIOUS ALTERNATIVE IS ROUND
85'S MISTAKE.** A word-type name search returns **1064 CIDs for xylene and
3371 for glucose**, in database order, ignores `MaxRecords`, and asking for
their properties is a **414 Request-URI Too Long**. Truncating an unranked
list is exactly what COD's file-id order did to round 84. Autocomplete answers
in about a second with M-XYLENE, P-XYLENE, O-XYLENE at the top - the list a
chemist wants - and its own ordering is kept as each candidate's `rank_hint`.
**A SILENT DISAMBIGUATION IS NOW REPORTED, and it is a real bug found on the
way.** OPSIN and CACTUS both answer "xylene" with **o-xylene** and "cresol"
with **o-cresol**, with no warning of any kind. The test is not a title
mismatch - PubChem's preferred name for ferrocene is "Bis(eta-cyclopentadienyl)
iron", which is a different NAME for the same thing - it is whether the query
is a PROPER SUBSTRING of what came back, i.e. whether a locant was added.
**PUBCHEM THROTTLES AT 5 REQUESTS A SECOND AND THE FAILURE IS SILENT.**
Measured: a burst of twelve name lookups through an 8-worker pool finishes in
0.64 s and the last two come back **503, "too many requests per second"** -
after which the bulk property call that fills the list is the one refused. The
rows then appear with no name, no formula and no weight, i.e. looking exactly
like broken enrichment; and because it depends on how many suggestions came
back, **"xylene" and "aspirin" failed while "cresol" worked**. `_RateLimit` is
process-wide (three provider threads each politely under the limit still add
up to three times it) and a 503 is retried rather than dropped.
**THE LIST FILLS INCREMENTALLY AND NEVER REORDERS ITSELF.** Christian's own
design. `search(progress=)` calls back per provider with that provider's
enriched, ranked batch, and `merge_batch` folds it into what is on screen: a
row already drawn can only be FILLED IN, never moved or removed. So PubChem
arriving after OPSIN gives the existing row its real name and its CID instead
of adding a second row for the same molecule, and nothing jumps under the
hand - round 78's rule applied to a search.
**A PASTED SMILES STILL WORKS, and now does better than before.** The old
dialog accepted SMILES/InChI/CAS and a straight port would have broken that.
`search_input` handles a pasted structure with no network at all, and because
the InChIKey join then runs on it, pasting `CC(=O)Oc1ccccc1C(=O)O` now comes
back labelled **Aspirin** - which the resolver never did.
**`ui/search_table.py` IS THE EXTRACTION.** Rounds 86 and 87 built the numeric
sorting, the unknowns-sink rule, the third-click-restores-ranking cycle, the
star column and the divider for the crystal search; every bit of it was needed
again. Two copies is the drift this project keeps finding, so both dialogs now
subclass one `ResultTable`. The extraction was validated by the 33 existing
crystal-search tests, which pass unchanged apart from asking `dlg.table` for
what is now the table's business.
**AND IT TURNED UP A BUG THAT HAD BEEN SHIPPING SINCE ROUND 86.** Those tables
wrote each numeric cell's value into `Qt.EditRole` "so Qt compares it as a
number" - and then never asked Qt to compare anything, because the sorting is
driven by hand in Python off the ATTRIBUTE. That write was not merely
redundant: **a QTableWidgetItem keeps DisplayRole and EditRole in one slot**,
so it silently replaced the formatted text and the column was rendered by Qt
rather than by `cells_for`. Invisible for four rounds because a temperature
and a year are whole numbers and 293.0 renders as "293"; it showed up at once
on molecular weights, where RDKit's 106.168 sat next to PubChem's 106.16 in
the same column. Removed, and the display is `cells_for`'s again.
**THE PROPERTIES TAB, AND MELTING POINT IS NOT A NUMBER.** Measured on
PubChem: aspirin's full record is **1.81 MB**, its Experimental Properties
section **75 kB**, and its Melting Point section alone **11 kB containing
seven melting points in three unit conventions** - `275 F (NTP, 1992)`,
`138-140` with no unit at all, `135 C (rapid heating)`, `135 C`. So the page
cannot print "the melting point"; it shows up to three values, each with its
source, and says how many more there were. That is Christian's "always cites
the source of the info for every item", and with a spread like that the
citation is the only way to judge which value to believe. A real record comes
to **3.2 kB**, which is the answer to "it must not become too big": the cap is
arithmetic (`MAX_PROPERTIES` x `MAX_VALUES` x `MAX_CHARS`), not hope.
**THE FORMAT IS IN CORE AND THE FETCHING IS IN THE ADD-ON**, and that split is
not tidiness: if `molom/addons/mol_properties.py` owned the storage layout,
disabling the add-on would make saved files unreadable and no second add-on
could cooperate with the first. `core/molprops.py` owns the metadata key, the
schema version and the caps; every line that knows what PubChem is lives in
the add-on. A record written by a LATER schema version is IGNORED rather than
read optimistically - half-understanding a format is how you show somebody a
melting point that is really a flash point.
**WHAT REACHES AN .xyz IS PROVENANCE ONLY.** An xyz comment is ONE line that
every other program reads, so a few hundred characters of melting points in it
is how you break somebody else's parser. `Record.provenance()` writes name,
formula, CID, InChIKey and the retrieval date; the measured values stay in the
`.molom`, where there is room. The identity record is stored on EVERY
import-by-name whether or not the add-on is enabled - it is small, it is the
answer to "what is this and where did it come from", and it is what lets the
add-on work on a molecule imported before it was switched on.
**AN EDIT MARKS IT STALE RATHER THAN DROPPING IT**, through round 75's
existing machinery: the record attaches as `POLICY_FRAGILE`, so the object
locks, a chemistry edit flags it and an export cannot ship it silently.
Fragile and not volatile for a second reason on top of Christian's original
one - these numbers describe a COMPOUND IDENTITY rather than a conformer, so
moving the molecule cannot invalidate them while changing an element makes
them describe something else entirely.
**AND ROUND 65'S GUARD CAUGHT ME REINTRODUCING ITS OWN BUG.** Importing
`molsearch` at module scope in `app.py` pulls the resolver and so
urllib/http/email into every launch - the exact ~130 ms round 65 removed. It
is imported at its use sites now, and the source-level guard was widened to
name `molsearch` as well as `resolve`, because the same cost arrives by that
route and the test that pins one should pin both.
Verified by RUNNING it, not by assertion: "xylene" returns twelve compounds
with the three isomers first and `read 'xylene' as O-Xylene` on the ortho row;
aspirin imports with its provenance on the comment line and the add-on then
stores 11 cited properties in 3264 bytes. Both themes photographed - the
depiction swaps its ink for a dark window rather than its background, since
black-on-transparent is the same failure as no picture but harder to
diagnose. **`ResolveNameDialog` is superseded and no longer wired to
anything**; it is kept for now because its did-you-mean contract is pinned by
round 29's and round 61's tests, and it is listed in `docs/OPEN_ITEMS.md` for
deletion if nothing adopts it.
1827 tests.

Round 89 (2026-08-26, the focal length finally does something - K1 closed, and
Christian designed the fix):
He asked the question that dissolves it: "why isn't dragging the handles just
selecting a 2D window porting of the viewport though? If I change focal
length, then things should just transition to more perspective or more
orthographic... blender also has an apparent zoom in/out when changing focal
length. But that doesn't change the camera view limits. It only changes the
way the viewport looks."
**Round 88 measured the bug; round 89 is his model built.** `frame_rect` was
ANGULAR (round 58, half-height `Z*tan(fov_y/2)`) and `viewport_fov_y` divides
by that same rectangle, so `tan(fov_y/2)` cancelled and the widget field of
view was `1/zoom` - a constant 43.17 deg from 24 mm to 200 mm.
**THE FRAME IS THE FILM, DRAWN AT `zoom` PIXELS PER MM.** Both dimensions free,
each following its own sensor axis. Work the projection out from there and it
is `tan(widget_fov/2) = REFERENCE_SENSOR_MM / (2 * focal * zoom)` - **the
sensor cancels**, so a handle cannot rescale the scene and the focal length is
the only thing that can. Both of his requirements at once, and neither
arranged: they fall out of drawing the film at a fixed scale. Measured
end to end: 24 mm -> 200 mm is **8.33x** magnification with the frame pixel-
identical, and `proj[1][1]` goes 1.64 -> 9.20 across 24-135 mm.
**A SENSOR PER AXIS is what makes "a handle moves only its border" true.**
With one horizontal sensor and a derived aspect, a side drag changed the
aspect, the aspect divided the sensor to give `fov_y`, and the vertical
framing moved with it - so round 58 could not have both properties however it
was written. `sensor_w`/`sensor_h`, with the aspect DERIVED, is Blender's own
model (`sensor_fit` + `sensor_width`/`sensor_height`) and the export now hands
both over with `sensor_fit = "AUTO"`. Round 57's "the other axis holds to a
tenth of a percent, because a resolution is whole pixels" is gone with it:
a horizontal drag does not touch `sensor_h` at all, so it holds EXACTLY.
**Two consequences worth knowing.** `set_resolution` exists because the shape
now comes from the FILM - typing 500x1000 into the properties page had to
reshape the film too, or it would have changed the pixel count of the same
picture. And a savefile written before this round carries one horizontal
`sensor_mm` with the aspect in the PIXELS, so `from_dict` migrates it as
`sensor_h = sensor_mm / aspect`; pinned to 1e-12 on three cameras, because
reading it any other way silently re-frames every saved shot.
**AND A THIRD FAULTY MEASURING INSTRUMENT IN ONE SESSION.** The real-window
check counted "molecule pixels" and reported a constant 876 px while the FOV
was plainly changing - it was measuring something that fills the window and
clips, so max-minus-min saturates. `proj[1][1]` settled it in one line, and
two saved frames confirmed it by eye. Round 86 counted the floor grid's axes,
round 86 again counted red oxygens as red rods, and this one counted the
window. **A pixel counter over a whole frame is almost always measuring
something else; measure the quantity, not the picture.**
1781 tests.

Round 88 (2026-08-25, one dialog owns the image export - and the focal length
does nothing, measured):
Christian, after using round 86's cell-box z-order: "does it matter whether I
render from a certain camera or through repeated F12 whether or not the unit
cell lines will be rendered on top or behind... I am also getting confused by
the re-rendering/settings dialogue. I don't think it shows the entire image
export settings dialogue where everything can be set. Like in GIMP I mean."
**HIS CONFUSION WAS STRUCTURAL, NOT A MISUNDERSTANDING.** Exporting a still
had **no dialog at all** - `on_export_image` was a bare `QFileDialog` - while
every option that decides what comes out lived somewhere else: the resolution
multiplier, the mesh subdivision and crop-to-content in **App > Settings**,
several tabs from the thing they affect, and the unit-cell z-order only behind
an F3 operator. So the export asked one question and silently obeyed four
answers given elsewhere, one of which (the z-order) DELIBERATELY differs from
what the viewport is showing. There is no way to use that and stay sure what
made a difference.
`ImageExportDialog` carries all of it - file, numbering, resolution with the
**pixel size computed live** (a multiplier is abstract; a pixel count is what
you check before pressing Export), crop and its margin, transparency, atom
labels, mesh detail and the cell-box z-order - and `_write_still` is the ONE
place a still is produced, so the first export and every later F12 cannot
differ. Reachable exactly where he asked: **File > Export image...,
Ctrl+Shift+E, and F3**, all of which already pointed at `on_export_image`.
**A transparent JPEG is warned about on the spot**, because JPEG has no alpha
and the failure is a black background you only see after opening the file.
**AND `on_render_settings` WAS THROWING THE SETTINGS AWAY.** The one route
whose entire purpose is "let me change something" popped the remembered target
before reopening the dialog - and both export dialogs read that memory to open
on your last choices (round 61). So asking for the settings reset them. It
does not clear anything now; nothing needs clearing, since both exports always
ask.
**THE CAMERA-VS-F12 QUESTION HAS A MEASURED ANSWER: NO.** Rendering the
vendored solid solution free-view and through a camera hides **60% and 61%**
of the cell box respectively, and both still paths went through the same
`render_image`. What differs is the VIEWPORT (overlay, by round 86's default)
against the EXPORT (depth) - so what he saw on screen was never what the file
had, which is exactly the kind of thing the scattered settings made impossible
to pin down. The dialog now states it per export. **The one real way they
could diverge is the fallback**: `except Exception -> grabFramebuffer()` hands
back a VIEWPORT grab, which obeys `cell_zorder` and not `cell_zorder_export`.
That is now said out loud in the status message rather than left to be
discovered.
**AND A THIRD THING HE FOUND, WHICH IS A REAL BUG AND IS NOT FIXED HERE: the
focal length does nothing.** Measured on ferrocene through a camera:
`cam.fov_y` moves correctly with the lens (84.86 deg at 24 mm to 12.52 deg at
200 mm) and the **widget field of view stays at 43.17 deg throughout**. The
algebra says why in one line, and it is round 58's own model taken one step
too far. `frame_rect` is ANGULAR - half-height `Z*tan(fov_y/2)` - and
`viewport_fov_y` then divides by that same rectangle, so
`tan(cam_fov_y/2)` **cancels exactly** and the widget FOV depends only on
`zoom`. Round 58 made the frame angular so that dragging a BORDER could not
rescale the scene, which was right; the side effect is that the LENS cannot
rescale it either. What magnification you do see is the render cropping to a
frame that grew, and it saturates - 135 mm and 200 mm give an identical
528 px span. Recorded as **K1**; fixing it is a redesign of the frame model,
because "a handle drag must not rescale" and "a lens change must rescale" pull
against each other through the aspect.
1765 tests.

Round 87 (2026-08-25, the asymmetric unit gets its pie sphere - open item A4
closed - and favourites in the crystal search):
**A4 WAS BLOCKED ON A DATA-LOSS HAZARD, NOT ON DIFFICULTY, and Christian's
decision was to remove the hazard rather than work around it.** The full cell
has drawn a shared site as one pie sphere since round 42, because `expand`'s
minimum-image merge collapses the co-located rows; the ASYMMETRIC UNIT listed
them verbatim and drew four atoms stacked inside one another. Same structure,
two pictures - and the one that looked broken was the one that had not lost
anything.
Merging for display is six lines (`cif.asym_view`). What made it dangerous is
`sync_asymmetric_unit`: it writes the DRAWN atoms straight into
`asym_symbols` and resets any parallel column whose length no longer matches,
so a merged view would go from five `_atom_site_` rows to two and write
`asym_occupancy = [1.0, 1.0]` - permanently reducing Nb/Ti/Ni/Co to the pure
NbO2 that round 42 exists to stop MoloM drawing. He chose merge-AND-fix over
the two cheap alternatives (lock the view, or leave it).
**`asym_rows` is what makes it safe**: one entry per drawn atom holding the
rows it stands for, `[[0,1,2,3],[4]]` for the solid solution. The write-back
walks it and gives every row of a site the drawn atom's new position while
keeping its own element and occupancy. **The lead row is stored FIRST**,
because the drawn atom carries the majority species and the write-back has to
know which row that element belongs to.
**THREE THINGS THIS BROKE, and two of them were mine.**
(1) **The reset loop measured the columns against the DRAWN ATOM COUNT.** With
five rows behind two atoms it found 5 != 2 and reset `asym_occupancy` to
`[1.0, 1.0]` - flattening the composition immediately after the write-back had
rebuilt it correctly. The columns describe `_atom_site_` ROWS, so they are
measured against `asym_symbols`; identical in the ordinary case, where one
atom is one row.
(2) **Every element edit in the asymmetric unit was silently discarded**,
because the first cut restored the stored symbol unconditionally. Caught by a
ROUND-51 test rather than by anything new - `_change_element` on an oxygen
then switching to the full cell, and the N was gone. That is round 43e's bug
reintroduced from a new direction. The drawn symbol now wins on the row it
represents; on a merged site it re-labels the majority species and leaves the
others and every occupancy alone, so nothing is lost either way.
(3) **A float round trip moved an atom off its special position.** The
write-back converts Cartesian back to fractional, and an atom at exactly 0
comes back as **-9.45e-17**. The SIGN is the damage: a tiny negative fraction
is on the far face, so the next expansion gives that site an extra boundary
copy and the cell came back as 22 atoms instead of 21 - a structure changed by
floating-point noise. `_snap_fractional` rounds to nine decimals (five is what
a CIF writes; a 0.3 A drag in a 10 A cell is 0.03, seven orders above the
snap) and the `+ 0.0` that turns -0.0 back into 0.0 is the entire point. Round
45b hit the same `-0.0` in the symmetry operators. **Pre-existing**, and only
visible once something did an asym -> edit -> cell round trip.
**FAVOURITES IN THE CRYSTAL SEARCH**, Christian's side request: "do not save
the cifs locally, just have the links to them stay persistent". So a favourite
is `Hit.to_dict()` - provider, reference and the fields needed to draw the row
- and never the file, which means it cannot go stale against COD the way a
private copy would, and a hundred of them cost a few kilobytes of settings.
Identity is `(source, ref)` and never the formula or the name, because a dozen
determinations of quartz share both and COD leaves most entries unnamed
(round 85). They show on their own when the window opens with nothing
remembered, and after a search they sit BELOW a full-width rule drawn exactly
as the F3 palette draws its category headers - `Qt.NoItemFlags`, so it cannot
be selected or imported. **A favourite the search FOUND is not repeated**: it
stays in the results with its star ticked, because showing it twice would make
one structure look like two and the copy in the results is the one carrying
its rank.
**The star column shifted every other column by one and broke six tests** that
had the old numbers written into them. The numbers live on the dialog now
(`COL_FORMULA`, `COL_TEMPERATURE`, ...) and the tests ask by meaning - round
71's lesson, that a test pinning a POSITION breaks when nothing behaved
differently.
1758 tests.

Round 86 (2026-08-25, the outliner learns what a SITE is, the search
remembers, and the cell box stops lying about what is in front):
Christian's batch, four things, and the outliner one is a crystallographic
argument rather than a convenience.
**(1) AN ELEMENT IS NOT A TYPE.** "The outliner does not allow to toggle
equivalent atoms as a group. Right now the hierarchy is just mol > element >
individual atoms... Let's say I want to hide all oxygen atoms of a specific
type. I can't do that efficiently." He is right, and the missing tier already
had its data: a cell draws one asymmetric-unit SITE over and over, and
`packing.pack` has recorded which site each drawn atom is an image of since
round 42 (`site_of`). So `occupancy.site_groups` turns that map into a
partition and the tree grows **mol > element > site > atom**, the site named
by the file's own `_atom_site_label`. Ferrocene's hundred carbons are five
rows of twenty - `C(11)` .. `C(15)` - and hiding one kind of oxygen is one
click. **The tier appears only where there is more than one site**: one site
is not a grouping, it is the same list one click deeper, and a molecule has
no sites at all, so both fall through to the flat tree that was there before.
Atoms added by an EDIT are images of nothing and are grouped separately as
"(added since)" rather than filed under a site they have no relation to.
**(2) THE ROWS WERE BUILT ONCE AND NEVER GIVEN BACK**, which is the whole of
"expanding element lists with lots of entries takes a lot of time" - and his
guess at the mechanism was half right. Measured before anything was changed:
opening a 300-atom element group took **473 ms**, and it left 300 live
`RowControls` behind forever, because collapsing removed nothing.
`refresh_row_controls` walks every live control on every colour, label or
visibility change, so ONE look inside that group went on costing **190 ms per
click for the rest of the session**, on rows nobody could see. Two fixes.
Collapsing now frees the rows (and puts the placeholder child back - a
QTreeWidget draws no expander arrow on an item with no children, so an emptied
group would look like a leaf and could never be reopened). And **`RowControls`
is ONE painted widget instead of five QToolButtons**: the squares were never
anything but fixed rectangles with a letter in them, and hit-testing five
rectangles is the one line that replaces seven widgets a row. Measured OFFSCREEN, 300
atoms: expand 473 -> 73 ms, refresh 190 -> 4.2 ms, and after a collapse 0.4 ms.
**Those numbers understate the expand by about 20x and the checklist run
caught it**: in a REAL SHOWN window the same 300 rows are **3.0 s -> 1.5 s**,
because offscreen nothing paints. Refresh is the honest win either way,
**178 -> 7 ms** in a real window. The remaining expand cost is Qt laying out
and painting a widget per row rather than the widget count - a bare QWidget
per row is 14.5 ms - so **the site tier is the real answer**, and it is a
crystal one: ferrocene's hundred carbons are five rows, not a hundred. Lesson
worth keeping: an offscreen timing is a fine A/B and a bad absolute.
**(3) THE TREE AND THE VIEWPORT DISAGREED ABOUT WHAT WAS SELECTED.** The
outliner emitted ONE atom on a click and nothing at all for a Ctrl or Shift
range, so six rows could be highlighted in the tree while the viewport showed
one atom - two selections, with the one you were looking at being the wrong
one. `atoms_selected` carries the lot now, and a row means the atoms below it
at every depth, so selecting the `C(12)` row selects all twenty of its images
and selecting `C` selects all hundred. The click handler had to be taught the
same lesson the OBJECT branch learned in round 24: Qt changes the selection on
PRESS and emits `itemClicked` on RELEASE, so emitting one atom there ran LAST
and collapsed the range back to the row clicked.
**(4) THE CELL BOX IS NOT ALWAYS IN FRONT.** "The unit cell axes are always
rendered on top in normal image exports and in the viewport. I think it
shouldn't be. At least never in png exports." An overlay has no depth, so
every edge is painted over whatever it crosses; on a packed cell the a, b and
c vectors cut visibly across every molecule they pass behind. Two F3
operators, **disambiguated as (Viewport) and (Image export)** because the
choice is genuinely made twice - on screen the box is partly a navigation aid
and an edge vanishing into the framework is a real loss, while an export has
to be true. **The viewport keeps the overlay and the export defaults to
depth**, which is what he asked for. The depth form is `core/cellbox.py`: one
thin ROD per edge, drawn in the ordinary opaque pass, so the occlusion is what
a depth buffer does for free. Rods rather than GL lines because `glLineWidth`
> 1 is invalid in a core profile (round 48), and rods are what VESTA and the
Blender export already draw - the radius is 0.4% of the cell's mean edge, so
it reads the same on a 3 A cell and a 200 A framework, and a 10 A cell lands
on exactly the 0.04 the Blender export already defaulted to.
**THE INSTANCE COLOUR IS RGBA AND I UPLOADED RGB**, which is worth recording
because of how it presented. The instance attribute layout is 16 matrix floats
plus a vec4 (`istride = 20 * 4`), so a three-float colour shifts every instance
after the first by one float and the whole buffer is read as garbage. It does
not draw as a wrong-coloured cell box; it draws as **enormous white triangles
across the entire frame** - Christian saw the screenshot before I did and said
"my god the image is completely screwed". Nothing raised, and every offline
test passed.
**AND THE VERIFICATION WAS WRONG TWICE BEFORE IT WAS RIGHT**, which is the
more useful lesson. The claim is OCCLUSION, and the first check counted
"axis-coloured pixels" in the two modes - that measures the rod's THICKNESS
(a rod is fatter than a 1.2 px pen, so depth mode had MORE of them) and, worse,
counted the floor grid's own red and green axis lines. The second counted
axis-coloured pixels lying on the structure - which counts the red oxygens and
the green occupancy wedges, because a red rod and a red oxygen are the same
pixel. The right measurement is COLOUR-AGNOSTIC and needs three frames: no
box, box on top, box in depth. A pixel where the overlay differs from the
no-box frame is one the box painted; if the depth frame AGREES with the no-box
frame there, the depth test refused to paint it. **54.5% of the box is behind
the structure** on the vendored solid solution, and the rest still draws. That
check is in `tools/smoke_gui.py`, because `render_image` builds an FBO and
cannot be reached from pytest at all (round 60).
**(5) THE CRYSTAL SEARCH REMEMBERS AND SORTS** - `docs/OPEN_ITEMS.md` section
I, which was his own list after round 85. The query and its hits are restored
when the dialog reopens **without re-running the search** (three network round
trips to redisplay what was on the screen a moment ago, and it could answer
differently), and a result older than a minute or two **says how old it is**,
because a stale list that looks live is worse than an empty one. Sorting is
driven by hand rather than by `setSortingEnabled(True)`, and the trap the open
item warned about was real: `QTableWidgetItem` compares LEXICALLY, so
temperature and year carry their value in `Qt.EditRole` for Qt to compare as
numbers, blanks sink to the bottom whichever way the column points (an unknown
temperature is not 0 K, and a plain `reverse=True` floats them to the top),
and a **third click returns to the search ranking** - which Qt's own sorting
has no way back to, and the ranking is the one thing the search itself is for.
The memory lives on `MainWindow`, not in a module global, so a second window
cannot inherit it.
**(6) THE SUITE COULD NOT BE RUN AS ONE PROCESS, and fixing it turned up a
real bug in the app.** `python -m pytest tests/` crawled from ~75% and never
finished, appearing to HANG in a different test each time - the most
misleading shape a problem can take - and it was NOT round 86's doing
(verified by stashing every change and reproducing it). Two causes.
**(a) Nothing tore the windows down**: each `MainWindow` leaves 17 top-level
widgets and 413 widgets, +340 / +8260 over twenty, until the process is
thrashing at 2.8 GB. **The obvious fix looks like it does nothing** -
`close()` + `deleteLater()` + `processEvents()` frees exactly as much as no
teardown at all, which sends you hunting a leak that is not there. The reason
is one line of Qt: **`processEvents()` does not dispatch DeferredDelete.**
`sendPostedEvents(None, QEvent.DeferredDelete)` does, and then the ordinary
idiom frees all of it - **+0 and +0 over 40 shown windows**. (`shiboken6.
delete` also frees it and must NOT be used: a QMenu is a top-level widget, its
parent's destruction has already freed it, `isValid` still reports it live,
and touching one is an access violation.)
**(b) A worker QThread was a CHILD of the dialog that started it**, so
destroying the dialog destroyed a RUNNING thread. That is the app's bug rather
than the suite's - start a name lookup that has to wait out the web timeout
and press Cancel - and it is why the suite then died silently at exit 127,
with no Python traceback and nothing from `PYTHONFAULTHANDLER`, in
`test_round29_fixes.py`: its did-you-mean test clicks a suggestion, which
kicks off a resolve, which was still in flight when the window was destroyed.
Found by bisecting to the ONE test that crashed alone, then to one line of it.
Workers are unparented now and held in `dialogs._LIVE_WORKERS` - un-parenting
alone would leave `self._worker` as the only reference, which dies with the
dialog, and Python is then free to collect a QThread mid-run, which is round
76's trap from the other side. `wait_for_workers()` runs from the test
teardown and from `__main__` before the process exits, because a thread
outliving the DIALOG is correct while one outliving the PROCESS is the same
crash from the other end.
**(7) rdkit AND openbabel ARE BASE DEPENDENCIES NOW**, which came out of
Christian asking why they were an extra at all. Measured rather than argued,
and the numbers are one-sided: a base install read **2 of the 13 formats the
Open dialog advertises** — xyz and cif/mmcif have native readers, while pdb,
mol, mol2, sdf, cml, gro, hin, gzmat, pdbqt and mdl all failed outright *and
were still listed in the file filter*, so the user picked "PDB" and got an
error. It also had no SMILES anywhere (paste, Ctrl+N, import-by-name), no
working Optimize panel, and `resolve.classify` fell back to "assume any
single word is a SMILES", so Ctrl+Shift+N on "ethanol" never reached OPSIN.
Against that: **43.5 MB** (rdkit 26.7 + openbabel 16.8) on top of the
**665 MB** of PySide6 that is already mandatory, i.e. about 6%. The one real
counter-argument was wheel coverage, and it does not hold: both publish for
Linux x86_64/aarch64, Windows and macOS arm64 across cp310-cp314, openbabel
also for Intel macOS and cp38/cp39. The `chem` extra is kept as an alias so
existing install commands do not warn. **A measurement worth not repeating
wrong**: blocking the imports in-process is NOT a base install, because
`_obabel_worker` is a SUBPROCESS and imports OpenBabel itself — the first
sweep reported pdb and mol reading fine when OpenBabel had simply read them
in a child. Patch `io._read_with_openbabel` instead.
**`python -m pytest tests/` is 1732 passed, 4 skipped in ~110 s again.**
1740 tests.

Round 85 (2026-08-25, the search finds the PURE compound - Christian's first
real use of it):
"Searching for the typical acids I use (benzoic acid, nicotinic acid,
terephthalic acid) and even simple stuff like DMSO never show a hit for the
pure chemical. It is always some derivative or co-crystallized stuff. Also, I
think I never get other sources than COD."
**(1) COD'S NAMES CANNOT FIND A PURE COMPOUND, and the numbers are stark.** A
text search for "benzoic acid" returns **2617 rows**, of which exactly ONE has
`chemname` equal to "benzoic acid" - and the pure compound's own entries are
spelled **"benzioc acid"** with `chemname` null. So every hit was a derivative
or a co-crystal whose name happened to contain the phrase, and round 84's
parse ceiling was reading 500 of those 2617 in COD's file-id order.
**The fix is a formula, because a formula is not a spelling and cannot be
mistyped into invisibility.** `resolve_formula` puts the query through
`core/resolve.py` - OPSIN, PubChem, CACTUS, the same cascade Ctrl+Shift+N uses
- and COD is then asked by formula AND by text, because the two answer
different questions (the formula finds the pure compound; the text index finds
the mineral names and co-crystals a formula cannot express). "Benzoic acid"
and "Dimethyl sulfoxide" come up first now, and "quartz" resolves to O2Si as a
bonus.
**(2) "DMSO" WAS A SEPARATE BUG AND A GOOD ONE.** `formula_key("DMSO")` split
it into D, M, S, O - all of which LOOK like element symbols, two of which are
not - so it parsed as a formula, the resolver was never consulted, and COD was
asked for a compound of deuterium and "M". That is why "DMSO" found NOTHING
while "dimethylsulfoxide" found co-crystals. Every token is checked against
the element table now.
**(3) AND A RANKING BUG THAT MADE TEREPHTHALIC AND NICOTINIC ACID UNFINDABLE
EVEN BY FORMULA.** COD leaves many entries unnamed - 5 of its 7 C6H5NO2 rows
have no name at all - and the scoring rewarded weak name similarity, so a
WRONGLY named isomer ("2-pyridinecarboxylic acid", fuzzy 0.5) outranked an
unnamed entry that was probably the compound wanted. The rule now: **a name
that matches is evidence FOR, a name that clearly denotes something else is
evidence AGAINST, and an ABSENT name is neither.** Unnamed sits between the
two at 0.95.
**Verified structurally rather than assumed**: the top unnamed C8H6O4 hit was
fetched and its connectivity perceived - all eight carbons 3-coordinate, an
aromatic ring plus two carboxyls, i.e. **COD 4130843 IS terephthalic acid**,
unnamed in COD's own index and now ranked first. The bicyclic anhydride it was
losing to would have sp3 carbons.
**(4) "NEVER OTHER SOURCES THAN COD" HAS AN HONEST HALF AND A FIXABLE HALF.**
The fixable half: OPTIMADE only accepts a FORMULA - the standard describes
structures, not literature - so a NAME query never reached it at all;
resolving names fixes that, and DMSO now returns an OQMD hit. The honest half:
MP and OQMD are inorganic/materials DFT databases, measured at **0 hits for
C7H6O2 and 1 for C2H6OS against 50 for SiO2 and 94 for TiO2**. For molecular
organic crystals they have essentially nothing, and that is what they ARE
rather than a fault. COD is the free source for organics; the CSD is where
they properly live and it is licensed with no free API.
**A mistake of my own, caught by a test I had already written**: round 84 put
`dedupe` inside the COD provider, where it can collapse two differently-named
entries that merely share a cell - and it cost the correctly-named one.
Deduping belongs at the top level, across providers, which is where it was.
**Christian's verdict after using it: "search for crystals is very nice now.
only thing it really needs is to remember the results of the last search and
sorting via clicking on the headers (like by temperature and year, ascending
and descending)."** Both are recorded as **section I of
`docs/OPEN_ITEMS.md`** and are the next thing to pick up. The header-sorting
one has a trap worth reading before starting it: `QTableWidgetItem` compares
LEXICALLY, so `setSortingEnabled(True)` alone would order 100 K before 98 K
and sort COD's constant null temperatures and years as text.
1700 tests.

Round 84 (2026-08-24, finding a crystal without leaving MoloM -
`core/cifsearch.py`, Ctrl+Shift+Alt+N):
Christian: "Searching the COD by hand is a pain... a tiered search algorithm
that doesn't die or stall if a single tier doesn't work right away and that
allows for fuzzy string matching and selection of multiple options found."
**A CRYSTAL SEARCH IS NOT A NAME RESOLUTION, and that is the whole design.**
`core/resolve.py` turns a molecule's name into ONE structure, so its tiers are
a CASCADE: the first that answers wins. A crystal name maps to MANY - a dozen
determinations of quartz, polymorphs, temperatures, redeterminations - so the
question is not "which service knows this?" but "show me the candidates". The
tiers therefore run CONCURRENTLY and their results are merged, deduped and
ranked here rather than by the providers, who disagree about what matching
means and half of whom do not fuzzy-match at all.
**CALLING THEM FOR REAL FOUND FIVE BUGS, and not one was findable by reading.**
This is round 37's and round 73's rule paying out again.
(1) **COD writes its formulae as `- O2 Si -`.** The leading dash made
`formula_key` bail, so every COD hit scored as a NAME match rather than as the
exact chemical identity it is. (2) **Materials Project's
`chemical_formula_descriptive` is the whole CELL's** - `O96Si48` for a silica -
so it never canonicalised to the query, every MP hit fell below `MIN_SCORE`,
and the tier returned nothing while saying nothing. (3) **COD's own OPTIMADE
endpoint answers 501**, so listing it - which was the plan, and Christian's -
would have put a guaranteed failure line in every single search. Removing it
changes the story honestly: **OPTIMADE is the COMPUTED tier and COD is the
EXPERIMENTAL one**, so a hit carries `computed` and the dialog says "(calc)",
because a DFT-relaxed cell is not a measurement. (4) **A substring test scored
"Ferrocenecarboxylic anhydride" exactly as highly as a file called
ferrocene**, both containing the query; the discriminator is whether the query
is a whole WORD. (5) Found by measuring rather than calling: **COD returns its
rows in file-id order**, and parsing 60 of 247 before ranking picked the
shortlist at random - ranking first moved "quartz" from `Quartz low` (1939) to
an exact `Quartz` (2008).
**OPTIMADE SERVES JSON, NOT CIF**, so without `optimade_cif` the computed tier
could be searched and not imported - half a feature. It writes a minimal P1
CIF (P1 because OPTIMADE gives the whole cell contents, so claiming any other
group would be inventing symmetry - round 52), which means all three tiers
hand MoloM the same thing and there is ONE import path. Verified by parsing
the output with MoloM's own reader: an MP silica round-trips to 144 sites.
**A download takes the SAME path a file on disk does** - written to a temp
file and opened - so the packed import, the disorder policy, the symmetry
derivation and every report ride along. A second, subtly different import path
for downloaded structures is exactly the drift this project keeps finding. The
temp file goes in a temp DIRECTORY with a real name in it, because the import
names an object after its file and `mkstemp` put `molom_d2dtna96` in the
outliner.
**The local tier is blank by default and stays blank**: there is no sensible
guess at where somebody keeps their CIFs and a wrong default would silently
search the wrong tree. Settable from F3 and from App > Settings, both.
41 tests, every one OFFLINE through an injectable `fetch` - but every payload
in them captured from the live services rather than written from memory.

Round 83 (2026-08-24, the occupancy pie spheres - open item A4, and it was
ONE bug wearing a disguise):
Christian: "Pie occupation spheres still only work for certain sites. They are
completely omitted in the asymmetric unit for cif: 1547149.cif."
**The composition map is keyed by DRAWN atom index and `packing.pack` has
always built it correctly** - all ten of `1547149.cif`'s Nb, every time. Two
callers then overwrote it with the map from `expand(boundary=False)`, whose
keys are CONTENT indices: `io.py` at import and `cif.build_view` on every
rebuild. That does not merely lose the boundary copies, **it changes what the
keys MEAN** - and because a content atom is its own first image, the two maps
AGREE on the first atoms of the cell. Hence 2 of 10 Nb drawn with a
composition and 8 plain, with no visible pattern, which is exactly what "only
works for certain sites" looks like from the outside.
**The same overwrite left `site_of` holding 6 entries for 21 atoms**, and left
`content_of` stale across a view switch. That one is the dangerous member of
the family: `images_of` reads it to decide which atoms are copies of the site
you picked, and `on_delete_selected` deletes every image - so a stale
`content_of` deletes the WRONG ATOMS. The rebuild now drops and re-sets every
per-atom map together, which is round 80's lesson in the one place that
regenerates the atom list wholesale instead of editing it.
**THE ASYMMETRIC UNIT IS STILL OPEN, DELIBERATELY, and the reason is a data-
loss hazard rather than a difficulty.** Showing a pie there means merging the
four rows (Nb/Ti/Ni/Co at one position) into one atom, as the cell does. But
`sync_asymmetric_unit` writes the asym view's atoms straight back into
metadata on any edit, and resets the parallel columns whenever the count
changes - so a merged view would, on the first edit, write `asym_symbols =
['Nb', 'O']` and `asym_occupancy = [1.0, 1.0]` and **permanently destroy the
solid solution**, reducing it to the pure NbO2 that round 42 existed to stop
MoloM drawing. It needs the write-back taught about shared sites first.
Christian has the decision.
1659 tests.

Round 82 (2026-08-24, an ABSOLUTE floor under a bond length - Christian's
chemistry, and the measurement that says how far it goes):
**His observation is right and the current rule was worst exactly where you
would expect.** "The only molecules that have 0.75 A or shorter bonds are H2
or exotic stuff like HeH+. After that, the next shortest bond length is HF,
meaning that there is a no-mans-land... that cleanly separates these molecular
fragments." Measured: H2 0.741, HeH+ 0.772, then **nothing until HF at
0.917** - and MoloM bonds neither of the first two (H-H is refused by
Avogadro's own rule, He is a noble gas), so under ~0.9 A nothing it would
draw is real. Nothing heavy-heavy exists below N#N at 1.098 at all.
**`IMPOSSIBLE_FACTOR` is RELATIVE, which makes it loosest precisely where
hydrogen is**: `0.65 x (r_C + r_H)` is **0.696 A** and `0.65 x (r_O + r_H)` is
**0.617**, so a badly refined C-H at 0.70 sailed straight through, while C-C
got 0.975. That is backwards - hydrogen has the fewest electrons to place it
with and had the loosest guard. `SHORTEST_REAL_BOND = 0.80` is taken as a
`max` with the relative floor: the light end is raised (C-H, O-H, N-H all to
0.80) and the heavy end is untouched (C-C 0.975, Zn-O 1.177).
**0.80 and not 0.90, and the reason is X-ray refinements.** A riding hydrogen
is routinely placed at 0.88-0.98 - `4-ABA-oxime.cif`'s own run 0.88-1.04 - so
0.90 would delete legitimate hydrogens and trade one bug for a worse one. The
usable window is 0.772 (HeH+) to 0.88 (the shortest real refined H), which is
narrower than the gas-phase gap suggests.
**WHAT IT DOES NOT DO, measured rather than assumed: it does not let
`periodic_pairs` drop its valence cap.** The reason I had given for keeping
that cap was HpPyBz's 0.75 A C...C fusing molecules, and Christian rightly
objected that the file is hand-made and unphysical. So the situation was
rebuilt - two molecules interpenetrating with a 0.75 A contact - and the
answer is that **the 0.75 contact is refused correctly and the molecules are
fused anyway, by four C-H contacts at 1.027 A**. That is an ordinary C-H bond
length; no distance rule, absolute or relative, can refuse it. Only a valence
argument can say those carbons cannot have six bonds. The short contact is a
SYMPTOM; the fusion is carried by ordinary-length bonds to atoms that are in
the wrong place. So the round-81 split stands and is now justified by
measurement rather than by an unphysical fixture: **draw what the file says,
group by what chemistry allows.**
Both vendored crystals are byte-identical before and after (ferrocene
210/300, the solid solution 21/23), because the floor only bites where a bond
is impossibly short.
1654 tests.

Round 81 (2026-08-22, open item A5 - a CIF viewer draws the FILE, on branch
`crystal-overvalence`):
**Christian settled this with an argument, not a preference, and the argument
dissolves the item rather than patching it.** "We are visualising information
that is recorded in a cif file, not the physical reality. If someone made a
shit refinement, then the cif is flawed and the visualiser should reflect
that... We should not be silently glossing over bad refinements. Just draw the
bond, even if it exceeds valence. It's a crystal structure. Due to occupancies
and disorder, that comes with the territory. And those types of over-valences
are informative because they either expose real, physical limitations, or
because they indicate bad data refinement."
He is also right about the second half, and it is the sharper point: **longest
first was always wrong for a crystal SPECIFICALLY because of hydrogen** - short
bonds, low electron count - so every real C-C is longer than every real C-H and
the cap sacrifices the skeleton to keep duplicate hydrogens. Round 41 patched
the ORDER (`_removal_order` sends a last link to the back). Round 81 removes
the question: `cif.display_bonds` passes `valence=False, cap_hydrogens=False`,
so nothing is dropped and the picture is the distance test plus the file.
**A5 was a CONSEQUENCE of dropping, which is why it dissolves.** Dropping a
BOND does not drop an ATOM, so the hydrogens on the far end of the dropped
bonds floated as unbonded spheres - 36 of them in that cell. Nothing is
dropped now, so nothing floats. Measured on a synthetic disordered methyl
(C-C 1.497, C-H 1.000, six H at 60 degrees - the numbers `4-ABA-oxime.cif`
gives, rebuilt here because that file is CCDC and cannot be vendored):
**capped, 4 edges, carbon degree 4, THREE orphan hydrogens; uncapped, 7 edges,
degree 7, none.**
**And it retires the idea I had been circling.** The geometric disorder sweep
would have been the wrong instrument anyway: an idealised staggered methyl
puts its closest H pair at **0.943 A**, outside `DISORDER_RADIUS` (0.8), so on
ideal geometry the sweep finds NOTHING and on a real file it catches only the
pairs the refinement happened to place under the threshold - which is exactly
why a naive sweep left a 2-hydrogen methyl. The right answer was never to
guess which atoms are real.
**What is deliberately NOT relaxed, and the split is round 42d's rule read
from the other side.** An impossibly short contact is still refused: that is
not a valence judgement (no chemistry puts two nuclei at half their covalent
radii) and round 43's tick already exists for looking at those. And
`periodic_pairs` keeps the cap, because it answers "what belongs TOGETHER" for
the fragment walks, the boundary completion and the percolation test - where
round 38 measured that one bad contact fusing four molecules makes a whole
cell read as a framework. So: **group by chemistry, draw by the file.**
`perceive_bonds` gained the same two flags for symmetry; its defaults are
unchanged, so a MOLECULE still gets the cap - the draw tool's C -> N dropping
an H rests on it, and a molecule being built is not a refinement.
Regression measured rather than assumed: both vendored crystals are unaffected
(ferrocene 210 atoms / 300 bonds, the solid solution 21 / 23, no unbonded atoms
either way), because the rule only bites where a file is over-valence.
1648 tests.

Round 80 (2026-08-22, open item A1 - a delete renumbers, and almost nothing
followed):
**A1 as reported was one instance of a class, and the class is what got
fixed.** `edits.delete_atoms` reindexed the BONDS and the cell reference
(round 42c) and nothing else, so every other map keyed by atom index kept its
old keys and quietly came to describe different atoms. Measured on cubane by
marking atom 15 and deleting atom 0: the meta table, the colour, the hidden
flag and the sphere scale all still said 15 while the molecule had 14 atoms.
**The reason it survived twenty rounds is that it never looks broken.** An
index map stays perfectly VALID after a renumbering - `meta.prune` was being
called and only ever caught the entries that fell off the END, which is
exactly the case that cannot happen when you delete an atom BELOW the marked
one. A test reconstructs the old behaviour to state it: prune leaves the meta
entry at index 4 in range, naming P, when it meant the S now at 3.
**Two levels, because the maps live in two places.**
`edits._remap_atom_metadata` handles what is on the STRUCTURE - the meta
table (via `meta.remap`, which had existed since round 19 and was never
called), plus `site_of`, `content_of`, `site_occupancy` and `refused_bonds`.
The keys are enumerated in one place with a note on what each would do wrong,
because the whole difficulty is that adding a new one and forgetting it is
invisible. `MolObject.remap_atoms` handles what is on the OBJECT - the seven
display maps - which `edits` cannot reach and must therefore be told about:
`delete_atoms` fills a `report` with the old-to-new mapping, the same pattern
`perceive_bonds` and `cif.expand` already use.
**`MolObject.delete_atoms` is the paired call**, and every UI call site now
goes through it. That is what makes the invariant hold rather than being
remembered: if there is an object to hand, delete through the object.
**THE SECOND RENUMBERING PATH IS `adjust_hydrogens`, and it is the one nobody
would think of.** Adding a hydrogen appends and disturbs nothing; REMOVING
one renumbers everything above it - and that is what C -> O does, and what
raising a bond order does. Measured: colouring cubane's last atom and
changing one carbon to oxygen left the colour key pointing PAST THE END of
the atom list. `report=` threads through `adjust_hydrogens` and
`set_element_adjusted`, with `MolObject` wrappers, and the eleven UI call
sites go through those.
**`MolObject.ATOM_MAPS` plus a test that compares it against every `atom_*`
field on a live object** is what stops this recurring: a new per-atom map
added beside the others fails at the line that introduced it rather than
silently going unmapped. That is the round-31 four-place checklist made
mechanical instead of remembered.
1640 tests.

Round 79 (2026-08-22, the trackpad, and one row instead of two):
**(1) THE VIEW CONTROLS BELONG ON THE TRANSPORT ROW.** Christian: "Why did you
put the view numbers and the fit button not on the same row as the playhead and
loop interval numbers? I think this also messes with the expandable transform
pane." Both halves right. They are read ALONGSIDE the frame range - the whole
point is that one says what plays and the other what is shown - and a second
bar under the rows was one more widget for the expand/collapse to fight with.
The pane's children are now the transport row, the grip and the rows, and
nothing else.
**(2) A TRACKPAD SWIPE IS NEVER PURELY ONE AXIS**, which is the whole of
"responsiveness is spotty... it works sometimes". The branch order asked `if dx
and not mods` FIRST, so a vertical flick carrying three pixels of horizontal
drift was handed to the pan branch and the zoom silently did not happen - about
as often as not, depending on the hand. The axis is chosen by which one
DOMINATES now.
**(3) AND THE ACTION IS LATCHED FOR THE GESTURE**, which is round 8's rule
("decided at gesture START, never per event") in a new place: without it a swipe
that drifts diagonally flips between panning and zooming halfway through, which
feels like the pane fighting you. `Qt.ScrollBegin`/`ScrollEnd` bound it where
the device reports them and a 0.35 s gap does where it does not. Holding a
modifier starts a NEW gesture, because that is a change of intent rather than a
wobble.
**(4) PANNING COULD NOT HAPPEN AT ALL on a device that reports horizontal
scroll as `angleDelta`.** `dx` was read from `pixelDelta` only and `dy` fell
back to `angleDelta` - so a tilt wheel, and any trackpad whose horizontal
scroll arrives as angles, gave `dx = 0` forever. That is Christian's "panning
doesn't even exist as a gesture", and it is one line: read BOTH axes from the
same source.
**(5) A wheel notch and 60 px of trackpad are now the same quantity**
(`PANE_STEP_PIXELS`, `PANE_WHEEL_UNITS`). A trackpad delivers a stream of small
deltas and a wheel one detent of 120, so a fixed per-event factor made the same
physical movement zoom by wildly different amounts on the two machines - the
other half of "spotty". The whole decision is `input_map.pane_scroll`, next to
the rest of the trackpad-vs-mouse reasoning (round 16) and testable without a
widget.
**(6) THE STRIP PAGE DID NOT FOLLOW A DRAG.** `_on_tracks_edited` refreshed the
clock and the bar and not the page, so dragging a bar left the Start box
describing where the strip used to be - Christian: "Moving the strip manually
does not seem to update the start number in the strip pane". A panel that shows
a stale number is worse than one showing nothing, because nothing about it
looks wrong.
1628 tests.

Round 78 (2026-08-21, the pane made workable, and a framerate that was a lie):
Christian used round 77 in anger. Every complaint was real and they group into
three.
**(1) THE AXIS MOVED UNDER HIS HAND, from two independent causes.** Round 77
left `play_end` following `duration` when no limit had been set, so **dragging
a strip to the right dragged Frame End with it** - and `TrackRows.set_timeline`
re-fitted the axis whenever the content outgrew the view, i.e. **on every mouse
move of that same drag**. The strips visibly compressed and the pan jumped back
to zero mid-gesture, which is his "moving a strip to the right fires the
movement reset in grab mode". Both are the same mistake in two places: a
VIEWING property being recomputed from the CONTENT. The frame range is now
fitted ONCE, the first time there is anything to play (`fit_range`, called from
`sync` only while `range_end` is None), and after that it is a fixed number
that arranging strips never touches. The axis is only ever moved by something
that means to - `fit_view`, the zoom, the pan, the View boxes. That leaves
exactly one gap, and it is closed as a deliberate action rather than a side
effect: a trajectory imported LATER sits outside the range, so the **⤢** button
beside the frame boxes re-fits it.
**(2) A STRIP START SNAPS TO A WHOLE FRAME**, and this is the "one frame too
much or too little". A strip dragged by the mouse landed on 3.7, so its last
frame fell BETWEEN two scene frames; fit a loop to that and the period is no
longer a whole number of frames, so the wrap gains or loses one. Blender's
sequencer snaps strips for the same reason, and nothing is lost because the
playhead only ever stops on whole frames.
**(3) TWO GESTURES DID NOTHING AT ALL.** `_gmove` (G) was armed by the key,
painted a cursor, and was **never read by `mouseMoveEvent`** - so the strip sat
still and the click that "confirmed" it committed a no-op. And
`mousePressEvent` returned early when `_row_at` found no row, so **clicking
below the strips left one selected**. Both were mechanisms with tests that
tested the ARITHMETIC and no test that drove the GESTURE - round 59's lesson,
which this file states and which I repeated anyway. `tests/test_round78_pane.py`
drives real QMouseEvents and QKeyEvents through the widget.
**Hotkeys are routed by focus OR THE POINTER** (`_live`). Relying on focus
alone is the other half of why G looked dead: a click selects the strip, and
anything that moves focus afterwards - the properties dock refreshing, the
viewport's own focus-follows-cursor (round 12) - leaves the pane holding a
selection it cannot act on. Blender routes a hotkey by which editor the mouse
is over, which is what a Blender user expects.
**(4) THE FRAMERATE WAS A LIE, and the arithmetic says why in one line.**
Christian counted "~2 seconds of playtime for 60 frames at 60 FPS". Playback
ran one frame per timer tick at `int(1000 / fps)` ms - **16 ms for 60 fps** -
and Windows' default timer granularity is ~15.6 ms, so a 16 ms QTimer does not
fire at 16 ms, it fires at **31.2**. Sixty frames therefore took **1.87 s**,
which is his two seconds to the tenth. The same failure arrives from the other
side the moment a repaint costs more than a frame: a per-tick scheme does not
drop frames, it SLOWS DOWN, and the number in the box stops describing
anything. So the timer is now only a wake-up (`_PLAY_TICK_MS = 4`,
`Qt.PreciseTimer`) and the STEP comes from `perf_counter`: each tick advances
by however much wall time has actually passed, carrying the remainder so the
error cannot accumulate, and drawing nothing at all when less than a frame is
due. Measured against a deliberately crippled 31.2 ms wake-up pattern: **one
60-frame loop per 1.03 s of wall time**, with 32 of the 60 frames drawn and the
rest skipped - which is what every player does and what keeps a preview and a
render of the same range the same length.
**(5) THE STRIP IS MEASURED IN SECONDS NOW.** Christian: "Change the main
strip property from frames to time. That is intuitive to a user." Frames stay
the MODEL's unit - they are what the clock counts, what the range bounds and
what a render writes - and `frames_for_seconds` is the single place the two
meet. Changing the framerate deliberately does NOT re-derive a strip's frame
count: that would renumber the whole scene under a control that says "fps", so
the duration readout moves instead, which is both honest and what Blender does.
**(6) THE PANE HAS ITS OWN BOUNDS, AND THEY ARE NOT THE PLAY RANGE.** Wheel
zooms about the cursor, Shift+wheel and a trackpad swipe pan, Ctrl+wheel
scrolls the rows, Home and a Fit button frame everything, and View [start] -
[end] states the interval exactly. Christian: "unless the pane limits can be
set, we run into the whole zooming out problem" - and he is right that this is
what turns a strip dragged far away from a dead end into an ordinary
navigation.
**(7) THE THINKING TASK: is smoothing irrelevant now? As a COUNT, entirely.**
How many pictures a strip has follows from its duration and the framerate, so
a third number could only disagree with the two that produced it - putting it
back would re-create exactly the redundancy round 77 removed. But a count was
never the only thing it could have said: what remains unspecified is whether
those pictures BLEND or STEP. Blending invents intermediate geometries;
stepping shows only the ones that were computed, which for an MD run is
sometimes precisely what you want to look at. That is a per-strip tick
(`Track.interpolated`, on by default) and it is the whole of what survives.
1622 tests.

Round 77 (2026-08-21, the player's units re-cut - and the mode loop was one
frame short the whole time):
Christian's brief: "The global settings should only be Frame Start, Frame End,
Framerate. Smoothing is a property that should be unique to a particular strip
... Just set one number of total frames inside the strip properties. User has
to adjust them until they're satisfied with the fluidity of the animation.
Default: 60 FPS, ergo 59 frames per oscillation animation." He also asked the
right question about the abstraction: a mode is GENERATED and a trajectory is
IMPORTED, so is interpolation even the same operation?
**(1) THE ANSWER IS THAT ONE NUMBER COVERS BOTH, AND THE ONLY REAL DIFFERENCE
IS WHETHER THE DATA CLOSES ON ITSELF.** A strip is now `frames` scene frames
long, and that single number is its length, its speed and its smoothness at
once - the old `speed` multiplier and the old global `smoothing` were one
degree of freedom wearing two hats, and neither told you how long the shot was
or whether the motion would look fluid. The mapping is one line with two
spans: **cyclic** data (a baked mode, where `mode_frames` samples
`sin(2*pi*k/n)` for k = 0..n-1 and deliberately omits the k = n duplicate)
divides `frames` by `n`, so the strip's last frame sits one arc short of the
start it came from; **linear** data (a trajectory, with two distinct ends)
divides `frames - 1` by `n - 1`, so the strip's last frame lands exactly ON
the last datum. The end mode (hold / loop / pingpong) is applied in the
STRIP's own frames rather than in the source's, which is what lets one rule
serve both. Interpolation is no longer a switch anywhere: it is simply what
happens when a strip is longer than its data, and `subdivision` (= the old
smoothing) is now DERIVED and shown on the page rather than set.
**(2) THE REWORK EXPOSED A BUG THAT HAS BEEN IN EVERY VIBRATION MoloM HAS EVER
ANIMATED.** The old LOOP wrapped a track at `n_frames - 1` local frames - i.e.
it assumed the last stored frame duplicated the first. A baked mode does not
store that duplicate. Measured on a 20-sample period: the animation covered
**93.3% of the oscillation and then crossed the remaining 1.33 source frames
in a single image**, a hitch once per revolution at four times the normal
step. It was invisible in any still and easy to read as "the framerate is
uneven". `interpolate.frame_pair` was the other half: it CLAMPED to [0, n-1],
so a position in the closing arc froze on the last sample instead of blending
it into the first - `cyclic=True` closes it. Both halves are pinned by
measurement rather than by index arithmetic: the wrap step must equal an
ordinary step for that part of the sine, and without the fix the last arc is
frozen and then leapt.
**(3) THE FRAME RANGE IS INCLUSIVE, which is where "subtract the last frame"
actually belongs.** Frame End is the last frame PLAYED and the frame after it
is Frame Start again - Blender's rule. The old `_wrap` ran over `end - start`,
so **the last frame of the range was never shown at all**. Because the range
is inclusive, `animation.frame_times` no longer has a last image to DROP
(round 54's rule): a cycle cannot repeat its own first picture, because the
strip's own length and the frame range already say where it ends. And it is
where Christian's 59 comes from: 60 frames counted from 0 END at 59.
**(4) THE DEFAULTS ARE MADE TO LINE UP RATHER THAN LEFT TO CHANCE.**
`DEFAULT_STRIP_FRAMES` is 60 and `vibrations.DEFAULT_PERIOD_FRAMES` went from
20 to 60, so a freshly baked mode is 60 real samples over a 60-frame strip:
one whole period per second at 60 fps, Frame End 59, and **every drawn frame a
true sample of the sine rather than a chord between two**. 20 samples only
ever looked continuous because the global smoothing was subdividing them, and
that knob no longer exists. One rule covers new strips of both kinds -
`default_frames(n) = max(n, 60)`: never fewer frames than the data really has,
never so few that a three-step optimisation flashes past in a twentieth of a
second.
**(5) WHAT WAS DELIBERATELY *NOT* DONE: the strip does not re-bake the mode.**
"Pick the number of total subdivisions of the mode" reads as though the strip
page's Frames box should regenerate the samples, and it very nearly does the
same job - but round 76's own rule for this page is that **a strip is the
animation's TRACK, not the molecule's data** (which is why Delete on a strip
never touches the frames). Changing a playback length must not mutate a
molecule and push an undo step. So "Frames / period" stays on the vibrations
page as the DATA control and "Frames" on the strip page is the PLAYBACK one;
the defaults being equal is what keeps them from feeling like two knobs for
one job, and stretching past the sample count just interpolates.
**(6) A LENGTH CHOSEN BY HAND IS REMEMBERED (`frames_locked`).** `sync` runs
on every rebuild and re-derives a strip's default from the source count, so
re-baking a mode at 40 samples would otherwise quietly overwrite a length the
user had tuned. Set through `Timeline.set_frames`, which is the only thing
that marks it - assigning `track.frames` directly does not, on purpose, so an
internal adjustment is not mistaken for a decision. Round 52's "once the user
has said otherwise, stop regenerating" in a third place.
**(7) THE PLAYER IS SAVED NOW.** `Timeline.to_dict` existed since round 22 and
**nothing had ever called it** - a `.molom` carried no strips at all. That
cost nothing while a strip only held a start and a speed nobody set; it is a
real loss the moment its length is the number you tune until the motion looks
right. It rides `_ui_state`, so no savefile version bump, and the exclusion
set rides with it (a strip taken off the player is a decision - round 52
again). A pre-round-77 file is migrated: the old length in pictures was
`(n - 1) / speed * smoothing`, a picture is now a frame, so that product IS
the new `frames` and the whole axis - range, offsets, playhead - scales by
`smoothing` with it.
**(8) A FRAME IS A COLUMN ON THE AXIS, not a line.** Frame k occupies
`[x(k), x(k+1))`, which is already why a strip is drawn out to its EXCLUSIVE
`end_time`. With Frame End inclusive, drawing its handle through the frame
itself veils the last frame that plays and says it is excluded - so the handle
and the veil boundary sit one column further along, and dragging it sets one
frame back. That is the only pixels-to-frames conversion left in the panel;
the spin boxes now write scene frames straight onto the clock, where the bar
used to convert to and from 1-based image numbers.
**(9) AND THE NEW TESTS FAILED ONLY IN THE FULL RUN**, which is the oldest
signature in this file. `tests/conftest.py` sandboxes QSettings so a test
cannot write into the developer's config - and does nothing about one test
writing into the NEXT test's, because `MainWindow` reads its preferences on
construction. One line in round 22's playback tests
(`win._fps_spin.setValue(10)`) had been handing **10 fps to every window
built after it** for fifty rounds; nothing noticed until a test asserted
something derived from the framerate (60 frames should be 1.00 s, and came
out as 6.00). The sandbox is emptied after every test now. Same lesson as
the round-37 circuit breaker and the round-46 module cache: shared state
across a suite fails in a different file from the one that caused it.
1608 tests.

Round 76 (2026-08-18, Christian's MOPAC batch - and the one that changed an
answer was CHARGE):
**(1) NOBODY COULD SET A CHARGE, so every semiempirical run was neutral.**
`_active_charge_and_spin` read `Structure.charge` correctly and nothing on
screen could write it - the only producer was the SMILES importer. Measured on
Christian's own square-planar PtCl4: as neutral it holds **2.170 A**, as the
real [PtCl4]2- it goes to **2.321 A** against an experimental ~2.31, with the
heat of formation moving +3.6 -> -89.0. Same geometry, same method, a different
species. So his "converges correctly at 2.169" was a real converged answer to
the wrong question. Charge and Multiplicity are spin boxes on the Optimize
panel now, stored on the MOLECULE (metadata, so they ride undo and savefiles)
and guarded on refresh, because `setValue` emits whether or not a hand moved it
and an unguarded page writes one molecule's charge onto the next (round 30).
**(2) TWO FREQUENCY JOBS AT ONCE COULD KILL ONE**, which is exactly what he
asked about. The worker was held in a single attribute, so starting a second
dropped the only Python reference to the first and its QThread could be
collected mid-run. Keyed per molecule now, with a second job on the SAME
molecule refused; each already had its own scratch directory, which is why
concurrent jobs on different molecules were otherwise fine. Output files go to
a `mkdtemp` deleted in a `finally` - nothing accumulates, nothing is heavy.
**(3) CONSOLE WINDOWS FLASHING** - "a lot of windows being opened ... which
look effectively like a blur on screen". Every helper MoloM shells out to is a
console program, and on Windows each `subprocess.run` pops a window; a FREQ job
runs four of them. `io.quiet_subprocess_kwargs()` is the one place that knows
about `CREATE_NO_WINDOW`, applied to all five call sites (OpenBabel, MOPAC x2,
Blender, ffmpeg) - so ordinary IMPORTS stopped flashing too.
**(4) FERROCENE CAME IN AS A CYCLOPENTADIENIDE, and OPSIN was innocent.** It
returns the structure correctly; MoloM's own salt-stripping then kept only the
largest fragment by heavy-atom count, so Fe2+ (one atom) and one ring were
discarded. The rule is right for sodium acetate and wrong for every
coordination compound - and `fragments_of` already recorded `has_metal`, so the
information to tell them apart was there. The line drawn: **a LONE group 1/2
cation is a counter-ion; any other metal is the compound.** Ferrocene keeps its
iron, sodium acetate and NaCl strip as before, and the mixed case is now right
too - disodium tetrachloridopalladate loses both sodiums and keeps [PtCl4]-like
[PdCl4]2- intact. SMILES still cannot express hapticity, so a metallocene
arrives as separate pieces; what it no longer does is silently lose the metal.
**(5) A META ATOM'S DISTANCE IS A CONSTRAINT, not a default.** Changing a
donor's element ran `adjust_bond_lengths`, which pushed the bond to a
covalent-radius sum - computed, doubly wrongly, from the `Xx` dummy at atomic
number 0. `ideal_bond_length` returns the meta atom's stated distance when
either end is a meta centre, so H -> Br leaves all four donors at 2.4000.
**(6) THE VIBRATIONS PAGE HAD NO WAY IN.** Its empty state said "open an ORCA
FREQ output" and stopped, while the one thing that could produce data was
reachable only by knowing an F3 operator's name. A "Calculate frequencies
(MOPAC PM7)" button, which NAMES the engine because semiempirical is a
statement about physics, plus an indeterminate busy bar scoped to that
molecule - indeterminate deliberately, since MOPAC reports no percentage and a
percentage would be a lie. Core still does not know MOPAC exists: the add-on
registers through a provider list, the same shape as
`forcefield.register_method`.
**(7) COMMENTS.** Right-click a molecule -> a plain-text editor, stored in
metadata and written to the .xyz COMMENT LINE as plain text - the one place
every other program already looks, where our JSON is readable only to us.
**(8) ANIMATION STRIPS ARE OBJECTS NOW.** They can be selected (orange, the
same colour and meaning as the viewport's selection outline), deleted, panned
and scrolled through, and they have a properties page. Two decisions worth
keeping: **Delete takes the strip off the PLAYER and never touches the
frames** - this is the animation's track, not its data; and the removal is
REMEMBERED (`Timeline.exclude`), because `sync` rebuilds a track for every
scene object and would otherwise put it straight back, which is round 52's
"once the user has said otherwise, stop regenerating" in a new place.

Round 75 (2026-08-18, computed layers on a molecule, and what an edit does to
them - `core/attachments.py`):
Christian's design, and the heart of it is that **an isosurface and a set of
normal modes fail DIFFERENTLY**, so one "invalidate" flag would be wrong for
one of them. An isosurface "is a property that belongs to a particular
conformer that cannot be retained the moment anything changes about a mol even
slightly. And it should be pretty easy to recalculate if it is lost" ->
`POLICY_VOLATILE`, dropped on any edit including a geometry one. Modes are the
opposite: "I might want to calculate the modes of a mol, but change some
elements for the sake of a comparative visualisation in powerpoint that is not
intended to be accurate. So there an edit should not get rid of modes, only
declare itself as no longer physical in the GUI and in any potential export" ->
`POLICY_FRAGILE`, kept and flagged. Throwing away a twenty-minute calculation
because somebody swapped an oxygen is the worse failure.
**A geometry edit deliberately does NOT stale a fragile layer.** Moving a whole
molecule is a rigid placement and the modes travel with it; flagging there
would put a warning on the commonest gesture in the program, which is round
40's "a warning that fires always is a warning nobody reads". Dragging ONE atom
does invalidate them and is not caught - a stated gap rather than an oversight.
**OVERWRITE PROTECTION, on the objects that need it and no others.** An object
locks itself on receiving its first attachment and unlocks with its last, so an
ordinary molecule never shows a lock it has no use for - Christian: "Only add
overwrite protections to outliner objects that actually require them." A lock
on something with nothing to lose is noise, and noise is what teaches people to
click through warnings.
**Making the edit path REFUSABLE was the one architecturally interesting
piece.** `viewport._begin_edit()` returned nothing, so an edit could be
announced and never refused - and protection IS a refusal. It returns a bool
now and all seven chemistry call sites honour it (a guard some paths ignore is
worse than none, because the protection then depends on which gesture you
used). `on_edit_begin` goes to the new `begin_chemistry_edit`, while
`on_model_edit_begin` still goes straight to `begin_model_edit`, which is what
keeps geometry ungated. The flag is set AFTER the undo snapshot, so Ctrl+Z
gives back a molecule that is not still marked unphysical - tested, not
assumed.
**THE OUTLINER ROW is Christian's sketch**: the tick boxes sit ABOVE the
expandable element rows, in a WRAPPING `FlowLayout` because the count is not
ours to bound once add-ons contribute them ("people will need to fit like 16 of
them in there because they never turn off an add-on"). Round 45 had already
written that layout for the same reason, so it moved to `ui/widgets.py` rather
than being written twice. `Attachment.toggleable` is the one call not in the
brief: a visibility tick on MODES would have nothing to do - they are a data
source for the animation, not a layer painted over the molecule - so they
render as a label and keep only the lock and the stale marking. An inert tick
box is the thing this project keeps finding as a bug.
**AND REPOINTING THE CALLBACK GATED SOMETHING THAT IS NOT AN EDIT.**
`on_edit_begin` changed meaning - from "take an undo snapshot" to "may I make a
chemistry edit?" - and two callers wanted only the snapshot: **grabbing a
CAMERA and trucking one**. So a molecule's overwrite lock refused to let you
move the camera, and popped a dialog to say so. In the test suite that dialog
had nobody to click it, so the run HUNG rather than failed - which is worse,
because a hang has no name attached to it. Found with
`faulthandler.dump_traceback_later` around pytest, which named the line in
seconds after several minutes of guessing; worth reaching for immediately next
time a suite stops rather than fails. Both moved to `on_model_edit_begin`, and
a test now pins that only `_begin_edit` may read `on_edit_begin` at all,
because the next person adding a gesture will reach for the same hook.
**HIDDEN ATOMS ARE DIAGONAL STRIPES NOW, and red belongs to unphysical.**
Christian: "Red should not be used for it." He is right - red is the loudest
mark the outliner has and hiding a few hydrogens is a routine display choice,
so spending red on it left nothing louder for the state that IS a correctness
problem. Round 31's actual claim is untouched and its test still makes it, now
about the red mark: it must survive selection, because a foreground brush loses
to `HighlightedText` and the one row you clicked is the one that stops warning
you. Stripes cannot be lost that way at all, being painted over the row rather
than being a text colour. 1586 tests.

Round 74 (2026-08-17, MOPAC FORCE feeds the vibrations page - a reader, and
nothing else):
Christian asked what else MOPAC does, then "do the vibrations reader". **The
point of this round is how little there is of it.** Rounds 27-31 and 63 built
the whole vibrational UI - mode cards, the mode baked onto the scene clock, the
IR sort, the mass-weighted selection ranking - and every bit of it consumes
`vibrations.Mode` and nothing else, so `parse_mopac_frequencies` sits next to
`parse_orca_frequencies` and **not one line downstream changed**. That is the
dividend of round 27's decision to make the animation ordinary frames.
**THE TRAP IS WHICH BLOCK TO READ.** MOPAC prints the eigenvectors TWICE, under
`NORMAL COORDINATE ANALYSIS (Total motion = 1 Angstrom)` and again under
`MASS-WEIGHTED COORDINATE ANALYSIS`, laid out identically with the same
`Root No.` header. The mass-weighted one would animate every hydrogen far too
little and every heavy atom far too much - a wrong animation that looks
entirely plausible. The parse stops at the mass-weighted header, and the test
that pins it is CHEMISTRY rather than a byte offset: in Cartesian displacements
water's hydrogens move more than three times as far as its oxygen, which is
exactly what mass-weighting removes.
**Two things MOPAC gives that ORCA does not, and one it gives differently.**
It names each mode's irreducible representation (`1 A1`, `2 A"`), so `Mode`
grew a `symmetry` field and the card shows it - the leading number counts modes
within that representation and is not part of the symbol. And it reports a
TRANSITION DIPOLE where ORCA reports an IR intensity in km/mol. The conversion
between them is not something to invent, so `Mode.intensity_unit` carries the
number's unit and the card formats and labels accordingly, rather than printing
0.53 D under a "km/mol" tooltip - where `{:.0f}` would have rendered it as a
flat, mislabelled "0". Sorting is unaffected: intensity goes as the square of
the dipole, and squaring is monotonic over non-negative values, so the order is
the same.
**`run_frequencies` OPTIMISES FIRST, and that is chemistry, not convenience.**
`FORCE` computes the Hessian at the geometry it is given, so at a
non-stationary point the imaginary frequencies are an artefact of the gradient
rather than a transition state - MOPAC's own shipped example is a FORCE run "of
a relaxed water molecule" for that reason. `optimise_first=False` is there for
looking at a real saddle point.
**`OperatorRegistry.unregister` had to exist**: `register` raises on a
duplicate id, so an add-on that registers an F3 operator and cannot remove it
fails to enable the SECOND time it is switched on - an ordinary thing to do
while trying one out. Safe only for operators registered after startup, since
`_install_shortcuts` builds its QActions once and a built-in's would be
stranded.
**Verified in a real window by driving the operator** (round 73's lesson: the
module working is not the feature working). Water comes back as A1 1396.5, B2
2810.8, A1 2861.0 with the properties dock opening on the mode list. Both
fixtures are verbatim from MOPAC v23.2.5; the methanol one is the valuable
one, because its 12 modes WRAP into two column blocks (a reader that handled
only the first would return 8 and look fine), it has a genuine imaginary mode,
and its A' / A" labels defeat any numeric parse. 1563 tests.

Round 73 (2026-08-14, MOPAC as an add-on - roadmap item 7, and the extension
point is the whole design):
Christian's constraint from the scoping was the design brief: "idk how well we
can integrate that as an addon that doesn't mess with anything else in the
software." **So `core/forcefield.py` gained a REGISTRY - a dict and a signature
- and nothing else.** `register_method(key, label, callable)`, where the
callable takes `optimize`'s own arguments minus the method. Core knows the
contract and never the implementation: it does not import the add-on, does not
know what a semiempirical method is, and holds no subprocess or binary
discovery of its own. Every line that knows what MOPAC is lives in
`molom/addons/mopac_optimize.py`, and disabling the add-on leaves core exactly
the module it was. Pinned by a test that reads forcefield's IMPORTS via the AST
rather than grepping its source for the word - the first cut did the latter and
failed on the comment explaining the extension point, which is round 71's "a
test that pinned the wrong thing" repeating within the hour.
**The other half of "doesn't mess with anything else" is that it must not be a
SECOND optimise panel.** A semiempirical method is the same gesture as a force
field - pick a method, press Start, get a geometry - so it goes in the one
Method list next to MMFF94 and UFF. `OptimizeDock.refresh_methods` rebuilds the
combo on register/unregister (add-ons are enabled while the window is open) and
PRESERVES the current selection, or enabling an unrelated add-on would silently
drop the user back to MMFF94.
**AN ADD-ON METHOD DOES NOT FALL BACK, deliberately.** Dropping MMFF94 -> UFF
is a change of force field; dropping a Hamiltonian to a force field is a change
of PHYSICS, and handing back an MMFF94 geometry labelled as the thing the user
asked for is round 38's silent substitution. It reports instead.
**Verified by RUNNING it (round 37's rule), and cross-checked against
CHEMISTRY rather than against numbers I chose.** MOPAC v23.2.5 at
`C:\Program Files\MOPAC\bin\mopac.exe` - note the `bin` level, which the first
draft of the discovery list missed, so a perfectly ordinary default install
found nothing. Water comes back at 0.956 A / 105.3 degrees with a heat of
formation of **-57.800 kcal/mol**, which is the experimental value PM7 is
fitted to - an independent statement that the whole path did what it claims.
PtCl4(2-) gives four equal Pt-Cl at **2.321 A** against an experimental ~2.31,
while MMFF94 has no parameters for platinum and quietly hands back a UFF guess:
that gap is the entire reason the tier exists. And **frozen atoms move
0.000000 A**, because MOPAC carries a per-COORDINATE optimisation flag in its
geometry block - so round 62's bug (the tier every metal complex lands on was
the one ignoring `fixed`) cannot recur here; the constraint IS the format.
**The output is read through OPENBABEL's `mopout` reader**, driven by MoloM's
own `_obabel_worker` subprocess, rather than by a parser written here - twenty
years of C++ against the format's variants, the existing timeout guard for
free, and no parser fixture invented from memory. `tests/data/
mopac_pm7_water.out` is verbatim from a real run.
**Two tests had to be rewritten within minutes of being written**, both for the
same reason: they encoded "there is no MOPAC on this machine", which stopped
being true half an hour later and would never have been true on the laptop. A
test about the missing-binary path has to FORCE the absence
(`monkeypatch.setattr(m, "find_mopac", ...)`), and the live jobs are behind a
`skipif` so the suite is honest on a machine without it. 1545 tests.
**AND IT SHIPPED UNLOADABLE, which is round 59's lesson exactly.** Christian's
first run showed a red line under the add-on in the preferences dialog:
`ImportError: attempted relative import with no known parent package`. The
module used `from ..core import forcefield`, and `core/addons.py` imports an
add-on **BY PATH** under a synthetic name (`molom_addon_<id>`), so it has no
package context and a relative import cannot resolve - every other bundled
add-on already imports absolutely, and this file followed `core/`'s convention
instead of `addons/`'s. **All 34 tests passed while the feature was
unreachable**, because every one of them imported it as
`molom.addons.mopac_optimize`, which HAS package context: the tests exercised
the MODULE and never the LOADING PATH, which is precisely round 59's "a
mechanism with tests and no gesture test is a feature nobody can reach". Two
tests now close it - one enables every BUNDLED add-on through the real
`AddOnManager`, one refuses any relative import in `molom/addons/` via the AST
so it fails at the line rather than at the symptom.
**Also this round: `docs/OPEN_ITEMS.md`** - every scoped-but-unbuilt item swept
out of this file into one inventory, because they had accumulated across 73
rounds of prose where nobody could see them at once. And
**`docs/ISOSURFACES.md`**, answering Christian's design questions about where a
physics-based visualisation would live before any of it is built.

Round 72 (2026-08-13, the shuttle fixed for real - and the pattern is that
every chase fix was written into ONE branch):
Christian: "the last round was supposed to fix the issues, but they persist
unchanged." He was right on all three, and the reason is worth stating once
because it caused this three rounds running: **rounds 69, 70 and 71 each fixed
a real bug in the THIRD-PERSON branch and left the identical bug standing in
first person**, while the round notes recorded the fix as done. Round 70's own
test is the confession - it asserted the string `"self._cockpit_pos(obj) if
chase else obj.origin"` appears in the source, i.e. it pinned the line that was
wrong and passed for as long as the code kept being wrong.
**(1) FIRST PERSON HAD ROUND 69'S AND ROUND 70'S BUGS, both of them.** The
camera was re-anchored inside `_fly_object`, so it followed the ship when it
TRANSLATED and not when it merely turned (round 69's scoping bug, fixed then
for the chase camera only); and `_fly_turn` still rotated the molecule about
`obj.origin`, on a comment claiming "first person is already the centroid AND
the eye" - which round 71 had itself disproved by measuring 8.10 A between the
two on this very file. Measured: three seconds of pure steering, no thrust,
took the eye from 0.35 A off the picked atom to **9.41 A**. So round 71 fixed
where the cockpit STARTS and left it leaving the instant you fly it. Now
`_follow_cockpit` runs every tick for both modes (snapping in the cockpit,
easing in the chase - there is nothing to lag behind when the eye IS the ship)
and both modes pivot on the cockpit. A pure turn moves the cockpit atom
0.0000 A in either mode.
**(2) "ALL YOU SEE IS THE INSIDE OF AN ATOM" HAD FIVE SEPARATE CAUSES**, and
the loudest one no offline test could ever have shown. `cam.distance = 0.35`
flat, against an ordinary carbon drawn at **0.409** - and the camera looks AT
that atom - so the eye was inside the sphere; `flight.cockpit_distance` clears
the atom's own DRAWN radius (read the same way `_build_object_block` computes
it, or the clearance is measured against a number nobody renders), and the cull
is widened to cover where the eye now stands. Then four things kept putting
geometry back in front of the lens. **The cull hid an atom's SPHERE and kept
its BONDS**, so the eye sat inside the cylinders, which looks identical.
**Round 71's draw cache froze a camera-dependent mask** - `_shuttle_hidden`
measures every atom against the EYE, which moves every tick, so a block built
once and reused drew a bystander molecule straight through the lens; the cache
is off while a cull is live (third person culls nothing, so the case round 71
measured on keeps it). **THE SELECTION OUTLINE IS AN ENLARGED SPHERE WITH ITS
FRONT FACES CULLED** - and in the cockpit the selected atom IS the atom the
camera sits on, always, because that is how the cockpit is named. So first
person rendered as **a completely flat orange screen**, 54% of the frame being
one atom's outline. And **a meta atom's HALO** is a stack of shells larger
again, blended additively - which is not hypothetical, since the ship in the
report is a meta complex.
**Every offline test passed throughout, and `tools/smoke_gui.py`'s rule is why
this was found: a REAL window, and then LOOK at the picture.** The frame had no
exception in it, drew in the right place, and was orange from edge to edge; an
ink count alone would have called it healthy, because there was plenty of ink.
Both overlay passes have had their own buffers since round 35 and neither had
ever been told about the cull, which is the cost of that split.
**(3) THE JUDDER WAS NEVER THE SPRING, and the arithmetic says why in one
line.** The hard clamp fires on **0 of 240 ticks** - before the fix as well as
after. A cap of 3 molecule RADII at a viewing distance of 1.9 radii is **58
degrees off the view axis, against a 20 degree half-frame**: the backstop for
"keep the ship on screen" only engaged long after the ship had left. So round
71 stiffened a spring that was never being reached, and the measurement that
"the clamp never fires" was true and reassuring and meant nothing. The limit is
an ANGLE now (`slip_limit`, 9 degrees of the frame, scaled by the viewing
distance) because the gap is only ever SEEN as an angle.
**That exposed the real mechanism, which is not a wall at all.** An exponential
follow settles at `gap = speed / rate`, so a FIXED rate means the gap is
proportional to the speed - and past a point the camera is being left behind
faster than it can close, no matter how good the easing. That is precisely
Christian's "as if the molecule has vastly more inertia than the camera", and
it is a steady-state failure where `spring_lag` only ever treated a transient.
`follow_rate` raises the rate exactly as far as it must to hold the gap inside
the frame at this speed - `lag` unchanged when slow, so the trailing feel that
is the whole point of the mode survives, stiffening by itself when fast.
**And the speed itself was scaled by the wrong thing.** `_scene_scale` measures
the whole SCENE, which is right for flying the camera (a navigation gesture)
and wrong for flying a molecule (a placement gesture judged against the
molecule). A 3.7 A ship in a 60 A scene got a **105 A/s** top speed - 1.75 A of
travel per FRAME - which no chase camera can hold. Shuttle mode measures the
SHIP now, so the speed and the chase geometry finally share one scale; Shift
still boosts 3x for crossing the room. Measured on that scene: the ship
wandered to **30.5 degrees** below the axis (off the bottom of a 20 degree
half-frame) in per-tick steps of up to **4.6 degrees**, and now stays in frame
with steps under 0.3. 1510 tests.

Round 71 (2026-08-12, `docking.molom` - and Christian diagnosed two of these
himself):
**(1) THE COCKPIT ANCHORS BOTH MODES NOW, and his hypothesis was exactly
right**: "could it be that the problem I had was that I free drew a mol far
away from its object origin". Measured on his file: the acetones have
`|origin - centroid| = 0.00` and work fine; **meta-ship's stored origin is
8.10 A from its real centroid**, with its nearest atom 3.07 A away and its
furthest 12.52. First person put the camera at `obj.origin`, so the cockpit
view was from a point in empty space nowhere near the hydrogen he had picked -
hence "the piloted mol is still miles away from what FPS mode showed you", and
hence why only the meta-ship showed it. `obj.origin` is documented as the
centroid and simply is not one once anything has moved it. Both modes take the
selected atom now: the eye lands 0.350 A from the picked hydrogen (i.e. exactly
`cam.distance`) instead of 10.2 A away.
**(2) THE JITTER WAS A WALL, and he named the mechanism before I found it**:
"as if the camera is colliding with a boundary... typically managed by spring
arm logic in game engines... as if the molecule has vastly more inertia than
the camera". It was colliding with a boundary - round 66's `clamp_slip` let the
pivot ease freely until the gap hit a hard cap and then SNAPPED it back to
exactly that cap, every frame, for as long as the burn lasted. Ease, wall,
snap: a judder that is not a frame-rate problem and that no amount of tuning
`lag` can remove, which is why my synthetic test (short, never reaching the cap)
showed zero reversals and I wrongly concluded it was frame rate. `spring_lag`
makes the follow rate rise smoothly from `lag` at 45% of the cap to `lag * 12`
at the cap, so the gap ASYMPTOTES instead of striking something. `clamp_slip`
stays as a backstop for a pathological dt only.
**(3) THE PER-TICK REBUILD IS CACHED.** `_fly_object` calls `refresh_geometry`
every tick, and `_rebuild` recomputed every visible object's matrices, colours
and cylinder transforms - 3.64 ms on a 91-atom scene, 22% of a 60 Hz frame, and
it scales with the SCENE rather than with the thing that moved. The per-object
work is extracted into `_build_object_block` and cached per object WHILE
FLYING; the flown molecule is deliberately never cached, so what is reused is
every OTHER object, which cannot change during a flight because the viewport
holds the keyboard. The cache is dropped in `_end_fly`, so nothing outside that
window can read a stale block. 3.64 -> 2.36 ms here, and the saving grows with
the share of the scene that is not the ship.
**A note on the extraction**: the loop body contains object-level `continue`
statements, so it is wrapped in `for _once in (0,):` rather than `if True:` -
"skip the rest of this block" is exactly what "skip to the next object" meant,
since one call now handles one object.
**And a test that pinned the wrong thing**: round 62's meta-colour test
asserted `meta_mod.all_meta` appeared *in the source of `_rebuild`*, so it
broke the moment that code moved even though the behaviour was identical. It
now checks the colour that actually reaches the buffer.

Round 70 (2026-08-12, a regression I caused, and the symmetry modifier made
legible):
**(1) I MADE THE CHASE WORSE IN ROUND 69, and the fix is the model, not the
tuning.** Christian: "turning only without acceleration now moves the entire
mol. and it is moving fast." Round 69 made the follow run every tick (right)
but `_fly_turn` still rotated the molecule about its CENTROID (wrong) - so with
a cockpit atom off-centre, a pure turn swung that atom along an arc, the camera
faithfully chased the arc, and the whole molecule swept across the frame. An
aircraft turns about its COCKPIT, and so does this now: the pivot is the
cockpit position in third person, `obj.origin` in first (where the centroid IS
the eye, so the two agree). Measured: 3 s of pure steering moved the cockpit
0.0000 A. `obj.origin` is rotated about the same pivot, because the centroid is
a point ON the molecule and leaving it behind desynchronises the cell box and
every later transform from the atoms they describe.
**(2) A SYMMETRY MODIFIER DELETED EVERY BOND.** `evaluate` returned `[]` for
bonds with a comment arguing that the copies' connectivity is a perception job
- true, and the consequence was that adding the modifier dropped the bonds of
the ASYMMETRIC UNIT as well, so the molecule fell apart into loose spheres.
The connectivity is perceived, once, on the output. `evaluate` runs per REBUILD
and not per frame, so it is affordable at the sizes this modifier is for.
**(3) THE INVENTED CELL WAS INVISIBLE, and that explains three complaints at
once.** A plain molecule gets a box invented for it (round 33), and that box
lived privately on the MODIFIER. So the viewport could not draw a cell box for
it, the ❖ page could not report a, b, c, and `on_add_modifier`'s boundary
branch - which reads `cell_of(obj)`, i.e. METADATA - saw no cell and refused.
That is "I have no idea what the cell/box limits are", "no idea where the
center of inversion actually lies", and "the boundary bonds modifier doesn't
add at all", all from one omission. The invented cell is written to metadata
now, so it is a real cell: the box draws, the page reports it, the symmetry
overlay can place its elements, and boundary adds. An IMPORTED cell is never
overwritten.

Round 69 (2026-08-12, the chase drift, shuttle speed, fractional entry):
**(1) THE CHASE CAMERA DRIFTED AWAY WHEN NOTHING WAS PRESSED**, and it is a
one-line scoping bug with a subtle cause. The follow lived inside
`if np.any(delta):` - i.e. it only ran when the ship TRANSLATED. But steering
rotates the molecule about its own origin, which swings the COCKPIT ATOM along
an arc, so a pure turn moved the target and never moved the camera; every turn
left the pivot further behind. `_chase_follow` is its own method called EVERY
tick now. It also fixes a second case nobody had hit yet: a pivot that starts
out of position could never converge, because convergence needed thrust.
Measured: three seconds of pure steering used to walk the camera off, and now
holds the gap at 1.66 A.
**(2) SHUTTLE IS SLOWER THAN FLIGHT, and that is a real distinction rather
than a number.** Christian: "shuttle mode must be at most half as fast."
Flying the CAMERA is a navigation gesture - you want to cross the scene and
arrive. Flying a MOLECULE is a PLACEMENT gesture: the thing you are moving is
the subject, it has to stay in frame, and at camera speeds it is out of the
viewport before the key comes up. `flight.shuttle_scaled` scales the
acceleration AND the top speed by `DEFAULT_SHUTTLE_FACTOR` (0.45), both rather
than the cap alone, because scaling only the top speed leaves the thing
lurching to it just as hard - which is precisely the part that makes a molecule
hard to place. Exposed as **Settings > Flight > Shuttle speed** and live-applied
to a shuttle in progress ONLY, since it is the difference between the two modes
and pushing it into a camera flight would slow down the thing it does not
describe. Rebuilt from the unscaled setting each time, so repeated edits cannot
compound.
**(3) FRACTIONAL COORDINATE ENTRY.** "a quarter along a" is a statement about
the STRUCTURE; 3.47 A is a statement about this particular cell. The ❖ page
grows a block showing the selected atom's fractional position, editable.
`set_fractional` writes EVERY frame, and `wrap` is **off by default** and a
tick: bringing a value into [0, 1) is what you want when typing a site into a
cell and emphatically not what you want when nudging an atom that legitimately
sits outside one - a boundary copy, or a molecule that has been unwrapped
(round 19). The block is live only for EXACTLY ONE picked atom on a molecule
that has a cell, and says which of those is missing rather than offering three
live-looking fields that would apply to nothing.

Round 68 (2026-08-12, a unit cell can finally be DEFINED - `core/celledit.py`):
Christian asked whether roadmap 1b was "the building of crystal structures" and
then answered his own question better than the roadmap did: "what we definitely
need is a way to define the unit cell parameters, right?" **1b is not that** -
it is packing-as-a-modifier and bond-graph caching, both internal - and the
thing he named was simply MISSING. Every routine in `core/cif.py` CONSUMES a
cell that came out of a file; the ❖ page rendered a, b, c and the angles as
read-only text; the only cell operators (`toggle_cell`, `crystal_cell`,
`crystal_packing`, `crystal_edit_asym`, `cell_info`) all assume one already
exists. So a molecule with no cell could never be given a box, and an imported
cell could never be corrected.
**THE DECISION THAT MATTERS is what happens to the ATOMS**, and there is no
single right answer, so it is a parameter and a tick rather than a default
buried in the code. Keeping FRACTIONAL coordinates means the atoms move with
the frame and the structure stretches with it - which is what a cell edit means
crystallographically, because fractional coordinates ARE the structure and
a, b, c are the frame they sit in. Keeping CARTESIAN means only the drawn box
changes. `apply_cell(keep_fractional=None)` decides sensibly: fractional if
there WAS a cell to have them in, Cartesian if there was not, because in that
case there are no fractional coordinates to preserve - only a box being drawn
around what is already there.
**THE VALIDATION IS THE INTERESTING PART.** Positive lengths are obvious; the
angles are what catches people out, because they are NOT independently
choosable. Three angles only close into a parallelepiped when
`1 - cos^2a - cos^2b - cos^2g + 2 cos a cos b cos g > 0`, i.e. the squared
volume factor, i.e. the metric tensor being positive definite. **30/30/120
passes every per-angle range check and describes no solid at all** - the faces
cannot meet. Catching it means `Cell.matrix()` never sees a degenerate frame,
and the refusal says which way the user is wrong, ON THE PAGE rather than in a
status-bar message that is gone four seconds later.
Also: a space-group symbol typed here is resolved through `spacegroups.
operators_for`, the SAME Hall database a file's own symbol goes through (round
40), so a cell defined by hand expands exactly as an imported one would; an
unrecognised symbol changes nothing rather than silently falling back to P1. A
new cell with no symbol IS P1, stated explicitly - P1 is true of every
arrangement of atoms (round 52). "Fit to molecule" fills the fields from the
bounding box plus a margin, because an editor that opens on 1x1x1 and demands
six numbers before anything can be seen is one nobody uses. Removing a cell
takes the operators, the stored asymmetric unit and the derived columns with it:
keeping a space group for a cell that no longer exists is how a later rebuild
invents a structure from nothing.

Round 67 (2026-08-12, the chase camera made consistent, and F3 repeating):
**(1) THE SHIP DRIFTED LEFT UNDER ROLL**, and it was one line: the chase pivot
was offset along the CAMERA's up vector, so rolling swung the offset sideways
and carried the molecule out of frame with it. `chase_pivot` now defaults to
**world Z** (`flight.WORLD_UP`), which cannot roll. On top of that the chase
camera no longer rolls AT ALL - `fly_look` is passed `roll=0.0` in third person,
and since it rebuilds the rotation from an azimuth/elevation pair that IS a
level camera with no residue to unwind.
**(2) THE ROLL MOVED TO THE SHIP**, where it belongs and where you can see it.
Applied as a DELTA about the ship's forward axis, because `model.roll` is an
ABSOLUTE angle and replaying it every tick would spin the molecule up without
limit (`roll_applied` tracks what has been used). First person is untouched:
inside the cockpit the camera and the ship are necessarily one rotation.
**(3) THE COCKPIT IS AN ATOM.** "Select single atom (cockpit)" - one selected
atom names the nose of the ship, which is what a chase camera needs to sit
behind; a centroid is wrong for anything long or hollow. Exactly one selection
counts, anything else is ambiguous and falls back to the origin.
**(4) CLOSER**: `CHASE_DISTANCE` 4.0 -> 1.9 radii and the height 0.9 -> 0.45.
Measured on ferrocene, 47.7 A -> 22.7 A.
**(5) THE STEERING INSTRUMENT IS SHARED.** The shuttle drew a bare circle and
none of the aim ring, drift reticle, roll tick or speed - so the one mode where
you are steering a whole molecule had the LEAST on screen. `_paint_aim` is now
the single implementation and both modes call it.
**(6) F3 REMEMBERS.** Blender pre-highlights the last search result so a single
Enter repeats it. `OperatorSearchDialog` takes `last=` and pre-selects it - but
only on an EMPTY search, because once you have typed, the best match is what
should be selected rather than a memory of something unrelated. An id that no
longer exists (an add-on unloaded) is harmless.

Round 66 (2026-08-12, roadmap item 10 - piloting from outside the ship):
**THIRD-PERSON SHUTTLE.** Christian: "3rd person mode for piloting mols. trying
to do it FPS only leads to problems." The problem is structural and worth
stating: inside the thing you are steering you cannot see its orientation, and
a molecule has no windscreen to give you a horizon, so the cockpit view is
missing the two cues that make flying legible.
The implementation is small because the camera was already the right shape: it
is an ORBIT rig, so the eye already sits `distance` behind `center`, and a
chase view is mostly a question of where to put the PIVOT. `start_shuttle`
takes `third_person=`; the pivot goes slightly ABOVE the ship
(`flight.chase_pivot`), which lifts the eye and drops the molecule below centre
frame - the chase-cam look rather than a bug - and `distance` scales with the
molecule's radius, because these scenes run from a 3 A molecule to a 200 A
framework and a fixed number would be either inside the ship or in the next
postcode. Turning needed NO change at all: the camera swings its heading, the
ship rotates in place, and the pivot eases to the new position, which gives a
bank for free.
**THE LAG IS THE FEATURE.** A rigid chase camera makes the whole world swing
around the molecule and is as disorienting as sitting inside it, which would
have reproduced the very problem being fixed. `flight.follow` is exponential
smoothing (`1 - exp(-lag*dt)`), framerate-INDEPENDENT for the same reason the
drag is: a fixed fraction per frame trails further at 30 fps than at 120, so
the feel would depend on the machine. A test runs it at both and asserts the
same answer. Measured on cubane: the pivot-to-ship gap opens 3.29 -> 4.36 A
under thrust and settles back to 3.30 when it coasts to rest.
**`clamp_slip` is the part the scoping missed.** Lag is a feel; losing the ship
off the edge of the screen during a long burn is a bug, so the gap is capped at
3 radii and the pivot is dragged along past that. Also: nothing is clipped in
third person. The cockpit hides atoms too close to the camera so they do not
fill the screen, and here that rule would hide the ship itself, so `clip` is 0
and `_shuttle_hidden` returns early on it.

Round 65 (2026-08-12, roadmap item 8 - and the answer is "it is mostly Qt"):
**LAUNCH-TIME GUARDS.** Christian: "the startup is getting slow." It was, and
nothing in 1378 tests would ever have said so. `tools/startup_profile.py`
splits it into the three problems one number cannot tell apart - IMPORT time,
CONSTRUCTION, FIRST PAINT - and `tests/test_round65_startup.py` guards it
STRUCTURALLY. **No wall-clock assertions anywhere**: a millisecond threshold
across a laptop and a desktop with very different CPUs either passes everywhere
or fails as noise, so the tests pin what is portable (core imports nothing
heavy, opening a window imports no network stack, expensive widgets are lazy)
and the numbers live in the tool for a human to read.
**3269 ms -> 2877 ms**, from two fixes. `core.resolve` was imported at module
scope in both `app.py` and `dialogs.py`, dragging urllib + http.client +
email.parser (~130 ms) into every launch for a PubChem lookup most sessions
never make; it is imported at its two use sites now. And the PERIODIC TABLE
(118 painted cells) was built eagerly despite being hidden at startup - it only
appears in plain edit mode - so it is a `@property` that builds on first touch.
**The measurement that matters most is the one that says where NOT to look**:
`MainWindow()` is ~940 ms cold and **~43 ms warm**, so almost all of it is Qt's
one-off font and style caching, which whichever widget is constructed first
pays. That is why the periodic table appeared to cost 638 ms and actually costs
33. What remains is `OpenGL.GL` (~500 ms) and creating the GL context, and
neither can be avoided before a first frame - so the guards are about not
ADDING to the bill rather than about shrinking it further.
**Also: COPY SMILES on a meta atom.** "he tries to use Xx as an element label"
- exactly right, and the same shape as round 62's optimiser bug: `Xx` is atomic
number 0, RDKit refuses it, and the whole SMILES failed with "unknown element
'Xx'". Both call sites now go through `_smiles_symbols`, which is
`meta.resolved_symbols` - a SMILES is a statement about chemistry and a
placeholder is not an element. His `meta-test` now copies as
`O=C1[O][Fe][O]C1=O`.

Round 64 (2026-08-12, the export's geometry, and rows that are buttons):
**(1) ATOMS WERE BAKED, NOT SUBDIVIDED.** "In blender atoms do not show a
modifier and look a little blocky?" Both halves true: the export baked an
icosphere at subdivision 3 and turned on smooth shading, which fixes the INSIDE
of a sphere and not its SILHOUETTE - so the outline stayed faceted and there
was no modifier to raise. `add_subsurf` puts a real Subdivision Surface
modifier on every atom (1 viewport / 2 render, tickable). Per OBJECT because
the mesh is a linked duplicate shared by every atom, which is the normal
Blender arrangement.
**(2) THE META HALO CAN GO TO BLENDER**, as an emissive material, **off by
default** on Christian's own instruction. It gets its OWN material
(`META_MATERIAL_PREFIX`) or every atom of that element would light up with it,
and the name carries the fact so no parallel bookkeeping has to be threaded
through the collector - the strength is a single option, so the prefix is all
the spec builder needs. Verified by RUNNING Blender 4.4 headless and inspecting
the saved .blend: `SUBSURF (1, 2)` on the atoms, emission 2.0 on
`MoloM meta Fe`, 0.0 on `MoloM O`.
**(3) The export was still colouring meta atoms `Xx` grey**, which round 62 had
just changed in the viewport - found while doing the above, and exactly the
round-37 rule (an export that quietly disagrees with the screen is worse than
none).
**(4) A MODE ROW IS THE BUTTON.** The selection share pushed the "A" button off
the right edge of a narrow dock, and the card was a frame holding a framed
widget holding a button - three nested boxes to say one thing. One clickable
`_ModeRow`, one frame, no button. `WA_StyledBackground` is required or a
QFrame subclass ignores its own stylesheet background (the round-35 ribbon
trap), and the click fires on RELEASE inside the row so a drag-away cancels.
**(5) The association script broke on his machine** with "The string is missing
the terminator". PowerShell 5.1 reads a BOM-less file as cp1252, so a UTF-8
em-dash arrives as three bytes and the string never closes. That is round 37's
ASCII rule in a new language, and there is now a test asserting no byte above
127 in the `.ps1`. **He has also asked for no em-dashes in code comments at
all** - a plain hyphen, everywhere.

Round 63 (2026-08-12, roadmap 1g, the halo, and the Explorer icon):
**(1) MODES RANKED BY A VIEWPORT SELECTION** — roadmap 1g, scoped 2026-08-03
and built as scoped. `selection_weight` is a PARTICIPATION RATIO: the selected
atoms' share of the mode's motion, divided by the whole. A raw displacement sum
was the obvious wrong answer — it ranks every high-amplitude mode above a mode
that is genuinely localised on the selection, which is the opposite of the
question. **Mass-weighting is on by default and is not cosmetic**: an
eigenvector is a CARTESIAN displacement, so a C-H stretch is nearly all
hydrogen motion by amplitude, and unweighted, picking a heavy atom returns
almost nothing — phosphorus's best share on the vendored H3PO4 job is 0.176
unweighted against 0.431 weighted. Weighting measures the share of the kinetic
ENERGY, which is what "this mode belongs to that part of the molecule" means.
Verified as CHEMISTRY, not as arithmetic: the three H rank the O-H stretches
(3822-3831 cm-1, 94%) first and the P ranks the P=O stretch (1346 cm-1) first.
The share is drawn on the card next to the IR intensity, on round 31's rule
that sorting by an invisible number is a list you must trust blindly; the page
is PUSHED the selection by the window rather than reaching for the viewport,
and it is scoped to the ACTIVE object because another molecule's indices would
mean different atoms here.
**(2) THE HALO HAD VISIBLE RINGS**, and it was three shells doing it — three
big alpha steps are three edges. Sixteen thin shells with a smooth
`(1-t)**2` falloff read as one bloom. The knob that matters is that alpha is
divided by the shell count (`3.0 / n`): they blend ADDITIVELY, so without it
raising the count blows the halo out instead of smoothing it, and the two
parameters cannot be tuned apart. A quartic was tried first and was too tight —
it put everything at the centre and the outer glow vanished.
**(3) A `.molom` FILE ICON.** The window icon (round 62) and the icon Explorer
draws on a FILE are unrelated things: the second is a Windows file association,
which lives in the registry. `molom/resources/molom.ico` is a real multi-size
ICO (PNG-compressed entries, valid since Vista) and
`tools/associate_molom_files.ps1` registers it — **opt-in, HKCU only so it needs
no administrator rights, and reversible with `-Remove`**. Deliberately NOT done
at startup: a program that quietly claims a file extension the first time it
runs is one people learn to distrust.

Round 62 (2026-08-12, the meta-atom optimisation, and a logo at last):
**(1) META-ATOM OPTIMISATION COLLAPSED THE COORDINATION SPHERE**, and it took
THREE compounding faults to do it. Christian: "the bonds do not keep the length
they are set with. They become incredibly short." Measured on his own
`testing.molom` (`meta-test`, a bent Fe centre with oxalate, distance set to
2.0 A): the saved file has both donors at **0.655 A**.
(a) The force field was handed the DUMMY symbol `Xx`. Both RDKit tiers refuse
an unknown element outright — the notes read `mmff94: unknown element 'Xx'`
and `uff: unknown element 'Xx'` — so every meta complex fell straight through
to OpenBabel UFF. (b) **`_openbabel_optimize` ignored `fixed` entirely**: the
parameter did not exist on it. That is the tier a metal complex ALWAYS lands
on, so the one case that most needs frozen atoms was the one case that never
got them, and `frozen_atoms` had been correct and useless all along. (c) With
nothing frozen and a zero-radius dummy, UFF pulled the donors onto the centre.
Fixed at all three levels: the optimiser is handed `meta.resolved_symbols` (the
element the centre STANDS FOR, `Fe` here) so it reaches a real tier, OpenBabel
honours `fixed` through `OBFFConstraints` (1-based, unlike everything else
here), and the locked spheres are `idealize`d BEFORE being frozen — freezing a
collapsed sphere just preserves the damage, and the whole promise of a locked
meta atom is that the distance you set is the distance you get. Verified on his
file: 0.655 -> 2.000, engine now **rdkit uff** instead of openbabel, frozen
atoms move 0.0000.
**(2) The "oxygen with a halo" was the same bug wearing a disguise.** Not a
stale meta index (the saved table is `{0: Xx}` and correct) and not a leftover
ligating mark — the meta atom had collapsed to 0.655 A from that oxygen, so its
glow simply ENVELOPED it. Restoring the distance puts the halo back on the
centre alone. Worth remembering as a diagnostic habit: an overlay that appears
on the wrong atom may just be an overlay on the right atom in the wrong place.
**(3) A meta atom now wears its RESOLVED element's colour** — Christian: "the
halo will distinguish them as meta-atoms well enough". The `Xx` grey said
nothing about what the centre becomes.
**(4) MONODENTATE LIGANDS MAY COORDINATE SEVERAL TIMES AT ONCE.** With exactly
one ligating atom marked, each selected placeholder gets its own copy, so four
of cubane's hydrogens become four imidazoles in one operation (32 -> 64 atoms,
measured). The geminal rule is untouched for anything polydentate, where slots
on two different centres would mean a BRIDGING ligand — a genuinely different
operation. Every transform is computed against the ORIGINAL coordinates before
anything is appended, so a failure on the third of five leaves the molecule
untouched rather than half-built.
**(5) Bonds are pickable in OBJECT mode.** `_bond_at` is scoped to the EDITED
molecule (it exists for hover-and-press-a-number), so double-clicking a stick
in object mode found nothing at all; `_bond_object_at` searches every visible
molecule and takes the NEAREST hit, or a bond behind would win over one in
front.
**(6) A LOGO.** `molom/resources/` carries Christian's SVG plus PNGs rendered
from it at seven sizes, set on the QApplication (so dialogs and the taskbar
inherit it) AND on `MainWindow` (so a window built by a test, the smoke tool or
an embedder is not the odd one out). PNGs rather than the SVG alone because
Qt's svg imageformat plugin is a deployment detail we do not control, and the
failure mode is silently falling back to the generic Python icon. `package-data`
had to be declared or the wheel would carry the module and none of the images —
a bug that cannot be reproduced in the source tree it was written in.
**(7) The animation export is in the File menu**, which is where someone who
does not use shortcuts will look for the most option-heavy thing in the program.

Round 61 (2026-08-11, the second post-release batch — and roadmap item 9 done):
**(1) GIF FRAME RATES ARE NOT ARBITRARY.** Christian rendered a 60 fps GIF and
got "the old jitter problem". The format stores each frame's delay as an INTEGER
number of CENTISECONDS, so the only exactly representable rates are 100/n —
60 fps wants 1.667 cs and the encoder has to round, unevenly, which is seen as a
stutter no amount of re-rendering fixes. `gif_delay`/`gif_fps`/`gif_note` snap it
BEFORE encoding (60 -> 50, 30 -> 33.33, 24 -> 25) and the dialog says so while
you are choosing, not after. `-r` is set as well as `-framerate`, or the output
rate drifts back to something unrepresentable. **His follow-up question — "is it
the same for images?" — has a clean answer: no.** MP4 carries a rational
timebase so 60 is exact, and a PNG sequence has no embedded timing at all; this
is a GIF-only limitation and only GIF is snapped.
**(2) THE RENDER SETTINGS WERE A ONE-WAY DOOR.** Round 55 made F12 press-and-
forget, which is right, but once `_render_target` was set the dialog never
appeared again and there was no operator to bring it back. `on_render_settings`
+ two F3 entries ("Render settings: animation / still — ask again") clear the
memory AND reopen the dialog immediately, because "ask me next time" is never
what someone wants when they have gone looking for the settings. The dialog also
reopens showing the LAST choices rather than the defaults — re-picking the other
six knobs to change one is pure friction.
**(3) A TRACKPAD COULD NOT LEAVE A CAMERA VIEW BY ROTATING.** Round 60 gave
every scroll inside a camera a job (plain resizes the frame, Ctrl dollies, Shift
trucks) — and on a trackpad a two-finger scroll IS the orbit gesture and there
is no middle button, so there was no scroll left that could exit. **Alt+scroll
orbits and therefore leaves**, which is the same escape hatch Alt+LMB already
provides for mice whose wheel-click is unusable (round 16), so it is the
consistent answer rather than a new idea. The on-frame hint names it, since an
invisible escape hatch is the same as no escape hatch.
**(4) ROADMAP ITEM 9: ffmpeg WITHOUT SHIPPING IT.** `imageio-ffmpeg` moved out
of `[project] dependencies` into an OPTIONAL `video` extra — a ~25 MB static
binary should not ride along on every install to serve the minority who export
video, when the primary animation format is a PNG sequence that needs no ffmpeg
at all. `ffmpeg_candidates` gives it the `find_blender` treatment (round 50): a
Settings hint first, then PATH, then the usual install locations, and the
bundled wheel LAST rather than first — a system ffmpeg is usually newer and has
the codecs the user installed it for. `ffmpeg_source` returns WHERE it came from
so the dialog can say "Video via ffmpeg on PATH" before the render; where there
is none, a "Locate ffmpeg..." button appears (and only then), and what it finds
is remembered. `NO_FFMPEG_HELP` names the thing that DOES work, because a
message that only lists what is broken reads as a dead end.
**(5) TEXT YOU CAN COPY.** "I just tried to mark the resolved SMILES from name
so I could copy it, but the highlighting is not possible." Qt labels are not
selectable by default, so everything MoloM computes and then displays was
readable and impossible to paste. `widgets.make_text_selectable` walks a
CONTAINER rather than taking a list of labels — the failure mode of the
hand-written version is the label somebody adds later — and skips labels with a
BUDDY, which carry a mnemonic and must keep click-to-focus. Applied to the
resolve dialog, the whole properties dock (including add-on pages, via
`add_page`) and the graphics-device report, which is the first thing anyone is
asked to paste into a bug report. The crystal page was already selectable; it
had been using `TextBrowserInteraction` since round 41 for its DOI links.
1331 tests.

Round 59 follow-up, same day: Christian replaced the five generated screenshots
with his own — deliberately NOT a clean-slate default scene per shot, because
"I wanted to show off molom's performance and ability to visualise multiple
structures at once." So the vibrations shot carries TWO independent ORCA FREQ
jobs animating on separate timeline tracks alongside several other imported
molecules and crystals, and the camera shot frames three different crystal
structures — a coordination compound, a polyhedral framework and a simple
ionic lattice — composed together in one shot. `docs/screenshots/README.md`
says outright that these are hand-picked, not tool output, so a future
`tools/screenshots.py` run does not silently overwrite them with a blander
default-scene set.

**Reported in passing, NOT reproduced or root-caused — logged for later,
explicitly not urgent (Christian: "niche case... acceptable bug we can get to
later"):** occupancy pie spheres appear not to propagate correctly from an
asymmetric-unit view to the full-cell view. Round 42's `site_occupancy` map is
keyed by DRAWN atom index and round 42/52's own lesson is that such a map has
to be rebuilt (or explicitly carried) every time the atom list is regenerated
— asym-unit -> full-cell is exactly that kind of rebuild, and round 51's
`_sync_all` bug (a page not refreshed on the very same transition) is the
shape of bug most likely to recur here. First step for whoever picks this up:
reproduce on a real shared-site file (`cod_1547149_solid_solution.cif` is
already vendored and is the file round 42 was written against) by switching
Asymmetric unit only -> Full unit cell with occupancy pie spheres ticked, and
check whether `site_occupancy`/`site_of` survives `packing.pack`'s rebuild.

## VERSION 0.2.0 (2026-08-03) — the line under the previous session
(Round 34 sits above it, unreleased.)
Everything below shipped between 0.1.0 and 0.2.0: the PC/mouse input preset,
the operator key table, CIF reading with symmetry, coordination polyhedra,
meta atoms, the scene clock with a multi-track timeline, vibrational modes,
per-element display control, and the symmetry modifier. 512 tests.

Round 58 (2026-08-10, the camera view rebuilt on Christian's correction):
round 57's frame model was wrong and he said exactly how. "When I pull the
corners, the camera zooms out or is moved back. It shouldn't. I want the
current camera position to not change and just adjust the borders of the
camera view." Everything else he reported falls out of the same mistake.
**The fault: the frame was FITTED and the projection was fitted to it.**
`frame_rect` returned the largest rectangle of the camera's aspect that the
window holds, and `sync_camera_lens` then widened the field of view so the
camera's own landed on it — so the instant a handle changed the aspect, the
rectangle changed size, the field of view changed with it, and **the entire
scene rescaled**. Which reads exactly as the camera dollying backwards.
**The fix is one decision: THE FRAME IS ANGULAR.** Half-width `Z*tan(fov_x/2)`
and half-height `Z*tan(fov_y/2)`, with `Z = zoom * widget_h / 2`. Work out
what the scene's on-screen scale then is and it comes to **`Z / distance` —
no `tx`, no `ty`, no lens, no aspect**. So moving a border cannot rescale
anything, and the only control that resizes the picture is `zoom`. That is
not a design choice dressed up as maths; it is the only model in which "the
borders move and nothing else does" is true, which is why it was worth
deriving rather than guessing at a third time.
**Consequences, all of them things he asked for.** A HANDLE moves a border:
horizontally by resizing the FILM (`sensor_mm` — a film back's border is
literally the size of the film), vertically through the aspect, since the
sensor size is horizontal and the aspect is what divides it. **The
resolution follows the aspect with the LONGER SIDE PINNED**, which is where
the "6000 x 5000 image even though the multiplier is 1" came from: round 57
had the handles driving the pixel count directly, `blender_export.
build_render` takes the ACTIVE CAMERA's resolution for the Blender scene, and
a few drags ratcheted it into the thousands. Dragging now reshapes a shot and
can never inflate it — measured, 40 outward corner drags leave a 640-pixel
camera at 640.
**The WHEEL is the frame zoom** ("mousewheel should also not move the camera,
only scroll in the view" / "scrolling forward should cause the frame to grow
in the viewport. Right now it is effectively changing the focal length"). It
was dollying `camera.distance` against a pinned field of view, which is
indistinguishable from a lens change. Every scroll gesture goes there while
inside a camera, not just the zoom one — there is nothing else a scroll could
mean when the camera is not allowed to move, and leaving pan or orbit live on
the wheel would be a way to move it by accident. A pan DRAG is refused with a
hint rather than silently ignored; a zoom drag does the frame zoom.
**CAMERA OBJECTS ARE DRAWN AND GRABBABLE** — "just like in blender they should
be cones with a rectangular base as wireframes which have a dashed line
attached to their tip that goes towards the xy plane". `cameras.
gizmo_geometry` returns the pieces in world space and `_paint_cameras` draws
them: the rectangular base IS the film, so its shape states the aspect ratio;
a small triangle marks up, which is the only thing distinguishing a rolled
camera from a level one at a glance; the dashed drop line is what makes the
thing placeable, since without it a camera above the floor and one below it
look identical. Clicking the apex selects it (the apex is where the camera IS,
so grabbing it moves the camera), **G moves and R aims** through a small modal
of its own — the molecule modals act on a selection of ATOMS through the
scene's snapshots and a camera has none — with the same click-to-confirm,
Esc-to-revert contract. `selected_camera_id` is a separate field from
`selection` for round 56's reason: a camera has no atoms, so every loop over
`(obj_id, atom)` would otherwise have to learn to skip it.
**Numpad 0 was bound to a key half the keyboards never send.** `Num+0` is
`KeypadModifier | Key_0`, and **with NUM LOCK OFF the numpad's 0 sends
`Key_Insert`**. `extra_keys=("Num+Ins",)` registers both, the same mechanism
round 55 used for both spellings of a Shift chord. **Esc leaves the camera
view** too, and it does so LAST in `cancel_modes` — Esc backs out of the
innermost thing you are in, so cancelling a grab must not also throw you out
of the shot.
**Two traps found while building it.** A frame is now free to grow past the
window, and it takes its own drag handles with it — so a border drag is
clamped at the window and says so (the wheel is how you make room). And
`_render_crop` asks for a buffer of `resolution / frame fraction`, which grows
without bound as the frame is pulled in — capped at 6x the widget, with the
crop scaled the rest of the way, because the frame's size on screen is a
VIEWING choice and must not decide how much memory a render takes. Verified in
a real window: dragging a border moved it while the molecule stayed at
**184.2 px, unchanged to a tenth of a pixel**, and a 640x360 camera rendered
640x360 and exported 640x360 to Blender.
**And SHIFT+DRAG came back, as a real camera move.** "All I need now is to
bring back shift+drag so that I can do final adjustments to the camera view.
That was in before and it was good." It was refused outright when the camera
was locked, which was one step too far — but restoring what round 57 did would
not have been right either: that panned the INTERACTIVE camera, so the framing
you nudged was gone the next time you pressed Numpad 0, and no render carried
it. `truck_camera` slides the camera OBJECT in its own screen plane, so the
adjustment survives leaving the shot and reaches the savefile, the render and
the Blender export. It does not contradict "unless the camera is selected and
grabbed, it should not move": a held modifier plus a drag IS the deliberate
gesture. Measured against the WIDGET's field of view rather than the camera's,
so the shot slides by exactly as many pixels as the hand moved at any frame
zoom — which makes the gesture self-regulating for fine work, since scrolling
in puts more pixels across the same part of the shot. One undo step per drag
(`_truck_gesture`, cleared on release).
1265 tests. **RELEASED AS 0.3.0.**

Round 57 (2026-08-10, the camera view becomes a view, and four animation
faults): Christian used round 56 in anger and every complaint pointed the same
way — **the camera view was a decoration laid over an ordinary view rather
than being one.**
**(1) The film back did not frame anything.** The scene was drawn at the
viewport's fixed 40 degree FOV over the whole window and the rectangle merely
painted on top, so the focal length changed the LABEL and nothing else and what
you composed inside the frame was not what would be rendered.
`cameras.viewport_fov_y` widens the widget's FOV so the camera's own lands
exactly on the rectangle, and it is applied by shadowing `Camera.FOV_Y` on the
one instance — which means every matrix in the program (view, projection,
picking rays, `fit`, `pan`, the offscreen render) follows from a single value
with no second code path to keep in step. `sync_camera_lens` is idempotent and
runs at the top of `paintGL`, so a resize or a lens edit cannot leave the
projection describing the previous frame; it only drops the `_camera_frame`
cache when the value really moves (dropping it per frame would undo round 35c).
**(2) "The corner drag buttons essentially do nothing" — and they nearly
didn't.** `frame_rect` always returned the largest rectangle of the aspect that
fits, so only the SHAPE could ever show, and **a corner dragged along the
rectangle's own diagonal is exactly the aspect-preserving direction**
(`scale_x == scale_y`): same shape, same drawn size, nothing moves. A corner
now also carries a `frame_zoom` (12-100%, purely a viewing property) by the
geometric mean of the two scale factors, so it visibly grows and shrinks while
the resolution still follows both axes independently; an edge keeps its one
job. Because the FOV follows the frame, pulling it in shows MORE of the scene
around the shot rather than cropping it.
**(3) A knob click "resets a previous dolly"** because every edit ran
`apply_to`, which assigns centre, distance AND rotation. Split into `apply_to`
(pose + lens) and `apply_lens_to`; `camera_changed` calls only the second, so
changing the film size is no longer a statement about where the camera stands.
**(4) "Is it even possible to exit the current camera view?"** Now: **orbit
leaves it, keeping the pose you rotated to** (Blender's rule — restoring the
pre-camera view would undo the very gesture that caused the exit), and so do
axis views and taking off into flight. Pan and zoom stay inside. The exception
is gated on the RESOLVED ACTION rather than on Shift/Ctrl, so it is identical
on a trackpad and a mouse; tumbling a MOLECULE does not exit, because that
moves the model. And the way out is written on the frame.
**(5) F12 through a camera renders the frame**, at the camera's resolution x
multiplier — as a CROP of an ordinary viewport render enlarged so the crop
never upscales. Enlarging by the same fraction on both axes leaves the widget's
aspect exactly intact, which is what keeps the projection identical to the
screen's and every overlay painter working unchanged (they all project through
`self.width()`). The animation dialog's default size comes from the active
camera for the same reason: a window-shaped default would be stretched by the
export's `IgnoreAspectRatio` scale.
**(6) ROLL was stored and never applied to the view**, and the Blender export
built its own twist matrix TRANSPOSED — so it rolled the OPPOSITE way from
`Camera.fly_look`, which round 56 said it was following. Nothing caught it
while the viewport ignored roll entirely: there was no preview to disagree
with. `cameras.twist_rotation` is now the single place that knows the
convention, `capture` takes the roll back OFF the pose it stores (or the next
activation tilts twice), and verified by rendering: a 0.45 rad camera comes out
of Blender 5.1 tilted the same way MoloM draws it (topmost-H bearing 121.4 deg
against 118.7 — the residual is blob-detection noise, where the old code
differed by 2 x 0.45 rad).
**The animation half, all four measured on Christian's own H3PO4 FREQ job.**
**(a) Only the FIRST animate click reset the location**, which is exactly what
he observed. Round 55's `_rest_for` re-read frame 0 only `if active is not
None` — i.e. only while a mode was already animating — so the first bake still
used the capture taken when the frequencies were read. There is nothing special
about the first one: frame 0 is the rest geometry whether a mode is baked
(sin 0 = 0) or not (the molecule itself), so it is read unconditionally.
**(b) "When an animation shortens a bond far enough it is no longer drawn."**
Correct, and the chemistry filters are not wrong — they were being asked the
wrong question. The player re-perceives connectivity on every integer frame
change, and at the DEFAULT 0.2 A amplitude the 1346 cm-1 mode squeezes P=O to
**1.127 A against an `IMPOSSIBLE_FACTOR` floor of 1.13**; at 0.4 A the O-H
stretches reach **0.56 A**. A normal mode is one molecule at successive phases
of an oscillation about equilibrium and nothing bonds or unbonds along the way,
so `bonding.FIXED_BONDS` in the structure's metadata (round 43's pattern —
rides undo and savepoints with no `Scene.snapshot` checklist) stops the
question being asked. `_freeze_mode_bonds` also re-perceives ONCE at frame 0,
which makes it self-healing for a molecule whose bonds an earlier big-amplitude
mode had already eaten.
**(c) The orange outline lagged the meshes.** It did: `_rebuild` draws from
`evaluated()`, which INTERPOLATES between frames, while `_selection_hull` read
`s.coords`, the nearest stored one — up to half a source frame apart, which on
a vibration reads as a lag that reverses at each turning point (Christian
guessed a 90 degree phase; the mechanism is the half-frame). `_ensure_pick_data`
had the same fault, so a click during playback landed on the stored frame while
the sphere was somewhere between two. Both take `display_coords()` now.
1246 tests.

Round 56 (2026-08-09, CAMERA OBJECTS — Blender's model, Christian's spec):
"introduce camera objects like in blender... that way a savefile can retain
previously used angles". `core/cameras.py` holds a `CameraObject`: a pose
(pivot + distance + quaternion, the same triple the interactive rig uses, so
activating one is an assignment), a lens, a film size and a roll.
**Three decisions worth keeping.** (1) **Focal length is MILLIMETRES against a
SENSOR WIDTH, not Angstrom** — Angstrom is the scene's unit and a focal length
only means something relative to the film it projects onto; (50 mm, 36 mm) is
a pair every photographer and every Blender user can already picture, and
`fov_y_degrees` turns it into the vertical FOV the projection actually wants
(one arctan, and the aspect divides the sensor so a 16:9 camera and a square
one do NOT frame the same height). (2) **Roll is explicit**, because the
interactive camera is a TURNTABLE and cannot represent a rolled pose (round 3
is the whole no-roll fix) — a saved camera has to carry it rather than hope
the orbit rig can hold it. (3) **Resolution is pixels PLUS a multiplier**:
512x512 at 2x is a different statement from 1024x1024 — "this framing,
finer" — and it survives deciding later that the figure wants 4x.
**Cameras are a SEPARATE list from `Scene.objects`**, and that is the whole
reason the round was cheap: a camera has no atoms, so every loop that draws,
picks, exports or perceives bonds would otherwise have to learn to skip it.
None of that code changed at all. They ride `snapshot`/`to_dict` like
everything else — and `from_dict` rebuilds the snapshot dict BY HAND, so the
first savefile lost them until that was carried too (a new entry in round 31's
four-place checklist, and the same shape of bug).
**The UI**: the outliner grows a section under a hairline divider with a
`+ Camera` row; double-click looks through one; **Numpad 0 TOGGLES** (glance
at the shot, then back to composing — entering only would make the key
half-useful, and the free view is restored to where it was). A 🎥 properties
page carries projection / focal length / sensor / pixels / multiplier / roll.
Looking through a camera veils everything outside the film back and draws the
frame with **eight drag handles** — Christian asked for "indicators that make
the user realise he can use them", and an invisible hit target is the
commonest way a drag-to-resize goes undiscovered. A corner is tested before an
edge, since dragging the very corner should never resize one axis only.
**The Blender export was the clean part.** MoloM's rig and Blender's camera
already share a convention (look down local -Z, +Y up), so a saved camera's
world matrix is the same construction `camera_setup` already used and roll is
just part of the rotation. Every saved camera becomes a real Blender camera,
the active one is made `scene.camera`, and the viewport camera is only added
when there are none — two cameras describing one shot is clutter. `data.lens`
and `sensor_width` are set DIRECTLY rather than through the field of view, so
the number in Blender's N panel is the number in MoloM's. Verified by running
it: an 85 mm camera at 640x360 with a 2x multiplier and 0.35 rad of roll came
out of Blender 5.1 as a 1280x720 render, tilted, from the .blend alone.
1219 tests.

Round 55 (2026-08-09, four of Christian's, and the render keys):
**(1) Re-baking a normal mode teleported the molecule home.** `_rest_geometry`
was captured ONCE when the frequencies were read and reused for every bake, so
selecting another mode — or nudging the amplitude, or the frames-per-period —
regenerated `rest + eigenvector * sin(phase)` around coordinates from before
the user had moved anything. `_rest_for` re-reads it instead: frame 0 of a
baked mode IS the undisplaced geometry (sin 0 = 0) and a grab moves EVERY
frame, so frame 0 is the rest geometry wherever the molecule now is. No extra
bookkeeping, and nothing left to go stale.
**(2) The lasso hotkey, and it was Christian's own guess.** Not a case problem
in the string: `Shift+Space, L` matches only if Shift is RELEASED before the
second key, and holding it through — as anyone does — makes Qt look for
`Shift+L` and fire nothing. `ops.chord_variants` registers both spellings for
any chord whose first part carries Shift, so box select was quietly as fragile
and is fixed with it.
**(3) X deletes**, alongside Del, which is what Blender does and what X was
doing nothing for. `Operator.extra_keys` is the general mechanism, and
`duplicate_keys` counts an extra binding as a claim like any other — two
operators sharing a key makes Qt fire NEITHER (round 16).
**(4) F12 / Ctrl+F12 are the EXECUTE keys**, Christian's own better idea. The
first press behaves like the ordinary export and opens the dialog; from then
on the same key renders immediately with those settings, which is what F12
means to a Blender user. The deliberate routes (Ctrl+Shift+E, Ctrl+Shift+A)
still ask every time, so nothing is taken away. Press-and-forget is only safe
because the filename INCREMENTS (`animation.next_free`, a tick in the dialog,
on by default): a render key that silently replaces the last render is a key
you cannot press twice. The remembered path is always the BASE one — storing
the incremented name instead compounds the suffix, and three presses gave
`shot.png`, `shot_001.png`, `shot_001_001.png`.
1191 tests.

Round 54 (2026-08-09, the animation export, copies that follow, and a
CORRECTION):
**(0) I was wrong about MSAA, and the retraction is the useful part.** Round
53 reported "4x multisampling requested but NOT granted" on the strength of
`format().samples()` returning 0. That property describes the WINDOW, and a
QOpenGLWidget renders into an FBO of Qt's own making — so it reads 0 on a
perfectly multisampled context. Queried properly from inside the live context,
`GL_SAMPLES` is **4** and `GL_SAMPLE_BUFFERS` is **1**: MSAA has been on all
along, and `render_image` sets `setSamples(4)` on its own FBO too, so exports
have it as well. `graphics_info()` now reports the framebuffer's real count
and labels it as such. Nothing needed fixing; only the instrument was wrong.
**(1) ANIMATION EXPORT** (`core/animation.py`, `Ctrl+Shift+A`) — the roadmap's
1d, asked for on 2026-08-02: "it sucks to have nice animations in a viewport
but not being able to render them". The pieces all existed (a clock that steps
deterministically, `render_image` at a resolution multiplier), so the export is
seek/render/write and the real work is the frame PLAN. **A PNG sequence is the
primary format and takes no dependency**; video is the optional tier through
`imageio-ffmpeg`, with a system `ffmpeg` preferred where there is one. The
frames are always written as a numbered sequence and the video encoded FROM
them, so a failed encode still leaves every rendered frame on disk.
Three decisions worth keeping: **the last image of a loop is dropped** (it is
the same picture as the first of the next, and keeping it hitches once per
revolution — invisible in any single frame, which is why it is a test); **the
plan follows the transport bar's own loop range**, since an independent export
range would be two sources of truth for one interval; and a sequence goes into
a FOLDER named after the chosen file rather than beside it. `render_image`
gained `furniture=` — a still figure is better without the cell box, an
animation of a rotating crystal is not — and the overlays are painted onto the
exported QImage through a SCALED painter, so there is still one implementation
of where the cell box goes. Verified end to end: a 12-frame spin exported 33
PNGs and a 28 kB MP4, with the scratch folder cleaned up and the playhead put
back where it was.
**(2) An edit to a packed crystal now reaches its own COPIES** (round-49 item
3, properly). An atom on a cell face is drawn twice and one at a corner eight
times, as independent entries in the atom list — so changing one left the
others as they were, and one face of the cell said F while the opposite face
still said H. `packing.pack` now records `content_of` (which cell-content atom
each drawn atom is an image of) and `images_of` turns that into the set to
edit. Element changes and deletions both go through it. Measured on ferrocene:
one H -> F changes 8 drawn atoms, deleting an Fe removes all of its images.
Where there is no mapping the input is returned unchanged — without it there
is nothing to say two atoms are the same SITE rather than merely the same
element, and guessing would silently change atoms nobody selected.
1176 tests.

Round 53 (2026-08-09, VESTA's sheen, and three things that were hiding):
**(1) A SPECULAR highlight on the coordination polyhedra**, Christian's
request — "shows up when you rotate the view so that the normal of a face is
directed straight at the observer". Blinn-Phong with the light AT the eye, so
the half-vector is the view vector and `N.H` is the `|N.V|` the diffuse term
already computes: `specular * |N.V| ** shininess`, one power over the scene.
It earns its place beyond looks — a highlight appearing and sliding off as the
solid turns is what tells you the faces are flat and which way each one
points, which a translucent silhouette cannot.
**Drawn as its OWN ADDITIVE pass**, not added to the face colour, and the
reason is measurable: the solid is drawn at 0.55 alpha, so a highlight mixed
in is more than half gone before it reaches the screen, and on a pale element
colour (niobium is nearly white) it then clips to nothing. Additive is also
the right model — a reflection is light ADDED over what is behind the surface.
**The trap this hit**: an ordinary additive blend accumulates the ALPHA
channel too, which is invisible on screen and wrong everywhere else. A grabbed
frame came back with 24% of the picture DARKER, every one of those pixels
scaled by a uniform 0.643 in all three channels — the signature of colour
divided by an alpha that had crept up, not of a lighting change.
`glBlendFuncSeparate(SRC_ALPHA, ONE, ZERO, ONE)` leaves alpha alone: 0.00%
darker afterwards. **Defaults chosen by rendering the same frame six ways and
differencing**: 0.30/24 lit 15.6% of the frame at a peak gain of 0.89, which
washes the colour out of the faces you most need to read (round 48's Fresnel
mistake from the other side); **0.15/32 is 11% lit at 0.61** and ships.
Tunable per VIEWPORT, not per module — a default ARGUMENT binds its value once
at import, which is why the first A/B attempt produced two identical frames.
**(2) The lasso was not lost, it was hidden.** `Shift+Space, L` and F3 only,
with a plain left-drag being box select — so nothing on screen said it still
existed. It has a toolbar button now.
**(3) The ❖ contents RADIO never followed the active crystal.** Set once at
construction, so with two CIFs open it kept whichever mode the LAST one was
put into — and a radio that is already checked emits nothing, so clicking the
mode you wanted did nothing. That is "I cannot toggle the different view
states of cifs when multiple cifs are imported", and it is round 51's tick bug
one control along.
**(4) `graphics_info()` + `F3 > Report the graphics device`.** Christian asked
whether PySide uses the dedicated GPU. It does — a QOpenGLWidget is a real GL
context — but WHICH adapter a process gets is the driver's decision, so the
only honest answer is `GL_RENDERER`. On the desktop PC it reads **AMD Radeon
RX 7900 XTX**, i.e. the discrete card. Found while adding it:
`QSurfaceFormat.setDefaultFormat` runs only in `molom/__main__.py`, so
anything else that builds a window — the smoke tool, a test, an embedder — got
the driver default (compatibility profile, no multisampling).
`MolViewport.__init__` now calls `setFormat` itself.
**~~MEASURED AND STILL OPEN: multisampling is requested but NOT granted.~~
WRONG, retracted in round 54**: `format().samples()` describes the window, not
the FBO a QOpenGLWidget draws into. `GL_SAMPLES` from inside the context is 4.
MSAA was on the whole time.
1157 tests.

Round 52 (2026-08-08, Christian's second MOF-5 batch — an edited cell is P1,
and a shared site can be STATED):
**(1) Adding atoms in the full cell then switching views destroyed the
structure** (618 atoms came back as 13). Two causes, one rule. Added atoms are
appended AFTER the boundary copies, so "the first `cell_content` are the
content" stops meaning anything the moment the count changes — the new carbons
were outside the content entirely and never reached the asymmetric unit. And
round 51's automatic re-derivation kept finding groups that could not rebuild
the cell: on MOF-5, `R3m` with **6 operators over 7 orbits — 42 atoms where the
cell holds 424**. "spglib found a group" is not "this unit and these operators
rebuild this cell", and nothing was checking the second claim.
**So an edit to a FULL CELL now demotes it to P1**, which is Christian's own
proposal. **P1 and not P-1**: P-1 asserts an inversion centre through the
origin, an arbitrary edit preserves no such thing, and writing it would make
every downstream expansion invent a half of the structure that is not there.
P1 is the one group true of every arrangement of atoms. Deriving the real group
is still available deliberately (`F3 > Crystal: re-derive the space group`),
and that route now REFUSES an answer that cannot reconstruct the cell —
`_reconstructs`, sharing `cif_write`'s `_expand`/`_covered`.
**(1b) P1 alone was not enough, and the reason is round 45d from the other
side.** The drawn content is not the canonical cell content: `packing.pack`
unwraps molecules to keep them whole, so **34 of ferrocene's 42 content atoms
sit outside [0,1)**, between -0.43 and 1.43. Storing those as the unit means
the next rebuild wraps them itself, tearing the molecules before the completion
runs — 210 drawn atoms came back as **168, four complete molecules where there
were five**. Wrapping them first fixes the tearing and not the completion,
because the relocation has already defeated it. So an edited cell is **FROZEN**:
`cell_frozen` stops the ❖ contents radio regenerating it at all, the atoms in
front of you ARE the structure, and Packing is greyed with the reason (a
supercell has to regenerate, and there would then be no way back to the single
cell). An Array modifier is the route to repeating it.
**(2) No automatic geometry change when an element changes in a CRYSTAL**
(Christian: "too risky" — he is right). A site in a crystal is not a free atom:
its position was refined against diffraction data and it usually sits ON a
symmetry element. `adjust_bond_lengths` is what pushed the MOF-5 hydrogen
0.44 A off its site in the first place. `viewport.is_crystal` gates both the
length adjustment and the hydrogen re-dressing; a molecule is untouched, where
`H -> Zn` lengthening its bond is the whole point of the draw tool.
**(3) The origin handle belongs to the SELECT tool.** With the draw tool armed
every click is a drawing gesture, so a handle in the middle of the molecule is
a trap. `MolViewport.select_tool_active` is the name for "edit mode, no tool
armed" — Blender calls it Tweak, MoloM's toolbar calls it Select. The handle is
not drawn and not pickable outside it, arming a tool puts it DOWN (or G would
silently move the origin), and Alt+O disarms whatever is holding clicks rather
than putting up a handle that cannot be grabbed.
**(4) `core/occupancy.py` + `F3 > Crystal: set the occupancies of a shared
site`** — the honest limit, closed. A shared position is destroyed at import
before occupancy is consulted (round 45e), nothing in the coordinates implies
it and no derivation can recover it, so the only honest answer is to let the
user say what the site is. Edits apply to the whole symmetry ORBIT via
`site_of` (a cubic cell draws one site 24 times). The writer splits a shared
site into **one `_atom_site_` row per species** at the same coordinates, which
is how a CIF expresses them — but ONLY on the rebuilt path: a file that has a
shared site already lists each species as its own row (the solid solution's
unit is [Nb, Ti, Ni, Co, O], five rows for four species on one position), so
expanding the verbatim round trip would write Ti, Ni and Co twice. A
user-edited composition sets `site_occupancy_edited`, which takes the writer
off the verbatim path because the stored unit is the FILE's, from before they
said otherwise. Measured: stating O 0.8 / N 0.2 on the oxide writes both rows
and keeps the file's own Nb/Ti/Ni/Co site intact.
1142 tests.

Round 51 (2026-08-08, Christian's MOF-5 report — four bugs, one of them old):
he changed a single H to an F in `938392.cif` (MOF-5) and the cell box came
off the floor of the xy plane while the cell "doubled". Both reproduced, and
they are the SAME fault seen twice.
**(1) `on_edit_begin` was wired to `push_undo`, not to `begin_model_edit`.**
Round 43e's whole mechanism — capture the crystal's pose BEFORE the atoms move
— hangs off `on_model_edit_begin`, which only the GEOMETRY modals (G, R, the
anchored tumble) use. Every CHEMISTRY edit — change element, draw, bond order,
delete — goes through the other hook, so `cell_pose` was measured AFTER the
atom had moved, read the move as a rotation of the whole crystal, and baked it
into the cell reference. Measured on MOF-5: **a 1.2 degree tilt and a 0.10 A
shift from one H -> F**, and since a rotated box has a larger axis-aligned
extent, the box appears to move AND grow. The next rebuild then re-poses the
regenerated atoms by that spurious rotation, which moves atoms that sat exactly
ON a cell face off it and changes which ones get boundary copies: **616 drawn
atoms became 760, with 144 extra carbons.** That is the "doubling". Round 43e's
test passed throughout because it drove geometry edits.
**(2) A re-derived space group left the stored asymmetric unit behind.** A
rebuild is `asym_symbols` + `asym_frac` expanded by `symops`, so the three have
to describe ONE structure; round 43d re-derived the operators after an edit to
the full cell and left the unit alone, silently making them describe two — and
a rebuild believes the metadata, not the atoms in front of it. Measured: one
H -> F on the packed MOF-5, then touching ANY ❖ control, and **616 atoms came
back as 7** (the file's asymmetric unit expanded by the 2-operator group spglib
had just derived). `resync_derived_asymmetric_unit` takes the unit from the
cell CONTENT via `orbit_representatives` at the same moment the operators
change, drops the parallel columns rather than mis-indexing them (round 43e's
rule), and re-pins the cell frame — which the full-cell branch never did, only
the asymmetric one.
**(3) `_sync_all` never refreshed the ❖ page.** Round 34's comment sitting
directly above the call NAMES that page and then only calls
`_sync_modifier_page` and `_sync_crystal_ribbon`. So an import left the whole
page describing the PREVIOUS molecule, every per-crystal tick with it — which
is exactly Christian's "the coordination polyhedra tickbox needs to be cycled
to show polyhedra even though it is on": the box carried the last structure's
state, so his first click was the one that finally set the flag on this one.
Fixed, and `set_cell` now writes **every** per-crystal tick from the object
(polyhedra, symmetry, ghosts, occupancy) rather than the two that happened to
be threaded through first. Those ticks emit through a `_loading` guard now
(`CrystalPage._emit`), because `toggled` does not care who moved the box and
an unguarded refresh writes one molecule's state onto the next — round 30's
TimelinePanel bug in a new costume.
**(4) Unticking Symmetry elements now collapses its filters** ("should it not
auto un-expand?" — it should: the filters choose between things none of which
are drawn). Found while doing it: `_toggle_kinds` guarded on
`self.sym_check.isEnabled()`, and **`isEnabled()` folds in every ANCESTOR** —
this page sits on a QStackedWidget inside a dock that is usually closed, so it
reported False for a perfectly live control and the arrow quietly stopped
ticking the box. Its own `_has_cell` flag now. Same family as round 34's
`isVisible` trap, one property along.
**Also this round: the Blender render defaults, chosen by MEASURING renders.**
"Everything looks super exposed and milky/washed out." Both halves are real and
they are different faults. Rendering MOF-5 six ways and measuring luminance
over the non-transparent pixels: **`Standard` blows 4.9% of the molecule to
pure white** (the "exposed" half) while AgX and Filmic clip nothing — but bare
AgX also **drops contrast from 0.165 to 0.120** (the "milky" half), which is
what a highlight roll-off costs. The fix is a contrast LOOK, so the shipping
default is **studio HDRI + AgX + "High Contrast"**: mean brightness 0.531
(unchanged), **0.0% blown**, contrast 0.160 (unchanged). Christian asked
whether Filmic should be the default instead — no, and the tutorials that say
so are dated: Filmic was Blender's default through 2.8x-3.x and desaturates
midtones toward grey, AgX replaced it in 4.0 and keeps the colour. Measured
here too, AgX + High Contrast holds more saturation (0.190) and more contrast
(0.160) than Filmic + High Contrast (0.187 / 0.157). **"Punchy" is a trap** —
it came out DARKER (mean 0.405 against 0.531) and bought no contrast back.
**And the round-50 leftover, done: OCCUPANCY now survives a re-derivation.**
`packing.pack` already recorded `site_of` — which asymmetric-unit site each
DRAWN atom came from — so a rebuilt cell can be looked up in the old column
rather than written as fully occupied. Used in two places, `cif_write.
_site_columns`: by the writer's `cell` policy, and by
`resync_derived_asymmetric_unit`, which used to drop the columns outright.
Measured on the solid solution: editing one O to N re-derives P4_2/mnm as
Amm2 and the exported file still carries Nb at 0.5 rather than claiming 1.0.
`site_of` is DROPPED afterwards, because it described the unit that has just
been replaced (round 42's rule about a per-atom map surviving a renumbering),
and where there is no mapping at all the column goes and the loss is reported
— a mis-indexed occupancy being worse than none. Two round-50/51 tests
asserted the old "occupancy is lost" behaviour and moved with the code, which
is round 38's lesson about fixtures again. 1120 tests.

Round 50 (2026-08-08, the round-49 list, top to bottom): four of the five
items, on the DESKTOP PC. **(0) The polyhedra perf item was real and it was
the shading.** `shade_colors` ran a Python loop per TRIANGLE per FRAME and the
triangle soup was rebuilt beside it with one `triangle_soup` call per
polyhedron: **53 ms a frame at 400 octahedra** (19 fps before a single pixel
is drawn), 1.4 ms at the ten `1547149.cif` has. The normals, the centroids,
the base colours and the soup are all camera-independent, so they moved into
`face_arrays` next to the cached hulls and only `shade_from_faces` runs per
frame — four array operations over the whole scene. **53 -> 0.32 ms (168x)**,
262 -> 1.3 ms at 2000 octahedra, and BYTE-IDENTICAL output, which is what
makes it a performance change rather than a look change. Also removed a dead
`glDisable(GL_BLEND)` sitting after a `return` (so the pass now restores the
blend state it turns on) and left culling alone, since off IS the default here.
**(0b) A hull face is a PLANE, not a triple.** Emitting one triangle per
accepted triple stacked FOUR of them on every square face — a cubic
8-coordinate centre came out **24 triangles over its 12**, which blends twice
in the viewport (a square face reads more opaque than a triangular one) and is
straight z-fighting in a render. The triples are grouped by the SET OF POINTS
ON THEIR PLANE — an exact integer key, where a rounded normal lets two triples
of one face disagree — and each face is fan-triangulated once in a
right-handed basis, which is what keeps the winding outward with no
per-triangle check. Pinned on the five standard coordination solids and on 50
random hulls.
**(1) The Blender export carries coordination polyhedra.** It returned atoms,
bonds, camera, centre, lights, materials and radius, so a MOF figure lost
exactly the thing that makes it readable. One closed mesh per centre, FLAT
shaded (a coordination polyhedron has real creases), on a translucent material
that is **never metallic** — a translucent metal renders as a chrome shell
with nothing visible inside it. `polyhedra.for_object` is now the ONE place
that decides which solids an object shows, called by both the viewport and the
exporter, so the render cannot disagree with the screen (round 37's rule).
Note `collect` must always be handed `cell_of`, not `cell_of if
options.unit_cell` — gating it on the box tick would silently drop the
polyhedra back to the drawn bonds and open them.
**(4) It writes a `.blend` now.** Christian: "I don't like having to load it in
every time... all I have to do is press F12." Blender IS installed, so the
export INVOKES it: the same generated script, run headlessly as `blender -b
--factory-startup --python build.py -- --save out.blend`. **The scene is BUILT
before the file is saved, so the .blend opens complete** — no auto-run, no
"Allow Execution" prompt, no trust dialog — and the script rides along as a
text datablock for re-running after a tweak, plus stays on disk beside the
.blend. The path is a SETTING with discovery (the stored hint, then PATH, then
the usual install locations newest-first), and **a `blender-launcher.exe`
resolves to the `blender.exe` beside it** because the launcher is a GUI shim
that cannot be scripted — which is the path Christian actually has. A failed
build leaves the script and says so; the script remains an output format on
its own, since it is diffable and needs no Blender at all.
Verified BY RUNNING IT (round 37's rule): Blender 5.1 headless on
`cod_1547149_solid_solution.cif` writes a 131 kB .blend with 10 Nb octahedra,
and rendering **that file** with no script involved gives the VESTA picture.
**(2) A real CIF writer** (`core/cif_write.py`) — see the round-50 entry below
for the whole of it. **(3) Editing a packed crystal is now FLAGGED** rather
than silently desynchronising the boundary copies. 1102 tests.

Round 50b (2026-08-08, `core/cif_write.py` — a written .cif is a crystal
again): there was no CIF writer at all. `io.write_structure_file` handed
OpenBabel an xyz block for any non-xyz extension, so a `.cif` carried
coordinates and nothing else — measured on a ZIF-8 export: no
`_cell_length_a`, no symmetry, no occupancies, and **MoloM's own parser
rejected the file MoloM had just written**. A CIF's content is cell +
operators + asymmetric unit, so the whole question is where those three come
from, and the choice is made **by measurement, not by a flag**: if the stored
asymmetric unit still reproduces the drawn cell CONTENT — i.e. nothing has
been edited — the file's own unit, operators, occupancies, disorder columns,
site labels and space-group spelling go straight back out (`_covered` asks it
that way round on purpose, since the disorder policy may legitimately have
dropped alternatives while a MOVED atom is simply not in the expansion).
Otherwise the symmetry is re-derived from the coordinates by spglib
(round 43d's `from_structure` + `orbit_representatives`) and the content
reduced to one atom per orbit, because operators that no longer describe the
structure would expand it into a cell that never existed.
Five details that had to be right: **the SETTING is preserved** (all nine
settings of number 14 share the standard short symbol, so writing `P2_1/c` for
a file that says `P 21/a` reads as an outright error — round 41 — hence the
file's own spelling is kept whenever the re-derived group is the SAME group,
compared as geometry via `operators_match` and never as text); **only the cell
CONTENT is written**, since everything past `cell_content` is a boundary copy
and writing those claims a cell with every face atom in it twice (ferrocene:
210 drawn, 42 content, 11 sites); **the pose is undone first**, or a rotated
crystal's coordinates ARE the rotation — pinned at 10, 37 and 90 degrees
writing a byte-identical file; **the operator loop is written ONCE**, because
putting both synonymous tags in one loop doubles the count for any reader that
knows them and the first cut read its own 16-operation file back as 32; and
**occupancy is never invented** — it cannot survive a re-derivation, so that
path writes 1.0 and SAYS so, the same discipline as round 38's chemistry
notes. A molecule with no cell gets a P1 box round it, reported as invented,
because a CIF without a cell is not a CIF and refusing outright is less useful
than writing one honestly labelled (geometry survives to 1.2e-4 A, which is
the 5-decimal fractional precision on a 15 A box). Verified against
independent readers: **ASE and pymatgen both read the written files exactly as
they read the originals**, and pymatgen warns on the ORIGINAL ferrocene (it
has no operator loop) and not on ours. `asym_labels` is now carried in the
import metadata so "C12A" is still called C12A after a round trip.
**Editing a packed crystal** (round-49 item 3) is flagged once per object with
the route that does work: the copies are ordinary independent atoms — on
ZIF-8 atom 0 has a copy at index 348 and moving one does not move the other —
and no existing guard covers it, since `begin_model_edit` handles the cell-box
drift (round 43e) and `sync_asymmetric_unit` only fires when the base IS the
asymmetric unit, which a packed import's base is not.

Round 45f (2026-08-06, over-valence allowed + the boundary step): two more of
Christian's, both in the sandbox only. **(1) Over-valence is now DRAWN.** "There
should be a carbon with 6 connected hydrogens there. I think that's the better
representation. VESTA and Mercury also do it" — and he is right: a methyl
disordered over two orientations at full occupancy (`4-ABA-oxime.cif`, round
41's file) is honestly depicted with six H, which reads as rotational dynamics
rather than as an error. `bondgraph.build` gained `valence=` and
`cap_hydrogens=` as separate flags from `sanity=`, because an impossibly short
contact is never a bond (not a judgement call) while an over-valence atom may
be exactly what a disordered site should look like. Defaults unchanged, so the
shipping path is untouched; the sandbox passes both False. Measured: 6 carbons
over four bonds, one of them C + 6 H exactly. **(2) A Boundary stage**, because
the completion had nothing to work off for a framework: an atom with k of its
coordinates on a boundary belongs to 2^k positions, and the WRAP CANNOT PRODUCE
THEM (it is a function — 0 maps to 0, never to 1), which is precisely why it is
its own step. `boundary_instances` returns `(atom, shift)` pairs so the round-44
graph instantiates them with their own coordination spheres. The direction has
to come from the coordinate and not from the wrapped residual: x = 1.0 has
residual 0.0 but sits at the TOP of the cell, so its partner is at shift -1.
**And the periodic branch of `complete_molecules` now closes each drawn atom's
own coordination** — one bonded shell — since a framework has no "whole" to
complete. That is what puts the oxygens on the metal sitting exactly on a face
of `1547149.cif` (6 -> 15 -> 59 atoms), and it needs no chemistry-specific
rule. Christian's related question about VESTA is worth recording: he observes
it extends oxides past the boundary but not intermetallics, and wonders how
much per-case logic is in there. A unified explanation that fits: VESTA draws
no metal-metal bonds at all, so an intermetallic has nothing to extend ALONG,
while an oxide's M-O bonds do. That does not explain `2108327.cif` (a Ba/Li
fluoride-oxide, where he sees bonds but no extension), so it is a hypothesis,
not an answer.
**Round 45g, same day — three fixes to the shell growth**, all from Christian
looking at the output. (1) The growth followed METAL-METAL bonds and dragged in
a superfluous outer layer: `1547149.cif` came out with 19 Nb from a content of
2. (2) It brought the partner ATOM only, so a ZIF's imidazolate N arrived as a
blue dot with no ring (`2130251.cif`). (3) He asked for metal-metal to go
entirely, as VESTA does. So the sandbox graph now DROPS every metal-metal edge
(`_without_metal_metal`), and the growth carries the partner's whole COVALENT
FRAGMENT (`_covalent_fragments`, which excludes metal-metal for the same
reason). Measured: 1547149 59 -> 51 atoms and Nb 19 -> 11 with no M-M bonds;
2130251 286 -> 368 with the rings complete; the Ni6Sn8 intermetallic now draws
BARE, 28 atoms and zero bonds, which is exactly what VESTA shows. **Still open
and worth a decision**: the remaining Nb come from completing the coordination
of boundary OXYGENS, which legitimately bond to metal outside the box — the
growth is symmetric while VESTA's looks asymmetric (it appears to add O to
metals but not metals to O).
**Round 45h — bonds between DISORDER ALTERNATIVES.** ZIF-7's guest water is
modelled over four partial sites (occupancy 0.48-0.50) and MoloM drew bonds
between them. Distance cannot possibly settle this: the alternatives sit
**1.359 A** apart and a peroxide O-O bond is 1.48 A, so the geometry is
indistinguishable — the information lives in the OCCUPANCY column.
`_without_alternatives` refuses a bond between two atoms that are both partial
and whose occupancies sum to about one or less, because they cannot both be
there. It also fixed a second symptom Christian spotted independently: those
spurious bonds fused the guest oxygens into one multi-atom fragment, and the
completion computes lattice positions PER GROUP, so an oxygen on a c edge came
out at three of its four positions instead of four. Both fixed by the one rule.
**Still open**: bonds from the FULL-occupancy O to the partial ones survive
(1.475 / 1.520 / 1.706 A) because the sum rule does not apply, and 1.475 A is
exactly a peroxide bond — no distance rule can reject it.
**Round 48 (2026-08-06, polyhedra that close, and can be seen): two more of
Christian's, both about the same picture. **(1) "Coordination polyhedra should
be complete no matter which combination of modes is applied."** They were built
from the DRAWN bonds, so a polyhedron was only ever as complete as the picture:
half of ZIF-8's zinc are boundary copies whose coordination is not completed
unless the copies tick is on, and those came out as flat triangles.
`polyhedra.build_periodic` takes the donor POSITIONS from the labelled graph
instead — it knows where the fourth nitrogen is even when no atom is drawn
there — so the solid closes independently of both checkboxes. Measured:
ZIF-8 {4: 12, 3: 12} -> **{4: 24} under all four combinations of the two
ticks**; `1547149.cif` 3 partial solids -> 10 complete octahedra. A metal
neighbour is never a vertex: a polyhedron is drawn through its LIGANDS.
**(2) A translucent solid has no readable silhouette**, so two things were
added: a **Fresnel rim** (`fresnel_colors`, grazing faces lightened toward
white) and an explicit **hull-edge wireframe** (`hull_edges`) drawn on top. The rim
was WRONG and Christian said so with a VESTA screenshot: brightening grazing
faces toward white washes the element colour out exactly where two faces meet,
which is the edge you most need to see. `shade_colors` replaces it with flat
FACE SHADING — `ambient + (1 - ambient) * |N.V|`, the light at the eye — so a
face turned toward you is the full colour and an oblique one is darker, which
is what makes neighbouring faces of an octahedron distinguishable. Flat, not
smooth: a coordination polyhedron has real creases. It is computed on the CPU
because the line shader carries no normals and a single alpha uniform; it is the only camera-dependent part, so the HULLS are
now cached on their inputs (`_polyhedra_plan`) — rebuilding a convex hull per
metal per repaint was the round-33 mistake sitting in the paint path unnoticed.
1047 tests.

Round 47b (2026-08-06, the ❖ page catches up with the packed pipeline):
Christian: "'Bonded atoms outside the cell' doesn't seem to work and needs to
go." Correct — it drove `shell_molecules`/`BoundaryModifier`, mechanisms the
packed path no longer uses, so the tick had quietly become inert. Replaced by
the sandbox's two, now that they are the real controls: **Draw atoms outside
the cell boundary** and **Complete the boundary copies too**, stored per object
as `pack_outside`/`pack_copies` and threaded through `build_view` ->
`packing.pack`, so a rebuild reproduces the picture. Measured on ZIF-8:
696 atoms with Zn coordination {4: 12, 3: 12} by default, **864 and {4: 24}**
with the copies tick, 360 and {2: 24} with outside off.
**Two of Christian's three points needed no code.** (1) "Asymmetric unit only
seems to not include atoms of partial occupancy for ZIF-8" — it does: the
parser reads all 9 `_atom_site_` rows including H00A/H00B/H00C at occupancy
0.5, and the asym view draws 9 atoms (Zn 1, N 1, C 3, H 4). Nothing is
dropped. (2) "Coordination polyhedra should always be closed" — the open ones
were the 12 Zn that are boundary COPIES, which do not complete their
coordination unless the copies tick is on; ticking it takes all 24 to four
donors and closes every tetrahedron. **Still open, and the principled fix**:
`polyhedra.build` takes its donors from the DRAWN bonds, so a polyhedron is
only as complete as the picture. Building it from the periodic graph instead —
the donor POSITIONS are known even when the donor atom is not drawn — would
close it always, independently of any display option. That is the right
answer to what he actually asked for.

Round 46 (2026-08-06, INSTALLABLE ADD-ONS — Blender's model): Christian, on the
debug and sandbox pages: "I just want them cordoned off somewhere so I don't
need to worry about them", and on the API: "I don't see why an add-on should
not have full access... If someone wants to brick their install with something
they made themselves, that's on them." So there is no sandbox and no capability
list — `register(window)` is handed the live `MainWindow` and may do anything
the app can. Four decisions, all his: **bundled + user folder** (`molom/addons/`
ships with MoloM, `~/.molom/addons/` is scanned too, both listed together, a
user id SHADOWING a bundled one so a shipped page can be patched without
editing the install); **`register()`/`unregister()` plus an `ADDON` dict**, the
bl_info shape, because it is what any Blender user already knows and it caps
nothing; **live enable, restart to fully remove** — unticking calls
`unregister()` and says a restart is needed, rather than promising a teardown
MoloM cannot enforce on third-party code; and **the two pipeline pages become
bundled add-ons, off by default**, which is the cordoning-off and simultaneously
the proof that the API carries a real page. `app.py` no longer mentions either
one — the shared plumbing moved to `molom/addons/_pipeline_host.py`, so nothing
you reason about while working on MoloM proper has to know they exist.
**Metadata is parsed with `ast`, never imported**: listing add-ons must not
execute third-party code, or one broken module takes the whole preferences
dialog with it. A test writes an add-on with an import-time side effect and
asserts it never fires. Enabling catches everything (`BaseException` on the
import path, so a partially executed module is removed from `sys.modules`), and
a failure disables that add-on and reports it rather than stopping startup.
`PropertiesDock` gained `add_page`/`remove_page` since the tab strip was a fixed
list built in the constructor. **Gotcha worth keeping**: `_import` caches in
`sys.modules` deliberately (enabling twice must not re-execute), which makes a
loaded add-on SHARED ACROSS THE TEST SUITE — the round-37 circuit-breaker trap
in a new place, and it presented the same way, one test failing only in the full
run. `tests/test_round46_addons.py` purges `molom_addon_*` around every test.
1042 tests.

Round 45i — the phosphate fix, chosen by measuring four policies rather than
one.** The shell grew from EVERY drawn atom including the boundary copies, so a
6-coordinate Mg with copies on three faces completed its sphere once per copy.
Four combinations were measured (grow from copies or not, carry the partner's
covalent fragment or not): growing from the in-cell atoms ONLY, still carrying
the fragment, is the winner — `Mg2(P2O7)(H2O)3.5.cif` 351 -> 185 atoms,
`Mg2(P2O7)(H2O)6.cif` 491 -> 255, and the ZIF ring completion is **unaffected**
(2130251 identical either way), which is what rules out the alternatives:
dropping the fragment carry halves the phosphates too but breaks the rings
again (368 -> 286). A "grow only from METALS" variant was also tried, on the
VESTA asymmetry hypothesis, and rejected — it barely touched the phosphates
(351 -> 341) and cost the ZIF. **The trade-off is real and is therefore a
CHECKBOX, not a silent default**: completing the boundary copies too makes a
dense oxide look fuller (`1547149.cif` 21 -> 51) while ballooning the
phosphates, so "Complete the boundary copies too" sits next to the outside
tick, off by default. Molecular crystals are untouched either way (242083 is
876 both ways). 1026 tests.

~~**Also open, measured not fixed**: the Mg pyrophosphates blow up 3.6-5.8x
(`Mg2(P2O7)(H2O)3.5.cif` 60 -> 347 atoms, 276 partners materialised). The
periodic branch grows a shell from EVERY drawn atom including the boundary
copies, and each carries the partner's whole covalent fragment — a P2O7 group
is 9 atoms and Mg is 6-coordinate, so it multiplies. The likely fix is to grow
only from atoms strictly INSIDE the cell, but that wants measuring against the
ZIF cases before it is written.~~ **FIXED in round 45i above.**

Round 45e (2026-08-06, the sandbox settles what a SITE is before drawing it):
Christian's framing, and it is the right one — "sites are not atoms, they are
statistically averaged electron densities explained by an atom type when the
CIF was refined". So an **Occupancy** stage now sits between Dedupe and Bonds,
splitting partial occupancies two ways because they need opposite treatment:
**(A) spatially DISTINCT** alternatives are drawn as full atoms (his call, and
a good one: a methyl over two orientations showing six hydrogens is an honest
cue that it rotates in the solid state), **(B) SHARED** positions — several
species on one Gitterplatz — collapse to one pie-chart atom. **The ordering
flaw this stage exists to work around**: by the time atoms exist, case B has
already been destroyed. `expand`'s minimum-image merge removes the co-located
species BEFORE occupancy is consulted, so on `SodiumNicotinate.cif` the
nitrogen sharing a position with a carbon comes back with multiplicity ZERO
and is simply absent. The composition therefore cannot be read off the drawn
atoms and is recomputed from the ASYMMETRIC UNIT via `cif.site_composition`
(round 42's rule, reached again from the other end). Measured: sodium
nicotinate 8 pie atoms (C 0.50 / N 0.50) plus 8 distinct partials as full
atoms; `1547149.cif` 2 pie atoms (Nb 0.50 / Ti 0.25 / Ni 0.15 / Co 0.10).
**No CIF tag declares case B** — `_atom_site_disorder_group`/`_assembly`
declare case A — so it is recognised geometrically, identical coordinates with
occupancies summing to about one. Worth knowing the converse also happens:
`4-ABA-oxime.cif` writes a genuinely disordered methyl at FULL occupancy, so
case A is invisible to an occupancy test there (round 41). `pipeline.Result`
gained a `meta` field, merged into the drawn structure's metadata, which is how
a stage hands the viewport something no coordinate implies — the pie spheres
render from `metadata["site_occupancy"]` with no new drawing code. `cif.expand`
gained `report["site_of"]` (informational only) so a caller can ask what a
drawn atom's occupancy was without re-deriving the expansion. 1021 tests.

Round 45d (2026-08-06, the SANDBOX rewritten — completion instead of
relocation): Christian found the thing that had been bothering him, on
`242083.cif` (two C60 + four Ni units + four chlorobenzenes, 312 atoms). After
Wrap the picture matches VESTA exactly. At **Molecules** the four
quarter-fullerenes sitting on the c-edges collapse into ONE fullerene hanging
out of the box — and he is right that this is the wrong picture. The
measurement: those four blobs are ONE C60 that the atom-by-atom wrap tore into
four corners, 102 atoms move, and the count is unchanged. `unwrap_molecules`
makes each fragment CONTIGUOUS and shifts it so its centroid is inside, which
preserves the cell content exactly (312 = Z formula units, what the ❖ count,
the density and the export all need) — **but once the molecule has moved it is
no longer ON a face, so `boundary_images` has nothing to repeat for it**, and
one fullerene gets completed where five belong. That is the whole bug: the
relocation defeats the completion that follows it. Measured consequence:
`Fragments` and `Complete` add exactly 0 atoms on that file, precisely because
Molecules already relocated everything. So the SANDBOX was emptied of the
round-45b/c experiment (overcomplete duplication, flat cuts, offsets, shifts)
and rebuilt on his stated intuition: "if wrap is the correct placement of sites
without atoms outside the boundary, then molecules should complete all four
quarter fullerenes". Stages are now Cell / Sites / Operators / Wrap / Dedupe
(all `pipeline.run`'s own) then **Bonds** — connectivity from the labelled
PERIODIC graph, drawn only where both ends are in the cell, because the wrap
tears molecules and straight-line bonds on wrapped coordinates are simply
wrong — then **Molecules**, Mercury's packing rule: every fragment with an atom
in the cell drawn WHOLE, nothing relocated. Result on 242083: **876 atoms, 5
fullerenes, 12 + 12** — byte-identical to `expand(shell_molecules=True)`, which
is the existing ❖ checkbox, reached by a completely different route. Ferrocene
210 / 10 molecules, H2bdc 72 / 4, 4-ABA 376 / 16. **Open and deliberate: a
periodic component has no "whole" to complete**, so ZIF-8 and ZnO keep only
their in-cell atoms and the trace says so. `complete_molecules` pools its
candidate translations PER AXIS over the whole group against the CLOSED cell —
the first cut used `-floor(x)` per atom, which never proposes the +1 image for
an atom at exactly 0, so a molecule on the origin corner drew once instead of
eight times (round 43b's lesson, re-learned). 1016 tests.

Round 45b (2026-08-06, the SANDBOX page — someone else's algorithm): a 🧪 tab
next to 🐞, for Christian to "experiment if I can come up with a different
algorithm that I can fully comprehend/survey". Nothing the app draws goes
through it. Cell / Sites / Operators are the debug page's stages by CALLING
`pipeline.run`, so the part not under experiment cannot drift; the divergence
is one stage, **Duplicate**: instead of wrapping, repeat every atom at a
lattice offset so the representation is OVERCOMPLETE and prune later. His
words were "duplicated at (x+1,y+1,z+1)", and **measuring first showed that
alone cannot work**: a diagonal shift never produces the image that needs +1
on ONE axis, so on `SodiumNicotinate.cif` it reaches 76 of the cell's 172
atoms — and since this scheme only ever widens, the missing 96 can never be
pruned back in. So the offsets are a visible CHOICE (diagonal / {0,1}^3 /
{-1,0,1}^3, 400 / 1600 / 5400 atoms) defaulting to what was asked for, and the
trace states its own coverage: the page is for judging an idea, so it has to
be able to say the idea is incomplete. `_coverage_lines` measures against
MoloM's own wrapped-and-merged content atom by atom. **`pipeline.
operator_images` is shared and returns FRACTIONS**, which is not fussiness: the
first cut had the sandbox convert `base.coords` back through the cell matrix,
and an exact 0.0 or 1.0 came back an epsilon off, so the "inside the box" count
read 190 where an independent measurement said 200. `PipelinePage` in
`ui/debug_page.py` is now the shared base (load / text / trace / freshness) with
an `extra_controls` hook. Both pages own ONE scene object between them —
alternative algorithms for the same thing, and seeing both at once is a picture
of neither.
**Two more stages (same day): Bonds and Prune.** Bonds is a HARD flat cut —
Christian's "2.6 A, anything higher is no longer a bond" — with no radii and no
chemistry, deliberately, so the picture is a property of one number. Non-
periodic on purpose: every atom is an individual in space, which is coherent
precisely because the duplicate stage already materialised the partners. Prune
is Mercury's rule as the first NARROWING step: drop every fragment with no atom
inside the cell. **Measured, and it decides the whole idea: 2.6 A is too
generous by a mile.** Two atoms either side of a bond angle sit at ~2.4 A, so
above ~2.3 A every 1,3 pair becomes a bond, the structure percolates into ONE
fragment and Prune has nothing to discard — on `SodiumNicotinate.cif` at 2.6 A
it is 1 fragment, 1600 of 1600 atoms kept, 860 of 1436 bonds 2.0 A or longer,
88 of them H-H. Below the threshold the idea works exactly as he described:
at 1.7-2.2 A it gives **224 fragments -> 42 kept -> 376 atoms**, all 172 cell
atoms plus the fragments that reach in from outside. So the cutoff is a spin
box next to the offsets, defaulting to the 2.6 A asked for, and the trace
prints a bond-LENGTH HISTOGRAM plus the count of bonds 2.0 A and over, because
that band is the whole diagnosis. **`prune_to_cell` needs a boundary
tolerance**: a symmetry operator produces an exact 0 as `-0.0`, a bare
`x >= 0` calls it outside, and an isolated Na (isolated once the cut excludes
Na-O at 2.4 A) then loses its whole singleton fragment — 171 of 172 until the
tolerance went in.
**Round 45c, same day — the sandbox grows the real bond rule.** Christian
pushed back on the metal-metal claim and was RIGHT: MoloM draws no Zn-Zn in
MOF-5 (Zn radius 1.18 gives a 2.81 A window against a 3.18 A contact), so
"metal-metal stays covalent so a Zn4O cluster survives" was wrong as stated —
the reason `bond_kind` keeps it covalent is FRAGMENT CUTTING, not drawing. But
metal-metal bonds do get drawn elsewhere: **8 of 36 files**, including 8 Na-Na
at 3.4296 A in `SodiumNicotinate.cif` (Na radius 1.55 -> a 3.55 A window,
uncapped because metals have no `MAX_COVALENT`). He noted VESTA draws none,
even for lithium. So the sandbox gained: the **real MoloM rule** as the default
bond mode (flat cut kept as the alternative), an **exclude metal-metal** tick,
a **shift by a vector in cell units** tick, and — added because measuring
showed the first two do not achieve the goal — **fragments over covalent bonds
only**. That last one is the lever: sodium nicotinate is a COORDINATION
POLYMER, one component through 594 Na-O bonds, so Prune discards nothing until
the fragment walk is restricted (round 38's rule). Measured on that file at
2x2x2: flat 2.6 A -> 1600 atoms 1 fragment; MoloM rule -> 1600, 1 fragment;
+ no metal-metal -> 1600, 1 fragment; **+ covalent fragments -> 376 atoms, 224
fragments, 42 kept, covers 172/172** — the complete cell plus the fragments
reaching in, which is exactly the baseline he described. **Also: the file's own
`_geom_bond_` loop is NOT read and could not be trusted verbatim** — it lists
Na...Na 3.43 A and Na...C 2.78 A as bonds, and `publ_flag` cannot filter them
(a carboxylate C-O at 1.2586 A is flagged `?`). Its third column IS the n_pqr
code though, i.e. a ready-made labelled graph, so it is worth a tier one day.
**Bug worth remembering: `for shift in shifts` shadowed the `shift` PARAMETER**,
so every atom was translated by the last offset (1,1,1). The trace agreed with
itself because the coverage check shifts its reference by the same vector; only
an outside measurement caught it (coverage 16/172 where the note said 172/172).
1021 tests.

Round 45 (2026-08-06, the DEBUG page — the pipeline one stage at a time):
Christian, straight after round 44: "I want to try an iterative debugging
approach that necessitates my step by step understanding of how unit cells are
drawn." A sixth properties tab (🐞) where a CIF is loaded AS TEXT and a row of
eleven buttons runs the pipeline up to that stage and no further. **The contract
is that a stage is a PURE FUNCTION of (text, stage index)** — every click
rebuilds from the text, the previous debug object is thrown away, and nothing
carries over; a picture that could contain leftovers from a previous click is
not evidence. Tested as such: run stage 9 (516 atoms on ZIF-8), then stage 2,
and get 9 atoms. `core/pipeline.py` is UI-free and its stages 2-5 are
**`cif.expand`'s own flags** rather than a reimplementation, so the page cannot
describe a pipeline the app does not run — pinned by a test asserting the last
stage equals an ordinary import plus its `BoundaryModifier`. Stage 1 is the
cell box with NO atoms and stage 2 the raw `_atom_site_` rows with no symmetry
and no bonds, which were Christian's two requests; the rest follow the real
order. **The symmetry step is split three ways** — Christian spotted it doing
more than it says on `SodiumNicotinate.cif`, where 24 of 25 sites are written
with NEGATIVE fractional coordinates and yet the structure lands inside the
box: `Operators` is `x' = Wx + w` alone (25 x 8 = 200 atoms, **132 of them
outside [0,1)**), `Wrap` is `x - floor(x)` (the step that actually fills the
box, and it wraps ATOM BY ATOM, which is why molecules are torn until the
Molecules stage), `Dedupe` is the 0.1 A minimum-image merge (**-28**, leaving
172). Only Dedupe corresponds to a `cif.expand` configuration; the first two
are its inner loop split open, so a test pins Dedupe to `expand`'s own output.
The Dedupe note prints the **per-site multiplicity breakdown**, which is the
cheapest correctness check there is: 19 general positions, 5 special
(multiplicity 4), one site contributing NOTHING — a symmetry-redundant row,
the urea N1/N1C pattern that makes pymatgen report occupancy 2 — and a warning
if any multiplicity fails to divide the operator count.
Two details worth keeping: **the camera is not re-fitted between stages**
(comparing two stages means seeing the same view twice) but IS fitted once per
file, and it frames the **cell corners as well as the atoms**, because stage 1
has none and `fit_view` would otherwise fall back to a 1 A radius at the origin
and leave a 17 A box off screen. The nine buttons sit in a **wrapping** flow
layout, not a QHBoxLayout — the dock is narrow and refuses horizontal
scrolling, so a plain row would push the last stages off the edge with no hint
they were there (the round-21 lesson). The page also prints a per-stage TRACE
(atoms, bonds, and what each step did — how many duplicates the operators
merged, what the disorder policy dropped, how many edges cross a cell face,
the component ranks), which is most of the value on a file you are arguing
with. 1003 tests.

Round 44 (2026-08-06, the LABELLED PERIODIC BOND GRAPH — stage 4 at last):
Christian brought a written CIF-visualisation spec ("I am no longer confident
our visualisation algorithm is mathematically sound and chronologically
logical") and asked whether it changed anything. It did, in two places, and
both were MEASURED before a line was written — as MoloM against MoloM, so the
same bond rules ran on both sides and only the architecture was under test.
The metric: does the drawn coordination match a 3x3x3 supercell of the same
cell, where the central cell's atoms have a complete environment? **10 of 36
files. The sharpest failure was the spec's own regression test: every Zn in
ZIF-8 drawn 3-coordinate, 12 of 12**, and on ZIF-4/7/62/67/zni/qtz too.
**Two independent faults, neither of them the one first suspected.** (1)
**Clip-then-bond.** Bonds were perceived from CARTESIAN coordinates after the
structure had been clipped to the cell, with `boundary_images` and
`BoundaryModifier` patching afterwards. An atom lying exactly ON a face is
drawn twice, once per face — which is the right convention — and the two
copies then SPLIT one coordination sphere between them. Traced on ZIF-8's Zn0
at frac (0, 0.25, 0.5): four N at 1.982 A under the minimum image, only two of
them near in a straight line, and the modifier patching one back. More
boundary shells could not fix it (2 and 3 give byte-identical output) because
the ATOMS were there all along; it was the bonds that were missing. Note the
first hypothesis — `covalent_only` excluding the Zn-N coordination bond — was
WRONG, and testing it cost one command: `covalent_only=False` gives identical
output on all 17 files tried. (2) **`periodic_pairs` used the minimum image
unguarded.** That convention is valid only while the cutoff is under half the
smallest PERPENDICULAR width (not the smallest EDGE, the tempting mistake in a
skewed cell), and it can never return more than one bond per pair of indices
nor any bond from an atom to its own image. Six of 37 files violate the guard
and five lose bonds against brute force: **alpha-iron 1 bond where there are
8**, ZnO 4 of 8, 2108327 7 of 29, 2106093 30 of 50, 1547149 8 of 14. Worth
knowing that NO ZIF is affected — their cells are 11-17 A perpendicular
against a 2.8 A cutoff — so the spec frames this as a framework hazard and on
this machine's files it is a dense-inorganic one. **New `core/bondgraph.py`**:
`Edge(i, j, shift, dist)` where the shift IS the CIF `n_pqr` code, built over
the translation shell derived from the perpendicular widths, with the
chemistry unchanged (the same `bonding.prune_pairs`, plus a periodic hydrogen
cap, because the molecular one measures straight lines from a coordinate array
and here the partner is in the next cell). `PeriodicGraph.instantiate` is
stage 5 and a pure LOOKUP: each drawn atom is labelled `(content index,
lattice shift)` by `label_instances`, so a face atom's two copies carry
different shifts and each gets its OWN complete sphere. Measured after:
**stage 4 reproduces the complete-environment coordination on 34 of 36 files**
(the two exceptions are ZIF-8's and ZIF-67's disordered methyl hydrogens,
round 41's open issue, where the valence cap picks between over-provided H),
and **every framework metal draws 4-coordinate with the component correctly
rank 3**. ZIF-8 went from 18 mismatched atoms to 4, all hydrogens.
**`missing_partners` is the bounded grow**, and WHICH bonds it may follow is
the whole difficulty — both rules were re-learned rather than reasoned out. A
covalent bond is followed only if it involves a NON-METAL (round 42b: metal-
to-metal is covalent by design, and following it buried Ni6Sn8's cell); a
COORDINATION bond only if the partner belongs to a covalent fragment of more
than one atom, because `bond_kind` deliberately does not distinguish Zn-N from
Na-Cl and the partner's own fragment is what separates a ZIF's imidazolate
from rock salt's lone chloride. **Packing was stacking duplicates**: each cell
carried its own boundary copies and the copy on a shared internal face is the
same atom as its neighbour's, so ferrocene's 2x2x1 drew 1680 atoms with 1680
coincident pairs — every atom twice. De-duplicated, NaCl's packings come out
as the textbook grid, `(2na+1)(2nb+1)(2nc+1)`: 27, 45, 75 where the old code
said 27, 54, 108. Three tests pinned those wrong numbers and were updated —
round 38's lesson again, that a fixture is the first casualty of a rule about
what is real. 984 tests.

Round 43 (2026-08-05, the refused-bond override — closing round 42d's last
gap): round 42d ended with VESTA drawing the contacts we refuse, so its cages
read as solid polyhedra while ours were clouds of spheres in the right places.
This is the tick that closes it, and it is deliberately a **VISUALISATION
override**: MoloM's rule that only a real bond is drawn as a bond does not
change, the user just gets to break it on purpose. **Christian's own wording
was "tick impossible bonds", and measuring first showed that would not have
worked** — on `2240539.cif` the refusals are 432 over-valence against only 96
impossibly short, so restoring the short ones alone leaves the picture broken.
The tick covers everything `prune_pairs` refused. `bonding._refused_display`
returns them as a drawable pair list in `report["refused"]`, stored at import
as `metadata["refused_bonds"]` and gated by `metadata["show_refused_bonds"]`
(the `polyhedra` pattern — per-object display state in metadata rides undo and
savepoints for free, no `Scene.snapshot` four-place checklist). **The hydrogen
cap still applies**, and that is the one genuinely subtle part: capping the
kept list and the full candidate list SEPARATELY picks different partners for
the same hydrogen — a hydrogen's nearest neighbour among all candidates is
often one of the impossible contacts — so their union hands it two sticks. 240
refused bonds that way against 144 done properly, with 96 double-bonded
hydrogens. Capping the refused list AGAINST the kept one, nearest first, is
what makes the union honest. Costs nothing either: capped and uncapped give
the SAME four 70-atom components (368 sticks against 752), which are exactly
the four F-centred lattice points round 42d measured. Measured end to end —
77 components with the tick off, 25 with it on (four cages of 70 plus 21 loose
atoms), and the GUI grab with hydrogens hidden is a scatter of dots before and
VESTA's cages after. Drawn **thinner (0.45x) and blended halfway to grey**
(`style.muted`, `REFUSED_BOND_*` — in `core` so the viewport and the Blender
export cannot drift), because a figure made with the tick on must not assert
chemistry nobody believes. They ride the ORDINARY cylinder buffer, not a pass
of their own: they are scene geometry, and only overlays need their own
buffers (round 35). The export carries them into Blender under their own
`MoloM C refused` materials so they stay adjustable as a group; verified by
running the script in Blender 5.1 headless. The ❖ tick greys out and reads
"Show refused bonds (144)" so a molecule with nothing refused cannot offer a
live-looking control that does nothing.

Round 43e (2026-08-06, round 43d's asymmetric-unit editing actually working):
Christian: "Editing asymmetric units does not work at all... When I change one
of the Zn in the asymmetric unit to Co I am told that the re-derived space
group is P1, which is obviously incorrect." Right twice over, and the second
half is the deeper one. **(1) The re-derivation fired while the base WAS the
asymmetric unit.** Round 43d guarded on "is there a `SymmetryModifier`?", and
the ❖ page's own "Asymmetric unit only" radio — the route he took, and the
obvious one — rebuilds the base and adds no modifier at all. spglib then
answered P1 perfectly correctly about 22 atoms alone in a box and overwrote a
real Pbca. `base_is_asymmetric_unit` tests BOTH routes, and re-derivation is
now restricted to the full cell exactly as he asked. The chemistry agrees:
changing one Zn to Co in the asymmetric unit changes all EIGHT of its images
together, so the operators still map the structure onto itself and the group
is untouched — the re-derivation was not wrong, it was asked the wrong
question. **(2) Nothing wrote the edit back**, so the next rebuild regenerated
from the file's own `asym_symbols` and "the Co switches back to Zn".
`sync_asymmetric_unit` writes symbols and fractional coordinates back whenever
the base is the asymmetric unit, which is what makes the edit persistent;
parallel columns (occupancy, disorder group/assembly) are reset rather than
guessed at when the atom count changes, because a silently mis-indexed
occupancy is worse than none. Measured end to end: asym Zn->Co keeps Pbca with
8 operators, the full cell comes back **Co 8 / Zn 8**, and switching back to
asym still shows the Co. **(3) The cell box crept**, which is his "small
re-scaling of the unit cell boundary". `cell_pose` is a Kabsch fit against a
SAMPLE OF THE ATOMS (round 19), and an edit is not a rigid motion — so moving
an atom that is in the sample makes the fit report a rotation nobody
performed, and the box follows it a little further with every edit. Two parts:
`begin_model_edit` captures the pose BEFORE the atoms move (the viewport
already calls into it, so this costs nothing), and the write-back re-pins the
reference against the CELL-frame coordinates so the error cannot accumulate.
A test drives six consecutive edits and pins the box to 1e-6. Measured
separately and worth recording: a, b, c, the box origin and its orientation
are identical across import -> asym -> edit -> cell on 2130205 and 2478154, so
the box GEOMETRY never changed — what he saw was the drift plus a full cell
that, once the group was P1, drew only the asymmetric unit inside a
correctly-sized box. **Also new: `core/coplanar.py`** — "if I add a substituent
to an imidazolate ring, the substituent is coplanar with the plane". The
selection says WHICH GROUP via `internal.torsion_split` (round 36), so any
atom of the substituent gives the same answer, and the group then moves
RIGIDLY: swing the attachment bond into the ring plane, then spin about it
until the group lies flattest. **Never a projection** — flattening by
projecting onto the plane shortens every bond that was out of it, giving a
coplanar and chemically wrong answer. The spin has a closed form
(`t = (atan2(B, (C-A)/2) + pi) / 2`, one atan2, and the `+ pi` is what picks
the minimum rather than the maximum). Measured: a planar substituent reaches
**exactly 0** out-of-plane rms with every bond length preserved to 1e-9 and
the ring untouched; an sp3 methyl cannot be flat and correctly puts its
ATTACHMENT atom in the plane instead, which the status line says out loud.
963 tests.

Round 43d (2026-08-06, unit-cell edits that persist, symmetry kept honest):
Christian's spec, both halves. "I want to be able to change the asymmetric
unit and have the change repeated while the space group is kept constant. If
the full cell is edited, then the space group has to be reevaluated or set to
triclinic because the symmetry has been broken." **Which half applies is
decided by whether a `SymmetryModifier` owns the expansion**, which is the
distinction that makes this coherent rather than two features fighting. With
one, the base IS the asymmetric unit (round 29's bargain), every edit is
repeated by the operators and the space group is an INPUT that must not be
touched; without one, the base is the full cell, so an edit really does break
the symmetry. `F3 > Crystal: edit the asymmetric unit` gets you from an
ordinary .cif import (whose base is the whole cell) to the first state:
`enable_symmetry_editing` REDUCES the base first — to the file's own
asymmetric unit where it was stored, otherwise to one atom per symmetry orbit
— because adding the modifier on top of already-expanded atoms is the round-32
trap. Measured: 176 base atoms become 22, the picture stays at 176 drawn, and
moving ONE asymmetric atom moves exactly 8, one per operator. The other half
is new machinery: **`spacegroups.from_structure` is the first thing in that
module that reads symmetry off ATOMS instead of off a name**, via spglib's
dataset, with `orbit_representatives` for the reduction. It runs on every edit
commit (`_reevaluate_edited_crystal`) and is also an explicit F3 operator.
Two rules keep it from doing harm: an UNBROKEN cell returns None and is left
alone (a control that fires when nothing changed would rewrite the file's own
setting with the database's spelling — `P 1 21/n 1` silently becoming
`P2_1/c`), and a structure with a symmetry modifier is skipped entirely, or
re-deriving from a lone asymmetric unit would collapse a perfectly good
structure to P1. **The hazard that made it return None on every real file**:
a drawn crystal carries boundary copies, which wrap onto atoms already
present, and spglib refuses a cell that lists the same site twice — measured
as None for 7712836 (999 atoms), 2240539 (980) and 2478154 (28) while giving
the file's own group for all three on their content alone. `content_subset`
reduces to one atom per distinct site on a rounded grid, probing the 27
neighbouring buckets because a single key splits two copies that straddle a
bucket edge (222 true sites came back as 225 at grid 1000 and correctly at
100/200/500/2000 — an arbitrary-grid coin toss, and three phantom sites are
enough to lose the whole search). Element is part of the key, so a shared site
(round 42) is never collapsed. Verified across every CIF on this machine:
**12 of 12 reproduce their own operator count from coordinates alone**, and
the content reduction recovers the exact cell content every time (280, 222,
16, 6, 42). 947 tests.

Round 43c (2026-08-05, the exterior control: lossless and orientation-free):
two more of Christian's, both about atoms appearing and disappearing when
nothing chemical changed. **(1) The rebuild resolved the disorder differently
from the import.** `build_view` reconstructs a `CifData` from what the object
stored, and it passed the occupancies but NOT the `_atom_site_disorder_group`
and `_atom_site_disorder_assembly` columns — which `resolve_disorder` prefers
over geometric overlap. So the first touch of any ❖ control silently
re-resolved the structure: on `7712836.cif` 222 content atoms became 294 and
999 drawn became 469, which is exactly "when it is unticked again, even more
atoms disappear". The columns ride in metadata now
(`asym_disorder_groups`/`_assemblies`) and both rebuild paths take them from
ONE helper, `_view_disorder_kwargs`, because the two paths disagreeing is the
whole failure mode. **(2) The checkbox was driving two mechanisms that mean
different things.** `_autoclose_boundary` adds the BoundaryModifier at import —
a correctness fix a framework needs whether or not anyone wants neighbouring
molecules drawn — and set `cell_exterior = 1` with it, so the box read TICKED
over a picture containing no shell at all. The first untick then disabled a
modifier the user had never enabled. The modifier is left alone by this
control now (it lives on the Modifiers page); the checkbox means one thing,
"draw the neighbouring cells' molecules". Round trip measured lossless:
999 -> 999 -> 999. **(3) Nothing cell-based was invariant under rotation.** A
cell is stored as lengths and angles, so `cell.matrix()` is built in a
canonical orientation and every fractional calculation assumes the atoms are
still in it — rotate `2130205.cif` and the drawn count went 216 -> 230, 276,
246 at 10, 37 and 90 degrees with nothing else touched. `MolObject.cell_pose`
recovers the rigid motion from the SAME reference sample the cell box follows
(round 19), `evaluate_stack` hands it to any modifier declaring `wants_pose`,
and `BoundaryModifier` un-poses, works, and re-poses. Opt-in on purpose: an
ArrayModifier's offset is a WORLD vector and must not be reinterpreted in the
cell frame. Also fixed alongside: a crystal rebuild regenerated coordinates as
`frac @ matrix`, i.e. in the file's pose, so touching any ❖ control snapped a
rotated crystal back — `_rebuild_pose`/`_apply_rebuild_pose` carry it, and the
cell reference is re-pinned against the CELL-frame coordinates (`
set_cell_reference(s, coords)`) because pinning it against the posed atoms
would make the fit the identity and draw the box square-on around rotated
atoms. 935 tests.

Round 43b (2026-08-05, "only one third of the CH polyhedra are shown"):
Christian put the override next to his VESTA export and counted. He was right,
and the arithmetic says exactly how right: the four cages sit ON the F-centred
lattice points, so the one at the origin belongs to all EIGHT corners and each
face-centred one to two opposite faces — **14 images, and MoloM drew 4**, which
is his one third. Three independent faults, all of them round 42d's geometric
grouping not having been carried far enough. (1) `expand`'s BOUNDARY branch
called `fragment_info` without `geometric=wholly_disordered` — the
`shell_molecules` branch six lines below it had it, and `unwrap_molecules`
above it had it, so this was a plain omission. On the chemistry graph the file
is 140 singletons and 70 pairs, so the 18 atoms lying exactly on a face carried
a two-atom shard each instead of their 70-atom cage: 21 atoms added rather than
700. (2) `_reaches_into_cell` perceives its own bonds and was doing it with
`sanity=True`, so each cage copy shattered and the shards that happened to lie
outside were culled INDIVIDUALLY — the copies came back as 45-, 19-, 18- and
17-atom stumps with centroids at 0.93 instead of on a lattice point. It takes
`geometric=` now, and it matters more here than anywhere else because this
function decides what survives. (3) With both fixed the count went 4 -> 13, and
the missing one was the (1,1,1) corner: `boundary_images` derived its lattice
shifts from the TRIGGERING ATOM, and the corner cage has atoms on the x, y and
z faces but **none with all three coordinates at zero** (measured: 6 atoms with
two coordinates on a face, 12 with one, none with three). Per-atom shifts can
therefore reach three faces and three edges but never the far corner. The
options are pooled over the whole group now — for a FINITE group only; a
periodic component still travels atom by atom, which is what keeps rock salt at
eight corner sodiums instead of a slab. Result 4 -> **14 complete 70-atom
cages, 8 corners + 6 face centres**, 980 atoms, no truncated fragments.
**Blast radius measured, not assumed**: every CIF on this machine expanded
before and after, and `2240539.cif` is the ONLY file whose count changes —
cell CONTENT is identical everywhere, including the 999-atom 7712836, ferrocene
and the solid solution. 928 tests.

Round 42 (2026-08-05, VESTA's occupancy pie spheres): a correctness fix with a
rendering feature on top. `1547149.cif` puts **Nb 0.50, Ti 0.25, Ni 0.15 and
Co 0.10 on ONE position** — a substitutional solid solution, and the file
names itself `Ni0.15Co0.1Ti0.25Nb0.5O2`. MoloM drew pure Nb, and not by
policy: all four sit at (0,0,0), so `expand`'s minimum-image de-duplication
threw three of them away **before occupancy was ever consulted** (`POLICY_ALL`
gave the same six atoms, which is what proves it was the dedup and not the
round-38 disorder resolution). A rendered composition the file never claimed,
with nothing anywhere to say so. `cif.shared_sites` / `site_composition` keep
the group — grouped at the SAME tolerance the de-duplication uses, so it
describes exactly the atoms that merging would otherwise discard — and
`expand` reports `site_occupancy` keyed by DRAWN atom index. Two things that
had to be right: the mapping is built at the very END (everything above drops
atoms and renumbers), and boundary/exterior copies **inherit** their source's
composition by matching fractional coordinates modulo 1, or the cell shows one
pie sphere at the centre and eight plain ones at the corners. `style.
occupancy_wedges` turns a composition into cumulative boundaries, normalised
against the site's OWN total (a site refined to 0.97 is rounding, not 3%
vacancy) and always padded to a fixed four so the instance stride is constant.
Rendering is a **second pass at `GL_LEQUAL`** over the ordinary spheres: same
mesh, same model matrix, so every fragment lands at exactly the same depth and
the wedges win on equality — no polygon offset, no z-fighting, and the atom
stays an ordinary atom to picking, selection and the selection hull. Its own
program and its own buffer, never the scene's (the round-35 flicker bug).
**Christian's precedence rule**: a colour set in the outliner WINS and the
atom draws solid, because painting an atom yourself is a deliberate statement
about that atom while the wedges are derived from the file. The ❖ page gets an
"Occupancy pie spheres" checkbox and prints the composition as a Shared site
row — one line per DISTINCT composition, not one per symmetry image. 909 tests.

Round 42d (2026-08-05, group by GEOMETRY, draw by CHEMISTRY): Christian read
VESTA's behaviour off its own outliner and got it exactly right — "VESTA
acknowledges these bonds between partial occupancy positions and uses them for
visualisation/connectivity, while not listing them as atom types". Our own ❖
page was already saying the same thing from the other side: **474 impossible
bond(s) dropped** on `2240539.cif`. Round 38's sanity filters reject a contact
shorter than 0.65x the covalent radii, and the alternatives of a disordered
site are by definition closer than that — so the chemistry graph shattered
that structure into 134 loose atoms and 73 pairs, nothing could be completed
at a cell face, and the corners showed fragments where VESTA shows a
polyhedral ball. Measured: the SAME atoms grouped on raw proximity give
exactly **4 components of 70 atoms**, which is the four F-centred lattice
points of Fm-3m — VESTA's picture precisely. Hence the rule: **the sanity
filters decide what to DRAW, never what belongs TOGETHER.** `fragment_info`
and `unwrap_molecules` take `geometric=`, and `expand` turns it on for the
wholly disordered case. It is NOT the default, and the discriminator is
occupancy: round 38's HpPyBz fault is a spurious 0.75 A contact between two
FULLY occupied molecules, and grouping geometrically there re-fuses two
separate molecules — the suite caught exactly that regression when the change
was first made unconditionally, which is why it is narrowed. Christian also
found that **2240539 breaks Mercury outright** (it will not open the file),
which retrospectively justifies picking VESTA as the ground truth. ~~STILL OPEN
on that file: VESTA also DRAWS those contacts, so its cages read as solid
polyhedra while ours are clouds of spheres in the right places.~~ **CLOSED in
round 43** by the ❖ page's refused-bond tick — as an OVERRIDE, so the rule that
only a real bond is drawn as a bond is untouched.

Round 42c (2026-08-05, the sweep's second pass — Christian's screenshots):
the first sweep framed every render on the CELL BOX, which cropped exactly the
atoms that were the bug. Christian spotted triazoles floating a cell away from
`Cu_trz_tet`, magnesiums above `H2Mg2O8P2` **with completion switched off**,
and a unit cell that FLIPPED when he deleted them. Re-rendered with `fit_view`
(his suggestion: press F), an objective test — "does any bonded fragment lie
entirely outside the cell?" — found **9 of the 37 files** drawing orphans.
Four faults, each fixed at its own level. (1) `boundary_images` carries an
atom's whole MOLECULE (round 33), so a molecule stored SPLIT across a face
gets translated bodily and its far half lands a full cell further out — that
is round 39's "walk it contiguous first" lesson in a new place, and it put two
Mg at z = 1.94. Rather than patch each producer, `_reaches_into_cell` applies
the rule both reference viewers state outright — Mercury includes a molecule
when ANY of its atoms is in the cell — as a final filter over COPIES only, so
Z and the ❖ count are untouched. It must **iterate to a fixed point**: removing
a fragment orphans whatever hung off it, and 2240539 still had 12 lone
hydrogens after one pass. (2) **The cell box flipped on deletion** because it
is carried by a Kabsch fit from reference atoms held as INDICES, and
`delete_atoms` renumbers: the indices stayed valid and quietly came to mean
different atoms, so the guard for out-of-RANGE indices never fired.
`edits._remap_cell_reference` remaps them like the bonds, and clears the
reference below three points rather than fitting an under-determined rotation.
(3) **Disorder resolution was splitting symmetry orbits.** Two overlapping
atoms from the same site are images of one another under the space group, so
keeping some and dropping others leaves a structure that does not obey its own
symmetry; `resolve_disorder` now takes `sites` and never separates them.
(4) `2240539.cif` — Christian's blocker — is a **plastic crystal**, one
molecule smeared over 192 operations of Fm-3m with all five sites at occupancy
0.21-0.43. With no fully occupied site there is no ordered skeleton to resolve
against, nothing is dominant, and greedy resolution produced a 184-of-280
chimera that rendered as a blob where VESTA shows a neat array of cages.
`expand` now detects the wholly-disordered case and draws the smear, which is
what VESTA, pymatgen and ASE all do: 280 atoms, exact. Afterwards **no file
draws an orphan fragment in either mode**, and cell content is unchanged
everywhere. NOTE ON FIXTURES: Christian's set is largely CCDC data and may not
be redistributed — two COD files are vendored, the rest of this round is tested
as rules rather than files. 918 tests.

Round 42b (2026-08-05, the 37-file VESTA sweep): Christian exported all 37
test CIFs from VESTA down every cell axis and asked for every discrepancy
addressed. Two sweeps were run. **Numerically**, against pymatgen, ASE and
each file's own formula x Z: every count difference from the two reference
readers is OUR DISORDER POLICY and nothing else — `POLICY_ALL` reproduces
pymatgen and ASE atom-for-atom on all six files that differ (2240539 280,
4118335 74, ZIF-62 368, 2370019 20, ZIF-7 585, ZIF-67 348), and on ZIF-67
formula x Z agrees with US rather than with them. **Visually**, all 99 views
were re-rendered from MoloM at the same axes and composited side by side,
which found three real faults. (1) The occupancy wedges split around the
world Y axis, so from exactly the axis views a crystallographer uses they
showed edge-on as slivers; the pie now faces the CAMERA (`atan` of the
view-space normal's x/y), which is what VESTA does and where the composition
most needs to be legible. (2) A one-atom component was being completed as if
it were a molecule, so BaLiF3 grew 15 -> 25 atoms — round 33's NaCl lesson one
function further out, now guarded in `exterior_molecules`. (3) The exterior
shell followed metal-to-metal bonds, which `bond_kind` calls COVALENT on
purpose (round 38, so an SBU is not dissected) — right for typing a bond and
wrong for growing a shell, because an intermetallic is metal-bonded in every
direction: Ni6Sn8 went 28 -> 55 atoms and buried a cell VESTA draws bare. The
shell now follows covalent bonds **involving a non-metal**, which is what
separates a ZIF linker from an intermetallic. The checkbox also stopped
conflating two mechanisms: `shell_molecules` (VESTA's default picture) is now
a separate parameter from `exterior` (round 35's explicit bonded shell), which
is why the round-35 tests kept passing throughout. Result per structure type,
measured: lattices and perovskites unchanged, molecular crystals x1.98,
frameworks x1.09-1.28. **Still open**: on a few files (4118335, Cu_trz_cub,
2240539) the molecule completion is more generous than VESTA's, because VESTA
wraps atoms individually and we wrap by molecule, so "which copies reach in"
is not the same question in the two programs.

Round 41 (2026-08-05, VESTA comparison + the crystal page grows up): Christian
exported all 37 test CIFs from VESTA down every cell axis and annotated three
against MoloM. **His diagnosis of `4-ABA-oxime.cif` was exactly right.** The
file writes a methyl DISORDERED OVER TWO ORIENTATIONS at full occupancy —
occupancy 1.0 on every site, no disorder group, no `_atom_site_occupancy`
column worth the name — so one carbon carries four to six hydrogens at
0.88-1.04 A plus its ring carbon at 1.497 A. Round 38's valence cap then has
to drop something, and it dropped **LONGEST FIRST**, which is the C-C: a
textbook single bond sacrificed to keep a fourth hydrogen. The methyl became a
loose fragment sitting inside the cell, so round 33's whole-molecule boundary
completion treated it as its own complete molecule and never carried it out —
which is precisely the visible difference from VESTA, where the molecules run
past the cell edge. `bonding._removal_order` now sends a bond that is some
atom's LAST link to the heavy-atom skeleton to the BACK of the queue. Nothing
else changes: a spurious long C...C on a carbon with other heavy neighbours is
not a last link and is still dropped first. Methyls come back as 3 H + the
ring bond, molecules complete across the boundary again. **Still open there**:
the surplus disorder hydrogens are now bonded to nothing and float as loose
white spheres (36 of them in that cell), because dropping the BOND does not
drop the ATOM. Resolving undeclared disorder geometrically would fix it — and
measured across all 37 files, `4-ABA-oxime.cif` is the ONLY one with
same-element atoms inside `DISORDER_RADIUS` that the file does not declare, so
the blast radius is one file — but on that carbon only two of its four H pairs
overlap, so a naive sweep leaves a 2-hydrogen methyl. Needs a decision, not a
patch. **The "bonded atoms outside the cell" tick really did nothing** on all three
of his files. Round 39 had repointed the checkbox from round 35's
`cif.bonded_exterior` to the `BoundaryModifier`, which by design closes only
COVALENT bonds crossing a face — a molecular crystal has none once it is
unwrapped and an oxide's are ionic, so the modifier was right and the control
was dead. But the deeper reason the picture differed is that **VESTA wraps
atoms INDIVIDUALLY and completes each molecule outwards, while MoloM wraps by
MOLECULE** (round 19, so a fragment is never cut in half) — which pulls a
straddling molecule bodily inside instead of drawing it half out, and leaves
the box with no context around it. `cif.exterior_molecules` states Mercury's
packing rule directly: draw a molecule if ANY of its atoms falls inside the
closed cell, including its copies in the 26 surrounding cells. Periodic
components are skipped (every shell of a framework looks as unfinished as the
last — that is the modifier's job). The checkbox now drives both mechanisms
and rebuilds through the same path the asym/cell/packing switch uses, so
turning it off restores exactly the previous atoms: 4-ABA 200 -> 404,
242083 510 -> 876, 1547149 15 -> 23, and the render matches Christian's VESTA
export of the same file. **VESTA also settles the 4-ABA question**: its
methyls carry every disorder hydrogen AND keep the C-C bond, which is what
MoloM now draws — the only remaining difference is that we do not draw sticks
to the fifth and sixth H, because carbon does not have six bonds. **The crystal
page was one long `\n`-joined string** and is now a two-column table: cell,
volume, Bravais lattice (`oP - orthorhombic, primitive`, from the IT number
plus the lattice letter), space group with its number, asymmetric-unit and
drawn atom counts, and a CALCULATED density — which on ZIF-8 comes out at
0.925 g/cm3 against the file's own reported 0.925, i.e. a free check that the
expansion is right. Under it a collapsible **File details** block carries the
names, formulae, weight, Z, temperature, radiation, wavelength, R factors,
colour, habit and provenance (DOI as a link, CCDC/COD codes) — every row
present only if that tag was, because CIFs carry wildly different subsets.
`_publ_section_title` and friends need `;`-block reading, which the parser did
not do. **Space groups are named in Hermann-Mauguin by default**, with a
Settings choice of short/full/standard-setting/Hall/as-written. The short form
used is the SETTING-PRESERVING one (`P2_1/n`, not `P2_1/c`): the standard
short symbol is identical for all nine settings of number 14, so printing it
for a P2_1/n file reads as an outright error to anyone who knows their own
compound. Also fixed: `CrystalPage` positioned three widgets by literal layout
INDEX (`insertWidget(2, ...)`), which this round's two new widgets silently
invalidated — the polyhedra checkbox landed in the middle of the details
block. They are placed relative to a named widget now. 898 tests.

Round 40 (2026-08-05, the space group a file NAMES instead of spelling out):
the last big correctness gap in the CIF reader, and the quietest.
`_symmetry_space_group_name_H-M 'P 21/c'` with no operator loop fell back to
P1, so MoloM drew the **asymmetric unit** — a quarter of the structure, with
no error, no warning, and a picture tidy enough to believe. On Christian's
`2101932.cif` (ferrocene) that is 11 atoms where there are 42, and the render
shows every iron carrying ONE cyclopentadienyl ring: half a sandwich, neatly
packed. New `core/spacegroups.py` resolves symbol → operators through
**spglib's Hall database** (pymatgen as a backstop), and the reason it is the
Hall database and not the 230 group numbers is **settings**: `P 21/c`,
`P 21/n` and `P 21/a` are all number 14 with DIFFERENT operators, so expanding
one file's coordinates with another's produces a confident, entirely wrong
structure. Measured, not assumed: across Christian's 37-file test set, **35 of
35 files that list their own operators have those operators reproduced exactly
from their symbol** — including Fd-3m origin choice 2, I4_1/amd, R-3
hexagonal, P6_122 and Im-3m's 96. The other two are the ones the round
rescues: ferrocene (via its Hall symbol `-P 2yab`; formula x Z = 42 exactly,
pymatgen agrees, **ASE refuses the file outright**) and `H2adp.cif`, whose
operator loop is three literal `?` marks (40 atoms, density 1.406 g/cm3 for
adipic acid — pymatgen returns 3 atoms for this file). Matching what CIFs
actually WRITE is the whole difficulty and is why this is not four lines
calling pymatgen: `P 21/c` is the commonest spelling on earth and
`SpaceGroup("P 21/c")` raises. Symbols are compared on a canonical key
(letters and digits only), full symbols also register their short forms
(`P 1 2_1/n 1` → `P 2_1/n`, without which `P 21/n` matches nothing), the
pre-1992 double-glide names are aliased (`Cmca` → `Cmce`, which is ZIF-L),
and the pre-1990 bar-less spellings resolve (`F d 3 m` → `Fd-3m`). Every
derivation is REPORTED in the import message and on the ❖ page — including
"setting b2 assumed" where a choice was genuinely open, and NOT where
convention settles it, because a warning that fires always is a warning nobody
reads. Two rules that keep it honest: **the file's own loop always wins** (a
program that writes P1 coordinates under the parent group's name would have
its structure DOUBLED otherwise — an identity-only loop is reported, never
acted on), and **an unresolvable symbol is stated** rather than silently
becoming P1. Also fixed en route: a **double-spaced loop header** (blank line
between every tag, which is legal CIF) made the tag scan stop at the first
blank and discard the entire atom-site loop — `H7Mg2O10P2.cif` was rejected as
"no fractional atom sites" and now reads 58 atoms, matching pymatgen exactly.
spglib is a HARD dependency now, not an optional tier: rdkit/openbabel degrade
to "cannot read this format", which is visible, while this degrades to a
structure a quarter of its true size. 898 tests.

Round 39 (2026-08-05, bonds across the cell faces — the ZIF batch): Christian
downloaded a set of new files and "molom fails on almost all of them".
Measured first, against ASE, pymatgen AND each file's own formula x Z: **six
of nine were already exact**, one was not a structure at all (`iq4001img1.cif`
is an imgCIF — detector axes, PILATUS geometry, no `_cell_length_*`), and the
real failures were three. The big one: **display bonds are perceived from
Cartesian coordinates with no minimum image**, so on his `2130205.cif` the
connectivity has 224 bonds and only 196 were DRAWABLE — 48 atoms were drawn a
bond short and every imidazolate at a face came out severed. VESTA shows the
same file as 276 atoms / 324 bonds because it materialises the partners.
Fixed with a **`BoundaryModifier`** (`kind="boundary"`), so the base structure
stays exactly the cell contents — Z, the ❖ count, editing and unit-cell export
untouched — while the viewport and the Blender export see a continuous
framework. Auto-added at import when a crystal actually needs one, and driven
by the ❖ page's existing checkbox, which is no longer a destructive rebuild.
Four rules earned by measurement, each of which stopped something exploding:
**covalent bonds only** (every one of MOF-5's 24 cross-face bonds is a
covalent C-C inside a linker; every one of NaCl's is ionic, and following
those turned a 9-atom cell into 59); **finite fragments only** (a lattice or a
covalent polymer is infinite, and every shell looks as unfinished as the
last); **whole molecules** (half a five-ring is not a thing that exists —
round 33's rule one step further out); and **de-duplicate against what is
already drawn** (`bonded_exterior` keyed images by `(site, image)`, which
assumes every input atom is its own (0,0,0) image — false the moment the input
carries boundary copies, and a structure with 777 of them grew to 6389 atoms).
A fragment that straddles a face must also be made CONTIGUOUS before it is
translated, or its far half lands two cells out bonded to nothing. ZIF
176/196 -> 216/252, MOF-5 424/488 -> 616/704, molecular crystals untouched.
873 tests.

Round 38 (2026-08-05, the chemistry a distance rule cannot have): Christian's
diagnosis, implemented in three parts. **BOND KINDS** (`bonding.bond_kind`):
metal-to-non-metal is a COORDINATION bond and that is where a framework gets
cut, which is how Mercury knows to stop after the carboxylate. DERIVED from
the element pair, never stored — so it cannot go stale, cannot be lost by an
edit and needs no reindexing when atoms are deleted. Metal-to-METAL stays
covalent, or an SBU would be dissected into loose atoms. `fragment_info` now
cuts a component at its coordination bonds **only if that component came back
periodic**: MIL-53's one 152-atom infinite component becomes 8 linkers + 8
OH bridges + 8 waters + 8 Al, every one finite and completable at the
boundary, while ferrocene — finite already — is never touched. Rock salt cuts
into single ions, which reproduces the round-32 per-atom completion for the
right reason. **VALENCE SANITY** (`bonding.prune_pairs`, used by BOTH
`perceive_bonds` and `cif.periodic_pairs`): a bond shorter than 0.65x the
covalent radii is impossible (C#C sits at 0.80, an X-ray riding C-H at 0.87,
HpPyBz's spurious contact at 0.50), and bonds past an element's covalent
valence are dropped LONGEST FIRST. Coordination bonds are exempt from the
cap — a chloride bridging three metals is ordinary. On the real MIL-53-lp
file: 80 carbons over valence -> 0, 384 bonds -> 264. **OCCUPANCY**
(`cif.resolve_disorder`): read since round 18 and finally USED. Three
policies — `dominant` (default; keep the most occupied of each overlapping
set), `major` (also drop < 50%, which is a framework without its disordered
guest), `all` (the old superimposed behaviour) — driven by the disorder GROUP
columns where the file has them and by geometric overlap where it does not.
It runs on the EXPANDED atoms, because alternatives are routinely symmetry
images of one another rather than separate rows. A lone partial site is never
dropped: it is a real partial site, and a half-occupied atom on a special
position is a special position. Every refusal is REPORTED —
`MainWindow.chemistry_note` puts it in the import message and on the ❖ page,
because a silently dropped atom is indistinguishable from a bug. 856 tests.

Round 37 (2026-08-05, Blender export + the cascade that stopped cascading):
**`Ctrl+Shift+B` writes a Blender BUILD SCRIPT** (`core/blender_export.py` +
`BlenderExportDialog`), which is roadmap item 1 of the rendering list,
delivered. A `.py` and not a `.blend` because writing .blend needs Blender
itself; the script is also diffable, editable and re-runnable. It carries
**materials with the right colours** (one per element plus one per DISTINCT
custom colour, so an outliner-painted atom arrives painted and two atoms
painted alike share a material), sRGB->linear converted; **the camera in
exactly the viewport's pose** (both look down local -Z with +Y up, so the
world matrix is the view rotation transposed with the eye in the translation
column — no Euler conversion, and ortho viewports export ortho); **an HDRI
from Blender's own material-preview set**, resolved at RUN time via
`bpy.utils.system_resource` so no path from this machine is baked in; **a lamp
rig placed in the camera's frame** with energies going as distance SQUARED
(and halved when an HDRI is present, which is what stopped the first render
blowing out); the unit cell as a/b/c-coloured cylinders; and the whole render
setup. VERIFIED BY RUNNING IT: Blender 5.1 headless, cubane and rock salt,
renders compared against the viewport grab — that is how the ASCII bug and the
engine-enum bug were found, neither of which any offline test would have
caught. **Shift+N was not a UI bug**: `opsin.ch.cam.ac.uk` is unreachable from
the desktop (DNS resolves, connections time out), and `_resolve_inner`
RETURNED on a tier-1 network failure instead of falling through — so a dead
OPSIN killed every import-by-name, including names PubChem knows perfectly
well. A dead tier now costs a tier, not the answer; **NIH CACTUS is a third
tier** (a different index again, answered in 0.4 s while OPSIN timed out); a
per-session **circuit breaker** stops paying the 6 s timeout on every
subsequent lookup (first lookup 6.7 s, the rest 0.4 s); and `_http_get`
normalises `TimeoutError`/`OSError` to `URLError`, because a READ timeout
raises the bare one and sails straight through every `except URLError` in the
module. 829 tests.

Round 36 (2026-08-04, the right button arbitrates + the methyl rotor):
**a right press no longer takes off.** Round 35 started flight optimistically
on the PRESS, reasoning that a click simply never travels anywhere — but
taking off CAPTURES the pointer (hides it, parks it at the viewport centre and
re-seeds it after every move), so by the time the button came up the release
position WAS the viewport centre, picked nothing, and any hand tremor in
between had already set `_drag_moved`. The geometry context menu was therefore
unreachable, which is exactly what Christian reported. A press now ARMS
(`_arm_fly`) and waits: released inside `fly_hold_ms` (Settings > Flight,
default 250 ms) it is an ordinary right CLICK and the menu opens AT ONCE at
the PRESS position; held past it, or dragged past the click slop, it flies;
double-clicked it latches, as before. 0 ms disables hold-to-fly and leaves
the double-click as the only way in. The deferred-menu machinery is GONE with
its cause — nothing needs holding back for a possible double-click now that a
single press cannot start anything. **The methyl rotor** (`internal.TWIST` +
`torsion_split` + `set_twist`, key **T**, also in the right-click menu): the
one edit a Cartesian editor and a 4-atom dihedral both fail to make
convenient. The selection says WHICH GROUP, not which atoms move — MoloM takes
the smallest fragment containing the whole selection that hangs off the rest
by exactly ONE bond, so the carbon, one hydrogen, the three hydrogens or the
whole CH3 all give the same rotor, and selecting the carbon alone (which sits
ON the axis and could never move) still works. Cutting is over BRIDGES only
(iterative Tarjan + a 2-edge-connected condensation, so it is linear rather
than a BFS per bond), which is what makes a ring refuse honestly instead of
deforming. Both sides of the cut need >= 2 atoms: an anchor side of one atom
means rotating the whole molecule about a terminal C-H, which is what R is
for. Christian's suggestion of pressing X twice cannot work — that cycles to
the OBJECT's local frame, and a C-R bond is no part of it; the axis belongs to
the molecule's connectivity, so it needs its own operator. Also: two round-35
ribbon tests failed on THIS machine only — `ndarray.ptp()` was removed in
NumPy 2.0 and the desktop runs 2.x; `np.ptp(arr)` works on both. 791 tests.

Round 35 (2026-08-04, 6DoF flight + VESTA crystal controls): **the selection
outline was five times too fat** — on cubane the eight carbons merged into one
orange blob with the hydrogens welded on, which is the opposite of what an
outline is for; `_OUTLINE_WIDTH_FRAC` and its clamp are divided by 5 and it is
a hairline now, as Blender's is. **The desktop-only flicker** was almost
certainly the overlay passes BORROWING the scene's instance buffers:
`_paint_meta_glow` and `_paint_selection` uploaded into `_sphere`/`_cylinder`
and set `_needs_rebuild` so the NEXT frame would put the molecule back, which
means the scene buffer only holds the molecule between `_rebuild()` and the
first overlay. Any frame reaching `_sphere.draw()` without a rebuild first
draws the selection HULL in place of the molecule — one frame of orange blobs.
It is timing- and driver-dependent, which is why the laptop never showed it.
Fixed by giving the hull and glow their own buffers (a few KB of duplicated
static mesh data), which also stops a selection forcing a whole-scene rebuild
+ `glBufferData` every single frame. NOT reproduced here, so it is the most
likely cause rather than a confirmed one — but it is a real bug either way.
**Flight is now Everspace-style 6DoF**: strafe primacy (lateral/vertical
acceleration equal to forward — applied to the ACCELERATION, since
`thrust_world` normalises and a weighting on the components would divide
straight back out), **auto-braking** (drag jumps to 1.8x the moment every key
comes up; one symmetric coefficient cannot be both low enough to build speed
against and high enough to park), 1:1 mouse look with no smoothing, and
**dynamic reticle drift** — a second mark that LAGS the hull under turn, so
the rate of turn is readable, which one centred crosshair can never be.
**Q/E now ROLL** and Space/Ctrl took over up/down; **creep moved from Ctrl to
Alt**, because a key that both moves you and quarters your speed is unusable.
Roll is an explicit absolute parameter on `Camera.fly_look`, applied last and
never fed back into the azimuth/elevation pair — so it cannot accumulate,
roll=0.0 is bit-for-bit the round-34 camera, and it **levels on landing**
because the orbit camera is a turntable that cannot represent a rolled pose.
**Right DOUBLE-click latches flight** (single right click or Esc lands);
holding still works. The context menu is deferred by one double-click interval
— but only where a menu would actually open, i.e. a right-click on an
already-selected atom, so double-clicking into flight over empty space costs
nothing. Every flight key is read only while `_fly` is live and the viewport
holds the keyboard, so **there are no conflicts** with the object/edit-mode
bindings for the same letters; a test pins it. All the constants are live in
Settings > Flight. **VESTA's orientation ribbon** (`ui/crystal_ribbon.py` +
`core/orient.py`) pops in when a crystal is in focus — a/b/c/a*/b*/c* axis
views, the standard clinographic oblique projection, and stepped
rotate/pan/zoom. The reciprocal axes come from the **inverse transpose**
(a plane normal is covariant — the round-26 lesson), and in a monoclinic
β=115° cell a and a* really are 25° apart, which is the whole reason VESTA
offers both. **Bonded atoms outside the cell** (`cif.bonded_exterior`) is
VESTA's boundary SEARCH, off by default: a different operation from round 32's
boundary completion, because a bond crossing a face has nothing ON the face to
repeat. 734 tests.

Round 35c (2026-08-04, third pass): **the symmetry/ghost overlay was 25 ms a
frame** — Christian's "choppy" was not a silly request, it was
`_eye_position()` rebuilding the rotation matrix from the quaternion, and
`_project`/`_segment_screen` rebuilding view AND projection, once per DRAWN
SEGMENT (~400 a frame on Pbca). Three fixes: `_camera_frame()` caches all
three on the camera state, `_depth_fade` uses scalar maths instead of
allocating a numpy array per segment, and `_cued_pen` memoises on the
quantised fade so a few hundred segments collapse to a handful of QPens.
25.1 -> 9.6 ms. **Leaving an axis view now re-levels**: `Camera.auto_level`
mirrors `auto_ortho`, so the first orbit out of a crystallographic axis view
restores world-Z-up first — the axis view's up is a CELL axis, which the
turntable cannot represent, so orbiting from it lurched. **Reticle expo**
(`AimReticle.expo`, default 2.0): the curve is applied to the MAGNITUDE, not
per axis, so the stick direction is never bent. A power curve, not the scaled
softplus Christian asked about — softplus's slope at the origin is already
half its asymptotic slope (so it barely softens the centre, which is the
whole point) and it is asymptotically linear rather than bounded (so full
stick would not mean full rate without renormalising). **The axis views were
mirrored, not rotated**: Mercury puts the origin TOP-LEFT with axis k+1
running right and k+2 running DOWN, and the chosen axis pointing AWAY. He
spotted it as "exactly mirrored around the red a axis" — and a mirror is not
achievable by any camera rotation, which is what made it diagnosable. 764
tests.

Round 35b (2026-08-04, flight feel + CIF correctness, from Christian's two
annotated images): **steering is a VIRTUAL STICK, not a mouse delta.** The
first cut had the reticle chase the angular rate and ease home, so a turn
stopped the instant the mouse stopped — his spec is "if my mouse points right,
the right turn should continue indefinitely until I have moved it back to the
centre". `flight.AimReticle` now holds a PERSISTENT offset (clamped to a disc,
with a rescaled dead zone) whose deflection is a sustained turn rate. Nothing
decays on its own. **Automatic banking**: `step_bank` eases the roll into the
turn proportionally to the horizontal deflection, HOLDS it while the stick is
out, and levels when it comes home — exactly as he described, and it is most
of what makes a turn read as a turn. Manual Q/E roll is a separate summed
term (`manual_roll` + `bank`), so neither eats the other. **Mouse-look was
translating the camera**: the rig is an ORBIT camera, eye = center + R^T·[0,0,
distance], so changing only the rotation swings the eye around the pivot on an
arc — "moving the cursor up and down moves the camera by a lot". `_fly_turn`
captures the eye and rebuilds `center` behind it; a pilot's head turns, it
does not orbit a point in front of them. **The cursor is CAPTURED, not
wrapped**: hidden, held at the viewport centre, re-seeded after every move,
with the delta taken against that anchor. Edge-wrapping could only work where
there was screen to wrap to, which is why steering died against the properties
dock on the right and at the top and bottom. **CIF**: `perceive_bonds` now
CAPS hydrogen at one bond (nearest heavy neighbour) — HpPyBz_th.cif drew eight
two-bonded hydrogens. Worth knowing that file is genuinely broken and MoloM is
not: **ASE reads exactly the same 192 atoms and the same 0.7533 A contact**, so
the clash is in the file; capping stops us DRAWING an impossible bond, it
cannot invent a structure. **The oblique view came from below** — the
elevation was added to the forward vector instead of subtracted, putting the
camera under the floor grid looking up through it. **Axis views were the
mirror of Mercury's**: "view along b" means b points AT you, not away, and the
up axis is CYCLIC (right = next, up = the one after), so the b view has c
across and a up. That is why his Mercury screenshot was wide where MoloM's was
tall. A second click on the same axis button flips to the other side, which is
what Mercury spends a whole extra row of x−/x+ buttons on. **Settings scrolls**
and has a filter box top-right, matching at word boundaries over labels AND
tooltips (a plain substring search had "roll" dragging in the pointing-device
row via "scroll"); a section name reveals its whole section, and OK/Cancel sit
outside the scroll area. The filter also caught a real bug: the Acceleration
slider was clamping at 30 while its readout claimed 60. 759 tests.

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

Round 30 (2026-08-03, playback spec) - **the IMAGES half of this was
superseded by round 77**, which collapsed an image and a scene frame back
into one thing and moved the subdivision onto each strip; the loop limits
and the sample-the-extremes rule below still stand. Kept as written
because the reasoning is what matters: **frames, images and seconds are
three different things** and the player used to muddle them. A *frame* comes out of
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
offline (`python -m pytest tests/ -q`, 2118 tests, no display needed).
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

`molom/core/bruker.py` is **VENDORED** from Christian's own
`ACH-Diffraction-Analysis-Suite` (`src/achdiff/core/bruker.py` and the
readers in `tools/quickplot.py`), MIT, Copyright 2026 Christian Nelle, AG
Henke, TU Dortmund - checked out beside MoloM on both machines. Keep it
DIFFABLE the way `io.py` is with OWB's `coords.py`: the `.raw` byte layout
was reverse-engineered there against a PowDLL export, so a fix on either side
belongs on both. Not taken (yet): `read_pdf_xml`, the ICDD card reader - see
`docs/OPEN_ITEMS.md` Q11.

Behavioural constants (verified against avogadrolibs sources, 2026-07-30):
- **Bond perception** (`core/bonding.py`) = `Molecule::perceiveBondsSimple`:
  bond iff `0.32² < d² < (r_cov_i + r_cov_j + 0.45)²`, He/Ne/Ar/Kr never
  bond (Xe DOES), H–H never bonds, radii ≤ 0 → 2.0 Å. All perceived bonds are
  order 1; `perceive_structure_bonds(keep_orders=True)` preserves user-drawn
  orders across re-perception (frame changes). **Round 38 adds chemistry on
  top of that distance rule** — `bond_kind` (covalent vs coordination),
  `MAX_COVALENT` and `IMPOSSIBLE_FACTOR`, applied by `prune_pairs`, which is
  shared with `cif.periodic_pairs` so the crystal path and the molecular path
  cannot disagree. `sanity=False` gets the bare Avogadro rule back.
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
  `Track` (a STRIP) per object. UI-free, so the whole mapping is testable
  without a timer. **Round 77 re-cut its units**: the clock ticks in scene
  frames at `fps` and a frame IS a picture, so the globals are only
  `play_start`/`play_end` (Frame Start / End, INCLUSIVE) and `fps`; a strip
  carries `frames` (how many scene frames it occupies - its length, speed
  and smoothness in one) plus `cyclic` (does the source close on itself?).
  `subdivision` is the old global `smoothing`, now derived per strip; round 78
  made the strip's own control a DURATION in seconds (`frames_for_seconds`),
  added `interpolated` (blend or step - all that a smoothing knob could still
  have said), snapped `Track.start` to whole frames, and stopped the frame
  range following the content (`fit_range`, called once).
  Read `Track.frame_at`'s docstring before changing any of it: the whole
  model exists so one formula serves a generated period and an imported
  trajectory, and `CYCLIC_FRAMES` in a structure's metadata is what tells
  them apart.
- `core/interpolate.py` — coordinates BETWEEN frames. `rigid=True` splits the
  Kabsch rigid motion out and rotates it properly instead of cutting the
  chord; only the residual deformation is lerped. `cyclic=True` (round 77)
  says the frames are one closed period, so the arc from frame n-1 back to
  frame 0 is interpolated instead of clamped — without it a baked mode
  freezes for the last arc of every revolution.
- `core/cif.py` — CIF parsing that keeps the crystallography: `Cell`
  (fractional<->Cartesian matrix, corners/edges for the box), `SymOp`
  (parses "-x+1/2, y, -z"), `parse_cif` -> asymmetric unit, `expand` ->
  full cell with minimum-image de-duplication. No new dependency; the CIF
  subset real files use is small. `ui/viewport.cell_of(obj)` reads the cell
  back out of `Structure.metadata["cell"]`. Round 38: `resolve_disorder`
  (occupancy + disorder groups, three policies), `periodic_pairs` (the
  minimum-image bond list, valence-sanitised), and `fragment_info` cutting a
  PERIODIC component at its coordination bonds — which is what makes a
  framework's linkers finite and completable at the boundary.
- `core/sandbox.py` — an ALTERNATIVE pipeline for the 🧪 page (round 45d).
  Nothing in the app reads it; it exists to try an algorithm on, and it gets
  emptied and rebuilt whenever the idea changes. Shares Cell..Dedupe with
  `core/pipeline.py` by calling it; diverges at `Bonds` (connectivity from the
  periodic graph, drawn only where both ends are in the cell) and
  `complete_molecules` (Mercury's packing: every fragment reaching into the
  cell drawn whole, nothing relocated).
- `core/pipeline.py` — the CIF pipeline exposed ONE STAGE AT A TIME, for the
  🐞 debug page (round 45). `run(text, upto)` is a pure function returning the
  atoms, the bonds and a per-stage TRACE. Stages 2-5 delegate to `cif.expand`'s
  own flags on purpose: a debug view that drifts from the real path is worse
  than none. Add a stage here and the page grows a button by itself.
- `core/bondgraph.py` — **STAGE 4, the labelled periodic bond graph** (round
  44). `Edge(i, j, shift, dist)`: the shift is the integer lattice translation
  applied to `j`, i.e. the CIF `n_pqr` code (`npqr()`), and carrying it is
  what makes the graph independent of the display window. Candidates come
  from the TRANSLATION SHELL sized by `perpendicular_widths` — never the
  minimum image, whose guard (`minimum_image_is_safe`) is kept only as a
  named predicate because its absence was the bug. The chemistry is not
  re-implemented: the same `bonding.prune_pairs`, plus a periodic hydrogen
  cap. `label_instances` tags each DRAWN atom `(content index, shift)` and
  `PeriodicGraph.instantiate` turns that into bonds by lookup — stage 5, and
  the reason an atom on a cell face now keeps its whole coordination sphere
  instead of splitting it between its two drawn copies. `components()`
  returns each component's lattice RANK (0 molecule / 1 chain / 2 layer /
  3 framework), which is the honest test for "can this be completed as a
  molecule?". Anything that draws or exports a crystal should go through
  `cif.display_bonds`, not `perceive_bonds`.
- `core/spacegroups.py` — space-group SYMBOL -> operators, for the CIFs that
  name their group and omit the loop. spglib's **Hall database** (530
  settings) first, pymatgen second, both optional-at-runtime and both
  degraded gracefully. Returns `x,y,z` STRINGS so the caller feeds them
  through the same `SymOp.from_xyz` a file-supplied loop takes — one code
  path, and the metadata round-trip is identical. The matching, not the
  operators, is the hard part: see `canonical_key`, `_short_forms` and
  `_e_glide_aliases`. `Symmetry.ambiguous` says whether a setting was really
  CHOSEN, which is what stops the report crying wolf on every P2_1/c file.
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
  half" has no answer and only the picked atom may move. Round 36 added the
  ROTOR: `torsion_split(n, bonds, selected)` finds the smallest fragment
  containing the selection that hangs off one bridge (Tarjan bridges + a
  2-edge-connected condensation, then the minimum over tree edges — linear,
  not a BFS per bond), and `set_twist` spins it. Use it, not `moving_group`,
  whenever the question is "which group did they mean?" rather than "which
  bond did they name?".
- `core/flight.py` — the 6DoF model behind right-mouse fly AND shuttle mode.
  `AimReticle` is the VIRTUAL STICK: a persistent offset whose deflection is a
  sustained turn rate, with a rescaled dead zone. It never decays — that is
  the point. `step_bank` rolls into the turn and levels when it centres.
  World-space velocity, thrust, exponential drag (stable at any dt), speed
  cap, scene-size scaling, per-axis acceleration (strafe primacy) and an
  auto-brake coefficient that only applies with no key held. `ReticleDrift`
  is the separated aiming mark. Roll is an explicit angle here and an explicit
  PARAMETER on `Camera.fly_look`, applied after the azimuth/elevation rebuild
  so it can never accumulate; pitch is still clamped short of vertical.
- `core/cameras.py` — saved viewpoints (round 56). A `CameraObject` is a
  pose plus a lens: focal length in MM against a sensor width, an explicit
  roll (the turntable cannot hold one), and pixels plus a multiplier. Also
  owns the film-back rectangle and its drag handles, so the viewport
  overlay is arithmetic that can be tested without a window. Round 57 added
  `viewport_fov_y` (which makes the rectangle a real framing rather than a
  decoration) and `twist_rotation`, the ONE place that knows which way roll
  goes; round 58 made the frame ANGULAR — `half_angles`, `frame_rect(tx, ty,
  zoom)`, `fit_frame_zoom`, `resize_frame` (a handle moves a BORDER) and
  `zoom_frame` (the wheel), plus `gizmo_geometry` for the wireframe pyramid
  drawn in the viewport. Read `frame_rect`'s docstring before changing any of
  it: the whole model exists so that moving a border cannot rescale the
  scene.
- `core/animation.py` — the scene clock as a FILE (round 54). `frame_times`
  is the plan and is where the mistakes live (a repeated loop boundary hitches
  once per cycle and is invisible in a single frame); PNG sequences need no
  dependency, video goes through ffmpeg and is always encoded FROM a written
  sequence so a failed encode still leaves the frames.
- `core/blender_export.py` — the scene as a Blender BUILD SCRIPT: geometry
  (following `viewport._rebuild`'s rules exactly — modifier output, per-atom
  colours/sizes, hidden atoms, the multi-bond layout), **coordination
  polyhedra** (round 50, via `polyhedra.for_object` so the render and the
  viewport cannot diverge), materials, camera, lamp rig, world/HDRI and render
  settings. `collect()` returns plain data and `build_script()` renders it into
  source, so the data and the text are testable separately. The emitted script
  is deliberately **ASCII only** and must stay that way. It also carries a
  `--save` handler, which is what `find_blender` + `write_blend` use to build a
  **.blend** headlessly — the scene is complete before the file is written, so
  nothing runs on load.
- `core/occupancy.py` — shared crystallographic SITES: read, edit, write.
  The composition of a solid solution is the one thing no derivation can
  recover (round 45e), so round 52 made it something the user can state.
  `orbit_of` uses `site_of` to apply an edit to the whole site;
  `expand_shared` splits it into one `_atom_site_` row per species.
- `core/cif_write.py` — the CIF WRITER (round 50). `cif_text` is pure
  formatting; `from_object` makes every decision, and makes them by
  MEASUREMENT: the stored asymmetric unit goes back out verbatim if it still
  reproduces the drawn content, otherwise spglib re-derives the group from the
  coordinates. Writes only the cell CONTENT (never the boundary copies), undoes
  the cell pose first, and reports what it decided — including when occupancy
  could not be carried and when a cell had to be invented.
- `core/orient.py` — crystallographic view orientations for the ❖ ribbon:
  direct and RECIPROCAL axis directions (the latter from the inverse
  transpose — a normal is covariant), `look_along`, and the classical
  clinographic oblique projection. UI-free, so the whole ribbon is testable.
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
- `core/cellbox.py` — the unit-cell box as drawable GEOMETRY, and where it
  sits in the picture. `OVERLAY` is the painted form MoloM has always had
  (always visible, which is what you want while navigating); `DEPTH` is one
  thin rod per edge drawn in the opaque pass, so it is occluded by what is in
  front of it - which is what a published still needs, and what the viewport's
  overlay silently lies about. Chosen separately for the viewport and for an
  image export (`viewport.cell_zorder` / `cell_zorder_export`). The rule for
  which edge is the a axis lives here so the screen, the export and
  `blender_export.cell_edges` cannot part company.
- `core/pxrd.py` — simulated powder diffraction from a crystal already open.
  UI-free and matplotlib-free: it returns arrays. Read the module docstring
  before touching the maths - the vendored scattering coefficients give the
  DIFFERENCE from Z rather than a Cromer-Mann sum, and multiplicity and
  systematic absences both fall out of MERGING coincident reflections rather
  than out of any rule. Validated against pymatgen's `XRDCalculator`.
  `core/scattering.py` is GENERATED by `tools/gen_scattering.py`.
  `cell_contents` / `pattern_for` (round 95) are the bridge from a
  crystal MoloM has open: they REGENERATE the cell from the asymmetric
  unit and the operators rather than reading the drawn atoms, which is
  what makes the pattern identical in the asym view, the full cell and
  a packing. `ui/pxrd_panel.py` is the window, and it is PAINTED -
  matplotlib is still not a dependency. Round 96 added `parse_source` (a wavelength, an energy in
  keV or eV, a named line, or a K-alpha doublet with its ratio),
  `peak_positions` (one peak per emission line, sharing `|F|^2` because
  `s = 1/(2d)` has no wavelength in it) and `keep_absent` for the hkl list.
  `compute` is vectorised and chunked; read its docstring before changing the
  loop, and see round 96 for why the paint path decimates and blits.
  Round 97 added `profile_at` - the profile at ARBITRARY x - which is what
  lets the plot sample at its own pixel columns at every zoom level;
  `profile` is the regular grid an EXPORT wants and is now a thin wrapper
  over it.
- `core/pxrdfile.py` — a MEASURED powder pattern read off disk. The text
  formats have no standard at all beyond "two or three columns of numbers
  under some header lines", so it is written to that rather than to any one
  vendor; the third column is the ESD and is not a second pattern. Decides
  comma-as-decimal PER FILE (a file is written by one machine in one locale),
  turns a descending scan the right way round, and REFUSES anything under
  `MIN_POINTS` - a reader that finds something in a prose report is the
  dangerous kind. `read` dispatches on the extension so the binary formats
  never reach the text path.
- `core/bruker.py` — VENDORED from Christian's `ACH-Diffraction-Analysis-Suite`
  (MIT), keep diffable the way `io.py` is with OWB's `coords.py`. `.raw`
  (RAW1.01/1.02) and `.brml`. Read `_RH_THETA`'s comment before touching the
  offsets: the header holds theta and 2-theta eight bytes apart and the wrong
  one gives a pattern at half the angles, which looks entirely plausible.
- `core/molsearch.py` — finding a MOLECULE by name, as a LIST (Ctrl+Shift+N).
  The counterpart to `core/resolve.py`, not a replacement: that one cascades
  to ONE structure and still does. Read the module docstring before touching
  a tier - the whole design turns on **the join key being the InChIKey**
  (a CID is PubChem-local, a SMILES is not canonical across toolkits), which
  is what lets a structure found by OPSIN be looked up in PubChem and so what
  makes a cascade answering first harmless. `merge_batch` is what keeps an
  incrementally filled list from reordering under the user's hand;
  `_RateLimit` is not optional, since PubChem 503s past 5 requests a second
  and does it silently.
- `core/depict.py` — the 2D skeletal picture, as PNG bytes. Draws from a
  SMILES and never from a Structure, so it cannot flatten the 3D coordinates
  it is describing.
- `molom/addons/mol_properties.py` — the compound-properties page. Its
  `identify()` is the piece worth knowing: a molecule's own GRAPH is its
  identifier (`io.structure_to_smiles` -> InChIKey -> CID), so the page works
  on anything drawn, edited or opened rather than only on what a search
  found - and a stored record can be CHECKED against the structure instead of
  being flagged by an edit. That is why nothing here locks an object.
- `core/molprops.py` — the FORMAT for a compound's properties: the metadata
  key, the schema version and the caps. In core so that disabling the add-on
  that fills it cannot make a savefile unreadable. Carries the
  MEASURED/COMPUTED split (`KIND_MEASURED`, `KIND_COMPUTED`), which is not
  cosmetic - a computed logP and a measured melting point are different
  claims and must never be shown as one list. The fetching and the page are
  `molom/addons/mol_properties.py`.
- `ui/search_table.py` — the results table BOTH searches use: numeric sorting
  that is done in Python, unknowns that sink either way up, a third click that
  restores the ranking, the star column and the favourites divider.
- `core/cifsearch.py` — finding a CRYSTAL by formula, mineral or name, and
  importing it (Ctrl+Shift+Alt+N). Three tiers - a local folder, COD, and
  OPTIMADE's computed providers - run CONCURRENTLY, because unlike a molecule
  name a crystal name has many right answers and every tier may hold part of
  the set. Ranking, deduping and fuzzy matching are done here, not by the
  providers. Read the module docstring before changing a tier: the failure
  model (a dead tier costs a tier, never the answer) is round 37's lesson and
  is the whole point. `optimade_cif` exists because OPTIMADE serves JSON, and
  writing a P1 CIF keeps ONE import path for all three tiers.
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
- **THE WIDGET'S WIDTH IS THE WRONG RULER FOR A VECTOR EXPORT** (round 101).
  A min/max envelope reduces to one point per COLUMN, so the peak detail an
  SVG carries is set by the column count and not by how finely the profile
  was computed - a 939 px plot over 45 degrees is 2.1 columns across a
  0.1 degree peak, and the peak is an octagon as soon as the figure is
  enlarged. Take the count from the FWHM (`export_columns`), keep the
  width-based figure as a floor, and cap it.
- **STORED POINT DENSITY IS NEARLY FREE, AND THE WALL CLOCK CANNOT SHOW IT**
  (round 101). Quadrupling the profile's resolution moves the DRAWN point
  count by 1.2% because the envelope bounds it, but timing the repaint gave
  42, 70 and 62 ms for the SAME configuration on interleaved runs. When a
  benchmark disagrees with itself, find the deterministic quantity - here the
  drawn point count - rather than averaging more noise.
- **A BLITTED PIXMAP CACHE MAKES `render()` PRODUCE A RASTER SVG** (round
  101). Anything that paints through a QPixmap cache and is then rendered
  into a `QSvgGenerator` embeds that pixmap as an `<image>`, so the file is
  an SVG with a bitmap in it - which looks perfect until somebody enlarges
  it. Split the painting from the device (`paint_into(painter)`) and let both
  the screen and the export call it, so they cannot disagree. And remember
  the min/max envelope is a per-PIXEL reduction: a vector device has no
  pixels, so it needs its own column count or the curve is polygonal.
- **A SCREEN PALETTE IS NOT A PAGE PALETTE, and the two overlap** (round
  101). MoloM's trace colours run 0.567-0.796 relative luminance and the
  measured ones 0.776-0.910, so no threshold tells "a colour somebody chose"
  from "near-white" - and ALL of them sit between 1.24:1 and 1.70:1 against
  white, where line art wants 3:1. The rule that works is a CEILING on
  luminance for every trace (`PAPER_LUMA`), applied by scaling all three
  channels together so the hue survives.
- **A GENERIC TWO-COLUMN READER WILL READ ALMOST ANYTHING, AND THAT IS THE
  BUG** (round 100). A Riet7 `.dat` is a header line plus a block of BARE
  intensities with no x column, so pairing the numbers off gives 276 points
  running to 1290 degrees - a pattern of nothing, drawn without an error.
  The guard that catches the whole class is exact physics rather than a
  plausibility heuristic: a scattering angle lies between 0 and 180 degrees
  (`pxrdfile.MAX_TWO_THETA`), so a first column outside that is not an angle
  and the columns are not what they were taken for. Any format whose numbers
  are not an (x, y) table - a matrix, a log, a header-driven block - fails
  this way, so add the format-specific reader AND keep the guard.
- **THE BRUKER RANGE HEADER CARRIES THETA AND 2-THETA EIGHT BYTES APART**
  (round 100, `core/bruker.py`). Reading the wrong one gives a pattern at
  HALF the angles, which looks like a perfectly ordinary pattern of a
  different compound - nothing about the numbers says which was read. Same
  trap in `.brml`, one `<Datum>` column along. `_RH_THETA` is a named
  constant precisely so the next person to touch the offsets fails at the
  line rather than at a plausible picture.
- **A DISPLAY value and a STORED value are two different coordinates**
  (round 57). `MolObject.display_coords()` interpolates between frames while
  `structure.coords` is the nearest stored one, so anything that draws or
  hit-tests alongside `_rebuild` must use the first. The selection hull and the
  pick arrays used the second, which is invisible when paused and reads as the
  outline LAGGING the atoms during playback — up to half a source frame, and it
  reverses at each turning point, which is why it looks like a phase error
  rather than an off-by-one. Grep for `s.coords` in `ui/viewport.py` whenever
  adding a pass that has to sit on top of the molecule.
- **Re-perceiving bonds per frame is right for a TRAJECTORY and wrong for a
  VIBRATION** (round 57). A normal mode is one molecule at successive phases of
  an oscillation, so the chemistry filters can only ever LOSE bonds on it: at
  the default 0.2 A amplitude an ordinary P=O goes under `IMPOSSIBLE_FACTOR`
  and the stick vanishes mid-animation. `bonding.FIXED_BONDS` in the
  structure's metadata says "these frames share one connectivity"; set it
  wherever frames are generated from a displacement rather than read from a
  file.
- **A capture taken "once, at load" goes stale the moment anything moves it**
  (round 57, and round 55 fixed half of this already). `_rest_geometry` was
  re-read only while a mode was ALREADY animating, so the FIRST bake still
  teleported the molecule home — which is why the symptom was the strange
  "only the first click does it". If the live data can answer the question
  (frame 0 IS the rest geometry), read it every time and keep the capture only
  as a fallback; a conditional refresh is a cache with one branch nobody tests.
- **A "camera view" that does not change the PROJECTION is a decoration**
  (round 57). MoloM drew the film back over a viewport still running its own
  fixed 40 degree FOV, so the focal length changed the label and nothing else
  and the frame was not a framing. Shadowing `Camera.FOV_Y` on the instance is
  the whole fix, and it is the right shape precisely because every matrix in
  the program derives from that one value — view, projection, picking rays,
  `fit`, `pan`, the offscreen render. Resist adding a `fov=` parameter to
  `projection_matrix`: that is a second code path.
- **Normalising a rectangle to "the largest that fits" throws away everything
  but its ASPECT** (round 57), so handles that change its SIZE appear dead —
  and a corner dragged along the rectangle's own diagonal is exactly the
  aspect-preserving direction, which is the one a user naturally drags. If a
  control is reported as doing nothing, check what of its output survives to
  the screen before checking whether it runs.
- **A FITTED rectangle plus a projection fitted to it means every reshape is a
  rescale** (round 58, and it is the round-57 fix biting from the other side).
  Round 57 answered "the handles do nothing" by making the fitted frame drive
  the field of view — so changing the aspect changed the frame's size, which
  changed the field of view, which rescaled the whole scene, which reads as
  the camera dollying backwards. The cure is to make the frame ANGULAR
  (half-width `Z*tan(fov_x/2)`): the scene's on-screen scale is then `Z /
  distance`, with no lens or aspect term, so "the borders move and nothing
  else does" is a property of the arithmetic instead of something arranged.
  When a control must leave something invariant, derive the invariant and see
  what parameterisation makes it fall out — do not fix the symptom.
- **A control that decides a BUFFER SIZE is a control that can exhaust memory**
  (round 58). `_render_crop` asked for `resolution / frame fraction`, so
  pulling the frame small demanded a proportionally huge offscreen buffer; and
  the frame handles drove the camera's resolution, which `blender_export.
  build_render` copies into the Blender scene — a few drags turned a 1x camera
  into a 6000x5000 render. Anything a user can drag needs a stated budget:
  pin the long side, cap the buffer, and scale the rest of the way.
- **`Num+0` is a key half the keyboards in the world never send** (round 58).
  It means `KeypadModifier | Key_0`, and with NUM LOCK OFF the numpad's 0
  sends `Key_Insert` instead — so the shortcut silently does nothing for
  anyone who does not happen to have Num Lock on. Register `Num+Ins` beside
  it (`extra_keys`), the same way round 55 registers both spellings of a
  Shift chord.
- **Re-applying a whole object to re-apply one field of it destroys the rest**
  (round 57). `camera_changed` called `apply_to`, which assigns centre,
  distance and rotation, so editing the RESOLUTION threw away any navigating
  done since Numpad 0 — "clicking a scaling knob resets a previous dolly".
  Split the assignment along the axis the user thinks in (pose vs lens) rather
  than passing flags.
- **A convention with two implementations has one bug waiting** (round 57).
  Roll was built in `blender_export` with the twist matrix TRANSPOSED, i.e.
  the opposite way from `Camera.fly_look`, and nothing caught it for a whole
  round because the viewport ignored roll entirely — there was no preview to
  disagree with. Any quantity that appears both on screen and in an export
  needs ONE function (`cameras.twist_rotation`), and the test is a comparison
  between the two, not an assertion about either.
- **`Scene.from_dict` rebuilds the snapshot dict BY HAND** (round 56), so
  anything added to `snapshot()` and not added there is silently lost on
  load — the cameras vanished from the first savefile that had them. When
  adding scene-level state, grep for `next_id`: it appears in `snapshot`,
  `to_dict`, `from_dict` and `restore`, and that is the checklist.
- **A two-part chord needs both spellings** (round 55). `Shift+Space, L` only
  matches when Shift comes UP before the second key; hold it and Qt looks for
  `Shift+L`. Nothing warns you — the action simply never fires, and it reads
  as "that hotkey does not work". `ops.chord_variants` returns both, and any
  new chord should go through it.
- **A remembered output path must be the BASE name** (round 55). Storing the
  incremented one back compounds the suffix: `shot.png`, `shot_001.png`,
  `shot_001_001.png`. Increment at the point of writing, never in the state.
- **`format().samples()` is not the sample count** (round 54). It describes
  the window; a QOpenGLWidget draws into an FBO Qt owns, so it reads 0 on a
  fully multisampled context. `glGetIntegerv(GL_SAMPLES)` from inside the
  live context is the only answer that means anything — and reporting the
  wrong one cost a round and a false claim in this file. Whenever a GL
  capability looks missing, query the FRAMEBUFFER, not the surface format.
- **An additive blend accumulates ALPHA as well as colour** (round 53), which
  is invisible on screen and wrong in every export. The symptom is not subtle
  once you look for it: a grabbed frame came back with the whole solid scaled
  by a uniform factor across all three channels — colour divided by an alpha
  that had crept up. `glBlendFuncSeparate(SRC_ALPHA, ONE, ZERO, ONE)` adds
  light and leaves alpha exactly as it was. Any additive pass over a scene
  that can be grabbed or rendered to a transparent PNG needs it.
- **A module constant used as a DEFAULT ARGUMENT cannot be tuned at run time**
  (round 53). `def f(x, spec=SPECULAR)` binds the value once at import, so
  setting `module.SPECULAR = 0.3` afterwards changes nothing — and an A/B
  harness written that way produces two byte-identical frames and looks like
  the feature does not work. Put anything meant to be adjustable on the OBJECT
  that owns the drawing.
- **`QSurfaceFormat.setDefaultFormat` is an entry-point call** (round 53), so
  it only happens under `python -m molom`. Every other way of building a
  window — the smoke tool, a test, an embedder — got the driver's default
  instead. Set the format on the WIDGET as well; it costs nothing and cannot
  be bypassed.
- **"A group was found" is not "this unit rebuilds this cell"** (round 52).
  spglib answered `R3m` for an edited MOF-5 and `orbit_representatives` gave 7
  orbits for it — 7 x 6 operators is 42 atoms, and the cell holds 424. Both
  answers come from the same dataset and are individually defensible; only
  their PRODUCT is the thing a rebuild depends on, and nothing was checking
  it. Check the reconstruction before storing derived symmetry, and prefer P1
  when the check fails: P1 always reconstructs.
- **The drawn cell content is not the canonical cell content** (round 52).
  `packing.pack` unwraps molecules to keep them whole, so a "content" atom can
  sit anywhere from -0.43 to 1.43 in fractional coordinates — 34 of
  ferrocene's 42. Feeding those back in as an asymmetric unit re-wraps them
  (tearing the molecules) and re-runs a completion that has already been
  defeated by the relocation (round 45d). If a structure has been through the
  packing, the way to preserve it is to STOP regenerating it, not to find
  better coordinates to regenerate from.
- **Two edit-begin hooks, and the chemistry one was not doing the work**
  (round 51). `on_model_edit_begin` is called by the geometry modals; every
  CHEMISTRY edit (element change, draw, bond order, delete) calls
  `on_edit_begin`, which was `push_undo` alone. Anything that must happen
  before ATOMS MOVE — round 43e's pose capture above all — has to be on BOTH,
  and the way to check is not to read the wiring but to drive a chemistry edit
  and assert the invariant. A test that only drives G and R proves nothing
  about this half.
- **`isEnabled()` folds in every ANCESTOR** (round 51, and round 34 said the
  same about `isVisible()`). A properties page lives on a QStackedWidget
  inside a dock that is usually closed, so `widget.isEnabled()` is False for a
  perfectly live control most of the time — and a guard written that way fails
  silently and intermittently. Keep the state you actually mean as your own
  flag (`CrystalPage._has_cell`).
- **A comment naming a call is not the call** (round 51). `_sync_all`'s
  comment explained at length why the ❖ page belongs there, and the line was
  never added — so every per-crystal control kept the previous molecule's
  state through an import, which reads as "the tick does nothing until you
  cycle it". When adding a "refresh everything" function, enumerate the
  panels in a list rather than by hand.
- **"Cached on its inputs" is only half the job if the SHADING is not**
  (round 50). Round 48 cached the convex hulls and then computed the face
  normals, the centroids and the triangle soup per frame anyway, inside a
  Python loop over triangles — 53 ms a frame at 400 octahedra, which is the
  round-33 rule broken by the very commit that quoted it. The test for
  "does this belong in the paint path?" is not "is it expensive?" but **"does
  it change when the camera moves?"**. Split the two halves into separate
  functions (`face_arrays` / `shade_from_faces`) so the boundary is visible in
  the API rather than remembered, and pin them as identical to the combined
  one — a performance change that alters the picture is a different change.
- **A convex-hull face is a PLANE, not a triple** (round 50). Accepting each
  candidate triple independently emits one triangle per triple, so any face
  with more than three points on it is covered several times over: a cubic
  8-coordinate centre gave 24 triangles over its 12, four stacked on each
  square face. Invisible in a wireframe and in a face COUNT nobody checks;
  visible as a square face blending twice in the viewport, and as z-fighting
  the moment the same geometry reaches a renderer. Group by the set of points
  on the plane (an exact integer key — a rounded normal lets two triples of
  one face disagree) and fan-triangulate once, in a basis built right-handed
  with the outward normal so the winding needs no per-triangle check.
- **`blender-launcher.exe` cannot be scripted** (round 50). It is the GUI shim
  Windows installs put beside `blender.exe`, and it is what a user will hand
  you when asked where Blender is — `-b --python` needs the real binary, which
  is in the same directory. Resolve it rather than trusting the path, and
  remember the path itself must be a SETTING with discovery: this project has
  two dev machines with Blender in different places, which is the whole reason
  round 16 happened.
- **An exception in `paintGL` kills everything drawn AFTER it, silently**
  (round 48, and this is the round-34 lesson biting a second time). Qt catches
  it, prints to stderr and carries on, so the window keeps working while the
  grid and the compass simply stop appearing — which is what a one-character
  mistake did: `self._camera_frame()[0]` on a dict raised `KeyError` inside
  `_draw_polyhedra`, and the two passes that follow it vanished the moment
  coordination polyhedra were switched on. **No headless test can see this**:
  the offscreen platform never runs paintGL, so `repaint()` returns happily and
  every assertion passes. `tools/smoke_gui.py` exists for exactly this — it
  opens a REAL window, wraps every `_draw*`/`_paint*` method so a raise is
  recorded rather than swallowed, grabs a frame per overlay, and exits
  non-zero. Run it whenever you touch a paint path.
- **`glLineWidth` is INVALID in a GL 3.3 core profile** (round 48) for any
  value but 1.0: it raises `GL_INVALID_VALUE`, PyOpenGL turns that into a
  `GLError`, and by the gotcha above that aborts the frame — which showed as
  the polyhedra pass tearing holes in everything and the picture flashing.
  Core profiles dropped wide lines; if a thicker outline is ever wanted it has
  to be geometry (a quad strip or a screen-space shader), not a state call.
- **CLIP THEN BOND splits a face atom's coordination sphere in half** (round
  44). An atom lying exactly on a cell face is drawn twice, once per face —
  correct, and what every viewer does — but if the bonds are then perceived
  from CARTESIAN coordinates, each copy only picks up the partners on its own
  side. The picture shows two atoms with half a sphere each instead of one
  atom with a whole one: every Zn in ZIF-8 came out 3-coordinate. It cannot be
  fixed by adding boundary shells, because the atoms were never missing, and
  it is invisible to any check that counts atoms. Bond on the PERIODIC
  structure first, label the edges, and instantiate.
- **The minimum image needs a guard, and it is the PERPENDICULAR width**
  (round 44). `d - round(d)` is valid only while the cutoff is under half of
  `min(d_a, d_b, d_c)` where those are `V/|b x c|` and friends — strictly
  smaller than the cell edges in a skewed cell, which is the tempting wrong
  check. It also cannot express more than one bond per pair of indices, nor
  any bond from an atom to its OWN image, so alpha-iron came back with one
  bond where bcc has eight and simple cubic would have none at all. Six of 37
  files here fail the guard, all of them dense inorganics — no ZIF does, so
  the framework files will not warn you about this.
- **A periodic graph must be invariant under how the atoms were written
  down** (round 44). `unwrap_molecules` moves whole fragments by lattice
  vectors to make them contiguous, so a shell of radius one around the
  coordinates AS GIVEN simply does not reach an atom carried two cells out —
  `bondgraph.build` came back with zero edges for a structure it had just
  described correctly. Wrap internally for the search and correct the labels
  back (`t - w[j] + w[i]`); a test drives it with an atom moved by (-1, 2, 0).
- **`bond_kind` will not tell a ZIF from rock salt, and that is deliberate**
  (round 44). Zn-N and Na-Cl are both metal-to-non-metal and both COORDINATION,
  because for "does this hold a molecule together?" both answer no. So a rule
  about whether to follow a bond OUT of the cell cannot be written in terms of
  the kind alone: ask what is on the other end. A partner in a covalent
  fragment of more than one atom carries a molecule worth completing (a ZIF's
  imidazolate); a partner alone in its fragment is an ion in a lattice, and
  completing it sprouts a slab.
- **A packing stacks each cell's own boundary copies** (round 44). The copy on
  a shared internal face is the same atom as its neighbour's, so a naive
  supercell draws it twice at exactly the same point — ferrocene's 2x2x1 had
  1680 coincident pairs in 1680 atoms, i.e. every atom doubled. Invisible in
  an atom count, visible as z-fighting and doubled sticks, and it makes every
  downstream measurement wrong. De-duplicated, NaCl's packings are the
  textbook `(2na+1)(2nb+1)(2nc+1)`: 27, 45, 75 — the old 27, 54, 108 were
  pinned by three tests, which had to be corrected with the code.
- **An EDIT is not a rigid motion, so never measure a pose across one**
  (round 43e). `cell_pose`/`rigid_from_reference` is a Kabsch fit over a
  sample of the atoms; move one of those atoms and the fit dutifully reports a
  rotation of the whole crystal that nobody performed. The cell box then
  creeps a little further with every edit, which reads as the box slowly
  rescaling. Capture the pose BEFORE the atoms move (`begin_model_edit`) and
  re-pin the reference against cell-frame coordinates afterwards, so the error
  cannot accumulate. Anything else derived from that fit has the same problem.
- **"Is the base the asymmetric unit?" has TWO answers and both must be
  checked** (round 43e). A `SymmetryModifier` is one route; the ❖ page's
  "Asymmetric unit only" radio is the other, and it rebuilds the base while
  adding no modifier at all. Round 43d tested only the first, so the obvious
  route through the UI fell into the branch meant for a full cell and had its
  space group re-derived from one asymmetric unit — P1, correctly, about
  entirely the wrong question. When a state can be reached two ways, the
  predicate belongs in one named function that knows both.
- **Flattening by PROJECTION is not flattening** (round 43e). Projecting a
  substituent's atoms onto the ring plane makes it coplanar and shortens every
  bond that was out of the plane. The operation wanted is a RIGID one — swing
  the attachment bond into the plane, then spin about it — which preserves
  every internal coordinate exactly and can be verified as such. And note an
  sp3 group can NEVER be coplanar: what lands in the plane is its attachment
  atom, so say that rather than reporting a residual as a failure.
- **A boundary copy's lattice shifts belong to the MOLECULE, not to the atom
  that triggered it** (round 43b). A fragment sitting on a corner can have
  atoms on the x, y and z faces with none carrying all three coordinates at
  zero — so per-atom shift options generate three faces and three edges and
  never the eighth corner. Pool the options over the group whenever the group
  travels whole; keep them per-atom for a PERIODIC component, or rock salt
  grows a slab (round 33).
- **`geometric=` has to reach EVERY consumer of the fragment graph, and the
  ones that cull are the dangerous ones** (round 43b). Round 42d added it to
  `unwrap_molecules` and `fragment_info`; `expand`'s boundary branch and
  `_reaches_into_cell` were missed, and the second is worse than the first —
  it perceives its own bonds, so a shattered cage was culled SHARD BY SHARD
  and came back as a truncated stump with a centroid off the lattice point.
  When a rule says "keep the molecule if any atom is inside", a wrong notion
  of "molecule" does not disable the rule, it silently applies it to the wrong
  thing. Grep for every call that re-perceives bonds when adding such a flag.
- **The union of two separately-capped bond lists is NOT capped** (round 43).
  `_cap_hydrogens` picks each hydrogen's nearest heavy partner from whatever
  list it is handed, so capping the KEPT bonds and the FULL candidate set
  independently and then drawing both gives that hydrogen two sticks —
  whenever its nearest neighbour is one of the refused contacts, which on a
  disordered structure is most of them. 96 double-bonded hydrogens on
  `2240539.cif`. Cap the second list AGAINST the first (nearest first, skip a
  hydrogen that already has its stick), never separately. Applies to any
  "restore what we filtered out" feature, not just this one.
- **Check WHICH filter did the damage before building the override for it**
  (round 43). "Tick impossible bonds" was the request, and the impossibly
  short ones are only 96 of 528 refusals on the file in question — the valence
  cap does the rest, because a disordered site's alternatives all bond to the
  same neighbours. Building exactly what was asked would have shipped a tick
  that left the picture just as broken. One `Counter` over the drop reasons
  settled it in a second.
- **De-duplication runs BEFORE occupancy, so a shared site loses its species**
  (round 42). Several elements on one crystallographic position are identical
  coordinates, which `expand`'s minimum-image merge discards on sight — the
  disorder policy never sees them, and `POLICY_ALL` returns the same atoms,
  which is how to tell this apart from a round-38 disorder decision. Anything
  that needs to know what a merge threw away has to be computed from the
  ASYMMETRIC UNIT, not from the expanded atoms.
- **A per-atom map must be built after everything that renumbers** (round 42),
  and copies must inherit it. `site_occupancy` is keyed by drawn index, so
  resolving disorder, wrapping, boundary completion and the exterior search
  all invalidate it; and a boundary copy of a shared site is still that site.
  Match copies to their source on the fractional coordinate modulo 1 rather
  than threading site indices through every function that appends atoms.
- **`GL_LEQUAL` is how you redraw the same geometry with a different shader**
  (round 42). Identical mesh and identical model matrix give bit-identical
  depth, so the second pass wins on equality with no polygon offset and no
  z-fighting — and the atom stays an ordinary atom to picking, the selection
  hull and every other pass, which is what makes the pie spheres additive
  instead of a special case threaded through `_rebuild`.
- **"Longest first" is the wrong way to cull an over-valence atom when the
  excess is DUPLICATE ATOMS** (round 41). Every real C-C (~1.5 A) is longer
  than every real C-H (~1.0 A), so a carbon carrying a disordered methyl's six
  hydrogens loses its bond to the molecule and becomes a loose fragment —
  which then defeats whole-molecule boundary completion, because a fragment
  that is already inside the cell has nothing to complete. A bond that is some
  atom's LAST link to the heavy-atom skeleton must be sacrificed last.
- **A disordered site is not always DECLARED** (round 41). `4-ABA-oxime.cif`
  writes a methyl over two orientations with `_atom_site_occupancy` 1.0
  throughout, so `is_disordered` is False and `resolve_disorder` never runs.
  Occupancy is evidence of disorder; geometry (two same-element atoms 0.69 A
  apart) is proof of it, and the two do not always agree.
- **Never position a widget by literal layout INDEX** (round 41).
  `CrystalPage` used `insertWidget(2, ...)` and `insertWidget(5, ...)`; adding
  two widgets higher up moved the polyhedra checkbox into the middle of an
  unrelated block, with nothing failing and no error. Use
  `lay.indexOf(anchor) + 1` so the position survives the next addition.
- **The standard short H-M symbol does not name a SETTING** (round 41). All
  nine settings of number 14 are `P2_1/c`, so displaying it for a file that
  says `P 21/n` looks like a bug to the person who made the compound. Show the
  setting-preserving short form (derived from the full symbol by dropping its
  `1`s) — which is also what CIFs themselves write.
- **A space-group SYMBOL is not a space-group NUMBER** (round 40). `P 21/c`,
  `P 21/n` and `P 21/a` are all number 14; their operators differ, and the
  file's coordinates are in one specific setting. Resolving a symbol via its
  IT number therefore silently produces a wrong structure for two of the
  three — which is why the resolver goes through spglib's 530-entry HALL
  database (one entry per setting) and why an IT number, which carries no
  setting at all, is the last route tried and is reported as such.
- **pymatgen rejects the commonest spelling of the commonest space group**
  (round 40). `SpaceGroup("P 21/c")` raises `Bad international symbol`; it
  wants `P2_1/c`. Since `P 21/c` is exactly what CIFs write, any symbol
  lookup needs its own normalisation before it reaches a library — compare on
  a canonical key (letters and digits, case-folded), and register each full
  symbol's short form too, because `P 1 2_1/n 1` is how the database spells
  what the file calls `P 21/n`.
- **Space groups were RENAMED and old files still use the old names**
  (round 40). The 1992 edition of International Tables introduced the double
  glide `e`: Abm2/Aba2/Cmca/Cmma/Ccca became Aem2/Aea2/Cmce/Cmme/Ccce, and
  ZIF-L.cif says `Cmca`. Older files also drop the bar (`F d 3 m` for
  `Fd-3m`). Both are matched by GENERATING candidate modern spellings and
  checking them against the database, never by trusting the transformation:
  the e-glide aliases are accepted only if they land on one of the five
  groups that can have an e-glide.
- **A warning that fires every time is a warning nobody reads** (round 40).
  The first cut reported "setting b1 assumed" on every ordinary P2_1/c file,
  because the symbol technically matches nine Hall settings. `Symmetry.
  ambiguous` distinguishes "the input left a choice open" (P 21/n, an origin
  choice, R axes) from "convention settles it", and only the former is
  mentioned. Same discipline as round 38's chemistry notes: report what was
  actually decided, not what could theoretically have been.
- **Blank lines inside a loop header are legal CIF** (round 40). The tag scan
  stopped at the first non-`_` line, so a double-spaced file lost its ENTIRE
  atom-site loop and was rejected as "no fractional atom sites" — a good file,
  refused, with a message pointing at the wrong thing. `H7Mg2O10P2.cif` is the
  regression case. Skip blanks and comments while collecting tags; stop only
  at a non-blank line that is not a tag.
- **Measure before believing "it fails on almost all of them"** (round 39).
  Nine files, three independent references (ASE, pymatgen, and each file's own
  `_chemical_formula_sum` x `_cell_formula_units_Z`): six were already exact,
  one was not a structure, and the real bug was in one place. The formula x Z
  check needs no dependency at all and is the fastest way to separate "our
  reader is wrong" from "this file is unusual".
- **A finite molecule straddling a face is NOT severed** (round 39) —
  `unwrap_molecules` pulls it back together (round 19). The severing only
  happens where unwrapping is refused, i.e. in a percolating component (round
  25). So a test fixture for cut bonds must contain a FRAMEWORK; four carbons
  in a box will silently be reassembled and prove nothing.
- **Translating a fragment that straddles a face keeps it in pieces**
  (round 39). It is stored split precisely because it could not be unwrapped,
  so a rigid shift throws the far half two cells out, where it hangs bonded to
  nothing. Walk it contiguous around the atom you are placing FIRST, then
  translate that.
- **Dedupe image atoms against POSITIONS, not against (site, image) keys**
  (round 39). The key assumes every input atom is the (0,0,0) image of its
  site, which stops being true the moment the input carries boundary copies —
  `expand(boundary=True)` puts atoms outside [0,1) by design.
- **A module-global circuit breaker is shared state across the whole suite**
  (round 39). Anything that reaches the real network once marks OPSIN down,
  and later tests that expect it to be TRIED then fail in a different file
  with no obvious connection — passing alone, failing in the full run.
  `tests/conftest.py` resets it around every test, next to the QSettings
  sandbox and for the same reason.
- **A bond KIND is derived, not stored** (round 38). It is a pure function of
  the two element symbols, so `bond_kind(a, b)` cannot go stale, cannot be
  lost by an edit, needs no reindexing in `delete_atoms`, and never has to be
  added to `Scene.snapshot`/`to_dict` — the four-place checklist that
  `atom_colors` exists to remind you about. Store only what cannot be
  recomputed. (The cost is that a user cannot override one bond's kind; if
  that is ever wanted, add a sparse override dict and pay the four places.)
- **Cut the framework only where it is INFINITE** (round 38). Splitting every
  metal-ligand bond would dismantle ferrocene and strand a paddlewheel's
  ligands from their metal at the cell boundary. `fragment_info` walks the
  full graph first and applies the coordination cut only to components that
  came back periodic — the hierarchy is "molecule, unless that is impossible",
  not "always cut at metals".
- **A valence cap belongs on COVALENT bonds only** (round 38). Applied to all
  bonds it would cull a chloride bridging three metals, an eight-coordinate
  lanthanide, every framework node — i.e. exactly the structures the whole
  exercise is for. The two rules compose: coordination bonds are exempt from
  the cap, and the impossibly-short rule applies to everything because no
  chemistry puts two nuclei that close.
- **Physically impossible test fixtures start failing when the code gets
  chemistry** (round 38). `test_molecules_are_reassembled_across_the_boundary`
  used a 0.4 A O-H because the number was convenient; valence sanity now
  refuses it, and the test broke without the code being wrong. When adding a
  rule about what is real, expect the synthetic fixtures to be the first
  casualties — fix the fixture, not the rule.
- **Say what you refused to draw** (round 38). Three separate mechanisms now
  discard atoms and bonds, and a viewer that quietly hides part of a file
  earns a reputation for being wrong. `MainWindow.chemistry_note` surfaces
  every drop in the import message and on the ❖ page; `perceive_bonds` and
  `cif.expand` both take a `report` dict for the same reason.
- **A fallback tier that RETURNS on failure is not a fallback** (round 37).
  `resolve._resolve_inner` returned "couldn't reach OPSIN" on a tier-1 network
  error, so one service going quiet took the whole cascade down and
  import-by-name failed for names PubChem answers instantly. The shape to
  copy: catch, record the failure in a `trouble` list, FALL THROUGH, and
  report it as a NOTE on whatever does answer. And put a circuit breaker on it
  — re-learning that a service is down costs the full timeout every single
  time, which is what makes a working feature feel broken.
- **A read timeout is not a `URLError`** (round 37). `urlopen` wraps a
  CONNECT failure in URLError but a READ timeout raises a bare `TimeoutError`,
  and `ssl.SSLError` is another `OSError` that gets through. Normalise in the
  one HTTP helper, not at five call sites.
- **Generated source must be ASCII** (round 37). This project's prose is full
  of em dashes; a `.py` written for another program passes through whatever
  encoding the writing step happened to use, and one cp1252 write turns an em
  dash into byte 0x97, which Blender reports as `SyntaxError: 'utf-8' codec
  can't decode byte 0x97` in a file nobody has edited. `blender_export`
  ascii-folds everything it emits AND the app writes UTF-8 explicitly.
- **Verify a generated program by RUNNING it** (round 37). Blender 4.4/5.1
  live on this machine: `blender -b --python out.py -o render_ -f 1` renders
  headless in a couple of seconds, and the resulting PNG next to a
  `grabFramebuffer()` of the viewport is the only real proof the camera
  matches. It caught the ASCII bug (the script never ran, and Blender happily
  rendered its DEFAULT CUBE instead — a silent success is the dangerous
  failure) and an engine bug: `bl_rna.properties["engine"].enum_items` does
  not list external engines, so the Cycles check silently fell through to
  EEVEE. Assign and catch `TypeError` instead.
- **Blender's shader sockets are LINEAR** (round 37) while every colour picker
  is sRGB, so a palette dropped in raw renders visibly washed out; and lamp
  power must scale with distance SQUARED or a preset tuned on a small molecule
  leaves a framework black. An HDRI plus a full lamp rig double-lights the
  scene — halve the lamps when there is a world.
- **A gesture that CAPTURES the pointer cannot start optimistically**
  (round 36). "Start flight on the press; a click never travels anywhere" is
  false the moment taking off hides the cursor and re-centres it: the release
  arrives at the viewport centre, `_pick_at` finds nothing there, and the
  click half of the button is dead. Any press that both (a) grabs or moves the
  pointer and (b) shares its button with a click action must ARM and wait for
  a hold, a drag or a release to say which it was. The corollary is that the
  click's position must be the PRESS position, never the release's.
- **A deferral is a symptom, not a fix** (round 36, retiring round 35's).
  Holding the context menu back by a double-click interval was there only
  because the press had already committed to flight. Once the press commits to
  nothing, the menu can open immediately and the delay is pure loss. Whenever
  a "wait and see which gesture this is" timer appears, check whether the real
  problem is that something ACTED too early.
- **`_project` returns `(xy, in_front)`, not `xy`** (round 36). Indexing the
  tuple as an array raises inside `paintGL`, where Qt PRINTS the traceback and
  carries on — the overlay silently never draws. Caught by the GUI smoke run,
  invisible to every offscreen test. Same lesson as round 34: run a real
  window when touching a paint path.
- **Nothing camera-constant may be computed per PRIMITIVE** (round 35c). The
  round-33 lesson was "not in a paint path"; this is the sharper version. The
  symmetry overlay called `_eye_position()` once per line segment, and each
  call rebuilt the rotation matrix from the quaternion — 400 times a frame.
  `_camera_frame()` caches eye + view + projection keyed on the camera state
  (safe for the picking paths too, which run outside paintGL). Also: for a
  single 3-vector, plain scalar arithmetic beats numpy several times over,
  because the array allocation dominates. And memoise QPen/QColor — building
  them per segment was the other half.
- **An axis view's up vector is a pose the turntable cannot hold** (round
  35c). Any view whose up is a CELL axis rather than world Z is "rolled" as
  far as the yaw/pitch orbit is concerned, so orbiting out of it lurches.
  `Camera.auto_level` re-levels on the first orbit, exactly as `auto_ortho`
  pops back to perspective. Set it wherever a non-Z-up pose is imposed.
- **Softplus is the wrong curve for a stick** (round 35c). It is smooth and
  monotone, but its slope at the origin is already half its asymptotic slope,
  so it barely softens the centre — which is the entire reason to reach for a
  curve — and being asymptotically linear rather than bounded it needs
  renormalising for full stick to mean full rate. `x**expo` gives f(0)=0 and
  f(1)=1 exactly and puts all its flattening where small corrections happen.
  Apply it to the MAGNITUDE, never per axis, or a diagonal stick turns in the
  wrong direction.
- **Rotating an ORBIT camera moves the eye** (round 35b). `eye = center +
  R^T·[0,0,distance]`, so changing only `rotation` swings the eye around the
  pivot on an arc of radius `distance`. Fine for orbiting — that IS orbiting —
  and completely wrong for flying, where it reads as looking up bodily lifting
  you off the ground. Any first-person turn must capture the eye first and
  rebuild `center` behind it (`_fly_turn`).
- **Edge-wrapping a cursor only works where there is screen to wrap TO**
  (round 35b). The flight wrap died against the properties dock on the right
  and against the top and bottom of the window, so steering just stopped in
  those directions. For a first-person mode, CAPTURE instead: hide the
  pointer, hold it at a fixed anchor, take the delta against that anchor and
  put it straight back. There is then no edge to reach and no visible
  teleport.
- **A camera-relative aim must not decay if it is a CONTROL** (round 35b).
  A reticle that eases back to centre is a readout; one that stays put is a
  stick. Christian wanted the stick — the turn continues until the mark is
  brought home. If a UI element both displays state and commands it, decide
  which, because the two want opposite behaviour.
- **Our CIF reader agreeing with ASE is the fastest way to blame the file**
  (round 35b). HpPyBz_th.cif draws hydrogens with two bonds and has a 0.75 A
  atom-atom contact; ASE reads exactly the same 192 atoms and the same
  contact, which settles "is this us?" in one command. Do that check before
  touching the parser. Capping H at one bond is still right — a hydrogen with
  two sticks is never a picture worth drawing — but it fixes the DRAWING, not
  the geometry.
- **"View along an axis" means the axis points AT you** (round 35b), and the
  up axis is CYCLIC: right = next axis, up = the one after. So the b view has
  c across and a up. Both halves were backwards in the first cut, which made
  MoloM's b view the 90°-rotated mirror of Mercury's on the same file. There
  is no universal convention here — Mercury, VESTA and Diamond differ — so the
  axis buttons also flip on a second click rather than pretending one is
  canonical.
- **A slider whose scale disagrees with its range clamps silently** (round
  35b), and the readout keeps showing the value you asked for because the
  label is set from the input, not from the slider. Acceleration defaulted to
  60 into a 10..300 range read at ÷10, so it pinned at 30 and said "60.00".
  Set the label from the slider, or test the round trip.
- **An overlay pass must NOT borrow the scene's GPU buffers** (round 35).
  `_paint_selection` and `_paint_meta_glow` uploaded their instances into
  `_sphere`/`_cylinder` and set `_needs_rebuild` so the next frame would put
  the real geometry back. That makes the scene buffer's correctness depend on
  paint ORDER plus a flag: any frame that reaches `_sphere.draw()` without a
  rebuild first draws the enlarged orange hull INSTEAD of the molecule, which
  is a one-frame flash — driver- and timing-dependent, so it showed on the
  desktop and never on the laptop. It also forced a full CPU rebuild and
  `glBufferData` every frame whenever anything was selected. Give a new
  overlay its OWN `_InstancedMesh`; the duplicated static mesh data is a few
  KB and buys immunity from the whole class.
- **A per-axis weight in front of a NORMALISED vector does nothing** (round
  35). `flight.thrust_world` divides by the length, so scaling the key
  components to make strafing snappier is divided straight back out and the
  tuning silently has no effect. Weight the ACCELERATION instead
  (`FlightModel.accel_for` blends the per-axis figures by how much of the
  input is on each axis). A test pins it, because the failure is invisible.
- **`QToolButton.clicked` passes the checked state — swallow it** (round 34,
  re-learned in round 35's ribbon). Every slot connected to a button here
  takes `_c=False` as its first default argument so the boolean can never be
  read as a real parameter. Non-checkable buttons pass `False` forever.
- **A plain `QWidget` ignores its own stylesheet background** (round 35)
  unless `WA_StyledBackground` is set — Qt only paints backgrounds for
  subclasses it knows. The crystal ribbon came out as loose controls floating
  on the bare viewport instead of a panel. Applies to any new floating strip.
- **Overloading single- and double-click on one button costs a delay**
  (round 35). Right-click opens the context menu and right-DOUBLE-click
  latches flight, and Qt fires the first click's action before it can know a
  second is coming (the round-8 gotcha). The menu is therefore deferred by
  `doubleClickInterval()` — but ONLY when a menu would actually open, which
  `open_context_menu` already restricts to a click on an already-selected
  atom. Scope any such deferral the same way, or every gesture pays for it.
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
  **And the sandbox has to be EMPTIED between tests** (round 77). It stops a
  test writing into the developer's config and does nothing about one test
  writing into the next one's: `MainWindow` reads its preferences on
  construction, so `win._fps_spin.setValue(10)` in one file hands 10 fps to
  every window built after it. Round 77's playback tests were the first to
  assert anything derived from the framerate and duly failed only in the
  FULL RUN — passing alone, which is the signature of shared state and the
  same shape as the round-37 circuit breaker and the round-46 module cache.
  `tests/conftest.py::_fresh_settings` clears it after every test.
- **AN INSTANCE COLOUR IS RGBA, AND THE FAILURE LOOKS NOTHING LIKE A COLOUR
  BUG** (round 86). `_InstancedMesh`'s attribute layout is `istride = 20 * 4`
  - sixteen matrix floats plus a **vec4** - so uploading a three-float colour
  shifts every instance after the first by one float and the buffer is read as
  garbage. It draws as enormous white triangles across the whole frame, raises
  nothing, and every offline test passes. Any new instanced pass must upload
  RGBA.
- **A NEW DRAW PASS HAS TO BE VERIFIED BY THE CLAIM IT MAKES, NOT BY COUNTING
  COLOURED PIXELS** (round 86). Checking that a depth-ordered cell box is
  occluded by counting "axis-coloured" pixels measures the ROD'S THICKNESS in
  one mode against a pen width in the other, and counts the floor grid's red
  and green axes and the molecule's own red oxygens into the bargain - it said
  the feature worked when it did not, and then that it did not when it did.
  The colour-agnostic form is three frames (no box / box on top / box in
  depth) and a pixel-by-pixel comparison: a pixel the overlay paints, where
  the depth frame still equals the no-box frame, is a pixel the depth test
  refused. Same shape as round 53's A/B differencing.
- **A QTreeWidget DRAWS NO EXPANDER ARROW ON AN ITEM WITH NO CHILDREN**
  (round 86), so a group emptied on collapse becomes a leaf and can never be
  opened again. The placeholder child is not a nicety; it is what keeps a
  lazily-filled group openable. And the guard around a lazy fill must be
  SAVED AND RESTORED rather than forced back to False, because `sync` holds
  the same guard down for the whole rebuild.
- **A ROW WIDGET IS THE COST OF AN OUTLINER, NOT WHAT IS IN IT** (round 86).
  Measured: 300 tree rows carrying one bare `QWidget` each cost 14.5 ms; the
  same rows carrying five QToolButtons and a layout cost 473 ms. If a row
  control is a few fixed rectangles with a letter in them, paint them - and
  free them when the group closes, or `refresh_row_controls` goes on walking
  them for the rest of the session.
- **`processEvents()` DOES NOT DISPATCH DeferredDelete** (round 86), so
  `close()` + `deleteLater()` frees NOTHING and looks like a leak somewhere
  else entirely - measured as identical to no teardown at all over 20 windows.
  `QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)` is the
  missing line, and with it the ordinary idiom frees everything. Reaching for
  `shiboken6.delete` instead also works, right up until it destroys a window
  whose QMenu is separately in `topLevelWidgets()` - `isValid` still says that
  menu is live, and touching it is an access violation.
- **A PIXEL COUNTER OVER A WHOLE FRAME IS USUALLY MEASURING SOMETHING ELSE**
  (round 89, and the third instance in one session). It reported a constant
  876 px for a molecule whose projection was demonstrably changing, because
  the object filled the window and clipped, so max-minus-min saturated. Round
  86's first cut counted the floor grid's red and green axis lines; its second
  counted red oxygens as red cell-box rods. Measure the QUANTITY - a matrix
  element, a frame-to-frame difference - and use the picture to confirm by
  eye, not to count.
- **A QTableWidgetItem KEEPS DisplayRole AND EditRole IN ONE SLOT** (round
  90). Writing a sort value into `Qt.EditRole` therefore REPLACES the text
  the cell was built with, and the column is rendered by Qt instead of by
  whatever formatted it. Round 86 did that so Qt could compare numerically
  and then sorted in Python anyway, so the write was pure harm - invisible
  for four rounds because a year and a temperature are whole numbers and
  293.0 renders as "293", and obvious the moment a molecular weight put
  RDKit's 106.168 next to PubChem's 106.16 in one column. If the sorting is
  hand-driven, do not write EditRole at all.
- **A BOUNDARY COPY IS THE SAME ATOM, SO EVERY EDIT HAS TO REACH IT**
  (round 99). A packed crystal draws an atom on a face twice and one on a
  corner eight times, as independent entries - `packing.image_groups` is the
  map, `images_of` the same question for one selection. An element change and
  a delete have gone through it since round 54; a GEOMETRY edit goes through
  `MainWindow._sync_packed_images`, which applies the same DELTA to every
  image. That is exact rather than approximate because images differ by a
  lattice translation and a translation commutes with a displacement. Do NOT
  reach for re-packing instead: `pack` unwraps molecules, so re-packing atoms
  it has already relocated does not reproduce the picture (round 52), and it
  renumbers everything (round 80).
- **THE FIRST `cell_content` DRAWN ATOMS ARE NOT THE CELL CONTENT** (round
  95). `packing.pack` says so in its own comments - `complete_molecules`
  REORDERS and duplicates - so a prefix slice is a different set of atoms.
  Measured on ferrocene: the first 42 drawn atoms are one molecule plus a
  lattice copy of it, where the cell holds two molecules related by a screw
  axis. `meta["content_of"]` is the map that answers it (the first drawn image
  of each content atom); `MainWindow._content_atom_indices` is the one place
  that reads it. Anything writing an asymmetric unit or exporting a cell has
  to go through it.
- **REDUCE A CURVE AT DEVICE RESOLUTION, NOT LOGICAL** (round 98). A min/max
  envelope built per `rect.width()` column has treads one and a half real
  pixels wide on a 150% display, and it reads as broken antialiasing -
  antialiasing cannot smooth a step it was told to draw. Use
  `width * devicePixelRatioF()`.
- **AN EDITABLE QComboBox INSERTS WHAT YOU TYPE** (round 98), as a new item
  whose `itemData` is None. Reading the data of the current row then gives
  `None` for exactly the typed values the box exists to accept - here, a
  custom wavelength, which was refused and left a whole pattern at the
  previous one. `setInsertPolicy(QComboBox.NoInsert)`, and fall back to the
  text whenever the row carries no data.
- **A GERMAN LOCALE'S DECIMAL SEPARATOR IS A COMMA** (round 98), so a
  QDoubleSpinBox silently keeps its old value when "0.15" is typed and
  `float("1,5406")` raises. Normalise both ways in `validate` /
  `valueFromText` and wherever a number is parsed out of free text - between
  DIGITS only, so a comma that separates two things still does.
- **A QFormLayout'S WIDEST ROW SETS THE WINDOW'S MINIMUM WIDTH** (round 98)
  unless it is told otherwise: `setFieldGrowthPolicy(AllNonFixedFieldsGrow)`
  plus `setRowWrapPolicy(WrapLongRows)`. One tab nobody has open while
  resizing had put the whole window's minimum back up by 400 px.
- **A STORED CURVE HAS ONE SAMPLING AND A PLOT HAS MANY ZOOM LEVELS**
  (round 97). A fixed grid is simultaneously too dense zoomed out (thousands
  of points on one pixel) and too sparse zoomed in - measured at 12 points
  across 754 pixels, i.e. a polygon. Where the curve is an analytic function,
  evaluate it AT THE PIXEL COLUMNS being drawn: the count is then bounded by
  the width of the window at every zoom. Supersample each column and reduce
  by min/max, or a peak narrower than a pixel falls between two samples and
  is drawn at 60% of its height. And choose between resampling and decimating
  the stored grid by WHICH IS FINER - resampling unconditionally draws peak
  tops low when zoomed out.
- **`resize` TAKES LOGICAL PIXELS, AND A LAYOUT MINIMUM OVERRIDES IT ANYWAY**
  (round 97). At 150% a 980 x 660 window is 1470 x 990 real ones, taller than
  a 1080p working area - so half the controls were off the bottom of the
  screen. Clamp the opening size to `screen().availableGeometry()`. And check
  `minimumSizeHint` before blaming `resize`: a word-wrapped QLabel reports
  the height it needs at its MINIMUM WIDTH (round 90d again), which set this
  window's minimum height to 634 px on its own, and fixed control rows set
  the width. Cap the label, and use `widgets.FlowLayout` for the rows.
- **A QDialog HAS NO MINIMISE OR MAXIMISE BUTTON** (round 97). Fine for a
  dialog; wrong for a modeless TOOL window somebody will want full-screen.
  `Qt.Window` plus `WindowMinimizeButtonHint` / `WindowMaximizeButtonHint`.
- **A QPixmap IS ALLOCATED IN DEVICE PIXELS AND PAINTED IN LOGICAL ONES**
  (round 96, and round 59 in `tools/screenshots.py` before it). `QPixmap(w,
  h)` gives w x h DEVICE pixels; `setDevicePixelRatio(1.5)` then declares
  them to be w/1.5 x h/1.5 logical ones, so a cache made at a widget's
  logical size covers two thirds of a 150% display. Allocate at
  `size * devicePixelRatioF()` and set the ratio; the painter works in
  logical coordinates either way, which is what makes everything drawn into
  it correct as it stands. It does not look like a scaling bug - it looks
  like the widget failed to lay out, because the part the pixmap does not
  cover is bare unpainted widget.
- **`QMenu.exec` RUNS A MODAL EVENT LOOP** (round 96), so a test that reaches
  one HANGS rather than failing - round 75's worst-shape-of-problem again.
  Build a context menu in a method that RETURNS it and show it in one line;
  the logic is all in the building.
- **A NUMBER SHOWN IN A BOX MUST ROUND-TRIP THROUGH IT** (round 96).
  `{:.5f}` renders Cu K-alpha1 as "1.54060", and the box hands that back as a
  different wavelength - which recomputed every pattern on every edit and
  moved every peak by a ten-thousandth of a degree. `{:.10g}` round-trips.
  Only the cache made it visible, which is an argument for caches.
- **A PYTHON LOOP IN A PAINT PATH COSTS MORE THAN THE POINTS IT SAVES**
  (round 96). Decimating a curve to one point per pixel column is right and
  is worth 5x; doing the selection with a `for` over a thousand columns made
  the window SLOWER than drawing all 4501 points. `np.repeat` plus a
  cumulative index. Same family as round 33 and round 50.
- **`resizeColumnsToContents` IGNORES A SECTION'S RESIZE MODE** (round 95).
  `QTableView.resizeColumnsToContents` is `resizeSections(ResizeToContents)`,
  which by documented design overrides the per-section mode - so it fits a
  STRETCH column to its longest entry too. Measured on the crystal search: a
  long name takes that column to 1771 px inside a 796 px viewport, and a
  relayout then snaps it back, which is the width visibly flipping between
  "contracted and full width used". Set the stretch column up once and fit the
  other columns ONE BY ONE.
- **A WRAPPED CELL'S HEIGHT DEPENDS ON ITS COLUMN'S WIDTH AND NOTHING
  PROPAGATES THAT** (round 95, round 90c's `heightForWidth` trap in an item
  view). `setWordWrap(True)` alone leaves a two-line name in a one-line row; a
  `ResizeToContents` vertical header fixes the initial layout and a
  `resizeEvent` calling `resizeRowsToContents` fixes it again after the window
  is widened.
- **RESTORE THE ACTIVE OBJECT *AFTER* PUTTING THE SELECTION BACK** (round 95).
  Every crystal-page fan-out ends with `select_whole_molecules`, which emits
  `selection_changed`, and picking moves the ACTIVE object to the last thing
  selected (round 7). Restoring `active_id` first therefore does nothing: the
  page comes back describing the last crystal in the list, its per-crystal
  ticks read THAT crystal's state, and if it happens to be an edited P1 cell
  the whole page greys. It reads as a tick turning itself on.
- **A PER-OBJECT FLAG GREYS THE PAGE ONLY IF EVERY TARGET HAS IT** (round 95).
  `cell_frozen` was read off the SUBJECT alone, so one edited cell in a
  selection of five disabled the contents radio for the other four - which
  would have worked perfectly well, since a frozen target is passed over the
  same way a molecule is. Say how many were skipped instead of refusing.
- **A REBUILD DROPS AND RE-SETS EVERY PER-ATOM MAP TOGETHER** (round 93, and
  round 83 said it first). `on_crystal_view` set `packed_bonds` only when the
  new view produced one, so switching to an asymmetric unit left the previous
  FULL CELL's bond list in metadata and `_perceive_fresh` applied 27-atom
  indices to two atoms. Setting conditionally is not the same as replacing.
- **A REFERENCE SAMPLE MUST BE CLEARED WHEN IT CANNOT BE RE-PINNED** (round
  92b). `set_cell_reference` refuses to pin below three atoms, which is right,
  and used to leave the OLD sample behind - so an asymmetric unit of two atoms
  kept 24 indices into a 27-atom list, the fit failed silently, and the
  crystal and its box snapped to the origin. Where no sample can exist the
  pose is recorded explicitly instead (`set_cell_pose`).
- **NOT EVERYTHING THAT IS NOT AN XYZ BLOCK IS A SMILES** (round 92b). The
  paste path assumed it was, so a CAS number produced two backend parse errors
  in a dialog. `resolve.classify` separates smiles / inchi / inchikey / cas /
  name and has done all along.
- **A RIGID MOTION IS NOT AN EDIT TO THE STRUCTURE** (round 91). Moving or
  turning a whole crystal preserves its space group exactly, so anything that
  re-derives symmetry on an edit commit has to ask WHAT the edit was -
  `_edit_was_rigid` fits the before and after with Kabsch. Without it a plain
  grab demoted `F m -3 m` to `P 1` and froze the cell, which then greys the ❖
  controls and reads as an unrelated UI bug. The composition has to be
  compared too: an element change moves no atoms at all.
- **A STYLESHEET SET ON A WIDGET APPLIES TO ITS CHILDREN** (round 90d), so
  `setStyleSheet("background: ...")` on a card paints every label inside it as
  its own little box. It reads as a deliberate (and ugly) design rather than
  as a bug. Scope it - `QFrame#propcard { ... }` with a matching
  `setObjectName` - whenever the sheet is meant for the widget alone.
- **A WORD-WRAPPED QLabel MUST BE ALLOWED TO SHRINK, NOT THE LAYOUT TO GROW**
  (round 90d). `QLayout.SetMinimumSize` stops a card being squashed vertically
  and immediately makes it as WIDE as its widest child's minimum, so a long
  value pushes the card past its dock and clips instead of wrapping. Both are
  the same missing `heightForWidth`; the fix that solves both is
  `setMinimumWidth(1)` plus a `Minimum` vertical size policy on the label.
- **SELECTABLE TEXT NEEDS THE I-BEAM CURSOR** (round 90d). Setting only
  `TextSelectableByMouse` gives you text that can be copied with nothing on
  screen saying so, which Christian rates as worse than not being able to
  copy it at all.
- **FOUR PATHS CHANGE THE ACTIVE OBJECT, AND EACH RE-SYNCS ITS PANELS BY
  HAND** (round 90c): `_sync_all`, `_on_obj_activated` (an outliner row),
  `_on_outliner_atoms` and `_on_selection_changed` (a viewport pick). Wiring a
  new panel into `_sync_all` alone covers imports and scene changes and NOT
  selection - so the panel keeps describing the molecule you clicked away
  from, and any button on it acts on that one. Round 51's bug, and round 90
  reintroduced it inside the hook added to prevent it. Anything per-object
  goes through `_sync_addon_pages()` or all four call sites.
- **A WRAPPED QLabel'S HEIGHT DEPENDS ON ITS WIDTH AND A QFrame DOES NOT
  PROPAGATE `heightForWidth`** (round 90c), so a frame full of wrapped labels
  can be given less height than its contents need and draws them on top of one
  another. `QLayout.SetMinimumSize` on the frame's own layout is the fix. It
  only shows once a card gets tall, which is why it survived until a property
  was expanded to seven values.
- **`deleteLater()` ALONE DOES NOT STOP A WIDGET PAINTING** (round 90c). The
  delete is dispatched on a later pass of the event loop (and never by
  `processEvents` - round 86), so a cleared row remains a child of its parent
  and keeps drawing at its old geometry until then - a ghost of the previous
  layout over the new one. `setParent(None)` first, then `deleteLater()`.
- **THE SELECTION OUTLINE MUST BE BUILT FROM `style.bond_cylinders`**
  (round 90c). A double bond is drawn as two cylinders offset by +-1.0*r at
  radius 1.3*r, so a single hull cylinder on the bond AXIS is swallowed whole
  and the bond shows no outline at all. It was hidden for five rounds because
  round 35 thinned the outline by 5x, which was right for the atoms and is
  what sank the hull inside the bond.
- **A FIXTURE PRUNED OF A FIELD THE CODE BRANCHES ON IS NOT A CAPTURE OF THE
  SERVICE** (round 90b, and it happened TWICE - the second time the pruned
  field was `URL`, so the source-link branch had nothing to read). The computed-properties fixture was captured without
  its `Reference` table, so the source-attribution branch that reads that
  table was never exercised and a test asserting the RIGHT answer passed on a
  payload PubChem does not send. The real page showed `[PubChem]` on twelve
  rows where it should have named XLogP3 and Cactvs. When trimming a captured
  payload, keep every field any branch reads - or capture it whole.
- **PUBCHEM SPLITS PROPERTIES INTO TWO SECTIONS AND A COMPOUND MAY HAVE ONLY
  ONE** (round 90b). `Experimental Properties` 404s with `PUGVIEW.NotFound`
  for Cassipourine (CID 101821144) while `Computed Properties` returns 16 kB.
  A 404 on one heading is an ordinary answer, not a failure, and asking for
  only one of the two makes an entry full of data look empty.
- **PUBCHEM ALLOWS 5 REQUESTS A SECOND AND REFUSES THE SIXTH SILENTLY**
  (round 90). Measured: twelve name lookups through an 8-worker pool finish
  in 0.64 s and the last two are 503 "too many requests per second" - and the
  one that gets refused is whichever call happens to be last, which in a
  search is the bulk property call that fills every row. The rows then draw
  with no name and no weight, looking exactly like broken enrichment, and it
  depends on how many suggestions came back, so it strikes one query and not
  the next. Any new PubChem call goes through `molsearch._pubchem_json`.
- **THE JOIN KEY BETWEEN CHEMICAL DATABASES IS THE InChIKey** (round 90) -
  not the name, which 404s for "xylene" and "cresol" on PubChem's own index
  while it holds both compounds; not a CID, which is PubChem-local and is
  what you get after the join; and not a SMILES, since RDKit and OpenBabel
  produce different canonical strings for one molecule. Anything that has to
  ask a second service about a structure hashes it first.
- **A CARTESIAN ROUND TRIP MOVES AN ATOM OFF A SPECIAL POSITION** (round 87).
  Converting coordinates out to Cartesian and back leaves an atom that sits at
  exactly 0 at about -9.45e-17, and the SIGN is what does the damage: a tiny
  negative fraction is on the far face of the cell, so the next expansion
  gives that site an extra boundary copy. The solid solution came back as 22
  atoms instead of 21 - a structure changed by floating-point noise. Snap
  fractional coordinates before storing them (`_snap_fractional`), and
  remember `+ 0.0`, which is what turns -0.0 back into 0.0. Round 45b hit the
  same thing in the symmetry operators.
- **A COLUMN INDEX WRITTEN INTO A TEST IS A POSITION, NOT A CLAIM** (round
  87). Inserting a star column at 0 shifted every other column by one and
  broke six tests while nothing behaved differently. Name the columns on the
  widget and have the tests ask by meaning - the same lesson round 71 learned
  about pinning a line of source.
- **SETTING ANYTHING ON COLUMN 0 OF A QTreeWidgetItem LOOKS LIKE A RENAME**
  (round 86, found by running the manual checklist; it predates the round).
  `setData` AND `setToolTip` both emit `itemChanged`, and `_on_item_changed`
  reads column 0 on an object row as a rename - so `_mark_hidden` emitted
  `renamed(1, 'cubane')`, the app re-synced the outliner, every item was
  destroyed, and the next write in the same method hit a dead one. Qt swallows
  that RuntimeError, so the symptom was not a crash: `refresh_row_controls`
  ABORTED partway, and with two molecules open hiding atoms in one left the
  other's stripe stale. Guard the WHOLE body with `_loading` - the first fix
  covered only the two `setData` calls, which silenced the exception (nothing
  writes after the tooltip) while leaving the spurious rename in place.
- **AN OFFSCREEN TIMING IS A FINE A/B AND A BAD ABSOLUTE** (round 86). The
  outliner's expand was reported as 473 -> 73 ms from an offscreen run; in a
  real shown window the same 300 rows are 3.0 s -> 1.5 s, because offscreen
  nothing paints. The improvement was real and the absolute was off by 20x.
  Quote real-window numbers for anything a user waits on.
- **A WORKER QThread MUST NOT BE A CHILD OF THE WIDGET THAT STARTED IT**
  (round 86). Destroying the widget destroys a running thread, which is an
  access violation with no Python traceback - it presents as the process
  vanishing at exit 127 long after the code that caused it. Un-parenting alone
  is not the fix either: `self._worker` is then the only reference and dies
  with the dialog, so Python may collect the thread mid-run (round 76).
  `dialogs._own_worker` holds it in a module-level set until `finished`, and
  `wait_for_workers()` runs before the process exits, because a thread
  outliving its dialog is correct while one outliving the process is not.
- **A DATABASE'S NAMES ARE NOT A SEARCH INDEX** (round 85). COD returns 2617
  rows for "benzoic acid" and exactly ONE is named that; the pure compound's
  own entries are spelled "benzioc acid" with no chemname. Search a NAME by
  resolving it to a FORMULA - a formula cannot be mistyped into invisibility -
  and keep the text search alongside for what a formula cannot express.
- **AN ABSENT NAME IS NOT EVIDENCE AGAINST** (round 85). Ranking rewarded weak
  name similarity, so a wrongly-named isomer outranked an unnamed entry that
  was the compound being looked for - and COD leaves most entries unnamed. A
  matching name is evidence for, a clearly different one is evidence against,
  a missing one is neither.
- **AN ACRONYM CAN PARSE AS A FORMULA** (round 85). "DMSO" splits into D, M,
  S, O, all of which look like element symbols. Check every token against the
  element table, or the name resolver is silently never consulted.
- **AN API YOU HAVE NOT CALLED IS AN API YOU HAVE GUESSED AT** (round 84).
  Five bugs in `core/cifsearch.py` were found by calling COD, Materials
  Project and OQMD for real, and none of them was findable by reading: COD
  wraps its formulae in dashes, MP's descriptive formula is the whole cell,
  COD's OPTIMADE endpoint answers 501, a substring test cannot tell
  "ferrocene" from "Ferrocenecarboxylic anhydride", and COD returns rows in
  file-id order so truncating before ranking picks the shortlist at random.
  Two of those failed SILENTLY - the tier returned nothing and said nothing.
- **A SEARCH IS NOT A RESOLUTION** (round 84). `resolve` cascades because a
  molecule name has one answer; `cifsearch` fans out because a crystal name
  has many, and every tier may hold part of the answer. Cascading would also
  hide an instant local hit behind a slow remote one.
- **A MAP KEYED BY INDEX CAN BE OVERWRITTEN BY ONE THAT MEANS SOMETHING ELSE**
  (round 83). `packing.pack`'s `site_occupancy` is keyed by DRAWN index;
  `expand(boundary=False)`'s is keyed by CONTENT index. Two callers assigned
  the second over the first, and because a content atom is its own first
  image the two AGREE on the opening atoms - so the damage looked like a
  feature that worked on some sites and not others rather than like a bug.
  When two producers fill the same metadata key, check what the KEYS mean, not
  just whether the value is present.
- **A RELATIVE BOND FLOOR IS LOOSEST WHERE HYDROGEN IS** (round 82).
  `0.65 x (r_i + r_j)` gives C-H 0.696 A and O-H 0.617, so a badly refined
  hydrogen - the atom most likely to be misplaced, having the fewest electrons
  to place it with - had the loosest guard of anything. `SHORTEST_REAL_BOND`
  (0.80) is taken as a `max` with it. The number is bounded on BOTH sides by
  real chemistry: above HeH+ (0.772, and MoloM bonds neither it nor H2), below
  the shortest hydrogen an X-ray refinement really produces (0.88).
- **A SHORT CONTACT IS A SYMPTOM, NOT THE FUSION** (round 82). Two molecules
  interpenetrating with an impossible 0.75 A contact are still fused after it
  is refused - by ordinary 1.027 A C-H contacts to atoms that are simply in
  the wrong place. No distance rule can refuse those, which is why the
  fragment walk still needs the valence cap even though the drawn picture no
  longer uses one.
- **A CIF VIEWER DRAWS THE FILE, NOT THE CHEMISTRY IT WISHES IT HAD**
  (round 81). Over-valence is DRAWN in a crystal - `cif.display_bonds` passes
  `valence=False, cap_hydrogens=False` - because a carbon with six hydrogens is
  what a methyl disordered over two orientations at full occupancy looks like,
  and it is informative either as a real limitation of the model or as a bad
  refinement. Capping forced a choice of which bond to sacrifice, and for a
  crystal that choice is systematically wrong: every real C-C is longer than
  every real C-H, so "longest first" sacrifices the skeleton to keep the
  duplicates. The cap survives for MOLECULES (the draw tool's chemistry) and
  for `periodic_pairs` (what belongs TOGETHER, for the fragment walks) - round
  42d's rule read from the other side: group by chemistry, draw by the file.
- **A DELETE RENUMBERS, SO DELETE THROUGH THE OBJECT** (round 80).
  `MolObject.delete_atoms` / `.adjust_hydrogens` / `.set_element_adjusted` are
  the paired calls: `edits` can only reach what is on the STRUCTURE, and a
  molecule's colours, labels, hidden atoms and sphere sizes are on the OBJECT.
  Every per-atom map is enumerated in exactly two places -
  `edits._PER_ATOM_*` and `MolObject.ATOM_MAPS` - and a test compares the
  second against every `atom_*` field on a live object, so a new one cannot be
  added and forgotten. **The failure is silent by construction**: an index map
  stays perfectly VALID after a renumbering and simply means a different atom,
  which is why `meta.prune` (out-of-range entries only) hid it for twenty
  rounds. And note the path nobody thinks of: `adjust_hydrogens` REMOVING a
  surplus H renumbers exactly as a delete does, which is what C -> O and a
  raised bond order both do.
- **A TRACKPAD SWIPE IS NEVER PURELY ONE AXIS** (round 79). Testing `if dx`
  before `dy` hands every vertical flick that drifts a few pixels sideways to
  the horizontal branch, so the gesture works about half the time - which is
  what "spotty" means and is very hard to see in a test that sends clean
  single-axis events. Choose by the DOMINANT axis, LATCH the action for the
  whole gesture (round 8: decided at gesture start, never per event), and read
  BOTH axes from the same source - `dx` from `pixelDelta` while `dy` falls back
  to `angleDelta` means horizontal scroll simply never arrives on a device that
  reports angles. A wheel notch and a fixed number of trackpad pixels must also
  be normalised to one unit, or the same movement zooms by different amounts on
  the two machines. It all lives in `core/input_map.py`, with the rest of the
  round-16 reasoning.
- **A PANEL SHOWING A STALE NUMBER IS WORSE THAN ONE SHOWING NOTHING**
  (round 79), because nothing about it looks wrong. Anything that edits a value
  a properties page displays has to refresh that page - dragging a strip in the
  track pane changed the same Start the strip page shows, and only the clock
  and the bar were re-synced.
- **NEVER RECOMPUTE A VIEWING PROPERTY FROM THE CONTENT** (round 78, and it
  cost two separate bugs in one gesture). The frame range followed `duration`
  and the pane re-fitted its axis whenever the content outgrew the view - so
  dragging a strip to the right moved Frame End AND rescaled the axis, on every
  mouse move, which reads as the strips shrinking under the hand. A range and
  an axis are DECISIONS: fit them once, or when something asks, and never as a
  side effect of the data changing. The same rule already governs the camera
  (`fit_view` is not run on every import).
- **A UI POSITION SET BY THE MOUSE MUST SNAP TO THE GRID IT LIVES ON**
  (round 78). A strip dragged to 3.7 has its last frame between two scene
  frames, so a loop fitted to it is not a whole number of frames and the wrap
  gains or loses one - reported as "one frame too much or too little", which
  sounds like an arithmetic bug and is a snapping one.
- **`int(1000 / fps)` IS NOT A FRAME INTERVAL ON WINDOWS** (round 78). It is
  16 ms at 60 fps against a ~15.6 ms default timer granularity, so the timer
  fires every 31.2 and playback runs at HALF the advertised rate - 60 frames in
  1.87 s. Any one-frame-per-tick scheme also slows down (rather than dropping
  frames) as soon as a repaint costs more than a frame. Advance by elapsed
  `perf_counter` time, carry the remainder, and let the timer oversample.
- **A LOOP OVER STORED FRAMES HAS TO KNOW WHETHER THE LAST ONE IS THE FIRST**
  (round 77). `vibrations.mode_frames` stores k = 0..n-1 of a period and
  deliberately omits the duplicate k = n, so wrapping at `n - 1` — which is
  what the player did for fifty-odd rounds — covers 93.3% of a 20-sample
  oscillation and then crosses the rest in ONE image, four times the normal
  step. An imported trajectory is the opposite: its last frame is real data
  and must be shown, and the cut back to the first is honest rather than
  something to interpolate across. `timeline.CYCLIC_FRAMES` in the
  structure's metadata is the one place that distinction is recorded, and
  `interpolate.frame_pair(cyclic=)` is the other half — it CLAMPS by
  default, which freezes the closing arc instead of blending it.
- **A frame is a COLUMN on the timeline axis, not a line** (round 77).
  Frame k occupies `[x(k), x(k+1))`, which is why a strip draws out to its
  EXCLUSIVE `end_time` while `duration` and Frame End are the last frame
  INCLUSIVE. Anything drawn at a range limit therefore belongs at
  `x(play_end + 1)`: putting it at `x(play_end)` veils the last frame that
  actually plays and says it is excluded.
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
- Deps: numpy, PySide6, PyOpenGL, spglib, **rdkit and openbabel-wheel** —
  all REQUIRED as of 2026-08-25. The last two were the `chem` extra on OWB's
  graceful-tiering model; measured, a base install read **2 of the 13 formats
  the Open dialog offers** and had no SMILES and no Optimize panel at all, for
  43.5 MB against the 665 MB of Qt already mandatory. The runtime code still
  degrades gracefully if an import fails — that costs nothing and is what
  makes the tiers testable — but nobody should be running without them.
  `imageio-ffmpeg` remains the one real extra (`molom[video]`).
- NOT a cluster tool. No SLURM/ssh anywhere. The LiDO gateway has no
  PySide6/GPU — MoloM is for local machines; the gateway keeps molden.
- It IS a git repo now (single "Initial commit", 2026-08-01), so behavioural
  changes are diffable from here on.

## Verification workflow
1. `python -m pytest tests/ -q` — 2118 offline tests, 4 skipped, ~230 s.
   `tests/conftest.py` sandboxes QSettings, so a GUI test can drive a real
   control without writing into your own MoloM configuration; it also
   **destroys the windows a test created** (round 86), without which the suite
   accumulates ~413 widgets per test and stops finishing at all. Two
   consequences worth knowing: a module- or session-scoped WIDGET fixture no
   longer works, and any new worker thread must be unparented and registered
   through `dialogs._own_worker`, or tearing its dialog down kills the run.
2. `python -m molom --selftest` — headless core sanity.
3. GUI smoke: `python tools/smoke_gui.py` — a REAL window (never
   offscreen), which is the only thing that can catch a paintGL
   exception. It wraps every `_draw*`/`_paint*` method so a raise is RECORDED
   rather than swallowed, grabs a framebuffer per step and exits non-zero.
   Steps cover the crystal overlays (polyhedra, symmetry, ghosts, refused
   bonds, the boundary ticks), the **camera view** (lens, frame zoom, roll,
   orbiting out — round 57) and a **baked vibration with a selection on it**
   (the bond count is printed, because a vibration that loses bonds is the
   round-57 failure). The PNGs land in `tools/_smoke/` and are meant to be
   looked at, not just asserted.

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
1. ~~**Blender export**~~ **DELIVERED round 37** (`core/blender_export.py`,
   Ctrl+Shift+B) — materials, camera, HDRI, lamps, unit cell, render setup,
   behind a pre-configuration dialog. Verified by running the output in
   Blender 5.1 headless and comparing the render with the viewport. **Round 50
   added coordination polyhedra and a `.blend` output**: Blender is invoked to
   build the scene, so the saved file opens complete and F12 renders it.
2. **Offscreen supersampling** — render the existing GL scene into an FBO at
   4-8x and downsample. Cheap to add, no new dependency, no new look.
3. **POV-Ray** — what Avogadro 1 used. Still works and produces nice CPU
   ray-traced output, but it is an aging ecosystem (last release 2021), a
   separate binary the user must install, and its own scene language to
   maintain. Only worth it if a specific journal-style look is wanted.
NOT recommended: bundling a Python ray tracer (slow, another dependency).

## NEXT UP — measured issues, in priority order (2026-08-08)
Round 49's list is DONE except for one item; what is left, plus what round 50
turned up while doing it. Christian is on the DESKTOP PC.

~~0. PERFORMANCE: `polyhedra.shade_colors` runs a Python loop per TRIANGLE per
FRAME.~~ **FIXED in round 50** — 53 ms -> 0.32 ms at 400 octahedra, output
byte-identical. Worth re-measuring a real frame with a packed MOF on screen
before calling the slowdown closed: this was the biggest single cost in the
paint path but it need not have been the only one.

~~1. The Blender export drops COORDINATION POLYHEDRA.~~ **DELIVERED round 50.**

~~2. There is NO CIF WRITER.~~ **DELIVERED round 50** (`core/cif_write.py`),
and round 51 closed its one gap: occupancy now survives a re-derivation, via
the `site_of` map `packing.pack` was already recording. Still worth doing once
there is a test set: run every CIF on the machine through read -> write -> read
and diff, which is a stronger check than the two vendored fixtures can give.
And note what a re-derivation still cannot recover — a SHARED site whose other
species were merged away at import (round 45e's ordering flaw): the solid
solution exports Nb 0.5 twice rather than Nb/Ti/Ni/Co, because Ti, Ni and Co
are not in the drawn structure to begin with. The unedited path writes all
four correctly, since it writes the stored asymmetric unit verbatim.

~~3. Editing a PACKED crystal desynchronises the boundary copies.~~
**FLAGGED, not fixed, in round 50**: the edit now says so once per object and
points at "Asymmetric unit only". The real fix is unchanged and still wanted —
edits should operate on the CONTENT and re-pack. `edits.adjust_bond_lengths`
is also still cell-unaware and can push an atom across a face.

~~4. Write a `.blend`, not a script.~~ **DELIVERED round 50**, verified by
running Blender 5.1 headless and rendering the saved file with no script
involved. Blender is at `C:\Program Files\Blender Foundation\Blender 5.1\`
on the PC (5.1 and 4.4 both installed) and under `Blender 4.4` on the laptop;
`blender_export.find_blender` discovers it, and the export dialog stores the
choice.

5. **The polyhedra could be MERGED per object in the Blender export.** They
   are one mesh per centre today, which is right for selecting them
   individually and wrong for a framework with 500 nodes. A "merge into one
   mesh" tick is a few lines and would matter on a big packing. Not urgent —
   measure a real ZIF export first, since 500 small meshes may be perfectly
   fine.
   **Christian asked about this on 2026-08-10** and his instinct is right —
   "Blender users would hate not having fine control after export because the
   export doesn't preserve distinct elements." **Nothing is merged today and
   nothing should be.** Every atom and every half-bond is its own Blender
   OBJECT sharing one mesh datablock as a linked duplicate, with the material
   on the object slot (`new_object`), so each atom is selectable, movable and
   recolourable and one material change repaints every atom of that element at
   once. Merging would trade exactly that away — and it is also what future
   KEYFRAME animation needs, since a per-atom trajectory is per-object
   keyframes. If the merge tick is ever built it must stay a tick, default off,
   and be scoped to the POLYHEDRA (which are decoration, not chemistry) rather
   than to the atoms.

~~6. **The `.blend` export cannot render on the spot.**~~ **NOT WANTED —
   closed 2026-08-12.** Christian: "We do not need blender render on the spot
   btw. Opening blender and pressing F12 from a blend file is convenient
   enough. The whole point is that you can set your scene more easily and
   immediately start working on shaders and lighting for the final touches."
   So the export's job is to hand over a scene that is ready to WORK ON, not to
   produce a finished picture — which is also why nothing is merged (see item 5)
   and why the .blend opens complete with no script to run.

7. **KEYFRAME ANIMATION in the Blender export — scoped 2026-08-10, not
   built.** Christian's constraint is settled and it costs nothing: the export
   already gives every atom its own object, so the animation is per-object
   keyframes on `location`, which is the shape Blender users expect and leaves
   materials, selection and per-atom edits exactly as they are after export.
   The plan: walk `animation.frame_times` (the existing export plan, so the
   .blend and a PNG sequence describe the same motion), and for each time
   write `ob.location` + `keyframe_insert("location", frame=k)` per atom, with
   the BONDS keyframed on `matrix_world` because a bond is a scaled and
   rotated cylinder rather than a translated sphere. Two decisions to make
   first: (a) whether to bake every frame or only the source frames and let
   Blender interpolate — source frames plus LINEAR interpolation is smaller
   and matches MoloM's own player, but Blender's default Bezier easing would
   NOT match, so the interpolation mode has to be set explicitly; and (b) what
   to do when connectivity changes between frames, which for a baked vibration
   it now never does (round 57's `FIXED_BONDS`) but for an MD trajectory it
   does — the honest options are to keyframe bond VISIBILITY or to refuse and
   say so. Scene frame range and fps come from the clock.

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
   - ~~**the P1-fallback gap**~~ **DELIVERED round 40**
     (`core/spacegroups.py`): a CIF naming its group without listing the
     operators is expanded, via **spglib's Hall database** rather than
     pymatgen — settings are the whole problem and pymatgen exposes standard
     settings only (it is kept as a backstop tier). spglib is a hard
     dependency; pymatgen still is not. Verified on Christian's 37-file set:
     35/35 files with their own loop reproduce it exactly from their symbol.
     ~~Still open from the original scoping: `.cif` EXPORT with a space group
     re-derived by spglib.~~ **DELIVERED round 50** (`core/cif_write.py`) —
     an unedited file round-trips its own operators and setting verbatim, an
     edited one has the group re-derived from the coordinates. Occupancy
     survives the first case and not the second; see NEXT UP.
   - ~~**BOND TYPING is the missing hierarchy**~~ **DELIVERED round 38**, all
     three parts (kinds, valence sanity, occupancy). The scoping is kept
     below because the reasoning is what matters, and because the two files
     it was measured on are still the regression cases. Christian's argument: MOF-5 is infinite through its bonds, benzoic
     acid is fine on distance alone, HpPyBz breaks because its geometry is
     not physical — so distance + connectivity CANNOT be a robust rule, and
     "there has to be code in Mercury that is chemistry, not just maths".
     Mercury knows to stop after the carboxylate because a Zn-O bond is
     COORDINATIVE and that is the logical place to cut. Measured on his own
     `MIL_53_Al - Kopie.cif` (176 atoms): as read it is ONE 152-atom periodic
     component; cutting every metal-ligand bond gives 32 FINITE components —
     8 x 16 (the BDC linkers), 8 x 3 (waters), 8 x 2 (the OH bridges), 8 x 1
     (the Al centres). Exactly his hypothesis, and it makes whole-molecule
     boundary completion terminate on a framework.
     So the design is a bond KIND, not a bond list: covalent / coordinative
     (metal-donor) / ionic, assigned at perception, with "molecule" meaning a
     component over COVALENT bonds only. Two more pieces are needed and
     neither is optional:
       * **valence sanity** — reject bonds that give an impossible
         coordination number (H > 1 is already capped, round 35b; C > 4,
         O > 3, halide > 1), longest first. This is what HpPyBz needs, and it
         is NOT the metal rule: that file's fusion comes from a 0.75 A
         contact, which no bond-typing scheme would catch.
       * **occupancy**, because the same failure arrives from disorder:
         `MIL-53-lp-new.cif` (also his) has 640 valence violations — carbons
         with 5, 6 and 9 neighbours — purely because our reader ignores
         `_atom_site_occupancy` and superimposes every disorder alternative.
         Two of the three CIFs on this machine hit that, so it is not an edge
         case.
     Worth knowing for the implementation: the CSD ships CURATED connectivity
     with its entries, so Mercury frequently is not perceiving bonds at all —
     it is reading them, with types included. We never have that luxury, which
     is why our perception has to carry the chemistry itself.
   - ~~**displayed bonds are still non-periodic**~~ **DELIVERED round 44**
     (`core/bondgraph.py` + `cif.display_bonds`): the bonds of a drawn crystal
     are instantiated from a labelled periodic graph built once on the cell
     content, so they no longer depend on the display window and a face atom's
     copies each carry a full coordination sphere. Verified as 34 of 36 files
     reproducing their complete-environment coordination, and every framework
     metal 4-coordinate. Still open from this: the graph is rebuilt per call
     rather than CACHED on (cell, ops, filtered sites, bond rules), so a
     packing change still re-derives it — correct, but the spec's invalidation
     table wants it keyed and kept.
   - packing as an ARRAY MODIFIER rather than the current destructive rebuild.
   - ~~SYMMETRY AS A MODIFIER~~ DELIVERED round 29 (`SymmetryModifier`): the
     base stays the asymmetric unit while the viewport and exporter see the
     full cell. Packing is still a destructive rebuild (above).
   - ~~**PARTIAL OCCUPANCIES**~~ **DELIVERED round 38**
     (`cif.resolve_disorder`, Settings > CIF disorder). Occupancy and the
     disorder GROUP/ASSEMBLY columns are read and applied, with three
     policies and a report of what was dropped. Still open on this:
     **occupancy is carried into export only on the LOSSLESS path**
     (round 50: a re-derived cell writes 1.0 and says so), and the policy is
     applied at IMPORT so
     switching it re-reads the file rather than re-resolving in place.
     Christian's wish for a large disordered test set also stands — the two
     MIL-53 files on this machine are the only real fixtures so far.
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
     added the loop limits (see the round-30 entry); **round 77 put frames
     and images back together** and made a strip's LENGTH the one number
     that describes its playback, which is also where interpolation now
     comes from.
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
1g. ~~**RANK MODES BY A VIEWPORT SELECTION**~~ **DELIVERED round 63**
   (`vibrations.selection_weight` / `rank_by_selection` / `SORT_SELECTION`, a
   third entry in the ∿ page's Sort by). It is a PARTICIPATION RATIO exactly as
   scoped, and mass-weighting shipped ON by default with a tick to turn it off:
   measured on the vendored H3PO4 job, phosphorus's best share goes from 0.176
   unweighted to 0.431 weighted, which is the difference between "hydrogens win
   everything" and a usable ranking. The chemistry checks out as a test rather
   than an assertion of faith — selecting the three H ranks the O-H stretches
   (3822-3831 cm-1, 94%) first, selecting the P ranks the P=O stretch
   (1346 cm-1) first. The share is drawn ON the mode card, because sorting by a
   number you cannot see is a list you have to trust blindly. Original scoping
   kept below.
   (Christian's long-term idea, 2026-08-03, NOT built): "allow the user to make a selection in the
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

1e. ~~**LIGAND TEMPLATE ATTACHMENT — SHIPPED BUT NOT WORKING PROPERLY.**~~
   **LARGELY CLOSED 2026-08-12.** Christian retested and the geometry half is
   fine: "templating seems to work when I put monodentate imidazol on the
   hydrogens of the cubane. putting oxalate on methane to form
   1,3-Dioxolan-2,4-dione also works. Even putting it on a meta atom work."
   What was actually broken was the META-ATOM OPTIMISATION downstream of it
   (round 62), not the fit. Also added in round 62: a monodentate ligand may
   now be coordinated onto SEVERAL placeholders at once, one copy each — his
   suggestion, and the geminal rule still holds for anything polydentate,
   where two centres would mean a bridging ligand.
   Original report kept below.
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
6b. **THE RESIDUAL THIRD-PERSON JITTER — diagnosed 2026-08-13, deliberately
   NOT fixed in 0.4.0.** Christian, after round 72: "it works as intended now
   except for the jitter in 3rd person mode specifically, but that is a
   cosmetic issue we can shelve for now". The mechanism is frame PACING, not
   the camera model: **`_FLY_TICK_MS = 16` is 62.5 Hz against a 60 Hz
   display**, so the two beat at ~2.5 Hz and every ~0.4 s a presented frame
   contains two integration steps or none. `dt` is wall-clock, so the physics
   is correct and the SIMULATION is smooth; what is uneven is the sampling of
   it, and the eye judges what is presented. Windows makes it worse - the
   default system timer granularity is ~15.6 ms, so a 16 ms QTimer does not
   fire at 16 ms.
   **Why third person specifically, which is the part that identifies it.** In
   the cockpit the camera is rigidly ON the cockpit atom, so ship and camera
   share any sampling error EXACTLY and nothing looks wrong relative to
   anything else. In the chase view the camera position is a lagging filter of
   the ship's, so uneven sampling appears as relative motion between the two -
   which is exactly what a sporadic wobble of the ship against the frame looks
   like. That also means it cannot be tuned away in `follow`/`spring_lag`:
   round 72 measured the per-tick screen step at 0.016 deg mean, and the
   problem is WHEN those steps are shown, not how big they are.
   **The fix is to integrate on the PAINT**: each presented frame advances by
   the time since the last presented frame, so displayed motion is a function
   of displayed time. Contained, because `_fly_tick(dt=)` stays the entry point
   and the ~50 tests that drive it directly are unaffected - the timer becomes
   a frame REQUESTER (`update()` only) and `paintGL` calls the tick with its
   own dt. Two things to be careful of: an exception inside `paintGL` is
   swallowed by Qt (see the gotchas), so the tick needs a guard there or a
   physics bug becomes an invisible one; and `_end_fly` must not run from
   inside a paint. The cheap partial, if the restructure is not wanted, is
   `_FLY_TICK_MS = 8` - it halves the beat amplitude and touches nothing, at
   the cost of doubling the per-tick rebuild that round 71 worked to reduce.
7. ~~**MOPAC as an add-on**~~ **DELIVERED round 73** - built as the second
   shape the scoping proposed (the add-on owns everything), plus the piece
   it left open: a registry in `core/forcefield.py` so the methods appear in
   the ONE Optimize panel instead of a parallel one nobody finds. See
   `molom/addons/mopac_optimize.py`. Original scoping kept below.
   (scoped 2026-08-10 — Christian: "the
   dependency is apparently tiny. Could probably run it in molom itself. But
   idk how well we can integrate that as an addon that doesn't mess with
   anything else in the software"). Semiempirical geometry optimisation and
   single-point energies sitting next to the existing MMFF94/UFF tier in
   `core/forcefield.py`, for the case a force field has no parameters for at
   all (an exotic metal centre, a transition state) and DFT is overkill for a
   quick check. MOPAC ships as a small, self-contained binary with no Python
   bindings of its own — the interface is a written input file and a parsed
   output file, the same shape `core/io.py`'s OpenBabel subprocess and
   ORCA Workbench's `orca_parser.py` already use, so nothing here is a new
   pattern.
   **The real question is exactly the one Christian asked, and it is an
   ADD-ON question, not a MOPAC question**: round 46 built add-ons on the
   principle of full access and no sandbox ("if someone wants to brick their
   install with something they made themselves, that's on them" — see
   `molom/addons/`), which is right for a page that reads and writes the
   live window. A geometry OPTIMISER is a different shape of risk: it wants to
   hand off `(symbols, coords, bonds, fixed)`, run a real subprocess, and hand
   back new coordinates — i.e. call the SAME SURFACE `forcefield.optimize`
   already exposes, not reach into the viewport or the scene graph itself.
   Two things worth deciding before writing code: (1) whether MOPAC should
   register as another **tier inside `core/forcefield.py`** (same function,
   same `fixed`-atom contract, same degrade-gracefully-if-the-binary-is-
   missing pattern rdkit/openbabel already follow) with the add-on only
   supplying the binary discovery and the Optimize panel a method choice — or
   whether it is cleaner kept OUTSIDE core entirely, as a bundled add-on that
   calls a small `run_mopac(symbols, coords, bonds, fixed) -> coords` helper
   of its own, so a MOPAC failure can never touch the tiers `core/` already
   guarantees offline-testable. The second shape is probably the safer answer
   to "doesn't mess with anything else" — it keeps MOPAC's subprocess and
   binary-discovery code entirely inside `molom/addons/`, same as the debug
   and sandbox pages round 46 already cordoned off, and `core/forcefield.py`
   never has to know it exists. (2) binary discovery: MOPAC has no wheel, so
   this needs the same settings-plus-PATH-plus-known-locations resolution
   `blender_export.find_blender` already does (round 50), not a hard
   dependency — round 40's rule (spglib is hard because degrading silently
   loses a quarter of a structure) does not apply here, since "MOPAC not
   found" is a visible, harmless degrade back to the existing force-field
   tiers.
10. ~~**THIRD-PERSON PILOT MODE**~~ **DELIVERED round 66.** `F3 > Shuttle mode:
   pilot from behind (third person)`, sharing every line of the flight model
   with the cockpit - the only differences are where the camera sits and that
   its pivot LAGS. Both design questions from the scoping were answered as
   scoped: the follow is exponential smoothing (`flight.follow`, framerate
   independent, pinned by a test that runs it at 30 and 120 fps and gets the
   same answer), and there is no collision at all. `clamp_slip` was the one
   addition the scoping missed - lag is a feel, but losing the ship off the
   edge of the screen during a long burn is a bug, so the gap is capped at 3
   radii. Nothing is clipped in third person either: the cockpit hides atoms
   near the camera, and here that would hide the ship. Original scoping below.
   (Christian, 2026-08-12: "3rd person mode for
   piloting mols. trying to do it FPS only leads to problems.") Not built.
   Shuttle mode (round 34, rebuilt on `core/flight.py` in round 35) snaps the
   camera INTO the molecule's origin and flies it first-person — which is the
   problem: you are inside the thing you are steering, so you cannot see its
   orientation, and a molecule is not a cockpit with a windscreen. A chase
   camera fixes exactly that: keep the same `FlightModel` driving the MOLECULE
   and put the camera behind and above it, following with a lag.
   The pieces exist. `flight.FlightModel` already produces a world-space
   velocity and `AimReticle` a turn rate, so the molecule's motion needs no new
   maths; what is new is the CAMERA's own follow. Two decisions worth making
   before writing it: (a) the follow should lag with a spring or a simple
   exponential smoothing rather than being rigidly attached — a rigid chase
   camera makes the world swing around the molecule and is as disorienting as
   the first-person view, whereas a lagging one is what reads as "following";
   and (b) the camera must not collide with the rest of the scene, which for a
   molecule viewer probably means ignoring collision entirely rather than
   implementing it. Note `Camera` is a TURNTABLE with no roll (round 3), so a
   banking chase view has the round-35 problem again: roll has to be an
   explicit parameter applied last, exactly as `fly_look` does it, or it
   accumulates.
8. ~~**PERIODIC LAUNCH-TIME TESTS**~~ **DELIVERED round 65.**
   `tools/startup_profile.py` prints the breakdown (and `--imports` the slowest
   modules); `tests/test_round65_startup.py` guards it. The tests assert
   STRUCTURE and never wall-clock, because a millisecond threshold on two
   machines with very different CPUs either passes everywhere or fails as
   noise: core must not pull in rdkit/openbabel/pymatgen, opening a window must
   not import the network stack, and expensive widgets must not be built before
   something asks for them. **Measured 3269 ms -> 2877 ms.** The two wins were
   the RESOLVER (urllib/http/email, ~130 ms, for a lookup most launches never
   make) and the PERIODIC TABLE, now built on first use. The useful finding is
   the one that stops the next person chasing ghosts: `MainWindow()` is ~940 ms
   cold and **~43 ms warm**, so nearly all of it is Qt's one-off font and style
   caching rather than MoloM's widgets - the periodic table's apparent 638 ms
   was mostly that cold cost, which whichever widget is built first pays. What
   is left is `OpenGL.GL` (~500 ms) and the GL context, both unavoidable before
   a first frame. Original scoping kept below.
   (Christian, 2026-08-11: "Add periodic launch
   time tests. The startup is getting slow.") Not built. The observation is
   almost certainly right and nothing in the suite would notice: 1310 tests
   build `MainWindow()` over and over and none of them times it, so startup can
   regress by half a second per round and only ever be felt, never reported.
   What to measure, in the order it is worth measuring: **import time** (`python
   -X importtime -c "import molom.ui.app"` — rdkit and openbabel are the usual
   suspects and both are supposed to be lazy, so if either is imported at module
   scope that is the whole answer), then **`MainWindow()` construction**, then
   **first paint**. Those are three different problems and a single "startup"
   number cannot tell them apart.
   Two design notes so this does not become a flaky test. (a) A wall-clock
   assertion in pytest is a machine-speed assertion, and this project runs on
   two machines with very different CPUs — so the useful form is a RATIO or a
   recorded baseline, not `assert t < 2.0`. The honest cheap version is a
   `tools/` script that prints a breakdown and a test that asserts only the
   things that are machine-independent: that `molom.core.*` imports pull in
   neither rdkit nor openbabel nor pymatgen, and that constructing a window
   opens no file dialogs and reads no CIF. (b) The add-on scan (round 46) walks
   `~/.molom/addons/` and parses metadata with `ast` at startup — cheap by
   design, but it is disk I/O in the launch path and worth being in the
   breakdown. Suspects to check first, all added since 0.2.0: the spglib import,
   the add-on scan, `QSurfaceFormat` setup, and the periodic-table widget
   (round 17 builds 118 painted cells).
9. ~~**ffmpeg WITHOUT SHIPPING IT**~~ **DELIVERED round 61** — the extra is
   `molom[video]`, discovery is hint -> PATH -> known locations -> the bundled
   wheel, the dialog names which one it found before the render and grows a
   "Locate ffmpeg..." button only when there is none, and GIF rates are snapped
   to what the format can store. The one thing deliberately NOT done is having
   MoloM `pip install` anything on the user's behalf: a program writing to its
   own environment is a bigger promise than it looks, and it stayed Christian's
   call. Original scoping kept below.
   (Christian, 2026-08-11: "Maybe we can make
   calling ffmpeg very intuitive to a user without shipping MoloM with it's own
   ffmpeg dependency?"). Round 54's animation export already resolves ffmpeg the
   right way — `animation.ffmpeg_executable()` tries a system `ffmpeg` on PATH
   FIRST, then `imageio_ffmpeg`'s static binary, then reports honestly — and PNG
   sequences need no ffmpeg at all. **The thing that is actually wrong is the
   dependency list**: `imageio-ffmpeg` sits in `[project] dependencies`, so
   every `pip install molom` drags a ~25 MB static binary in whether or not the
   user ever exports a video. It belongs in `[project.optional-dependencies]`
   next to rdkit and openbabel, which is exactly the tier this project already
   uses for "works without it, better with it".
   What "intuitive" then has to mean, since the failure moves from install time
   to use time: the export dialog should say which ffmpeg it found (or that it
   found none) BEFORE the render starts, not after — round 54's rule that a
   failed encode still leaves the frames is the safety net, not the UX. Give it
   the `blender_export.find_blender` treatment (round 50): a stored path hint in
   Settings, then PATH, then the usual install locations, with a "Browse..." and
   a one-line "PNG sequence works without ffmpeg" note so the dialog never reads
   as a dead end. Worth deciding at the same time whether the video tier should
   offer to `pip install imageio-ffmpeg` on the spot — convenient, and also a
   program writing to its own environment, which is a bigger promise than it
   looks.
