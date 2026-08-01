# MoloM operator log

The human-readable log of every operator in the F3 search palette
(`core/ops.py` registry, populated in `ui/app.py::_register_operators`).
**Keep this file in sync when adding operators.** "Condition" is the
`enabled` predicate the palette uses to grey out entries.

## Modes (Blender's Tab)
**Object mode** arranges whole molecules. **Edit mode** edits the chemistry of
ONE molecule — an orange border, a header (`EDIT | name | draw: C`) and the
status bar show it. In edit mode picking is scoped to that molecule, plain
clicks belong to the draw tool, and adding atoms is only possible here.

| Key | Object mode | Edit mode |
|---|---|---|
| Tab | enter edit mode on the active molecule — **on an empty scene it creates a new molecule** so you can draw from scratch | back to object mode |
| **E** | — | **arm / disarm the draw tool** (the toolbar's ✎ follows). Everything below marked *(draw)* needs it armed; with it off, edit-mode clicks only select, so nothing grows by accident |
| click an atom | select it | *(draw)* **convert it to the draw element** (+ hydrogens re-dressed) |
| click empty space | clear selection | *(draw)* **add an atom** of the draw element there |
| type an element + Enter | — | **overwrite the selected atoms' element** (and set the draw element). Works whether or not the draw tool is armed. `E` is the tool key, so Er/Eu/Es go through *Change element...* |
| hover a bond, press 0-4 | — | set that bond's order directly (0 removes; 4 = quadruple, for metal-metal bonds). The hovered bond highlights with **one stick per order** — no text — and **hydrogens are re-dressed automatically**, so the molecule stays force-field ready |

**Edit mode owns every unmodified letter.** `G` and `R` remain transforms and
`E` toggles the draw tool; everything else types into the element buffer, so
Ar/Ag/Au/Dy work instead of firing align or duplicate. Ctrl/Alt combos still
reach the menus. Alignment (`A`) is therefore an object-mode operation — Tab
out, align, Tab back.
| **drag from an atom** | box select | *(draw)* **grow a new bonded atom**, with two pieces of guidance: hovering an existing atom **rings it in green and snaps** (so it is obvious the release will close a ring), and otherwise the length **soft-snaps toward the single-bond distance** — squeeze in past it and the **bond order rises to 2 then 3**, using the same length ratios as import perception. — pure Avogadro: it follows the cursor in the view plane and is CONFIRMED on release, with hydrogens re-dressed. In an axis-aligned view the view plane IS that plane, so drawing in a Z-view places atoms in XY. **Drop it onto another atom and the ring closes**: the temporary atom is discarded and the two are bonded instead |
| **drag from empty space** | box select | box select |
| Ctrl/Shift+click | extend selection | extend selection (no drawing) |
| letters | hotkeys | **type an element symbol**, Enter confirms — it becomes the new draw element and converts any selected atoms |
| 1 / 2 / 3 / 0 | bond order for 2 selected atoms | same |
| G / R | move / rotate | move / rotate (unchanged) |
| X / Y / Z | lock the anchored tumble axis | (free — they type Xe, Yb, Zn…) |

Because G and R stay transforms in edit mode, elements starting with G or R
(Ga, Ge, Ru, Re…) are typed by pressing **Enter first**, then the letters,
then Enter again. Everything else (Fe, Na, Cu, Zn, Cl…) types directly.

## File
| Operator | Shortcut | Condition |
|---|---|---|
| Open structure file **or project**... | Ctrl+O | — |
| **Save project (savepoint `.molom`)** — every molecule with its name, visibility, style, object origin/frame, bond orders and trajectory frames, plus the camera and view settings | Ctrl+S | scene not empty |
| **Save project as...** | Ctrl+Shift+P | scene not empty |
| Import molecule by name... (OPSIN → PubChem) | Ctrl+Shift+N | — |
| New from SMILES... (dots split into separate molecules) | Ctrl+N | — |
| Paste XYZ / SMILES | Ctrl+V | — |

**SMILES imports are normalised, file imports are not.** Any SMILES route
(paste, Ctrl+N, import-by-name, .smi files) generates coordinates from
scratch, so each molecule is auto-aligned largest-planar-part-to-XY, centred,
and — when one paste carries several molecules, e.g. ChemDraw's
dot-separated copy `CCO.c1ccccc1.OC(=O)c1ccccc1` — spread along +Z with 2 Å
of bounding-sphere clearance so nothing overlaps. One undo entry per batch.
Measured//computed **file** imports (xyz, sdf, pdb, …) are never silently
transformed.
| **Export geometry...** — every molecule ticked visible in the outliner goes into the file (merged into one record); a single visible trajectory still writes all its frames | **Ctrl+E** | scene not empty |
| **Export image...** — PNG/JPG snapshot of the viewport exactly as drawn (grid, labels and all) at its current resolution | **Ctrl+Shift+E** | scene not empty |
| **New empty molecule** — an empty object to draw into (Tab on an empty scene does this too) | — | — |
| Clear scene | — | scene not empty |

## Select
| Operator | Shortcut | Condition |
|---|---|---|
| Select all — **in edit mode this is scoped to the molecule being edited**; Space does the same after an edit | Ctrl+A / Space (edit mode) | scene not empty |
| Clear selection / cancel mode | Esc | selection not empty |
| Select whole molecule of selection ("select linked") | Ctrl+L, or double-click an atom — **Shift/Ctrl + double-click ADDS a molecule** instead of replacing, for gathering several to merge or move together | selection not empty |
| Box select | **just left-drag** (also double-click-drag; Shift extends) | scene not empty |
| Lasso select (arm tool — then left-drag traces a lasso) | Shift+Space, L | scene not empty |
| Box select (re-arm after a lasso) | Shift+Space, B | scene not empty |

Left-drag box select is the default and needs no arming — the earlier
double-click-only trigger never fired reliably on a trackpad. In edit mode a
drag that *starts on an atom* draws instead (see the mode table above).

## Edit
| Operator | Shortcut | Condition |
|---|---|---|
| Undo / Redo | Ctrl+Z / Ctrl+Y | history exists |
| Move selection (grab) | G → X/Y/Z world axis, **same key again = object-local axis, third press = off**; Shift+X/Y/Z plane (same cycling); Shift = precision (Settings factor); digits = exact Å; LMB/Enter commit, RMB/Esc cancel. Locked axes/planes draw as dashed guide lines through the pivot | selection not empty |
| Rotate selection | R → same axis/local/precision scheme; no lock = view axis; digits = degrees (right-handed about the axis). **Two-finger scroll rotates while the modal is active** (laptop path) as does circling the mouse around the pivot. Pivot = the molecule's OBJECT ORIGIN (an X lock spins about the X-parallel through the origin, never the world X line) | selection not empty |
| **Duplicate selection** — a new outliner object inheriting the parent's style and local frame; a partial copy is re-perceived and hydrogen-filled. Movement starts immediately, and duplicate+move is ONE undo step | **D** | selection not empty |
| **Repeat last action** — repeats the whole last ACTION, not just its transform: after `D, X, 6, confirm` it duplicates again and offsets the new copy by the same 6 Å, so holding Shift+R lays down a row of copies. After a plain G/R it falls back to repeating just that move/rotation | **Shift+R** | a transform happened |
| **Drop to floor** — moves the selected molecules so the selection centroid lands on z = 0 | **End** | selection not empty |
| **Object origin — edit mode only.** The orange dot is always drawn on top of the molecule, so it is clickable from any angle. Click it to **pick the origin up** (the Unreal-style gizmo appears); G moves it and R turns its frame through the full modal (axis locks, object-local repress, typed numbers, precision); click anywhere else to **set it down**. While it is picked up the **transform panel switches to the ORIGIN's own transform**, so it can be typed in as well as dragged. `O` snaps it to the selection centroid and picks it up in one go | O / click the dot | edit mode |
| Origin: snap to selection centroid | — (F3) | active molecule exists |
| Origin: align compass rotation with world — resets the object's local frame to the world axes | — (F3) | active molecule exists |
| Align largest planar part to XY / XZ / YZ plane | — (F3/menu) | active molecule exists |
| Align 2 selected atoms to the X / Y / Z axis (smallest turn; whole molecule rotates rigidly about the pair's midpoint) | — (F3/menu) | exactly 2 atoms of one molecule |
| Flip last axis alignment (180° — for when the molecule ends up the wrong way around) | — (F3/menu) | an axis alignment was made |
| **Align (selection-aware)** — see the table below | **A** | selection not empty |
| Add atom... | **Shift+A** | — |

### A — selection-aware align
Always moves/rotates **whole molecules**, never individual atoms.

| Selection | A does | then |
|---|---|---|
| 1 atom | molecule jumps so that atom sits on the **world origin** | — |
| 2 atoms, **two different molecules** | the **first-picked** molecule slides straight at the second atom, stopping with exactly **3.0 Å** between the picked atoms (the second molecule never moves) | — |
| 2 atoms, one molecule | waits for an axis key | **X / Y / Z** → the pair lands on that axis |
| 3+ atoms, one molecule | waits for an axis key | **X / Y / Z** (Shift optional) → the selection's best-fit plane goes into the plane **perpendicular** to that axis, so **Shift+Z = XY plane** |

Esc cancels a pending wait. Holding Shift while pressing the axis key is
fine — bare modifier presses are ignored while waiting.
| Delete selected atoms — **their terminal hydrogens go too** | Del | selection not empty |
| Change element of selection... | E | selection not empty |
| Cycle bond none→1→2→3→none | B | exactly 2 atoms of one molecule |
| Bond order single / double / triple (0 removes) | 1 / 2 / 3 / 0 | exactly 2 atoms of one molecule |
| Remove bond | Shift+B | exactly 2 atoms of one molecule |
| Adjust hydrogens on selection (fill to typical valence, drop the excess) | — | selection not empty |
| Set draw element... | — | — |
| Re-perceive bonds from geometry | Ctrl+P | active molecule exists |
| Re-assign bond orders (keeps hand-edited connectivity) | — | active molecule exists |

### Force field (the Optimize panel)
`Ctrl+R` opens a dock with **Task / Method / Max steps / Start**. Defaults
follow ORCA Workbench's coordinate pre-optimisation and Avogadro:
**MMFF94**, automatically falling back to **UFF** when MMFF has no
parameters (metals, odd valences), and to OpenBabel UFF if RDKit refuses the
molecule outright. It runs in a worker thread, is one undo step, and never
touches connectivity — only coordinates.

*Task* is either the whole active molecule or **"Optimize selection (freeze
rest)"**, which pins every unselected atom. That is how you relax a fragment
you just drew without disturbing the rest of the structure — and it is the
same mechanism the coordination "meta atom" restraints will use.

### Hydrogen handling when drawing
Avogadro's "adjust hydrogens" only fixes the hydrogen COUNT; geometry
cleanup is left to the force field. MoloM does both, on the new atom **and
the atom you dragged from**: the count is corrected, the bond is set to the
covalent length, and the source atom's remaining terminal hydrogens are
re-placed by a VSEPR relaxation so none of them ends up crowding the new
substituent. Heavy neighbours are never moved — including the atom you just
drew, which stays where you dropped it. Squaring up those heavy–heavy angles
is what the Optimize button is for.

### Bond orders — perceived once, never behind your back
Import formats we read carry no bond orders, so orders are assigned **once at
import** from geometry (bond length relative to the covalent radii, capped by
typical valence — the cap is what makes a benzene ring come out
Kekulé-alternating instead of six doubles). Metals get no multiple bonds:
guessing multiplicity at a metal centre is exactly the fight a user preparing
a complex does not want.

After import, **nothing re-perceives on its own.** Moving an atom out of a
molecule and confirming no longer breaks its bonds — connectivity and orders
change only via the explicit operators above, the bond keys, or edit mode.

## View
| Operator | Shortcut | Condition |
|---|---|---|
| Fit view — frames the **selection** when there is one, otherwise the whole scene | F / Home | scene not empty |
| **Local view** — isolate the selected molecules and frame them; press again to restore what was visible | **/** | scene not empty |
| **Shuttle mode** — UE5-style pilot for a whole molecule: the camera snaps into the molecule's origin and you fly it like a ship. **W/S** forward/back, **A/D** strafe, **Q/E** down/up, **scroll** steers (yaw + pitch), **Ctrl+scroll / pinch** rolls, **Esc** lands and keeps the new position (the camera returns to where it was). Geometry too close to the cockpit is hidden so it cannot clip. F3 only, deliberately no hotkey | — (F3) | active molecule exists |
| Toggle perspective / orthographic | **Shift+O** | — |
| View along +X/−X/+Y/−Y/+Z/−Z | compass ball click, or F3/menu — switches to ortho, next orbit pops back to perspective (Blender auto-persp). Compass hover: letters glow white; negative balls are full-size and show their −X/−Y/−Z labels | — |
| Force field: optimize geometry (panel) | Ctrl+R | — |
| Toggle outliner panel (also its edge tab) | M | — |
| Toggle transform panel — its **own small floating window** that pops out from behind the outliner (also the ◀ T edge tab); location + Euler rotation of the active molecule; fields scrub on drag, click to type, arithmetic like `3+5*1.3` evaluates | N | — |

### Viewport toolbar (Blender's T panel)
A translucent column of buttons floating over the viewport's top-left:
select, draw (E), move (G), rotate (R), origin (O), measure, optimize. The
checkable ones mirror the viewport's live state, so a hotkey lights its
button and clicking a button is the same as the hotkey. Draw and origin are
greyed outside edit mode.

## Modifier
| Operator | Shortcut | Condition |
|---|---|---|
| Modifiers panel (properties dock) | — (F3), or the right edge tab | — |
| Add an array modifier to the active molecule | — (F3 / panel) | active molecule exists |
| Apply the modifier stack (bake into atoms) | — (F3 / panel) | the stack is non-empty |

Modifiers are **non-destructive**, Blender-style: the array's copies are what
the viewport draws and what `Ctrl+E` exports, but picking, editing and the
force field keep working on the one base molecule. That is what lets a
40×40 adsorption surface stay editable as a single unit cell. *Apply* bakes
the result into real atoms and clears the stack. The stack is saved in
`.molom` projects and survives undo.

*Array*: **count** plus an **offset** in Å, or "relative to the molecule's
size" — with relative on, an offset of 1 along X tiles the molecule edge to
edge, so a slab is two numbers.

### Properties dock — the one right-hand panel
A vertical tab strip (Blender's properties editor) with three pages:
**🗂 Outliner**, **🔧 Modifiers**, **⚛ Force field**. `M` opens it on the
outliner, `Ctrl+R` on the force field, the edge tab on whichever was last
shown. Everything is collapsed by default and expands downward, so the panel
stays readable however much is in the scene.

Modifiers appear as a **column of cards**: the header shows the enable
checkbox, the name and a one-line summary (`x3 (8.3, 0, 0) A`), and the
settings stay hidden until you click the ▸.

### Edge tabs
Small translucent arrow strips that pop each dock in and out. Each one sits
on the edge its dock is attached to — the outliner's on the right (a
vertical strip), the transform and optimize ones along the bottom — so the
arrow points the way the panel will come out. No text labels.

### Outliner (VESTA-style tree)
```
water                    [eye] [style]
  └ C  (2)               ■ ■ ■          <- element group
      └ C0               ■ ■ ■          <- individual atom
  └ H  (6)               ■ ■ ■
+ New molecule
```
- Everything below a molecule is **collapsed by default**; atom rows are
  built only when a group is expanded, so a big structure costs nothing
  until you look inside it.
- Element groups **and** individual atoms carry the same three squares —
  the only difference is how many atoms the click applies to:

  | Square | Click | Right-click |
  |---|---|---|
  | **Colour** | pick a colour | reset to the element colour |
  | **Label on/off** | toggle labels (`A` = all on, `–` = some) | — |
  | **Label type** | menu: element / index / element+index / custom, plus custom text (single atom) and label colour | — |

  A `~` on a square means the atoms below it disagree — mixed colours or
  mixed label types.
- The **Labels** dropdown at the top sets the molecule-wide default; a
  per-atom or per-element choice overrides it.
- Array-modifier copies inherit the base atom's colour.


- A row click selects that molecule **and makes it active**, so Tab edits
  what you just clicked. Picking a molecule in the viewport does the same in
  reverse — the outliner follows the viewport.
- **Drag across the eye column** to paint the same visibility onto every row
  you cross (Blender's checkbox drag).
- **Shift+click an eye** toggles between "show only this one" and "show
  everything except this one".
- Rows are **multi-selectable** (Ctrl/Shift). Right-click for select /
  rename / hide / delete, and with several rows highlighted, **Merge**.
- **"+ New molecule"** under the list creates an empty object and drops its
  name straight into rename; Tab then draws into it from scratch.
| Atom labels: element / index | — (View menu checkboxes, F3) | — |
| Toggle floor grid | — | — |
| Toggle background (Blender grey / white) | Ctrl+B | — |
| Display style: Ball and stick / Stick / VdW / Wireframe | — | — |
| Re-perceive bonds (active molecule) | Ctrl+P | active molecule exists |

## App
| Operator | Shortcut | Condition |
|---|---|---|
| Search operation (this palette) | F3 | — |
| Settings... (rotation sensitivity, Shift-precision factor, startup mode) | — | — |
| About MoloM | — | — |

## Navigation (not operators, viewport-level)
- Two-finger scroll / MMB drag = camera TURNTABLE orbit — yaw about world Z
  + pitch only, **no roll ever** (Blender behaviour; keeps the horizon
  level). Ctrl+scroll zoom, Shift+scroll pan, RMB pan.
- **Exactly ONE atom selected AND the cursor over that atom**: the gesture
  instead TUMBLES that molecule rigidly about the selected atom — the camera
  and grid do not move, and a yellow Avogadro-style crosshair flashes on the
  anchor. This is a model edit: one undo entry per gesture. Scrolling in
  empty space always orbits the camera, so the tumble can no longer fire
  from nowhere; once a gesture is running it continues even if the cursor
  drifts off. Any other selection size orbits the camera.
- **X / Y / Z lock the tumble axis** (global → object-local → off, as in
  G/R), drawn as a dashed guide through the anchor. A locked tumble spins
  about that axis only, which is what makes tumbling usable in an
  axis-aligned orthographic view.
- During G/R/origin modals plain scroll never orbits; in R it rotates.
- Compass: hover lights the labels; click any ball for that axis view. The
  grid is procedurally infinite with a distance fade. The whole UI uses a
  dark Fusion palette (menus included).

## Settings
Rotation sensitivity, Shift-drag precision factor, **sphere size** (scales
every atom radius, updates live — only the instance buffers are rebuilt),
**undo history depth (default 30)**, **adjust hydrogens when editing**,
startup maximized/windowed.

## Bond lengths follow the element
Changing an atom's element also fixes the bond it hangs off: turning an H
into a Zn stretches the C–H distance to the C–Zn covalent sum, and shrinking
an element pulls it back in. Only TERMINAL atoms are moved (the changed atom
when it has one neighbour, otherwise its terminal neighbours) — an atom
inside a ring or chain is left alone rather than distorting geometry you did
not ask to change.

## Meta atoms (designed, foundation shipped — not yet an operator)
`core/coordination.py` holds the geometry half of the "meta atom" idea:
named coordination templates (linear, bent, trigonal planar, tetrahedral,
square planar, trigonal bipyramidal, octahedral), a fit of a template onto
the bonds an atom already has, and `CoordinationSpec` (geometry + donor
distance + locked flag) with `ideal_donor_positions` producing restraint
targets. Hydrogen placement already uses it, so it is live code rather than
speculation. What is still missing is the force field that consumes a spec
as restraints — see the roadmap in CLAUDE.md.

## Planned / not yet operators
- Force-field pre-optimisation (MMFF/UFF) consuming CoordinationSpec
  restraints; meta-atom UI (assign a geometry to a selected centre).
- Duplicate molecule, measurement overlays in-viewport, per-PC mouse control
  preset, screenshot export, drag-to-draw bonded atoms (Avogadro style).
