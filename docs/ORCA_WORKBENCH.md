# Using MoloM from ORCA Workbench

This is roadmap item F, and it is the thing MoloM was started for: OWB's
`viewer_3d_path` / `editor_3d_path` slots pointed at a first-party tool
instead of Avogadro.

## 1. Point OWB at MoloM

OWB launches an external 3D program as `[program, file.xyz]` and nothing else
(`orca_workbench/ui/molecules_tab.py::open_xyz_3d`), so no OWB code changes.
It needs a single program path, which you get from:

```bash
molom --where
```

On this machine that prints
`C:\Users\chris\AppData\Roaming\Python\Python310\Scripts\molom.EXE`. Paste it
into OWB's **External programs** settings, into any of:

| slot | what it is used for |
|---|---|
| `viewer_3d_path` | look at one geometry |
| `editor_3d_path` | the geometry round-trip (see below) |
| `traj_viewer_path` | a multi-frame optimisation trajectory |

The trajectory slot works because MoloM reads a multi-frame `.xyz` as a
trajectory and gives it the scene clock, so an optimisation plays back.

If `molom --where` says there is no console script, `pip install -e .` in the
MoloM checkout creates one. OWB accepts a bare `molom` too, since it checks
`os.path.isfile(viewer) or _on_path(viewer)`.

## 2. The geometry round-trip

OWB's flow, unchanged:

1. **Edit geometry** in the Molecules tab opens the `.xyz` in `editor_3d_path`.
2. You edit, and **Save so it overwrites the .xyz**.
3. Back in OWB, **Reload geometry** re-reads that file and sets
   `coords_locked`, so a hand-edited geometry is not clobbered by SMILES
   regeneration.

Step 2 is the part MoloM had to learn. **Ctrl+S writes the geometry back over
the file the session was opened from**, because that is what OWB's instruction
means and what every other editor does. Specifically:

* opened from a structure file, no project saved -> Ctrl+S overwrites that
  file;
* a `.molom` project open or saved -> Ctrl+S saves the project, as before;
* neither -> Ctrl+S offers **Save project as...**.

`Ctrl+Alt+S` ("Save geometry back to the opened file") always means the first
of those and is in the File menu and F3, so the round-trip is reachable
whatever else has happened in the session.

Only the FIRST structure file of a session becomes the document. Imports ADD
in MoloM rather than replacing, so opening a second molecule to compare
against does not silently re-point Save at it.

## 3. Reading a `%geom` constraint

**ORCA atom indices are 0-based** - `orca_workbench/core/geomspec.py` says so
outright, and OWB's constraint editor uses the same numbers. To see which
atoms a constraint names:

```bash
molom mol.xyz --select 3,7,11
```

Commas or spaces, either way. The atoms are selected on opening, and for two,
three or four of them MoloM prints the bond, angle or dihedral they define -
which is exactly what the constraint is about. Press **F** to frame the
selection.

An index the file does not have is reported rather than quietly dropped.

## What is still open

* **F2 is one-way.** MoloM can read indices out of a constraint; it cannot
  hand a selection back as a `%geom` block. "Copy selection as an ORCA
  constraint" is the obvious next step and is not built.
* MoloM does not know about OWB's project structure - it is handed one file
  at a time, which is all the slots offer.
