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
offline (`python -m pytest tests/ -q`, 1265 tests, no display needed).
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
1. `python -m pytest tests/ -q` — 1265 offline tests. `tests/conftest.py`
   sandboxes QSettings, so a GUI test can drive a real control without
   writing into your own MoloM configuration.
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

6. **The `.blend` export cannot render on the spot.** It saves and stops,
   which is the right default, but "and render it now" is one more
   `subprocess` call (`blender -b out.blend -o //render_ -f 1`) and would
   close the loop for someone making a figure. Wanted only if Christian asks:
   he specifically said the point is that F12 works.

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
