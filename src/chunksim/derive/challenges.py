"""Which challenges (tasks) are valid, given the unlocked chunks' sources.

Port of the core of `calcChallenges`/`calcChallengesWork` (worker.js): a
fixed point over 28 of the 29 challenge categories - all but `BiS`. Each
challenge's `Chunks`/`Items`/`Objects`/`Monsters`/`NPCs`/`Skills`/`Tasks`
requirements are checked against the source index (`sources.py`) and the
running set of already-valid challenges; a valid challenge with an `Output`
feeds back as a new item source, so another pass may unlock further
challenges - repeating until nothing changes.

**`BiS` is never evaluated *here*, but it is computed - by `bis.py`, not
this module.** Unlike the other 28 categories, `BiS` challenges have no
static definition anywhere in `chunkinfo.json` - `challenges.BiS` doesn't
exist in the export at all, so it shares no structure with the
requirement-checking this module does for every other category (upstream's
`calcBIS` compares the `equipment` table's combat stats across weapon/armour
slots per combat style instead - see `bis.py`'s module docstring for the
full port). `UNSUPPORTED_CATEGORIES` and the `skill in UNSUPPORTED_CATEGORIES`
skip below exist only to guard against a hypothetical/malformed export that
*does* carry a literal `challenges.BiS` branch: presence-checking it with
this module's generic engine would produce nonsense (real BiS validity isn't
a presence check at all), so it's skipped rather than silently mis-evaluated.
Callers wanting BiS should read `pipeline.Derived.bis`, not
`ChallengeResult.valid['BiS']`, which this module never populates.

Scope: `calcChallengesWork` is ~1,500 extremely dense lines. What's implemented, and what isn't,
below.

Implemented:
- `Chunks`/`Objects`/`Monsters`/`NPCs`/`Mix` requirements: full presence
  checking, including `[+]` family matching (`objectsPlus`-style groups,
  ported via `chunkinfo.json`'s `codeItems`) and `[+]xN` "at least N of"
  counting for `Chunks`. `Monster[+]` has no family table and is a
  **wildcard** meaning "any monster at all" (`_ANY_MEMBER_FAMILIES`,
  worker.js:4306) - treating it as an ordinary family made `Cast ~|wind
  strike|~`, Magic's only Level 1 `Primary` route, permanently invalid.
- **Untrainable skills are pruned to their `Level 1` challenges**
  (`_prune_untrainable_skills`, worker.js:1521): if `checkPrimaryMethod` says
  a skill can't be trained here and no `passiveSkill` floor covers it, every
  challenge above Level 1 is discarded. This is how upstream locks a skill
  behind a quest - `Herblore` needs `Unlock ~|Herblore|~ after Druidic
  Ritual`, and while that quest is out of reach the skill keeps nothing.
- `Items` requirements: presence checking, including `[+]`/`[+]xN` family
  matching via `codeItems.itemsPlus`, and `AllowedSources`/`NonShop`
  filtering. The `*` secondary marker does **not** gate validity directly -
  verified against upstream (worker.js:4046,4064) - but it sets a `Secondary`
  flag with three consequences, and **the one that matters is now ported**:
  `checkPrimaryMethod` requires `Primary && !Secondary` (worker.js:5135), so
  a method whose consumed ingredient is only somebody else's by-product does
  not make its skill trainable. `_is_secondary` computes the flag and
  `_has_primary_task` applies it. The other two stay unported and are inert:
  a `forcedPrimary` gate with **zero** real-export uses (worker.js:4433), and
  the `primary-`/`secondary-` split on seeded `Output` items
  (worker.js:3024-3041), which `_seed_items_with_outputs` flattens and which
  provably cannot move `_source_quality_ok`. See those functions. For
  combat skills and challenges whose `Category` includes `BIS Skilling`, an
  item sourced *only* from another skill's crafted output is additionally
  rejected unless `Not Equip`/`Wield Crafted Items`/a Slayer source/the
  requiring skill being Magic excuses it - see `_source_quality_ok`.
- `Skills` requirements: the sub-skill must be *trainable*, via
  `_check_primary_method` - a port of upstream's `checkPrimaryMethod` over
  its `universalPrimary` table (a `Primary`-flagged valid challenge at an
  attainable level, or any monster, or bones, or a usable ammo/launcher
  pair, or - for `Combat` - any combat skill being trainable). This replaced
  a much looser "the skill has *a* valid entry" stand-in, which reported
  `Combat` untrainable on every real map (it has 14 challenges, all needing
  specific chunks) and so silently invalidated every Slayer-master
  assignment and everything gated behind them.
- `Tasks` requirements (a challenge needing specific *other* challenges
  already valid), including `[+]`/`[+]xN` families via `codeItems.tasksPlus`.
  Lookups consult the previous pass as well as the partially-built current
  one: categories are iterated in the export's own key order, so a
  dependency pointing "backwards" (`Nonskill` at index 16 needing `Slayer`
  at 21) would otherwise never resolve at all, since `new_valid` is rebuilt
  from scratch each pass.
- `MaxSkill`/`Not F2P`/`Not Skiller` gates, and the general category-rule
  gate (a `Category` naming a rule that's off invalidates the challenge,
  unless the category is in `maybePrimary` or is the `Secondary Primary`
  special case) plus the `InsidePOH Primary` category's hard block.
- The `processingSkill` categories' (Runecraft, Magic, Herblore, Cooking,
  Firemaking, Fletching, Smithing, Crafting, Construction) "Highest Level"
  grouping (`_group_processing_skill_challenges`, worker.js:4413-4680):
  **when `rules['Highest Level']` is off**, a challenge that consumes an
  available ingredient is valid only if it is the *lowest*-`Level`-consumer
  of at least one such ingredient (e.g. smelting a bronze bar lets you smith
  a bronze dagger, not simultaneously every higher-tier bronze item) - not
  "surface only the highest", the docstring here previously had this
  backwards. **When the rule is on** (true of the map this was built
  against), every consumer is valid, matching the plain per-challenge
  checking above with no grouping needed.

Not implemented - each raises `NotImplementedError` naming the mechanic,
except where noted as a silent, documented approximation instead:
- `QuestPointsNeeded`/`CombatPointsNeeded`/`KudosNeeded`/`TotalLevelNeeded`/
  `CombatLevelNeeded` gates: correctly computing those aggregates needs
  state (quest points earned, kudos, etc.) this module does not derive.
  Rare in the export (single digits to low tens of challenges; 42 on the
  map this was built against, all of them one of these five gates).
- **Silent approximation, not a raise**: the "Highest Level" grouping above
  doesn't model upstream's `tools`/`ManualNonProcessing`/Quest-Diary-sub-task
  direct-add escapes, its `Boosting` level-shift, its multi-pass re-pick
  after `Tasks`/`Skills` pruning, or the `nonskill` chain-flattening that
  lets a group's own `Items` re-expand mid-walk. It also runs once, after
  the fixed point converges, rather than feeding grouped-out challenges'
  `Output` back out of `_seed_items_with_outputs` - so item-seeding can be
  mildly over-inclusive relative to the final grouped `valid`.
- **`Multi Step Processing` is unported, and it is not the "requirement"
  an earlier version of this note called it.** It is *permissive*, and it
  has two halves. Upstream does not put a valid processing recipe with a
  non-tool ingredient into `valids` at all: it defers it into
  `tempItemSkill[skill][item]` (worker.js:4444/4557), to be re-picked later
  by whichever `Highest Level` branch applies (worker.js:1875 on, 1906 off).
  With the rule on, every such deferred recipe's `Output` is then published
  into the item index under a `multi-<skill>` tag (worker.js:3576) so a
  *further* recipe can chain off something not yet actually reachable - and
  the second half is the safety valve for that: a combat-skill challenge
  without `Not Equip`, or any `Extra` one, is refused when every source of an
  ingredient it consumes is one of those speculative tags (worker.js:3956).
  Neither half is here, and neither can be until the deferral is. This module
  keeps those recipes in `valid` throughout - 940 of them on the second
  cached map and 726 on the first, 616 and 611 of which carry an `Output` -
  so their outputs are seeded unconditionally, which lands nearer the rule
  being *on* than off, and there is no `multi-` tag for the gate to test. The
  deferral is a change to this module's core loop rather than an addition to
  it, which is why it is recorded here rather than half-built.

  **A shortcut was tried and the oracle refused it**, which is worth knowing
  before anyone tries the same one. Tagging every processing recipe's seeded
  `Output` `multi-<skill>` and adding the gate on top looks like it buys the
  second half without the deferral, and it does not: upstream's grouping fork
  *re-adds* the recipes it picks (worker.js:1875 with `Highest Level` on,
  1906 with it off), and a re-added recipe is back in `valids` and seeded
  `primary-` like anything else. Only the ones the fork **drops** stay
  speculative. Tagging them all made `Obtain a ~|regen bracelet|~` read as
  reachable-only-by-a-maybe and cost the BiS oracle a pick. With
  `Highest Level` on - as it is on both cached maps - the fork drops nothing,
  so the correct answer there is that *no* tag is `multi-` and the gate never
  fires. Which is to say: the gate cannot be exercised by either cached map,
  and the deferral is not optional groundwork for it but the whole of it.
- Mahogany Homes *is* handled - see `_MAHOGANY_HOMES_CONTRACT`, the Max Cape
  and Quest Point Cape injections are now `derive/injected.py`, the Collection
  Log Clues threshold is `_clue_reward_gate_met`, and the **Slayer lock** is
  too: its level cap arrives folded into `max_skill` and its equipment half
  as `_compile_items`' `locked_equipment`, both from
  `pipeline.slayer_capped_max_skill`/`slayer_locked_equipment`. Shortcut
  Task / Combat and Teleport Spells / Cleaning Herbs only ever set
  `NeverShow` upstream, a display-only panel filter that never affects
  validity - so it stays out of this module, but it is *not* unused: it
  gates the active-task pick, and `active_tasks._never_show` recomputes it
  there (nothing sets it statically in the export).
- `userTasks` (the other manual override) is not applied; it is empty in
  real data. `manualTasks` **is** applied - see `_inject_manual_tasks`. An
  earlier version of this docstring claimed both were deliberately skipped
  because a simulated roll has no such history to replay; that reasoning
  holds for `simulate.py` but not for deriving the *current* map, where
  ignoring `manualTasks` hid two `Extra` entries the map's own oracle lists.

The fixed point runs in **two phases**, and both halves are load-bearing. The
first converges with the *trainability* prunes switched off, so trainability
is decided from a fully seeded item index; from the second outer pass
`_prune_untrainable_skills` and `_drop_unreachable_subskills` join the inner
loop, and the item index is re-seeded from the pruned `valid` each time.
(`_inject_manual_tasks` and `_drop_superseded_backups` are not phase-gated -
they run every inner pass throughout, neither one depending on trainability.)

- Pruning from the *start* starves the seeding: deciding trainability from a
  half-seeded index prunes a skill whose own `Output` chain would have made
  it trainable, and the next pass then settles on the wrong fixed point. It
  broke `Magic`, and with it the BiS oracle's `Master wand`.
- Pruning only *after* convergence leaves a removed challenge's `Output` on
  the shelf: a locked `Herblore` still supplied `Blamish oil`, which kept
  `Make an oily fishing rod` valid and a Wilderness diary task active - 57
  items stayed keyed to challenges that were no longer valid.

Pruning only ever removes, so the loop still terminates.

Also implemented, beyond the requirement checking above:

- **`BackupParent`** (`_drop_superseded_backups`, worker.js:1679): a
  challenge naming one is deleted once that parent is valid *or* backlogged,
  unless it carries `ManualValid`. All 17 real uses are `Hunter`'s barehanded
  catches - `Barehanded catch a wandering lucky impling` (Level 99) exists
  for players with no butterfly net and must vanish once the Level 89 net
  version is possible; instead it outranked its own parent and became the
  active Hunter task. **This is the module's one *absence* check**, so
  `valid` no longer strictly grows - 11 challenges disappear on the real map
  once a net is reachable. See `unlock.py` for what that costs the
  attribution partition.
- **`Set`/`Priority`** (`_drop_outclassed_extra_sets`, worker.js:1514): an
  `Extra` `Set` is one slot's interchangeable ladder - `BIS Axe` runs bronze
  to infernal - and only `BIS Skilling` challenges carry it, 63 across 15
  sets. Unswept, the whole ladder stays valid and a player holding an
  infernal axe is still told to obtain the steel one: 19 of the second real
  map's 20 outstanding `BIS Skilling` tasks. **The oracle map has the rule
  off**, so no `Set` challenge is valid there and none of its pinned `Extra`
  counts could ever have caught this. Note upstream's sweep keeps the
  running *minima* rather than the single best, by way of a real bug in it
  that the function's docstring sets out - and the export contains sets
  where the two differ.
- **The `Collection Log Clues` threshold** (`_clue_reward_gate_met`,
  worker.js:3790): the rule has two halves and only the category one was
  here. On, a reward task still waits until the share of its `ClueRewardTier`
  the map can actually reach clears `Collection Log Clues Amount` - and at
  the shipped default of `"100"` that means *every* step of the tier. The
  measurement (`_clue_tasks_possible`) is a per-pass function of `Nonskill`
  validity, which is why the gate sits on the dynamic side though upstream
  writes it beside the category check. Turning the rule on used to add 519
  `Extra` tasks on the second real map and now adds none, the best tier there
  being 27% reachable.
- **The `maybePrimary` downgrade** (`_effective_primary`, worker.js:3678):
  `Normal Farming`, `Sulphurous Fertiliser`, `Shortcut` and `InsidePOH
  Primary` are "methods that are only primary if their respective rule is
  checked". The same four are exempt from the ordinary category gate, which
  is the *other* half of that sentence and was the only half implemented -
  so with `Shortcut` off, 638 challenges kept a `Primary` flag the rule had
  taken away. Turning it off on the oracle map now drops 177 challenges
  (Agility loses its only training route) where it used to drop none.
- **`Secondary MTA`** (`_FORCED_PRIMARY`, worker.js:3605, checked at 4433):
  the rule writes `forcedPrimary` onto one named Magic challenge, and a
  `forcedPrimary` challenge whose ingredients are all somebody else's
  by-products is invalid. Nothing in the export carries `forcedPrimary`,
  which is why this was recorded as inert - upstream sets it at runtime.
- **`Smithing by Smelting`** (`_check_primary_method`, worker.js:5226): with
  the rule off, a `manualTasks` Smithing entry only proves Smithing
  trainable if an anvil is actually reachable. The seeded object index is
  what answers that, since `Build an ~|anvil (amenity)|~` outputs one.
- **`manualTasks`** (`_inject_manual_tasks`, worker.js:1168): every entry the
  export still defines is forced valid with its stored value, for every
  category but `BiS`, and is exempt from the `BackupParent` sweep the way
  upstream's `ManualValid` flag makes it.
- **The `Show Diary Tasks Any` waiver** (`_diary_tier_waived`,
  worker.js:1360): a diary tier's completion challenge is marked by carrying
  a `Reward`, and the next tier's tasks depend on it. With that rule on the
  dependency is dropped, so an Elite task shows without the Hard diary being
  finished - the dependent must carry no `Reward` itself, or the tiers
  collapse into each other. This was the whole of the Diary gap: outstanding
  Diary tasks went 1 -> 5 against the map's own oracle.
- **The non-skill `Skills` filter** (`_drop_unreachable_subskills`,
  worker.js:8533): for `Extra`/`Quest`/`Diary`/`BiS` - the categories
  `calcCurrentChallenges2` sends down its `else` branch, having no per-skill
  winner to pick - a challenge is dropped when its `Skills` names a sub-skill
  that is untrainable *and* uncovered by a boosted `passiveSkill` floor, or
  whose requirement exceeds `maxSkill`. `manualTasks` entries are exempt. It
  changes nothing on the map this was built against, every sub-skill named
  there being trainable and within `maxSkill`.
- **`chunkinfo.constructionLocked`** (`_MAHOGANY_HOMES_CONTRACT`,
  worker.js:3758): when set - real data has `{'chunk': '10547'}` - every
  challenge whose name contains `contract for ~|Mahogany Homes|~` is invalid
  outright, Mahogany Homes being gated behind a chunk the account hasn't
  taken. Missing it made `chunksim tasks` propose an expert contract as the
  Construction goal.

`_seed_items_with_outputs` is the output-feedback half of the fixed point,
and is a located port (worker.js:2848/2894/3030) rather than this project's
own invention, as an earlier version of this docstring recorded it: a valid
challenge's `Output` becomes an item, *and* doubles as the activity key into
`skillItems[<that skill>]`, admitting everything that activity yields. That
second half is the only route to non-Slayer `skillItems` - `Master wand`
exists solely in `skillItems.Nonskill['Pizazz points loot']`, reached via the
`~|Pizazz points|~*` challenge's `Output`. (`sources.py` handles the *other*
`skillItems` route, a Slayer monster physically present in a chunk.)
`backloggedSources['items']` is honoured here as upstream does, and it isn't
cosmetic: a backlogged `Uncut onyx` otherwise re-enters at a 1/100,000,000
rate and drags an entire crafting chain in with it.
`_seed_objects_with_outputs` is the same feedback for `Output Object`
(worker.js:3036-3045, merged at 3255-3262) - the furniture, braziers, patches
and salvaging hooks a valid challenge *builds*. It was unported, and what it
cost was a whole skill: all seven `Build a ~|<tier>|~ salvaging hook|~`
challenges declare one, all eight shipwrecks require `AnySalvagingHook[+]`,
and with no seeding a map could build every hook in the game and hold none.
On an all-chunks map it is worth **+166 valid challenges, +44 Sailing and +33
items**; on both cached maps validity is byte-identical and one object
(`Player fire`) is added. Simplified - everything
is tagged `primary-` rather than split by drop rate, and the `Rare Drop
Amount` filter on an activity's items isn't applied; the `bossLogs` gate is.
Upstream splits that tag on the challenge's `Secondary`/`ForcedSecondary`
flags as well as on rate (worker.js:3024-3041), which this flattening also
drops. **Checked, and it cannot change an answer here**: the only consumer of
those tags is `_source_quality_ok`, which rejects any tag whose suffix is a
real skill name and so reads `primary-Cooking` and `secondary-Cooking`
identically. The one case that would differ is upstream tagging
`secondary-<Source>` where `Source` is not a skill name, which passes that
gate where `primary-<skill>` fails; no real-export instance has been looked
for. `active_tasks.py`'s docstring records the same flattening from the
`ForcedSecondary` side.

**How the fixed point is evaluated, and why it is shaped that way.** This
module is where every derivation command spends its time - measured on the
real export, `calc_challenges` was ~2.5s of `derive`'s 2.7s - so the loop's
structure is load-bearing, not incidental. A challenge's requirements split
cleanly in two:

- `_static_gates_met` - level/unsupported, `Category`, `Chunks`,
  `Monsters`/`NPCs`, `Mix`. Every input (`rules`, `max_skill`, `chunk_ids`,
  `reachable_sections`, the monster/npc indexes) is fixed for the whole
  `calc_challenges` call, so **nothing the fixed point does can change the
  answer**. Run once, up front, as a candidate filter: on the real export it
  takes 14,692 challenges down to 5,935 - the loops used to re-derive those
  8,757 rejections on all nine-to-twelve sweeps.
- `_dynamic_gates_met` - `Items`, `Skills`, `Tasks`, which read the item index
  the loop keeps re-seeding and the validity being computed. These must stay
  inside.
- `_objects_requirement` - **`Objects`, which is neither**, and this is the
  one place the split is three-way rather than two. Its index moves too, now
  that `Output Object` is seeded, so the gate cannot stay static; but moving
  it wholesale into the sweeps would put 1,631 presence checks back on every
  one of them for the sake of the handful that can actually change. So it is
  decided against the *base* index and only deferred where a `seedable`
  object is what is missing - sound because seeding only ever adds, so a met
  requirement stays met and an unmeetable one stays unmeetable. Measured, the
  deferral changes neither cached map's runtime (0.88s -> 0.85s on the
  reference map).

`_ItemPlan`/`_compile_items` carry the same idea one level down: an `Items`
requirement's *parsing* (`*` stripping, `[+]` detection, `itemsPlus` family
resolution - 7,569 refs on the real export) is static, while the index it is
checked against is not, so the parse happens once per challenge and only the
check repeats. `_items_requirement_met` is that same compile-then-check, kept
as the single-challenge entry point so there is one statement of the
semantics rather than two.

Two smaller things follow the same rule of "decide it where it cannot change":
`_quality_flags` lifts the source-quality gate's per-challenge terms into the
plan, and `_tasks_requirement_met` asks two dictionaries rather than building
the merged one it used to (membership in `{**a, **b}` is membership in either,
and that merge ran ~300,000 times a derivation over categories reaching 878
entries - 20x the cost of asking both).

All of these are pure hoists: the predicates, their arguments and their order
are unchanged, and the whole point is that they are *provably* unable to alter
the result. Verified as such at every step - the real map's full derivation is
byte-identical throughout, and the opt-in oracles still pass. Together they took
`derive` from 2.68s to ~0.76s.

What is *not* done: warm-starting this fixed point from a previous `valid`
instead of from `{}`. This file used to call that "by far the largest
remaining win" and refuse it on safety grounds. **Both halves of that were
wrong, and the measurement is the interesting half.**

It is not a win at all. Built and measured against a real map, seeding `valid`
made `derive` 0.730s -> 0.803s - a 9% *loss*. Nothing about a seed reduces the
work: `new_valid` is rebuilt from the whole candidate list on every sweep
regardless of where it starts, so a seed cannot remove a candidate, only
change the trajectory - while making the first sweep's `_seed_items_with_outputs`
larger. The sweep count barely moves. (The ~2x available to a simulation is
`pipeline.derive`'s `carry_areas`, which is a different thing: it seeds the
*area* loop, whose passes each cost a full `calc_challenges`.)

Nor is it as fragile as the refusal implied. Seeded with every one of the
14,694 challenges - maximally wrong - it still converged on exactly the cold
answer, and over 24 real rolls across both cached maps it never once differed.
The reason is structural: the `Tasks` dependency graph is **acyclic** (0 cycles
among the 4,831 challenges carrying `Tasks`), so a spuriously seeded task has
nothing to support it and disappears on the next sweep.

The non-monotonicity is real - `_drop_superseded_backups` *removes* a
barehanded-catch challenge once the method it backs up becomes valid, so more
validity can mean less - and it is why the usual "monotone operator from below"
argument does not apply. It is just not what makes warm-starting a bad idea.
Being pointless is.

`strip_task_markup` lives here too, the display-side counterpart to
`search.normalise`: it drops a task name's `~|...|~` delimiters without
lowercasing or collapsing anything. It is *only* for output - the raw names
stay the keys everywhere (`valid`, `completedChallenges` lookups,
`--export-json`), since those must match what upstream stores. It removes the
delimiter **characters**, not the `~|`/`|~` pairs: four real names are
malformed (`Carve a ~log |canoe|~` has its opening `|` four characters late)
and pair-stripping left the visible wreckage `Carve a ~log |canoe`.
Character-stripping renders those correctly and is byte-identical on all
14,688 well-formed names, where neither `~` nor `|` occurs outside this
markup. **Only call it on a challenge/task name** - other branches use those
characters for real (the shop `~ Uglug's stuffsies ~`), which is why
`cli.py`'s `search` applies it per hit type rather than blanket. It
deliberately leaves the `#` variant separator (`~|wooden hull#Raft|~`) and
the trailing `*` secondary marker alone: both are real parts of the stored
name, and how upstream renders them isn't something this project has located.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass, field
from typing import Any

from chunksim.derive import boosts
from chunksim.model.chunkinfo import ChunkInfo
from chunksim.model.rates import build_clue_complete_num
from chunksim.derive.sources import SourceIndex, apply_item_task_unlocks
from chunksim.model.summary import _mapping

#: index.js:1017's `maybePrimary`, verbatim: "methods that are only primary
#: if their respective rule is checked". The list does double duty upstream
#: and does the same here - `_category_gate_met` exempts these categories
#: from the ordinary rule gate, and `_effective_primary` applies the rule to
#: the `Primary` flag instead.
_MAYBE_PRIMARY = frozenset({"Normal Farming", "Sulphurous Fertiliser", "Shortcut", "InsidePOH Primary"})


#: The one challenge upstream ever sets `forcedPrimary` on (worker.js:3605).
#: Nothing in the export carries the field.
_FORCED_PRIMARY = ("Magic", "Participate in all parts of the ~|Magic Training Arena|~")

#: Categories `calc_challenges` never evaluates - their absence from
#: `ChallengeResult.valid` means "not computed", not "nothing is valid".
#: See the module docstring for why `BiS` specifically is out of scope.
UNSUPPORTED_CATEGORIES = frozenset({"BiS"})

_PROCESSING_SKILLS = frozenset(
    {"Runecraft", "Magic", "Herblore", "Cooking", "Firemaking", "Fletching", "Smithing", "Crafting", "Construction"}
)

#: index.js's `skillNames`/`combatSkills` - every real skill category, and
#: the 7 combat ones. Used by `_source_quality_ok`'s source-tag check.
_SKILL_NAMES = frozenset(
    {
        "Slayer", "Thieving", "Attack", "Defence", "Strength", "Hitpoints", "Ranged",
        "Prayer", "Magic", "Farming", "Herblore", "Hunter", "Cooking", "Woodcutting",
        "Firemaking", "Fletching", "Fishing", "Mining", "Runecraft", "Sailing",
        "Smithing", "Crafting", "Agility", "Construction", "Combat",
    }
)
_COMBAT_SKILLS = frozenset({"Attack", "Strength", "Defence", "Hitpoints", "Ranged", "Magic", "Prayer"})

#: Appended to a task obtained during the chunk in play - one still sitting
#: in `checkedChallenges`, not yet migrated into `completedChallenges` by the
#: next roll. Shared by `bis.py` and `other_tasks.py` so the two panels mark
#: the same thing the same way.
CURRENT_CHUNK_SUFFIX = "(Active)"


#: Substring upstream matches a challenge name against when
#: `chunkinfo.constructionLocked` is set (worker.js:3758) - Mahogany Homes is
#: gated behind a specific chunk the player hasn't taken, so every contract
#: tier is invalid regardless of its own requirements. Matched as a plain
#: substring against the *raw* (markup-carrying) name, exactly as upstream does.
_MAHOGANY_HOMES_CONTRACT = "contract for ~|Mahogany Homes|~"

#: `[+]` names upstream treats as "any member of the index will do" when the
#: `codeItems` family table has no entry for them, rather than as an
#: unsatisfiable requirement. Only `Monster[+]` gets this in worker.js.
_ANY_MEMBER_FAMILIES = frozenset({"Monster[+]"})

_LEVEL_GATES_NOT_SUPPORTED = (
    "QuestPointsNeeded",
    "CombatPointsNeeded",
    "KudosNeeded",
    "TotalLevelNeeded",
    "CombatLevelNeeded",
)


@dataclass(frozen=True)
class ChallengeResult:
    """`valid[skill][name]` mirrors upstream's `globalValids` value shape:
    the challenge's `Level`, or its `Label`, or bare `True` if neither
    exists - `True` always for `Quest`/`Diary`, matching upstream exactly.

    `unsupported` lists every `skill/name` challenge that could not be
    evaluated at all (it uses a mechanic this module doesn't implement, e.g.
    an item family or the `*` secondary marker) - such a challenge is never
    valid here, which is a real gap, not a probably-harmless one: report
    `unsupported` alongside `valid` rather than silently treating an absence
    from `valid` as "checked and invalid".

    `available_items` is `SourceIndex.items` plus every valid challenge's
    `Output` (the fixed point's own `_seed_items_with_outputs` result, at
    the pass matching `valid`). It is what downstream consumers wanting "what
    can I actually get" should read - `SourceIndex.items` alone omits
    anything only obtainable by *making* it, e.g. `Granite ring (i)`, which
    exists solely as the output of an imbue challenge. Deliberately excluded
    from `as_dict`: it's a pipeline artifact (thousands of entries), not part
    of the user-facing task result.

    `available_objects` is the exact twin for `Output Object` - the furniture,
    braziers, patches and salvaging hooks a valid `Build`/`Light`/`Plant`
    challenge *makes* - and exists for the same reason: `SourceIndex.objects`
    holds only what an unlocked chunk already contains, so on the real export
    it has none of the 94 objects the map can build. Read it, not
    `SourceIndex.objects`, when the question is "what can I stand in front
    of". Excluded from `as_dict` on the same grounds.
    """

    valid: dict[str, dict[str, int | str | bool]]
    unsupported: frozenset[str]
    available_items: dict[str, dict[str, str]] = field(default_factory=dict)
    available_objects: dict[str, dict[str, Any]] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"valid": self.valid, "unsupported": sorted(self.unsupported)}


def contains_sections(chunk_str: str) -> bool:
    """Port of `containsSections`: does `chunk_str` look like `NUM-SECTION`
    (a plain number, or a plain number, or `W` followed by one)?
    """
    base, sep, section = chunk_str.partition("-")
    if not sep or not _looks_numeric(base):
        return False
    if _looks_numeric(section):
        return True
    return section.startswith("W") and _looks_numeric(section[1:])


def _looks_numeric(value: str) -> bool:
    try:
        float(value)
    except ValueError:
        return False
    return True


def only_shop(sources: Mapping[str, str]) -> bool:
    """Port of `onlyShop`: are every one of `sources`'s tags `'shop'`?"""
    return all(tag == "shop" for tag in sources.values())


def has_allowed_source(sources: Mapping[str, str], allowed_sources: Any) -> bool:
    """Port of `hasAllowedSource`: no restriction, or at least one of
    `sources`'s *keys* (source names) is in `allowed_sources`.
    """
    if not isinstance(allowed_sources, list) or not allowed_sources:
        return True
    return any(source in allowed_sources for source in sources)


def _chunk_reachable(
    chunk_ref: str, chunk_ids: Mapping[str, bool], reachable_sections: Mapping[str, Mapping[str, bool]]
) -> bool:
    if not contains_sections(chunk_ref):
        return chunk_ref in chunk_ids
    base, _, section = chunk_ref.partition("-")
    return base in chunk_ids and bool(reachable_sections.get(base, {}).get(section))


def _plus_family(chunk_info: ChunkInfo, key: str, name: str) -> list[str] | None:
    family = _mapping(chunk_info.code_items, key).get(name)
    return family if isinstance(family, list) else None


def chunks_requirement_met(
    challenge: Mapping[str, Any],
    chunk_ids: Mapping[str, bool],
    reachable_sections: Mapping[str, Mapping[str, bool]],
    chunk_info: ChunkInfo,
) -> bool:
    chunk_refs = challenge.get("Chunks")
    if not isinstance(chunk_refs, list):
        return True
    for chunk_ref in chunk_refs:
        if not isinstance(chunk_ref, str):
            continue
        if "[+]" in chunk_ref:
            base_name, marker, count_str = chunk_ref.partition("[+]x")
            family_name = f"{base_name}[+]" if marker else chunk_ref
            family = _plus_family(chunk_info, "chunksPlus", family_name)
            if family is None:
                return False
            matches = sum(1 for ref in family if _chunk_reachable(ref, chunk_ids, reachable_sections))
            needed = int(count_str) if marker else 1
            if matches < needed:
                return False
        elif not _chunk_reachable(chunk_ref, chunk_ids, reachable_sections):
            return False
    return True


def _presence_requirement_met(
    challenge: Mapping[str, Any],
    field: str,
    index: Mapping[str, Mapping[str, Any]],
    chunk_info: ChunkInfo,
    plus_key: str,
) -> bool:
    names = challenge.get(field)
    if not isinstance(names, list):
        return True
    for name in names:
        if not isinstance(name, str):
            continue
        if "[+]" in name:
            family = _plus_family(chunk_info, plus_key, name)
            if family is None:
                # A `[+]` name with no family table is normally a dead
                # requirement, except `Monster[+]`, which upstream reads as
                # the wildcard "any monster at all" (worker.js:4306-4317).
                # Missing this made `Cast ~|wind strike|~` - Magic's only
                # Level 1 `Primary` route on the real map - permanently
                # invalid, so `checkPrimaryMethod` called Magic untrainable.
                if name in _ANY_MEMBER_FAMILIES and index:
                    continue
                return False
            if not any(member in index for member in family):
                return False
        elif name not in index:
            return False
    return True


def _seedable_objects(challenges: Mapping[str, Mapping[str, Any]]) -> frozenset[str]:
    """Every object any challenge in the export can *build*, whether or not
    that challenge is reachable here.

    This is a property of the export rather than of a map, so it is what makes
    the `Objects` gate splittable: an object outside this set can never arrive
    during a `calc_challenges` call, so its absence is as static as it ever
    was. 94 objects across 138 challenges - Construction 85, Sailing 24,
    Firemaking 16, Farming 12, Nonskill 1.
    """
    seedable: set[str] = set()
    for skill_challenges in challenges.values():
        if not isinstance(skill_challenges, dict):
            continue
        for challenge in skill_challenges.values():
            if isinstance(challenge, dict):
                output = challenge.get("Output Object")
                if isinstance(output, str):
                    seedable.add(output)
    return frozenset(seedable)


def _objects_requirement(
    challenge: Mapping[str, Any],
    objects: Mapping[str, Mapping[str, Any]],
    chunk_info: ChunkInfo,
    seedable: frozenset[str],
) -> bool | tuple[tuple[str, ...], ...]:
    """`Objects` decided against the *base* index, three ways: `True`, `False`,
    or the groups whose answer has to wait for the seeding.

    `_presence_requirement_met` is the two-way version and stays that for
    `Monsters`/`NPCs`, whose indexes really are fixed for the call. Objects
    are not - `_seed_objects_with_outputs` adds to them mid-fixed-point - but
    the split survives intact, because seeding only ever *adds*:

    - a requirement the base index already meets can never stop being met, so
      it is decided `True` once, exactly as before;
    - a requirement it does not meet, whose unmet names are none of them
      `seedable`, can never come to be met, so it is decided `False` once;
    - only what is left needs re-checking per sweep, and only against the
      groups returned here rather than the whole requirement.

    On the real export 621 of the 1,631 `Objects`-carrying challenges name a
    seedable object, and almost all of those are anvils, furnaces and cooking
    ranges a map either has from the start or does not - so what actually
    defers is a handful. That is the whole reason this is a tri-state rather
    than "move `Objects` into the dynamic half", which would have put 1,631
    presence checks back on every one of the nine-to-twelve sweeps.
    """
    names = challenge.get("Objects")
    if not isinstance(names, list):
        return True
    deferred: list[tuple[str, ...]] = []
    for name in names:
        if not isinstance(name, str):
            continue
        if "[+]" in name:
            family = _plus_family(chunk_info, "objectsPlus", name)
            if family is None:
                # Same reading as `_presence_requirement_met`: a `[+]` name
                # with no family table is a dead requirement bar the wildcard,
                # and no amount of seeding gives it members.
                if name in _ANY_MEMBER_FAMILIES and objects:
                    continue
                return False
            members = tuple(member for member in family if isinstance(member, str))
            if any(member in objects for member in members):
                continue
            if any(member in seedable for member in members):
                deferred.append(members)
                continue
            return False
        if name in objects:
            continue
        if name in seedable:
            deferred.append((name,))
            continue
        return False
    return tuple(deferred) if deferred else True


def _objects_met(groups: tuple[tuple[str, ...], ...], objects: Mapping[str, Mapping[str, Any]]) -> bool:
    """The deferred half of `_objects_requirement`, per sweep: every group
    needs one member present in the seeded index.
    """
    return all(any(member in objects for member in group) for group in groups)


def _mix_requirement_met(
    challenge: Mapping[str, Any],
    monsters: Mapping[str, Mapping[str, Any]],
    npcs: Mapping[str, Mapping[str, Any]],
    chunk_info: ChunkInfo,
) -> bool:
    names = challenge.get("Mix")
    if not isinstance(names, list):
        return True
    for name in names:
        if not isinstance(name, str):
            continue
        if "[+]" in name:
            family = _plus_family(chunk_info, "mixPlus", name)
            if family is None or not any(member in monsters or member in npcs for member in family):
                return False
        elif name not in monsters and name not in npcs:
            return False
    return True


def _item_source_ok(
    sources: Mapping[str, str] | None, non_shop: bool, allowed_sources: Any
) -> bool:
    if sources is None:
        return False
    if non_shop and only_shop(sources):
        return False
    return has_allowed_source(sources, allowed_sources)


def _effective_primary(challenge: Mapping[str, Any], rules: Mapping[str, Any] | None) -> bool:
    """Is this challenge a *primary* way to train its skill, once the rules
    have had their say? Port of worker.js:3678-3684.

    A challenge in a `_MAYBE_PRIMARY` category is only primary while that
    category's rule is on: with `Shortcut` off, an agility shortcut stops
    counting as a way to train Agility, and `checkPrimaryMethod` can go on to
    call the whole skill untrainable. 638 export challenges carry both a
    truthy `Primary` and one of these categories, so the downgrade is not a
    corner - it was simply never applied here, and every read of the flag saw
    the export's raw value.

    Upstream does this by **mutating the export** (stashing the untouched
    value in `OriginalPrimary` so re-runs stay idempotent), which this module
    cannot do: the parsed export is shared across processes and must stay
    read-only. Computing the answer per read is equivalent and needs no
    `OriginalPrimary`.

    Upstream assigns inside a `forEach`, so with two `_MAYBE_PRIMARY`
    categories on one challenge the **last** wins rather than both applying.
    That is reproduced rather than reconciled, though it cannot fire: no
    export challenge carries more than one.

    **`rules=None` is not `rules={}`.** An empty ruleset is a real ruleset
    that happens to say no to everything, and upstream reads it that way -
    `rules[category]` is `undefined`, so the flag is downgraded (see
    `model.rules` on why absent is never neutral). `None` is the different
    statement "no ruleset was available here", which is what a caller
    reconstructing a panel from the roll ledger has, and it leaves the
    export's own flag alone rather than guessing.

    `costing/` still reads the raw `Primary` flag. That is a separate
    question - what a task *costs* to train - and those modules are this
    project's own work rather than a port, so they are left alone here.
    """
    if rules is None:
        return challenge.get("Primary") is True
    primary = challenge.get("Primary") is True
    categories = challenge.get("Category")
    if not isinstance(categories, list):
        return primary
    for category in categories:
        if category in _MAYBE_PRIMARY:
            primary = rules.get(category) is True and challenge.get("Primary") is True
    return primary


def _quality_flags(
    skill: str, challenge: Mapping[str, Any], rules: Mapping[str, Any]
) -> tuple[bool, bool]:
    """`(applies, waived)` for the source-quality gate.

    Both are properties of the challenge, the requiring skill and the rules -
    none of which move while a fixed point runs - so `_ItemPlan` computes them
    once and `_source_quality_ok` is left with only the part that reads the
    item index.
    """
    applies = skill in _COMBAT_SKILLS or (
        isinstance(challenge.get("Category"), list) and "BIS Skilling" in challenge["Category"]
    )
    waived = (
        challenge.get("Not Equip") is True
        or rules.get("Wield Crafted Items") is True
        or skill == "Magic"
    )
    return applies, waived


def _source_quality_ok(sources: Mapping[str, str], *, applies: bool, waived: bool) -> bool:
    """Port of the combat/`BIS Skilling` source-quality gate
    (worker.js:4067-4082): for combat skills and challenges whose `Category`
    includes `BIS Skilling`, an item only counts if at least one of its
    sources is *not* a plain skill-training output (a `primary-<Skill>` /
    `secondary-<Skill>` tag where `<Skill>` is a real skill name, i.e. an
    output fed back by `_seed_items_with_outputs`) - don't require training a
    skill just to wield its product - unless `Not Equip` is set,
    `rules['Wield Crafted Items']` is on, the training skill is Slayer, or
    the requiring skill is Magic. Upstream's escape hatch for a matching
    Quest/Diary `Tasks` sub-task (the `'--'`-joined naming convention) is not
    ported - it has no real-export uses worth the complexity.

    `applies`/`waived` come from `_quality_flags`. `waived` is upstream's
    per-challenge escape hatch, and it sits *inside* the loop there, so an item
    with no sources at all still fails - hence `bool(sources)` rather than a
    bare `True`.
    """
    if not applies:
        return True
    if waived:
        return bool(sources)
    for tag in sources.values():
        source_skill = tag.partition("-")[2]
        if "-" not in tag or source_skill not in _SKILL_NAMES or source_skill == "Slayer":
            return True
    return False


def _item_usable(
    sources: Mapping[str, str] | None,
    *,
    non_shop: bool,
    allowed_sources: Any,
    applies: bool,
    waived: bool,
) -> bool:
    if not _item_source_ok(sources, non_shop, allowed_sources):
        return False
    assert sources is not None  # narrowed by _item_source_ok
    return _source_quality_ok(sources, applies=applies, waived=waived)


@dataclass(frozen=True)
class _ItemPlan:
    """An `Items` requirement with its *parsing* done once.

    Every field here comes from the challenge and the export, both immutable
    for the life of a `calc_challenges` call, while the item index the plan is
    checked against is what the fixed point keeps re-seeding. Splitting the two
    means the `*` stripping, `[+]` detection and `itemsPlus` family resolution
    happen once per challenge instead of on all ninety-odd sweeps: 7,569 refs
    on the real export, re-parsed every time.

    `families` holds one `(members, needed)` per ref - a plain ref is a
    one-member family needing one match, and a `None` members means the
    `itemsPlus` lookup failed, which fails the whole requirement.
    """

    families: tuple[tuple[tuple[str, ...] | None, int], ...]
    allowed_sources: Any
    non_shop: bool
    #: `_quality_flags` for this challenge - see `_source_quality_ok`.
    quality_applies: bool
    quality_waived: bool

    @property
    def simple(self) -> bool:
        """Does `_item_usable` reduce to "the index has this item at all"?

        True when none of the three gates can refuse anything: `_item_source_ok`
        is then `sources is not None` (`non_shop` off, and `has_allowed_source`
        returns `True` unconditionally unless `allowed_sources` is a *non-empty
        list*), and `_source_quality_ok` returns `True` on its first line when
        the gate does not apply. So the whole predicate is a presence check.

        Worth deciding because `_item_usable` runs 677,231 times a derivation
        and the overwhelming majority of plans are this shape - see
        `_item_plan_met`, which is the only reader.
        """
        return (
            not self.non_shop
            and not self.quality_applies
            and not (isinstance(self.allowed_sources, list) and self.allowed_sources)
        )


def _compile_items(
    challenge: Mapping[str, Any],
    chunk_info: ChunkInfo,
    *,
    skill: str = "",
    rules: Mapping[str, Any] = {},
    locked_equipment: frozenset[str] = frozenset(),
) -> _ItemPlan | None:
    """Resolve a challenge's `Items` refs, or `None` if it has no `Items`.

    `locked_equipment` is the slayer gear a `slayerLocked` level puts out of
    reach (`pipeline.slayer_locked_equipment`). Upstream does not drop those
    items: it **renames** them, moving `baseChunkData['items'][x]` to
    `x + '*'` (worker.js:3271-3278), and a starred key satisfies a
    requirement for every skill *except* a combat one
    (`!items[x] && (!items[x + '*'] || combatSkills.includes(skill))`,
    worker.js:4067). That is the game's own distinction between owning a
    nose peg and being able to wear it - you can still craft, fletch or
    light one at any Slayer level.

    This project has no starred item index to rename into: `sources.py` and
    `_seed_items_with_outputs` both key plainly, and flattening that was a
    deliberate simplification long before this. So the equivalent is applied
    at compile time and only where the star would have bitten - a blocked
    member is struck out of the family for a combat skill and left alone for
    every other. Striking it per *member* rather than refusing the family is
    what keeps `Facemask[+]` satisfiable by a member that is not slayer gear.
    """
    item_refs = challenge.get("Items")
    if not isinstance(item_refs, list):
        return None
    blocked = locked_equipment if skill in _COMBAT_SKILLS else frozenset()
    families: list[tuple[tuple[str, ...] | None, int]] = []
    for item_ref in item_refs:
        if not isinstance(item_ref, str):
            continue
        name = item_ref.replace("*", "")
        if "[+]" in name:
            base_name, marker, count_str = name.partition("[+]x")
            family = _plus_family(chunk_info, "itemsPlus", f"{base_name}[+]" if marker else name)
            families.append(
                (
                    tuple(member for member in family if member not in blocked)
                    if family is not None
                    else None,
                    int(count_str) if marker else 1,
                )
            )
        else:
            families.append((() if name in blocked else (name,), 1))
    applies, waived = _quality_flags(skill, challenge, rules)
    return _ItemPlan(
        families=tuple(families),
        allowed_sources=challenge.get("AllowedSources"),
        non_shop=challenge.get("NonShop") is True,
        quality_applies=applies,
        quality_waived=waived,
    )


def _cached_plan(
    plans: MutableMapping[tuple[str, str], _ItemPlan | None],
    skill: str,
    name: str,
    challenge: Mapping[str, Any],
    chunk_info: ChunkInfo,
    *,
    rules: Mapping[str, Any],
    locked_equipment: frozenset[str],
) -> _ItemPlan | None:
    """`_compile_items` against a table, keyed by `(skill, name)`.

    `None` is a real plan - "this challenge has no `Items`" - so this asks
    `in`, never a falsy default.
    """
    key = (skill, name)
    if key in plans:
        return plans[key]
    plan = _compile_items(
        challenge, chunk_info, skill=skill, rules=rules, locked_equipment=locked_equipment
    )
    plans[key] = plan
    return plan


def _item_plan_met(plan: _ItemPlan, items: Mapping[str, Mapping[str, str]]) -> bool:
    """Check a compiled plan against the current item index.

    Everything the check needs that isn't the index itself was decided when the
    plan was compiled - the refs, and the source-quality gate's two flags - so
    what runs here per sweep is dictionary lookups and nothing more. Counting
    stops at `needed` because the answer cannot change after that, which the
    uncompiled `sum()` had no way to do.

    A `plan.simple` plan skips `_item_usable` for the presence check it
    provably reduces to; see that property. Same predicate, one call instead
    of four, on the hottest line in the derivation.
    """
    simple = plan.simple
    for family, needed in plan.families:
        if family is None:
            return False
        matches = 0
        for member in family:
            # `.get(...) is not None`, not `in`: a present-but-`None` entry is
            # not a usable item, and that is what `_item_usable` would say.
            usable = (
                items.get(member) is not None
                if simple
                else _item_usable(
                    items.get(member),
                    non_shop=plan.non_shop,
                    allowed_sources=plan.allowed_sources,
                    applies=plan.quality_applies,
                    waived=plan.quality_waived,
                )
            )
            if usable:
                matches += 1
                if matches >= needed:
                    break
        if matches < needed:
            return False
    return True


def _items_requirement_met(
    challenge: Mapping[str, Any],
    items: Mapping[str, Mapping[str, str]],
    chunk_info: ChunkInfo,
    *,
    skill: str,
    rules: Mapping[str, Any],
) -> bool:
    """Port of the `Items` block (worker.js:3899-4121). The `*` secondary
    marker is stripped and otherwise ignored *here*: verified against upstream
    (worker.js:4046,4064), it does **not** gate validity - it sets a
    per-challenge `Secondary` flag, whose three consequences are traced in
    this module's docstring. One is inert on real data (the seeded-`Output`
    tag split cannot move `_source_quality_ok`); the other two are ported -
    the `Secondary` input to `checkPrimaryMethod` (see `_is_secondary` and
    `_has_primary_task`) and `forcedPrimary`, which carries the `Secondary
    MTA` rule and is checked in `_dynamic_gates_met`. An earlier version of
    this note called `forcedPrimary` inert because no *export* challenge
    carries it; upstream writes it at runtime instead. `[+]`
    resolves through `codeItems.itemsPlus`, the same shape `_plus_family`
    already handles for `Chunks`/`Objects`/`Monsters`/`NPCs`/`Mix`.

    Compile-then-check, so this and `calc_challenges`'s hot loop share one
    statement of the semantics - the loop just hoists the compile step out.
    """
    plan = _compile_items(challenge, chunk_info, skill=skill, rules=rules)
    if plan is None:
        return True
    return _item_plan_met(plan, items)


#: index.js's `universalPrimary`: how each skill is *actually trained*.
#: A skill counts as trainable if any one of its listed methods is met.
_UNIVERSAL_PRIMARY: dict[str, tuple[str, ...]] = {
    "Slayer": ("Primary[+]",), "Thieving": ("Primary[+]",),
    "Attack": ("Monster[+]",), "Defence": ("Monster[+]",),
    "Strength": ("Monster[+]",), "Hitpoints": ("Monster[+]",),
    "Ranged": ("Ranged[+]",), "Prayer": ("Primary[+]", "Bones[+]"),
    "Runecraft": ("Primary[+]",), "Sailing": ("Primary[+]",),
    "Magic": ("Primary[+]",), "Farming": ("Primary[+]",),
    "Herblore": ("Primary[+]",), "Hunter": ("Primary[+]",),
    "Cooking": ("Primary[+]",), "Woodcutting": ("Primary[+]",),
    "Firemaking": ("Primary[+]",), "Fletching": ("Primary[+]",),
    "Fishing": ("Primary[+]",), "Mining": ("Primary[+]",),
    "Smithing": ("Primary[+]",), "Crafting": ("Primary[+]",),
    "Agility": ("Primary[+]",), "Construction": ("Primary[+]",),
    "Combat": ("Combat[+]",),
}


def _secondary_source_ok(tag: Any, *, plus: bool, farming_primary: bool) -> bool:
    """Does one source tag stop the item that carries it reading as a
    by-product? Ports the two spellings upstream gives this test, which are
    not the same test.

    The plain-item form (worker.js:4086) is a **conjunction**: a `-Farming`
    tag never clears the flag unless `rules['Farming Primary']` is on. The
    family form (worker.js:4014) puts the same clause inside the second
    disjunct, where `!tag.includes('secondary-')` has already fired for a
    `primary-Farming` tag - so there it is dead. Both are ported as written
    rather than reconciled: which one runs is decided by the shape of the
    requirement, and guessing that upstream meant the stricter one everywhere
    would be inventing a gate.
    """
    if not isinstance(tag, str):
        return False
    if not plus and "-Farming" in tag and not farming_primary:
        return False
    return not tag.startswith("secondary-") or tag == "shop"


def _is_secondary(
    challenge: Mapping[str, Any],
    items: Mapping[str, Mapping[str, str]],
    chunk_info: ChunkInfo,
    rules: Mapping[str, Any],
) -> bool:
    """Upstream's `Secondary` flag (worker.js:3927-4139, settled at 4431):
    **is one of the things this challenge consumes obtainable only as
    somebody else's by-product?**

    The `*` in an `Items` entry marks a consumed *secondary* ingredient, and
    the flag asks whether that ingredient has any source worth the name. A
    tag of `primary-<skill>` or `shop` says yes and clears it; a tag of
    `secondary-<source>` alone says the only way to that item is as a
    side-effect of doing something else, and the challenge inherits the
    doubt. An unmarked entry - a tool, an `Axe[+]` - can never set it, which
    is the same reading `costing/estimate.py` takes of the marker.

    Only ever asked of a challenge already known **valid**, which is what
    lets this be as short as it is: upstream reaches its source test only
    after the item has passed presence, `NonShop` and `AllowedSources`, and a
    valid challenge has passed all three by construction.

    The `Objects` half of upstream's flag (worker.js:4287-4318) is
    deliberately not ported, because it cannot fire: it filters the object's
    source **keys**, and those are chunk ids or - since `Output Object` was
    seeded - challenge names. Neither ever contains `secondary-`.
    """
    refs = challenge.get("Items")
    if not isinstance(refs, list):
        return False
    farming_primary = rules.get("Farming Primary") is True
    for ref in refs:
        if not isinstance(ref, str) or "*" not in ref:
            continue
        name = ref.replace("*", "")
        if "[+]" in name:
            base_name, marker, _ = name.partition("[+]x")
            family = _plus_family(chunk_info, "itemsPlus", f"{base_name}[+]" if marker else name)
            members: tuple[str, ...] = tuple(family) if family is not None else ()
            plus = True
        else:
            members, plus = (name,), False
        cleared = any(
            _secondary_source_ok(tag, plus=plus, farming_primary=farming_primary)
            for member in members
            for tag in (items.get(member) or {}).values()
        )
        if not cleared:
            return True
    return False


def _has_primary_task(
    skill: str,
    valid: Mapping[str, Mapping[str, Any]],
    chunk_info: ChunkInfo,
    passive_skill: Mapping[str, int],
    backlog: Mapping[str, Mapping[str, Any]],
    rules: Mapping[str, Any],
    items: Mapping[str, Any],
    source_index: SourceIndex,
) -> bool:
    """`Primary[+]`: a valid challenge flagged `Primary`, not backlogged, at
    a level actually attainable - `Level == 1`, or within
    `passiveSkill[skill] + bestBoost` (worker.js:5114).

    The boost term is upstream's, and it widens the gate: a boost item the
    chunks provide lets a challenge above the passive floor still count as a
    training method, which can flip a whole skill from untrainable to
    trainable. Upstream additionally allows a `skillQuestXp` floor, which is
    not modelled - no quest-XP state exists anywhere in this codebase.

    **`Primary` is not enough on its own: it has to be `Primary` and not
    `Secondary`** (worker.js:5135), which is the one live consequence of the
    `*` marker and was this module's longest-standing named gap. A method
    whose consumed ingredient is only somebody else's by-product is not a way
    to train the skill, and counting it as one lets a skill claim a training
    route it cannot actually run. Measured on both cached maps it moves
    nothing - 7 valid `Primary` challenges on each are `Secondary`, and no
    skill's whole `Primary` set is - which is the point of porting it now
    rather than after a map where it does.
    """
    challenges = chunk_info.challenges.get(skill) or {}
    backlogged = backlog.get(skill) or {}
    passive = passive_skill.get(skill)
    for name in valid.get(skill, {}):
        challenge = challenges.get(name)
        if not isinstance(challenge, dict):
            continue
        if not _effective_primary(challenge, rules) or name in backlogged:
            continue
        level = challenge.get("Level")
        # `Secondary` is asked last of the three, though upstream writes the
        # whole condition as one `&&`: it is the only term that walks an
        # item's sources, and asking it before the level test put it on every
        # `Primary` challenge in the skill rather than on the one about to
        # answer. Measured on the reference map, that ordering alone was 96,191 calls a
        # `derive` and +30% on the whole command.
        if not isinstance(level, (int, float)) or level == 1:
            if not _is_secondary(challenge, items or {}, chunk_info, rules):
                return True
            continue
        if isinstance(passive, (int, float)) and passive > 1:
            best, saw = boosts.best_boost(
                skill,
                name,
                challenge,
                float(level),
                rules=rules,
                chunk_info=chunk_info,
                items=items,
                source_index=source_index,
            )
            if level <= passive + best + saw and not _is_secondary(
                challenge, items or {}, chunk_info, rules
            ):
                return True
    return False


def _check_primary_method(
    skill: str,
    valid: Mapping[str, Mapping[str, Any]],
    source_index: SourceIndex,
    chunk_info: ChunkInfo,
    *,
    passive_skill: Mapping[str, int],
    backlog: Mapping[str, Mapping[str, Any]],
    manual_tasks: Mapping[str, Mapping[str, Any]],
    rules: Mapping[str, Any] | None = None,
    items: Mapping[str, Any] | None = None,
    objects: Mapping[str, Any] | None = None,
    _seen: frozenset[str] = frozenset(),
) -> bool:
    """Port of `checkPrimaryMethod` (worker.js:5077-5220): can `skill`
    actually be *trained* in the current chunks?

    This is a different question from "does the skill have a valid
    challenge", which is what this used to answer - and the difference has
    teeth. `Combat` has only 14 challenges in the whole export, all needing
    chunks a given map is unlikely to own, so the old stand-in reported it
    untrainable always; every challenge gated on `Skills: {Combat: N}` -
    including all six Slayer-master assignments - was therefore invalid,
    which silently invalidated whole `taskUnlocks` chains hanging off them.
    Upstream instead defines `Combat` as "any combat skill is trainable",
    and those in turn need only a monster to hit.

    Not modelled (all documented rather than silently approximated): the
    `Boosting` level shift and `skillQuestXp` floor inside `Primary[+]`, and
    the secondary/processing-source filtering inside `Ranged[+]`.
    """
    rules = rules or {}
    # Upstream's `baseChunkData['items']` is the seeded index; falling back
    # to the narrow one only loses boosts, never invents them. `objects` is
    # the same bargain for the `Smithing by Smelting` anvil below - and it
    # has to be the *seeded* set, since `Build an ~|anvil (amenity)|~`
    # outputs one.
    items = source_index.items if items is None else items
    objects = source_index.objects if objects is None else objects
    lines = _UNIVERSAL_PRIMARY.get(skill)
    if lines is None:
        return True  # upstream: `!universalPrimary[skill] && (tempValid = true)`

    for line in lines:
        if line == "Primary[+]":
            if _has_primary_task(
                skill, valid, chunk_info, passive_skill, backlog, rules, items, source_index
            ):
                return True
        elif line == "Monster[+]":
            if source_index.monsters:
                return True
        elif line == "Bones[+]":
            bones = _mapping(chunk_info.code_items, "boneItems")
            bone_names = bones if isinstance(bones, dict) else {}
            if any(bone in source_index.items for bone in bone_names):
                return True
        elif line == "Combat[+]":
            if any(
                other not in _seen
                and _check_primary_method(
                    other,
                    valid,
                    source_index,
                    chunk_info,
                    passive_skill=passive_skill,
                    backlog=backlog,
                    manual_tasks=manual_tasks,
                    rules=rules,
                    items=items,
                    objects=objects,
                    _seen=_seen | {skill},
                )
                for other in sorted(_COMBAT_SKILLS)
            ):
                return True
        elif line == "Ranged[+]":
            # Upstream needs a usable ammo/launcher pair *and* something to
            # shoot; the per-source secondary filtering is not modelled.
            ammo_tools = _mapping(chunk_info.code_items, "ammoTools")
            usable = any(
                ammo in source_index.items
                and isinstance(launchers, dict)
                and any(weapon in source_index.items for weapon in launchers)
                for ammo, launchers in ammo_tools.items()
                if ammo != "No ammo"
            )
            if usable and source_index.monsters:
                return True

    # `manualTasks[skill]` naming a Primary, non-backlogged challenge also
    # counts as a training method, as does an explicit `manualPrimary`.
    #
    # `Smithing by Smelting` (worker.js:5226) rides on this branch alone:
    # with the rule off, a manually-added Smithing task only proves the skill
    # trainable if the chunks actually hold an anvil, because smelting ore
    # into bars is not by itself a way to train Smithing. With the rule on
    # the whole condition short-circuits, which is why this was invisible on
    # both cached maps.
    challenges = chunk_info.challenges.get(skill) or {}
    backlogged = backlog.get(skill) or {}
    smithing_ok = (
        skill != "Smithing"
        or rules.get("Smithing by Smelting") is True
        or "Anvil" in objects
        or "Rusted anvil" in objects
    )
    for name in manual_tasks.get(skill, {}):
        challenge = challenges.get(name)
        if not isinstance(challenge, dict) or name in backlogged:
            continue
        if not _effective_primary(challenge, rules) or not smithing_ok:
            continue
        if not _is_secondary(challenge, items or {}, chunk_info, rules):
            return True
    return False


def _has_any_valid(skill: str, valid: Mapping[str, Mapping[str, Any]]) -> bool:
    """Kept for the `Skills` requirement's *level* half only - see
    `_skills_requirement_met`. Trainability now goes through
    `_check_primary_method`."""
    return bool(valid.get(skill))


def _skills_requirement_met(
    challenge: Mapping[str, Any],
    max_skill: Mapping[str, int],
    valid: Mapping[str, Mapping[str, Any]],
    *,
    trainable: Mapping[str, bool],
) -> bool:
    """A `Skills` requirement needs the sub-skill to be *trainable* (see
    `_check_primary_method`, precomputed once per pass into `trainable`) and
    its level within `max_skill` where that caps it."""
    skills = challenge.get("Skills")
    if not isinstance(skills, dict):
        return True
    for sub_skill, required_level in skills.items():
        if not trainable.get(sub_skill, False):
            return False
        if isinstance(required_level, (int, float)) and sub_skill in max_skill:
            if required_level > max_skill[sub_skill]:
                return False
    return True


def _diary_tier_waived(
    skill: str,
    challenge: Mapping[str, Any],
    task_name: str,
    task_skill: str,
    chunk_info: ChunkInfo,
    rules: Mapping[str, Any],
) -> bool:
    """Is this `Tasks` dependency waived by `Show Diary Tasks Any`?

    Port of the `skill === 'Diary'` arm at worker.js:1360. A diary tier's
    completion challenge (`~|Morytania Diary#Hard|~ Complete the Hard Diary`)
    is marked by carrying a `Reward`, and the tasks of the *next* tier depend
    on it. With `Show Diary Tasks Any` on - "Show all diary tasks possible,
    regardless of tier" - that dependency is dropped, so an Elite task shows
    without the Hard diary being finished. The dependent must not itself be a
    tier completion, or the tiers would collapse into each other.

    `Combat Achievements` is exempt from the rule check upstream and always
    waived.
    """
    if skill != "Diary" or task_skill != "Diary":
        return False
    if "Reward" in challenge:
        return False
    dependency = (chunk_info.challenges.get("Diary") or {}).get(task_name)
    if not isinstance(dependency, dict) or "Reward" not in dependency:
        return False
    return rules.get("Show Diary Tasks Any") is True or (
        dependency.get("BaseQuest") == "Combat Achievements"
    )


def _tasks_requirement_met(
    challenge: Mapping[str, Any],
    valid: Mapping[str, Mapping[str, Any]],
    chunk_info: ChunkInfo,
    prev_valid: Mapping[str, Mapping[str, Any]] = {},
    *,
    skill: str = "",
    rules: Mapping[str, Any] = {},
) -> bool:
    """A challenge needing other challenges already valid, including `[+]`
    families (`codeItems.tasksPlus`, 153 of them) and the `[+]xN` "at least
    N of" form - the same shape `Chunks`/`Items`/etc. use, resolved here
    against `valid` rather than a source index.

    206 of the export's 6,428 `Tasks` entries are families, and missing them
    silently invalidated whole chains: `Gargoyle task` requires
    `VannakaBetterMastersAndMortimer[+]x1` (any one of six Slayer masters),
    and while it stayed invalid every `taskUnlocks` gate keyed on it -
    including the one guarding `Grotesque Guardians`, hence `Granite gloves`
    - failed too.
    """
    tasks = challenge.get("Tasks")
    if not isinstance(tasks, dict):
        return True
    for task_name, task_skill in tasks.items():
        if not isinstance(task_skill, str):
            continue
        if _diary_tier_waived(skill, challenge, task_name, task_skill, chunk_info, rules):
            continue
        # Consult the previous pass as well as the partially-built current
        # one: categories are evaluated in the export's own key order, so a
        # cross-category dependency pointing "backwards" (Nonskill at index
        # 16 needing Slayer at 21) would otherwise never resolve - not
        # merely converge slowly, since `new_valid` is rebuilt each pass.
        # Real case: `Gargoyle task` needs any Slayer-master assignment.
        #
        # Tested as two lookups rather than built as one merged dict: this
        # runs ~300,000 times per derivation and the categories reach 878
        # entries, so materialising `{**prev, **current}` per reference cost
        # 20x what asking both costs. Membership in the union is membership
        # in either, so the answer is identical.
        current = valid.get(task_skill, {})
        previous = prev_valid.get(task_skill, {})
        if "[+]" in task_name:
            base_name, marker, count_str = task_name.partition("[+]x")
            family_name = f"{base_name}[+]" if marker else task_name
            family = _plus_family(chunk_info, "tasksPlus", family_name)
            if family is None:
                return False
            needed = int(count_str) if marker and count_str.isdigit() else 1
            found = 0
            for member in family:
                if member in current or member in previous:
                    found += 1
                    if found >= needed:
                        break
            if found < needed:
                return False
        elif task_name not in current and task_name not in previous:
            return False
    return True


def _category_gate_met(
    challenge: Mapping[str, Any], rules: Mapping[str, Any], secondary_primary_amount: str
) -> bool:
    categories = challenge.get("Category")
    if not isinstance(categories, list):
        return True
    for category in categories:
        if category == "InsidePOH Primary" and rules.get("InsidePOH") is not True:
            level = challenge.get("Level")
            if isinstance(level, (int, float)) and level > 1:
                return False
        if category in _MAYBE_PRIMARY:
            continue
        if category not in rules:
            continue
        if rules[category] is True:
            continue
        if category == "Secondary Primary" and secondary_primary_amount != "1":
            continue
        return False
    return True


def _level_gates_met(challenge: Mapping[str, Any], skill: str, max_skill: Mapping[str, int], rules: Mapping[str, Any]) -> bool:
    for gate in _LEVEL_GATES_NOT_SUPPORTED:
        if gate in challenge:
            raise NotImplementedError(f"the {gate!r} gate is not supported")
    level = challenge.get("Level")
    if isinstance(level, (int, float)) and skill in max_skill and level > max_skill[skill]:
        return False
    if challenge.get("Not F2P") is True and rules.get("F2P") is True:
        return False
    if challenge.get("Not Skiller") is True and rules.get("Skiller") is True:
        return False
    return True


def _challenge_value(challenge: Mapping[str, Any], skill: str) -> int | str | bool:
    if skill in ("Quest", "Diary"):
        return True
    level = challenge.get("Level")
    if isinstance(level, (int, str)):
        return level
    label = challenge.get("Label")
    if isinstance(label, str):
        return label
    return True


def _static_gates_met(
    skill: str,
    name: str,
    challenge: Mapping[str, Any],
    *,
    chunk_ids: Mapping[str, bool],
    reachable_sections: Mapping[str, Mapping[str, bool]],
    monsters: Mapping[str, Mapping[str, Any]],
    npcs: Mapping[str, Mapping[str, Any]],
    chunk_info: ChunkInfo,
    rules: Mapping[str, Any],
    max_skill: Mapping[str, int],
    secondary_primary_amount: str,
    construction_locked: bool,
) -> bool:
    """The half of the evaluation whose every input is fixed for a whole
    `calc_challenges` call, so it can be - and is - decided once.

    `rules`/`max_skill`/`secondary_primary_amount`/`construction_locked` are
    per-map constants; `chunk_ids`/`reachable_sections` and the monster/npc
    indexes are arguments to the call and never change inside its loops.
    `items` does, via `_seed_items_with_outputs`, which is why `Items` is in
    `_dynamic_gates_met` - and so, since `Output Object` was ported, do
    `objects`, which is why `Objects` is decided by `_objects_requirement`
    beside this rather than in it.

    On the real export this rejects **8,757 of 14,692** challenges, and the
    loops used to re-derive every one of those rejections nine to twelve times
    per call. Raises `NotImplementedError` for the unsupported level gates,
    exactly where `_evaluate_challenge` used to.
    """
    if construction_locked and _MAHOGANY_HOMES_CONTRACT in name:
        return False
    if not _level_gates_met(challenge, skill, max_skill, rules):
        return False
    if not _category_gate_met(challenge, rules, secondary_primary_amount):
        return False
    if not chunks_requirement_met(challenge, chunk_ids, reachable_sections, chunk_info):
        return False
    if not _presence_requirement_met(challenge, "Monsters", monsters, chunk_info, "monstersPlus"):
        return False
    if not _presence_requirement_met(challenge, "NPCs", npcs, chunk_info, "npcsPlus"):
        return False
    return _mix_requirement_met(challenge, monsters, npcs, chunk_info)


#: Upstream's `tempClueTasksPossible` keys (worker.js:3457), in its order.
#: Fixed rather than discovered, because a tier missing from the table is
#: what makes a clue challenge invalid - see `_clue_tasks_possible`.
_CLUE_TIERS = ("beginner", "easy", "medium", "hard", "elite", "master")


def _clue_tasks_possible(
    valid: Mapping[str, Mapping[str, Any]], challenges: Mapping[str, Mapping[str, Any]]
) -> dict[str, float]:
    """How much of each clue tier this map can actually do, as a percentage.

    Port of worker.js:3455-3483. Every `Nonskill` challenge carrying a
    `ClueTier` is one step of that tier's clue scroll - 983 of them across the
    six tiers - and the fraction of them currently valid is how upstream
    decides whether the tier is worth collecting the *rewards* of. See
    `_clue_reward_gate_met` for the other half.

    A tier with no steps at all divides zero by zero. JS answers `NaN` and
    carries on; the comparison that reads this is `<`, which is false against
    `NaN`, so an empty tier is treated as passing rather than failing. That is
    reproduced rather than special-cased - all six tiers are populated in the
    current export, so it is guard code, but it is guard code that decides
    validity in the direction opposite to the missing-key case just below it.
    """
    possible = dict.fromkeys(_CLUE_TIERS, 0)
    total = dict.fromkeys(_CLUE_TIERS, 0)
    nonskill = challenges.get("Nonskill")
    if not isinstance(nonskill, dict):
        return {tier: math.nan for tier in _CLUE_TIERS}
    valid_nonskill = valid.get("Nonskill") or {}
    for name, challenge in nonskill.items():
        tier = challenge.get("ClueTier") if isinstance(challenge, dict) else None
        if tier not in total:
            continue
        total[tier] += 1
        if name in valid_nonskill:
            possible[tier] += 1
    return {
        tier: (possible[tier] / total[tier]) * 100 if total[tier] else math.nan
        for tier in _CLUE_TIERS
    }


def _clue_reward_gate_met(
    challenge: Mapping[str, Any], rules: Mapping[str, Any], clue_possible: Mapping[str, float]
) -> bool:
    """Port of worker.js:3790-3796: with `Collection Log Clues` on, a reward
    task is only offered once its tier is reachable enough.

    The rule has two halves and only the first was here. `_category_gate_met`
    handles it as an ordinary category - off means the 517 reward tasks are
    out - but *on* does not mean all 517 are in: each carries a
    `ClueRewardTier`, and it is refused unless that tier's
    `_clue_tasks_possible` share reaches `rules['Collection Log Clues
    Amount']`. At the shipped default of 100 that means every step of the
    tier must be doable, which is a strong condition and the reason turning
    the rule on used to add 519 tasks here against upstream's rather fewer.

    A tier **absent** from the table fails outright, where a tier present but
    `NaN` passes; upstream writes those two as separate clauses of one `||`
    and they are not the same test. The absent case is real: the table is
    empty until the first pass has some validity to measure, so on the first
    pass no reward task is valid at all, and they arrive as the fixed point
    settles.

    Lives on the dynamic side of the gate split even though upstream writes
    it beside the category check, because the share it reads is a function of
    the validity being computed.
    """
    if rules.get("Collection Log Clues") is not True:
        return True
    categories = challenge.get("Category")
    if not isinstance(categories, list) or "Collection Log Clues" not in categories:
        return True
    if "ClueRewardTier" not in challenge:
        return True
    tier = challenge.get("ClueRewardTier")
    if not isinstance(tier, str) or tier not in clue_possible:
        return False
    return not clue_possible[tier] < build_clue_complete_num(
        rules.get("Collection Log Clues Amount")
    )


def _dynamic_gates_met(
    skill: str,
    name: str,
    challenge: Mapping[str, Any],
    *,
    plan: _ItemPlan | None,
    items: Mapping[str, Mapping[str, str]],
    objects: Mapping[str, Mapping[str, Any]],
    deferred_objects: tuple[tuple[str, ...], ...],
    valid: Mapping[str, Mapping[str, Any]],
    chunk_info: ChunkInfo,
    rules: Mapping[str, Any],
    max_skill: Mapping[str, int],
    trainable: Mapping[str, bool],
    prev_valid: Mapping[str, Mapping[str, Any]],
    clue_possible: Mapping[str, float],
) -> bool:
    """The half that has to stay in the loop: `Items` and the buildable half
    of `Objects` read indexes the fixed point keeps re-seeding, and
    `Skills`/`Tasks` read the validity being computed.

    `plan` is the challenge's `Items` refs already resolved (`_compile_items`),
    and `deferred_objects` the `Objects` groups `_objects_requirement` could
    not settle against the base index - both because only the *index* they are
    checked against changes between sweeps.

    `forcedPrimary` (worker.js:4433) lives here too, and it is dynamic for the
    same reason: it is a test on the settled `Secondary` flag, which reads the
    item index. Nothing in the export sets `forcedPrimary` - `Secondary MTA`
    does, on one named challenge, at worker.js:3605. See `_FORCED_PRIMARY`.
    """
    if deferred_objects and not _objects_met(deferred_objects, objects):
        return False
    if plan is not None and not _item_plan_met(plan, items):
        return False
    if not _clue_reward_gate_met(challenge, rules, clue_possible):
        return False
    if not _skills_requirement_met(challenge, max_skill, valid, trainable=trainable):
        return False
    if (skill, name) == _FORCED_PRIMARY and rules.get("Secondary MTA") is not True:
        # `forcedPrimary && Secondary -> invalid`. With `Secondary MTA` on,
        # `forcedPrimary` is false and the gate never fires - which is why
        # both cached maps see nothing here, and why `_items_requirement_met`
        # used to call this consequence inert. It is inert in the *export*;
        # the rule writes the flag at runtime.
        if _is_secondary(challenge, items, chunk_info, rules):
            return False
    return _tasks_requirement_met(challenge, valid, chunk_info, prev_valid, skill=skill, rules=rules)


def _evaluate_challenge(
    skill: str,
    name: str,
    challenge: Mapping[str, Any],
    *,
    chunk_ids: Mapping[str, bool],
    reachable_sections: Mapping[str, Mapping[str, bool]],
    items: Mapping[str, Mapping[str, str]],
    objects: Mapping[str, Mapping[str, Any]],
    monsters: Mapping[str, Mapping[str, Any]],
    npcs: Mapping[str, Mapping[str, Any]],
    valid: Mapping[str, Mapping[str, Any]],
    chunk_info: ChunkInfo,
    rules: Mapping[str, Any],
    max_skill: Mapping[str, int],
    secondary_primary_amount: str,
    trainable: Mapping[str, bool],
    prev_valid: Mapping[str, Mapping[str, Any]],
    construction_locked: bool,
    locked_equipment: frozenset[str] = frozenset(),
    #: Defaults to upstream's own starting state - an empty table, which
    #: refuses every clue *reward* task. Single-challenge callers have no
    #: fixed point to measure it from; the loop passes the real one.
    clue_possible: Mapping[str, float] = {},
) -> int | str | bool | None:
    """Both halves, in upstream's order. `calc_challenges` runs the halves
    separately (static once, dynamic per pass); this stays as the composed
    form the tests exercise one challenge at a time through.
    """
    if not _static_gates_met(
        skill,
        name,
        challenge,
        chunk_ids=chunk_ids,
        reachable_sections=reachable_sections,
        monsters=monsters,
        npcs=npcs,
        chunk_info=chunk_info,
        rules=rules,
        max_skill=max_skill,
        secondary_primary_amount=secondary_primary_amount,
        construction_locked=construction_locked,
    ):
        return None
    # Single-challenge entry point, so there is nothing seeded to wait for:
    # whatever `_objects_requirement` defers is checked against the index it
    # was handed, which is the two-way answer this used to give.
    decision = _objects_requirement(
        challenge, objects, chunk_info, _seedable_objects(chunk_info.challenges)
    )
    if decision is False:
        return None
    deferred = decision if isinstance(decision, tuple) else ()
    if not _dynamic_gates_met(
        skill,
        name,
        challenge,
        clue_possible=clue_possible,
        plan=_compile_items(
            challenge, chunk_info, skill=skill, rules=rules, locked_equipment=locked_equipment
        ),
        items=items,
        objects=objects,
        deferred_objects=deferred,
        valid=valid,
        chunk_info=chunk_info,
        rules=rules,
        max_skill=max_skill,
        trainable=trainable,
        prev_valid=prev_valid,
    ):
        return None
    return _challenge_value(challenge, skill)


def _seed_items_with_outputs(
    base_items: Mapping[str, Mapping[str, str]],
    valid: Mapping[str, Mapping[str, Any]],
    challenges: Mapping[str, Mapping[str, Any]],
    chunk_info: ChunkInfo,
    rules: Mapping[str, Any],
    backlogged_sources: Mapping[str, Any],
    backlog: Mapping[str, Mapping[str, Any]] = {},
) -> dict[str, dict[str, str]]:
    """A valid challenge's `Output` becomes a new item source for the next
    pass - and, when that `Output` names an activity in
    `skillItems[<that skill>]`, so does every item that activity yields.

    **And a valid quest or diary hands over its `Reward`**, which is a
    separate branch and was unported - see `_seed_rewards`.

    The second half is what makes non-Slayer `skillItems` reachable at all.
    Upstream's link (worker.js:2848, index.js:8603) is exactly this: a
    challenge's `Output` doubles as the *activity key* into `skillItems`.
    `Master wand`, for instance, exists only in
    `skillItems.Nonskill['Pizazz points loot']`, reached because the
    `~|Pizazz points|~*` challenge has `Output: 'Pizazz points loot'` -
    without this it is unobtainable, and BiS picks a worse Magic weapon.
    Note the activity key is *not* an entity name, which is why
    `sources.py`'s chunk-presence route can't find these (it handles the
    other `skillItems` path: a Slayer monster physically in an unlocked
    chunk - see `_slayer_skill_items_for`).

    Upstream accumulates these in an `outputs` map tagged
    `'<primary|secondary>-' + the challenge's own Source` before merging
    into the item index (worker.js:2894, 3037). Simplified here: everything
    is tagged `primary-`, since upstream's primary/secondary split is a
    drop-rate comparison against `Secondary Primary Amount` that this
    module doesn't compute, and the `Rare Drop Amount` rate filter on the
    activity's items isn't applied either (both admit everything on the map
    this was built against). The `bossLogs` gate *is* applied - it excludes
    8 real activities and is live whenever the `Boss` rule is off.

    `backloggedSources['items']` is honoured, matching upstream's own gate
    on this merge (worker.js:3030) and `sources.py`'s handling of the
    ordinary routes. It is *not* cosmetic: a user backlogs a source to say
    "I will not do this", so leaving it in silently readmits it as a
    prerequisite. Real example - `Uncut onyx` is backlogged on the map this
    was built against, and without this gate it re-entered through
    `skillItems.Nonskill['Bag full of gems loot']` at a 1/100,000,000 rate,
    dragged in the whole onyx -> onyx bracelet -> `Regen bracelet` crafting
    chain, and displaced the correct Melee-hands BiS pick.
    """
    items: dict[str, dict[str, str]] = {item: dict(sources) for item, sources in base_items.items()}
    skill_items = chunk_info.skill_items
    boss_logs = _mapping(chunk_info.code_items, "bossLogs")
    allow_boss = rules.get("Boss") is True
    backlogged_items = _mapping(backlogged_sources, "items")

    for skill, names in valid.items():
        skill_challenges = challenges.get(skill, {})
        activities = skill_items.get(skill)
        activities = activities if isinstance(activities, dict) else {}
        for name in names:
            challenge = skill_challenges.get(name)
            if not isinstance(challenge, dict):
                continue
            output = challenge.get("Output")
            if not isinstance(output, str):
                continue
            if backlogged_items.get(output) is not True:
                items.setdefault(output, {})[name] = f"primary-{skill}"

            table = activities.get(output)
            if not isinstance(table, dict) or (not allow_boss and output in boss_logs):
                continue
            source = challenge.get("Source")
            tag = f"primary-{source}" if isinstance(source, str) and source else f"primary-{skill}"
            for item in table:
                if isinstance(item, str) and backlogged_items.get(item) is not True:
                    items.setdefault(item, {}).setdefault(name, tag)

    # The `Slay an ~|abyssal demon|~` sources just added are exactly what
    # `taskUnlocks['Items']`'s `"<item>^<monster>"` keys gate, and upstream
    # re-runs `gatherChunksInfo` mid-`calcChallenges` so its own pass sees
    # them too. Re-applying here is what keeps a merged drop table's
    # location-specific half out - see `sources.apply_item_task_unlocks`.
    _seed_rewards(items, valid, challenges, backlog, backlogged_items)
    apply_item_task_unlocks(items, _mapping(chunk_info.data, "taskUnlocks"), valid)
    return items


#: `skillingPets` (worker.js:2726) - the pet each skill can drop while you
#: train it. `Sailing` is in the table ahead of the skill itself.
_SKILLING_PETS = {
    "Fishing": "Heron",
    "Mining": "Rock golem",
    "Woodcutting": "Beaver",
    "Agility": "Giant squirrel",
    "Farming": "Tangleroot",
    "Thieving": "Rocky",
    "Runecraft": "Rift guardian",
    "Sailing": "Soup",
}


def _seed_skilling_pets(
    items: dict[str, dict[str, str]],
    valid: Mapping[str, Mapping[str, Any]],
    challenges: Mapping[str, Mapping[str, Any]],
    rules: Mapping[str, Any],
    trainable: Mapping[str, bool],
) -> None:
    """Make each skilling pet reachable where its skill is, in place. Port of
    worker.js:2725-2748.

    A pet is not dropped by a monster or sold anywhere - it falls out of
    *doing the skill*, so upstream adds it to the item index directly under
    the source key `Manually Added*` once two things hold: the skill is
    trainable at all, and it has at least one valid challenge that is neither
    flagged `NoPet` nor carrying a `Description`. The second is what keeps a
    quest or diary step from earning you a pet - those are the entries with
    prose attached.

    The tag is `secondary-<skill>`, so the pet reads as a by-product
    throughout: `_is_secondary` will not let a challenge that needs one count
    as a way to train anything, which is right - nobody trains Fishing by
    fishing up a Heron.

    Upstream also *deletes* the key when the condition stops holding, and
    tidies an item left with no sources. Nothing here needs that: the index is
    rebuilt from `SourceIndex` every pass, so a pet that stops qualifying is
    simply not re-added.

    `trainable` is this pass's map, computed from the previous pass's
    validity, where upstream asks `checkPrimaryMethod` against the pass's own
    `newValids`. The fixed point closes that gap - the two agree by the time
    it settles - and asking again here would repeat the most expensive sweep
    in the module for an answer one pass stale at worst.
    """
    if rules.get("Skilling Pets") is not True:
        return
    for skill, pet in _SKILLING_PETS.items():
        if not trainable.get(skill):
            continue
        skill_challenges = challenges.get(skill) or {}
        earns_pet = any(
            isinstance(entry, dict) and "NoPet" not in entry and "Description" not in entry
            for entry in (skill_challenges.get(name) for name in valid.get(skill, {}))
        )
        if earns_pet:
            items.setdefault(pet, {})["Manually Added*"] = f"secondary-{skill}"


def _seed_objects_with_outputs(
    base_objects: Mapping[str, Mapping[str, Any]],
    valid: Mapping[str, Mapping[str, Any]],
    challenges: Mapping[str, Mapping[str, Any]],
    backlog: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """A valid challenge's `Output Object` becomes a new *object* for the next
    pass. Port of worker.js:3036-3045 and its merge at worker.js:3255-3262.

    The twin of `_seed_items_with_outputs`, and unported until the salvaging
    hooks made its absence visible. Upstream builds `outputObjects` inside the
    same walk over `newValids` that builds `outputs`, then merges it into
    `baseChunkData['objects']` unconditionally - unconditionally being correct
    because the walk only ever saw valid challenges.

    What it opens is a chain the export models end to end and this project
    could not walk: all seven `Build a ~|<tier>|~ salvaging hook|~` challenges
    declare `Output Object`, all eight shipwrecks require
    `AnySalvagingHook[+]` through `objectsPlus`, and with no seeding
    `source_index.objects` held zero hooks however many were buildable. It is
    not a Sailing fix - 85 of the 138 challenges carrying an `Output Object`
    are Construction, and an anvil you build is an anvil you can smith at.

    Both of upstream's gates are here bar one. The challenge's own backlog
    applies (including the `#`/`/` spelling the payload uses for a sub-name),
    as it does in `_seed_rewards`: backlogging a build says you will not do
    it. There is no item-style `backloggedSources['objects']` to honour -
    upstream has none. What is flattened is the tag: upstream splits
    `primary-`/`secondary-` on the challenge's `Secondary` flag, which is
    computed during validity rather than stated in the export, and **no
    consumer of the objects index reads its tags at all** - every check
    against it, here and in `sources.py`, is a membership test. The same
    flattening, for the same reason, is recorded on `_seed_items_with_outputs`.
    """
    objects: dict[str, dict[str, Any]] = {
        name: dict(sources) for name, sources in base_objects.items()
    }
    for skill, names in valid.items():
        skill_challenges = challenges.get(skill, {})
        backlogged = backlog.get(skill) or {}
        for name in names:
            challenge = skill_challenges.get(name)
            if not isinstance(challenge, dict):
                continue
            output = challenge.get("Output Object")
            if not isinstance(output, str):
                continue
            if name in backlogged or name.replace("#", "/") in backlogged:
                continue
            objects.setdefault(output, {})[name] = f"primary-{skill}"
    return objects


def _seed_rewards(
    items: dict[str, dict[str, str]],
    valid: Mapping[str, Mapping[str, Any]],
    challenges: Mapping[str, Mapping[str, Any]],
    backlog: Mapping[str, Mapping[str, Any]],
    backlogged_items: Mapping[str, Any],
) -> None:
    """A completed quest or diary tier hands you its `Reward`, in place.
    Port of worker.js:3345-3354.

    `Reward` was read here only as a *marker* - `other_tasks._is_step_chain`
    and `_diary_tier_waived` use "has a `Reward`" to mean "this is a tier or
    quest completion" - and never as what it plainly is: **a source of
    items**. 227 challenges carry one (98 Quest, 129 Diary) between them
    naming 206 distinct items, none of which had any route into the index.

    The one that mattered most is `Raft`. Every one of the export's 243
    Sailing challenges gates on `AnyBoat[+]` -> `Raft`/`Skiff`/`Sloop`, the
    three `Buy a <boat> from a shipwright` challenges each require
    `~|Pandemonium|~ Complete the quest` to be *finished*, and that quest's
    own completion carries `Reward: ["Raft", "Captain's log", "Spyglass"]`.
    So the boat was always sourced - by the branch nothing walked - and
    without it Sailing was unreachable on every map including one with every
    chunk in the game unlocked. There is no circularity: the quest's six
    steps gate on chunks alone, never on a boat.

    Tagged `secondary-<category>` as upstream tags it, which is deliberately
    *not* `primary-`: the suffix is `Quest`/`Diary` rather than a skill name,
    so `_source_quality_ok` lets a reward satisfy a combat requirement -
    correct, since an anti-dragon shield off a quest is a shield you wear.

    Both backlogs apply, as upstream applies them: the challenge's own
    (`backlog[category]`, including the `#`/`/` spelling the payload uses for
    a sub-name) and the item's (`backloggedSources['items']`). A user
    backlogging a quest is saying they will not do it, so its rewards must
    not arrive anyway.
    """
    for category, names in valid.items():
        category_challenges = challenges.get(category, {})
        backlogged = backlog.get(category) or {}
        for name in names:
            challenge = category_challenges.get(name)
            if not isinstance(challenge, dict):
                continue
            rewards = challenge.get("Reward")
            if not isinstance(rewards, list) or not rewards:
                continue
            if name in backlogged or name.replace("#", "/") in backlogged:
                continue
            for reward in rewards:
                if isinstance(reward, str) and backlogged_items.get(reward) is not True:
                    items.setdefault(reward, {})[name] = f"secondary-{category}"


def _prune_untrainable_skills(
    new_valid: dict[str, dict[str, int | str | bool]],
    chunk_info: ChunkInfo,
    source_index: SourceIndex,
    *,
    rules: Mapping[str, Any],
    passive_skill: Mapping[str, int],
    backlog: Mapping[str, Mapping[str, Any]],
    manual_tasks: Mapping[str, Mapping[str, Any]],
    items: Mapping[str, Mapping[str, str]],
    objects: Mapping[str, Mapping[str, Any]],
) -> None:
    """Strip a skill that cannot be trained here back to its `Level 1`
    challenges, in place. Port of worker.js:1521-1529.

    This is how upstream locks a skill behind a quest. `Herblore` is the
    worked example: its only `Level == 1` `Primary` route is `Unlock
    ~|Herblore|~ after Druidic Ritual`, which needs that quest to be
    completable. While it isn't, `checkPrimaryMethod('Herblore')` is false,
    and *every* Herblore challenge above `Level 1` is discarded - not merely
    deprioritised. Without this the skill kept 56 valid challenges and
    `active_tasks.py` went on to propose one of them.

    The `Level 1` survivors are upstream's `newValids[skill][task] === 1`,
    a **strict** comparison against the stored valid value. That value is the
    challenge's `Level` for a skill category and `True` for Quest/Diary/etc,
    and JS `true === 1` is false - so the bool has to be excluded explicitly
    here, where `True == 1` would otherwise be true.

    Applies to every category but `BiS`; the non-skill ones are unaffected in
    practice because `_check_primary_method` reports any skill absent from
    `_UNIVERSAL_PRIMARY` as trainable, exactly as upstream's
    `!universalPrimary[skill] && (tempValid = true)` does.
    """
    for skill in list(new_valid):
        if skill in UNSUPPORTED_CATEGORIES:
            continue
        if _check_primary_method(
            skill,
            new_valid,
            source_index,
            chunk_info,
            passive_skill=passive_skill,
            backlog=backlog,
            manual_tasks=manual_tasks,
            rules=rules,
            items=items,
            objects=objects,
        ):
            continue
        passive = passive_skill.get(skill)
        if isinstance(passive, (int, float)) and not isinstance(passive, bool) and passive > 1:
            continue
        kept: dict[str, int | str | bool] = {
            name: value
            for name, value in new_valid[skill].items()
            if not isinstance(value, bool) and value == 1
        }
        if kept:
            new_valid[skill] = kept
        else:
            del new_valid[skill]


def _inject_manual_tasks(
    new_valid: dict[str, dict[str, int | str | bool]],
    challenges: Mapping[str, Mapping[str, Any]],
    manual_tasks: Mapping[str, Mapping[str, Any]],
) -> None:
    """Force every `manualTasks` entry valid, in place. Port of
    worker.js:1168-1178.

    A manual task is the player asserting "I can do this", recorded per
    account, and upstream writes it straight into `valids`/`newValids` with
    the stored value and flags the challenge `ManualValid`. Every category but
    `BiS` participates, and only challenges the export still defines.

    This module's docstring used to say manual overrides were deliberately
    unapplied. That is right for a *simulated* roll, which has no such history
    to replay - but wrong for deriving the current map, where ignoring them
    hid `(Slayer) Obtain an ~|eternal gem|~` and `(Slayer) Obtain an ~|imbued
    heart|~`, both of which the map's own `activeTasks` oracle lists.
    """
    for skill, entries in manual_tasks.items():
        if skill in UNSUPPORTED_CATEGORIES or not isinstance(entries, dict):
            continue
        skill_challenges = challenges.get(skill)
        if not isinstance(skill_challenges, dict):
            continue
        for name, value in entries.items():
            if name in skill_challenges:
                new_valid.setdefault(skill, {})[name] = value


#: The categories `calcCurrentChallenges2` sends down its `else` branch
#: (worker.js:8390/8533) - the ones with no per-skill winner to pick, where it
#: instead prunes challenges whose `Skills` sub-requirements are out of reach.
_NON_SKILL_CATEGORIES = frozenset({"Extra", "Quest", "Diary", "BiS"})


def _drop_unreachable_subskills(
    new_valid: dict[str, dict[str, int | str | bool]],
    chunk_info: ChunkInfo,
    source_index: SourceIndex,
    *,
    rules: Mapping[str, Any],
    max_skill: Mapping[str, int],
    passive_skill: Mapping[str, int],
    backlog: Mapping[str, Mapping[str, Any]],
    manual_tasks: Mapping[str, Mapping[str, Any]],
    items: Mapping[str, Mapping[str, str]],
    objects: Mapping[str, Mapping[str, Any]],
) -> None:
    """Drop `Extra`/`Quest`/`Diary` challenges whose `Skills` requirement names
    a sub-skill out of reach - port of worker.js:8533-8567, in place.

    A sub-skill is out of reach when it is untrainable (`checkPrimaryMethod`)
    *and* no `passiveSkill` floor covers the boosted requirement, or when the
    requirement simply exceeds `maxSkill`. Challenges listed in `manualTasks`
    are exempt, as upstream exempts them.

    This is the counterpart of `_prune_untrainable_skills` for the categories
    that have no single active pick, and shares its schedule: held back until
    the first fixed point converges, then run inside the loop from the second
    outer pass on. Deciding trainability from a half-seeded item index prunes
    things whose own `Output` chain would have justified them - see
    `calc_challenges` for why both halves of that are needed.

    Upstream's `slayerLocked` arm reaches this gate as a cap on
    `max_skill['Slayer']`, folded in by `pipeline.slayer_capped_max_skill`
    before any of this runs - so it needs no branch here. An earlier version
    of this docstring called that arm inert because no cached map sets it;
    that is a statement about two maps, not about the app.
    """
    for category in sorted(_NON_SKILL_CATEGORIES & set(new_valid)):
        category_challenges = chunk_info.challenges.get(category)
        if not isinstance(category_challenges, dict):
            continue
        manual = manual_tasks.get(category) or {}
        for name in list(new_valid[category]):
            challenge = category_challenges.get(name)
            if not isinstance(challenge, dict) or name in manual:
                continue
            needed = challenge.get("Skills")
            if not isinstance(needed, dict):
                continue
            for sub_skill, level in needed.items():
                if not isinstance(level, (int, float)) or isinstance(level, bool):
                    continue
                cap = max_skill.get(sub_skill)
                if isinstance(cap, (int, float)) and level > cap:
                    break
                if _check_primary_method(
                    sub_skill,
                    new_valid,
                    source_index,
                    chunk_info,
                    passive_skill=passive_skill,
                    backlog=backlog,
                    manual_tasks=manual_tasks,
                    rules=rules,
                    items=items,
                    objects=objects,
                ):
                    continue
                best, saw = boosts.best_boost(
                    sub_skill,
                    name,
                    challenge,
                    float(level),
                    rules=rules,
                    chunk_info=chunk_info,
                    items=items,
                    source_index=source_index,
                )
                floor = passive_skill.get(sub_skill)
                if not isinstance(floor, (int, float)) or floor < level - (best + saw):
                    break
            else:
                continue
            del new_valid[category][name]
        if not new_valid[category]:
            del new_valid[category]


def _drop_superseded_backups(
    new_valid: dict[str, dict[str, int | str | bool]],
    prev_valid: Mapping[str, Mapping[str, Any]],
    challenges: Mapping[str, Mapping[str, Any]],
    backlog: Mapping[str, Mapping[str, Any]],
    manual_tasks: Mapping[str, Mapping[str, Any]],
) -> None:
    """Delete every challenge whose `BackupParent` is satisfied, in place.

    Port of worker.js:1679-1690 (repeated at 1445). A `BackupParent` names
    the *proper* way to do the same thing, and the challenge carrying it is
    only offered while that proper way is out of reach: once the parent is
    valid - or has been backlogged, which upstream counts the same way,
    since backlogging is a deliberate "not this one" - the backup is deleted
    outright rather than merely deprioritised. `ManualValid` exempts a
    challenge from this (no export entry uses it, but it costs nothing to
    honour). The backlog lookup also tries the `#` -> `/` spelling, as
    upstream does everywhere it reads that branch.

    All 17 real uses are `Hunter`'s barehanded catches: `Barehanded catch a
    wandering ~|lucky impling|~` (Level 99) exists for players with no
    butterfly net, and must vanish the moment `Catch a wandering ~|lucky
    impling|~` (Level 89, needs the net) becomes possible. Without this it
    outranked its own parent on `Level` and was reported as the active
    Hunter task - the reported bug.

    **This is the one requirement in this module that is an *absence* check**,
    so `ChallengeResult.valid` no longer only grows: an unlock that supplies
    a butterfly net removes 11 challenges on the real map. `unlock.py`'s
    attribution partition is documented against that.
    """
    for skill, names in new_valid.items():
        skill_challenges = challenges.get(skill)
        if not isinstance(skill_challenges, dict):
            continue
        skill_backlog = backlog.get(skill) or {}
        previous = prev_valid.get(skill) or {}
        for name in list(names):
            challenge = skill_challenges.get(name)
            if not isinstance(challenge, dict):
                continue
            parent = challenge.get("BackupParent")
            # Upstream sets `ManualValid` on a manually-added challenge
            # (worker.js:1178) and exempts it here; we read the manual ledger
            # directly rather than mutating the shared export.
            if not isinstance(parent, str) or challenge.get("ManualValid"):
                continue
            if name in (manual_tasks.get(skill) or {}):
                continue
            if (
                parent in names
                or parent in previous
                or parent in skill_backlog
                or parent.replace("#", "/") in skill_backlog
            ):
                del names[name]
    # `new_valid` is only ever created via `setdefault` when something is
    # added, so a skill key implies at least one valid challenge. Deleting
    # the last one has to preserve that, or `valid` starts carrying empty
    # branches that never otherwise occur.
    for skill in [skill for skill, names in new_valid.items() if not names]:
        del new_valid[skill]


def _js_lower_priority(challenger: Any, incumbent: Any) -> bool:
    """`challenger < incumbent` with JavaScript's answer for a non-number.

    Upstream compares two `Priority` fields with a bare `<`, and a missing
    one is `undefined`: `5 < undefined` and `undefined < 5` are *both* false
    there, where a Python `float("inf")` stand-in would make one of them
    true. Every `Set`-bearing entry in the export carries an integer
    `Priority`, so this is guard code - but it is the guard that decides
    whether an entry is kept or deleted, so it answers the way upstream does.
    """
    if isinstance(challenger, bool) or isinstance(incumbent, bool):
        return False
    if not isinstance(challenger, (int, float)) or not isinstance(incumbent, (int, float)):
        return False
    return challenger < incumbent


def _drop_outclassed_extra_sets(
    new_valid: dict[str, dict[str, int | str | bool]],
    challenges: Mapping[str, Mapping[str, Any]],
    backlog: Mapping[str, Mapping[str, Any]],
    manual_tasks: Mapping[str, Mapping[str, Any]],
) -> None:
    """Thin an `Extra` `Set` down to the members worth chasing, in place.

    Port of the `extraSets` sweep (worker.js:1514-1534, repeated at
    1771-1785) plus the backlog half of the same rule (worker.js:3771-3777,
    upstream's `'Set outclassed'`). A `Set` groups the interchangeable ways
    of holding one slot - `BIS Axe` has 19 members from bronze to infernal -
    and `Priority` ranks them, **lower being better**. Only `BIS Skilling`
    challenges carry the pair: 63 challenges across 15 sets, and no other
    category uses `Set` at all.

    Without this the whole ladder stays valid, so a player holding an
    infernal axe was still being told to obtain the steel, mithril, adamant,
    black, dragon and felling axes. On the second real map that is 19 of its
    20 outstanding `BIS Skilling` tasks. **The oracle map cannot see this**:
    it has `rules['BIS Skilling']` off, so it has no `Set`-bearing challenge
    valid at all, and every `Extra` count it pins stayed green throughout.

    Two things about the sweep are not what the name suggests, and both are
    upstream's behaviour rather than a simplification here:

    - **It is not an argmax.** Upstream means to keep one member per set and
      writes `extraSets[newValids[skill][challenge]['Set']]` to find the
      incumbent to delete - but `newValids[skill][challenge]` is the
      challenge's *value* (a level or a boolean), so `.Set` is `undefined`
      and the delete lands on a key that does not exist. The incumbent
      survives; only the *worse* member of each comparison is ever removed.
      What that leaves is the running minima of `Priority` in iteration
      order: the first member seen, then any member better than everything
      before it. It is visible in the real export - `BIS Angler Hat` lists
      the ordinary hat (`Priority` 2) before the spirit one (`Priority` 1),
      so a player who can reach both is offered both.
    - **Iteration order is the export's own key order.** Upstream sweeps
      `Object.keys(newValids['Extra'])`, i.e. insertion order, and `Extra`
      entries are inserted by the scan at worker.js:3673 that sorts on
      `Description` then `Level` - neither of which any of the 2,932 `Extra`
      challenges has, so the comparator is `NaN` throughout and the export's
      order survives. Iterating `challenges['Extra']` here reproduces that
      without depending on how this module happened to build its own dict.

    A backlogged member is dropped before the sweep rather than inside it:
    upstream refuses it back in `checkChallenge`, so it never reaches
    `newValids` and never takes part. `ManualValid` (and this module's
    `manual_tasks` stand-in for it, as in `_drop_superseded_backups`) exempts
    a member from being deleted, but not from becoming the first incumbent -
    upstream checks the flag in two of the three branches and not the first.
    """
    names = new_valid.get("Extra")
    extra = challenges.get("Extra")
    if not names or not isinstance(extra, dict):
        return
    backlogged = backlog.get("Extra") or {}
    manual = manual_tasks.get("Extra") or {}
    incumbent: dict[str, Any] = {}
    for name in extra:
        if name not in names:
            continue
        challenge = extra[name]
        if not isinstance(challenge, dict):
            continue
        group = challenge.get("Set")
        if not isinstance(group, str):
            continue
        if name in backlogged or name.replace("#", "/") in backlogged:
            del names[name]
            continue
        priority = challenge.get("Priority")
        if group not in incumbent:
            incumbent[group] = priority
            continue
        exempt = bool(challenge.get("ManualValid")) or name in manual
        if _js_lower_priority(priority, incumbent[group]):
            if not exempt:
                incumbent[group] = priority
        elif not exempt:
            del names[name]
    # Same contract as `_drop_superseded_backups`: a skill key in `new_valid`
    # implies at least one valid challenge, so an emptied branch has to go.
    if not names:
        del new_valid["Extra"]


def _group_processing_skill_challenges(
    valid: Mapping[str, Mapping[str, int | str | bool]],
    challenges: Mapping[str, Mapping[str, Any]],
    items: Mapping[str, Mapping[str, str]],
    rules: Mapping[str, Any],
    chunk_info: ChunkInfo,
    source_index: SourceIndex,
) -> dict[str, dict[str, int | str | bool]]:
    """Port of the "Highest Level" grouping fork (worker.js:4413-4680), run
    once after `calc_challenges`'s fixed point converges.

    When `rules['Highest Level']` is off, a `_PROCESSING_SKILLS` challenge
    that consumes an available ingredient is valid only if it is the
    lowest-*boosted*-`Level` consumer (upstream's `tempLevel`,
    worker.js:4590) of at least one such ingredient - ties keep
    whichever consumer is seen first, in `chunk_info.challenges`' own key
    order (upstream's further `Priority`/`Primary`/`Secondary` tie-break
    isn't modelled - see the module docstring). When the rule is on, every
    consumer of an available ingredient is valid, which is exactly what the
    per-challenge checking already produced, so this is a no-op.
    """
    if rules.get("Highest Level") is True:
        return {skill: dict(names) for skill, names in valid.items()}

    result: dict[str, dict[str, int | str | bool]] = {
        skill: dict(names) for skill, names in valid.items() if skill not in _PROCESSING_SKILLS
    }
    for skill in _PROCESSING_SKILLS:
        skill_valid = valid.get(skill)
        if not skill_valid:
            continue
        skill_challenges = challenges.get(skill, {})
        groups: dict[str, list[str]] = {}
        winners: dict[str, int | str | bool] = {}
        for name in skill_valid:
            challenge = skill_challenges.get(name)
            item_refs = challenge.get("Items") if isinstance(challenge, dict) else None
            if not isinstance(item_refs, list) or not item_refs:
                winners[name] = skill_valid[name]
                continue
            for item_ref in item_refs:
                if not isinstance(item_ref, str):
                    continue
                ingredient = item_ref.replace("*", "").split("[+]x")[0]
                if ingredient in items:
                    groups.setdefault(ingredient, []).append(name)

        def _level(name: str, skill: str = skill) -> float:
            challenge = skill_challenges.get(name, {})
            level = challenge.get("Level")
            if not isinstance(level, (int, float)):
                return float("inf")
            return boosts.real_level(
                skill,
                name,
                challenge,
                float(level),
                rules=rules,
                chunk_info=chunk_info,
                items=items,
                source_index=source_index,
            )

        for names in groups.values():
            winner = min(names, key=_level)
            winners[winner] = skill_valid[winner]
        if winners:
            result[skill] = winners
    return result


def calc_challenges(
    chunk_ids: Mapping[str, bool],
    reachable_sections: Mapping[str, Mapping[str, bool]],
    source_index: SourceIndex,
    chunk_info: ChunkInfo,
    *,
    rules: Mapping[str, Any],
    max_skill: Mapping[str, int] | None = None,
    backlogged_sources: Mapping[str, Any] | None = None,
    passive_skill: Mapping[str, int] | None = None,
    backlog: Mapping[str, Mapping[str, Any]] | None = None,
    manual_tasks: Mapping[str, Mapping[str, Any]] | None = None,
    construction_locked: bool = False,
    locked_equipment: frozenset[str] = frozenset(),
    forced_valid: Mapping[str, Mapping[str, int | str | bool]] | None = None,
    max_iterations: int = 15,
    item_plans: MutableMapping[tuple[str, str], _ItemPlan | None] | None = None,
) -> ChallengeResult:
    """Port of `calcChallenges`/`calcChallengesWork`'s core fixed point - see
    the module docstring for exactly what is and is not implemented.

    `item_plans` is an optional table of compiled `Items` plans to fill and
    reuse. A plan depends only on the challenge, the export, the skill, the
    rules and `locked_equipment` - none of which move while `pipeline.derive`
    loops - so `derive` hands the same table to all eight of its passes rather
    than recompiling 6,300 plans on each. Omitted, this call keeps its own, and
    behaves exactly as it did before the table existed. It is a parameter and
    never a module global, so `--jobs` is untouched.
    """
    challenges = chunk_info.challenges
    max_skill = max_skill or {}
    passive_skill = passive_skill or {}
    backlog = backlog or {}
    manual_tasks = manual_tasks or {}
    secondary_primary_amount = str(rules.get("Secondary Primary Amount", "1"))

    plans = item_plans if item_plans is not None else {}

    items: Mapping[str, Mapping[str, str]] = source_index.items
    objects: Mapping[str, Mapping[str, Any]] = source_index.objects
    seedable_objects = _seedable_objects(challenges)
    valid: dict[str, dict[str, int | str | bool]] = {}
    # Upstream's `clueTasksPossible` starts empty and is refilled at the end
    # of every pass - see `_clue_reward_gate_met` for what an empty table
    # means and why it is not the same as a table full of zeroes.
    clue_possible: dict[str, float] = {}
    unsupported: set[str] = set()
    #: The first outer pass converges *without* pruning, so trainability is
    #: decided from a fully seeded index - deciding it earlier prunes a skill
    #: whose own `Output` chain would have made it trainable, which broke
    #: `Magic` and with it the BiS oracle's `Master wand`.
    pruning = False

    # Decide the invariant half of every challenge's requirements once, here,
    # rather than on each of the nine-to-twelve sweeps below: nothing they read
    # changes for the life of this call (see `_static_gates_met`). On the real
    # export this is 14,692 challenges in, 5,935 candidates out - so the loops
    # below stop re-deriving 8,757 rejections they cannot change.
    # Each entry carries everything about the challenge that cannot change
    # while this call runs: its compiled `Items` plan and the value it takes
    # when valid. Only the three dynamic gates are left to the sweeps.
    candidates: list[
        tuple[
            str,
            str,
            Mapping[str, Any],
            _ItemPlan | None,
            tuple[tuple[str, ...], ...],
            int | str | bool,
        ]
    ] = []
    for skill, skill_challenges in challenges.items():
        if skill in UNSUPPORTED_CATEGORIES or not isinstance(skill_challenges, dict):
            continue
        for name, challenge in skill_challenges.items():
            if not isinstance(challenge, dict):
                continue
            try:
                survives = _static_gates_met(
                    skill,
                    name,
                    challenge,
                    chunk_ids=chunk_ids,
                    reachable_sections=reachable_sections,
                    monsters=source_index.monsters,
                    npcs=source_index.npcs,
                    chunk_info=chunk_info,
                    rules=rules,
                    max_skill=max_skill,
                    secondary_primary_amount=secondary_primary_amount,
                    construction_locked=construction_locked,
                )
            except NotImplementedError:
                # A challenge using a mechanic this module doesn't implement -
                # always one of `_LEVEL_GATES_NOT_SUPPORTED`, the only raise on
                # this path - must not abort every other, evaluable challenge.
                # Recording it once here is the same answer the per-pass
                # `unsupported.add` reached, since the gate is a static property
                # of the challenge. See `ChallengeResult.unsupported`.
                unsupported.add(f"{skill}/{name}")
                continue
            if not survives:
                continue
            # `Objects` is the one gate whose index the fixed point moves, so
            # it is settled here where it can be and deferred where it cannot
            # - see `_objects_requirement`.
            decision = _objects_requirement(
                challenge, source_index.objects, chunk_info, seedable_objects
            )
            if decision is False:
                continue
            candidates.append(
                (
                    skill,
                    name,
                    challenge,
                    _cached_plan(
                        plans,
                        skill,
                        name,
                        challenge,
                        chunk_info,
                        rules=rules,
                        locked_equipment=locked_equipment,
                    ),
                    decision if isinstance(decision, tuple) else (),
                    _challenge_value(challenge, skill),
                )
            )

    # Outer pass: the post-convergence prunes below *remove* challenges, and a
    # removed challenge's `Output` must stop being an available item - otherwise
    # a locked skill still feeds the rest of the derivation. `Herblore` being
    # locked behind Druidic Ritual left `Blamish oil` on the shelf, which kept
    # `Make an oily fishing rod` valid, which kept a Wilderness diary task
    # active. Re-seed from the pruned `valid` and re-derive until nothing moves;
    # pruning only ever removes, so this terminates.
    for _ in range(max_iterations):
        settled = {skill: dict(names) for skill, names in valid.items()}
        for _ in range(max_iterations):
            # Trainability depends on the *previous* pass's validity, so compute
            # it once per pass rather than per challenge (`_check_primary_method`
            # walks every valid challenge in a skill).
            trainable = {
                skill: _check_primary_method(
                    skill,
                    valid,
                    source_index,
                    chunk_info,
                    passive_skill=passive_skill,
                    backlog=backlog,
                    manual_tasks=manual_tasks,
                    rules=rules,
                    items=items,
                    objects=objects,
                )
                for skill in _UNIVERSAL_PRIMARY
            }
            new_valid: dict[str, dict[str, int | str | bool]] = {}
            for skill, name, challenge, plan, deferred, value in candidates:
                if _dynamic_gates_met(
                    skill,
                    name,
                    challenge,
                    clue_possible=clue_possible,
                    plan=plan,
                    items=items,
                    objects=objects,
                    deferred_objects=deferred,
                    valid=new_valid,
                    chunk_info=chunk_info,
                    rules=rules,
                    max_skill=max_skill,
                    trainable=trainable,
                    prev_valid=valid,
                ):
                    new_valid.setdefault(skill, {})[name] = value
            _inject_manual_tasks(new_valid, challenges, manual_tasks)
            # The bulk-synthesised challenges (`derive/injected.py`) are
            # written into `valids` at the *end* of upstream's pass, after its
            # scan, and its `valids` is rebuilt from scratch each pass - so
            # they are valid every pass whatever the scan made of them. That
            # is not a detail: a bird-nest droptable row names its nest under
            # `Monsters` with an `-object` suffix that no monster index
            # carries, so judging them would silently drop all 30 of them.
            # Contrast `injected_challenges`, whose definitions land *before*
            # the scan and are judged - see that module.
            for category, entries in (forced_valid or {}).items():
                new_valid.setdefault(category, {}).update(entries)
            _drop_superseded_backups(new_valid, valid, challenges, backlog, manual_tasks)
            _drop_outclassed_extra_sets(new_valid, challenges, backlog, manual_tasks)
            if pruning:
                # Second outer pass onward the index is fully seeded, so the
                # prunes can join the fixed point - and must, or each pass
                # re-derives the very skills the last one pruned and re-seeds
                # their `Output`s with them.
                _prune_untrainable_skills(
                    new_valid,
                    chunk_info,
                    source_index,
                    rules=rules,
                    passive_skill=passive_skill,
                    backlog=backlog,
                    manual_tasks=manual_tasks,
                    items=items,
                    objects=objects,
                )
                _drop_unreachable_subskills(
                    new_valid,
                    chunk_info,
                    source_index,
                    rules=rules,
                    max_skill=max_skill,
                    passive_skill=passive_skill,
                    backlog=backlog,
                    manual_tasks=manual_tasks,
                    items=items,
                    objects=objects,
                )
            # Upstream measures the clue tiers at the end of each pass
            # (worker.js:3455) and the next pass's gate reads the answer, so
            # the table starts empty and no reward task is valid until a pass
            # has produced some `Nonskill` validity to measure.
            clue_possible = _clue_tasks_possible(new_valid, challenges)
            if new_valid == valid:
                break
            valid = new_valid
            items = _seed_items_with_outputs(
                source_index.items,
                valid,
                challenges,
                chunk_info,
                rules,
                backlogged_sources or {},
                backlog,
            )
            _seed_skilling_pets(items, valid, challenges, rules, trainable)
            objects = _seed_objects_with_outputs(
                source_index.objects, valid, challenges, backlog
            )

        # Run once, after convergence, not per pass: deciding trainability from a
        # half-seeded item index prunes a skill whose own `Output` chain would
        # have made it trainable, and because that prune then starves the next
        # pass of those items the loop settles on the wrong fixed point (it broke
        # `Magic`, and with it the BiS oracle's `Master wand`).
        _prune_untrainable_skills(
            valid,
            chunk_info,
            source_index,
            rules=rules,
            passive_skill=passive_skill,
            backlog=backlog,
            manual_tasks=manual_tasks,
            items=items,
            objects=objects,
        )
        _drop_unreachable_subskills(
            valid,
            chunk_info,
            source_index,
            rules=rules,
            max_skill=max_skill,
            passive_skill=passive_skill,
            backlog=backlog,
            manual_tasks=manual_tasks,
            items=items,
            objects=objects,
        )
        _drop_outclassed_extra_sets(valid, challenges, backlog, manual_tasks)
        reseeded = _seed_items_with_outputs(
            source_index.items,
            valid,
            challenges,
            chunk_info,
            rules,
            backlogged_sources or {},
            backlog,
        )
        _seed_skilling_pets(reseeded, valid, challenges, rules, trainable)
        reseeded_objects = _seed_objects_with_outputs(
            source_index.objects, valid, challenges, backlog
        )
        if reseeded == items and reseeded_objects == objects and valid == settled:
            break
        items = reseeded
        objects = reseeded_objects
        pruning = True

    grouped = _group_processing_skill_challenges(
        valid, challenges, items, rules, chunk_info, source_index
    )
    return ChallengeResult(
        valid=grouped,
        unsupported=frozenset(unsupported),
        available_items={item: dict(sources) for item, sources in items.items()},
        available_objects={name: dict(sources) for name, sources in objects.items()},
    )
