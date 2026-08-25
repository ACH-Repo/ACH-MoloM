# Round 86 — what to test

Everything below is a real gesture, not an internal check. The **watch for**
line on each is the failure mode I'd expect if I got it wrong.

---

## 1. Crystal search — `Ctrl+Shift+Alt+N`

- [ ] **1.1** Search `benzoic acid`. Close the dialog with Cancel. Reopen it.
      → The query and the whole result table should still be there, the info
      line reading *"…from your last search. Press Enter to run it again."*
      **Watch for:** an empty table (memory not restored), or a visible pause
      / network spinner (it re-ran the search, which it must not).

- [ ] **1.2** Leave it ten minutes, reopen.
      → The line should now say *"…, 10 minutes ago"*.
      **Watch for:** no age at all on a genuinely old result — a stale list
      that looks live is the thing this exists to prevent.

- [ ] **1.3** Import something, then reopen the dialog.
      → Still remembered. (Kept whether or not you imported: closing the
      dialog to look at what you just took is the commonest way to end up
      reopening it.)

- [ ] **1.4** Click the **T / K** header. Click again. Click a third time.
      → ascending, then descending, then **back to the original ranking**.
      **Watch for:** `100` sorting before `98` (that is the lexical bug the
      whole thing was written to avoid), or the third click doing nothing.

- [ ] **1.5** With the temperature column sorted, look at where the blank
      cells went. Now reverse it.
      → Blanks stay at the **bottom** both ways.
      **Watch for:** blanks jumping to the top when reversed — an unknown
      temperature is not the highest one.

- [ ] **1.6** Same on **Year**, and on **Name / mineral** (that one should be
      case-insensitive: `Quartz` and `quartz` adjacent, not in different
      halves).

- [ ] **1.7** **The one that would be worst to get wrong:** sort by
      temperature, pick a row *in the middle*, note its formula and space
      group, and import it.
      → You must get **that** structure.
      **Watch for:** a different crystal arriving — that would mean the table
      row is not being mapped back through the sort.

---

## 2. Outliner — the crystallographic site tier

Use a CIF with several sites per element. Ferrocene
(`tests/data/cod_2101932_ferrocene.cif`) has five carbon sites; one of your
MOFs is a better real test.

- [ ] **2.1** Expand an element group.
      → Rows named as **the file names them** — `C(11)`, `O3`, `Nb1` — with a
      count each, and the atoms one level further down.
      **Watch for:** invented names like `site 2` where the CIF has real
      labels.

- [ ] **2.2** Hit the **H** square on one site row.
      → Every drawn image of that site disappears together, and nothing else.
      This is the thing you asked for: *"hide all oxygen atoms of a specific
      type."*

- [ ] **2.3** Colour a site, and set a sphere size on a site.
      → Same behaviour, whole orbit at once.

- [ ] **2.4** Find an element with only **one** site (ferrocene's Fe).
      → **No site tier** — straight to the atoms. One site is not a grouping.

- [ ] **2.5** Open a plain molecule (cubane, or anything from SMILES).
      → Unchanged: element → atoms, no middle row.

- [ ] **2.6** Edit a crystal (draw an atom into it), then expand that element.
      → The added atom appears under **(added since)** rather than being
      filed under a site it has nothing to do with.

---

## 3. Outliner — speed and the freeing

- [ ] **3.1** Expand a big element group (your 300-oxygen case).
      → Should feel immediate now. Measured 473 → 73 ms flat, and 4.5 ms when
      it splits into sites.

- [ ] **3.2** Collapse it, then expand it again.
      → Must still open. **Watch for:** the expander arrow vanishing after a
      collapse, leaving a row that can never be reopened — that is the
      failure mode of freeing the children, and the placeholder row is what
      prevents it.

- [ ] **3.3** Collapse everything, then click a colour / hide square anywhere.
      → No lag. Before, one look inside a big group made *every* later click
      pay ~190 ms for the rest of the session.

- [ ] **3.4** Expand a site, collapse the parent element while the site is
      still open, reopen both.
      → State restored, nothing stale.

- [ ] **3.5** Expand some groups, then import another file (which re-syncs the
      whole tree).
      → What was open is still open, three levels deep.

---

## 4. Outliner selection → viewport

- [ ] **4.1** Click a **site** row.
      → Those atoms outline orange in the viewport, all images together.

- [ ] **4.2** Ctrl-click a second site row.
      → Both sites highlighted — the first is not dropped.
      **Watch for:** the selection collapsing to one row on release. That was
      the original bug and it lives in the click-vs-selection ordering.

- [ ] **4.3** Shift-click a **range** of atom rows.
      → All of them highlighted.

- [ ] **4.4** Click an **element** row.
      → Every atom of that element.

- [ ] **4.5** Select several atoms this way, then press **G** in the viewport.
      → They grab and move as a group. This is the point of the whole item:
      *"editing multiple atoms very tiresome."*

- [ ] **4.6** Select atom rows on a molecule that is **not** the active one.
      → It becomes active (so Tab edits what you just selected).

---

## 5. Unit cell box z-order

- [ ] **5.1** With a dense CIF open, `F3` → **"Unit cell box (Viewport): draw
      on top / respect depth"**.
      → The box edges and the a/b/c vectors now **disappear behind** the
      framework where they pass behind it, and stay drawn where they are in
      front. The status bar says which mode you are in.

- [ ] **5.2** Toggle it back.
      → Straight back to the overlay you have always had.

- [ ] **5.3** Export a still (`Ctrl+Shift+E`, or F12) of a packed structure
      **without** touching anything — the export defaults to depth-respecting.
      → The axes no longer cut across the molecules in front of them. That is
      your original report.

- [ ] **5.4** `F3` → **"Unit cell box (Image export)…"**, set it back to on
      top, export again.
      → The old behaviour, deliberately. The two are independent — changing
      one must not move the other.

- [ ] **5.5** **The judgement call I want your eye on:** the depth-respecting
      form is a **rod** per edge (real geometry — that is what makes occlusion
      possible at all), so it gets thicker as you zoom in, the way VESTA's
      does. Look at it on a large packing and on a small cell.
      → If it reads as too heavy next to the bonds, the single number is
      `cellbox.RADIUS_FRAC` (currently 0.4% of the cell's mean edge; a 10 Å
      cell lands on 0.04 Å, which is exactly what the Blender export already
      used).

- [ ] **5.6** Restart MoloM.
      → Both choices remembered.

---

## Known and deliberate

- The **asymmetric-unit view of a solid solution** still shows stacked atoms
  rather than a pie sphere. That is the decision you just made (merge + fix
  the write-back) and it is **not built yet**.
- **`python -m pytest tests/` finishes again** — 1732 passed, 4 skipped, in
  about 110 s, in one process. It had stopped finishing at all; the causes are
  in `docs/OPEN_ITEMS.md` **J4**. One of them was a real app bug: cancelling a
  name lookup or a crystal search while it was still running could destroy a
  live worker thread. **Worth a manual go:** `Ctrl+Shift+N`, type a name,
  press Resolve, and hit Cancel before it answers — MoloM should just close
  the dialog.
