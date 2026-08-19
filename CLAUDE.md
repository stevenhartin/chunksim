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

**And the last nineteen groups were resolved by the other field.**
`variant_candidates` records them as beyond it - "Runecraft's `with guardian
essence` and friends, where every variant is empty because the minigame has no
`{{Recipe}}` at all" - which was half right. The minigame has no recipe, but
the *essence* does: the wiki writes one `Nature rune` recipe per essence it
accepts, and upstream writes `Items: ["Pure essence*"]` on the altar task and
nothing at all on the minigame one. So the distinguishing field was never
missing; it was in the **materials** rather than in the label, and
`recipe_rates.material_candidates` reads it exactly as `variant_candidates`
reads the other. What it cost: all twelve altar runes shared a key with their
Guardians of the Rift twin, because `rate_for` maximises and pure essence is
the fastest thing that prices - so the twin took the pure-essence recipe too,
and `apply`'s guard held the six with a money-making guide on that guide.
**Runecraft is now off the scrape entirely** with the climb unmoved at 228.2h,
since Guardians of the Rift owns it either way.

**The signal is upstream's `Items` and not the task's words**, which Fletching
is the proof of: every `Fletch ~|X logs|~ into shafts` task contains the word
`logs`, so a word-subset test says the magic one describes the plain-log recipe
too - `names_variant`'s "must not match a task that merely says furnace"
arriving through a different door. All six were taking one recipe regardless of
which log they named; each now takes its own, and the rates fall away from
plain logs at 4,390/hr to magic at 1,026 exactly as the chopping gets slower.

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

**A `#` in upstream's item name is a wiki section, and the section is the
variant.** Upstream writes `Build a ~|wooden hull#Raft|~`; the wiki has one
`Wooden hull` page carrying three `{{Recipe}}`s labelled `Raft`, `Skiff` and
`Sloop`. Only the whole span was offered as a join key, so none of the boat
parts joined anything and 45 Construction methods sat unpriced. Offering the
**page half** fixes it and nothing else was needed — the anchor stays in the
task's own words, so `variant_candidates` reads `Raft` out of them exactly as
it reads `Superheat` out of `with superheat item`. It is offered **last**,
because an anchor is usually a *place*: 1,872 marked spans carry a `#` and most
are objects (`coal rock#Miscellania`, `soil#Fossil Island`), so the corpus
decides — 169 name a page that is a recipe output whose variants include the
anchor. Construction went **492 modelled to 531** and no climb moved on any of
the three maps, boat parts running 89/hr to 17,763/hr.

**The other half of a missed join is a rename, and it reads as a slow method
rather than as a gap.** `recipe_rates` joins on a full string, so upstream's
vocabulary and the wiki's have to agree — and they drift, because the export
lags the game. `Bronze javelin heads` became `Bronze javelin tips` in the
Sailing pre-release of 5 November 2025; the wiki moved the page and left a
redirect, the export still says `heads`, and six Smithing methods sat at the
1,000/hr floor with no rate at all. `Adamant bolts (unf)` is the same failure
over a *space*, against `Adamant bolts(unf)`. So `chunksim recipes` now asks
the wiki, in the forward direction, what the names nothing joined resolve to,
and writes `src/chunksim/heuristics/wiki_aliases.json`. **Direction is the
whole cost argument**: asked forwards it is 701 names in fifteen requests and
thirty-seven answers; asked backwards (`prop=redirects` over every recipe page)
it is complete and useless — measured, 100 pages carry 1,000 redirects and page
past `rdlimit=max`, so the corpus is ~26,000 aliases to recover the few anything
wants. The alias may fill a name but **never displaces a recipe that already
answers to it**, since a redirect from `X` says nothing about a recipe whose own
output is `X`. It bought Smithing 7 methods on each map, Crafting 9, and left
Smithing on the second map at **188 computed, 0 scraped, 1 unpriced**.

**Which names get asked is the half that was wrong for longer.** Only upstream's
`Output` was, so a challenge carrying none was never asked at all — most of
Construction's furniture, and the wiki has filed `Demon throne` under `Demonic
throne` the whole time. The **marked span is a title** too, which is what
upstream writes `~|...|~` for, so it is asked about as well; the verb-stripped
key stays out because it is a *sentence* (`a broken strut in the Motherlode
Mine`) and two thousand of those have the same answer. That is what took the
question from 236 names to 701 and the answers from twenty to thirty-seven.
This is also why
`chunksim recipes` is the one fetch subcommand that reads an export: the
question is whether two vocabularies still agree, and neither half alone can be
asked it.

**Not every gap the alias fetch leaves is a rename, and two of the leftovers
had their own small mechanism.** A trailing digit in the marked span is
sometimes the *task's* count rather than the recipe's: `~|rune case 1|~`,
`~|rune case 2|~` and `~|rune case 3|~` are three tasks for one wiki page with
no numbered variants at all, told apart by which runes each stocks. Offering
the digit-stripped page as one more join key lets `material_candidates` do
what it already does for every other unlabelled variant — measured across the
whole export, three tasks carry a trailing digit whose bare form is a recipe
output, and all three are this page. And a plain name can collide with a
different thing entirely: the wiki disambiguates `thistle (Construction)` from
Farming's own `Thistle` the same way it disambiguates `with superheat item`,
so `join_keys` tries the marked span with `(Construction)` appended last, and
it does so wherever a skill is threaded through it, which two of `join_keys`'
three callers had never done before now.

**The last few misses are not a redirect and not a naming pattern — they are
the wiki using a different word, with nothing to catch it.** `Wooden dining
table` is the wiki's furniture name, not its title (`Wood dining table`); the
mounted fish and head trophies are `Teak/Mahogany display (fishing trophy)`
and `Teak display (head trophy)`; and the top two pool tiers keep upstream's
family word `revitalisation` where the wiki's own progression moves on to
`rejuvenation` after the second tier
(`Restoration → Revitalisation → Rejuvenation → Fancy → Ornate`). None of these
is a MediaWiki redirect — there is no page under upstream's name for one to
point *from* — so `recipe_rates.HAND_ALIASES` is a small hand-verified table
for exactly this failure mode, the same shape `remote/skill_tables.
SHORTCUT_ALIASES` is for shortcuts. It cannot live in `wiki_aliases.json`:
that file is `chunksim recipes`' own fetch, rewritten wholesale on every run,
so a hand entry there would survive only until the next refresh silently
undid it. `costing/inputs.load_aliases` merges the two, the fetch winning any
collision. Between the three mechanisms, Construction's `Build` methods that
join a recipe at all went from 76 unpriced to 23 — a floor of quest and drop
gates the wiki itself cannot resolve, plus four minigame actions whose own
page states no cycle and three boat cosmetics that are not repeatable
training at all.

**A boss played the slow way pays a skill the fast way never touches.**
World-hopped Wintertodt earns its 500 points and leaves, so no part of its
hour is spent on a brazier going out — which is why `Repair braziers at
~|Wintertodt|~` sat unpriced beside a fully modelled Firemaking/Woodcutting
loop. `Wintertodt/Strategies` publishes the solo regime as a table, and every
column of it is linear in the *Firemaking* level: one constant per skill,
fitted against six published rows and rounded as the wiki rounds them,
reproduces 17 of 18 cells exactly (`costing/wintertodt.solo_rate_at`). Only
the Construction column is spent — the other two are the evidence that the
law is proportionality, and carrying them would change nothing, since the
running maximum in `training_bands` keeps the fast loop's Firemaking above
solo's everywhere. The gate is upstream's own `Access the ~|Wintertodt|~`
rather than a level compared here, floored rather than refused below it: the
export census `chunksim training` runs infers no Firemaking level at all, and
comparing `1 < 50` there reported a genuinely priced method as unpriced.

**A recipe's material and the export's item graph can name the same thing
differently, and the item walk has no reason to expect they agree.**
`Build an ~|ancient altar|~` refused to price despite every input the export
names being reachable, because `world.item_sources` is built entirely from
the export's own `Output` strings (`derive/search.build_world_index`) while a
recipe's materials are the wiki's words. The wiki's `{{Recipe}}` for
`Ancient altar` lists `Pharaoh's sceptre (uncharged)` - correctly, Pyramid
Plunder really does hand the sceptre over with no charges - and the only
challenge that produces one anywhere in the export states its `Output` as
the bare `Pharaoh's sceptre`, so the walk never seeds the wiki's exact
string. `recipe_rates.MATERIAL_ALIASES` is a fallback `estimate.
material_seconds` tries only once the literal name has already failed -
**the reverse direction from `HAND_ALIASES`**, which takes an export name to
a wiki title so a challenge can find its recipe, where this takes a
recipe's own material to the export name so the item walk can find a route.
The two are not interchangeable: they run against different vocabularies in
opposite directions, and conflating them would search the wrong dictionary.

**Two more turned up by asking a sharper question, and both are hand-verified
too.** Where a recipe's material has no route, does the *challenge's own*
`Items` name a longer form of it? Measured across the export that is true
exactly twice - `Black mask` against upstream's `Black mask (10)`, and
`Araxyte venom sac` against its `Araxyte venom sack` - so this is a second
hand entry rather than a rule, and each is decided by upstream itself rather
than by resemblance. The black mask is a charge suffix the export models and
the wiki recipe does not; the venom sac is the same vocabulary lag
`wiki_aliases.json` handles for outputs, on the material axis where that
fetch cannot look (renamed `sack` -> `sac` on 30 June 2026, the wiki followed
and the export has not). Between them `Build an ~|undead combat dummy|~`, its
ornate twin and Herblore's extended anti-venom+ all price, leaving Construction
with **three** unpriced methods, all minigames.

**The search that found it turned up twenty more, deliberately left alone.**
Stripping a trailing parenthetical off the recipe corpus's 524 unrouted
material names and retrying against `item_sources` resolves 21, and the
shapes behind the parenthesis are not one thing: Trahaearn degradation
tiers (`Corrupted helm (attuned)`/`(basic)`), a cooking state (`Spider on
shaft (raw)`), the same unfinished/finished split the alias fetch already
handles for bars (`Mith grapple (unf)`), and a dose the corpus's own
`_dose_variants` fallback was built for and cannot reach here because this
runs after the wiki recipe is already chosen (`Super defence(4)`). A
strip-and-retry rule applied uniformly would price a degraded item as free
to obtain from a fresh one - the same mistake pricing a shop item at its
ground-spawn cousin's rate would be - so only the sceptre, checked by hand
against the wiki, is in the table. No climb moves on fray, verf or
fray-uber; `Build an ~|ancient altar|~` prices at 761/hr, below the floor
anything else on the climb already clears.

**A currency this project would not price was a currency nobody had asked
about.** Castle Wars armour joins a real recipe and refused on every input,
which read as the standard shape - an item the world does not provide - and
was not: `~|Castle Wars Ticket Exchange|~` is valid on the ceiling, upstream's
own `Source: "shop"` flag says so, and the wiki states the price of every
piece. What blocked it was two gaps at once. The wiki's page is a hand-written
stock table rather than a `{{Shop}}` infobox, the one shape `remote/stores.py`'s
Bucket query reads, so no re-scrape has ever reached it or ever will -
`heuristics.DEFAULT_SHOP_PRICES` is nine rows read off the page by hand,
merged under the scrape the same way `DEFAULT_CURRENCY_PER_HOUR` is. And the
shop's own `Output` names a loot table (`Castle Wars tickets loot`) exactly
the way a monster's drop table does, which routed it through `estimate.
_route_hours`'s `task:` branch - pricing a deterministic purchase as a random
roll, the wrong mechanic entirely. `derive/search.build_world_index` now
seeds a `shop` route alongside the `task:` one wherever upstream's own
`Source: "shop"` says so - 46 challenges carry the flag, and the change is
inert for the other 45 until someone supplies their prices too, since a shop
with no entry in `DEFAULT_SHOP_PRICES` prices exactly as it did before.

**The rate itself is the user's own method, and the wiki checks the timing
rather than supplying it.** The go-to approach is organising scored draws,
which pay both teams at once rather than fighting for a win: 2 tickets a side
on a non-dedicated world, which the wiki confirms (3 on a dedicated one, not
modelled - a scored draw needs cooperation either way, and the smaller figure
is what a solo player can rely on organising). A game is a stated 20 minutes
and the wiki states a non-dedicated wait of 2, so 22 minutes for 2 tickets is
`60/11` an hour. Construction goes 553 modelled to 556; the three armour
tasks read 40.8/4.5/0.5 hr against 18/180/1,800 tickets respectively, all
under the floor anything else on the climb clears, so no climb moves on any
of the three maps.

**A quest reward can be a recurring material and still cost nothing to
reuse.** Three sword mounts - `darklight`/`silverlight`/`excalibur (mounted)`
- each want the one-time quest weapon as a recipe material, and pricing it
through the item walk charged the whole cost of the quest on every cycle of
a build-and-destroy loop that only ever needs one sword. The wiki states the
mechanic identically on all three pages: "when the mounted sword object is
destroyed, the sword is returned." **Checked and rejected as a general
`(mounted)` rule** - the fish and head trophies beside them say the opposite
on their own pages, "cannot be removed to retrieve the stuffed fish/head" -
so `recipe_rates.RETURNED_MATERIALS` is three hand-verified `(output,
material)` pairs, not a name-keyed heuristic. Safe because a rate is only
ever asked for a challenge the derivation already calls valid, which for
these three means the quest is already done - zeroing the sword's cost does
not claim it was free to obtain, only that this loop never obtains it twice.

The wiki's `{{Recipe}}` template marks `mat2cost = 0` on all three pages,
which looks like the same fact and is not: that field is exposed nowhere in
the Bucket `production_json` this project actually reads (verified against
the live table - only `output.cost` survives), and even where present it
means "the wiki's cost calculator has no coin price," which is equally true
of the fish trophies' materials and implies nothing about return. Construction
goes 556 modelled to 559; the three swords read 19,809-21,398 xp/hr, real
enough to be interesting and still under `wooden fence`'s 55,436, so no
climb moves.

**"Answered elsewhere" is only true if the answer lands on the same row.**
`costing/spells.py` refused every `Combat` cast on the stated grounds that
`costing/combat_xp.py` "already prices it". That is true of the *skill* and
false of the *challenges*: `combat_xp` keys its rates on
`monster_stats/<monster>`, so all 56 combat `Cast ...` methods read `unpriced`
while Magic itself was well covered - a model answering a different question
than the one the report asks. The other half of the old reason does not hold
either: it claimed the infobox's `speed` carries an `(N on autocast)` aside
making the manual figure the wrong cadence, and **22 combat spells were
checked and every one is a flat `5 ticks`** with no such aside.

So a combat cast is priced at the **base experience it pays whether or not it
lands** - splashing, which is a real method and needs only the three published
terms a utility cast needs. **Damage experience is deliberately not counted**:
it depends on the target, the gear and the gates, which is exactly what
`combat_xp.py` models, so this is a floor - correct for splashing, conservative
for fighting - and it can never compete with the combat answer because
`training_bands` takes the maximum. Magic goes **92 modelled to 132** and no
climb moves on any map: fire bolt reads 11,507/hr against the Arceuus library's
163,350.

**And a refused cast now says which reagent it wanted**, on the same terms the
recipe layer does: `spells.unroutable` walks the challenge's own `Items` only
once `rate_for` has already returned `None`, and its answers land in the same
`Heuristics.unroutable` map, so `Cast ~|iban blast|~` reads "needs Iban's
staff" and the nine resurrections "needs Book of the dead".

**A blighted spell sack replaces the runes and nothing else**, so a sack
variant borrows its base cast's experience, speed and kind and differs only in
what it eats. No `infobox_spell` covers one - the sack is an *item* rather
than a spell - which is why upstream's 18 of them were the only `Cast ...`
methods with no entry at all rather than a partial one. `spells.with_sacks`
derives them from the cast each names, and the difference costs nothing:
`rate_for` charges the *challenge's* `Items`, which is the sack, so runes are
never billed for a cast that does not use them. They price as far worse than
their rune twins, which is right - `Cast ~|entangle|~ from a spell sack` is
2,145/hr against the plain cast's 41,681, because a sack is a rare drop and
runes are not.

**A quest prize is held, not eaten, and the export says which items those
are.** `Cast ~|iban blast|~` wanted an `Iban's staff` and the nine
resurrections a `Book of the dead`, and both refused outright rather than
reading slow - because `derive/search.build_world_index` reads a challenge's
`Output` and not its `Reward`, so 138 of the export's 206 quest prizes have no
route at all. That is not the gap it looks like: **the quest is already done,
or the challenge would not be valid**, and every layer here prices only what
the derivation calls valid. Charging one per cast bills the whole quest every
three seconds.

**The exemption is a conjunction and neither half would do alone.** Upstream's
`*` marks what an action consumes and is not reliable by itself - `Cast
~|bones to bananas|~` lists `Big bones[+]` unmarked and plainly eats it - and
"is a quest reward" says nothing about consumption on its own. Together they
are safe, and measured: six quest-reward items are named by a primary training
method and **every one is unmarked** (`Book of the dead`, `Iban's staff`,
`Bosun's workbench schematic`, and the three quest swords a mount displays), so
nothing in the export is undercharged by this. Magic goes 136 modelled to 146.

**A price the scrape reads and a quantity it cannot see.** The blighted surge
sack refused on the same shape twice over. Its `{{StoreLine}}` is `sell=10`
with `displayname=Blighted surge sack (x50)` - ten points for **fifty** - and
`displayname` is exposed nowhere in the `storeline` bucket, so the scrape
prices one sack at fifty times the truth. `heuristics.SHOP_BUNDLES` divides it
out rather than replacing the price, so a re-scrape keeps working. And the
currency had no rate at all: Emir's Arena pays **12 Reward Points for
*losing***, which a queue-and-forfeit cycle collects in about two minutes, so
360 an hour and a sack costs 2 seconds. The win figure is not modelled -
winning a PvP fight is not something this project can promise anybody.

**The result inverts a ranking, which is the interesting part.** A surge cast
from a sack is 29,749/hr against 3,451 with the runes, because a wrath rune is
expensive and two seconds of forfeiting is not. Magic goes 146 modelled to 154.

**"You cannot cast it again" was the last of the three refusals, and the wiki
publishes the rate for doing exactly that.** `spells.py` priced no teleport at
all, on the reasoning that a cast moves you somewhere you have to travel back
from and no page states the journey. You cast it again from where you land:
`Pay-to-play Magic training` says "Repeatedly casting Camelot Teleport offers
around 80,000 experience per hour, with 55.5 experience per cast". What the old
reasoning got *right* is that the animation alone overstates - 3 ticks is
111,000/hr against that observed 80,000 - and the difference turns out to be a
fixed **0.698 seconds** of clicking rather than an unknowable trip.

**One figure, one parameter, so reproducing it is an identity** - the thing
`costing/gathering_overhead.py` warns to read as arithmetic rather than
agreement. What it buys is the *shape*: the overhead is the interface and not
the destination, so it carries to every teleport and to the 4-tick speeds the
Camelot figure never saw. A lectern is still the other answer and a better one
where it applies, since making tablets pays the same experience and spends no
runes - and `Summon boat (tablet)` turned out to be missing from that
whitelist, listed on `Lectern space` beside the two boat tablets that were
there. Magic goes 154 modelled to 158.

**A cooldown is a cast speed, and reading only one of the two fields was
wrong in both directions.** `infobox_spell` states a cadence two ways: `speed`
blocks before the spell lands, `cooldown` is an instant cast followed by a
wait before the next - and for experience an hour they are the same cycle.
`remote/combat.parse_cadence` takes the **larger** where a page states both,
and that is not merely a gap-filler:

- It **fills** eleven of the seventeen spells whose `speed` is blank - the
  Arceuus offerings, corruptions, wards, charges, `dark lure`, `vile vigour`
  and `shadow veil`.
- It **corrects** twelve more that were already priced and priced too fast.
  The nine resurrections read `speed = 4` and `cooldown = 16`, so they were
  **four times** too quick - `Cast ~|resurrect lesser ghost|~` goes 32,228/hr
  to 14,838. `Mark of Darkness` and both vengeances state `speed = 0`, which
  `castable` had been dropping as instant; they are 10 and 50.

Magic goes 158 modelled to 169 and unpriced 17 to **6**, and the six split two
ways rather than being one gap. **Five are supply-bound**: the four Arceuus
reanimations wait on ensouled heads dropped by monsters and `Resurrect Crops`
on a patch having died, so the cast is instant beside the wait and a figure
computed from it would describe the spell where the answer is the drop table's
or the growth clock's. They join `costing/oneoff.py`, which now carries two
shapes - a decoration placed once, and a loop whose cadence is not the
action's - with the `reason` beside each saying which. **The sixth is an
ordinary cast the infobox forgot**: `Monster Examine` is neither instant nor
on a cooldown, so `spells.STATED_TICKS` states its five ticks the way
`recipe_rates.stated_ticks` states an untimed recipe's, filling only where
the wiki is blank and never overwriting.

**Magic now has no unpriced method at all** - 170 modelled, 5 one-off, 90
uncompletable of 265.

**A number in a table is only the number the column header says it is.**
Tempoross' reward table gives "Repairing totems/masts" as **40**, and it is
40 *points* - the column is headed `Points` and dousing a fire pays the same
40 for no experience at all. The experience is on the object's own page,
stated twice: "Construction experience equal to 4 times the player's level",
and `{{Skill info}}`'s `skill1exp = 4 x Construction Level`. So repairs are
`4 x level`, not a flat 40, and the difference is 25x at the top of the climb.

**What is left over is one honest guess, named as one.** A tether site breaks
"between 15% and 25%" per wave, "rolled independently for each tether site" -
but nothing states **how many waves a game contains**, because the wave is one
of several attacks Tempoross chooses between, it only attacks above 10%
energy, and the fight runs a variable number of phase cycles. So
`tempoross.REPAIRS_PER_GAME` is 1, deliberately the low end, and it is the
only invented factor in a module that otherwise transcribes: `4 x level` a
repair and five games an hour are both published, so the rate is `20 x level`
and the bands are `GUESS` because one invented factor makes the product
invented.

**Where an activity caps what you can earn, the mechanic is a budget and the
model is division.** The Fishing Trawler tabulates what each action on the
boat pays in contribution points *and* in experience, then caps a game at 255
points - so what a skill takes out is decided by its action's
points-per-experience rather than by how fast anyone clicks. Filling a leak is
one point per experience and fixing a rail is the same 5 experience for twice
the points, so a Construction player ignores the rails: 51 leaks, 255
experience, and at a published 6.5-minute round that is 9.23 games an hour and
2,354/hr before the 51 swamp paste it eats. **Labelled a ceiling**, for
`costing/troublebrewing.py`'s reason - every term is published, and the two
assumptions on top (every point from leaks, and leaks spawning fast enough to
absorb them) are not checkable from anything the wiki states.
**Crafting's net repair is in the same table and is refused**: its success
chance depends on Crafting level and the page's only success chart is for the
fish, which is `costing/pickpocket.py`'s call for its seven uncharted NPCs.

**Two published tables that close on each other are worth more than either.**
Vale Totems states its per-totem experience by log tier and its Construction
experience by level, and neither states a rate this project could use
directly. They close: a totem is `4 x (build/carve + decorate)` - "the
building action, three carvings, and four decorations" - on all six tiers to
the tenth of a point, and the Construction table is `104 x level` on all nine
rows, which is where the 104 totems an hour comes from and which the page
independently calls "13 loops (104 totems) per hour". Multiplying the first by
that constant reproduces the published Fletching-per-hour column on five of
six rows and shows the sixth to be a **wiki typo** - redwood is 393,868.8
where the page says 393,686.8, a digit transposition the other five agreeing
makes readable as one.

**And the correction is the whole point of charging materials.** Every
published figure here assumes the logs were bought - the calculator's own
assumptions say so - where a chunk map must chop them. Five logs a totem at
104 totems an hour is 520 an hour, so redwood needs **2.6 hours of chopping
per hour of totems** and the map is log-limited to 28.6 totems an hour. That
took `fray-uber`'s Fletching climb from 85.0h to 231.3h, superseding a
`{{Recipe}}`-derived rate whose 2 ticks are the *build action* against the
whole totem's experience. The decoration's own fletching experience is
deliberately not credited here: it is already a separate priced method, and
folding it in would double-count.

**A weight tier is a yield, not a drop, and the difference is worth one
module.** Mining granite hands over one of `Granite (500g)`/`(2kg)`/`(5kg)` at
20.7/22.15/25.39% - one action, three weights of the thing you just mined - so
a 5kg block is one mine in four, where `Raw bass loot` pairs an `Always` raw
bass with a 1/1000 `Big bass` beside it. `estimate._route_hours`' certainty
gate could not tell them apart and refused both, which is what left `Build a
~|volcanic theme|~` unpriced for want of granite the map plainly mines.
**The boundary is a gap in the data**: of the 25 unpriceable non-`Always`
members of a gathering-modelled table, nothing at all sits between 8.33% and
19.92%, so anywhere from 9% to 19% selects the same eight items - granite's
three weights, sandstone's four, and the Cam Torum calcified deposit.

**It is a flat cost rather than an opened route, and that is the whole
finding.** Opening the gate was tried twice and reverted twice; the second
attempt is the instructive one, because gated to exactly those eight items it
*still* failed to price `fray-uber` in three minutes. The count was never the
problem - `_route_hours` prices an uncertain member by dividing the quantity by
the share, and a fractional quantity is a fixpoint key nothing else ever
matches, so the memo stops hitting and Prayer's bone walk alone reached 2.5M
`_item_hours` calls. A yield needs no route: the action's own pace is already
in `Heuristics.action_seconds`, so the cost of one block is that over the
share - one number the walk reads and stops, beside `costing/herbs.py`'s. It is
checked **last**, after `_recipe_hours`, because `costing/yields.py` prices 75
items and most of them (`Coal`, `Logs`, `Bones`) have real routes that must
win; what is left is exactly what the gate refused.

**A rare drop off an already-modelled gathering action was worth trying and
not worth keeping.** Four more Construction methods and a Smithing one
shared a shape: their material is a rare table member of an activity
`costing/gathering.py` already computes a real per-level pace for -
`Big bass` at 1/1000 off ordinary bass fishing, `Granite (5kg)` at 25.39%
off the granite rock - and `estimate._route_hours`'s certainty gate refuses
any non-`Always` table member outright, regardless of whether the pace
behind it is trustworthy. Measured first: 296 rare members of a
gathering-modelled table across the whole export, 21 unpriceable, 7
consumed as a material anywhere. Letting the share through when `Rate.match
== GATHERING_MATCH` reopened the exact door the certainty gate's own
comment was written to close - it names Prayer/hydra-bones as the original
regression - and Prayer's bone-burying material walk pushed `_item_hours`
past two million calls on `fray-uber`, a real cached map, without finishing
in a minute: 296 near-unique `quantity / share` values barely dedup through
the fixpoint memo, and Prayer's walk touches enough of them to matter.
Reverted; the finding is recorded beside the check in `estimate.py` rather
than left to be rediscovered, since seven methods near no climb's floor
were not worth a regression that size on a map anyone might run.

**And the smallest of the untimed-recipe fixes: a tick cost every sibling
states and one page leaves blank.** `Yew tree (Construction)`'s `{{Recipe}}`
carries no `ticks` at all, where `Oak`/`Willow`/`Maple`/`Magic`/`Spirit tree
(Construction)` on the same POH page are all `ticks = 5` and the mechanic is
identical across the family - plant a bagged tree, same object, same action.
`costing/yewtree.py` names the one output rather than a rule over the
family, for the reason `chisel.py` does: 650 of the corpus's 4,043 recipes
carry no stated ticks, far too broad a net to trust by resemblance alone.
Construction goes 559 modelled to 560; the tree reads 3,418 xp/hr and no
climb moves.

**And a shop the export never states exists at all, not merely one the
scrape's shape defeats.** `Build an ~|otherworldy theme|~`'s last blocker
was `Magic secateurs`, and upstream's own item graph names only the
Fairytale I quest as its source - correctly, since the quest gates the
task and the wiki confirms it: "after defeating Tanglefoot, additional
pairs may be purchased from Malignius Mortifer for 40,000 coins each."
That NPC is not a `shopItems` entry, not a `Source: "shop"` challenge,
nothing the export states at all - so `derive/search.HAND_SHOP_SOURCES` is
one hand-seeded route, the one exception to `build_world_index` reading
only the raw export, paired with `heuristics.DEFAULT_SHOP_PRICES`'s 40,000
coins. Construction goes 560 modelled to 561; the theme reads 2,570 xp/hr
and no climb moves.

**One action can pay two skills at different rates, and the table that charges
its materials cannot say so.** A Port Piscarilius fishing crane pays `4 x
Crafting level` *and* `4 x Construction level` for one success, rolled on a
`{{Skilling success chart}}` read at **whichever of the two is higher** - so on
a Construction climb below the player's Crafting level the payout moves and the
chance does not. Every other term is published too (10 ticks an attempt, nine
nails and three planks a success, one more nail bent per failure), and the
curve check is a real one: the chart's `low1=41`/`high1=76` reproduce the
page's own prose, "approximately 20% at level 30 to 30% at level 99", through
the same `gathering.success_chance` every other chart in the project uses.

**The materials are folded into the rate rather than declared**, which is the
part worth copying. `Heuristics.material_seconds_per_xp` is keyed by *task*,
and upstream files one task name under both skills - so a single entry would
have to serve two different experience-per-repair figures and be wrong for
whichever skill it was not computed against. `costing/crane.py` charges the
nails and planks inside each skill's own rate instead, and they are most of the
answer: 71,466/hr becomes 39,546 at level 99. The loop is world-hopped for the
reason `costing/wintertodt.py` is - a repaired crane takes 30-60 seconds to
break again, and hopping to one already broken is what makes the tick count the
binding constraint. No climb moves on any map: 39,546 loses to `wooden fence`'s
55,436 and to Crafting's `ruby` at 89,184.

**An `unpriced` row can say which ingredient it wanted, and 47 of 418 do.**
`blocker`/`blocked_by` were only ever filled for a method the *world* cannot
reach; a reachable one that joined a recipe and lost an input is the other half
of "why is there no number here". `rate_for` returns a bare `None` because it
is the hot path and needs a yes-or-no, so `recipe_rates.unroutable` walks the
same materials again **only once that has already failed**, over the memoised
closure `estimate.material_seconds` builds - a lookup rather than a second
walk. It rides to the report on `Heuristics.unroutable` rather than on
`RecipeCoverage`, because `Heuristics` is what `cached_enrich` stores and what
`coverage.statuses_for` is already handed. **Blank stays blank**: no recipe
joined at all, or one joined and was refused for want of a stated duration, and
neither is an ingredient to name. `coverage.INPUT` is deliberately *not* in
`BLOCKERS` - that tuple is the breakdown of what the world lacks, printed for
`uncompletable` rows only.

**A decoration is not a slow method, and the difference is a claim about the
challenge rather than about the model.** Seven challenges upstream flags
`Primary` are things nobody trains with: four trophy mounts and three boat
cosmetics. The mounts are the interesting case, because the obvious reason is
wrong - `Mounted bass` says outright that "duplicate big fish can be added for
additional experience", so it *is* repeatable. What disqualifies it is that
the repeat consumes a fresh big fish, a 1/1000 to 1/3000 roll off ordinary
fishing, which prices the loop at **3.0 to 3.5 xp/hr**; and that the *display*
is the real Construction action, already priced (`Oak display`, 120 xp for two
oak planks, and its teak and mahogany tiers). The rate alone would not settle
it - Construction lists `steel dragon (Construction)` at 3/hr and this project
deliberately removed the floor that used to hide such methods.
`costing/oneoff.py` names the seven and `coverage.STATUSES` gains `one-off`,
placed beside `unreachable` rather than near `unpriced` for the same reason:
it says the question does not apply, not that the answer is missing. A status
rather than a filter, so the per-skill totals still add to 602 and a reader
looking for `Build a ~|mounted bass|~` still finds it.

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

**An action that pays several skills should be read once and spent several
times.** Barbarian fishing was already modelled - `gathering.py` rolls its
cascade, sturgeon then salmon then trout, each on the last one failing - but
only for Fishing, while the export carries all three challenges again under
**Strength** and **Agility** at their own lower requirements. `costing/
barbarian.py` adds nothing to the model: it walks the same cascade with the
same curves and the same five-tick roll and sums a different experience
column, so the Fishing figure it reproduces is identical to the node walk's
and the ancillary one cannot drift from it. The check is a *ratio* rather than
a level - the wiki publishes Str/Agi beside Fishing and the two run 0.090 to
0.092 across the climb, where this computes **0.089 at every level** - which is
the right shape of check when the absolute figures are known to differ
(38,224 against the guide's 48,000 at level 70, inherited deliberately).
**The level axis is Fishing's, not the skill being trained**: which fish you
catch decides the ancillary pay and that depends on Fishing, so the rate is
flat in Strength.

Wiring it up found a real defect it had been hiding. `inputs.priced_heuristics`
folded combat's computed methods in with a dict comprehension keyed by skill,
which **replaced** the whole tuple - so anything non-combat filed under a
*combat* skill was destroyed, and all 21 of barbarian fishing's Strength bands
were computed and thrown away before a reader could see them. The comment
above it already said "Merged, not replaced". It does now.

**One action is not one item, and assuming it was cost Herblore its whole
model.** The item walk charged a challenge's `Items` once per unit of its
`Output`, so a grimy ranarr weed cost a whole ranarr seed - 163 seconds of
killing for the drop - and priced at 168.9s. A herb patch returns **8.8 herbs
for the one seed planted** (the wiki's own empirical figure for a standard,
unprotected patch), so the true marginal cost is 19.2s. Every potion consuming
a herb therefore fell under the 1,000/hr floor and kept a `wiki:herblore`
figure that never paid for its herbs at all - which is exactly the
"guides do not include gathering costs and we do" asymmetry, showing up as the
guide *winning*. `Heuristics.harvest_yield` carries the figure and
`estimate._route_hours` spends it; `costing/farming.harvest_yields` fills it,
joined on upstream's own `Category`/`Objects` so the Chambers of Xeric herbs -
found rather than farmed - are correctly left out.

**Where the division goes is the whole of it.** Dividing the *quantity* going
in does not work: `_kill_hours` floors a drop at `1/chance` kills - you cannot
see a ranarr seed in fewer, however little of one you want - so the seed stayed
at 163s and only the tools scaled. The action costs what it costs and hands
back `yielded` of the output, so the division belongs on the total. Herblore's
recipe-priced methods went 26 to 34 and its guide-backed ones 45 to 37.

**The 1,000/hr floor marks "nothing priced this" and no longer refuses
anything.** It used to double as a guard in `recipe_rates.apply`: a computed
rate below it was skipped, on the argument that a sub-floor number says the
model is missing something far more often than it says the method is glacial.
That had a real case - Supercompost at 173 xp/hr, the one Farming method the
recipes reached, pricing Farming 1 -> 99 at **75,353 hours**.

**What retired it is that the surrounding models caught up.** `training_bands`
takes a running *maximum*, so a slow method decides a climb only where it is
the only one - and Tithe Farm now covers Farming from 34, bounding Supercompost
to the stretch below it: 236.4h rather than 75,353h. Meanwhile the guard was
costing the distinction it existed to protect, filing a method that is
genuinely slow *as* one nothing has priced. Those are different answers and
`Rate.match` exists to tell them apart. Measured over both cached maps,
removing it **priced 218 more methods** (1,579 -> 1,797), moved 37 off a guide,
and changed exactly one climb by 5.5h. A sub-floor rate is now a rate; what
remains at the floor is only what nothing reached.

**A minigame you cannot steer is one method, and pricing it per output invents
a choice.** Guardians of the Rift opens exactly two portals at a time, one
elemental and one catalytic, so which rune an essence becomes is the game's
decision. The export carries twelve `with guardian essence` challenges and they
were being priced **five different ways**: `air` from a money-making guide about
the *ordinary altar* (56,760/hr), `chaos` from one about *the Abyss*, five from
the recipe layer as a single one-tick imbue, and only the top four from
`wiki:gotr` - because `_add_banded`'s first published band is level 40 and
everything below it fell through to whatever else had joined on the rune's
`Output`. `costing/gotr.py` replaces all of it with one curve: **the mix is
modelled and the throughput is calibrated**, the published bands divided by the
mix to recover essence an hour (3,704 at 40 rising to 9,532 at 99, which is the
colossal pouch at 85 appearing where it should). Runecraft on the uber map goes
**271.4h to 234.2h** and the climb reads as one activity from 30 to 99.

Two things it had to get right and one bug it exposed. **Bands carry the
minigame's level, not the rune's** - the export gives `Craft an ~|air rune|~
with guardian essence` a `Level` of 1, and a rate written against that offers
the minigame to a player who cannot enter it. And **an activity that gathers
what it consumes must carry no material cost at all**: the scraped path dodged
that through `training._ALL_INCLUSIVE_SOURCES`, which a `ComputedMethod` has no
source to be matched by, so the essence was charged twice and the climb read
474.9h until the entry was removed from `material_seconds_per_xp` outright.

**Gathering that pays the *same* skill must be credited, not only charged.**
`TrainingOption.effective_xp_per_hour` has always added the time to obtain
what a method consumes - that is what stops a guide's "with the materials to
hand" figure winning a chunk map. It was discarding the other half: sorting a
salvage pays 95 Sailing and costs 34 seconds of *salvaging*, which itself pays
200 Sailing, so the pair is 295 experience for 36 seconds rather than 95. The
formula composes as `3600 x (1 + material_xp_per_xp) / (processing +
gathering)`, and **the credit is only ever the same skill** - a log chopped for
a bow pays Woodcutting, which does nothing for a Fletching climb. Opulent
salvage sorting went 8,427/hr to 26,167.

**The generic version needed the item walk to say which route it took**, and
now it does. `_Priced.experience` accumulates `(skill, experience)` along the
route the walk *chose*, so a bar smelted is credited and a bar bought is not -
`_item_hours` takes the `min` over routes, and crediting the smelting to a
shop purchase would be fabrication. `material_seconds` returns a
`_MaterialWalk` carrying both questions over **one memo**, because "how long
does a bar take" and "what did getting it pay" are the same decision seen
twice. 233 methods are credited on the reference map; `Smith a ~|steel
platebody|~` gains 9% from the bars it smelts.

**The credit is per unit of output, and that is not a detail.** Superglass Make
pays 180 experience and returns **28.8** molten glass, so crediting the
action's experience paid nine times what a piece is worth and handed
glassblowing the entire Crafting climb - 146.3h against 101.9h off one bad
number. The walk charges a challenge once per item, so the credit is per item
too, and where variants disagree the *smallest* is taken: this number makes a
method look faster and the walk cannot say which variant it used.

**Both halves or neither.** The worked case, pinned in
`tests/test_training.py`: a material taking a minute for 10,000 experience and
a minute of production paying 20,000 is 30,000 in two minutes - 900,000/hr.
Charging the minute without crediting the experience gives 600,000; crediting
without charging gives 1,800,000.

**Doses are fungible, and the item walk did not know it.** No action in the
game *makes* a two-dose potion - you brew a three or a four and drink one, or
decant - so `Attack potion(2)` had no route at all while `Attack potion(3)`
priced in a second, and every method consuming a partial dose was dropped.
`estimate._dose_hours` prices `N` doses at `N/M` of an `M`-dose potion, taking
the cheapest `M`. Herblore's recipe-priced methods went **66 to 77** and its
published-rate ones **26 to 16**.

(A dose hop used to need a special exemption from the walk's depth budget;
the budget is gone - see the fixpoint paragraph below - so a dose is now just
another route.)

**Herblore's climb got slower and that is the correction working.** The uber
map went 29.2h to 61.0h because the recipe layer now *reaches* the low levels
and charges for the herbs, where the `wiki:herblore` figures it displaced
assume the materials to hand. The four bands still on that scrape read
356,000-522,500/hr against recipe-priced neighbours at 5,000-18,000, which is
the size of the gap that assumption hides.

**A herb is a supply, not a route, and both routes the walk had were wrong on
their own.** Farming priced at the clicking - 60 seconds a patch over 8.8
herbs - says nothing about the **eighty minutes** a herb takes to grow, and
implies you can do it back to back. A drop priced per herb asks "how long for
a ranarr" of a table that hands out thirteen herbs without being asked which.
`costing/herbs.py` models the cycle instead: a run is 2 minutes plus 1 a
patch, and the rest of the eighty is spent on the best **pooled** herb source
the map can kill. On the every-rollable-chunk map that is 9 patches, an
11-minute run for 79.2 herbs, and 336 herbs an hour at **10.7 seconds** each;
on the reference map 2 patches and 28.1 seconds. Checked before the routes in
`_item_hours` for the reason currency is, so nothing cheap-looking undercuts
it.

**Pooling the drops is the point of them, and it has a stated cost**: a herb
costs the same whichever it is. That is right for a *climb*, where you brew
whatever your herbs allow, and wrong for a single goal needing one ranarr -
the estimate's Herblore hours are the first question, so that is the one it
answers. **A patch location may name a section** (`11321-2`) or a whole chunk
(`13141`), and comparing the first against unlocked-chunk keys silently
matched nothing - it undercounted the uber map at 5 patches of 12.

**A method this project cannot cost is refused, not quoted.** `rate_for`
returns `None` when an input has no route - rightly, since tick-math over
inputs nothing can price is a made-up number - but it is also the only source
of `material_seconds_per_xp`, so the *scraped* rate then survived ranking as
though the ingredients were free, and the ingredients in question are exactly
the ones too hard to price. Its docstring recorded that bias rather than
fixing it, on the measured grounds that **not one such method won a band**.
That stopped being true: `Mix an ~|ancient mix|~` needs an `Ancient brew(2)`
the map cannot route, so `wiki:herblore`'s 522,500/hr stood unchallenged
against recipe-priced neighbours at 30,546 and took the **top four bands of
the skill**. `recipe_rates.refuse_dropped` now strips the scrape from a
dropped method; a hand pin survives, and so does a `modelled` rate, because a
model answering for a whole activity is not a claim about a recipe's inputs.

**Doses are a vocabulary difference as often as a real one**, so `join_keys`
offers them as a *fallback* - exact keys first. Upstream names a challenge's
output `Super combat potion(3)` where the only recipe makes a `(4)`, and
`Extreme potion(3)` where the wiki says `Extreme energy potion(3)`; the
verb-stripped key carries no dose at all, which is what kept the second from
ever joining. Both then join, both are dropped for inputs with no route, and
both are refused - which is how Herblore's climb came to end where it should.

**Herblore is a slow skill and now reads as one.** `Mix a ~|super restore|~`
at 30,546/hr wins from 63 to 99 and 1 -> 99 is **431.5h**, against the 46.4h
four materials-free guide figures were claiming.

**A method the export carries and no rate table would ever name.** The
Arceuus library pays a *multiple of the level you already have* - 15x for
Magic, 5x for Runecraft, one tome per book delivered - so nothing about it has
an hourly figure to publish, and `Turn in books at the ~|Arceuus Library|~ for
Runecraft xp` sat unpriced. It mattered most exactly where the map was
poorest: the second cache reaches no Guardians of the Rift and no lavas, so
its whole Runecraft climb above 77 was blood runes at 11,118/hr, against the
library's `5 x 77 x 110` = **42,350**. Runecraft there goes **1,225.7h to
290.4h** and Magic 137.9h to 95.6h. The one stated number is 110 books an
hour, measured, the middle of an observed 100-120.

**The lesson is about where to look, not about Runecraft.** A skill reading
absurdly slow on one map and fine on another is a *reachability* signal:
`verf` had 14 valid Runecraft methods against the uber map's 50, and the gap
was one activity nobody had modelled. Before assuming a rate is wrong, count
what the map can actually reach.

**The export lists what pays experience, not everything you can make**, and
the item walk routed only through it. Chiselling a dark essence block into
four fragments pays *Crafting*, so upstream carries no Runecraft challenge for
it - and `Dark essence fragments` had **no route at all** on a map holding the
Dark Altar, even though the mining half (`Mine a ~|dense essence block|~`) was
priced the whole time. `estimate._recipe_hours` falls back to the wiki's own
recipe when every other route has failed, honouring `output_quantity`, so
nothing that already prices can change.

**The soul rune chain is why a depth bound kept having to grow.** It is
fragments <- dark essence block <- dense essence block <- the mining challenge
<- its tools - five levels, when `_MAX_DEPTH` was 3 and its comment said three
was "past every real case measured". At five, blood runes on the second cache
went 11,118/hr to **31,316** and soul runes from refused to **38,880**. The
bound itself is gone now (the fixpoint paragraph below); the lesson stands:
every value it ever held was a work-around for the walk's cost, and each next
real chain arrived from outside the set of "measured cases".

**An untimed recipe has to fall back to something, but a counted one must not
reach the fallback.** `DEFAULT_ACTION_SECONDS` is right for an action nobody
has timed and wrong for one somebody has, so the stated durations are applied
to the recipe corpus *before* `_setup` flattens it - one corpus, which the item
walk and `recipe_rates.rate_for` now cannot disagree about. Two modules fill
it and both fill only where the wiki publishes nothing: `costing/herblore.py`
states the bank cycle a clean herb costs, and `costing/chisel.py` states
**zero** for a dark essence block, which is chiselled *while running* to the
altar on a trip the rune's own recipe already pays for. That zero is a claim
about this activity's geography rather than about chisels - a gem cut at a
bank is emphatically not free - which is why it names the one output instead
of reaching for a rule over verbs. It is also unspendable as a rate: the
export carries no challenge whose `Output` is `Dark essence fragments`, so
only the item walk can ever read it. Measured over both cached maps and the
uber one it moves exactly two methods (the figures above) and **no climb at
all**, the library still owning Runecraft wherever it is reachable.

**A join that misses reads as a gap; a join that hits the *wrong* action
reads as a fast method.** The export carries both `Cook a ~|marlin|~` - level
91, 225 experience - and `Cut up a ~|raw marlin|~`, which is level **1** and
pays **2**. `mmg:Money making guide/Cooking raw marlin` joined both, because
the guide's own activity normalises to the same words the cut-up's task does,
so a knife action carried **292,500/hr** and owned the entire Cooking climb
from 1 to 99 on the uber map. Nothing about that is visible in the output: it
is a plausible number on a real task from a real guide.

**Four things had to be true before the recipe could displace it**, and each
is a rule rather than a patch. The join runs on the **fish going in**, because
upstream names the output `Marlin loot` - a bundle the wiki has no page for -
and the wiki files the knife under the offcuts it makes (`costing/
fishcutting.py`; the offcuts output is the other half of the key, since the
fish alone also reaches the cooked and burnt recipes). An **`(alt)` twin is not
a second method**: 20 of them in the export, every one with a non-alt twin, and
every difference a flag or a second route into the same action. An
**`ActionRate`'s key carries what it is made from**, because the wiki labels a
variant only where the *method* differs and ten fish make `Fine fish offcuts`
with an empty label each. And the **family task takes what no species named**,
which is `variant_candidates`' rule on the input axis. Cooking now has **no
scraped rate at all** on either cached map or the uber one, and the uber climb
reads 63.8h against the reference map's 63.8h where it used to read 44.6h.

**The item walk is a fixpoint over a table now, and the depth budget is
gone with everything that managed it.** The old shape was a depth-first path
search: a visited set pruning cycles per path, `_MAX_DEPTH = 5` bounding work,
and two exemptions (`partial_products`, dose hops) letting real chains through
the bound. Its cost was measured before it was replaced - the same subproblem
re-priced once per *path context*, 284,260 recursive calls for 3,591 distinct
questions on the reference map - and without the bound it hung outright on the
every-rollable-chunk map, because simple paths are factorial. The fixpoint
settles each `(item, quantity, amortise)` question once per round; a route
that closes on a key still on the stack reads *last round's* answer instead of
exploring around itself, so **a cycle is a discarded path, never a discarded
item**, and convergence is guaranteed by positive costs - a derivation through
a cycle can never beat the acyclic one it contains. A round whose belief-reads
all held is exact, which is nearly every question; a stale read re-derives
only the keys whose evaluation transitively read it (`_Fixpoint.readsets`) -
clearing everything instead cost 4M evaluations for 137k questions.

**What the bound had been distorting, measured on removal**: no climb moved on
any of the three maps, and 29 reference-map rates *rose* - all runite and
adamant smithing, whose bars now price through deeper, cheaper chains (rune
platebody 1,283/hr -> 2,157). The uber map's lava eel went 9/hr to 2,898, the
jade crossbow-bolt enchant and infernal plate priced at all, and the wild pie
fell 20,765/hr to 3,816 because its part-pie ladder is charged in full rather
than waved through as a `Partial Products` exemption. Cold pricing: reference
map 5.8s -> 1.4s, the uber map 48s -> 12.5s end to end.

**Magic's missing model was one field, and it was not in the Bucket.**
`infobox_spell` has stated the runes a cast eats for a while - 190 of the
export's 214 `Cast` tasks join it - but nothing said how long a cast takes, so
57 of Magic's 175 primary challenges had a rate and `Cast ~|high level
alchemy|~` was not one of them. The infobox does state it, as `|speed = 5
ticks`, and the Bucket exposes only six fields with the duration not among
them; `chunksim heuristics` now sends the same page names back through
`fetch_wiki_pages` and reads the line. Four batched requests, 200 of 201 pages,
and `costing/spells.py` turns them into rates. **Only utility spells**, on the
infobox's own `type` (Combat 86, Utility 53, Teleport 51): a teleport's speed
is the animation rather than the method - priced on it a teleport reads
111,000/hr against the guides' implied 270 casts an hour - and a combat cast
belongs to `combat_xp.py`, which already prices it with the gear and the gates
in it. **And the materials are the export's rather than the infobox's**: the
runes are not the whole cost, since `Cast ~|bones to bananas|~` eats a big
bone and `Smelt a ~|steel bar|~ with superheat item` an iron ore and a coal.
Priced on runes alone bones to bananas reads 150,000/hr, which is a spell that
would have won the whole climb.

**And a teleport is answered by its tablet.** The four guides still on
teleports turned out to be describing lecterns - `mmg:Money making guide/
Creating Camelot teleport tablets` and its siblings - which is the resolution
rather than the problem: a travel cast moves you somewhere you cannot cast it
again, so the *only* repeatable form of a teleport is the one made at a
lectern, and the wiki carries a `{{Recipe}}` for every tablet with its ticks,
its runes and its soft clay. `costing/lectern.py` says which tasks have that
route, gated on the cheapest player-owned-house lectern that makes each
(`Lectern space`'s own table) - and on nothing at all for the Arceuus tablets,
whose **dark essence block is already its own gate** through the walk's
ordinary route refusal. Ancient and Lunar tablets consume soft clay like the
standard ones and the page does not list them, so they are refused: a
whitelist, so the wiki's silence cannot read as permission. Where no lectern
makes the tablet the teleport keeps **no rate at all** rather than a guide's,
because a method the map does not have is not a slow method
(`spells.refuse_untabled`; one task on each cached map).

Magic went **47 priced methods to 62** on the reference map, 56 to 76 on the
second and 67 to **102** on the uber one, with **no scraped rate left on any of
them**. No climb moves: combat casting owns Magic on all three.

**Where a published figure sits above what the mechanic allows, count the
mechanic.** Cooking's last three guide-backed methods each turned out to be
countable, and one of them contradicted its source. `Dissect a ~|sacred eel|~`
is a knife action with no time in it - an hour of it is an hour of *fishing* -
so `costing/sacredeel.py` reads the Fishing model's own roll a second time
(21.09% at level 87, the wiki's own figure) and multiplies by a pay that steps
with **Cooking** level, since that decides the scales. The bands are Cooking's
and the Fishing level is handed in, which is the opposite assignment to
`barbarian.py` and the same question from the other side. Tempoross' cooking
regime is the page's other table, counted out of the `max permits`
walkthrough: 55 fish a game, five games an hour, 10 experience a fish, 2,750 -
against the 2,500 a money-making guide was supplying, which is the reassurance
rather than the point.

**Trouble Brewing is the one that disagreed, and the disagreement is the
argument for modelling.** Its chain is one-to-one end to end - chop a scrapey
tree, fletch the log, deposit the bark for 100 Cooking - so
`costing/troublebrewing.py` prices the two mechanics the tree's page publishes
(a chop attempt every 4 ticks, a 1/8 depletion) and charges the untimed fletch
and deposit **nothing**, which makes the answer an arithmetic ceiling rather
than an estimate. Two games an hour at twenty minutes is 40 minutes of play, so
at most 1,000 logs and at most **100,000 experience an hour** - where
theoatrix's 1-99 Cooking guide states "around 200k". That needs two logs every
four ticks, so it is outside the mechanic rather than a near miss, and it is
not carried. The model reads 13,820/hr at Woodcutting 1 with an iron axe -
close to the 15,000 `stated.py` had been guessing for all eight of the
minigame's skills - and 88,889 at 99 with a crystal one. **A community figure
is still evidence**; what changed is that it can now be checked against the
actions underneath it.

**Not every "computed" number is evidence, and the docstrings say which.**
Thieving's fifteen tabulated stalls come out at exactly 1.00x against the
scrape, and that is an identity rather than agreement — the wiki's column is
`3600 / respawn * xp` and so is the model. Mining's one fitted row is the same
standing for the opposite reason: one parameter against one observation. Read a
1.00x in `costing/gathering_overhead.py`'s output as a claim about arithmetic
until the docstring says otherwise; the numbers that carry information are the
ones with several rows and a residual, like Woodcutting's 12/17 and Hunter's
6/10.

**"Nothing else published can check it" is a claim with a shelf life.** That
sentence was in `gathering.PROFILES["Thieving"]` about its 15.5-tick chest
interval, fitted to the Rogues' Castle guide's 270,154/hr - and `Chest (Aldarin
Villas)` states "approximately 400 chests can be successfully opened per hour"
at level 60, which the interval misses by **2.9x**. Two observations, one
parameter, and they disagree.

They disagree because they are not the same quantity. Every Rogues' Castle
attempt succeeds - you "search for traps" and the chest opens - so the cost per
chest is the **walk** to the next of the three sitting together in a room. A
chest you *fail* at stays shut in front of you and is retried where you stand,
so its cost is an **attempt**. One number for both prices a retry as a walk. The
fallible chests therefore name their own interval in `fixed_interval` and the
walk-shaped figure is left to the case it was measured on.

**And the calibration reads the sentence beside the figure.** `Thieving
training` says of the same method "bring a lockpick and some stamina or super
energy potions", so the 400/hr is against the *lockpick* curve - 883 attempts an
hour, 4.08 seconds each. The chance spent afterwards is still the plain one,
because a lockpick is an item this map may not hold: the same split
`costing/pickpocket.py` makes between what a published figure is calibrated on
and what an estimate here may assume. The page's other sentence is then the
residual rather than a second fit - "without a lockpick or energy potions, only
rates up to 40,000 can be expected" over 36-45, where this reads 37,905 to
46,868, high at the top because losing the potions lengthens the run back from
the failure teleport and nothing here has a term for it. The chest goes
**16,633/hr to 37,914** where it opens.

**No published training figure decides anything on any cached map any more**,
and the last seven went four different ways - which is the useful part, because
each is a rule rather than a patch.

**An `Output` that contradicts the `Items` is a data error, and the `Items`
win.** Upstream files `Mix a ~|divine magic potion|~` under `Divine ranging
potion(3)` and `Mix a ~|divine battlemage potion|~` under `Divine bastion
potion(3)`. Each put two tasks on one recipe, so `_ambiguous` refused both and
all four kept a `wiki:herblore` figure of 387,500-431,250/hr. `join_keys`
already carried the right output further down the list; `_joined` now prefers
the first key whose recipe the challenge's own `Items` own, and falls back to
the first key otherwise - **a preference, not a filter**, so a challenge listing
nothing prices as it did. The dose is a vocabulary difference here exactly as it
is in `join_keys`: upstream writes the family `Ranging potion[+]` where a
`{{Recipe}}` writes `Ranging potion(3)`, so doses are dropped *after* a literal
comparison fails.

**The markup already says what the thing is.** `Craft a ~|toy cat|~ on a
crafting table 4` carries no `Output` and verb-strips to `toy cat on a crafting
table 4`, which is a facility rather than a thing - eight Crafting challenges
share that shape. The `~|...|~` span is the item, so it is the last exact key.
Coming after `Output` is what keeps `Craft a ~|nature rune|~ with guardian
essence` on the minigame instead of collapsing onto the plain altar rune.

**One lap can be two challenges.** `Run the ~|Wilderness Agility Course|~ with
the agility dispenser` is the lap `courses.py` already prices - the dispenser
hands out one ticket a lap and those tickets *are* `bonus_per_hour`, the
18,400/hr the ticket's own page publishes - so `Course.also` gives it the same
bands. Upstream's third challenge for the course, redeeming the ticket, keeps
**no** rate on purpose: its experience is already inside that 18,400.

**And a method its own page disclaims is refused, not quoted.** The Stranglewood
fishing spot's page says "it is not recommended for training Fishing, not even
when trying to obtain raw pike or caskets", and the figure it carried came from
a *money*-making guide about a table that is newspapers and old boots three
catches in five. `{{Fishing info}}` states the experience (7.5) and nothing
states the cadence, so a chance fitted to the guide's own figure would be the
guide with extra steps. `costing/disclaimed.py` names it with the sentence.

What is left on all three maps is **four hand pins** in `overrides.json` and
nothing else, and only two of those decide a band. **Two of Tithe Farm's three
bands are relabelled at the same time**: they were `exact` off `wiki:tithe`
where they are this project's own arithmetic, which is what made Farming read as
the one skill a scrape still owned outright.

**A `{{Thieving info}}` box says what its `time` means, in its own `type`
field**, and that is what makes the last Thieving guide replaceable. A
`Pickpocket`'s `time` is the stun timer, a `Stall`'s the restock, and a
`Chest`'s the cycle - so the Dorgesh-Kaan wire machine, which is a stall that
can fail, prices as `6000 / 10 ticks x p x 22` with every term published: the
cycle is stated outright ("a total of 10 ticks per wire stolen"), the
experience is in the box, and the success chart is fitted to 23,848 logged
attempts. It checks against the page's own "around 13,000" ceiling (12,943 at
99) and, sharply, against the rebalance note of 8 May 2024 - "from 94.1% at
level 99 to 98.0%" - where the chart read gives **98.05%** and the
pre-rebalance curve still quoted in a hidden comment on the same page would
give 94%. The guide it displaces was a flat 9,240/hr for a method running
**7,167 to 12,943** across the climb. Measured over the wiki, 256 pages carry
the box, 139 also carry a chart and 34 of those state a `time` - almost all
pickpockets or stalls, both already priced - so `costing/wiremachine.py` being
about one object is the measurement rather than a missed generalisation.

**And that same `type` field is what makes the box's `time` readable at all,
which took twenty-two more Thieving methods off the floor.** The field was
being read for the *loop* and thrown away for the *duration*, because it means
two things: a `Stall`'s `time` is the restock and a `Chest`'s the loot
respawn, where a `Pickpocket`'s is the **stun timer** - sixty of the box's
ninety-four - so reading it ungated would price every NPC as a stall
restocking every five seconds. Gated on the kind it supplies exactly what
`Stall/Thievable` files under a name the object's own page does not carry:
Mor Ul Rek's counters are `Shop Counter (gems)`/`(ore)` as pages and `Gem
stall (Mor Ul Rek)`/`Ore stall (Mor Ul Rek)` as rows. **Reading the page beats
aliasing the name**, and the gem counter is why - an alias redirects *every*
lookup, and the Thieving calculator's row for it states 160 experience where
both the stall table and its own infobox say 408. It prices at 13,989/hr,
which is the stall table's own `Max XP/Hr` column exactly.

**A nought is a restock and `> 0` read it as a missing one.** Four chests -
rusty, tarnished, stone and reinforced - state `0 seconds` on the Thieving
page's own table, and their pages say what that means: "the chest's loot
respawns instantly". Dropped as falsy they had no restock at all, so
`restock_kinds` refused them and four real methods read as gaps. The guard was
in two places, the scraper and `load_tables`, and both are `>= 0` now.

**Which interval they take is decided by a published figure rather than by a
third fit.** They are fallible chests retried in place, the Aldarin mechanic -
all four carry a `Teleport chance upon failure` chart - so `fixed_interval`'s
6.8 ticks is the candidate against the 15.5 that measures the walk between
three Rogues' Castle chests. `Stone chest` says "players can expect to gain
over 85,000 experience per hour", which at 280 experience is 304 opens; at
15.5 ticks that needs a success chance of 0.784 where its chart tops out at
**0.605 at level 99**, so the walk interval cannot produce the wiki's own
number at any level. At 6.8 it arrives at level 68, twelve above where the
chest opens - what a figure quoted without a level should look like.

**Half of what the box describes is not a loop, and leaving that unsaid was
the same mistake `coverage.REFUSED` exists for.** `Door`, `Trap` and
`Trapdoor` are twenty-two pages, and they used to stay refused by being
*absent* from `remote/gathering.LOOP_KINDS` - where an absent kind is
indistinguishable from a page nobody scraped, so eleven deliberate refusals
printed as `unpriced`. Carrying the name lets
`gathering.SkillProfile.refused_kinds` say it. **Only `Trap` is still refused**
- six of its seven pages state `xp = 0`, so a trap is a hazard to avoid rather
than an action that pays - and the doors are priced; see below.

**And a refusal by name catches whatever else generates that name, which this
walked straight into.** `Ore stall` looked unanswerable - the wiki's page is a
disambiguation of two level-82 stalls paying 350 in Mor Ul Rek and 191 in Port
Roberts - so it was refused by that name, and the refusal also took `Steal
from a ~|Shop Counter (ore)|~`, whose `Output` is *also* `Ore stall`. The
resolution was better than the refusal anyway: `Module:Skill calc/Thieving`
carries one row called exactly `Ore stall`, at 350, and files the gem counter
beside it as `Gem stall (Mor Ul Rek)` - so the wiki's own calculator uses the
bare name for Mor Ul Rek's, and following it is evidence rather than a guess.

Thieving went **76 modelled to 85 and 34 unpriced to 9**, and no climb moved
on any of the three maps. What is left splits three ways: two Hallowed
Sepulchre coffins and the Rogues' Den wall safe, which are minigame objects
nothing states a cadence for; the ogre coffin and Entrana's candles, whose
boxes carry no `time` and, for the candles, no `type` either; and four with no
Thieving data anywhere - the Grim Tales crumbling wall, Chambers of Xeric
cavern grubs, the H.A.M. storeroom guard (a pickpocket the wiki does not
chart) and the Underground Pass cage, which upstream names no object for.

**Where a page publishes a rate for one skill and a tick-perfect account of
the mechanic, the second answers for the skill the first never mentions.**
The Hallowed Sepulchre's `Experience rates` table is entirely Agility, so both
coffin challenges sat unpriced while `costing/sepulchre.py` quoted that table
for the five floors. `Hallowed Sepulchre/Strategies` states a tick-perfect
time for every entrance of every floor, and a lap runs floors 1 to N in order
- you cannot start on floor 5 - so the mean of those rows plus six ticks a
staircase is the whole no-looting lap, and fifteen more ticks a floor for one
coffin is the looting one. A coffin pays a flat **200** Thieving experience,
stated on both coffin pages and again in the Strategies page's own note, on a
published `Coffin opening success chance` chart - so the expected pay runs
83.6 at level 66 to 149.2 at 99 rather than being flat.

**Tick-perfect is not a rate, and the gap is not one term.** Spent raw the
table prices perfect play - floor 5 at 118,768 against the main page's
`Realistic No looting XP/hour` of 88,500 - which the page's own note says is
possible ("above 100,000 XP/hr at maximum efficiency without mistakes") and
which is therefore a check on the arithmetic rather than the answer. **No
constant overhead reconciles the two**: solving the published column for a
per-floor cost gives 21.8, 19.5, 10.8, 12.8 and 27.9 seconds, so the gap is
mistakes, and mistakes do not scale with the count of staircases. A
`MISTAKE_FACTOR` on the floor time does, calibrated to put a five-floor
no-looting lap at **91,805**, inside the 90,000-95,000 a good player sustains
- and that lands **1.04x** the wiki's own floor-5 figure, a second and
independent check on the same number.

**Twenty seconds between laps is the term that matters more than its size.**
It is the timer running out and putting you back in the lobby, and it is
charged per *lap*: 4% of a five-floor lap and a third of a floor-1 one. That
is why the lower floors read **0.84x to 0.95x** their published rows while the
deepest reads 1.04x - a short lap really is mostly overhead - and it is most of
what closes the gap between shallow and deep coffin runs, which without it
favoured floor 1 by a factor of two.

**The published column is the oracle rather than the source**, the
relationship `costing/barracuda.py` describes - and the check caught a stale
figure of this project's own: floor 5 carried 90,000/98,500 where the page says
75,800/88,500, the 90,000 being a *footnote* about looting only the Grand
Hallowed Coffin.

**Every band is `GUESS`, and the Agility floors moved out of `modelled` to say
so.** Three factors are invented - the staircase, the lobby and the mistake
factor - and `costing/tempoross.py`'s rule is that one invented factor makes
the product invented. The cost is stated: fray-uber's Agility climb goes
**80.9h to 86.8h**, the only climb that moves on any map, and almost all of
that is the stale 98,500 being corrected rather than the model disagreeing
with the page.

**The depth is taken rather than maximised over.** A lap runs to the deepest
floor the map holds, which is what every guide describes and is still *not* the
best coffin rate available - 7,663/hr on floor 1 against 5,331 on five, at
Thieving 99. Maximising would rest the whole answer on one invented number.
**And the depth is read off upstream's own `Access the Nth floor` challenges
rather than off an Agility level**, for `costing/wintertodt.py`'s reason: the
no-map census infers no level, and comparing `1 < 52` there reports a priced
method as unpriced.

**A safe is not opened once, it is worried at - and that is why nothing could
price it.** Every other Thieving object rolls once and you click again; a
Rogues' Den lobby safe keeps going by itself, "another attempt to crack the
safe every 4 ticks (2.4 seconds) until they either crack the safe or trigger a
trap". So the thing with a success chance is the *attempt* and the thing that
pays 70 experience is the *run*, which is a shape `costing/gathering.py` has no
vocabulary for - it wanted a restock, and a safe has nothing to restock.

**Three published numbers and no free parameter**, which is why
`costing/wallsafe.py` is unusually well checked. The chart reproduces the
page's own prose exactly (85/256 and 161/256 against "33.2% at level 50 ...
62.9% at level 99"). The page's trap rule - "the chance of triggering a trap
per attempt appears to be (100% - success chance) / 2" - makes an attempt a
three-way roll and a run a race, so a run cracks with `2p/(1+p)`: **0.4985 and
0.7722** against a published "49%" and "77%", neither of them fitted. And the
cadence is recovered rather than guessed: "the safe can theoretically be looted
every 8 ticks, granting up to 52,500 experience per hour, assuming no failures"
is exactly `70 x 6000 / 8`, so the eight is four ticks of attempt plus four of
re-click, and the model **reduces to that ceiling when `p` is 1**.

It reads 20,926/hr at level 50 and 36,394 at 99, against the page's
"realistically ... around 30-40k xp per hour". The stethoscope series is
charted beside the plain one and not spent - Martin Thwait's shop needs
Agility 50, so it is an item a map may not hold.

**And the last of Thieving's obstacles is 0.2 experience.** `Climb the
~|crumbling wall (Grim Tales)|~` awards a fifth of a point for a long climb
during a quest, per its own `{{Skill info}}`, so it joins the doors in
`refuses` rather than reading as a gap. Thieving is **86 modelled, 3 guessed,
5 unpriced and 17 refused** of 118, from 76/1/34/0 when this started, and no
climb moved for any of it.

**"You unlock a door once and it stays unlocked" is not what disqualifies a
method, and the module that proves it was already in the tree.**
`costing/shortcuts.py` prices an Agility shortcut - a thing in the way, an
experience for getting past it, and no page anywhere stating how often you can
do it - at a stated **eight ticks**, and its own conclusion is that most of
them are not training methods and the numbers say so. A picked lock is that
shape exactly, so refusing doors as a class was inconsistent rather than
careful. Measured first: **not one of the 22 `Door`/`Trap`/`Trapdoor` pages
carries a `time`**, so there was nothing inside the family to infer from and
the borrow is from the nearest published obstacle instead, with
`inferred_loops` capping every door rate at `INFERRED` for it.

**What the charts do to the answer is the interesting part.** A flat eight
ticks would put the Yanille Dungeon door at 37,500/hr, beating every Agility
shortcut in the game; its own `{{Skilling success chart}}` is `low1=4
high1=40` and drops it to **6,006**. Seven of the eleven doors carry a chart
and every one of them is damped like that, so the family runs 2,250/hr for the
Underground Pass cage to 11,602 for the Magic axe hut - which is
`shortcuts.py`'s own finding arriving a second time, from a different skill.
`certain_kinds` is checked *after* every curve source, so the four with no
chart read as certain, which is the wiki's convention and which the
Underground Pass gate's prose confirms outright: "100% successful below the
required level".

**And a task can name the wrong thing entirely.** `Unlock the ~|paladin|~
door` states no `Objects`, so its only join key is the span - and `paladin` is
a real page with a real chart. It priced at **117,670/hr**, a door read as a
pickpocket, and `_ALIASES` could not fix it because the *pickpocket* challenge
offers that key too. `gathering._TASK_NODES` is keyed by whole task name and
**replaces** the key list rather than leading it, which is the half that
mattered: `_experience_for` scans the calculator across every key before it
looks at any infobox, and the calculator has a `Paladin` row and no door, so
leading left the door on the NPC's 131.8 experience and its two-tick cadence.
It reads 6,006/hr against the wiki's own `Door (Ardougne Castle)`, level 61
and 50 experience - upstream's `Level: 61` exactly.

**Upstream names a place where the wiki names the thing**, which is the last
of Thieving's join misses. `Unlock the cage in the ~|Underground Pass|~`
carries no `Objects` and only a chunk, where the wiki has `Cage (Underground
Pass, slave)` and the dungeon walkthrough states its mechanic: "Pick-locking
these cage doors gives 3 experience in the Thieving skill when successful and
can be done at level 1 Thieving" - upstream's `Level: 1` exactly. **Safe
because it is measured**: across every gathering skill in the export, one
challenge offers `Underground Pass` as a key and it is this one. It is *not*
the level-50 `Gate (Underground Pass Shortcut)`, which upstream carries
separately and which the wiki also calls a cage in its prose.

Thieving is **96 modelled, 3 guessed, 4 unpriced and 8 refused** of 118, from
76/1/34/0 when this started, and no climb has moved for any of it.

**Only one chart on a page is about the page, and taking the first was
pricing two NPCs off the wrong one.** `costing/pickpocket.py` already knew -
"a chart is matched by its own label, and three pages prove why" - and fixed
it for *its* scrape; the gathering scrape kept `charts[0]` and did not.
Measured, **31 of the 643 pages carrying `{{Skilling success chart}}` carry
more than one**, and on 29 the first is the right one - a chest's
teleport-on-failure chart, a fishing spot's second rod, the Motherlode ore
split. The two that are not are NPCs you can also *fight*: the H.A.M. Member's
first chart is "Avoiding concussions using Agility" and the Menaphite Thug's a
blackjack "knockout chance". Both were priced off them - the member at
65,571/hr against a true 49,950, and the thug at **330,274 against 122,759**,
a fake method that beat the Rogues' Castle chest. `remote/gathering.
CHART_LABELS` is a two-row hand table for `recipe_rates.HAND_ALIASES`' reason:
a rule general enough to catch them would have to guess which of a page's
charts is about the skill being asked, and "first" is right 29 times in 31.
It moved fray-uber's Thieving climb from 47.4h to 50.1h, the thug's fake band
coming out.

**But a knock-out chart is not junk data, it is a different method's chart** -
which is the correction to the paragraph above, and it is worth more than the
bug was. `Thieving training` gives blackjacking three brackets of the climb:
"knock out the bandit and pickpocket them twice while they are unconscious.
**The timing is right when the player receives experience drops every two
ticks**". So the chance that decides the rate is the knockout's and the two
pickpockets after it are free, which is why the wiki charts a knock-out chance
for these three NPCs and an *awake* chance for only one of them. Priced awake
the Menaphite Thug reads 104,422/hr against a published **265,000**, and the
two Pollnivneach bandits were refused outright as uncharted - true only of a
method nobody uses.

**The cycle lands on the page's own ceiling exactly**: two thug pickpockets at
137.5 over six ticks is **275,000 an hour**, against "at maximum efficiency,
it is possible to gain up to 270,000-275,000 experience per hour at level 99".
That also settles a silence - the bandits' page states that "knocking out
either bandit rewards 10 Thieving experience" and the thug's states nothing,
and crediting the thug a knockout bonus would put perfect play at 285,000,
above the page's own maximum. Against the published brews column
`costing/blackjack.py` runs **1.16x at level 45 falling to 1.02x at 99**, and
**nothing is fitted to close that** because nothing could: a constant
multiplier cannot produce a residual that shrinks, and neither can a constant
overhead - solving the column for extra ticks per cycle gives 1.14 at 45 down
to 0.10 at 99. The page says what the shape is in its own hidden comment,
"lower levels scale down more to factor in that you fail more often and likely
make more mistakes", and practice is not a term this model has.

**Finding it meant the node walk had to stop pricing the bandits**, which had
been the worse half of the same confusion: their only chart is the knock-out
one, so the walk read it as a steal, spent the two-tick awake cadence with no
stun, and gave the bearded bandit the no-beard one's 84.3 experience because
`_names` strips `#Bearded` before the join - **202,488/hr apiece**, three
errors compounding. They are `refuses`d by the one key both offer.

**And a refusal's sentence belongs only on a refused row.** `coverage.build`
was overwriting the source column whenever *anything* had refused the task,
which is not the same claim: the bandits are refused by the node walk and
priced by `blackjack.py`, and the row read `modelled` with "only a knock-out
chart" in the column that should have said `computed:blackjacking`. fray-uber's
Thieving goes 50.1h to **42.5h** with the method in, and no climb moves on
either real map.

**And a curve can be shared outright where the two really are the same
creature.** `Guard (H.A.M. Storerooms)` has no chart anywhere and was refused
with the six uncharted pickpockets, which it is not like: it is a H.A.M.
member with a different loot table, paying the same **22.2** experience, its
own infobox differing only in stating level 20 where the member's says 15. So
`shared_curves` takes the member's line **unmoved** rather than
`assumed_curves` re-anchoring it to open at 20 - the claim is that the chance
is the same function of level, not that the two are equally hard where each
opens. 60.9% at 20 against the member's 59.0% at 15, `INFERRED`, and
defensible where a median over the eighteen charted NPCs is not because it
names one donor for one borrower.

**A failed attempt can pay, and the three pages that say so are all 0.5.**
The ogre coffin's `XP on failure` and the H.A.M. and Port Sarim jail doors'
`Failure XP` are the whole corpus, so `SkillProfile.fail_experience` is a hand
table and `costing/shortcuts.py`'s `failxp` is the same arithmetic on the
Agility side. It matters most where the model is worst: a coffin picked at
level 20 succeeds once in ten, so the eight and a half misses pay 4.4 against
the success's 27 - **16% of the answer**.

**And "no restock stated" is not "no restock, stated".** `restock_kinds`
refuses a chest with no row in the Thieving page's `Respawn Time` table, and
rightly - without one a stall falls back to the interaction cadence and reads
as the fastest method in the game. But the ogre coffins are quest scenery and
were never tabulated, while their own page describes the loop outright: "they
can be safespotted by standing between the northern coffin and the centre
coffin allowing you to continuously pick the coffins". `stated_respawns` is
how a profile says that on the record, and the coffin takes `fixed_interval`'s
6.8 ticks for the reason the pirate chests do - it is picked where you stand.
It reads 2,816/hr at 20 and 12,132 at 99, and the **chart reproduces the
page's own prose exactly**: "without a lockpick, the success rate ranges from
around 10% at level 20, up to a 50% chance at level 99" against 10.16% and
50.00%. What is deliberately not modelled is the drain - every failure costs
1-4 Thieving levels and it stacks - because nothing states how fast it is
restored.

Thieving is **98 modelled, 3 guessed, 2 unpriced and 8 refused** of 118, from
76/1/34/0 when this started.

**Where the wiki states the mechanic and not the number, two of its own
sentences can bound the number.** The Chambers of Xeric thieving room has the
sharpest cadence in the skill - "upon clicking the chest, an attempt to open
it will be made **every game tick** until the player succeeds", sourced to Mod
Ash - and a chart whose plain series reproduces the page's own prose exactly
("around 39% at level 1, scaling to about 61% at level 99"). What it states
nowhere is **what one open pays**: no `{{Thieving info}}` on the chest's page,
no row in the Thieving page's chest table, no row in `Module:Skill calc/
Thieving`, and nothing in the Module namespace - searched rather than assumed.

So `costing/coxchest.py` recovers it, and the recovery is bounded rather than
fitted. `Thieving training` says two independent things about the room: "it
only requires about **one hour of raid time to level from 1-40**", which
integrated over that climb implies 9.75 an open and bounds it to
**[8.36, 11.70]** if "about an hour" is 50 to 70 minutes; and "you can expect
experience rates of **up to 30,000-50,000** experience an hour", which over
the levels the method covers bounds it to **[8.67, 12.51]**. The intervals
overlap on **[8.67, 11.70]** and the figure is the round 10 inside it, at
which the guide's hour is **59 minutes**. That is one unknown against two
observations rather than `costing/disclaimed.py`'s "the guide with extra
steps" - and it is still a `GUESS`, because a figure the wiki declines to
state is not one this project read.

**It is also the one place here that spends a tooled curve.** Everywhere else -
`pickpocket.py`'s gloves, the Hallowed coffins' lockpick, the wall safe's
stethoscope - the plain series is spent because the item comes from a shop a
chunk map may not hold. This lockpick comes from *inside the raid*, "can
obtain from a Scavenger inside the raid", and both bounding observations
assume it; spending the plain series would apply a figure recovered under one
regime to another, and would put the whole climb below the guide's own band.

**The grub cap is arithmetic rather than a caveat.** You cannot carry more
than 28 and the guide's own instruction is to "drop the grubs, then continue
picking locks"; the yield rule is published down to its rounding, and it is
exactly one grub an open below level 50 - so a two-tick drop every 28 opens,
about 4%. That the recovery sits entirely inside that flat stretch is what
makes it independent of the yield rule. Above 49 the yield rises and nothing
says whether the experience follows, which the module names rather than
hides.

Thieving is down to **one** unpriced method - Entrana's candles, whose infobox
carries no `type` and whose page carries no chart.

**A constant standing in for a curve is not the conservative end, and saying
so was the mistake.** `PICKPOCKET_CYCLE_SECONDS` was 3.5 seconds, fitted to one
published figure - a Knight of Ardougne at level 55, 86,000 xp/hr - and its own
comment argued that pricing every NPC at its opening level "understates the tail
rather than overstating the start". Both halves were wrong. `Thieving training`
states that the rates it publishes "assume the player has completed the medium
Ardougne Diary and is using dodgy necklaces", so the figure it was fitted to had
gear in it; and the success chance is not similar across NPCs, running **0.34 to
0.71** at their own opening levels. Measured against each NPC's own curve the
constant is **2x to 3.6x fast on every one of the eighteen the wiki charts**.

Everything needed to replace it is published. The `Thieving` page writes the
equation - "every pickpocket will take on average `2 + 8(1-p)` ticks ... [so]
the actual amount of pickpockets in n ticks will be `np/(10-8p)`" - `Stun
(status)` states the 8-tick lockout, and the never-failing knight rate of
252,900 xp/hr is 3,000 an hour at 84.3 experience and so exactly a 2-tick
attempt. `costing/pickpocket.py` then reproduces the geared 86,000 to **1.6%**,
the tick-perfect figure exactly, and the level the page says failing stops at
(95) to the level. It **spends the plain curve** rather than that one, which is
30% lower and is the usual shape: a guide is evidence about the action, a model
is evidence about the action plus the map.

**A chart is matched by its own label, and three pages prove why.** The H.A.M.
Member's first `{{Skilling success chart}}` is "Avoiding concussions using
Agility" and the Menaphite Thug's a blackjack "knockout chance"; taking the
first chart read the H.A.M. member at 14.5% instead of 59%. The label says
`<NPC> pickpocket chance` and that is the join.

**And the seven NPCs nothing charts keep no rate at all.** The digsite workman,
the villager, the cave goblin, the Fremennik citizen, the two Pollnivneach
bandits and the pirate have a `{{Thieving info}}` box and no success chart
anywhere. Borrowing a median off the other eighteen was refused on that 0.34-0.71
spread - a median is not evidence about any one of them - which is the same call
`costing/shortcuts.py` makes for the 37 shortcuts nothing here can verify. The
cost is stated rather than hidden: the reference map loses its cave-goblin band
and the every-rollable-chunk map its Fremennik-citizen one, both of which were
quoting roughly twice the truth.

**Where a skill rolls, the published rate is the rate of somebody who has
stopped failing.** Firemaking has a `{{Skilling success chart}}` like any
gathering skill - 65/256 at level 1, certain from 43 - and nothing here was
spending it, so the bottom of the skill was quoted at its level-43 figure and
normal logs read 51,979/hr against a true **14,661**. The wiki has done the same
arithmetic and published it, which is the check rather than the source:
`Pay-to-play Firemaking training` multiplies 1,485 logs an hour by the
experience for every band from 42 up and quotes the two bands *below* 43 lower
than that product, under a footnote saying they include failed attempts. Those
ratios are 0.8006 and 0.8850 against **0.7975 and 0.8759** here - two rows, a
real residual, under 1%, which is what a check looks like when it is not an
identity.

**And a twin that needs a different object is a different method.** The export
carries `Burn ~|X logs|~` *and* `Burn ~|X logs|~ at a fire` for fifteen logs,
and their `Items` say what they are: one needs a `Tinderbox` and makes a `Player
fire`, the other needs a `ForesterFire[+]` and no tinderbox at all. They were
priced identically, because `burning_rate` turns an experience figure into a
rate and the log is all either names. A campfire is **9 ticks a log and never
rolls** - the wiki states the tick count in its own change note and quotes a
flat 665 logs an hour at *every* level, where the line-burning table's rows are
docked - so the two **cross over at level 12** and one number for both was wrong
in both directions at once. `costing/firemaking.py` tells them apart on
upstream's `Objects` rather than on the `at a fire` suffix, because a rename can
take a suffix away.

**An identity is worthless as a rate and valuable as an oracle**, which is what
to do with one rather than avoid it. Sailing's last six published figures were
the Barracuda trials, and `Sailing training` states all nine of them as wiki
expressions — `{{#expr:(385 + 14*15 + 2*19.5)*60*60/(108+10)}}` — over
components each trial's *own* page publishes. So `costing/barracuda.py` reads
the components and lands on the same nine numbers to the experience point, and
no climb on any of the three maps moves at all. What that buys is a **check**:
`tests/test_costing_barracuda.py` asserts every computed rate against the
scraped row, so the day Jagex moves a trial's experience and the wiki follows,
the next `chunksim heuristics` fails a test instead of letting the two drift.
The scrape stops being the estimator's source and becomes the model's oracle —
the same relationship `activeTasks` already has to the derivation. It also
recovers what a quotient threw away: the training page's factor order is
inconsistent (`14*15` count-then-each against `25*20` each-then-count), so only
the component form can say how many crates a rank collects, and doing so found
the one place two wiki pages disagree.

**A model has to be refusable on the measurement, and the boat one was.** The
wiki is insistent that a trial's rate depends on the hull — "a rosewood hull to
increase your base boat speed by 20% ... will increase lap speeds and experience
per hour by ~15%", and the Jubbly Jive's Marlin at 85,000/hr on mahogany against
90,000 on camphor — and `Hull` tabulates a speed per tier against a Sailing and a
Construction level, so the map would decide. The two observations imply exponents
of **0.75 and 0.235**. A trial is turning, collecting and waiting as much as it is
sailing, so there is no curve both support and none is invented; every rank is
priced at its target time instead, which is at least the same assumption
everywhere. **That target is a rank threshold and not a lap time** — the standing
bias in all nine figures, scraped or computed, since completion pays "regardless
of time taken" and the wiki's own Gwenith Glide observation is 5:20 against a 6:09
target.

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
a gap; it reads as a faster method. **That twin turned out to be a second
method rather than a duplicate** - a forester's campfire, 9 ticks and no roll,
where the line is 4 and rolls; the pair is `costing/firemaking.py`'s subject
and the paragraph above is what it found.

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

**Every wiki fetch is a developer command that writes into `src/`, and the
estimator never reaches one.** `gather-tables` was the first and the argument
generalised: the tables move about once a game update, so making every install
re-read the wiki costs the estimator a network dependency it does not otherwise
have. `chunksim heuristics` and `chunksim recipes` now write beside it —
`wiki_rates.json`, `wiki_recipes.json`, `wiki_aliases.json` — all checked in and
shipped as package data under the existing `heuristics/*.json` glob, so adding
one needs no packaging change.

**The measurement that forced it**: of 2,411 reachable training methods,
**1,229 priced only when the fetched blobs were present** and 348 without. Now
all 1,577 price from a cache holding no wiki data at all, to identical values —
`tests/test_packaging.py` pins both halves. `cache.SHIPPED_BLOB_NAMES` is the
list, `blob_write_path` is where a developer command writes and `blob_source`
what a reader opens. **A checkout is a closed world in `blob_source`**, real or
a test fixture: reaching past an empty fixture tree to the packaged file made
three simulate tests derive an extra state off rates they were never given.
`chunksim estimate` must still never reach the fetching code, which is why it
is injected into `gathering.build_tables` rather than imported by it.

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
chunksim heuristics             # developer only: rates -> src/chunksim/heuristics/wiki_rates.json (30+ requests)
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
`chunksim chunkinfo`'s envelope around one), `CHUNKSIM_MAP_CACHE`
(presence-only), `CHUNKSIM_SLOW_ORACLES` (presence-only), `CHUNKSIM_NO_WATERMARK`, `CHUNKSIM_TILE_VERSION`,
`CHUNKSIM_GUI_VERBOSE`.

**`chunksim training` is the one subcommand where omitting `--map` asks a different question**
rather than defaulting one, which is why it sets `infer_map=False` and why `cli/app.main` has a hook
for that. With a map it is about that world; without, it is about the *export* - how many of its
2,707 primary methods are `modelled`, `pinned`, `published`, `guess`, `unpriced`,
`refused`, `one-off` or `unreachable` (`costing/coverage.py`). **`--show-category STATUS` turns any of those counts
back into its list** - with a `SKILL` that skill's, without it every skill's grouped - which
is the follow-up the table always provokes and which used to need `--export-json` and a JSON
tool. Both the flag and the positional skill are matched case-insensitively against the names
the table prints (so `guessed` reaches `guess`), and a miss names the valid values and exits
`2` rather than printing an empty section.

**And `--rules-from` is not optional in practice when several maps are cached.** With no
rules borrowed, every rule-gated challenge fails a gate `coverage.blocker_for` cannot name -
there is no rules branch for it to point at - so 866 land in the `unstated` bucket that is
otherwise empty, and Construction reads 2 `unpriced` against 14. The counts are not a smaller
version of the real answer but a different and much emptier one, so the report prints a
warning saying so.

**An absence somebody chose is not the same absence as a gap, and for a long time
the report could not tell them apart.** Several models decline a method *by name* so
that no number is quoted for it - `gathering.SkillProfile.refuses` (the swaying tree
is one object worth one experience, an impling is a wandering spawn nothing publishes
a rate for), `costing/disclaimed.py` (a page whose own words disclaim it),
`pickpocket.refuse_uncharted` (a flat cycle this project has evidence runs 2x-3.6x
fast). Every one of those decisions then printed as **`unpriced`**, the one word that
means "somebody should go and close this" - so the report was stating the opposite of
what the refusal decided, and each module's docstring had to argue against its own
output. `coverage.REFUSED` is the same absence with the deciding module's sentence
beside it, carried on `Heuristics.refused` the way `unroutable` carries "needs Black
mask". **Nineteen rows move on the export** - Woodcutting and Mining reach zero
`unpriced` outright - and the reason is data rather than a comment, which is what
turned four `frozenset`s into mappings.

**It renames only what would otherwise be `unpriced`**, and that is the difference
from `one-off`. A decoration has an arithmetic rate and is exempt anyway, so
`one_off` is checked *ahead* of every priced tier; a refusal has no rate by
construction, so it is checked *last* - and the day somebody finds the missing
mechanic the model wins and the refusal goes quiet with nothing edited, which is
exactly what `costing/disclaimed.py` promises about its own entry.

**`uncompletable` and `unreachable` are one test asked of two worlds, and only one is
news.** A method a particular map cannot do is the ordinary condition of a chunk map. A
method the *ceiling* cannot do - every rollable chunk unlocked - says no player could ever
perform it, so the report names it differently and says **why**, per row
(`coverage.blocker_for`, `MethodStatus.blocker`). Measured, the 307 are: 133 wanting an
item nothing in the world provides (Leagues rewards, `Vorkath's stuffed head`), 108 behind
a quest the ceiling cannot finish, 32 behind a **rule the base map has off** - a player's
choice rather than a gap - 17 an object, 9 a chunk or section outside the rollable set, 6
upstream's own `BackupParent` fallback of a challenge that *is* valid, 2 an NPC, and
**zero unexplained**. The order the branches are tried in is what keeps it from naming
symptoms: a rule-gated family's items are beside the point, and a quest-gated challenge
lists the items that quest would hand over.

**Separating those from the priced statuses is the correction that mattered.** Every computed layer walks the derivation's `valid` set, so a challenge outside
it is never offered to any of them and keeps whatever the raw scrape left in
`Heuristics.training`. Counted as `published` that reads "somebody's guide decides this
method", where the truth is "upstream's own gates put it out of reach and nothing here was
ever asked" - `Mix an ~|ancient brew|~` wants nihil dust and `Mix a ~|Guthix rest|~` a
quest the ceiling cannot finish. Measured, **all 47 of the export's remaining `published`
rows were this, and not one reachable method anywhere is on a published figure.**
Reachability is checked before everything including a pin, because a leftover is a
leftover whoever wrote it. That report still needs a world to price against, and choosing one took
measuring: seeded with `default_rules` the state derives 4,932 valid challenges against a real map's
10,111, because most defaults are `False` and a `False` rule *refuses* its gate; leaving the branch
out is more permissive for refusal-gates (9,273) and still wrong for the ones that widen; every rule
`True` is refused outright by `derive`'s unported `KeyItem Bosses` pass. So it borrows a cached map's
rules and says which.

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
cache/reference/                   # chunkinfo, tasks_map, tile_version
                                   # (the wiki blobs moved to src/chunksim/heuristics/)
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

**The estimator's numbers live in four places and only one is in `cache/`.** `chunksim heuristics`
writes the scrape to `src/chunksim/heuristics/wiki_rates.json` (checked in, shipped); hand-written
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
