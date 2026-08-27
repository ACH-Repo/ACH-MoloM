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
| **E** | — | **arm / disarm the draw tool** (the toolbar's ✎ follows). A plain hotkey again since element typing was removed. Everything below marked *(draw)* needs it armed; with it off, edit-mode clicks only select, so nothing grows by accident |
| **periodic table** | — | a floating chart appears right of the tool column **in plain edit mode** (draw tool OFF). Cells carry each element's own viewport colour and nudge when pressed; clicking one sets the draw element and converts the selection. It also carries the **✳ Meta atom** button. It hides while the draw tool is armed |
| **after any draw or element change** | — | **the selection is cleared.** The atom you just made is already the element you asked for, so leaving it selected would make the next pick from the periodic table convert it instead of only setting what the NEXT atom will be |
| click an atom | select it | *(draw)* **convert it to the draw element** (+ hydrogens re-dressed) |
| click empty space | clear selection | *(draw)* **add an atom** of the draw element there |
| pick from the periodic table | — | **overwrite the selected atoms' element** (and set the draw element). Elements are only ever PICKED — typing them was removed in round 20: it cost every letter hotkey, could not spell Ge (G starts a grab), and whichever key armed the draw tool collided with the tail of Ge/Fe/Be/He/Ne/Re/Se |
| hover a bond, press 0-4 | — | set that bond's order directly (0 removes; 4 = quadruple, for metal-metal bonds). The hovered bond highlights with **one stick per order** — no text — and **hydrogens are re-dressed automatically**, so the molecule stays force-field ready |
| **drag from an atom** | box select | *(draw)* **grow a new bonded atom**, with two pieces of guidance: hovering an existing atom **rings it in green and snaps** (so it is obvious the release will close a ring), and otherwise the length **soft-snaps toward the single-bond distance** — squeeze in past it and the **bond order rises to 2 then 3**, using the same length ratios as import perception. — pure Avogadro: it follows the cursor in the view plane and is CONFIRMED on release, with hydrogens re-dressed. In an axis-aligned view the view plane IS that plane, so drawing in a Z-view places atoms in XY. **Drop it onto another atom and the ring closes**: the temporary atom is discarded and the two are bonded instead |
| **drag from empty space** | box select | box select |
| Ctrl/Shift+click | extend selection | extend selection (no drawing) |
| letters | hotkeys | hotkeys (the same ones) |
| 1 / 2 / 3 / 0 | bond order for 2 selected atoms | same |
| G / R | move / rotate | move / rotate (unchanged) |
| **T** | twist the selected terminal group about its bond axis | same |
| X / Y / Z | lock the anchored tumble axis | free |

**Letters are ordinary hotkeys in BOTH modes** (round 20). Edit mode used to
swallow every letter for the element buffer, which cost all of them; elements
are picked from the chart now, so `E` (draw tool), `A`, `B`, `D`, `M`, `N`
and the rest behave the same wherever you are. The origin gizmo stays
**Alt+O** rather than `O`, because `Shift+O` is already the projection
toggle.

## File
| Operator | Shortcut | Condition |
|---|---|---|
| Open structure file **or project**... | Ctrl+O | — |
| **Save project (savepoint `.molom`)** — every molecule with its name, visibility, style, object origin/frame, bond orders and trajectory frames, plus the camera and view settings | Ctrl+S | scene not empty |
| **Save project as...** | Ctrl+Shift+P | scene not empty |
| **Find a molecule by name...** — a LIST of candidates with formula, weight and a skeletal preview | **Ctrl+Shift+N** | — |
| **Find a crystal structure...** — COD, OPTIMADE and a folder of your own, searched at once | **Ctrl+Shift+Alt+N** | — |
| Crystal search: set the local CIF folder... | F3 / Settings | — |

**The result table remembers and sorts.** Reopening the dialog puts the last
query and its hits straight back — *without re-running the search*, which
would cost three network round trips to redisplay what was on the screen a
moment ago, and could silently answer differently. If the result is more than
a minute or two old the dialog **says how old**: a stale list that looks live
is worse than an empty one, because a COD entry can be superseded. Enter runs
it again.

**Star a structure to keep it.** The first column is a favourite tick. What
is remembered is the REFERENCE - the provider and its own id - never the file,
so a favourite cannot go stale against COD the way a private copy would, and a
hundred of them cost a few kilobytes rather than a hundred CIFs on disk.
Favourites show on their own when the dialog opens with nothing remembered,
and after a search they sit **below a full-width rule**, drawn the way the F3
palette draws its category headers. One the search itself found stays in the
results with its star ticked rather than being listed twice.

**Clicking a column header sorts by it** — ascending, then descending, then
back to the search ranking, which is the one thing the search itself is for.
Temperature and year sort as NUMBERS (100 K after 98 K, not before it), and a
blank — which COD leaves constantly — sinks to the bottom whichever way the
column points, because an unknown temperature is not 0 K.
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
| **Export image...** — the full still-export dialog: file and numbering, resolution multiplier with the **pixel size shown live**, crop-to-content and its margin, transparency, atom labels, mesh detail, and whether the unit-cell box respects depth | **Ctrl+Shift+E**, File menu, F3 | scene not empty |

**Every option that changes the exported image is in that one dialog.** It
used to be a bare file picker, while the resolution multiplier, the mesh
subdivision and crop-to-content lived in App > Settings and the cell-box
z-order only in F3 — so the export asked one question and silently obeyed four
answers given elsewhere. `F12` then repeats **those** settings, not whatever
Settings happens to hold, and `F3 > Render settings: still` reopens the dialog
on your last choices.
| **Export image...** — PNG/JPG snapshot of the viewport exactly as drawn (grid, labels and all) at its current resolution | **Ctrl+Shift+E** | scene not empty |
| **Export to Blender...** — a **`.blend`** (or the build script alone) with materials, coordination polyhedra, saved cameras, lights and world, after a pre-configuration dialog. See below | **Ctrl+Shift+B** | scene not empty |
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

**Whole-molecule operations are fragment-scoped in edit mode.** One outliner
object routinely holds several disconnected pieces while you build — a metal
centre and a ligand not yet bonded to it. In edit mode `A`, `Home`, `End` and
friends move only the fragment CONNECTED to the selection, so nudging the
atom you just drew does not drag the untouched ligand. Object mode still
moves the whole molecule.

Left-drag box select is the default and needs no arming — the earlier
double-click-only trigger never fired reliably on a trackpad. In edit mode a
drag that *starts on an atom* draws instead (see the mode table above).

## Edit
| Operator | Shortcut | Condition |
|---|---|---|
| Undo / Redo | Ctrl+Z / Ctrl+Y | history exists |
| Move selection (grab) | G → X/Y/Z world axis, **same key again = object-local axis, third press = off**; Shift+X/Y/Z plane (same cycling); Shift = precision (Settings factor); digits = exact Å; LMB/Enter commit, RMB/Esc cancel. Locked axes/planes draw as dashed guide lines through the pivot | selection not empty |
| Rotate selection | R → same axis/local/precision scheme; no lock = view axis; digits = degrees (right-handed about the axis). **Two-finger scroll rotates while the modal is active** (laptop path) as does circling the mouse around the pivot. Pivot = the molecule's OBJECT ORIGIN (an X lock spins about the X-parallel through the origin, never the world X line) | selection not empty |
| **Duplicate selection** — in OBJECT mode a new outliner object inheriting the parent's style and local frame (a partial copy is re-perceived and hydrogen-filled); in EDIT mode the atoms are copied **into the same molecule**, with their internal bonds and any meta-atom specs, because edit mode means "I am working inside this molecule". Movement starts immediately, and duplicate+move is ONE undo step | **D** | selection not empty |
| **Repeat last action** — repeats the whole last ACTION, not just its transform: after `D, X, 6, confirm` it duplicates again and offsets the new copy by the same 6 Å, so holding Shift+R lays down a row of copies. After a plain G/R it falls back to repeating just that move/rotation | **Shift+R** | a transform happened |
| **Drop to floor** — moves the selected molecules so the selection centroid lands on z = 0 | **End** | selection not empty |
| **Hide the selected atoms** — across every molecule the selection touches. The selection is cleared afterwards, so the next G or Delete cannot act on atoms you can no longer see | **H** | selection not empty |
| **Show every hidden atom** in the scene | **Alt+H** | something is hidden |
| **Object origin — edit mode only.** The orange dot is always drawn on top of the molecule, so it is clickable from any angle. Click it to **pick the origin up** (the Unreal-style gizmo appears); G moves it and R turns its frame through the full modal (axis locks, object-local repress, typed numbers, precision); click anywhere else to **set it down**. While it is picked up the **transform panel switches to the ORIGIN's own transform**, so it can be typed in as well as dragged. `Alt+O` snaps it to the selection centroid and picks it up in one go | **Alt+O** / click the dot | edit mode |
| Origin: snap to selection centroid | — (F3) | active molecule exists |
| Origin: align compass rotation with world — resets the object's local frame to the world axes | — (F3) | active molecule exists |
| Align largest planar part to XY / XZ / YZ plane | — (F3/menu) | active molecule exists |
| Align 2 selected atoms to the X / Y / Z axis (smallest turn; whole molecule rotates rigidly about the pair's midpoint) | — (F3/menu) | exactly 2 atoms of one molecule |
| Flip last axis alignment (180° — for when the molecule ends up the wrong way around) | — (F3/menu) | an axis alignment was made |
| **Align (selection-aware)** — see the table below | **A** | selection not empty |
| **Geometry: set bond length** — drag or type an exact value; the whole trailing FRAGMENT follows, so every other length and angle is preserved. LMB/Enter set, RMB/Esc cancel | right-click over the selection, or F3 | exactly 2 atoms of one molecule |
| **Geometry: set angle** — the vertex is the **middle atom in pick order**; the far fragment swings about it | right-click over the selection, or F3 | exactly 3 atoms of one molecule |
| **Geometry: set dihedral** — the two inner atoms in pick order are the axis; the far fragment spins about it | right-click over the selection, or F3 | exactly 4 atoms of one molecule |
| **Twist a terminal group about its bond axis** (the methyl rotor) — the selection says *which group*, not which atoms move: MoloM takes the **smallest fragment containing the whole selection that hangs off the rest by exactly one bond**, so the carbon, one hydrogen, the three hydrogens or the whole CH₃ all give the same rotor. That bond is the axis, drawn dashed with a ring on the fixed end. A **relative** angle — drag, scroll or type degrees; LMB/Enter set, RMB/Esc cancel | **T**, right-click over the selection, or F3 | the selection resolves to a rotor: **both** sides of the cut need ≥2 atoms, so a ring atom, a lone terminal H and a whole molecule are all refused (with a reason) |
| Add atom... | **Shift+A** | — |

### A — selection-aware align
Always moves/rotates **whole molecules**, never individual atoms.

| Selection | A does | then |
|---|---|---|
| 1 atom | molecule jumps so that atom sits on the **world origin** | — |
| 2 atoms, **two different molecules** | the **first-picked** molecule slides straight at the second atom, stopping with exactly **3.0 Å** between the picked atoms (the second molecule never moves) | — |
| 2 atoms, one molecule | waits for an axis key | **X / Y / Z** → the pair lands on that axis |
| 3+ atoms, one molecule | waits for an axis key | **X / Y / Z** (Shift optional) → the selection's best-fit plane goes into the plane **perpendicular** to that axis, so **Shift+Z = XY plane** |

**The axis key is a PREVIEW, not a commit.** It applies the alignment and
leaves the operation live, so you can press X, look at it, press Y instead,
and only then keep it — the same contract G and R have:

| | |
|---|---|
| **X / Y / Z** | apply that alignment and keep waiting. Pressing another axis key replaces it; previews are re-applied from the original pose, so X then Y gives the Y alignment, never Y on top of X |
| **left-click** (or Enter) | keep it — one undo step for the whole operation |
| **right-click** or **Esc** | put it back exactly as it was, leaving no undo entry |

The **1-atom** case has no axis to choose, so it still applies at once.
Holding Shift while pressing the axis key is fine — bare modifier presses are
ignored while waiting, and no other key cancels.
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
| **Shuttle mode (cockpit)** — UE5-style pilot for a whole molecule: the camera snaps into the molecule's origin and you fly it like a ship, on the same 6DoF model as right-mouse flight. **W/S** thrust, **A/D** strafe, **Space/Ctrl** up/down, **Q/E** roll, **scroll** steers (yaw + pitch), **Esc** lands and keeps the new position (the camera returns to where it was). Geometry too close to the cockpit is hidden so it cannot clip. F3 only, deliberately no hotkey | — (F3) | active molecule exists |
| **Shuttle mode (third person)** — the same flight, from a chase camera behind and above the ship. See below | — (F3) | active molecule exists |
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

ferrocene                [eye] [style]        <- a CRYSTAL gets a site tier
  └ C  (100)             ■ ■ ■
      └ C(11)   (20)     ■ ■ ■          <- crystallographic site
          └ C1           ■ ■ ■          <- individual atom
      └ C(12)   (20)     ■ ■ ■
  └ Fe (10)              ■ ■ ■          <- ONE site, so no tier
```
- Everything below a molecule is **collapsed by default**; rows are built
  only when a group is expanded **and thrown away again when it is
  collapsed**, so a big structure costs nothing until you look inside it and
  stops costing when you look away. (Before round 86 they were built once and
  never freed, and `refresh_row_controls` walks every live control on every
  colour, label or visibility change — so one look inside a 300-atom group
  went on costing ~190 ms per click for the rest of the session, on rows
  nobody could see.)
- **A crystal gets a third tier: the crystallographic SITE.** An element is
  not a type — a cell draws one asymmetric-unit site over and over, and
  *that* is what the refinement calls a type, what the file labels, and what
  somebody means by "the bridging oxygens" as against "the terminal ones".
  Christian: *"let's say I want to hide all oxygen atoms of a specific type.
  I can't do that efficiently."* Now it is one click on the site row.
  - The row is named by the file's own `_atom_site_label` (`C(11)`, `O3`).
  - It appears **only where there is more than one site** to choose between.
    One site is not a grouping, it is the same list one click deeper, and a
    molecule has no sites at all — both fall through to the flat tree.
  - Atoms added by an edit are images of no site and are grouped separately
    as **(added since)** rather than being filed under a site they have
    nothing to do with.
  - It is also what makes a big crystal quick to open: ferrocene's hundred
    carbons are five rows, not a hundred.
- Element groups, sites **and** individual atoms carry the same five squares —
  the only difference is how many atoms the click applies to:

  | Square | Click | Right-click |
  |---|---|---|
  | **Colour** | pick a colour | reset to the element colour |
  | **H / S** | hide these atoms (`H` = shown, `S` = hidden, `h` = mixed) | — |
  | **R** | sphere size for these atoms — opens a slider under the square | — |
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
- **Selecting atom, site or element rows selects those atoms in the
  viewport**, Ctrl/Shift ranges included. A row stands for the atoms below
  it, so selecting the `O3` site selects every drawn image of that site and
  selecting the `O` group selects every oxygen. Before round 86 the outliner
  emitted one atom on a click and nothing at all for a range, so the tree
  could show six rows highlighted while the viewport showed one atom — two
  selections disagreeing, with the one you were looking at being the wrong
  one.
- **Drag across the eye column** to paint the same visibility onto every row
  you cross (Blender's checkbox drag).
- **Shift+click an eye** toggles between "show only this one" and "show
  everything except this one".
- **Ticking an eye back ON also un-hides every atom of that molecule.** `H`
  only hides, so cycling the tick is the one obvious way back — otherwise
  the only route out is hunting for whichever element group's square happens
  to read `S`.
- **A molecule with hidden atoms has a bright red row.** Hidden atoms are
  invisible by definition, so without the mark a molecule missing its
  hydrogens looks exactly like one that never had any: you cannot tell a
  display choice from a broken import.
- Hiding is not just cosmetic — a hidden molecule's atoms are **not drawn,
  not pickable, and their bonds go with them**, and an animated molecule you
  have hidden stops costing anything per frame (its bonds are re-perceived
  when it comes back, not while nobody can see it).
- Rows are **multi-selectable** (Ctrl/Shift). Right-click for select /
  rename / hide / delete, and with several rows highlighted, **Merge**.
- **"+ New molecule"** under the list creates an empty object and drops its
  name straight into rename; Tab then draws into it from scratch.
| Atom labels: element / index | — (View menu checkboxes, F3) | — |
| Toggle floor grid | — | — |
| Toggle background (Blender grey / white) | Ctrl+B | — |
| Display style: Ball and stick / Stick / VdW / Wireframe | — | — |
| Re-perceive bonds (active molecule) | Ctrl+P | active molecule exists |
| **Unit cell: report cell parameters and space group** | — (F3) | active molecule has a cell |

## Modifiers
| Modifier | Does |
|---|---|
| **Array** | `count` copies on a constant offset — one unit cell becomes a slab |
| **Symmetry (CIF)** | applies the crystal's space-group operations, optionally packed `na x nb x nc` |

The symmetry modifier is the non-destructive alternative to the ❖ page's
asym/cell/packing switch: that switch REBUILDS the atom list, so the
asymmetric unit you were editing is gone until you switch back. As a modifier
the base molecule stays the asymmetric unit — the thing you actually edit —
while the viewport and the exporter see the full cell. Bonds are not carried
across the copies (connectivity is a perception job, and would be wrong at
the cell faces anyway).

**Adding it puts the molecule into that state.** A `.cif` import already
shows the full cell, so appending the modifier to it would re-apply the
operations, de-duplicate straight back to the same atoms, and change nothing
on screen. Adding therefore reduces the base to the asymmetric unit the file
listed (kept in metadata since import, so this is a restore rather than a
guess) and lets the modifier regenerate the cell. Once it is on the stack the
❖ page's asym / full cell / packing switch drives the **modifier** instead of
rebuilding atoms underneath it — "asymmetric unit" simply turns the modifier
off. **It works on a plain molecule too**, which is the most instructive way to
use it: take a fragment, add one operation at a time — a 2-fold, a glide, a
centring — and watch an asymmetric unit turn into a cell. A box is invented
around the molecule, with its origin offset so the molecule sits at a
*general* position; put it on the cell origin instead and every operation
through that origin maps the molecule onto itself, so nothing appears to
happen. The card carries a preset list of the standard elements (inversion
centre, 2/3/4/6-fold axes, 2₁ screws, mirrors, a/b/c/n glides, A/B/C/I
centrings) and a free-text field taking any operation in the CIF's own xyz
notation.

## Crystallography (CIF)
`.cif` / `.mmcif` go through MoloM's **own** reader before OpenBabel, because
OpenBabel parses the file but hands back a bag of Cartesian atoms with the
cell and space group discarded. The native reader keeps:

- the **cell** (a, b, c, α, β, γ) and its fractional→Cartesian matrix,
- the **space group** name as written,
- every **symmetry operation** ("-x+1/2, y, -z"),
- the **asymmetric unit** in fractional coordinates.

All of it rides in `Structure.metadata`, so it survives undo snapshots and
`.molom` savepoints without any extra plumbing. On import the operators are
applied to fill the cell; copies landing on an existing atom (minimum-image,
0.1 Å) are dropped, so atoms on special positions do not stack up. A file
with no symmetry listed is treated as P1.

The **unit cell box** carries a/b/c from the origin corner in the axis
colours (red/green/blue), the same convention as the compass. Toggle it from
F3 ("Show unit cell box").

**Where it sits in the picture is a separate choice, made twice.**

| Operator | Draws the box as | Default |
|---|---|---|
| **Unit cell box (Viewport): draw on top / respect depth** | painted overlay — 12 near-plane clipped edges, always visible | **on top** |
| **Unit cell box (Image export): draw on top / respect depth** | real geometry — one thin rod per edge, occluded by whatever is in front of it | **respect depth** |

The two default differently on purpose. On screen the box is partly a
navigation aid: you want to know where the cell is even when it runs behind
the framework, and an edge vanishing into a dense structure is a real loss.
An **export has to be true** — an overlay has no depth, so every edge it
crosses is drawn as though it were in front, which on a packed cell means the
a, b and c vectors cut visibly across every molecule they pass behind.
Christian, 2026-08-25: *"the unit cell axes are always rendered on top ... I
think it shouldn't be. At least never in png exports."*

The depth-respecting form is a rod per edge (`core/cellbox.py`), which is what
VESTA and Diamond draw and what the Blender export has always produced — so
the screen, the still and the `.blend` cannot disagree about which edge is the
a axis. The radius is **proportional to the cell** (0.4% of its mean edge), so
it reads the same on a 3 Å cell and a 200 Å framework.

### The orientation ribbon (round 35)
Selecting a crystal — in the outliner, or any part of it **in the viewport** —
pops a VESTA-style strip in along the top of the viewport. It hides again the
moment a non-crystal is in focus, so an ordinary molecule never loses the
space. Every button is a camera move; the maths is in `core/orient.py`.

| Group | Buttons | What it does |
|---|---|---|
| axis views | **a b c a\* b\* c\*** | view along a direct or reciprocal cell axis — the axis points **at you**. Click the same button again to view from the other side. Switches to ortho, next orbit pops back |
| standard | **◈** | the standard orientation of the crystal shape — the classical clinographic oblique projection (c vertical, turned arctan⅓ ≈ 18.4° and tipped arctan⅙ ≈ 9.5°) |
| rotate | **↺ ↻ ⤴ ⤵** + `Step (°)` | turntable rotation by that many degrees per click |
| pan | **⬅ ➡ ⬆ ⬇** + `Step (px)` | pan by that many pixels per click |
| zoom | **+ − ⤢** + `Step (%)` | zoom by that percentage per click, plus fit |

**The direct and reciprocal axes are different directions** in anything less
symmetric than an orthorhombic cell — in the monoclinic β = 115° case a and a\*
are 25° apart — which is exactly why VESTA offers both, and why `axis_vector`
takes the reciprocal ones from the **inverse transpose** of the cell matrix. A
plane normal is covariant; transporting it with the direct matrix is the same
error as the round-26 mirror-plane bug, which came out 62° wrong.

There is deliberately **no in-plane rotation button**: the camera is a
turntable and a level horizon is an invariant the rest of the app depends on.
Roll lives in flight mode, where it is explicit and zeroes on landing.

**Which way round are the axes?** Two conventions have to be stated because
programs genuinely differ and there is no universal answer:

* **the chosen axis points INTO the screen** and the cell origin sits
  top-left, as it does in Mercury;
* **the other two are cyclic**: for axis *k*, the next axis goes RIGHT and the
  one after it goes DOWN. So the **b** view has **c** across the top and
  **a** running down the left edge.

**Orbiting out of an axis view re-levels the viewport.** The up vector here is
a cell axis, which the world-Z-up turntable has no way to express, so the
first orbit restores the ordinary alignment before turning — the same contract
`auto_ortho` has with perspective.

Crystallographic axes themselves are conventionally **right-handed**
(a × b · c > 0) and the origin sits at a cell corner; nothing is "flipped".
What differs between viewers is purely presentational — which corner lands
top-left, and whether +c is drawn up or down the page. That is why the axis
buttons here alternate sides on a repeat click instead of asserting that one
of them is correct.

### Bonded atoms outside the cell (round 35)
VESTA's *boundary search*, on the crystal's outliner row (**Ext**) and on the
❖ page. It draws the atoms just beyond each face that are **bonded** to atoms
inside, so a chain or a framework runs on instead of ending flat at the wall —
which is what Christian's side-by-side against VESTA showed MoloM doing.

This is a different operation from round 32's boundary completion: that
repeats sites lying exactly ON a face onto their equivalent faces, and a bond
crossing a face has nothing on the face to repeat. **Off by default**, so no
existing structure changes on import. The cell CONTENT is untouched — anything
counting Z keeps using `expand(boundary=False)`, and the exterior atoms are
never part of it.

**Molecules are kept whole.** Wrapping each atom into the cell on its own
strands hydrogens on the far face; each bonded fragment is instead walked
using the nearest periodic image and then shifted by its centroid, so the
cell shows complete molecules the way CCDC/Mercury do.

**The drawn cell completes its boundary.** Expanding the asymmetric unit into
[0, 1) gives the cell's *contents*, which is not the same thing as its
*picture*: an atom at the origin belongs to all eight corners, one on a face
to both faces, one on an edge to all four. So rock salt draws as **14 Na**
(8 corners + 6 face centres) around **13 Cl** (12 edge midpoints + the body
centre) — the diagram every textbook shows — rather than a single sodium in
one corner. The content is unchanged: these are the same atoms seen from the
neighbouring cells, and Z is still Z.

A boundary copy brings its **whole molecule**, not just the atom. Urea's
carbon and oxygen sit exactly on the x face, so copying them alone put a bare
C=O in the cell with its two NH2 groups left on the other side. This follows
the two reference viewers: VESTA draws atoms outside the boundary that are
bonded to atoms inside it, and Mercury packs whole molecules, including one
when *any* of its atoms fits.

A **periodic** component is the exception — a framework, or an ionic lattice
like rock salt where Na and Cl fall inside the covalent criterion. It is
infinite and cannot be completed, so only the atom travels. Telling the two
apart needs more than a walk through the cell: NaCl has two atoms and no loop
to find, so it also asks whether the component bonds to its own lattice image
(Na is 2.48 Å from the chlorine next door; urea's molecule is 2.7 Å clear of
its own image and only H-bonded).

A molecule whose centroid sits exactly ON a face (urea's does, by symmetry)
is placed inside the box, not outside it. That decision used to come down to
whether floating point produced 1.0 or 0.99999.

**The box follows its molecule live.** Its placement is a Kabsch fit against
reference atoms recorded at import, recomputed while painting — so it tracks
a grab or a rotation *during* the drag, not on commit.

| Operator | Where |
|---|---|
| Crystal: asymmetric unit / full unit cell / packing (supercell) | **Properties ▸ ❖ Crystal page**, View ▸ Crystal, or F3 |
| Show unit cell box | the ❖ page's checkbox, View ▸ Crystal, or F3 |
| Unit cell: cell parameters and space group | shown on the ❖ page; also F3 |
| Show refused bonds (visualisation override) | the ❖ page's checkbox |
| Crystal: edit the asymmetric unit (cell follows the symmetry) | F3 |
| Crystal: re-derive the space group from the coordinates | F3 (also automatic on every edit to a full cell) |
| Make the selected substituent coplanar with its ring | F3 |

**Editing a crystal, and what happens to its symmetry.** Which of two things
happens depends on whether a **symmetry modifier** is on the stack:

* **with one** — the base molecule is the *asymmetric unit*, so an edit is
  repeated by every operator and the **space group is kept**. `F3 ▸ Crystal:
  edit the asymmetric unit` puts an ordinary `.cif` import into this state by
  reducing the base first (to the file's own asymmetric unit, or to one atom
  per symmetry orbit);
* **without one** — the base is the whole cell, so an edit genuinely breaks
  the symmetry. The operators are then **re-derived from the coordinates**
  and the ❖ page says what happened; a structure with nothing left becomes
  **P1**. An untouched cell is never re-derived, so the file's own setting is
  not quietly respelled.

**Each crystal carries its own switches in the outliner**: a `.cif` object
gets one extra child row with **Cell** (unit cell box), **Poly**
(coordination polyhedra), **Asym** / **Full** (contents) and **⋯**
(Advanced). Labels are deliberately short — the row shares its width with the
tree — and each one carries a full explanation as a tooltip. Ordinary molecules get nothing there, because
they have no cell to talk about. Everything applies immediately — there is no
Apply button. **Advanced…** opens the ❖ page on that crystal, and the ❖ tab
is greyed out whenever the active molecule has no cell.

The **❖ Crystal page** in the properties dock is the discoverable home for
all of this: radio buttons for asymmetric unit / full cell / packing, the
supercell counts, the cell-box checkbox, and the cell parameters read out in
full. Menus and F3 still work, but a property OF the molecule belongs beside
the molecule's other properties.

Every mode is regenerated from the stored asymmetric unit, so switching back
and forth cannot drift.

Known gaps: a CIF that names only a space group and gives **no symmetry
loop** falls back to P1, which shows just the asymmetric unit (pymatgen is
the planned fix); the bond perception that runs after unwrapping is not
periodic, so a *framework* still shows cut at the cell faces; packing is a
destructive rebuild rather than a modifier; CIF export is not implemented.

### Sort by: Viewport selection (round 63)
A third ordering next to Frequency and IR intensity: **select atoms in the
viewport and the modes that move THOSE atoms rank first.** The number it sorts
on is drawn on each card as a percentage, because sorting by a figure you
cannot see is a list you have to trust blindly.

It is a **participation ratio** — the selected atoms' share of the mode's
motion, over the whole — not a raw displacement sum. A raw sum ranks every
loud mode above a mode that is genuinely localised on your selection, which is
the opposite of the question you asked.

**Mass-weighting is on by default**, and the tick appears only with this
ordering. An eigenvector is a Cartesian displacement, so a C–H stretch is
nearly all hydrogen motion by amplitude; unweighted, every mode involving a
hydrogen scores highly and selecting a heavy atom returns almost nothing.
Weighting by mass measures the share of the kinetic energy instead. Measured on
the vendored H3PO4 job: phosphorus's best share is 0.176 unweighted, 0.431
weighted. Selecting the three hydrogens puts the O–H stretches (3822–3831 cm⁻¹,
94%) on top; selecting the phosphorus puts the P=O stretch (1346 cm⁻¹) on top.

With nothing selected it falls back to Frequency — there is no question to
answer yet, and an arbitrary order would be worse than the spectrum.

## Vibrational modes (∿ page)
**Just open the ORCA FREQ output** — the modes are read off it as the file
is imported. (F3 "load ORCA frequencies" still attaches a job to a molecule
that is already open, and the page carries the same button.) Unlike ❖, the
**∿** tab is always clickable: with no frequency data the page says so rather
than greying itself out, because a dead tab cannot tell you what is missing.

Each mode is one row showing its wavenumber — imaginary modes in orange,
translations/rotations hidden unless you ask for them — with an **A** button
that animates it.

Above the list sit the settings that turn a mode into frames, and they
belong to the whole imported FREQ object rather than to one mode:

| Setting | Means |
|---|---|
| **Amplitude** | peak displacement of the busiest atom, in Angstrom. Slider 0.05–1.00 (default **0.2**); the box beside it takes typed values and may go higher, which simply pegs the slider |
| **Frames / period** | how finely one oscillation is sampled |
| **Sort by** | **Frequency** (the spectrum, ascending) or **IR intensity** (strongest first — which bands you would actually see). The intensity in km/mol is shown on each row |
| **Range** | a cm-1 window, filtering the list live as you type. Either end may be left empty for no bound |

Amplitude is scaled that way because ORCA's eigenvectors are normalised but
not to any physical size, so without it a stiff mode is invisible and a
floppy one explodes.

IR intensities come from the output's `IR SPECTRUM` table, which only lists
the vibrations — the translations and rotations have no intensity and sort to
the bottom. A job with no such block (a plain Hessian, or Raman only) still
works; there is simply nothing to sort by.

**Frames per period steps in fours, and that is not cosmetic.** A mode is
sampled as `sin(2*pi*k/n)`, whose turning points fall at k = n/4 and k = 3n/4.
Unless four divides n those are not whole frames and the sampling never
reaches the extremes of the oscillation — at n = 6 the animation peaks at
0.87 of the amplitude you asked for, so the highest and lowest points of the
chemical coordinate, which are the reason to look at the mode at all, are
quietly cut off. Any count you type is snapped to the nearest multiple of
four. It is the number of frames GENERATED - the data. How long the mode then
plays for is the strip's own **Frames**, on the Animation strip page, and the
two defaults are equal (60) so that out of the box every frame drawn is a real
sample of the sine rather than a chord between two.

Animating bakes one period of the mode into ordinary trajectory frames, so it
arrives on the scene clock like any other track: it interpolates, it appears
in the multi-track pane, and it plays alongside other trajectories. The track
is set to loop, because a vibration is one.

**Baking does not move the molecule.** The undisplaced geometry is read from
frame 0 of whatever is there, which is the rest geometry wherever you have
since dragged the molecule to — not from a capture taken when the file was
read.

**A baked mode's bonds are FIXED** (`bonding.FIXED_BONDS`). The player
re-perceives connectivity when a trajectory steps to a new frame, which is
right for an MD run — bonds really do break there — and wrong for a
vibration, which is one molecule at successive phases of an oscillation.
Asking the chemistry filters about a squeezed phase can only lose bonds:
measured on the vendored H3PO4 job, at the DEFAULT 0.2 Å amplitude the
1346 cm⁻¹ mode takes P=O to 1.127 Å against an `IMPOSSIBLE_FACTOR` floor of
1.13 Å and the bond vanishes; at 0.4 Å the O–H stretches reach 0.56 Å. So the
bonds are perceived once, at rest, and left alone. **Ctrl+P** still
re-perceives on request.

## Trajectory playback (the scene clock)
There is **one playhead for the whole scene**, not one per molecule, so every
trajectory loaded plays at the same time. The bar under the viewport is that
playhead: play/pause (**Space**), the frame range, the framerate, a position
readout, and a **▾** toggle that opens the track rows.

### Three global numbers, and one per strip
The bar carries **Frame Start**, **Frame End** and **Framerate**, and nothing
else. A *scene frame* is one picture; the clock ticks one per tick at the
framerate; a strip's own **Frames** says how many scene frames it occupies.

| | |
|---|---|
| a **source frame** | a coordinate set that came out of an input file, or one generated sample of a normal mode. How many there are is a property of the data. |
| a **scene frame** | one picture the player draws, and one position of the playhead. |
| **Duration** (per strip) | how long that strip takes to play, in SECONDS. Its length, therefore its speed, therefore how finely its source data is subdivided — one number, on the Animation strip page. The frame count follows from it and the framerate. |
| **Framerate** | scene frames per second. Global, because it is a property of the playback rather than of any one molecule. |

A strip therefore occupies `Duration x Framerate` frames, and it interpolates
exactly when that is more than its data has. There is no global smoothing
knob: lengthening one strip makes that molecule play longer and more smoothly
and leaves every other strip alone, which is what the old global one could not
do.

**Is smoothing gone for good?** As a COUNT, yes — how many pictures there are
now follows from the duration and the framerate, so a third number could only
disagree with them. What a count could never say is whether those pictures
*blend* or *step*, and that is a real choice about a trajectory: blending
invents intermediate geometries, stepping shows only the ones that were
computed. That survives as the per-strip **Interpolate between frames** tick,
on by default.

**Playback keeps real time.** The clock advances by elapsed wall time, not one
frame per timer tick, so a scene that cannot be drawn at the framerate drops
frames instead of playing slowly — `n_frames / Framerate` seconds is what a
loop takes, and it matches what a render of the same range will produce.

**Cyclic and linear data are sampled differently, and only there.** A baked
normal mode is one closed period — the last stored sample is *not* a repeat of
the first — so its `n` samples divide the strip into `n` equal arcs and the
strip's last frame sits one arc short of home, which is what makes the loop
seamless. An imported trajectory has two distinct ends, so `Frames - 1` scene
intervals divide `n - 1` source intervals and the strip's last frame lands
exactly on the last datum. The strip page says which it is.

### The frame range
**Frame [start] - [end]** bound the interval the playhead runs over, so you
can loop the interesting twenty frames of a five-hundred-frame run. The range
is **inclusive**: Frame End is the last frame played, and the frame after it
is Frame Start again. They are also draggable in the track pane — the two
green handles, which sit on the boundary *after* the frame they name — and
everything outside them is veiled.

**It does not follow the content.** The range is fitted once, the first time
there is anything to play, and is then yours: arranging strips never moves it.
The **⤢** button beside the boxes fits it to every strip again, which is how a
trajectory imported later is brought into the loop.
Having it track the content meant dragging a strip to the right dragged Frame
End along with it, which re-scaled the pane mid-gesture, and a strip nudged to
a fractional start made the loop period fractional too — which is how a loop
ends up one frame long or short. **Strip starts snap to whole frames** for the
same reason.

Dragging the playhead past a limit parks it there rather than wrapping: a wrap
under the cursor is unreadable while scrubbing. Playback itself still wraps,
per the end mode.

**The track pane** (▾, or drag the grip above it to resize) shows one row per
animated molecule on a shared time axis with a single playhead across all of
them:

There is **no separate transport slider**: the playhead itself is the
scrubber. Drag it from the ruler strip along the top of the pane, or grab its
line anywhere down the rows.

| In the rows | Does |
|---|---|
| drag the playhead / ruler | scrub the scene clock |
| drag a green handle | move that end of the **looping interval** |
| drag a bar sideways | slide that strip's **start**, snapped to whole frames |
| click a bar | select it (orange), and show it on the strip page |
| **G** | grab the selected strip: it follows the pointer, click or Enter drops it, **Esc** puts it back |
| **X** / **Del** | take the selected strip off the player (the frames stay) |
| click anywhere that is not a strip | deselect |
| click the dot in the gutter | enable / disable that strip |
| double-click a bar | cycle its end mode: hold → loop → pingpong |
| click empty track space | seek the playhead there |

| Moving the view | Does |
|---|---|
| **wheel / swipe up-down** | zoom time, keeping the frame under the cursor still |
| **swipe left-right** | pan time |
| **Shift+wheel** | pan time |
| **Ctrl+wheel** | scroll the rows |
| **Home**, the **Fit** button | frame every strip and the whole play range |
| **View [start] - [end]** | show exactly that interval |

A scroll is read by whichever axis DOMINATES, and the action is **latched for
the whole gesture**: a trackpad swipe is never purely one axis, so a rule that
checked the horizontal delta first handed most vertical flicks to the pan
branch, and a swipe that drifted diagonally flipped between panning and zooming
under the hand. Holding a modifier starts a new gesture, since that is a
deliberate change of intent rather than a wobble. A wheel notch and 60 px of
trackpad are the same quantity, so the two devices zoom by the same amount for
the same movement.

The pane's keys work when it has focus **or the pointer is over it**, which is
how Blender routes a hotkey and is what keeps G from grabbing the molecule
instead of the strip.

**The View bounds are not the play range.** One says what the pane shows, the
other what plays — and the pane needs its own or a strip dragged far to the
right leaves everything a sliver with no way back. They sit on the transport
row beside the frame range, not in a bar of their own.

Rows are ordered by start time, so a staggered set reads top-to-bottom.

Each object gets a **strip** mapping scene time to its own frames through a
**start offset**, a **duration**, and an end behaviour (**hold** the last
frame, **loop**, or **pingpong**). So two trajectories can be staggered, or
run at different rates, off the same clock — a shorter strip over the same
data plays faster. A molecule with one frame is a still and simply never
moves.

**A strip longer than its data** interpolates between frames instead of
stepping. A plain blend would send every atom along the straight chord
between positions,
which makes a *rotating* molecule contract toward its centroid halfway
through the turn and spring back — bonds visibly losing length. Instead the
rigid part of the motion is extracted (Kabsch) and turned as a real rotation,
and only the leftover deformation is blended. At 3000 atoms this costs
0.25 ms per frame, well under the buffer upload that follows it.

Interpolated coordinates are **display only** — the stored frames are never
written, so scrubbing cannot damage a trajectory, and editing always sees
real frame data. Bond perception runs only when an object's nearest whole
frame changes, never on every interpolated tick.

For a **cyclic** strip the blend also carries across the wrap, from the last
stored sample back into the first. Without that the closing arc of every
revolution is frozen and then leapt in one frame — which is exactly what a
baked mode did before round 77, covering 93.3% of a 20-sample period and
crossing the rest at four times the normal step.

### The Animation strip page
Clicking a strip in the track pane selects it (orange, the same colour and
meaning as the viewport's selection outline) and shows it on its own
properties page:

| Field | Means |
|---|---|
| **Start** | the scene frame the strip begins on. May be negative — the pane has canvas either side of the frame range for exactly that. Dragging the bar changes the same number. |
| **Duration** | how long the strip takes to play, in seconds. The one number that decides its playback: its length, hence its speed, hence how finely its data is subdivided. Raise it until the motion looks fluid. The frame count follows from it and the framerate. |
| **Interpolate between frames** | blend between the source frames, or hold each one until the next is due. All that is left of the old global Smoothing — see above. |
| **At the end** | hold the last frame, loop, or ping-pong — applied in the strip's *own* frames, which is what lets one rule serve a period and a run alike. |
| **Source** | frames in the underlying data, and whether they are one closed period or a run with two distinct ends. |
| **Sampling** | scene frames drawn per source frame — the old global Smoothing, now read off rather than set. |
| **Occupies** | the frames it covers, and how long that is in seconds at the current framerate. |

**Remove from player** takes the strip off the timeline and leaves the frames
alone: this is the animation's track, not the molecule's data. The removal is
remembered, so the next rebuild does not put it straight back.

Setting **Duration** never re-bakes anything either — a mode's sample count is
the vibrations page's *Frames / period*, and a playback length must not
quietly mutate a molecule and push an undo step.

## Finding a crystal structure (Ctrl+Shift+Alt+N)
Type a formula, a mineral name or a chemical name; pick one or more results;
import. **Multi-select is the point** — comparing two polymorphs side by side
is the commonest reason to go looking.

**Why this is a different dialog from Import-by-name.** Resolving a molecule
NAME gives one answer, so that dialog shows a resolution and an Import button.
A crystal name gives many — polymorphs, temperatures, redeterminations, a
dozen determinations of quartz — so this one is a list you choose from.

| Tier | Covers | Notes |
|---|---|---|
| **Local folder** | your own `.cif` files | blank until you set it (F3, or Settings ▸ Local CIF folder). Indexed from the header only, and sub-folders are included. A structure you already have needs no network and sorts first |
| **COD** | experimental determinations | formula *and* a text index, so mineral and chemical names work |
| **OPTIMADE** | Materials Project, OQMD | formula only — the standard describes structures, not literature, so there is no name to match. These are **computed** structures and are marked `(calc)`: a DFT-relaxed cell is not a measurement |

The three run **at the same time**, not as a cascade, and a provider that is
slow, down or speaks a dialect costs that provider and nothing else — the
dialog names what did not answer, because "Materials Project did not answer"
is something you can act on and "1 source failed" is not.

**A chemical NAME is resolved to a FORMULA first**, through the same
OPSIN → PubChem → CACTUS cascade Ctrl+Shift+N uses, and COD is then asked by
formula *and* by text. This is what makes a search for "benzoic acid" find
benzoic acid: COD returns 2617 rows for that text and exactly **one** is named
it — the pure compound's own entries are spelled "benzioc acid" with no
chemname at all, so every hit was a derivative. A formula cannot be mistyped
into invisibility. The summary says what it searched as.

It also makes OPTIMADE reachable from a name query, since the standard
describes structures rather than literature and can only be asked for a
formula. Be aware what is on the other end, though: **Materials Project and
OQMD are computed inorganic databases** — 0 hits for C₇H₆O₂ against 50 for
SiO₂ — so for molecular organics COD is effectively the only free source. The
CSD is where those live, and it is licensed.

**Ranking** is done here rather than by the providers. An exact formula
outranks any name similarity, because a canonical formula is a chemical
identity and not a spelling — `TiO2` and `O2Ti` are one key. Below that,
matching a whole WORD beats matching a prefix, which is what separates
"ferrocene" from "Ferrocenecarboxylic anhydride". Within a formula match the
name breaks ties — C₈H₆O₄ is terephthalic acid *and* five other things — but
only a name that really matches: **an absent name is not evidence against**,
and COD leaves most of its entries unnamed, so a wrongly-named isomer used to
outrank the compound you were actually looking for. The same entry served by two
providers is collapsed (the local copy wins); a redetermination — same formula
and space group, a cell differing in the third decimal — survives as its own
row, because that is exactly what you are choosing between.

Imports go through the ordinary file path, so the packing, the disorder policy
and the symmetry derivation all apply exactly as they do to a file on disk.

## Measure
The 📏 toolbar tool. Click **2** atoms for a distance, **3** for an angle
(vertex on the middle pick), **4** for a dihedral in the atan2 convention.
Clicking a picked atom again unpicks it; **Esc** finishes. Picks are ringed and
chained in the viewport and the value is drawn there too — it lived in the
status bar before, where transient messages covered it and it read as a dead
tool.

It works in BOTH modes and **never touches the selection**, so you can
measure without losing what you were about to edit.

### They PERSIST (round 60)
A finished measurement stays on screen, so a figure can carry several at once.

| Gesture | What happens |
|---|---|
| A fifth click, or a click on empty space | **Keeps** the finished measurement and starts the next one. It used to discard it |
| Turning the tool off, **Esc** | Keeps it too — putting the tool away is not a reason to lose a measurement |
| Hover one | It lights up WHITE, which is the cue that Delete will take it |
| **Delete** while hovering, or after clicking one | Deletes that measurement. With none targeted, Delete still deletes ATOMS as always |
| Click a measurement's label | Selects it, for a Delete without hovering |
| `F3 > Measurements: show or hide them all` | Hides them without deleting them |
| `F3 > Measurements: delete every one` | Bins the lot |

A kept measurement is drawn SOLID and the one being picked DASHED, so "still
picking" and "finished" are distinguishable at a glance.

They live on the VIEWPORT, not in the scene — a measurement is an annotation on
the current view, so it stays out of `Scene.snapshot` (round 31's four-place
checklist) and out of `.molom` savefiles. The consequence is deliberate: a
measurement whose atom has been deleted is dropped rather than re-pointed at
whatever now holds that index (`prune_measurements`, called from
`refresh_geometry` as well as from the painter).

## Coordination polyhedra (MOFs and frameworks)
The **Poly** switch on a crystal's outliner row draws a translucent solid
through the donor atoms around every metal centre, coloured by that metal.
This is how framework structures are shown in practice — balls and sticks
stop being readable after a few nodes.

Centres are metals with at least 3 and at most 12 bonded neighbours (fewer
has no interior; more is a graph artefact rather than a coordination sphere).
The solid is depth-tested but does not write depth, and is drawn double-
sided, so linkers read through it and a large cage is still visible from
inside. It is a per-object setting, so a framework can be shown as polyhedra
next to a molecule shown as sticks.

## Symmetry elements and ghosts (CIF)
Two optional overlays on the ❖ Crystal page, most useful with **Asym**
showing:

Each element KIND can be switched on separately (rotation axes, screw axes,
mirrors, glides, inversion centres, rotoinversions) — a group like Fm-3m has
enough distinct elements that drawing them all at once is unreadable.

**The filter drives both pictures.** Glyphs and ghosts are built from the
same filtered operation list, so switching off "glide" removes the glide
planes *and* the copies the glides produce — what is drawn and which copies
appear can never disagree. Ghosts can also be shown on their own, with the
glyphs off.

- **Symmetry elements** draws the space group in the printed-table language:
  a lens for a 2-fold, triangle for 3, square for 4, hexagon for 6, hollow
  for a **screw** axis, an outlined quad for a **mirror**, dashed for a
  **glide**, and a small open circle for an **inversion centre**.
- **Ghost images** draws every symmetry copy of the asymmetric unit as a
  faint SKELETON — bonds and all, not a scatter of dots, so a copy is
  recognisable as the same fragment moved. For "how does this fill the cell"
  this is usually the faster read.

**Ghosts are wrapped by MOLECULE, not by atom** (round 34). Putting each atom
of an image into [0,1) on its own shreds any copy straddling a cell face:
half of it reappears on the opposite side, and because the ghost's bonds come
from a minimum-image adjacency the two halves stay connected and get drawn
with lines reaching clear across the box. That is the "ghost atoms are
glitched — bonds where there shouldn't be any, facing the wrong way and way
too long" report, and it is the round-19 real-atom bug one level up. Each
image now goes through `cif.unwrap_molecules`, and its bonds are re-tested at
its own coordinates (`cif.direct_pairs`) so a contact that only exists across
a face is not drawn at all — which also covers a PERIODIC component, since
that one cannot be made contiguous by any amount of unwrapping.

**Order does not matter.** Each operation is applied independently to the
asymmetric unit, so the result is its orbit — a set, which has no ordering.
(Composition *is* order-dependent, since space groups are generally
non-abelian, but nothing here composes operations.) Turning a kind off
changes which copies you see, but never by re-ordering anything.

Classification is `core/symmetry.py` and is plain linear algebra on each
operation's 3×3: determinant separates proper rotations from rotoinversions,
the trace gives the order, the invariant eigenvector gives the axis (or the
plane normal), and the translation splits into the intrinsic screw/glide part
and the part that merely locates the element. A 192-operation group collapses
to the handful of distinct elements worth drawing.

## Join (J)
Blender's Join, meaning whichever join makes sense where you are:

| Situation | J does |
|---|---|
| edit mode, exactly 2 atoms selected | bond them (already bonded = no-op; J is join, not cycle) |
| selection spans 2+ molecules | merge them — a small popup **at the cursor** asks *into a new molecule* (originals kept, hidden) or *replace the originals* |

The popup is Blender's pattern: it appears where the pointer already is, so
click it, or walk it with the arrow keys and confirm with Enter. Escape
cancels.

## Ligand templates
> **Status (0.2.0): not working reliably in practice.** The geometry is
> tested and the synthetic case docks correctly, but Christian hit failures
> in real use on 2026-08-03. Treat the description below as the intent.

Two F3 operators, deliberately no tab — this is an advanced move.

1. **Template: Set ligating atom(s)** — select the coordinating atom(s) on a
   ligand. They gain small violet dots, drawn on top so they are findable
   from any angle. Nothing moves and no dialog opens; the marks wait while
   you build the other half.
2. **Template: Coordinate ligand** — select the placeholder atoms on a centre
   (typically the hydrogens a meta atom was dressed with) and run it. The
   ligand is rotated and translated so its donors land where the placeholders
   were, the placeholders are deleted, and bonds are made donor→centre.

The placeholders must be **geminal** — all on one atom. A set spanning two
centres is a bridging ligand, a different operation, and is refused rather
than guessed. They need **not be hydrogen**: any terminal atom works.

Three or more donors are a determined fit (Kabsch). One or two are not, so
the leftover freedom is resolved deliberately: the ligand's bulk is pointed
away from the centre. With a single donor the spin about the new bond is
still free — adjust it with **R**.

## Meta atoms
A coordination centre that **holds its shape** while the force field relaxes
everything around it — for metals MMFF/UFF have no parameters for. Set one
from the **✳ Meta atom…** button on the periodic table (or F3 "Meta atom"),
with the selected atom as the centre.

The window sets three things: the **coordination geometry** (any template in
`core/coordination.py`), the **centre–donor distance r**, and **the element
it becomes on export**. Optionally it moves the bonded donors onto the ideal
directions straight away.

In the app the centre is drawn as the dummy `Xx` **with a violet glow**, and
is **dressed with placeholder hydrogens** on the template's directions when
created — so the geometry it enforces is visible, and you replace a
placeholder with the real donor instead of free-drawing a coordination number
the spec was never meant for. On export it is written as the chosen element; if no
element was chosen it stays a dummy rather than being guessed at.

**During optimisation** a locked centre freezes itself *and its donors*, so
the coordination sphere cannot collapse while the ligands relax. That is a
rigid constraint, not a harmonic restraint — a true restrained minimisation
needs RDKit position constraints and is the next refinement.

## App
| Operator | Shortcut | Condition |
|---|---|---|
| Search operations (this palette) | F3 | — |
| Settings... (pointing device, rotation sensitivity, Shift-precision factor, startup mode) | — | — |
| About MoloM — also the navigation cheat-sheet | — | — |
| Quit MoloM | Ctrl+Q | — |

## Navigation (not operators, viewport-level)
**The scroll wheel means different things on different devices** — set
*Pointing device* in Settings, or leave it on Auto:

| Gesture | Trackpad | Mouse |
|---|---|---|
| plain scroll / wheel | orbit | **zoom** (one notch = one step) |
| Ctrl + scroll | zoom | zoom |
| Shift + scroll | pan | pan |
| MMB drag | orbit | orbit |
| Shift / Ctrl + MMB drag | pan / zoom | pan / zoom |
| Alt + LMB drag | orbit | orbit (for mice with a stiff wheel-click) |
| **RMB hold** (past ~250 ms, or drag) | **fly** (see below) | **fly** |
| **RMB double-click** | **fly, latched** — hands free until a single right click or Esc lands you | same |
| **RMB click over the selection** | context menu, at once | context menu, at once |
| LMB drag | box select | box select |

**Auto** decides per event: a precision trackpad reports pixel deltas, a
notched wheel only reports 1/8-degree steps. Only the *plain* gesture differs
between the two schemes, so the modifiers carry across machines. Orbiting
with a wheel was the laptop-only default; on a desktop one notch is a ~11°
jump, which reads as a broken viewport (`core/input_map.py`).

- Orbit is a camera TURNTABLE — yaw about world Z + pitch only, **no roll
  ever** (Blender behaviour; keeps the horizon level).
- **Exactly ONE atom selected AND the cursor over that atom**: the orbit
  gesture instead TUMBLES that molecule rigidly about the selected atom (with
  a mouse that means MMB / Alt+LMB drag, since the wheel zooms) — the camera
  and grid do not move, and a yellow Avogadro-style crosshair flashes on the
  anchor. This is a model edit: one undo entry per gesture. Scrolling in
  empty space always orbits the camera, so the tumble can no longer fire
  from nowhere; once a gesture is running it continues even if the cursor
  drifts off. Any other selection size orbits the camera.
- **X / Y / Z lock the tumble axis** (global → object-local → off, as in
  G/R), drawn as a dashed guide through the anchor. A locked tumble spins
  about that axis only, which is what makes tumbling usable in an
  axis-aligned orthographic view.
- During G/R/origin modals plain scroll never orbits; in R a trackpad scroll
  rotates (with a mouse, circle the pointer around the pivot instead).
- Compass: hover lights the labels; click any ball for that axis view. The
  grid is procedurally infinite with a distance fade. The whole UI uses a
  dark Fusion palette (menus included).

### Flying — 6DoF arcade controls, round 35
Everspace-style handling. **Hold RMB** to fly for a moment, or **double-click
RMB to LATCH** it — then both hands are free and a **single right click or
Esc** lands you.

**A right press ARMS flight; it does not start it** (round 36). Taking off
captures the pointer — hides it and parks it at the viewport centre — so
starting on the press made the release land in the middle of the screen with
nothing under it, and the right-click menu became unreachable. Held past
**Hold to fly** (Settings > Flight, default 250 ms) *or* dragged past the
click slop, the press becomes flight; released before either, it is an
ordinary right CLICK. Set the delay to **0** to switch hold-to-fly off
entirely and reach flight only by double-clicking.

| Input | Effect |
|---|---|
| move the mouse | move the AIM RETICLE. It stays where you put it, and the ship keeps turning toward it until you bring it back to the middle — a virtual stick, not a delta. Pitch stops just short of vertical |
| **W / S** | thrust forward / back |
| **A / D** | strafe left / right |
| **Space / Ctrl** | rise / descend |
| **Q / E** | **roll** left / right |
| **Shift** | boost (3x) |
| **Alt** | creep (0.25x) |
| scroll | set the cruising speed |
| release the keys | **auto-brake** — drag jumps to 1.8x, so you stop where you meant to |
| turning | the ship **banks into the turn** automatically, holds the bank while the reticle is out, and levels when it comes home |

Changes from round 34: Q/E gave up vertical thrust to **roll** and Space/Ctrl
took it over; **creep moved from Ctrl to Alt**, because a key that both moves
you and quarters your speed is unusable.

It is a real little physics model (`core/flight.py`), not a step per
keypress: thrust accelerates a world-space velocity, drag is exponential (so
it is stable at any frame time), and speed is capped. Velocity is kept in
WORLD space deliberately — turning does not re-aim the momentum you already
have, so you keep drifting the way you were going while you look elsewhere,
which is what makes it feel like flying rather than like a camera. Speeds
scale with the scene size, so a 3 Å cell and a 300 Å framework fly the same.

**Strafe primacy**: lateral and vertical acceleration match forward exactly,
so sidestepping is a primary way to move rather than a nudge. The per-axis
factors are applied to the ACCELERATION, not to the key vector — `thrust_world`
normalises, so a weighting folded into the components would be divided
straight back out.

**Inertial dampening**: the drag coefficient is `damping` while a key is held
and `damping * brake_factor` the moment they all come up. One symmetric
coefficient cannot be both low enough to build speed against and high enough
to park.

**The reticle is a virtual stick.** The hull mark sits dead centre (where the
nose points); the second mark is where you have pointed, drawn inside a faint
ring showing its travel limit. Its offset is a sustained turn RATE, so the
ship keeps coming round for as long as the mark is out there — it does not
decay, and the turn does not stop just because you stopped moving the mouse.
Bringing it back to the middle is what stops the turn.

**The pointer is captured, not wrapped.** While flying it is hidden and held
at the viewport centre, with each delta taken against that anchor. You can
sweep as far as you like in any direction; there is no edge to hit, so nothing
is interrupted by running into the properties dock or the top of the window.

**Turning does not move you.** The camera is an orbit rig, so rotating it
alone would swing the eye around the pivot — looking up would lift you. The
eye is pinned during a turn and only thrust translates it.

**Roll is scoped to flight and levels on landing.** `Camera.fly_look` takes it
as an explicit absolute parameter applied last, never fed back into the
azimuth/elevation pair — so it cannot accumulate, and passing 0.0 (what every
non-flight caller does) gives bit-for-bit the round-34 camera. It has to level
on exit because the orbit camera is a turntable with no way to represent a
rolled pose.

All of it is tunable live in **App > Settings > Flight** (acceleration, drag,
auto-brake, strafe response, roll rate, turn rate, aim expo and the
hold-to-fly delay), including while flying.

**Shuttle / pilot mode uses the identical model**, with the molecule as the
airframe instead of the camera — so there is one place to tune the feel and
the two cannot drift apart. The round-8 version moved a fixed step on every
key PRESS, which delivered Qt's auto-repeat rhythm and read as choppy.

**Key conflicts:** none. Every flight key is read only while `_fly` is live,
and `_keyboard_captured()` then makes the viewport `grabKeyboard()` and
intercept `ShortcutOverride`, so W/A/S/D/Q/E/Space never reach the object- or
edit-mode QActions that also claim those letters. A test pins this.

**RMB no longer pans.** Pan is on Shift+MMB and Shift+scroll, on both
devices. Hanging pan off a modified right-drag was rejected because every
modifier that could carry it already means something *inside* flight.

### Right-click menu (over the selection)
A right-CLICK — pressed and released inside the hold delay, with the cursor
**on a selected atom** — opens a small at-the-cursor menu
(`ui/choice_popup.py`, the same widget J uses) instead of flying. It lists
only what applies: the geometry edit that fits the selection size (with its
CURRENT value, so the menu doubles as a readout), the **twist** when the
selection resolves to a rotor, plus Hide and Delete. The entries run the
registered operators, so the menu, the hotkey and F3 can never disagree.

It opens **immediately** on the release (round 36). Round 35 held it back by
one double-click interval so that double-clicking into flight would not pop a
menu first; that is no longer needed, because a single press cannot start
flight any more. The cost is that a right double-click *on a selected atom*
flashes the menu instead of latching flight — anywhere else it latches as
before, and holding still works even on a selected atom.

## Camera objects (rounds 56 and 57)

A camera is a saved viewpoint that lives in the scene, appears at the bottom
of the outliner and rides savepoints and undo like anything else. **F3 →
"Camera: place one here"** (or the `+ Camera` outliner row) saves the view you
are looking at.

### In the viewport
Each camera is drawn as Blender draws one: a **wireframe pyramid** whose
rectangular base is the film (so its shape is the aspect ratio), a small
triangle on top for which way is up, a dot at the apex, and a **dashed line
straight down to the XY plane** — without that line a camera above the floor
and one below it look identical.

| Gesture | What happens |
|---|---|
| **Click the apex dot** | selects the camera and makes it active |
| **G** | move it (screen-parallel, like a pan). Click to confirm, Esc to revert |
| **R** | aim it (turntable, so it cannot pick up a roll it would then store twice) |
| **Double-click it** | look through it |

The camera you are looking THROUGH is not drawn — you are standing at its
apex, and its film back is already on screen as the frame.

### Looking through one

| Gesture | What happens |
|---|---|
| **Orbit** (MMB / Alt+LMB drag) | **Leaves the camera**, keeping the pose you rotated to — Blender's rule |
| **Esc**, **Numpad 0** | Leaves and restores the view from before you entered |
| **Mouse wheel / two-finger scroll** | Resizes the FRAME (see below). Never moves the camera |
| **Ctrl+scroll** | **DOLLIES** the camera along its own view axis — really closer to or further from the subject, so the perspective changes. The frame keeps its size and the contents grow |
| **Alt+scroll**, **Alt+LMB drag** | Orbits, and therefore **LEAVES** the camera view. This is the trackpad's way out: every other scroll inside a camera is spoken for, and a trackpad has no middle button, so without it "rotate to exit" was unreachable there |
| **Shift+scroll**, **Shift+drag** (left button, or Shift+MMB) | Trucks the CAMERA sideways — the last few pixels of framing. 1:1 on screen at any frame zoom, so scroll in for a finer nudge |
| **Compass click / axis view / flight** | Leaves the camera — all view rotations |
| **Tumbling a molecule** | Stays inside — that moves the MODEL, not the camera |

Numpad 0 is bound to **both** `Num+0` and `Num+Ins`, because with **Num Lock
off** the numpad's 0 sends `Key_Insert` — binding only the first is a shortcut
half the keyboards in the world never send.

**The camera object never moves by accident.** Not by a plain scroll, not by
dragging its frame, not by editing its lens or resolution. The gestures that DO
move it all carry a MODIFIER or a selection, and each says so in the status bar:
**Shift+drag** and **Shift+scroll** truck it, **Ctrl+scroll** dollies it, and
**G** on a selected camera gizmo moves it from outside. ("Camera: update the
active one to this view" re-aims it wholesale.)

Round 60 note: a plain scroll resizes the frame and the two MODIFIED scrolls
move the camera. Round 58 sent every scroll to the frame zoom, which made
Ctrl+scroll and Shift+scroll indistinguishable — the modifier is the deliberate
statement, exactly as it is for Shift+drag. The routing reads the MODIFIER and
not `input_map`'s resolved action on purpose: a mouse resolves a plain wheel to
ZOOM and a trackpad resolves it to ORBIT, so keying off the action would give
one gesture two meanings across the two dev machines.

A Shift+drag moves the camera OBJECT, not the free view — which is the
difference between an adjustment that survives leaving the shot and one that
quietly does not, and it is what carries the nudge into the savefile, the
render and the Blender export. The whole drag is one undo step.

**On the LEFT button as well as the middle one** (round 59). Round 58 built
`truck_camera` and hung it off the pan drag, which is Shift+MIDDLE — so the
plain gesture still started an additive box select, and the feature was
unreachable for anyone whose wheel-click is a stiff scroll-wheel press (the
reason round 16 already had to alias orbit onto Alt+LMB). Inside a camera view
Shift + left-drag now trucks; outside one it is still additive box select, and
an explicitly armed box or lasso tool still wins over it.

### The film back

The rectangle is what will be **rendered**, and it means it: the viewport's
field of view is set so the camera's own lands exactly on the frame.

**The frame is angular, not fitted.** Its half-width is `Z·tan(fov_x/2)` and
its half-height `Z·tan(fov_y/2)`, with `Z` set by the frame zoom alone. The
consequence is the whole point: the on-screen scale of the scene works out to
`Z / distance`, with no lens or aspect term in it, so

* **dragging a handle moves a BORDER of the shot** — what it contains changes
  and nothing rescales. A horizontal drag resizes the FILM (the sensor width),
  a vertical one changes the aspect; the resolution follows the aspect with
  the **longer side pinned**, so dragging can reshape a shot but never inflate
  its pixel count;
* **the wheel is the only thing that resizes the picture** — frame and
  contents together, which is Blender's camera-view zoom.

A border is clamped at the window so its own handles cannot be dragged off
screen; scroll out first if you want a wider shot than there is room for.

**F12 through a camera** renders exactly the framed rectangle at the camera's
resolution × multiplier — a crop of an ordinary viewport render, enlarged so
the crop does not upscale (capped, so a small frame cannot demand a huge
buffer). One projection, one set of overlay painters.

### Roll
The interactive camera is a turntable and cannot hold a rolled pose, so a
saved camera carries roll explicitly and it is applied on top of the pose when
you look through one. It uses `Camera.fly_look`'s convention, and
`cameras.twist_rotation` is the single place that knows it — the Blender
export built its own with the matrix transposed and therefore rolled the
opposite way, which nothing noticed while the viewport ignored roll entirely.

## Animation export (Ctrl+Shift+A) and the render keys

| Key / operator | What it does |
|---|---|
| **Ctrl+Shift+E** / **Ctrl+Shift+A** | The deliberate routes. Always ask, every time |
| **F12** / **Ctrl+F12** | Render NOW with the last settings, to the next free filename. The first press behaves like the deliberate route |
| `F3 > Render settings: animation / still (ask again)` | Forgets the remembered target and reopens the dialog. Without these the settings were a **one-way door** — once F12 had a target the dialog never came back |

The dialog reopens showing the LAST choices, not the defaults: someone who goes
looking for the settings is nearly always there to change one of them.

**A PNG image sequence is the primary format and needs no ffmpeg at all.** It is
what feeds Blender or a journal, and a failed video encode still leaves every
rendered frame on disk, because the video is always encoded FROM the written
sequence.

**GIF frame rates are snapped** (round 61). The format stores each frame's delay
as a whole number of centiseconds, so the only rates it can hold exactly are
100/n — 60 fps wants 1.667 cs, gets rounded unevenly, and plays as a stutter.
MoloM snaps before encoding and says what it is going to do while you choose:
60 → 50, 30 → 33.3, 24 → 25. **MP4 is not affected** (a rational timebase holds
60 exactly) and a PNG sequence has no embedded timing at all.

**ffmpeg is found, not shipped** (round 61, roadmap item 9). `imageio-ffmpeg` is
an OPTIONAL extra (`pip install "molom[video]"`) rather than a required
dependency — a ~25 MB static binary should not ride along on every install for a
minority feature. The search order is a Settings hint, then `PATH`, then the
usual install locations, then the bundled wheel LAST (a system ffmpeg is usually
newer and has the codecs you installed it for). The dialog names which one it
found *before* the render, and grows a **"Locate ffmpeg..."** button only when
there is none.

## Defining a unit cell (round 68)
The ❖ page's **Define / edit the cell** block. Until now every cell control
assumed a cell that came out of a `.cif`: a molecule with no cell could never
be given one, and an imported cell could never be corrected.

| Control | What it does |
|---|---|
| **a, b, c, alpha, beta, gamma** | The six parameters, editable |
| **Fit to molecule** | Fills them from the bounding box plus a 2 Å margin, so there is something sensible to adjust |
| **Space group** | A symbol (`P 21/c`). Resolved through the same Hall database a file's own symbol goes through, so a hand-made cell expands exactly as an imported one would. Empty means P1 |
| **Keep fractional coordinates** | See below |
| **Apply** / **Remove cell** | |

**"Keep fractional coordinates" is the decision that matters**, and there is no
right default for both cases:

* **ON** — the atoms keep their fractional positions and move with the box, so
  the structure stretches and shears with it. This is what a cell edit *means*
  crystallographically: fractional coordinates are the structure, and a, b, c
  are the frame they live in. Doubling `a` doubles every distance along **a**.
* **OFF** — the atoms stay exactly where they are and only the drawn box
  changes. This is what you want when putting a box around a molecule that
  never had one.

Giving a cell to a molecule that had none always keeps Cartesian regardless,
because there are no fractional coordinates to preserve.

**The angles are not independent.** Three angles only close into a cell when
`1 − cos²α − cos²β − cos²γ + 2·cosα·cosβ·cosγ > 0` — the squared volume factor.
Something like **30/30/120 passes every per-angle range check and describes no
solid at all**; the faces cannot meet. That is refused with the reason written
on the page, and nothing is written to the structure.

**Removing a cell takes the crystallography with it** — operators, the stored
asymmetric unit, the derived columns. Keeping a space group for a cell that no
longer exists is how a later rebuild invents a structure from nothing.

### Atom position (fractional), round 69
Select **exactly one atom** on a molecule that has a cell and the block below
shows its position in cell fractions, editable. "A quarter along **a**" is a
statement about the structure; 3.47 Å is a statement about this particular
cell, which is why typing a site is how a structure gets built by hand.

**Wrap into the cell is off by default.** Bringing a value into [0, 1) is what
you want when typing a site in, and emphatically not what you want when nudging
an atom that legitimately sits outside one — a boundary copy, or a molecule
that has been unwrapped to keep it whole.

The move applies to every frame, and the block greys itself out (saying which
condition is missing) rather than offering three live-looking fields that would
apply to nothing.

## Third-person shuttle (rounds 66 and 67)
`F3 > Shuttle mode: pilot from behind`. The same flight model as the cockpit -
same thrust, same coast, same steering - with the camera behind and above the
molecule instead of inside it, and the **same steering instrument** (hull mark,
travel ring, aim reticle, roll tick, speed).

**Select ONE atom first and it becomes the cockpit.** The camera sits behind
and slightly above that atom, which is what you want for anything long or
hollow, where the centroid is nowhere near the nose. With nothing selected, or
more than one atom, it falls back to the molecule's origin.

**The camera's up is always world Z and it never rolls.** Q/E rolls the SHIP,
which in third person you can see it do. Letting the camera roll tilted the
horizon and - because the pivot used to be offset along the camera's own up -
swung the molecule off to one side, which is exactly what "the piloted mol is
on the left hand side once a roll has been introduced" was.

Why it exists: in first person you cannot see the ship's orientation, and a
molecule has no windscreen to give you a horizon, so the two cues that make
flying legible are both missing. That is what "trying to do it FPS only leads
to problems" means in practice.

**The camera lags, and that is the feature.** A rigid chase camera swings the
whole world around the ship and is as disorienting as sitting inside it, which
would reproduce the problem being fixed. The pivot eases toward the ship with
exponential smoothing, so acceleration is readable: the molecule pulls ahead in
frame under thrust and settles back when you coast. The easing is
framerate-independent (`1 - exp(-lag·dt)`), because a fixed fraction per frame
would trail further at 30 fps than at 120 and the feel would depend on the
machine.

Two details that are deliberate:

* **The gap is capped** at 3 molecule radii. Lag is a feel; losing the ship off
  the edge of the screen during a long burn is a bug.
* **Nothing is clipped.** The cockpit hides atoms too close to the camera so
  they cannot fill the screen; here that rule would hide the ship itself.

The chase distance and height scale with the molecule's own radius - these
scenes run from a 3 Å molecule to a 200 Å framework, and a fixed distance would
be either inside the ship or nowhere near it.

## Blender export (Ctrl+Shift+B, round 37)
Writes a **`.blend`** (round 50). Christian: "I don't like having to load it in
every time... all I have to do is press F12." Blender is INVOKED to build it —
the same generated script, run headlessly as `blender -b --factory-startup
--python build.py -- --save out.blend` — so the scene is complete before the
file is saved and the `.blend` opens ready to render: no auto-run, no "Allow
Execution", no trust dialog. The script rides along as a text datablock and
stays on disk beside the `.blend`, and it is still an output format on its own,
because it is diffable, editable before it runs and needs no Blender at all.
The Blender path is a setting with discovery (stored hint, then PATH, then the
usual install locations newest-first); a `blender-launcher.exe` is resolved to
the real `blender.exe` beside it, since the launcher is a GUI shim that cannot
be scripted. A failed build leaves the script and says so.
**One Angstrom = one Blender unit.**

A dialog comes up first, because a render is a dozen decisions and every one
is quicker to make here than to hunt for in Blender afterwards. Defaults are
chosen so that "just press OK" gives something worth looking at.

| Group | What it does |
|---|---|
| **Environment (HDRI)** | Blender's own material-preview HDRIs — `forest`, `studio`, `city`, `courtyard`, `interior`, `night`, `sunrise`, `sunset` — or a file of your own, or none. Resolved from `bpy.utils.system_resource` when the script RUNS, so no path from this machine is baked in. Strength and Z rotation included; rotation is the cheapest way to move a highlight off an atom you need to read |
| **Show the environment behind the molecule** | Off (default) renders on a **transparent** background while still lighting with the HDRI — what a figure wants |
| **Camera** | Placed in exactly the viewport's pose: same position, same aim, same vertical field of view, orthographic if the viewport is. Resolution defaults to the viewport's own size, so the framing you see is the framing you get |
| **Lamp rig** | Three-point studio / key only / none / sun. Lamps are placed in the CAMERA's frame so the rig follows the shot, and their power goes as **distance squared** so a 5 Å molecule and a 100 Å framework are lit the same. With an HDRI they run at **half** strength — both at full blows the white hydrogens out |
| **Materials** | One per element **plus one per distinct custom colour**, so an atom the outliner painted violet arrives violet and two atoms painted alike share a material. Colours are converted **sRGB → linear** (Blender's sockets are linear; raw sRGB renders washed out). Metals optionally get a metallic shader |
| **Geometry** | Style (or follow the viewport), icosphere subdivisions, bond sides, shade smooth. Bonds are split at the midpoint and coloured by each atom, exactly as the viewport draws them; hidden atoms, per-atom sizes and the modifier stack all carry over |
| **Unit cell** | The box as cylinders with a/b/c in the axis colours |
| **Render** | Cycles or EEVEE (the script falls back gracefully — EEVEE was renamed twice and Cycles is an add-on), samples, and the view transform. **Standard** keeps the viewport's colours literally; AgX/Filmic roll off the highlights |

Everything lands in a `MoloM` collection with `atoms`, `bonds` and `rig`
sub-collections, so re-running the script cannot lose your own objects. Atoms
and bonds share one mesh datablock each and are linked duplicates with
per-OBJECT material slots: the file stays small and every atom is still
individually selectable. Choices are remembered between sessions (the camera
and resolution are not — those follow the viewport).

## Boundary bonds (round 39)
A bond whose partner sits in the next cell is not drawn by a straight-line
perceiver, so a **framework comes out severed at every face**. On a real ZIF
the connectivity had 224 bonds and only 196 were drawable — 48 atoms short a
bond each, and every imidazolate at a face reduced to a stub.

The **Boundary bonds** modifier closes them by materialising the periodic
image at the far end of each cut bond. It is a MODIFIER, so the molecule
itself stays exactly the cell contents (Z, the ❖ atom count, editing and
unit-cell export are unaffected) while the viewport and the Blender export see
a continuous framework. It is added automatically at import when a crystal
needs one, appears on the Modifiers page, and the ❖ page's *Bonded atoms
outside the cell* checkbox switches it on and off.

Four rules, each of which stops it running away:

| Rule | Why |
|---|---|
| **covalent bonds only** | Every one of MOF-5's 24 cross-face bonds is a covalent C–C inside a linker; every one of rock salt's is ionic. Following coordination bonds turned a 9-atom NaCl cell into 59 and said nothing new — and a coordination bond is where a framework is *meant* to be cut (round 38) |
| **finite fragments only** | A lattice or a covalent polymer is infinite; every shell you draw looks as unfinished as the last. The explicit round-35 *exterior* search still works on those — that is a deliberate "show me one more shell", not an automatic fix |
| **whole molecules** | Half a five-ring is not a thing that exists. Turn it off in the card for the cheaper single-atom closure |
| **de-duplicate by position** | An image landing on an atom that is already drawn is a duplicate. Without this a structure carrying 777 boundary copies grew to 6389 atoms |

## Chemistry filters (round 38)
Three things a distance rule cannot know, applied at import and reported in
the status bar and on the ❖ page. **Every refusal is stated** — a silently
dropped atom is indistinguishable from a bug.

| Filter | What it does | Why |
|---|---|---|
| **Bond kinds** | A bond between a metal and a non-metal is a **coordination** bond (`bonding.bond_kind`). Metal–metal stays covalent | It is where a framework gets cut into molecules. MIL-53's single 152-atom infinite component becomes 8 linkers + 8 OH bridges + 8 waters + 8 Al, all finite and completable at the cell boundary — which is how Mercury knows to stop after the carboxylate. The cut is applied **only to components that are actually infinite**, so ferrocene is never dissected |
| **Valence sanity** | Bonds shorter than **0.80 Å, or 0.65 × the covalent radii, whichever is larger**, are impossible and go — the absolute floor is what guards hydrogen, where the relative one gives C–H only 0.696 Å. It sits above HeH+ (0.772, and neither it nor H₂ is bonded at all) and below the shortest hydrogen an X-ray refinement really produces (0.88). The **over-valence cap does not apply to what a crystal DRAWS** (round 81) — it still applies to molecules, and to the fragment walk that decides what belongs together, where it goes longest-first with a last link to the skeleton kept back. Coordination bonds are exempt from the cap | HpPyBz_th.cif's 0.75 Å C···C fused four molecules into a chain that percolated, so the whole cell read as a framework. But a carbon with six hydrogens is what a methyl disordered over two orientations at full occupancy *is*, and a viewer that quietly picks four of them is glossing over the refinement. A chloride bridging three metals is ordinary and must survive |
| **Occupancy / disorder** | `_atom_site_occupancy` and the disorder GROUP columns are read and applied. Settings ▸ **CIF disorder**: *Resolve superimposed alternatives* (default), *Only the major component* (drops < 50%), *Draw every alternative* (the raw file) | A disordered CIF lists every alternative, and drawing them together superimposes atoms that are never present at once. Resolution runs on the EXPANDED atoms, because alternatives are routinely symmetry images of one another. A **lone** partial site is never dropped — it is a real partial site, and a half-occupied atom on a special position is a special position |

## Settings
**Pointing device (auto / trackpad / mouse)**, rotation sensitivity,
Shift-drag precision factor, **sphere size** (scales every atom radius,
updates live — only the instance buffers are rebuilt), **atom label size**,
**undo history depth (default 30)**, **adjust hydrogens when editing**,
**CIF disorder policy**, startup maximized/windowed, render resolution and
smoothness.

Atom labels are sized from each atom's on-screen RADIUS (so they track zoom)
and only squeezed when the text would overhang the sphere — every label in a
molecule therefore comes out the same height. The slider multiplies that
size; it is not bold, and it prefers a wide sans (Verdana) so digits stay
distinct.

## Where shortcuts come from
Every key lives on its **operator** (`key=` in `_register_operators`) and is
installed by `MainWindow._install_shortcuts` as one window-level QAction.
Menus reuse those same action objects and never define keys of their own.

This is deliberate: the menus are an ESSENTIALS shortlist (F3 is the real
index), and when they were thinned the keys went with them — `O`, `Home`,
`End`, `Shift+R`, `B`, `Shift+B`, `Ctrl+B`, `Ctrl+P` and the box-select chord
were bound nowhere. F3 itself was worse: it sat on **two** menu actions, and
Qt answers an ambiguous shortcut by firing *neither*, so the palette silently
stopped opening. `OperatorRegistry.duplicate_keys()` now makes that a startup
error and `tests/test_round16_input.py` pins the table.

Keys that must reach the viewport instead (`E` for the draw tool, `X/Y/Z`)
are registered with **no** `key=` — a single-letter QAction outranks the
widget.

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
- Duplicate molecule, measurement overlays in-viewport, depth-cue fog,
  numbered-frame outliner rows for trajectories.


## Finding a molecule (Ctrl+Shift+N) - round 90

Replaced the single-answer resolver dialog, and the reason is measured rather
than aesthetic: PubChem's exact-name endpoint **404s on "xylene" and on
"cresol"**, while OPSIN answers both with the ORTHO isomer and says nothing
about it. A dialog that shows one structure cannot tell you either happened.

OPSIN, CACTUS and PubChem are asked AT ONCE and their results merged. The
merge runs on the **InChIKey**, not on the name and not on the CID: a CID is
PubChem-local and a SMILES is not canonical across toolkits, while an InChIKey
is a hash every service indexes on. That is also what lets a structure OPSIN
found be enriched with PubChem's name, formula and weight - so the cascade in
`core/resolve.py` did not have to change at all.

Rows appear as each provider lands and a row already drawn is never moved,
only filled in. Formula and molecular weight are computed offline by RDKit, so
every row has them; for the case this exists to fix they are identical across
the candidates, which is why the panel on the right draws the selected
compound. A name that was silently interpreted says so on its row.

The search accepts a pasted SMILES, InChI or CAS number as well as a name.

### Compound properties (add-on, F3: "Compound: fetch properties from PubChem")

`molom/addons/mol_properties.py`, off by default. Adds a properties page
showing what is known about the compound a molecule IS - melting point,
density, solubility and the rest - each value with its source. It shows up to
three values per heading and says how many more there were, because there is
no such thing as "the melting point": aspirin's own record carries seven, in
three unit conventions, one of them without a unit at all.
