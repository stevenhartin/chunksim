# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**This file holds only what spans modules or cannot be discovered from them.** Every module's own
rationale — what it ports, what it approximates, what it refuses to guess at, and the measurements
behind each — lives in its **module docstring**, next to the code it constrains. Those docstrings are
long, current, and are the real documentation: **read the module's docstring before trusting its
numbers or changing its behaviour.** This file is a map to them, not a substitute, and anything that
can live in one belongs there instead of here.

## Project

chunksim is a CLI that reads state from the source-chunk web app, caches it locally, and runs
offline operations on that cache. source-chunk is upstream and read-only from here.

**Two apps, one distribution.** `chunksim` is the CLI; `chunksim-gui` is a local server plus a browser
front-end that draws the world map. The library both use is eight subpackages, and there is
deliberately **no `core/` and no second distribution** — three pyprojects would buy independent
versioning nobody needs, and a subpackage can be lifted out on the day someone wants to reuse it.

```
src/chunksim/
  model/    what upstream's data *is*, before anything is derived from it
  remote/   the only outbound network calls
  store/    the only disk
  derive/   the pure layer: the derivation chain and everything that walks it
  costing/  derivation -> hours, and the optional seam to osrs-dps
  runs/     what a *run* is: a base state, a sequence of rolls, its replay
  cli/      one module per subcommand family, parser beside handler
  gui/      the server, split by what each route costs
```

Each directory's `__init__.py` carries the rule that holds across it **and one entry per module
saying what that module owns** — and no code: no re-exports, which would rebuild the god-module this
layout replaced and put "which tests do I run" back to "all of them". The single exception is
`cli/__init__.py`, which re-exports `main` because `[project.scripts]` names `chunksim.cli:main`.
**Those eight docstrings are the directory of this project** — the map from "what am I looking for"
to "which file".

Planned: a shortest-path search ("fewest chunk unlocks to reach X"). `derive/graph.py` is shaped for
it but is **not** speculative — it is the substrate two ported upstream passes already run on
(`findConnectedSections` in `sections.py`, `selectAllNeighborsCanvas` in `neighbours.py`), and
`runs/simulate.py` builds one too. Treat it as load-bearing, not as scaffolding for the unwritten.

## source-chunk

- Source: https://github.com/source-chunk/chunk-picker-v2/
- Live instance, the only one that matters: https://source-chunk.github.io/chunk-picker-v2/?<map-id>

It imposes an artificial rule set on Old School RuneScape by adding barriers to the world: it holds
the set of chosen chunks, tracks goals for the active chunk, and randomly selects the next chunk to
unlock from the allowed neighbours. Reproducing that selection and the neighbour-eligibility rules is
the core of this tool — **read the upstream source for them rather than inferring from observed
output.** Module docstrings cite `worker.js`/`index.js` line numbers throughout.

**Chunk** — a fixed square block of tiles; the unit source-chunk unlocks.
**Tile** — the smallest interactable square; the avatar occupies one at a time.
**Section** — a chunk may be split into numbered sub-areas; unlocking a chunk only makes section `0`
reachable, not the rest (`derive/sections.py`).

`?<map-id>` is a map ID, not page state — the real backend is a public Firebase Realtime Database, read
with a plain unauthenticated GET: `https://chunkpicker.firebaseio.com/maps/<map_id>.json`. Chunk
adjacency/neighbour data isn't there; it's `chunkpicker-chunkinfo-export.json` in the upstream repo,
served from the **`gh-pages`** branch — that's upstream's default branch, and `main` 404s.

**Map payload strings and keys are selectively passed through a reversible Firebase-safe encoding**,
applied per-field by the app rather than uniformly across the payload — so **which branches need
`firebase.decode_payload` is only knowable by checking real fetched data**, not by inspecting the
client source. Some fields also intern task names to `t_N` ids, and **a single category can mix ids
and literal names**, which has already caused one real bug from a small sample that looked
literal-only. `model/firebase.py`'s docstring is the authority on all of it. **Run any payload branch
through it before believing it.**

## Architecture

One responsibility per module, so the simulation work has a pure layer to build on.
**`remote/api.py` is the only module that makes *outbound* network calls and `store/cache.py` the
only one that touches disk; everything else is pure.** `gui/server.py` is the one exception in each
direction and neither weakens the rule: it is the only module that **accepts inbound** connections,
binding loopback unless `--host` says otherwise, and the only disk it touches beyond `cache.py` is
its own packaged read-only resources.

The derivation chain is `sections` -> `sources` -> `challenges` -> `bis` ->
`active_tasks`/`other_tasks` (all in `derive/`), wired by `derive/pipeline.py`'s `derive` and reached
by every subcommand through it. **This is a deliberately partial reimplementation of upstream's own
logic**, and it **refuses rather than approximates** — unported behaviour raises rather than
returning a plausible number.

### Rules that cut across modules

Each of the first three has already caused a real bug.

- **Reachable items are `ChallengeResult.available_items`, not `SourceIndex.items`.** The latter
  omits anything obtainable only by *making* it. `bis.py`, `boosts.py` and `estimate.py` each got
  this wrong independently. **The same goes for objects**: `ChallengeResult.available_objects`, not
  `SourceIndex.objects`, since `Output Object` is seeded.
- **The opt-in oracle tests are the correctness signal.** The cached map records upstream's own
  computed answers (`activeTasks.BiS`, `activeTasks.Slayer`, …) and the tests assert against them.
  **Treat a mismatch as a defect in this code, not as oracle staleness** — an earlier stage of this
  project explained five real bugs away that way.
- **Task names are markup-bearing keys.** The raw `~|...|~` form is the key everywhere (`valid`,
  ledger lookups, `--export-json`); `derive/task_names.strip_task_markup` is display-only and applies
  to challenge/task names *only* — other branches use `~` and `|` for real.
- **The cached map does not contain the derivation — don't try to read it instead of computing.**
  `chunkinfo.activeTasks` holds ~49 UI-facing answers against the ~2,700 valid tasks this project
  computes, and the payload has no sections, sources or validity branches at all. That is exactly
  what makes those few entries oracles. `completedChallenges` is the player's ticked list, an
  *input*. What `cache/derived/` avoids is computing the derivation *twice*, which is the real
  version of this optimisation.
- **The pure layer must stay process-parallel, so there is no module-level mutable state anywhere** —
  no `lru_cache`, no module-level memo dicts, no globals; `MapState`/`Derived` are frozen. `chunksim
  simulate --jobs N` and `runs/batch.price_steps` both depend on it, and a cache added to a "pure"
  module would break `--jobs` silently, as runs that disagree. `cache/derived/` is content-keyed, so
  two workers racing on one key write identical bytes and the atomic rename makes either winner
  correct.

  **The rule is about *module* scope, and caching within one call is how the hot paths are fast.**
  Four shapes are sanctioned, in increasing scope: a `cached_property` or dict on a frozen bundle
  built per call and passed down (`costing/estimate.py`'s `_Walk`); a dict captured by a closure
  (`estimate.material_seconds`); a previous result passed in *and* returned, never stored
  (`dps_bridge.PricedFights`); and content-keyed disk (`store/derived_cache.py`). All four die with
  the call or travel as data, so a worker cannot inherit one. The test is not "is there a dict" but
  "could two processes see different contents" — and where a memo outlives a request, as the GUI's
  `ReferenceBlobs` does, it must be validated against what it caches rather than merely remembered.

### Costing: how a number gets chosen

`chunksim estimate` turns the derivation into hours. **The export carries no durations, rates or XP
figures at all**, so every number spent comes from a scrape, a wiki recipe, a model in `costing/`, or
a default in `costing/heuristics.py`. That subpackage is 98 modules, most of them one activity or
one mechanic each; **their docstrings carry the measurements, the checks and the refusals, and this
file deliberately does not repeat them.** What follows is only what holds across all of them.

**The ordering is `defaults < scraped < computed (recipe) < modelled (gathering) < overrides`**, and
the rule behind it is that a number this project computed beats a number somebody published. **A
guide is evidence about the action; a model is evidence about the action plus the map** — a guide
assumes the materials are to hand, where a chunk map may have to make them.
`training.effective_xp_per_hour` is where that bites: it charges a method for the time to obtain what
it consumes and credits it for experience the gathering pays *in the same skill*. **Both halves or
neither** — charging without crediting and crediting without charging are both wrong, and
`tests/test_training.py` pins the worked case.

- **A join that misses does not read as a gap; it reads as a fast method.** An uncharged twin of a
  charged method outranks it, and nothing in the output says so. This is the single most productive
  bug shape in the costing layer; suspect it whenever a rate looks good.
- **An ambiguous join may fill the floor but may not replace the scrape.** A recipe that cannot say
  which of several tasks it describes is not evidence against a rate that names one.
- **A rate is a curve, not a number.** `Heuristics.computed` carries a level per entry and
  `training_bands` opens each band where it belongs, taking a running **maximum** — so a slow method
  decides a climb only where it is the only one, which is why there is no floor filtering slow rates
  out any more.
- **One invented factor makes the product invented.** Any model spending a constant nobody published
  reports `GUESS`, however well-published the rest of its terms are. A figure that is arithmetic
  rather than agreement (one parameter fitted to one observation) is worth no more than the
  observation, and the docstring has to say so.
- **A ceiling is said rather than hidden.** Where the model computes the best case the mechanic
  allows, the docstring calls it a ceiling and explains what is unmodelled.
- **The item walk is a fixpoint over a table, with no depth bound.** A route closing on a key still
  on the stack reads last round's answer, so **a cycle is a discarded path, never a discarded item**;
  positive costs guarantee convergence. Every depth bound this ever had was a work-around for cost
  and distorted real chains. Beware fractional quantities as fixpoint keys — they dedup against
  nothing and blow the memo up.
- **Hand alias tables run in two directions across two vocabularies, and conflating them searches the
  wrong dictionary.** One takes an export name to a wiki title so a challenge can find its recipe;
  the other takes a recipe's own material to an export name so the item walk can find a route.
- **Check whether the wiki is silent before writing down what it should have said.** More than one
  hand table has been retired within the hour by a query shape that reached the data.
- **The modelled layer does not make the scrape redundant.** The model prices a node, a roll and a
  chance; the activities only the scrape reaches (Wintertodt, Forestry, shooting stars, Pyramid
  Plunder) have none of the three. `tests/test_costing_gathering.TestTheScrapeIsNotRedundant` pins
  this per skill so a later "these look superseded" cannot pass review as a tidy-up.
- **A published figure is often better used as an oracle than as a source.** Where a model reproduces
  a scraped row from its components, assert the two against each other and the day upstream moves a
  number the suite fails instead of the two silently drifting.

**Every wiki fetch is a developer command that writes into `src/`, and the estimator never reaches
one.** `chunksim heuristics`, `chunksim recipes` and `chunksim gather-tables` write checked-in blobs
under `src/chunksim/heuristics/`; `chunksim estimate` reads them and makes no network call.
`cache.SHIPPED_BLOB_NAMES` is the list, `blob_write_path` is where a developer command writes and
`blob_source` what a reader opens — but **it names five of the seven shipped files**: `gathering.json`
and `overrides.json` predate it and keep their own `PACKAGED_GATHERING`/`PACKAGED_OVERRIDES` pair, so
grepping that tuple for either finds nothing and concludes wrongly that it does not ship.
**A checkout is a closed world in `blob_source`** — reaching past an empty test fixture tree to the
packaged file made three simulate tests derive against rates they were never given.
`tests/test_packaging.py` pins that a cache holding no wiki data at all still prices every method
identically.

### Reading the coverage report

`chunksim training` without `--map` asks about the *export* rather than a world: how many of its
~2,700 primary methods are `modelled`, `pinned`, `published`, `guess`, `unpriced`, `refused`,
`one-off`, `uncompletable` or `unreachable` (`costing/coverage.py`). The statuses each mean one
thing, and keeping them apart is what makes the report worth reading:

- **`unpriced` means "somebody should go and close this"** and nothing else,
  and the export currently has none - every one of its ~2,700 primary methods
  carries a real status. A new one appearing is a game update this project has
  not caught up with, not a backlog. A method a model
  declines *by name* is `refused`, carried with the deciding module's own sentence; a thing nobody
  trains with (a trophy mount, a one-slot upgrade) is `one-off`. `one_off` is checked **ahead** of
  every priced tier because such a method usually does have an arithmetic rate; `refused` is checked
  **last**, so the day somebody finds the missing mechanic the model wins and the refusal goes quiet
  with nothing edited.
- **`uncompletable` and `unreachable` are one test asked of two worlds.** A method *this map* cannot
  do is the ordinary condition of a chunk map; one the **ceiling** cannot do — every rollable chunk
  unlocked — says no player could ever perform it, so the report names it differently and says why
  per row (`coverage.blocker_for`). The order the branches are tried in is what stops it naming
  symptoms.
- **Unreachable is checked before every priced status, including a pin.** Every computed layer walks
  the derivation's `valid` set, so an unreachable challenge is never offered to one and keeps
  whatever the raw scrape left behind. Counted as `published` that would claim a guide decides the
  method, when the truth is that nothing here was ever asked.
- **`--rules-from MAP` is not optional in practice.** With no rules borrowed, every rule-gated
  challenge fails a gate `coverage.blocker_for` cannot name and the counts are a different, much
  emptier answer rather than a smaller one. The report warns when it happens.
- **`--show-category STATUS` turns any count back into its list**, matched case-insensitively against
  the names the table prints; a miss names the valid values and exits `2`.

### Test against more than one map

Every rule in a map's `rules` branch is a number or a flag a *player* set, so **a second map is a
second set of inputs rather than more of the same data** — 41 of the first map's 104 rules are off,
and each is a stretch of upstream nothing here could otherwise see. A second real map alone found
three defects, including a `0` reaching a ratio parser as `"1/0"` (JS yields `Infinity` and raises
nothing; Python disagreed) and two unported BiS rules. The BiS, `Diary`/`Extra` and per-skill oracles
all run over **every fetched map in the cache**, so `chunksim fetch --map <other>` is the cheapest
way to widen the signal. Each map's residual disagreement is pinned by *name* in
`tests/test_other_tasks._KNOWN_ORACLE_DELTA`, and a map with no entry there fails rather than quietly
widening what the suite asserts.

The GUI's undocumented `__UBER__` fetch (`gui/actions.py`) builds a map holding every **rollable**
chunk on top of whichever map is open — the ceiling the docstrings' measurements are quoted against.
**Rollable is `chunkinfo['sections']`, not `chunkinfo['chunks']`**: 1,172 of the export's 2,234, the
rest being unwalkable squares and named areas a roll can never land on.

### Where things live

**What each individual module owns lives in its subpackage's `__init__.py`**, as one entry per
module, and that is where a new module's entry goes too. Read the `__init__` before working
anywhere in the directory; this file names only the eight.

| Subpackage | What it is, and the rule it carries |
|---|---|
| `model/` | Upstream's data as typed, tolerant accessors, the Firebase wire codec, and the two exact vocabularies — drop-rate strings and the XP curve. **Imports from no other subpackage**, so it is the one to read first and then stop thinking about. |
| `remote/` | Every outbound call, and every wikitext parser reading what comes back. **`api.py` is the only module in the project that opens an outbound connection** — one directory to grep for `urlopen` rather than an honour system. |
| `store/` | Every disk touch: `cache/`'s layout and envelope, the content-keyed derived cache, and this install's own metadata. Holds the one **upward** edge in the layering, because a store of results has to know their shape. |
| `derive/` | The derivation chain and everything that walks or diffs it. **No module-level mutable state** — `--jobs N` runs them in worker processes, and a cache here breaks that as runs that disagree. |
| `costing/` | Derivation -> hours: the rate layers, the item walk, and the per-skill models. **`dps_bridge.py` is the only module that may import `osrs_dps`**, and the extra must stay optional. |
| `runs/` | What a run is: a base state, its rolls, its replay. **A run is self-contained** — stepping one needs no base map, no export and no `derive`. |
| `cli/` | One module per subcommand family, `add_parser` beside handler, so a flag change edits one file. The only `__init__` carrying code, because `[project.scripts]` names `chunksim.cli:main`. |
| `gui/` | The local server and the browser front end, split by **what each route costs**: `routes_view.py` answers without parsing the export and `routes_derived.py` may not. `resources/` is the front end itself. |

### Two constraints on the GUI worth knowing before editing it

**Panels heal themselves; nothing tells them to.** `poll` compares two tokens from `/api/revision`:
`data`, a stamp over the files an answer is computed from (`cache.data_stamp`), and `revision`, the
map's own mtime. Watching only the second was a real bug — the map file does not move when the export
arrives. **Do not fix a stale panel by calling `reloadPanels` from wherever the data changed**; that
is the pattern this replaced, and the number of places needing it is the problem.

- **The map is the OSRS wiki's cartography tiles and the browser loads them — this project never
  touches one.** `/api/tiles` hands out a URL *template*. That is a **licence decision, not an
  optimisation**: the tiles are CC BY-NC-SA 3.0 against this project's GPL-3.0, so caching them under
  `cache/` or re-serving them off loopback would make this a redistributor of NonCommercial artwork,
  where linking makes it a page with a picture on it. `tests/test_gui_contract.py` asserts no tile
  route exists, so a later "let's cache these" cannot pass review by looking like a speed-up.
- **One vocabulary for how near a chunk is, everywhere.** `data-hold` is `unlocked` / `reachable` /
  `locked`, and the Find icons, the chunk pills, the section pills and the chunk cards all speak it:
  green a square you hold, blue one you can walk into without rolling it, grey neither. **A reachable
  chunk offers no unlock**, because it costs no roll and never appears among the candidates.

**Constants crossing into JavaScript have nothing enforcing agreement**, so
`tests/test_gui_contract.py` reads `app.js` and asserts them against the Python. It also pins the
interface rules that each replaced a bug (one tooltip system; chip strips record what is *off*; no
`raw()` interpolation inside an attribute) and that every length in `style.css` — **font size
included** — comes from the one scale. `app.js` is heavily commented and is where the front end's
rationale lives.

## Toolchain

Python 3.14.7, mypy, pip (no uv). Run `mypy` and `.venv/bin/pytest` before each commit.

**Zero *required* runtime dependencies, deliberately** — `pyproject.toml` has an empty
`dependencies`, so a new module gets the stdlib and nothing else. `store/derived_cache.py` is the
shape that keeps to: it wanted zstd and got it from 3.14's stdlib (PEP 784) rather than PyPI, and
still degrades to plain pickle on a CPython built without `_zstd`.

There are two extras and they are not alike. `dev` is `pytest`. **`dps` is
[`osrs-dps`](https://github.com/stevenhartin/osrs-dps), and it must stay optional** — it is a package
a user installs deliberately, never vendored in, and `costing/dps_bridge.py` is the only module that
may import it, behind a `try`/`except ImportError` that sets `DPS_AVAILABLE`. Importing `dps_bridge`
is always safe; calling into it without the extra raises `DpsUnavailableError`, and its tests skip
rather than fail. Both projects are GPL-3.0-or-later, so they may ship as one work. A change to
`osrs-dps` that moves a number is a change to `chunksim estimate`'s answers, so run both suites.

`mypy` and `pytest` are invoked differently on purpose: **mypy is the *system* install** (there is no
`.venv/bin/mypy`), configured with `python_executable = ".venv/bin/python"` so it can see pytest's
stubs — which is why it must run from the repo root and needs the venv to exist. **pytest is only a
`dev` extra inside the venv and is not on `PATH`**, so a bare `pytest` fails with "command not
found".

## Commands

```
pip install -e ".[dev]"     # editable install into .venv; provides the `chunksim` script
chunksim fetch --map ID         # GET live state -> cache/maps/fetched/<map>.json
chunksim show  [--map ID]       # summarise the cached copy; no network
chunksim chunkinfo              # GET upstream's chunk/challenge reference data (~10MB)
chunksim heuristics             # developer only: rates -> src/chunksim/heuristics/wiki_rates.json (30+ requests)
                                # + the courier task table -> .../courier_tasks.json
                                # + the bounty table and sea monster hp -> .../bounty_tasks.json
chunksim recipes [--chunkinfo P] # developer only: per-action xp + ticks -> .../wiki_recipes.json
                                # + the wiki's renames -> .../wiki_aliases.json
chunksim gather-tables          # developer only: GET the gathering tables -> src/chunksim/heuristics/gathering.json
chunksim estimate [BUCKET] [--limit N]                 # rough hours for the outstanding active tasks
chunksim training [SKILL] [--map ID] [--rules-from MAP] [--show-category STATUS] # what trains each skill, and what priced it
chunksim sections [list|CHUNK] [--limit N]             # reachable sections
chunksim sources  [CATEGORY]   [--limit N]             # items/objects/monsters/npcs/shops
chunksim tasks    [CATEGORY]   [--limit N]             # valid/active/obsolete/completed, incl. BiS
chunksim unlock   --chunk ID [--cache-map NAME]        # what one candidate chunk would add
chunksim diff --map1 A --map2 B [BRANCH] [--limit N]   # symmetric comparison of two cached maps
chunksim neighbours [--limit N]                        # chunks eligible to unlock next
chunksim simulate --rolls N [--seed S] [--cache-map NAME] [--runs R] [--jobs J]
              [--cache-behaviour all|extremities|none] [--no-carry-areas]
chunksim maps [list [--runs]] | maps rm NAME... [--include-fetched] | maps clean [--include-fetched]
chunksim derived [list [--verbose]] | derived clean [--older-than DAYS] [--all]
chunksim search   QUERY [--type T ...] [--limit N]
python -m chunksim ...    # same CLI without the console script
chunksim-gui [--map ID] [--compare ID] [--port N] [--host H] [--allow-host H] [--keep-alive]
         [--no-browser] [--tab] [--timeout S]
mypy                         # strict, over src/ and tests/; run from the repo root
.venv/bin/pytest             # whole suite
```

Env vars: `CHUNKSIM_CACHE` (the directory `cache/` is made under), `CHUNKSIM_CHUNKINFO` (an export, or
`chunksim chunkinfo`'s envelope around one), `CHUNKSIM_MAP_CACHE` (presence-only),
`CHUNKSIM_SLOW_ORACLES` (presence-only), `CHUNKSIM_NO_WATERMARK`, `CHUNKSIM_TILE_VERSION`,
`CHUNKSIM_GUI_VERBOSE`.

**`chunksim training` is the one subcommand where omitting `--map` asks a different question** rather
than defaulting one, which is why it sets `infer_map=False` and why `cli/app.main` has a hook for
that. See *Reading the coverage report* above.

**Flag conventions, so each means one thing everywhere.** `--export-json PATH` (or `-` for stdout) and
`--recompute` are carried by the nine *derivation* subcommands and nothing else (`--export-json` also
by `maps list`), not by the five I/O ones. `--limit` defaults to `None` — full output, so piping just
works — except for `search`, where it is `10`. **`--map ID` is carried by every subcommand that reads a
cached map**, so the usage lines above name it only where the map *is* the point; `chunksim diff` is the
one taking two, hence `--map1`/`--map2`, and it reports **both directions**, which `chunksim unlock`
deliberately does not. **`--chunkinfo PATH` is the per-invocation form of `CHUNKSIM_CHUNKINFO`** and rides
along on all ten subcommands that parse the export — plus `chunksim recipes`, which reads one for a
different reason: to ask the wiki which of upstream's item names it has since renamed.

**`cache/` is sorted by purpose, and `cache/maps/` holds maps and nothing else holds maps.** That
sentence is the layout's whole point: `list_maps` used to glob `cache/*.json` and skip the names it
*knew* were not maps, so every new blob had to be remembered or it turned up in the picker as a map
that failed the moment it was chosen. A directory cannot be forgotten.

```
cache/maps/fetched/<id>.json       # from Firebase; only `chunksim fetch` writes one
cache/maps/simulated/<batch>/…     # rolled by `chunksim simulate`
cache/maps/edited/<batch>/…        # made by hand: `chunksim unlock --cache-map`, or the GUI
cache/reference/                   # chunkinfo, tasks_map, tile_version
                                   # (the wiki blobs live in src/chunksim/heuristics/)
cache/derived/                     # pipeline.derive + dps_bridge.enrich results, keyed by content
cache/overrides/<map_id>.json      # heuristic corrections belonging to one map
cache/players/<map_id>.json        # the account a map is linked to, and any xp set by hand
cache/assets/                      # section masks, skill icons, CA tier icons
cache/gui/                         # window.json, settings.json, and the browser profile
```

A batch of any computed kind holds `batch.json` (seeds, rolls, `batch_id`, and the payload it rolled
from) beside one directory per run holding `map.json`, `rolls.json`, `run.json` and `timeline.json`.
**A name is claimed across every kind**, so `--map foo` never has to guess which directory meant it.

**The two sidecars are addressed by map id rather than stored beside the map, and both follow it.**
`cache/overrides/` and `cache/players/` are keyed by name, so a map made from another inherits its
player file at creation (`cache.copy_player`, never overwriting) and removing a map takes both with
it — a name is reclaimable, and a re-rolled batch inheriting the deleted one's account is a map
priced against a person nothing on screen names. **A run reads its batch's player file** rather than
one per run directory, so linking an account on a batch relinks all forty of its futures at once;
`cache.player_source` is the one place that chain is walked, and `derived_cache.pricing_digests`
walks it too or a fresh link serves back the answer computed at the floor.
**Where `cache/` itself lands is `data_root`'s answer, and it is three answers in order**:
`CHUNKSIM_CACHE` if set; else the checkout you are standing in; else the user's own data directory
(`%LOCALAPPDATA%\chunksim`, `~/Library/Application Support/chunksim`, `~/.local/share/chunksim`).
The middle one needs **`pyproject.toml` *and* `src/chunksim/`** — `pyproject.toml` alone is any Python
project, and an installed `chunksim` run from inside one must not decide that project is its home.

`cache/` is gitignored, so a fresh clone has no data until `chunksim fetch`/`chunksim chunkinfo` run — and
so is `/*.json` at the repo root, which is where `--export-json` output lands when it is aimed at
the checkout rather than `/tmp` or stdout. A stray `tasks.json` there is that, not project data.

**The estimator's numbers are all checked in and shipped, and only one layer is in `cache/`.**
`src/chunksim/heuristics/` holds the scrapes — `wiki_rates.json`, `wiki_recipes.json`,
`wiki_aliases.json`, `courier_tasks.json`, `bounty_tasks.json` and `gathering.json` — beside `overrides.json`, the hand
corrections, so a correction is diffable and survives a re-scrape. Corrections belonging to *one map*
go in `cache/overrides/<map_id>.json`, which is gitignored with the rest. `cache.SHIPPED_BLOB_NAMES`
is the list a developer command writes and a reader opens. **The guide to which numbers are worth
correcting is `heuristics/README.md` at the *repo root*, not beside the blobs** — that directory holds
nothing else, and `src/chunksim/heuristics/` holds no README.

The merge is `defaults < scraped < overrides < map overrides`, and it happens **once**, in
`load_reference` — so `ReferenceBlobs.overrides` is the *effective* set and every downstream reader
gets the fourth layer without being told about it. A `ReferenceBlobs` is therefore about one map,
which is why `map_id` is on it and why the GUI memoises one per map. **Both apps must pass the map id
or neither should**: `costing/inputs.py` exists because `chunksim estimate` and the Estimate tab had
already drifted once, and a layer one of them applied would be that drift again in the hardest place
to see.

**`User-Agent` differs by host, deliberately.** Firebase and GitHub get none — those endpoints are
public and unauthenticated, so a header would only publish information nobody asked for. The **OSRS
wiki gets `api.WIKI_USER_AGENT` and requires it**: an anonymous request there is answered with HTTP
403 (measured). One principle — send what the endpoint needs to serve the request and nothing more
about who is asking. The header names the project and its repo, never the user.

### Installing, and the one rebuild loop left

```
pipx install --force --editable .                    # once, not per change
pip install -e ../osrs-dps                           # the optional dps extra, into .venv
(cd ../osrs-dps && pyproject-build) && pipx inject --force chunksim ../osrs-dps/dist/osrs_dps-*.whl
```

**`chunksim` on `PATH` is an editable install, so there is nothing to rebuild** — a Python edit is live
immediately, and so is a `gui/resources/` edit, since `RESOURCE_DIR` is `__file__`-relative and
resolves into the checkout. Editing the front end is edit → reload the tab. **The cost is that the
checkout is load-bearing**: move or delete it and both commands break. And one failure mode moves
rather than disappearing — a new subdirectory without an `__init__.py` imports fine here and is
silently absent from any wheel built later, which is what `tests/test_packaging.py` catches.

**The `dps` extra is installed two different ways, one per venv**, and both are needed: `.venv` is
what `pytest`/`mypy` see, pipx's own venv is what the `chunksim` on `PATH` sees. An injected package
survives `pipx install --force` (both measured), but `inject` *copies* a wheel — so a change to
`osrs-dps` needs a rebuild and a re-inject, and `--force` is required because the version does not
move between builds, which makes a plain `inject` a silent no-op.

`pyproject-build` is **not part of the development loop.** Three reasons left to build a wheel:
shipping to another machine, proving the packaged `gui/resources` shipped
(`python -m zipfile -l dist/*.whl | grep resources`), and checking `packages.find` still discovers
every subpackage — the third of which `tests/test_packaging.py` covers in milliseconds.

## Packaging for Windows

`packaging/build_windows.py` assembles a payload; `packaging/chunksim.iss` turns it into an
installer. Both are built artefacts under `packaging/build/`, which is gitignored.

```
packaging\build.bat                                    # asks for a version, then builds
packaging\build.bat /version 0.2.0                     # bump without asking
packaging\build.bat /keep                              # build what is there, no bump
packaging\build.bat /nodps                             # without the DPS calculator
packaging\build.bat /payload                           # stop before Inno Setup

pyproject-build && python packaging/build_windows.py   # the same, by hand
iscc packaging/chunksim.iss                            # -> packaging/build/chunksim-<v>-setup.exe
```

**A release is a version in two files.** `pyproject.toml` is what the running program calls itself
and `chunksim.iss` is what the installer does; `packaging/set_version.py` writes both and refuses
anything `build_info.is_newer` says is not an advance — a release numbered below the last one is
invisible to every install already out there, and shows up only as silence. `build.bat` bumps first
and **commits last, only on success**, naming just those two files so an unrelated dirty tree is not
swept into a release commit.

`build.bat` is the one file here that cannot be tested where it is written. Its syntax and its first
two steps were run under `wine cmd`; the rest needs a real Windows box. **`%ProgramFiles(x86)%` is
read outside every parenthesised block on purpose** — the brackets in its *value* close an `if` block
early, which is how a batch file that reads correctly fails only on the machines that have it set.

**Embeddable CPython, not a freeze**, and the reason is this project's own shape: zero runtime
dependencies means there is no graph to resolve, while `gui.RESOURCE_DIR` and
`cache.PACKAGED_OVERRIDES` are `__file__`-relative and `build_info` reads `importlib.metadata` — all
three of which a one-file freeze breaks or has to be told about. The wheel must exist first: its
`.dist-info` is copied beside the package, and without it the watermark and the update check both go
quiet. The interpreter is verified against the SHA-256 in python.org's **SPDX SBOM**.

**The Windows build bundles `osrs-dps`, so recipients are entitled to the corresponding source for
both.** chunksim is public; `osrs-dps` is not, so the payload carries `source/`: an sdist for each,
built in the same invocation as the wheels so the two correspond. `verify_payload` treats a missing
archive as a build failure — the licence half is checked like the code half. `--without-dps` (or
`/nodps`) builds without it.

**Three cross-file contracts, all pinned by `tests/test_packaging.py`**: the installer's
`OutputBaseFilename` must end in `api.INSTALLER_ASSET_SUFFIX` or the updater never finds the asset;
`AppVersion` must match `pyproject.toml` or an update installs itself forever; and `AppId` is a fixed
GUID, which is what makes a new version an upgrade rather than a second Add/Remove entry.

**`wine` runs the payload**, which is how this was verified without a Windows machine. It is also what
found `dps_bridge` raising `NameError` on import without the optional extra, which every test
environment had hidden. Compiling the `.iss` still needs Inno Setup.

## Tests

**Which tests a change needs is a file, not a judgement** — that is what the module split bought, and
the only reason to prefer this layout to the one file it replaced. Tests are pytest, in `tests/`,
**flat and named after the module under test**: `tests/test_cli_estimate.py` for `cli/estimate.py`,
`tests/test_gui_view.py` for `gui/routes_view.py`, `tests/test_gui_contract.py` for `app.js` and
`style.css`. Flat rather than mirroring the package tree, because pytest's default import mode
collides on duplicate basenames across directories without `__init__.py`.

**`costing/` is the one place the name is not enough, so look for two.** Most of its modules take a
`test_costing_` prefix (`tests/test_costing_wintertodt.py`), but ten carry the bare name because
the module name alone was already unambiguous or the file predates the prefix —
`costing/estimate.py` is `tests/test_estimate.py`, and so are `training`, `farming`, `slayer`,
`prayer`, `heuristics`, `recipe_rates`, `combat_xp`, `dps_bridge` and `dps_overhead`. Four modules
have no file of their own and are exercised through their callers: `coverage.py` through
`test_cli_training.py`, `levels.py` through `test_costing_player_levels.py`, and the two
`*_overhead.py` helpers through the models that spend them.

**Running one file is the point of the layout, so run one:**

```
.venv/bin/pytest tests/test_estimate.py                 # one module's tests
.venv/bin/pytest tests/test_estimate.py::test_name      # one test
.venv/bin/pytest -k wintertodt                          # by name, across files
.venv/bin/pytest -m real_export                         # just the oracles (needs the env vars below)
.venv/bin/pytest -x -q tests/test_cli_estimate.py       # stop at the first failure
mypy src/chunksim/costing/estimate.py                   # one file; still from the repo root
```

A bare path argument overrides `files` in `[tool.mypy]`, so a single-file `mypy` checks that file and
its imports rather than the whole tree — quick while iterating, but **the commit gate is the bare
`mypy`**, which is what sees a signature change's other callers.

**The ordinary suite is not the real correctness signal.** The oracles are, and they are opt-in:

```
.venv/bin/pytest                                                              # whole suite
CHUNKSIM_CHUNKINFO=cache/reference/chunkinfo.json CHUNKSIM_MAP_CACHE=1 .venv/bin/pytest   # every oracle
CHUNKSIM_CHUNKINFO=… CHUNKSIM_MAP_CACHE=1 CHUNKSIM_SLOW_ORACLES=1 .venv/bin/pytest            # + the slow ones
```

Run those before trusting a change to `sections`/`sources`/`challenges`/`bis`/`active_tasks`/
`other_tasks`, and **treat a failure as a bug in this code rather than a stale oracle.** Do not report
a green `.venv/bin/pytest` as a change being verified.

- **Upstream is live, so pin shape exactly and size only where zero kills the claim.** The export
  grows, and exact counts turn that into oracles reporting this code as wrong when nothing here has
  moved. A count is quoted to defend an argument, and an argument dies at zero or at a ratio, not at
  a different magnitude. What stays exact is anything that would mean upstream changed *shape*.
  **Re-fetch and re-run is the sync ritual**, and module docstrings carry their measurements with the
  date they were taken.
- **The oracles are marked, not `skipif`-ed.** `@pytest.mark.real_cache` (needs the export *and* this
  checkout's populated `cache/`), `@pytest.mark.real_export`, or `@pytest.mark.slow` (minutes, gated
  on `CHUNKSIM_SLOW_ORACLES`); `conftest.pytest_collection_modifyitems` turns them into skips when the
  inputs are absent, and the markers are registered in `pyproject.toml` so a typo is a warning rather
  than a silently-never-run test. Gating a real-cache test on the export alone is a bug: it makes the
  test *fail* with `CacheMissError` on a fresh clone instead of skipping.
- **Read the export through `cache.read_chunkinfo`, never `json.loads` on the env var** — the latter
  bypasses the envelope unwrap. One reader, one answer.
- **A patch target is a module path, so it moves when code does.** `read_chunkinfo` is read in two
  places (`cli/io_commands.py` and `cli/common.py`), and patching one leaves the other reading the
  developer's real cache — not a failing test but a passing one computed against the wrong map.
  `conftest.cached_map` patches both. Pass `cache.py`'s `root` a `tmp_path`, and any test calling
  `cache.read_chunkinfo()` without an explicit `override` must take the `no_ambient_chunkinfo` fixture.
- **`conftest.py` holds what more than one file needs and nothing else** — the markers, `project`,
  `cached_map`, `simulatable`, `derived_entries`, `no_ambient_chunkinfo`, and the **session-scoped**
  `real_export`/`real_state`/`real_derived`, which share one `pipeline.derive` across the oracles and
  never use `cached_derive`, so the oracles stay a cache-free signal. Anything used by one file stays
  in that file: conftest is depended on by every test, which is the blast radius all of this is trying
  to shrink. `tests/` is not a package, so a test file cannot import from `conftest.py` — which is why
  the gates are markers and the shared setup is fixtures.
- A test needing the real export is opt-in; build fixtures by hand for the normal suite so a fresh
  clone stays green.

## Conventions

- PEP 8, type hints on all functions.
- **Design rationale goes in the module docstring, next to the code it constrains** — not here. This
  file is for what spans modules or cannot be discovered from them. When a port turns out to be
  wrong, **correct the docstring rather than appending a note**, and keep the superseded claim only
  where the wrong version is the tempting one.
- **A new module lands in two docstrings**: its own (why it exists and what it refuses to guess at)
  and its subpackage's `__init__.py` (one entry saying what it owns). Nothing about it belongs in
  this file unless it changes something that spans subpackages.
- **`README.md` is the user-facing counterpart and describes every subcommand and most flags**, so a
  new subcommand, a renamed flag or a changed default lands in three places: the module docstring
  (why), this file (what spans modules) and the README (what a user types). It is the one that
  drifts, because nothing in the test suite reads it.
- Run `mypy` and `.venv/bin/pytest`, then commit and push per change. Tracks `main` over SSH.
- **This line is the standing authorization, so commit and push without asking first.** Run `mypy`
  and `.venv/bin/pytest` green, then `git commit` and `git push` after every change (a discrete
  task or fix, not every intermediate edit) — do not stop to confirm the commit or the push
  themselves, only the git-safety cases (force-push, history rewrite, `--no-verify`, and the like)
  still need it. **A push that fails is left alone, not retried or investigated** — a rejected
  non-fast-forward push usually means the user pushed from elsewhere, and it is theirs to reconcile
  and push later. A short factual note that it failed is fine; do not treat it as a blocker.
