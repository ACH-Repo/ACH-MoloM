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
offline (`python -m pytest tests/ -q`, 66 tests, no display needed).
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
- `core/ops.py` — operator registry for F3 (labels, categories, shortcuts,
  `enabled(ctx)` predicates; `search` ranks enabled-first). Log:
  docs/OPERATORS.md — KEEP IN SYNC.
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

## Hard-won gotchas (don't re-learn these)
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
- The infinite grid is drawn AFTER opaque geometry, blended, depth-test ON
  but depth-write OFF: molecules occlude it, it overlays below-floor atoms,
  and the fade never punches holes in the depth buffer. QSurfaceFormat
  needs GL 3.3 for `fwidth` AA in the grid shader (already required).
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
  key the edit mode wants must NOT also be a QAction shortcut — check the
  menus before adding one.
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
- **Edit-mode key policy**: G and R stay transforms, EVERY other letter feeds
  the element buffer (so Fe/Na/Cu/Zn type directly). Elements starting with
  G or R need Enter-first. X/Y/Z are free outside a modal in edit mode (they
  type Xe/Yb/Zn); in OBJECT mode they cycle the anchored-tumble axis lock.
- Bond-order perception is greedy-by-length **plus an augmenting-path repair**
  — plain greedy is maximal but not maximum, so a six-ring could stall at two
  double bonds instead of three. The repair is what makes benzene Kekule.
- The instanced mat4 attribute occupies locations 2–5 (one vec4 per column,
  divisor 1); numpy math-convention matrices must be per-instance
  **transposed** before upload (`np.transpose(mats, (0,2,1))`).
- Trajectory frame switches re-perceive bonds but KEEP user-assigned orders
  (`keep_orders=True`); `Ctrl+P` re-perceives from scratch.
- `elements.atomic_number` is tolerant ("C1"/"cl2" → 6/17) — same convention
  as OWB `transform._sym`. "D" (deuterium) is NOT in the table.
- **Wheel events = trackpad orbit** (laptop-first per Christian): plain
  scroll rotates, Ctrl zooms, Shift pans; MMB/RMB drag are the mouse
  fallback (orbit/pan). LMB drag deliberately does NOT rotate. Scroll signs
  are marked in `wheelEvent` for easy flipping if the feel is inverted on
  some hardware. A "PC mouse preset" overhaul is expected later.
- Grid lines drawing across atoms below z=0 is CORRECT (depth-tested floor,
  same as Blender); don't "fix" it.
- Selection is now a list of `(obj_id, atom_index)` tuples everywhere; bond
  edit ops require both picks in the SAME object.

## Environment
- Dev machine: Windows, Python 3.10 (`python`), deps: numpy, PySide6,
  PyOpenGL (+ rdkit, openbabel-wheel installed and optional at runtime —
  graceful degradation mirrors OWB's tiering).
- NOT a cluster tool. No SLURM/ssh anywhere. The LiDO gateway has no
  PySide6/GPU — MoloM is for local machines; the gateway keeps molden.
- Not a git repo yet (as of 2026-07-30). `git init` + first commit is a
  sensible next step if the maintainer wants history.

## Verification workflow
1. `python -m pytest tests/ -q` — 66 offline tests.
2. `python -m molom --selftest` — headless core sanity.
3. GUI smoke: a scripted QTimer run that opens examples, switches styles,
   selects atoms, drives the trajectory bar, and grabs framebuffers lives in
   the session scratchpad pattern (`smoke_gui.py`) — recreate as needed; the
   `grabFramebuffer()` PNGs are how rendering was verified without manual
   clicking (ethanol B&S, selection halos, stick, VdW, wireframe, ethene
   double bond, trajectory frame 3).

## The meta-atom plan (Christian's question, 2026-07-31)
Goal: guide pre-optimisation of metal-organic complexes without needing force
field parameters for the metal. Design agreed:
- a centre carries a `CoordinationSpec` (geometry + donor distance + locked);
- `ideal_donor_positions` turns that into explicit target points;
- the optimiser restrains donors to those targets (harmonic), freezes the
  metal's own FF terms, and lets the organic ligands relax under MMFF/UFF.
Shipped so far: the geometry half (`core/coordination.py`, tested). Still
open: storing a spec on an atom (Structure metadata, must survive savepoints
and undo), the UI to assign one, and the restrained optimiser itself.

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
1. PC/mouse control preset ("will need potential overhaul for PC later" —
   the laptop two-finger scheme is explicitly interim); scroll-sign
   feel-check on real trackpad hardware.
2. Editing polish: element palette / periodic-table dialog, undo/redo (OWB
   snapshot-undo patterns), H-fill, force-field cleanup (RDKit MMFF / OB UFF
   on selection), R rotate modal to pair with G (bond-axis rotation of a
   selection is the chemically meaningful one).
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
