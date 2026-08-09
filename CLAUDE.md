# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

fray-claude is a CLI that reads state from the source-chunk web app, caches it locally, and runs
offline operations on that cache. source-chunk is upstream and read-only from here.

**Two apps, one distribution.** `fray` is the CLI; `fray-gui` is a local server plus a browser
front-end that draws the world map — see the GUI paragraph below Commands. The 30 modules beside
`cli.py` are the library both use, which is why there is no separate `core/` package and no second
distribution: the layering already exists, and three pyprojects would buy independent versioning
nobody needs.

Planned: a shortest-path search ("fewest chunk unlocks to reach X" — `graph.py` exists to serve it and
has no other reason to be a separate module), and heatmaps of likely rolls over N attempts (the
cached simulation batches are the input, and `gui/resources/app.js`'s `LAYERS` array plus
`MapView.overlays` is the seam they attach to — see the `cache/maps/` layout under Commands).

`fray estimate` answers "time to complete the goals" — the export still has no duration source, so
the numbers come from the OSRS wiki and a community spreadsheet via `fray heuristics`. See the
estimator paragraph below Commands.

## source-chunk

- Source: https://github.com/source-chunk/chunk-picker-v2/
- Live instance, the only one that matters: https://source-chunk.github.io/chunk-picker-v2/?fray

It imposes an artificial rule set on Old School RuneScape by adding barriers to the world: it holds
the set of chosen chunks, tracks goals for the active chunk, and randomly selects the next chunk to
unlock from the allowed neighbours. Reproducing that selection and the neighbour-eligibility rules is
the core of this tool — read the upstream source for them rather than inferring from observed output.

`?fray` is a map ID, not page state — the real backend is a public Firebase Realtime Database, read
with a plain unauthenticated GET: `https://chunkpicker.firebaseio.com/maps/<map_id>.json`. Chunk
adjacency/neighbour data isn't there; it's `chunkpicker-chunkinfo-export.json` in the upstream repo,
served from the **`gh-pages`** branch — that's upstream's default branch; `main` 404s.

**Chunk** — a fixed square block of tiles; the unit source-chunk unlocks.
**Tile** — the smallest interactable square; the avatar occupies one at a time.
**Section** — a chunk may be split into numbered sub-areas (`chunkinfo.json`'s `sections`); a chunk
being unlocked only makes section `0` reachable, not the rest — see `sections.py`.

Top-level keys of a map payload, for reference while `cache/` is empty: `activeSubTabs`,
`chunkOrder`, `chunkinfo`, `chunks`, `manualPrimary`, `recentFancyRollTime`, `recentLoginTime`,
`rules`, `settings`, `topbarSelection`, `uid`. `chunkOrder` is a partial log with repeating
timestamps — fewer entries than there are unlocked chunks — not an authoritative unlock order.

Map payload strings and object keys are selectively passed through a reversible Firebase-safe
encoding before being written (`.`/`#`/`/`/`'`/`,`/`+`/`!` become sentinel tokens, `%` becomes `-_-`,
purely-numeric keys gain a `*fb*_` prefix, and some fields intern task names to `t_N` ids via
upstream's `tasksMap.json`) — applied per-field by the app, not uniformly across the whole payload,
so which branches need `firebase.decode_payload` is only knowable by checking real fetched data, not
by inspecting the client source. `chunks.unlocked` and `chunkOrder` are stored plain; `chunkinfo`'s
`manualSections`/`stickeredNotes`/`activeTasks`/`completedChallenges`/`checkedChallenges`/`backlog`/
`manualTasks` are encoded. `activeTasks`/`completedChallenges`/`checkedChallenges`/`backlog` key
their entries by `t_N` task id, but **a single category can mix ids and literal encoded names**:
`tasksMap.json` interns names lazily (note its `currentNextIndex` counter), so a name that has never
been interned is stored literally instead. Real data had `completedChallenges.BiS` at 65 ids to 5
literals and `completedChallenges.Extra` at 277 to 1, every literal confirmed absent from
`tasksMap.json`. **Do not assume a category is literal-only from a small sample** — literal keys sort
before `t_N` ones (`'O' < 't'`), which is exactly how an early sample of `BiS` looked literal-only and
produced a real bug (see `firebase.decode_challenge_keyed`). `manualTasks` genuinely *is* literal
throughout, verified the opposite way: its names *are* in `tasksMap.json` yet are still stored by name.
`firebase.decode_challenge_keyed` handles both forms.

## Architecture

One responsibility per module, so the planned simulation work has a pure layer to build on.
**`api.py` is the only module that makes *outbound* network calls and `cache.py` the only one that
touches disk; everything else is pure.** `gui/server.py` is the one exception in each direction and
neither weakens the rule: it is the only module that **accepts inbound** connections, binding
loopback unless `--host` says otherwise, and the only disk it touches beyond `cache.py` is its own
packaged read-only resources — every map it reads goes through `cache.read_cache`. The derivation
chain is
`sections` -> `sources` -> `challenges` -> `bis` -> `active_tasks`/`other_tasks`, wired by
`pipeline.derive` and reached by every subcommand through it.

**This is a deliberately partial reimplementation of upstream's own logic.** Each module's docstring
carries the precise, current list of what it ports, what it approximates, and what it refuses to
guess at, with `worker.js`/`index.js` line references — **read it before trusting that module's
numbers or changing its behaviour.** That is where the design rationale lives; this section is a
map to it, not a substitute.

**Test against more than one map.** Every rule in `rules` is a number or a flag a *player* set, so a
second map is a second set of inputs and not just more data. `verf` alone found three defects nothing
in the repo could have: `Secondary Primary Amount` of `0` reached `rates.parse_ratio` as `"1/0"` and
killed every derivation command (JS `1/0` is `Infinity` and raises nothing, Python disagreed); and
`Show Best in Slot 1H and 2H` plus the **obsidian set effect** were both unported, so 3 of its 10
recorded BiS picks were wrong. The BiS oracle now runs over **every fetched map in the cache**, so
`fray fetch --map <other>` is all it costs to widen the signal — and it is the fastest way to find
the next one.

Five things that cut across modules — the first three because each has already caused a real bug:

- **Reachable items are `ChallengeResult.available_items`, not `SourceIndex.items`.** The latter
  omits anything obtainable only by *making* it. `bis.py` and `boosts.py` both got this wrong first.
- **The opt-in oracle tests are the correctness signal.** The cached map records upstream's own
  computed answers (`activeTasks.BiS`, `activeTasks.Slayer`, ...) and the tests assert against them.
  **Treat a mismatch as a defect in this code, not as oracle staleness** — an earlier stage of this
  project explained five real bugs away that way.
- **Task names are markup-bearing keys.** The raw `~|...|~` form is the key everywhere (`valid`,
  ledger lookups, `--export-json`); `challenges.strip_task_markup` is display-only, and applies to
  challenge/task names *only* — other branches use `~` and `|` for real.
- **The cached map does not contain the derivation — don't try to read it instead of computing.**
  This looks like an obvious optimisation and isn't possible: `chunkinfo.activeTasks` holds **49
  entries** (BiS 6, Diary 5, Extra 37, Slayer 1) against the **2,700 valid tasks** across 21 skill
  categories this project computes, and the payload has no sections, sources or validity branches at
  all. Upstream derives all of it in the browser and persists only those few UI-facing answers —
  which is exactly what makes them oracles. `completedChallenges` is the player's ticked list, an
  *input*. Computing it is therefore unavoidable; what `cache/derived/` does is avoid computing it
  *twice* (see below), which is the real version of the optimisation this bullet keeps attracting.
- **The pure layer must stay process-parallel.** `fray simulate --jobs N` runs simulations in worker
  processes, and a roll costs a full `derive` (~0.76s on the real export, ~100% of the runtime), so
  this is the only way a heatmap-sized batch finishes. `batch.price_steps` leans on the same property
  from the other direction — it prices a run's steps in workers, and `price_slice` builds everything
  it needs *inside the task* rather than in a pool `initializer`, precisely so no module ever grows a
  memo. That holds today only because there is **no
  module-level mutable state anywhere** — no `lru_cache`, no memo dicts, no globals; `_UNARMED_SOURCES`
  and `_UNIVERSAL_PRIMARY` are read-only constants — and because `MapState`/`Derived` are frozen.
  Adding a cache to a "pure" module would break `--jobs` silently, in the form of runs that disagree.
  Workers each load their own `ChunkInfo` (~0.1s) rather than sharing the parent's; one process writes
  any given file, never two. `cache/derived/` obeys the same rule from the other direction: it is
  content-keyed, so two workers racing on one key write identical bytes and the atomic rename makes
  either winner correct — which is why it needs no lock and has no shared index.

| Module | Owns |
|---|---|
| `api.py` | The network. `FetchError`. An unknown map is HTTP 200 + bare `null`, never a 404. Four hosts: Firebase, upstream's `gh-pages`, the OSRS wiki (which **requires** a `User-Agent`) and one published Google Sheet. **The map tiles are a fifth host it never calls** — `MAP_TILE_URL` is a template the browser uses; see the GUI paragraph. |
| `wiki.py` | Wikitext template parsing, plus `map_tile_version` over the map page's rendered *HTML*. Pure. Quest length is in `{{Quest details}}`, **not** `{{Infobox Quest}}` — the tempting wrong template has no `length` and so returns `None` for every quest without erroring. |
| `experience.py` | The exact 1–99 XP curve, closed-form. **Not a heuristic and not overridable** — that separation from `heuristics.py` is the point of the module. |
| `scrape.py` | The ~18 requests that build the scraped layer, and the coverage it reports. **Both apps run it** — `fray heuristics` and the GUI's Maps tab — so the two cannot write different files. Decides no rate; `heuristics.py` does that. |
| `heuristics.py` | Every hand-correctable number, and the `defaults < scraped < overrides` merge. Owns the joins and their `exact`/`contained` provenance; **no fuzzy tier**, by measurement — read the docstring before adding one back. |
| `slayer.py` | Slayer's rate, which is a *distribution* not a chosen method: a time-weighted mean over what a master assigns. Also owns `superior_rolls_per_hour` — the shared `SuperiorDropTable+` is one pool per master, not one per superior. **Masters are gated on their NPC being reachable** — without that it quoted Duradel on a map holding none of him. Reports `coverage`, because renormalising over reachable tasks flatters a sparse map. |
| `estimate.py` | The four buckets — quests, boss drops, activities, skilling — over the **active** set. **Costs the unique *item*, not the task** — one whip answers three tasks — and **clamps per source**, since items off one monster are earned in parallel. Owns the item walk, its bounded `Output` recursion, the `unpriced` list, and **three gates** — monster reachable, slayer task assignable, master reachable. Read the docstring before pricing anything off `WorldIndex`, which spans the whole world. |
| `cache.py` | The disk. `CacheMissError`, the `map_id`/`fetched_at`/`source`/`kind`/`data` envelope, the `--chunkinfo`/`FRAY_CHUNKINFO` override, and the purpose-sorted layout below (incl. `--map` resolution across kinds, atomic writes, the cross-kind batch-name claim and `migrate_layout`). |
| `build_info.py` | Which install is running, and when it was made: the `*.dist-info` mtime (pip writes those fresh, so it dates the *install*, not the wheel), `wheel`/`editable`/`source`, and the one-line watermark both apps print. Never raises and never guesses a date. |
| `firebase.py` | The Firebase-safe string codec, incl. `decode_challenge_keyed`'s mixed `t_N`/literal key handling. Run any payload branch through it before believing it. |
| `chunkinfo.py` | Typed, tolerant accessors over the parsed export. Build **one** `ChunkInfo` per invocation — parsing the ~7MB export is the expensive part. |
| `sections.py` | Which sections of the unlocked chunks are reachable, plus named-area unlocking. `sectionsLimits` deliberately lives in `neighbours.py` instead. |
| `graph.py` | The export's `sections` branch as a **directed** `(chunk, section)` graph, with each edge's `sectionsLimits` gate pre-bound. Shaped for the not-yet-written pathfinding search. |
| `rates.py` | OSRS drop-rate string parsing/formatting, matching JS's rounding because the output lands inside task names — **and its division**, so a zero denominator is `inf` rather than a `ZeroDivisionError`. |
| `sources.py` | What the unlocked chunks make available (`SourceIndex`). Applies `taskUnlocks` to items *and* entities, so availability depends on challenge validity. |
| `challenges.py` | Which challenges are valid (`ChallengeResult`) — a two-phase fixed point over 28 of 29 categories. **`BiS` is never evaluated here**; read `pipeline.Derived.bis`. Also **where every derivation command spends its time** — read the docstring's static/dynamic gate split before touching the loop. |
| `bis.py` | Best-in-slot per (combat style, slot). Inherently **non-monotonic**: recomputed fresh per state, never accumulated. Scores **set effects** (Obsidian only — the rest are table rows nobody could verify) and honours `Show Best in Slot 1H and 2H`, both of which only a second map exercised. |
| `active_tasks.py` | Per-skill active/obsolete/completed classification. A *display* winner only — it never changes `ChallengeResult.valid`. |
| `boosts.py` | Temporary skill boosts. With `rules['Boosting']` on, **every** level comparison upstream makes is boosted, so this is a dependency of `challenges.py`/`active_tasks.py`, not a feature. |
| `other_tasks.py` | The three non-skill categories, `Diary`/`Quest`/`Extra`. No single winner — upstream renders every valid, uncompleted one. |
| `pipeline.py` | `MapState` + `derive`. Owns the **loop** where upstream's area-unlock circularity lives, so the modules above stay one-directional. Raises `ConvergenceError` rather than returning a truncated derivation. |
| `unlock.py` | What one candidate unlock adds, by diffing two `derive` calls. **Owns the project's attribution rule** and its one exception. Additions-only, and only over one `MapState` — for two arbitrary maps read `delta.py`. |
| `delta.py` | The **symmetric** comparison of two derived states, over all six `Derived` branches. Owns the diff primitives `unlock.py` projects down to its one-directional view; the two must agree, which `tests/test_delta.py` asserts. |
| `neighbours.py` | Which chunks are eligible to unlock next, and upstream's canvas numbering (**descending chunk id, 1-based**). Owns the `sectionsLimits` gate. |
| `timeline.py` | Replaying a run one roll at a time, and `added_hours` — what a roll *cost*, as a diff of what is being costed rather than of the totals. **A run is self-contained** — the state before roll k is `final − rolls[k:]`, so stepping needs no base map, no export and no `derive`. Owns the delta series and the rule that step 0 is a baseline rather than a roll. |
| `simulate.py` | Seeded chunk-roll simulation: the bootstrap pool, plus the dispatch to `neighbours.py`. Records are never revisited by a later roll. `simulated_payload` turns a finished ledger back into a map payload — read its docstring before changing which branches it touches. |
| `batch.py` | N simulations from one state, each cached as its own map. Owns seed derivation and **both** `ProcessPoolExecutor`s in the project — `run_batch` for rolling, `price_steps` for costing a timeline (two rounds: `warm_slice` strided across every core, then `price_slice` over long contiguous slices). `--jobs` must never change a result, either of them. Also `save_unlock` — a batch of one, so the **one** writer of the run metadata both apps read back. |
| `derived_cache.py` | The on-disk cache of the **two** expensive per-state computations: `cached_derive` and `cached_enrich`. Owns both keys (a hash of every input each reads), the zstd+pickle codec, and `CacheBehaviour`/`RollCache` — which of a simulation's states to keep. Pure bar the bytes, which `cache.py` writes. |
| `search.py` | World-wide fuzzy search over the *raw* export — all 5 item routes, so a strict superset of what `fray sources` can list. |
| `summary.py` | Pure reductions over a raw payload. Extend this, not `cli.py`. Also home to `format_age` (both apps render ages, and two copies of the bucketing would disagree) and `_mapping`, the tolerant dict accessor eight other modules import despite the `_` — Firebase omits empty containers, so every lookup anywhere must survive a missing branch. |
| `dps_bridge.py` | The seam to `osrs-dps`, which prices a kill from the gear `bis.py` reaches instead of a money-making guide. Prices **only `estimate.reachable_providers`** — 188 of the export's 872, because every `kills_per_hour` lookup is gated on that set and the rest is thrown away. `enrich_incremental` + `fight_signature` keep a timeline's previous roll where nothing that decides a kill has moved; `enrich` stays untouched. **Optional import** — check `DPS_AVAILABLE`, never assume it. `enrich` is the one entry point a command needs. Owns the export→library conversions (`magic_damage` is a display percentage here and tenths of a percent there), the overhead model, the monster-name join and its `exact`/`variant` provenance, and the refusal of fight *phases* and group bosses. |
| `cli.py` | argparse subcommands and rendering only; new logic goes in a pure module. `gui/server.py` follows the same rule, with `gui/panels.py` as its pure module. |
| `gui/panels.py` | Shaping `Derived` into what the panel draws — sections of groups of `{key, name, note, icon}`, one shape across all five categories. Pure. Owns the three rules that are domain knowledge rather than formatting: a quest keeps only its **furthest** step, `Extra`'s collection-log rows split source from item, BiS groups by combat style. |
| `gui/worldmap.py` | Where a chunk sits on the map, and which of its sides face outward. Pure. Owns the projection (`grid_x = region_x - 15`, **`grid_y = 65 - region_y`** — the y axis is flipped), the tile pyramid's constants, the two kinds of id that have no square, and `hull_edges`. In `gui/` because all of it is about one particular tiling. |
| `gui/server.py` | Routing, as a **pure `handle_request`** with a `BaseHTTPRequestHandler` adapter over it — so tests reach the whole surface without binding a socket. Owns the static allowlist, the `Sec-Fetch-Site`/`Host` checks — the latter against `Context.allowed_hosts` rather than loopback, so a non-loopback bind serves a page that can *act* rather than one whose every button 403s — and the **lazy proxy** for upstream's section masks and skill icons. |
| `gui/jobs.py` | The background job registry the POST actions use. **The only mutable state in the GUI**, kept out of the pure layer deliberately. |
| `gui/derivation.py` | The boundary between the cheap path and the expensive one. Loads `ChunkInfo` **lazily** — a request that does not need a derivation must not pay for one, and a test asserts the map view never triggers it. |
| `gui/browser.py` | Finding a Chromium-family browser and opening an app window whose lifetime is the server's. `--user-data-dir` is load-bearing, not tidiness. `window_flags` restores the remembered geometry, which Chrome will not — see the GUI paragraph below Commands. |
| `gui/__init__.py` | `fray-gui`'s argparse and its socket, and the **arming of at most one** of the two shutdown mechanisms — never both, and neither under `--keep-alive`. Owns `allowed_hosts`, the pure half of `--host`/`--allow-host`. Downloads nothing: the map is the browser's to fetch. The GUI imports the library rather than shelling out to `fray`, which would re-parse the 10MB export per call. |

## Toolchain

Python 3.14.6, mypy, pip (no uv). Run `mypy` and `.venv/bin/pytest` before each commit.

**Zero *required* runtime dependencies, deliberately** — `pyproject.toml` has an empty `dependencies`,
so a new module gets the stdlib and nothing else. `derived_cache.py`
is the shape that keeps to: it wanted zstd and got it from 3.14's stdlib (`compression.zstd`, PEP 784)
rather than PyPI, and still degrades to plain pickle on a CPython built without `_zstd`.

There are two extras and they are not alike. `dev` is `pytest`. **`dps` is
[`osrs-dps`](https://github.com/stevenhartin/osrs-dps), and it must stay optional for a reason beyond
taste: it is GPL-3.0 where this project is MIT.** So it is a package a user installs deliberately
(`pip install -e ../osrs-dps`), never vendored in, and `dps_bridge.py` is the only module that may
import it — behind a `try`/`except ImportError` that sets `DPS_AVAILABLE`. Importing `dps_bridge` is
always safe; calling into it without the extra raises `DpsUnavailableError`. Its tests skip rather
than fail when the extra is absent, like the `FRAY_CHUNKINFO` oracles.

## Commands

```
pip install -e ".[dev]"     # editable install into .venv; provides the `fray` script
fray fetch [--map ID]       # GET live state -> cache/maps/fetched/<map>.json (default: fray)
fray show  [--map ID]       # summarise the cached copy; no network
fray chunkinfo              # GET upstream's chunk/challenge reference data -> cache/{chunkinfo,tasks_map}.json
fray heuristics             # GET wiki/spreadsheet rates -> cache/wiki_rates.json (~18 requests)
fray estimate [BUCKET] [--limit N]   # rough hours for the outstanding active tasks
fray sections [list|CHUNK] [--limit N]   # reachable sections; list/drill down with a positional
fray sources  [CATEGORY]   [--limit N]   # items/objects/monsters/npcs/shops; list one with a positional
fray tasks    [CATEGORY]   [--limit N]   # valid/active/obsolete/completed, incl. BiS (partial - see the module docstrings)
fray unlock   --chunk ID [--cache-map NAME]   # what one candidate chunk would add; optionally saved
fray diff --map1 A --map2 B [BRANCH] [--limit N]   # symmetric comparison of two cached maps
fray neighbours [--limit N] # chunks eligible to unlock next, numbered as the app's canvas numbers them
fray simulate --rolls N [--seed S]   # simulate N chunk rolls and accumulate their tasks/sections
fray simulate --rolls N --cache-map NAME [--runs R] [--jobs J] [--cache-behaviour all|extremities|none]
fray maps [list [--runs]] | maps rm NAME... [--include-fetched] | maps clean [--include-fetched]
fray derived [list [--verbose]] | derived clean [--older-than DAYS] [--all]    # manage cached derivations
fray search   QUERY [--type T ...] [--limit N]   # fuzzy search item/monster/npc/object/shop/task
python -m fray_claude ...   # same CLI without the console script
FRAY_NO_WATERMARK=1 fray ... # silence the provenance line on stderr
mypy                        # strict, over src/ and tests/; run from the repo root
.venv/bin/pytest            # whole suite
.venv/bin/pytest tests/test_summary.py::test_summarise_counts_unlocked_chunks   # single test
FRAY_CHUNKINFO=path .venv/bin/pytest tests/test_sections.py -k real   # opt-in oracle test against a real export
python -c 'import json;json.dump(json.load(open("cache/reference/chunkinfo.json"))["data"],open("/tmp/raw.json","w"))'
FRAY_CHUNKINFO=/tmp/raw.json FRAY_MAP_CACHE=1 .venv/bin/pytest   # all six oracles, the real correctness signal
fray-gui [--map ID] [--compare ID] [--port N] [--host H] [--allow-host H] [--keep-alive]
         [--no-browser] [--tab]
pyproject-build && pipx install --force dist/*.whl   # build + reinstall `fray` and `fray-gui`
python -m zipfile -l dist/*.whl | grep resources     # prove the GUI's html/js/css shipped
pip install -e ../osrs-dps                           # the optional `dps` extra, into .venv for development
(cd ../osrs-dps && pyproject-build) && pipx inject --force fray-claude ../osrs-dps/dist/osrs_dps-*.whl
```

Those two lines go together: `FRAY_CHUNKINFO` wants a *raw* export, not `fray chunkinfo`'s
envelope-wrapped `cache/reference/chunkinfo.json` (hence the extraction — see Conventions for why pointing it at
the envelope fails silently), and `FRAY_MAP_CACHE` is presence-only, its value unused.

`--export-json PATH` (or `-` for stdout, replacing the text summary) is carried by the nine
*derivation* subcommands plus `maps list`, not the four I/O ones (`fetch`/`show`/`chunkinfo`/
`heuristics`). `--recompute` is carried by those same nine and nothing else, so it means one thing
everywhere. `--limit` defaults to `None` (full
output) for `sections`/`sources`/`tasks`/`neighbours`/`diff` so piping just works, but to `10` for
`search`. See `cli.py`'s docstring.

**The `dps` extra is installed two different ways, one per venv.** `pip install -e ../osrs-dps` puts
it in `.venv` for development and the test suite; the `fray` on `PATH` lives in pipx's own venv and
needs `pipx inject` instead. An injected package **survives `pipx install --force`** (measured), so
the ordinary rebuild loop leaves it alone — but injecting copies a wheel, so a change to `osrs-dps`
needs its wheel rebuilt and re-injected, and `--force` is required there for the same reason it is
for `fray`: the version does not move between builds, so a plain `inject` silently no-ops.

`fray diff` is the one subcommand taking two maps, hence `--map1`/`--map2` rather than `--map`; both
are required, and either can name a fetched or a simulated map. It reports **both directions**, which
`fray unlock` deliberately does not — `unlock` is additions-only because adding a chunk is very nearly
monotone, and two arbitrary maps are not related that way at all. Read `delta.py` before assuming the
two commands answer the same question.

**`cache/` is sorted by purpose, and `cache/maps/` holds maps and nothing else holds maps.**
That sentence is the layout's whole point. `list_maps` used to glob `cache/*.json` and skip the
names it *knew* were not maps, so every new blob had to be remembered or it turned up in the picker
as a map called `wiki_rates` that failed the moment it was chosen — two were missed exactly that
way. A directory cannot be forgotten.

```
cache/maps/fetched/<id>.json           # from Firebase; only `fray fetch` writes one
cache/maps/simulated/<batch>/…         # rolled by `fray simulate`
cache/maps/unlocked/<batch>/…          # `fray unlock --cache-map`: one chunk added by hand
cache/reference/                       # chunkinfo, tasks_map, wiki_rates, tile_version
cache/derived/                         # pipeline.derive results, keyed by content
cache/assets/                          # section masks, skill icons
cache/gui/                             # window.json, and the browser profile
```

A batch, whichever computed kind:

```
cache/maps/<kind>/<batch>/batch.json          # seeds, rolls, `batch_id`, and the payload it rolled from
cache/maps/<kind>/<batch>/run-001/map.json    # a normal envelope carrying `kind` — the *map*, priced in full
cache/maps/<kind>/<batch>/run-001/rolls.json  # that run's per-roll ledger — with batch.json, the *simulation*
cache/maps/<kind>/<batch>/run-001/run.json    # that run's summary, which `maps list` reads
cache/maps/<kind>/<batch>/run-001/timeline.json  # per-step hours, once something paid to compute them
```

**Three kinds, and `unlocked` used to be filed under `simulated`.** This file argued for that —
both mean "this project computed it, upstream never saw it", and a third kind would have to be
taught to every removal path. What that missed is that the picker has to *say* which, and calling a
map made by adding one chunk by hand a simulation is simply wrong. `COMPUTED_KINDS` is what the
removal paths take, so a fourth kind is one line rather than a hunt.

**`batch_id` is what makes several runs one job.** Minted once per batch before any run starts and
written into *every* run, not just the summary — the directory name cannot carry it, because a name
clash renames the batch and a rename severs the link. `read_batch` recovers it from the runs when
`batch.json` is missing, so an interrupted batch is still recognisably one job.

A name is claimed across **every** kind (`_name_taken`), so `--map foo` never has to guess which
directory meant it; a clash gains `-2`, `-3`, … as before. `cache.migrate_layout` moves a
pre-split cache into this one on first touch — renaming rather than re-fetching, because the chunk
export is a 10MB download and `assets/` is fifteen hundred files pulled one at a time. It is
idempotent and identifies an old flat `cache/*.json` as a fetched map by *elimination*, which is
the reasoning this layout retires — so it happens once, there, and never on a read path.

**The estimator's numbers live in two places, and only one is in `cache/`.** `fray heuristics`
writes the scrape to `cache/wiki_rates.json` (a normal blob, refetchable, gitignored); hand-written
corrections go in **`heuristics/overrides.json`, which is checked in** so they are diffable and
survive a re-scrape (`heuristics/README.md`, also checked in, is the guide to which numbers are
worth correcting and what the three layers are). Overrides win, key by key. The export has *no* durations, rates or XP figures at
all, so every number `fray estimate` spends comes from one of those two files or a default in
`heuristics.py` — read that module's docstring on coverage before quoting a total, and
`estimate.py`'s on what `current level` means: **the map records no skill levels** (`maxSkill` is
a declared cap, `passiveSkill` is what's reachable untrained), so `estimate.infer_levels` reads a
floor out of the *completed* challenges — a ticked `Buy the Defence cape` proves 99 Defence. `experience.py`'s XP
curve is the one exact input and is deliberately not overridable.

**`dps_bridge` prices what the estimate can ask about, and nothing else.** `price_monsters` used to
be handed `sorted(chunk_info.drops)` — all **872** monsters in the export — where **188** are
reachable providers with drops and, on the real map, **11** were ever consulted. Every
`Heuristics.kills_per_hour` call in `estimate.py` is gated on `reachable_providers(derived)`
(`_kill_hours` takes its provider from it, `_superior_hours` refuses a base outside it,
`_required_kills` skips a monster outside it), so a rate for anything else is computed and can never
be spent. Restricting it left the answer **identical to four decimal places** — 3969.1204h either
way, with buckets, per-item hours and `unpriced` all unchanged — and took `enrich` from 1.26s to
0.69s. `dps_bridge` **imports** `reachable_providers` rather than keeping its own copy, so the gate
cannot drift from the thing it gates; `tests/test_estimate.py` spies on every lookup to assert
nothing asks outside it. `DpsCoverage.offered` is reported beside `monsters` because "188 monsters"
alone reads as poor coverage of the export rather than full coverage of the map.

**With the `dps` extra installed the layering is `defaults < scraped < computed < overrides`.**
`fray estimate` calls `dps_bridge.enrich`, which recomputes kill rates and slayer task rates from
the map's own BiS gear and lets them beat the scrape — the wiki's numbers assume gear and methods
(chinning, barrage bursting) a chunk map may not have. **Hand overrides still win**, which is the
point of the file; `enrich` takes the pinned keys and leaves them alone. Without the extra the
command runs exactly as before, and `fray show` reports which of the two you are getting, because
they are materially different totals — 3,969h against 2,816h on the real map.

**`fray-gui` is the second app, and it derives nothing.** It draws the world map: unlocked chunks
bright against a locked wash, a thin grid between every chunk, a hull outline around the outside of
the unlocked blob (no border between two unlocked chunks — that is `worldmap.hull_edges`), and a
delta mode where `--compare`'s gains are green and its losses red. It can also drive `fetch`,
`simulate`, `unlock` and `timeline`, which return a job id and report progress while a thread does the work.

**A simulated run carries its own past, and the timeline is what reads it.** `simulate` writes every
roll to `rolls.json` and nothing used to read it back, so a simulation could say where you end up and
not what each roll bought you. The state before roll k is `final − rolls[k:]` — **no base map, no
export, no `derive`** — so `GET /api/timeline` and `/api/view?step=` are both ~1ms and the slider
redraws as you drag it. `timeline.py` owns that arithmetic and `tests/test_timeline.py` asserts a run
replays with its base map *deleted*.

**A run is born with its timeline, because pricing a state it has already derived is free.**
`batch._Pricer` costs each state as `simulate_rolls` passes through it — measured under 5ms against
the ~0.82s `derive` the roll paid anyway — and `write_sim_run` stores the series as
`run-00N/timeline.json`. Rebuilding it afterwards would pay that 0.82s per step all over again, which
is why the callback (`simulate.simulate_rolls`'s `on_state`) exists at all; `simulate.py` still knows
nothing about hours.

**What a simulation does *not* pay for is `dps_bridge.enrich`, at ~1.29s a roll.** That is 13× the
rest of the pricing and would take a 100×50 batch from 68 minutes to 176, on every batch whether or
not anyone opens its timeline. So a run stores the wiki-rate answer and `POST /api/timeline` upgrades
it on request — **across cores, via `batch.price_steps`**, since 94% of a step is `osrs_dps`
simulating 7,335 independent fights and steps do not depend on each other. Measured on 16 steps
(8 physical cores / 16 logical): 20.0s sequential, 10.3s at 2, 5.5s at 4, 3.1s at 8, 2.7s auto —
**it plateaus at the physical core count and SMT buys 5%**, so overshooting is free and `jobs=0` can
take `os.process_cpu_count()` without guessing at the topology. Every job count gives identical
totals, which `tests/test_batch.py` pins.

**The first repricing of a run cannot reuse the simulation's cached derivations, and that is
correct.** A simulation derives from the *base* map's `MapState`; the timeline derives from the
*run's*, and `simulated_payload` moves `checkedChallenges` into `completedChallenges` and drops
`activeTasks`, so the two hash differently — and **`derive` really does return different objects**
(the `active_tasks` branch reads `state.active_tasks`), even though `estimate` comes out identical
to the penny. Excluding those fields from `derivation_key` looks like a free 0.8s a step and would
be a stale-derivation bug. Measured: a first press is 4.6s against 2.7s warm, on 16 steps. `timeline.stamp`'s **`enriched` flag records which, and `timeline.matches` deliberately
excludes it from the freshness comparison** — the cheap numbers are a coarser answer, not a stale one,
and treating them as stale would blank a perfectly good graph the moment the extra was installed.
Everything else in the stamp *is* compared, including the digest of the checked-in
`heuristics/overrides.json`, which moves without any fetch having happened. A mismatch reads as
*absent*, so the page offers to recompute rather than refusing to draw.

**A bar is what the roll cost, not how the total moved**, and the difference is the point. A timeline
walks one player's history forward, so by the time roll k lands everything roll k−1 opened is behind
them; a chunk that only makes old work *cheaper* has added nothing. Subtracting totals says otherwise
— it reports a saving as negative work, and a measured early-game run showed −2.4h on exactly that.
`timeline.added_hours` is therefore a **diff of what is being costed**: an item counts when it is in
this roll's estimate and was not in the last one, quests likewise, skills contribute
`max(0, current − previous)`. It builds a filtered `EstimateResult` and reads `.buckets`, so the
per-source clamp is the estimator's own rather than a second copy — and clamping within the new set
is right here, because if the earlier grind is finished you are not standing there any more.
**The consequence the panel must own: these do not sum to the Estimate tab's total.** `null` (nobody
computed it) and `0.0` (this roll added nothing) still have to draw differently.

**A roll only ever adds, and pricing exploits that.** Measured over 20 rolls: the reachable-provider
set grew by 0–8 a roll and never shrank, and **3,867 of 4,094 kill rates (94%) were byte-identical to
the roll before** — 16 rolls changed not one — with slayer task rates at 95%. So
`dps_bridge.enrich_incremental` keeps the previous roll's rates unless `fight_signature` moved, and
`enrich` itself is left untouched so every non-timeline caller is provably unaffected. **`kit.items`
is deliberately not in the signature wholesale**: it moved on 17 of 20 rolls because it grows with
every item the map reaches, and it feeds exactly one thing (`_charged`, swapping a *worn* uncharged
wilderness weapon), so a new potion cannot change a fight the potion is not in. `wilderness` is
excluded too — it is per monster, so membership is compared per monster instead of invalidating
everything. Slayer reuse is **per master**, keyed on which of *that master's* assignable monsters are
reachable; gating on the whole set recomputed all three masters on 10 of 20 rolls where 50 of 60
master-tables were reusable. Measured end to end: 14.5s of full pricing against 3.4s, output
identical, which `tests/test_dps_bridge.py` asserts against the real export.

**`_slices` is contiguous, reversing the striding it used to do.** Striding was right when every step
was priced from scratch — cost grew along a run, so contiguous slices handed one worker the expensive
tail. Incrementalism inverts that: only a slice's *head* is expensive, which is both more even and
the only arrangement where reuse is possible, since a strided slice never holds two consecutive
rolls. Slices overlap by one step, because a slice starting mid-run needs the roll before its head as
the baseline `added_hours` measures against.

**Deriving and pricing want opposite shapes, so `price_steps` does two rounds.** A cold `derive` is
~0.8s, perfectly independent, and wants every core; pricing wants long contiguous slices. Doing both
in one pass forced a choice and either choice cost more than the pair — short slices left the pricing
nothing to reuse, long ones left twelve cores idle through the derivations. `warm_slice` fills
`cache/derived/` across every worker first, strided; then the pricing round reads them back at ~3ms.

**A run directory holds two different objects, and the timeline wants the one it was not reading.**
A *simulation* is a fixed base plus a sequence of rolls, each read on the assumption that everything
before it is done — `batch.json` + `rolls.json`. A *map* is a world in its own right that any command
can price in full against current BiS — `map.json`. The timeline is a question about the first and
was deriving against the second, so it reached **0 of 13** of the derivations the simulation had
already cached, against **13/13** from the base.

So `batch.json` records `base_payload`, the payload it rolled from, and `cache.read_base_payload`
answers with it. **A name is a pointer that can dangle; the payload is the thing** — which makes a
simulation self-contained in the stronger sense (base plus sequence, replayable with every other file
gone) rather than trading that property away. Measured: a reprice of a fresh 20-roll simulation went
5.11s → **2.31s**, and 0.55s with the fetched base map deleted.

**The fallback chain is stored payload → `base_map` by name → the run's own payload, and all three
give the same numbers.** Only the cache-hit rate differs, so a batch written before this is slower
and not wrong. That is asserted rather than assumed, because a fallback that changed an answer would
be a much worse thing to have than a slow one. `map.json` is untouched: `fray tasks --map <run>`, the
map view and the Estimate tab all still read the full synthetic world.

**A batch of several runs is not a map, and the picker must not offer it as one.**
`cache.resolve_map_path` refuses to guess which run a bare batch name means, so selecting one 404s
*every* route and the map goes blank — a pre-existing bug the timeline surfaced. `app.js`'s
`mapOptions` makes a multi-run batch an `<optgroup>` label over its runs. A one-run batch stays
selectable, since there the name is unambiguous everywhere.

**A step and a comparison are exclusive.** Two maps and a rewind would want a third colour for
"gained by this roll but lost against the other side", which is nobody's question — so the step wins
in `mapQuery` and the strip hides itself while comparing. Switching map clears `state.step` *before*
the view loads, or the new map is rewound to a roll it never had.

**`GET /api/unlock` and `POST /api/unlock` are the two halves of one thing.** The GET prices a
candidate and keeps nothing; the POST saves the world it was describing, through `batch.save_unlock`
so the CLI's `--cache-map` and the panel's **Unlock** write the same metadata. **Fetch takes a typed
id, not the selected map** — every source-chunk map is a public read, so the ids worth fetching are
exactly the ones not yet in the picker; blank means `cache.DEFAULT_MAP_ID`, which is the fourth
constant crossing into JavaScript with a test holding the two in agreement.

**All fifteen CLI subcommands are reachable from it.** `GET /api/{maps,view,revision,summary,
neighbours,chunk,sections,unlock,diff,search,estimate,tasks,tiles,areas,derived,jobs,timeline,roll,reference,build}` and
`POST /api/{fetch,simulate,unlock,timeline,cancel,refresh,maps/remove,derived/prune,window}`. The panel's tabs are tasks / chunk / find / estimate /
maps, and `?map=&compare=&candidates=1&sections=1&step=&tab=` reproduces a view.

Things worth knowing before changing it:

- **Clicking a roll frames it; a separate control breaks it down.** They cannot be one gesture - a
  dialog would cover the map it had just framed - so a click moves the slider, selects the rolled
  chunk and flies the camera to it, and *Details* opens the overlay. That overlay reads
  `GET /api/roll`, which carries **task names** where `/api/timeline` carries counts: one roll of the
  real export opened 239 tasks, so every name for every step would be most of a megabyte spent to draw
  a bar chart. The bars also need `pointer-events: none` — they are painted over their own hit areas,
  so without it hovering a tall green column did nothing while the empty background either side worked.
- **A simulation counts rolls and can be stopped, and stopping keeps what it rolled.** `2/3 runs` on a
  3×100 job is three updates across four minutes, so progress is `X/300 rolls` — `simulate_rolls`
  gained `on_roll` beside the `on_state` pricing uses, which also reports the baseline and would start
  the count at one before anything had happened. **`POST /api/cancel` is a request, not a kill**: the
  work stops where it safely can (the roll it is on), so the job stays `running` until it agrees and
  the page keeps polling. It ends `CANCELLED`, which is **not** `FAILED` — the user did it, and what
  it kept is an ordinary cached map. A partial run's ledger is short in exactly the way an exhausted
  roll pool already leaves it, so `simulated_payload` needs no special case and `tasks`, `estimate`
  and the timeline all read it unchanged; only `run.json`/`batch.json` record `cancelled`, which is
  why `maps list` is where "you stopped this" gets said. **Per roll inline, per run when pooled** —
  `--jobs > 1` puts the callback in a worker with no channel back, and a `multiprocessing.Queue`
  through `RunSpec` would buy a smoother CLI bar for the one piece of shared state this module is
  built without.
- **The wiki rates are fetched on open when they have never been fetched, and only then.** Without
  them every hour in the Estimate tab falls back to a default and the total is thousands of hours
  light — the panel would say so in small print beside a confident-looking number, which is a poor
  first impression to buy for eighteen requests. `warmReference` fires once per page load and only on
  *absent*; a re-scrape is a decision and the Maps tab has the button. **The 10MB chunk export is
  deliberately not fetched this way** — that is `fray chunkinfo`'s to start. `GET /api/reference` is
  what the page asks: a `stat` and the envelope's first few hundred bytes, so finding out whether the
  export exists never reads it.
- **The page watermarks itself with the server's install, not its own.** `pipx install` without
  `--force` is a silent no-op, so `fray`/`fray-gui` on `PATH` can be an older build than the checkout
  they came from with nothing on screen to say so — which is what `GET /api/build` and the CLI's
  first line exist to fix. Baking the stamp into `app.js` at build time would answer about the *page*
  where `--host` may put the browser on another machine entirely, so the answer is the server's. The
  relative age is re-rendered on the two-second poll rather than only at boot, or a tab left open all
  afternoon goes on claiming the install happened a minute ago. **An editable install dates the link,
  not the code**, so the wording changes with the kind rather than calling that "installed".
- **A request is milliseconds, so nothing is cached.** Rendering needs only `chunks.unlocked` — a
  chunk's square is fixed by its id — so there is no `ChunkInfo` parse and no `derive`. Every
  request re-reads the map file, which is what makes a `fray fetch` in another terminal appear in
  the browser two seconds later with no invalidation machinery at all.
- **The map's delta uses `delta.diff_names`, not `compare_maps`.** The latter derives *both* sides
  whatever `branches` says — the `derive_with(...)` calls are arguments to `compare` — so it would
  spend ~2s on a set difference. `/api/diff` is where it belongs and the only route allowed to be
  slow: the **Diff** button asks what those chunks actually *gave* you, which is a question about
  sections, tasks, sources and BiS and has no cheap answer.
- **The world drawn bright is the *compared* map's, not the base's.** `added`/`removed` are the same
  either way, but a comparison asks what the base *becomes* — so the hull traces the compared side's
  own set (`build_view` outlines everything that is not `removed`) and `app.js` washes a removed
  square like any other locked one before tinting it red. Leaving it bright draws a world neither
  map is in.
- **Two constants cross into JavaScript with nothing enforcing agreement** — the `Edge` bitfield and
  the projection, both plain integers over JSON — so `tests/test_gui_server.py` reads `app.js` and
  asserts them against the Python. The same file asserts the canvas is given an explicit size, since
  `inset: 0` does not stretch a replaced element and the failure is silent. A third assertion pins
  that **no `raw()` interpolation lands inside an attribute**: `data-tip="${raw(...)}"` splices
  unescaped quotes through the closing quote, and the markup after it appears on screen as text.
- **Three interface rules that each replaced a bug**, all pinned by `tests/test_gui_server.py`:
  **one tooltip system** (`data-tip`, never `title` — both at once shows two tooltips, and only the
  custom one can carry a heading, a note and a key hint); **chip strips record what is *off*, not
  what is on** (holding the selected set froze it at whatever the first chunk happened to contain,
  so a category nobody had seen yet came up unchecked — click narrows to one, shift adds, ctrl
  removes); and **an action's reply shape decides whether it is polled** — `fetch`/`simulate`/
  `unlock`/`timeline`/`refresh` return a job id, `maps/remove`/`derived/prune`/`window`/`cancel` return the
  result, and reading `{ job }` off all of them polled `/api/jobs/undefined`, whose 404 silently swallowed
  the refresh callback and left deleted maps on screen. A finished job reports `summariseReply(result)`
  rather than "Finished", because `claim_batch` suffixes a clash and the name that landed is not
  always the name that was typed.
- **Every length in `style.css` comes from one scale** (`--s1`…`--s6`, `--r1`…`--r3`), and a test
  asserts no token is used undefined or defined unused. Panes reserve their scrollbar with
  `scrollbar-gutter: stable`, because Chrome's overlay bar sits *on top* of the last characters of a
  long task name.
- **`gui/panels.py` is `app.js`'s pure module**, and the reason it exists is that `bis`,
  `task_classification` and `other_tasks` offer three shapes where the panel needs one. Walking
  `Object.keys` over a *category envelope* is what made the first tasks tab print `active_total`
  and `groups` as if they were task names. New shaping goes there, not into the JavaScript.
- **The map is the OSRS wiki's cartography tiles, and the browser loads them — this project never
  touches one.** `/api/tiles` hands out a URL *template*; `app.js` puts it in an `Image`. That is a
  licence decision, not an optimisation: the tiles are CC BY-NC-SA 3.0 against this project's MIT,
  so caching them under `cache/` or re-serving them off loopback would make this a redistributor of
  NonCommercial artwork, where linking makes it a page with a picture on it. `MAP_TILE_ATTRIBUTION`
  is on screen for the same reason, and `tests/test_gui_server.py` asserts no tile route exists so
  a later "let's cache these" cannot pass review by looking like a speed-up.
  **The scheme fits this project almost exactly**: `256 / 2**z` game tiles per 256px tile with y
  counting *northward*, so at `NATIVE_TILE_ZOOM = 2` one tile **is** one chunk and its index is the
  chunk id decomposed. `drawTiles` picks the pyramid level from the on-screen cell size, and **falls back up the pyramid
  when a tile is not there** — every level covers the same world, so the level above holds it at half
  the resolution, and blurry beats a black square. That also covers the case it was written for: a
  browser `Image` cannot tell a 404 from a dropped connection, so a miss is retried `TILE_TRIES`
  times before it is remembered, and one unlucky request no longer blacks a square out for the
  session. The sub-rectangle's **y is flipped and its x is not** (`step - 1 - (y & mask)`), because
  tile indices count north while image rows run south; a test pins that, and getting it backwards
  mirrors each fallback into a still-plausible piece of map. Two
  things bite here — `worldToScreenY` needs `MAX_REGION_Y + 1` because it maps an *edge* where
  `gridToChunk` numbers a *cell*, and the version comes from
  `MediaWiki:Kartographer-map-version?action=raw`, the message Kartographer itself reads, because
  no index of renders exists anywhere. Both have tests; the first was found by comparing the canvas
  against a raw tile (0.016 mean channel difference aligned, 13.7 one pixel out).
  `FRAY_TILE_VERSION` pins a render when that message moves.
- **The tile set is `-1`, "Full Map", not `0`, "Gielinor Surface" — and that is what puts the
  dungeons on the grid.** Where the two overlap the tiles are byte-identical, so nothing is traded
  away, and `-1` is what the wiki's own `World_map` asks for. The grid is therefore the *whole*
  region rectangle (x 14–66, y 18–197, 53×180) rather than the surface's, underground sits north of
  the overworld because of the y-flip, and **1,905 of the export's 1,919 numeric ids are placeable
  against 1,176 before**. A plane selector picks the floor; it changes the tiles and nothing else,
  since a region contains every plane. **Above the ground floor the two are separated per pixel**, because a
  plane-N tile is one flat image holding the ground floor faded back *plus* this floor's features —
  no transparency, and `basePlainTileURL` is the same URL here, so there is no overlay tile to ask
  for. Darkening the tile darkens both, which was the first attempt and the wrong one. The fade is
  linear, so `composeFloor` fits `planeN ≈ a·plane0 + b` per channel per tile (`a` runs 0.13→0.52,
  so it cannot be assumed), sinks what fits and leaves what misses. Measured on Lumbridge plane 2:
  8,901 floor pixels untouched at luminance 77, 56,635 ground pixels 60 → 17. It costs ~3ms a tile,
  so it is cached and rationed by `PLANE_COMPOSE_BUDGET` per frame; unbudgeted tiles draw
  unseparated rather than blank. What is left unplaced: nothing.
- **A named area is placed by the export, not by matching its name.** `Abyss` has no coordinates,
  but the export stores such a place *twice* — once under its name holding the contents, and once as
  one or more ordinary numbered chunks carrying `Name` — and a numbered chunk is a region, so it has
  a square. `chunkinfo.area_names()` inverts that (`6727` → `Grotesque Guardians' Lair`); all 315
  named areas resolve, 301 land somewhere drawable, and **502 of the 719 placeable underground
  chunks get a label**, which is what stops the dungeons being a field of unnamed squares. No fuzzy
  tier, because there is nothing to be fuzzy about — contrast `heuristics.py`, whose joins really do
  span two vocabularies. The mapping is many-to-one (Hallowed Sepulchre is 24 regions) but **no
  region carries two names**, so inverting is lossless. `build_view(areas=…)` resolves a named id to
  those regions and **collapses it onto the numeric cell** when a map holds both, since two cells on
  one square would double the hull and the count. **A `<parent>#<part>` with nowhere to go borrows its parent's regions**, which is what places the
  last 14 — synthetic ids like `109001` carrying `Brimhaven Dungeon#Section 1` and nothing else, at
  regions no tiling covers. The condition is "has no square", **not** "contains a `#`": 59 named
  areas carry the separator and 52 already have their own region, so firing on the separator would
  throw away detail the export went to the trouble of recording. Given the whole export that leaves
  **2,234 ids → 1,905 cells and an empty `skipped`**, so `skipped` is now a statement about a map
  rather than about the export. `/api/view` only pays the 10MB parse when the map actually holds a
  non-numeric id; `/api/areas` serves the whole mapping once, map-independently.
  **Never read `maps.runescape.wiki/osrs/data/dataloader.json`** — it is the superseded standalone
  app's config, pinned at a 2019 render, and believing it is what made an earlier pass conclude the
  tiles were seven years stale. The current sources are `wgKartographerDataConfig` (read off any
  page embedding a map) and `versions/<v>/basemaps.json`.
  **The 1,534 section masks and 24 skill icons are the same argument with a different answer to
  *when*:** they are proxied one file at a time, on the request that first draws them, because a
  chunk has a handful of sections and nobody opens all of them. `cache.section_overlay_path` is the
  **one asset name that reaches the disk from a URL**, so it is matched whole against an alphabet
  holding no `.` and no `/`. A mask's *opaque* pixels are its section — a `tRNS` chunk makes grey 0
  transparent — which is what lets several composite onto one square. An **unsplit** chunk has no
  mask at all, so `server.WHOLE_CHUNK_SECTION` (`"*"`) tells the browser to fill the square itself;
  without it the overlay left 664 of the 1,176 placed chunks bare, which reads as missing data.
- **The window's size is remembered by us, and has to be.** An app window's bounds are stored per
  app id, and Chrome derives that id from the URL — which carries the port and the `?map=` deep
  link, so every launch looks like a new app to it and nothing is ever restored. The page reports
  its geometry to `/api/window` and `browser.window_flags` reads it back. A first run opens
  **maximised, not fullscreen**: closing the window is how you stop the server, and fullscreen hides
  the control that does it.
- **Serving it beyond loopback needs the `Host` check to know what the bind was named.** The check
  exists to close DNS rebinding, so it cannot simply be dropped — but hardcoded to loopback it did
  not refuse a remote page, it *half* served one: every panel rendered and every POST 403'd, which
  reads as a broken GUI rather than as a policy. `--host` therefore seeds `Context.allowed_hosts`
  (`gui.allowed_hosts`, pure and tested without a socket), `--allow-host` adds a name the bind does
  not spell, and a **wildcard bind names nothing** — `0.0.0.0` is every interface, not the address
  anyone types, so it still refuses until told what to expect. Nothing is resolved on a request path:
  that would be a network call from the module that makes none, at the request of whoever sent the
  header. There is still no token, so **the address chosen is the whole of the access control**; an
  ssh `-L` forward needs none of this and is the better answer when it fits.
- **The window's lifetime is the server's, by one of two mechanisms and never both** — or by neither,
  under `--keep-alive`, which is what a server left running over ssh wants: the heartbeat stops it
  fifteen seconds after a laptop's tab closes, which is right for a closed tab and wrong for a
  session you mean to come back to. With a
  Chromium-family browser present (Chrome, Edge, Brave, Chromium, Vivaldi, Opera) it opens an *app
  window* — `--app` plus its own `--user-data-dir`, the latter being load-bearing rather than tidy:
  without it Chrome hands the URL to a running instance and the launched process exits at once,
  stopping the server the moment it started. Otherwise it opens a tab and a **heartbeat** stops the
  server `IDLE_TIMEOUT_SECONDS` after the last request; `--tab` and `--no-browser` take that second
  path deliberately, so it is the one to test against. Neither is a dependency — `dependencies` is
  still empty, and a machine with only Firefox takes the second path. A running job holds the server
  open either way.

**Caching the `EstimateResult` is the obvious move and the wrong one.** Measured on the real map,
`estimate` over a `Derived` is **3.1ms** and `dps_bridge.enrich` is **662ms** — so caching the answer
saves 3ms and caching the *pricing* saves 662. `derived_cache.cached_enrich` therefore stores the
enriched `Heuristics` (21KB) rather than the estimate (which is also only valid for one set of level
overrides). `fray estimate` goes 1.72s → 0.18s, the GUI's estimate panel 0.81s → 0.03s, and
repricing a 21-step timeline a second time 5.6s → 0.6s.

**Its key is a strict superset of the derivation's, and has to be.** `enrich` reads the derived
state *and* the scraped rates, `heuristics/overrides.json` and the calculator itself, none of which
`derive` has heard of — so `PricingDigests` carries three more digests and `enrichment_key` tags
itself `enrichment` so it cannot collide with a derivation sharing the directory. **The `osrs-dps`
version is not usable for the library digest**: it is installed editable, so it reads `0.0.1`
however much of the calculator changes underneath. `dps_library_digest` hashes its 16 source files
instead, which costs 3ms and actually moves. Those three digests are deliberately *not* folded into
`Digests`, or a re-scrape would throw away every stored derivation for nothing.

**`cache/derived/` is a third thing, and not a map.** It holds `pipeline.derive`'s *results*, one
zstd-compressed pickle per key (~0.12MB each), so a repeat command costs ~0.15s instead of ~1.05s.
The key is a hash of everything `derive` read — the `MapState` fields, the unlocked set, and content
digests of the chunkinfo export and tasks map — which is why one entry serves `sections`, `sources`,
`tasks`, `neighbours` and `search` on the same state, and why `fray fetch` invalidates without
anything having to notice. `--recompute` bypasses it; `fray derived list|clean` inspects and ages it
out by last read. `fray simulate --cache-behaviour all|extremities|none` chooses how much of a
simulation to keep (default `all`, ~118KiB per roll state — a repeat of a seeded batch then costs
0.3s instead of 7.8s; `extremities` keeps only each run's first and last state, the last being the
one the saved simulated map holds). **`derived_cache.py` owns all of that — read it before changing what `derive`
returns**, because a result dataclass gaining a field must invalidate old entries (it does: the key
includes a hash of those classes' shapes). `derive` itself stays uncached and pure, which is what
keeps the opt-in oracles an honest signal.

`mypy` and `pytest` are invoked differently on purpose: mypy is the *system* install (there is no
`.venv/bin/mypy`), configured with `python_executable = ".venv/bin/python"` so it can see pytest's
stubs — which is why it must run from the repo root and needs the venv to exist. pytest is only a
`dev` extra inside the venv and is **not** on `PATH`, so a bare `pytest` fails with
"command not found"; call `.venv/bin/pytest` (or activate the venv first).

`cache/` is gitignored — including `cache/maps/` — so a fresh clone has no data and
`fray show`/`fray sections` fail until `fray fetch`/`fray chunkinfo` run. `fray chunkinfo` downloads ~10MB; `--chunkinfo PATH` or the
`FRAY_CHUNKINFO` env var point `fray sections` (and later commands) at an existing local export
instead.

`pyproject-build` (from the `build` package — `pip install build` or `pipx install build` if it's not
already on `PATH`) writes `dist/fray_claude-<version>-py3-none-any.whl`, independent of the `.venv`
editable install. `pipx install` installs that into its own managed venv and puts `fray` on `PATH` for
use outside this checkout. The `--force` is load-bearing, not optional: the version in `pyproject.toml`
doesn't change between builds, so a plain `pipx install dist/*.whl` on an already-installed package is
a silent no-op ("already seems to be installed") — it will not pick up new code.

## Conventions

- PEP 8, type hints on all functions
- **Design rationale goes in the module docstring, next to the code it constrains** — not here. This
  file is for what spans modules or can't be discovered from them. When a port turns out to be wrong,
  correct the docstring rather than appending a note: several already record a superseded claim
  explicitly, which is worth keeping only where the wrong version is the tempting one.
- **`README.md` is the user-facing counterpart and describes every subcommand and most flags**, so a
  new subcommand, a renamed flag or a changed default lands in three places, not one: the module
  docstring (why), this file (what spans modules) and the README (what a user types). It is the one
  that drifts, because nothing in the test suite reads it.
- Commit after completing a change, and try to push
- **Always finish a task by rebuilding and reinstalling, then checking it took.** The `fray` and
  `fray-gui` on `PATH` live in pipx's own venv, so until this runs they are still the *previous*
  build — and every manual check you or the user then makes is of old code:
  ```
  rm -rf dist build && pyproject-build && pipx install --force dist/*.whl
  diff "$(pipx environment --value PIPX_LOCAL_VENVS)/fray-claude/lib/python3.14/site-packages/fray_claude/cli.py" src/fray_claude/cli.py
  ```
  `--force` is not optional (see Commands: the version never moves, so a plain `pipx install` is a
  silent no-op), and the `diff` is the half that is easy to skip — a build can succeed and still
  leave `PATH` pointing at yesterday's wheel. It should print nothing.
- Tests are pytest, in `tests/`, named after the module under test (`tests/test_summary.py`). No test
  touches the network, and none the real `cache/` bar the six oracles that read it through
  `cache.project_root()` (`test_active_tasks`, `test_other_tasks`, `test_neighbours` x2, `test_bis` x2).
  Every one of those is gated on **both** `FRAY_CHUNKINFO` and `FRAY_MAP_CACHE` — the latter is
  presence-only, a flag saying "this checkout's own `cache/` is populated, read it", since the map is
  not read from its value. Gating a real-cache test on `FRAY_CHUNKINFO` alone is a bug, not a shortcut:
  it makes the test *fail* with `CacheMissError` on a fresh clone instead of skipping, which is what
  the two `test_bis` oracles used to do. To add one, copy an existing pair of decorators verbatim. Pass
  `cache.py`'s `root` a `tmp_path`, and monkeypatch `urllib.request.urlopen` (`tests/test_api.py`)
  or `fray_claude.cli.fetch_map` (`tests/test_cli.py`).
  Any test calling `cache.read_chunkinfo()` without an explicit `override` must
  `monkeypatch.delenv("FRAY_CHUNKINFO", raising=False)` first, or an ambient env var shadows `tmp_path`
- A test that needs the real (~7MB) chunkinfo export is opt-in, not run by default: build fixtures by
  hand for the normal suite, and gate the real-export check on `FRAY_CHUNKINFO` with
  `pytest.mark.skipif`, so a fresh clone stays green. **These are the tests that catch real defects**
  — they compare against upstream's own recorded answers, so run them (with `FRAY_CHUNKINFO` set)
  before trusting a change to `sections`/`sources`/`challenges`/`bis`/`active_tasks`/`other_tasks`,
  and treat a failure as a bug in this code rather than a stale oracle.
  `FRAY_CHUNKINFO` must point at a *raw* export file, not this project's own envelope-wrapped
  `cache/reference/chunkinfo.json` (`fray chunkinfo`'s output) — `cache.read_chunkinfo`'s override path reads it
  directly with no `["data"]` unwrapping, so pointing it at the envelope silently produces wrong or
  incomplete results rather than an error. Extract the raw export first if working from the cache
  (`json.load(open("cache/reference/chunkinfo.json"))["data"]`).
- **`User-Agent` differs by host, deliberately.** Firebase and GitHub get none — those endpoints are
  public and unauthenticated, so there's nothing to disguise and a header would only publish
  information nobody asked for. The **OSRS wiki gets `api.WIKI_USER_AGENT`, and requires it**: an
  anonymous request there is answered with HTTP 403 (measured, not assumed), because the wiki applies
  MediaWiki's user-agent policy asking automated clients to identify themselves. Both rules come from
  one principle — send what the endpoint needs to serve the request, and nothing more about who is
  asking. The header names the project and its repo, never the user.
