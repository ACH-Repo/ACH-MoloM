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

- **Partial occupancies and disorder are read but IGNORED.** If a site is
  disordered, every alternative position is drawn at once, superimposed. It
  will look like atoms in impossible places, because they are. Fixing this
  properly needs a display policy (dominant component by default, with a way
  to see the others), and I want a decent set of real disordered files first
  — so **please send me disordered CIFs**, they are exactly what is missing.
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

- **The right mouse button now FLIES** (hold it, then WASD/QE, Shift to
  boost). It used to pan. Pan moved to Shift+MMB and Shift+scroll — if that
  costs you something important, say so and I will reconsider.
- **A right CLICK over the selection opens a context menu** with bond
  length / angle / dihedral editing. Select 2, 3 or 4 atoms **in the order
  that defines the coordinate** (the middle atom of an angle is the vertex;
  the two inner atoms of a torsion are the axis), then right-click one of
  them. The rest of the molecule follows the change rigidly.
- **Selection is now an orange outline** instead of a translucent blue
  bubble.
- **Ghost images of the asymmetric unit** were being torn apart at cell
  faces; that is fixed, but it is exactly the kind of fix that can be right
  on the structures I have and wrong on yours.

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
