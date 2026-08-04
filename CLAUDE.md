# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

fray-claude is a CLI that reads state from the source-chunk web app, caches it locally, and runs
offline operations on that cache. source-chunk is upstream and read-only from here.

Planned: a shortest-path search ("fewest chunk unlocks to reach X" — `graph.py` exists to serve it and
has no other reason to be a separate module), render a world-map image for a simulated state, generate
heatmaps of likely rolls over N attempts (the cached simulation batches are the input for this — see
the `cache/sims/` layout under Commands).

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
**`api.py` is the only module that touches the network and `cache.py` the only one that touches
disk; everything else is pure.** The derivation chain is
`sections` -> `sources` -> `challenges` -> `bis` -> `active_tasks`/`other_tasks`, wired by
`pipeline.derive` and reached by every subcommand through it.

**This is a deliberately partial reimplementation of upstream's own logic.** Each module's docstring
carries the precise, current list of what it ports, what it approximates, and what it refuses to
guess at, with `worker.js`/`index.js` line references — **read it before trusting that module's
numbers or changing its behaviour.** That is where the design rationale lives; this section is a
map to it, not a substitute.

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
  this is the only way a heatmap-sized batch finishes. That holds today only because there is **no
  module-level mutable state anywhere** — no `lru_cache`, no memo dicts, no globals; `_UNARMED_SOURCES`
  and `_UNIVERSAL_PRIMARY` are read-only constants — and because `MapState`/`Derived` are frozen.
  Adding a cache to a "pure" module would break `--jobs` silently, in the form of runs that disagree.
  Workers each load their own `ChunkInfo` (~0.1s) rather than sharing the parent's; one process writes
  any given file, never two. `cache/derived/` obeys the same rule from the other direction: it is
  content-keyed, so two workers racing on one key write identical bytes and the atomic rename makes
  either winner correct — which is why it needs no lock and has no shared index.

| Module | Owns |
|---|---|
| `api.py` | The network. `FetchError`. An unknown map is HTTP 200 + bare `null`, never a 404. Four hosts now: Firebase, upstream's `gh-pages`, the OSRS wiki (which **requires** a `User-Agent`) and one published Google Sheet. |
| `wiki.py` | Wikitext template parsing. Pure. Quest length is in `{{Quest details}}`, **not** `{{Infobox Quest}}` — the tempting wrong template has no `length` and so returns `None` for every quest without erroring. |
| `experience.py` | The exact 1–99 XP curve, closed-form. **Not a heuristic and not overridable** — that separation from `heuristics.py` is the point of the module. |
| `heuristics.py` | Every hand-correctable number, and the `defaults < scraped < overrides` merge. Owns the joins and their `exact`/`contained` provenance; **no fuzzy tier**, by measurement — read the docstring before adding one back. |
| `slayer.py` | Slayer's rate, which is a *distribution* not a chosen method: a time-weighted mean over what a master assigns. Also owns `superior_rolls_per_hour` — the shared `SuperiorDropTable+` is one pool per master, not one per superior. **Masters are gated on their NPC being reachable** — without that it quoted Duradel on a map holding none of him. Reports `coverage`, because renormalising over reachable tasks flatters a sparse map. |
| `estimate.py` | The four `plan.md` buckets over the **active** set. **Costs the unique *item*, not the task** — one whip answers three tasks — and **clamps per source**, since items off one monster are earned in parallel. Owns the item walk, its bounded `Output` recursion, the `unpriced` list, and **three gates** — monster reachable, slayer task assignable, master reachable. Read the docstring before pricing anything off `WorldIndex`, which spans the whole world. |
| `cache.py` | The disk. `CacheMissError`, the `map_id`/`fetched_at`/`source`/`is_simulated`/`data` envelope, the `--chunkinfo`/`FRAY_CHUNKINFO` override, and the fetched-vs-simulated map layout below (incl. `--map` resolution, atomic writes and the batch-name claim). |
| `firebase.py` | The Firebase-safe string codec, incl. `decode_challenge_keyed`'s mixed `t_N`/literal key handling. Run any payload branch through it before believing it. |
| `chunkinfo.py` | Typed, tolerant accessors over the parsed export. Build **one** `ChunkInfo` per invocation — parsing the ~7MB export is the expensive part. |
| `sections.py` | Which sections of the unlocked chunks are reachable, plus named-area unlocking. `sectionsLimits` deliberately lives in `neighbours.py` instead. |
| `graph.py` | The export's `sections` branch as a **directed** `(chunk, section)` graph, with each edge's `sectionsLimits` gate pre-bound. Shaped for the not-yet-written pathfinding search. |
| `rates.py` | OSRS drop-rate string parsing/formatting, matching JS's rounding because the output lands inside task names. |
| `sources.py` | What the unlocked chunks make available (`SourceIndex`). Applies `taskUnlocks` to items *and* entities, so availability depends on challenge validity. |
| `challenges.py` | Which challenges are valid (`ChallengeResult`) — a two-phase fixed point over 28 of 29 categories. **`BiS` is never evaluated here**; read `pipeline.Derived.bis`. Also **where every derivation command spends its time** — read the docstring's static/dynamic gate split before touching the loop. |
| `bis.py` | Best-in-slot per (combat style, slot). Inherently **non-monotonic**: recomputed fresh per state, never accumulated. |
| `active_tasks.py` | Per-skill active/obsolete/completed classification. A *display* winner only — it never changes `ChallengeResult.valid`. |
| `boosts.py` | Temporary skill boosts. With `rules['Boosting']` on, **every** level comparison upstream makes is boosted, so this is a dependency of `challenges.py`/`active_tasks.py`, not a feature. |
| `other_tasks.py` | The three non-skill categories, `Diary`/`Quest`/`Extra`. No single winner — upstream renders every valid, uncompleted one. |
| `pipeline.py` | `MapState` + `derive`. Owns the **loop** where upstream's area-unlock circularity lives, so the modules above stay one-directional. Raises `ConvergenceError` rather than returning a truncated derivation. |
| `unlock.py` | What one candidate unlock adds, by diffing two `derive` calls. **Owns the project's attribution rule** and its one exception. Additions-only, and only over one `MapState` — for two arbitrary maps read `delta.py`. |
| `delta.py` | The **symmetric** comparison of two derived states, over all six `Derived` branches. Owns the diff primitives `unlock.py` projects down to its one-directional view; the two must agree, which `tests/test_delta.py` asserts. |
| `neighbours.py` | Which chunks are eligible to unlock next, and upstream's canvas numbering (**descending chunk id, 1-based**). Owns the `sectionsLimits` gate. |
| `simulate.py` | Seeded chunk-roll simulation: the bootstrap pool, plus the dispatch to `neighbours.py`. Records are never revisited by a later roll. `simulated_payload` turns a finished ledger back into a map payload — read its docstring before changing which branches it touches. |
| `batch.py` | N simulations from one state, each cached as its own map. Owns seed derivation and the **only** `ProcessPoolExecutor` in the project. `--jobs` must never change a result. |
| `derived_cache.py` | The on-disk cache of `derive` results: the key (hash of every input), the zstd+pickle codec, `cached_derive`, and `CacheBehaviour`/`RollCache` — which of a simulation's states to keep. Pure bar the bytes, which `cache.py` writes. |
| `search.py` | World-wide fuzzy search over the *raw* export — all 5 item routes, so a strict superset of what `fray sources` can list. |
| `summary.py` | Pure reductions over a raw payload. Extend this, not `cli.py`. Also home to `_mapping`, the tolerant dict accessor eight other modules import despite the `_` — Firebase omits empty containers, so every lookup anywhere must survive a missing branch. |
| `cli.py` | argparse subcommands and rendering only; new logic goes in a pure module. |

## Toolchain

Python 3.14.6, mypy, pip (no uv). Run `mypy` and `.venv/bin/pytest` before each commit.

**Zero runtime dependencies, deliberately** — `pyproject.toml` has an empty `dependencies` and
`pytest` alone in the `dev` extra, so a new module gets the stdlib and nothing else. `derived_cache.py`
is the shape that keeps to: it wanted zstd and got it from 3.14's stdlib (`compression.zstd`, PEP 784)
rather than PyPI, and still degrades to plain pickle on a CPython built without `_zstd`.

## Commands

```
pip install -e ".[dev]"     # editable install into .venv; provides the `fray` script
fray fetch [--map ID]       # GET live state -> cache/<map>.json (default map: fray)
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
mypy                        # strict, over src/ and tests/; run from the repo root
.venv/bin/pytest            # whole suite
.venv/bin/pytest tests/test_summary.py::test_summarise_counts_unlocked_chunks   # single test
FRAY_CHUNKINFO=path .venv/bin/pytest tests/test_sections.py -k real   # opt-in oracle test against a real export
python -c 'import json;json.dump(json.load(open("cache/chunkinfo.json"))["data"],open("/tmp/raw.json","w"))'
FRAY_CHUNKINFO=/tmp/raw.json FRAY_MAP_CACHE=1 .venv/bin/pytest   # all six oracles, the real correctness signal
pyproject-build && pipx install --force dist/*.whl   # build + reinstall the `fray` command system-wide
```

Those two lines go together: `FRAY_CHUNKINFO` wants a *raw* export, not `fray chunkinfo`'s
envelope-wrapped `cache/chunkinfo.json` (hence the extraction — see Conventions for why pointing it at
the envelope fails silently), and `FRAY_MAP_CACHE` is presence-only, its value unused.

`--export-json PATH` (or `-` for stdout, replacing the text summary) is carried by the nine
*derivation* subcommands plus `maps list`, not the four I/O ones (`fetch`/`show`/`chunkinfo`/
`heuristics`). `--recompute` is carried by those same nine and nothing else, so it means one thing
everywhere. `--limit` defaults to `None` (full
output) for `sections`/`sources`/`tasks`/`neighbours`/`diff` so piping just works, but to `10` for
`search`. See `cli.py`'s docstring.

`fray diff` is the one subcommand taking two maps, hence `--map1`/`--map2` rather than `--map`; both
are required, and either can name a fetched or a simulated map. It reports **both directions**, which
`fray unlock` deliberately does not — `unlock` is additions-only because adding a chunk is very nearly
monotone, and two arbitrary maps are not related that way at all. Read `delta.py` before assuming the
two commands answer the same question.

**Two kinds of cached map.** A *fetched* map is `cache/<id>.json`; a *simulated* one is anything this
project computed — `fray simulate --cache-map` and `fray unlock --cache-map` both land here — one
directory per run under a named batch:

```
cache/sims/<batch>/batch.json          # every run's seed and rolled chunk ids - the analysis surface
cache/sims/<batch>/run-001/map.json    # a normal envelope, `is_simulated: true`
cache/sims/<batch>/run-001/rolls.json  # that run's per-roll ledger
```

Every subcommand's `--map` takes either kind, because `cache.read_cache` resolves them: a fetched
`cache/<id>.json` wins, then `<batch>/run-00N`, then a bare `<batch>` holding exactly one run (which is
what makes `--cache-map X` then `--map X` work). A bare batch name with several runs is an error naming
them, never a guess. A name that is already taken — by a batch *or* a fetched map — gains `-2`, `-3`,
… so `--map` is never ambiguous; the claim is a `mkdir(exist_ok=False)`, so parallel writers cannot
both win it. Counting how often a chunk was rolled means reading `batch.json`, not the payloads.
An unlock product is a one-run batch that differs only in its envelope `source` and `run.json`'s
`origin`: `is_simulated` and `MapEntry.kind` stay as they are for a simulation, since both mean "this
project computed it, upstream never saw it" — see `cache.write_sim_run` for why a third `kind` isn't
worth what it would cost `maps rm`/`maps clean`.

**The estimator's numbers live in two places, and only one is in `cache/`.** `fray heuristics`
writes the scrape to `cache/wiki_rates.json` (a normal blob, refetchable, gitignored); hand-written
corrections go in **`heuristics/overrides.json`, which is checked in** so they are diffable and
survive a re-scrape. Overrides win, key by key. The export has *no* durations, rates or XP figures at
all, so every number `fray estimate` spends comes from one of those two files or a default in
`heuristics.py` — read that module's docstring on coverage before quoting a total, and
`estimate.py`'s on what `current level` means: **the map records no skill levels** (`maxSkill` is
a declared cap, `passiveSkill` is what's reachable untrained), so `estimate.infer_levels` reads a
floor out of the *completed* challenges — a ticked `Buy the Defence cape` proves 99 Defence. `experience.py`'s XP
curve is the one exact input and is deliberately not overridable.

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

`cache/` is gitignored — including `cache/sims/` — so a fresh clone has no data and
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
- Commit after completing a change, and try to push
- After completing a task, rebuild and reinstall the CLI locally so the `fray` on `PATH` reflects it:
  `pyproject-build && pipx install --force dist/*.whl` (see Commands for why `--force` is required)
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
  `cache/chunkinfo.json` (`fray chunkinfo`'s output) — `cache.read_chunkinfo`'s override path reads it
  directly with no `["data"]` unwrapping, so pointing it at the envelope silently produces wrong or
  incomplete results rather than an error. Extract the raw export first if working from the cache
  (`json.load(open("cache/chunkinfo.json"))["data"]`).
- **`User-Agent` differs by host, deliberately.** Firebase and GitHub get none — those endpoints are
  public and unauthenticated, so there's nothing to disguise and a header would only publish
  information nobody asked for. The **OSRS wiki gets `api.WIKI_USER_AGENT`, and requires it**: an
  anonymous request there is answered with HTTP 403 (measured, not assumed), because the wiki applies
  MediaWiki's user-agent policy asking automated clients to identify themselves. Both rules come from
  one principle — send what the endpoint needs to serve the request, and nothing more about who is
  asking. The header names the project and its repo, never the user.
