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
- Element groups **and** individual atoms carry the same five squares —
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

The **unit cell box** draws as a viewport overlay — 12 clipped edges, with
a/b/c from the origin corner in the axis colours (red/green/blue), the same
convention as the compass. Toggle it from F3 ("Show unit cell box").

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
four. The player's **Smoothing** then subdivides between these frames, which
is why a fairly small count still looks continuous.

Animating bakes one period of the mode into ordinary trajectory frames, so it
arrives on the scene clock like any other track: it interpolates, it appears
in the multi-track pane, and it plays alongside other trajectories. The track
is set to loop, because a vibration is one.

## Trajectory playback (the scene clock)
There is **one playhead for the whole scene**, not one per molecule, so every
trajectory loaded plays at the same time. The bar under the viewport is that
playhead: play/pause (**Space**), the loop limits, the two playback knobs, a
position readout, and a **▾** toggle that opens the track rows.

### Frames, images and seconds
Three different things, kept apart deliberately:

| | |
|---|---|
| a **frame** | a coordinate set that came out of an input file. How many there are is a property of the data — a trajectory's steps, one sample of a normal mode — and nothing the player chooses. |
| an **image** | one picture the player draws. **Smoothing** says how many fill the gap between two consecutive frames (1 = no interpolation, draw the frames themselves). |
| **Framerate** | images per second. Global, because it is a property of the playback rather than of any one molecule. |

So one source frame lasts `Smoothing / Framerate` seconds, and **Playback**
counts images: `current / total`. Keeping the two knobs separate is what lets
a 12-frame optimisation and a 200-frame trajectory both play at a watchable
speed without touching the data.

One consequence is worth knowing: at a fixed framerate, doubling the
smoothing plays *slower* as well as smoother — twice as many pictures in the
same second is half the trajectory per second, exactly like shooting video at
60 fps and playing it back at 30. Raise the framerate too if you want the
original speed. Both knobs sit next to each other so the trade is visible.

### Loop limits
**Loop [first] - [last]** bound the interval the playhead runs over, in
images, so you can loop the interesting twenty frames of a five-hundred-frame
run. They are also draggable in the track pane — the two green handles — and
everything outside them is veiled. Leaving the end on its maximum means "to
the end of the scene", so a trajectory that grows later stays covered.

The limits are stored in frames, so changing the smoothing renumbers them but
does not move them. Dragging the playhead past a limit parks it there rather
than wrapping: a wrap under the cursor is unreadable while scrubbing.
Playback itself still wraps, per the end mode.

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
| drag a bar sideways | slide that track's **start offset** |
| click the dot in the gutter | enable / disable that track |
| double-click a bar | cycle its end mode: hold → loop → pingpong |
| click empty track space | seek the playhead there |

Rows are ordered by start time, so a staggered set reads top-to-bottom.

Each object gets a **track** mapping scene time to its own frames through a
**start offset**, a **speed**, and an end behaviour (**hold** the last frame,
**loop**, or **pingpong**). So two trajectories can be staggered, or run at
different rates, off the same clock. A molecule with one frame is a still and
simply never moves. The scene runs as long as its longest track.

**Smoothing** above 1 interpolates between frames instead of stepping. A
plain blend would send every atom along the straight chord between positions,
which makes a *rotating* molecule contract toward its centroid halfway
through the turn and spring back — bonds visibly losing length. Instead the
rigid part of the motion is extracted (Kabsch) and turned as a real rotation,
and only the leftover deformation is blended. At 3000 atoms this costs
0.25 ms per frame, well under the buffer upload that follows it.

Interpolated coordinates are **display only** — the stored frames are never
written, so scrubbing cannot damage a trajectory, and editing always sees
real frame data. Bond perception runs only when an object's nearest whole
frame changes, never on every interpolated tick.

## Measure
The 📏 toolbar tool. Click **2** atoms for a distance, **3** for an angle
(vertex on the middle pick), **4** for a dihedral in the atan2 convention.
Clicking a picked atom again unpicks it; a fifth click starts over; **Esc**
finishes. Picks are ringed and chained in the viewport and the value is drawn
there too — it lived in the status bar before, where transient messages
covered it and it read as a dead tool.

It works in BOTH modes and **never touches the selection**, so you can
measure without losing what you were about to edit.

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
| **RMB hold** | **fly** (see below) | **fly** |
| **RMB click over the selection** | context menu | context menu |
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

### Flying (hold the right mouse button) — round 34
UE5's right-mouse fly. Hold RMB and:

| Input | Effect |
|---|---|
| move the mouse | look — yaw + pitch, **never roll**; pitch stops just short of vertical (over the pole the horizon inverts, which is indistinguishable from roll) |
| **W / S** | forward / back |
| **A / D** | strafe left / right |
| **Q / E** | down / up |
| **Shift** | boost (3x) |
| **Ctrl** | creep (0.25x) |
| scroll | set the cruising speed |
| release RMB | stop thrusting — you **coast** to a stop |

It is a real little physics model (`core/flight.py`), not a step per
keypress: thrust accelerates a world-space velocity, drag is exponential (so
it is stable at any frame time), and speed is capped. Velocity is kept in
WORLD space deliberately — turning does not re-aim the momentum you already
have, so you keep drifting the way you were going while you look elsewhere,
which is what makes it feel like flying rather than like a camera. Speeds
scale with the scene size, so a 3 Å cell and a 300 Å framework fly the same.

**Shuttle / pilot mode uses the identical model**, with the molecule as the
airframe instead of the camera — so there is one place to tune the feel and
the two cannot drift apart. The round-8 version moved a fixed step on every
key PRESS, which delivered Qt's auto-repeat rhythm and read as choppy.

**RMB no longer pans.** Pan is on Shift+MMB and Shift+scroll, on both
devices. Hanging pan off a modified right-drag was rejected because every
modifier that could carry it already means something *inside* flight.

### Right-click menu (over the selection)
A right-CLICK — pressed and released without moving or thrusting, with the
cursor **on a selected atom** — opens a small at-the-cursor menu
(`ui/choice_popup.py`, the same widget J uses) instead of flying. It lists
only what applies: the geometry edit that fits the selection size (with its
CURRENT value, so the menu doubles as a readout), plus Hide and Delete. The
entries run the registered operators, so the menu, the hotkey and F3 can
never disagree.

## Settings
**Pointing device (auto / trackpad / mouse)**, rotation sensitivity,
Shift-drag precision factor, **sphere size** (scales every atom radius,
updates live — only the instance buffers are rebuilt), **atom label size**,
**undo history depth (default 30)**, **adjust hydrogens when editing**,
startup maximized/windowed, render resolution and smoothness.

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
