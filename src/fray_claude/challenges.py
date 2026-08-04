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
  filtering. The `*` secondary marker is stripped and otherwise ignored -
  verified against upstream (worker.js:4046,4064) it does **not** gate
  validity, only a `Secondary` flag feeding `checkPrimaryMethod` and a
  `forcedPrimary` gate with zero real-export uses, so it isn't threaded
  through here. (`checkPrimaryMethod` itself *is* ported, as
  `_check_primary_method`; it is that `Secondary` **input** to it which
  isn't.) See `_items_requirement_met`'s docstring. For
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
  mildly over-inclusive relative to the final grouped `valid`. The
  `Multi Step Processing` rule's chain-of-crafted-items requirement is not
  checked at all, which can over-include processing-skill tasks when that
  rule is on.
- Dynamic Max Cape / Quest Point Cape challenge injection, Slayer-lock,
  Collection Log Clues thresholds: not implemented. (Mahogany Homes *is*
  now handled - see `_MAHOGANY_HOMES_CONTRACT`.) Shortcut
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
  taken. Missing it made `fray tasks` propose an expert contract as the
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
rate and drags an entire crafting chain in with it. Simplified - everything
is tagged `primary-` rather than split by drop rate, and the `Rare Drop
Amount` filter on an activity's items isn't applied; the `bossLogs` gate is.

**How the fixed point is evaluated, and why it is shaped that way.** This
module is where every derivation command spends its time - measured on the
real export, `calc_challenges` was ~2.5s of `derive`'s 2.7s - so the loop's
structure is load-bearing, not incidental. A challenge's requirements split
cleanly in two:

- `_static_gates_met` - level/unsupported, `Category`, `Chunks`,
  `Objects`/`Monsters`/`NPCs`, `Mix`. Every input (`rules`, `max_skill`,
  `chunk_ids`, `reachable_sections`, the object/monster/npc indexes) is fixed
  for the whole `calc_challenges` call, so **nothing the fixed point does can
  change the answer**. Run once, up front, as a candidate filter: on the real
  export it takes 14,692 challenges down to 5,935 - the loops used to
  re-derive those 8,757 rejections on all nine-to-twelve sweeps.
- `_dynamic_gates_met` - `Items`, `Skills`, `Tasks`, which read the item index
  the loop keeps re-seeding and the validity being computed. These must stay
  inside.

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

What is *not* done, deliberately: warm-starting this fixed point from the
previous outer pass's `valid` instead of from `{}`. It would cut the nine-to-
thirteen sweeps per call to two or three - by far the largest remaining win -
and the usual argument (a monotone operator started below its least fixed point
converges to that same fixed point) would make it safe. The operator is not
monotone: `_drop_superseded_backups` *removes* a barehanded-catch challenge once
the method it backs up becomes valid, so more validity can mean less. Same trap
sits under skipping the static prefilter on later outer passes, since
`taskUnlocks` gating can withdraw a source. Both would have to be justified by
agreement on one map, which this project has learnt not to accept as proof.

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

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from fray_claude import boosts
from fray_claude.chunkinfo import ChunkInfo
from fray_claude.sources import SourceIndex, apply_item_task_unlocks
from fray_claude.summary import _mapping

_MAYBE_PRIMARY = frozenset({"Normal Farming", "Sulphurous Fertiliser", "Shortcut", "InsidePOH Primary"})

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

_TASK_MARKUP = re.compile(r"[~|]")


#: Appended to a task obtained during the chunk in play - one still sitting
#: in `checkedChallenges`, not yet migrated into `completedChallenges` by the
#: next roll. Shared by `bis.py` and `other_tasks.py` so the two panels mark
#: the same thing the same way.
CURRENT_CHUNK_SUFFIX = "(Active)"


def strip_task_markup(task_name: str) -> str:
    """Drop the `~|...|~` delimiters a task name wraps its subject in,
    preserving the text (and its casing) between them.

    The markers exist so the web app can style the item/monster a task
    names; nothing downstream of a terminal wants them. Removes the
    delimiter *characters* rather than the `~|`/`|~` pairs, because four
    real names are malformed - `Carve a ~log |canoe|~` has the opening
    `|` four characters late, and pair-stripping leaves the visible
    wreckage `Carve a ~log |canoe`. Character-stripping renders those as
    `Carve a log canoe` and is byte-identical to pair-stripping on all
    14,688 well-formed names in the export, where no `|` and no `~` ever
    appears outside this markup.

    **Only ever call this on a challenge/task name.** Names from other
    branches can use these characters for real (the shop `~ Uglug's
    stuffsies ~`), which is why `cli.py`'s `search` output applies it to
    task hits and `task:` routes rather than to every hit.

    Deliberately does *not* touch the `#` variant separator
    (`~|wooden hull#Raft|~`) or the trailing `*` secondary marker: both are
    real parts of the stored name, and rendering them is upstream behaviour
    this project hasn't located. Unlike `search.normalise`, this is for
    *display*, so it neither lowercases nor collapses anything.
    """
    return _TASK_MARKUP.sub("", task_name)


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
    """

    valid: dict[str, dict[str, int | str | bool]]
    unsupported: frozenset[str]
    available_items: dict[str, dict[str, str]] = field(default_factory=dict)

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


def _chunks_requirement_met(
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


def _compile_items(
    challenge: Mapping[str, Any],
    chunk_info: ChunkInfo,
    *,
    skill: str = "",
    rules: Mapping[str, Any] = {},
) -> _ItemPlan | None:
    """Resolve a challenge's `Items` refs, or `None` if it has no `Items`."""
    item_refs = challenge.get("Items")
    if not isinstance(item_refs, list):
        return None
    families: list[tuple[tuple[str, ...] | None, int]] = []
    for item_ref in item_refs:
        if not isinstance(item_ref, str):
            continue
        name = item_ref.replace("*", "")
        if "[+]" in name:
            base_name, marker, count_str = name.partition("[+]x")
            family = _plus_family(chunk_info, "itemsPlus", f"{base_name}[+]" if marker else name)
            families.append(
                (tuple(family) if family is not None else None, int(count_str) if marker else 1)
            )
        else:
            families.append(((name,), 1))
    applies, waived = _quality_flags(skill, challenge, rules)
    return _ItemPlan(
        families=tuple(families),
        allowed_sources=challenge.get("AllowedSources"),
        non_shop=challenge.get("NonShop") is True,
        quality_applies=applies,
        quality_waived=waived,
    )


def _item_plan_met(plan: _ItemPlan, items: Mapping[str, Mapping[str, str]]) -> bool:
    """Check a compiled plan against the current item index.

    Everything the check needs that isn't the index itself was decided when the
    plan was compiled - the refs, and the source-quality gate's two flags - so
    what runs here per sweep is dictionary lookups and nothing more. Counting
    stops at `needed` because the answer cannot change after that, which the
    uncompiled `sum()` had no way to do.
    """
    for family, needed in plan.families:
        if family is None:
            return False
        matches = 0
        for member in family:
            if _item_usable(
                items.get(member),
                non_shop=plan.non_shop,
                allowed_sources=plan.allowed_sources,
                applies=plan.quality_applies,
                waived=plan.quality_waived,
            ):
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
    marker is stripped and otherwise ignored here: verified against upstream
    (worker.js:4046,4064), it does **not** gate validity - it only sets a
    per-challenge `Secondary` flag that feeds `checkPrimaryMethod` and a
    `forcedPrimary` gate that has zero real-export uses, so it isn't threaded
    through here. (`checkPrimaryMethod` is ported, as `_check_primary_method`
    - it is the `Secondary` input to it that isn't.) `[+]`
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
    """
    challenges = chunk_info.challenges.get(skill) or {}
    backlogged = backlog.get(skill) or {}
    passive = passive_skill.get(skill)
    for name in valid.get(skill, {}):
        challenge = challenges.get(name)
        if not isinstance(challenge, dict):
            continue
        if challenge.get("Primary") is not True or name in backlogged:
            continue
        level = challenge.get("Level")
        if not isinstance(level, (int, float)) or level == 1:
            return True
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
            if level <= passive + best + saw:
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
    `Boosting` level shift and `skillQuestXp` floor inside `Primary[+]`, the
    secondary/processing-source filtering inside `Ranged[+]`, and the
    `Smithing by Smelting` anvil caveat on the `manualTasks` override.
    """
    rules = rules or {}
    # Upstream's `baseChunkData['items']` is the seeded index; falling back
    # to the narrow one only loses boosts, never invents them.
    items = source_index.items if items is None else items
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
    challenges = chunk_info.challenges.get(skill) or {}
    backlogged = backlog.get(skill) or {}
    for name in manual_tasks.get(skill, {}):
        challenge = challenges.get(name)
        if isinstance(challenge, dict) and challenge.get("Primary") is True and name not in backlogged:
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
    objects: Mapping[str, Mapping[str, Any]],
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
    per-map constants; `chunk_ids`/`reachable_sections` and the
    objects/monsters/npcs indexes are arguments to the call and never change
    inside its loops (only `items` does, via `_seed_items_with_outputs`, which
    is why `Items` is in `_dynamic_gates_met` instead).

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
    if not _chunks_requirement_met(challenge, chunk_ids, reachable_sections, chunk_info):
        return False
    if not _presence_requirement_met(challenge, "Objects", objects, chunk_info, "objectsPlus"):
        return False
    if not _presence_requirement_met(challenge, "Monsters", monsters, chunk_info, "monstersPlus"):
        return False
    if not _presence_requirement_met(challenge, "NPCs", npcs, chunk_info, "npcsPlus"):
        return False
    return _mix_requirement_met(challenge, monsters, npcs, chunk_info)


def _dynamic_gates_met(
    skill: str,
    challenge: Mapping[str, Any],
    *,
    plan: _ItemPlan | None,
    items: Mapping[str, Mapping[str, str]],
    valid: Mapping[str, Mapping[str, Any]],
    chunk_info: ChunkInfo,
    rules: Mapping[str, Any],
    max_skill: Mapping[str, int],
    trainable: Mapping[str, bool],
    prev_valid: Mapping[str, Mapping[str, Any]],
) -> bool:
    """The half that has to stay in the loop: `Items` reads the item index the
    fixed point keeps re-seeding, and `Skills`/`Tasks` read the validity being
    computed.

    `plan` is the challenge's `Items` refs already resolved (`_compile_items`),
    since only the *index* they are checked against changes between sweeps.
    """
    if plan is not None and not _item_plan_met(plan, items):
        return False
    if not _skills_requirement_met(challenge, max_skill, valid, trainable=trainable):
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
        objects=objects,
        monsters=monsters,
        npcs=npcs,
        chunk_info=chunk_info,
        rules=rules,
        max_skill=max_skill,
        secondary_primary_amount=secondary_primary_amount,
        construction_locked=construction_locked,
    ):
        return None
    if not _dynamic_gates_met(
        skill,
        challenge,
        plan=_compile_items(challenge, chunk_info, skill=skill, rules=rules),
        items=items,
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
) -> dict[str, dict[str, str]]:
    """A valid challenge's `Output` becomes a new item source for the next
    pass - and, when that `Output` names an activity in
    `skillItems[<that skill>]`, so does every item that activity yields.

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
    apply_item_task_unlocks(items, _mapping(chunk_info.data, "taskUnlocks"), valid)
    return items


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

    Upstream's `slayerLocked` arm is inert - no real map payload carries that
    branch - and is not reproduced.
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
    max_iterations: int = 15,
) -> ChallengeResult:
    """Port of `calcChallenges`/`calcChallengesWork`'s core fixed point - see
    the module docstring for exactly what is and is not implemented.
    """
    challenges = chunk_info.challenges
    max_skill = max_skill or {}
    passive_skill = passive_skill or {}
    backlog = backlog or {}
    manual_tasks = manual_tasks or {}
    secondary_primary_amount = str(rules.get("Secondary Primary Amount", "1"))

    items: Mapping[str, Mapping[str, str]] = source_index.items
    valid: dict[str, dict[str, int | str | bool]] = {}
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
    candidates: list[tuple[str, str, Mapping[str, Any], _ItemPlan | None, int | str | bool]] = []
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
                    objects=source_index.objects,
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
            if survives:
                candidates.append(
                    (
                        skill,
                        name,
                        challenge,
                        _compile_items(challenge, chunk_info, skill=skill, rules=rules),
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
                )
                for skill in _UNIVERSAL_PRIMARY
            }
            new_valid: dict[str, dict[str, int | str | bool]] = {}
            for skill, name, challenge, plan, value in candidates:
                if _dynamic_gates_met(
                    skill,
                    challenge,
                    plan=plan,
                    items=items,
                    valid=new_valid,
                    chunk_info=chunk_info,
                    rules=rules,
                    max_skill=max_skill,
                    trainable=trainable,
                    prev_valid=valid,
                ):
                    new_valid.setdefault(skill, {})[name] = value
            _inject_manual_tasks(new_valid, challenges, manual_tasks)
            _drop_superseded_backups(new_valid, valid, challenges, backlog, manual_tasks)
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
                )
            if new_valid == valid:
                break
            valid = new_valid
            items = _seed_items_with_outputs(
                source_index.items, valid, challenges, chunk_info, rules, backlogged_sources or {}
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
        )
        reseeded = _seed_items_with_outputs(
            source_index.items, valid, challenges, chunk_info, rules, backlogged_sources or {}
        )
        if reseeded == items and valid == settled:
            break
        items = reseeded
        pruning = True

    grouped = _group_processing_skill_challenges(
        valid, challenges, items, rules, chunk_info, source_index
    )
    return ChallengeResult(
        valid=grouped,
        unsupported=frozenset(unsupported),
        available_items={item: dict(sources) for item, sources in items.items()},
    )
