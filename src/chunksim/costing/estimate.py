"""How long the outstanding work would take, in the roughest useful terms.

Five buckets - quests, boss drops, monster drops, activity unlocks and
skilling, the set `BUCKETS` names. Every number spent here comes from
`heuristics.py` and is a guess;
the only exact arithmetic is `experience.py`'s XP curve. Read both before
quoting a total.

**Scope is the active set, not everything valid.** One goal per skill
(`active_tasks.py`'s winner), the outstanding BiS picks, and the valid
uncompleted Diary/Quest/Extra tasks - about a hundred things rather than the
~2,700 valid ones. "How long to finish this chunk" is a question about what
you are actually working towards; the superseded tiers below each winner are
not work you will ever do.

**The item is the unit of work, not the task.** Tasks overlap heavily: an
abyssal whip answers a BiS pick, a Slayer collection-log entry *and* the
Abyssal Sire's own log entry, and you obtain one whip. Costing per task
charged for it three times - 1,035 of the real map's hours were that
duplication, across seven items. `ItemEstimate` therefore keys on the item and
carries the tasks it satisfies alongside. Quests are the exception and stay
per-task, a quest not being something you can get twice over.

**Items from one source are earned in parallel, and the total says so.**
Killing abyssal demons for a dagger at 1/32,000 hands you the head at 1/6,000
long before you finish, so the pair costs the dagger's 533 hours and not their
633. Every `ItemEstimate` therefore records the `source` it comes off, and
`EstimateResult.buckets` takes the **longest** item per source rather than the
sum - a superior counting as its base monster, since that is what you are
actually killing. This was the estimate's largest single overstatement:
correcting it took the real map from 10,673 hours to 3,849. The per-item hours
are untouched and still printed, because "how long for this one thing" and
"how long for all of it" are different questions.

**A leaf item's display groups under the task that wants it, not under its
own recipe.** `source` is "what you kill or do for it", and for a real drop
that is a monster or a minigame - a fine display heading. For a made or
bought item it is `make:Craft a coif` or `shop:General Store`: true, but a
one-off name that never groups with anything, so a Diary/CA task needing
several such items showed as that many disconnected headings instead of one.
`ItemEstimate.group` (set by `_leaf_group`, off `_leaf_task_groups`'
task-name -> `other_tasks` group-name index) is the fix: a leaf item's
display key becomes its Diary/CA/Extra group when it has a real task behind
it, so `Coif` reads as a line under `Varrock Diary - Medium` rather than as
its own heading. `EstimateResult.buckets`/`by_source` clamp on the same key
(`_group_key`), so the displayed grouping and the totalled hours can never
disagree about what counts as one thing. A group's heading is `_group_total`'s
**max within a source, summed across sources**: items sharing one real
`source` are earned in parallel and max (unchanged from before `group`
existed - `test_items_from_different_sources_still_add_up` already pins that
distinct sources add, and a shared `group` must not silently turn that into
a clamp), and a Diary/CA cluster can hold both at once if two of its leaf
items happen to route through the same shop or recipe.

**The item walk.** A task needs items; an item has routes (`search.py`'s
`WorldIndex`, the whole-world index of all five); a route has a rate. The
cheapest route wins and its cost is `(1 / p) / kills_per_hour`. Rates come
from `drops`/`skillItems` and are parsed by `rates.parse_ratio`, falling back
to `Heuristics.rarity` for the ~1,200 entries the export words rather than
numbers (`Always`, `Common`, ...). Drop tables compose multiplicatively, the
same expansion `sources.py` does for the unlocked case.

**Three gates stand between a drop and its price, and skipping any of them
prices a game nobody is playing.**

1. *The provider has to be reachable.* `WorldIndex` spans the whole world,
   so without a check the walk costs every drop in OSRS. `SourceIndex`'s
   monsters, objects *and* NPCs are the answer - all placed in an unlocked
   chunk and past their `taskUnlocks` gates. `Colossal Hydra` is what taught
   the check: a `skillItems.Slayer` activity with 43 drops and no chunk
   anywhere, priced as though you could go and fight one. `Larran's big
   chest` taught the breadth of it: a `skillItems` activity is only
   *usually* a monster, and a monsters-only gate refused its 34 drops.
2. *A task-gated monster has to be assigned.* `taskUnlocks['Monsters']` names
   a `<X> task` Nonskill requirement per location - Grotesque Guardians want
   a gargoyle task - and being sent one costs far more than the fighting
   does. `task_gated_monsters` reads them; `_task_hours` prices the wait. If
   no reachable master can assign it, the route has **no** price rather than
   a free one.
3. *The master has to be reachable too.* That gate lives in `slayer.py`, and
   its absence had this module quoting Duradel on a map holding none of him.

**Superiors are the exception that proves the first gate.** A superior slayer
monster is never in a chunk - it replaces a normal counterpart on death, on
task, at 1/200 - so gate 1 correctly refuses it and `_superior_hours` then
prices it through its base monster, which carries gates 2 and 3 itself.

**The four items superiors *share* are priced differently again.** Imbued
heart, eternal gem and the two battlestaves sit on `SuperiorDropTable+`,
which every superior rolls, so they are one source and not thirty-one: you
never hunt a particular superior, you take a master's assignments and price
whatever turns up. `slayer.superior_rolls_per_hour` aggregates the rate over
everything that master can send you to - Krystilia's abyssal demons, jellies
and nechryaels feeding one pool - and does it **per master**, because you
serve one at a time and combining two would describe nobody's game. A
superior's *own* drops stay attributed to its base monster.

**A `make:` route inherits its material's source when that material *is*
the cost.** `Imbue a ~|granite ring|~ at Dom Onion's Reward Shop` needs
nothing beyond a `Granite ring` and a shop trip, so pricing it under its own
`make:Imbue a granite ring...` heading hid it from the same-source clamp
above: the ring priced once under `Grotesque Guardians` and the imbue priced
the same hours again under a one-off heading, on `fray` doubling a chunk of
the estimate that was never two grinds. `_route_hours` now checks whether one
required material accounts for `_DOMINANT_MATERIAL_SHARE` (99%) of the
route's own cost and, when it does, stamps the route with that material's
source instead - so the imbue folds into `Grotesque Guardians`' own group and
clamps against it like any other drop would. **Deliberately narrow**: a
recipe drawing from two different real sources stays summed (you cannot
grind two bosses at once, so that time is genuinely sequential), and a
`make:` chain - a bar smelted before being smithed - never qualifies as the
"material," because propagating through an intermediate would misattribute a
further processing step's own time to whatever fed it.

**Where the time goes, and what was tried.** Pricing every reachable
method's materials was 60.6s on the reference map and is 0.6s, entirely from three
caches that live on the `_Walk` or the `material_seconds` closure and die
with the call: `reachable_lower` and `skill_tables`, which were rebuilt per
*route*, and `_drop_rates`, whose answers do not depend on the quantity being
priced though the walk asks once per quantity - 134,451 calls for 3,661
distinct questions, one pair asked 754 times.

What is *not* done, having been measured: skipping a route whose cheapest
possible cost already exceeds the best found so far. It is sound - every
class has an admissible bound, `1/kills_per_hour` for a kill and
`action_seconds` for a `task:` - but it must skip on a strict `>` and must
not reorder, because the winner is the *first* route achieving the minimum
and `EstimateResult.buckets` clamps per source, so a changed tie-break moves
a bucket total. With the caches in place the profile is flat - no single
function is above a quarter of it - and the remaining upside is a fraction of
0.6s for the only change here that would need that proof. The bound is
written down so the next person measures before building it.

**Two deliberate limits, both of which would otherwise bite.**

- *An item made from other items recurses*, and can cycle: A is the output of
  a challenge needing B, which needs A. Cycles are discarded by a visited
  set, and anything hitting either is reported `unpriced` rather than guessed
  at - the posture `challenges.py` takes with `unsupported`.
- *A task can want a kill rather than a drop.* Several diary tasks are of
  that shape - "kill an abyssal demon in the Slayer Tower" - with `Monsters`
  and no `Items`. They cost one kill, attributed to the monster, so the
  per-source clamp folds them into any grind already happening there. Only a
  BiS task, which has no challenge at all, has its item read out of its
  `~|...|~` span; doing that to a challenge produced a request for an item
  called `Morytania Diary#Elite`.
- *Quantity is ignored.* Drop quantities are strings this project has never
  parsed (`"25-30 (noted)"`, `"1,3"`, `"104-194"`), and every task here is
  "obtain one", so the first drop ends it. A task wanting fifty of something
  is therefore under-costed; none of the active-set tasks currently are.

**The skilling bucket, and the honest gap in it.** Time to a level is
`xp_between(current, target) / rate`, where the rate is the fastest *reachable*
`Primary: true` method - reachable meaning present in `ChallengeResult.valid`,
so an unlocked chunk adding a faster method shortens the estimate. Slayer
takes `slayer.best_master` instead, because its rate is a distribution rather
than a method you pick.

`current` is the problem, and it reaches further than this bucket. **The map
records no skill levels.** `maxSkill` is a *cap* the player declared, not a
level they hold; `passiveSkill` is what is reachable *without* a training
method (`worker.js:5114`) and names five skills on the real map. Neither is
"what I am now".

`infer_levels` reads it out of the ledger instead: **a completed challenge is
proof of its own level requirement.** `Buy the ~|Defence cape|~` is not
something a player under 99 Defence has ticked off, so the highest `Level`
among a skill's completions is a floor on that skill. On the real map that
gives 22 skills real numbers - Defence 99, Cooking 99, Mining 99, Attack 75 -
where `passiveSkill` alone gave five.

It is still a floor. A player at 99 Attack who has ticked nothing above 75
reads as 75, and every skill row prints the level it assumed so a wrong one
is visible. `levels` in `heuristics/overrides.json` replaces it outright.

**`goal_levels` raises that floor to where the chunk is going.** An active
goal carries the level it needs, and finishing the chunk means reaching it -
Slayer here is inferred at 45 and aiming at 92. What a slayer master offers
is judged at *those* levels, because that list is the one that holds for the
tail of the chunk and the tail is where the time goes. The XP still to earn
is measured from the floor up, which is the whole point of the climb.

`slayer.py` reads these numbers to decide what a master will offer, and that
is where they matter most: Vannaka's basilisks want Defence 20, which
`passiveSkill` could not confirm, so the task read as "never offered" - free -
instead of "offered and unreachable", which costs a 30-point skip.

### The item walk is a fixpoint over a table, not a path search

It used to be depth-first with a visited set and a depth bound, and the cost
of that shape was measured before it was replaced: the same subproblem was
re-priced once per *path context* - 284,260 recursive `_item_hours` calls on
the reference map for 3,591 distinct questions, `Pickaxe[+]` alone asked
11,816 times - and without the depth bound the every-rollable-chunk map hung
outright on simple-path enumeration, because a visited set prunes cycles per
path and the paths are factorial.

Now each `(item, quantity, amortise)` question settles once per round into
`_Fixpoint.settled`. A route that closes on a key still on the stack reads
*last round's* answer for it (`_Fixpoint.belief`) instead of exploring around
itself - `None` on the first round, which discards the cyclic path exactly as
the visited set did while every acyclic chain still prices. A question that
read no stale belief is exact in one round, which is nearly every question;
otherwise it re-runs with settled answers promoted to beliefs until the
reads hold. Positive route costs make that converge: a derivation
through a cycle costs more than the acyclic derivation it would have to
beat. `_MAX_ACTIVE` and `_MAX_ROUNDS` are work bounds in the old
`_MAX_DEPTH`'s honest sense - seatbelts, not semantics.

**`_Walk.leaf_routes`** sits under it: the hundreds of kill/shop/spawn routes
per item read nothing recursive, so their best is computed once per question
and only `task:` routes stay live. What remains hot afterwards is not this
module: it is `dps_bridge.enrich`, whose ~5,700 monster pricings are measured
83% distinct.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
import dataclasses
import re
from dataclasses import dataclass, field
from functools import cached_property
from typing import Any, Callable, Sequence

from chunksim.costing.levels import (
    TaskGate,
    goal_levels,
    infer_levels,
    task_gated_monsters,
    _levels,
)
from chunksim.model.chunkinfo import ChunkInfo
from chunksim.model.experience import (
    MAX_LEVEL,
    level_for_xp,
    xp_between,
    xp_for_level,
)
from chunksim.costing.combat_xp import (
    COMBAT_SKILLS,
    farmable_providers,
    hitpoints_credit,
    slayer_credit,
)
from chunksim.costing import (
    brimstone,
    gathering,
    herbs,
    larran,
    lootsack,
    recipe_rates,
    valeoffering,
    yields,
)
from chunksim.costing import barrows, colosseum, gauntlet, instanced, moons, raids, tempoross, tzhaar, wintertodt
from chunksim.remote.recipes import Recipe
from chunksim.costing.farming import (
    DEFAULT_HARVESTS_PER_DAY,
    FarmingPlan,
    plan_for as farming_plan,
)
from chunksim.costing.training import (
    LampGrant,
    TrainingBand,
    TrainingOption,
    quest_xp_grants,
    training_bands,
    training_options,
)
from chunksim.costing.heuristics import (
    TITHE_SOURCE,
    Heuristics,
    Rate,
    Superior,
    activity_name,
)
from chunksim.derive.pipeline import Derived, MapState
from chunksim.model.rates import parse_quantity, parse_ratio
from chunksim.derive.search import WorldIndex, normalise
from chunksim.costing.slayer import (
    MasterRate,
    best_master,
    master_rates,
    superior_rolls_per_hour,
    superior_spawns_per_hour,
    superior_table_items,
)
from chunksim.model.summary import _mapping

#: The buckets, in the order `chunksim estimate` reports them.
BUCKETS = ("quests", "boss drops", "monster drops", "activities", "skilling")

#: There is deliberately no depth bound on the item walk any more.
#:
#: **`_MAX_DEPTH` spent three values and every one of them was a work-around
#: for cost, not a statement about the game.** Three was "past every real
#: case measured" until the soul rune chain needed five; six priced every
#: multi-ingredient pie and was rejected because the unmemoised walk paid
#: 2.5x for it (6.6s to 14.9s on the reference map) - so the pies were
#: reached by inventing `partial_products`, a category of hops that spent no
#: budget, and dose hops were argued free the same way. Three mechanisms,
#: each existing only to manage a bound that its own docstring said "buys a
#: limit on work" rather than correctness.
#:
#: The fixpoint table removed the cost that justified all of it - a chain is
#: settled once rather than re-priced per path context - and what remains is
#: the pure semantics: the cheapest acyclic derivation, however long. A path
#: that closes on itself is discarded; the item still prices through any
#: acyclic chain that reaches it.
#:
#: Measured on removal, against the depth-5 walk it replaced: **no climb
#: moved on any of the three maps** (reference and second map totals
#: identical, the every-rollable-chunk map +0.2h). What moved is the tail
#: the bound had been distorting: 29 method rates on the reference map -
#: all of them runite and adamant smithing, where the bars now price through
#: deeper, cheaper chains and the rates *rose* (rune platebody 1,283/hr ->
#: 2,157) - and on the uber map the lava eel went 9/hr to 2,898, the jade
#: crossbow-bolt enchant and the infernal plate priced at all, and the wild
#: pie fell 20,765/hr to 3,816 because its part-pie ladder is now charged in
#: full rather than waved through as `partial_products`.

#: Routes that cost no meaningful time once reachable: a shop purchase and a
#: ground spawn are both "walk there and take it".
_FREE_ROUTES = frozenset({"shop", "spawn"})

#: Skills this project will not put an hours figure on, whatever the export
#: says about training them. **A refusal, not a gap in the data** - and the
#: only entry is `Sailing`, which was new enough that no money-making guide
#: covered it, `{{Recipe}}` had no rows for it and no wiki table published a
#: rate for any of its 27 primary methods. So every one of them sat at the
#: 1,000/hr floor and the climb read as 13,034 hours, which is not a
#: conservative estimate but a made-up one wearing a number.
#:
#: **Membership is now a *precondition*, not the decision.** It used to be
#: both, which made it a standing claim about the world that nothing rechecked
#: - and the world has since moved: `Sailing training` now publishes figures
#: for barracuda trials, courier tasks, salvaging and sea charting. So a skill
#: named here is refused only while **no reachable method of it has a real
#: rate**, which `training_options` already answers by dropping every
#: `default`. The day one of those rates is joined, the skill prices itself
#: and needs no edit here.
#:
#: The pairing matters in both directions. Without the set, "nothing is rated"
#: would refuse any skill the scrape simply has not reached yet, where the
#: floor is the honest answer and an improving scrape will fix it. Without the
#: recheck, a skill stays refused after the numbers arrive. Remove a skill from
#: here when its rates are not merely published but *joined* - until then the
#: entry costs nothing and stops a 13,034-hour fiction.
UNRATED_SKILLS = frozenset({"Sailing"})

#: A group boss, mapped to the soloable variant that shares its drop table -
#: so the item walk can price the drop off the encounter a player can
#: actually do alone, instead of off a wiki rate that describes a team.
#: `dps_bridge.GROUP_BOSSES` already refuses to *simulate* a kill time for
#: these ("the wiki's rates for these describe a team, so comparing against
#: them is meaningless too" - its own docstring), but that refusal only ever
#: stopped `dps_bridge.price_monsters`/`kills_by_style` from running; nothing
#: kept the wiki money-making-guide rate `Heuristics.kills_per_hour` still
#: has for these names out of the *kill route* this module builds - so
#: `Nightmare staff` priced off "The Nightmare" at a guide's 12/hr rather
#: than off the real, DPS-modelled `Phosani's Nightmare` at 5.8/hr, despite
#: both carrying the item on the export's own drop tables (`chunk_info.drops`
#: - Phosani's is the harder, faster-percentage version: `Nightmare staff` is
#: 1/533 there against 1/300 for the team fight, `Inquisitor's mace` 1/1250
#: against 1/750). **Curated, not derived** - nothing in the export marks
#: which pairs of monsters are the same encounter at two party sizes, and the
#: other ten `GROUP_BOSSES` entries (Nex, Corporeal Beast, the five ordinary
#: Theatre/Chambers/Tombs bosses) have no such solo sibling to redirect to,
#: so they stay refused rather than guessed at.
_GROUP_BOSS_SOLO_ALTERNATIVE: Mapping[str, str] = {"The Nightmare": "Phosani's Nightmare"}

#: Seconds to reach a shop and get back to where the work happens. **A rough
#: fixed figure, not a measurement** - the export has no geography to compute
#: one from, and a bank-to-shop-to-bank run is thirty seconds either side of
#: plausible for most of the map.
SHOP_TRIP_SECONDS = 30.0

#: Seconds one *action* takes when nothing says otherwise. **Performing a
#: conversion used to be free**, so a chain bottoming out in a gathering action
#: with no inputs cost nothing at all: `Plank <- Process logs <- Logs <- Cut
#: logs from roots <- (nothing)`. Four ticks is an ordinary skilling action and
#: is what stands in until a guide's `kph` or a recipe's tick cost says better.
DEFAULT_ACTION_SECONDS = 4 * 0.6

#: `costing/gathering.py`'s five skills - Fishing, Mining, Woodcutting, Hunter,
#: Thieving - the ones a success-chance model and a money-making-guide scrape
#: both exist to cover. See `_route_hours`'s `made == item` gate: a *byproduct*
#: task in one of these five (`Primary` is not `True`) is a fish, ore or drop a
#: guide never quotes a pace for and `gathering.priced_methods` never prices,
#: because both were written for the skill's *training* methods - so "four
#: ticks is a fair stand-in" is a claim about those, not about this.
_UNGUIDED_GATHERING_SKILLS = frozenset(gathering.PROFILES)

#: Seconds to close whatever interface is open, hop to another world and get
#: back to work - **measured, not guessed**: a stopwatch run of "close a shop
#: interface, hop, reopen it" read ten seconds on the dot. `SPAWN_HOPS_PER_HOUR`
#: below had already assumed this figure for a ground spawn with no
#: measurement behind it at all, so one constant now backs both.
WORLD_HOP_SECONDS = 10.0

#: Seconds to pick one item off the ground. One tick, which caps collection
#: at 6,000 an hour before anything else is considered.
SPAWN_PICKUP_SECONDS = 0.6

#: How often you can be standing at a fresh spawn, per hour. **A ground item
#: does not respawn while you wait for it** - the cheap way to collect is to
#: hop worlds, so `WORLD_HOP_SECONDS` a hop is the realistic ceiling.
#: Multiplied by how many of the item sit at that spawn.
SPAWN_HOPS_PER_HOUR = 3600.0 / WORLD_HOP_SECONDS

#: Items one trip can carry back. An inventory is 28 slots and one holds what
#: you are working with, so a purchase run brings 27.
SHOP_TRIP_ITEMS = 27.0

#: A shop's own stock is the controlling cost once it is below a trip's worth,
#: and `WORLD_HOP_SECONDS` is what a fresh one costs. **Rough, like
#: `SHOP_TRIP_SECONDS` above it**: this project has no way to say how many of
#: the ~200 worlds still hold a world nobody has hit recently, so the model
#: assumes every hop finds one - which is exactly why `SHOP_RESTOCK_CUTOFF_SECONDS`
#: exists to cut this model off before that assumption stops being reasonable.
#:
#: Where this is decisive even *inside* the cutoff: Lumbridge General Store's
#: tinderbox (stock 2, 60s restock - nowhere near
#: `SHOP_RESTOCK_CUTOFF_SECONDS`) still needs 13 extra worlds to fill the rest
#: of a 27-item trip, 130 seconds a trip the earning cost alone (1 coin) never
#: charged. Left unmodelled, a low-stock general-store line read exactly as
#: fast as a high-stock one, which is the same shape of join-miss
#: `production.py`'s docstring calls out.
def _shop_hop_seconds(quantity: float, stock: int | None, amortise: bool) -> float:
    if stock is None or stock <= 0:
        return 0.0
    visits = quantity / stock
    if not amortise:
        visits = max(0.0, math.ceil(visits) - 1.0)
    return visits * WORLD_HOP_SECONDS


#: "There's no good way to estimate" how contested a shop's own restock is
#: against the rest of the game running on the same ~200 worlds - so rather
#: than guess at it, a restock slower than this is refused as a route at all,
#: never merely slowed down. Toci's Gem Store clears it at 6h for a ruby, 4h
#: for an emerald and 2h for a sapphire (all measured, `remote/stores.py`);
#: an ordinary general store's tools clear in under two minutes and are
#: untouched. **A flat one hour, chosen rather than derived**: this project
#: refuses a genuinely uncharted mechanic elsewhere (`costing/trawler.py`'s net
#: repair) rather than approximate it, and a contested-restock rate is the same
#: shape of unknown.
SHOP_RESTOCK_CUTOFF_SECONDS = 3600.0


def _location_reachable(walk: _Walk, location: str) -> bool:
    """Whether a `spawn` route's own chunk-or-chunk-section is one this map
    has actually opened.

    **The same shape of miss `costing/herbs.py`'s docstring already found for
    herb patches**: the export writes a location as a plain chunk id
    (`"13141"`) or as a chunk *and* a section (`"11321-2"`), and comparing the
    second against the unlocked-chunk keys silently matches nothing - which
    undercounted herb patches at 5 of 12 on the every-rollable-chunk map
    before `herbs.patch_count` split the two apart. This module never made
    that split at all: a spawn's chunk was never checked against the map's
    own unlocked set, only the *item* was checked against
    `reachable_items` - so an uncut ruby lying in chunk 12581 section 1 (The
    Summer Shore) priced as reachable on a map that had never unlocked it,
    because the same item also has a real, reachable route (a TzHaar gem
    shop) elsewhere.

    Section `"0"` is deliberately not looked up in `reachable_sections`:
    `derive/sections.py`'s own fixed point never inserts it there because
    unlocking a chunk makes it reachable for free.
    """
    chunk, _, section = location.partition("-")
    if chunk not in walk.unlocked_chunks:
        return False
    if not section or section == "0":
        return True
    return bool(walk.reachable_sections.get(chunk, {}).get(section))


def _shop_reachable(walk: _Walk, shop: str) -> bool:
    """Whether `shop` stands in a chunk-or-chunk-section this map has opened.

    `WorldIndex.locations["Shop"]` is built off the same per-chunk `Shop`
    blocks `_location_reachable` reads for `Spawn`, so a shop is reachable
    the same way a spawn is: at least one of its locations open. **A shop
    with no location at all is not gated** - `derive.search.HAND_SHOP_SOURCES`
    exists precisely for a shop the export never states exists in any chunk
    (Malignius Mortifer, for the one hand-added Magic secateurs route), so an
    empty location set means "nothing to check against", not "unreachable".
    """
    locations = walk.world.locations.get("Shop", {}).get(shop)
    if not locations:
        return True
    return any(_location_reachable(walk, location) for location in locations)


def _spawn_block(chunk_info: ChunkInfo, location: str) -> Mapping[str, Any]:
    """The `Spawn` table at a chunk-or-chunk-section location.

    `search.build_world_index` names a sectioned spawn `f"{chunk_id}-{section_id}"`
    and an unsectioned one the bare chunk id - the same split
    `_location_reachable` reads, and for the same reason: reading `provider`
    straight off `chunks[provider]` (as this function replaces) never matches
    a sectioned location at all, so its quantity silently fell back to the
    "unknown, assume one" default instead of the real figure.
    """
    chunk, _, section = location.partition("-")
    entry = chunk_info.chunks.get(chunk, {})
    if not isinstance(entry, dict):
        return {}
    if not section:
        return _mapping(entry, "Spawn")
    return _mapping(_mapping(entry, "Sections").get(section, {}), "Spawn")

#: How much of a `make:` route's own cost its dominant material has to
#: explain before `_route_hours` treats the recipe as *that* material's grind
#: wearing a recipe, and stamps its source accordingly rather than a one-off
#: `make:...` heading - see the comment at the `dominant_source` computation
#: for what this buys (the granite-ring case) and what it deliberately
#: refuses (a slow crafting action layered on a cheap material).
_DOMINANT_MATERIAL_SHARE = 0.99


@dataclass(frozen=True)
class TaskEstimate:
    """One task's cost, and the single most expensive thing behind it."""

    task: str
    bucket: str
    hours: float
    detail: str = ""
    #: The entries behind `hours`, as override-file paths. See `_Priced.knobs`.
    knobs: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "bucket": self.bucket,
            "hours": self.hours,
            "detail": self.detail,
            "knobs": list(self.knobs),
        }


@dataclass(frozen=True)
class _Priced:
    """A costed route to one item: how long, why, and off what."""

    hours: float
    detail: str
    #: The thing you repeatedly kill or do to get it. Items sharing a source
    #: are earned *at the same time*, which is what `EstimateResult.buckets`
    #: uses to stop adding them together.
    source: str
    #: Which entries this number was read off, as **override-file paths**
    #: (`monsters/Abyssal demon`). **Recorded where each is read, never
    #: reconstructed afterwards** - the joins are fuzzy enough
    #: (`heuristics.py` owns `exact`/`contained`) that guessing which entry a
    #: number came from is exactly the mistake this exists to stop.
    #:
    #: **The path is the file's branch, not the `Heuristics` field's name**,
    #: and the two differ in three places: `currencies` is read into
    #: `currency_per_hour`, `actions` into `action_seconds`, `shops` into
    #: `shop_prices`. A knob exists to say where to go and change something,
    #: so a name that is not in the file is worse than no name at all - which
    #: is what the first version of this recorded.
    #: `tests/test_estimate.py` checks every knob a real estimate emits
    #: against `heuristics.CONFIG_BRANCHES`, on the real map - a fixture
    #: reaches one route at a time and missed all three. A route
    #: built out of other routes unions theirs; a route whose numbers are all
    #: constants records nothing, which is the honest answer rather than an
    #: empty gesture at the nearest branch.
    knobs: tuple[str, ...] = ()
    #: `(skill, experience)` earned **along the route this actually took**,
    #: which is why it is carried rather than looked up afterwards.
    #: `_item_hours` takes the `min` over routes, so a bar smelted and a bar
    #: bought cost different amounts *and pay different experience* - and
    #: crediting the smelting to a shop purchase would be fabrication. Empty
    #: for every route but `make:`; a kill, a spawn and a shop pay nothing.
    experience: tuple[tuple[str, float], ...] = ()
    #: This route's own materials, each with its own `_Priced` - empty unless
    #: the caller asked for `trace=True` (`_item_hours`/`_route_hours`), which
    #: nothing but `training.trace_option` does. **Opt-in and additive**: the
    #: `task:` branch of `_route_hours` already builds this list to sum
    #: `.hours` out of it and discards it afterwards - `trace=True` is the
    #: only difference between discarding it and keeping it. Every other
    #: route is already a leaf (`_kill_hours`, shop, spawn, currency, herb,
    #: yield, raid), so `children` is `()` there regardless of `trace`.
    children: tuple["_Priced", ...] = ()
    #: What material this `_Priced` answers the question for, from the
    #: *parent's* own materials list - `""` at the root of a trace (a caller
    #: already knows what it asked about) and on every non-traced answer.
    #: **Not the route's own name** - `.source`/`.detail` already say where
    #: this came from; `label` says what it *is*, which nothing else on this
    #: type carries, because a `_Priced` is otherwise only ever read by the
    #: caller that already knows what item it asked `_item_hours` for.
    label: str = ""


@dataclass(frozen=True)
class ItemEstimate:
    """One item's cost, and every active task that wants it.

    The unit of the boss-drop, monster-drop and activity buckets. Tasks overlap heavily -
    an abyssal whip is a BiS pick *and* two separate log entries - and the
    work of getting one is done once, so the cost is counted once.
    """

    item: str
    bucket: str
    hours: float
    detail: str = ""
    #: What you kill or do for it. Shared sources are worked in parallel.
    source: str = ""
    tasks: tuple[str, ...] = ()
    #: The `Diary`/`Extra` root this item's display groups under, when it has
    #: one - see `_leaf_task_groups` and `EstimateResult.sources_in`. Empty
    #: for everything priced off a real, repeatable source (a monster, a
    #: minigame): those already group correctly under `source`, and giving
    #: them a `group` too would only add a second name for the same thing.
    group: str = ""
    #: The `Heuristics` entries behind `hours`, as override paths - see
    #: `_Priced.knobs`. This is what makes the number arguable: `detail` says
    #: what was assumed in prose, and this says where to go and change it.
    knobs: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "item": self.item,
            "bucket": self.bucket,
            "hours": self.hours,
            "detail": self.detail,
            "source": self.source,
            "tasks": list(self.tasks),
            "group": self.group,
            "knobs": list(self.knobs),
        }


@dataclass(frozen=True)
class SkillEstimate:
    """One skill's climb to its current goal."""

    skill: str
    goal: str
    current_level: int
    target_level: int
    xp: int
    xp_per_hour: float
    method: str
    hours: float
    #: True when the *whole* climb is at the un-joined floor. A climb that is
    #: only part floored reports `floor_xp` instead - see `_skill_estimate`.
    defaulted: bool = False
    #: The climb split where the rate changes, in order. Empty for a skill
    #: already at its goal.
    bands: tuple[TrainingBand, ...] = ()
    #: How much of `xp` is priced at the floor rather than at a measured rate.
    #: Defaulted so every existing constructor stays valid.
    floor_xp: int = 0
    #: XP this climb is spared by quests the map can finish. Already removed
    #: from `xp`, so it is a note about where the head start came from.
    xp_from_quests: int = 0
    #: Calendar days this climb takes, where that is the real constraint
    #: rather than the hours. Farming only - see `costing/farming.py`.
    days: float = 0.0
    #: XP this climb is spared because the *other* combat skills earn it on
    #: the way. Hitpoints only, and in practice most of the climb - see
    #: `combat_xp.hitpoints_credit`. Already removed from `xp`, like the
    #: quest grant beside it.
    xp_from_combat: float = 0.0
    #: The entries behind the climb, one per band that has one. See
    #: `_skill_knobs`, which is where the three cases are decided.
    knobs: tuple[str, ...] = ()
    #: The level the quest XP leaves you at, which is where the climb starts.
    #: Equal to `current_level` when no quest pays into this skill.
    effective_level: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "skill": self.skill,
            "goal": self.goal,
            "current_level": self.current_level,
            "target_level": self.target_level,
            "xp": self.xp,
            "xp_per_hour": self.xp_per_hour,
            "method": self.method,
            "hours": self.hours,
            "defaulted": self.defaulted,
            "floor_xp": self.floor_xp,
            "xp_from_quests": self.xp_from_quests,
            "xp_from_combat": round(self.xp_from_combat, 1),
            "days": round(self.days, 1),
            "xp_from_combat": self.xp_from_combat,
            "effective_level": self.effective_level,
            "knobs": list(self.knobs),
            "bands": [band.as_dict() for band in self.bands],
        }


@dataclass(frozen=True)
class UnpricedSkill:
    """A skill goal this project refuses to put a number on, and why.

    **Not zero, and not the floor.** `Attack`, `Defence`, `Hitpoints` and
    `Ranged` carry no `Primary: true` challenge anywhere in the export - there
    is no "train Attack" entry, because you train it by fighting - so the old
    code divided by a zero rate and reported the climb as **free**, and pricing
    it at the floor instead would put 288 hours on five levels of Attack, wrong
    by two orders of magnitude and in the headline.

    Refusing is the posture this module already takes for an item it cannot
    route (`unpriced`), and it keeps the same total while making it honest.
    """

    skill: str
    goal: str
    current_level: int
    target_level: int
    xp: int
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "skill": self.skill,
            "goal": self.goal,
            "current_level": self.current_level,
            "target_level": self.target_level,
            "xp": self.xp,
            "reason": self.reason,
        }


def _group_key(item: ItemEstimate) -> str:
    """The display/clamping key for one item - `group` if it has one."""
    return item.group or item.source or item.item


def _group_total(items: Sequence[ItemEstimate]) -> float:
    """A group's hours: **max within a source, summed across sources**.

    Two items off the same `source` are earned in parallel (one Abyssal
    demon grind pays for both the dagger and the head), so they max. Two
    items off *different* sources are not - buying rope does not buy a
    tinderbox even when the same shop sells both and the same Diary task
    wants both - so distinct sources add. A `group` (an item with no real
    repeatable source of its own, rolled up under the Diary/CA task that
    wants it - see `ItemEstimate.group`) can hold both shapes at once: two
    leaf items sharing one `shop:` source *and* a third from an unrelated
    `make:` route. Maxing within a source first and summing the per-source
    maxes after is the one rule that gets every combination right, and it is
    also just what `source`-only grouping already did before `group`
    existed - this is that rule, generalised rather than replaced.
    """
    per_source: dict[str, float] = {}
    for item in items:
        per_source[item.source] = max(per_source.get(item.source, 0.0), item.hours)
    return sum(per_source.values())


@dataclass(frozen=True)
class EstimateResult:
    """Per-bucket hours, the detail behind them, and what could not be priced."""

    #: Quest-bucket entries. Quests are the one thing costed per *task*, since
    #: a quest is not an item you can get twice over.
    tasks: tuple[TaskEstimate, ...] = ()
    #: The boss-drop, monster-drop and activity buckets, one entry per unique item.
    items: tuple[ItemEstimate, ...] = ()
    skills: tuple[SkillEstimate, ...] = ()
    #: The master the Slayer estimate used - the fastest reachable one.
    slayer: MasterRate | None = None
    #: **Every** reachable master, fastest first. The estimate has to pick
    #: one, but XP rate is not the only reason to choose: coverage, how much
    #: of the list is unpriced, and how often supers turn up all differ, and
    #: a player may reasonably want a slower master for any of them. Shown in
    #: full rather than collapsed to the winner.
    slayer_masters: tuple[MasterRate, ...] = ()
    #: `master -> superior *spawns* per hour`. What a player recognises,
    #: and two orders of magnitude commoner than a shared-table roll.
    superior_spawns: dict[str, float] = field(default_factory=dict)
    #: `master -> superior-table rolls per hour`, for the same comparison.
    #: Computed at the levels the player has *declared they can reach*, not
    #: the ones they hold, because that is what the item prices rest on - the
    #: skilling bucket is already paying for the climb. At a passive floor of
    #: 45 every superior-bearing task is level-gated out and this would read
    #: zero everywhere, which would contradict the hours printed beside it.
    superior_rolls: dict[str, float] = field(default_factory=dict)
    #: Items with no priceable route - the honest coverage figure.
    unpriced: tuple[str, ...] = ()
    #: Skill goals with no trainable method anywhere in the export. Reported
    #: rather than priced; see `UnpricedSkill`.
    unpriced_skills: tuple[UnpricedSkill, ...] = ()
    #: Quest XP that may go to one of several skills, left unspent. See
    #: `training.LampGrant`.
    unallocated_quest_xp: tuple[LampGrant, ...] = ()

    @property
    def buckets(self) -> dict[str, float]:
        """Hours per bucket, **clamped per source**.

        Items from the same source are earned at the same time, not one after
        another: the hours that get you an abyssal dagger at 1/32,000 have
        long since got you the abyssal head at 1/6,000, so the pair costs the
        dagger's time and not their sum. Summing them was the estimate's
        largest single overstatement - on the real map it turned a 2,400-hour
        Abyssal demon grind into nearly 4,000.

        The per-item hours are untouched and still reported: "how long for
        this one thing" and "how long for all of it" are different questions
        and both are worth answering.
        """
        totals = {bucket: 0.0 for bucket in BUCKETS}
        for task in self.tasks:
            totals[task.bucket] = totals.get(task.bucket, 0.0) + task.hours
        for (bucket, _), hours in self.by_source().items():
            totals[bucket] = totals.get(bucket, 0.0) + hours
        totals["skilling"] += sum(skill.hours for skill in self.skills)
        return totals

    def by_source(self) -> dict[tuple[str, str], float]:
        """`(bucket, display key) -> hours` - see `_group_total`."""
        grouped: dict[tuple[str, str], list[ItemEstimate]] = {}
        for item in self.items:
            grouped.setdefault((item.bucket, _group_key(item)), []).append(item)
        return {key: _group_total(items) for key, items in grouped.items()}

    def sources_in(self, bucket: str) -> list[tuple[str, float, list[ItemEstimate]]]:
        """Each display group in `bucket`: what it costs, and what it yields.

        Grouped by `ItemEstimate.group` where an item has one, else by its
        `source` - `_group_key`. `Abyssal dagger` and `Abyssal head` group
        under `Abyssal demon` either way; `Coif` (`source="make:Craft a
        coif"`, no real repeatable source of its own) groups under whichever
        Diary/CA task wants it instead of standing as its own one-off
        heading. `_group_total` decides max vs sum per group.
        """
        grouped: dict[str, list[ItemEstimate]] = {}
        for item in self.items_in(bucket):
            grouped.setdefault(_group_key(item), []).append(item)
        return sorted(
            ((key, _group_total(items), items) for key, items in grouped.items()),
            key=lambda row: (-row[1], row[0]),
        )

    @property
    def total_hours(self) -> float:
        return sum(self.buckets.values())

    def items_in(self, bucket: str) -> list[ItemEstimate]:
        return sorted(
            (item for item in self.items if item.bucket == bucket),
            key=lambda item: (-item.hours, item.item),
        )

    def in_bucket(self, bucket: str) -> list[TaskEstimate]:
        return sorted(
            (task for task in self.tasks if task.bucket == bucket),
            key=lambda task: (-task.hours, task.task),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "buckets": self.buckets,
            "total_hours": self.total_hours,
            "tasks": [task.as_dict() for task in self.tasks],
            "items": [item.as_dict() for item in self.items],
            "by_source": {
                f"{bucket}/{source}": hours
                for (bucket, source), hours in self.by_source().items()
            },
            "skills": [skill.as_dict() for skill in self.skills],
            "slayer": self.slayer.as_dict() if self.slayer else None,
            "slayer_masters": [
                {
                    **rate.as_dict(),
                    "superior_spawns_per_hour": self.superior_spawns.get(rate.master, 0.0),
                    "superior_rolls_per_hour": self.superior_rolls.get(rate.master, 0.0),
                }
                for rate in self.slayer_masters
            ],
            "unpriced": list(self.unpriced),
            "unpriced_skills": [skill.as_dict() for skill in self.unpriced_skills],
            "unallocated_quest_xp": [lamp.as_dict() for lamp in self.unallocated_quest_xp],
        }


class _Fixpoint:
    """Mutable state for the walk's fixpoint evaluation - see `_item_hours`.

    One per `_Walk`, dying with it, which is the sanctioned cache shape. The
    walk is single-threaded within one call tree, so none of this needs a
    lock, and `--jobs` workers each build their own.
    """

    __slots__ = ("settled", "belief", "active", "reads", "readsets", "pending")

    def __init__(self) -> None:
        #: `(item, quantity, amortise, trace)` -> this round's answer.
        #: Authoritative once a round completes without reading any belief
        #: that then moved.
        #:
        #: **Authoritative for *this* walk only, and it must never be seeded
        #: from another one.** `_settle` returns a key present here without
        #: re-deriving it, and a seeded key carries no `readsets` entry, so
        #: the convergence loop's invalidation cannot reach it either: it is
        #: frozen for the walk's life. A grind tried exactly this - adopting
        #: the previous roll's table, since a roll only *adds* providers and
        #: a route that existed still costs what it cost. That argument is
        #: true and insufficient. It reasons only about routes that existed,
        #: where three things move a settled answer between two states:
        #: a `None` becoming a route (the roll provided the first one), a
        #: cost falling (a new provider undercut the old), and the
        #: `Heuristics` the walk spends being recomputed per roll. All three
        #: are live - the measured failure was Prayer silently losing
        #: `Wyvern bones (Chaos Altar)`, whose `None` was settled before the
        #: bones were reachable and served forever after. Worth 27% a roll
        #: and reverted anyway; a sound seed needs per-key dependencies over
        #: the reachability gates *and* the rates, which this does not track.
        self.settled: dict[tuple[str, float, bool, bool], _Priced | None] = {}
        #: Last round's answers, consulted only where evaluation closes on
        #: itself. Empty on the first round, which prices a cycle's back-edge
        #: as "no route" - exactly the path-discard the visited set used to
        #: perform, but paid once per question rather than once per path.
        self.belief: dict[tuple[str, float, bool, bool], _Priced | None] = {}
        #: The keys currently being evaluated on the stack.
        self.active: set[tuple[str, float, bool, bool]] = set()
        #: Every belief read this round, with the value that was read. **The
        #: whole convergence test**: a round is exact iff every value it read
        #: matches that key's final answer - `settled` where the key settled
        #: after the cycle unwound, the belief itself otherwise. Checking
        #: reads rather than "did anything newly settle" is what stops a
        #: question whose answers were already right from promoting and
        #: re-deriving its cone: the first cut retried on any new key, and
        #: the every-rollable-chunk map paid 7.27 million evaluations for
        #: 1,634 questions before this rule replaced it.
        self.reads: dict[tuple[str, float, bool, bool], _Priced | None] = {}
        #: key -> the belief keys its evaluation transitively read, kept only
        #: where that set is non-empty - which is only the keys inside a
        #: cyclic cluster, a few dozen against the uber map's 136,875. **What
        #: makes a retry cheap**: when a read turns out stale, exactly the
        #: keys whose readsets touch it are re-derived, and everything else
        #: stays settled. The first cut cleared `settled` wholesale and paid
        #: 4 million evaluations for 137 thousand distinct questions.
        self.readsets: dict[
            tuple[str, float, bool, bool], frozenset[tuple[str, float, bool, bool]]
        ] = {}
        #: The evaluation stack's read-accumulators, one per active key.
        #: A child's reads roll up into its parent on pop, which is what
        #: makes `readsets` transitive without a graph walk.
        self.pending: list[set[tuple[str, float, bool, bool]]] = []


@dataclass(frozen=True)
class _Walk:
    """Everything the item walk reads, bundled so it isn't passed six-deep."""

    chunk_info: ChunkInfo
    world: WorldIndex
    heuristics: Heuristics
    tables: dict[str, Any] = field(default_factory=dict)
    #: `{challenge: (skill, experience one performance pays)}` - see
    #: `recipe_rates.challenge_experience`. What lets a `make:` route say what
    #: it earned as well as what it cost.
    made_experience: Mapping[str, tuple[str, float]] = field(default_factory=dict)
    #: `{output (lowercased): recipes}` across every skill, for the **last
    #: resort** route - see `_recipe_hours`. An intermediate the export has no
    #: challenge for is otherwise unreachable however well the wiki documents
    #: it: chiselling a dark essence block into fragments pays *Crafting*, so
    #: upstream lists no Runecraft challenge, and `Dark essence fragments` had
    #: no route at all on a map holding the Dark Altar.
    recipes: Mapping[str, tuple[Recipe, ...]] = field(default_factory=dict)
    #: `{herb: seconds}` from `costing/herbs.py`. **Checked before the routes**,
    #: like currency, because both routes the walk would otherwise take are
    #: wrong on their own: farming priced at the clicking ignores the eighty
    #: minutes a herb grows, and a drop priced per herb asks a table that hands
    #: out thirteen without being asked which.
    herb_seconds: Mapping[str, float] = field(default_factory=dict)
    #: `{lowercased item: seconds}` from `costing/raids.py` - a raid reward
    #: priced by the raid rather than by the drop table the export files it
    #: under.
    #:
    #: **Lowercased, because three vocabularies meet here.** The wiki writes
    #: `Scythe of Vitur (uncharged)`, upstream's drop table writes `Scythe of
    #: vitur`, and `world.item_sources` does not carry it at all - so neither
    #: the wiki's spelling nor `by_lower` reaches it. Folding the case is the
    #: only lookup that finds every one, and an item name is not a place two
    #: different things differ only by capitalisation.
    #:
    #: **Checked before the routes, for `herb_seconds`' reason and more
    #: sharply.** The export models each raid as a monster carrying a table,
    #: so `Heuristics.kills_per_hour` fell back to `DEFAULT_KPH` and the walk
    #: read 150 raids an hour: a twisted bow priced at 5.7 hours against 289,
    #: and `Xeric's champion` - two thousand completions - at **24 seconds**.
    #: A route that wrong cannot be allowed to win, and `yield_seconds` is a
    #: last-resort fallback that by design never displaces one.
    raid_seconds: Mapping[str, float] = field(default_factory=dict)
    #: `{item: seconds}` from `costing/yields.py` - a gathering action's own
    #: weight tiers, which the certainty gate below would otherwise refuse.
    #: **Flat, and checked before the routes**, for the reason the herb one
    #: is: routing them would divide the quantity by a fractional share, and
    #: a fractional quantity is a fixpoint key nothing else ever matches.
    yield_seconds: Mapping[str, float] = field(default_factory=dict)
    #: Everything reachable on this map that can *provide* an item: the
    #: monsters, objects and NPCs of `SourceIndex`, all past their
    #: `taskUnlocks` gates. Not monsters alone - a `skillItems` activity is
    #: only usually a monster (`search.py`), and `Larran's big chest` is an
    #: Object, so a monsters-only gate refused its 34 drops outright.
    available: frozenset[str] = frozenset()
    #: Items this map can actually get hold of - `SourceIndex.items`, which is
    #: already gated on `taskUnlocks['Shops']`, the minigame rule and the
    #: backlog. A shop or spawn route is only free if it is *here*.
    reachable_items: frozenset[str] = frozenset()
    #: `derived.expanded_chunks`' key set: chunk ids (and named areas) this
    #: map has actually unlocked. **A spawn needs its own chunk checked, not
    #: just its item** - `reachable_items` says "Uncut ruby exists somewhere
    #: reachable", which stayed true through a real TzHaar shop route even
    #: while a *specific* ground spawn (`12581-1`, The Summer Shore) sat in a
    #: chunk nobody had unlocked. See `_location_reachable`.
    unlocked_chunks: frozenset[str] = frozenset()
    #: `derived.reachable_sections`: `{chunk: {section: True}}` for every
    #: section beyond the implicit `"0"` - `derive/sections.py`'s own fixed
    #: point. A spawn keyed by a chunk-and-section location needs this, not
    #: `unlocked_chunks` alone: unlocking a chunk only opens section `0`.
    reachable_sections: Mapping[str, Mapping[str, bool]] = field(default_factory=dict)
    #: Monster -> the slayer task you must be on to fight it, where one is
    #: required. Derived from `taskUnlocks`; see `task_gated_monsters`.
    #: `monster -> TaskGate`. **The gate carries where it applies**, because
    #: `Konar quo Maten` keys his tasks by location and a bare name matches
    #: none of his 93 - see `costing/levels.TaskGate`.
    task_gates: dict[str, TaskGate] = field(default_factory=dict)
    #: `codeItems.itemsPlus`: `Air rune[+]` -> the four runes that satisfy it.
    #: **Upstream's "or anything equivalent" marker**, and the item walk never
    #: read it - so a task wanting `Air rune[+]` found no item by that name and
    #: went unpriced, while `Air rune` itself priced in 2.4 seconds.
    item_families: dict[str, list[str]] = field(default_factory=dict)
    #: The shared superior drop table: item -> its share of one roll.
    superior_table: dict[str, float] = field(default_factory=dict)
    #: `master -> superior-table rolls per hour` while serving that master.
    superior_rolls: dict[str, float] = field(default_factory=dict)
    #: Every master's task table. A gated kill is priced against whichever
    #: master can assign the task *soonest*, not the one with the best XP
    #: rate: different masters assign different things, and Krystilia being
    #: fastest overall is no help at all when the task you need is gargoyles.
    masters: tuple[MasterRate, ...] = ()
    #: `(monster, item)` -> `_drop_rates`' answer for this walk. The rates are
    #: a fact about the export and the config, so they do not vary with the
    #: quantity being priced - but `_item_hours` is called once per quantity,
    #: and each of those re-walks the same routes asking the same question.
    #: Measured pricing the reference map's methods: 134,451 calls, 3,661 distinct, one
    #: pair asked 754 times. Filled lazily rather than built up front, since a
    #: single `estimate` touches a fraction of the export's monsters.
    drop_rates: dict[tuple[str, str], tuple[float, float] | None] = field(
        default_factory=dict
    )
    #: The fixpoint state: settled answers, last round's beliefs, and the
    #: keys on the stack. See `_item_hours` for the algorithm and
    #: `_Fixpoint` for the fields. Per-call like `drop_rates` above - never
    #: module state, so `--jobs` stays honest. **Both
    #: `dataclasses.replace(walk, ...)` sites reset it**, because `replace`
    #: shares field references and the fields they change (`recipes`,
    #: `made_experience`) change answers.
    fixpoint: _Fixpoint = field(default_factory=_Fixpoint)
    #: `(item, quantity, amortise)` -> the best **leaf** route and its position
    #: in `item_sources`, or `None` when no leaf prices. A leaf is any source
    #: that does not recurse - a kill, a shop, a ground spawn - and none of
    #: them reads `seen` or `depth`, so the answer is a fact about the walk
    #: rather than about the caller. This is what the subtree memo above
    #: cannot catch: the toolchain cycle (a pickaxe is bars is ore is a
    #: pickaxe) makes those subtrees context-shaped, but the hundreds of kill
    #: routes re-scanned inside every one of those contexts are not.
    #: Measured on the reference map it takes `_kill_hours` from 2.26M calls
    #: to the distinct few thousand.
    leaf_routes: dict[
        tuple[str, float, bool], tuple["_Priced", int] | None
    ] = field(default_factory=dict)
    #: item -> the quantity-independent facts of its kill routes, plus the
    #: leaf sources that still need a live call (free routes, and superiors,
    #: which recurse). **What makes a leaf scan arithmetic**: on the
    #: every-rollable-chunk map a common drop has hundreds of kill sources,
    #: and the scan ran `_kill_hours` 1.26 million times - formatting a
    #: detail string and allocating a `_Priced` for candidates that lose the
    #: min. The facts hoist the gates, the drop rates and the per-master
    #: assignment waits once per item; each `(quantity, amortise)` question
    #: is then a few float operations per fact, and only the winner builds
    #: its `_Priced`. Exact: same arithmetic in the same order, ties still
    #: resolved by `item_sources` position.
    kill_facts: dict[
        str, tuple[tuple["_KillFact", ...], tuple[tuple[int, str, str], ...]]
    ] = field(default_factory=dict)
    #: item -> its `task:` sources with their positions **and their
    #: challenges**, so the live half of the split loop neither re-filters
    #: `item_sources` nor re-reads the export per call - the challenge lookup
    #: was two `_mapping` calls inside a loop that runs a million times on the
    #: reference map. A source whose skill the export does not carry, or whose
    #: challenge is not a dict, is dropped here once rather than refused per
    #: call.
    task_routes: dict[
        str, tuple[tuple[int, str, str, dict[str, Any]], ...]
    ] = field(default_factory=dict)
    #: Lowercased item name -> the export's own spelling. Task names carry
    #: the item in lower case inside their `~|...|~` span
    #: (`Obtain a ~|granite ring (i)|~`) while `item_sources` is keyed by the
    #: item itself (`Granite ring (i)`), so a case-sensitive lookup silently
    #: fails to price every task reached through its span.
    by_lower: dict[str, str] = field(default_factory=dict)

    @cached_property
    def reachable_lower(self) -> frozenset[str]:
        """`reachable_items` lowercased, for the free-route gate.

        **Cached because `_route_hours` asks per route, not per item.** Built
        fresh it is a 1,918-name `frozenset` comprehension, and the shop/spawn
        gate reads it once for every one of the map's ~5,550 free sources - so
        as a plain property it cost `computed_rates` 47.9s of its 60.6s.
        Caching it is 9x on the recipe walk and moves no number.

        Per-instance, on a `_Walk` built per `_setup` call - the same local
        cache `material_seconds`' closure is, never module-level, so the
        purity rule that keeps `--jobs` honest is untouched. `_Walk` is frozen
        but has a `__dict__` (no `slots=True`), which is what lets
        `cached_property` write through; `dataclasses.replace` yields a fresh
        instance with an empty cache, so the field cannot outlive its input.
        """
        return frozenset(name.lower() for name in self.reachable_items)

    @cached_property
    def skill_tables(self) -> tuple[dict[str, Any], ...]:
        """`skillItems` flattened to the same `{activity: {item: {qty: rate}}}`.

        Cached for the same reason and on the same terms as `reachable_lower`:
        it is a pure function of `chunk_info` that `_drop_rates` rebuilt on
        every call, once per drop route per item.
        """
        return tuple(
            _mapping(self.chunk_info.skill_items, skill)
            for skill in self.chunk_info.skill_items
        )

    def resolve(self, item: str) -> str:
        """The export's spelling of `item`, if it has one."""
        return self.by_lower.get(item.strip().lower(), item)


def _probability(raw: str, heuristics: Heuristics) -> float | None:
    """A drop-rate string as a probability, or `None` if it says nothing.

    `rates.parse_ratio` returns `nan` for every non-fraction, which is 1,197
    of the export's 12,939 rate entries; the worded ones resolve through the
    config, and `Varies`/`Unknown` stay `None` on purpose.
    """
    ratio = parse_ratio(raw.partition("@")[0])
    if not math.isnan(ratio):
        return ratio if 0 < ratio <= 1 else None
    return heuristics.rarity(raw)


def _drop_rates(walk: _Walk, monster: str, item: str) -> tuple[float, float] | None:
    """`(chance, yield)` for one kill of `monster`: how often `item` drops, and
    how many arrive when it does.

    **Two numbers because there are two questions.** Obtaining an item at all
    is one roll of the table however big the stack - Hydra's dragon knives are
    1/10,000 whether the drop is 200 or 400 - so a *goal* is priced on
    `chance`. Accumulating a hundred of something is priced on the expected
    yield, `chance * stack`, because the stack really does amortise. Using
    either number for the other question is wrong by the stack size, which the
    export puts as high as 45.

    A range is its mean and a note is the same item; see `rates.parse_quantity`
    for both, and `_kill_hours` for how the two combine.

    Several rows can offer the same item, so the best of each wins.

    Memoised on the walk - see `_Walk.drop_rates` for why the same question
    arrives dozens of times, and the module docstring for why a cache that
    lives on a stack-local object is not the module state the purity rule
    forbids.
    """
    key = (monster, item)
    if key in walk.drop_rates:
        # `None` is an answer: "this monster does not drop it". Asking `in`
        # rather than `get` keeps that from being recomputed every time.
        return walk.drop_rates[key]

    best: tuple[float, float] | None = None
    for source in (walk.chunk_info.drops, *walk.skill_tables):
        rows = _mapping(source, monster)
        for name, quantities in rows.items():
            if not isinstance(quantities, dict):
                continue
            direct = name == item
            table = walk.tables.get(name) if not direct else None
            if not direct and not isinstance(table, dict):
                continue
            for count, raw in quantities.items():
                chance = _probability(str(raw), walk.heuristics)
                if chance is None:
                    continue
                if not direct:
                    within = _table_probability(table, item, walk.heuristics)
                    if within is None:
                        continue
                    chance *= within
                stack = parse_quantity(str(count)) or 1.0
                found = (chance, chance * stack)
                best = found if best is None else (
                    max(best[0], found[0]), max(best[1], found[1])
                )
    walk.drop_rates[key] = best
    return best


def _table_probability(
    table: dict[str, Any] | None, item: str, heuristics: Heuristics
) -> float | None:
    if not isinstance(table, dict):
        return None
    raw = table.get(item)
    return _probability(str(raw), heuristics) if raw is not None else None


def _item_hours(
    walk: _Walk,
    item: str,
    *,
    quantity: float = 1.0,
    amortise: bool = False,
    trace: bool = False,
) -> _Priced | None:
    """Cheapest route to `quantity` of `item`, as `(hours, why)`, or `None`.

    `None` is "no route this module can price", which the caller reports as
    unpriced rather than dropping - an estimate that silently skips its
    expensive half is worse than one that admits a gap.

    **`quantity` defaults to one, which is every goal.** A task wants an
    abyssal whip, not forty; the parameter exists for *materials*, where a
    recipe consuming two guam leaves an action is asking a different question
    and a stacked drop amortises across it. See `_drop_rates`.

    **`trace` asks the same question and gets a fuller answer, never a
    different one.** Off (the default) everywhere but `training.trace_option`,
    it only tells a recursive route (`_route_hours`'s `task:` branch) to keep
    the `_Priced` of each material it already prices, on `_Priced.children`,
    instead of discarding the list once `.hours` is summed out of it - see
    `costing/training.py`. It widens the fixpoint key to `(item, quantity,
    amortise, trace)` so a traced and an untraced question never share one
    settled answer, but it is a `bool`, not the fractional-quantity blow-up
    the warning below is about - and a trace call always builds its own fresh
    `_Walk`, so in ordinary use the two questions never even meet in one
    table.

    **The evaluation is a fixpoint, not a path search.** Each `(item,
    quantity, amortise)` question is settled once per round into a table; a
    route that closes on a key already on the stack reads *last round's*
    answer for it instead of exploring around itself - `None` on the first
    round, which discards the cyclic path exactly as the old visited set did,
    while any acyclic chain to the same item still prices. A round is exact
    when every belief it read matches that key's final answer
    (`_Fixpoint.reads`), which is one round for nearly every question;
    otherwise the settled answers are promoted to beliefs and the question
    re-runs until the reads hold, which positive route costs guarantee
    terminates - a derivation through a cycle costs more than the acyclic
    derivation it would have to beat.

    This is what replaced both the visited-set recursion and `_MAX_DEPTH`.
    The path search priced the same subproblem once per *path context* -
    fine at depth 5, factorial without it: the every-rollable-chunk map hung
    on simple-path enumeration the moment the bound came off. The table
    prices it once per round, and rounds are almost always one.
    """
    item = walk.resolve(item)
    fixpoint = walk.fixpoint
    key = (item, quantity, amortise, trace)
    if fixpoint.active:
        return _settle(walk, key)

    # Top level: run rounds until every belief read held. `found` is bound
    # on the first pass, and `_MAX_ROUNDS` is a work bound in the same
    # spirit as `_MAX_ACTIVE` - convergence is expected in two.
    found: _Priced | None = None
    for _ in range(_MAX_ROUNDS):
        fixpoint.reads.clear()
        found = _settle(walk, key)
        settled = fixpoint.settled
        belief = fixpoint.belief
        stale = {
            read
            for read, value in fixpoint.reads.items()
            if (settled[read] if read in settled else belief.get(read)) != value
        }
        if not stale:
            break
        # A belief that was read has since moved, so every settled answer
        # whose evaluation transitively read one of the moved keys is
        # re-derived - and only those. Their current values are promoted to
        # beliefs first, so the next round's cycles read this round's
        # answers; everything outside the cluster stays settled, which is
        # what keeps a retry proportional to the cycle rather than to the
        # question's whole cone.
        doomed = [
            settled_key
            for settled_key, read_keys in fixpoint.readsets.items()
            if read_keys & stale and settled_key in settled
        ]
        for settled_key in doomed:
            belief[settled_key] = settled.pop(settled_key)
            fixpoint.readsets.pop(settled_key, None)
    return found


def priced_material(
    walk: _Walk,
    item: str,
    quantity: float,
    *,
    amortise: bool = True,
    material_aliases: Mapping[str, str] = {},
) -> _Priced | None:
    """`_item_hours` with its recursion kept, for `training.trace_option`.

    The only caller allowed to ask for `trace=True` - everywhere else in this
    module asks the ordinary question and gets the ordinary, childless
    answer. Public rather than a second underscored name so
    `costing/training.py` can reach the walk's own pricing without a second
    implementation of it, the trade `_route_hours`'s own docstring warns a
    parallel walker would have to make.

    **Tries `material_aliases` on the same terms `material_seconds`'s own
    closure does** - a material named in the wiki's vocabulary that
    `world.item_sources` (built off the export's `Output` strings) does not
    recognise under that spelling. Only once the literal name has failed, so
    a material the export does recognise is never routed through the alias
    table by mistake.
    """
    found = _item_hours(walk, item, quantity=quantity, amortise=amortise, trace=True)
    if found is None:
        aliased = material_aliases.get(item)
        if aliased is not None:
            found = _item_hours(
                walk, aliased, quantity=quantity, amortise=amortise, trace=True
            )
    return found


def material_walk(
    state: MapState,
    derived: Derived,
    world: WorldIndex,
    heuristics: Heuristics,
    *,
    level_overrides: dict[str, int] | None = None,
    made_experience: Mapping[str, tuple[str, float]] | None = None,
    recipes: Mapping[str, Sequence[Recipe]] | None = None,
) -> _Walk:
    """The `_Walk` a caller outside this module can price materials against -
    `material_seconds` and `training.trace_option` both build theirs from
    here, so the two can never disagree about reachability. Factored out of
    `material_seconds`'s own setup rather than duplicated by a second caller.
    """
    walk = _setup(state, derived, world, heuristics, level_overrides or {}, recipes).walk
    if made_experience:
        # Reset for the reason `material_seconds` resets after this same
        # replace: the experience credits ride on every `_Priced`, so a memo
        # filled under one table is wrong under another.
        walk = dataclasses.replace(
            walk, made_experience=made_experience, fixpoint=_Fixpoint(), leaf_routes={}
        )
    return walk


#: How many keys may be mid-evaluation at once. **A work bound, not a
#: semantic one**: it caps the recursion depth of a single derivation chain,
#: and a chain of sixty-four distinct recipes is beyond anything the corpus
#: holds - the longest real one measured is the nine-hop pie. Overflow reads
#: the belief, exactly as a cycle does, so a pathological corpus degrades to
#: an extra round rather than to a crash.
_MAX_ACTIVE = 64

#: How many promote-and-retry rounds a question may spend before its answer
#: is taken as-is. Positive costs make improvement monotone, so this is a
#: seatbelt; two rounds is the measured ceiling on all three maps.
_MAX_ROUNDS = 8


def _settle(walk: _Walk, key: tuple[str, float, bool, bool]) -> _Priced | None:
    """One key's answer this round: settled, believed, or evaluated now."""
    fixpoint = walk.fixpoint
    settled = fixpoint.settled
    if key in settled:
        return settled[key]
    if key in fixpoint.active or len(fixpoint.active) >= _MAX_ACTIVE:
        value = fixpoint.belief.get(key)
        fixpoint.reads.setdefault(key, value)
        if fixpoint.pending:
            fixpoint.pending[-1].add(key)
        return value
    fixpoint.active.add(key)
    fixpoint.pending.append(set())
    try:
        found = _best_route(
            walk, key[0], quantity=key[1], amortise=key[2], trace=key[3]
        )
    finally:
        fixpoint.active.discard(key)
        read_keys = fixpoint.pending.pop()
        if read_keys:
            fixpoint.readsets[key] = frozenset(read_keys)
            if fixpoint.pending:
                fixpoint.pending[-1] |= read_keys
    settled[key] = found
    return found


def _best_route(
    walk: _Walk,
    item: str,
    *,
    quantity: float,
    amortise: bool,
    trace: bool = False,
) -> _Priced | None:
    """`_item_hours` past the fixpoint table: try every route, keep the best.

    `item` arrives already resolved. Cycles need no handling here - a child
    evaluation that closes on an ancestor reads the belief inside `_settle`.
    """
    # **`[+]` means "or anything equivalent", so take the cheapest.** The
    # family is upstream's own list; picking the best of it is the same
    # reading `_required_kills` already takes for `monstersPlus`, which stops
    # at the first *reachable* member. Done before `resolve`, since the family
    # key is not an item name and will not resolve to one.
    members = walk.item_families.get(item)
    if members:
        cheapest: _Priced | None = None
        for member in members:
            if not isinstance(member, str):
                continue
            priced = _item_hours(
                walk, member, quantity=quantity, amortise=amortise, trace=trace
            )
            if priced is not None and (cheapest is None or priced.hours < cheapest.hours):
                cheapest = priced
        return cheapest

    # **Currency is earned, not fetched.** `Coins` and `Tokkul` are ordinary
    # items to the export - both have ground spawns - so the walk found one
    # lying about and priced ten million of them at nothing. What money costs
    # is the time to earn it, at its own rate, and that is true however you
    # come by it. Checked before the routes so no spawn can undercut it.
    earned = walk.heuristics.currency_per_hour.get(item)
    if earned is not None:
        if earned <= 0:
            return None
        return _Priced(
            quantity / earned,
            f"earn {quantity:,.0f} {item}",
            f"currency:{item}",
            (f"currencies/{item}",),
        )

    # **A raid reward is priced by the raid.** See `_Walk.raid_seconds`: the
    # export files these under a drop table and the walk would otherwise read
    # a raid as a monster killed 150 times an hour.
    raided = walk.raid_seconds.get(item.lower())
    if raided:
        # **Named by the run that earns it, not by "raid".** A fire cape is
        # sixty-three waves of the Fight Caves and nobody calls that a raid;
        # reading `raid: 1 Jal-nib-rek` on the Inferno's pet sent a reader
        # looking in `costing/raids.py`, which has never heard of it - and
        # `raids.activity_for` used to be the one missing entirely, so every
        # unique, cape and pet the three real raids actually price through
        # `raids.item_seconds` read the same way: `source="raids"`, no knob,
        # the identical problem this branch already existed to fix for
        # everything *except* the raids themselves. Checked first since it is
        # the common case; order does not otherwise matter; the five never
        # share an item.
        activity = (
            raids.activity_for(item)
            or tzhaar.activity_for(item)
            or colosseum.activity_for(item)
            or barrows.activity_for(item)
            or moons.activity_for(item)
            or gauntlet.activity_for(item)
        )
        # **Gauntlet items get the label but no knob.** `gauntlet.activity_for`
        # answers `"The Gauntlet"`, the activity name a reader would look
        # this up as - but the knob path needs the *place* key
        # (`"Gauntlet Lobby"`), and the two Hunllefs' durations differ, so
        # `instanced.knob_for(activity)` would resolve to nothing useful
        # here. `RUN_ONLY_PLACES` membership is the general test - true for
        # the three raids and for `tzhaar`/`colosseum`'s own activities,
        # false for Barrows and Perilous Moons (ordinarily-reachable content,
        # not a lobby-gated instance) and for the Gauntlet by exactly the
        # name mismatch above.
        knobbed = activity in instanced.RUN_ONLY_PLACES
        label = activity.lower() if activity else "raid"
        return _Priced(
            quantity * raided / 3600.0,
            f"{label}: {quantity:,.0f} {item}",
            activity or "raids",
            # **The knob is the run's own duration**, which is the number
            # actually behind this row. It briefly rode `actions/{name}` and
            # that was a lie in the panel - nothing named `Inferno` is in
            # `action_seconds`, so the stack resolved to the bare
            # `DEFAULT_ACTION_SECONDS` and offered an editable "2.4", the
            # generic four-tick seconds-per-action, beside a forty-minute run.
            # `runs/{place}` resolves, displays the model's own figure as its
            # default, and moves this row when edited.
            (instanced.knob_for(activity),) if activity and knobbed else (),
        )

    # **A herb is priced by its supply, not by a route.** See
    # `costing/herbs.py`: farming is gated on an eighty-minute grow and a
    # drop table is rolled for herbs rather than for one herb, so the cycle is
    # the unit. Checked here for the reason currency is - so no spawn or
    # cheap-looking drop can undercut the real cost.
    steeped = walk.herb_seconds.get(item)
    if steeped:
        return _Priced(
            quantity * steeped / 3600.0,
            f"herb supply: {quantity:,.0f} {item}",
            "herbs",
            ("actions/herbs",),
        )

    shared = _superior_table_hours(walk, item, quantity)
    if shared is not None:
        return shared

    # **The source loop, split by whether a route can recurse.** A `task:`
    # route walks its challenge's own `Items` and must be priced live, in this
    # context; everything else - a kill, a shop, a spawn - reads nothing from
    # `seen` or `depth`, so its best is computed once per question and reused
    # in every context, including the ones the subtree memo has to refuse.
    # The winner is still the first source reaching the minimal hours in
    # `item_sources` order, which is what the index tie-break preserves - a
    # tie between routes must not pick its winner by which cache answered.
    sources = walk.world.item_sources.get(item, ())
    tasks = walk.task_routes.get(item)
    if tasks is None:
        tasks = tuple(
            (at, source.route, source.name, challenge)
            for at, source in enumerate(sources)
            if source.route.startswith("task:")
            and isinstance(
                challenge := _mapping(
                    walk.chunk_info.challenges, source.route.removeprefix("task:")
                ).get(source.name),
                dict,
            )
        )
        walk.task_routes[item] = tasks
    key = (item, quantity, amortise)
    if key in walk.leaf_routes:
        held = walk.leaf_routes[key]
    else:
        # **Kill routes are arithmetic over hoisted facts; only free routes
        # and superiors run live.** See `_Walk.kill_facts`. The min is taken
        # over `(hours, position)` so a tie between a fact and a live route
        # still goes to whichever source `item_sources` lists first, exactly
        # as the single loop it replaces did.
        held = None
        parts = walk.kill_facts.get(item)
        if parts is None:
            parts = _kill_facts(walk, item, sources)
            walk.kill_facts[item] = parts
        facts, live = parts
        best_hours = math.inf
        best_at = -1
        won_fact: _KillFact | None = None
        won_master = ""
        for fact in facts:
            hours, master, _key = _fact_hours(fact, quantity, amortise)
            if hours < best_hours:
                best_hours, best_at = hours, fact.at
                won_fact, won_master = fact, master
        for at, route, provider in live:
            priced = _route_hours(walk, item, route, provider, quantity, amortise)
            if priced is not None and (
                priced.hours < best_hours
                or (priced.hours == best_hours and at < best_at)
            ):
                best_hours, best_at = priced.hours, at
                won_fact = None
                held = (priced, at)
        if won_fact is not None:
            held = (_fact_priced(won_fact, quantity, won_master, amortise), best_at)
        walk.leaf_routes[key] = held
    best: _Priced | None
    if held is not None:
        best, best_at = held
    else:
        best, best_at = None, -1
    for at, route, provider, challenge in tasks:
        priced = _route_hours(
            walk, item, route, provider, quantity, amortise,
            challenge=challenge, trace=trace,
        )
        if priced is not None and (
            best is None
            or priced.hours < best.hours
            or (priced.hours == best.hours and at < best_at)
        ):
            best, best_at = priced, at
    decanted = _dose_hours(walk, item, quantity, amortise)
    if decanted is not None and (best is None or decanted.hours < best.hours):
        best = decanted
    if best is None:
        best = _recipe_hours(walk, item, quantity, amortise, trace=trace)
    if best is None:
        # **A weight tier is priced by its yield** - see `costing/yields.py`,
        # and `_route_hours`' certainty gate for what this stands in for.
        #
        # **A fallback, for `_recipe_hours`' reason and one of its own.** It
        # must not displace a route: this prices 75 items and most of them -
        # `Coal`, `Logs`, `Bones` - are ordinary yields of some action *and*
        # have real routes of their own, which are what the walk should
        # spend. Checked last, nothing that already prices can change, and
        # what is left is exactly the members the certainty gate refused.
        yielded = walk.yield_seconds.get(item)
        if yielded:
            best = _Priced(
                quantity * yielded / 3600.0,
                f"yield: {quantity:,.0f} {item}",
                "yield",
                ("actions/yields",),
            )
    return best


@dataclass(frozen=True)
class ItemRoute:
    """One way to obtain an item, priced on its own - what `_best_route`
    takes the minimum of, kept rather than thrown away.

    `route` says which *kind* of thing `provider` is - `"kill"` (a monster,
    object or NPC's drop table), `"shop"`, `"spawn"`, `"make"` (a challenge
    that produces it), `"family"` (one member of a `[+]` "or anything
    equivalent" group), `"currency"`, `"herb"`, `"raid"`, `"superior"`,
    `"dose"` or `"recipe"`/`"yield"` (the two last-resort fallbacks) - so a
    caller can label a row without re-parsing `priced.source`, which was
    never written to be machine-read back apart.
    """

    route: str
    provider: str
    priced: _Priced


def item_routes(
    walk: _Walk, item: str, quantity: float = 1.0, amortise: bool = True
) -> tuple[ItemRoute, ...]:
    """Every way this map can obtain `item`, sorted fastest first.

    **The same candidates `_best_route` considers, none of them discarded.**
    That function exists to answer "what does the walk actually spend", and
    picks one; this exists to answer "what are my options", which is a
    different question asked by a person rather than by the estimate - the
    GUI's Find panel is the one caller. Deliberately *not* built by
    threading a collector through `_best_route` itself: that function's own
    per-walk caches (`leaf_routes`, `kill_facts`) are keyed and shaped for
    "the winner, remembered", and bending them to also remember every loser
    would slow down the one path that runs on every item in an estimate to
    speed up the one that runs once, on a click.

    A `[+]` family is expanded into one row per member rather than collapsed
    to the family's own cheapest, since "Bronze axe" and "Iron axe" are
    genuinely different things a reader might already own one of - the one
    place this deliberately answers a different question than `_best_route`
    would for the same item.

    **`amortise` defaults `True`, unlike every other caller of these
    routes.** A reader clicking "Show Sources" is asking how fast this map
    can *supply* the material, not how long until they see one for the
    first time - and those are different numbers whenever a drop hands over
    more than one at once. Revenant demons drop 8-16 Mahogany planks at
    1/58: the goal question (`amortise=False`, what `_best_route` asks for
    a task needing exactly one) answers "15.2 minutes", correctly, because
    that is the wait to see the *first* plank regardless of stack size - but
    it reads as the *source's speed*, and a reader comparing it against
    "Process mahogany logs" at 25.9s would conclude the Revenant route is
    sixty times slower than it is. The real long-run rate is one drop's
    kills divided by its mean stack, 4.8 kills per plank, ~75 seconds -
    still the make route's loser, just not by two orders of magnitude it
    never actually loses by. `quantity` stays `1.0`: a single unit is what
    the panel is pricing, `amortise` decides which question that unit asks.

    **`_recipe_hours`/`yield_seconds` keep `_best_route`'s own gate: tried
    only where nothing else priced at all.** They are not a second real
    option so much as a less specific description of one already found -
    `Mahogany plank`'s wiki recipe and the export's own `Process mahogany
    logs` challenge are the same sawmill trip, and showing both as though a
    reader could choose between them would be exactly the "unjoined method
    outranks its own charged twin" shape `costing/production.py`'s docstring
    warns about.
    """
    found: list[ItemRoute] = []

    members = walk.item_families.get(item)
    if members:
        for member in members:
            if not isinstance(member, str):
                continue
            priced = _item_hours(walk, member, quantity=quantity, amortise=amortise)
            if priced is not None:
                found.append(ItemRoute("family", member, priced))
        found.sort(key=lambda entry: entry.priced.hours)
        return tuple(found)

    earned = walk.heuristics.currency_per_hour.get(item)
    if earned is not None and earned > 0:
        found.append(
            ItemRoute(
                "currency",
                item,
                _Priced(
                    quantity / earned,
                    f"earn {quantity:,.0f} {item}",
                    f"currency:{item}",
                    (f"currencies/{item}",),
                ),
            )
        )

    raided = walk.raid_seconds.get(item.lower())
    if raided:
        activity = (
            raids.activity_for(item)
            or tzhaar.activity_for(item)
            or colosseum.activity_for(item)
            or barrows.activity_for(item)
            or moons.activity_for(item)
            or gauntlet.activity_for(item)
        )
        knobbed = activity in instanced.RUN_ONLY_PLACES
        label = activity.lower() if activity else "raid"
        found.append(
            ItemRoute(
                "raid",
                activity or "raids",
                _Priced(
                    quantity * raided / 3600.0,
                    f"{label}: {quantity:,.0f} {item}",
                    activity or "raids",
                    (instanced.knob_for(activity),) if activity and knobbed else (),
                ),
            )
        )

    steeped = walk.herb_seconds.get(item)
    if steeped:
        found.append(
            ItemRoute(
                "herb",
                "Herb patches",
                _Priced(
                    quantity * steeped / 3600.0,
                    f"herb supply: {quantity:,.0f} {item}",
                    "herbs",
                    ("actions/herbs",),
                ),
            )
        )

    shared = _superior_table_hours(walk, item, quantity)
    if shared is not None:
        found.append(ItemRoute("superior", shared.source, shared))

    for source in walk.world.item_sources.get(item, ()):
        route, provider = source.route, source.name
        if route in _FREE_ROUTES:
            priced = _route_hours(walk, item, route, provider, quantity, amortise)
            if priced is not None:
                found.append(ItemRoute(route, provider, priced))
        elif route.startswith("task:"):
            challenge = _mapping(
                walk.chunk_info.challenges, route.removeprefix("task:")
            ).get(provider)
            if isinstance(challenge, dict):
                priced = _route_hours(
                    walk, item, route, provider, quantity, amortise, challenge=challenge
                )
                if priced is not None:
                    found.append(ItemRoute("make", provider, priced))
        else:
            priced = _kill_hours(walk, provider, item, quantity, amortise)
            if priced is not None:
                found.append(ItemRoute("kill", provider, priced))

    decanted = _dose_hours(walk, item, quantity, amortise)
    if decanted is not None:
        found.append(ItemRoute("dose", item, decanted))

    # **Last resort, and only where nothing above priced at all** - the same
    # gate `_best_route` puts on both: a recipe or a flat yield describing
    # the same mechanic a real route already priced is not a second option,
    # it is the same mechanic from a less specific source. `Mahogany plank`
    # is the case that found this: the export's own `Process mahogany logs`
    # challenge already prices the sawmill, and the wiki's `{{Recipe}}` for
    # the same page describes the identical trip - showing both would read
    # as a choice between two actions where the game only has one.
    if not found:
        recipe = _recipe_hours(walk, item, quantity, amortise)
        if recipe is not None:
            found.append(ItemRoute("recipe", item, recipe))

    if not found:
        yielded = walk.yield_seconds.get(item)
        if yielded:
            found.append(
                ItemRoute(
                    "yield",
                    item,
                    _Priced(
                        quantity * yielded / 3600.0,
                        f"yield: {quantity:,.0f} {item}",
                        "yield",
                        ("actions/yields",),
                    ),
                )
            )

    found.sort(key=lambda entry: entry.priced.hours)
    return tuple(found)


@dataclass(frozen=True)
class MaterialStep:
    """One node of a production chain, recursively - a `_Priced` reshaped for
    a caller outside this module to read, since `_Priced` itself is private
    and its `label`/`children` are opt-in fields nothing but `trace=True`
    populates.

    `priced_candidate` is the only place these are built: the root's `label`
    is the item the reader asked about, and every `children` entry's `label`
    is the material name `_route_hours`/`_recipe_hours` stamped on it while
    building that step, one level up.
    """

    label: str
    hours: float
    detail: str
    source: str
    children: tuple["MaterialStep", ...] = ()


def _step_from_priced(priced: _Priced, label: str) -> MaterialStep:
    return MaterialStep(
        label=label,
        hours=priced.hours,
        detail=priced.detail,
        source=priced.source,
        children=tuple(
            _step_from_priced(child, child.label) for child in priced.children
        ),
    )


#: Which `ItemRoute.route` values are a production chain a drill-down can
#: walk into. A kill, a shop trip, a ground spawn, a herb supply, a raid
#: reward, a currency earn, a dose conversion and an `[+]` equivalent item are
#: all *obtained*, not *made from other items* - `item_routes` prices every
#: one of them as a leaf (`_Priced.children` is always `()`), so there is
#: nothing beneath one to drill into. Only `"make"` (a real export challenge)
#: and `"recipe"` (the wiki last resort) genuinely consume other items.
DRILLABLE_ROUTES = frozenset({"make", "recipe"})


def priced_candidate(
    walk: _Walk, item: str, route: str, provider: str, quantity: float = 1.0,
    amortise: bool = True,
) -> MaterialStep | None:
    """One `item_routes` candidate, re-priced with its own materials kept -
    the Find panel's drill-down side panel asks for exactly the production
    step a reader clicked, not `item_routes`' whole list of alternatives for
    `item`. `None` for a `route` not in `DRILLABLE_ROUTES`, or where the
    candidate no longer prices at all (the two are indistinguishable to a
    caller, which is fine: both mean "nothing to show").

    **Re-finds the candidate rather than being handed its challenge.** The
    Find panel only ever holds what `item_routes` returned - `route` and
    `provider`, not upstream's own category key, which `item_routes` already
    discarded when it relabelled every `task:*` source `"make"` for display.
    Searching `walk.world.item_sources` by `provider` recovers it, the same
    index `item_routes` itself built its list from.

    **Recurses through `children` for free.** Each material's own `_Priced`
    comes from the ordinary `_item_hours(..., trace=True)` call `_route_hours`
    and `_recipe_hours` already make - at whatever route *that* item's own
    walk judges cheapest, not by a second call back into this function. That
    is a deliberate difference from the root: a reader chose which of
    `item_routes`' rows to open, but a material three levels down is priced
    the way the estimator would price it, not re-offered as another choice.
    """
    if route == "make":
        for source in walk.world.item_sources.get(item, ()):
            if source.route.startswith("task:") and source.name == provider:
                challenge = _mapping(
                    walk.chunk_info.challenges, source.route.removeprefix("task:")
                ).get(provider)
                if isinstance(challenge, dict):
                    priced = _route_hours(
                        walk, item, source.route, provider, quantity, amortise,
                        challenge=challenge, trace=True,
                    )
                    return _step_from_priced(priced, item) if priced is not None else None
        return None
    if route == "recipe":
        priced = _recipe_hours(walk, item, quantity, amortise, trace=True)
        return _step_from_priced(priced, item) if priced is not None else None
    return None


def _recipe_hours(
    walk: _Walk,
    item: str,
    quantity: float,
    amortise: bool,
    trace: bool = False,
) -> _Priced | None:
    """Make `item` from a wiki recipe, when nothing else can provide it.

    **`trace` keeps this recipe's own materials, mirroring `_route_hours`'
    `task:` branch exactly** - the only other place a made item's `_Priced`
    carries `children`. Without it, a material whose cheapest route happens
    to be a last-resort recipe rather than a real export challenge would show
    up in a drill-down as a leaf despite genuinely having ingredients
    underneath it.

    **The last resort, and deliberately so.** The walk routes through the
    *export's* challenges, which is right: they carry this map's gates. But an
    intermediate the export has no challenge for is then unreachable however
    well the wiki documents it - and the export only lists what pays
    experience in the skill that owns the challenge. Chiselling a dark essence
    block into fragments pays **Crafting**, so there is no Runecraft challenge
    for it, and `Dark essence fragments` had no route at all on a map holding
    the Dark Altar. That cost the second cache its two best Runecraft methods:
    blood runes read 11,118/hr off pure essence when the same altar does
    31,316 off fragments, and soul runes were refused outright.

    Tried only when every other route has failed, so nothing that already
    prices can change. `output_quantity` is honoured - one chisel yields four
    fragments - and an untimed recipe falls back to `DEFAULT_ACTION_SECONDS`
    rather than being refused, because here the alternative is not a slower
    route but no route at all.

    **That default is the last word, not the first.** `_build_walk` applies the
    stated durations to the corpus before the walk ever sees it, so an action
    somebody has actually counted arrives timed: `chisel.CHISEL_TICKS` is zero
    for a dark essence block, which is chiselled on a run already being paid
    for, and `herblore.CLEAN_TICKS` is the bank cycle a grimy herb costs. What
    reaches `DEFAULT_ACTION_SECONDS` here is only what nothing has counted.
    """
    best: _Priced | None = None
    for recipe in walk.recipes.get(item.lower(), ()):
        made = max(recipe.output_quantity, 1.0)
        total = 0.0
        knobs: list[str] = []
        earned: list[tuple[str, float]] = []
        inputs: list[_Priced] = []
        failed = False
        for material in recipe.materials:
            priced = _item_hours(
                walk,
                material.name,
                quantity=quantity * material.quantity / made,
                amortise=amortise,
                trace=trace,
            )
            if priced is None:
                failed = True
                break
            total += priced.hours
            knobs.extend(priced.knobs)
            earned.extend(priced.experience)
            inputs.append(
                dataclasses.replace(priced, label=material.name) if trace else priced
            )
        if failed:
            continue
        ticks = recipe.ticks if recipe.ticks is not None else None
        seconds = 0.6 * ticks if ticks is not None else DEFAULT_ACTION_SECONDS
        total += seconds * quantity / made / 3600.0
        if recipe.experience > 0:
            earned.append((recipe.skill, recipe.experience * quantity / made))
        if best is None or total < best.hours:
            best = _Priced(
                total,
                f"make {item} from {recipe.page}",
                f"recipe:{recipe.output}",
                _unique(knobs),
                tuple(earned),
                tuple(inputs) if trace else (),
            )
    return best


#: A potion's dose, as the game and the wiki both write it: `Attack potion(3)`.
_DOSE = re.compile(r"^(?P<name>.+?)\((?P<dose>[1-4])\)$")

#: The doses a potion comes in.
_DOSES: tuple[int, ...] = (1, 2, 3, 4)


def _dose_hours(
    walk: _Walk,
    item: str,
    quantity: float,
    amortise: bool,
) -> _Priced | None:
    """Price `item` as doses of the same potion at another strength.

    **Doses are fungible and nothing else in the walk knew it.** There is no
    action in the game that *makes* a two-dose potion: you brew a three or a
    four and drink one, or decant. So `Attack potion(2)` had no route at all
    while `Attack potion(3)` priced in a second, and every method consuming a
    partial dose was dropped - 18 Herblore methods, which is why a published
    xp/hour survived on 26 of them.

    A dose is a dose, so `N` of them cost `N/M` of an `M`-dose potion, and the
    cheapest `M` wins as everywhere else here. A three asking a two asking a
    three closes on an active key and reads the belief, like every cycle.

    **Deliberately not a discount for the leftovers.** Buying a four to use
    two really does leave two behind, and a player would drink them - but
    counting that here would price a potion at less than its own doses and
    let the walk arbitrage strengths against each other.
    """
    found = _DOSE.match(item)
    if found is None:
        return None
    name, dose = found.group("name"), int(found.group("dose"))
    best: _Priced | None = None
    for other in _DOSES:
        if other == dose:
            continue
        candidate = f"{name}({other})"
        priced = _item_hours(
            walk, candidate, quantity=quantity * dose / other, amortise=amortise
        )
        if priced is not None and (best is None or priced.hours < best.hours):
            best = _Priced(
                priced.hours,
                f"{dose} of {other} doses: {priced.detail}",
                priced.source,
                priced.knobs,
                priced.experience,
            )
    return best


def _superior_table_hours(
    walk: _Walk, item: str, quantity: float = 1.0
) -> _Priced | None:
    """Price one of the four items every superior shares, or `None`.

    **Superiors are one source, not thirty-one.** The table is rolled by any
    superior, and you never hunt a particular one - you take a master's
    assignments and whatever supers turn up, turn up. So the rate is the
    master's *aggregate*: Krystilia's abyssal demons, jellies and nechryaels
    all feed the same pool. Pricing this against a single base monster asks
    which superior you are farming, which is not a question the game poses.

    Per master, because you serve one at a time - combining two masters'
    pools would describe nobody's game. The best of them wins, as everywhere
    else here.
    """
    share = walk.superior_table.get(item)
    if not share:
        return None

    best: tuple[float, str] | None = None
    for master, rolls in walk.superior_rolls.items():
        if rolls <= 0:
            continue
        hours = (max(1.0, quantity) / share) / rolls
        if best is None or hours < best[0]:
            best = (hours, master)
    if best is None:
        return None

    hours, master = best
    return _Priced(
        hours,
        f"superior table under {master},"
        f" {max(1.0, quantity) / share:,.1f} rolls at {_rolls_label(walk, master)}",
        f"superiors:{master}",
        # A *branch*, not a leaf: the roll rate is computed from the master's
        # whole assignment table rather than read off one entry, so naming a
        # single task would point at the wrong knob.
        (f"slayer/{master}",),
    )


def _rolls_label(walk: _Walk, master: str) -> str:
    """How often the *shared table* comes up - far rarer than a superior."""
    rolls = walk.superior_rolls.get(master, 0.0)
    return f"1 table roll per {1 / rolls:,.0f}h" if rolls > 0 else "no supers"


#: What an item pack holds. **Stated on every pack's own page** - "A pack
#: containing 100 feathers", "...100 pieces of soft clay", "...100 empty
#: buckets" - and it is 100 on all twenty-three the export carries, which is
#: why this is a constant rather than a table.
PACK_UNITS = 100.0

#: The suffix upstream gives the pack itself. The conversion challenge states
#: `Items: ["<X> pack*"]` and an `Output` of the bare item, which is the shape
#: `_pack_units` recognises.
_PACK_SUFFIX = " pack"


def _pack_units(challenge: Mapping[str, Any]) -> float:
    """`PACK_UNITS` where this challenge opens an item pack, else `1.0`.

    **Only where the output is a plain item.** Six `Open a ... pack*`
    challenges name a loot *table* instead (`Herb pack loot`, `Seed pack
    loot`); those are rolls rather than a hundred of one thing, and
    `_route_hours`' certainty gate already handles them.
    """
    made = challenge.get("Output")
    if not isinstance(made, str) or made.endswith(" loot"):
        return 1.0
    for item in challenge.get("Items") or ():
        if isinstance(item, str) and item.replace("*", "").strip().lower().endswith(
            _PACK_SUFFIX
        ):
            return PACK_UNITS
    return 1.0


def _route_hours(
    walk: _Walk,
    item: str,
    route: str,
    provider: str,
    quantity: float = 1.0,
    amortise: bool = False,
    challenge: dict[str, Any] | None = None,
    trace: bool = False,
) -> _Priced | None:
    if route in _FREE_ROUTES:
        # **A shop is only free if you can walk into it.** `WorldIndex` spans
        # the whole world, so without this any item stocked by any of the
        # export's 435 shops - or lying on the ground anywhere - priced at zero
        # and won the `min` outright. Every *kill* route was already hard-gated
        # on reachability (`_kill_hours`: "availability is not negotiable"), so
        # this was the one route that could reach off the map.
        #
        # It barely moved the item bucket - 4 of 207 items on the real map -
        # but it is decisive for anything priced *per action*: eye of newt,
        # grimy guam leaf and snapdragon are all stocked or spawned somewhere,
        # so an ingredient walk without this gate concludes that every recipe's
        # inputs are instant.
        if item.lower() not in walk.reachable_lower:
            return None
        if route == "spawn":
            # **A ground spawn is cheap, not free.** Picking one up is a tick,
            # which alone caps collection at 6,000 an hour - and the item does
            # not come back while you stand there, so the real limit is how
            # fast you can reach a fresh one. Hopping worlds is the usual
            # answer at `WORLD_HOP_SECONDS` a hop, and each hop yields however
            # many of the item lie at that spawn.
            #
            # Left free, a `Spawn` of two planks priced a ten-plank wooden
            # fence at nothing and made it 296,471 Construction xp/hr.
            #
            # **The item-level gate above is not enough for a spawn.**
            # `reachable_lower` only says the item exists somewhere reachable
            # on this map - true the moment *any* route to it is, which said
            # nothing about *this* spawn's own chunk. See `_location_reachable`.
            if not _location_reachable(walk, provider):
                return None
            at_spawn = _spawn_block(walk.chunk_info, provider).get(item)
            count = float(at_spawn) if isinstance(at_spawn, (int, float)) else 1.0
            per_hour = min(
                3600.0 / SPAWN_PICKUP_SECONDS, SPAWN_HOPS_PER_HOUR * max(1.0, count)
            )
            hours = quantity / per_hour if per_hour > 0 else 0.0
            return _Priced(
                hours,
                f"{route}: {provider}"
                + (f", {quantity:,.0f}x" if quantity > 1 else "")
                + f" ({count:g} per hop, {per_hour:,.0f}/hr)",
                f"{route}:{provider}",
            )

        # **Buying is instant; the money is not.** A shop route costs however
        # long it takes to earn the price, at the currency's own rate - which
        # is what stops a Construction build reading `Coins x 10,000,000` from
        # being the fastest training in the game. A price the wiki does not
        # list, or one charged in a currency with no rate, is *no route* rather
        # than a free one.
        seconds = walk.heuristics.shop_seconds(provider, item)
        if seconds is None:
            return None
        # **The item-level gate above is not enough for a shop either** - the
        # same gap `_location_reachable` closed for spawns. TzHaar-Hur-Rin's
        # Ore and Gem Store priced an uncut ruby as cheap and plentiful on a
        # map that had never opened the chunk it actually stands in, because
        # `reachable_lower` only asks whether an uncut ruby exists reachable
        # *somewhere* - true regardless, once the spawn fix above stopped
        # masking it. See `_shop_reachable`.
        if not _shop_reachable(walk, provider):
            return None
        stock, restock_seconds = walk.heuristics.shop_limits(provider, item)
        # **A restock this slow is a contested resource, not a rate.** Six
        # hours split across roughly two hundred worlds, competing with
        # everyone else on them, is not something this project can turn into
        # a number it would stand behind - so past `SHOP_RESTOCK_CUTOFF_SECONDS`
        # this is refused outright, the same call `costing/trawler.py` makes
        # for the net repair's uncharted success chance. Toci's Gem Store's
        # uncut ruby (6h) and emerald (4h) both fall here; its sapphire (2h)
        # does too - a gem store is exactly the "extremely competitive" shape
        # this exists for, not a loophole around it.
        if restock_seconds is not None and restock_seconds > SHOP_RESTOCK_CUTOFF_SECONDS:
            return None
        # **Zero in stock is not "the wiki forgot to say"; the module states
        # it explicitly** - a line a shop only ever refills from players
        # selling in, so there is no route to buying the first one.
        if stock is not None and stock <= 0:
            return None
        # **The money is not the only cost; the walk there is, and so is the
        # shelf running out.** A shop run brings back one inventory, so buying
        # is priced per *trip* as well as per coin - and where the shop's own
        # stock is below what a trip wants, filling it costs a world hop per
        # extra visit on top of that, at `WORLD_HOP_SECONDS` each
        # (`_shop_hop_seconds`). `amortise` is the difference between the two
        # questions the walk is asked: a goal wants one item and pays for the
        # whole trip, while a recipe wants two planks *per action* and pays
        # its share of a trip that also supplied the next dozen actions.
        # Charging a full trip per action put thirty seconds on every cast of
        # every spell - `_shop_hop_seconds` follows the same amortise split so
        # a scarce material does not do the same thing to hops.
        trips = quantity / SHOP_TRIP_ITEMS
        if not amortise:
            trips = max(1.0, math.ceil(trips))
        travel = trips * SHOP_TRIP_SECONDS
        hops = _shop_hop_seconds(quantity, stock, amortise)
        hours = (seconds * quantity + travel + hops) / 3600.0
        detail = (
            f"{route}: {provider}"
            + (f", {quantity:,.0f}x" if quantity > 1 else "")
            + f" ({seconds * quantity:,.0f}s earning + {travel:,.0f}s travel"
            + (f" + {hops:,.0f}s hops" if hops > 0 else "")
            + ")"
        )
        return _Priced(
            hours,
            detail,
            f"{route}:{provider}",
            (f"shops/{provider}/{item}",),
        )

    if route.startswith("task:"):
        # Made rather than found: the cost is its inputs, recursively. The
        # challenge normally rides in from `_best_route`'s per-item cache;
        # the lookup below only serves a direct caller.
        if challenge is None:
            found = _mapping(
                walk.chunk_info.challenges, route.removeprefix("task:")
            ).get(provider)
            if not isinstance(found, dict):
                return None
            challenge = found
        # **A challenge's `Output` is often a table rather than the item.** 223
        # of them are: `Catch a ~|raw swordfish|~` yields `Raw swordfish loot`,
        # `{"Raw swordfish": "Always", "Big swordfish": "1/2500"}`. So doing it
        # once does not hand over one of whatever you asked for, and the number
        # of performances is `quantity / chance` - the same arithmetic
        # `_kill_hours` does for a monster, read off the same `_drop_rates`.
        #
        # **`chance`, not the expected yield**, when the walk wants one of
        # something: obtaining an item at all is one roll of the table however
        # big the stack. `amortise` is the accumulating question and takes the
        # yield, exactly as a kill does.
        #
        # **Only where the item is certain**, which is the same gate an
        # activity's own route is under and refused for the same reason. The
        # time to *perform* a challenge is `DEFAULT_ACTION_SECONDS` where
        # nothing states it - a default, and multiplying a defaulted pace by a
        # real drop chance is precisely the mistake `combat_xp.best_target`
        # refuses. At `Always` there is no multiplication to get wrong: the
        # action hands the thing over, and four ticks for a fishing action is a
        # fair stand-in. So `Raw swordfish` prices and the `Big swordfish`
        # beside it at 1/2500 does not, until someone states a rate for the
        # fishing spot - at which point the activity route prices it properly.
        made = challenge.get("Output")
        # **A monster named beside a *different* output is a kill for a drop**,
        # and a kill is not a four-tick action. This is the same argument the
        # branch below makes for `Output != item` - "a kill has a route of its
        # own (`_kill_hours`, with the gear and the gates), so refusing here
        # loses nothing" - which had simply never been applied when the output
        # *is* the item asked for.
        #
        # What it was costing: `Cut magic logs from an ~|ent|~` names
        # `Monsters: ["Ent"]` and outputs `Magic logs`, so magic logs priced at
        # 3.6 seconds against 25.6 for chopping one - the same 3.6 as an oak
        # log, because the default knows nothing about either. An ent is a
        # Forestry event, not something available every four ticks.
        #
        # **`item not in monsters` is what keeps the slayer tokens**, where the
        # output *is* the monster (`Slay a ~|bloodveld|~` -> `Bloodveld`).
        #
        # **Unless a `*`-marked `Items` entry names the real cost.** `*` is
        # upstream's own consumed-secondary marker (`challenges._is_secondary`'s
        # docstring: "An unmarked entry - a tool, an `Axe[+]` - can never set
        # it"), so an ent's `Axe[+]` is a tool this gate is still right to
        # distrust, but `Chest (Bryophyta's lair)*`'s `Mossy key*` is not: it is
        # consumed once per opening, and the item walk already knows the
        # cheapest way to get one (Bryophyta at 1/16, a Moss giant at 1/150).
        #
        # **Two different wrongs, fixed by the same exception.** Yama's five
        # sigil offerings (`Contract of <X>*`) and two Nightmare/vampyre loot
        # tables have no other route in the export at all, so refusing them
        # left them honestly `unpriced` - this reclaims a real price for
        # them. `Chest (Bryophyta's lair)*` and `Chest (Obor's lair)*`
        # (`Giant key*`) are the sharper case: refusing *this* route did not
        # leave them unpriced, because both chests are also `skillItems`
        # activities read as an ordinary monster elsewhere in the walk, and
        # `Heuristics.kills_per_hour` had never heard of either - so they
        # priced anyway, at `DEFAULT_KPH["regular"]`, 150 an hour, which is
        # the wrong number this exception was written to stop being the only
        # one available. `keyed_chests.py` is the other half of that fix: it
        # corrects the *skillItems* route's rate for both chests, which this
        # gate does not reach.
        #
        # Measured over the whole export, the plain form refuses 17 routes and
        # 12 of them were already priced above 250 seconds by their inputs;
        # what moves there is the five ent challenges, which fall back to
        # chopping. This exception reclaims 11 further routes that the plain
        # form refused *despite* naming a real consumed ingredient - the two
        # chests, Yama's five sigils, and two Nightmare/vampyre loot tables.
        monsters = challenge.get("Monsters") or ()
        consumed = any(
            isinstance(ref, str) and "*" in ref for ref in challenge.get("Items") or ()
        )
        if (
            isinstance(made, str)
            and made == item
            and monsters
            and item not in monsters
            and not consumed
            and provider not in walk.heuristics.action_seconds
        ):
            return None
        # **A minigame's byproduct fish is not a fishing spot's fish.** `Catch
        # a ~|raw manta ray|~` (`Category: Minigame`, `Objects: ["Trawler
        # boat"]`, `Primary: False`) names no monster, so the gate above never
        # saw it, and `made == item` here is `Always`-certain the way an
        # ordinary catch is - so it fell to `DEFAULT_ACTION_SECONDS` and read
        # as a plain four-tick fishing action. It is not one: the actual
        # mechanic is a shared-table minigame roll nothing in
        # `heuristics/wiki_rates.json` or `costing/gathering.py` states a pace
        # for, because both were built to answer for the skill's *training*
        # methods and this is not one (`Primary` is `False`). Priced anyway,
        # `Cook a ~|manta ray|~` read 229,024/hr - the whole climb's best
        # Cooking method - on a "catch" costing 2.4s, the same pace as
        # standing at an ordinary spot with a rod.
        #
        # **Scoped to the five skills the claim was ever made for.** A
        # Construction or Firemaking byproduct with no stated pace still gets
        # the plain default below; this gate only pulls back the one sentence
        # ("four ticks for a fishing action is a fair stand-in") that was
        # never a claim about Mining, Woodcutting, Hunter or Thieving byproduct
        # tasks either - the Sorceress's Garden sq'irk juices and the Forestry
        # `~|clothes pouch|~`/`~|secateurs attachment|~` alts are the same
        # shape again, caught by the same skill set.
        skill = route.removeprefix("task:")
        if (
            isinstance(made, str)
            and made == item
            and skill in _UNGUIDED_GATHERING_SKILLS
            and challenge.get("Primary") is not True
            and provider not in walk.heuristics.action_seconds
        ):
            return None
        if isinstance(made, str) and made != item:
            # **And only where the pace is stated rather than defaulted.**
            # `Slay the ~|Alchemical Hydra|~ alt` outputs a table holding
            # `Hydra bones` at `Always`, so the certainty gate above passes it
            # - and killing the Alchemical Hydra is not a four-tick action.
            # Priced at `DEFAULT_ACTION_SECONDS` it put Prayer at 11.3h off
            # 1,155,000 xp/hr of hydra bones. A kill has a route of its own
            # (`_kill_hours`, with the gear and the gates), so refusing here
            # loses nothing; what this route is for is the *action* challenges
            # whose pace a guide's `kph` actually states - `Catch a ~|raw
            # swordfish|~` at 18.5s, `Catch a ~|raw shark|~` at 7.5s.
            if provider not in walk.heuristics.action_seconds:
                return None
            rates = _drop_rates(walk, made, item)
            if rates is None or rates[0] < 1.0:
                # **Opening this to an uncertain share was tried twice and
                # reverted twice**, and the second time is the instructive
                # one. It is not the *number* of items: gated to the eight
                # whose share clears `yields.ORDINARY_SHARE`, `fray-uber`
                # still failed to price in three minutes. The cost is that
                # `quantity / share` is fractional and near-unique, so every
                # downstream `(item, quantity, amortise)` key is distinct and
                # the fixpoint memo never hits - Prayer's bone walk alone
                # reached 2.5M `_item_hours` calls. An ordinary yield is
                # priced as a flat per-item cost instead, before the routes
                # and beside a herb: see `_Walk.yield_seconds`.
                return None
            share = rates[1] if amortise else rates[0]
            if share <= 0:
                return None
            quantity = quantity / share
        # **An item pack is a hundred of the thing and upstream models it as
        # one.** Every `<X> pack` challenge in the export states `Items: ["<X>
        # pack*"]` and an `Output` of the bare item, so the walk charged a
        # whole pack for one crystal, one feather, one bucket - a hundred
        # times the truth. The count is not a guess: each pack's own examine
        # text states it ("A pack containing 100 feathers"), and it is 100 on
        # every one of the twenty-three the export carries.
        #
        # Divided into the quantity rather than out of the total, which is the
        # same arithmetic and matches the `share` line above. It is safe from
        # the fractional-key problem `_route_hours`' certainty gate warns
        # about because a pack is *bought*: one shop hop and no chain behind
        # it, so the fixpoint memo never sees the fraction twice.
        units = _pack_units(challenge)
        if units > 1:
            quantity = quantity / units
        total = 0.0
        inputs: list[_Priced] = []
        knobs: list[str] = [f"actions/{provider}"]
        for required in challenge.get("Items") or ():
            if not isinstance(required, str):
                continue
            wanted = required.replace("*", "")
            priced = _item_hours(
                walk, wanted, quantity=quantity, amortise=amortise, trace=trace
            )
            if priced is None:
                return None
            total += priced.hours
            # **Labelled here, not on the way out.** `wanted` is this loop's
            # own variable - the one place that knows which material a given
            # `_Priced` answers for - so a trace's child is stamped with it
            # before it joins `inputs`, the list `children` becomes below.
            inputs.append(dataclasses.replace(priced, label=wanted) if trace else priced)
            # **A made thing is its inputs, so it is their knobs too.** The
            # whip in a recipe is the whip's kill rate; correcting that is
            # what moves this number, and pointing only at the recipe would
            # send you to the one entry that is already right.
            knobs.extend(priced.knobs)
        # **The conversion itself can cost money.** Upstream models the
        # sawmill as a swap of logs for planks and records no price, so a
        # mahogany plank came out costing exactly one mahogany log. The fee is
        # `remote/stores.py`'s and is zero for every conversion that has none.
        # **And performing it costs time.** A guide's `kph` or a recipe's tick
        # cost where either is known, and four ticks where neither is.
        total += (
            walk.heuristics.action_seconds.get(provider, DEFAULT_ACTION_SECONDS)
            * quantity
            / 3600.0
        )
        made = challenge.get("Output")
        if isinstance(made, str):
            fee = walk.heuristics.conversion_seconds(made) * quantity / 3600.0
            if not math.isfinite(fee):
                return None
            total += fee
        # **One action can yield several of what it makes, and the division
        # belongs here rather than on `quantity`.** A herb patch returns ~8.8
        # herbs for the one seed planted. Dividing the quantity going *in* does
        # not work: `_kill_hours` floors a drop at `1/chance` kills - you
        # cannot see a ranarr seed in fewer, however little of one you want -
        # so the seed stayed at its full 163s and only the tools scaled. The
        # whole action costs what it costs and hands back `yielded` of the
        # output, so the per-item cost is the total over the yield. Absent
        # means one, which is every other challenge in the export.
        # **A made item can be a single real grind wearing a recipe**, and
        # stamping every route `f"make:{provider}"` regardless hid that from
        # the same-source clamp `EstimateResult.buckets` relies on: `Imbue a
        # ~|granite ring|~ at Dom Onion's Reward Shop` needs nothing beyond a
        # `Granite ring` and a shop trip, so its entire cost *is* Grotesque
        # Guardians' own grind - yet on the real `fray` map the ring priced
        # once at 78.85 hours under `Grotesque Guardians` and the imbue
        # priced the same 78.85 hours again under its own one-off heading,
        # doubling a chunk of the estimate that was never two grinds.
        #
        # **Only when one real source explains (effectively) the whole
        # cost.** A multi-material recipe drawing from two different real
        # sources is genuinely sequential - you cannot grind two bosses at
        # once, so summing them stays correct - and a `make:` chain (a bar
        # smelted before being smithed) is excluded by the `"make:"` prefix
        # test: propagating through an intermediate would misattribute a
        # further processing step's own time to whatever fed *it*, the same
        # failure shape as crediting a slow crafting action to a cheap
        # material. `_DOMINANT_MATERIAL_SHARE` is what keeps that case out:
        # it passes a route like the ring's, whose only other cost is a
        # thirty-second shop trip against 78.85 hours, and refuses one where
        # the *action* - not the material - is the real cost.
        dominant_source = ""
        if inputs and total > 0:
            heaviest = max(inputs, key=lambda priced: priced.hours)
            if (
                heaviest.source
                and not heaviest.source.startswith("make:")
                and heaviest.hours / total >= _DOMINANT_MATERIAL_SHARE
            ):
                dominant_source = heaviest.source
        yielded = walk.heuristics.harvest_yield.get(provider, 1.0)
        if yielded > 1.0:
            total /= yielded
        # **What performing this paid, on top of what the inputs paid.**
        # Scaled by the same `quantity` and divided by the same yield as the
        # cost above, so the two halves describe one action.
        earned: list[tuple[str, float]] = []
        made_by = walk.made_experience.get(provider)
        if made_by is not None:
            earned.append((made_by[0], made_by[1] * quantity / yielded))
        for priced in inputs:
            earned.extend(priced.experience)
        return _Priced(
            total,
            # **No "make: " prefix.** `provider` is already a full sentence
            # ("Imbue a granite ring at Dom Onion's Reward shop"), unlike the
            # bare noun phrases the other routes' `detail` strings prefix
            # with their own verb ("earn: 500,000 Coins") - prepending one
            # here only restated what the sentence already said.
            provider,
            dominant_source or f"make:{provider}",
            _unique(knobs),
            tuple(earned),
            tuple(inputs) if trace else (),
        )

    return _kill_hours(walk, provider, item, quantity, amortise)


class _KillFact:
    """One kill route's quantity-independent half - see `_Walk.kill_facts`."""

    __slots__ = ("at", "provider", "chance", "per_kill", "kph", "task", "masters")

    def __init__(
        self,
        at: int,
        provider: str,
        chance: float,
        per_kill: float,
        kph: float,
        task: str | None,
        masters: tuple[tuple[float, float, str, str], ...],
    ) -> None:
        self.at = at
        self.provider = provider
        self.chance = chance
        self.per_kill = per_kill
        self.kph = kph
        #: The slayer task gating the monster, or `None` for a walk-up kill.
        self.task = task
        #: `(wait hours, assignment count, master)` per master that can
        #: assign it - `hours_to_be_assigned` hoisted, since the wait walks
        #: the master's whole table and depends on nothing but the task.
        self.masters = masters


def _provider_kills_per_hour(walk: _Walk, provider: str) -> Rate:
    """`Heuristics.kills_per_hour(provider)`, unless `provider` names a whole
    raid or instance rather than a monster within one.

    **A `skillItems` table can be keyed by the run itself.** `Theatre of
    Blood`'s own `Sanguine dust`/`Sanguine ornament kit` sit in a
    `skillItems.Nonskill` table named "Theatre of Blood" - the same string as
    the *object* you walk up to and click in Ver Sinhaza to start a raid, so
    `walk.available` correctly allows it (you genuinely can reach that
    object) and this project's generic "provider" machinery then asked
    `kills_per_hour("Theatre of Blood")` as if the raid itself were a monster
    to farm. Nothing scrapes a kills-per-hour for a raid's own name, so that
    read as `DEFAULT_KPH`'s 150 an hour - the exact bug `raids.item_seconds`
    already exists to keep out of `Long bone`/`Sanguine dust`'s siblings that
    *are* covered by it, reappearing for the ones that are not.

    **A hand override still wins.** Only substituted when
    `Heuristics.kills_per_hour` would otherwise answer from `DEFAULT_KPH` -
    an explicit `monsters/<place>` correction (or a real future scrape under
    that exact name) is not this function's to second-guess.
    """
    rate = walk.heuristics.kills_per_hour(provider)
    if not rate.source.startswith("default") or provider not in instanced.RUN_ONLY_PLACES:
        return rate
    run = instanced.run_seconds(provider, walk.heuristics.run_seconds)
    if not run:
        return rate
    return Rate(3600.0 / run, source=f"runs:{provider}", match="modelled")


def _provider_knob(provider: str) -> str:
    """The knob path a provider's rate is corrected through.

    **`runs/<place>`, not `monsters/<place>`, for a `RUN_ONLY_PLACES`
    member** - matching `instanced.knob_for` and the raid-drop branch in
    `_best_route`. A hand correction belongs on the number this project
    actually spent, and for a raid/instance that is its own run duration,
    not a kills-per-hour nothing here computes from it any more.
    """
    return instanced.knob_for(provider) if provider in instanced.RUN_ONLY_PLACES else f"monsters/{provider}"


def _kill_facts(
    walk: _Walk, item: str, sources: Sequence[Any]
) -> tuple[tuple[_KillFact, ...], tuple[tuple[int, str, str], ...]]:
    """Split an item's leaf sources into kill facts and live-call leaves.

    A source that can never price - unreachable, no drop rate, no kill rate,
    gated on a task no master can assign - is dropped here once instead of
    being refused per quantity, which is the same answer `_kill_hours` gives
    it and none of the work.
    """
    facts: list[_KillFact] = []
    live: list[tuple[int, str, str]] = []
    waits: dict[TaskGate, tuple[tuple[float, float, str, str], ...]] = {}
    for at, source in enumerate(sources):
        route, provider = source.route, source.name
        if route.startswith("task:"):
            continue
        if route in _FREE_ROUTES:
            live.append((at, route, provider))
            continue
        if provider not in walk.available:
            if walk.heuristics.superiors.get(provider):
                # Superiors recurse into their base monster and stay live.
                live.append((at, route, provider))
            continue
        rates = _drop_rates(walk, provider, item)
        if rates is None or rates[0] <= 0 or rates[1] <= 0:
            continue
        rate = _provider_kills_per_hour(walk, provider)
        if rate.value <= 0:
            continue
        gate = walk.task_gates.get(provider)
        masters: tuple[tuple[float, float, str, str], ...] = ()
        task = None if gate is None else gate.task
        if gate is not None:
            # **Memoised on the gate, place included.** Two monsters gated on
            # the same task at different places are different waits at a
            # master who assigns by location, so keying on the bare task would
            # hand one of them the other's answer.
            if gate not in waits:
                found: list[tuple[float, float, str, str]] = []
                for master in walk.masters:
                    key = master.key_for(gate)
                    if key is None:
                        continue
                    # Same override `_task_hours` reads - see its own
                    # comment. Duplicated here rather than shared because
                    # this is the hoisted, hot-path twin of that function,
                    # and the two must keep computing the same answer.
                    override = (walk.heuristics.wait_hours.get(master.master) or {}).get(key)
                    wait = override if override is not None else master.hours_to_be_assigned(key)
                    sized = (walk.heuristics.slayer.get(master.master) or {}).get(key)
                    if wait is None or sized is None or sized.count <= 0:
                        continue
                    # **The master's own key travels with it.** It is what
                    # the `wait/<master>/<task>` knob has to name, and the
                    # gate's bare `Hydras` resolves to nothing in a
                    # location-keyed master's config - a dead dial in the
                    # panel, which is the bug this whole join started as.
                    found.append((wait, sized.count, master.master, key))
                waits[gate] = tuple(found)
            masters = waits[gate]
            if not masters:
                # `_task_hours` would answer `None` at every quantity.
                continue
        facts.append(
            _KillFact(at, provider, rates[0], rates[1], rate.value, task, masters)
        )
    return tuple(facts), tuple(live)


def _fact_hours(
    fact: _KillFact, quantity: float, amortise: bool = False
) -> tuple[float, str, str]:
    """A fact's hours at `quantity`, and the winning master where gated.

    **The hot half**: pure arithmetic, no strings, no allocation - it runs
    once per fact per question and almost every result loses the min. The
    operations reproduce `_kill_hours`' exactly, floats and all, so a tie
    against a live route resolves the same way it always did - `amortise`
    included, since a fact this misses is a fact `_best_route` would then
    lose to whatever `_route_hours`' own, correctly-amortised call to
    `_kill_hours` computed for a *live* route, the same shape of bug the
    Find panel's drill-down surfaced: `Diamond amulet`'s cheapest real route
    is a Magpie impling at 1/21 with a 3-drop stack, amortised to 168s, but
    an unamortised fact read 504s and lost to a 395s recipe chain that was
    never actually the fastest thing on the map.
    """
    kills = quantity / fact.per_kill if amortise else max(1 / fact.chance, quantity / fact.per_kill)
    if fact.task is None:
        return kills / fact.kph, "", ""
    hours = math.inf
    won = ""
    key = ""
    for wait, count, master, task in fact.masters:
        assignments = max(1.0, kills / count)
        candidate = assignments * (wait + count / fact.kph)
        if candidate < hours:
            hours, won, key = candidate, master, task
    return hours, won, key


def _fact_priced(
    fact: _KillFact, quantity: float, master: str, amortise: bool = False
) -> _Priced:
    """The winner's `_Priced`, strings and knobs exactly as `_kill_hours`
    builds them - only ever called for the route that won the min."""
    kills = quantity / fact.per_kill if amortise else max(1 / fact.chance, quantity / fact.per_kill)
    detail = f"{fact.provider} at 1/{1 / fact.chance:,.0f}, {fact.kph:g}/hr"
    if amortise and fact.per_kill > fact.chance:
        detail = f"{fact.provider}: {fact.per_kill / fact.chance:,.1f}/drop at 1/{1 / fact.chance:,.0f}, {fact.kph:g}/hr"
    elif kills > 1 / fact.chance:
        detail = f"{fact.provider} x{kills:,.0f} kills, {fact.kph:g}/hr"
    if fact.task is None:
        return _Priced(
            kills / fact.kph, detail, fact.provider, (_provider_knob(fact.provider),)
        )
    hours, _, key = _fact_hours(fact, quantity, amortise)
    # **The winning master's own key, not the gate's name** - see
    # `slayer.MasterRate.key_for`. `Konar quo Maten` keys by location, so
    # `wait/Konar quo Maten/Hydras` names nothing and the dialog it opens
    # would have no value to show.
    return _Priced(
        hours,
        f"{detail} on {key} task",
        fact.provider,
        (_provider_knob(fact.provider), f"wait/{master}/{key}"),
    )


def _kill_hours(
    walk: _Walk, provider: str, item: str, quantity: float = 1.0,
    amortise: bool = False,
) -> _Priced | None:
    """Hours of killing `provider` for `quantity` of `item`, gates included.

    **Availability is checked first and is not negotiable.** `provider` has to
    be a monster this map can actually reach - placed in an unlocked chunk and
    past its `taskUnlocks` gates. Without that the walk prices the whole game:
    `Colossal Hydra` is a `skillItems.Slayer` activity with 43 drops and no
    chunk anywhere (it is a superior, spawned from Alchemical Hydra), and it
    was being costed as though you could go and fight one.

    **`amortise` picks which of two questions `quantity` is answering.** A
    goal (`amortise=False`, the default) wants to know when the drop will
    first appear at all - `1/chance` kills, whatever the stack turns out to
    be, since a whip is a whip whether the table hands over one or three.
    `amortise=True` wants the long-run *rate*, which a stacked drop changes:
    Revenant demons hand over 8-16 Mahogany planks at once, so the real
    average is one drop's worth of kills divided by its mean stack, not the
    time to merely see the first one. Skipping the `1/chance` floor is what
    does that - see `item_routes`, the caller this exists for, whose reader
    is comparing *sources* of a material rather than asking for exactly one.
    """
    if provider not in walk.available:
        superior = walk.heuristics.superiors.get(provider)
        return (
            _superior_hours(walk, superior, item, quantity, amortise)
            if superior else None
        )

    rates = _drop_rates(walk, provider, item)
    if rates is None or rates[0] <= 0 or rates[1] <= 0:
        return None
    chance, per_kill = rates
    rate = _provider_kills_per_hour(walk, provider)
    if rate.value <= 0:
        return None

    # **Both bounds, and the binding one wins - unless `amortise` says there
    # is only one.** You cannot see the drop in fewer than `1/chance` kills
    # however large the stack, and once you want more than one stack it is
    # `quantity/yield`. At `quantity == 1` the first always binds, which is
    # what keeps a goal priced on the rate alone; `amortise` drops that floor
    # because the question it answers has no "at least one" to floor at.
    kills = quantity / per_kill if amortise else max(1 / chance, quantity / per_kill)
    detail = f"{provider} at 1/{1 / chance:,.0f}, {rate.value:g}/hr"
    if amortise and per_kill > chance:
        detail = f"{provider}: {per_kill / chance:,.1f}/drop at 1/{1 / chance:,.0f}, {rate.value:g}/hr"
    elif kills > 1 / chance:
        detail = f"{provider} x{kills:,.0f} kills, {rate.value:g}/hr"

    if provider in walk.task_gates:
        # Mandatory: a task-gated monster priced without its task reads as
        # though you could walk up and fight it. If the wait cannot be
        # costed, the honest answer is that this route has no price.
        gated = _task_hours(walk, provider, kills, rate.value)
        if gated is None:
            return None
        hours, task, master = gated
        return _Priced(
            hours,
            f"{detail} on {task} task",
            provider,
            (_provider_knob(provider), f"wait/{master}/{task}"),
        )
    return _Priced(kills / rate.value, detail, provider, (_provider_knob(provider),))


def _task_hours(
    walk: _Walk, provider: str, kills: float, kills_per_hour: float
) -> tuple[float, str, str] | None:
    """Cost of `kills` of a task-gated monster, waiting for tasks included.

    You cannot go and kill a Grotesque Guardian; you have to be *sent*. One
    assignment yields `mean_count` of them, so `kills` needs
    `kills / mean_count` assignments, and each of those costs the wait for
    that task to come up plus the killing itself. Ignoring the wait is what
    made these look cheap: a gargoyle task once every several hours dwarfs the
    twenty minutes of actual fighting.

    **`wait` is downtime alone, not "wait plus this fight" - read
    `MasterRate.hours_to_be_assigned`'s own docstring for why that split
    matters.** `wait + rate.count / kills_per_hour` below is the two
    halves added exactly once each: hours spent on *other* tasks before
    `Gargoyles` comes up, plus the real time to clear it once it does -
    `kills_per_hour` here being the caller's own rate for whatever is
    actually gated (`Grotesque Guardians`'s scripted kill time, not the
    ordinary Gargoyle `slayer.task_kills_per_hour` prefers for the task's
    *other* purpose, training XP). Folding the boss's own completion time
    into `wait` too, as an earlier version of `hours_to_be_assigned` did,
    counted it twice.

    **Every layer that wants the cost of a gated kill comes through here** -
    the drop route, the superior route and, since it turned out to want the
    same thing, the kill-goal route. That last one used to price `1 /
    kills_per_hour` flat, so a Combat Achievement naming a monster you have to
    be *assigned* read as three minutes.

    **The master's own key for the task is `MasterRate.key_for`**, not the
    gate's name: `Konar quo Maten` keys by location and a bare name matched
    none of his, which left every gated monster on a Konar-only map unpriced.
    """
    gate = walk.task_gates.get(provider)
    if gate is None:
        return None

    # Cheapest over the masters that can assign it: the size is theirs too,
    # so wait and assignment length have to come from the same one. **Which
    # master won is part of the answer**, not a detail of finding it - the
    # entry a caller would correct is that master's, and every other master's
    # is irrelevant to this number.
    best: tuple[float, str, str] | None = None
    for master in walk.masters:
        key = master.key_for(gate)
        if key is None:
            continue
        # **A direct override of the wait itself outranks the computed
        # figure.** `wait/{master}/{key}` is a real knob a player can set -
        # see `knobs.BRANCH_NOTES["wait"]` - because `hours_to_be_assigned`
        # is a blend over the master's *whole* task list and nothing else
        # here names one leaf a correction could land on.
        override = (walk.heuristics.wait_hours.get(master.master) or {}).get(key)
        wait = override if override is not None else master.hours_to_be_assigned(key)
        rate = (walk.heuristics.slayer.get(master.master) or {}).get(key)
        if wait is None or rate is None or rate.count <= 0:
            continue
        assignments = max(1.0, kills / rate.count)
        hours = assignments * (wait + rate.count / kills_per_hour)
        if best is None or hours < best[0]:
            best = (hours, key, master.master)
    return best


def _superior_hours(
    walk: _Walk, superior: Superior, item: str, quantity: float = 1.0,
    amortise: bool = False,
) -> _Priced | None:
    """Hours to obtain `quantity` of `item` from a superior slayer monster.

    A superior is never placed in a chunk: it replaces one of its normal
    counterparts on death, only while on task, at roughly 1/200. So its cost
    is its base monster's cost multiplied by how many base kills a superior
    takes - and the base is usually task-gated itself, which the recursion
    picks up. `amortise` means the same thing it does in `_kill_hours`: drop
    the "has to happen at all" floor and answer the long-run per-item rate.
    """
    if superior.spawn_rate <= 0 or superior.base not in walk.available:
        return None
    rates = _drop_rates(walk, superior.name, item)
    if rates is None or rates[0] <= 0 or rates[1] <= 0:
        return None
    chance, per_kill = rates
    rate = walk.heuristics.kills_per_hour(superior.base)
    if rate.value <= 0:
        return None

    # Base kills needed: one superior per `1 / spawn_rate`, and the same two
    # bounds `_kill_hours` takes - the drop has to happen at all, and a stack
    # amortises once you want more than one, unless `amortise` says to skip
    # straight to the rate.
    supers = quantity / per_kill if amortise else max(1 / chance, quantity / per_kill)
    kills = (1 / superior.spawn_rate) * supers
    if superior.base in walk.task_gates:
        # Same rule as a direct kill: if the base's task cannot be costed,
        # the route has no price. Falling back to an ungated figure here made
        # the superior route look *cheaper* than the base monster's own drop,
        # which is how a 1/512 drop came out at 1,707 hours.
        gated = _task_hours(walk, superior.base, kills, rate.value)
        if gated is None:
            return None
        hours, task, master = gated
        knobs: tuple[str, ...] = (f"monsters/{superior.base}", f"wait/{master}/{task}")
    else:
        hours = kills / rate.value
        knobs = (f"monsters/{superior.base}",)
    # The *base* monster is the source: the superior spawns while you kill it,
    # so its drops accumulate alongside the base's own.
    return _Priced(
        hours,
        f"{superior.name} (superior) <- {superior.base}"
        f" at 1/{1 / superior.spawn_rate:,.0f}, drop 1/{1 / chance:,.0f}",
        superior.base,
        # The spawn rate is the superior's own entry; the kill rate is the
        # base's, since that is what you are actually fighting.
        (f"superiors/{superior.name}", *knobs),
    )


def _unique(paths: Iterable[str]) -> tuple[str, ...]:
    """`paths` with duplicates dropped, first-seen order kept.

    Order is the order they were read in, which for a made item is the recipe
    walked depth-first - so the dialog lists the thing you are making before
    the things it is made of. Sorting would lose that and gain nothing.
    """
    seen: dict[str, None] = {}
    for path in paths:
        seen.setdefault(path, None)
    return tuple(seen)


def _bucket_for(walk: _Walk, source: str) -> str:
    """Boss drops, ordinary monster drops and activity unlocks, told apart by
    what `source` names.

    **A colon-prefixed leaf route is never a monster**, so `_is_leaf_source`'s
    own test - a colon in the string - is what keeps a `make:`/`shop:`/
    `spawn:`/`currency:`/`recipe:` route out of `monster drops` without a
    second lookup: none of those names is ever a key in
    `world.locations["Monster"]`. What is left after the boss check is a bare
    provider name, and asking the world index whether it is a monster at all
    is what used to be missing - every non-boss kill and every non-boss drop
    (`Wyrm`, say) fell into `activities` alongside real activity unlocks and
    shop/recipe routes, with nothing on screen telling them apart.
    """
    if source in walk.world.boss_monsters:
        return "boss drops"
    if source in walk.world.locations.get("Monster", {}):
        return "monster drops"
    return "activities"


def _is_leaf_source(source: str) -> bool:
    """A one-off recipe/shop/spawn/currency route rather than a repeatable
    activity - see `ItemEstimate.group`.

    Every route `_item_hours` can return is either a bare provider name (a
    monster, a raid/instanced label, the literal `"herbs"` or `"yield"`) or
    one of four colon-prefixed leaf routes this module builds: `currency:`,
    `spawn:`/`shop:` (`_route_hours`'s own `route`), `recipe:` and `make:`.
    A colon is therefore the whole test, and it is exhaustive over every
    `_Priced` this module constructs - a real, repeatable source is never
    given one.
    """
    return ":" in source


def _leaf_task_groups(derived: Derived) -> dict[str, str]:
    """Diary/CA/Extra task name -> its display group's root name.

    `other_tasks.py` already computed the group each task belongs to
    (`~|Combat Achievements#Grandmaster|~ Wasn't Event Close` ->
    `Combat Achievements - Grandmaster`; a plain diary task the same way; an
    `Extra` task by its `Label`) - this is only the reverse index, task name
    to that group's `name`. `Quest` is excluded: quest steps are costed per
    task already (`_quest_tasks`), never routed through the item walk that
    calls this.
    """
    groups: dict[str, str] = {}
    for category, tasks in derived.other_tasks.categories.items():
        if category == "Quest":
            continue
        for group in tasks.groups:
            for name in (*group.active, *group.completed):
                groups[name] = group.name
    return groups


def _leaf_group(
    task_groups: Mapping[str, str], source: str, wanted_by: Iterable[str]
) -> str:
    """Which Diary/CA/Extra group a leaf item's display should roll up
    under, or `""` when none of its tasks belong to one - a BiS pick with no
    challenge behind it, say, which stays under its own recipe heading."""
    if not _is_leaf_source(source):
        return ""
    found = {task_groups[task] for task in wanted_by if task in task_groups}
    # Deterministic rather than "first found": `wanted_by` is a `set`, whose
    # iteration order is not something a display should depend on.
    return min(found) if found else ""


def _quest_tasks(derived: Derived, heuristics: Heuristics) -> list[TaskEstimate]:
    """Each outstanding quest, costed by the fraction of its steps left.

    `other_tasks.py` groups quest steps under their `BaseQuest`, which is also
    the wiki's page title, so the group name is the join key and the group's
    active list is what remains.
    """
    category = derived.other_tasks.categories.get("Quest")
    if category is None:
        return []

    estimates: list[TaskEstimate] = []
    for group in category.groups:
        remaining = len(group.active)
        if not remaining:
            continue
        rate = heuristics.quest_hours(group.name)
        total = max(remaining, _steps_in(derived, group.name))
        estimates.append(
            TaskEstimate(
                task=group.name,
                bucket="quests",
                hours=rate.hours * remaining / total,
                detail=f"{remaining}/{total} steps, {rate.length or 'unknown length'}",
                # The step counts are the export's and the fraction is
                # arithmetic; the only number anyone can argue with is how
                # long the quest takes. Quest names carry `/` - `Recipe for
                # Disaster/Freeing Evil Dave` - which is why `knobs.split`
                # takes its depth from the branch and not from the separator.
                knobs=(f"quests/{group.name}",),
            )
        )
    return estimates


def _steps_in(derived: Derived, quest: str) -> int:
    return sum(
        1
        for names in (derived.challenges.valid.get("Quest") or {},)
        for name in names
        if normalise(name).startswith(normalise(quest))
    )


def _has_training_method(chunk_info: ChunkInfo, skill: str, heuristics: Heuristics) -> bool:
    """Is there *any* way of training `skill`?

    Two different sources, because the combat skills answer differently. A
    challenge-based skill asks the export rather than the map: "this map cannot
    reach a Herblore method yet" is a floor band and a correctable gap, while
    "nothing anywhere trains Attack" is a different statement wanting a
    different answer. Measured: Attack 131 challenges and 0 primary, Defence
    146/0, Hitpoints 11/0, Ranged 172/0.

    **And that used to be the whole answer, which made combat unpriceable.**
    It is not a gap in the export - combat has no training *task* because it
    does not need one, it needs a monster. So a computed combat rate counts as
    a method here, and the five skills leave `unpriced_skills` the moment
    `costing/combat_xp.py` can reach something to hit.
    """
    if heuristics.combat.get(skill) is not None:
        return True
    return any(
        isinstance(challenge, dict) and challenge.get("Primary") is True
        for challenge in _mapping(chunk_info.challenges, skill).values()
    )


def _farming_bands(
    plan: FarmingPlan,
    options: Sequence[TrainingOption],
    start_xp: int,
    capped: int,
) -> tuple[tuple[TrainingBand, ...], float]:
    """Farming's climb and its calendar, which are two different quantities.

    **The schedule is one method among the skill's others, not the whole
    answer.** It used to be the whole answer, and that hid Tithe Farm - a
    minigame with no growing time at all, which the map may or may not reach.

    **Where the minigame is available it is preferred outright, and not
    because it is faster by the hour.** It is not: the schedule's blended rate
    counts only the clicking, so it reads several times higher while taking
    months of calendar to deliver. The axis that decides is the calendar, and
    on that the minigame wins by roughly six to one - so it is chosen above
    the level it opens at and the schedule keeps everything below, which is
    also what a player would really do. The wiki says the same thing from the
    other side: you tithe farm *between* the time patches take to grow.

    **And where the minigame is reachable the calendar is not reported at
    all.** It opens at level 34, so from there on the growing time in the
    schedule's rate is a *choice* rather than a constraint, and what the
    player spends is hours. When the minigame is locked the calendar stands,
    because then the waiting is the skill.

    **That limit used to bite from 34 to 74 and now does not.** The guide
    publishes one figure, at 74, so the two lower seed tiers were unrated and
    `active` was 74 - the whole stretch the minigame is actually playable over
    was priced at the schedule's blended rate, which is only achievable by
    waiting. Charging the level-74 figure from 34 was the other bias and was
    rejected for inventing a number. `skill_tables.parse_tithe` removed the
    choice: the lower tiers are now computed from the minigame's own reward
    mechanics, at roughly 23,000 and 55,000 against the top tier's 90,000, so
    `active` is 34 and the stretch is priced at what it really pays.

    **What is left below 34 is the schedule's rate, and that is the answer
    rather than a gap.** The minigame is locked there, so the waiting really
    is the skill - and the only legitimate *active* methods below it are
    composting and raking, which is why a band reading a few hundred an hour
    is not evidence of a missing method. Farming is trained passively and the
    schedule is that model; Tithe Farm is the one reasonable active method and
    it now opens where the game opens it. So a later pass finding 268/hr here
    and going looking for faster low-level Farming should stop: there is
    nothing to find, and the tempting fix - lending the minigame's rate down
    below 34 - prices an activity the player cannot enter.
    """
    schedule = TrainingOption(
        method=f"{len(plan.runs)} patches, {plan.xp_per_day:,.0f} xp/day",
        level=1,
        xp_per_hour=plan.xp_per_day / plan.hours_per_day,
        match="farming",
    )
    active = min(
        (option.level or 1 for option in options if option.source == TITHE_SOURCE),
        default=None,
    )
    if active is None or active >= capped:
        bands = training_bands((*options, schedule), start_xp, capped)
    else:
        split = max(start_xp, xp_for_level(active))
        bands = training_bands((*options, schedule), start_xp, level_for_xp(split))
        # Above the minigame's level the schedule is left out rather than
        # outranked, which is the whole of "prefer it where you have it".
        bands += training_bands(options, split, capped)
    if active is not None and any(band.match != "farming" for band in bands):
        return bands, 0.0
    grown = sum(band.xp for band in bands if band.match == "farming")
    return bands, plan.days_for(grown) if grown > 0 else 0.0


def _skill_knobs(bands: tuple[TrainingBand, ...]) -> tuple[str, ...]:
    """The entries behind a climb, collected from the bands that have one.

    **Read off the band rather than worked out from it**, which is the same
    rule `_Priced.knobs` follows and the one this function was written twice
    for breaking. Inferring `training/<method>/<skill>` from what a band
    carries was wrong four separate ways, each silently - the path was
    accepted, written, and moved no number:

    - a combat band's rate is damage against hitpoints, not a training entry;
    - a Slayer band's is a distribution over a master's whole assignment
      table, and `training/<master>` is not a key anywhere;
    - a farming band is a calendar schedule rather than a rate;
    - and for the ordinary case the key is the *challenge's* name, where
      `TrainingBand.method` is `activity_name(...)` - a display string.

    So each producer sets `TrainingBand.knob` where it chooses the rate, and
    this collects them. A band with no knob is one the file describes nothing
    for, which is the honest answer rather than a guess.
    """
    return _unique(band.knob for band in bands if band.knob)


def _skill_estimate(
    skill: str,
    goal: str,
    current: int,
    target: int,
    xp: int,
    bands: tuple[TrainingBand, ...],
    *,
    xp_from_quests: int = 0,
    xp_from_combat: float = 0.0,
    days: float = 0.0,
    effective_level: int = 0,
) -> SkillEstimate:
    """One skill's row, summarised from its bands.

    **`xp_per_hour` is the blended rate and `method` the band that trains the
    most XP**, which is what keeps this change additive: every existing reader -
    the CLI's `{xp} xp @ {rate}/hr = {hours}h {method}` line, the panel, the
    JSON - keeps working and keeps saying something true. The bands carry the
    detail for anyone who wants it.

    `defaulted` keeps its old meaning too: the *whole* climb is at the floor,
    i.e. nothing on this map has a measured rate for this skill. A climb that is
    part floored says so through `floor_xp` instead, which is the more common
    and more interesting case - on the real map the floor is 1% of Herblore's
    XP and 56% of its hours.
    """
    hours = sum(band.hours for band in bands)
    floor_xp = sum(band.xp for band in bands if band.match == "default")
    widest = max(bands, key=lambda band: band.xp, default=None)
    return SkillEstimate(
        skill=skill,
        goal=goal,
        current_level=current,
        target_level=target,
        xp=xp,
        xp_per_hour=xp / hours if hours > 0 else 0.0,
        method=(widest.method if widest and widest.method else "(none found)"),
        hours=hours,
        defaulted=bool(bands) and floor_xp == xp,
        bands=bands,
        floor_xp=floor_xp,
        xp_from_quests=xp_from_quests,
        xp_from_combat=xp_from_combat,
        days=days,
        effective_level=effective_level or current,
        knobs=_skill_knobs(bands),
    )


@dataclass(frozen=True)
class _Setup:
    """The walk, and the three things `estimate` computes on the way to it.

    Built by `_setup` so that pricing a *material* uses the same gates as
    pricing a goal. Two constructions of `_Walk` would be two answers to
    "can this map reach a blast furnace", and the second one would be wrong
    the moment either moved.
    """

    walk: _Walk
    levels: dict[str, int]
    masters: tuple[MasterRate, ...]
    slayer: MasterRate | None


def _challenge_outputs(
    chunk_info: ChunkInfo, valid: Mapping[str, Mapping[str, Any]]
) -> set[str]:
    """Everything a *valid* challenge names as its `Output`.

    Usually an item; sometimes the name of a `skillItems` table, which is how
    the export says "doing this gives you a roll on that".
    """
    found: set[str] = set()
    for category, names in valid.items():
        challenges = _mapping(chunk_info.challenges, category)
        for name, ok in names.items():
            if not ok:
                continue
            entry = challenges.get(name)
            if isinstance(entry, dict) and isinstance(entry.get("Output"), str):
                found.add(entry["Output"])
    return found


#: Upstream's own category for a dish part-way through being assembled.
_PARTIAL_PRODUCTS = "Partial Products"




def _run_priced_items(overrides: Mapping[str, float] = {}) -> dict[str, float]:
    """Every reward whose cost is a **completion count**, not a drop rate.

    Eight families, one shape. `costing/raids.py` answers for the three
    raids, `costing/tzhaar.py` for the Fight Caves and the Inferno,
    `costing/barrows.py` for the Barrows chest, `costing/colosseum.py` for
    the Fortis Colosseum, `costing/moons.py` for Perilous Moons,
    `costing/gauntlet.py` for the Gauntlet and the Corrupted Gauntlet, and
    `costing/wintertodt.py`/`costing/tempoross.py` for the phoenix and Tiny
    tempor pets; all eight exist because the export files a run as a
    monster (or names a reward it has no table for at all) and a walk that
    believes it prices a forty-minute Inferno at three minutes, or a
    Barrows chest's uniques at whatever `DEFAULT_KPH` implies for a monster
    with no drop table.

    **Merged in one place so the two call sites cannot drift.** The goal walk
    and the post-enrichment walk both spend this, and `costing/inputs.py`
    exists because two consumers of one layer had already drifted once.

    A key collision between any two of the eight would be a real problem
    rather than a tie-break, so it is not silently resolved: nothing is in
    more than one, and `tests/test_costing_tzhaar.py` pins that.
    """
    return {
        **raids.item_seconds(overrides),
        **tzhaar.item_seconds(overrides),
        **barrows.item_seconds(),
        **colosseum.item_seconds(overrides),
        **moons.item_seconds(),
        **gauntlet.item_seconds(),
        **wintertodt.item_seconds(),
        **tempoross.item_seconds(),
    }


def _setup(
    state: MapState,
    derived: Derived,
    world: WorldIndex,
    heuristics: Heuristics,
    level_overrides: dict[str, int],
    recipes: Mapping[str, Sequence[Recipe]] | None = None,
) -> _Setup:
    """Everything the item walk needs, assembled once.

    **The goal walk carries the raid rewards and nothing else from
    `yield_seconds`**, which is a deliberate asymmetry rather than an
    oversight. That map's other contributors - a gathering action's weight
    tiers, a vale offering, a reward sack - are *material* costs, and this
    walk is the one pricing goals; they are assembled in `material_seconds`
    where the recipe layer reads them.

    The raids and the wave minigames are here because without them a goal walk
    prices a *run* as a monster. The export models each as a drop table, so
    `Heuristics.kills_per_hour` fell back to `DEFAULT_KPH`: `Xeric's champion`,
    which wants two thousand raids, came out at **24 seconds**, and
    `Jal-nib-rek` - a 1/100 off a Zuk kill that costs a whole Inferno - at
    5.0 hours against this project's own 45. See `_run_priced_items`,
    `costing/raids.item_seconds` and `costing/tzhaar.item_seconds`.

    **`providers` is `farmable_providers`, not `reachable_providers`, for the
    same reason `combat_xp.best_target` already needed the distinction.** Some
    raids place their own bosses in a chunk after all - the Chambers files
    `Skeletal Mystic` and `Muttadile` under the `Chambers of Xeric` chunk
    itself, unlike the Theatre, whose five bosses carry no `Monster` branch
    anywhere (`costing/instanced.py`'s own docstring measures the gap). Left
    as `reachable_providers`, those two read as ordinary farmable monsters:
    `Heuristics.kills_per_hour` has no scrape for either, so `Long bone` and
    `Curved bone` - both real `Extra` tasks on the real map - priced at
    `DEFAULT_KPH`'s **150 kills an hour**, the exact bug `_run_priced_items`
    exists to keep out of the *drop* route, reappearing through the *kill*
    route instead. `farmable_providers` already excludes anything whose every
    reachable chunk is inside `instanced.run_only` - reusing it here rather
    than re-deriving the same test is what closes this for every raid at
    once instead of one export snapshot's two named items.

    **And a `_GROUP_BOSS_SOLO_ALTERNATIVE` entry is dropped from `providers`
    when its solo sibling is also reachable**, for the reason that constant's
    own docstring gives: "The Nightmare" is real content with a real drop
    table, so nothing upstream marks it unreachable the way an instanced
    raid boss is - it just has no honest kill rate a solo player can use, and
    leaving it in `providers` let the walk keep pricing off a team's wiki
    figure while its own soloable twin sat right next to it unused. Only
    dropped when the twin is *also* reachable, so a map that somehow reaches
    the team fight without the solo one still gets the (bad) guide number
    rather than nothing.
    """
    levels = _levels(state, level_overrides or {})
    reachable = frozenset(derived.source_index.monsters)
    providers = farmable_providers(derived, state.chunk_info)
    providers -= {
        boss
        for boss, solo in _GROUP_BOSS_SOLO_ALTERNATIVE.items()
        if solo in providers
    }
    valid = derived.challenges.valid
    # `derive`'s *settled* expansion, not a fresh one-shot call: areas keep
    # opening as challenges become valid, and expanding once leaves 60 named
    # areas locked on the real map - `Wilderness Slayer Cave` among them,
    # which silently cost Krystilia every task that can roll a superior.
    expanded = dict(derived.expanded_chunks)
    # A slayer master you cannot reach assigns nothing - see `slayer.py`.
    reachable_masters = frozenset(derived.source_index.npcs)

    # End-of-chunk levels, not today's: the task list a master offers then
    # is the one that holds for the tail of the chunk, which is where the
    # time goes.
    goals = goal_levels(state, derived, levels)
    reachable_rates = tuple(
        master_rates(
            state.chunk_info,
            heuristics,
            reachable_monsters=reachable,
            valid=valid,
            unlocked=expanded,
            reachable_sections=derived.reachable_sections,
            levels=goals,
            combat_level=goals.get("Combat", MAX_LEVEL),
            reachable_masters=reachable_masters,
        )
    )
    slayer_rate = best_master(list(reachable_rates))
    # **Larran's small and big chests, opens per hour rather than
    # `DEFAULT_KPH`.** Neither chest has a stat block, so without this
    # `heuristics.kills_per_hour` fell through to 150/hr and priced an uncut
    # ruby or a rune platebody as though the chest opened on demand. A key is
    # the whole cost, and Krystilia's Wilderness Slayer tasks are the only
    # way to earn one - see `costing/larran.py`. A no-op wherever she cannot
    # be reached at all (`krystilia is None`).
    krystilia = next((rate for rate in reachable_rates if rate.master == "Krystilia"), None)
    heuristics = larran.priced(heuristics, krystilia, state.chunk_info, reachable)
    # **The brimstone chest, Konar's own twin of the above.** Same gap, same
    # fix: no stat block, so `DEFAULT_KPH` priced it at 150 opens an hour. A
    # brimstone key's only source is Konar quo Maten's own slayer tasks - see
    # `costing/brimstone.py`. A no-op wherever she cannot be reached at all.
    konar = next((rate for rate in reachable_rates if rate.master == "Konar quo Maten"), None)
    heuristics = brimstone.priced(heuristics, konar, state.chunk_info, reachable)
    # The same end-of-chunk levels for task-gated drops. Grotesque Guardians
    # need a gargoyle task, which needs Slayer 75; at today's level that task
    # is unassignable and the drop would read as unobtainable forever. It
    # isn't - the skilling bucket is already costing the climb.
    # **An activity a valid challenge unlocks is a provider too.** The export
    # models the Evil chicken outfit as `Trade bird's eggs for nests*` at a
    # Shrine, whose `Output` names the `skillItems.Nonskill` table holding the
    # four pieces at 1/1200 - so the pieces are reachable the moment the trade
    # is, and were unpriced because nothing put the *table* in the provider
    # set beside monsters, objects and NPCs.
    #
    # **Gated on someone having stated a rate**, which is what keeps this from
    # pricing the other 322 such tables at the 60/hr default: a minigame reward
    # table given a guessed rate would make its rarest drop look cheap, and a
    # guessed rate multiplied by a real drop chance is the mistake
    # `combat_xp.best_target` already refuses.
    unlocked_activities = frozenset(
        name
        for name in _challenge_outputs(state.chunk_info, valid)
        if any(name in _mapping(state.chunk_info.skill_items, skill)
               for skill in state.chunk_info.skill_items)
        and not heuristics.kills_per_hour(name).source.startswith("default")
    )
    providers = providers | unlocked_activities
    gate_masters = reachable_rates
    by_lower = {item.lower(): item for item in world.item_sources}
    walk = _Walk(
        chunk_info=state.chunk_info,
        world=world,
        heuristics=heuristics,
        tables=_mapping(state.chunk_info.code_items, "dropTables"),
        by_lower=by_lower,
        available=providers,
        # **`available_items`, not `SourceIndex.items`** - the project's first
        # cross-cutting rule, and this module was the third to get it wrong
        # after `bis.py` and `boosts.py`. The latter omits anything obtainable
        # only by *making* it: 1,103 items against 1,918 on the reference map, so 815
        # reachable items were refused a shop or spawn route on the grounds
        # that the map could not reach them, when it plainly could.
        reachable_items=frozenset(derived.challenges.available_items),
        unlocked_chunks=frozenset(expanded),
        reachable_sections=derived.reachable_sections,
        task_gates=task_gated_monsters(
            state.chunk_info, world, frozenset(expanded)
        ),
        masters=gate_masters,
        item_families={
            name: members
            for name, members in _mapping(state.chunk_info.code_items, "itemsPlus").items()
            if isinstance(members, list)
        },
        superior_table=superior_table_items(state.chunk_info),
        superior_rolls={
            rate.master: superior_rolls_per_hour(rate, state.chunk_info, heuristics)
            for rate in gate_masters
        },
        # **The raids** - see `_Walk.raid_seconds`. A cape is a *counter*
        # rather than a drop, so no rate the export carries could have
        # expressed it, and the drop route it does carry is wrong by two
        # orders of magnitude.
        #
        # **Lowercased**, because the wiki, the export's drop table and
        # `world.item_sources` disagree about capitalisation and one of them
        # does not carry the item at all - see `_Walk.raid_seconds`.
        raid_seconds={
            item.lower(): seconds
            for item, seconds in _run_priced_items(heuristics.run_seconds).items()
        },
    )
    # **What a herb costs, which is a supply rather than a route.** The
    # patches this map can stand in, plus the best *pooled* herb source it can
    # kill - see `costing/herbs.py` for why a herb table is not thirteen
    # separate questions. Assembled after the walk because the pool needs the
    # walk's own drop rates and reachability.
    # **Every recipe, keyed by what it makes**, for `_recipe_hours`' last
    # resort. Flattened across skills because the walk asks "how do I get this
    # item", never "which skill makes it".
    #
    # **The stated durations are applied here rather than downstream**, so the
    # walk and `recipe_rates.rate_for` read one corpus and cannot disagree
    # about how long an untimed action takes - `recipe_rates.ticks_for` is the
    # one answer and `stated_ticks` the one merge, which says which modules
    # fill it. Anything still untimed falls back to `DEFAULT_ACTION_SECONDS`
    # inside `_recipe_hours`, which is where an unknown belongs.
    #
    # **A stated instant is resolved here too, and it has to be.** `ticks = 0`
    # survives parsing now (`Recipe.timed`), and left alone it would make the
    # walk price 448 recipes as costing no time at all - the exact failure
    # `rate_for`'s old refusal existed to avoid.
    stated = recipe_rates.stated_ticks(state.chunk_info, recipes or {})
    by_output: dict[str, tuple[Recipe, ...]] = {}
    for rows in (recipes or {}).values():
        for made in rows:
            if not made.timed:
                made = dataclasses.replace(made, ticks=recipe_rates.ticks_for(made, stated))
            key = made.output.lower()
            by_output[key] = (*by_output.get(key, ()), made)
    if by_output:
        # **A different recipe corpus is a different walk**, and `replace`
        # shares field references - so the subtree memo and the frame stack
        # are reset rather than inherited, or answers cached against one
        # corpus would be served against the other.
        # `kill_facts` may ride along: nothing in it reads the recipe corpus
        # or the experience table.
        walk = dataclasses.replace(
            walk, recipes=by_output, fixpoint=_Fixpoint(), leaf_routes={}
        )

    grimy = herbs.herb_items(derived.source_index.items)
    if grimy:
        patches = herbs.patch_count(
            world.entity_locations("Herb patch"), expanded, derived.reachable_sections
        )
        _, active = herbs.pooled_rate(
            walk.available,
            grimy,
            lambda provider, herb: (_drop_rates(walk, provider, herb) or (0.0, 0.0))[1],
            lambda provider: heuristics.kills_per_hour(provider).value,
        )
        walk = dataclasses.replace(
            walk, herb_seconds=herbs.costs(grimy, patches, active)
        )
    # **The action's own weight tiers**, priced flat for the reason the herbs
    # above are - see `costing/yields.py`, and `_route_hours`' certainty gate
    # for what it is standing in for.
    # **And a minigame's own reward roll, which is the same shape.** A vale
    # offering is rummaged a hundred at a time for one roll of a published
    # table, and the totem that produced it is priced by `valetotems` with its
    # five logs charged - so the pace behind the share is computed rather than
    # defaulted. See `costing/valeoffering.py`; it is merged into the same map
    # because the walk asks one question of it.
    walk = dataclasses.replace(
        walk,
        # **The same raid answers the goal walk gets**, so the two layers
        # cannot disagree about what a raid drop costs - `costing/inputs.py`
        # exists because two apps drifted on exactly this kind of split.
        raid_seconds={
            item.lower(): seconds
            for item, seconds in _run_priced_items(walk.heuristics.run_seconds).items()
        },
        yield_seconds={
            **yields.costs(
                state.chunk_info,
                heuristics.action_seconds,
                lambda task, skill: heuristics.xp_per_hour(task, skill).match,
                lambda provider, member: (
                    _drop_rates(walk, provider, member) or (0.0, 0.0)
                )[0],
            ),
            **valeoffering.costs(
                derived.challenges.valid,
                levels,
                # **The walk as it stands, which is sound here and only
                # here.** A totem's logs are ordinary items, priced by routes
                # that cannot themselves pass through a vale offering - so
                # reading the pre-`yield_seconds` walk for them is not a
                # missing answer, it is the only one there is.
                lambda item, quantity: _log_seconds(walk, item, quantity),
            ),
            # **And a reward sack, which is the same shape with one twist.**
            # The export records a sack's share *per roll* and an open is five
            # to eleven of them - see `costing/lootsack.py`, whose pace comes
            # from `costing/rumours.py` and inherits that module's one guess.
            **lootsack.costs(state.chunk_info, derived.challenges.valid),
        },
    )
    return _Setup(
        walk=walk, levels=levels, masters=reachable_rates, slayer=slayer_rate
    )


@dataclass(frozen=True)
class _MaterialWalk:
    """The two questions one item walk answers, sharing one memo.

    **They have to share it.** `_item_hours` takes the `min` over routes, so
    "how long does a bar take" and "what experience did getting it pay" are
    the same decision seen twice - answering them from two walks would let a
    bar be *bought* for the cost and *smelted* for the credit.
    """

    #: `(item, quantity) -> seconds`, or `None` where there is no route.
    seconds: Callable[[str, float], float | None]
    #: `(item, quantity, skill) -> experience in that skill along the route`.
    experience: Callable[[str, float, str], float]
    #: **What `_setup` actually priced, chests included.** `_setup` derives
    #: Larran's and the brimstone chest's own opens-per-hour and folds them
    #: into a *local* `Heuristics` that only the walk's closures ever saw -
    #: `recipe_priced`'s own returned `Heuristics` (what `priced_layers` and
    #: therefore every GUI knob reads) kept the pre-`_setup` copy, so a
    #: correctly-derived chest rate priced every reward inside it right while
    #: reading `monsters/Brimstone chest` in the knob dialog still showed the
    #: bare `DEFAULT_KPH` 150/hr underneath it. `recipe_priced` merges this
    #: back in rather than leaving it walk-only.
    heuristics: Heuristics


def _log_seconds(walk: _Walk, item: str, quantity: float) -> float | None:
    """Seconds for `quantity` of `item`, for `valeoffering`'s log bill."""
    priced = _item_hours(walk, item, quantity=quantity, amortise=True)
    return None if priced is None else priced.hours * 3600.0


def material_seconds(
    state: MapState,
    derived: Derived,
    world: WorldIndex,
    heuristics: Heuristics,
    *,
    level_overrides: dict[str, int] | None = None,
    made_experience: Mapping[str, tuple[str, float]] | None = None,
    recipes: Mapping[str, Sequence[Recipe]] | None = None,
    material_aliases: Mapping[str, str] = {},
) -> _MaterialWalk:
    """Two callables over one item walk: what a material costs, and what
    obtaining it *paid*.

    **What `costing/recipe_rates.py` needs and cannot build for itself.** The
    item walk lives here, behind a `_Walk` carrying this map's reachability
    gates; a recipe is a pure fact about the game. So the seam is this
    closure: `recipe_rates` asks "how long to get two guam leaves" without
    learning what a `_Walk` is, and `estimate` answers without learning what a
    recipe is.

    `None` means no route, which the caller must treat as *drop the method*
    rather than as free - see that module's docstring.

    The closure holds one `_Walk` and is therefore worth reusing across a whole
    skill's recipes; it is a local, never a module-level cache, so the purity
    rule that keeps `--jobs` honest is untouched.

    **It also remembers, and `(item, quantity)` is the whole key.** Every call
    reaches `_item_hours` with the same `walk` and `amortise=True`, so nothing
    else can vary the answer - and the recipes ask the same question about
    three times over (1,235 calls over 451 distinct pairs pricing the
    reference map's methods), because `Cosmic rune` is a material of dozens
    of them. The fixpoint table underneath makes a miss cheap too; this keeps
    a hit from re-entering the walk at all.

    **`material_aliases` is tried only after the literal name fails.** A
    recipe's material is the wiki's own vocabulary, and `world.item_sources`
    is built entirely from the export's `Output` strings - so where the two
    disagree, `_item_hours` sees no route for a material the map plainly
    provides. See `recipe_rates.MATERIAL_ALIASES` for what it holds and why
    it is one hand-verified entry rather than a general rule.
    """
    walk = material_walk(
        state,
        derived,
        world,
        heuristics,
        level_overrides=level_overrides,
        made_experience=made_experience,
        recipes=recipes,
    )
    memo: dict[tuple[str, float], _Priced | None] = {}

    def priced_for(item: str, quantity: float) -> _Priced | None:
        key = (walk.resolve(item), quantity)
        if key in memo:
            return memo[key]
        # `amortise`: a recipe's materials are bought for a run of actions,
        # not fetched one trip at a time. See `_route_hours`.
        found = _item_hours(walk, item, quantity=quantity, amortise=True)
        if found is None:
            # **The recipe's own name for a material, where the export's item
            # graph knows it under another** - see
            # `recipe_rates.MATERIAL_ALIASES`. Tried only once the literal
            # name has failed, so a material the export *does* recognise is
            # never routed through the alias table by mistake.
            aliased = material_aliases.get(item)
            if aliased is not None:
                found = _item_hours(walk, aliased, quantity=quantity, amortise=True)
        memo[key] = found
        return found

    def experience(item: str, quantity: float, skill: str) -> float:
        """Experience in `skill` earned obtaining `quantity` of `item`.

        **Only along the route the walk chose**, which is why this shares the
        memo with `seconds` rather than answering separately: a bar smelted
        and a bar bought cost different amounts and pay different experience,
        and the two answers have to be about the same decision.
        """
        found = priced_for(item, quantity)
        if found is None:
            return 0.0
        return sum(paid for earned, paid in found.experience if earned == skill)

    def seconds(item: str, quantity: float) -> float | None:
        # Keyed on the export's own spelling, since `_item_hours` resolves
        # anyway and two spellings of one item are one question.
        # `None` is a real answer here - "no route", which the caller must
        # treat as *drop the method* - so this asks `is None`, never `or`.
        found = priced_for(item, quantity)
        return None if found is None else found.hours * 3600.0

    return _MaterialWalk(seconds=seconds, experience=experience, heuristics=walk.heuristics)


def estimate(
    state: MapState,
    derived: Derived,
    world: WorldIndex,
    heuristics: Heuristics,
    *,
    level_overrides: dict[str, int] | None = None,
    recipes: Mapping[str, Sequence[Recipe]] | None = None,
) -> EstimateResult:
    """Estimate the outstanding active work. See the module docstring first."""
    setup = _setup(state, derived, world, heuristics, level_overrides or {}, recipes)
    walk, levels = setup.walk, setup.levels
    reachable_rates, slayer_rate = setup.masters, setup.slayer
    tasks: list[TaskEstimate] = list(_quest_tasks(derived, heuristics))
    unpriced: list[str] = []

    # Price the *item*, once, no matter how many tasks want it. An abyssal
    # whip answers a BiS pick, a Slayer log entry and a monster-drop log
    # entry; charging for it three times inflated the total by however much
    # the active set happens to overlap, which on the real map is a lot.
    task_groups = _leaf_task_groups(derived)
    items: list[ItemEstimate] = []
    for item, wanted_by in sorted(_required_items(walk, derived).items()):
        priced = _item_hours(walk, item)
        if priced is None:
            unpriced.append(item)
            continue
        items.append(
            ItemEstimate(
                item=item,
                bucket=_bucket_for(walk, priced.source),
                hours=priced.hours,
                detail=priced.detail,
                source=priced.source,
                tasks=tuple(sorted(wanted_by)),
                group=_leaf_group(task_groups, priced.source, wanted_by),
                knobs=priced.knobs,
            )
        )

    # Tasks wanting a kill rather than a drop: one kill at that monster's
    # rate, attributed to it so the clamp folds it into any grind already
    # happening there.
    for monster, wanted_by in sorted(_required_kills(walk, derived).items()):
        # **Unless the kill *is* a run.** `1 / kills_per_hour` is right for
        # something you can walk up to and wrong by three orders of magnitude
        # for something sixty-eight waves in: four Combat Achievements naming
        # `TzKal-Zuk` shared 0.05 hours between them, when each needs a whole
        # Inferno. Asked of `costing/instanced.py` rather than of any one
        # activity, so the raids' final bosses answer here too and a later
        # layer cannot reach a different number - which is exactly how this
        # branch came to disagree with the item walk in the first place.
        run = instanced.kill_seconds(monster, heuristics.run_seconds)
        if run is not None:
            activity = instanced.place_of_boss(monster) or monster
            items.append(
                ItemEstimate(
                    item=f"kill {monster}",
                    bucket=_bucket_for(walk, activity),
                    hours=run / 3600.0,
                    detail=f"{activity.lower()}: one completion",
                    source=activity,
                    tasks=tuple(sorted(wanted_by)),
                    knobs=(instanced.knob_for(activity),),
                )
            )
            continue
        kph = heuristics.kills_per_hour(monster).value
        if kph <= 0:
            continue
        # **And unless the kill has to be *assigned*.** The third layer to
        # learn this: a monster behind a slayer task cannot be walked up to
        # any more than a run's boss can, so one kill is one wait plus the
        # killing. Priced flat, `Alchemical Hydra` - which you may only fight
        # on a Hydras task - read as three minutes. `_task_hours` is the same
        # function the drop and superior routes use, so all three now agree
        # about what being sent costs.
        gated = _task_hours(walk, monster, 1.0, kph)
        if gated is not None:
            hours, task, master = gated
            items.append(
                ItemEstimate(
                    item=f"kill {monster}",
                    bucket=_bucket_for(walk, monster),
                    hours=hours,
                    detail=f"one kill at {kph:g}/hr on {task} task",
                    source=monster,
                    tasks=tuple(sorted(wanted_by)),
                    knobs=(f"monsters/{monster}", f"wait/{master}/{task}"),
                )
            )
            continue
        if monster in walk.task_gates:
            # Gated, and no master can be costed for it - the same refusal the
            # drop route makes rather than quoting an ungated figure.
            unpriced.append(f"kill {monster}")
            continue
        items.append(
            ItemEstimate(
                item=f"kill {monster}",
                bucket=_bucket_for(walk, monster),
                hours=1 / kph,
                detail=f"one kill at {kph:g}/hr",
                source=monster,
                tasks=tuple(sorted(wanted_by)),
                knobs=(f"monsters/{monster}",),
            )
        )

    skills: list[SkillEstimate] = []
    unpriced_skills: list[UnpricedSkill] = []
    combat_at: dict[str, tuple[int, str, int, int, int, int, int]] = {}
    grants, lamps = quest_xp_grants(derived, state.chunk_info)
    for skill, classification in sorted(derived.task_classification.skills.items()):
        goal = classification.active
        if goal is None:
            continue
        challenge = _mapping(state.chunk_info.challenges, skill).get(goal)
        target = challenge.get("Level") if isinstance(challenge, dict) else None
        if not isinstance(target, (int, float)) or isinstance(target, bool):
            continue
        current = levels.get(skill, 1)
        capped = min(int(target), MAX_LEVEL)
        target_xp = xp_for_level(capped)
        # **One operation, not two.** Adding the quest reward to the starting
        # total both removes that XP from the climb and moves the start up the
        # curve, so there is no separate level adjustment that could disagree
        # with it. Clamped at the goal: a reward can overshoot.
        granted = grants.get(skill, 0)
        start_xp = min(xp_for_level(max(1, min(current, MAX_LEVEL))) + granted, target_xp)
        xp = max(0, target_xp - start_xp)
        # **Two different refusals, and the difference is worth saying.** One
        # is "the export lists nothing that trains this"; the other is "the
        # export lists plenty and nobody anywhere has timed any of it". Both
        # end here rather than at the floor, because a four-figure number with
        # nothing behind it is worse than an admission.
        refusal = ""
        if xp > 0 and skill in UNRATED_SKILLS and not training_options(
            derived, state.chunk_info, heuristics, skill
        ):
            refusal = "no published rates for this skill yet"
        elif xp > 0 and not _has_training_method(state.chunk_info, skill, heuristics):
            # No `Primary: true` challenge anywhere in the export - the four
            # combat skills, which you train by fighting rather than by an
            # activity the export lists. Refused, not guessed at.
            refusal = "no training method exists for this skill"
        if refusal:
            unpriced_skills.append(
                UnpricedSkill(
                    skill=skill,
                    goal=goal,
                    current_level=current,
                    target_level=int(target),
                    xp=xp,
                    reason=refusal,
                )
            )
            continue
        farming_days = 0.0
        bands: tuple[TrainingBand, ...] = ()
        if skill == "Farming" and heuristics.crops:
            # **Farming is days, not hours.** A crop grows while you do
            # something else, so the schedule - how many harvests a day you
            # get round to - is what limits it. `active_hours` is the clicking
            # and goes in the bucket beside every other skill; the calendar is
            # reported next to it and deliberately not added, because a day of
            # waiting is not a day of playing.
            plan = farming_plan(
                heuristics.crops,
                capped,
                harvests_per_day={
                    **DEFAULT_HARVESTS_PER_DAY,
                    **heuristics.farming_schedule,
                },
            )
            if plan.xp_per_day > 0 and plan.hours_per_day > 0:
                bands, farming_days = _farming_bands(
                    plan,
                    training_options(derived, state.chunk_info, heuristics, skill),
                    start_xp,
                    capped,
                )
        if bands:
            pass
        elif skill == "Slayer" and slayer_rate is not None and slayer_rate.xp_per_hour > 0:
            # **Slayer is one band by nature.** Its rate is a distribution over
            # what a master assigns rather than a method you pick and outgrow,
            # so `slayer.py` answers for the whole climb and there is nothing
            # to band.
            bands = (
                TrainingBand(
                    level_from=level_for_xp(start_xp),
                    level_to=capped,
                    xp=xp,
                    xp_per_hour=slayer_rate.xp_per_hour,
                    method=slayer_rate.master,
                    match="slayer",
                    # **A branch, like the superior table.** The rate is a
                    # distribution over everything the master assigns, so no
                    # single entry is behind it - and `training/<master>` is
                    # not a key anywhere, which is what the first version of
                    # this recorded.
                    knob=f"slayer/{slayer_rate.master}",
                ),
            )
        else:
            bands = training_bands(
                training_options(derived, state.chunk_info, heuristics, skill),
                start_xp,
                capped,
            )
        skills.append(
            _skill_estimate(
                skill,
                goal,
                current,
                int(target),
                xp,
                bands,
                xp_from_quests=min(granted, xp_between(current, capped)),
                days=farming_days,
                effective_level=level_for_xp(start_xp),
            )
        )
        if skill in COMBAT_SKILLS:
            combat_at[skill] = (
                len(skills) - 1, goal, current, int(target), capped, start_xp, granted
            )

    def _rebuild(skill: str, credited: float) -> None:
        """Re-price one combat climb with `credited` XP taken off its front."""
        at, goal_, level_, target_, capped_, start_, granted_ = combat_at[skill]
        target_xp_ = xp_for_level(capped_)
        moved = int(min(start_ + credited, target_xp_))
        skills[at] = _skill_estimate(
            skill,
            goal_,
            level_,
            target_,
            max(0, target_xp_ - moved),
            training_bands(
                training_options(derived, state.chunk_info, heuristics, skill),
                moved,
                capped_,
            ),
            xp_from_quests=min(granted_, xp_between(level_, capped_)),
            xp_from_combat=min(credited, float(xp_between(level_, capped_))),
            effective_level=level_for_xp(moved),
        )

    # **A Slayer task is a fight, so it pays the combat skills too.** Its XP is
    # the monster's hitpoints, which makes a Slayer rate a damage rate - and
    # 394 hours of it on the benchmark map had already earned the Hitpoints,
    # Defence and Attack climbs being charged for beside it. Credited before
    # `hitpoints_credit`, so that pass sees the hours that are actually left.
    slayer_at = next(
        (i for i, entry in enumerate(skills) if entry.skill == "Slayer"), None
    )
    if slayer_at is not None and slayer_rate is not None and combat_at:
        damage = skills[slayer_at].hours * slayer_rate.xp_per_hour
        needs = {
            skill: float(skills[at].xp) for skill, (at, *_) in combat_at.items()
        }
        for skill, credited in sorted(slayer_credit(damage, needs).items()):
            if credited > 0:
                _rebuild(skill, credited + skills[combat_at[skill][0]].xp_from_combat)

    # **Hitpoints is earned by the other combat climbs, not beside them.**
    # Every point of damage paying 4 XP to Strength pays 1.33 to Hitpoints at
    # the same instant, so pricing both climbs in full bills the same hours
    # twice. Done after the loop rather than inside it because the credit
    # depends on skills that sort after `Hitpoints` - Magic, Ranged, Strength.
    if "Hitpoints" in combat_at and heuristics.combat_damage:
        at = combat_at["Hitpoints"][0]
        credit = hitpoints_credit(
            {entry.skill: entry.hours for entry in skills},
            heuristics.combat_damage,
        )
        if credit > 0:
            _rebuild("Hitpoints", credit + skills[at].xp_from_combat)
    return EstimateResult(
        unpriced_skills=tuple(unpriced_skills),
        unallocated_quest_xp=lamps,
        tasks=tuple(tasks),
        items=tuple(items),
        # **A skill already past its goal is not a row, it is noise.** `xp`
        # is what is still outstanding after the quest grant and the
        # Slayer/Hitpoints credit above are both taken off the front, so a
        # zero here means nothing this estimate can still charge for -
        # `effective_levels` reaching the target from a linked account, a
        # quest reward covering the rest, or the two crediting passes just
        # above finishing the job. Filtered here rather than in the loop
        # because the crediting passes need `combat_at`'s indices into
        # `skills` to stay valid until they are done running.
        skills=tuple(entry for entry in skills if entry.xp > 0),
        slayer=slayer_rate,
        slayer_masters=reachable_rates,
        superior_rolls=dict(walk.superior_rolls),
        superior_spawns={
            rate.master: superior_spawns_per_hour(rate, state.chunk_info, heuristics)
            for rate in reachable_rates
        },
        unpriced=tuple(sorted(unpriced)),
    )


def _item_tasks(derived: Derived) -> list[str]:
    """The active non-quest tasks: BiS picks still to get, plus Diary/Extra."""
    names = list(derived.bis.active)
    for category, tasks in derived.other_tasks.categories.items():
        if category == "Quest":
            continue
        names.extend(name for group in tasks.groups for name in group.active)
    return names


def _required_items(walk: _Walk, derived: Derived) -> dict[str, set[str]]:
    """Every item the active set needs, mapped to the tasks that want it.

    **The item is the unit of work, not the task.** One abyssal whip closes a
    BiS pick, a Slayer collection-log entry and a monster-drop log entry; you
    obtain it once. Keying on the item collapses that to a single cost and
    keeps the tasks it answers alongside, so the listing can still show why
    it is wanted.

    A BiS task names its item in its `~|...|~` span and has **no challenge
    behind it** (`bis.py` synthesises those names), so the span is the only
    handle there. Where a challenge *does* exist the span is not an item and
    must not be read as one: `~|Morytania Diary#Elite|~ Task 5` is "kill an
    abyssal demon in the Slayer Tower", and taking its span produced a
    request for an item called `Morytania Diary#Elite`, which of course had
    no route and reported as unpriced.
    """
    wanted: dict[str, set[str]] = {}
    for task in _item_tasks(derived):
        challenge = _find_challenge(walk, task)
        if challenge is None:
            wanted.setdefault(walk.resolve(activity_name(task)), set()).add(task)
            continue
        for item in _challenge_items(walk, task):
            wanted.setdefault(walk.resolve(item), set()).add(task)
    return wanted


def _required_kills(walk: _Walk, derived: Derived) -> dict[str, set[str]]:
    """Tasks that want no item, only something dead, by what has to die.

    Several diary tasks are of this shape - "kill an abyssal demon in the
    Slayer Tower", "kill Callisto, Venenatis and Vet'ion". One kill is
    cheap, but it is not free and it is not an item, and pricing it against
    the monster means the per-source clamp folds it into whatever grind that
    monster is already part of.
    """
    families = _mapping(walk.chunk_info.code_items, "monstersPlus")
    wanted: dict[str, set[str]] = {}
    for task in _item_tasks(derived):
        challenge = _find_challenge(walk, task)
        if challenge is None or challenge.get("Items"):
            continue
        for name in challenge.get("Monsters") or ():
            if not isinstance(name, str):
                continue
            members = families.get(name) if "[+]" in name else [name]
            for member in members if isinstance(members, list) else [name]:
                if isinstance(member, str) and member in walk.available:
                    wanted.setdefault(member, set()).add(task)
                    break
    return wanted


def _find_challenge(walk: _Walk, task: str) -> dict[str, Any] | None:
    for challenges in walk.chunk_info.challenges.values():
        if isinstance(challenges, dict) and isinstance(challenges.get(task), dict):
            found: dict[str, Any] = challenges[task]
            return found
    return None


def _challenge_items(walk: _Walk, task: str) -> list[str]:
    for challenges in walk.chunk_info.challenges.values():
        if not isinstance(challenges, dict):
            continue
        challenge = challenges.get(task)
        if isinstance(challenge, dict):
            return [
                item.replace("*", "")
                for item in challenge.get("Items") or ()
                if isinstance(item, str)
            ]
    return []
