# CCDC / CSD access — scoping

Christian, 2026-09-02: "scope out integration of access to databases like
CCDC… How is verification performed? Is it a `.lic` file like in PyMOL? Does
this lead to potential risks when publishing on github?"

Nothing here is built. This is the design and the licensing position, written
before any code, the same way `docs/ISOSURFACES.md` was.

---

## 0. What is on this machine today (measured, 2026-09-02)

This is the first thing to settle, because it decides what is demonstrable.

| | |
|---|---|
| `C:\Users\chris\CCDC\` | Mercury, encifer, activation + telemetry utilities |
| `%LOCALAPPDATA%\CCDC\ApplicationServices.ini` | `[licensing_v1] is_community_feature_licensed=true` |
| `ccdc-data/` (the CSD itself) | **absent** |
| `import ccdc` / `csd_python_api` | **not installed** |

So this is **Mercury Community** — the free tier. There is no CSD database
and no CSD Python API on the machine.

**Consequence: no amount of MoloM code makes CSD data reachable from here.**
The blocker is a licence and an installation, not a feature. That is an
institutional-access step with its own lead time, and it is the long pole for
anything CSD-shaped before a presentation.

---

## 1. How verification works — and no, it is not a `.lic` file

PyMOL reads a `license.lic` file from a known path. CCDC does **not** work
that way. Licensing is an **activation key** (or a licence server), resolved
by the CCDC libraries themselves:

```
CCDC_LICENSING_CONFIGURATION=la-code;123456-123456-123456-123456-123456-123456
CCDC_LICENSING_CONFIGURATION=lf-server;http://licence-server:8080
```

`la-code` is a per-customer activation key; `lf-server` points at an
institutional licence server, which is how a department with a site licence
usually deploys it. The environment variable **overrides everything else**,
which is what makes it scriptable; otherwise the key is stored once by
`ccdc-utilities/software-activation` and found automatically thereafter.

`~/CCDC/Licenses/generic_license.txt` is *not* a key — it is the text of the
licence agreement. There is no key file for us to read.

**This is good news for MoloM.** The strongest possible position is that
**MoloM never sees the key at all**: we `import ccdc`, and the package
resolves its own licence from the environment or the activation store. We
read no key, store no key, print no key, and log no key. A credential you
never touch is a credential you cannot leak.

**So: do not build a "paste your CCDC key here" settings field.** It would put
the key in `QSettings` — the Windows registry — turn it into something
MoloM's own error paths could print, and make it the sort of thing that ends
up in a screenshot. If a user is not activated, the right response is a link
to CCDC's activation instructions, not a text box.

---

## 2. Risks when publishing on GitHub

Three separate risks. Only the first is about the key, and it is the least
dangerous of the three.

### (a) The activation key — low risk if we never touch it

Handled by §1: never read it, never store it, never echo it. The residual
risk is a user pasting a key into an issue or a log. Worth a line in the
error message: *"CCDC reports no licence"* rather than dumping the licensing
configuration.

### (b) THE DATA — the real risk, and the easy one to get wrong

**CSD structures are licensed and may not be redistributed.** This project
has already met the rule once: round 42c records that Christian's own test
set "is largely CCDC data and may not be redistributed", which is why the
vendored CIFs in `tests/data/` are COD entries and the rest of that round is
tested as rules rather than files.

Concretely, for a public repo:

- **Never vendor a CSD entry as a test fixture.** Not even a small one. Not
  even "just the cell". A CSD-derived test file in `tests/data/` is a licence
  breach in a public repo, and it is the exact mistake that is easiest to
  make while writing a reader.
- **Never cache downloaded structures anywhere inside the repo.** A cache
  belongs under the user's own data directory, and `.gitignore` is not a
  safety mechanism — the cache path should simply never be inside the tree.
- **A `.molom` savefile containing a CSD structure is redistributable only as
  far as the user's own licence allows.** Not MoloM's problem to enforce, but
  worth one sentence in the docs so nobody posts one to an issue tracker
  assuming it is like a `.xyz`.
- **Screenshots for the README are covered by the same terms.** The existing
  `docs/screenshots/` are Christian's own structures and COD entries; keep it
  that way.

### (c) The package itself

Importing `ccdc` in MoloM's source is fine — an import is not
redistribution. Bundling any part of the CCDC package, a wheel, or the
conda channel is not fine, and there is no reason to: the API is installed
from CCDC's own pip repository or the local conda channel that ships with
the CSD Portfolio, never from PyPI. So it can never be a `pyproject`
dependency, not even an optional one — it has to be discovered at runtime.

---

## 3. The architecture — it is a tier, and it lives in an add-on

This fits what already exists, and needs almost no new invention.

`core/cifsearch.py` (round 84) already runs its providers **concurrently**
and merges, dedupes and ranks the results itself, precisely because a crystal
name has many right answers and every tier may hold part of the set. Its
failure model is already the right one: **a dead tier costs a tier, never the
answer.** A CSD provider is one more tier.

Two rules from earlier rounds settle where the code goes:

- **Round 73 (MOPAC):** core gets a *registry* and a signature; every line
  that knows what the vendor is lives in `molom/addons/`. Core does not
  import it, does not know it exists, and disabling the add-on leaves core
  exactly the module it was.
- **Round 84:** a downloaded structure takes **the same path a file on disk
  does** — written to a temp file and opened — so the packed import, the
  disorder policy, the symmetry derivation and every report ride along. A
  second, subtly different import path for one provider is exactly the drift
  this project keeps finding.

That second rule makes the integration surface tiny, because the CSD Python
API hands out CIF text directly:

```python
# molom/addons/csd_search.py  — sketch, not built
from ccdc.search import TextNumericSearch      # only inside the add-on
from ccdc import io

def search(query, limit):
    hits = []
    s = TextNumericSearch()
    s.add_compound_name(query)
    for hit in s.search()[:limit]:
        entry = hit.entry
        hits.append(Hit(source="CSD", ref=entry.identifier,
                        name=entry.chemical_name,
                        formula=entry.formula,
                        cif=entry.crystal.to_string("cif")))
    return hits
```

`entry.crystal.to_string("cif")` is the whole bridge. Everything downstream —
`core/cif.py`, the packing, the polyhedra, the PXRD window — is unchanged.

**Registration is conditional on the licence, not on the import.** A machine
can have `ccdc` installed and no valid licence, and the failure then happens
on the first search rather than at import. So the add-on should probe once
(cheaply, e.g. one trivial search or `io.EntryReader('CSD')`) and register
the tier only if that succeeds — otherwise the search dialog grows a tier
that is guaranteed to fail, which is worse than not having it.

**Tests can have no fixture.** By §2(b) there can be no vendored CSD entry,
so the tests are: the provider is absent when `ccdc` is absent; the provider
is absent when the licence probe fails; a `Hit` built from a synthetic
CIF string flows through the normal import path. Live tests skip where the
API is not installed — the same arrangement `test_round100_measured.py`
already uses for the sibling diffraction suite.

---

## 4. What this means for a presentation that is soon

Being straight about it: **the CSD tier cannot be demonstrated on this
machine, and the blocker is not code.** It needs, in order:

1. a CSD licence — TU Dortmund very likely has a site licence; what is
   needed is the customer number and activation key (or the licence server
   address) from whoever administers it;
2. the CSD Portfolio installed **including the database** (tens of GB) and
   the CSD Python API, which is a separate component;
3. activation.

Steps 1–3 are institutional and none of them is under our control.

### What *is* buildable now, and demos the same idea

- **Build the provider architecture and the CSD tier anyway.** It is a small
  amount of code, it is testable without a licence, and it means the feature
  is genuinely "ready for licensed users" rather than promised. The search
  dialog then shows a CSD tier the moment a licensed machine runs it.
- **Demo the tier mechanism against COD**, which works today and already
  returns real hits. The honest framing for a slide is "three sources today,
  and CSD drops in where a group has the licence" — which is true, and is a
  better claim than a live CSD search that depends on a licence server being
  up in the lecture theatre.
- **Hand off to Mercury**, which *is* installed here. MoloM already has the
  program-slot pattern from ORCA Workbench (`viewer_3d_path` /
  `editor_3d_path`, round 92); pointing one at Mercury and adding "open this
  structure in Mercury" is an afternoon and works on this machine today.

### One thing deliberately NOT proposed

**Access Structures** is CCDC's free service and is the obvious-looking
shortcut. It is not one: a download requires reading and accepting the
conditions of use interactively before the button becomes live. Automating
that acceptance is circumventing a term of use, not a technical obstacle to
route around, so MoloM should not do it. Linking a user *out* to Access
Structures for a deposition number is fine and costs nothing.

---

## 4b. Does a `.molom` savefile carrying CSD structures matter? YES

Christian asked, 2026-09-03. The rule is explicit and it is the one in
§2(b), stated by CCDC itself:

> "The licence does not allow external sharing of original data from the CSD,
> such as making bulk CIF files available to others outside your
> organization."

and separately, software or data **derived from** the CSD Portfolio may not
be distributed without CCDC's prior written approval.

So, concretely:

- keeping a `.molom` with CSD structures in it, and working with it, is
  ordinary licensed use;
- **sending one outside AG Henke is sharing CSD data**, whatever the file
  extension says. A savefile is not a neutral container - it holds the
  coordinates.
- posting one to a public issue tracker, or committing one to this repo as a
  test fixture, is the same thing in a more permanent form.

**Where it is genuinely ambiguous, and worth asking rather than assuming:**

1. **What counts as "bulk"?** CCDC does not quantify it. One structure in a
   figure is plainly fine; a savefile with forty is not obviously either way.
2. **Is a savefile "original data" or "derived data"?** The two have
   different rules - original may not be shared at all, derived *may* be
   permitted or may need a separate agreement - and a `.molom` holds the
   coordinates verbatim, which argues for the first.
3. **Does an edited structure change the answer?** A demoted, re-packed,
   element-substituted cell is arguably a derived work, and arguably still
   the CSD's coordinates.

**Where to write:** CCDC's own route is a support ticket at
<https://support.ccdc.cam.ac.uk/support/tickets/new>. Worth doing with the
site licence's customer number to hand, because the terms vary per licence
and only CCDC can say what AG Henke's allows.

**What MoloM could do about it, NOT built and wanting a decision:** mark
structures that came from a licensed source in the savefile, and warn on
save or on export. That is a small feature and a real decision - it puts a
dialog in front of an ordinary action - so it is recorded rather than
assumed.

## 5. What IS built: the key hole, with no key in it

Round 102b. `core/cifsearch.register_provider(key, label, search_fn)` is the
extension point a CSD tier would use, plus `unregister_provider` and
`extra_providers`. A registered tier runs in the concurrent fan-out beside
the local, COD and OPTIMADE ones, is ranked and deduped with them, and a
failure costs a tier rather than the search (round 37).

`search_fn(query, formula=..., limit=..., timeout=...)` returns `Hit`s. A
`Hit` carrying CIF text flows into the ordinary import path, so nothing
downstream needs to know where it came from.

**Nothing about CCDC is in `core/`, and a test asserts it** - no module
under `molom/core/` may import `ccdc`. The remaining piece is
`molom/addons/csd_search.py`, which is where the licence probe and the
actual API calls belong, and it is deliberately unwritten: it cannot be run
or tested on this machine, and an untested API-call layer is the "mechanism
with tests and no gesture test" trap this project keeps finding (round 59).

Registration must be conditional on the tier being USABLE - an installed
`ccdc` with no valid licence would otherwise put a row in the dialog that is
guaranteed to fail, which is worse than not offering it.

## 6. Open questions for Christian

1. **Does AG Henke have a CSD site licence, and is it a key or a licence
   server?** That decides whether §1's `la-code` or `lf-server` form is the
   one to document, and whether step 1 above is a phone call or a purchase.
2. **Is the Python API part of the site licence?** It is a separate component
   of the CSD Portfolio and is not always deployed with Mercury.
3. **Is the search the point, or the data?** A substructure or similarity
   search over the CSD is a much bigger feature than "fetch this refcode",
   and only the first really needs the Python API — a refcode you already
   know can be opened from a local CIF today.
4. **Would ICSD matter too?** Same licensing shape, different vendor,
   inorganic rather than organic — and AG Henke being a framework group, it
   may be the more useful of the two. Worth deciding before the provider
   interface is fixed.

## Sources

- <https://support.ccdc.cam.ac.uk/support/solutions/articles/103000306179-how-do-i-activate-the-software-for-all-users->
- <https://support.ccdc.cam.ac.uk/support/solutions/articles/103000305955-activating-the-csd-python-api>
- <https://downloads.ccdc.cam.ac.uk/documentation/API/installation_notes.html>
- <https://support.ccdc.cam.ac.uk/support/solutions/articles/103000306188-how-do-i-download-cifs-from-the-access-structures-service->
- <https://www.ccdc.cam.ac.uk/solutions/software/csd-python/>
