# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

fray-claude is a CLI that reads state from the source-chunk web app, caches it locally, and runs
offline operations on that cache. source-chunk is upstream and read-only from here.

**Two apps, one distribution.** `fray` is the CLI; `fray-gui` is a local server plus a browser
front-end that draws the world map — see the GUI paragraph below Commands. The library both use is
six subpackages, and there is still **no `core/` and no second distribution**: three pyprojects would
buy independent versioning nobody needs, and a subpackage can be lifted out on the day someone
actually wants to reuse it.

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
`sections` -> `sources` -> `challenges` -> `bis` -> `active_tasks`/`other_tasks` (all in
`derive/`), wired by
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
| `remote/api.py` | The network. `FetchError`. An unknown map is HTTP 200 + bare `null`, never a 404. Four hosts: Firebase, upstream's `gh-pages`, the OSRS wiki (which **requires** a `User-Agent`) and one published Google Sheet. **The map tiles are a fifth host it never calls** — `MAP_TILE_URL` is a template the browser uses; see the GUI paragraph. |
| `remote/wiki.py` | Wikitext template parsing, plus `map_tile_version` over the map page's rendered *HTML*. Pure. Quest length is in `{{Quest details}}`, **not** `{{Infobox Quest}}` — the tempting wrong template has no `length` and so returns `None` for every quest without erroring. |
| `model/experience.py` | The exact 1–99 XP curve, closed-form. **Not a heuristic and not overridable** — that separation from `heuristics.py` is the point of the module. |
| `remote/scrape.py` | The ~18 requests that build the scraped layer, and the coverage it reports. **Both apps run it** — `fray heuristics` and the GUI's Maps tab — so the two cannot write different files. Decides no rate; `heuristics.py` does that. |
| `remote/skill_tables.py` | Agility, Thieving, Firemaking and **Woodcutting** rates, from the wiki tables (`Shortcuts`, `Agility`, `Stall/Thievable`, `Thieving`). Pure wikitext-table parsing with a depth-aware cell splitter, because `{{Coins\|{{GEP\|x\|10*13.8}}}}` is full of `\|` that are not cell breaks. **These are the two skills `{{Recipe}}` cannot describe** - both have zero rows in the wiki's recipe bucket. Owns `COURSE_ALIASES`, the 4 spellings the export gets wrong (`Canafis`), and `parse_woodcutting`, whose 16 rows join **all 16** on `Output` and take the **bottom** of a published range because the top is 2-tick manipulation. |
| `remote/stores.py` | What a shop charges and **in what currency**, from the `storeline` Bucket. 6,326 lines, of which 4,438 are coins and 126 Tokkul; the rest are points and tickets nobody converts. The API caps a query at 5,000 rows whatever `limit` says, so it pages with `offset`. Joins 403 of the export's 435 shops and prices 3,798 of its 4,163 stock lines. |
| `remote/farming.py` | The wiki calculator's crop table, `Module:Skill calc/Farming`, read as raw Lua - 76 crops with level, per-item xp, plant xp, seed and patch type. Parsed by **brace matching, not by splitting on `name =`**: every crop's `materials` has a name of its own, and a split ends each crop before the `type` that says which patch it goes in. |
| `costing/farming.py` | Farming as a **schedule rather than a rate**. Owns `DEFAULT_HARVESTS_PER_DAY` - fruit tree 1, tree 3, cactus 3, bush 3, allotment 8, herb 8, hardwood 1/3, redwood 1/7 - and reports two numbers that measure different things: `active_hours` (clicking, goes in the bucket) and `days` (calendar, reported beside it and never added). Hops, flowers, belladonna, spirit trees and celastrus are **absent** from the schedule rather than zeroed. |
| `remote/prayer.py` | What a bone pays and what an altar multiplies it by: `{{Prayer info}}` across its 193 transclusions (41 bones of 195 invocations - the rest are spectral, bonemeal, reanimated or **ashes**, which are scattered rather than buried) plus the seven altar pages. The oak altar states its base as the word *normal*, so an **unstated base is 100%** rather than a parse failure, and the teak page carries a third percentage that is not a multiplier at all. |
| `costing/prayer.py` | Prayer, where **the rate is not the question and the bone supply is**. Burying is two ticks and an altar one, so an hour is 3,000-6,000 bones whatever else is true; what decides the climb is the *collection*, priced through `estimate.material_seconds` like a recipe's materials. Owns `CHAOS_ALTAR_CHUNK` - **four of the export's five `Chaos altar (Prayer)` objects are prayer-point recharges**, so the training one is pinned to region 11835 by contents rather than by name - and the 7x it works out at (3.5x an offering, 50% bone save, so two offerings a bone). |
| `costing/heuristics.py` | Every hand-correctable number, and the `defaults < scraped < overrides` merge. Owns the joins and their `exact`/`contained` provenance; **no fuzzy tier**, by measurement — read the docstring before adding one back. |
| `costing/slayer.py` | Slayer's rate, which is a *distribution* not a chosen method: a time-weighted mean over what a master assigns. Also owns `superior_rolls_per_hour` — the shared `SuperiorDropTable+` is one pool per master, not one per superior. **Masters are gated on their NPC being reachable** — without that it quoted Duradel on a map holding none of him. Reports `coverage`, because renormalising over reachable tasks flatters a sparse map. |
| `costing/estimate.py` | The four buckets — quests, boss drops, activities, skilling — over the **active** set. **Costs the unique *item*, not the task** — one whip answers three tasks — and **clamps per source**, since items off one monster are earned in parallel. Owns the item walk, its bounded `Output` recursion, the `unpriced` list, and **three gates** — monster reachable, slayer task assignable, master reachable. Read the docstring before pricing anything off `WorldIndex`, which spans the whole world. Skilling is `costing/training.py`'s; what stays here is the loop and `unpriced_skills` — Attack, Defence, Hitpoints and Ranged have **no training method anywhere in the export**, and were being costed at zero. |
| `costing/levels.py` | `infer_levels`/`goal_levels`/`reachable_providers` and the gating helpers. Separate because `dps_bridge`, both apps and `runs/batch.py` want exactly these and were importing the whole estimator to get them. **The map records no skill levels** — `infer_levels` reads a floor out of the completed challenges. |
| `costing/training.py` | How fast a skill goes, and why. **A climb is priced band by band as methods unlock**, walked on the XP axis so a quest reward shortens it and raises its start in one operation. The step function is a running maximum, so **the floor can only ever be the first band** — which is what keeps it visible. Also `quest_xp_grants`, whose grammar is not just skill names (`Attack\|Defence\|Strengthx4` is four lamps). |
| `store/cache.py` | The disk. `CacheMissError`, the `map_id`/`fetched_at`/`source`/`kind`/`data` envelope, the `--chunkinfo`/`FRAY_CHUNKINFO` override, and the purpose-sorted layout below (incl. `--map` resolution across kinds, atomic writes, the cross-kind batch-name claim and `migrate_layout`). |
| `store/build_info.py` | Which install is running, and when it was made: the `*.dist-info` mtime (pip writes those fresh, so it dates the *install*, not the wheel), `wheel`/`editable`/`source`, and the one-line watermark both apps print. Never raises and never guesses a date. |
| `model/firebase.py` | The Firebase-safe string codec, both ways. `decode_challenge_keyed`'s mixed `t_N`/literal key handling; and `encode_string`/`encode_key`, which the GUI's edit mode needs to write a tick back. **The encoding is not canonical and does not need to be** - upstream writes a space as `-_-20` where this writes a space - so the property asserted is `decode(encode(name)) == name`, over all 49,721 interned names. `encode_key` deliberately does **not** intern to a `t_N` id: upstream interns lazily, so a literal is a shape it already produces. Run any payload branch through it before believing it. |
| `model/chunkinfo.py` | Typed, tolerant accessors over the parsed export. Build **one** `ChunkInfo` per invocation — parsing the ~7MB export is the expensive part. |
| `derive/sections.py` | Which sections of the unlocked chunks are reachable, plus named-area unlocking. `sectionsLimits` deliberately lives in `neighbours.py` instead. |
| `derive/graph.py` | The export's `sections` branch as a **directed** `(chunk, section)` graph, with each edge's `sectionsLimits` gate pre-bound. Shaped for the not-yet-written pathfinding search. |
| `model/rates.py` | OSRS drop-rate string parsing/formatting, matching JS's rounding because the output lands inside task names — **and its division**, so a zero denominator is `inf` rather than a `ZeroDivisionError`. |
| `derive/sources.py` | What the unlocked chunks make available (`SourceIndex`). Applies `taskUnlocks` to items *and* entities, so availability depends on challenge validity. |
| `derive/challenges.py` | Which challenges are valid (`ChallengeResult`) — a two-phase fixed point over 28 of 29 categories. **`BiS` is never evaluated here**; read `pipeline.Derived.bis`. Also **where every derivation command spends its time** — read the docstring's static/dynamic gate split before touching the loop. |
| `derive/task_names.py` | `strip_task_markup`: a task name as a person reads it. The raw `~\|...\|~` form is the key everywhere else, so this is display-only and applies to challenge/task names **only** — other branches use `~` and `\|` for real. |
| `derive/bis.py` | Best-in-slot per (combat style, slot). Inherently **non-monotonic**: recomputed fresh per state, never accumulated. Scores **set effects** (Obsidian only — the rest are table rows nobody could verify) and honours `Show Best in Slot 1H and 2H`, both of which only a second map exercised. |
| `derive/active_tasks.py` | Per-skill active/obsolete/completed classification. A *display* winner only — it never changes `ChallengeResult.valid`. |
| `derive/boosts.py` | Temporary skill boosts. With `rules['Boosting']` on, **every** level comparison upstream makes is boosted, so this is a dependency of `challenges.py`/`active_tasks.py`, not a feature. |
| `derive/other_tasks.py` | The three non-skill categories, `Diary`/`Quest`/`Extra`. No single winner — upstream renders every valid, uncompleted one. |
| `derive/pipeline.py` | `MapState` + `derive`. Owns the **loop** where upstream's area-unlock circularity lives, so the modules above stay one-directional. Raises `ConvergenceError` rather than returning a truncated derivation. |
| `derive/unlock.py` | What one candidate unlock adds, by diffing two `derive` calls. **Owns the project's attribution rule** and its one exception. Additions-only, and only over one `MapState` — for two arbitrary maps read `delta.py`. |
| `derive/delta.py` | The **symmetric** comparison of two derived states, over all six `Derived` branches. Owns the diff primitives `unlock.py` projects down to its one-directional view; the two must agree, which `tests/test_delta.py` asserts. |
| `derive/neighbours.py` | Which chunks are eligible to unlock next, and upstream's canvas numbering (**descending chunk id, 1-based**). Owns the `sectionsLimits` gate. |
| `runs/timeline.py` | Replaying a run one roll at a time, and `added_hours` — what a roll *cost*, as a diff of what is being costed rather than of the totals. **A run is self-contained** — the state before roll k is `final − rolls[k:]`, so stepping needs no base map, no export and no `derive`. Owns the delta series and the rule that step 0 is a baseline rather than a roll. |
| `runs/simulate.py` | Seeded chunk-roll simulation: the bootstrap pool, plus the dispatch to `neighbours.py`. Records are never revisited by a later roll. `simulated_payload` turns a finished ledger back into a map payload — read its docstring before changing which branches it touches. |
| `model/edits.py` | A tick written back into a payload — **the one place this project writes to upstream's data rather than reading it.** Pure. The danger is not complexity but silence: a mis-encoded key derives as though the task were never ticked, and nothing errors. Stores by encoded name rather than minting a `t_N` id, because upstream interns lazily and a literal is a shape it already produces. |
| `runs/batch.py` | N simulations from one state, each cached as its own map. Owns seed derivation and **both** `ProcessPoolExecutor`s in the project — `run_batch` for rolling, `price_steps` for costing a timeline (two rounds: `warm_slice` strided across every core, then `price_slice` over long contiguous slices). `--jobs` must never change a result, either of them. Also `save_unlock` and `save_edit` — batches of one over the shared `_write_one_run_batch`, so there is still exactly **one** writer of the run metadata both apps read back. An edit's ledger records its chunks and **no attribution**: nothing derived them, and inventing a task count for a hand edit would manufacture the kind of number this project refuses everywhere else. |
| `store/derived_cache.py` | The on-disk cache of the **two** expensive per-state computations: `cached_derive` and `cached_enrich`. Owns both keys (a hash of every input each reads), the zstd+pickle codec, and `CacheBehaviour`/`RollCache` — which of a simulation's states to keep. Pure bar the bytes, which `cache.py` writes. |
| `derive/search.py` | World-wide fuzzy search over the *raw* export — all 5 item routes, so a strict superset of what `fray sources` can list. |
| `model/summary.py` | Pure reductions over a raw payload. Extend this, not the CLI. Also home to `format_age` (both apps render ages, and two copies of the bucketing would disagree) and `_mapping`, the tolerant dict accessor eight other modules import despite the `_` — Firebase omits empty containers, so every lookup anywhere must survive a missing branch. |
| `remote/wikitable.py` | Reading a wikitable. Shared by the two modules that parse them; owns the depth-aware cell splitter (`{{Coins\|{{GEP\|x\|10*13.8}}}}` has four `\|` and none is a cell break) and `column_index`, which resolves a `colspan` header against the width the data actually uses. |
| `remote/combat.py` | Monster hitpoints and xp multipliers (one `infobox_monster` Bucket query, 1,382 monsters, 361 with a non-zero bonus **as a percentage**), plus the autocastable spells. **`infobox_spell` cannot tell an attack spell from a utility one** - Fire Surge, Charge and Vengeance have identical infoboxes and the categories disagree - so the filter is the wiki's own layout: the table with a max-hit column. Taking the highest-xp "combat" spell picks Charge, at 2.4x. |
| `costing/combat_xp.py` | Combat XP, which is damage and almost nothing else: 4 per damage melee/Ranged, **2 for Magic**, 1.33 Hitpoints, plus the spell's base xp per cast. Owns three gates that each removed a wrong answer: `farmable_providers` (**reachable is not farmable** - a raid room is fought once per raid), `spawn_caps` (the export counts spawns per chunk, so a map holding two of something cannot supply 900 kills an hour), and `hitpoints_credit` (**Hitpoints is earned by the other combat climbs, not beside them**). Refuses a monster whose kill rate is only a default. |
| `costing/dps_bridge.py` | The seam to `osrs-dps`, which prices a kill from the gear `bis.py` reaches instead of a money-making guide. Prices **only `estimate.reachable_providers`** — 188 of the export's 872, because every `kills_per_hour` lookup is gated on that set and the rest is thrown away. `enrich_incremental` + `fight_signature` keep a timeline's previous roll where nothing that decides a kill has moved; `enrich` stays untouched. **Optional import** — check `DPS_AVAILABLE`, never assume it. `enrich` is the one entry point a command needs. Owns the export→library conversions (`magic_damage` is a display percentage here and tenths of a percent there), the overhead model, the monster-name join and its `exact`/`variant` provenance, and the refusal of fight *phases* and group bosses. |
| `remote/recipes.py` | `{{Recipe}}` as the wiki's Bucket table serves it: experience per action, tick cost and materials, for 3,889 recipes across 13 skills. Pure parsing. `production_json` is JSON inside JSON, every number is a string, and one page can hold several recipes told apart only by the output's `subtxt`. |
| `costing/recipe_rates.py` | A recipe turned into an XP rate: `experience * 3600 / (0.6*ticks + materials + overhead)`, joined to a challenge **exactly** on `Output` (93-95% of the processing skills, ~0% of the gathering ones). Owns the layering `defaults < computed < scraped < overrides` - **the one place a computed number does *not* beat the scrape**, and the docstring carries the measurement that says why. An unpriceable material drops the method rather than falling back to ticks. |
| `costing/recipe_overhead.py` | The harness that fitted `ACTION_OVERHEAD_SECONDS`. **No caller in `src/`**, like `dps_overhead.py`. Fits only the cheap-material pairs, because the residuals are bimodal and averaging the two halves means nothing - and now reports that six such pairs remain and the fit is flat, which is why that constant is documented as an assumption rather than a measurement. |
| `costing/dps_overhead.py` | The harness that fitted the overhead constants. **No caller in `src/`** — it exists to be re-run when someone doubts them, and it is out of `dps_bridge.py` because that file is large for a licence reason, not a structural one. |
| `costing/inputs.py` | What `fray estimate` and the Estimate tab must agree about, assembled once. The two had already drifted — the CLI applied `pinned_slayer` and the GUI did not — and a shared `cache/derived/` key made that silently order-dependent. |
| `cli/app.py` | The parser and `main`. Asks each family for its subcommands, dispatches through `args.func`, and turns four exception types into an exit code. **159 lines, from 1,750** — if it is about a particular subcommand it does not belong here. |
| `cli/common.py` | What every family needs before it can answer: `load_state`, `derive_cached`, `emit_json`, `digests`, `error`, `DEFAULT_MAP`. The names lost their underscore when they crossed a module boundary. |
| `cli/render.py` | Capping, grouping and stripping for a terminal. Shared by the listing commands and `diff`, which prints the same names either side of a comparison. |
| `cli/<family>.py` | One per subcommand family — `io_commands`, `listing`, `search`, `unlock`, `diff`, `estimate`, `neighbours`, `simulate`, `maps`, `derived` — each holding its handlers **and** its `add_parser` block, so a flag change edits one file. `tests/test_cli_<family>.py` is the file that checks it. |
| `gui/panels.py` | Shaping `Derived` into what the panel draws — sections of groups of `{key, name, note, icon, category}`, one shape across all five categories. **`category` is not the section**: all 21 skills share one section (a skill has at most one active task, so 21 headings would be 21 lists of one) where the payload keys ticks per skill, and edit mode writes a tick. Pure. Owns the three rules that are domain knowledge rather than formatting: a quest keeps only its **furthest** step, `Extra`'s collection-log rows split source from item, BiS groups by combat style. |
| `gui/worldmap.py` | Where a chunk sits on the map, and which of its sides face outward. Pure. Owns the projection (`grid_x = region_x - 15`, **`grid_y = 65 - region_y`** — the y axis is flipped), the tile pyramid's constants, the two kinds of id that have no square, and `hull_edges`. In `gui/` because all of it is about one particular tiling. |
| `gui/server.py` | Routing, as a **pure `handle_request`** with a `BaseHTTPRequestHandler` adapter over it — so tests reach the whole surface without binding a socket. Owns the `Sec-Fetch-Site`/`Host` checks — the latter against `Context.allowed_hosts` rather than loopback, so a non-loopback bind serves a page that can *act* rather than one whose every button 403s. |
| `gui/http.py` | The vocabulary every route speaks: `Response`, `Context`, `_json`/`_error`, and the heartbeat. **Must stay directly in `gui/`** — `RESOURCE_DIR` is `__file__`-relative, which is why the split is flat rather than a `routes/` package. |
| `gui/routes_view.py` | The **cheap path**: every route answerable without parsing the export. Nothing here may call `ctx.derivations.load`; `_areas_for` is the one documented exception and has a test. |
| `gui/routes_derived.py` | The **expensive path**: chunk, sections, diff, unlock, estimate, tasks. `/api/diff` derives both sides and is the one route allowed to be slow. |
| `gui/routes_reference.py` | Bytes belonging to no map: the static allowlist, blob freshness, the tile *template*, and the lazy proxy for section masks and skill icons. |
| `gui/actions.py` | The eleven POST handlers and `_ACTIONS`. **An action's reply shape decides whether the page polls it** — a job id, or the result. |
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
fray recipes                # GET per-action xp + tick costs -> cache/reference/wiki_recipes.json (13 requests)
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
FRAY_CHUNKINFO=cache/reference/chunkinfo.json FRAY_MAP_CACHE=1 .venv/bin/pytest   # every oracle, the real signal
fray-gui [--map ID] [--compare ID] [--port N] [--host H] [--allow-host H] [--keep-alive]
         [--no-browser] [--tab]
pipx install --force --editable .    # once: `fray`/`fray-gui` on PATH then track src/
pyproject-build                      # a wheel, for shipping only — not part of the loop
python -m zipfile -l dist/*.whl | grep resources     # prove the GUI's html/js/css shipped
pip install -e ../osrs-dps                           # the optional `dps` extra, into .venv for development
(cd ../osrs-dps && pyproject-build) && pipx inject --force fray-claude ../osrs-dps/dist/osrs_dps-*.whl
```

**`FRAY_CHUNKINFO` takes either the raw export or `fray chunkinfo`'s envelope around one**, so the
oracle run is that one line and needs no temp file. It did need one: the override path read the file
as-is, so pointing it at the cache's own `chunkinfo.json` returned the four-key envelope, every
accessor answered "absent", and the derivation came out empty and plausible — silently. Now
`cache._unwrapped_export` matches the envelope's **whole** key set and unwraps it (a *map* envelope is
refused outright, being a different thing rather than a wrapped export). `FRAY_MAP_CACHE` is
presence-only, its value unused.

`--export-json PATH` (or `-` for stdout, replacing the text summary) is carried by the nine
*derivation* subcommands plus `maps list`, not the four I/O ones (`fetch`/`show`/`chunkinfo`/
`heuristics`). `--recompute` is carried by those same nine and nothing else, so it means one thing
everywhere. `--limit` defaults to `None` (full
output) for `sections`/`sources`/`tasks`/`neighbours`/`diff` so piping just works, but to `10` for
`search`. See `cli/app.py`'s docstring.

**The `dps` extra is installed two different ways, one per venv.** `pip install -e ../osrs-dps` puts
it in `.venv` for development and the test suite; the `fray` on `PATH` lives in pipx's own venv and
needs `pipx inject` instead. An injected package **survives `pipx install --force`**, including the
`--editable` reinstall (both measured), so switching this project to an editable install left
`osrs_dps` in place. Injecting still copies a wheel, though, so a change to *`osrs-dps`* needs its
wheel rebuilt and re-injected with `--force` — the version does not move between builds, so a plain
`inject` silently no-ops. That asymmetry is now the whole of the rebuild loop: none for this project,
one for the optional extra.

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
cache/reference/                       # chunkinfo, tasks_map, wiki_rates, wiki_recipes, tile_version
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

**Four kinds, and `unlocked` used to be filed under `simulated`.** The fourth is `edited` - a map a
person changed by hand in the GUI and committed under a new name - and it cost exactly what this
file promised: one entry in `COMPUTED_KINDS`, after which removal, resolution, listing and
cross-kind name claiming all followed with no other change. It is distinct from `unlocked` because
that kind means precisely one thing (one candidate chunk, by `fray unlock --cache-map`), and calling
a map with six ticked tasks an "unlock" is the same wrong that split `unlocked` out of `simulated`.
`COMPUTED_KINDS` is what every removal path takes, which is what makes a new kind one line rather
than a hunt — and the argument against splitting (both mean "this project computed it, upstream
never saw it") loses to the fact that the picker has to *say* which.

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
`costing/levels.py`'s on what `current level` means: **the map records no skill levels** (`maxSkill` is
a declared cap, `passiveSkill` is what's reachable untrained), so `infer_levels` reads a
floor out of the *completed* challenges — a ticked `Buy the Defence cape` proves 99 Defence. `experience.py`'s XP
curve is the one exact input and is deliberately not overridable.

**A skill is priced band by band, and the bands are the reasoning.** `costing/training.py` walks the
climb splitting where the rate changes, so Herblore 1→99 is nine methods — cleaning guams at 3 up to
super combats at 90, 100h — where one rate chosen at the starting level made it 13,034h. Three
consequences worth knowing before reading a skilling number: the printed `xp_per_hour` is a **blend**
and nobody trains at it; **the floor can only be the first band**, so `floor_xp` rather than the total
says how much is guesswork; and **151 of the 310 scraped rates are `contained` joins**, which is why
every band prints its provenance — a guide another method names *exactly* is refused to a contained
claim, which removed 11 wrong joins including `Mix a ~|combat potion|~` taking *Making **super**
combat potions*. Quest XP is taken off the front of the climb, from exactly the
quests the quests bucket already charges hours for, which is what makes double counting impossible.

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

**Three things that made combat wrong before they were added, all of them about the *fight* rather
than the arithmetic.** The XP model is a published constant times damage and was right from the
start; every error was in what it was multiplied by.

- **A kill rate is paired with the health of the version that was simulated.** `best_kill` picks
  whichever version dies quickest - `Wolf#Level 11`, 10 health - and the first combat model multiplied
  that rate by the *wiki's* `Wolf`, 69 health, which is a different animal. `KillEstimate.hitpoints`
  now carries the library's own figure so the two cannot come apart, and `kills_by_style(prefer=...)`
  chooses the version by **damage per hour** rather than by kill speed, because for experience the
  fat wolf is the good one.
- **Reachable is not farmable.** The export puts 21 monsters in `Chambers of Xeric`, 9 in `Inferno`
  and 7 in `Fight Caves`, and the derivation is right to call them reachable - all 87 challenges
  requiring the raid are valid, and its drops really are obtainable. What you cannot do is kill
  Muttadile repeatedly to train Strength. `INSTANCED_AREAS` gates **only** combat training; excluding
  them from `reachable_providers` would change item pricing, which is a different and correct answer.
  A monster reachable in an instance *and* somewhere you can stand stays farmable.
- **Nothing modelled the wait for the next monster.** `dps_bridge`'s overhead is 1.2s of retarget
  plus tick waste, and a respawn timer only for bosses - right for "how long until the drop", wrong
  for a 2-health monster you would run out of. `spawn_caps` reads the per-chunk spawn counts the
  export already has (`chunks[id]["Monster"]`) and caps the rate at `spawns * 3600 / respawn`. The
  respawn is the one assumption in the file. It binds on 144 of 793 (monster, style) pairs on the
  benchmark map and changed the winner in all three styles.

**And the styles are priced separately, because the experience depends on which one you use.**
`price_combat` returns one target per style, so Ranged is priced on the map's bow rather than on its
whip. **The kit is not optional in that call** - without it the Magic loadout has no runes, never
lands a hit, and Magic silently fell back to the rough model this exists to replace.

**The combat skills are priced from damage, not from a training method** - they have no
`Primary: true` challenge anywhere in the export, so there was never a task to join a rate to and
`Attack`/`Strength`/`Defence`/`Hitpoints`/`Ranged` sat in `unpriced_skills`. They do not need one:
combat XP is a published constant times a number this project already computes. 4 experience per
point of damage in melee and Ranged, **2 in Magic** (the easy mistake, and a factor of two on the
whole climb), 1.33 to Hitpoints, plus the spell's own base experience per cast - which is *two thirds*
of a Magic rate, so it is not a rounding term. Damage per hour is `kills_per_hour * hitpoints`, which
means **combat rates improve automatically with the `dps` extra** without `combat_xp.py` knowing it
exists. Two things to know before quoting one: one damage figure serves all five skills, since
`kills_per_hour` does not say which style did the killing; and Hitpoints is **not** charged beside
whatever else you train, because in the game it comes free with it - see `hitpoints_credit` and
`slayer_credit` below. Measured against a known
figure it did not see: Magic came out at 200,228/hr barraging, where the community quotes 200-250k.

**Woodcutting is priced off its own training page, and the other three gathering skills are not -
which is a measurement, not an omission.** The obvious model for a gathering skill is
`actions_per_hour = f(level, tool_tier, node_count)`, and the export has the node counts. It does not
survive contact with the data: dividing each already-rated method's xp/hr by the wiki calculator's
xp-per-action gives an implied actions/hour spanning **6.2x in Woodcutting, 10x in Fishing and 21.5x
in Mining** (65/hr for runite against 1,400 for a shooting star). A single fitted `f` would be wrong
by up to twenty-one times and look confident doing it, which is worse than the floor.

The same measurement says what to read instead. Those pairs multiply out to **1.5-3.1x** spreads in
xp *per hour* - because OSRS balances higher tiers to pay more per action and give proportionally
fewer - so xp/hr is the quantity the game holds roughly steady and the one worth reading off a page.
`Pay-to-play Woodcutting training` tabulates exactly that per log, and its `{{plinkt}}` first
parameter **is** the export's `Output`, so all sixteen rows join exactly and none is left over.
Woodcutting went from 4 rated methods of 53 and **301.0h** to 17 and **176.4h**, every band `exact`.
Mining's ore table and Fishing's fish table publish experience per *action* only - the figure
`Module:Skill calc` already carries - so they stay on their guide joins rather than being given an
invented factor; their hourly figures exist only in prose keyed by technique name (`Motherlode Mine`,
`Barbarian Fishing`), which is the fuzzy join this project refuses.

**`TABLE_KINDS` is keyed by skill, and that is load-bearing.** The tables used to be tried in one
fixed order for every skill, which was harmless only while no two shared a key space. Woodcutting and
Firemaking do: both join on the log, through `Output` and `Items` respectively. First-match-wins
priced `Chop ~|magic logs|~` at 394,778/hr - the rate for *burning* one - and put Woodcutting 1-99 at
35.3 hours, about what the fastest method in the game manages.

**Agility and Thieving are priced off wiki tables, not guides or recipes** - they are the two skills
with no `{{Recipe}}` rows at all, and no money-making guide joins their method names, so every one of
their ~229 primary methods sat at the 1,000/hr floor (Agility 1 -> 99 read as 2,142 hours with
`(none found)` as its method). The export was never the gap: it already holds 9 rooftop courses, 9
other courses, 5 Sepulchre floors, 185 shortcuts, 33 pickpocket targets and 21 stalls, each with its
level and the object or NPC it acts on. Only the experience figures were missing.
`remote/skill_tables.py` reads them and `heuristics._table_rates` joins them **structurally** - a
shortcut, stall or pickpocket on the `Objects`/`NPCs`/`Output` name, a course on its own name - so
there is no `contained` tier and nothing to be fuzzy about. Courses and stalls publish an hourly rate
directly; shortcuts and pickpockets publish xp per action and are divided by
`SHORTCUT_CYCLE_SECONDS`/`PICKPOCKET_CYCLE_SECONDS`, the only two numbers here that are assumptions
rather than measurements (the second is calibrated against the wiki's own 86,000/hr for Knights of
Ardougne **at the level the method opens**, which is the conservative end of a rate that climbs with
success chance). Joined 44 of 112 Agility methods and 39 of 117 Thieving ones - the misses are
minigames and access-only rows nothing publishes a rate for.

**`[+]` means "or anything equivalent", and the item walk was the one place that did not know.**
`codeItems.itemsPlus` maps `Air rune[+]` to the four runes that satisfy it, and `_required_kills`
has always expanded the monster equivalent - but `_item_hours` looked the name up literally, found no
item called `Air rune[+]`, and reported it unpriced while `Air rune` itself priced in 2.4 seconds.
That was **16 of the 75 unpriced items** on the benchmark map. The family is expanded before
`resolve` (the key is not an item name and will not resolve to one) and the **cheapest** member wins,
which is the same reading `_required_kills` takes when it stops at the first reachable one.

**An activity a valid challenge unlocks is a provider, not just monsters, objects and NPCs.** The
export models the Evil chicken outfit as `Trade bird's eggs for nests*` at a Shrine, whose `Output`
names a `skillItems.Nonskill` table holding the four pieces at 1/1200 each - so the pieces are
reachable the moment the trade is, and they were unpriced because nothing put the *table* in the
provider set. **Gated on someone having stated a rate for it**, which is what stops the same rule
pricing the other 322 such tables at the 60/hr default: a minigame reward table given a guessed rate
makes its rarest drop look cheap, and a guessed rate multiplied by a real drop chance is the mistake
`combat_xp.best_target` already refuses. The rate itself is a hand entry in
`heuristics/overrides.json` - a bird's egg is about one an hour while woodcutting, so a piece is
1,200 hours.

**Six currencies have rates now**, and only one is measured: marks of grace, off the rooftop table.
The rest are stated figures - 500,000 coins, 25,000 Tokkul, 200 zeal, 100 Mahogany Homes points, 80
tithe, 40 abyssal pearls an hour - pinned by a test because a silent edit to one moves every item
bought with it, and tunable under `currencies` in `heuristics/overrides.json`.

**Two of those currencies came from opposite places.** Marks of grace are
read off the rooftop table's own column - every course pays between 8 and 18 an hour, and that narrow
spread is what makes one figure honest where a per-map one would be false precision. Mahogany Homes
points are a stated 100 an hour, tunable like the rest.

**`Points` is not one currency**, which is the part worth knowing: 127 store lines are priced in
something called Points and Mahogany Homes, Pest Control and Barbarian Assault each mean their own.
So a rate may be qualified as `"<shop>:<currency>"` and that is checked before the bare name - which
also means the unqualified `Points` still has no rate, and everything else priced in it is still
refused rather than given Mahogany Homes'.

**Nothing the estimator reaches is free any more, and that was the largest remaining error.**
`_route_hours` used to price a shop or a ground spawn at zero seconds on the grounds that both are
instant. Both are - the transaction is; the *money* and the *respawn* are not - and it stayed harmless
only while the estimator asked for one abyssal whip at a time. Pricing Construction made it dominant:
a build is a stack of bought planks, and a menagerie steel dragon reads `Coins x 10,000,000`.

- **A shop costs the money and the walk.** The price comes from `remote/stores.py` and the time to
  earn it from `Heuristics.currency_per_hour` - **500,000 coins an hour and 25,000 Tokkul**, both
  tunable under `currencies` in `heuristics/overrides.json`. The currency is kept rather than
  flattened to a price because 375 Tokkul is twenty times 375 coins. A currency with **no** rate is
  refused, not guessed: castle wars tickets and trading sticks have no exchange rate anyone would
  agree on. On top of the money, `SHOP_TRIP_SECONDS` (30) per `SHOP_TRIP_ITEMS` (27) - and
  `_item_hours(amortise=)` is the difference between the two questions the walk is asked, since a
  goal wants one item and pays for a whole trip where a recipe wants two planks *per action* and pays
  its share of a trip that supplied the next dozen. Charging a full trip per action put thirty
  seconds on every cast of every spell.
- **Currency is earned, not fetched.** `Coins` and `Tokkul` are ordinary items to the export - both
  have ground spawns - so the walk found one lying about and priced ten million at nothing. They are
  now checked *before* the routes, so no spawn can undercut the rate.
- **A ground spawn is cheap, not free.** A pickup is one tick, which alone caps collection at 6,000
  an hour; the real limit is that the item does not return while you stand there, so it is
  `SPAWN_HOPS_PER_HOUR` (360, six hops a minute at ~10s each) multiplied by how many lie at that
  spawn. Left free, a `Spawn` of two planks priced a ten-plank wooden fence at nothing and made it
  296,471 Construction xp/hr.

**Performing an action costs time, which closes the last free route.** `_route_hours` charged a
`task:` route for its *inputs* and never for doing it, so any chain bottoming out in a gathering
action with nothing to consume cost zero - `Plank <- Process logs <- Logs <- Cut logs from roots <-
(nothing)`. The time comes from whichever source knows it: a money-making guide's **`kph` is actions
an hour** (248 methods, every one of them with a usable figure), a recipe's tick cost covers an order
of magnitude more, and `DEFAULT_ACTION_SECONDS` - four ticks - stands in for the rest. `ActionRate`
exposes `performing_seconds` separately from `action_seconds` precisely because the walk charges the
materials itself and handing it the whole cycle would bill them twice.

**And the sawmill charges.** Upstream models it as seven `Process <X> logs` challenges and records no
price, so a plank cost exactly one log; `Heuristics.conversion_seconds` adds the fee, keyed by what
the conversion *makes* because that is what the challenge's `Output` names. It returns **zero** where
`shop_seconds` returns `None` - a conversion with no recorded fee really is free to perform, and only
the sawmill charges - while an unknown *currency* is still refused.

Together those took Construction's best computed build from 296,471 xp/hr to 69,121, which puts the
hand-verified **Mahogany Homes at 165,000 top of the list** where it belongs.

**Farming is measured in days, and it is the only skill that is.** A crop grows for hours or days
while you do something else, so what limits the skill is how many harvests a day you get round to -
not how fast you click. Priced as a rate it came out at **75,353 hours for 1 → 99**, off the single
method the recipe data reached (supercompost, 8.5 xp for fifteen watermelons). It is now **145 days
of calendar and 64 hours of clicking**, and the estimate reports both: the hours go in the bucket
where they are comparable with every other skill, the days are printed beside them and deliberately
**not added**, because a day of waiting is not a day of playing.

The schedule *is* the model, and every figure in it is stated rather than measured - redwood at 0.14
a day is one a week because that is how long it takes to grow. Tunable under `farming` in
`heuristics/overrides.json`. One input is genuinely missing and is documented where it bites: the
per-crop `Chance1`/`Chance99` behind the wiki's `ChanceToSave` live in the calculator's JavaScript and
in no page this can read, so variable-yield crops use the calculator's own published assumed yields
and a stated six for herbs and allotments. It moves the total very little - a magic tree is 13,914 xp
against a ranarr's 30, so the trees carry the climb.

**Firemaking is a constant plus a number, and that is the whole model.** You light a fire every four
ticks, twenty-seven to an inventory, then bank - so a trip is `27 x 2.4 + 10` seconds and pays
`27 x` the log's experience. Normal logs come out at 51,979/hr and willow at 116,952, which is what
the skill does. **Burning a log is not a `{{Recipe}}`**, so the recipe bucket has only *pyre* logs and
no money-making guide covers the bottom of the skill: the only rated method was magic logs at level
75, and **Firemaking 1 → 99 priced at 1,738 hours** with 1,210 of them floored. It is now **33.1
hours** across six bands, all `exact`, ending at a hand-entered Wintertodt. The logs are assumed to
hand, which is how every published Firemaking rate is quoted - charging the walk to gather them would
price the Woodcutting climb twice on a map training both.

**Prayer is priced from the drop table, because that is what actually limits it.** Burying a bone
is two ticks and offering one at an altar is one, so an hour of pure clicking is 3,000 or 6,000
bones whatever else is true - and nobody has 6,000 bones. The whole model is therefore
`experience_per_bone * 3600 / (offering_seconds + collect_seconds)`, where the collection comes
through `estimate.material_seconds`, the same closure `recipe_rates.py` prices a recipe's materials
with. Measured: **Prayer 1 -> 99 is 79.7h on `fray`** (big bones at the Chaos Altar, 163,558/hr,
against the wiki's own 120-180k/hr for that method) and **150.2h on `verf-sim/run-001`** (a limestone
altar with both burners), where both sat at the 13,034h floor before.

Three things about it are worth knowing before changing a number:

- **The export has no burying challenge**, so the rate cannot be joined to a task. Prayer's six
  `Primary` methods offer fish at a shrine and shards at a libation bowl; the thing every player
  does from level 1 is not modelled at all. So it reaches `training_options` through
  `Heuristics.computed`, the door `costing/combat_xp.py` already used for the five combat skills -
  which is why that field is `computed` and not `combat`. It is **added to** the challenge-derived
  options rather than substituted for them: for combat the two are the same thing, but Prayer's six
  offering challenges are real alternatives and the band walk should get to pick.
- **Which chaos altar is the trap.** The export puts `Chaos altar (Prayer)` in five chunks and only
  the Chaos Temple church in level 38 Wilderness takes bones - Varrock, the Yanille Agility dungeon
  and the Underground Pass are prayer-point recharges. Keying on the object name would hand a
  sevenfold rate to any map holding the Varrock one, so `CHAOS_ALTAR_CHUNK` pins region 11835,
  identified by the contents the wiki's own description of that temple names.
- **A house altar is gated twice.** Reaching the Construction challenge says the map holds a house;
  `infer_levels` saying you have the level says you can build the altar. The incense burners are
  their own challenges at 61-69, so an altar reachable without them takes `base` rather than `lit` -
  on a gilded altar, 2.5x against 3.5x. Each burner is worth exactly +50 percentage points across
  all seven altars, which `tests/test_prayer.py` asserts rather than computes from.

**Sailing is refused outright, and that is a different statement from the floor.** The floor means
"this project has not reached that method yet" and is the right answer while a scrape could still
improve it. Sailing is the narrower case where the numbers do not exist anywhere to be found: it is
new enough that no money-making guide covers it, `{{Recipe}}` has no rows for it and no wiki table
publishes a rate for any of its **27 primary methods**, so all of them sit at the floor and the climb
reads as 13,034 hours - not a conservative estimate but a made-up one wearing a number.
`estimate.UNRATED_SKILLS` puts it in `unpriced_skills` instead, alongside the combat skills but for
the opposite reason: those have no training method in the export at all, where Sailing has plenty and
nobody has timed one. Remove a skill from that set the day something publishes rates for it.

**A computed rate slower than the 1,000/hr floor is refused.** The floor is a deliberate stand-in for
ignorance, not a speed, and a computed number below it says the model is missing something about that
method - a bulk action, a faster variant, materials someone already has - far more often than it says
the method is genuinely glacial. Supercompost is the case that forced the rule: 8.5 xp for an action
that gathers fifteen watermelons prices at 173 xp/hr, it is the *only* Farming method the recipe data
reaches on the benchmark map, and the band walk applied it to the whole climb - **Farming 1 → 99 at
75,353 hours**. 130 of 852 computed rates sit below the floor across nine skills; refusing them puts
Farming back to 13,034h *marked as defaulted*, which is honestly unknown rather than confidently
wrong.

**Construction joins on the task's own name, and it is the only skill that needs to.** Its challenges
carry `Output Object` - the furniture - where every other skill carries `Output`, so the exact join
reached **28 of its 602** methods. The recipe's output *is* the furniture name and the task says so
(`Build a ~|mahogany table|~`), so `recipe_rates.join_keys` tries `Output`, then `Output Object`, then
the task name with its verb stripped. Measured across all thirteen skills that route gains **500
Construction methods and six elsewhere** - a Construction fix that happens to be expressible
generally, not a new fuzzy tier, and still an exact comparison of whole strings.

**A recipe priced in coins is refused, because there is no gp-per-hour model here.** `Coins` is
stocked by a ground spawn, so the item walk prices it at zero seconds - and a Construction recipe
reading `Coins x 10,000,000` came out free, making a steel dragon in the menagerie the fastest
training in the game at 3,348,000 xp/hr. 39 recipes name coins against 3,889 that do not.

**What is still wrong with Construction, and it is the same root:** a material stocked by a reachable
shop costs *nothing* (`estimate._FREE_ROUTES`), so a build whose inputs are all shop-bought is priced
on ticks alone - `obsidian fence` at 2.9M xp/hr off free Tokkul. The opposite end is as bad: the only
route to a mahogany plank on the real map is **pickpocketing Gangsters at 1/13**, so a mahogany table
costs 6 x 307s and reads as 1,638 xp/hr. Both need a shop model (money as time), which is a larger
decision than a rate fix. **None of it moves a number today** - no cached map has a Construction
goal - so this is coverage insurance rather than a correction.

**Three defects in the scraped training rates, all of which the band walk amplified.** A bad rate on
a *low-level* method is far worse than a bad rate anywhere else, because `training_bands` takes a
running maximum: a wrong number at level 1 prices the whole climb. All three were found by reading
the extremes of `wiki_rates.json` rather than by a test, and all three are now pinned:

- **`.5273` parsed as `5273`.** `_NUMBER_RE` demanded a leading digit, so a leading-dot decimal lost
  its point - a ten-thousand-fold error that reached the estimate as Fishing at **2,604,862 xp/hr**
  from level 5.
- **`Experience{N}num` is sometimes arithmetic.** `Catching sardines & herring` writes
  `.5273*20 + .4727*30` - 53% of catches at 20 xp and 47% at 30, so 24.7 a catch. `wiki.parse_amount`
  evaluates it through `ast` with the node types checked, never `eval`, and **refuses rather than
  falling back** when a value that is entirely arithmetic will not evaluate: reading `1/0` as 1 is a
  wrong number where "the guide does not say" is the honest one.
- **`Experience{N}isph` says the figure is already per hour.** Ten guide-skill pairs set it, and
  Subduing Tempoross states 62,000 Fishing xp an hour beside 60 permits an hour - multiplied
  together, **3,720,000**.

**And the most specific contained claim now wins a guide.** The existing rule only refuses a contained
claim when some *other* method names the guide exactly, which leaves every guide nobody names exactly
open to its vaguest claimant: `Chop ~|logs|~` is contained in "Cutting camphor logs" exactly as
`Chop ~|camphor logs|~` is, and the level **1** method kept an 82,512/hr rate meant for level 66. A
claim that is a strict substring of another claim on the same guide is the less specific reading and
is refused. Five joins removed, 311 -> 306.

**The Giants' Foundry is what makes Smithing tractable, and nothing had rated it.** All six
`Forge a <tier> ~|preform|~` challenges are reachable on both cached maps and every one carried a
`default` rate, so `training_options` dropped them and the climb was walked on recipe tick-math -
**874.1 hours**, topped out by a *bronze platebody* at 24,341/hr because it opens at level 18 and the
running maximum never found better. The wiki's own page publishes swords per hour against average XP
per hour for five alloy tiers, which map onto the six preforms (bronze and iron are both "Lowest"):
48,000 / 85,000 / 135,000 / 195,000 / 276,000. Hand entries in `heuristics/overrides.json`, pinned by
a test, and **Smithing 1 -> 99 is now 54.5h across five tiers, every band `exact`**.

**The caveat is the one the material ranking exists to catch and cannot catch here.** A foundry
challenge's `Items` is `AdamantMats[+]` - a family placeholder, not an item - and its `Output` is
`None`, so no recipe joins it and `material_seconds_per_xp` is `0.0`. The rate is therefore the
wiki's, quoted with the bars to hand, and the bars are not priced. That is optimistic on a chunk map
in exactly the way `effective_xp_per_hour` was built to prevent, and it is stated here rather than
hidden because the fix needs `[+]` family expansion in the material walk, not a different number.

**A method is ranked on what it costs, not on what its action costs.** A published rate is quoted
with the materials to hand - "299,000 an hour at anglerfish" describes the range, not the trip before
it - and on a chunk map the trip is often most of the cost. Ranking on the published figure picked
`xerician robe` for Crafting at 167,200/hr on a map where one xerician fabric takes 95 seconds to
obtain and a robe needs four: **831/hr** once the fabric is counted, and a method no player would
touch. `TrainingOption.effective_xp_per_hour` adds the two halves as seconds per XP
(`3600 / (processing + gathering)`), `training_bands` ranks and prices on it, and the gathering half
comes from the same `ActionRate`s the recipe rates do - so the two cannot disagree about a recipe.

Measured on `verf-sim/run-001`: Crafting moved off xerician robes to **topaz bracelet, 46.0h ->
85.4h**, and Cooking off anglerfish to **shark, 14.3h -> 28.8h** with 13.2h of that named as
gathering. Skilling 951.0h -> 1,004.9h. The totals rise a little and the *methods* change a lot,
which is the point: the estimator now avoids a method it cannot supply instead of being charged for
one it would never pick.

**`TrainingBand` carries both halves** (`published_xp_per_hour` beside `xp_per_hour`, and
`material_hours` between them), because a familiar 290,000/hr shark reading as 148,000 looks like a
defect until you can see why. The CLI prints the gathering share as its own line, like farming's
calendar days.

**The known bias, stated rather than hidden:** only methods a `{{Recipe}}` describes have a material
cost, so a method with no recipe row is ranked as though its inputs were free and is quietly
favoured. Coverage is 93-95% on the processing skills and ~0% on the gathering ones, where there is
usually nothing to consume anyway - but this is the direction to check first when a chosen method
looks too good.

**Two computed layers, and they sit on opposite sides of the scrape.** `dps_bridge` puts its kill
rates *above* the guides; `recipe_rates` puts its XP rates *below* them. That is not an
inconsistency to tidy up - it is measured, and the two are computing different kinds of thing. A
simulated fight and a money-making guide answer the same question, so the better-informed one should
win. A recipe and a guide do not: where a method's materials price free, tick-math is a median 1.38x
*above* the guide because the wiki's tick cost is the action and not the cycle (no banking, no
walking); where they cost something it lands at x0.0011 to x0.024 *below*, because this project
charges you for fishing the anglerfish where the guide assumes you bought it. So a guide, when there
is one, keeps the method. What the recipes replace is the **1,000/hr floor** - on the real map 370 of
417 priced methods had nothing but that, against 47 with a guide. `costing/recipe_overhead.py`
re-runs the fit behind the one constant this involves.

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
in `mapQuery` and the strip reduces itself while comparing. Switching map clears `state.step` *before*
the view loads, or the new map is rewound to a roll it never had. **It reduces rather than
disappears, and the ledger is therefore fetched before the comparison is checked**: a run whose
history is merely out of view looked exactly like a map that never had one, which is a working
feature reading as a broken one. The reduced strip says which and carries the one click back.

**Anything that makes a map selects it; nothing puts it in the compare slot.** Roll was fixed for
this and `POST /api/unlock` was not, so unlocking a chunk from the panel hid the record of what it
added — the same bug, in the other action. A computed map needs no comparison to show its gains: it
replays its own ledger, so the chunk it added draws green either way, and only the timeline is lost
by comparing.

**`GET /api/unlock` and `POST /api/unlock` are the two halves of one thing.** The GET prices a
candidate and keeps nothing; the POST saves the world it was describing, through `batch.save_unlock`
so the CLI's `--cache-map` and the panel's **Unlock** write the same metadata. **Fetch takes a typed
id, not the selected map** — every source-chunk map is a public read, so the ids worth fetching are
exactly the ones not yet in the picker; blank means `cache.DEFAULT_MAP_ID`, which is the fourth
constant crossing into JavaScript with a test holding the two in agreement.

**All fifteen CLI subcommands are reachable from it.** `GET /api/{maps,view,revision,summary,
neighbours,chunk,sections,unlock,diff,search,estimate,tasks,tiles,areas,derived,jobs,timeline,roll,reference,build}` and
`POST /api/{fetch,simulate,unlock,commit,snapshot,timeline,cancel,refresh,maps/remove,derived/prune,window}`. The panel's tabs are tasks / chunk / find / estimate /
maps, and `?map=&compare=&candidates=1&sections=1&step=&tab=` reproduces a view.

**The page has four modes, and the ribbon says which in colour.** It had three
already, encoded as mutually exclusive *conditions* — a compare box with
something in it was Diff, a non-null step was Timeline, neither was Browse —
which is why `comparingNotice` existed: a function whose whole job was to
apologise for an interaction the interface refused to name. `state.mode` names
them, `setMode` is the single transition point, and `mapQuery` switches on what
the page *is* rather than on which control happens to hold a value. The
exclusivity stops being a rule the query enforces and becomes a property of the
modes: **one mode carries a comparison and it is not one of the ones that step.**

| mode | base map | carries | editing |
|---|---|---|---|
| Browse | any non-simulated | a pinned step, if the map has one roll | prompts to enter Edit |
| Edit | any non-simulated | the pending set, and **Commit** | this is the mode |
| Diff | the browsed map | `compare`, any map at all | disabled |
| Timeline | **always** a simulation | the strip and the step | disabled |

`mode === "timeline"` ⟺ the base map's kind is `simulated`, and that
biconditional is what makes the separation real rather than cosmetic: a run is
fifty worlds, so browsing it as one is the confusion this removes. `selectMap`
asks before entering and puts the picker back on a decline; `openMap` is the
unprompted twin for the actions that *make* a map, which select their result
directly and would otherwise have landed a run in Browse. From Timeline you
cannot enter Diff or Edit — both would show a simulation outside its mode — and
the door says so rather than going quietly grey.

**Browse still carries a step, and that is the judgement call.** A batch of one
— a saved unlock, an edit — has exactly one roll, pinned at its end so
`/api/view` can say which chunk arrived. That is not a rewind; it is the only
world the map has. Banning it would have silently lost the green chunk a saved
unlock exists to show, which is the bug
`test_unlocking_opens_the_result_as_the_map` was written for — so `hideStrip`
sits beside `hideTimeline`, because "this map has no history" and "its history
is not yours to drag from here" were the same call and are two different states.

**An edit is pending until it is committed, and that is what makes it cheap.**
A ticked row greys in place and an unlocked chunk lights up amber with **no
derivation at all**; exactly one happens, on the world that results. A preview
that re-derived per click would cost ~0.8s a tick to answer a question nobody
asked half way through. The set lives in `state.edits` in the browser and
nowhere else until **Commit** — so leaving the mode or changing map asks before
throwing it away. `POST /api/commit` is the only writer, through
`batch.save_edit`, and returns the **claimed** name because `claim_batch`
suffixes a clash.

**Snapshot is the way out of a timeline, which is what makes the invariant
affordable.** A run cannot be diffed, edited or browsed, so "I want to work with
*this* roll" is answered by making it a real map — and after that it behaves
like any other. `POST /api/snapshot` derives **nothing**: the world after k
rolls is the base payload with those k chunks applied, since `simulated_payload`
reads only `chunk_id`. The records it is handed are synthetic while the ledger
*written out* is the run's own, truncated, so the snapshot's history is the real
one rather than a hollowed-out copy. It is filed as `edited` rather than as a
fifth kind: a kind exists to be *said* in the picker, and "this came out of a
timeline" and "I ticked some things" are one answer there.

**The one place this can be quietly wrong is the encoder.** A mis-encoded key
writes a tick `firebase.decode_challenge_keyed` cannot read back, and the map
then derives exactly as though the task had never been ticked — nothing errors
anywhere. So the round-trip property over all 49,721 interned names is not
optional, and `tests/test_gui_actions.py` asserts a committed tick through the
same decoder every derivation uses rather than asserting some key is present.

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
- **The page watermarks itself with the server's install, not its own.** It was built when `PATH`
  carried a *wheel* that a forgotten `--force` could leave weeks stale; with the editable install
  there is no stale state left to warn about, and the line now answers a different question — *which
  checkout is serving me*, which `--host` makes a real question. `GET /api/build` and the CLI's first
  line are where it is answered. Baking the stamp into `app.js` at build time would answer about the *page*
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
  the projection, both plain integers over JSON — so `tests/test_gui_contract.py` reads `app.js` and
  asserts them against the Python. The same file asserts the canvas is given an explicit size, since
  `inset: 0` does not stretch a replaced element and the failure is silent. A third assertion pins
  that **no `raw()` interpolation lands inside an attribute**: `data-tip="${raw(...)}"` splices
  unescaped quotes through the closing quote, and the markup after it appears on screen as text.
- **Three interface rules that each replaced a bug**, all pinned by `tests/test_gui_contract.py`:
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
  is on screen for the same reason, and `tests/test_gui_contract.py` asserts no tile route exists so
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

**A Slayer climb pays for the combat climbs beside it, and not charging for that was the largest
remaining double count.** Slayer experience is the monster's hitpoints, so a Slayer rate in XP per
hour **is** a damage rate - no separate model needed, which is what makes this a credit rather than a
guess. On `verf-sim/run-001` that is 394 hours of Slayer dealing 8.6M damage, against a Hitpoints
climb needing 8.7M, a Defence climb needing 12.8M and an Attack climb needing 0.3M, all three of
which were being priced in full beside the hours that had already earned them. Skilling went
**1,263.3h to 951.0h**; Defence and Attack now cost nothing and Hitpoints 235.3h -> 40.8h.

`combat_xp.slayer_credit` owns the arithmetic, and it is two sharing rules because the game has two:

- **Hitpoints is free alongside** - every point of damage pays it 1.33 whatever style dealt the
  damage - so it never competes and is credited up to what the climb still needs.
- **The attacking skills compete**, because a kill is dealt in one style. So it is the *damage* that
  is shared out and each skill converts its share at its own rate, which is how Magic's 2 per damage
  stays honest instead of being averaged with melee's 4. Sharing the experience instead would pay for
  two climbs with one fight.

Allocated **smallest remaining need first**: deterministic, so `--jobs` cannot move a total, and it
matches the plan's `w_s = 1 while below goal` - finishing the cheap goals first is what maximises how
many a fixed quantity of damage closes. Every allocation respecting the caps is realisable by a
player switching styles as each goal lands, so this is a choice among correct answers rather than an
approximation of one. It runs **before** `hitpoints_credit`, so that pass sees the hours actually
left rather than crediting the same damage twice.

**There is no oracle for any of this** - nothing upstream records what a shared climb ought to cost -
so `tests/test_combat_xp.py` pins invariants instead of numbers: never more than the need, never more
damage spent than dealt, monotonic in the damage, and identical under 50 shuffles of the goal order.

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

**Which tests a change needs is now a file, not a judgement.** That is what the split bought, and it
is the only reason to prefer this layout to the one file it replaced:

```
.venv/bin/pytest tests/test_cli_estimate.py    # changed cli/estimate.py          0.5s
.venv/bin/pytest tests/test_gui_view.py        # changed gui/routes_view.py       0.3s
.venv/bin/pytest tests/test_gui_contract.py    # changed app.js or style.css      0.2s
.venv/bin/pytest                               # the whole suite, still           2.6s
```

The last line is the honest caveat: the suite was never slow, so **none of this made the tests
faster**. What cost time was the ritual around them — a wheel rebuild per change, an oracle setup with
a hand-extracted temp file — and that is what Phase 0 of this work removed. The split is about how
much you have to read and re-verify, not about seconds.

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
already on `PATH`) writes `dist/fray_claude-<version>-py3-none-any.whl`. **Building one is no longer
part of the development loop** — `pipx install --force --editable .` put `fray` and `fray-gui` on
`PATH` pointing at `src/` — so there are exactly three reasons left to build a wheel: shipping to
another machine, proving the packaged `gui/resources` shipped
(`python -m zipfile -l dist/*.whl | grep resources`), and checking that `packages.find` still
discovers every subpackage. `tests/test_packaging.py` covers the third in milliseconds, which is the
only one that could otherwise be missed for weeks.

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
- **`fray` on `PATH` is an editable install, so there is nothing to rebuild.** This used to end every
  task: build a wheel, `pipx install --force`, then `diff` the installed file to prove it took, because
  a plain `pipx install` on an unmoved version is a silent no-op and every manual check afterwards
  would be of yesterday's code. One command retires all of it:
  ```
  pipx install --force --editable .        # once, not per change
  ```
  pipx's venv now imports `src/` directly, so a Python edit is live in `fray`/`fray-gui` immediately —
  and so is a `gui/resources/` edit, since `RESOURCE_DIR` is `__file__`-relative and now resolves into
  the checkout (measured: the served `style.css` is byte-identical to the source file). Editing the
  front end is edit → reload the tab. The watermark says `editable install, linked …` rather than
  `installed …`, which is `build_info.py` reporting the change rather than being confused by it.
  **The cost is that the checkout is now load-bearing**: move or delete it and both commands break.
  And one failure mode moves rather than disappearing — a new subdirectory without an `__init__.py`
  imports fine here and is silently absent from any wheel built later, which is what
  `tests/test_packaging.py` now catches.
- Tests are pytest, in `tests/`, **flat and named after the module under test** — `tests/test_summary.py`,
  `tests/test_cli_estimate.py` for `cli/estimate.py`, `tests/test_gui_view.py` for `gui/routes_view.py`.
  Flat rather than mirroring the package tree: pytest's default import mode collides on duplicate
  basenames across directories without `__init__.py`, so `tests/cli/test_estimate.py` beside
  `tests/costing/test_estimate.py` is a landmine, and `pytest tests/test_cli_*.py` already gives
  directory-grade selection.
- **The opt-in oracles are marked, not `skipif`-ed.** Write `@pytest.mark.real_cache` (needs the export
  *and* this checkout's populated `cache/`) or `@pytest.mark.real_export`;
  `conftest.pytest_collection_modifyitems` turns them into skips when the inputs are absent, and the
  markers are registered in `pyproject.toml` so a typo is a warning rather than a silently-never-run
  test. `tests/` is not a package, so a test file cannot import from `conftest.py` — which is why the
  gates are markers and the shared setup is fixtures.
  Gating a real-cache test on the export alone is a bug, not a shortcut: it makes the test *fail* with
  `CacheMissError` on a fresh clone instead of skipping, which is what two `test_bis` oracles used to do.
- `conftest.py` holds what more than one file needs and nothing else: the two markers, `project`,
  `cached_map`, `simulatable`, `derived_entries`, `no_ambient_chunkinfo`, and the **session-scoped**
  `real_export`/`real_state`/`real_derived`. Those three share one `pipeline.derive` across the twelve
  oracles — never `cached_derive`, so the oracles stay a cache-free signal. Anything used by one file
  stays in that file: conftest is depended on by every test in the project, which is the blast radius
  all of this is trying to shrink.
- Pass `cache.py`'s `root` a `tmp_path`, and monkeypatch `urllib.request.urlopen` (`tests/test_api.py`)
  or `fray_claude.cli.io_commands.fetch_map`. **A patch target is a module path, so it moves when code
  does** — `read_chunkinfo` is read in two places now (`cli/io_commands.py` for `fray chunkinfo`,
  `cli/common.py` for every derivation command) and patching one leaves the other reading the
  developer's real cache. That is not a failing test but a passing one computed against the wrong map;
  `conftest.cached_map` patches both.
  Any test calling `cache.read_chunkinfo()` without an explicit `override` must take the
  `no_ambient_chunkinfo` fixture, or an ambient env var shadows `tmp_path`
- A test that needs the real (~7MB) chunkinfo export is opt-in, not run by default: build fixtures by
  hand for the normal suite, and gate the real-export check on `FRAY_CHUNKINFO` with
  `pytest.mark.skipif`, so a fresh clone stays green. **These are the tests that catch real defects**
  — they compare against upstream's own recorded answers, so run them (with `FRAY_CHUNKINFO` set)
  before trusting a change to `sections`/`sources`/`challenges`/`bis`/`active_tasks`/`other_tasks`,
  and treat a failure as a bug in this code rather than a stale oracle.
  `FRAY_CHUNKINFO` accepts either form — a raw export, or `fray chunkinfo`'s envelope around one —
  so `cache/reference/chunkinfo.json` is now the thing to point it at. **Read the export through
  `cache.read_chunkinfo`, never with `json.loads` on the env var**: nine test sites did the latter and
  so bypassed the unwrap, which is what made the one-line oracle run fail on seven tests while the
  hand-extracted file passed. One reader, one answer.
- **`User-Agent` differs by host, deliberately.** Firebase and GitHub get none — those endpoints are
  public and unauthenticated, so there's nothing to disguise and a header would only publish
  information nobody asked for. The **OSRS wiki gets `api.WIKI_USER_AGENT`, and requires it**: an
  anonymous request there is answered with HTTP 403 (measured, not assumed), because the wiki applies
  MediaWiki's user-agent policy asking automated clients to identify themselves. Both rules come from
  one principle — send what the endpoint needs to serve the request, and nothing more about who is
  asking. The header names the project and its repo, never the user.
