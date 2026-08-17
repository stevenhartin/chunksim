# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**This file holds only what spans modules or cannot be discovered from them.** Every module's own
rationale — what it ports, what it approximates, what it refuses to guess at, and the measurements
behind each — lives in its **module docstring**, next to the code it constrains. Those docstrings are
long, current and are the real documentation: **read the module's docstring before trusting its
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
to "which file", which used to be a table here and is now next to the code it describes.

Planned: a shortest-path search ("fewest chunk unlocks to reach X"). `derive/graph.py` is shaped for
it but is **not** speculative — it is the substrate two ported upstream passes already run on
(`findConnectedSections` in `sections.py`, `selectAllNeighborsCanvas` in `neighbours.py`), and
`runs/simulate.py` builds one too. Treat it as load-bearing, not as scaffolding for the unwritten.

The **heatmap** that used to sit beside it is built: the batch dialog's `Show heatmap` folds every
run's `/api/timeline` into one mean per square and paints it in the timeline's own bands. It needed
no Python — the batch is already fetched by the dialog that offers it — which is why the arithmetic
lives in `app.js` beside `runBands` rather than in `gui/panels.py`: that module shapes a `Derived`,
and this shapes ten timelines the browser is holding.

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
  This looks like an obvious optimisation and is not possible: `chunkinfo.activeTasks` holds ~49
  UI-facing answers against the ~2,700 valid tasks this project computes, and the payload has no
  sections, sources or validity branches at all. That is exactly what makes those few entries
  oracles. `completedChallenges` is the player's ticked list, an *input*. What `cache/derived/` avoids
  is computing the derivation *twice*, which is the real version of this optimisation.
- **The pure layer must stay process-parallel, so there is no module-level mutable state anywhere** —
  no `lru_cache`, no module-level memo dicts, no globals; `MapState`/`Derived` are frozen. `chunksim
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

### The computed rate layers, and the one guard that keeps them honest

**A number this project computed beats a number somebody published**, without
exception, and the two computed layers differ only in which of them wins:

```
defaults < scraped < computed (recipe) < modelled (gathering) < overrides
```

`recipe_rates` used to sit *below* the scrape, and the argument for that was
the silver bar: a money-making guide assumes you bought it where the recipe
charges you six minutes for mining it, so the two were said to measure
different things. That is still true and it is no longer the right conclusion.
The guide's shopping trip is the thing a chunk map most often cannot make, so a
recipe reading *below* a guide is the model being right about this map rather
than the model being pessimistic — **a guide is evidence about the action, a
recipe is evidence about the action plus the map**, and the second is what an
estimate here is for. `gathering` still outranks `recipe_rates` for its own
reason: a success curve and a training guide measure the same thing, and the
curve is evaluated at *this* map's level with *this* map's best reachable axe.

**The flip needed one guard, and finding out why is the useful part.**
`recipe_rates`' headline claim is that its join is exact — *on `Output`*. Where
upstream offers several ways to make one thing, one recipe reaches all of them:
`Craft a ~|nature rune|~` and `Craft a ~|nature rune|~ with guardian essence`
share an `Output` and are the altar loop and a minigame. That is **32 outputs
covering 71 tasks** on the reference export, almost all of them Runecraft's
Guardians of the Rift variants and Smithing's `with superheat item` ones. While
the scrape won this was invisible; making the recipe win made it load-bearing,
and it cost Runecraft its whole measured climb — the uber map went 271.4h to
474.9h as a 16,728/hr altar recipe displaced `wiki:gotr`'s 25,000/40,000/50,000
bands. So **an ambiguous join may fill the 1,000/hr floor but may not replace
the scrape**: a recipe that cannot say which of several tasks it describes is
not evidence against a rate that names one. With the guard, the whole flip
moves two climbs on the reference map (Cooking 89.9h → 63.8h, Runecraft
1480.5h → 1448.8h) and nothing at all on the uber map.

**Then two thirds of that ambiguity turned out to be manufactured here.** The
join threw away the field that resolves it: a `{{Recipe}}` carries the wiki's
own *variant* label, so `Bronze bar` is three recipes — `Normal furnace`,
`Blast Furnace`, `Superheat` — where upstream is two tasks, `Smelt a ~|bronze
bar|~` and the same `with superheat item`. Joined on `Output` alone the fastest
won both, which priced the furnace task as a spell and made the pair collide.
`recipe_rates.variant_candidates` gives a task the variants it *names* and
otherwise the ones no sibling named, and `_ambiguous` keys on the recipe chosen
rather than the item made. **Which groups this resolves is the interesting
part**: 13 of the 32, being all twelve bar pairs plus Cooking's chompy on
`Fire` against `Ogre spit-roast`. The other nineteen are Runecraft's `with
guardian essence` and friends, where *every* variant is the empty string
because the minigame has no `{{Recipe}}` at all — so the guard above still
holds them, and it is the wiki rather than a heuristic deciding which case is
which. Smithing's scraped methods went 14 → 2 on the reference map, 15 → 1 on
the uber one and **14 → 0 on the second**; the two that survive are the runite
pair, refused by the sub-floor rule rather than by ambiguity. **No climb on
either map moved**, which is the point: this buys coverage for a map that does
not hold the Giants' Foundry, not a different answer for the two that do.

**The other half of a missed join is a rename, and it reads as a slow method
rather than as a gap.** `recipe_rates` joins on a full string, so upstream's
vocabulary and the wiki's have to agree — and they drift, because the export
lags the game. `Bronze javelin heads` became `Bronze javelin tips` in the
Sailing pre-release of 5 November 2025; the wiki moved the page and left a
redirect, the export still says `heads`, and six Smithing methods sat at the
1,000/hr floor with no rate at all. `Adamant bolts (unf)` is the same failure
over a *space*, against `Adamant bolts(unf)`. So `chunksim recipes` now asks
the wiki, in the forward direction, what the names nothing joined resolve to,
and writes `cache/reference/wiki_aliases.json`. **Direction is the whole cost
argument**: asked forwards it is 256 names in six requests and twenty answers;
asked backwards (`prop=redirects` over every recipe page) it is complete and
useless — measured, 100 pages carry 1,000 redirects and page past `rdlimit=max`,
so the corpus is ~26,000 aliases to recover the twenty anything wants. The
alias may fill a name but **never displaces a recipe that already answers to
it**, since a redirect from `X` says nothing about a recipe whose own output is
`X`. It bought Smithing 7 methods on each map, Crafting 9, and left Smithing on
the second map at **188 computed, 0 scraped, 1 unpriced**. This is also why
`chunksim recipes` is the one fetch subcommand that reads an export: the
question is whether two vocabularies still agree, and neither half alone can be
asked it.

**A published figure that covers part of an activity is a scale, not the
answer.** Tithe Farm is the worked example and the shape is worth copying.
The Farming guide quotes one rate, "from level 74 onwards ... 90,000-100,000",
for a minigame the game opens at **34** - so its two lower seed tiers were
unrated, and `estimate._farming_bands` priced the whole 34-74 stretch at the
growing schedule's blended rate. Both available options were biased: refuse
them (understate, because the schedule's rate is only reachable by waiting) or
lend them the level-74 figure (overstate, because the tiers differ by nearly
four times). The way out was to stop treating the guide as the unit of
evidence. The minigame's *own* page states its reward mechanics, and they
close into `skill_tables.TITHE_SACK_MULTIPLIER` - a full 100-fruit sack pays
**1,610x the fruit's harvest experience**, which reproduces the wiki's three
published per-sack totals (9,660 / 22,540 / 37,030) to the experience point.
So the *shape* of the curve is the wiki's own arithmetic and the published
figure is spent only on the *scale*: one sack's duration, fixed so the top
tier still reads 90,000. The lower tiers then fall out at ~23,000 and ~55,000
rather than being invented, `active` moves from 74 to 34, and a hypothetical
Farming 1->99 on the uber map goes **4,222h to 230.9h**. Neither cached map
moves, because Farming is at goal on both - this is coverage for a map where
it is not.

**Upstream's own flags sometimes already answer the question you were about to
model.** Agility shortcuts looked like 58 unpriced training methods; the wiki's
list shows **93 of 162 award no experience at all**, which would make them
rejects rather than gaps. Mostly they already are: **on the 28 that join today**, every
`Primary: true` shortcut pays something and 29 of the 30 non-primary ones pay
nothing. That is a strong signal and not a rule - widening the join turned up
`Fence (Burgh de Rott)` and `Crevice (Fremennik Slayer Dungeon)`, both
`Primary: true` and both 0 xp - so `costing/shortcuts.py` refuses a
zero-experience shortcut itself (`found.experience <= 0`) rather than trusting
the flag. What the skill
actually needed was a rate: eight ticks an attempt, the failure experience
from each shortcut's own `{{Agility info}}`, and the success curve from
`{{Skilling success chart}}` through the `success_chance` the gathering model
already had. That replaced `heuristics.SHORTCUT_CYCLE_SECONDS`, an 18-second
figure whose own comment called it "a stated target, not a measurement",
chosen so the best shortcut reached ~5,000/hr - so every shortcut is 3.75x
faster now except where a curve damps it (Edgeville to Varrock Sewers goes
2,000 to 3,838 rather than 7,500, succeeding 51% at the level it opens).
45 methods, median ~3,000/hr, best 18,750 - still bad, which is the honest
answer for a door. The join needed both halves: `heuristics.shortcut_keys`
rewrites the three *structural* disagreements (a `#Version` anchor, a version
folded into the parenthetical, a bare object), and
`skill_tables.SHORTCUT_ALIASES` writes down the 22 that are genuine
vocabulary drift - an apostrophe moved, `Burg de Rot` against `Burgh de Rott`,
a qualifier upstream lacks. **A word-overlap scorer proposed 21 more and was
rejected**: it offered a Shilo Village stepping stone for a house window in
Aldarin and collapsed five Brimhaven Dungeon shortcuts onto one Lumbridge
stone. Those 37 stay unpriced, which is the honest state for a join nothing
here can verify.

**Not every "computed" number is evidence, and the docstrings say which.**
Thieving's fifteen tabulated stalls come out at exactly 1.00x against the
scrape, and that is an identity rather than agreement — the wiki's column is
`3600 / respawn * xp` and so is the model. Mining's one fitted row is the same
standing for the opposite reason: one parameter against one observation. Read a
1.00x in `costing/gathering_overhead.py`'s output as a claim about arithmetic
until the docstring says otherwise; the numbers that carry information are the
ones with several rows and a residual, like Woodcutting's 12/17 and Hunter's
6/10.

**The third layer is not a rate at all, and that is what makes it compose.**
`costing/production.py` reads the same `Module:Skill calc` tables the gathering
model does, for a different column: what one action *consumes*, against the XP
that action pays. A calculator row carries no ticks, so it can never state a
rate - it states a **material cost**, which `training.effective_xp_per_hour`
folds into whichever rate won. That is why it needs no place in the ordering
above: a published figure keeps the method and simply stops being quoted with
its materials free.

It is the general form of a correction that used to be written by hand, one
method at a time, and the numbers say why it was worth generalising: on the
reference map **Fletching 1 -> 99 went 30.0h to 244.9h** and **Firemaking 35.2h
to 81.3h**. Both were topped by a method charged nothing for what it burned or
fletched. The Firemaking case also shows the shape of the bug to watch for -
the export carries `Burn ~|magic logs|~` *and* `Burn ~|magic logs|~ at a fire`,
they render to the same words, and while only one of them joined, **the
uncharged twin outranked the charged one**. A join that misses does not read as
a gap; it reads as a faster method.

**A modelled rate is not one number**, which is the other thing to know before
reading `costing/training.py`. A gathering rate is a function of level, so
`gathering.apply` writes the opening-level figure into `Heuristics.training` and
`gathering.banded_methods` puts the rest of the curve into `Heuristics.computed`
— which already carries a level per entry, because combat and Prayer needed one.
`training_bands` then opens each point where it belongs, and a climb reads as one
method getting faster rather than as ten methods.

**The modelled layer does not make the scrape redundant, and the measurement
says so.** Once all five gathering skills were modelled the obvious cleanup was
to drop the training-guide stages the model outranks. It is wrong, structurally
rather than for now: the model prices a *node, a roll and a chance*, and the
methods only the scrape reaches have none of the three. Measured over the whole
export, methods only the scrape can price — Fishing 15, Hunter 16, Mining 18,
Thieving 19, Woodcutting 4 — are Forestry events, Wintertodt, Pyramid Plunder,
shooting stars, Rogues' Castle chests and barbarian fishing. **No skill
calculator states an experience-per-action for an activity, because there is no
repeatable action to state one for**, which is why 196 of the model's 281
refusals are "no experience row" and why almost all of them are right. The two
sources partition the skill: the model owns the loop, the scrape owns the
activities, and where they overlap the layering already prefers the model — on
both cached maps every *reachable* gathering method is `modelled`.
`tests/test_costing_gathering.TestTheScrapeIsNotRedundant` pins it per skill, so
a later "these look superseded" cannot pass review by looking like a tidy-up.
**Mining has since reached zero and is asserted separately rather than dropped
from the list** — its three scrape-only methods were closed by finding each
mechanic on its own page, not by trusting the guide, and the test now pins the
zero in both directions so a regression reads as one. That is the shape any
other skill leaving the set has to take.

**`chunksim gather-tables` is the one subcommand that writes into `src/`.**
Everything else that fetches writes a cache blob a user is expected to refresh;
this writes `src/chunksim/heuristics/gathering.json`, which is checked in and
shipped as package data. That is deliberate — the tables move about once a game
update, and making every install re-read six hundred wiki pages would cost the
estimator a network dependency it does not otherwise have. **`chunksim estimate`
must never reach that code**, which is why the fetching is injected into
`gathering.build_tables` rather than imported by it.

### Test against more than one map

Every rule in a map's `rules` branch is a number or a flag a *player* set, so a second map is a
second set of inputs rather than more of the same data. A second real map alone found three
defects nothing in
the repo could have — including a `0` that reached a ratio parser as `"1/0"` (JS yields `Infinity` and
raises nothing; Python disagreed) and two unported BiS rules. The BiS oracle, the `Diary`/`Extra` one
and the per-skill one all run over **every fetched map in the cache**, so `chunksim fetch --map <other>`
is all it costs to widen the signal, and it is the fastest way to find the next defect. **A map is a
set of rules a player chose**, so a second one is a second set of inputs rather than more of the same:
41 of the first map's 104 rules are off, and every one of those is a stretch of upstream nothing here
could see — `BIS Skilling` being off there is how a whole unported `Set` sweep survived a category
whose active set is asserted exactly. Each map's residual disagreement is pinned by *name* in
`tests/test_other_tasks._KNOWN_ORACLE_DELTA`, and a map with no entry there fails rather than quietly
widening what the suite asserts. The GUI's undocumented `__UBER__` fetch (see `gui/actions.py`)
builds a map holding every **rollable** chunk on top of whichever map is open, which is what the
docstrings' measurements are quoted against. **Rollable is `chunkinfo['sections']`, not
`chunkinfo['chunks']`** — 1,172 of the export's 2,234, the rest being unwalkable squares and 315
named areas a roll can never land on. It used to unlock all 2,234, which built a state no player can
be in and made 11,135 tasks valid against the rollable set's 10,111.

### Where things live

**What each individual module owns lives in its subpackage's `__init__.py`**, as one entry per
module, and that is where a new module's entry goes too. Read the `__init__` before working
anywhere in the directory; this file names only the eight, because a sixty-row table of files nobody
is touching is context spent on nothing every session.

| Subpackage | What it is, and the rule it carries |
|---|---|
| `model/` | Upstream's data as typed, tolerant accessors, the Firebase wire codec, and the two exact vocabularies — drop-rate strings and the XP curve. **Imports from no other subpackage**, so it is the one to read first and then stop thinking about. |
| `remote/` | Every outbound call, and every wikitext parser reading what comes back. **`api.py` is the only module in the project that opens an outbound connection** — one directory to grep for `urlopen` rather than an honour system. |
| `store/` | Every disk touch: `cache/`'s layout and envelope, the content-keyed derived cache, and this install's own metadata. Holds the one **upward** edge in the layering, because a store of results has to know their shape. |
| `derive/` | The derivation chain and everything that walks or diffs it. **No module-level mutable state, across all fifteen modules** — `--jobs N` runs them in worker processes, and a cache here breaks that as runs that disagree. |
| `costing/` | Derivation -> hours: the rate layers, the item walk, and the per-skill models. **`dps_bridge.py` is the only module that may import `osrs_dps`**, and the extra must stay optional. |
| `runs/` | What a run is: a base state, its rolls, its replay. **A run is self-contained** — stepping one needs no base map, no export and no `derive`. |
| `cli/` | One module per subcommand family, `add_parser` beside handler, so a flag change edits one file. The only `__init__` carrying code, because `[project.scripts]` names `chunksim.cli:main`. |
| `gui/` | The local server and the browser front end, split by **what each route costs**: `routes_view.py` answers without parsing the export and `routes_derived.py` may not. `resources/` is the front end itself. |

### Two constraints on the GUI worth knowing before editing it

**Panels heal themselves; nothing tells them to.** `poll` compares two tokens from `/api/revision`:
`data`, a stamp over the files an answer is computed from (`cache.data_stamp` — the export, the tasks
map, the wiki files), and `revision`, the map's own mtime. Watching only the second was a real bug —
the map file does not move when the export arrives, so a panel that rendered before it landed stayed
on its placeholder for ever. **Do not fix a stale panel by calling `reloadPanels` from wherever the
data changed**; that is the pattern this replaced, and the number of places needing it is the problem.
Chrome throttles the timer in a hidden tab, so a `visibilitychange` listener polls on the way back.

- **The map is the OSRS wiki's cartography tiles and the browser loads them — this project never
  touches one.** `/api/tiles` hands out a URL *template*. That is a **licence decision, not an
  optimisation**: the tiles are CC BY-NC-SA 3.0 against this project's GPL-3.0, so caching them under
  `cache/` or re-serving them off loopback would make this a redistributor of NonCommercial artwork,
  where linking makes it a page with a picture on it. `tests/test_gui_contract.py` asserts no tile
  route exists, so a later "let's cache these" cannot pass review by looking like a speed-up.
- **One vocabulary for how near a chunk is, everywhere.** `data-hold` is `unlocked` / `reachable` / `locked`, and the Find icons, the chunk pills, the section pills and the chunk cards all speak it. It is the map's own language: green a square you hold, blue one you can walk into without rolling it, grey neither. **A reachable chunk offers no unlock**, because it costs no roll and never appears among the candidates — measured on the reference map, the reachable, rollable and held sets do not intersect at all.

**Constants crossing into JavaScript have nothing enforcing agreement**, so
  `tests/test_gui_contract.py` reads `app.js` and asserts them against the Python. It also pins the
  interface rules that each replaced a bug (one tooltip system; chip strips record what is *off*;
  no `raw()` interpolation inside an attribute) and that every length in `style.css` comes from the
  one scale. `app.js` is heavily commented and is where the front end's rationale lives. **Type comes from tokens like every other length**: two faces (`--sans`, `--mono`) and four steps (`--t-micro`/`--t-note`/`--t-body`/`--t-title`), with a contract test refusing a bare `font-size` or `font-weight` — font size was the one length that had escaped the scale.

## Toolchain

Python 3.14.6, mypy, pip (no uv). Run `mypy` and `.venv/bin/pytest` before each commit.

**Zero *required* runtime dependencies, deliberately** — `pyproject.toml` has an empty
`dependencies`, so a new module gets the stdlib and nothing else. `store/derived_cache.py` is the
shape that keeps to: it wanted zstd and got it from 3.14's stdlib (PEP 784) rather than PyPI, and
still degrades to plain pickle on a CPython built without `_zstd`.

There are two extras and they are not alike. `dev` is `pytest`. **`dps` is
[`osrs-dps`](https://github.com/stevenhartin/osrs-dps), and it must stay optional** — this project has
*no* required runtime dependencies and that one would be the first. It used to be a licence boundary
as well, GPL-3.0 against this project's MIT; **that half is gone — chunksim is GPL-3.0-or-later now,
so the two can ship in one distribution.** What did not change is the code: it is a package a user
installs deliberately, never vendored in, and `costing/dps_bridge.py` is the only module that may import it — behind a
`try`/`except ImportError` that sets `DPS_AVAILABLE`. Importing `dps_bridge` is always safe; calling
into it without the extra raises `DpsUnavailableError`. Its tests skip rather than fail when the
extra is absent, like the `CHUNKSIM_CHUNKINFO` oracles. A change to `osrs-dps` that moves a number is a
change to `chunksim estimate`'s answers, so run both suites.

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
chunksim heuristics             # GET wiki/spreadsheet rates -> cache/reference/wiki_rates.json (30+ requests)
chunksim recipes [--chunkinfo P] # GET per-action xp + tick costs -> cache/reference/wiki_recipes.json
                                # + the wiki's renames -> cache/reference/wiki_aliases.json
chunksim gather-tables          # developer only: GET the gathering tables -> src/chunksim/heuristics/gathering.json
chunksim estimate [BUCKET] [--limit N]                 # rough hours for the outstanding active tasks
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
`chunksim chunkinfo`'s envelope around one), `CHUNKSIM_MAP_CACHE`
(presence-only), `CHUNKSIM_SLOW_ORACLES` (presence-only), `CHUNKSIM_NO_WATERMARK`, `CHUNKSIM_TILE_VERSION`,
`CHUNKSIM_GUI_VERBOSE`.

**Flag conventions, so each means one thing everywhere.** `--export-json PATH` (or `-` for stdout) and
`--recompute` are carried by the nine *derivation* subcommands and nothing else (`--export-json` also
by `maps list`), not by the five I/O ones. `--limit` defaults to `None` — full output, so piping just
works — except for `search`, where it is `10`. **`--map ID` is carried by every subcommand that reads a
cached map**, so the usage lines above name it only where the map *is* the point; `chunksim diff` is the
one taking two, hence `--map1`/`--map2`, and it reports **both directions**, which `chunksim unlock`
deliberately does not. **`--chunkinfo PATH` is the per-invocation form of `CHUNKSIM_CHUNKINFO`** and rides
along on all ten subcommands that parse the export — plus `chunksim recipes`, which is not one of
them and reads an export for a different reason: to ask the wiki which of upstream's item names it
has since renamed. See the vocabulary-lag paragraph above.

**`cache/` is sorted by purpose, and `cache/maps/` holds maps and nothing else holds maps.** That
sentence is the layout's whole point: `list_maps` used to glob `cache/*.json` and skip the names it
*knew* were not maps, so every new blob had to be remembered or it turned up in the picker as a map
that failed the moment it was chosen. A directory cannot be forgotten.

```
cache/maps/fetched/<id>.json       # from Firebase; only `chunksim fetch` writes one
cache/maps/simulated/<batch>/…     # rolled by `chunksim simulate`
cache/maps/edited/<batch>/…        # made by hand: `chunksim unlock --cache-map`, or the GUI
cache/reference/                   # chunkinfo, tasks_map, wiki_rates, wiki_recipes, wiki_aliases,
                                   # tile_version
cache/derived/                     # pipeline.derive + dps_bridge.enrich results, keyed by content
cache/overrides/<map_id>.json      # heuristic corrections belonging to one map
cache/assets/                      # section masks, skill icons, CA tier icons
cache/gui/                         # window.json, settings.json, and the browser profile
```

A batch of any computed kind holds `batch.json` (seeds, rolls, `batch_id`, and the payload it rolled
from) beside one directory per run holding `map.json`, `rolls.json`, `run.json` and `timeline.json`.
**A name is claimed across every kind**, so `--map foo` never has to guess which directory meant it.
**Where `cache/` itself lands is `data_root`'s answer, and it is three answers in order**:
`CHUNKSIM_CACHE` if set; else the checkout you are standing in; else the user's own data directory
(`%LOCALAPPDATA%\chunksim`, `~/Library/Application Support/chunksim`, `~/.local/share/chunksim`).
The middle one needs **`pyproject.toml` *and* `src/chunksim/`** — `pyproject.toml` alone is any Python
project, and an installed `chunksim` run from inside one must not decide that project is its home.
That last branch used to be the working directory, which is harmless in a checkout and wrong
everywhere else.

`cache/` is gitignored, so a fresh clone has no data until `chunksim fetch`/`chunksim chunkinfo` run — and
so is `/*.json` at the repo root, which is where `--export-json` output lands when it is aimed at
the checkout rather than `/tmp` or stdout. A stray `tasks.json` there is that, not project data.

**The estimator's numbers live in four places and only two are in `cache/`.** `chunksim heuristics`
writes the scrape to `cache/reference/wiki_rates.json` (refetchable, gitignored); hand-written
corrections go in **`src/chunksim/heuristics/overrides.json`, which is checked in *and* shipped as
package data** so they are diffable and
survive a re-scrape; and corrections belonging to *one map* go in `cache/overrides/<map_id>.json`,
which is cache data and gitignored with the rest. The fourth is
**`src/chunksim/heuristics/gathering.json`**, the scraped gathering tables — checked in and shipped
like the corrections beside it, but a *scrape* rather than a hand opinion, so it is regenerated
wholesale by `chunksim gather-tables` and corrected through `overrides.json` like everything else.
`heuristics/README.md` is the guide to which numbers are worth correcting. The export has *no* durations, rates or XP figures at all, so every
number `chunksim estimate` spends comes from one of those three files or a default in
`costing/heuristics.py`.

The merge is `defaults < scraped < overrides < map overrides`, and it happens **once**, in
`load_reference` — so `ReferenceBlobs.overrides` is the *effective* set and every downstream reader
(`load_heuristics`, `levels`, `pinned`, `recipe_priced`) gets the fourth layer without being told
about it. A `ReferenceBlobs` is therefore about one map, which is why `map_id` is on it and why the
GUI memoises one per map. **Both apps must pass the map id or neither should**: `costing/inputs.py`
exists because `chunksim estimate` and the Estimate tab had already drifted once, and a layer one of them
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
swept into a release commit. A failed build leaves them modified and says so.

`build.bat` is the one file here that cannot be tested where it is written. Its syntax and its first
two steps were run under `wine cmd`; the wheel build, the payload step and Inno Setup need a real
Windows box. **`%ProgramFiles(x86)%` is read outside every parenthesised block on purpose** - the
brackets in its *value* close an `if` block early, which is how a batch file that reads correctly
fails only on the machines that have it set.

**Embeddable CPython, not a freeze**, and the reason is this project's own shape: zero runtime
dependencies means there is no graph to resolve, while `gui.RESOURCE_DIR` and
`cache.PACKAGED_OVERRIDES` are `__file__`-relative and `build_info` reads `importlib.metadata` — all
three of which a one-file freeze breaks or has to be told about. The wheel must exist first: its
`.dist-info` is copied beside the package, and without it the watermark and the update check both go
quiet. The interpreter is verified against the SHA-256 in python.org's **SPDX SBOM** (`*.spdx.json` —
there is no `SHA256SUMS`).

**The Windows build bundles `osrs-dps`, and that is what the relicense was for.** Both projects are
GPL-3.0-or-later now, so they may ship as one work — which also means recipients are entitled to the
corresponding source for *both*. chunksim is public; `osrs-dps` is not, so pointing at a repository
would answer for half of what is installed. The payload therefore carries `source/`: an sdist for
each, built in the same invocation as the wheels so the two correspond, and a `README.txt` saying so.
`verify_payload` treats a missing archive as a build failure — the licence half is checked like the
code half. `--without-dps` (or `/nodps`) builds without it, and a missing sibling checkout warns
rather than fails.

**Three cross-file contracts, all pinned by `tests/test_packaging.py`**: the installer's
`OutputBaseFilename` must end in `api.INSTALLER_ASSET_SUFFIX` or the updater never finds the asset;
`AppVersion` must match `pyproject.toml` or an update installs itself forever; and `AppId` is a fixed
GUID, which is what makes a new version an upgrade rather than a second Add/Remove entry.

**`wine` runs the payload**, which is how this was verified without a Windows machine — the
interpreter, the CLI, the `%LOCALAPPDATA%` branch of `data_root`, the packaged corrections and the
GUI serving on loopback. It is also what found `dps_bridge` raising `NameError` on import without the
optional extra, which every test environment had hidden. Compiling the `.iss` still needs Inno Setup.

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
CHUNKSIM_CHUNKINFO=cache/reference/chunkinfo.json CHUNKSIM_MAP_CACHE=1 .venv/bin/pytest   # every oracle
CHUNKSIM_CHUNKINFO=… CHUNKSIM_MAP_CACHE=1 CHUNKSIM_SLOW_ORACLES=1 .venv/bin/pytest            # + the slow ones
```

Run those before trusting a change to `sections`/`sources`/`challenges`/`bis`/`active_tasks`/
`other_tasks`, and **treat a failure as a bug in this code rather than a stale oracle.** Do not report
a green `.venv/bin/pytest` as a change being verified.

- **Upstream is live, so pin shape exactly and size only where zero kills the claim.** The export
  grows: two edges and a `"???"` arrived between fetches a week apart, and exact counts turned that
  into oracles reporting this code as wrong when nothing here had moved. A count is quoted to defend
  an argument — "the graph must stay directed", "the placeholder still exists", "most casts have a
  rune cost" — and an argument dies at zero or at a ratio, not at a different magnitude. What stays
  exact is anything that would mean upstream changed *shape*: a target outside `sections`, a third
  `sectionsLimits` entry, a `"???"` node that gained a real ref. **Re-fetch and re-run is the sync
  ritual** — `chunksim chunkinfo` then the oracle line below — and the module docstrings carry their
  measurements with the date they were taken.
- **The oracles are marked, not `skipif`-ed.** `@pytest.mark.real_cache` (needs the export *and* this
  checkout's populated `cache/`), `@pytest.mark.real_export`, or `@pytest.mark.slow` (minutes, and
  gated on `CHUNKSIM_SLOW_ORACLES` so the ordinary oracle run stays worth typing — today that is the
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
- **A new module lands in two docstrings**: its own (why it exists and what it refuses to guess at)
  and its subpackage's `__init__.py` (one entry saying what it owns). Nothing about it belongs in
  this file unless it changes something that spans subpackages.
- **`README.md` is the user-facing counterpart and describes every subcommand and most flags**, so a
  new subcommand, a renamed flag or a changed default lands in three places: the module docstring
  (why), this file (what spans modules) and the README (what a user types). It is the one that
  drifts, because nothing in the test suite reads it.
- Run `mypy` and `.venv/bin/pytest`, then commit and push per change. Tracks `main` over SSH.
