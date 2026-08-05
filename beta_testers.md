# MoloM — notes for beta testers

Thanks for trying this. MoloM is an early, fast-moving molecule viewer and
builder, so this file is the honest version of "what state is it in": what to
look at first, what I already know is shaky, and what a genuinely useful bug
report looks like.

Maintainer: Christian Nelle (AG Henke, TU Dortmund).

---

## The one thing I am least confident about: `.cif` import

**If you find one bug, I would rather it were this one.** Crystal structures
are complicated and annoying, and the CIF reader is hand-rolled — a
deliberate choice (no heavy dependency, offline tests), but it means the
subset of the format it understands is the subset I have tested against.
Real files from real databases are far more varied than any test fixture.

Please throw structures at it, especially awkward ones, and tell me when the
picture disagrees with Mercury, VESTA or Diamond. Known weak spots, roughly
in order of how likely they are to bite:

- **A file can simply be wrong, and MoloM will now say so rather than draw
  it.** One test file here (an OpenBabel-converted `.cif`) has two atoms
  0.75 Å apart, which is not a distance chemistry allows — and **ASE reads
  exactly the same atoms from it**, so the geometry really is broken in the
  file rather than in the reader. MoloM refuses bonds that are impossibly
  short or that push an atom past its valence, and **tells you in the status
  bar how many it dropped**. If a structure looks impossible, it is still
  worth opening it in a second program before assuming MoloM mangled it.
- **Partial occupancies and disorder are now handled** — see *Settings ▸ CIF
  disorder*. By default MoloM keeps the most occupied of each set of
  superimposed alternatives; "only the major component" additionally drops
  everything under half occupancy, which for a MOF usually means the
  framework without its disordered guest; "draw every alternative" gets the
  old raw behaviour back. **I still want disordered CIFs**: the policy is
  only as good as the files it has been tried on, and I have two.
- **A space-group SYMBOL with no symmetry-operator loop falls back to P1**,
  which silently shows you only the asymmetric unit. If a structure looks
  like a fraction of what it should be, this is the first thing to suspect.
- **Bonds across cell faces are perceived non-periodically**, so a FRAMEWORK
  (as opposed to a molecular crystal) can appear cut open at the boundary.
  The atoms are there; the sticks between them are not.
- **Non-standard settings, odd origins, and unusual centrings** are the least
  exercised paths of all.

The parts I am comparatively confident about, because they were checked
against reference viewers rather than guessed: cell parameters, symmetry
expansion with de-duplication on special positions, whole-molecule wrapping,
boundary completion (rock salt gives the textbook 14 Na + 13 Cl), and the
symmetry element glyphs.

**What helps most in a report:** the file itself, a screenshot of what MoloM
drew, and — if you can — a screenshot of the same file in Mercury or VESTA.
"It looks wrong" plus the file is already a good report; I can usually find
the rest.

---

## Other things worth knowing before you start

- **It is a Blender-style interface, not an Avogadro-style one.** Tab
  switches between object mode (arranging molecules) and edit mode (changing
  one molecule's chemistry). G grabs, R rotates, A aligns, D duplicates,
  F frames the selection, and **F3 opens a searchable list of every command**
  — if you cannot find something, press F3 and type a word for it. Full key
  table in `docs/OPERATORS.md`.
- **Imports ADD, they never replace.** Opening a second file puts a second
  molecule in the scene. The outliner (M) is where you manage them.
- **Bonds are perceived once, at import, and are not silently re-perceived
  afterwards.** If you pull an atom out of a molecule, its bonds stay. That
  is deliberate — connectivity changing under you while you edit is worse.
  Ctrl+P re-perceives on request.
- **Coordinates read from FILES are never silently transformed** (no
  auto-centring, no auto-rotating). Geometry generated from SMILES is fair
  game and does get centred and aligned.
- Two optional libraries widen what can be opened: **RDKit** and
  **openbabel-wheel**. Without them MoloM still runs, just with fewer import
  formats.

## Where the rough edges are, outside CIF

- **Ligand templates** (marking donor atoms and docking a ligand onto a metal
  centre) exist and the geometry is right in isolation, but the workflow
  around them does not hold together yet in real use. Treat it as unfinished.
- **Meta atoms** (a dummy centre carrying a coordination geometry, frozen
  during optimisation) work, but the constraint is rigid rather than
  harmonic: the centre and its whole first coordination sphere are frozen
  while the ligands relax. Also, deleting atoms near a meta centre can leave
  its table pointing at the wrong indices.
- **Force-field optimisation degrades quietly** rather than refusing: MMFF94
  → UFF → OpenBabel UFF, and a half-drawn molecule that is not valid
  chemistry will still get the best geometry available rather than an error.
  If a result looks odd, check which tier actually ran.
- **Animation export does not exist yet.** You can animate in the viewport
  and export a single image (Ctrl+Shift+E), but not a movie.
- **`fit_view` frames the ATOMS**, so a unit cell box larger than its
  contents can overflow the view.

## Recently changed, so most likely to be wrong

These landed in the current round and have had the least real-world use:

- **The right mouse button FLIES**, and the controls are now full 6DoF:
  **W/S** thrust, **A/D** strafe, **Space/Ctrl** up-down, **Q/E** roll,
  Shift boosts, **Alt** creeps. Hold the button to fly for a moment, or
  **double-click it to latch** — then a single right click or Esc lands you.
  Letting go of the keys auto-brakes rather than drifting. Pan is on
  Shift+MMB and Shift+scroll; if losing right-drag pan costs you something
  important, say so.
  **Steering is a virtual stick, not a mouse drag.** The mouse moves a
  reticle; wherever you leave it, the ship keeps turning that way until you
  bring it back to the middle. The ship banks into the turn automatically and
  levels when the reticle comes home. The pointer is hidden and captured
  while flying, so you can sweep as far as you like without hitting an edge.
  The whole feel is tunable under **App > Settings > Flight**, live, even
  while you are flying — if it is wrong for your hardware, that is the first
  place to look, and I would like to know what you ended up with.
- **A right CLICK over the selection opens a context menu** with bond
  length / angle / dihedral editing. Select 2, 3 or 4 atoms **in the order
  that defines the coordinate** (the middle atom of an angle is the vertex;
  the two inner atoms of a torsion are the axis), then right-click one of
  them. The rest of the molecule follows the change rigidly. Note the menu
  now waits one double-click interval before appearing, so that a double
  right-click can mean "fly" instead — that pause is deliberate.
- **Selection is an orange outline** instead of a translucent blue bubble,
  and it is much thinner than it was a round ago.
- **Crystals get a VESTA-style orientation ribbon** along the top of the
  viewport whenever one is selected: view down a, b, c or the reciprocal
  a\*, b\*, c\*, drop into the standard clinographic projection, and
  rotate/pan/zoom in fixed steps. The reciprocal axes are genuinely
  different directions from the direct ones in a non-orthogonal cell — if
  they ever look identical to you in a monoclinic or triclinic structure,
  that is a bug worth reporting.
- **"Ext" on a crystal's outliner row** draws bonded atoms just outside the
  cell, so chains and frameworks run on instead of being cut off at the
  faces. It is **off by default**. This partly addresses the "bonds across
  cell faces" limitation listed above — the atoms and their bonds are now
  drawn, though the perception behind them is still non-periodic.
- **Ghost images of the asymmetric unit** were being torn apart at cell
  faces; that is fixed, but it is exactly the kind of fix that can be right
  on the structures I have and wrong on yours.

There is also a **screen flicker** I have had one report of, on a desktop
machine but never on the laptop. I found and fixed a genuine bug that would
produce exactly that symptom — the selection outline could be drawn in place
of the molecule for a single frame — but I could not reproduce the flicker
itself, so I cannot promise it is gone. **If you still see flickering, please
say so**, and mention your GPU: that is the variable I could not test.

## Reporting

Anything is welcome, including "this felt wrong but I cannot say why" —
several of the better fixes in here started as exactly that. Especially
useful:

- the file, if one is involved;
- a screenshot (MoloM's own Ctrl+Shift+E writes a clean PNG);
- what you expected instead;
- whether you are on a **trackpad or a mouse** — the two have genuinely
  different input handling, and a bug in one is often invisible in the other.

If something crashes or a feature seems dead, it is also worth checking the
terminal: an exception inside a Qt slot **prints and lets the app carry on**,
so a stack trace there often explains something that looks like a rendering
or "feel" problem.
