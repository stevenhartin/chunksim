# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

fray-claude is a CLI that reads state from the source-chunk web app, caches it locally, and runs
offline operations on that cache. source-chunk is upstream and read-only from here.

Landed: derive reachable sections/available sources/valid tasks from a cached map, per-chunk unlock
deltas, and multi-roll simulation (`fray unlock`/`fray simulate`) — see `challenges.py`'s docstring
for what's deliberately unsupported before trusting the numbers.
Planned: render a world-map image for a simulated state, generate heatmaps of likely rolls over N
attempts, estimate time to complete all goals (needs a task-duration source; the export has none).

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
`manualSections`/`stickeredNotes`/`activeTasks`/`checkedChallenges`/`backlog` are encoded.

## Architecture

One responsibility per module, so the planned simulation work has a pure layer to build on:

- `api.py` — the only module that touches the network; raises `FetchError`. An unknown map comes back
  as HTTP 200 with a bare `null` rather than a 404, so that is the only "no such map" signal.
- `cache.py` — the only module that touches disk; raises `CacheMissError`. Stores the payload in an
  envelope (`map_id`/`fetched_at`/`source`/`data`), so readers go through the `data` key. Finds
  `cache/` by walking up to the nearest `pyproject.toml`, letting the CLI run from any subdirectory.
  Non-map blobs (the chunkinfo export, tasks map) go through the generic `write_blob`/`read_blob`
  pair instead; `read_chunkinfo` layers an override (`--chunkinfo` / `FRAY_CHUNKINFO` env var) in
  front of the cached copy, for working from an existing local export.
- `firebase.py` — pure; the Firebase-safe string codec (`decode_string`, `decode_key`, `decode_value`,
  `decode_payload`). Port of `decodeQueryParam`/`decodeObject` from upstream's `index.js`; run any map
  payload branch through this before treating it as real chunk ids, rule names, or task text.
- `chunkinfo.py` — pure; typed, tolerant accessors (`ChunkInfo`) over the parsed chunkinfo export.
  Parsing the ~7MB export is the expensive part, not attribute access, so build one `ChunkInfo` per
  command invocation and pass it down rather than re-parsing.
- `sections.py` — pure; which sections of the unlocked chunks are reachable (`unlocked_sections`), a
  fixed point over `chunkinfo.json`'s `sections`/`chunks` connectivity. Port of `findConnectedSections`
  plus the one live part of `getAllChunkAreas` — its automatic area-detection branch is upstream dead
  code (a filter predicate with no `return`, always falsy), so only the `manualAreas` override is
  reproduced. `sectionsLimits` deliberately isn't used here: it gates *rollable-neighbour* eligibility,
  not the connectivity of chunks already unlocked, so it belongs with `simulate.py` instead.
- `rates.py` — pure; OSRS drop-rate string parsing/formatting (`parse_ratio`, `find_fraction`,
  `looks_non_numeric`). Centralises what upstream re-parses inline at every use site; `find_fraction`'s
  output string is embedded verbatim in synthesized task names (stage 3), so its half-away-from-zero
  rounding and no-trailing-zero formatting deliberately match JS's `Math.round`/`Number.toString`
  rather than Python's.
- `sources.py` — pure; what the unlocked chunks make available (`gather_chunks_info` ->
  `SourceIndex`: items/objects/monsters/npcs/shops). Port of `gatherChunksInfo`, including the
  drop-rate threshold (`Rare Drop Amount`) and primary/secondary classification (`Secondary Primary
  Amount`) that decide whether/how an item appears — both feed ordinary challenge validity, unlike
  the quantity-keyed `dropTablesGlobal` side table (upstream's `calcedQuantity`), which only the
  dynamic "Every Drop"/"All Droptables" challenge synthesis in `calcChallengesWork` consumes and so
  belongs with `challenges.py` instead. The `KeyItem Bosses` rate-boosting pass is unported; a map
  with that rule on makes `gather_chunks_info` raise `NotImplementedError` rather than silently
  producing an incomplete index.
- `challenges.py` — pure; which challenges are valid given the source index (`calc_challenges` ->
  `ChallengeResult`), a fixed point over 28 of the 29 categories. `BiS` (`UNSUPPORTED_CATEGORIES`) is
  not computed at all, not reduced-scope: unlike every other category, `BiS` challenges have no static
  definition anywhere in `chunkinfo.json` — upstream's `calcBIS` (~3,000 lines) synthesizes them at
  runtime by comparing the `equipment` table's combat stats across slots per combat style, with
  weapon-ammo pairing and dynamic "Obtain a/an X" task-name generation. It shares no structure with
  requirement-checking, so `valid['BiS']` is simply never populated — its absence means "not
  evaluated", not "nothing valid". Port of the core of `calcChallenges`/`calcChallengesWork`
  (~1,500 dense lines) for the other 28 — **deliberately partial, read the module docstring before
  trusting output**. In short: `Chunks`/`Objects`/`Monsters`/`NPCs`/`Mix` requirements (incl. `[+]`
  families) are exact. `Items` requirements are basic presence only — a `[+]` family or `*`
  secondary-marker item is not evaluable, and since those are the overwhelming majority of real
  `Items` entries, `calc_challenges` catches that failure *per challenge* rather than aborting the
  whole computation, collecting affected `skill/name` pairs in `ChallengeResult.unsupported` so the
  gap stays visible rather than reading as "checked and invalid". `processingSkill` categories
  (Runecraft/Magic/Herblore/Cooking/Firemaking/Fletching/Smithing/Crafting/Construction) get plain
  presence checking too, not upstream's "Highest Level" grouping — a real, silent accuracy gap for
  those 9 categories, not a raise, documented in the module docstring. The output-feedback fixed point
  (`_seed_items_with_outputs`) is this module's own design, not a located port — upstream's exact
  mechanism for it wasn't found despite an extensive search of `calcChallengesWork`.
- `pipeline.py` — pure; bundles the per-map inputs (`MapState`) and runs `unlocked_sections` ->
  `gather_chunks_info` -> `calc_challenges` for a given unlocked-chunk-id set (`derive`).
  `load_map_state` decodes a raw cached-map payload into a `MapState` once; `unlock.py`/`simulate.py`
  (and `cli.py`'s `sections`/`sources`/`tasks` subcommands) all call `derive` rather than re-deriving
  the same pipeline themselves.
- `unlock.py` — pure; what a single candidate chunk unlock adds (`tasks_added_by` -> `UnlockDelta`),
  by running `pipeline.derive` for the unlocked set and for that set plus the candidate, then diffing.
  This is the module the project's attribution rule lives in: because `ChallengeResult.valid` only
  ever grows (every requirement `challenges.py` checks is a presence check, never an absence check),
  the diff partitions cleanly — each task belongs to exactly the one unlock that first made it valid,
  and a later unlock can never retroactively change an earlier delta. Diffing the *panel*
  (`calcCurrentChallenges2`, not ported) instead would be wrong: it shows only the highest challenge
  per skill and re-picks BiS as better items appear, so it is not monotonic.
- `simulate.py` — pure; simulates chunk rolls and accumulates the tasks/sections they unlock
  (`simulate_rolls` -> `list[UnlockRecord]`), each record built via `unlock.delta_from` and never
  revisited by a later roll. Two roll mechanisms, ported from index.js: a "random start" bootstrap
  pool (`walkableChunks`/`walkableChunksF2P` filtered by `settings.rollingChunksOptions`) used only
  when nothing is unlocked yet, and an ongoing neighbour pool (port of `selectAllNeighborsCanvas`) —
  every chunk orthogonally grid-adjacent (`±1`, `±256`; the grid is 256 chunks tall) to an unlocked
  chunk, expanded through `chunkinfo.json`'s `sections` connectivity graph and gated by
  `sectionsLimits`' task requirements (this is `sectionsLimits`' actual purpose — see `sections.py`).
  A seeded `random.Random` picks uniformly from whichever pool applies, over a *sorted* candidate list
  so the same seed reproduces the same run regardless of set/dict iteration order. Not modelled: manual
  chunk selection/blacklisting, `roll2`/`roll5` bonus rerolls, and the `chunkNeighboursOptions` UI
  conveniences — all user-interaction features orthogonal to a pure roll simulation.
- `summary.py` — pure, I/O-free reductions over a raw payload; extend this layer, not `cli.py`.
  Firebase omits empty containers rather than storing them, so every lookup must tolerate a missing
  branch — `_mapping` exists for that; reuse it (`chunkinfo.py` does too, over the export instead of a
  map payload).
- `cli.py` — argparse subcommands only. `main()` funnels `FetchError`, `CacheMissError`, and
  `NotImplementedError` into a stderr message and exit 1; a new subcommand keeps its logic in a pure
  module (`_load_state` -> `pipeline.load_map_state` handles the common cache-read + decode step).
  `--export-json PATH` (where supported) writes a subcommand's full result as JSON to `PATH`, or to
  stdout if `PATH` is `-` — in which case it replaces the human-readable summary on stdout rather than
  interleaving with it, so piping stays clean.

## Toolchain

Python 3.14.6, mypy, pip (no uv). Run `mypy` before each commit.

## Commands

```
pip install -e ".[dev]"     # editable install into .venv; provides the `fray` script
fray fetch [--map ID]       # GET live state -> cache/<map>.json (default map: fray)
fray show  [--map ID]       # summarise the cached copy; no network
fray chunkinfo              # GET upstream's chunk/challenge reference data -> cache/{chunkinfo,tasks_map}.json
fray sections [--map ID]    # reachable sections for the cached map's unlocked chunks
fray sources  [--map ID]    # items/objects/monsters/npcs/shops the cached map's unlocked chunks give
fray tasks    [--map ID]    # which challenges are currently valid (partial - see challenges.py)
fray unlock   --chunk ID    # tasks/sections one candidate chunk would add on top of the cached map
fray simulate --rolls N [--seed S]   # simulate N chunk rolls and accumulate their tasks/sections
python -m fray_claude ...   # same CLI without the console script
mypy                        # strict, over src/ and tests/; run from the repo root
pytest                      # whole suite
pytest tests/test_summary.py::test_summarise_counts_unlocked_chunks   # single test
FRAY_CHUNKINFO=path pytest tests/test_sections.py -k real   # opt-in oracle test against a real export
pyproject-build && pipx install --force dist/*.whl   # build + reinstall the `fray` command system-wide
```

The system mypy is configured with `python_executable = ".venv/bin/python"` so it can see pytest's
stubs, which is why it must run from the repo root and needs the venv to exist.

`cache/` is gitignored, so a fresh clone has no data and `fray show`/`fray sections` fail until
`fray fetch`/`fray chunkinfo` run. `fray chunkinfo` downloads ~10MB; `--chunkinfo PATH` or the
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
- Commit after completing a change
- After completing a task, rebuild and reinstall the CLI locally so the `fray` on `PATH` reflects it:
  `pyproject-build && pipx install --force dist/*.whl` (see Commands for why `--force` is required)
- Tests are pytest, in `tests/`, named after the module under test (`tests/test_summary.py`). No test
  touches the network or the real `cache/`: pass `cache.py`'s `root` a `tmp_path`, and monkeypatch
  `urllib.request.urlopen` (`tests/test_api.py`) or `fray_claude.cli.fetch_map` (`tests/test_cli.py`).
  Any test calling `cache.read_chunkinfo()` without an explicit `override` must
  `monkeypatch.delenv("FRAY_CHUNKINFO", raising=False)` first, or an ambient env var shadows `tmp_path`
- A test that needs the real (~7MB) chunkinfo export is opt-in, not run by default: build fixtures by
  hand for the normal suite, and gate the real-export check on `FRAY_CHUNKINFO` with
  `pytest.mark.skipif`, so a fresh clone stays green
  (`tests/test_sections.py::test_manual_sections_match_a_real_export` is the existing example)
- No custom `User-Agent` on requests — the endpoint is public and unauthenticated, so there's nothing
  to disguise
