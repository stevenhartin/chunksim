# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**This file holds only what spans modules or cannot be discovered from them.** Every module's own
rationale — what it ports, what it approximates, what it refuses to guess at, and the measurements
behind each — lives in its **module docstring**, next to the code it constrains. Those docstrings are
long, current and are the real documentation: **read the module's docstring before trusting its
numbers or changing its behaviour.** This file is a map to them, not a substitute, and anything that
can live in one belongs there instead of here.

## Project

fray-claude is a CLI that reads state from the source-chunk web app, caches it locally, and runs
offline operations on that cache. source-chunk is upstream and read-only from here.

**Two apps, one distribution.** `fray` is the CLI; `fray-gui` is a local server plus a browser
front-end that draws the world map. The library both use is eight subpackages, and there is
deliberately **no `core/` and no second distribution** — three pyprojects would buy independent
versioning nobody needs, and a subpackage can be lifted out on the day someone wants to reuse it.

```
src/fray_claude/
  model/    what upstream's data *is*, before anything is derived from it
  remote/   the only outbound network calls
  store/    the only disk
  derive/   the pure layer: the derivation chain and everything that walks it
  costing/  derivation -> hours, and the optional GPL seam to osrs-dps
  runs/     what a *run* is: a base state, a sequence of rolls, its replay
  cli/      one module per subcommand family, parser beside handler
  gui/      the server, split by what each route costs
```

Each directory's `__init__.py` carries the rule that holds across it and **nothing else** — no
re-exports, which would rebuild the god-module this layout replaced and put "which tests do I run"
back to "all of them". The single exception is `cli/__init__.py`, which re-exports `main` because
`[project.scripts]` names `fray_claude.cli:main`.

Planned: a shortest-path search ("fewest chunk unlocks to reach X" — `derive/graph.py` exists to
serve it and has no other reason to be a separate module), and heatmaps of likely rolls over N
attempts (the cached simulation batches are the input; `gui/resources/app.js`'s `LAYERS` array plus
`MapView.overlays` is the seam they attach to).

## source-chunk

- Source: https://github.com/source-chunk/chunk-picker-v2/
- Live instance, the only one that matters: https://source-chunk.github.io/chunk-picker-v2/?fray

It imposes an artificial rule set on Old School RuneScape by adding barriers to the world: it holds
the set of chosen chunks, tracks goals for the active chunk, and randomly selects the next chunk to
unlock from the allowed neighbours. Reproducing that selection and the neighbour-eligibility rules is
the core of this tool — **read the upstream source for them rather than inferring from observed
output.** Module docstrings cite `worker.js`/`index.js` line numbers throughout.

**Chunk** — a fixed square block of tiles; the unit source-chunk unlocks.
**Tile** — the smallest interactable square; the avatar occupies one at a time.
**Section** — a chunk may be split into numbered sub-areas; unlocking a chunk only makes section `0`
reachable, not the rest (`derive/sections.py`).

`?fray` is a map ID, not page state — the real backend is a public Firebase Realtime Database, read
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
  This looks like an obvious optimisation and is not possible: `chunkinfo.activeTasks` holds ~49
  UI-facing answers against the ~2,700 valid tasks this project computes, and the payload has no
  sections, sources or validity branches at all. That is exactly what makes those few entries
  oracles. `completedChallenges` is the player's ticked list, an *input*. What `cache/derived/` avoids
  is computing the derivation *twice*, which is the real version of this optimisation.
- **The pure layer must stay process-parallel, so there is no module-level mutable state anywhere** —
  no `lru_cache`, no module-level memo dicts, no globals; `MapState`/`Derived` are frozen. `fray
  simulate --jobs N` and `runs/batch.price_steps` both depend on it, and a cache added to a "pure"
  module would break `--jobs` silently, as runs that disagree. `cache/derived/` is content-keyed, so
  two workers racing on one key write identical bytes and the atomic rename makes either winner
  correct.

  **The rule is about *module* scope, and caching within one call is how the hot paths are fast.**
  Four shapes are sanctioned, in increasing scope: a `cached_property` or dict on a frozen bundle
  built per call and passed down (`costing/estimate.py`'s `_Walk`, which carries three and is 93x
  because of them); a dict captured by a closure (`estimate.material_seconds`); a previous result
  passed in *and* returned, never stored (`dps_bridge.PricedFights`); and content-keyed disk
  (`store/derived_cache.py`). All four die with the call or travel as data, so a worker cannot
  inherit one. The test is not "is there a dict" but "could two processes see different contents" —
  and where a memo outlives a request, as the GUI's `ReferenceBlobs` does, it must be validated
  against what it caches rather than merely remembered.

### Test against more than one map

Every rule in a map's `rules` branch is a number or a flag a *player* set, so a second map is a
second set of inputs rather than more of the same data. `verf` alone found three defects nothing in
the repo could have — including a `0` that reached a ratio parser as `"1/0"` (JS yields `Infinity` and
raises nothing; Python disagreed) and two unported BiS rules. The BiS oracle runs over **every fetched
map in the cache**, so `fray fetch --map <other>` is all it costs to widen the signal, and it is the
fastest way to find the next defect. The GUI's undocumented `__UBER__` fetch (see `gui/actions.py`)
builds an every-chunk map on top of whichever map is open, which is what the docstrings' measurements
are quoted against.

### Where things live

The table says what each module **owns**; its docstring says why.

| Module | Owns |
|---|---|
| `model/chunkinfo.py` | Typed, tolerant accessors over the parsed export. Build **one** per invocation — the ~10MB parse is the expensive part. |
| `model/firebase.py` | The Firebase-safe codec, both ways, incl. mixed `t_N`/literal keys and the encoder the GUI's edit mode writes through. |
| `model/summary.py` | Pure reductions over a raw payload — extend this, not the CLI. Also `format_age` and `_mapping`, the tolerant dict accessor eight modules import despite the `_`. |
| `model/rates.py` | Drop-rate string parsing/formatting matching JS's rounding, **and its division**, so a zero denominator is `inf`. |
| `model/experience.py` | The exact 1–99 XP curve, closed-form. **Not a heuristic and not overridable** — that separation from `heuristics.py` is the point of the module. |
| `model/edits.py` | A tick written back into a payload — **the one place this project writes to upstream's data.** The danger is silence, not complexity. |
| `remote/api.py` | The network. Four hosts. An unknown map is HTTP 200 + bare `null`, never a 404. **The map tiles are a fifth host it never calls.** |
| `remote/wiki.py` | Wikitext template parsing and numeric-value extraction (arithmetic, `{{#expr:}}`, and what to refuse). |
| `remote/wikitable.py` | Reading a wikitable: the depth-aware cell splitter and `column_index`'s `colspan` resolution. |
| `remote/scrape.py` | The sixteen stages (thirty-odd requests) that build the scraped layer, and its coverage. **Both apps run it**, so the two cannot write different files. Decides no rate. |
| `remote/skill_tables.py` | Rates from wiki tables, headings and prose for the skills `{{Recipe}}` and the guides cannot describe. |
| `remote/recipes.py` | `{{Recipe}}` as the wiki's Bucket serves it: experience, ticks and materials per action. |
| `remote/stores.py` | What a shop charges and **in what currency**. |
| `remote/combat.py` | Monster hitpoints and xp multipliers; autocastable spells and what each cast consumes. |
| `remote/prayer.py`, `remote/farming.py` | Bones/altars, and the Farming calculator's crop table read as raw Lua. |
| `derive/sections.py` | Which sections of the unlocked chunks are reachable, plus named-area unlocking and the one place this project overrules the export. |
| `derive/sources.py` | What the unlocked chunks make available (`SourceIndex`), incl. `taskUnlocks` over items *and* entities. |
| `derive/challenges.py` | Which challenges are valid — a two-phase fixed point. **`BiS` is never evaluated here.** Also **where every derivation command spends its time**: read the static/dynamic gate split before touching the loop. |
| `derive/bis.py` | Best-in-slot per (combat style, slot). Inherently **non-monotonic**: recomputed fresh per state, never accumulated. |
| `derive/active_tasks.py` | Per-skill active/obsolete/completed classification. A *display* winner only — it never changes `ChallengeResult.valid`. |
| `derive/other_tasks.py` | The three non-skill categories, `Diary`/`Quest`/`Extra`. No single winner. |
| `derive/boosts.py` | Temporary skill boosts. With `rules['Boosting']` on this is a **dependency** of the two above, not a feature. |
| `derive/pipeline.py` | `MapState` + `derive`. Owns the **loop** where upstream's area-unlock circularity lives, and the `slayerLocked` fold. Raises `ConvergenceError` rather than returning a truncated derivation. |
| `derive/unlock.py` | What one candidate unlock adds, by diffing two `derive` calls. **Owns the project's attribution rule.** Additions-only. Records *eligibility* and the two boost clamps as well as validity — a diff of `valid` alone cannot see a skill becoming trainable, and ranks on the wrong number when a boost applies. |
| `derive/delta.py` | The **symmetric** comparison of two derived states. `unlock.py` projects its primitives down to a one-directional view, and the two must agree. |
| `derive/neighbours.py` | Which chunks are eligible to roll next, upstream's canvas numbering, and the `sectionsLimits` gate. |
| `derive/graph.py` | The export's `sections` branch as a **directed** graph. Shaped for the not-yet-written pathfinding search. |
| `derive/search.py` | World-wide fuzzy search over the *raw* export — a strict superset of what `fray sources` can list. |
| `costing/heuristics.py` | Every hand-correctable number, and the `defaults < scraped < overrides` merge. Owns the joins and their `exact`/`contained` provenance; **no fuzzy tier, by measurement.** |
| `costing/estimate.py` | The four buckets over the **active** set. **Costs the unique *item*, not the task**, and **clamps per source**. Owns the item walk and the gates on it, and records the `Heuristics` entries each number was read off — where they are read, never reconstructed. |
| `costing/training.py` | How fast a skill goes. **A climb is priced band by band as methods unlock**, so the floor can only ever be the first band. Each band carries the override path behind its rate, set where the rate is chosen. |
| `costing/recipe_rates.py` | A recipe turned into an XP rate, joined exactly on `Output`. Owns `defaults < computed < scraped < overrides` — **the one place a computed number does *not* beat the scrape.** |
| `costing/combat_xp.py` | Combat XP, which is damage and almost nothing else. Owns the three gates and the two credits that each removed a wrong answer. |
| `costing/slayer.py` | Slayer's rate, which is a *distribution* not a chosen method, and the points economy that decides where you train. |
| `costing/prayer.py`, `costing/farming.py` | The two skills whose limit is not a rate: bone supply, and a **schedule** measured in calendar days beside its active hours. |
| `costing/levels.py` | `infer_levels`/`goal_levels`/`reachable_providers` and the gating helpers. **The map records no skill levels** — the floor is read out of completed challenges. |
| `costing/inputs.py` | What `fray estimate` and the Estimate tab must agree about, assembled once. The two had already drifted. Also `ReferenceBlobs`: the reference files read **once per invocation** and threaded, rather than four times by four callers — and the one place the four override layers are merged, so no reader can apply three of them. |
| `costing/dps_bridge.py` | The seam to `osrs-dps`. **Optional import** — check `DPS_AVAILABLE`, never assume it. Prices only `reachable_providers`, which it imports rather than copying. |
| `costing/*_overhead.py` | The harnesses that fitted the overhead constants. **No caller in `src/`** — they exist to be re-run when someone doubts them. |
| `store/cache.py` | The disk. The envelope, the `--chunkinfo`/`FRAY_CHUNKINFO` override, `--map` resolution across kinds, atomic writes, the cross-kind name claim, `migrate_layout`, and both override files. |
| `store/derived_cache.py` | The on-disk cache of the **two** expensive per-state computations, and both their keys. **Read it before changing what `derive` returns** — including a *nested* result dataclass, which `_RESULT_TYPES` must list or the key will not move. |
| `store/build_info.py` | Which install is running and when it was made. Never raises and never guesses a date. |
| `runs/simulate.py` | Seeded chunk-roll simulation and `simulated_payload`. Records are never revisited by a later roll. |
| `runs/batch.py` | N simulations from one state. Owns seed derivation and **both** `ProcessPoolExecutor`s in the project. **`--jobs` must never change a result.** Also the single writer of the run metadata both apps read back. |
| `runs/timeline.py` | Replaying a run one roll at a time, and `added_hours` — what a roll *cost*, as a diff of what is being costed rather than of the totals. **A run is self-contained**: stepping needs no base map, no export and no `derive`. |
| `cli/app.py` | The parser and `main`, and nothing else. If it is about a particular subcommand it does not belong here. |
| `cli/common.py` | What every family needs before it can answer: `load_state`, `derive_cached`, `emit_json`, `digests`, `error`, `DEFAULT_MAP`. |
| `cli/<family>.py` | One per subcommand family, each holding its handlers **and** its `add_parser` block, so a flag change edits one file. `cli/render.py` is the shared terminal formatting. |
| `gui/server.py` | Routing, as a **pure `handle_request`** with a `BaseHTTPRequestHandler` adapter over it. Owns the `Sec-Fetch-Site`/`Host` checks, and `_state_at` — the one place `(map, step)` becomes a world, so six routes cannot disagree about what a step means. |
| `gui/http.py` | The vocabulary every route speaks. **Must stay directly in `gui/`** — `RESOURCE_DIR` is `__file__`-relative, which is why the split is flat rather than a `routes/` package. |
| `gui/routes_view.py` | The **cheap path**: every route answerable without parsing the export. Nothing here may call `ctx.derivations.load` (one documented exception, with a test). |
| `gui/routes_derived.py` | The **expensive path**. `/api/diff` derives both sides and is the one route allowed to be slow. |
| `gui/routes_reference.py` | Bytes belonging to no map: the static allowlist, blob freshness, the tile *template*, and the lazy asset proxy. |
| `gui/actions.py` | The POST handlers. **An action's reply shape decides whether the page polls it** — a job id, or the result. |
| `gui/jobs.py` | The background job registry. **The only mutable state in the GUI**, kept out of the pure layer deliberately. Also `claim_once`, which is what stops the page's boot warm-up re-scraping the wiki on every reload. |
| `gui/derivation.py` | The boundary between the cheap path and the expensive one. Loads `ChunkInfo` **lazily**, and holds the `ReferenceBlobs` — the one memo here validated against the files' mtimes, because stale overrides key the enrichment cache. Also `load_step`, which is how a panel describes one roll of a run rather than the map. |
| `gui/settings.py` | What a preference *means* - defaults, and the validation that refuses rather than coerces. `cache.py` stores it and knows nothing about it; this is where the next preference goes. |
| `gui/knobs.py` | What an override **path** means: which layer a value came from, and whether a proposed one is allowed. Pure, and the guard on paths that address a file read back and parsed. |
| `gui/panels.py` | Shaping `Derived` into what the panel draws — one shape across all five categories. Pure. **New shaping goes here, not into the JavaScript.** A *roll* is shaped from the ledger alone, so anything the selection compares has to be in the ledger. |
| `gui/worldmap.py` | Where a chunk sits on the map and which sides face outward. Owns the projection (the y axis is flipped) and `hull_edges`. |
| `gui/browser.py` | Finding a Chromium-family browser and opening an app window whose lifetime is the server's. `--user-data-dir` is load-bearing, not tidiness. |
| `gui/__init__.py` | `fray-gui`'s argparse and socket, `allowed_hosts`, and the **arming of at most one** of the two shutdown mechanisms. Downloads nothing. |

### Two constraints on the GUI worth knowing before editing it

- **The map is the OSRS wiki's cartography tiles and the browser loads them — this project never
  touches one.** `/api/tiles` hands out a URL *template*. That is a **licence decision, not an
  optimisation**: the tiles are CC BY-NC-SA 3.0 against this project's MIT, so caching them under
  `cache/` or re-serving them off loopback would make this a redistributor of NonCommercial artwork,
  where linking makes it a page with a picture on it. `tests/test_gui_contract.py` asserts no tile
  route exists, so a later "let's cache these" cannot pass review by looking like a speed-up.
- **Constants crossing into JavaScript have nothing enforcing agreement**, so
  `tests/test_gui_contract.py` reads `app.js` and asserts them against the Python. It also pins the
  interface rules that each replaced a bug (one tooltip system; chip strips record what is *off*;
  no `raw()` interpolation inside an attribute) and that every length in `style.css` comes from the
  one scale. `app.js` is heavily commented and is where the front end's rationale lives.

## Toolchain

Python 3.14.6, mypy, pip (no uv). Run `mypy` and `.venv/bin/pytest` before each commit.

**Zero *required* runtime dependencies, deliberately** — `pyproject.toml` has an empty
`dependencies`, so a new module gets the stdlib and nothing else. `store/derived_cache.py` is the
shape that keeps to: it wanted zstd and got it from 3.14's stdlib (PEP 784) rather than PyPI, and
still degrades to plain pickle on a CPython built without `_zstd`.

There are two extras and they are not alike. `dev` is `pytest`. **`dps` is
[`osrs-dps`](https://github.com/stevenhartin/osrs-dps), and it must stay optional for a reason beyond
weight: it is GPL-3.0 where this project is MIT.** So it is a package a user installs deliberately,
never vendored in, and `costing/dps_bridge.py` is the only module that may import it — behind a
`try`/`except ImportError` that sets `DPS_AVAILABLE`. Importing `dps_bridge` is always safe; calling
into it without the extra raises `DpsUnavailableError`. Its tests skip rather than fail when the
extra is absent, like the `FRAY_CHUNKINFO` oracles. A change to `osrs-dps` that moves a number is a
change to `fray estimate`'s answers, so run both suites.

`mypy` and `pytest` are invoked differently on purpose: **mypy is the *system* install** (there is no
`.venv/bin/mypy`), configured with `python_executable = ".venv/bin/python"` so it can see pytest's
stubs — which is why it must run from the repo root and needs the venv to exist. **pytest is only a
`dev` extra inside the venv and is not on `PATH`**, so a bare `pytest` fails with "command not
found".

## Commands

```
pip install -e ".[dev]"     # editable install into .venv; provides the `fray` script
fray fetch [--map ID]       # GET live state -> cache/maps/fetched/<map>.json (default: fray)
fray show  [--map ID]       # summarise the cached copy; no network
fray chunkinfo              # GET upstream's chunk/challenge reference data (~10MB)
fray heuristics             # GET wiki/spreadsheet rates -> cache/reference/wiki_rates.json (30+ requests)
fray recipes                # GET per-action xp + tick costs -> cache/reference/wiki_recipes.json
fray estimate [BUCKET] [--limit N]                 # rough hours for the outstanding active tasks
fray sections [list|CHUNK] [--limit N]             # reachable sections
fray sources  [CATEGORY]   [--limit N]             # items/objects/monsters/npcs/shops
fray tasks    [CATEGORY]   [--limit N]             # valid/active/obsolete/completed, incl. BiS
fray unlock   --chunk ID [--cache-map NAME]        # what one candidate chunk would add
fray diff --map1 A --map2 B [BRANCH] [--limit N]   # symmetric comparison of two cached maps
fray neighbours [--limit N]                        # chunks eligible to unlock next
fray simulate --rolls N [--seed S] [--cache-map NAME] [--runs R] [--jobs J]
              [--cache-behaviour all|extremities|none] [--no-carry-areas]
fray maps [list [--runs]] | maps rm NAME... [--include-fetched] | maps clean [--include-fetched]
fray derived [list [--verbose]] | derived clean [--older-than DAYS] [--all]
fray search   QUERY [--type T ...] [--limit N]
python -m fray_claude ...    # same CLI without the console script
fray-gui [--map ID] [--compare ID] [--port N] [--host H] [--allow-host H] [--keep-alive]
         [--no-browser] [--tab]
mypy                         # strict, over src/ and tests/; run from the repo root
.venv/bin/pytest             # whole suite
```

Env vars: `FRAY_CHUNKINFO` (an export, or `fray chunkinfo`'s envelope around one), `FRAY_MAP_CACHE`
(presence-only), `FRAY_SLOW_ORACLES` (presence-only), `FRAY_NO_WATERMARK`, `FRAY_TILE_VERSION`,
`FRAY_GUI_VERBOSE`.

**Flag conventions, so each means one thing everywhere.** `--export-json PATH` (or `-` for stdout) and
`--recompute` are carried by the nine *derivation* subcommands and nothing else (`--export-json` also
by `maps list`), not by the four I/O ones. `--limit` defaults to `None` — full output, so piping just
works — except for `search`, where it is `10`. `fray diff` is the one subcommand taking two maps,
hence `--map1`/`--map2`; it reports **both directions**, which `fray unlock` deliberately does not.

**`cache/` is sorted by purpose, and `cache/maps/` holds maps and nothing else holds maps.** That
sentence is the layout's whole point: `list_maps` used to glob `cache/*.json` and skip the names it
*knew* were not maps, so every new blob had to be remembered or it turned up in the picker as a map
that failed the moment it was chosen. A directory cannot be forgotten.

```
cache/maps/fetched/<id>.json       # from Firebase; only `fray fetch` writes one
cache/maps/simulated/<batch>/…     # rolled by `fray simulate`
cache/maps/edited/<batch>/…        # made by hand: `fray unlock --cache-map`, or the GUI
cache/reference/                   # chunkinfo, tasks_map, wiki_rates, wiki_recipes, tile_version
cache/derived/                     # pipeline.derive + dps_bridge.enrich results, keyed by content
cache/overrides/<map_id>.json      # heuristic corrections belonging to one map
cache/assets/                      # section masks, skill icons
cache/gui/                         # window.json, settings.json, and the browser profile
```

A batch of any computed kind holds `batch.json` (seeds, rolls, `batch_id`, and the payload it rolled
from) beside one directory per run holding `map.json`, `rolls.json`, `run.json` and `timeline.json`.
**A name is claimed across every kind**, so `--map foo` never has to guess which directory meant it.
`cache/` is gitignored, so a fresh clone has no data until `fray fetch`/`fray chunkinfo` run.

**The estimator's numbers live in three places and only two are in `cache/`.** `fray heuristics`
writes the scrape to `cache/reference/wiki_rates.json` (refetchable, gitignored); hand-written
corrections go in **`heuristics/overrides.json`, which is checked in** so they are diffable and
survive a re-scrape; and corrections belonging to *one map* go in `cache/overrides/<map_id>.json`,
which is cache data and gitignored with the rest. `heuristics/README.md` is the guide to which
numbers are worth correcting. The export has *no* durations, rates or XP figures at all, so every
number `fray estimate` spends comes from one of those three files or a default in
`costing/heuristics.py`.

The merge is `defaults < scraped < overrides < map overrides`, and it happens **once**, in
`load_reference` — so `ReferenceBlobs.overrides` is the *effective* set and every downstream reader
(`load_heuristics`, `levels`, `pinned`, `recipe_priced`) gets the fourth layer without being told
about it. A `ReferenceBlobs` is therefore about one map, which is why `map_id` is on it and why the
GUI memoises one per map. **Both apps must pass the map id or neither should**: `costing/inputs.py`
exists because `fray estimate` and the Estimate tab had already drifted once, and a layer one of them
applied would be that drift again in the hardest place to see.

**`User-Agent` differs by host, deliberately.** Firebase and GitHub get none — those endpoints are
public and unauthenticated, so a header would only publish information nobody asked for. The **OSRS
wiki gets `api.WIKI_USER_AGENT` and requires it**: an anonymous request there is answered with HTTP
403 (measured). One principle — send what the endpoint needs to serve the request and nothing more
about who is asking. The header names the project and its repo, never the user.

### Installing, and the one rebuild loop left

```
pipx install --force --editable .                    # once, not per change
pip install -e ../osrs-dps                           # the optional dps extra, into .venv
(cd ../osrs-dps && pyproject-build) && pipx inject --force fray-claude ../osrs-dps/dist/osrs_dps-*.whl
```

**`fray` on `PATH` is an editable install, so there is nothing to rebuild** — a Python edit is live
immediately, and so is a `gui/resources/` edit, since `RESOURCE_DIR` is `__file__`-relative and
resolves into the checkout. Editing the front end is edit → reload the tab. **The cost is that the
checkout is load-bearing**: move or delete it and both commands break. And one failure mode moves
rather than disappearing — a new subdirectory without an `__init__.py` imports fine here and is
silently absent from any wheel built later, which is what `tests/test_packaging.py` catches.

**The `dps` extra is installed two different ways, one per venv**, and both are needed: `.venv` is
what `pytest`/`mypy` see, pipx's own venv is what the `fray` on `PATH` sees. An injected package
survives `pipx install --force` (both measured), but `inject` *copies* a wheel — so a change to
`osrs-dps` needs a rebuild and a re-inject, and `--force` is required because the version does not
move between builds, which makes a plain `inject` a silent no-op.

`pyproject-build` is **not part of the development loop.** Three reasons left to build a wheel:
shipping to another machine, proving the packaged `gui/resources` shipped
(`python -m zipfile -l dist/*.whl | grep resources`), and checking `packages.find` still discovers
every subpackage — the third of which `tests/test_packaging.py` covers in milliseconds.

## Tests

**Which tests a change needs is a file, not a judgement** — that is what the module split bought, and
the only reason to prefer this layout to the one file it replaced. Tests are pytest, in `tests/`,
**flat and named after the module under test**: `tests/test_cli_estimate.py` for `cli/estimate.py`,
`tests/test_gui_view.py` for `gui/routes_view.py`, `tests/test_gui_contract.py` for `app.js` and
`style.css`. Flat rather than mirroring the package tree, because pytest's default import mode
collides on duplicate basenames across directories without `__init__.py` — `tests/cli/test_estimate.py`
beside `tests/costing/test_estimate.py` is a landmine, and `pytest tests/test_cli_*.py` already gives
directory-grade selection.

**The ordinary suite is not the real correctness signal.** The oracles are, and they are opt-in:

```
.venv/bin/pytest                                                              # whole suite, ~2.6s
FRAY_CHUNKINFO=cache/reference/chunkinfo.json FRAY_MAP_CACHE=1 .venv/bin/pytest   # every oracle
FRAY_CHUNKINFO=… FRAY_MAP_CACHE=1 FRAY_SLOW_ORACLES=1 .venv/bin/pytest            # + the slow ones
```

Run those before trusting a change to `sections`/`sources`/`challenges`/`bis`/`active_tasks`/
`other_tasks`, and **treat a failure as a bug in this code rather than a stale oracle.** Do not report
a green `.venv/bin/pytest` as a change being verified.

- **The oracles are marked, not `skipif`-ed.** `@pytest.mark.real_cache` (needs the export *and* this
  checkout's populated `cache/`), `@pytest.mark.real_export`, or `@pytest.mark.slow` (minutes, and
  gated on `FRAY_SLOW_ORACLES` so the ordinary oracle run stays worth typing — today that is the
  `--carry-areas` equality run, which is that default's standing evidence — every carried run
  also checks itself against a cold derivation, so a divergence surfaces on real data too — and
  the roll panel replayed over a whole 50-roll run, where the ordinary variant replays twelve —
  the prefix is what *finds* a defect, the full run is what lets you say the panel and the
  derivation agree generally); `conftest.pytest_collection_modifyitems`
  turns them into skips when the inputs are absent, and the markers are registered in `pyproject.toml`
  so a typo is a warning rather than a silently-never-run test. Gating a real-cache test on the export
  alone is a bug, not a shortcut: it makes the test *fail* with `CacheMissError` on a fresh clone
  instead of skipping.
- **Read the export through `cache.read_chunkinfo`, never `json.loads` on the env var** — the latter
  bypasses the envelope unwrap, which is what once made the one-line oracle run fail on seven tests
  while a hand-extracted file passed. One reader, one answer.
- **A patch target is a module path, so it moves when code does.** `read_chunkinfo` is read in two
  places (`cli/io_commands.py` and `cli/common.py`), and patching one leaves the other reading the
  developer's real cache — not a failing test but a passing one computed against the wrong map.
  `conftest.cached_map` patches both. Pass `cache.py`'s `root` a `tmp_path`, and any test calling
  `cache.read_chunkinfo()` without an explicit `override` must take the `no_ambient_chunkinfo` fixture.
- **`conftest.py` holds what more than one file needs and nothing else** — the two markers, `project`,
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
- **`README.md` is the user-facing counterpart and describes every subcommand and most flags**, so a
  new subcommand, a renamed flag or a changed default lands in three places: the module docstring
  (why), this file (what spans modules) and the README (what a user types). It is the one that
  drifts, because nothing in the test suite reads it.
- Run `mypy` and `.venv/bin/pytest`, then commit and push per change. Tracks `main` over SSH.
